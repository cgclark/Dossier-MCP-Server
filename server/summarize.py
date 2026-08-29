#!/usr/bin/env python3
"""summarize.py — Dossier band-3-lite: on-device summaries via Apple Foundation Models.

Runs helpers/summarize (Apple Intelligence, ~3B on-device) over an artifact's OCR text and
stores a `summary` + `key_points` on the artifact row — a one-line gist for find/digest that
keeps full text off Claude. REDUCTION ONLY: never authoritative; deterministic band-1/2
(dates, SHAs, form fields) remain the source of truth.

    summarize.py <workdir> [<artifact_id>|missing|all] [--points N] [--max-chars N]

`missing` (default) summarises artifacts that have OCR text but no summary yet.
"""
import argparse, json, sqlite3, subprocess, sys
from pathlib import Path

if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent.parent
SUMMARIZE = ([sys.executable, str(BASE / "helpers" / "summarize_win.py")]
             if sys.platform.startswith("win") else [str(BASE / "helpers" / "summarize")])


def ensure_columns(db):
    """Add summary/key_points columns if this manifest predates them (idempotent migration)."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(artifact)")}
    if "summary" not in cols:
        db.execute("ALTER TABLE artifact ADD COLUMN summary TEXT")
    if "key_points" not in cols:
        db.execute("ALTER TABLE artifact ADD COLUMN key_points TEXT")


def run_summary(ocr_path, points=5, max_chars=50000):
    """Summarise one OCR text file → dict (or a skip/None). Guards against huge tabular dumps."""
    if not ocr_path or not Path(ocr_path).exists():
        return None
    try:
        n = Path(ocr_path).stat().st_size
    except OSError:
        return None
    if n > max_chars:
        return {"available": True, "skipped": "too-large", "chars": n}
    r = subprocess.run(SUMMARIZE + [str(ocr_path), "--points", str(points)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def store(db, aid, res):
    """Persist a summary result; returns 'ok' | 'skipped' | 'unavailable'."""
    if not res:
        return "unavailable"
    if res.get("skipped") or res.get("refused") or not res.get("available") or not res.get("summary"):
        return "skipped" if (res.get("skipped") or res.get("refused")) else "unavailable"
    db.execute("UPDATE artifact SET summary=?, key_points=? WHERE id=?",
               (res["summary"], json.dumps(res.get("key_points") or [], ensure_ascii=False), aid))
    return "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("target", nargs="?", default="missing", help="artifact id | 'missing' | 'all'")
    ap.add_argument("--points", type=int, default=5)
    ap.add_argument("--max-chars", type=int, default=50000)
    a = ap.parse_args()
    db = sqlite3.connect(Path(a.workdir) / "manifest.db")
    ensure_columns(db); db.commit()

    if a.target == "all":
        rows = db.execute("SELECT id,ocr_path FROM artifact WHERE ocr_path IS NOT NULL "
                          "AND duplicate_of IS NULL ORDER BY id").fetchall()
    elif a.target == "missing":
        rows = db.execute("SELECT id,ocr_path FROM artifact WHERE ocr_path IS NOT NULL "
                          "AND duplicate_of IS NULL AND (summary IS NULL OR summary='') "
                          "ORDER BY id").fetchall()
    else:
        rows = db.execute("SELECT id,ocr_path FROM artifact WHERE id=?", (int(a.target),)).fetchall()

    counts = {"ok": 0, "skipped": 0, "unavailable": 0}
    for aid, ocr in rows:
        res = run_summary(ocr, a.points, a.max_chars)
        outcome = store(db, aid, res); db.commit()
        counts[outcome] += 1
        note = "" if outcome == "ok" else f"  ({(res or {}).get('skipped') or (res or {}).get('reason') or 'no text'})"
        print(f"  #{aid:<4} {outcome}{note}")
        if outcome == "unavailable" and res and res.get("reason"):
            # Apple Intelligence off / model not ready → stop early, nothing will succeed.
            if "available" in res and res.get("available") is False:
                print(f"stopping: Foundation Models unavailable ({res['reason']})"); break

    print(f"\nsummarised {counts['ok']}, skipped {counts['skipped']}, unavailable {counts['unavailable']}")


if __name__ == "__main__":
    main()
