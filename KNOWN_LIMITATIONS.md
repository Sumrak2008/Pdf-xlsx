# Known Limitations

This document lists known, intentional limitations of PdfXlsx — behavior
that was a deliberate design trade-off rather than a bug. It is shipped
alongside the program and referenced from the per-document conversion
report.

## Table detection

- **At most one dominant table region is recovered per scanned (OCR) page**,
  by either detection strategy (`ocr-lines` or `ocr-text` in
  `table_detector.py`). A scanned page containing two or more separate
  small tables will typically have only the largest/most prominent one
  recovered, or have them merged into a single region. Direct (non-OCR)
  text-layer pages do not have this limitation — `text_extractor.py`
  detects each table on the page independently.
- Table detection on scanned pages relies on either a clearly ruled grid or
  consistent whitespace gaps between columns. A table with inconsistent
  spacing, partially missing rulings, or very tight column spacing may be
  mis-segmented (extra/missing column boundaries) or not detected at all
  and fall back to plain-text extraction.
- Nested tables (a table inside a table cell) are not specially recognized;
  the inner table's content is read as plain cell text.

## OCR accuracy and uncertainty

- OCR accuracy depends directly on scan quality: low resolution, blur,
  heavy noise, low contrast, or skew beyond what orientation detection can
  correct will all reduce recognition accuracy and increase the number of
  cells flagged as uncertain.
- The orientation-correction step (Tesseract OSD) for rotation "baked into"
  the pixels (no `/Rotate` flag in the PDF) is a best-effort heuristic: on
  pages with little or unevenly distributed text it can fail to reach a
  confident verdict, in which case the page is left as rendered and the
  page may be unreadable by OCR.
- Per-cell confidence is the average of that cell's recognized words; a
  cell containing one badly-recognized word among several good ones may
  still fall below the uncertainty threshold as a whole, or vice versa.

## Cell value interpretation

- Slashed dates (`DD/MM/YYYY` vs `MM/DD/YYYY`) are genuinely ambiguous
  whenever both readings are valid (e.g. `03/04/2024`). PdfXlsx always
  resolves this as `DD/MM/YYYY` and flags the cell uncertain with an
  explicit reason — it does not attempt to guess document locale from
  context.
- Only three thousands-separator number conventions are recognized
  (`1.234,56`, `1,234.56`, `1 234,56`); a number formatted with an
  unsupported convention is kept as plain text rather than mis-parsed.
- Only three currency notations are recognized (₽ / руб., $, €/EUR); other
  currencies are kept as plain text.
- Live Excel formulas are never reconstructed. Only the *value* the source
  PDF displayed is written — there is no way to recover a "formula" from a
  PDF, since PDFs never contain one in the first place.

## Documents

- Password-protected PDFs are not opened or decrypted under any
  circumstances (this is intentional, not a missing feature) — the user
  must remove the password themselves before conversion.
- A corrupted or non-PDF file is reported with a clear Russian error
  message and skipped; it does not stop a batch of other files from being
  processed.
- Extremely large documents (very many pages, or very high effective scan
  resolution at a high configured OCR DPI) will take proportionally longer
  and use proportionally more temporary disk space; the program performs a
  best-effort, approximate free-space check before starting but does not
  hard-cap the size of documents it will attempt.

## Platform

- The program is built and tested for Windows 10/11, 64-bit, only. It is
  not packaged or tested for 32-bit Windows, ARM Windows, macOS, or Linux,
  even though the underlying Python code is platform-independent and is
  exercised on Linux in CI for testing purposes.
