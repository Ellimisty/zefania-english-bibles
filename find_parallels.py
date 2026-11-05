"""Detect parallel verses across the gospels -> parallels table.

Computes word-set Jaccard between verse pairs of Mt(40)/Mk(41)/Lk(42)/Jn(43)
using a reference translation's tokens. High similarity = candidate parallel
pericope. Stored:

  parallels(b1,c1,v1, b2,c2,v2, score)   — score = Jaccard on lowercased
                                           alphabetic tokens

Translation-agnostic: uses KJV+ tokens by default (richest Strong's edition),
but --trans changes the reference.
"""

import argparse
import itertools
import sqlite3
from collections import defaultdict

GOSPELS = [40, 41, 42, 43]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="bible_graph.db")
    ap.add_argument("--trans", default="KJV")
    ap.add_argument("--min", type=float, default=0.3)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db, timeout=300)
    conn.execute("PRAGMA busy_timeout=300000")
    tid = conn.execute("SELECT id FROM translations WHERE identifier=?",
                       (args.trans,)).fetchone()[0]

    # verse -> set of lowercased alphabetic tokens
    verses = defaultdict(dict)  # bnum -> {(c,v) -> set}
    for b, c, v, pos, tok in conn.execute("""
        SELECT v.bnumber, v.cnumber, v.vnumber, vt.position, t.lower
        FROM verse_tokens vt
        JOIN verses v ON v.id = vt.verse_id
        JOIN tokens t ON t.id = vt.token_id
        WHERE vt.translation_id=? AND v.bnumber IN (40,41,42,43)""", (tid,)):
        verses[b].setdefault((c, v), set()).add(tok)
    for b in GOSPELS:
        # drop non-alpha tokens (punct)
        for k in verses[b]:
            verses[b][k] = {w for w in verses[b][k] if any(ch.isalpha() for ch in w)}
        print(f"book {b}: {len(verses[b])} verses")

    conn.execute("""CREATE TABLE IF NOT EXISTS parallels(
        b1 INT, c1 INT, v1 INT, b2 INT, c2 INT, v2 INT, score REAL)""")
    conn.execute("DELETE FROM parallels")

    n = 0
    for b1, b2 in itertools.combinations(GOSPELS, 2):
        keys1, keys2 = list(verses[b1]), list(verses[b2])
        for k1 in keys1:
            s1 = verses[b1][k1]
            for k2 in keys2:
                s2 = verses[b2][k2]
                inter = len(s1 & s2)
                if inter < 3:
                    continue
                score = inter / len(s1 | s2)
                if score >= args.min:
                    conn.execute("INSERT INTO parallels VALUES (?,?,?,?,?,?,?)",
                                 (b1, *k1, b2, *k2, round(score, 3)))
                    n += 1
        print(f"{b1} x {b2}: {n} so far", flush=True)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_par ON parallels(b1,c1,v1)")
    conn.commit()
    print(f"parallels: {n}")
    # sanity: Mk 1.1-ish pairs
    for r in conn.execute(
            "SELECT * FROM parallels WHERE b1=40 AND b2=41 ORDER BY c1, v1 LIMIT 8"):
        print(r)
    conn.close()


if __name__ == "__main__":
    main()
