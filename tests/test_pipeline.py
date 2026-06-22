from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from pdfxlsx.core import paths
from pdfxlsx.core.config import ConversionSettings
from pdfxlsx.core.errors import CorruptPdfError, PdfXlsxError
from pdfxlsx.core.pipeline import convert_document, resolve_output_paths, run_conversion

TESSERACT_MISSING = paths.tesseract_executable() is None


def _make_scanned_pdf(table_pdf_path: Path, out_path: Path, dpi: int = 300) -> Path:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(table_pdf_path))
    bitmap = doc[0].render(scale=dpi / 72.0)
    image = bitmap.to_pil().convert("RGB")
    width_pt, height_pt = letter
    c = canvas.Canvas(str(out_path), pagesize=letter)
    c.drawImage(ImageReader(image), 0, 0, width=width_pt, height=height_pt)
    c.save()
    return out_path


def test_direct_extraction_for_text_pdf(make_table_pdf):
    pdf_path = make_table_pdf([["Наименование", "Количество"], ["Товар А", "1"], ["Товар Б", "2"]])
    result = convert_document(str(pdf_path), ConversionSettings())

    assert result.page_count == 1
    page = result.pages[0]
    assert page.page_kind == "text"
    assert page.extraction_method == "direct"
    assert len(result.tables) == 1
    table = result.tables[0]
    values_by_pos = {(c.row, c.col): c.value for c in table.cells}
    assert values_by_pos[(0, 0)] == "Наименование"
    assert values_by_pos[(0, 1)] == "Количество"
    assert values_by_pos[(1, 0)] == "Товар А"
    assert values_by_pos[(1, 1)] == 1
    assert values_by_pos[(2, 1)] == 2


def test_blank_page_classified_and_skipped(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    c.showPage()
    c.save()

    result = convert_document(str(pdf_path), ConversionSettings())
    assert result.page_count == 1
    assert result.pages[0].page_kind == "blank"
    assert result.pages[0].extraction_method == "blank"
    assert result.tables == []


def test_cancel_check_stops_before_first_page(make_table_pdf):
    pdf_path = make_table_pdf([["A", "B"], ["1", "2"]])
    result = convert_document(str(pdf_path), ConversionSettings(), cancel_check=lambda: True)
    assert result.cancelled is True
    assert result.pages == []


def test_missing_file_raises_pdfxlsx_error(tmp_path):
    with pytest.raises(PdfXlsxError):
        convert_document(str(tmp_path / "does_not_exist.pdf"), ConversionSettings())


def test_corrupt_pdf_raises_corrupt_pdf_error(tmp_path):
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"this is not a pdf file at all")
    with pytest.raises(CorruptPdfError):
        convert_document(str(bad_pdf), ConversionSettings())


def test_resolve_output_paths_uses_naming_convention(tmp_path):
    pdf_path = tmp_path / "Отчёт.pdf"
    xlsx_path, report_path = resolve_output_paths(str(pdf_path), ConversionSettings())
    assert xlsx_path.name == "Отчёт_editable.xlsx"
    assert report_path.name == "Отчёт_conversion_report.txt"
    assert xlsx_path.parent == tmp_path


def test_run_conversion_writes_xlsx_and_report(make_table_pdf, tmp_path):
    pdf_path = make_table_pdf([["A", "B"], ["1", "2"]], path=tmp_path / "doc.pdf")
    settings = ConversionSettings()
    result = run_conversion(str(pdf_path), settings)

    xlsx_path, report_path = resolve_output_paths(str(pdf_path), settings)
    assert xlsx_path.exists()
    assert report_path.exists()
    assert result.page_count == 1


def test_run_conversion_skips_report_when_disabled(make_table_pdf, tmp_path):
    pdf_path = make_table_pdf([["A", "B"], ["1", "2"]], path=tmp_path / "doc.pdf")
    settings = ConversionSettings(save_report=False)
    run_conversion(str(pdf_path), settings)

    xlsx_path, report_path = resolve_output_paths(str(pdf_path), settings)
    assert xlsx_path.exists()
    assert not report_path.exists()


@pytest.mark.skipif(TESSERACT_MISSING, reason="tesseract not available")
def test_ocr_extraction_for_scanned_pdf(make_table_pdf, tmp_path):
    table_pdf = make_table_pdf([["Наименование", "Количество"], ["Товар", "5"]])
    scanned_pdf = _make_scanned_pdf(table_pdf, tmp_path / "scanned.pdf")

    result = convert_document(str(scanned_pdf), ConversionSettings())

    assert result.page_count == 1
    page = result.pages[0]
    assert page.page_kind == "scanned"
    assert page.extraction_method == "ocr"
    assert len(result.tables) == 1
    table = result.tables[0]
    texts = {c.display_text for c in table.cells}
    assert any("Товар" in t for t in texts)
    assert any("5" in t for t in texts)
