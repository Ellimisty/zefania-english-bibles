# Shopping list — resources to acquire

Resources referenced across the chats, with what we already have.

## Acquire (open/public)

- [x] **MACULA datasets** — cloned: Clear-Bible/macula-greek +
      macula-hebrew (syntactic trees for both testaments)
- [x] **OpenBible cross-references** — 344,800 voted edges ->
      `cross-references/cross_references.txt`, ingested as
      xref kind='openbible' (655k edges)
- [x] **SWORD modules** — sword_get.py downloads all 464 rawzip
      modules; TSK, BDBGlosses_Strongs, Nave, Easton, ISBE,
      AbbottSmith, Smith fetched; sword_read.py decodes
      zCom/zText/zLD formats (no e-Sword key needed)
- [ ] **Dead Sea Scrolls corpus** (Qumran digital) — DSS Hebrew/Aramaic
      texts for period-matched corpus expansion
- [ ] **Josephus** (Greek, public domain via Perseus/TLG) — corpus expansion
      for n-gram probability
- [ ] **Greek LXX text** (Rahlfs/Swete, PD) — the Septuagint proper; we
      only have Brenton's *English* translation (LXXE)
- [ ] **Treasury of Scripture Knowledge (TSK)** — the classic public-domain
      cross-reference set (~500k links); often the base xref source
- [ ] **LSJ / Abbott-Smith Greek lexicons** (Perseus/Internet Archive) —
      fuller definitions beyond Strong's one-line glosses
- [ ] **Gesenius Hebrew Grammar** (PD) — for decoding morphhb morph codes
      into readable forms
- [ ] **Universal Dependencies Ancient Greek** (Perseus TLG treebanks)
- [ ] **e-Sword RSC codec decoder** — 11+ modules (.bblx/.lexx/.dctx/
      .topx/.refx) are SQLite but content blobs are RSC-encrypted;
      need e-Sword app export or a community decoder (es2text, the
      'esword' crate) — THEN all 182 modules are readable
- [ ] **e-Sword module formats spec** (.bblx/.cmtx/.dctx/.topx) — for
      direct e-Sword module import (they're SQLite)
- [ ] **Spelling-variant datasets** — more ME spelling maps if we want
      to expand word_variants beyond hand curation

## Own (already in corpus/derived)

- Strong's Hebrew+Greek lexicons (openscriptures, morphgnt)
- morphhb WLC (306k Hebrew words w/ morph)
- MorphGNT SBLGNT (137k Greek words w/ parsing)
- LEB translation (bracketed-addition data exists in file)
- Brenton's LXX English (LXXE)
- Torrey's Topical Textbook (61k topic refs)
- 5 source-tagged translations (KJV+, RWEBSTER, Luther1545, Elberfelder,
  Schlachter)
- ~68 untagged translations with 30M projected tags
- USAS single/MWE lexicons (74k entries)
- 844 language packs sorted

## Licensing notes

- Some converted files carry copyright `status` fields (e.g., Afrikaans
  1983 © Bybelgenootskap) — don't redistribute those packs
- ESV/NIV/NASB are proprietary — only via official APIs with limits
- Crosswire SWORD modules are the largest public pool for future ingest
