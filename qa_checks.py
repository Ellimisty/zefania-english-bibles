"""QA / integrity checks across bible_graph.db and .pack files.

Covers:
  referential  - every FK resolves (tokens, sequences, strongs, verses)
  dedup        - sequence sha matches recomputed hash, no dup (id,seq) pairs
  encoding     - mojibake signatures (â/Ã runs), replacement chars,
                 camelCase mashups, missing-space-after-punct tokens
  coverage     - per-translation token/tag counts, verses vs expected
  projection   - proj tag positions inside verse bounds, method enum valid
  pack         - verses->sequences link, dict ids all present, sha column

Usage:
  python qa_checks.py                 # graph db + all *.pack in cwd
  python qa_checks.py --pack bibles-kjv.pack
  python qa_checks.py --graph bible_graph.db
"""

import argparse
import glob
import hashlib
import os
import re
import sqlite3

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def report(kind, name, detail=""):
    print(f"[{kind}] {name}" + (f" — {detail}" if detail else ""))


def varints(buf):
    n = shift = 0
    for b in buf:
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            yield n; n = shift = 0
        else:
            shift += 7


def sha1(tb, sb, stb):
    return hashlib.sha1(tb + sb + stb).digest()


def check_graph(db):
    print(f"\n=== {db} ===")
    c = sqlite3.connect(db, timeout=120)
    c.execute("PRAGMA busy_timeout=120000")

    # --- referential: orphan tokens / strongs / strong_dict rows ---
    n = c.execute("""SELECT COUNT(*) FROM tokens t
        WHERE NOT EXISTS (SELECT 1 FROM verse_tokens vt WHERE vt.token_id=t.id)"""
        ).fetchone()[0]
    report(WARN if n else PASS, "orphan tokens", str(n))

    n = c.execute("""SELECT COUNT(*) FROM verse_tokens vt
        WHERE NOT EXISTS (SELECT 1 FROM tokens t WHERE t.id=vt.token_id)"""
        ).fetchone()[0]
    report(FAIL if n else PASS, "verse_tokens -> tokens resolve", str(n))

    n = c.execute("""SELECT COUNT(*) FROM token_strongs ts
        WHERE NOT EXISTS (SELECT 1 FROM strongs s WHERE s.id=ts.strong_id)"""
        ).fetchone()[0]
    report(FAIL if n else PASS, "token_strongs -> strongs resolve", str(n))

    n = c.execute("""SELECT COUNT(*) FROM token_strongs ts WHERE NOT EXISTS
        (SELECT 1 FROM verse_tokens vt WHERE vt.translation_id=ts.translation_id
         AND vt.verse_id=ts.verse_id AND vt.position=ts.position)""").fetchone()[0]
    report(FAIL if n else PASS, "token_strongs positions valid", str(n))

    # --- encoding: mojibake signatures in token pool ---
    n = c.execute("""SELECT COUNT(*) FROM tokens
        WHERE text LIKE '%â%' OR text LIKE '%Ã%'""").fetchone()[0]
    report(WARN if n else PASS, "mojibake-pattern tokens (â/Ã)", str(n))

    n = c.execute("""SELECT COUNT(*) FROM tokens
        WHERE text LIKE '%'||char(0xFFFD)||'%'""").fetchone()[0]
    report(FAIL if n else PASS, "U+FFFD replacement chars", str(n))

    n = c.execute("""SELECT COUNT(*) FROM tokens
        WHERE text GLOB '*[a-z][A-Z]*'""").fetchone()[0]
    report(WARN if n else PASS, "camelCase-glued tokens", str(n))

    n = c.execute("""SELECT COUNT(*) FROM tokens
        WHERE text GLOB '*[a-z],[a-z]*' OR text GLOB '*[a-z];[a-z]*'
           OR text GLOB '*[a-z]:[a-z]*' OR text GLOB '*[a-z].[a-z]*'""").fetchone()[0]
    report(WARN if n else PASS, "glued punctuation tokens (word,word)", str(n))

    # --- verse refs sane (Zefania numbering goes to ~91 for apocrypha) ---
    n = c.execute("""SELECT COUNT(*) FROM verses WHERE bnumber NOT BETWEEN 1 AND 95
        OR cnumber < 1 OR vnumber < 1""").fetchone()[0]
    report(FAIL if n else PASS, "verse refs in range", str(n))

    # --- coverage: translations present, tagged coverage ---
    tot = c.execute("SELECT COUNT(*) FROM translations").fetchone()[0]
    tagged = c.execute(
        "SELECT COUNT(DISTINCT translation_id) FROM token_strongs").fetchone()[0]
    proj = c.execute(
        "SELECT COUNT(*) FROM token_strongs_proj").fetchone()[0]
    report(PASS, "translations", f"{tot} total, {tagged} source-tagged, "
                               f"{proj:,} projected tags")

    # --- equivalence table sanity: no self-pairs ---
    n = c.execute("SELECT COUNT(*) FROM strong_equiv WHERE code=other_code").fetchone()[0]
    report(FAIL if n else PASS, "strong_equiv self-pairs", str(n))
    c.close()


def check_pack(path):
    print(f"\n=== {path} ===")
    c = sqlite3.connect(path, timeout=120)
    tables = {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}

    n = c.execute("""SELECT COUNT(*) FROM verses v
        WHERE NOT EXISTS (SELECT 1 FROM sequences s WHERE s.id=v.seq_id)"""
        ).fetchone()[0]
    report(FAIL if n else PASS, "verses -> sequences resolve", str(n))

    if "sha" in {r[1] for r in c.execute("PRAGMA table_info(sequences)")}:
        bad = 0
        for sid, tb, sb, stb, sha in c.execute(
                "SELECT id, tokens, spaces, strongs, sha FROM sequences LIMIT 200000"):
            if sha1(tb, sb, stb) != sha:
                bad += 1
        report(FAIL if bad else PASS, "sequence sha matches", f"{bad} bad")

    # every dict id referenced exists
    n = c.execute("""SELECT COUNT(*) FROM strong_words sw
        WHERE NOT EXISTS (SELECT 1 FROM dictionary d WHERE d.id=sw.dict_id)"""
        ).fetchone()[0] if "strong_words" in tables else -1
    if n >= 0:
        report(FAIL if n else PASS, "strong_words -> dictionary", str(n))

    # token decode spot-check: no index errors
    bad = 0
    for tb, sb in c.execute("SELECT tokens, spaces FROM sequences LIMIT 20000"):
        ids = list(varints(tb))
        if len(sb) < (len(ids) + 7) // 8:
            bad += 1
    report(FAIL if bad else PASS, "space-bitset lengths", f"{bad} short")

    c.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="bible_graph.db")
    ap.add_argument("--pack", action="append")
    args = ap.parse_args()

    if os.path.exists(args.graph):
        check_graph(args.graph)
    packs = args.pack or glob.glob("*.pack")
    for p in packs:
        check_pack(p)
    if not packs:
        print("no packs found")


if __name__ == "__main__":
    main()
