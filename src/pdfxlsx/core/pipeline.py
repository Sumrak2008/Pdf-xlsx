"""Top-level orchestration: one PDF in, a `DocumentResult` (and, via
`run_conversion`, the two output files) out.

Per-page routing follows one rule: a page is read directly from the PDF's
own text/table structure (`text_extractor.py`) only when it is both a
text page *and* unrotated. Any rotation, even on an otherwise-clean text
page, sends it through rasterization + OCR (`image_utils.py` /
`table_detector.py`) instead - `pdfplumber`'s coordinate handling for
rotated pages is unreliable, while rendering through `pypdfium2` already
applies the page's `/Rotate` flag correctly before anything else looks at
the pixels. Errors on one page are recorded on that page's `PageOutcome`
and processing continues with the next page; only a missing/unusable OCR
engine aborts the whole document, since every remaining OCR page would
fail identically.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pdfplumber
import pypdfium2 as pdfium
from PIL import Image

from pdfxlsx.core import (
    cell_typing,
    image_utils,
    ocr_engine,
    table_detector,
    tempfiles,
    text_extractor,
    xlsx_writer,
)
from pdfxlsx.core import report as report_module
from pdfxlsx.core.config import ConversionSettings
from pdfxlsx.core.errors import (
    CorruptPdfError,
    EncryptedPdfError,
    InsufficientDiskSpaceError,
    OcrEngineUnavailableError,
    OutputNotWritableError,
    PdfXlsxError,
)
from pdfxlsx.core.models import DocumentResult, PageOutcome
from pdfxlsx.core.pdf_classifier import PageKind, classify_page

logger = logging.getLogger(__name__)

CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[int, int], None]


def resolve_output_paths(pdf_path: str, settings: ConversionSettings) -> tuple[Path, Path]:
    src = Path(pdf_path)
    out_dir = Path(settings.output_dir) if settings.output_dir else src.parent
    return out_dir / f"{src.stem}_editable.xlsx", out_dir / f"{src.stem}_conversion_report.txt"


def _split_paragraphs(text: str) -> list[str]:
    return [line.strip() for line in text.split("\n") if line.strip()]


def _open_pdf(pdf_path: Path) -> pdfplumber.PDF:
    try:
        return pdfplumber.open(str(pdf_path))
    except Exception as exc:
        message = str(exc).lower()
        if "password" in message or "encrypt" in message:
            raise EncryptedPdfError(pdf_path.name) from exc
        raise CorruptPdfError(pdf_path.name, technical_detail=str(exc)) from exc


def _process_text_page(plumber_page: pdfplumber.page.Page, index: int, settings: ConversionSettings) -> PageOutcome:
    raw_tables = text_extractor.find_tables(plumber_page)
    paragraphs = text_extractor.extract_plain_text_outside_tables(plumber_page, raw_tables)
    typed_tables = [cell_typing.type_table(t, settings, index, i) for i, t in enumerate(raw_tables)]
    return PageOutcome(
        page_index=index,
        page_kind="text",
        extraction_method="direct",
        tables=typed_tables,
        plain_text_paragraphs=paragraphs,
    )


def _ocr_paragraphs_outside_table(image: Image.Image, bbox: tuple[float, float, float, float], lang: str) -> list[str]:
    x0, y0, x1, y1 = (int(v) for v in bbox)
    masked = np.array(image).copy()
    masked[max(0, y0) : y1, max(0, x0) : x1] = 255
    return _split_paragraphs(ocr_engine.ocr_plain_text(Image.fromarray(masked), lang=lang))


def _process_ocr_page(pdfium_doc: pdfium.PdfDocument, index: int, settings: ConversionSettings) -> PageOutcome:
    lang = settings.ocr_language.value
    rasterized = image_utils.rasterize_page(pdfium_doc, index, dpi=settings.ocr_dpi)
    raw_tables = table_detector.detect_and_extract_tables(rasterized.image, lang=lang, dpi=settings.ocr_dpi)

    if raw_tables and raw_tables[0].bbox is not None:
        paragraphs = _ocr_paragraphs_outside_table(rasterized.image, raw_tables[0].bbox, lang)
    elif not raw_tables:
        paragraphs = _split_paragraphs(ocr_engine.ocr_plain_text(rasterized.image, lang=lang))
    else:
        paragraphs = []

    typed_tables = [cell_typing.type_table(t, settings, index, i) for i, t in enumerate(raw_tables)]
    warnings = []
    if not typed_tables and not paragraphs:
        warnings.append("Таблицы и текст на странице не обнаружены (возможно, низкое качество скана).")

    return PageOutcome(
        page_index=index,
        page_kind="scanned",
        extraction_method="ocr",
        tables=typed_tables,
        rotation_degrees=rasterized.pdf_rotation_applied or rasterized.osd_rotation_applied,
        warnings=warnings,
        plain_text_paragraphs=paragraphs,
    )


def _process_page(
    plumber_page: pdfplumber.page.Page,
    pdfium_doc: pdfium.PdfDocument,
    index: int,
    settings: ConversionSettings,
) -> PageOutcome:
    classification = classify_page(plumber_page, index)
    if classification.kind == PageKind.BLANK:
        return PageOutcome(page_index=index, page_kind="blank", extraction_method="blank")

    try:
        if classification.kind == PageKind.TEXT and classification.rotation == 0:
            return _process_text_page(plumber_page, index, settings)
        return _process_ocr_page(pdfium_doc, index, settings)
    except OcrEngineUnavailableError:
        raise
    except Exception as exc:
        logger.warning("Page %d failed: %s", index, exc)
        return PageOutcome(
            page_index=index,
            page_kind=classification.kind.value,
            extraction_method="failed",
            error=f"Не удалось обработать страницу: {exc}",
        )


def convert_document(
    pdf_path: str,
    settings: ConversionSettings,
    *,
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
) -> DocumentResult:
    start = time.monotonic()
    pdf_file = Path(pdf_path)
    if not pdf_file.is_file():
        raise PdfXlsxError(f"Файл «{pdf_file.name}» не найден.")

    plumber_pdf = _open_pdf(pdf_file)
    try:
        try:
            pdfium_doc = pdfium.PdfDocument(str(pdf_file))
        except Exception as exc:
            raise CorruptPdfError(pdf_file.name, technical_detail=str(exc)) from exc

        try:
            page_count = len(plumber_pdf.pages)
            pages: list[PageOutcome] = []
            tables = []
            cancelled = False

            for index, plumber_page in enumerate(plumber_pdf.pages):
                if cancel_check is not None and cancel_check():
                    cancelled = True
                    break
                outcome = _process_page(plumber_page, pdfium_doc, index, settings)
                pages.append(outcome)
                tables.extend(outcome.tables)
                if progress_callback is not None:
                    progress_callback(index + 1, page_count)

            return DocumentResult(
                source_pdf=str(pdf_file),
                page_count=page_count,
                pages=pages,
                tables=tables,
                duration_seconds=time.monotonic() - start,
                cancelled=cancelled,
            )
        finally:
            pdfium_doc.close()
    finally:
        plumber_pdf.close()


def run_conversion(
    pdf_path: str,
    settings: ConversionSettings,
    *,
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
) -> DocumentResult:
    """Convert `pdf_path` and write both output files next to it (or into
    `settings.output_dir`), checking output writability/disk space first."""
    xlsx_path, report_path = resolve_output_paths(pdf_path, settings)
    out_dir = xlsx_path.parent
    if not tempfiles.can_write_to(out_dir):
        raise OutputNotWritableError(str(out_dir))

    required_mb = max(settings.min_free_disk_mb, tempfiles.estimate_required_mb(Path(pdf_path), settings.ocr_dpi))
    available_mb = tempfiles.free_space_mb(out_dir)
    if available_mb < required_mb:
        raise InsufficientDiskSpaceError(str(out_dir), required_mb, available_mb)

    result = convert_document(pdf_path, settings, cancel_check=cancel_check, progress_callback=progress_callback)
    xlsx_writer.write_document(result, settings, str(xlsx_path))
    if settings.save_report:
        report_module.write_report(result, settings, str(report_path))
    return result
