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

`export` writes an [arrows.app](https://arrows.app)-compatible JSON graph
following the DAG-export conventions from `zachconc/antconc_ngram`:

- Book → Chapter → Verse hierarchy (`pathGroup: "CANON"`)
- per-translation token chains (`NEXT:<slug>` edges) plus `TRANSLATES`
  edges into shared Strong's nodes, all tagged `pathGroup: <slug>`
- n-gram layer nodes for n=2..3 built from **non-overlapping adjacent**
  token partitions, with `PART_OF` edges from constituent tokens and
  `MERGE` edges (`branch: "left"/"right"`) for every valid binary
  decomposition
- relationship ids are unique `e0, e1, ...` (never colliding with the
  `n`-prefixed node ids); nodes carry `layer_index`/`size` properties

See `james_1_1.json` for an example. Use `--format simple` for the original
token-chains-only export (hierarchy + `NEXT:<slug>` + `TRANSLATES` edges,
no n-gram layers); `--format dag` is the default.

The prebuilt database is attached to the repo's Releases as
`bible_graph.db.gz` (the raw file exceeds GitHub's file-size limit).

## Greek truth layer (`ingest_greek.py`)

`ingest_greek.py` adds a translation-agnostic Greek NT layer to
`bible_graph.db` (no existing tables are modified):

    greek_words(translation_id NULL, bnumber, cnumber, vnumber, position,
                surface, lemma, strong_id -> strongs.id, parsing)

Source: MorphGNT SBLGNT (`github.com/morphgnt/sblgnt`, vendored at
`zachconc/vendor/sblgnt_morphgnt/`, gitignored) with lemma→Strong's from
`github.com/morphgnt/morphological-lexicon` `lexemes.yaml`
(`zachconc/vendor/lexemes.yaml`). Book files `61-Mt`..`87-Re` map to
`bnumber` 40..66. ~137.5k words, ~5.2k distinct Strong's codes linked;
~500 rows (mostly punctuation-bearing forms / unmapped lemmas) keep
`strong_id` NULL.

Sample query — English words in KJV that realize each Greek lemma of
James 1:1:

```sql
SELECT w.lemma, s.code, t.text
FROM greek_words w
JOIN strongs   s  ON s.id = w.strong_id
JOIN verses    v  ON v.bnumber = w.bnumber AND v.cnumber = w.cnumber
                  AND v.vnumber = w.vnumber
JOIN token_strongs ts ON ts.verse_id = v.id AND ts.strong_id = w.strong_id
JOIN verse_tokens  vt ON vt.translation_id = ts.translation_id
                     AND vt.verse_id = ts.verse_id
                     AND vt.position = ts.position
JOIN tokens t ON t.id = vt.token_id
WHERE w.bnumber = 59 AND w.cnumber = 1 AND w.vnumber = 1
ORDER BY w.position;
```

## Reader pack (`build_pack.py` / `read_pack.py`)

`bibles.pack` is a DRY, reader-optimized SQLite bundle: one shared token
dictionary, verse *sequences* deduplicated across translations (identical
verses stored once), and a `verses` index mapping
(translation, book, chapter, verse) → sequence. The full 67-translation
pack is ~168 MB vs ~273 MB of source XML; a Rust GUI reader lives in
`zachconc/antconc_ngram` (`cargo run --bin reader -- bibles.pack`).

```
python build_pack.py                      # full pack -> bibles.pack
python build_pack.py --list               # list translation identifiers
python build_pack.py --translations kjv --out bibles-kjv.pack
python read_pack.py list
python read_pack.py read KJV James 1 1 [--strongs]
```

`--translations` takes comma-separated substrings matched against each
module's slug/identifier/name. Custom bundles and incremental extension:

```
# preview the marginal cost of adding translations to an existing pack
python build_pack.py --base bibles-kjv.pack --translations web --estimate

# actually merge them into a new bundle
python build_pack.py --base bibles-kjv.pack --translations web \
                     --out bibles-kjv-web.pack
```

Per-file output reports verses, new sequences, new dictionary words,
new Strong's codes, and ~MB of sequence data — i.e. the true cost of each
addition after dedup. Bundles ship as plain `.pack` files; the reader
binary takes a path argument, so any subset works without code changes.

Compression: `xz -6` shrinks packs ~4× (full pack 168 MB → 42 MB,
KJV+WEB bundle 44 MB → 9.5 MB) and decompresses in ~1–2 s. Both readers
accept `.pack.xz` directly — `read_pack.py` and the Rust reader
decompress to a temp file on open.

## Database backends

The same graph is mirrored into Neo4j and SurrealDB (both resumable):

```
python migrate_neo4j.py      # bolt://localhost:7687, --start-at <stage>
python migrate_surrealdb.py  # ws://127.0.0.1:8000/rpc, --start-at <stage>
```

## Notes

- `SF_2006-03-02_ENG_TTB_(TORREY'S TOPICAL TEXTBOOK).xml` contains no
  `BIBLEBOOK` elements (it's a topical index, not Bible text), so it has no
  split output.
- Some translations exist in multiple editions/revisions; folder names use the
  full original filename to keep them distinct.
- `GER/` holds 49 German Zefania modules (zips); extract and point
  `build_graph.py`/`build_pack.py --src` at the XMLs to ingest them.
