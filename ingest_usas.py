"""USAS semantic tagging for pack translations -> <pack>.usas.db

Looks up each token's lemma in book/lexicons/usas_single.tsv
(lemma + POS -> semantic tags). Positions line up with pack tokens so
the layer joins cleanly with pos_tags / metrics.

Lemmatizer: exact lowercase match, then irregulars map, then suffix
stripping (s/es/ed/en/ing/ly/er/est/'s). Coverage on Bible English is
high; unmatched words are left untagged (stored NULL rows? no — skipped).

Usage: python ingest_usas.py --pack bibles-kjv.pack --translation KJV
"""

import argparse
import csv
import os
import sqlite3
import sys

LEX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "book", "lexicons")

IRREG = {
    "was":"be","were":"be","been":"be","is":"be","are":"be","am":"be",
    "has":"have","had":"have","does":"do","did":"do","done":"do",
    "went":"go","gone":"go","saw":"see","seen":"see","knew":"know",
    "known":"know","gave":"give","given":"give","took":"take",
    "taken":"take","came":"come","made":"make","found":"find",
    "thought":"think","told":"tell","said":"say","begat":"beget",
    "begot":"beget","died":"die","arose":"arise","fell":"fall",
    "stood":"stand","wrote":"write","written":"write","spoke":"speak",
    "spoken":"speak","broke":"break","broken":"break","chose":"choose",
    "chosen":"choose","drove":"drive","ate":"eat","eaten":"eat",
    "drank":"drink","drunk":"drink","sang":"sing","sung":"sing",
    "swore":"swear","sworn":"swear","swam":"swim","swum":"swim",
    "began":"begin","begun":"begin","ran":"run","won":"win",
    "sat":"sit","shot":"shoot","sold":"sell","held":"hold",
    "left":"leave","kept":"keep","slept":"sleep","met":"meet",
    "sent":"send","meant":"mean","heard":"hear","built":"build",
    "bought":"buy","brought":"bring","caught":"catch","taught":"teach",
    "sought":"seek","fought":"fight","drew":"draw","drawn":"draw",
    "grew":"grow","grown":"grow","children":"child","men":"man",
    "women":"woman","brethren":"brother","feet":"foot","teeth":"tooth",
    "geese":"goose","mice":"mouse","lives":"life","knives":"knife",
    "wives":"wife","loaves":"loaf","haves":"half","selves":"self",
}

SUFFIXES = ("ing", "est", "edly", "edly", "ed", "es", "ly", "er",
            "'s", "s")


def load_lexicon():
    """lemma -> tag (first/most-common across POS rows)."""
    lex = {}
    path = os.path.join(LEX_DIR, "usas_single.tsv")
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            lemma = row["lemma"].lower()
            lex.setdefault(lemma, row["semantic_tags"].split()[0])
    return lex


def load_mwe():
    """templates -> ([(literal_or_None)], tag); literal None = wildcard.
    Template parts look like: 'word'_POS, word, *_POS, 'word'_* """
    out = []
    path = os.path.join(LEX_DIR, "usas_mwe.tsv")
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            parts = []
            for comp in row["mwe_template"].split():
                comp = comp.strip("'\"")
                lit = comp.split("_")[0].lower()
                parts.append(None if lit in ("", "*") else lit)
            if len(parts) > 1 and any(p is not None for p in parts):
                out.append((parts, row["semantic_tags"].split()[0]))
    out.sort(key=lambda x: -len(x[0]))  # longest match first
    return out


def lemmatize(w):
    w = w.lower()
    if w in LEX: return w
    if w in IRREG: return IRREG[w]
    for suf in SUFFIXES:
        if w.endswith(suf) and len(w) > len(suf) + 2:
            stem = w[:-len(suf)]
            # undoubling: stopped -> stop, running -> run
            if len(stem) > 2 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
                if stem[:-1] in LEX:
                    return stem[:-1]
            if stem in LEX: return stem
            if stem + "e" in LEX: return stem + "e"
    return w if w in LEX else None


def varints(buf):
    n = shift = 0
    for b in buf:
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            yield n; n = shift = 0
        else:
            shift += 7


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="bibles.pack")
    ap.add_argument("--translation", required=True)
    ap.add_argument("--book", type=int)
    args = ap.parse_args()

    global LEX
    LEX = load_lexicon()
    print(f"lexicon: {len(LEX)} lemmas")
    mwe = load_mwe()
    print(f"mwe templates: {len(mwe)}")

    con = sqlite3.connect(args.pack)
    tid = con.execute(
        "SELECT id FROM translations WHERE slug LIKE ? OR identifier=? LIMIT 1",
        (f"%{args.translation}%", args.translation)).fetchone()[0]
    dic = dict(con.execute("SELECT id, text FROM dictionary"))

    out = args.pack + ".usas.db"
    odb = sqlite3.connect(out)
    odb.execute("""CREATE TABLE IF NOT EXISTS usas_tags(
        bnum INT, cnum INT, vnum INT, pos INT,
        word TEXT, lemma TEXT, tag TEXT,
        PRIMARY KEY(bnum,cnum,vnum,pos))""")

    q = ("SELECT v.bnum, v.cnum, v.vnum, s.tokens FROM verses v "
         "JOIN sequences s ON s.id=v.seq_id WHERE v.translation_id=?")
    p = [tid]
    if args.book:
        q += " AND v.bnum=?"; p.append(args.book)
    q += " ORDER BY v.bnum, v.cnum, v.vnum"

    odb.execute("""CREATE TABLE IF NOT EXISTS usas_mwe(
        bnum INT, cnum INT, vnum INT, start_pos INT, end_pos INT,
        template TEXT, tag TEXT,
        PRIMARY KEY(bnum,cnum,vnum,start_pos,end_pos))""")

    n_tok = n_tag = n_mwe = 0
    rows, mrows = [], []
    for b, c, v, tb in con.execute(q, p):
        ids = list(varints(tb))
        words = [dic.get(d, "") for d in ids]
        lemmas = [lemmatize(w) or w.lower() for w in words]
        # multiword pass: longest templates first, skip covered positions
        covered = set()
        for parts, tag in mwe:
            n = len(parts)
            for i in range(len(lemmas) - n + 1):
                if i in covered:
                    continue
                if all(p is None or p == lemmas[i + k] or p == words[i + k].lower()
                       for k, p in enumerate(parts)):
                    mrows.append((b, c, v, i, i + n - 1,
                                  "/".join(p or "*" for p in parts), tag))
                    covered.update(range(i, i + n))
                    n_mwe += 1
        for i, did in enumerate(ids):
            word = dic.get(did, "")
            if not word[:1].isalpha() and not word[:1].isdigit():
                continue
            lemma = lemmas[i]
            tag = LEX.get(lemma)
            n_tok += 1
            if tag:
                rows.append((b, c, v, i, word, lemma, tag))
                n_tag += 1
    odb.executemany("INSERT OR REPLACE INTO usas_tags VALUES (?,?,?,?,?,?,?)",
                    rows)
    odb.executemany("INSERT OR REPLACE INTO usas_mwe VALUES (?,?,?,?,?,?,?)",
                    mrows)
    odb.commit()
    print(f"{n_tag}/{n_tok} tokens tagged, {n_mwe} MWE spans -> {out}")
    odb.close(); con.close()


if __name__ == "__main__":
    LEX = {}
    main()
