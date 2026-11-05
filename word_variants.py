"""Cluster spelling variants -> word_variants(surface, canonical).

For each lowercased token, find a canonical form = the most frequent
token sharing a normalized stem. Handles:
  - archaic suffixes: loveth->love, didst->do, -est/-eth endings
  - archaic spelling: begat/begot, sabbaoth, shew/show, whilst/while
  - inflections: servants->servant

Use: python word_variants.py [bible_graph.db]
"""

import sqlite3
import sys
from collections import defaultdict

ARCHAIC = {
    "shew":"show","sabbaoth":"sabaoth","whilst":"while","betwixt":"between",
    "thee":"thou","thy":"thine","hath":"have","doth":"do","hast":"have",
    "hadst":"have","shalt":"shall","wilt":"will","art":"be","wast":"be",
    "wert":"be","spake":"speak","begat":"beget","begot":"beget",
    "yea":"yes","nay":"no","aye":"yes","ye":"you","thou":"you",
    "unto":"to","unto":"to","thine":"your","wherefore":"why",
    "hereof":"of-this","thereof":"of-it","wherein":"in-which",
}

SUFFIX = ("eth", "est", "th", "st", "ed", "es", "s")


def stems(w):
    yield w
    for s in SUFFIX:
        if w.endswith(s) and len(w) > len(s) + 2:
            yield w[:-len(s)]
    if w in ARCHAIC:
        yield ARCHAIC[w]


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else "bible_graph.db"
    conn = sqlite3.connect(db, timeout=300)
    conn.execute("PRAGMA busy_timeout=300000")

    freq = {}
    for text, n in conn.execute(
            "SELECT t.lower, COUNT(*) FROM verse_tokens vt "
            "JOIN tokens t ON t.id=vt.token_id GROUP BY t.lower"):
        if text and all(ch.isalpha() or ch in "'-" for ch in text):
            freq[text] = freq.get(text, 0) + n
    words = sorted(freq)
    print(f"{len(words)} alphabetic tokens")

    # stem -> most frequent word with that stem
    canon = {}
    for w in words:
        best = canon.get(w)
        for s in stems(w):
            if s in freq and (best is None or freq[s] > freq[best]):
                best = s
            # stem may map to an even more frequent form
            canon.setdefault(s, w)
    # second pass: prefer the frequency-max for every stem key
    stem_best = defaultdict(lambda: (None, 0))
    for w in words:
        for s in stems(w):
            if freq[w] > stem_best[s][1]:
                stem_best[s] = (w, freq[w])

    conn.execute("""CREATE TABLE IF NOT EXISTS word_variants(
        surface TEXT PRIMARY KEY, canonical TEXT,
        n_surface INT, n_canonical INT)""")
    conn.execute("DELETE FROM word_variants")
    n = 0
    for w in words:
        best = None
        for s in stems(w):
            cand = stem_best.get(s, (None, 0))
            if cand[0] and cand[0] != w and (best is None
               or freq[cand[0]] > freq[best]):
                best = cand[0]
        if best:
            conn.execute("INSERT INTO word_variants VALUES (?,?,?,?)",
                         (w, best, freq[w], freq[best]))
            n += 1
    conn.commit()
    print(f"word_variants: {n}")
    for r in conn.execute(
            "SELECT surface, canonical FROM word_variants "
            "WHERE canonical != surface ORDER BY n_surface DESC LIMIT 15"):
        print(" ", r)
    conn.close()


if __name__ == "__main__":
    main()
