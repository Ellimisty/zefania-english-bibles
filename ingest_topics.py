"""Ingest Torrey's Topical Textbook (Zefania dictionary XML) -> topics tables.

  topics(id, name)            — item titles e.g. "Access to God"
  topic_sub(id, topic_id, title)  — sub-headings e.g. "Is by Christ"
  topic_refs(sub_id, bnum, cnum, vnum) — reflink mscope="b;c;v"

No existing tables are modified.
"""

import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

TTB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "SF_2006-03-02_ENG_TTB_(TORREY'S TOPICAL TEXTBOOK).xml")


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else "bible_graph.db"
    conn = sqlite3.connect(db, timeout=300)
    conn.execute("PRAGMA busy_timeout=300000")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS topics(id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE IF NOT EXISTS topic_sub(id INTEGER PRIMARY KEY,
            topic_id INT, title TEXT);
        CREATE TABLE IF NOT EXISTS topic_refs(sub_id INT,
            bnum INT, cnum INT, vnum INT);
        DELETE FROM topics; DELETE FROM topic_sub; DELETE FROM topic_refs;""")

    root = ET.parse(TTB).getroot()
    n_top = n_sub = n_ref = 0
    sub_rows, ref_rows = [], []
    for i, item in enumerate(root.iter("item"), 1):
        name = item.get("id", "").strip()
        conn.execute("INSERT INTO topics VALUES (?,?)", (i, name))
        n_top += 1
        for desc in item.iter("description"):
            title_el = desc.find("title")
            title = (title_el.text or "").strip() if title_el is not None else ""
            n_sub += 1
            sub_rows.append((n_sub, i, title))
            for rl in desc.iter("reflink"):
                m = re.match(r"(\d+);(\d+);(\d+)", rl.get("mscope", ""))
                if m:
                    ref_rows.append((n_sub, *map(int, m.groups())))
                    n_ref += 1
    conn.executemany("INSERT INTO topic_sub VALUES (?,?,?)", sub_rows)
    conn.executemany("INSERT INTO topic_refs VALUES (?,?,?,?)", ref_rows)
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_tref ON
                    topic_refs(bnum, cnum, vnum)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tsub ON topic_sub(topic_id)")
    conn.commit()
    print(f"topics={n_top} subs={n_sub} refs={n_ref}")
    conn.close()


if __name__ == "__main__":
    main()
