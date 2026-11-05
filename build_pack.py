"""Build a DRY reader pack from Zefania XML files.

The whole pile of translations collapses into one shared token dictionary
plus deduplicated verse *sequences*: identical verse texts across
translations are stored once. Output is a small SQLite file so any reader
gets indexed random access (open any bible in the pile) with no custom
parser needed.

Schema:
  meta(key, value)
  translations(id, slug, name, identifier)
  dictionary(id, text)                      -- shared token pool, pack-local ids
  strongs_dict(id, code)                    -- e.g. 'G1401', 'H7225'
  sequences(id, n_tokens, tokens BLOB, spaces BLOB, strongs BLOB)
      tokens : varint-packed dictionary ids (token order)
      spaces : bitset, bit i = leading space before token i (bit0 always 0)
      strongs: per tagged position: varint(pos_delta), varint(strong_id)
  verses(translation_id, bnum, cnum, vnum, seq_id)

Usage:
  python build_pack.py [--src .] [--out bibles.pack]
"""

import argparse
import hashlib
import os
import re
import sqlite3
import xml.etree.ElementTree as ET

TOKEN_RE = re.compile(r"\w+|[^\w\s]")

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value);
CREATE TABLE translations(id INTEGER PRIMARY KEY, slug TEXT UNIQUE,
                          name TEXT, identifier TEXT);
CREATE TABLE dictionary(id INTEGER PRIMARY KEY, text TEXT UNIQUE);
CREATE TABLE strongs_dict(id INTEGER PRIMARY KEY, code TEXT UNIQUE);
CREATE TABLE sequences(id INTEGER PRIMARY KEY, n_tokens INT,
                       tokens BLOB, spaces BLOB, strongs BLOB);
CREATE TABLE verses(translation_id INT, bnum INT, cnum INT, vnum INT,
                    seq_id INT,
                    PRIMARY KEY(translation_id, bnum, cnum, vnum));
