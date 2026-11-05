"""Export projection review buckets -> strong_review table + CSV.

Two kinds of cases from project_strongs (they never produced tags):
  no_consensus : word has a corpus prior but none of its codes appear in
                 this verse's consensus — prime LLM-adjudication material
  unmatched    : no prior at all — usually articles/particles or vocabulary
                 absent from tagged editions

Rows: strong_review(translation_id, verse_id, position, word, kind,
                    candidates, consensus)
candidates/consensus are comma-joined code lists for a reviewer to judge.

Usage: python export_review.py [--trans SLUG] [--csv review.csv]
"""

import argparse
import sqlite3
from collections import Counter, defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="bible_graph.db")
    ap.add_argument("--trans", help="only this translation id fragment")
    ap.add_argument("--csv")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db, timeout=300)
    conn.execute("PRAGMA busy_timeout=300000")

    prior = defaultdict(set)
    for w, code in conn.execute("""
        SELECT DISTINCT t.lower, s.code FROM token_strongs ts
        JOIN verse_tokens vt ON vt.translation_id=ts.translation_id
                            AND vt.verse_id=ts.verse_id
                            AND vt.position=ts.position
        JOIN tokens t ON t.id=vt.token_id
        JOIN strongs s ON s.id=ts.strong_id"""):
        prior[w].add(code)

    consensus = defaultdict(set)
    for vid, code in conn.execute("""
        SELECT DISTINCT ts.verse_id, s.code FROM token_strongs ts
        JOIN strongs s ON s.id=ts.strong_id"""):
        consensus[vid].add(code)

    projected = {(r[0], r[1], r[2]) for r in conn.execute(
        "SELECT translation_id, verse_id, position FROM token_strongs_proj")}
    tagged_tids = {r[0] for r in conn.execute(
        "SELECT DISTINCT translation_id FROM token_strongs")}

    conn.execute("""CREATE TABLE IF NOT EXISTS strong_review(
        translation_id INT, verse_id INT, position INT, word TEXT,
        kind TEXT, candidates TEXT, consensus TEXT,
        PRIMARY KEY(translation_id, verse_id, position))""")

    variants = dict(conn.execute(
        "SELECT surface, canonical FROM word_variants"))

    n = Counter()
    rows = []
    for tid, slug in conn.execute("SELECT id, slug FROM translations"):
        if tid in tagged_tids or (args.trans and args.trans not in slug):
            continue
        if "_ENG_" not in slug and "_English_" not in slug:
            continue
        for vid, pos, tok in conn.execute("""
            SELECT vt.verse_id, vt.position, t.lower
            FROM verse_tokens vt JOIN tokens t ON t.id=vt.token_id
            WHERE vt.translation_id=?""", (tid,)):
            if (tid, vid, pos) in projected:
                continue
            exp = consensus.get(vid)
            if not exp:
                continue
            cands = prior.get(tok)
            kind = "unmatched"
            if not cands:
                cands = prior.get(variants.get(tok, ""))
                kind = "unmatched_variant" if cands else "unmatched"
            else:
                kind = "no_consensus"
            rows.append((tid, vid, pos, tok, kind,
                         ",".join(sorted(cands)) if cands else "",
                         ",".join(sorted(exp))))
            n[kind] += 1
        conn.executemany(
            "INSERT OR REPLACE INTO strong_review VALUES (?,?,?,?,?,?,?)",
            rows)
        conn.commit()
        rows.clear()
        print(f"{slug}: {dict(n)}", flush=True)

    print(f"strong_review total: {sum(n.values()):,}  {dict(n)}")
    if args.csv:
        import csv
        w = csv.writer(open(args.csv, "w", newline="", encoding="utf-8"))
        w.writerow(["translation_id", "verse_id", "position", "word",
                    "kind", "candidates", "consensus"])
        w.writerows(conn.execute("SELECT * FROM strong_review LIMIT 50000"))
        print(f"-> {args.csv}")
    conn.close()


if __name__ == "__main__":
    main()
