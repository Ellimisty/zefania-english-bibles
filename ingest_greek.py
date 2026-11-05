"""
ingest_greek.py -- Build the Greek "truth layer" for bible_graph.db.

Populates a NEW table `greek_words` with morphologically-tagged Greek NT
words from the MorphGNT SBLGNT dataset (https://github.com/morphgnt/sblgnt),
anchored to the existing shared `strongs` table via the lemma->Strong's
mapping in morphgnt's morphological-lexicon `lexemes.yaml`.

Existing tables are NOT altered.

Data sources (vendored, gitignored):
  zachconc/vendor/sblgnt_morphgnt/   git clone of github.com/morphgnt/sblgnt
  zachconc/vendor/lexemes.yaml       raw file from github.com/morphgnt/morphological-lexicon

morphgnt file format (one word per line, space-separated, 7 fields):
  bbccvv POS PARSE TEXT WORD NORMALIZED LEMMA
  e.g. "010101 N- ----NSF- Biblos Biblos biblos biblos"

File names 61-Mt .. 87-Re encode NT book order 1..27 -> bnumber 40..66.
"""

import os
import re
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "bible_graph.db")
MORPHGNT_DIR = os.path.join(HERE, "zachconc", "vendor", "sblgnt_morphgnt")
LEXEMES = os.path.join(HERE, "zachconc", "vendor", "lexemes.yaml")

# morphgnt file index 61..87 -> NT book order 1..27 -> bnumber 40..66
# (Mt=61 -> 40 ... Jas=80 -> 59 ... Re=87 -> 66)


def load_lemma_strongs(path):
    """Parse lexemes.yaml -> {lemma: strongs_int} without a YAML lib."""
    mapping = {}
    lemma = None
    for line in open(path, encoding="utf-8"):
        if line and not line[0].isspace():
            m = re.match(r"^(.+):\s*$", line.rstrip("\n"))
            lemma = m.group(1).strip() if m else None
        elif lemma and line.lstrip().startswith("strongs:"):
            val = line.split(":", 1)[1].strip()
            if val.isdigit():
                mapping[lemma] = int(val)
    return mapping


def norm_strongs_code(n):
    """Raw strongs int -> existing-code style 'G1401' (no leading zeros)."""
    return "G%d" % n


def main():
    if not os.path.isdir(MORPHGNT_DIR):
        sys.exit("Missing %s -- run: git clone --depth 1 "
                 "https://github.com/morphgnt/sblgnt zachconc/vendor/sblgnt_morphgnt"
                 % MORPHGNT_DIR)
    if not os.path.isfile(LEXEMES):
        sys.exit("Missing %s -- fetch lexemes.yaml from "
                 "github.com/morphgnt/morphological-lexicon" % LEXEMES)

    lemma2strong = load_lemma_strongs(LEXEMES)
    print("lemmas with Strong's:", len(lemma2strong))

    con = sqlite3.connect(DB)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS greek_words (
            translation_id INTEGER,      -- always NULL: Greek layer is translation-agnostic
            bnumber INTEGER,
            cnumber INTEGER,
            vnumber INTEGER,
            position INTEGER,
            surface TEXT,
            lemma TEXT,
            strong_id INTEGER REFERENCES strongs(id),
            parsing TEXT
        )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_greek_words_bcv "
                "ON greek_words(bnumber, cnumber, vnumber)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_greek_words_strong "
                "ON greek_words(strong_id)")
    cur.execute("DELETE FROM greek_words")  # idempotent re-runs
    con.commit()

    existing = {code: sid for sid, code in
                cur.execute("SELECT id, code FROM strongs")}
    new_codes = set()
    unmapped_lemmas = set()
    batch, total = [], 0

    files = sorted(f for f in os.listdir(MORPHGNT_DIR)
                   if f.endswith("-morphgnt.txt"))
    for fname in files:
        file_idx = int(fname.split("-")[0])
        bnumber = file_idx - 21  # 61->40 ... 87->66
        with open(os.path.join(MORPHGNT_DIR, fname), encoding="utf-8") as fh:
            pos_by_verse = {}
            for line in fh:
                parts = line.split()
                if len(parts) < 7:
                    continue
                ref, pos, parse, text, word, norm, lemma = parts[:7]
                cnum, vnum = int(ref[2:4]), int(ref[4:6])
                key = (cnum, vnum)
                pos_by_verse[key] = pos_by_verse.get(key, 0) + 1
                position = pos_by_verse[key]

                strong_id = None
                snum = lemma2strong.get(lemma)
                if snum is not None:
                    code = norm_strongs_code(snum)
                    sid = existing.get(code)
                    if sid is None:
                        new_codes.add(code)
                        existing[code] = sid = -len(new_codes)  # temp id
                    strong_id = sid
                else:
                    unmapped_lemmas.add(lemma)

                batch.append((None, bnumber, cnum, vnum, position,
                              text, lemma, strong_id,
                              pos + " " + parse))
                total += 1

        if len(batch) > 20000:
            cur.executemany(
                "INSERT INTO greek_words VALUES (?,?,?,?,?,?,?,?,?)", batch)
            con.commit()
            batch.clear()

    if batch:
        cur.executemany(
            "INSERT INTO greek_words VALUES (?,?,?,?,?,?,?,?,?)", batch)
        batch.clear()
    con.commit()

    # Insert genuinely new Strong's codes, then swap negative placeholder ids
    # for the real strongs.id values.
    for code in sorted(new_codes):
        cur.execute("INSERT OR IGNORE INTO strongs(code) VALUES (?)", (code,))
    con.commit()
    real = {code: sid for sid, code in
            cur.execute("SELECT id, code FROM strongs")}
    for code, tmp in existing.items():
        if isinstance(tmp, int) and tmp < 0:
            cur.execute(
                "UPDATE greek_words SET strong_id=? WHERE strong_id=?",
                (real[code], tmp))
    con.commit()

    # ---- sanity checks ----
    n = cur.execute("SELECT COUNT(*) FROM greek_words").fetchone()[0]
    print("total greek_words rows:", n)
    print("new strongs codes added:", len(new_codes))
    print("lemmas w/o Strong's mapping:", len(unmapped_lemmas))

    print("\nJames 1:1 (bnumber=59):")
    for r in cur.execute("""
        SELECT w.position, w.surface, w.lemma, s.code, w.parsing
        FROM greek_words w LEFT JOIN strongs s ON s.id = w.strong_id
        WHERE w.bnumber=59 AND w.cnumber=1 AND w.vnumber=1
        ORDER BY w.position"""):
        print("  %2d %-15s lemma=%-15s %s %s" % r)

    linked = cur.execute("""
        SELECT COUNT(DISTINCT s.code) FROM greek_words w
        JOIN strongs s ON s.id = w.strong_id
        WHERE w.strong_id IS NOT NULL""").fetchone()[0]
    unmapped_rows = cur.execute(
        "SELECT COUNT(*) FROM greek_words WHERE strong_id IS NULL").fetchone()[0]
    print("\ndistinct strongs codes linked from greek_words:", linked)
    print("rows with NULL strong_id:", unmapped_rows)
    con.close()


if __name__ == "__main__":
    main()
