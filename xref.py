"""Build the xref verse->verse edge layer -> xref(v1, v2, kind, weight).

Sources (all in-house):
  topic   - verses sharing a Torrey's subtopic (topic_sub)
  parallel- computed synoptic parallels (score >= 0.35)
  strong  - verses sharing 2+ Strong's roots (rare-root co-occurrence)
  sim     - high similarity scores from the similarity table (if present)

weight: topic=0.7, parallel=0.9, strong=0.5, sim=0.6 (heuristic;
duplicates across kinds are merged with max weight).

Usage: python xref.py [bible_graph.db]
"""

import os
import sqlite3
import sys
from collections import defaultdict


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else "bible_graph.db"
    c = sqlite3.connect(db, timeout=300)
    c.execute("PRAGMA busy_timeout=300000")
    c.execute("""CREATE TABLE IF NOT EXISTS xref(
        v1 INT, v2 INT, kind TEXT, weight REAL,
        PRIMARY KEY(v1, v2, kind))""")
    c.execute("DELETE FROM xref")

    # topic: verses sharing a subtopic -> complete the pair graph per sub
    sub_map = defaultdict(list)
    for sid, b, ch, v in c.execute(
            "SELECT sub_id, bnum, cnum, vnum FROM topic_refs"):
        vid = c.execute(
            "SELECT id FROM verses WHERE bnumber=? AND cnumber=? AND vnumber=?",
            (b, ch, v)).fetchone()
        if vid:
            sub_map[sid].append(vid[0])
    n = 0
    for sid, vids in sub_map.items():
        for i, a in enumerate(vids):
            for b in vids[i + 1:i + 9]:  # cap 8 links per verse per topic
                c.execute("INSERT OR REPLACE INTO xref VALUES (?,?,?,?)",
                          (a, b, "topic", 0.7))
                c.execute("INSERT OR REPLACE INTO xref VALUES (?,?,?,?)",
                          (b, a, "topic", 0.7))
                n += 2
    print(f"topic edges: {n}")

    # parallels: verse_id lookup from (b,c,v) keys
    vid_of = {r[0]: r[1] for r in c.execute(
        "SELECT bnumber||'.'||cnumber||'.'||vnumber, id FROM verses")}
    n = 0
    for b1, c1, v1, b2, c2, v2, s in c.execute(
            "SELECT b1,c1,v1,b2,c2,v2,score FROM parallels WHERE score >= 0.35"):
        a = vid_of.get(f"{b1}.{c1}.{v1}")
        b = vid_of.get(f"{b2}.{c2}.{v2}")
        if a and b:
            c.execute("INSERT OR REPLACE INTO xref VALUES (?,?,?,?)",
                      (a, b, "parallel", 0.9))
            c.execute("INSERT OR REPLACE INTO xref VALUES (?,?,?,?)",
                      (b, a, "parallel", 0.9))
            n += 2
    print(f"parallel edges: {n}")

    # strong co-occurrence: verses sharing >=2 strong codes (KJV tags)
    share = defaultdict(list)
    for vid, code in c.execute("""
        SELECT ts.verse_id, ts.strong_id FROM token_strongs ts
        JOIN translations tr ON tr.id=ts.translation_id
        WHERE tr.identifier='KJV'"""):
        share[code].append(vid)
    n = 0
    pair_n = defaultdict(int)
    for code, vids in share.items():
        if len(vids) > 400:
            continue  # common roots too weak as edges
        for i, a in enumerate(vids):
            for b in vids[i + 1:]:
                k = (a, b) if a < b else (b, a)
                pair_n[k] += 1
    for (a, b), cnt in pair_n.items():
        if cnt >= 2:
            c.execute("INSERT OR REPLACE INTO xref VALUES (?,?,?,?)",
                      (a, b, "strong", 0.5))
            c.execute("INSERT OR REPLACE INTO xref VALUES (?,?,?,?)",
                      (b, a, "strong", 0.5))
            n += 2
    print(f"strong edges: {n}")

    # openbible: voted human cross-references
    ob_map = {"gen": 1, "exo": 2, "lev": 3, "num": 4, "deut": 5, "josh": 6,
              "judg": 7, "ruth": 8, "1sam": 9, "2sam": 10, "1kgs": 11,
              "1kin": 11, "2kgs": 12, "2kin": 12, "1chr": 13, "2chr": 14,
              "ezra": 15, "neh": 16, "esth": 17, "job": 18, "ps": 19,
              "psa": 19, "prov": 20, "eccl": 21, "song": 22, "isa": 23,
              "jer": 24, "lam": 25, "ezek": 26, "dan": 27, "hos": 28,
              "joel": 29, "amos": 30, "obad": 31, "jonah": 32, "mic": 33,
              "nah": 34, "hab": 35, "zeph": 36, "hag": 37, "zech": 38,
              "mal": 39, "matt": 40, "mark": 41, "luke": 42, "john": 43,
              "acts": 44, "rom": 45, "1cor": 46, "2cor": 47, "gal": 48,
              "eph": 49, "phil": 50, "col": 51, "1thess": 52, "2thess": 53,
              "1tim": 54, "2tim": 55, "titus": 56, "phlm": 57, "heb": 58,
              "jas": 59, "james": 59, "1pet": 60, "2pet": 61, "1john": 62,
              "2john": 63, "3john": 64, "jude": 65, "rev": 66}
    vid_of2 = {r[0]: r[1] for r in c.execute(
        "SELECT bnumber||'.'||cnumber||'.'||vnumber, id FROM verses")}

    def ob_ref(s):
        s = s.strip()
        m = s.split(".")
        if len(m) < 3:
            return None
        b = ob_map.get(m[0].lower().replace(" ", ""))
        if not b:
            return None
        return f"{b}.{m[1]}.{m[2]}"

    n = 0
    path = "cross-references/cross_references.txt"
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if line.startswith("#") or "\t" not in line:
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            a0, b0, votes = parts[0], parts[1], parts[2]
            try:
                votes = int(votes)
            except ValueError:
                continue
            # expand "B.C.V1-B.C.V2" ranges to first verse only (graph
            # granularity)
            b1 = b0.split("-")[0]
            a = vid_of2.get(ob_ref(a0) or "")
            b = vid_of2.get(ob_ref(b1) or "")
            if a and b:
                w = min(0.5 + votes / 200.0, 1.0)
                c.execute("INSERT OR REPLACE INTO xref VALUES (?,?,?,?)",
                          (a, b, "openbible", w))
                c.execute("INSERT OR REPLACE INTO xref VALUES (?,?,?,?)",
                          (b, a, "openbible", w))
                n += 2
    print(f"openbible edges: {n}")

    c.execute("CREATE INDEX IF NOT EXISTS idx_xref ON xref(v1)")
    c.commit()
    print(f"total: {c.execute('SELECT COUNT(*) FROM xref').fetchone()[0]:,}")
    c.close()


if __name__ == "__main__":
    main()
