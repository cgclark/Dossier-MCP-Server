#!/usr/bin/env python3
"""savings.py — Dossier Milestone 7 (dual-baseline token savings).

Shows BOTH baselines (raw-image, full-text) vs the Dossier actual (ledger projection),
plus the on-device cost as a SEPARATE currency (VLM tokens ≠ Claude tokens).

    savings.py <workdir>
"""
import argparse, sqlite3, sys
from pathlib import Path

if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

IMG_TOK_PER_PAGE = 1600   # Apple resizes large images to ~this
CHARS_PER_TOK = 4
LEDGER_TOK_PER_EVENT = 25


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("workdir")
    a = ap.parse_args()
    db = sqlite3.connect(Path(a.workdir) / "manifest.db")

    pages = db.execute("SELECT COALESCE(SUM(pages),0) FROM artifact WHERE duplicate_of IS NULL").fetchone()[0]
    chars = db.execute("SELECT COALESCE(SUM(LENGTH(body)),0) FROM doc_fts").fetchone()[0]
    events = db.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    arts = db.execute("SELECT COUNT(*) FROM artifact WHERE duplicate_of IS NULL").fetchone()[0]
    # on-device VLM cost (separate currency)
    vlm = db.execute("SELECT COALESCE(SUM(prompt_tok+gen_tok),0) FROM metric WHERE model IS NOT NULL").fetchone()[0]

    raw = pages * IMG_TOK_PER_PAGE
    txt = chars // CHARS_PER_TOK
    actual = events * LEDGER_TOK_PER_EVENT + 2000

    def pct(b):
        return f"{100*(b-actual)//b}%" if b else "n/a"

    print(f"Dossier savings — {arts} artifacts, {pages} pages, {chars:,} chars, {events} events\n")
    print("── Claude context tokens ─────────────────────────")
    print(f"  actual (ledger projection) ~{actual:,}")
    print(f"  baseline · raw-image       ~{raw:,}   → saved {pct(raw)}")
    print(f"  baseline · full-text       ~{txt:,}   → saved {pct(txt)}")
    print("── On-device cost (separate currency) ────────────")
    print(f"  local VLM tokens            {vlm:,}   (VLM tokenizer ≠ Claude tokens; never summed)")
    print("\ncaveats: baselines are estimates (image ≈1,600 tok/pp after resize); actual measured;")
    print("         raw-image baseline alone exceeds a context window → naive approach cannot fit.")


if __name__ == "__main__":
    main()
