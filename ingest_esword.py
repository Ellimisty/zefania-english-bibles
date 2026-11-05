"""Ingest e-Sword modules (.bblx/.lexx/.dctx/.topx/.refx) -> bible_graph.db.

Decode chain (from SimpleBibleReader FormatUtil.cs):
  plaintext = zlib_decompress( twofish_ecb_decrypt(blob, key) + [skip 2] )
  key = ESWORD_KEY env var or KEY constant below (16 bytes hex)

The released source strips Passwords.eSword9_Password; restore it from
any fork that kept it or from your e-Sword install, then:
  ESWORD_KEY=<hex> python ingest_esword.py e-Sword/thayer.lexx --dump

Usage:
  python ingest_esword.py <module>            # list tables/rows
  python ingest_esword.py <module> --dump N   # show first N decoded rows
  python ingest_esword.py <lexx> --lexicon    # -> lexicon_extra table
"""

import os
import sqlite3
import sys
import zlib

KEY_HEX = os.environ.get("ESWORD_KEY", "")
_IV = bytes(16)


def decode(blob):
    if not KEY_HEX:
        raise SystemExit("set ESWORD_KEY=<hex key> first")
    from twofish import Twofish
    key = bytes.fromhex(KEY_HEX)
    tf = Twofish(key)
    data = blob + b"\x00" * ((16 - len(blob) % 16) % 16)
    plain = b"".join(tf.decrypt(data[i:i + 16])
                     for i in range(0, len(data), 16))
    return zlib.decompress(plain[2:])


def list_module(path):
    c = sqlite3.connect(path)
    for name, in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"):
        if name.startswith("sqlite"):
            continue
        n = c.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({name})")]
        print(f"  {name}: {n} rows {cols}")
    c.close()


def main():
    path = sys.argv[1]
    if "--dump" in sys.argv:
        n = int(sys.argv[sys.argv.index("--dump") + 1])
        c = sqlite3.connect(path)
        tbl = c.execute("SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name NOT LIKE 'sqlite%' LIMIT 1").fetchone()[0]
        print(f"(decoding {tbl})")
        for row in c.execute(f"SELECT * FROM {tbl} LIMIT {n}"):
            print(row[0], decode(row[-1])[:200])
        c.close()
        return
    print(path)
    list_module(path)


# ---- TSK: decode VerseCommentary -> parse ref lists -> xref edges ----

TSK_BOOKS = {"gn": 1, "ex": 2, "lv": 3, "nu": 4, "dt": 5, "jos": 6,
             "jdg": 7, "ru": 8, "1sa": 9, "2sa": 10, "1ki": 11,
             "2ki": 12, "1ch": 13, "2ch": 14, "ezr": 15, "ne": 16,
             "es": 17, "job": 18, "ps": 19, "pr": 20, "ec": 21,
             "so": 22, "is": 23, "je": 24, "la": 25, "ezk": 26,
             "da": 27, "ho": 28, "jl": 29, "am": 30, "ob": 31,
             "jon": 32, "mic": 33, "na": 34, "hab": 35, "zep": 36,
             "hag": 37, "zec": 38, "mal": 39, "mt": 40, "mr": 41,
             "lu": 42, "joh": 43, "ac": 44, "ro": 45, "1co": 46,
             "2co": 47, "ga": 48, "eph": 49, "php": 50, "col": 51,
             "1th": 52, "2th": 53, "1ti": 54, "2ti": 55, "tit": 56,
             "phm": 57, "heb": 58, "jas": 59, "1pe": 60, "2pe": 61,
             "1jo": 62, "2jo": 63, "3jo": 64, "jude": 65, "re": 66}

import re
REF_RE = re.compile(
    r"\b(\d?\s?[A-Za-z]{2,4})\s+(\d+):(\d+)(?:\s*-\s*(\d+))?\b")


def parse_refs(text):
    """Extract 'Ge 1:1' / 'Ps 119:105-110' style refs from decoded TSK."""
    out = []
    for m in REF_RE.finditer(text):
        book = m.group(1).replace(" ", "").lower()
        if book not in TSK_BOOKS:
            continue
        b, ch, v1 = TSK_BOOKS[book], int(m.group(2)), int(m.group(3))
        v2 = int(m.group(4)) if m.group(4) else v1
        out.extend((b, ch, v) for v in range(v1, min(v2 + 1, v1 + 20)))
    return out


def ingest_tsk(path, graph_db="bible_graph.db"):
    """Decode tsk.cmtx VerseCommentary -> xref kind='tsk'."""
    src = sqlite3.connect(path)
    g = sqlite3.connect(graph_db)
    g.execute("""CREATE TABLE IF NOT EXISTS xref(
        v1 INT, v2 INT, kind TEXT, weight REAL,
        PRIMARY KEY(v1, v2, kind))""")
    vid_of = {r[0]: r[1] for r in g.execute(
        "SELECT bnumber||'.'||cnumber||'.'||vnumber, id FROM verses")}
    n = 0
    for b, c1, v1, c2, v2, blob in src.execute(
            "SELECT Book,ChapterBegin,VerseBegin,ChapterEnd,VerseEnd,"
            "Comments FROM VerseCommentary"):
        a = vid_of.get(f"{b}.{c1}.{v1}")
        if not a:
            continue
        text = decode(blob).decode("utf-8", "replace")
        for b2, ch2, vv2 in parse_refs(text):
            tgt = vid_of.get(f"{b2}.{ch2}.{vv2}")
            if tgt and tgt != a:
                g.execute(
                    "INSERT OR REPLACE INTO xref VALUES (?,?,?,?)",
                    (a, tgt, "tsk", 0.8))
                g.execute(
                    "INSERT OR REPLACE INTO xref VALUES (?,?,?,?)",
                    (tgt, a, "tsk", 0.8))
                n += 2
    g.commit()
    print(f"tsk edges: {n}")
    src.close()
    g.close()


if __name__ == "__main__":
    if "--tsk" in sys.argv:
        ingest_tsk(sys.argv[1], sys.argv[sys.argv.index("--db") + 1]
                   if "--db" in sys.argv else "bible_graph.db")
    else:
        main()
