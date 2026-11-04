# Zefania XML English Bibles

A collection of English Bible translations in [Zefania XML](http://bgfdb.de/zefaniaxml/bml/) format, split into per-book, per-chapter files.

## Layout

- `*.xml` (root) — original Zefania XML files, one file per translation.
- `split/<source-file-stem>/<NN>_<Book>/<NNN>.xml` — one XML file per chapter,
  preserving the original `VERS` markup (including Strong's numbers where present).

Example:

```
split/SF_2009-01-23_ENG_KJV_(KING JAMES VERSION)/01_Genesis/001.xml
```

## Regenerating the split files

```
python split_books.py
```

## Linguistic graph engine (`build_graph.py`)

A SQLite-backed knowledge graph over all translations enforcing strict DRYness:

- **Shared token pool** — ~45M token instances collapse to ~92k unique token
  nodes; identical surface forms are never duplicated.
- **Translations as paths** — `verse_tokens` stores each translation's ordered
  sequence through the shared pool (shared prefixes literally share nodes).
- **Strong's anchor layer** — `<gr str="...">` markup is extracted into a
  shared Greek/Hebrew `strongs` table (`G`/`H` prefixed by book), enabling
  many-to-many semantic queries (e.g. how many English words map to *diakonos*).
- **Divergence metrics** — per-verse shared-prefix length and Jaccard
  vocabulary similarity against a reference translation (`similarity` table).

```
python build_graph.py ingest          # parse all *.xml -> bible_graph.db (~2.7 GB)
python build_graph.py metrics --ref KJV
python build_graph.py export James 1 1 --out james_1_1.json
```

`export` writes an [arrows.app](https://arrows.app)-compatible JSON graph:
Book → Chapter → Verse hierarchy, per-translation token chains (`NEXT:<slug>`
edges), and `TRANSLATES` edges into shared Strong's nodes. See
`james_1_1.json` for an example.

The prebuilt database is attached to the repo's Releases as
`bible_graph.db.gz` (the raw file exceeds GitHub's file-size limit).

## Notes

- `SF_2006-03-02_ENG_TTB_(TORREY'S TOPICAL TEXTBOOK).xml` contains no
  `BIBLEBOOK` elements (it's a topical index, not Bible text), so it has no
  split output.
- Some translations exist in multiple editions/revisions; folder names use the
  full original filename to keep them distinct.
