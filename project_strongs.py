"""Project Strong's codes onto untagged translations.

Pipeline per untagged verse:
  1. consensus = multiset of codes that tagged translations assign on the
     same verse (vote across tagged eds covering it)
  2. each untagged word gets candidate codes from the corpus-wide
     word->code prior (built from ALL tagged verses)
  3. pick the candidate inside the consensus multiset:
       - unique candidate hit        -> method='prior',  confidence 0.8
       - multiple candidates         -> method='vote',   confidence by margin
       - no prior -> spelling variant-> method='variant', confidence 0.5
  4. misses -> 'unmatched' (article/particle territory)

Output: token_strongs_proj(translation_id, verse_id, position,
                           strong_id, method, confidence)
Never writes token_strongs — this is a *projected* layer for review.

Usage: python project_strongs.py [--trans SLUG] [--limit N]
"""

import argparse
import sqlite3
from collections import Counter, defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="bible_graph.db")
    ap.add_argument("--trans", help="only this translation id")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db, timeout=300)
    conn.execute("PRAGMA busy_timeout=300000")

    # ---------- word -> code prior (all tagged verses) ----------
    print("building word->code prior...")
    prior = defaultdict(Counter)   # lower word -> Counter(code -> n)
    for w, code, n in conn.execute("""
        SELECT t.lower, s.code, COUNT(*) FROM token_strongs ts
        JOIN verse_tokens vt ON vt.translation_id=ts.translation_id
                            AND vt.verse_id=ts.verse_id
                            AND vt.position=ts.position
        JOIN tokens t ON t.id=vt.token_id
        JOIN strongs s ON s.id=ts.strong_id
        GROUP BY t.lower, s.code"""):
        prior[w][code] = n
    print(f"  {len(prior)} word forms")

    # equivalence pooling: code -> set including equivalents
    equiv = defaultdict(set)
    for c1, c2, kind in conn.execute(
            "SELECT code, other_code, kind FROM strong_equiv WHERE kind='equivalent'"):
        equiv[c1].add(c2); equiv[c2].add(c1)

    # spelling variants: surface -> canonical
    variants = dict(conn.execute(
        "SELECT surface, canonical FROM word_variants"))

    # ---------- per-verse consensus (code multiset across tagged eds) ----------
    print("building per-verse consensus...")
    consensus = defaultdict(Counter)  # verse_id -> Counter(code -> tagged-ed count)
    for vid, code, n in conn.execute("""
        SELECT ts.verse_id, s.code, COUNT(DISTINCT ts.translation_id)
        FROM token_strongs ts JOIN strongs s ON s.id=ts.strong_id
        GROUP BY ts.verse_id, s.code"""):
        consensus[vid][code] = n

    # ---------- untagged English translations ----------
    tagged = {r[0] for r in conn.execute(
        "SELECT DISTINCT translation_id FROM token_strongs")}
    untagged = [r for r in conn.execute(
        "SELECT id, slug FROM translations WHERE slug LIKE '%_ENG_%'")
        if r[0] not in tagged and (not args.trans or args.trans in r[1])]
    print(f"untagged ENG translations: {len(untagged)}")

    conn.execute("""CREATE TABLE IF NOT EXISTS token_strongs_proj(
        translation_id INT, verse_id INT, position INT,
        strong_id INT, method TEXT, confidence REAL,
        PRIMARY KEY(translation_id, verse_id, position))""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_tsp ON
        token_strongs_proj(verse_id)""")

    sid_of = {c: i for i, c in conn.execute("SELECT id, code FROM strongs")}
    stats = Counter()
    out = []
    for tid, slug in untagged:
        conn.execute("DELETE FROM token_strongs_proj WHERE translation_id=?",
                     (tid,))
        n_verses = 0
        for vid, pos, tok in conn.execute("""
            SELECT vt.verse_id, vt.position, t.lower
            FROM verse_tokens vt JOIN tokens t ON t.id=vt.token_id
            WHERE vt.translation_id=? ORDER BY vt.verse_id, vt.position""",
                (tid,)):
            if args.limit and n_verses >= args.limit:
                break
            expect = consensus.get(vid)
            if not expect:
                continue
            n_verses = max(n_verses, vid)  # approx progress
            cands = prior.get(tok)
            method = "prior"; conf = 0.8
            if not cands:
                canon = variants.get(tok)
                if canon:
                    cands = prior.get(canon)
                    method, conf = "variant", 0.5
            if not cands:
                stats["unmatched"] += 1
                continue
            # expand candidates through equivalence
            exp_set = set(expect)
            for e in list(exp_set):
                exp_set |= equiv.get(e, set())
            hits = [(c, cands[c]) for c in cands if c in exp_set]
            if not hits:
                stats["no_consensus"] += 1
                continue
            if len(hits) == 1:
                code = hits[0][0]
            else:
                hits.sort(key=lambda x: -x[1])
                code = hits[0][0]
                method = "vote"
                conf = hits[0][1] / (hits[0][1] + hits[1][1])
            out.append((tid, vid, pos, sid_of.get(code), method,
                        round(conf, 3)))
            stats[method] += 1
        if len(out) > 200000:
            conn.executemany(
                "INSERT OR REPLACE INTO token_strongs_proj VALUES (?,?,?,?,?,?)",
                out)
            conn.commit()
            out.clear()
        print(f"{slug}: done ({stats})", flush=True)

    conn.executemany(
        "INSERT OR REPLACE INTO token_strongs_proj VALUES (?,?,?,?,?,?)", out)
    conn.commit()
    print(f"projected: {sum(stats[k] for k in ('prior','vote','variant')):,} tags")
    print(dict(stats))
    conn.close()


if __name__ == "__main__":
    main()
