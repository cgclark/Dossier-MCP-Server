#!/usr/bin/env python3
"""server.py — Dossier Milestone 8: MCP server for Claude Desktop.

Exposes the lean Dossier tool surface. Each tool shells out to the deterministic
modules/binaries and returns only compact text — the MCP boundary keeps bulk
(images, full text) out of the conversation context.

Hardening (21 Aug): every read tool is async and offloads its blocking subprocess to a
thread bounded by a timeout (asyncio.wait_for), and sh() itself kills a child that runs
past its timeout. So no single slow/wedged call can hang the event loop or block the
requests behind it (the failure mode that previously required a Desktop restart). `get`
also caps its line span so a huge range can't dump a whole document.

Run via the venv python (which has `mcp`); register in claude_desktop_config.json.
"""
import asyncio, json, os, subprocess, sys
from pathlib import Path
from mcp.server.fastmcp import FastMCP

HERE = Path(__file__).parent
PY = sys.executable
HELP = HERE.parent / "helpers"
ASSEMBLE = [PY, str(HELP / "assemble_win.py")] if sys.platform.startswith("win") \
    else [str(HELP / "assemble")]
mcp = FastMCP("dossier")


def sh(cmd, limit=20000, timeout=45):
    """Run a child process with a HARD timeout — a wedged child is killed, never awaited forever."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return (f"(aborted: this call exceeded {timeout}s and its process was killed — the server "
                f"stays responsive. Narrow the range/query, or run the same command via the `dossier` CLI.)")
    except Exception as e:
        return f"(error launching call: {e})"
    out = (r.stdout or "") + (("\n[stderr] " + r.stderr) if r.returncode else "")
    return out[:limit] if out else "(no output)"


async def _run(cmd, limit=20000, timeout=45):
    """Offload sh() to a worker thread and bound it — belt-and-suspenders so the MCP event
    loop is never blocked even if the subprocess timeout is somehow bypassed."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(sh, cmd, limit, timeout), timeout=timeout + 5)
    except asyncio.TimeoutError:
        return (f"(aborted: call exceeded {timeout}s — server stays responsive. "
                f"Use a narrower call, or the `dossier` CLI.)")


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


