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


def verse_map(c, kjv_pack="bibles-kjv-web.pack"):
    """testament -> {sword_index: graph verse_id}.

    SWORD indexes by KJV v11n verse ordinal. Build the ordinal list
    from the pack's KJV verse set (exact v11n) so non-canonical rows
    (v0 prologues, expanded verse counts) can't shift the mapping.
    """
    vid_of = {r[0]: r[1] for r in c.execute(
        "SELECT bnumber||'.'||cnumber||'.'||vnumber, id FROM verses")}
    pk = sqlite3.connect(kjv_pack)
    tid = pk.execute(
        "SELECT id FROM translations WHERE identifier='KJV'"
        ).fetchone()[0]
    ot = {}
    nt = {}
    rows = pk.execute(
        "SELECT bnum, cnum, vnum FROM verses WHERE translation_id=? "
        "ORDER BY bnum, cnum, vnum", (tid,)).fetchall()
    pk.close()
    i_ot = i_nt = 0
    for b, ch, v in rows:
        vid = vid_of.get(f"{b}.{ch}.{v}")
        if not vid:
            continue
        if b <= 39:
            ot[i_ot] = vid
            i_ot += 1
        else:
            nt[i_nt] = vid
            i_nt += 1
    return {"ot": ot, "nt": nt}


def mod_dir(path, sub):
    """find modules/<drv>/<name>/ inside an extracted module dir"""
    for root, _, files in os.walk(path):
        if any(f.endswith((".bzv", ".czv", ".zdt", ".idx"))
               for f in files):
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


def chapter_map(c, kjv_pack="bibles-kjv-web.pack"):
    """testament -> {chapter_ordinal: [graph verse_ids]} — KJV v11n."""
    pk = sqlite3.connect(kjv_pack)
    tid = pk.execute(
        "SELECT id FROM translations WHERE identifier='KJV'"
        ).fetchone()[0]
    rows = pk.execute(
        "SELECT DISTINCT bnum, cnum FROM verses WHERE translation_id=? "
        "ORDER BY bnum, cnum", (tid,)).fetchall()
    pk.close()
    ot, nt = {}, {}
    i_ot = i_nt = 0
    for b, ch in rows:
        vids = [r[0] for r in c.execute(
            "SELECT id FROM verses WHERE bnumber=? AND cnumber=? AND "
            "vnumber>0 ORDER BY vnumber", (b, ch))]
        if b <= 39:
            ot[i_ot] = vids
            i_ot += 1
        else:
            nt[i_nt] = vids
            i_nt += 1
    return {"ot": ot, "nt": nt}


def ingest_commentary(name, modpath, db="bible_graph.db"):
    c = sqlite3.connect(db, timeout=300)
    c.execute("PRAGMA busy_timeout=300000")
    c.execute("""CREATE TABLE IF NOT EXISTS commentary(
        verse_id INT, source TEXT, text TEXT,
        PRIMARY KEY(verse_id, source))""")
    base = mod_dir(modpath, "comments")
    chapter_level = any(f.endswith(".czz") for f in os.listdir(base)
                        if os.path.isfile(os.path.join(base, f)))
    if chapter_level:
        vm = chapter_map(c)
        per_entry = lambda m, i: m.get(i, [])
    else:
        vm = verse_map(c)
        per_entry = lambda m, i: [m[i]] if i in m else []
    n = 0
    for t, m in (("ot", vm["ot"]), ("nt", vm["nt"])):
        try:
            z = ZModule(base, t)
            nv = z.nverses()
        except Exception:
            continue
        for i in range(nv):
            try:
                entry = z.read(i)
            except Exception:
                continue
            if not entry.strip():
                continue
            for vid in per_entry(m, i):
                txt = re.sub(r"<[^>]+>", " ", entry)
                txt = re.sub(r"\s+", " ", txt).strip()
                c.execute(
                    "INSERT OR REPLACE INTO commentary VALUES (?,?,?)",
                    (vid, name, txt))
                n += 1
    c.commit()
    print(f"{name} entries: {n}")
    c.close()


