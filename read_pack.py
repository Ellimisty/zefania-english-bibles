"""Minimal reader for bibles.pack — proves a reader can open any bible.

Usage:
  python read_pack.py list                          # list translations
  python read_pack.py read KJV James 1 1            # one verse
  python read_pack.py read KJV James 1              # whole chapter
  python read_pack.py read KJV James 1 --strongs    # with strong's codes
"""

import argparse
import lzma
import os
import sqlite3
import sys
import tempfile

BOOK_NAMES = {
    "genesis":1,"exodus":2,"leviticus":3,"numbers":4,"deuteronomy":5,
    "joshua":6,"judges":7,"ruth":8,"1 samuel":9,"2 samuel":10,"1 kings":11,
    "2 kings":12,"1 chronicles":13,"2 chronicles":14,"ezra":15,"nehemiah":16,
    "esther":17,"job":18,"psalms":19,"proverbs":20,"ecclesiastes":21,
    "song of solomon":22,"isaiah":23,"jeremiah":24,"lamentations":25,
    "ezekiel":26,"daniel":27,"hosea":28,"joel":29,"amos":30,"obadiah":31,
    "jonah":32,"micah":33,"nahum":34,"habakkuk":35,"zephaniah":36,"haggai":37,
    "zechariah":38,"malachi":39,"matthew":40,"mark":41,"luke":42,"john":43,
    "acts":44,"romans":45,"1 corinthians":46,"2 corinthians":47,"galatians":48,
    "ephesians":49,"philippians":50,"colossians":51,"1 thessalonians":52,
    "2 thessalonians":53,"1 timothy":54,"2 timothy":55,"titus":56,"philemon":57,
    "hebrews":58,"james":59,"1 peter":60,"2 peter":61,"1 john":62,"2 john":63,
    "3 john":64,"jude":65,"revelation":66,
}


def varints(buf):
    n = 0; shift = 0
    for b in buf:
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            yield n
            n = 0; shift = 0
        else:
            shift += 7


def decode_sequence(con, seq_row):
    sid, n, tokens_b, spaces_b, strongs_b, seq_id = seq_row
    ids = list(varints(tokens_b))
    texts = [r[0] for r in con.execute(
        f"SELECT text FROM dictionary WHERE id IN ({','.join('?' * len(ids))})",
        ids)] if ids else []
    # ids come back unordered — map properly
    rows = dict(con.execute(
        f"SELECT id, text FROM dictionary WHERE id IN ({','.join('?' * len(ids))})",
        ids))
    texts = [rows[i] for i in ids]
    # spaces bitset
    out = []
    for i, t in enumerate(texts):
        if i > 0 and (spaces_b[i // 8] >> (i % 8)) & 1:
            out.append(" ")
        out.append(t)
    text = "".join(out)
    # strongs
    tags = {}
    last = 0
    it = iter(varints(strongs_b))
    for delta, s in zip(it, it):
        last += delta
        tags.setdefault(last, []).append(s)
    return text, tags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "read"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--pack", default="bibles.pack")
    ap.add_argument("--strongs", action="store_true")
    a = ap.parse_args()

    pack = a.pack
    tmp = None
    if pack.endswith(".xz"):
        # decompress once to a temp file (~2s for the full pack)
        tmp = tempfile.NamedTemporaryFile(suffix=".pack", delete=False)
        tmp.close()
        with lzma.open(pack, "rb") as f_in, open(tmp.name, "wb") as f_out:
            while chunk := f_in.read(1 << 22):
                f_out.write(chunk)
        pack = tmp.name
    con = sqlite3.connect(pack)

    if a.cmd == "list":
        for r in con.execute(
            "SELECT t.identifier, t.name, COUNT(v.vnum) FROM translations t "
            "LEFT JOIN verses v ON v.translation_id=t.id "
            "GROUP BY t.id ORDER BY t.id"):
            print(f"{r[0] or '?':<12} {r[1]:<55} {r[2]} verses")
        return

    # read <slug> <book...> <chapter> [verse]
    parts = list(a.args[1:])
    vnum = int(parts.pop()) if parts and parts[-1].isdigit() and len(parts) >= 2 else None
    cnum = int(parts.pop()) if parts and parts[-1].isdigit() else None
    if cnum is None:
        sys.exit("usage: read <slug> <book> <chapter> [verse]")
    book = " ".join(parts)
    bnum = BOOK_NAMES.get(book.lower()) or (int(book) if book.isdigit() else None)
    if bnum is None:
        sys.exit(f"unknown book '{book}'")
    tid = con.execute(
        "SELECT id FROM translations WHERE slug LIKE ? OR identifier=? LIMIT 1",
        (f"%{a.args[0]}%", a.args[0])).fetchone()
    if not tid:
        sys.exit("translation not found")
    tid = tid[0]

    q = ("SELECT v.vnum, s.id, s.n_tokens, s.tokens, s.spaces, s.strongs "
         "FROM verses v JOIN sequences s ON s.id=v.seq_id "
         "WHERE v.translation_id=? AND v.bnum=? AND v.cnum=?")
    p = [tid, bnum, cnum]
    if vnum is not None:
        q += " AND v.vnum=?"; p.append(vnum)
    rows = con.execute(q + " ORDER BY v.vnum", p).fetchall()
    if not rows:
        sys.exit("no verses found")
    strong_names = dict(con.execute("SELECT id, code FROM strongs_dict"))
    for vnum_, sid_, n_, tb, sb, stb in rows:
        text, tags = decode_sequence(con, (sid_, n_, tb, sb, stb, sid_))
        print(f"{vnum_} {text}")
        if a.strongs and tags:
            for pos, codes in sorted(tags.items()):
                toks = text.split()
                word = toks[pos] if pos < len(toks) else "?"
                print(f"    [{pos}] {word} -> {', '.join(strong_names.get(c, str(c)) for c in codes)}")

    if tmp:
        con.close()
        os.unlink(tmp.name)


if __name__ == "__main__":
    main()
