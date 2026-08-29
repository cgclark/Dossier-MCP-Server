#!/usr/bin/env python3
"""summarize_win.py — Windows port of helpers/summarize (Swift/Apple Foundation Models).

    summarize_win.py <textfile> [--points N]     (or: summarize_win.py -   to read stdin)

Apple Intelligence has no Windows on-device equivalent, so this step calls
Claude Haiku over the network via the Anthropic API instead — the one place the
Windows pipeline leaves the device (everything else: ingest/OCR/dates/search/
assemble stays fully local). Requires ANTHROPIC_API_KEY in the environment.

Preserves the macOS binary's exact degrade contract so server/summarize.py's
caller doesn't need to know which platform produced the JSON:
  {"available": false, "reason": "..."}                      — can't run at all
  {"available": true, "empty": true, "summary": "", "key_points": []}
  {"available": true, "refused": true, "reason": "...", "chunks": N}
  {"available": true, "error": "..."}
  {"available": true, "model": "...", "chars": N, "chunks": N, "truncated": bool,
   "summary": "...", "key_points": [...]}
"""
import json, os, re, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

MODEL = "claude-haiku-4-5-20251001"
CHUNK_CHARS = 6000
MAX_CHUNKS = 12
MAX_CHARS = CHUNK_CHARS * MAX_CHUNKS


def die(msg, code=2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def chunk_text(text):
    """Same scheme as the macOS binary: ~6000-char pieces on paragraph boundaries,
    capped at 12 chunks (~72k chars)."""
    paras = re.split(r"\n\s*\n", text)
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 2 > CHUNK_CHARS and cur:
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + "\n\n" + p) if cur else p
        if len(chunks) >= MAX_CHUNKS:
            break
    if cur and len(chunks) < MAX_CHUNKS:
        chunks.append(cur)
    truncated = len(text) > MAX_CHARS
    return chunks[:MAX_CHUNKS], truncated


def call_haiku(client, prompt, max_tokens=1024):
    resp = client.messages.create(
        model=MODEL, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


def summarize_chunk(client, chunk):
    prompt = ("Summarize the following document excerpt in 2-3 neutral, factual sentences. "
               "Do not add commentary or opinions.\n\n" + chunk)
    return call_haiku(client, prompt, max_tokens=300)


def digest(client, chunk_summaries, points):
    joined = "\n".join(f"- {s}" for s in chunk_summaries)
    prompt = (
        f"Below are section summaries of one document, in order. Produce a single JSON object "
        f"(and nothing else — no markdown fences, no commentary) with exactly two keys: "
        f'"summary" (a 2-4 sentence neutral overview of the whole document) and "key_points" '
        f"(a list of up to {points} short factual bullet points). Section summaries:\n{joined}"
    )
    raw = call_haiku(client, prompt, max_tokens=600)
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return d.get("summary", ""), list(d.get("key_points") or [])
    except json.JSONDecodeError:
        return None


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--points", type=int, default=5)
    a = ap.parse_args()

    if a.input != "-":
        p = Path(a.input)
        if not p.exists():
            die(f"no such file: {p}")
        text = p.read_text(encoding="utf-8", errors="ignore")
    else:
        text = sys.stdin.read()

    if not text.strip():
        print(json.dumps({"available": True, "empty": True, "summary": "", "key_points": []}))
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(json.dumps({"available": False,
                           "reason": "ANTHROPIC_API_KEY not set in the environment"}))
        return

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        print(json.dumps({"available": False, "reason": f"anthropic client init failed: {e}"}))
        return

    chunks, truncated = chunk_text(text)
    try:
        chunk_summaries = [summarize_chunk(client, c) for c in chunks]
    except Exception as e:
        msg = str(e)
        if "refus" in msg.lower() or "content_filter" in msg.lower():
            print(json.dumps({"available": True, "refused": True, "reason": msg,
                               "chunks": len(chunks)}))
        else:
            print(json.dumps({"available": True, "error": msg}))
        return

    try:
        result = digest(client, chunk_summaries, a.points)
    except Exception as e:
        print(json.dumps({"available": True, "error": str(e)}))
        return

    if result is None:
        print(json.dumps({"available": True, "error": "could not parse a JSON digest from the model"}))
        return
    summary, key_points = result

    print(json.dumps({
        "available": True,
        "model": "claude-haiku (Anthropic API)",
        "chars": len(text),
        "chunks": len(chunks),
        "truncated": truncated,
        "summary": summary,
        "key_points": key_points,
    }))


if __name__ == "__main__":
    main()
