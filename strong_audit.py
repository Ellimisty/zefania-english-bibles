"""Audit Strong's tag consistency across tagged translations.

For each pair of tagged translations sharing a verse, align their token
streams (exact match when texts are identical — shared token sequences
make this free; difflib otherwise) and compare tags at aligned positions:

  conflict : both tagged, different codes      (the real discrepancies)
  gap      : one tagged, the other not         (coverage inconsistency)

Pairs are grouped by language (slug contains _ENG_ / _GER_ etc.) so we
never waste time aligning German against English.

Output:
  - table `strong_audit` in bible_graph.db (all findings)
  - top conflict word-pairs printed for human/LLM review
"""

import argparse
import difflib
import sqlite3
from collections import Counter, defaultdict


def language_of(slug):
    for part in slug.split("_"):
        if len(part) == 3 and part.isalpha():
            return part
        if len(part) >= 3 and part[:3].isalpha() and part[:3].isupper():
            return part[:3]
    return "UNK"


def load_verse(conn, tid, vid):
    toks = [r[0] for r in conn.execute(
        "SELECT t.lower FROM verse_tokens vt JOIN tokens t ON t.id=vt.token_id "
        "WHERE vt.translation_id=? AND vt.verse_id=? ORDER BY vt.position",
        (tid, vid))]
    tags = {p: c for p, c in conn.execute(
        "SELECT ts.position, s.code FROM token_strongs ts "
        "JOIN strongs s ON s.id=ts.strong_id "
        "WHERE ts.translation_id=? AND ts.verse_id=?",
        (tid, vid))}
    return toks, tags


def aligned_pairs(toks1, toks2):
    """yield (pos1, pos2) for aligned tokens (exact or difflib)."""
    if toks1 == toks2:
        yield from enumerate(range(len(toks1)))
        return
    sm = difflib.SequenceMatcher(None, toks1, toks2, autojunk=False)
    for b in sm.get_matching_blocks():
        for i in range(b.size):
            yield b.a + i, b.b + i


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="bible_graph.db")
    ap.add_argument("--min-count", type=int, default=3,
                    help="min occurrences for printed conflict summaries")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db, timeout=300)
    conn.execute("PRAGMA busy_timeout=300000")

    conn.execute("""CREATE TABLE IF NOT EXISTS strong_audit(
        verse_ref TEXT, pos INT, word1 TEXT, code1 TEXT,
        word2 TEXT, code2 TEXT, t1 TEXT, t2 TEXT, kind TEXT)""")
    conn.execute("DELETE FROM strong_audit")

    tagged = conn.execute(
        "SELECT DISTINCT ts.translation_id, tr.slug, tr.identifier "
        "FROM token_strongs ts JOIN translations tr ON tr.id=ts.translation_id").fetchall()
    by_lang = defaultdict(list)
    for tid, slug, ident in tagged:
        by_lang[language_of(slug)].append((tid, ident or slug))
    print("tagged translations:")
    for lang, ts in by_lang.items():
        print(f"  {lang}: {', '.join(i for _, i in ts)}")

    verses_by_tid = {}
    for tid, _ in {t for ts in by_lang.values() for t in ts}:
        verses_by_tid[tid] = {v for (v,) in conn.execute(
            "SELECT DISTINCT verse_id FROM token_strongs WHERE translation_id=?",
            (tid,))}

    conflicts = Counter()
    examples = {}
    n_conf = n_gap = n_checked = 0

    for lang, ts in by_lang.items():
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                t1, id1 = ts[i]
                t2, id2 = ts[j]
                shared = verses_by_tid[t1] & verses_by_tid[t2]
                for vid in shared:
                    toks1, tags1 = load_verse(conn, t1, vid)
                    toks2, tags2 = load_verse(conn, t2, vid)
                    ref = conn.execute("SELECT ref FROM verses WHERE id=?",
                                       (vid,)).fetchone()[0]
                    for p1, p2 in aligned_pairs(toks1, toks2):
                        c1, c2 = tags1.get(p1), tags2.get(p2)
                        n_checked += 1
                        if c1 and c2:
                            if c1 != c2:
                                n_conf += 1
                                key = (id1, toks1[p1], c1, id2, toks2[p2], c2)
                                conflicts[key] += 1
                                examples.setdefault(key, f"{ref}")
                                conn.execute(
                                    "INSERT INTO strong_audit VALUES (?,?,?,?,?,?,?,?,?)",
                                    (ref, p1, toks1[p1], c1, toks2[p2], c2,
                                     id1, id2, "conflict"))
                        elif c1 or c2:
                            n_gap += 1
                            conn.execute(
                                "INSERT INTO strong_audit VALUES (?,?,?,?,?,?,?,?,?)",
                                (ref, p1, toks1[p1], c1, toks2[p2], c2,
                                 id1, id2, "gap"))
                print(f"{id1} x {id2}: {len(shared)} verses checked")
    conn.commit()

    print(f"\naligned positions checked: {n_checked:,}")
    print(f"conflicts (both tagged, different codes): {n_conf:,}")
    print(f"gaps (one tagged, one not): {n_gap:,}")
    print("\ntop conflict word-pairs (t1 word/code -> t2 word/code):")
    for (id1, w1, c1, id2, w2, c2), n in conflicts.most_common(40):
        if n < args.min_count:
            break
        print(f"  {n:4}x {id1}:{w1}({c1}) -> {id2}:{w2}({c2})   e.g. {examples[(id1, w1, c1, id2, w2, c2)]}")

    conn.close()


if __name__ == "__main__":
    main()
