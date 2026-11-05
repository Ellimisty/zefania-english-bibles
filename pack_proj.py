"""Bake token_strongs_proj into a .pack as a proj_tags table.

proj_tags(translation_id, bnum, cnum, vnum, pos, strong_id, method, confidence)

Packs with this table no longer need bible_graph.db nearby for the
reader's projected-tag overlay.

Usage: python pack_proj.py <pack> [<pack> ...]
       python pack_proj.py bibles.pack
"""

import sqlite3
import sys

GRAPH = "bible_graph.db"


def bake(pack):
    g = sqlite3.connect(GRAPH, timeout=300)
    con = sqlite3.connect(pack)
    con.execute("""CREATE TABLE IF NOT EXISTS proj_tags(
        translation_id INT, bnum INT, cnum INT, vnum INT, pos INT,
        strong_id INT, method TEXT, confidence REAL)""")
    con.execute("DELETE FROM proj_tags")

    slug2tid = dict(con.execute(
        "SELECT slug, id FROM translations").fetchall())
    g2pack = {}
    for (slug, tid) in slug2tid.items():
        g2pack[slug] = tid

    vmap = {r[0]: r[1:] for r in g.execute(
        "SELECT id, bnumber, cnumber, vnumber FROM verses")}
    n = 0
    # map graph translations -> pack ids via slug
    for gtid, slug in g.execute("SELECT id, slug FROM translations"):
        if slug not in g2pack:
            continue
        ptid = g2pack[slug]
        for vid, pos, code, method, conf in g.execute("""
            SELECT p.verse_id, p.position, s.code, p.method, p.confidence
            FROM token_strongs_proj p JOIN strongs s ON s.id=p.strong_id
            WHERE p.translation_id=?""", (gtid,)):
            b, c, v = vmap.get(vid, (None, None, None))
            if b is None:
                continue
            # pack strong ids are local: pack code -> strongs_dict id
            con.execute(
                "INSERT OR IGNORE INTO strongs_dict(code) VALUES (?)", (code,))
            psid = con.execute(
                "SELECT id FROM strongs_dict WHERE code=?", (code,)).fetchone()[0]
            con.execute(
                "INSERT OR REPLACE INTO proj_tags VALUES (?,?,?,?,?,?,?,?)",
                (ptid, b, c, v, pos, psid, method, conf))
            n += 1
        con.commit()
    con.execute("""CREATE INDEX IF NOT EXISTS idx_proj ON
        proj_tags(translation_id, bnum, cnum, vnum)""")
    con.commit()
    con.execute("VACUUM")
    print(f"{pack}: {n:,} projected tags")
    con.close(); g.close()


if __name__ == "__main__":
    for p in sys.argv[1:]:
        bake(p)
