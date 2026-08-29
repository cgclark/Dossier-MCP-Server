#!/usr/bin/env python3
"""deliverables.py — Dossier Milestone 6 (exhibit list + digest).

  exhibit_list   deterministic exhibit schedule (chronological default) — ~0 Claude tokens
  digest         per-exhibit fact skeleton + one-line {{relevance}} placeholders for Claude

    deliverables.py <workdir> exhibit_list [--order chrono|type]
    deliverables.py <workdir> digest
"""
import argparse, sqlite3, re, sys
from pathlib import Path

if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

DATE_SRCS = ["formfield-R1@%", "formfield@%", "content@%", "pdf./Info", "fs.birthtime"]


def best_date(db, aid):
    for src in DATE_SRCS:
        r = db.execute("SELECT COALESCE(value_utc,value_wall) d FROM event WHERE artifact_id=? "
                       "AND source LIKE ? AND COALESCE(value_utc,value_wall) IS NOT NULL "
                       "ORDER BY id LIMIT 1", (aid, src)).fetchone()
        if r and r[0]:
            return r[0][:10]
    return "0000-00-00"


def key_dates(db, aid):
    rows = db.execute(
        "SELECT kind, COALESCE(value_wall,value_utc,value_raw) v, resolution FROM event "
        "WHERE artifact_id=? AND kind IN ('effective','expires','signed','executed','sent') "
        "ORDER BY id", (aid,)).fetchall()
    seen, out = set(), []
    for k, v, res in rows:
        if v and (k, v) not in seen:
            seen.add((k, v))
            out.append((k, v[:10] if re.match(r"\d{4}-", v) else v, res))
    return out[:4]


def letter(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def has_col(db, table, col):
    return col in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}


def load(db, order):
    sumcol = "summary" if has_col(db, "artifact", "summary") else "NULL"
    arts = db.execute(f"SELECT id,original_path,kind,pages,sha256,title,{sumcol} FROM artifact "
                      "WHERE duplicate_of IS NULL").fetchall()
    items = [{"id": a[0], "doc": Path(a[1]).name, "kind": a[2], "pages": a[3],
              "sha": a[4], "title": a[5], "summary": a[6], "date": best_date(db, a[0])} for a in arts]
    items.sort(key=lambda x: (x["kind"], x["date"]) if order == "type" else (x["date"], x["kind"]))
    for i, it in enumerate(items):
        it["ex"] = letter(i)
    return items


def exhibit_list(db, order):
    items = load(db, order)
    print(f"# Exhibit Schedule ({order}-ordered) — {len(items)} exhibits\n")
    print("| Ex | Date | Type | Description | Pages | SHA-256 |")
    print("|----|------|------|-------------|-------|---------|")
    for it in items:
        desc = (it["title"] or it["doc"])[:46]
        print(f"| {it['ex']} | {it['date']} | {it['kind']} | {desc} | {it['pages'] or ''} | {it['sha'][:10]}… |")


def digest(db):
    items = load(db, "chrono")
    print(f"# Digest — {len(items)} exhibits  (lines marked [doc-backed] vs {{{{relevance}}}} = Claude)\n")
    for it in items:
        print(f"## Exhibit {it['ex']} — {(it['title'] or it['doc'])[:54]}")
        print(f"  Type:   {it['kind']}                         [doc-backed]")
        kds = key_dates(db, it["id"])
        if kds:
            for k, v, res in kds:
                tag = "[doc-backed]" + (" (R1)" if res == "reinspect" else "")
                print(f"  {k.title():<10} {v:<14} {tag}")
        else:
            print(f"  Date:   {it['date']}                       [doc-backed]")
        if it.get("summary"):
            gist = it["summary"] if len(it["summary"]) <= 200 else it["summary"][:197].rstrip() + "…"
            print(f"  Gist:   {gist}  [on-device AI — verify, not authoritative]")
        print(f"  Relevance: {{{{synopsis — Claude, ≤15 words, cite page}}}}")
        print(f"  Source: {it['doc']} · SHA-256 {it['sha'][:10]}…\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir"); ap.add_argument("cmd")
    ap.add_argument("--order", default="chrono")
    a = ap.parse_args()
    db = sqlite3.connect(Path(a.workdir) / "manifest.db")
    if a.cmd == "exhibit_list":
        exhibit_list(db, a.order)
    elif a.cmd == "digest":
        digest(db)


if __name__ == "__main__":
    main()
