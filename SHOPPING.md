# Shopping list — resources to acquire

Resources referenced across the chats, with what we already have.

## Acquire (open/public)

- [ ] **MACULA datasets** — syntactic trees for Hebrew OT + Greek NT
      (Biblical Humanist/openscriptures; the real "spaCy for biblical
      languages" — parsing, not just morphology)
- [ ] **OpenBible cross-references** — verse→verse xref edges
      (feeds Project A's xref layer)
- [ ] **Dead Sea Scrolls corpus** (Qumran digital) — DSS Hebrew/Aramaic
      texts for period-matched corpus expansion
- [ ] **Josephus** (Greek, public domain via Perseus/TLG) — corpus expansion
      for n-gram probability
- [ ] **Greek LXX text** (Rahlfs/Swete, PD) — the Septuagint proper; we
      only have Brenton's *English* translation (LXXE)
- [ ] **Universal Dependencies Ancient Greek** (Perseus TLG treebanks)
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
