"""Sola-scriptura sermon assembler — 4 phases, scripture only.

  python sermon.py "Philippians 4:6" [bible_graph.db]

  Phase 1 anchor:       the verse itself.
  Phase 2 expansion:    verses sharing the anchor's Strong's roots
                        (definitional / semantic expansion).
  Phase 3 parallel:     computed synoptic/topical parallels.
  Phase 4 imperative:   topic-mate verses with command flavor.

All edges come from `xref` (built by xref.py); text is reconstructed
from graph tokens (approximate spacing -- packs are the exact source).
"""

import sqlite3
import sys

BOOKS = ("Genesis Exodus Leviticus Numbers Deuteronomy Joshua Judges Ruth "
         "1_Samuel 2_Samuel 1_Kings 2_Kings 1_Chronicles 2_Chronicles Ezra "
         "Nehemiah Esther Job Psalms Proverbs Ecclesiastes Song_of_Solomon "
         "Isaiah Jeremiah Lamentations Ezekiel Daniel Hosea Joel Amos "
         "Obadiah Jonah Micah Nahum Habakkuk Zephaniah Haggai Zechariah "
         "Malachi Matthew Mark Luke John Acts Romans 1_Corinthians "
         "2_Corinthians Galatians Ephesians Philippians Colossians "
         "1_Thessalonians 2_Thessalonians 1_Timothy 2_Timothy Titus "
         "Philemon Hebrews James 1_Peter 2_Peter 1_John 2_John 3_John "
         "Jude Revelation").split()
BMAP = {b.lower().replace("_", " "): i + 1 for i, b in enumerate(BOOKS)}


def verse_text(c, vid):
    rows = c.execute("""SELECT t.word FROM verse_tokens vt
        JOIN tokens t ON t.id=vt.token_id WHERE vt.verse_id=?
        ORDER BY vt.position""", (vid,)).fetchall()
    return " ".join(r[0] for r in rows)


def ref(c, vid):
    b, ch, v = c.execute(
        "SELECT bnumber, cnumber, vnumber FROM verses WHERE id=?",
        (vid,)).fetchone()
    return f"{BOOKS[b-1].replace('_',' ')} {ch}:{v}" if b <= len(BOOKS) \
        else f"[{b}] {ch}:{v}"


def get_verse(c, refstr):
    book, ref2 = refstr.rsplit(" ", 1)
    ch, v = ref2.split(":")
    b = BMAP[book.lower()]
    return c.execute(
        "SELECT id FROM verses WHERE bnumber=? AND cnumber=? AND vnumber=?",
        (b, ch, v)).fetchone()[0]


def top_edges(c, vid, kinds, n=4):
    ph = ",".join("?" * len(kinds))
    return c.execute(f"""SELECT v2, MAX(weight) FROM xref
        WHERE v1=? AND kind IN ({ph}) GROUP BY v2
        ORDER BY 2 DESC LIMIT ?""", (vid, *kinds, n)).fetchall()


def main():
    anchor_ref = sys.argv[1]
    db = sys.argv[2] if len(sys.argv) > 2 else "bible_graph.db"
    c = sqlite3.connect(db)
    vid = get_verse(c, anchor_ref)
    print(f"### {anchor_ref} — sola-scriptura exposition\n")

    seen = {vid}
    phases = [
        ("I. Anchor", [vid]),
        ("II. Definitional expansion",
         [v for v, _ in top_edges(c, vid, ("strong",))]),
        ("III. Illustrative parallel",
         [v for v, _ in top_edges(c, vid, ("parallel", "topic"))]),
        ("IV. Imperative application",
         [v for v, _ in top_edges(c, vid, ("topic",))]),
    ]
    for title, vids in phases:
        print(f"\n**{title}**")
        for v in vids:
            if v in seen and title != "I. Anchor":
                continue
            seen.add(v)
            print(f"- {ref(c, v)}: {verse_text(c, v)[:300]}")
    c.close()


if __name__ == "__main__":
    main()
