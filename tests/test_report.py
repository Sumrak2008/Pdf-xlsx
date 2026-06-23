from __future__ import annotations

from pdfxlsx.core.config import ConversionSettings
from pdfxlsx.core.models import DocumentResult, PageOutcome, TypedCell, TypedTable
from pdfxlsx.core.report import build_report_text


def _table_with_uncertain(n_uncertain: int, n_total: int, page_index=0):
    cells = [
        TypedCell(
            value=f"СЕКРЕТНОЕ_ЗНАЧЕНИЕ_{i}_xq7z",
            display_text=f"СЕКРЕТНОЕ_ЗНАЧЕНИЕ_{i}_xq7z",
            number_format=None,
            row=i,
            col=0,
            row_span=1,
            col_span=1,
            is_uncertain=i < n_uncertain,
            comment="x" if i < n_uncertain else None,
        )
        for i in range(n_total)
    ]
    return TypedTable(n_rows=n_total, n_cols=1, cells=cells, page_index=page_index, table_index_on_page=0, source="lines")


def test_report_never_includes_cell_text():
    table = _table_with_uncertain(1, 3)
    page = PageOutcome(page_index=0, page_kind="text", extraction_method="direct", tables=[table])
    result = DocumentResult(source_pdf="/home/user/секретный_документ.pdf", page_count=1, pages=[page], tables=[table], duration_seconds=12.0)
    text = build_report_text(result, ConversionSettings())
    assert "секретный_документ.pdf" in text  # filename is fine
    for cell in table.cells:
        assert str(cell.value) not in text.replace("секретный_документ.pdf", "")


def test_report_counts_uncertain_cells():
    table = _table_with_uncertain(2, 5)
    page = PageOutcome(page_index=0, page_kind="text", extraction_method="direct", tables=[table])
    result = DocumentResult(source_pdf="x.pdf", page_count=1, pages=[page], tables=[table])
    text = build_report_text(result, ConversionSettings())
    assert "Ячеек, требующих проверки: 2" in text


def test_report_breaks_down_extraction_methods():
    pages = [
        PageOutcome(page_index=0, page_kind="text", extraction_method="direct"),
        PageOutcome(page_index=1, page_kind="scanned", extraction_method="ocr"),
        PageOutcome(page_index=2, page_kind="scanned", extraction_method="failed", error="Повреждённая страница"),
    ]
    result = DocumentResult(source_pdf="x.pdf", page_count=3, pages=pages)
    text = build_report_text(result, ConversionSettings())
    assert "Всего страниц: 3" in text
    assert "Обработано успешно: 2" in text
    assert "Прямое извлечение текста: 1" in text
    assert "Распознавание (ocr): 1".lower() in text.lower() or "Распознавание (OCR): 1" in text
    assert "Повреждённая страница" in text


def test_report_notes_rotation_correction():
    pages = [PageOutcome(page_index=0, page_kind="scanned", extraction_method="ocr", rotation_degrees=90)]
    result = DocumentResult(source_pdf="x.pdf", page_count=1, pages=pages)
    text = build_report_text(result, ConversionSettings())
    assert "поворот" in text.lower()


def test_report_mentions_offline_processing():
    result = DocumentResult(source_pdf="x.pdf", page_count=1, pages=[PageOutcome(page_index=0, page_kind="text", extraction_method="direct")])
    text = build_report_text(result, ConversionSettings())
    assert "локально" in text.lower()
    assert "интернет" in text.lower()


def test_report_cancelled_flag_surfaced():
    result = DocumentResult(source_pdf="x.pdf", page_count=1, pages=[], cancelled=True)
    text = build_report_text(result, ConversionSettings())
    assert "отменено" in text.lower()
