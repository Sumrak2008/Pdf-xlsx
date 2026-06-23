# Architecture

## Overview

PdfXlsx is a Windows desktop application (PySide6 GUI over a pure-Python
conversion core) that turns a PDF into a real, editable `.xlsx` workbook.
The core is GUI-agnostic and fully synchronous; the GUI runs it on a
background `QThread` so the UI stays responsive.

```
src/pdfxlsx/
  __main__.py            python -m pdfxlsx entry point
  version.py              single source of truth for the app version
  gui/
    app.py                QApplication bootstrap
    main_window.py        file queue, settings form, progress, log panel
    widgets.py            FileDropListWidget (drag-and-drop)
    worker.py             QThread wrapper around core.pipeline
  core/
    pipeline.py           per-document and per-page orchestration
    pdf_classifier.py     text / scanned / blank page classification
    text_extractor.py     direct extraction via pdfplumber (no OCR)
    image_utils.py        rasterization + rotation correction (pypdfium2, OSD)
    ocr_engine.py         pytesseract wrapper, bundled-binary-only
    table_detector.py     table structure recovery from a rasterized image
    cell_typing.py        RawCell -> TypedCell (value typing, uncertainty)
    xlsx_writer.py        TypedTable -> real openpyxl cells
    report.py             <name>_conversion_report.txt generation
    models.py             shared dataclasses between stages
    config.py             ConversionSettings, OcrLanguage, SheetSplitMode
    errors.py             exceptions with ready Russian user_message
    paths.py               frozen-build-relative path resolution
    tempfiles.py          per-run temp dir, disk space checks, cleanup
```

## Pipeline: one PDF in, two files out

`pipeline.run_conversion(pdf_path, settings)`:

1. Resolve output paths (`<name>_editable.xlsx`, `<name>_conversion_report.txt`)
   next to the source PDF, or in `settings.output_dir` if set.
2. Check the output folder is writable (`tempfiles.can_write_to`) and that
   there is enough free disk space (`tempfiles.estimate_required_mb` vs.
   `tempfiles.free_space_mb`) — raises `OutputNotWritableError` /
   `InsufficientDiskSpaceError` *before* any processing starts.
3. `convert_document(...)`: open the PDF with both `pdfplumber` (structure)
   and `pypdfium2` (rasterization), process every page (see below), and
   assemble a `DocumentResult`.
4. `xlsx_writer.write_document(...)` and, if enabled,
   `report.write_report(...)`.

Opening the PDF (`_open_pdf`) distinguishes a genuinely corrupt file from a
password-protected one: most encryption errors carry "password"/"encrypt"
in their message, but `pdfminer.pdfdocument.PDFPasswordIncorrect` carries
an *empty* message, so the exception's type name is also checked.

## Per-page routing

For each page, `pdf_classifier.classify_page` looks at the number of
embedded characters (`page.chars`) and the fraction of the page area
covered by embedded images:

- `char_count >= MIN_CHARS_FOR_TEXT_PAGE` (8) → `PageKind.TEXT`
- otherwise, `image_area_ratio >= MIN_IMAGE_AREA_RATIO_FOR_SCAN` (0.5), or
  any non-zero text/image at all → `PageKind.SCANNED`
- nothing on the page at all → `PageKind.BLANK` (skipped, recorded as such)

`pipeline._process_page` then applies one rule: **a page is read directly
only when it is `PageKind.TEXT` *and* `rotation == 0`.** Any rotation —
even on an otherwise clean text page — routes through rasterization + OCR
instead, because `pdfplumber`'s coordinate handling for rotated pages is
unreliable, while `pypdfium2` applies the page's `/Rotate` flag correctly
during rendering regardless. This means a rotated text page is classified
`SCANNED` for routing purposes but still recovers actual table structure
(via `table_detector`, not just free text) once rasterized.

Per-page errors are caught and recorded on that page's `PageOutcome.error`;
processing continues with the next page. Only `OcrEngineUnavailableError`
aborts the whole document, since every remaining OCR page would fail
identically.

## Direct extraction (text_extractor.py)

Runs pdfplumber's table-finder twice — `"lines"` (ruled-grid) and `"text"`
(whitespace-clustering) strategies — keeps both sets of detections, and
where their bounding boxes overlap by more than 50%, keeps the lines-based
one (it carries real merge/grid geometry). Merged cells are recovered by
building a global row/column boundary axis from the union of all anchor-cell
edges and mapping each anchor cell's bbox onto it. Free text outside any
detected table is extracted by cropping the table bounding boxes out of the
page before calling `extract_text()`.

Every direct-extraction `RawCell` has `confidence=100.0, source="text"` —
this is what makes OCR-confidence-based uncertainty never apply to
PDFs that were already real text.

## OCR path (image_utils.py, table_detector.py, ocr_engine.py)

1. `image_utils.rasterize_page` renders the page via `pypdfium2`, applying
   the PDF's own `/Rotate` flag during rendering (`pdfium`'s rotation
   argument is inverted relative to the PDF convention — see
   `_quarter_turn_for_pdfium`). If the page had no `/Rotate` flag, it then
   runs Tesseract's orientation-and-script detection (OSD) on the rendered
   image and physically rotates it if OSD is confident
   (`confidence >= OSD_MIN_CONFIDENCE = 0.5`) — this is the "baked-in
   rotation" case (e.g. a photographed page fed in sideways with no
   metadata recording that fact).
