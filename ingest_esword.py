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


if __name__ == "__main__":
    main()
