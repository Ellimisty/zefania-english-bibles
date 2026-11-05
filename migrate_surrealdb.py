"""Migrate bible_graph.db (SQLite) into a SurrealDB instance.

Model (schemaless):
  translation:<sid>   {slug, filename, name, identifier}
  token:<id>          {text, lower, is_punct}          -- shared deduplicated pool
  strong:`<CODE>`     {code}                            -- e.g. strong:`G1401`, `H*853`
  verse:<id>          {bnumber, cnumber, vnumber, bname, ref}
  verse_text:<sid>_<vid> {translation, verse, slug, ref,
                          tokens: [token:<id>, ...],
                          strongs: {"pos": [strong:<c>,...]}}
  greek_word         {bnumber, cnumber, vnumber, position,
                      surface, lemma, parsing, strong}
  similarity:<vid>_<tid> {verse, ref_translation, translation,
                          shared_prefix, jaccard}
  Edges: token->translated_as->strong  (unique surface-form/strong pairs)

Usage:
    python migrate_surrealdb.py [--db bible_graph.db] [--url ws://127.0.0.1:8000/rpc]
                                [--ns main] [--dbn main] [--batch 500]
                                [--start-at translations]
"""

import argparse
import json
import re
import sqlite3

from surrealdb import Surreal


def esc(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def sid(slug):
    return re.sub(r"[^A-Za-z0-9]", "_", slug)


def sref(code):
    """Backtick-quoted strong record ref — codes like 'H*853' aren't bare-safe."""
    return "strong:`" + code.replace("`", "\\`") + "`"


def batched(seq, n):
    buf = []
    for x in seq:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="bible_graph.db")
    ap.add_argument("--url", default="ws://127.0.0.1:8000/rpc")
    ap.add_argument("--user", default="root")
    ap.add_argument("--pw", default="root")
    ap.add_argument("--ns", default="main")
    ap.add_argument("--dbn", default="main")
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--start-at", default="translations",
                    choices=["translations", "verse_texts", "strong_tags",
                             "greek_words", "similarity", "translated_as"])
    args = ap.parse_args()

    STAGES = ["translations", "verse_texts", "strong_tags", "greek_words",
              "similarity", "translated_as"]
    start_i = STAGES.index(args.start_at)
    skip = lambda name: STAGES.index(name) < start_i

    con = sqlite3.connect(args.db, timeout=300)
    sdb = Surreal(args.url)
    sdb.signin({"username": args.user, "password": args.pw})
    sdb.use(args.ns, args.dbn)

    def run(stmts):
        sdb.query(";".join(stmts)).execute()

    # --- dimension tables (always run unless we start past them) ---
    if not skip("verse_texts"):
        rows = con.execute(
            "SELECT slug, filename, name, identifier FROM translations"
        ).fetchall()
        for b in batched(rows, args.batch):
            run([
                f"UPSERT translation:{sid(sl)} SET slug={esc(sl)}, filename={esc(fn or '')}, "
                f"name={esc(nm or '')}, identifier={esc(ident or '')}"
                for sl, fn, nm, ident in b
            ])
        print(f"translations: {len(rows)}", flush=True)

        rows = con.execute("SELECT id, text, lower, is_punct FROM tokens").fetchall()
        for b in batched(rows, args.batch):
            run([
                f"UPSERT token:{i} SET text={esc(t)}, lower={esc(l or '')}, is_punct={bool(p)}"
                for i, t, l, p in b
            ])
        print(f"tokens: {len(rows)}", flush=True)

        rows = con.execute("SELECT code FROM strongs").fetchall()
        for b in batched(rows, args.batch):
            run([f"UPSERT {sref(c)} SET code={esc(c)}" for (c,) in b])
        print(f"strongs: {len(rows)}", flush=True)

        rows = con.execute(
            "SELECT id, bnumber, cnumber, vnumber, bname, ref FROM verses"
        ).fetchall()
        for b in batched(rows, args.batch):
            run([
                f"UPSERT verse:{i} SET bnumber={bn}, cnumber={cn}, vnumber={vn}, "
                f"bname={esc(bn_ or '')}, ref={esc(rf)}"
                for i, bn, cn, vn, bn_, rf in b
            ])
        print(f"verses: {len(rows)}", flush=True)

    tslug = dict(con.execute("SELECT id, slug FROM translations"))

    if not skip("verse_texts"):
        # --- verse_text records: tokens array + per-position strong tags ---
        last_tid, last_vid, total = None, None, 0
        stmts, toks, tags = [], [], {}

        def flush(tid, vid, toks, tags):
            slug = tslug[tid]
            s = (
                f"UPSERT verse_text:{sid(slug)}_{vid} SET slug={esc(slug)}, "
                f"translation=translation:{sid(slug)}, verse=verse:{vid}, "
                f"tokens=[{', '.join('token:' + str(t) for t in toks)}]"
            )
            if tags:
                inner = ", ".join(
                    f"{json.dumps(str(p))}: [{', '.join(sref(c) for c in codes)}]"
                    for p, codes in tags.items()
                )
                s += f", strongs={{{inner}}}"
            return s

        for tid, vid, pos, tk in con.execute(
            "SELECT translation_id, verse_id, position, token_id FROM verse_tokens "
            "ORDER BY translation_id, verse_id, position"
        ):
            if (tid, vid) != (last_tid, last_vid):
                if toks:
                    # fold strong tags accumulated so far into this flush
                    stmts.append(flush(last_tid, last_vid, toks, tags))
                    if len(stmts) >= args.batch:
                        run(stmts); total += len(stmts); stmts = []
                toks, tags = [], {}
                last_tid, last_vid = tid, vid
            toks.append(tk)
        if toks:
            stmts.append(flush(last_tid, last_vid, toks, tags))
        if stmts:
            run(stmts); total += len(stmts)
        print(f"verse_texts (token paths): {total}", flush=True)

        # fold token_strongs into strongs maps (separate pass below)

    if not skip("strong_tags"):
        # strong tags -> verse_text.strongs maps
        cur_vt, tags = None, {}
        upd, total = [], 0
        for tid, vid, pos, scode in con.execute(
            "SELECT ts.translation_id, ts.verse_id, ts.position, s.code "
            "FROM token_strongs ts JOIN strongs s ON s.id=ts.strong_id "
            "ORDER BY ts.translation_id, ts.verse_id, ts.position"
        ):
            key = f"verse_text:{sid(tslug[tid])}_{vid}"
            if key != cur_vt and tags:
                inner = ", ".join(
                    f"{json.dumps(str(p))}: [{', '.join(sref(c) for c in codes)}]"
                    for p, codes in tags.items()
                )
                upd.append(f"UPDATE {cur_vt} SET strongs={{{inner}}}")
                if len(upd) >= args.batch:
                    run(upd); total += len(upd); upd = []
                tags = {}
            cur_vt = key
            tags.setdefault(pos, []).append(scode)
        if tags:
            inner = ", ".join(
                f"{json.dumps(str(p))}: [{', '.join(sref(c) for c in codes)}]"
                for p, codes in tags.items()
            )
            upd.append(f"UPDATE {cur_vt} SET strongs={{{inner}}}")
        if upd:
            run(upd); total += len(upd)
        print(f"verse_text strong tags: {total}", flush=True)

    if not skip("greek_words"):
        rows = con.execute(
            "SELECT w.bnumber, w.cnumber, w.vnumber, w.position, w.surface, w.lemma, "
            "s.code, w.parsing FROM greek_words w LEFT JOIN strongs s ON s.id=w.strong_id "
            "ORDER BY w.bnumber, w.cnumber, w.vnumber, w.position"
        ).fetchall()
        total = 0
        for b in batched(rows, args.batch):
            stmts = []
            for bn, cn, vn, pos, surf, lem, scode, pars in b:
                s = (
                    f"UPSERT greek_word:{bn}_{cn}_{vn}_{pos} SET bnumber={bn}, cnumber={cn}, vnumber={vn}, "
                    f"position={pos}, surface={esc(surf or '')}, lemma={esc(lem or '')}, "
                    f"parsing={esc(pars or '')}"
                )
                if scode:
                    s += f", strong={sref(scode)}"
                stmts.append(s)
            run(stmts); total += len(stmts)
        print(f"greek_words: {total}", flush=True)

    if not skip("similarity"):
        rows = con.execute(
            "SELECT verse_id, ref_translation_id, translation_id, shared_prefix, jaccard "
            "FROM similarity"
        ).fetchall()
        total = 0
        for b in batched(rows, args.batch):
            run([
                f"UPSERT similarity:{v}_{t} SET verse=verse:{v}, "
                f"ref_translation=translation:{sid(tslug[r])}, "
                f"translation=translation:{sid(tslug[t])}, "
                f"shared_prefix={p}, jaccard={j}"
                for v, r, t, p, j in b
            ])
            total += len(b)
        print(f"similarity: {total}", flush=True)

    if not skip("translated_as"):
        pairs = con.execute(
            "SELECT DISTINCT vt.token_id, s.code FROM token_strongs ts "
            "JOIN verse_tokens vt ON vt.translation_id=ts.translation_id "
            "AND vt.verse_id=ts.verse_id AND vt.position=ts.position "
            "JOIN strongs s ON s.id=ts.strong_id"
        ).fetchall()
        total = 0
        for b in batched(pairs, args.batch):
            run([
                f"RELATE token:{tk}->translated_as:{tk}_{sid(c)}->{sref(c)}" for tk, c in b
            ])
            total += len(b)
        print(f"translated_as edges: {total}", flush=True)

    sdb.close()
    con.close()
    print("done")


if __name__ == "__main__":
    main()
