# Feature roadmap (mined from chats + built so far)

Consolidated plan. Architecture invariant from the chats:
**Layer 0 immutable canonical text / Layer 1 deterministic algorithmic
edges / Layer 2 inferred edges with confidence + review / Layer 3 derived
experiences.** Bug rule: never mutate Layer 0; every inferred edge carries
method + confidence + reversibility check.

## Done (see README layer table)

- DRY pack format + shared dictionary + dedup sequences + xz bundles
- Strong's anchors, lemmas (Greek + Hebrew), strong_words, strong_equiv,
  strong_audit, strong_class
- CLAWS POS (`pos_tags` sidecar), USAS semantic (`usas_tags`/`usas_mwe`),
  per-verse metrics (`bible_layers`), verse alignment (`align` sidecar)
- word_variants (archaic + ME), word→code prior, token_strongs_proj
  (~30M projected tags, method+confidence), strong_review buckets
- OSHB Hebrew morphology (306k words), Torrey's topics (61k refs),
  synoptic parallels (26k pairs), QA suite (qa_checks.py)
- Reader: browse/search/compare(diff-highlight)/Strong's inspector/
  concordance/projected-tag overlay/divergence coloring/bookmarks/
  theme/file-picker/temp-staging
- 844 per-language packs; ingest/migration tooling; mojibake QA + repair

## Project A — Sola Scriptura engine (sermon/devotional generator)

Goal from chat: devotionals composed **100% of scripture** — a "Superverse"
where every sentence decompresses into cross-references, not human prose.

- [ ] `xref` layer: cross-reference edges verse→verse
      (sources: Torrey's refs done; OpenBible crossrefs; our own
      `parallels` + `strong_words` co-occurrence + `similarity`)
- [ ] `expansion`: click a phrase → decompress into its scriptural
      expansions (Strong's co-definition verses, OT/NT overlays,
      imperative parallels) — Phase 1-4 assembler from the chat
- [ ] `sermon.py <topic|anchor>`: 4-phase exposition assembler
      (anchor verse → definitional expansion → illustrative parallel →
      imperative application), all from graph layers
- [ ] confidence gates: candidate edges only activate in "exploratory"
      mode until review-approved (strong_review is the seed table)

## Project B — Expanding/contracting visual map (the original DAG idea)

- [ ] 12-byte binary DAG nodes (LeftChildID+RightChildID+frequency)
      — exists in antconc/graph_feed; needs pack-side table `dag_nodes`
- [ ] interactive visualizer: expandable compound nodes
      (egui eg_graph or three-d/WebGL canvas for >10k nodes)
- [ ] arrows.app export is done; richer: cytoscape/gexf exports
- [ ] compression view: pruned single-use high-N nodes (frequency>1 kept)

## Project C — Review dashboard ("Scribe gate")

- [ ] strong_review UI: approve/reject/adjust projected tags +
      conflict candidates; writes `strong_review_verdicts`
- [ ] equivalence proposal queue (strong_equiv candidates 283)
- [ ] MWE/USAS spot-checks; mojibake/glued-token repair queue
      (Rotherham 1967, ORTHJBC 357, German ~600 flagged)

## Project D — Remaining data gaps

- [ ] Middle-English second pass on word_variants (Wycliffe/Tyndale
      unmatched ~544k)
- [ ] spelling-aware projection rerun for ME translations
- [ ] POS-aware USAS disambiguation once pos_tags complete
- [ ] verse-alignment sidecar generalization (per-pair align db)
- [ ] pack-side `dag_nodes` + n-gram feeder resume (45/110 done)
- [ ] glued-token source repairs (Rotherham etc. — needs per-file
      spacing fix, QA-flagged)

## Project E — Re-Sword (e-Sword ground-up rebuild, from the PRD chat)

The reader + packs are the foundation; this is the productized app on top.

