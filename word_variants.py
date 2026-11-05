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

# Middle English / Wycliffe / Tyndale spellings -> canonical modern form
ME = {
    "bigynne":"begin","bigunne":"begin","bygynnynge":"beginning",
    "gaderide":"gather","gadered":"gathered","gadere":"gather",
    "heelide":"healed","heelide":"healed","heelith":"heal",
    "knewe":"know","knyght":"knight","knoue":"know","knowe":"know",
    "myghti":"mighty","nyght":"night","ryght":"right","syght":"sight",
    "lyght":"light","hygh":"high","saugh":"saw","sayde":"said",
    "seye":"say","seyde":"said","seyde":"said","tolde":"told",
    "solde":"sold","bolde":"bold","colde":"cold","holde":"hold",
    "whiche":"which","whil":"while","whanne":"when","werre":"war",
    "wyf":"wife","lyf":"life","wyne":"wine","synne":"sin",
    "fadir":"father","modir":"mother","bretheren":"brethren",
    "euere":"ever","neuere":"never","ouer":"over","vndir":"under",
    "aftir":"after","bifore":"before","aboue":"above","sone":"son",
    "sonne":"sun","worlde":"world","worde":"word","lord":"lord",
    "heuene":"heaven","erthe":"earth","watir":"water","fir":"fire",
    "foule":"fowl","foweles":"fowls","scheep":"sheep","scheeld":"shield",
    "swerde":"sword","werre":"war","werrede":"waged-war",
    "peple":"people","temple":"temple","disciplis":"disciples",
    "prohetis":"prophets","prestis":"priests","kyng":"king",
    "quene":"queen","lordes":"lords","seruaunt":"servant",
    "seruauntis":"servants","childre":"children","men":"men",
    "wommen":"women","foolis":"fools","wise":"wise","wnwise":"unwise",
    "cité":"city","cyte":"city","cytee":"city","flee":"flee",
    "sle":"slay","sleen":"slain","se":"see","seen":"seen",
    "go":"go","goon":"gone","comen":"came","cam":"came",
    "taak":"take","token":"took","maad":"made","maade":"made",
    "hadd":"had","hedde":"had","saide":"said","saugh":"saw",
    "bare":"bore","brake":"broke","fond":"found","stood":"stood",
    "sat":"sat","lay":"lay","layn":"lain","fleysh":"flesh",
    "fleisch":"flesh","blod":"blood","breed":"bread","deed":"dead",
    "dede":"dead","deeth":"death","lyue":"live","lyueth":"lives",
    "dye":"die","deyde":"died","hool":"whole","coold":"cold",
    "sooth":"sooth","treuthe":"truth","verray":"very","parfit":"perfect",
    "perfit":"perfect","poure":"poor","riche":"rich","stronge":"strong",
    "yonge":"young","olde":"old","newe":"new","trewe":"true",
    "fewe":"few","grete":"great","litel":"little","mydel":"middle",
    "good":"good","god":"god","euyll":"evil","euil":"evil",
    "hele":"heal","heleth":"heals","helpe":"help","hope":"hope",
    "loue":"love","loued":"loved","loueth":"loves","hatith":"hates",
    "dredith":"fears","drede":"fear","ferde":"feared","wondir":"wonder",
    "wondride":"wondered","wepte":"wept","slepte":"slept",
    "kepte":"kept","lafte":"left","raught":"reached",
    "wrouhte":"wrought","soughte":"sought","broughte":"brought",
    "thouhte":"thought","taughte":"taught","kaughte":"caught",
    "southe":"south","northe":"north","eest":"east","weste":"west",
    "faste":"fast","laste":"last","firste":"first","nexte":"next",
    "othir":"other","another":"another","ech":"each","suche":"such",
    "myche":"much","litil":"little","no":"no","nat":"not",
    "noght":"not","nought":"not","nouht":"not","yee":"yea",
    "yis":"yes","sothly":"truly","certis":"certainly","peraduenture":"perhaps",
}

SUFFIX = ("eth", "est", "th", "st", "ed", "es", "s")


def stems(w):
    yield w
    for s in SUFFIX:
        if w.endswith(s) and len(w) > len(s) + 2:
            yield w[:-len(s)]
    if w in ARCHAIC:
        yield ARCHAIC[w]
    if w in ME:
        yield ME[w]


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