@mcp.tool()
def ingest(matter_dir: str, work: str) -> str:
    """OCR + extract a matter's sources/ into a manifest at <work>.

    Non-blocking: OCR of a large pile takes minutes, so this starts (or resumes) the
    work in a detached background process and returns immediately — it will NOT hit the
    MCP request timeout. Poll `ingest_status(work)` until it reports `done`, then run
    cluster/chronology/organize/savings. Idempotent: re-calling resumes a stalled job
    or returns the finished summary instantly."""
    prog = Path(work) / ".ingest" / "progress.json"
    if prog.exists():
        try:
            d = json.loads(prog.read_text())
        except Exception:
            d = {}
        if d.get("state") == "running" and _alive(d.get("pid")):
            return ("ingest already running in the background — "
                    + sh([PY, str(HERE / "ingest.py"), "--work", work, "--status"], timeout=20))
        if d.get("state") == "done":
            summ = Path(work) / ".ingest" / "summary.txt"
            return ("ingest already complete for this work dir.\n"
                    + (summ.read_text() if summ.exists() else
                       sh([PY, str(HERE / "ingest.py"), "--work", work, "--summary-only"], timeout=20)))
    sd = Path(work) / ".ingest"; sd.mkdir(parents=True, exist_ok=True)
    logf = open(sd / "log", "ab")
    p = subprocess.Popen([PY, str(HERE / "ingest.py"), matter_dir, "--work", work],
                         stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    return (f"ingest started in the background (pid {p.pid}) for:\n  {matter_dir}\n"
            f"OCR + extraction runs on-device and can take several minutes for a large pile.\n"
            f"Poll with ingest_status(work=\"{work}\") until it reports `done`, then continue "
            f"with cluster / chronology / organize / savings.")


@mcp.tool()
async def ingest_status(work: str) -> str:
    """Progress of a running ingest (files done / total), or the final summary once `done`.
    Poll this after `ingest`. If it reports `stalled`, re-call `ingest` to resume."""
    return await _run([PY, str(HERE / "ingest.py"), "--work", work, "--status"], timeout=20)


@mcp.tool()
async def find(work: str, query: str) -> str:
    """Full-text search the corpus → matching docs + tiny snippets (+ on-device gists). Never dumps docs."""
    return await _run([PY, str(HERE / "query.py"), work, "find", query], timeout=25)


@mcp.tool()
async def get(work: str, artifact_id: int, start: int = 0, end: int = 40, pages: str = "") -> str:
    """Return a slice of ONE artifact's text, on demand. Two addressing modes:

      • PAGE mode (recommended when you think in pages): pass pages="6-9" (or "6") to fetch whole
        pages by PAGE number — it maps pages→lines for you.
      • LINE mode (default): start..end are 0-based LINE numbers. The default 0..40 is just the
        first ~40 lines (i.e. page 1) — you MUST pass a real range (or use `pages=`) to read further;
        omitting them does not error, it simply returns the opening lines."""
    if pages:
        lo, _, hi = pages.partition("-")
        hi = hi or lo
        return await _run([PY, str(HERE / "query.py"), work, "get",
                           str(artifact_id), lo.strip(), hi.strip(), "--pages"], timeout=25)
    MAX_SPAN = 600
    if end - start > MAX_SPAN:            # cap the artifact slice so a huge range can't dump a whole doc
        end = start + MAX_SPAN
    return await _run([PY, str(HERE / "query.py"), work, "get", str(artifact_id), str(start), str(end)], timeout=25)


@mcp.tool()
async def verify(work: str, value: str, artifact_id: int) -> str:
    """Confirm a string is present in an artifact + its offsets (document-backed check)."""
    return await _run([PY, str(HERE / "query.py"), work, "verify", value, str(artifact_id)], timeout=25)


@mcp.tool()
async def chronology(work: str) -> str:
    """Build the merged UTC-sorted ledger with cross-doc coincidence flags; returns a summary."""
    return await _run([PY, str(HERE / "chronology.py"), work], timeout=90)


@mcp.tool()
async def organize(work: str, apply: bool = False) -> str:
    """Dedup + misfile flags + provenance naming plan (symlink tree if apply=true). Non-destructive."""
    cmd = [PY, str(HERE / "organize.py"), work] + (["--apply"] if apply else [])
    return await _run(cmd, timeout=90)


@mcp.tool()
async def summarize(work: str, target: str = "missing") -> str:
    """On-device summary + key_points per artifact (Apple Foundation Models). target: <id>|missing|all.
    REDUCTION ONLY — not authoritative; verify facts against sources. Slow (~5-6s/doc)."""
    return await _run([PY, str(HERE / "summarize.py"), work, target], timeout=600)


@mcp.tool()
async def exhibit_list(work: str, order: str = "chrono") -> str:
    """Deterministic exhibit schedule (order: chrono|type). ~0 Claude tokens."""
    return await _run([PY, str(HERE / "deliverables.py"), work, "exhibit_list", "--order", order], timeout=30)


@mcp.tool()
async def digest(work: str) -> str:
    """Per-exhibit fact skeleton (+ on-device gist) with one-line {{relevance}} placeholders for Claude."""
    return await _run([PY, str(HERE / "deliverables.py"), work, "digest"], timeout=30)


@mcp.tool()
async def assemble(spec_json: str, out_pdf: str) -> str:
    """Assemble an exhibit-bundle PDF from the ORIGINALS per a JSON spec (cover schedule + pages)."""
    return await _run(ASSEMBLE + [spec_json, out_pdf], timeout=120)


@mcp.tool()
async def cluster(work: str, threshold: float = 0.8, apply: bool = False) -> str:
    """Group near-duplicate counterpart-signed copies into one agreement (shingle-Jaccard); every copy preserved."""
    cmd = [PY, str(HERE / "cluster.py"), work, "--threshold", str(threshold)] + (["--apply"] if apply else [])
    return await _run(cmd, timeout=120)


@mcp.tool()
async def savings(work: str) -> str:
    """Dual-baseline token-savings report (raw-image & full-text vs Dossier actual)."""
    return await _run([PY, str(HERE / "savings.py"), work], timeout=30)


if __name__ == "__main__":
    mcp.run()
