"""Migrate bible_graph.db (SQLite) into a running Neo4j instance.

Graph model:
  (:Translation {slug, filename, name, identifier})
  (:Token {id, text, lower, is_punct})          -- shared deduplicated pool
  (:Strongs {code})                              -- e.g. 'G1401', 'H*853'
  (:Verse {id, bnumber, cnumber, vnumber, bname, ref})
  (:VerseText {key, slug, ref, tokens, strongs}) -- tokens: [token ids in order]
  (:GreekWord {bnumber,cnumber,vnumber,position,surface,lemma,parsing})
  (:Similarity {verse_id, shared_prefix, jaccard})

  (:Verse)-[:HAS_TEXT]->(:VerseText)-[:TRANSLATED_BY]->(:Translation)
  (:Token)-[:TRANSLATES]->(:Strongs)             -- unique surface/strong pairs
  (:GreekWord)-[:STRONGS]->(:Strongs)
  (:Similarity)-[:OF_VERSE]->(:Verse)
  (:Similarity)-[:FOR_TRANSLATION]->(:Translation)

Usage:
    python migrate_neo4j.py [--db bible_graph.db] [--uri bolt://127.0.0.1:7687]
                            [--user neo4j] [--pw biblegraph] [--batch 2000]
"""

import argparse
import sqlite3

from neo4j import GraphDatabase


def sid(slug):
    import re
    return re.sub(r"[^A-Za-z0-9]", "_", slug)


def batched(seq, n):
    buf = []
    for x in seq:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf


