#!/usr/bin/env python3
"""organize.py — Dossier Milestone 4.

Non-destructive organization off the manifest: dedup report, misfile flags, a
provenance-driven naming plan, and a symlink tree. Originals never move.

    organize.py <workdir> [--apply]      (default: plan only)
"""
import argparse, json, re, sqlite3, sys
from pathlib import Path

if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

STOP = {"the", "of", "and", "for", "re", "fwd", "copy", "final", "signed", "scan", "1", "2"}


def slug(s, n=4):
    words = [w for w in re.findall(r"[A-Za-z]+", s.lower()) if w not in STOP][:n]
    return "-".join(words) or "doc"


def best_date(db, aid):
    # operative content date → artifact created → fs.birthtime  (fallback chain)
    for src in ("formfield@%", "content@%", "pdf./Info", "fs.birthtime"):
        r = db.execute("SELECT COALESCE(value_utc,value_wall) d FROM event WHERE artifact_id=? "
                       "AND source LIKE ? AND COALESCE(value_utc,value_wall) IS NOT NULL "
                       "ORDER BY id LIMIT 1", (aid, src)).fetchone()
        if r and r[0]:
            return r[0][:10]
    return "0000-00-00"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir"); ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    work = Path(a.workdir)
    db = sqlite3.connect(work / "manifest.db")

    dupes = db.execute("SELECT COUNT(*) FROM artifact WHERE duplicate_of IS NOT NULL").fetchone()[0]
    arts = db.execute("SELECT id,original_path,kind,sha256,title FROM artifact "
                      "WHERE duplicate_of IS NULL").fetchall()

    plan, misfiled = [], []
    tree = work / "organized"
    for aid, opath, kind, sha, title in arts:
        op = Path(opath)
        date = best_date(db, aid)
        name = f"{date}__{kind}__{slug(title or op.stem)}__{sha[:8]}{op.suffix.lower()}"
        plan.append((aid, opath, name))
        # misfile heuristic: a distinctive title token absent from the filename
        if title:
            toks = [w for w in re.findall(r"[A-Za-z]{4,}", title.lower()) if w not in STOP]
            if toks and not any(t in op.name.lower() for t in toks):
                misfiled.append((op.name, title))

    if a.apply:
        tree.mkdir(exist_ok=True)
        for aid, opath, name in plan:
            link = tree / name
            if not link.exists():
                try:
                    link.symlink_to(Path(opath).resolve())
                except OSError:
                    pass

    print(f"organize: {len(arts)} unique artifacts, {dupes} duplicates")
    print(f"misfile candidates (title≠filename): {len(misfiled)}")
    for n, t in misfiled[:8]:
        print(f"  ? {n[:40]:40} title~ {t[:34]}")
    print(f"\nnaming plan sample ({'APPLIED symlinks' if a.apply else 'plan only'}):")
    for _, opath, name in plan[:8]:
        print(f"  {name}")
    (work / "organize_plan.json").write_text(json.dumps(
        [{"artifact_id": i, "original": o, "name": n} for i, o, n in plan], indent=2))


if __name__ == "__main__":
    main()
