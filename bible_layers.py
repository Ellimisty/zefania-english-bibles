"""Per-verse linguistic layers over a .pack — ported from book/scripts
detectors, wired to our pack format + pos_tags sidecar.

Layers per verse:
  words, sentences, dialogue_pct     - cheap style metrics
  passive                            - regex detect (be + VBN-ish) when no
                                       pos_tags; CLAWS aux+VVN when tagged
  speech_verbs                       - said/answered/cried... count
  pos_tags joined                    - when a .pos.db exists, passive count
                                       comes from tags (more accurate)

Writes metrics(bnum,cnum,vnum, ...) into <pack>.layers.db
"""

import argparse
import re
import sqlite3
import sys

SPEECH_VERBS = re.compile(
    r"\b(said|answered|cried|spake|asked|replied|declared|called|told|"
    r"commanded|answered|proclaimed|whispered|shouted|called|named)\b", re.I)
# regex fallback: be/is/are/was/were/been/being + participle heuristic
PASSIVE_RE = re.compile(
    r"\b(?:am|is|are|was|were|be|been|being|get|got|getting|gotten)\s+"
    r"(?:\w+ly\s+)?\w+(?:ed|en|n)\b", re.I)
QUOTE_RE = re.compile(r"[“\"‘']")
AUX = {"VBB","VBD","VBG","VBI","VBM","VBN","VBR","VBZ","VDB","VDD","VDG",
       "VDI","VDN","VDZ","VHB","VHD","VHG","VHI","VHN","VHZ","VM","VMK"}


def varints(buf):
    n = shift = 0
    for b in buf:
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            yield n; n = shift = 0
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
        text = "".join((" " if i > 0 and i // 8 < len(sb)
                        and (sb[i // 8] >> (i % 8)) & 1 else "")
                       + dic.get(did, "") for i, did in enumerate(ids))
        yield b, c, v, text


def load_pos(db):
    try:
        con = sqlite3.connect(db)
        rows = {}
        for b, c, v, pos, tok, tag in con.execute(
                "SELECT bnum,cnum,vnum,pos,token,tag FROM pos_tags"):
            rows.setdefault((b, c, v), []).append((tok, tag))
        con.close()
        return rows
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="bibles.pack")
    ap.add_argument("--translation", required=True)
    ap.add_argument("--pos", default=None, help="pos_tags db path")
    ap.add_argument("--book", type=int)
    ap.add_argument("--chapter", type=int)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    con = sqlite3.connect(args.pack)
    tid = con.execute(
        "SELECT id FROM translations WHERE slug LIKE ? OR identifier=? LIMIT 1",
        (f"%{args.translation}%", args.translation)).fetchone()[0]

    out = args.out or (args.pack + ".layers.db")
    odb = sqlite3.connect(out)
    odb.execute("""CREATE TABLE IF NOT EXISTS metrics(
        bnum INT, cnum INT, vnum INT, words INT, sentences INT,
        dialogue_pct REAL, passives INT, speech_verbs INT,
        pos_passives INT, PRIMARY KEY(bnum,cnum,vnum))""")

    pos = load_pos(args.pos or (args.pack + ".pos.db"))

    rows = []
    for b, c, v, text in pack_verses(con, tid, args.book, args.chapter):
        words = len(text.split())
        sentences = max(len(re.findall(r"[.!?]", text)), 1)
        quotes = QUOTE_RE.findall(text)
        dialogue_pct = min(len(quotes) / max(len(text), 1), 1.0)
        passives = len(PASSIVE_RE.findall(text))
        speech = len(SPEECH_VERBS.findall(text))
        tags = pos.get((b, c, v), [])
        pos_pass = sum(1 for j, (_, t) in enumerate(tags[:-1])
                       if t in AUX and any(tt == "VVN" for _, tt in tags[j+1:j+3]))
        rows.append((b, c, v, words, sentences, dialogue_pct,
                     passives, speech, pos_pass))

    odb.executemany("INSERT OR REPLACE INTO metrics VALUES (?,?,?,?,?,?,?,?,?)",
                    rows)
    odb.commit()
    print(f"{len(rows)} verses -> {out}")
    if pos:
        print(f"pos_tags joined for {len(pos)} verses")
    for r in rows[:3]:
        print(f"  {r[0]}:{r[1]}:{r[2]} words={r[3]} sent={r[4]} dlg={r[5]:.2f} "
              f"pass={r[6]} speech={r[7]} pospass={r[8]}")
    odb.close(); con.close()


if __name__ == "__main__":
    main()
