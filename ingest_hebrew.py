"""Ingest Open Scriptures morphological Hebrew Bible -> hebrew_words table.

mirrors ingest_greek.py for the OT truth layer:
  hebrew_words(bnumber, cnumber, vnumber, position,
               surface, lemma, strong_id -> strongs.id, morph)

Source: zachconc/vendor/morphhb/wlc/*.xml (OSIS, openscriptures/morphhb).
lemma="b/7225" carries inseparable prefixes before the Strong's number;
morph="HR/Ncfsa" is the OSHB morph code. Verse osisID "Gen.1.1".
"""

import glob
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

WLC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "zachconc", "vendor", "morphhb", "wlc")

BOOKS = {  # wlc filename -> bnumber (Zefania OT numbering)
    "Gen":1,"Exod":2,"Lev":3,"Num":4,"Deut":5,"Josh":6,"Judg":7,"Ruth":8,
    "1Sam":9,"2Sam":10,"1Kgs":11,"2Kgs":12,"1Chr":13,"2Chr":14,"Ezra":15,
    "Neh":16,"Esth":17,"Job":18,"Ps":19,"Prov":20,"Eccl":21,"Song":22,
    "Isa":23,"Jer":24,"Lam":25,"Ezek":26,"Dan":27,"Hos":28,"Joel":29,
    "Amos":30,"Obad":31,"Jonah":32,"Mic":33,"Nah":34,"Hab":35,"Zeph":36,
    "Hag":37,"Zech":38,"Mal":39,
}


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else "bible_graph.db"
    conn = sqlite3.connect(db, timeout=300)
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("""CREATE TABLE IF NOT EXISTS hebrew_words(
        bnumber INT, cnumber INT, vnumber INT, position INT,
        surface TEXT, lemma TEXT, strong_id INT, morph TEXT)""")
    conn.execute("DELETE FROM hebrew_words")

    strong_ids = {c: i for i, c in conn.execute(
        "SELECT id, code FROM strongs WHERE code LIKE 'H%'")}

    rows = []
    for path in sorted(glob.glob(os.path.join(WLC, "*.xml"))):
        fname = os.path.splitext(os.path.basename(path))[0]
        bnum = BOOKS.get(fname)
        if not bnum:
            continue
        for ev, el in ET.iterparse(path, events=("end",)):
            if not el.tag.endswith("verse"):
                continue
            m = re.match(r"\w+\.(\d+)\.(\d+)", el.get("osisID", ""))
            if not m:
                continue
            cnum, vnum = int(m.group(1)), int(m.group(2))
            ws = [w for w in el.iter() if w.tag.endswith("}w")]
            for pos, w in enumerate(ws):
                lemma = (w.get("lemma") or "")
                morph = w.get("morph")
                surf = "".join(w.itertext()).strip()
                # lemma "b/7225" -> strong H7225 (last numeric segment)
                sid = None
                mm = re.findall(r"\d+", lemma)
                if mm:
                    sid = strong_ids.get("H" + mm[-1])
                rows.append((bnum, cnum, vnum, pos, surf, lemma, sid, morph))
            el.clear()
        print(fname, len(rows), flush=True)

    conn.executemany("INSERT INTO hebrew_words VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_hb ON
                    hebrew_words(bnumber, cnumber, vnumber)""")
    conn.commit()
    linked = conn.execute(
        "SELECT COUNT(*) FROM hebrew_words WHERE strong_id IS NOT NULL"
        ).fetchone()[0]
    print(f"hebrew_words: {len(rows)} rows, {linked} linked to strongs")
    conn.close()


if __name__ == "__main__":
    main()
