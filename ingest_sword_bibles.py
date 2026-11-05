"""Batch-ingest SWORD zText translations -> bible_graph.db.

  python ingest_sword_bibles.py [--limit N] [--only A,B]

Bulk inserts: one translation row per module, verse_tokens via
executemany. Skips modules that error. Progress to sword_bibles.log.
"""

import os
import re
import sqlite3
import sys
import glob as _g

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sword_read import ZModule

TAG = re.compile(r"<[^>]+>")
WORD = re.compile(r"([A-Za-z0-9']+|[.,;:!?()\[\]\-—\"“”‘’])")


def find_mods():
    out = []
    for moddir in sorted(_g.glob("sword/mods/*/")):
        for root, _, files in os.walk(moddir):
            if "nt.bzv" in files or "ot.bzv" in files:
                out.append((os.path.basename(moddir.rstrip("/\\")), root))
                break
    return out


def main():
    only = None
    if "--only" in sys.argv:
        only = {s.upper() for s in
                sys.argv[sys.argv.index("--only") + 1].split(",")}
    limit = (int(sys.argv[sys.argv.index("--limit") + 1])
             if "--limit" in sys.argv else 10**9)
    pack = "bibles-kjv-web.pack"

    g = sqlite3.connect("bible_graph.db", timeout=600)
    g.execute("PRAGMA busy_timeout=600000")
    g.execute("PRAGMA journal_mode=WAL")
    pk = sqlite3.connect(pack)
    tid = pk.execute(
        "SELECT id FROM translations WHERE identifier='KJV'"
        ).fetchone()[0]
    kjv = pk.execute(
        "SELECT bnum, cnum, vnum FROM verses WHERE translation_id=? "
        "ORDER BY bnum, cnum, vnum", (tid,)).fetchall()
    pk.close()
    vid_of = {r[0]: r[1] for r in g.execute(
        "SELECT bnumber||'.'||cnumber||'.'||vnumber, id FROM verses")}
    ot, nt = {}, {}
    i_ot = i_nt = 0
    for b, c, v in kjv:
        vid = vid_of.get(f"{b}.{c}.{v}")
        if not vid:
            continue
        if b <= 39:
            ot[i_ot] = vid
            i_ot += 1
        else:
            nt[i_nt] = vid
            i_nt += 1

    token_id = {r[0]: r[1] for r in g.execute(
        "SELECT text, id FROM tokens")}
    have = {r[0] for r in g.execute(
        "SELECT identifier FROM translations")}
    log = open("sword_bibles.log", "a", encoding="utf-8")

    done = 0
    for slug, base in find_mods():
        if done >= limit:
            break
        if only and slug.upper() not in only:
            continue
        if slug in have:
            continue
        try:
            zsets = []
            for tname, vm in (("ot", ot), ("nt", nt)):
                try:
                    z = ZModule(base, tname)
                    zsets.append((z, vm))
                except Exception:
                    pass
            if not zsets:
                continue
            # collect verses first
            verses = []  # (vid, [tokens])
            allw = set()
            for z, vm in zsets:
                for i in range(z.nverses()):
                    if i not in vm:
                        continue
                    try:
                        text = z.read(i)
                    except Exception:
                        continue
                    words = WORD.findall(TAG.sub(" ", text))
                    if not words or len(words) > 500:
                        continue
                    verses.append((vm[i], words))
                    allw.update(words)
            if len(verses) < 100:
                continue
            g.execute(
                "DELETE FROM translations WHERE identifier=?", (slug,))
            cur = g.execute(
                "INSERT INTO translations (slug,name,identifier)"
                " VALUES (?,?,?)", (slug.lower(), slug, slug))
            trid = cur.lastrowid
            newt = [(w, w.lower(),
                     0 if any(ch.isalnum() for ch in w) else 1)
                    for w in allw if w not in token_id]
            g.executemany(
                "INSERT OR IGNORE INTO tokens (text,lower,is_punct)"
                " VALUES (?,?,?)", newt)
            for w, *_ in newt:
                pass
            # fetch ids for everything used
            ids = {}
            for w in allw:
                r = token_id.get(w) or g.execute(
                    "SELECT id FROM tokens WHERE text=?",
                    (w,)).fetchone()[0]
                ids[w] = r
            rows = [(trid, vid, pos, ids[w])
                    for vid, words in verses
                    for pos, w in enumerate(words)]
            g.executemany(
                "INSERT OR REPLACE INTO verse_tokens VALUES (?,?,?,?)",
                rows)
            g.commit()
            done += 1
            msg = f"ok {slug}: {len(verses)} verses, {len(rows)} tokens"
            print(msg)
            log.write(msg + "\n")
            log.flush()
        except Exception as e:
            log.write(f"FAIL {slug}: {e}\n")
            log.flush()
    print(f"done: {done} modules")
    g.close()


if __name__ == "__main__":
    main()
