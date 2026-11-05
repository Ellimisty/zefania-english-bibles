"""Ingest SWORD zCom modules -> bible_graph.db.

  TSK (and any zCom commentary) -> xref kind='tsk' edges
  Other commentaries           -> commentary(verse_id, source, text)

Verse mapping: SWORD zCom indexes by testament verse ordinal
(KJV v11n). Our verses table in canonical order maps 1:1:
  ot.bzv index i -> i-th verse with bnumber<=39
  nt.bzv index i -> i-th verse with bnumber in 40..66

Usage:
  python ingest_sword.py --tsk sword/mods/TSK
  python ingest_sword.py --commentary MHC sword/mods/MHC
"""

import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sword_read import ZModule
from ingest_esword import parse_refs


def verse_map(c):
    """testament -> {sword_index: our verse_id}"""
    ot = {}
    nt = {}
    for i, vid in enumerate(c.execute(
            "SELECT id FROM verses WHERE bnumber<=39 ORDER BY "
            "bnumber, cnumber, vnumber")):
        ot[i] = vid[0]
    for i, vid in enumerate(c.execute(
            "SELECT id FROM verses WHERE bnumber BETWEEN 40 AND 66 "
            "ORDER BY bnumber, cnumber, vnumber")):
        nt[i] = vid[0]
    return {"ot": ot, "nt": nt}


def mod_dir(path, sub):
    """find modules/<drv>/<name>/ inside an extracted module dir"""
    for root, _, files in os.walk(path):
        if "ot.bzv" in files or "nt.bzv" in files or \
           any(f.endswith(".bzv") for f in files):
            return root
    return path


def ingest_tsk(modpath, db="bible_graph.db"):
    c = sqlite3.connect(db, timeout=300)
    c.execute("PRAGMA busy_timeout=300000")
    c.execute("""CREATE TABLE IF NOT EXISTS xref(
        v1 INT, v2 INT, kind TEXT, weight REAL,
        PRIMARY KEY(v1, v2, kind))""")
    vm = verse_map(c)
    vid_of = {r[0]: r[1] for r in c.execute(
        "SELECT bnumber||'.'||cnumber||'.'||vnumber, id FROM verses")}
    base = mod_dir(modpath, "comments")
    n = 0
    for t, vm in (("ot", vm["ot"]), ("nt", vm["nt"])):
        z = ZModule(base, t)
        for i in range(z.nverses()):
            try:
                entry = z.read(i)
            except Exception:
                continue
            if not entry.strip() or i not in vm:
                continue
            a = vm[i]
            for b2, ch2, vv2 in parse_refs(entry):
                tgt = vid_of.get(f"{b2}.{ch2}.{vv2}")
                if tgt and tgt != a:
                    c.execute(
                        "INSERT OR REPLACE INTO xref VALUES (?,?,?,?)",
                        (a, tgt, "tsk", 0.8))
                    c.execute(
                        "INSERT OR REPLACE INTO xref VALUES (?,?,?,?)",
                        (tgt, a, "tsk", 0.8))
                    n += 2
    c.execute("CREATE INDEX IF NOT EXISTS idx_xref ON xref(v1)")
    c.commit()
    print(f"tsk edges added: {n}")
    c.close()


def ingest_commentary(name, modpath, db="bible_graph.db"):
    c = sqlite3.connect(db, timeout=300)
    c.execute("PRAGMA busy_timeout=300000")
    c.execute("""CREATE TABLE IF NOT EXISTS commentary(
        verse_id INT, source TEXT, text TEXT,
        PRIMARY KEY(verse_id, source))""")
    vm = verse_map(c)
    base = mod_dir(modpath, "comments")
    n = 0
    for t, m in (("ot", vm["ot"]), ("nt", vm["nt"])):
        z = ZModule(base, t)
        for i in range(z.nverses()):
            try:
                entry = z.read(i)
            except Exception:
                continue
            if not entry.strip() or i not in m:
                continue
            # strip ThML tags for plain-text storage
            txt = re.sub(r"<[^>]+>", " ", entry)
            txt = re.sub(r"\s+", " ", txt).strip()
            c.execute("INSERT OR REPLACE INTO commentary VALUES (?,?,?)",
                      (m[i], name, txt))
            n += 1
    c.commit()
    print(f"{name} entries: {n}")
    c.close()


if __name__ == "__main__":
    if "--tsk" in sys.argv:
        ingest_tsk(sys.argv[sys.argv.index("--tsk") + 1])
    elif "--commentary" in sys.argv:
        i = sys.argv.index("--commentary")
        ingest_commentary(sys.argv[i + 1], sys.argv[i + 2])
