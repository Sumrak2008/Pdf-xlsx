# Development Report

## Summary

PdfXlsx is a fully offline Windows 10/11 (x64) desktop application that
converts PDF documents into editable `.xlsx` workbooks, with real Excel
cells rather than embedded images. This report summarizes what was built,
the technical decisions made along the way, and the verification performed.

- 81 automated tests passing (`pytest`), plus a separate, slower PyInstaller
  build-and-launch smoke test (`pytest -m smoke`) not run by default.
- `ruff check` clean across `src/`, `tests/`, `tools/`.
- ~4,000 lines of Python across the conversion core, the GUI, and the test
  suite (excluding generated build artifacts and third-party code).
- Five commits, building up: core conversion pipeline → GUI → end-to-end
  scenario test suite (+ one real bug fix it surfaced) → packaging/CI/release
  infrastructure (+ one real packaging bug it surfaced) → documentation.

## Architecture decisions

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design. Key choices,
with rationale:

- **Portable `--onedir` PyInstaller build, not a single EXE or installer.**
  Required by the spec (no admin rights, no installer), and as a side
  benefit keeps Qt's LGPLv3-licensed shared libraries as separate,
  replaceable DLL files rather than statically embedded into one binary —
  the more straightforward way to stay compliant with LGPLv3's
  relink/replace provision.
- **Routing rule: direct extraction only for unrotated text pages; OCR for
  everything else.** Verified empirically (see "Verification" below) that
  `pdfplumber`'s coordinate handling on rotated pages is unreliable, while
  `pypdfium2` correctly applies a page's `/Rotate` flag during rendering —
  so any rotated page, even one with a real text layer, is routed through
  rasterization + OCR instead of being trusted for direct extraction.
- **Single source of truth for the build**: `tools/build_windows.ps1` is
  invoked identically by a local developer and by
  `.github/workflows/release.yml`, so CI and local builds cannot silently
  diverge.
- **Tesseract OCR sourced via Chocolatey + a direct download of just the
  three needed language files** from the official `tessdata_fast`
  distribution, rather than vendoring binaries into the git repository or
  trusting whatever language set the Chocolatey package happens to ship.
  This is build-time-only network access, explicitly permitted by the
  project's offline requirement (only *runtime* network access is
  forbidden) and documented in [SECURITY_OFFLINE.md](SECURITY_OFFLINE.md).
- **Strict, conservative cell-value typing** (`cell_typing.py`): a cell is
  only promoted from text to a richer type (number/date/percent/currency)
  when the pattern is unambiguous; leading-zero numerals are always kept as
  text; genuinely ambiguous slashed dates are still converted but flagged
  uncertain with an explicit reason rather than silently guessed. This
  follows directly from the "never invent, never auto-correct, default to
  text" requirement.
- **The conversion report never includes recognized text or cell values** —
  enforced structurally: `report.py` has no code path that reads
  `TypedCell.value` or `.display_text`, only counts and flags.

## Verification performed

Beyond the automated test suite, the following was specifically verified
by hand, given the absence of a Windows machine in the development
environment:

- **A real built executable was launched and observed to stay running**
  (not just a clean PyInstaller compile log) under
  `QT_QPA_PLATFORM=offscreen`, which caught a genuine packaging bug
  (`ModuleNotFoundError: No module named 'backports'`, from a PyInstaller/
  setuptools runtime-hook interaction on Python <3.12) that a successful
  build alone would not have revealed. This check is now permanently
  encoded as `tests/test_smoke.py` (`pytest -m smoke`) and runs in CI on
  every push.
- **Tesseract OSD-based rotation correction** was empirically confirmed
  reliable (confidence ~5.1-5.36, well above the code's
  `OSD_MIN_CONFIDENCE = 0.5` threshold) for 90/180/270-degree baked-in
  rotations, and the sign/direction of `image_utils.rotate_image`'s
  `Image.rotate(-degrees, expand=True)` call was verified to correctly
  invert Tesseract's reported "rotate clockwise to fix" value.
  `pypdfium2`'s rotation argument was separately confirmed to be inverted
  relative to a PDF's own `/Rotate` convention (`_quarter_turn_for_pdfium`).
