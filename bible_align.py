"""Batch verse-pair alignment sidecar -> <pack>.align.db

LCS-aligns every shared verse between two translations (same algorithm
as the reader's compare view) and stores:

  align(a, b, bnum, cnum, vnum, n_eq, n_a, n_b, sim, ops)

  sim = fraction of positions aligned equal
  ops = compact diff opcodes, e.g. "|2=servant/slave|7:heaven|9+of God"
        '=' replace, ':' delete from a, '+' insert in b

Powers divergence queries at scale (which chapters/books diverge most,
where identical text starts to split) without the GUI recomputing.

Usage: python bible_align.py --pack bibles-kjv-web.pack --a KJV --b WEB
"""

import argparse
import difflib
import sqlite3


def varints(buf):
    n = shift = 0
    for b in buf:
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            yield n; n = shift = 0
        else:
            shift += 7


def verse_words(con, tid, dic):
    """(bnum,cnum,vnum) -> list of lowercased alpha-normalized tokens."""
    out = {}
    for b, c, v, tb in con.execute(
            "SELECT v.bnum, v.cnum, v.vnum, s.tokens FROM verses v "
            "JOIN sequences s ON s.id=v.seq_id WHERE v.translation_id=?", (tid,)):
        out[(b, c, v)] = [dic.get(d, "").strip(",.;:!?()[]<>\"'").lower()
                          for d in varints(tb)]
    return out


def encode_ops(a, b, sm):
    parts = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            parts.append(f"{i1}={'/'.join(a[i1:i2])}/{'/'.join(b[j1:j2])}")
        elif tag == "delete":
            parts.append(f"{i1}:{'/'.join(a[i1:i2])}")
        elif tag == "insert":
            parts.append(f"{i1}+{'/'.join(b[j1:j2])}")
    return "|".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="bibles.pack")
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    args = ap.parse_args()

    con = sqlite3.connect(args.pack)
    dic = dict(con.execute("SELECT id, text FROM dictionary"))
    def pick(s):
        r = con.execute("SELECT id FROM translations WHERE identifier=?",
                        (s,)).fetchone()
        if not r:
            r = con.execute("SELECT id FROM translations WHERE slug LIKE ? "
                            "LIMIT 1", (f"%{s}%",)).fetchone()
        return r[0]
    tid_a = pick(args.a)
    tid_b = pick(args.b)
    ida = con.execute("SELECT identifier FROM translations WHERE id=?",
                      (tid_a,)).fetchone()[0]
    idb = con.execute("SELECT identifier FROM translations WHERE id=?",
                      (tid_b,)).fetchone()[0]

    va, vb = verse_words(con, tid_a, dic), verse_words(con, tid_b, dic)
    shared = sorted(set(va) & set(vb))
    print(f"{ida} x {idb}: {len(shared)} shared verse coords")

    out = args.pack + ".align.db"
    odb = sqlite3.connect(out)
    odb.execute("""CREATE TABLE IF NOT EXISTS align(
        a TEXT, b TEXT, bnum INT, cnum INT, vnum INT,
        n_eq INT, n_a INT, n_b INT, sim REAL, ops TEXT,
        PRIMARY KEY(a, b, bnum, cnum, vnum))""")
    odb.execute("DELETE FROM align WHERE a=? AND b=?", (ida, idb))

    rows = []
    for key in shared:
        w1, w2 = va[key], vb[key]
        sm = difflib.SequenceMatcher(None, w1, w2, autojunk=False)
        n_eq = sum(bl.size for bl in sm.get_matching_blocks())
        sim = n_eq / max(len(w1), len(w2), 1)
        rows.append((ida, idb, *key, n_eq, len(w1), len(w2),
                     round(sim, 4), encode_ops(w1, w2, sm)))
    odb.executemany("INSERT OR REPLACE INTO align VALUES (?,?,?,?,?,?,?,?,?,?)",
                    rows)
    odb.execute("CREATE INDEX IF NOT EXISTS idx_align ON align(bnum,cnum,vnum)")
    odb.commit()
    mean = sum(r[8] for r in rows) / len(rows)
    print(f"{len(rows)} verse pairs -> {out}  mean sim={mean:.3f}")
    # most divergent sample
    for r in sorted(rows, key=lambda x: x[8])[:5]:
        print(f"  {r[2]}:{r[3]}:{r[4]} sim={r[8]}  {r[9][:80]}")
    odb.close(); con.close()


if __name__ == "__main__":
    main()
