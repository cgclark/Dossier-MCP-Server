#!/usr/bin/env python3
"""chronology.py — Dossier Milestone 3.

Build (a) per-artifact timelines and (b) a merged matter-wide ledger, UTC-sorted,
with cross-artifact corroboration/conflict flags. Deterministic; reads the manifest.
Output is compact (the projection Claude reads), never document content.

    chronology.py <workdir> [--window-min 10] [--out chronology.json]
"""
import argparse, json, sqlite3, sys
from pathlib import Path
from datetime import datetime, timedelta

if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def sortkey(ev):
    # order by best available instant; zone-unknown wall-clocks sort by their stated time,
    # explicit UTC by the instant. None dates sink to the end.
    t = ev["value_utc"] or ev["value_wall"]
    return (t is None, t or "")


def parse(t):
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir"); ap.add_argument("--window-min", type=int, default=10)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    db = sqlite3.connect(Path(a.workdir) / "manifest.db")
    db.row_factory = sqlite3.Row

    rows = db.execute(
        "SELECT e.*, a.original_path, a.kind AS akind FROM event e "
        "JOIN artifact a ON a.id=e.artifact_id WHERE a.duplicate_of IS NULL "
        "AND (e.value_utc IS NOT NULL OR e.value_wall IS NOT NULL)").fetchall()

    events = []
    for r in rows:
        events.append({
            "artifact_id": r["artifact_id"], "doc": Path(r["original_path"]).name,
            "kind": r["kind"], "value_utc": r["value_utc"], "value_wall": r["value_wall"],
            "zone_status": r["zone_status"], "source": r["source"],
            "provenance": r["provenance"], "granularity": r["granularity"],
        })
    events.sort(key=sortkey)

    # per-artifact
    per = {}
    for e in events:
        per.setdefault(e["doc"], []).append(e)

    # merged: flag events within window across DIFFERENT artifacts (corroboration/conflict candidates)
    win = timedelta(minutes=a.window_min)
    timed = [(parse(e["value_utc"]), e) for e in events if parse(e["value_utc"])]
    for i, (ti, ei) in enumerate(timed):
        near = [ej["doc"] for tj, ej in timed
                if ej["doc"] != ei["doc"] and abs((ti - tj).total_seconds()) <= win.total_seconds()]
        if near:
            ei["coincident_with"] = sorted(set(near))

    out = {
        "artifacts": len(per),
        "events_total": len(events),
        "zone_unknown": sum(1 for e in events if e["zone_status"] == "unknown"),
        "coincidences": sum(1 for e in events if e.get("coincident_with")),
        "merged_ledger": events,      # compact, UTC-sorted
        "per_artifact": per,
    }
    dst = Path(a.out) if a.out else Path(a.workdir) / "chronology.json"
    dst.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"chronology: {out['artifacts']} artifacts, {out['events_total']} dated events "
          f"({out['zone_unknown']} zone-unknown), {out['coincidences']} cross-doc coincidences")
    print(f"written: {dst}")
    print("\nearliest 6 (UTC-ordered, doc-backed instants):")
    for e in [x for x in events if x["value_utc"]][:6]:
        print(f"  {e['value_utc'][:19]}  {e['kind']:10} {e['doc'][:34]:34} [{e['source']}]")


if __name__ == "__main__":
    main()
