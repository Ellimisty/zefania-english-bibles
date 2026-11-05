"""Multi-translation linguistic graph engine.

Ingests a directory of Zefania XML Bible translations into a SQLite
database enforcing strict DRYness:

- a globally deduplicated token pool (each surface form exists once)
- translations stored as ordered paths (token sequences) through that pool
- Strong's Greek/Hebrew numbers as a shared semantic anchor layer
- structural divergence metrics between a reference translation and the rest

Usage:
    python build_graph.py ingest [--src .] [--db bible_graph.db]
    python build_graph.py metrics [--db bible_graph.db] [--ref KJV]
    python build_graph.py export <book> <chapter> <verse> [--out graph.json]
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SRC_DIR, "bible_graph.db")
TOKEN_RE = re.compile(r"\w+|[^\w\s]")

SCHEMA = """
CREATE TABLE IF NOT EXISTS translations (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE,
    filename TEXT,
    name TEXT,
    identifier TEXT
);
CREATE TABLE IF NOT EXISTS verses (
    id INTEGER PRIMARY KEY,
    bnumber INTEGER, cnumber INTEGER, vnumber INTEGER,
    bname TEXT, ref TEXT,
    UNIQUE(bnumber, cnumber, vnumber)
);
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY,
    text TEXT UNIQUE,
    lower TEXT,
    is_punct INTEGER
);
CREATE TABLE IF NOT EXISTS strongs (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE          -- e.g. 'G430', 'H7225'
);
CREATE TABLE IF NOT EXISTS verse_tokens (
    translation_id INTEGER,
    verse_id INTEGER,
    position INTEGER,
    token_id INTEGER,
    PRIMARY KEY (translation_id, verse_id, position)
);
CREATE TABLE IF NOT EXISTS token_strongs (
    translation_id INTEGER,
    verse_id INTEGER,
    position INTEGER,
    strong_id INTEGER,
    PRIMARY KEY (translation_id, verse_id, position, strong_id)
);
CREATE TABLE IF NOT EXISTS similarity (
    verse_id INTEGER,
    ref_translation_id INTEGER,
    translation_id INTEGER,
    shared_prefix INTEGER,
    jaccard REAL,
    PRIMARY KEY (verse_id, ref_translation_id, translation_id)
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_vt_token ON verse_tokens(token_id);
CREATE INDEX IF NOT EXISTS idx_vt_verse ON verse_tokens(verse_id);
CREATE INDEX IF NOT EXISTS idx_ts_strong ON token_strongs(strong_id);
"""


def safe_slug(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "", name).strip()
    return re.sub(r"\s+", "_", name) or "unknown"


def iter_text_runs(vers):
    """Yield (text, strongs_list) for text inside VERS, honoring <gr str=...>.

    Tokens inside an element carrying a `str` attribute inherit those
    Strong's numbers; .text and .tail are both processed so word order
    and inline markup are preserved.
    """
    yield vers.text or "", []
    for el in vers:
        strongs = (el.get("str") or "").split() if el.get("str") else []
        yield el.text or "", strongs
        yield el.tail or "", []


def parse_verse_tokens(vers):
    """Return [(token_text, [strong_codes, ...]), ...] in order."""
    out = []
    for text, strongs in iter_text_runs(vers):
        for tok in TOKEN_RE.findall(text):
            out.append((tok, strongs))
    return out


def book_lang(bnumber: int) -> str:
    return "H" if bnumber <= 39 else "G"


BOOK_NAMES = {
    1: "Genesis", 2: "Exodus", 3: "Leviticus", 4: "Numbers", 5: "Deuteronomy",
    6: "Joshua", 7: "Judges", 8: "Ruth", 9: "1 Samuel", 10: "2 Samuel",
    11: "1 Kings", 12: "2 Kings", 13: "1 Chronicles", 14: "2 Chronicles",
    15: "Ezra", 16: "Nehemiah", 17: "Esther", 18: "Job", 19: "Psalms",
    20: "Proverbs", 21: "Ecclesiastes", 22: "Song of Solomon", 23: "Isaiah",
    24: "Jeremiah", 25: "Lamentations", 26: "Ezekiel", 27: "Daniel",
    28: "Hosea", 29: "Joel", 30: "Amos", 31: "Obadiah", 32: "Jonah",
    33: "Micah", 34: "Nahum", 35: "Habakkuk", 36: "Zephaniah", 37: "Haggai",
    38: "Zechariah", 39: "Malachi", 40: "Matthew", 41: "Mark", 42: "Luke",
    43: "John", 44: "Acts", 45: "Romans", 46: "1 Corinthians",
    47: "2 Corinthians", 48: "Galatians", 49: "Ephesians", 50: "Philippians",
    51: "Colossians", 52: "1 Thessalonians", 53: "2 Thessalonians",
    54: "1 Timothy", 55: "2 Timothy", 56: "Titus", 57: "Philemon",
    58: "Hebrews", 59: "James", 60: "1 Peter", 61: "2 Peter", 62: "1 John",
    63: "2 John", 64: "3 John", 65: "Jude", 66: "Revelation",
}
BOOK_NUMBERS = {v.lower(): k for k, v in BOOK_NAMES.items()}


def ingest(src_dir, db_path):
    con = sqlite3.connect(db_path, timeout=300)
    con.executescript(SCHEMA)
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=OFF")
    token_ids = dict(cur.execute("SELECT text, id FROM tokens"))
    strong_ids = dict(cur.execute("SELECT code, id FROM strongs"))
    verse_ids = dict(cur.execute("SELECT ref, id FROM verses"))

    files = sorted(f for f in os.listdir(src_dir) if f.lower().endswith(".xml"))
    for fn in files:
        path = os.path.join(src_dir, fn)
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as e:
            print(f"{fn}: parse failed ({e})")
            continue
        books = root.findall("BIBLEBOOK") or root.findall(".//BIBLEBOOK")
        if not books:
            print(f"{fn}: no BIBLEBOOK elements, skipped")
            continue

        slug = safe_slug(os.path.splitext(fn)[0])
        cur.execute(
            "INSERT OR IGNORE INTO translations(slug, filename, name, identifier) VALUES (?,?,?,?)",
            (slug, fn, root.get("biblename", "").strip(),
             (root.findtext("./INFORMATION/identifier") or "").strip()),
        )
        tid = cur.execute("SELECT id FROM translations WHERE slug=?", (slug,)).fetchone()[0]

        new_tokens = {}
        new_strongs = {}
        new_verses = []
        vt_rows = []   # (ref, pos, token_text)
        ts_rows = []   # (ref, pos, strong_code)
        n_tokens = 0
        for book in books:
            bnum = int(book.get("bnumber", "0") or 0)
            bname = (book.get("bname") or "").strip()
            lang = book_lang(bnum)
            for ch in book.findall("CHAPTER"):
                cnum = int(ch.get("cnumber", "0") or 0)
                for vers in ch.findall("VERS"):
                    vnum = int(vers.get("vnumber", "0") or 0)
                    ref = f"{bnum}.{cnum}.{vnum}"
                    if ref not in verse_ids:
                        new_verses.append((bnum, cnum, vnum, bname, ref))
                        verse_ids[ref] = None
                    for pos, (tok, strongs) in enumerate(parse_verse_tokens(vers)):
                        vt_rows.append((ref, pos, tok))
                        if tok not in token_ids and tok not in new_tokens:
                            new_tokens[tok] = (tok, tok.lower(), 0 if re.match(r"\w", tok) else 1)
                        for s in strongs:
                            code = f"{lang}{s}"
                            ts_rows.append((ref, pos, code))
                            if code not in strong_ids and code not in new_strongs:
                                new_strongs[code] = (code,)
                        n_tokens += 1

        cur.executemany("INSERT OR IGNORE INTO tokens(text, lower, is_punct) VALUES (?,?,?)", list(new_tokens.values()))
        cur.executemany("INSERT OR IGNORE INTO strongs(code) VALUES (?)", list(new_strongs.values()))
        cur.executemany("INSERT OR IGNORE INTO verses(bnumber, cnumber, vnumber, bname, ref) VALUES (?,?,?,?,?)", new_verses)
        if new_tokens:
            token_ids.update(dict(cur.execute(
                f"SELECT text, id FROM tokens WHERE text IN ({','.join('?' * len(new_tokens))})",
                list(new_tokens))))
        if new_strongs:
            strong_ids.update(dict(cur.execute(
                f"SELECT code, id FROM strongs WHERE code IN ({','.join('?' * len(new_strongs))})",
                list(new_strongs))))
        verse_ids.update(dict(cur.execute("SELECT ref, id FROM verses")))

        cur.executemany(
            "INSERT OR IGNORE INTO verse_tokens VALUES (?,?,?,?)",
            [(tid, verse_ids[r], p, token_ids[t]) for r, p, t in vt_rows],
        )
        cur.executemany(
            "INSERT OR IGNORE INTO token_strongs VALUES (?,?,?,?)",
            [(tid, verse_ids[r], p, strong_ids[c]) for r, p, c in ts_rows],
        )
        con.commit()
        print(f"{fn}: {n_tokens} tokens ingested")
    cur.executescript(INDEXES)
    con.commit()
    con.close()


def get_tokens(con, tid, vid):
    return [
        r[0]
        for r in con.execute(
            "SELECT t.text FROM verse_tokens vt JOIN tokens t ON t.id=vt.token_id "
            "WHERE vt.translation_id=? AND vt.verse_id=? ORDER BY vt.position",
            (tid, vid),
        )
    ]


def metrics(db_path, ref_ident="KJV"):
    con = sqlite3.connect(db_path)
    ref = con.execute(
        "SELECT id FROM translations WHERE identifier=? OR slug LIKE ? "
        "ORDER BY CASE WHEN identifier=? THEN 0 ELSE 1 END, id LIMIT 1",
        (ref_ident, f"%{ref_ident}%", ref_ident),
    ).fetchone()
    if not ref:
        sys.exit(f"reference translation '{ref_ident}' not found")
    ref_id = ref[0]
    token_text = dict(con.execute("SELECT id, lower FROM tokens"))
    cur = con.cursor()
    verses = [r[0] for r in con.execute(
        "SELECT DISTINCT verse_id FROM verse_tokens WHERE translation_id=?", (ref_id,))]
    for i, vid in enumerate(verses):
        rows = con.execute(
            "SELECT vt.translation_id, vt.position, vt.token_id FROM verse_tokens vt "
            "WHERE vt.verse_id=? ORDER BY vt.translation_id, vt.position",
            (vid,),
        ).fetchall()
        by_tid = {}
        for tid, pos, tk in rows:
            by_tid.setdefault(tid, []).append(token_text[tk])
        ref_tokens = by_tid.get(ref_id)
        if not ref_tokens:
            continue
        ref_set = set(ref_tokens)
        for tid, toks in by_tid.items():
            if tid == ref_id:
                continue
            prefix = 0
            for a, b in zip(ref_tokens, toks):
                if a == b:
                    prefix += 1
                else:
                    break
            tset = set(toks)
            union = ref_set | tset
            j = len(ref_set & tset) / len(union) if union else 0.0
            cur.execute(
                "INSERT OR REPLACE INTO similarity VALUES (?,?,?,?,?)",
                (vid, ref_id, tid, prefix, round(j, 4)),
            )
        if i % 5000 == 0:
            con.commit()
            print(f"{i}/{len(verses)} verses", flush=True)
    con.commit()
    # summary
    print(f"{'translation':<60} {'mean_prefix':>11} {'mean_jaccard':>12}")
    for slug, mp, mj in con.execute(
        "SELECT tr.slug, AVG(s.shared_prefix), AVG(s.jaccard) FROM similarity s "
        "JOIN translations tr ON tr.id=s.translation_id "
        "WHERE s.ref_translation_id=? GROUP BY s.translation_id ORDER BY AVG(s.jaccard) DESC",
        (ref_id,),
    ):
        print(f"{slug:<60} {mp:>11.2f} {mj:>12.4f}")
    con.close()


def export_verse(db_path, book, chapter, verse, out_path, fmt="dag"):
    con = sqlite3.connect(db_path)
    if str(book).isdigit():
        bnum = int(book)
    else:
        bnum = BOOK_NUMBERS.get(str(book).lower())
        if bnum is None:
            # fuzzy fallback over canonical names and whatever bnames exist
            cands = {n.lower(): b for b, n in BOOK_NAMES.items()}
            cands.update(
                (n.lower(), b)
                for b, n in con.execute(
                    "SELECT DISTINCT bnumber, bname FROM verses WHERE bname != ''"
                )
            )
            bnum = next((b for n, b in cands.items() if str(book).lower() in n), None)
        if bnum is None:
            sys.exit(f"book '{book}' not found")
    row = con.execute(
        "SELECT id FROM verses WHERE bnumber=? AND cnumber=? AND vnumber=?",
        (bnum, chapter, verse),
    ).fetchone()
    if not row:
        sys.exit("verse not found")
    vid = row[0]
    nodes, rels, node_map = [], [], {}
    counters = {"n": 0, "e": 0}

    def node(caption, labels, x=0.0, y=0.0, properties=None):
        key = (caption, tuple(sorted(labels)))
        if key not in node_map:
            counters["n"] += 1
            nid = f"n{counters['n']}"
            node_map[key] = nid
            nodes.append({
                "id": nid,
                "position": {"x": x, "y": y},
                "caption": caption,
                "style": {},
                "labels": labels,
                "properties": properties or {},
            })
        return node_map[key]

    def edge(a, b, t, path_group=None, branch=None):
        # arrows.app relationship ids use the e0, e1, ... scheme so they can
        # never collide with node ids (n1, n2, ...). `pathGroup` identifies
        # which path/translation an edge belongs to ("CANON" for the shared
        # Book/Chapter/Verse hierarchy); `branch` ("left"/"right") marks the
        # two halves of a binary n-gram decomposition, as in export.rs.
        props = {}
        if branch is not None:
            props["branch"] = branch
        if path_group is not None:
            props["pathGroup"] = path_group
        rid = f"e{counters['e']}"
        counters["e"] += 1
        rels.append({
            "id": rid, "type": t, "style": {},
            "properties": props, "fromId": a, "toId": b,
        })

    bname, ref = con.execute("SELECT bname, ref FROM verses WHERE id=?", (vid,)).fetchone()
    bname = bname or BOOK_NAMES.get(bnum, f"Book {bnum}")
    book_n = node(bname, ["Book"], -600, -600)
    chap_n = node(str(chapter), ["Chapter"], -300, -600)
    vers_n = node(f"{bname} {chapter}:{verse}", ["Verse"], 0, -600)
    edge(book_n, chap_n, "HAS_CHAPTER", path_group="CANON")
    edge(chap_n, vers_n, "HAS_VERSE", path_group="CANON")

    NGRAM_SIZES = (2, 3)
    for row_i, (tid, slug) in enumerate(con.execute("SELECT id, slug FROM translations")):
        toks = con.execute(
            "SELECT vt.position, t.text FROM verse_tokens vt JOIN tokens t ON t.id=vt.token_id "
            "WHERE vt.translation_id=? AND vt.verse_id=? ORDER BY vt.position",
            (tid, vid),
        ).fetchall()
        if not toks:
            continue
        y = row_i * (500 if fmt == "dag" else 300)
        ver_n = node(slug, ["Translation"], -900, y)
        vtext_n = node(f"{slug}:{ref}", ["VerseText", slug], -600, y)
        edge(vers_n, vtext_n, "HAS_TEXT", path_group=slug)
        edge(vtext_n, ver_n, "TRANSLATED_BY", path_group=slug)

        # token layer (size-1 n-grams): layer_index = position in verse
        tok_nodes = {}
        text_at = {}
        prev = None
        for pos, text in toks:
            tok_n = node(text, ["Token"], pos * 160, y,
                         properties={"layer_index": pos, "size": 1} if fmt == "dag" else None)
            tok_nodes[pos] = tok_n
            text_at[pos] = text
            edge(vtext_n, tok_n, "CONTAINS_TOKEN", path_group=slug)
            if prev is not None:
                edge(prev, tok_n, f"NEXT:{slug}", path_group=slug)
            prev = tok_n
            for (code,) in con.execute(
                "SELECT s.code FROM token_strongs ts JOIN strongs s ON s.id=ts.strong_id "
                "WHERE ts.translation_id=? AND ts.verse_id=? AND ts.position=?",
                (tid, vid, pos),
            ):
                edge(tok_n,
                     node(code, ["Strongs", "Greek" if code.startswith("G") else "Hebrew"],
                          pos * 160, y - 200),
                     "TRANSLATES", path_group=slug)

        # n-gram layers for n=2..3 built from NON-OVERLAPPING adjacent
        # partitions of the token stream ("quick brown" + "fox jumps",
        # never sliding "quick brown" + "brown fox"), per export.rs.
        if fmt != "dag":
            continue
        positions = sorted(text_at)
        # text -> node id, seeded with unigrams so decompositions can
        # terminate at token nodes
        ngram_ids = {text_at[p]: tok_nodes[p] for p in positions}
        for size in NGRAM_SIZES:
            layer_y = y - 400 - (size - 2) * 200
            layer_idx = 0
            i = 0
            while i + size <= len(positions):
                span = positions[i:i + size]
                caption = " ".join(text_at[p] for p in span)
                x = (span[0] + span[-1]) * 80
                ng_n = node(caption, ["Ngram", slug], x, layer_y,
                            properties={"layer_index": layer_idx, "size": size})
                ngram_ids[caption] = ng_n
                # PART_OF from each constituent token
                for p in span:
                    edge(tok_nodes[p], ng_n, "PART_OF", path_group=slug)
                # all valid binary decompositions: split into (k)-gram +
                # (size-k)-gram for k in 1..size-1, connecting only when
                # both halves exist as nodes (Rust MERGE convention)
                for k in range(1, size):
                    left = " ".join(text_at[p] for p in span[:k])
                    right = " ".join(text_at[p] for p in span[k:])
                    if left in ngram_ids and right in ngram_ids:
                        edge(ngram_ids[left], ng_n, "MERGE",
                             path_group=slug, branch="left")
                        edge(ngram_ids[right], ng_n, "MERGE",
                             path_group=slug, branch="right")
                layer_idx += 1
                i += size

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "style": {
                "font-family": "sans-serif",
                "background-color": "#ffffff",
                "background-image": "",
                "background-size": "100%",
                "node-color": "#ffffff",
                "border-width": 4,
                "border-color": "#000000",
                "radius": 50,
                "node-padding": 5,
                "node-margin": 2,
                "outside-position": "auto",
                "node-icon-image": "",
                "node-background-image": "",
                "icon-position": "inside",
                "icon-size": 64,
                "caption-position": "inside",
                "caption-max-width": 200,
                "caption-color": "#000000",
                "caption-font-size": 50,
                "caption-font-weight": "normal",
                "label-position": "inside",
                "label-display": "pill",
                "label-color": "#000000",
                "label-background-color": "#ffffff",
                "label-border-color": "#000000",
                "label-border-width": 4,
                "label-font-size": 40,
                "label-padding": 5,
                "label-margin": 4,
                "directionality": "directed",
                "detail-position": "inline",
                "detail-orientation": "parallel",
                "arrow-width": 5,
                "arrow-color": "#000000",
                "margin-start": 5,
                "margin-end": 5,
                "margin-peer": 20,
                "attachment-start": "normal",
                "attachment-end": "normal",
                "relationship-icon-image": "",
                "type-color": "#000000",
                "type-background-color": "#ffffff",
                "type-border-color": "#000000",
                "type-border-width": 0,
                "type-font-size": 16,
                "type-padding": 5,
                "property-position": "outside",
                "property-alignment": "colon",
                "property-color": "#000000",
                "property-font-size": 16,
                "property-font-weight": "normal",
            },
            "nodes": nodes,
            "relationships": rels,
        }, f, indent=2)
    print(f"wrote {out_path}: {len(nodes)} nodes, {len(rels)} relationships")
    con.close()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest")
    p.add_argument("--src", default=SRC_DIR)
    p.add_argument("--db", default=DB_PATH)
    p = sub.add_parser("metrics")
    p.add_argument("--db", default=DB_PATH)
    p.add_argument("--ref", default="KJV")
    p = sub.add_parser("export")
    p.add_argument("book")
    p.add_argument("chapter", type=int)
    p.add_argument("verse", type=int)
    p.add_argument("--out", default="graph_export.json")
    p.add_argument("--format", choices=["dag", "simple"], default="dag",
                   help="dag: full layered export with n-gram/PART_OF/MERGE layers; "
                        "simple: original token-chain export only")
    p.add_argument("--db", default=DB_PATH)
    a = ap.parse_args()
    if a.cmd == "ingest":
        ingest(a.src, a.db)
    elif a.cmd == "metrics":
        metrics(a.db, a.ref)
    elif a.cmd == "export":
        export_verse(a.db, a.book, a.chapter, a.verse, a.out, a.format)


if __name__ == "__main__":
    main()