def ingest_lexicon(name, modpath, db="bible_graph.db",
                   prefix_map=None):
    """zLD lexicon -> lexicon_extra(code, dict, defn).

    Keys like '00001'/'G1'/'Aaron' -> code. prefix_map converts numeric
    keys to codes, e.g. {'g':'G','h':'H'} picks by module.
    """
    from sword_read import ZLD
    base = mod_dir(modpath, "lexdict")
    c = sqlite3.connect(db, timeout=300)
    c.execute("PRAGMA busy_timeout=300000")
    c.execute("""CREATE TABLE IF NOT EXISTS lexicon_extra(
        code TEXT, dict TEXT, defn TEXT,
        PRIMARY KEY(code, dict))""")
    z = ZLD(base)
    n = 0
    for i, key in enumerate(z.keys):
        k = key.strip()
        if not k:
            continue
        code = k
        if k.isdigit() and prefix_map:
            code = prefix_map + k
        try:
            txt = z.entry(i)
        except Exception:
            continue
        txt = re.sub(r"<[^>]+>", " ", txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        if txt:
            c.execute("INSERT OR REPLACE INTO lexicon_extra VALUES (?,?,?)",
                      (code, name, txt))
            n += 1
    c.commit()
    print(f"{name}: {n} entries")
    c.close()



def ingest_eusebian(modpath, db="bible_graph.db",
                    kjv_pack="bibles-kjv-web.pack"):
    c = sqlite3.connect(db, timeout=300)
    c.execute("PRAGMA busy_timeout=300000")
    c.execute("""CREATE TABLE IF NOT EXISTS parallels(
        b1 INT, c1 INT, v1 INT, b2 INT, c2 INT, v2 INT, score REAL,
        PRIMARY KEY(b1, c1, v1, b2, c2, v2))""")
    pk = sqlite3.connect(kjv_pack)
    tid = pk.execute(
        "SELECT id FROM translations WHERE identifier='KJV'"
        ).fetchone()[0]
    kjv = pk.execute(
        "SELECT bnum, cnum, vnum FROM verses WHERE translation_id=? AND "
        "bnum BETWEEN 40 AND 66 ORDER BY bnum, cnum, vnum",
        (tid,)).fetchall()
    pk.close()
    z = ZModule(os.path.join(modpath, "modules/texts/ztext/eusebian"),
                "nt")
    groups = {}
    for i in range(min(z.nverses(), len(kjv))):
        try:
            num = z.read(i).strip().lstrip(".")
        except Exception:
            continue
        if not num:
            continue
        groups.setdefault(num, []).append(kjv[i])
    n = 0
    seen = set()
    for num, vs in groups.items():
        if len(vs) < 2:
            continue
        for i, a in enumerate(vs):
            for b in vs[i + 1:]:
                key = (min(a, b), max(a, b))
                if key in seen:
                    continue
                seen.add(key)
                c.execute(
                    "INSERT OR REPLACE INTO parallels VALUES (?,?,?,?,?,?,?)",
                    (a[0], a[1], a[2], b[0], b[1], b[2], 1.0))
                n += 1
    c.commit()
    print(f"eusebian pairs: {n}")
    c.close()

if __name__ == "__main__":
    if "--eusebian" in sys.argv:
        ingest_eusebian(sys.argv[sys.argv.index("--eusebian") + 1])
        sys.exit()
    if "--lexicon" in sys.argv:
        i = sys.argv.index("--lexicon")
        pref = (sys.argv[sys.argv.index("--prefix") + 1]
                if "--prefix" in sys.argv else None)
        ingest_lexicon(sys.argv[i + 1], sys.argv[i + 2], prefix_map=pref)
        sys.exit()
    if "--tsk" in sys.argv:
        ingest_tsk(sys.argv[sys.argv.index("--tsk") + 1])
    elif "--commentary" in sys.argv:
        i = sys.argv.index("--commentary")
        ingest_commentary(sys.argv[i + 1], sys.argv[i + 2])
