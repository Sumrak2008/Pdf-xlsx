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

import numpy as np
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


def test_grid_keeps_row_divider_partly_hidden_by_a_merged_cell(make_table_pdf, render_page):
    """Regression: a row divider that only crosses the table's *un-merged*
    columns (because some other column in that row spans several rows) used
    to be discarded as "spurious" for covering less than half the table
    width, even though it is a real ruled line. That silently destroyed the
    internal grid for any table using row-spanning merges - exactly the
    layout of the real-world scanned form that surfaced this bug - and
    glued the de-duplicated rows' text together into one garbled cell
    (e.g. "1 2 3", "10 20 30") instead of keeping them separate.
    """
    _configure_ocr()
    pdf = make_table_pdf(
        rows=[
            ["Описание", "A", "B", "C", "D"],
            ["Труба ГС-1", "1", "10", "100", "X"],
            ["Труба ГС-1", "2", "20", "200", "Y"],
            ["Труба ГС-1", "3", "30", "300", "Z"],
        ],
        spans=[((0, 1), (0, 3))],
        col_widths=[210, 25, 25, 25, 25],
    )
    image = render_page(pdf, dpi=300)
    table = table_detector.extract_table_from_grid(image, lang="rus+eng", dpi=300)
    assert table is not None
    assert table.n_rows == 4
    assert table.n_cols == 5
    merged = next(c for c in table.cells if c.row == 1 and c.col == 0)
    assert merged.row_span == 3
    by_pos = {(c.row, c.col): c.text for c in table.cells}
    assert by_pos[(1, 1)] == "1"
    assert by_pos[(2, 1)] == "2"
    assert by_pos[(3, 1)] == "3"


def test_vertical_header_text_is_recovered_via_rotation():
    """Regression: column headers in real-world technical tables are often
    printed as vertical (90-degree rotated) text to fit narrow columns
    (e.g. "Категория, группа" running bottom-to-top). OCR'd in the cell's
    native horizontal orientation this reads as nonsense glyph soup, even
    though every individual cell's structure (row/col position, span) is
    correct - only the recognized text is garbage. Retrying the cell
    rotated +-90 degrees and keeping whichever orientation scores best
    recovers the real text.
    """
    _configure_ocr()
    from pathlib import Path

    from PIL import Image, ImageDraw, ImageFont

    fonts_dir = Path(__file__).resolve().parent.parent / "tools" / "fonts"
    font = ImageFont.truetype(str(fonts_dir / "DejaVuSans.ttf"), 28)
    horizontal = Image.new("RGB", (420, 60), "white")
    ImageDraw.Draw(horizontal).text((10, 10), "Категория, группа", font=font, fill="black")
    vertical = horizontal.rotate(90, expand=True)

    native_words = ocr_engine.ocr_words(vertical, lang="rus+eng", psm=6)
    best_words = table_detector._best_orientation_words(vertical, native_words, lang="rus+eng")
    recovered = " ".join(w.text for w in best_words)
    assert "Категория" in recovered
    assert "группа" in recovered


def test_non_rectangular_merge_group_falls_back_to_unmerged_cells():
    """Regression: a missing divider between (0,0)/(0,1) plus a separate
    missing divider between (0,1)/(1,1) chains all three into one union-find
    group via transitivity, even though that group is L-shaped, not a
    rectangle. Excel/openpyxl can only represent rectangular merges, so
    collapsing it into one cell with a row_span/col_span bounding box would
    claim (1,0) too - a cell it never actually swallowed - leading the
    writer to either crash (writing into a cell already inside another
    merge) or silently overlap two cells' worth of text. Each member of a
    non-rectangular group must come back out as its own independent cell.
    """
    row_ys = [0, 10, 20, 30]
    col_xs = [0, 10, 20, 30]
    horizontal_mask = np.zeros((31, 31), dtype=np.uint8)
    vertical_mask = np.zeros((31, 31), dtype=np.uint8)

    # Vertical divider between col0/col1: absent for row band 0 only, so
    # (0,0) and (0,1) merge; present for every other row band.
    vertical_mask[10:30, 10] = 255
    # Vertical divider between col1/col2: present everywhere (no merges).
    vertical_mask[0:30, 20] = 255

    # Horizontal divider between row0/row1: absent for column band 1 only,
    # so (0,1) and (1,1) merge; present for every other column band.
    horizontal_mask[10, 0:10] = 255
    horizontal_mask[10, 20:30] = 255
    # Horizontal divider between row1/row2: present everywhere.
    horizontal_mask[20, 0:30] = 255

    cells = table_detector._build_cells_with_merges(horizontal_mask, vertical_mask, row_ys, col_xs)

    assert len(cells) == 9
    assert all(c.row_span == 1 and c.col_span == 1 for c in cells)
    positions = {(c.row, c.col) for c in cells}
    assert positions == {(r, c) for r in range(3) for c in range(3)}


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
