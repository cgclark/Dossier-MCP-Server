#!/usr/bin/env python3
"""query.py — Dossier Milestone 5: token-cheap retrieval over the manifest.

  find <q>            FTS over OCR text → paths + tiny snippets (never dumps docs)
  get <aid> [a b]     return lines a..b of one artifact's text (targeted slice)
  verify <val> <aid>  confirm a string is present in an artifact + its locations

Finding is free (manifest lookup); opening costs tokens, on demand only.
    query.py <workdir> <cmd> ...
"""
import argparse, sqlite3, json, re
from pathlib import Path


def has_col(db, table, col):
    return col in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir"); ap.add_argument("cmd"); ap.add_argument("args", nargs="*")
    ap.add_argument("--pages", action="store_true",
                    help="for `get`: interpret the two numbers as PAGE numbers, not line numbers")
    a = ap.parse_args()
    db = sqlite3.connect(Path(a.workdir) / "manifest.db")

    if a.cmd == "find":
        # Quote as an FTS5 phrase so punctuation (commas, $, #) can't break MATCH syntax.
        q = '"' + " ".join(a.args).replace('"', ' ') + '"'
        sumcol = "a.summary" if has_col(db, "artifact", "summary") else "NULL"
        rows = db.execute(
            f"SELECT a.id, a.original_path, snippet(doc_fts,0,'[',']','…',12), {sumcol} "
            "FROM doc_fts JOIN artifact a ON a.id=doc_fts.artifact_id "
            "WHERE doc_fts MATCH ? AND a.duplicate_of IS NULL LIMIT 20", (q,)).fetchall()
        out = []
        for r in rows:
            d = {"id": r[0], "doc": Path(r[1]).name, "snippet": r[2]}
            if r[3]:  # on-device gist (reduction, not authoritative) — helps triage which hit to open
                d["gist"] = r[3] if len(r[3]) <= 160 else r[3][:157].rstrip() + "…"
            out.append(d)
        print(json.dumps(out, indent=2, ensure_ascii=False))

    elif a.cmd == "get":
        aid = int(a.args[0])
        r = db.execute("SELECT ocr_path FROM artifact WHERE id=?", (aid,)).fetchone()
        if not r or not r[0]:
            print("(no text)"); return
        lines = Path(r[0]).read_text(errors="ignore").splitlines()
        if a.pages:
            # map PAGE numbers → line indices via the '===== PAGE N =====' separators
            p_lo = int(a.args[1]) if len(a.args) > 1 else 1
            p_hi = int(a.args[2]) if len(a.args) > 2 else p_lo
            marks = {}
            for i, ln in enumerate(lines):
                m = re.match(r"=====\s*PAGE\s+(\d+)\s*=====", ln.strip())
                if m:
                    marks[int(m.group(1))] = i
            if not marks:
                print("(no page markers in this artifact — use line numbers instead)"); return
            lo = marks.get(p_lo, 0)
            hi = min([marks[k] for k in marks if k > p_hi] or [len(lines)])
        else:
            lo = int(a.args[1]) if len(a.args) > 1 else 0
            hi = int(a.args[2]) if len(a.args) > 2 else lo + 40
        print("\n".join(lines[lo:hi]))

    elif a.cmd == "verify":
        val = a.args[0]; aid = int(a.args[1])
        r = db.execute("SELECT ocr_path FROM artifact WHERE id=?", (aid,)).fetchone()
        body = Path(r[0]).read_text(errors="ignore") if r and r[0] else ""
        locs = [m.start() for m in re.finditer(re.escape(val), body)]
        print(json.dumps({"value": val, "artifact": aid, "present": bool(locs),
                          "count": len(locs), "offsets": locs[:10]}, indent=2))


if __name__ == "__main__":
    main()
