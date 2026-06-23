"""Shared data structures passed between pipeline stages.

Both the direct-text extraction path (text_extractor.py) and the OCR path
(table_detector.py) produce the same `RawTable`/`RawCell` shapes so that
downstream stages (cell_typing.py, xlsx_writer.py) do not need to know
where a table came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RawCell:
    text: str
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    confidence: float = 100.0
    """0-100. 100 means the text came from the PDF's own structure (not OCR)."""
    source: str = "text"
    """"text" or "ocr"."""


@dataclass(slots=True)
class RawTable:
    n_rows: int
    n_cols: int
    cells: list[RawCell] = field(default_factory=list)
    """Anchor cells only; positions covered by a span are omitted."""
    strategy: str = "lines"
    """One of "lines", "text", "ocr-lines", "ocr-text" - kept for the report."""
    bbox: tuple[float, float, float, float] | None = None


@dataclass(slots=True)
class PageOutcome:
    page_index: int
    page_kind: str
    extraction_method: str
    """"direct", "ocr", "failed", or "blank"."""
    tables: list[TypedTable] = field(default_factory=list)
    rotation_degrees: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    plain_text_paragraphs: list[str] = field(default_factory=list)
    """Free-form text on the page that is not part of any detected table."""


@dataclass(slots=True)
class TypedCell:
    value: object
    display_text: str
    number_format: str | None
    row: int
    col: int
    row_span: int
    col_span: int
    is_uncertain: bool
    comment: str | None
    is_header: bool = False
    align_h: str | None = None
    wrap_text: bool = False


@dataclass(slots=True)
class TypedTable:
    n_rows: int
    n_cols: int
    cells: list[TypedCell]
    page_index: int
    table_index_on_page: int
    source: str


@dataclass(slots=True)
class DocumentResult:
    source_pdf: str
    page_count: int = 0
    pages: list[PageOutcome] = field(default_factory=list)
    tables: list[TypedTable] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    cancelled: bool = False