2. `table_detector.detect_and_extract_tables` tries two strategies, in
   order, returning the first that succeeds:
   - **`ocr-lines`**: binarize the image (Otsu threshold), find long
     horizontal/vertical runs via morphological opening (anything shorter
     than `MIN_LINE_INCHES` is treated as a glyph stroke, not a ruled
     line), cluster them into grid coordinates, validate each candidate
     line actually spans the table (`_filter_spurious_lines`, discarding
     coincidental alignments of text glyphs), recover merged cells via
     union-find over which grid boundaries are missing a line, erase the
     ruling pixels so cell crops don't pick up border slivers, then OCR
     each cell crop independently for per-cell accuracy.
   - **`ocr-text`**: whole-page word-level OCR, words clustered into rows
     by vertical overlap and into columns by horizontal whitespace gaps —
     the OCR analogue of pdfplumber's `"text"` strategy.
3. Free text outside the detected table's bounding box is recovered with a
   second OCR pass on a copy of the image with the table region whited
   out.

**Known limitation, by design**: only one dominant table region is
recovered per scanned page, by either strategy. See KNOWN_LIMITATIONS.md.

## Cell value typing (cell_typing.py)

`RawCell.text` (always a plain string, from either path) is converted to a
`TypedCell` with a real Python value (`int`/`float`/`date`/`str`) and an
Excel number format, following one governing rule: **a cell is only
promoted to a richer type when the text matches a pattern unambiguous
enough that no plausible alternative reading exists; otherwise it stays
text, unmodified.** Concretely:

- A leading-zero numeral (`^0\d+$`, e.g. `007`, `0123`) is always kept as
  text — it reads as a code, not a number, and converting it would both
  invent a different value and silently drop the leading zero.
- Integers, decimals (`.` or `,` decimal separator), and three thousands-
  separator conventions (`1.234,56`, `1,234.56`, `1 234,56`) are recognized
  as numbers.
- Percent (`12,5%`) and three currency notations (₽/руб., $, €/EUR) are
  recognized and given an Excel number format; the underlying numeric value
  is the amount, not including the symbol.
- Dates: ISO (`2024-01-02`), Russian long form (`2 января 2024`), dotted
  (`02.01.2024`), and slashed (`02/01/2024`). Slashed dates are genuinely
  ambiguous (DD/MM vs MM/DD) whenever both readings are in range — in that
  case the cell is still converted (DD/MM/YYYY convention) but flagged
  uncertain with an explicit "ambiguous date format" reason, never silently
  guessed.
- Live formulas are never reconstructed: only the *value* that the source
  document displayed is ever written.

Two independent forms of uncertainty are tracked and rendered identically
(yellow fill + Russian comment in `xlsx_writer.py`):

- **OCR uncertainty** — `source == "ocr"` and confidence is below
  `ConversionSettings.ocr_confidence_threshold`.
- **Interpretation uncertainty** — the characters are presumed correct, but
  more than one reasonable value follows from them (currently: ambiguous
  slashed dates). This applies even to a perfectly clean text-layer PDF.

Disabling "highlight uncertain cells" suppresses the fill/comment but never
changes which *value* was written.

## Output (xlsx_writer.py)

Mechanical from this point on — every type/uncertainty decision was already
made upstream. Tables are placed at sheet coordinates, merges applied via
`Worksheet.merge_cells`, headers (row 0 of a table) get bold font, uncertain
cells get a yellow fill (`FFFF00`) plus an `openpyxl.comments.Comment` with
the Russian reason. **Borders are only drawn for tables whose source
strategy is `"lines"` or `"ocr-lines"`** — i.e. ones with confirmed ruled-
grid evidence; borderless tables get no invented border. Two sheet-layout
modes (`SheetSplitMode`): one worksheet per PDF page (tables stacked
vertically, free text below), or one worksheet per table (with free text on
its own per-page sheet) — "per table" wins if both checkboxes are set.

## Report (report.py)

`build_report_text` produces only counts, a strategy/method breakdown, the
number of rotation-corrected pages, the count of cells flagged uncertain,
per-page warnings/errors, and a closing line confirming offline processing
— **never** the recognized text or any cell value, by construction (there is
no code path in `report.py` that reads `TypedCell.value` or
`TypedCell.display_text`).

## GUI thread model

`gui/worker.py`'s `ConversionWorker(QThread)` runs `pipeline.run_conversion`
for each queued `BatchJob` sequentially, emitting Qt signals
(`file_started`, `page_progress`, `file_finished`, `file_failed`,
`batch_finished`) that `MainWindow` connects to update the file list status
text, progress bar, and log panel. Cancellation is cooperative: `cancel()`
sets a flag checked between pages (`cancel_check`), so the current page
always finishes before a job stops.

## Frozen-build layout (paths.py)

```
PdfXlsx/
    PdfXlsx.exe
    _internal/...            (PyInstaller runtime, created automatically)
    tools/
        tesseract/
            tesseract.exe
            *.dll
            tessdata/
                rus.traineddata
                eng.traineddata
                osd.traineddata
```

Everything is resolved relative to `sys.executable`'s own directory
(`paths.app_root()`), never via PATH or the registry, so the folder works
unmodified from anywhere it's unzipped to. In dev mode (`is_frozen() ==
False`), `paths.py` additionally falls back to a system Tesseract
installation purely so tests/development don't require vendoring binaries
into the git repository — that fallback is unreachable in the frozen build.
