"""Build strong_equiv + strong_class tables in bible_graph.db.

strong_equiv(code, other_code, kind, note)
    kind='equivalent' : same word/root, different Strong's entry — safe to pool
    kind='related'    : different words taggers commonly conflate — poolable for
                        projection but worth keeping the distinction
    kind='candidate'  : high-frequency audit conflicts awaiting review

strong_class(code, class, note)
    classes: 'prefix' (tags the prefix, not the root — e.g. min-),
             'particle' (untranslatable / grammatical markers)

Curated seeds come from strong_audit top conflicts + known Strong's quirks.
"""

import sqlite3

EQUIV = [
    # (code, other, kind, note)
    ("H1980", "H3212", "equivalent", "halakh 'go' — two spellings, same verb"),
    ("H6038", "H6037", "equivalent", "anav/anavah — adjective vs noun of same root"),
    ("H3083", "H3129", "equivalent", "Jonathan — two spellings"),
    ("H3069", "H136",  "equivalent", "qere/keriv: YHWH w/ Adonai vowels vs Adonai"),
    ("G848",  "G846",  "related",   "autou (reflexive) vs autos — taggers disagree"),
    ("G25",   "G26",   "equivalent", "agapao verb / agape noun — same word family"),
    ("G1161", "G2532", "related",   "de vs kai — both rendered 'and', frequent split"),
    ("G1063", "G2532", "related",   "gar vs kai — kai gar parsed differently"),
    ("G5360", "G26",   "equivalent", "philadelphia — love-noun family"),
    ("H376",  "H582",  "related",   "ish vs enosh — both 'man/men'"),
    ("H776",  "H4480", "related",   "erets 'land' vs min- prefix tag"),
    ("H6440", "H4480", "related",   "panim 'face/before' vs min- prefix tag"),
    ("H8432", "H4480", "related",   "tavek 'midst' vs min- prefix tag"),
    ("H5869", "H2896", "related",   "ayin vs tov — 'good' in 'tohu tov' phrasing"),
    ("H2895", "H2896", "equivalent", "tov verb/adj forms of 'good'"),
    ("H3190", "H2896", "equivalent", "yatav 'be good' vs tov — same root family"),
    ("G18",   "G2570", "related",   "agathos vs kalos — 'good' vs 'fine'"),
    ("G5543", "G5544", "equivalent", "chrestos adj / chrestotes noun — kindness"),
    ("G5544", "G19",   "related",   "chrestotes 'kindness' vs agathosune 'goodness'"),
    ("G2443", "G3363", "related",   "hina 'that' vs me 'lest' — opposite senses!"),
    ("G5210", "G846",  "related",   "hymeis vs autos — 2pl vs 3sg pronoun conflation"),
    ("G3754", "G2532", "related",   "hoti 'because/that' vs kai 'and'"),
    ("G3363", "G2532", "related",   "me vs kai at verse starts"),
    ("G3004", "G2532", "related",   "lego vs kai — discourse-tagging split"),
    ("G1722", "G1519", "related",   "en vs eis — 'in' vs 'into' conflation"),
    ("G3303", "G2532", "related",   "men (particle) vs kai"),
    ("G3756", "G2532", "related",   "ou vs kai — 'and not' segmentation"),
]

# codes that tag a *prefix/particle* attached to the word rather than the
# root lexeme — treated separately during projection
CLASSES = [
    ("H4480", "prefix", "min- 'from/of' — KJV-style tags the preposition prefix"),
    ("H*853", "particle", "eth — accusative marker, untranslatable"),
    ("G*3754", "particle", "hoti used as quotation marker"),
]


def main():
    conn = sqlite3.connect("bible_graph.db", timeout=300)
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("""CREATE TABLE IF NOT EXISTS strong_equiv(
        code TEXT, other_code TEXT, kind TEXT, note TEXT,
        PRIMARY KEY(code, other_code))""")
    conn.execute("DELETE FROM strong_equiv")
    conn.execute("""CREATE TABLE IF NOT EXISTS strong_class(
        code TEXT PRIMARY KEY, class TEXT, note TEXT)""")
    conn.execute("DELETE FROM strong_class")

    for code, other, kind, note in EQUIV:
        conn.execute("INSERT OR REPLACE INTO strong_equiv VALUES (?,?,?,?)",
                     (code, other, kind, note))
        conn.execute("INSERT OR REPLACE INTO strong_equiv VALUES (?,?,?,?)",
                     (other, code, kind, note))
    conn.executemany("INSERT OR REPLACE INTO strong_class VALUES (?,?,?)", CLASSES)

    # surface high-frequency conflict pairs not yet classified -> candidates
    unclassified = conn.execute("""
        SELECT code1, code2, COUNT(*) n FROM strong_audit
        WHERE kind='conflict' AND code1 IS NOT NULL AND code2 IS NOT NULL
        GROUP BY code1, code2 HAVING n >= 10 ORDER BY n DESC""").fetchall()
    n_cand = 0
    for c1, c2, n in unclassified:
        seen = conn.execute(
            "SELECT 1 FROM strong_equiv WHERE code=? AND other_code=?",
            (c1, c2)).fetchone()
        if not seen:
            conn.execute("INSERT INTO strong_equiv VALUES (?,?,?,?)",
                         (c1, c2, "candidate", f"{n} audit conflicts"))
            conn.execute("INSERT INTO strong_equiv VALUES (?,?,?,?)",
                         (c2, c1, "candidate", f"{n} audit conflicts"))
            n_cand += 1
    conn.commit()

    for kind, n in conn.execute(
            "SELECT kind, COUNT(*)/2 FROM strong_equiv GROUP BY kind"):
        print(f"strong_equiv[{kind}]: {n} pairs")
    print(f"strong_class: {conn.execute('SELECT COUNT(*) FROM strong_class').fetchone()[0]}")
    print(f"candidates added: {n_cand}")
    conn.close()


if __name__ == "__main__":
    main()
