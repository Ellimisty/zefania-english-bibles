# Zefania XML Bibles — extensible linguistic & translation-analysis system

An offline-first, strictly-DRY corpus engine over Zefania XML Bible files.
The goal: a reader/analyzer where you can open any Bible in the collection,
compare translations structurally and semantically, inspect original-language
relationships, and drop in new translations without redesigning anything.

Motivation: translations overlap in small regions but diverge sharply in
grammar, structure, vocabulary, and translation philosophy — "BBE and KJV
are identical to that point, and then they diverge a lot." Every shared
token, verse, and relationship should be stored exactly once, and every
analytic layer should ride on top of that deduplicated core.

## Design principles

- **DRY everything** — one shared token dictionary; identical verses stored
  once and referenced by many translations; identical Strong's codes pooled.
- **Exact reconstruction** — punctuation, spacing at markup boundaries,
  token order, and Strong's positions all round-trip byte-perfectly.
- **Many-to-many everywhere** — `diakonos` → servant/minister/deacon; one
  English word → several Greek roots; nothing assumes 1:1 mappings.
- **Layered analysis** — each knowledge layer is an independent table/sidecar
  keyed by (translation, book, chapter, verse[, position]); layers compose
  but never rewrite each other.
- **Offline-first** — SQLite everywhere; optional mirrors into Neo4j and
  SurrealDB for graph queries.

## Data layers (current & planned)

