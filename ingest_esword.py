"""Ingest e-Sword modules (.bblx/.lexx/.dctx/.topx/.refx) -> bible_graph.db.

STATUS: e-Sword 11+ modules are SQLite but their content blobs use the
proprietary RSC codec (compressed+encrypted). sqliteplus_license table
confirms. To use them we need ONE of:
  a) e-Sword app itself: open module -> Print/Export -> text/RTF
  b) a community decoder (e.g. the 'esword' rust crate, es2text,
     or the RSC codec implementations on GitHub)
  c) older e-Sword 9.x modules (.bbl/.cmt/.dctx plain-text era)

When decoded, the target tables are already designed:
  lexx  (Topic=H/G code, Definition)   -> lexicon_extra(code, dict, defn)
  dctx  (Topic, Definition)            -> dictionary(topic, dict, defn)
  dctx  Nave/Torrey topical            -> topic_refs (kind='nave')
  topx  topical cross-refs             -> xref (kind='esword_topx')
  cmtx  commentary notes               -> commentary(verse_id, source, text)
  bblx  translations                   -> redundant w/ Zefania XMLs

Usage once a decoder exists:
  python ingest_esword.py <module> [--decoded file.rtf]
"""

import sqlite3
import sys


def try_decode(blob):
    """Placeholder: returns plaintext once RSC codec is available."""
    raise NotImplementedError(
        "RSC codec not implemented — see module docstring for options")


def list_module(path):
    c = sqlite3.connect(path)
    for name, in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"):
        if name.startswith("sqlite"):
            continue
        n = c.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({name})")]
        print(f"  {name}: {n} rows {cols}")
    c.close()


if __name__ == "__main__":
    print(sys.argv[1])
    list_module(sys.argv[1])