- [ ] **Interlinear mode**: stacked view English + Greek/Hebrew + transliteration + morphology (greek_words + hebrew_words ready)
- [ ] **Color-coded morphology**: inline POS/morph coloring (pos_tags + parsing data ready)
- [ ] **Hover tooltips**: Strong's/cross-ref/morph popups without clicks (inspector is close; needs hover variant)
- [ ] **Semantic NL search**: "verses about anxiety when starting something new" — embedding or USAS-based query over all translations
- [ ] **Dockable workspaces**: saved layouts (parallel-reading vs word-study)
- [ ] **Markdown notes + bidirectional [[links]]**: notes keyed to verse refs, wiki-style graph of personal study
- [ ] **Module ecosystem**: packs ARE modules — needs a downloader/UI for .pack.xz bundles + custom bundle builder front-end
- [ ] **Sync (optional layer)**: notes/highlights sync via diff-push; offline-first stays the rule
- [ ] **AI summarization** (future): commentary digests — deferred, but the xref/topics layers are the data backend
- [ ] **Collab study** (future): shared notebooks for groups
- [ ] n-gram/linguistic-pattern tool: antconc_ngram plugs in as the analysis engine — authorship-anomaly/frequency views over greek_words

## Project F — Ultra/Fractal Bible (from DRY-Bible + Story-mining chats)

- [ ] **Ultra Verses**: merge near-identical passages into canonical
      "superverses" (parallels + align sims already compute the overlap)
- [ ] **Fractal/RAID Bible**: pericope-level derivability tree —
      pairwise verse↔verse similarity chunked by book (parallel jobs,
      store into `similarity`-style table per book pair)
- [ ] **Story/truth mining**: thematic arcs (Cain→mercy/mark, cities→
      Babel, "lies told about God") — topical graph over topics+USAS+
      parallels; LLM-assisted extraction → reviewed `story_threads`
- [ ] **Translation families**: cluster translations by word-order/
      vocabulary (similarity matrix -> "KJV-family", "NHEB-family", etc.)

## Project G — e-Sword module integration (user's library, 182 files)

BLOCKER: e-Sword 11+ modules are RSC-encrypted blobs inside SQLite
(sqliteplus_license). Need e-Sword's own export, a community RSC
decoder, or older 9.x plaintext modules. `ingest_esword.py` scaffolds
the pipelines; decode hook pending.

Once decoded:
- [ ] `.lexx` (bdb, thayer, mounce, kjc) → `lexicon_extra(code, dict,
      defn)` — real lexicon definitions joined on Strong's codes;
      upgrades the reader's inspector panel
- [ ] `.dctx` topical (nave, torrey, scofield refs) → `topic_refs` +
      `xref kind='nave'` — more sermon-engine edges
- [ ] `.dctx` general (easton, hastings, hitchcock, isbe, webster,
      fausset, smith, vines-ot/nt) → `dictionary(topic, dict, defn)`
      layer; name/place lookups in reader
- [ ] `.topx` (Christian Faith) → `xref kind='esword_topx'`
- [ ] `.cmtx` commentaries (barnes, clarke, bullinger, cambridge,
      vincent, wesley, spurgeon, scofield) → `commentary(verse_id,
      source, text)` — reader "commentary pane" per verse
- [ ] `.refx` books → `book_chapters(book, ch, text)` sidecar;
      searchable long-form. Library now includes:
      ante-nicene fathers (9 vols), Josephus (Antiquities, Wars),
      E.M. Bounds prayer works (7), Tozer (Knowledge of the Holy),
      Edersheim (Jewish Social Life, Life and Times of Jesus),
      F.B. Meyer character studies (Joseph, David, Jeremiah, Peter),
      Torrey works, Wurmbrand, In His Steps, Foxe-style devotionals
- [ ] `tsk.cmtx` (Treasury of Scripture Knowledge) — 29,675
      VerseCommentary entries; decode Comments -> parse ref lists ->
      `xref kind='tsk'` (parser written in ingest_esword.py)
- [ ] `.mapx` maps → probably image assets; low priority
- [ ] `.bblx` bibles → redundant with Zefania XMLs; skip except
      `+`-tagged variants if they carry Strong's we lack
- [ ] TSK: not installed; grab from e-Sword downloads or use
      OpenBible (already in) + Nave's as xref sources

## Guardrails (from the chats — now partially built)

- qa_checks.py regression suite — run before/after every ingest or
  layer build; add checks as new layers land
- immutable Layer 0: all inferred layers are separate tables/sidecars
- method + confidence columns on every projected row
- round-trip: pack decode == source tokens (already verified by design;
  add a qa round-trip test that re-encodes a sample verse)
- review-before-commit for inferred edges (strong_review_verdicts)
