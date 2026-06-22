"""Direct table/text extraction from text-based PDF pages via pdfplumber.

No OCR is involved here: every value comes straight from the PDF's own
character/glyph data, which is why every produced `RawCell.confidence` is
100 and `source` is "text".
"""

from __future__ import annotations

import pdfplumber

from pdfxlsx.core.models import RawCell, RawTable

LINES_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
TEXT_SETTINGS = {"vertical_strategy": "text", "horizontal_strategy": "text"}


def _table_from_pdfplumber(table, strategy: str) -> RawTable | None:
    """Reconstruct row/col spans from pdfplumber's per-cell bounding boxes.

    pdfplumber represents a merged cell by giving its bounding box once, at
    the grid position where it starts, and `None` at every other grid
    position it covers. We rebuild a global column/row boundary axis from
    the union of all anchor-cell edges, then express each anchor as a
    (row, col, row_span, col_span) in that grid.
    """
    raw_rows = table.rows
    xs: set[float] = set()
    ys: set[float] = set()
    for row in raw_rows:
        for cell_bbox in row.cells:
            if cell_bbox is None:
                continue
            x0, top, x1, bottom = cell_bbox
            xs.add(round(x0, 1))
            xs.add(round(x1, 1))
            ys.add(round(top, 1))
            ys.add(round(bottom, 1))
    if not xs or not ys:
        return None
    sorted_xs = sorted(xs)
    sorted_ys = sorted(ys)
    col_of = {v: i for i, v in enumerate(sorted_xs)}
    row_of = {v: i for i, v in enumerate(sorted_ys)}
    n_cols = len(sorted_xs) - 1
    n_rows = len(sorted_ys) - 1
    if n_cols <= 0 or n_rows <= 0:
        return None

    extracted = table.extract()
    cells: list[RawCell] = []
    for r_idx, row in enumerate(raw_rows):
        if r_idx >= len(extracted):
            continue
        for c_idx, cell_bbox in enumerate(row.cells):
            if cell_bbox is None:
                continue
            x0, top, x1, bottom = cell_bbox
            col_start = col_of[round(x0, 1)]
            col_end = col_of[round(x1, 1)]
            row_start = row_of[round(top, 1)]
            row_end = row_of[round(bottom, 1)]
            text = extracted[r_idx][c_idx] or ""
            cells.append(
                RawCell(
                    text=text.strip(),
                    row=row_start,
                    col=col_start,
                    row_span=max(1, row_end - row_start),
                    col_span=max(1, col_end - col_start),
                    confidence=100.0,
                    source="text",
                )
            )

    if not cells:
        return None
    raw_table = RawTable(n_rows=n_rows, n_cols=n_cols, cells=cells, strategy=strategy, bbox=table.bbox)
    if strategy == "text":
        # The whitespace-based strategy sometimes inserts a spurious fully
        # empty row between real rows when line spacing is generous. Since
        # text-strategy tables never have merged cells, rows can be safely
        # dropped and renumbered.
        raw_table = _drop_empty_rows(raw_table)
    return raw_table


def _drop_empty_rows(raw_table: RawTable) -> RawTable:
    occupied_rows = sorted({c.row for c in raw_table.cells if c.text})
    if not occupied_rows:
        return raw_table
    remap = {old: new for new, old in enumerate(occupied_rows)}
    kept_cells = [
        RawCell(
            text=c.text,
            row=remap[c.row],
            col=c.col,
            row_span=c.row_span,
            col_span=c.col_span,
            confidence=c.confidence,
            source=c.source,
        )
        for c in raw_table.cells
        if c.row in remap
    ]
    return RawTable(
        n_rows=len(occupied_rows),
        n_cols=raw_table.n_cols,
        cells=kept_cells,
        strategy=raw_table.strategy,
        bbox=raw_table.bbox,
    )


def find_tables(page: pdfplumber.page.Page) -> list[RawTable]:
    """Try the ruled-line strategy first, then the whitespace strategy.

    Both strategies run; where their detected regions overlap, the
    lines-based result wins because it carries real grid/merge geometry.
    Non-overlapping regions from either strategy are kept, so a page that
    mixes a ruled table and a separate borderless table is handled too.
    """
    results: list[RawTable] = []
    for strategy_name, settings in (("lines", LINES_SETTINGS), ("text", TEXT_SETTINGS)):
        try:
            found = page.find_tables(table_settings=settings)
        except Exception:
            found = []
        for t in found:
            built = _table_from_pdfplumber(t, strategy_name)
            if built is not None:
                results.append(built)

    if not results:
        return []

    # Deduplicate overlapping detections between the two strategies by
    # bounding box, preferring the lines-based (richer) version.
    deduped: list[RawTable] = []
    used_boxes: list[tuple[float, float, float, float]] = []
    for t in sorted(results, key=lambda t: 0 if t.strategy == "lines" else 1):
        if t.bbox and any(_boxes_overlap(t.bbox, b) for b in used_boxes):
            continue
        deduped.append(t)
        if t.bbox:
            used_boxes.append(t.bbox)
    return deduped


def _boxes_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    inter_w = min(ax1, bx1) - max(ax0, bx0)
    inter_h = min(ay1, by1) - max(ay0, by0)
    if inter_w <= 0 or inter_h <= 0:
        return False
    inter_area = inter_w * inter_h
    a_area = (ax1 - ax0) * (ay1 - ay0)
    b_area = (bx1 - bx0) * (by1 - by0)
    return inter_area > 0.5 * min(a_area, b_area)


def extract_plain_text_outside_tables(page: pdfplumber.page.Page, tables: list[RawTable]) -> list[str]:
    """Free text on the page that does not belong to any detected table."""
    if not tables:
        text = page.extract_text() or ""
        return [p.strip() for p in text.split("\n") if p.strip()]
    cropped = page
    for t in tables:
        if t.bbox is None:
            continue
        try:
            cropped = cropped.outside_bbox(t.bbox)
        except Exception:
            continue
    text = cropped.extract_text() or ""
    return [p.strip() for p in text.split("\n") if p.strip()]
