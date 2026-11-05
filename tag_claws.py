"""POS-tag translations via UCREL's CLAWS web service (C7 tagset).

Reads a .pack (or a translation slice), reconstructs verse text, batches it
under a chapter marker (~90k chars per submission), submits to CLAWS via
direct POST (headless-Chromium fallback via playwright), and writes
pos_tags(translation_id, bnum, cnum, vnum, position, token, tag) to
bible_graph.db — or to a sidecar <pack>.pos.db when --pack is given.

Usage:
  python tag_claws.py --pack bibles-kjv.pack --translation KJV \
                      --book James --chapter 1            # smoke test
  python tag_claws.py --pack bibles.pack --translation KJV --out kjv.pos.db
"""

import argparse
import os
import re
import sqlite3
import sys

CLAWS_API = "http://ucrel-api.lancaster.ac.uk/cgi-bin/claws74.pl"
CLAWS_FORM = "http://ucrel-api.lancaster.ac.uk/claws/free.html"
MARKER = "ZZZVERSEBOUNDARYZZZ"
MAX_WORDS = 85000      # UCREL accepts ~90k words per submission
MAX_CHARS = 800000


def claws_requests(text):
    import requests
    from collections import OrderedDict
    try:
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/130.0 Safari/537.36"})
        s.get(CLAWS_FORM, timeout=30)
        fields = OrderedDict([
            ("email", (None, "a.nobody@here.ac.uk")),
            ("tagset", (None, "c7")),
            ("style", (None, "vert")),
            ("text", (None, text[:MAX_CHARS])),
        ])
        resp = s.post(CLAWS_API, files=fields, timeout=120)
        m = re.search(r"<pre>(.*?)</pre>", resp.text, re.S)
        return m.group(1) if m and m.group(1).strip() else None
    except Exception:
        return None


def claws_browser(text):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(CLAWS_FORM, timeout=30000)
            page.check('input[name="tagset"][value="c7"]')
            page.check('input[name="style"][value="vert"]')
            page.fill('textarea[name="text"]', text[:MAX_CHARS])
            page.click('input[type="submit"]')
            page.wait_for_load_state("load", timeout=120000)
            pre = (page.inner_text("pre")
                   if page.query_selector("pre") else "")
            browser.close()
        return pre if pre.strip() else None
    except Exception:
        return None


def submit(text):
    return claws_requests(text) or claws_browser(text)


def parse_vert(vert):
    """yield (token, tag) — first candidate per row like analyze_prose."""
    for line in vert.splitlines():
        parts = line.split()
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        token = parts[2]
        if token == MARKER:
            yield (MARKER, None)
            continue
        tags = re.findall(r"[A-Z]+[0-9]*[A-Z]*", parts[-1])
        if tags:
            yield (token, tags[0])


def varints(buf):
    n = shift = 0
    for b in buf:
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            yield n
            n = shift = 0
        else:
            shift += 7


def pack_verses(con, tid, bnum=None, cnum=None):
    q = ("SELECT v.bnum, v.cnum, v.vnum, s.tokens, s.spaces "
         "FROM verses v JOIN sequences s ON s.id=v.seq_id "
         "WHERE v.translation_id=?")
    p = [tid]
    if bnum is not None:
        q += " AND v.bnum=?"; p.append(bnum)
    if cnum is not None:
        q += " AND v.cnum=?"; p.append(cnum)
    q += " ORDER BY v.bnum, v.cnum, v.vnum"
    dic = dict(con.execute("SELECT id, text FROM dictionary"))
    for b, c, v, tb, sb in con.execute(q, p):
        ids = list(varints(tb))
        text = "".join((" " if i > 0
                        and i // 8 < len(sb)
                        and (sb[i // 8] >> (i % 8)) & 1 else "")
                       + dic.get(did, "") for i, did in enumerate(ids))
        yield b, c, v, text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="bibles.pack")
    ap.add_argument("--translation", required=True)
    ap.add_argument("--book", type=int)
    ap.add_argument("--chapter", type=int)
    ap.add_argument("--out", default=None,
                    help="sidecar db (default <pack>.pos.db)")
    args = ap.parse_args()

    con = sqlite3.connect(args.pack)
    tid = con.execute(
        "SELECT id FROM translations WHERE slug LIKE ? OR identifier=? LIMIT 1",
        (f"%{args.translation}%", args.translation)).fetchone()
    if not tid:
        sys.exit(f"translation '{args.translation}' not found")
    tid = tid[0]

    out = args.out or (args.pack + ".pos.db")
    odb = sqlite3.connect(out)
    odb.execute("""CREATE TABLE IF NOT EXISTS pos_tags(
        bnum INT, cnum INT, vnum INT, pos INT, token TEXT, tag TEXT,
        PRIMARY KEY(bnum, cnum, vnum, pos))""")
    odb.execute("""CREATE TABLE IF NOT EXISTS pos_done(
        translation TEXT, bnum INT, cnum INT,
        PRIMARY KEY(translation, bnum, cnum))""")
    ident = con.execute("SELECT identifier FROM translations WHERE id=?",
                        (tid,)).fetchone()[0]

    # group verses into ~85k-word batches
    batches, cur, words = [], [], 0
    for b, c, v, text in pack_verses(con, tid, args.book, args.chapter):
        w = len(text.split())
        if words + w > MAX_WORDS and cur:
            batches.append(cur); cur, words = [], 0
        cur.append((b, c, v, text)); words += w
    if cur:
        batches.append(cur)

    total = 0
    for batch in batches:
        joined = f"\n\n{MARKER}\n\n".join(t for _, _, _, t in batch)
        vert = submit(joined)
        if vert is None:
            sys.exit("CLAWS submit failed (rate limit / no playwright)")
        # walk segments back onto verses
        segs, cur = [[]], None
        for tok, tag in parse_vert(vert):
            if tok == MARKER:
                segs.append([])
            else:
                segs[-1].append((tok, tag))
        if len(segs) != len(batch):
            print(f"warning: {len(segs)} segments vs {len(batch)} verses",
                  file=sys.stderr)
        for (b, c, v, _), seg in zip(batch, segs):
            odb.executemany(
                "INSERT OR REPLACE INTO pos_tags VALUES (?,?,?,?,?,?)",
                [(b, c, v, i, tok, tag) for i, (tok, tag) in enumerate(seg)])
            total += len(seg)
        odb.commit()
        print(f"batch: {len(batch)} verses, {sum(len(s) for s in segs)} tags",
              flush=True)
    print(f"done: {total} tags -> {out}")
    odb.close(); con.close()


if __name__ == "__main__":
    main()
