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
                       [--translations KJV,WEB,...] [--list]
                       [--base existing.pack] [--estimate]

--translations takes comma-separated substrings matched case-insensitively
against the translation slug, identifier, and name — e.g. --translations kjv
builds a pack with every KJV-family module (KJV, KJVAK, KJ2000, MKJV1962,
RKJVNT, KJVCNT, BIBLE.AKJV, KJVPCE). Because verse sequences are deduplicated
globally, family packs stay tiny.

--base merges new translations into an existing pack: the base pack's
dictionary, sequences, and verses are carried over untouched, and only the
requested translations are parsed. Per-file output shows the marginal cost
(new sequences / dictionary words / Strong's codes / ~MB). --estimate does
the same analysis without writing a pack.
"""

import argparse
import hashlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
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
CREATE TABLE strongs_dict(id INTEGER PRIMARY KEY, code TEXT UNIQUE,
                          lemma TEXT, gloss TEXT);
CREATE TABLE strong_words(strong_id INT, dict_id INT,
                          PRIMARY KEY(strong_id, dict_id));
CREATE TABLE sequences(id INTEGER PRIMARY KEY, n_tokens INT,
                       tokens BLOB, spaces BLOB, strongs BLOB,
                       sha BLOB UNIQUE);
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


def getvarints(buf):
    n = shift = 0
    for b in buf:
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            yield n
            n = shift = 0
        else:
            shift += 7


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


def seq_hash(tb, sb, stb):
    return hashlib.sha1(bytes(tb) + b"|" + bytes(sb) + b"|" + bytes(stb)).digest()


LEXEMES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "zachconc", "vendor", "lexemes.yaml")
HEBREW_STRONG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "zachconc", "vendor", "HebrewLexicon",
                             "HebrewStrong.xml")

_NS = "{http://openscriptures.github.com/morphhb/namespace}"


def load_hebrew_info(path=HEBREW_STRONG):
    """Parse HebrewStrong.xml -> {strongs_int: (hebrew_word, gloss)}."""
    info = {}
    if not os.path.isfile(path):
        return info
    root = ET.parse(path).getroot()
    for entry in root.iter(f"{_NS}entry"):
        sid = entry.get("id", "")
        if not (sid[:1] == "H" and sid[1:].isdigit()):
            continue
        w = entry.find(f"{_NS}w")
        lemma = (w.text or "").strip() if w is not None else None
        defs = [d.text.strip() for d in entry.iter(f"{_NS}def") if d.text]
        gloss = "; ".join(defs[:3]) if defs else None
        info[int(sid[1:])] = (lemma, gloss)
    return info


def load_strong_info(path=LEXEMES):
    """Parse lexemes.yaml -> {strongs_int: (lemma, gloss)} — same hand
    parser style as ingest_greek.py, inverted and gloss-aware."""
    info = {}
    lemma = strongs = gloss = None
    if not os.path.isfile(path):
        return info
    def flush():
        if isinstance(strongs, int):
            info[strongs] = (lemma, gloss)
    for line in open(path, encoding="utf-8"):
        if line and not line[0].isspace():
            flush()
            lemma = strongs = gloss = None
            m = re.match(r"^(.+):\s*$", line.rstrip("\n"))
            lemma = m.group(1).strip() if m else None
        elif lemma:
            ls = line.lstrip()
            if ls.startswith("strongs:"):
                val = ls.split(":", 1)[1].strip()
                strongs = int(val) if val.isdigit() else None
            elif ls.startswith("gloss:"):
                gloss = ls.split(":", 1)[1].strip()
    flush()
    return info


def load_base(base_path, dict_ids, strong_ids, seq_ids):
    """Prefill dedup maps from an existing pack. Returns (max_dict_id,
    max_strong_id, max_seq_id, n_verses)."""
    bcon = sqlite3.connect(base_path)
    max_dict = bcon.execute("SELECT COALESCE(MAX(id),0) FROM dictionary").fetchone()[0]
    for i, t in bcon.execute("SELECT id, text FROM dictionary"):
        dict_ids[t] = i
    max_strong = bcon.execute("SELECT COALESCE(MAX(id),0) FROM strongs_dict").fetchone()[0]
    for i, c in bcon.execute("SELECT id, code FROM strongs_dict"):
        strong_ids[c] = i
    max_seq = bcon.execute("SELECT COALESCE(MAX(id),0) FROM sequences").fetchone()[0]
    cols = {r[1] for r in bcon.execute("PRAGMA table_info(sequences)")}
    if "sha" in cols:
        for sid_, sha in bcon.execute("SELECT id, sha FROM sequences"):
            seq_ids[sha] = sid_
    else:  # legacy pack without stored hashes — recompute
        for sid_, tb, sb, stb in bcon.execute(
                "SELECT id, tokens, spaces, strongs FROM sequences"):
            seq_ids[seq_hash(tb, sb, stb)] = sid_
    n_verses = bcon.execute("SELECT COUNT(*) FROM verses").fetchone()[0]
    bcon.close()
    return max_dict, max_strong, max_seq, n_verses


def parse_file(args):
    """Worker: parse one XML into (slug, biblename, ident, verses) or
    (None..., error_string). verses = [(bnum, cnum, vnum, lang, toks)]."""
    fn, src_dir = args
    try:
        root = ET.parse(os.path.join(src_dir, fn)).getroot()
    except ET.ParseError as e:
        return fn, None, None, None, f"parse failed ({e})"
    books = root.findall("BIBLEBOOK") or root.findall(".//BIBLEBOOK")
    if not books:
        return fn, None, None, None, "no BIBLEBOOK elements, skipped"
    slug = safe_slug(os.path.splitext(fn)[0])
    biblename = root.get("biblename", "").strip()
    ident = (root.findtext("./INFORMATION/identifier") or "").strip()
    verses = []
    for book in books:
        bnum = int(book.get("bnumber", "0") or 0)
        lang = "H" if bnum <= 39 else "G"
        for ch in book.findall("CHAPTER"):
            cnum = int(ch.get("cnumber", "0") or 0)
            for vers in ch.findall("VERS"):
                vnum = int(vers.get("vnumber", "0") or 0)
                toks = verse_tokens(vers)
                if toks:
                    verses.append((bnum, cnum, vnum, lang, toks))
    return fn, slug, biblename, ident, verses


def build(src_dir, out_path, only=None, base=None, estimate=False):
    dict_ids = {}          # text -> pack dictionary id
    strong_ids = {}        # code -> pack strongs_dict id
    seq_ids = {}           # sha1 -> sequence id
    next_dict = next_strong = next_seq = 1
    dict_rows, strong_rows, seq_rows, verse_rows = [], [], [], []
    sw_pairs = set()           # (strong_id, dict_id) -> strong_words table
    base_bytes = 0

    if base:
        print(f"loading base pack {base}...")
        md, ms, mq, base_verses = load_base(base, dict_ids, strong_ids, seq_ids)
        next_dict, next_strong, next_seq = md + 1, ms + 1, mq + 1
        base_bytes = os.path.getsize(base)
        print(f"base: {base_verses} verses carried over")
        # recover strong->word pairs from base sequences (ids are preserved)
        bcon = sqlite3.connect(base)
        for tb, stb in bcon.execute("SELECT tokens, strongs FROM sequences"):
            ids = list(getvarints(tb))
            pos = 0
            it = iter(getvarints(stb))
            for delta, sid_ in zip(it, it):
                pos += delta
                if pos < len(ids):
                    sw_pairs.add((sid_, ids[pos]))
        bcon.close()

    con = None
    cur = None
    if not estimate:
        if os.path.exists(out_path):
            os.remove(out_path)
        con = sqlite3.connect(out_path)
        con.executescript(SCHEMA)
        if base:
            base_esc = base.replace("'", "''")
            con.execute(f"ATTACH DATABASE '{base_esc}' AS base")
            # explicit columns: base may predate the lemma/gloss columns
            for t, cols in (
                ("translations", "id, slug, name, identifier"),
                ("dictionary", "id, text"),
                ("strongs_dict", "id, code"),
                ("sequences", "id, n_tokens, tokens, spaces, strongs"),
                ("verses", "translation_id, bnum, cnum, vnum, seq_id"),
                ("meta", "key, value"),
            ):
                con.execute(f"INSERT INTO {t} ({cols}) SELECT {cols} FROM base.{t}")
        cur = con.cursor()

    def dict_id(text):
        nonlocal next_dict
        i = dict_ids.get(text)
        if i is None:
            i = next_dict; next_dict += 1
            dict_ids[text] = i
            dict_rows.append((i, text))
        return i

    strong_info = load_strong_info()
    if strong_info:
        print(f"loaded {len(strong_info)} strong->lemma entries from lexemes.yaml")
    hebrew_info = load_hebrew_info()
    if hebrew_info:
        print(f"loaded {len(hebrew_info)} strong->hebrew entries from HebrewStrong.xml")

    def strong_id(code):
        nonlocal next_strong
        i = strong_ids.get(code)
        if i is None:
            i = next_strong; next_strong += 1
            strong_ids[code] = i
            lemma = gloss = None
            if code[:1] in "GH" and code[1:].isdigit():
                src = strong_info if code[0] == "G" else hebrew_info
                lemma, gloss = src.get(int(code[1:]), (None, None))
            strong_rows.append((i, code, lemma, gloss))
        return i

    n_files_verses = 0
    files = sorted(f for f in os.listdir(src_dir) if f.lower().endswith(".xml"))
    # parse in worker processes; dedup/encode stays single-threaded
    if len(files) > 1:
        import multiprocessing
        pool = multiprocessing.Pool()
        results = pool.imap(parse_file, ((f, src_dir) for f in files), chunksize=1)
    else:
        pool = None
        results = map(parse_file, ((f, src_dir) for f in files))
    for fn, slug, biblename, ident, parsed in results:
        if not isinstance(parsed, list):
            print(f"{fn}: {parsed}"); continue
        if only is not None:
            hay = f"{slug} {ident} {biblename}".lower()
            if not any(p in hay for p in only):
                continue
        if cur is not None:
            cur.execute(
                "INSERT OR IGNORE INTO translations(slug, name, identifier) VALUES (?,?,?)",
                (slug, biblename, ident))
            tid = cur.execute("SELECT id FROM translations WHERE slug=?", (slug,)).fetchone()[0]
        else:
            tid = -1

        n_verses = n_seq_new = n_bytes = 0
        d0, s0 = len(dict_rows), len(strong_rows)
        for bnum, cnum, vnum, lang, toks in parsed:
            tb = bytearray(); sb = bytearray()
            bits = 0; sbuf = bytearray()
            last_pos = 0
            for i, (text, lead, strongs) in enumerate(toks):
                did = dict_id(text)
                putvarint(tb, did)
                if lead and i > 0:
                    bits |= 1 << (i % 8)
                if i % 8 == 7:
                    sb.append(bits); bits = 0
                for s in strongs:
                    putvarint(sbuf, i - last_pos)
                    swid = strong_id(f"{lang}{s}")
                    putvarint(sbuf, swid)
                    sw_pairs.add((swid, did))
                    last_pos = i
            if len(toks) % 8:
                sb.append(bits)
            h = seq_hash(tb, sb, sbuf)
            sid_ = seq_ids.get(h)
            if sid_ is None:
                sid_ = next_seq; next_seq += 1
                seq_ids[h] = sid_
                seq_rows.append((sid_, len(toks), bytes(tb), bytes(sb),
                                 bytes(sbuf), h))
                n_seq_new += 1
                n_bytes += len(tb) + len(sb) + len(sbuf)
            if cur is not None:
                verse_rows.append((tid, bnum, cnum, vnum, sid_))
            n_verses += 1
            n_files_verses += 1
        print(f"{fn}: {n_verses} verses, {n_seq_new} new seqs "
              f"(+{len(dict_rows) - d0} dict, +{len(strong_rows) - s0} strongs, "
              f"~{n_bytes / 1e6:.2f} MB seq data)", flush=True)

    new_dict_bytes = sum(len(t) + 8 for _, t in dict_rows)
    new_strong_bytes = sum(len(r[1]) + 8 for r in strong_rows)
    new_seq_bytes = sum(len(r[2]) + len(r[3]) + len(r[4]) + 40 for r in seq_rows)
    verse_bytes = (len(verse_rows) if verse_rows else n_files_verses) * 28
    est_added = (new_dict_bytes + new_strong_bytes + new_seq_bytes + verse_bytes) * 1.15

    if estimate:
        print("\n-- estimate only, no pack written --")
        print(f"new content: {len(seq_rows)} sequences, {len(dict_rows)} dict words, "
              f"{len(strong_rows)} strongs, {n_files_verses} verse refs")
        print(f"estimated added size: ~{est_added / 1e6:.1f} MB"
              + (f" (base {base_bytes / 1e6:.1f} MB -> ~{(base_bytes + est_added) / 1e6:.1f} MB total)"
                 if base else ""))
        return

    print("writing...")
    cur.executemany("INSERT INTO dictionary VALUES (?,?)", dict_rows)
    cur.executemany("INSERT INTO strongs_dict VALUES (?,?,?,?)", strong_rows)
    cur.executemany("INSERT INTO sequences VALUES (?,?,?,?,?,?)", seq_rows)
    cur.executemany("INSERT OR IGNORE INTO strong_words VALUES (?,?)",
                    sorted(sw_pairs))
    cur.executemany("INSERT OR REPLACE INTO verses VALUES (?,?,?,?,?)", verse_rows)
    cur.execute("INSERT OR REPLACE INTO meta VALUES ('format','bibles.pack.v1')")
    con.commit()
    # stats
    for t in ("translations", "dictionary", "sequences", "verses",
              "strongs_dict", "strong_words"):
        print(t, cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
    con.execute("VACUUM")
    con.close()
    print(f"pack size: {os.path.getsize(out_path)/1e6:.1f} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--out", default="bibles.pack")
    ap.add_argument("--translations", default=None,
                    help="comma-separated substrings to include "
                         "(slug/identifier/name), e.g. KJV,WEB")
    ap.add_argument("--base", default=None,
                    help="existing .pack to extend — carries over its "
                         "dictionary/sequences/verses and adds only the "
                         "requested translations")
    ap.add_argument("--estimate", action="store_true",
                    help="report marginal cost per translation without "
                         "writing a pack")
    ap.add_argument("--list", action="store_true",
                    help="list available translation identifiers and exit")
    args = ap.parse_args()

    if args.list:
        # identifiers live in each XML's INFORMATION block; scan cheaply
        for fn in sorted(os.listdir(args.src)):
            if not fn.lower().endswith(".xml"):
                continue
            try:
                root = ET.parse(os.path.join(args.src, fn)).getroot()
            except ET.ParseError:
                continue
            ident = (root.findtext("./INFORMATION/identifier") or "").strip()
            name = root.get("biblename", "").strip()
            if root.findall("BIBLEBOOK") or root.findall(".//BIBLEBOOK"):
                print(f"{ident or safe_slug(os.path.splitext(fn)[0]):24} {name}")
        raise SystemExit

    only = None
    if args.translations:
        only = [p.strip().lower() for p in args.translations.split(",") if p.strip()]
    if args.base and not only:
        print("note: --base without --translations reprocesses every source file "
              "(idempotent, but slow). Pass --translations to add specific ones.")
    build(args.src, args.out, only=only, base=args.base, estimate=args.estimate)