| Layer | Where | Contents | Status |
|---|---|---|---|
| Token pool | pack `dictionary` / graph `tokens` | shared surface forms | done |
| Verse sequences | pack `sequences` / graph `verse_tokens` | deduplicated token streams + space bits | done |
| Strong's anchors | `strongs_dict`, `token_strongs` | G/H codes from `<gr str>` markup | done |
| **strong_words** | pack `strong_words` | every surface word realizing each code (word→root map) | done |
| **Lexical metadata** | `strongs_dict.lemma/gloss` | Greek (morphgnt lexemes.yaml) + Hebrew (openscriptures HebrewStrong.xml) | done |
| **strong_equiv** | graph `strong_equiv` | equivalent/related/candidate code pairs from cross-translation audit | done |
| **strong_class** | graph `strong_class` | prefix/particle codes (min-, eth, hoti) | done |
| **strong_audit** | graph `strong_audit` | per-position conflicts/gaps between tagged translations | done |
| Divergence metrics | graph `similarity` | shared-prefix len + Jaccard vs reference translation | done |
| Greek truth layer | graph `greek_words` | morphgnt SBLGNT surface/lemma/parsing | done |
| N-grams | graph `ngrams`, `translation_ngrams` | corpus n-gram frequencies (Rust feeder) | partial (45/~110 done) |
| **CLAWS POS** | `<pack>.pos.db` `pos_tags` | UCREL C7 tags per token position | tooling done, KJV James 1 verified |
| **USAS semantic** | planned `usas_tags` | single-word + MWE lexicons in `book/lexicons/` | pending |
| **bible_layers metrics** | `<pack>.layers.db` `metrics` | words/sentences/dialogue%/passives/speech-verbs per verse | tooling done |
| Strong's projection | planned | codes projected onto untagged translations (vocab priors + elimination + phrase spans) | designed |
| **Verse alignment** | `<pack>.align.db` | token-level difflib alignment between translation pairs; "identical to that point then diverge" as data; powers diff-highlighted compare view | in progress |
| **OSHB Hebrew morphology** | graph `hebrew_words` | morphhb WLC surface/lemma/morph per Hebrew word — OT equivalent of greek_words (306,785 words, 98% Strong's-linked) | done |
| **Torrey's topics** | graph `topics` | `SF_2006-03-02_ENG_TTB` is a topic→verses index (no BIBLEBOOK) — parse into topical layer | pending |
| **Synoptic parallels** | graph `parallels` | Gospel harmony / Eusebian apparatus mapping same-pericope passages | pending |
| **USAS semantic** | `<pack>.usas.db` `usas_tags` | semantic-field tags via lexicon join + lemmatizer (`ingest_usas.py`; ~99% coverage) | tooling done |
| **Reader concordance** | GUI | every verse where a Strong's root appears — clickable refs in inspector | done |
| **Divergence coloring** | GUI + sidecar | `similarity` scores exported to pack sidecar; color verses vs chosen reference | pending |
| **Bookmarks** | GUI | persist last reading position per pack | done |
| **Spelling-variant table** | planned | begat/begot, sabbaoth-era variants for cross-era matching (feeds projection) | pending |
| Hebrew morphology | future | OT parsing beyond lemma/gloss | future |

## Pipelines

### Graph DB (`build_graph.py`) → `bible_graph.db`

The analysis backbone (~45M+ token instances, 110+ translations):

```
python build_graph.py ingest          # parse all *.xml
python build_graph.py metrics --ref KJV
python build_graph.py export James 1 1 --out james_1_1.json   # arrows.app
```

Export formats: `--format dag` (default: hierarchy + token chains +
TRANSLATES + n-gram layer nodes with PART_OF/MERGE edges) or
`--format simple` (token chains only).

### Reader packs (`build_pack.py`) → `*.pack` / `*.pack.xz`

Indexed-random-access SQLite bundles for the GUI reader. Tables:
`translations`, `dictionary`, `sequences` (tokens+spaces+strongs+sha),
`strongs_dict` (code, lemma, gloss), `strong_words`, `verses`, `meta`.

```
python build_pack.py                          # full pack
python build_pack.py --list                   # what's in the source dir
python build_pack.py --translations kjv --out bibles-kjv.pack
python build_pack.py --base bibles-kjv.pack --translations web --estimate
python build_pack.py --base bibles-kjv.pack --translations web \
                     --out bibles-kjv-web.pack
```

`--src <dir>` builds from any folder of Zefania XMLs (batch per language).
Parallel XML parse + `sha`-keyed base merges keep builds linear.
`xz -6` → ~4× smaller; both readers accept `.pack.xz` directly.

### Sidecar DBs (per-pack, resumable)

- `tag_claws.py` — CLAWS POS tagging via UCREL web service
  (requests-first, playwright fallback, ~85k words/submission):
  `python tag_claws.py --pack bibles-kjv.pack --translation KJV`
- `bible_layers.py` — per-verse metrics; joins `.pos.db` automatically:
  `python bible_layers.py --pack bibles-kjv.pack --translation KJV`

### Strong's integrity

- `strong_audit.py` — aligns tagged translations position-by-position
  (shared sequences = exact, difflib = near); writes `strong_audit`
  conflicts/gaps
- `strong_equiv.py` — curated equivalent/related pairs (halakh spellings,
  qere/keriv, agapao/agape…) + auto-flagged `candidate` conflicts for review

### Mirrors

```
python migrate_neo4j.py      # bolt://localhost:7687
python migrate_surrealdb.py  # ws://127.0.0.1:8000/rpc
```

Both support `--start-at <stage>` for resumable migration.

## GUI reader

`zachconc/antconc_ngram` (Rust, egui):

- translation/book/chapter browsing, **search** within a translation,
  **parallel compare** view, **Strong's** highlighting + click-inspector
  (code, lemma, gloss, *every word* the root collapsed into via
  `strong_words`), chapter ◀▶ nav, **Go to** `James 1:5` box,
  per-verse copy button, light/dark theme
- double-click friendly: no-arg launch tries `bibles.pack` nearby, else
  file picker; works on a temp copy so packs can be rebuilt while open
- `cargo build --bin reader` → `target/debug/reader.exe <pack>`

## Corpus layout

- `*.xml` here — English Zefania modules (incl. JW-decrypted set: NWT
  2013/1984, KJV-JW, ASV-JW, Living English, Emphasized, Kingdom
  Interlinear — all "(Jehovah's Witnesses Edition)")
- `split/<slug>/<book>/<ch>.xml` — per-chapter splits (`split_books.py`)
- `D:\Bible\bibles\bibles_sorted\<LANG>/` — sorted multi-language tree:
  Zef-XML zips extracted + Holy-Bible-XML-Format files converted to
  Zefania (`D:\Bible\bibles\sort_bibles.py`, `manifest.csv` flags
  content-duplicate files across archives)
- `D:\Bible\bibles\packs\bibles-<LANG>.pack` — per-language reader packs

## Notes

- Copyright status varies by module; some converted files carry explicit
  `status` copyright strings — check before redistributing.
- `SF_2006-03-02_ENG_TTB_*.xml` is a topical index (no BIBLEBOOK) — skipped.
- JW files contain no `str=` Strong's markup, including the interlinear.
