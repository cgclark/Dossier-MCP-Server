#!/usr/bin/env python3
"""cluster.py — Dossier near-duplicate clustering (counterpart-signed agreements).

Counterpart execution = the same instrument signed in separate copies by different
parties; together they're ONE agreement. Exact SHA dedup won't merge them (signatures
differ), so this groups artifacts whose BODY text is near-identical via shingle-Jaccard.
Every copy is preserved; the group records the logical agreement + the executed date
(latest signing across copies). Deterministic, no LLM.

    cluster.py <workdir> [--threshold 0.8] [--apply]
"""
import argparse, sqlite3, re, hashlib
from collections import defaultdict
from pathlib import Path


def stable(s):
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")


def shingles(text, k=5):
    toks = [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) >= 2]
    if len(toks) < k:
        return {stable(t) for t in toks}
    return {stable(" ".join(toks[i:i + k])) for i in range(len(toks) - k + 1)}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


class UF:
    def __init__(self, n): self.p = list(range(n))
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b): self.p[self.find(a)] = self.find(b)


def ensure_schema(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(artifact)")]
    if "group_id" not in cols:
        db.execute("ALTER TABLE artifact ADD COLUMN group_id INTEGER")
    db.execute("""CREATE TABLE IF NOT EXISTS agreement_group(
        id INTEGER PRIMARY KEY, members INTEGER, similarity REAL, executed_wall TEXT, label TEXT)""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--threshold", type=float, default=0.8)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    db = sqlite3.connect(Path(a.workdir) / "manifest.db")
    ensure_schema(db)

    rows = db.execute("SELECT a.id, a.original_path, a.title, "
                      "(SELECT body FROM doc_fts d WHERE d.artifact_id=a.id) "
                      "FROM artifact a WHERE a.duplicate_of IS NULL").fetchall()
    items = []  # (aid, path, title, shingleset)
    for aid, path, title, body in rows:
        sh = shingles(body)
        if len(sh) >= 20:        # skip near-empty/sparse-OCR docs (would cluster spuriously)
            items.append((aid, path, title, sh))

    n = len(items)
    uf = UF(n)
    sims = {}
    for i in range(n):
        for j in range(i + 1, n):
            la, lb = len(items[i][3]), len(items[j][3])
            if min(la, lb) / max(la, lb) < 0.5:      # prune by size ratio
                continue
            s = jaccard(items[i][3], items[j][3])
            if s >= a.threshold:
                uf.union(i, j); sims[(i, j)] = s

    groups = defaultdict(list)
    for idx in range(n):
        groups[uf.find(idx)].append(idx)
    multi = [g for g in groups.values() if len(g) > 1]

    print(f"near-dup clustering @ threshold {a.threshold}: "
          f"{len(multi)} counterpart group(s) among {n} eligible artifacts")
    for g in multi:
        members = [items[i] for i in g]
        ss = [sims[(min(i, j), max(i, j))] for x, i in enumerate(g) for j in g[x + 1:]
              if (min(i, j), max(i, j)) in sims]
        avg = sum(ss) / len(ss) if ss else 1.0
        aids = [m[0] for m in members]
        q = ("SELECT MAX(COALESCE(value_wall,value_utc)) FROM event WHERE artifact_id IN (%s) "
             "AND (kind IN ('signed','executed','effective') OR kind LIKE 'docusign%%')"
             % ",".join("?" * len(aids)))
        executed = db.execute(q, aids).fetchone()[0]
        label = (members[0][2] or Path(members[0][1]).name)[:50]
        print(f"\n  • agreement: {len(members)} copies · ~{avg:.2f} similarity · {label}")
        for m in members:
            print(f"      - {Path(m[1]).name[:58]}")
        print(f"      executed (latest signing across copies): {executed or 'n/a'}")
        if a.apply:
            gid = db.execute("INSERT INTO agreement_group(members,similarity,executed_wall,label) "
                             "VALUES(?,?,?,?)", (len(members), round(avg, 3), executed, label)).lastrowid
            for m in members:
                db.execute("UPDATE artifact SET group_id=? WHERE id=?", (gid, m[0]))
    if a.apply:
        db.commit()
        print("\napplied: group_id set on member artifacts; agreement_group populated.")
    elif multi:
        print("\n(plan only — re-run with --apply to record the groups)")


if __name__ == "__main__":
    main()
