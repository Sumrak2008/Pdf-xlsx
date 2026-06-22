"""Table structure recovery for rasterized (OCR) pages.

Two strategies, mirroring the text-extraction path:

* "ocr-lines": an actual ruled grid is found in the image (via OpenCV
  morphology); cells, including merges, are reconstructed from which grid
  boundaries actually have a drawn line, and each cell is OCR'd separately
  for the best possible per-cell accuracy.
* "ocr-text": no reliable grid is found; word boxes from a whole-page OCR
  pass are clustered into rows (by vertical position) and columns (by
  whitespace gaps), the same idea as pdfplumber's "text" strategy but
  applied to OCR output instead of embedded characters.

Limitation (see KNOWN_LIMITATIONS.md): at most one dominant table region
is recovered per scanned page with each strategy. Pages with several
separate small tables may have them merged or only the largest recovered.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np
from PIL import Image

from pdfxlsx.core import ocr_engine
from pdfxlsx.core.models import RawCell, RawTable
from pdfxlsx.core.ocr_engine import Word

logger = logging.getLogger(__name__)

MIN_LINE_INCHES = 0.12
"""A straight run shorter than this (in inches, at the page's render DPI) is
treated as a glyph stroke rather than a table border. Independent of how
large the table is relative to the full page - unlike a page-fraction-based
threshold, this also detects small tables that occupy only part of a page.
"""
DEFAULT_DPI = 300
MIN_GRID_SIZE = 2
LINE_PRESENCE_THRESHOLD = 0.5
CELL_PADDING_PX = 2


def _binarize(image: Image.Image) -> np.ndarray:
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binary


def _line_masks(binary: np.ndarray, dpi: int = DEFAULT_DPI) -> tuple[np.ndarray, np.ndarray]:
    kernel_len = max(20, round(dpi * MIN_LINE_INCHES))
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_len, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_len))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel, iterations=1)
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel, iterations=1)
    return horizontal, vertical


def _cluster_positions(mask_sum: np.ndarray, threshold: float, merge_dist: int = 5) -> list[int]:
    """Cluster 1D projection peaks (rows or columns with lots of line pixels)."""
    above = np.where(mask_sum > threshold)[0]
    if len(above) == 0:
        return []
    clusters: list[list[int]] = [[int(above[0])]]
    for v in above[1:]:
        if v - clusters[-1][-1] <= merge_dist:
            clusters[-1].append(int(v))
        else:
            clusters.append([int(v)])
    return [int(round(sum(c) / len(c))) for c in clusters]


def detect_grid(image: Image.Image, dpi: int = DEFAULT_DPI) -> tuple[list[int], list[int]] | None:
    """Returns (row_ys, col_xs) sorted grid line coordinates, or None.

    A row/column is first considered a *candidate* grid line once the
    morphological opening (which already discards anything shorter than
    `MIN_LINE_INCHES`) leaves a non-trivial number of "on" pixels in it -
    an absolute pixel count, not a fraction of the full page, so small
    tables on large pages are detected just as reliably as page-filling
    ones. Candidates are then re-checked against `_filter_spurious_lines`,
    which discards ones that don't actually span the table: a coincidental
    alignment of glyph strokes across several characters (e.g. in a run of
    text) can produce a contiguous dark run just long enough to survive
    the opening without being anywhere near a real ruled line.
    """
    binary = _binarize(image)
    horizontal, vertical = _line_masks(binary, dpi=dpi)
    kernel_len = max(20, round(dpi * MIN_LINE_INCHES))
    presence_threshold = kernel_len * 0.3

    row_sum = (horizontal > 0).sum(axis=1)
    col_sum = (vertical > 0).sum(axis=0)

    row_ys = _cluster_positions(row_sum, threshold=presence_threshold)
    col_xs = _cluster_positions(col_sum, threshold=presence_threshold)

    if len(row_ys) < MIN_GRID_SIZE or len(col_xs) < MIN_GRID_SIZE:
        return None

    row_ys, col_xs = _filter_spurious_lines(horizontal, vertical, row_ys, col_xs)
    if len(row_ys) < MIN_GRID_SIZE or len(col_xs) < MIN_GRID_SIZE:
        return None
    return sorted(row_ys), sorted(col_xs)


def _filter_spurious_lines(
    horizontal_mask: np.ndarray, vertical_mask: np.ndarray, row_ys: list[int], col_xs: list[int]
) -> tuple[list[int], list[int]]:
    """Drop candidate grid lines that don't actually span the table.

    A genuine ruled line runs (nearly) the full width/height of the table;
    a stray surviving run from text glyphs covers only a sliver of it. This
    re-checks each candidate's coverage across the table's full extent
    (rather than just "enough absolute on-pixels somewhere"), which is what
    actually distinguishes the two cases.
    """
    col_min, col_max = col_xs[0], col_xs[-1]
    row_min, row_max = row_ys[0], row_ys[-1]
    kept_rows = [
        y
        for y in row_ys
        if _segment_line_presence(horizontal_mask, y, col_min, col_max, vertical=False) >= LINE_PRESENCE_THRESHOLD
    ]
    kept_cols = [
        x
        for x in col_xs
        if _segment_line_presence(vertical_mask, x, row_min, row_max, vertical=True) >= LINE_PRESENCE_THRESHOLD
    ]
    return kept_rows, kept_cols


def _segment_line_presence(mask: np.ndarray, axis_fixed: int, start: int, end: int, vertical: bool) -> float:
    if end <= start:
        return 0.0
    if vertical:
        segment = mask[start:end, axis_fixed]
    else:
        segment = mask[axis_fixed, start:end]
    if segment.size == 0:
        return 0.0
    return float((segment > 0).sum()) / segment.size


def _union_find(n: int) -> list[int]:
    return list(range(n))


def _find(parent: list[int], x: int) -> int:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent: list[int], a: int, b: int) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[ra] = rb


def _build_cells_with_merges(
    horizontal_mask: np.ndarray, vertical_mask: np.ndarray, row_ys: list[int], col_xs: list[int]
) -> list[RawCell]:
    n_rows = len(row_ys) - 1
    n_cols = len(col_xs) - 1

    def idx(r: int, c: int) -> int:
        return r * n_cols + c

    parent = _union_find(n_rows * n_cols)

    for r in range(n_rows):
        for c in range(n_cols - 1):
            presence = _segment_line_presence(vertical_mask, col_xs[c + 1], row_ys[r], row_ys[r + 1], vertical=True)
            if presence < LINE_PRESENCE_THRESHOLD:
                _union(parent, idx(r, c), idx(r, c + 1))
    for r in range(n_rows - 1):
        for c in range(n_cols):
            presence = _segment_line_presence(horizontal_mask, row_ys[r + 1], col_xs[c], col_xs[c + 1], vertical=False)
            if presence < LINE_PRESENCE_THRESHOLD:
                _union(parent, idx(r, c), idx(r + 1, c))

    groups: dict[int, list[tuple[int, int]]] = {}
    for r in range(n_rows):
        for c in range(n_cols):
            root = _find(parent, idx(r, c))
            groups.setdefault(root, []).append((r, c))

    cells: list[RawCell] = []
    for members in groups.values():
        rows = [m[0] for m in members]
        cols = [m[1] for m in members]
        r0, r1 = min(rows), max(rows)
        c0, c1 = min(cols), max(cols)
        cells.append(
            RawCell(
                text="",
                row=r0,
                col=c0,
                row_span=r1 - r0 + 1,
                col_span=c1 - c0 + 1,
                confidence=100.0,
                source="ocr",
            )
        )
    return cells


def _erase_grid_lines(image: Image.Image, horizontal_mask: np.ndarray, vertical_mask: np.ndarray) -> np.ndarray:
    """Whiteout the detected ruling pixels so cropped cells don't carry a
    sliver of the border into the OCR pass.

    A fixed pixel padding around each cell crop is not enough to reliably
    clear the border: rendered line width depends on the source PDF's own
    stroke width and the render DPI, and a too-thin margin leaves a partial
    line edge that Tesseract reads as stray glyphs (e.g. "|") and that
    throws off recognition of the real text next to it. Erasing the exact
    line pixels (already isolated by the morphological opening used for
    grid detection) is robust regardless of how thick the drawn lines are.
    """
    np_image = np.array(image).copy()
    line_mask = (horizontal_mask > 0) | (vertical_mask > 0)
    np_image[line_mask] = 255
    return np_image


def extract_table_from_grid(image: Image.Image, lang: str, dpi: int = DEFAULT_DPI) -> RawTable | None:
    grid = detect_grid(image, dpi=dpi)
    if grid is None:
        return None
    row_ys, col_xs = grid
    binary = _binarize(image)
    horizontal_mask, vertical_mask = _line_masks(binary, dpi=dpi)
    cells = _build_cells_with_merges(horizontal_mask, vertical_mask, row_ys, col_xs)
    if not cells:
        return None

    np_image = _erase_grid_lines(image, horizontal_mask, vertical_mask)
    for cell in cells:
        x0 = max(0, col_xs[cell.col] + CELL_PADDING_PX)
        x1 = min(np_image.shape[1], col_xs[cell.col + cell.col_span] - CELL_PADDING_PX)
        y0 = max(0, row_ys[cell.row] + CELL_PADDING_PX)
        y1 = min(np_image.shape[0], row_ys[cell.row + cell.row_span] - CELL_PADDING_PX)
        if x1 <= x0 or y1 <= y0:
            continue
        crop = Image.fromarray(np_image[y0:y1, x0:x1])
        words = ocr_engine.ocr_words(crop, lang=lang, psm=6)
        cell.text = " ".join(w.text for w in words).strip()
        cell.confidence = (sum(w.confidence for w in words) / len(words)) if words else 0.0

    return RawTable(
        n_rows=len(row_ys) - 1,
        n_cols=len(col_xs) - 1,
        cells=cells,
        strategy="ocr-lines",
        bbox=(float(col_xs[0]), float(row_ys[0]), float(col_xs[-1]), float(row_ys[-1])),
    )


def _cluster_rows(words: list[Word]) -> list[list[Word]]:
    if not words:
        return []
    ordered = sorted(words, key=lambda w: w.y0)
    rows: list[list[Word]] = [[ordered[0]]]
    row_bottom = ordered[0].y1
    for w in ordered[1:]:
        avg_h = sum(x.y1 - x.y0 for x in rows[-1]) / len(rows[-1])
        if w.y0 <= row_bottom - 0.4 * avg_h:
            rows[-1].append(w)
            row_bottom = max(row_bottom, w.y1)
        else:
            rows.append([w])
            row_bottom = w.y1
    for row in rows:
        row.sort(key=lambda w: w.x0)
    return rows


def _column_boundaries(words: list[Word]) -> list[int]:
    x_min = min(w.x0 for w in words)
    x_max = max(w.x1 for w in words)
    width = x_max - x_min + 1
    coverage = np.zeros(width, dtype=bool)
    for w in words:
        coverage[w.x0 - x_min : w.x1 - x_min] = True

    heights = [w.y1 - w.y0 for w in words]
    median_h = sorted(heights)[len(heights) // 2] if heights else 20
    min_gap_px = max(18, int(median_h * 1.0))

    boundaries = [x_min]
    in_gap = False
    gap_start = 0
    for i, val in enumerate(coverage):
        if not val and not in_gap:
            in_gap = True
            gap_start = i
        elif val and in_gap:
            in_gap = False
            if i - gap_start >= min_gap_px:
                boundaries.append(x_min + (gap_start + i) // 2)
    if in_gap and width - gap_start >= min_gap_px:
        boundaries.append(x_min + (gap_start + width) // 2)
    boundaries.append(x_max + 1)
    return sorted(set(boundaries))


def extract_table_from_words(image: Image.Image, lang: str) -> RawTable | None:
    words = ocr_engine.ocr_words(image, lang=lang, psm=3)
    if len(words) < 4:
        return None
    rows = _cluster_rows(words)
    if len(rows) < MIN_GRID_SIZE:
        return None
    boundaries = _column_boundaries(words)
    if len(boundaries) - 1 < MIN_GRID_SIZE:
        return None

    cells: list[RawCell] = []
    for r_idx, row_words in enumerate(rows):
        col_buckets: dict[int, list[Word]] = {}
        for w in row_words:
            cx = (w.x0 + w.x1) / 2
            col = max(0, min(len(boundaries) - 2, _bucket_index(boundaries, cx)))
            col_buckets.setdefault(col, []).append(w)
        for col, bucket in col_buckets.items():
            bucket.sort(key=lambda w: w.x0)
            text = " ".join(w.text for w in bucket)
            confidence = sum(w.confidence for w in bucket) / len(bucket)
            cells.append(
                RawCell(text=text, row=r_idx, col=col, confidence=confidence, source="ocr")
            )
    if not cells:
        return None
    return RawTable(
        n_rows=len(rows),
        n_cols=len(boundaries) - 1,
        cells=cells,
        strategy="ocr-text",
        bbox=None,
    )


def _bucket_index(boundaries: list[int], x: float) -> int:
    for i in range(len(boundaries) - 1):
        if boundaries[i] <= x < boundaries[i + 1]:
            return i
    return len(boundaries) - 2


def detect_and_extract_tables(image: Image.Image, lang: str, dpi: int = DEFAULT_DPI) -> list[RawTable]:
    table = extract_table_from_grid(image, lang, dpi=dpi)
    if table is not None:
        return [table]
    table = extract_table_from_words(image, lang)
    if table is not None:
        return [table]
    return []
