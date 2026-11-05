"""Ingest a SWORD zText Bible translation -> bible_graph.db.

  python ingest_sword_bible.py <ModName> <sword/mods/ModName> [pack]

Maps SWORD verse indices to graph verse ids using the pack's KJV v11n
verse order (ot = i-th OT verse, nt = i-th NT verse). Text is tokenized
on whitespace with edge punctuation split off — matches graph style
approximately. Deleting rows for the slug first makes reruns idempotent.
"""

import os
import re
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sword_read import ZModule

TAG = re.compile(r"<[^>]+>")
WORD = re.compile(r"([A-Za-z0-9']+|[.,;:!?()\[\]\-—\"“”‘’])")


def tokenize(text):
    text = TAG.sub(" ", text)
    return WORD.findall(text)


def main():
    slug = sys.argv[1]
    modpath = sys.argv[2]
    pack = sys.argv[3] if len(sys.argv) > 3 else "bibles-kjv-web.pack"
    db = "bible_graph.db"
    g = sqlite3.connect(db, timeout=600)
    g.execute("PRAGMA busy_timeout=600000")
    g.execute("PRAGMA journal_mode=WAL")

    # KJV v11n ordinal -> graph verse id (same map as ingest_sword)
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
    ot = {}
    nt = {}
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

    # translation row (idempotent by slug)
    g.execute("DELETE FROM verse_tokens WHERE translation_id IN"
              " (SELECT id FROM translations WHERE identifier=?)", (slug,))
    g.execute("DELETE FROM translations WHERE identifier=?", (slug,))
    cur = g.execute(
        "INSERT INTO translations (slug, name, identifier) VALUES (?,?,?)",
        (slug.lower(), slug, slug))
    trid = cur.lastrowid

    token_id = {}
    tok_ins = 0

    def tok(t):
        nonlocal tok_ins
        if t in token_id:
            return token_id[t]
        low = t.lower()
        isp = 0 if t.isalnum() or "'" in t else 1
        r = g.execute(
            "INSERT OR IGNORE INTO tokens (text, lower, is_punct)"
            " VALUES (?,?,?)", (t, low, isp))
        tid_ = g.execute("SELECT id FROM tokens WHERE text=?",
                         (t,)).fetchone()[0]
        token_id[t] = tid_
        tok_ins += 1
        return tid_

    base = None
    for root, _, files in os.walk(modpath):
        if "ot.bzv" in files or "nt.bzv" in files:
            base = root
            break
    if not base:
        sys.exit("no ztext files found")
    n = 0
    for tname, vm in (("ot", ot), ("nt", nt)):
        try:
            z = ZModule(base, tname)
            nv = z.nverses()
        except Exception:
            continue
        for i in range(nv):
            if i not in vm:
                continue
            try:
                text = z.read(i)
            except Exception:
                continue
            words = tokenize(text)
            if not words:
                continue
            vid = vm[i]
            for pos, w in enumerate(words):
                g.execute(
                    "INSERT OR REPLACE INTO verse_tokens VALUES (?,?,?,?)",
                    (trid, vid, pos, tok(w)))
            n += 1
            if n % 50000 == 0:
                g.commit()
                print(f"{n:,} tokens")
    g.commit()
    print(f"{slug}: {n:,} tokens ({tok_ins:,} new token rows)")
    g.close()


if __name__ == "__main__":
    main()
