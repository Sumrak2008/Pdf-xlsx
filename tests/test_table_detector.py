"""Tests for OCR-based table/grid recovery (pdfxlsx.core.table_detector).

Two regressions are pinned down here specifically because they were each
silent in isolation - the grid shape looked plausible, only the cell text
gave them away:

* a fixed pixel padding around a cropped cell does not reliably clear the
  rendered grid line, so a sliver of the border ends up inside the crop
  and corrupts that cell's OCR result.
* a row/column is wrongly promoted to "grid line" status if a run of text
  glyphs happens to align into a contiguous dark streak at least as long
  as the line-detection kernel, even though it covers only a tiny sliver
  of the table rather than spanning it.
"""

from __future__ import annotations

import pytest

from pdfxlsx.core import ocr_engine, paths, table_detector

pytestmark = pytest.mark.skipif(paths.tesseract_executable() is None, reason="tesseract not available")


def _configure_ocr():
    ocr_engine.configure()


def test_grid_with_merged_header_has_correct_shape(make_table_pdf, render_page):
    _configure_ocr()
    pdf = make_table_pdf(
        rows=[
            ["Header spanning all columns", "", ""],
            ["A1", "B1", "C1"],
            ["A2", "B2", "C2"],
        ],
        spans=[((0, 0), (2, 0))],
        col_widths=[120, 120, 120],
    )
    image = render_page(pdf, dpi=300)
    table = table_detector.extract_table_from_grid(image, lang="eng", dpi=300)
    assert table is not None
    assert table.n_rows == 3
    assert table.n_cols == 3
    header = next(c for c in table.cells if c.row == 0)
    assert header.col_span == 3


def test_cell_crop_does_not_pick_up_border_line_glyphs(make_table_pdf, render_page):
    """Regression: a fixed CELL_PADDING_PX left border slivers in the crop,
    which Tesseract read as e.g. a leading "|" glued onto the real text."""
    _configure_ocr()
    pdf = make_table_pdf(rows=[["A1", "B1", "C1"], ["A2", "B2", "C2"]], col_widths=[120, 120, 120])
    image = render_page(pdf, dpi=300)
    table = table_detector.extract_table_from_grid(image, lang="eng", dpi=300)
    assert table is not None
    for cell in table.cells:
        assert "|" not in cell.text
        assert not cell.text.startswith("(")


def test_grid_ignores_spurious_line_from_aligned_text_glyphs(make_table_pdf, render_page):
    """Regression: a long text cell could produce a coincidental run of
    on-pixels long enough to survive the line-detection kernel, splitting
    one logical row into two and corrupting its row_span."""
    _configure_ocr()
    pdf = make_table_pdf(
        rows=[
            ["№", "Наименование товара", "Кол-во", "Цена", "Сумма"],
            ["001", "Болт М6х20 ГОСТ 7798-70", "150", "12.50", "1875.00"],
            ["002", "Гайка М6 DIN 934", "150", "5.00", "750.00"],
            ["003", "Шайба плоская 6мм", "300", "1.20", "360.00"],
            ["", "Итого:", "", "", "2985.00"],
        ],
        spans=[((0, 4), (1, 4))],
        col_widths=[40, 220, 60, 60, 80],
    )
    image = render_page(pdf, dpi=300)
    table = table_detector.extract_table_from_grid(image, lang="rus+eng", dpi=300)
    assert table is not None
    assert table.n_rows == 5
    assert table.n_cols == 5
    for cell in table.cells:
        assert cell.row_span == 1 or (cell.row == 4 and cell.col_span == 2)


def test_borderless_table_via_word_clustering(make_borderless_pdf, render_page):
    _configure_ocr()
    pdf = make_borderless_pdf(
        rows=[
            ["Код", "Наименование", "Кол-во", "Цена"],
            ["001", "Болт М6", "150", "12.50"],
            ["002", "Гайка М6", "150", "5.00"],
        ]
    )
    image = render_page(pdf, dpi=300)
    grid = table_detector.detect_grid(image, dpi=300)
    assert grid is None
    table = table_detector.detect_and_extract_tables(image, lang="rus+eng", dpi=300)
    assert len(table) == 1
    assert table[0].strategy == "ocr-text"
    assert table[0].n_rows == 3
    assert table[0].n_cols == 4