def run_batch(sess, cypher, rows, batch, total=[0]):
    for b in batched(rows, batch):
        sess.run(cypher, rows=b).consume()
        total[0] += len(b)
        if total[0] % 50000 < batch:
            print(f"  {total[0]}...", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="bible_graph.db")
    ap.add_argument("--uri", default="bolt://127.0.0.1:7687")
    ap.add_argument("--user", default="neo4j")
    ap.add_argument("--pw", default="biblegraph")
    ap.add_argument("--batch", type=int, default=2000)
    ap.add_argument("--start-at", default="translations",
                    choices=["translations", "strongs", "tokens", "verses",
                             "verse_texts", "strong_tags", "translates",
                             "greek_words", "similarity"])
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    drv = GraphDatabase.driver(args.uri, auth=(args.user, args.pw))
    sess = drv.session(database="neo4j")

    # constraints (idempotent)
    for q in [
        "CREATE CONSTRAINT translation_slug IF NOT EXISTS FOR (t:Translation) REQUIRE t.slug IS UNIQUE",
        "CREATE CONSTRAINT token_id IF NOT EXISTS FOR (t:Token) REQUIRE t.id IS UNIQUE",
        "CREATE CONSTRAINT strongs_code IF NOT EXISTS FOR (s:Strongs) REQUIRE s.code IS UNIQUE",
        "CREATE CONSTRAINT verse_id IF NOT EXISTS FOR (v:Verse) REQUIRE v.id IS UNIQUE",
        "CREATE CONSTRAINT versetext_key IF NOT EXISTS FOR (v:VerseText) REQUIRE v.key IS UNIQUE",
    ]:
        sess.run(q).consume()

    STAGES = ["translations", "strongs", "tokens", "verses", "verse_texts",
              "strong_tags", "translates", "greek_words", "similarity"]
    start_i = STAGES.index(args.start_at)
    skip = lambda name: STAGES.index(name) < start_i

    tslug = dict(con.execute("SELECT id, slug FROM translations"))
    strong_code = dict(con.execute("SELECT id, code FROM strongs"))

    if not skip("translations"):
        print("translations")
        run_batch(sess,
            "UNWIND $rows AS r MERGE (t:Translation {slug:r[0]}) "
            "SET t.filename=r[1], t.name=r[2], t.identifier=r[3]",
            con.execute("SELECT slug, filename, name, identifier FROM translations"),
            args.batch)

    if not skip("strongs"):
        print("strongs")
        run_batch(sess,
            "UNWIND $rows AS r MERGE (s:Strongs {code:r[0]})",
            con.execute("SELECT code FROM strongs"), args.batch)

    if not skip("tokens"):
        print("tokens")
        run_batch(sess,
            "UNWIND $rows AS r MERGE (t:Token {id:r[0]}) "
            "SET t.text=r[1], t.lower=r[2], t.is_punct=r[3]",
            con.execute("SELECT id, text, lower, is_punct FROM tokens"), args.batch)

    if not skip("verses"):
        print("verses")
        run_batch(sess,
            "UNWIND $rows AS r MERGE (v:Verse {id:r[0]}) "
            "SET v.bnumber=r[1], v.cnumber=r[2], v.vnumber=r[3], v.bname=r[4], v.ref=r[5]",
            con.execute("SELECT id, bnumber, cnumber, vnumber, bname, ref FROM verses"),
            args.batch)

    if not skip("verse_texts"):
        # --- VerseText nodes + hierarchy edges ---
        print("verse_texts (token paths)")

        def verse_text_rows():
            cur = None
            toks = []
            for tid, vid, pos, tk in con.execute(
                "SELECT translation_id, verse_id, position, token_id FROM verse_tokens "
                "ORDER BY translation_id, verse_id, position"
            ):
                if (tid, vid) != cur:
                    if toks:
                        pt, pv = cur
                        yield (f"{sid(tslug[pt])}_{pv}", tslug[pt], pv, toks)
                    toks = []
                    cur = (tid, vid)
                toks.append(tk)
            if toks:
                pt, pv = cur
                yield (f"{sid(tslug[pt])}_{pv}", tslug[pt], pv, toks)

        run_batch(sess,
            "UNWIND $rows AS r "
            "MERGE (vt:VerseText {key:r[0]}) SET vt.slug=r[1], vt.tokens=r[3] "
            "WITH vt, r "
            "MATCH (v:Verse {id:r[2]}) MERGE (v)-[:HAS_TEXT]->(vt) "
            "WITH vt, r MATCH (t:Translation {slug:r[1]}) MERGE (vt)-[:TRANSLATED_BY]->(t)",
            verse_text_rows(), args.batch)

    if not skip("strong_tags"):
        # --- strong tags as (VerseText)-[:HAS_STRONG {pos}]->(Strongs) edges ---
        print("verse_text strong tags")
        run_batch(sess,
            "UNWIND $rows AS r "
            "MATCH (vt:VerseText {key:r[0]}) MATCH (s:Strongs {code:r[2]}) "
            "MERGE (vt)-[e:HAS_STRONG {pos:r[1]}]->(s)",
            ((f"{sid(tslug[tid])}_{vid}", pos, c) for tid, vid, pos, c in con.execute(
                "SELECT ts.translation_id, ts.verse_id, ts.position, s.code "
                "FROM token_strongs ts JOIN strongs s ON s.id=ts.strong_id")),
            args.batch)

    if not skip("translates"):
        # --- translated_as edges: unique token->strong pairs ---
        print("TRANSLATES edges (unique token->strong pairs)")
        run_batch(sess,
            "UNWIND $rows AS r "
            "MATCH (t:Token {id:r[0]}) MATCH (s:Strongs {code:r[1]}) "
            "MERGE (t)-[:TRANSLATES]->(s)",
            con.execute(
                "SELECT DISTINCT vt.token_id, s.code FROM token_strongs ts "
                "JOIN verse_tokens vt ON vt.translation_id=ts.translation_id "
                "AND vt.verse_id=ts.verse_id AND vt.position=ts.position "
                "JOIN strongs s ON s.id=ts.strong_id"),
            args.batch)

    if not skip("greek_words"):
        # --- greek words ---
        print("greek_words")
        run_batch(sess,
            "UNWIND $rows AS r "
            "CREATE (g:GreekWord {bnumber:r[0], cnumber:r[1], vnumber:r[2], position:r[3], "
            "surface:r[4], lemma:r[5], parsing:r[6]}) "
            "WITH g, r WHERE r[7] IS NOT NULL "
            "MATCH (s:Strongs {code:r[7]}) MERGE (g)-[:STRONGS]->(s)",
            ((b, c, v, p, su, le, pa, sc) for b, c, v, p, su, le, sc, pa in
             con.execute(
                "SELECT w.bnumber, w.cnumber, w.vnumber, w.position, w.surface, w.lemma, "
                "s.code, w.parsing FROM greek_words w LEFT JOIN strongs s ON s.id=w.strong_id")),
            args.batch)

    if not skip("similarity"):
        # --- similarity ---
        print("similarity")
        run_batch(sess,
            "UNWIND $rows AS r "
            "MERGE (s:Similarity {key:r[0]}) "
            "SET s.verse_id=r[1], s.shared_prefix=r[2], s.jaccard=r[3] "
            "WITH s, r MATCH (v:Verse {id:r[1]}) MERGE (s)-[:OF_VERSE]->(v) "
            "WITH s, r MATCH (t:Translation {slug:r[4]}) MERGE (s)-[:FOR_TRANSLATION]->(t)",
            ((f"{v}_{t}", v, p, j, tslug[t]) for v, r, t, p, j in
             con.execute(
                "SELECT verse_id, ref_translation_id, translation_id, shared_prefix, jaccard "
                "FROM similarity")),
            args.batch)

    sess.close()
    drv.close()
    con.close()
    print("done")


if __name__ == "__main__":
    main()