- **The 16-scenario synthetic-PDF test suite**
  (`tools/synthetic_pdfs.py` + `tests/test_scenarios.py`) was built by
  first running each generated PDF through the real pipeline via ad-hoc
  scratch scripts and inspecting the actual `PageOutcome`/`DocumentResult`
  shapes, *before* writing the final test assertions — rather than writing
  assertions against assumed behavior. This is what surfaced the one real
  pipeline bug described below.

## Bugs found and fixed during development

1. **Encrypted-PDF misclassification** (`pipeline.py::_open_pdf`). pdfminer
   raises `PDFPasswordIncorrect` with an *empty* exception message, so the
   original password/encryption sniff (substring match on the lowercased
   message) never matched, and an encrypted PDF was reported as merely
   corrupt rather than password-protected. Fixed by additionally checking
   the exception's type name. Caught directly by
   `test_scenario_16_encrypted_pdf_raises_russian_error`.
2. **PyInstaller/setuptools packaging crash**
   (`ModuleNotFoundError: No module named 'backports'`). On Python <3.12,
   `setuptools._vendor.jaraco.context` unconditionally imports
   `backports.tarfile`, which PyInstaller's automatically-included
   `pkg_resources` runtime hook exercises but does not vendor. Fixed by
   pinning `backports.tarfile` in `requirements-dev.txt`; caught only
   because the built executable was actually launched, not just compiled,
   and is now guarded against regressing via the `pytest -m smoke` CI step.

## Test coverage

`tests/test_scenarios.py` (16 scenarios, generated by
`tools/synthetic_pdfs.py`) covers every major requirement axis from the
specification in one place:

| # | Scenario | Covers |
|---|---|---|
| 1-3 | Bordered text tables: Russian, English, mixed | Direct extraction, language handling |
| 4 | Borderless text table | pdfplumber "text" strategy, no OCR |
| 5 | Merged header table | Multi-column header span recovery |
| 6 | Multi-page with a blank page | Multi-page handling, blank-page skip |
| 7 | Table + surrounding paragraph text | `plain_text_paragraphs` alongside a table |
| 8 | Clean scanned bordered table | OCR, `ocr-lines` strategy |
| 9 | Clean scanned borderless table | OCR, `ocr-text` strategy |
| 10 | Scanned table, strict confidence threshold | Deterministic uncertain-cell highlighting end to end (including the actual `.xlsx` fill color) |
| 11 | Low-quality/noisy scan | OCR robustness (no crash) under blur + pixel noise |
| 12 | Rotated text page (`/Rotate` flag, no pixel change) | PDF-attribute rotation, OCR routing for "text but rotated" |
| 13 | Rotated scanned page (baked into pixels, no flag) | Tesseract OSD-based rotation correction |
| 14 | Mixed document (one direct page + one scanned page) | Per-page routing within a single document |
| 15 | Corrupt / non-PDF file | `CorruptPdfError` with a Russian message |
| 16 | Password-encrypted PDF | `EncryptedPdfError` with a Russian message |

Plus dedicated unit-level suites for cell typing (`test_cell_typing.py`),
table structure recovery (`test_table_detector.py`), report generation
(never leaks content — `test_report.py`), XLSX writing (merges, borders,
highlighting, leading zeros — `test_xlsx_writer.py`), pipeline-level
behavior (`test_pipeline.py`), and the GUI (`test_gui.py`, headless via
`QT_QPA_PLATFORM=offscreen`).

## Known limitations

See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) for the full, user-facing
list (also referenced from every conversion report). The most significant:
at most one dominant table is recovered per *scanned* page (text-layer
pages have no such limit); OCR accuracy depends on scan quality; live Excel
formulas are never reconstructed, only the displayed value.

## Offline guarantee

See [SECURITY_OFFLINE.md](SECURITY_OFFLINE.md) for the full audit. A static
source scan of `src/pdfxlsx/` confirms zero network-capable imports or
calls anywhere in the runtime code; the only network access in this
repository happens at build time (`pip install`, fetching the Tesseract
engine and language data) and is fully documented as such.
