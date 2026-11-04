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

## Notes

- `SF_2006-03-02_ENG_TTB_(TORREY'S TOPICAL TEXTBOOK).xml` contains no
  `BIBLEBOOK` elements (it's a topical index, not Bible text), so it has no
  split output.
- Some translations exist in multiple editions/revisions; folder names use the
  full original filename to keep them distinct.