CREATE INDEX idx_verses_seq ON verses(seq_id);
CREATE INDEX idx_verses_book ON verses(translation_id, bnum, cnum);
"""


def safe_slug(name):
    name = re.sub(r'[<>:"/\\|?*]', "", name).strip()
    return re.sub(r"\s+", "_", name) or "unknown"


def putvarint(buf, n):
    while n > 0x7F:
        buf.append((n & 0x7F) | 0x80)
        n >>= 7
    buf.append(n)


def iter_runs(vers):
    """Yield (text, strongs) honoring <gr str=...>, same as build_graph."""
    yield vers.text or "", []
    for el in vers:
        strongs = (el.get("str") or "").split() if el.get("str") else []
        yield el.text or "", strongs
        yield el.tail or "", []


def verse_tokens(vers):
    """[(token, leading_space, [strong_nums])] in order.

    A token's leading space may live at the END of the previous text run
    (e.g. `a <gr>servant</gr>`), so carry a flag across run boundaries.
    """
    out = []
    prev_trailing_ws = False
    for text, strongs in iter_runs(vers):
        prev_end = 0
        first = True
        for m in TOKEN_RE.finditer(text):
            gap = text[prev_end:m.start()]
            lead = (first and prev_trailing_ws) or any(
                c in " \t\r\n" for c in gap)
            out.append((m.group(0), lead, strongs))
            prev_end = m.end()
            first = False
        if text:
            prev_trailing_ws = text[-1] in " \t\r\n"
    return out


def build(src_dir, out_path):
    if os.path.exists(out_path):
        os.remove(out_path)
    con = sqlite3.connect(out_path)
    con.executescript(SCHEMA)
    cur = con.cursor()

    dict_ids = {}          # text -> pack dictionary id
    strong_ids = {}        # code -> pack strongs_dict id
    seq_ids = {}           # sha1 -> sequence id
    next_dict = next_strong = next_seq = 1
    dict_rows, strong_rows, seq_rows, verse_rows = [], [], [], []

    def dict_id(text):
        nonlocal next_dict
        i = dict_ids.get(text)
        if i is None:
            i = next_dict; next_dict += 1
            dict_ids[text] = i
            dict_rows.append((i, text))
        return i

    def strong_id(code):
        nonlocal next_strong
        i = strong_ids.get(code)
        if i is None:
            i = next_strong; next_strong += 1
            strong_ids[code] = i
            strong_rows.append((i, code))
        return i

    files = sorted(f for f in os.listdir(src_dir) if f.lower().endswith(".xml"))
    for fn in files:
        try:
            root = ET.parse(os.path.join(src_dir, fn)).getroot()
        except ET.ParseError as e:
            print(f"{fn}: parse failed ({e})"); continue
        books = root.findall("BIBLEBOOK") or root.findall(".//BIBLEBOOK")
        if not books:
            print(f"{fn}: no BIBLEBOOK elements, skipped"); continue

        slug = safe_slug(os.path.splitext(fn)[0])
        cur.execute(
            "INSERT OR IGNORE INTO translations(slug, name, identifier) VALUES (?,?,?)",
            (slug, root.get("biblename", "").strip(),
             (root.findtext("./INFORMATION/identifier") or "").strip()))
        tid = cur.execute("SELECT id FROM translations WHERE slug=?", (slug,)).fetchone()[0]

        n_verses = n_seq_new = 0
        for book in books:
            bnum = int(book.get("bnumber", "0") or 0)
            lang = "H" if bnum <= 39 else "G"
            for ch in book.findall("CHAPTER"):
                cnum = int(ch.get("cnumber", "0") or 0)
                for vers in ch.findall("VERS"):
                    vnum = int(vers.get("vnumber", "0") or 0)
                    toks = verse_tokens(vers)
                    if not toks:
                        continue
                    tb = bytearray(); sb = bytearray()
                    bits = 0; sbuf = bytearray()
                    last_pos = 0
                    for i, (text, lead, strongs) in enumerate(toks):
                        putvarint(tb, dict_id(text))
                        if lead and i > 0:
                            bits |= 1 << (i % 8)
                        if i % 8 == 7:
                            sb.append(bits); bits = 0
                        for s in strongs:
                            putvarint(sbuf, i - last_pos)
                            putvarint(sbuf, strong_id(f"{lang}{s}"))
                            last_pos = i
                    if len(toks) % 8:
                        sb.append(bits)
                    h = hashlib.sha1(bytes(tb) + b"|" + bytes(sb) + b"|" + bytes(sbuf)).digest()
                    sid_ = seq_ids.get(h)
                    if sid_ is None:
                        sid_ = next_seq; next_seq += 1
                        seq_ids[h] = sid_
                        seq_rows.append((sid_, len(toks), bytes(tb), bytes(sb), bytes(sbuf)))
                        n_seq_new += 1
                    verse_rows.append((tid, bnum, cnum, vnum, sid_))
                    n_verses += 1
        print(f"{fn}: {n_verses} verses, {n_seq_new} new sequences")

    print("writing...")
    cur.executemany("INSERT INTO dictionary VALUES (?,?)", dict_rows)
    cur.executemany("INSERT INTO strongs_dict VALUES (?,?)", strong_rows)
    cur.executemany("INSERT INTO sequences VALUES (?,?,?,?,?)", seq_rows)
    cur.executemany("INSERT OR REPLACE INTO verses VALUES (?,?,?,?,?)", verse_rows)
    cur.execute("INSERT INTO meta VALUES ('format','bibles.pack.v1')")
    con.commit()
    # stats
    for t in ("translations", "dictionary", "sequences", "verses", "strongs_dict"):
        print(t, cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
    con.execute("VACUUM")
    con.close()
    print(f"pack size: {os.path.getsize(out_path)/1e6:.1f} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--out", default="bibles.pack")
    args = ap.parse_args()
    build(args.src, args.out)
