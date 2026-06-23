"""TypedTable -> real, editable .xlsx cells via openpyxl.

Purely mechanical from here on: by the time a `TypedCell` reaches this
module, every type/uncertainty decision has already been made upstream
(cell_typing.py). This module's job is just to place values at the right
sheet coordinates, apply merges, and render the few presentational
decisions (uncertain-cell highlighting, header styling, borders, column
widths) that follow directly from data already on the `TypedCell`.

Borders are only drawn for tables whose source strategy is one of the
"lines"/"ocr-lines" kind - i.e. ones we know for a fact had a ruled grid in
the original PDF/scan. For borderless ("text"/"ocr-text") tables we have
no reliable evidence of where (or whether) a border belongs, so none is
invented.
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from pdfxlsx.core.config import ConversionSettings, SheetSplitMode
from pdfxlsx.core.models import DocumentResult, TypedTable

UNCERTAIN_FILL = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")

# openpyxl writes VML comment-drawing elements via namespace URIs only, with
# no prefix registered, so the serializer falls back to auto-generated
# ns0/ns1/ns2 prefixes. That is valid XML, but Excel's legacy VML reader
# (the format predates real namespace support) matches these prefixes
# literally rather than by URI, so it can't find its own shapes and the
# whole file gets flagged as unreadable. Canonicalizing to the v:/o:/x:
# prefixes real Excel/Microsoft-authored VML always uses fixes this.
_VML_CANONICAL_PREFIXES = {
    "urn:schemas-microsoft-com:vml": "v",
    "urn:schemas-microsoft-com:office:office": "o",
    "urn:schemas-microsoft-com:office:excel": "x",
}


def _canonicalize_vml_prefixes(vml_bytes: bytes) -> bytes:
    text = vml_bytes.decode("utf-8")
    declared = dict(re.findall(r'xmlns:(\w+)="([^"]+)"', text))
    for uri, canonical in _VML_CANONICAL_PREFIXES.items():
        old_prefix = next((p for p, u in declared.items() if u == uri), None)
        if old_prefix is None or old_prefix == canonical:
            continue
        text = text.replace(f"xmlns:{old_prefix}=", f"xmlns:{canonical}=")
        text = text.replace(f"{old_prefix}:", f"{canonical}:")
    return text.encode("utf-8")


def _fix_comment_vml_drawings(xlsx_path: str) -> None:
    """Rewrite VML comment-drawing prefixes in an already-saved workbook.

    Must run as a post-processing pass after `wb.save()`: openpyxl's own
    comment/VML writer is what produces the malformed prefixes, and it
    offers no hook to influence that part of its serialization.
    """
    with zipfile.ZipFile(xlsx_path, "r") as archive:
        names = archive.namelist()
        if not any(name.startswith("xl/drawings/commentsDrawing") for name in names):
            return
        contents = {name: archive.read(name) for name in names}

    for name, data in contents.items():
        if name.startswith("xl/drawings/commentsDrawing") and name.endswith(".vml"):
            contents[name] = _canonicalize_vml_prefixes(data)

    # mkstemp() creates the temp file with mode 0600 (owner read/write only),
    # and os.replace() carries that mode over onto xlsx_path - silently
    # downgrading it from wb.save()'s normal, broadly-readable permissions.
    # Restore the original mode so callers/services reading the file back
    # don't lose access.
    original_mode = os.stat(xlsx_path).st_mode

    out_dir = os.path.dirname(xlsx_path) or "."
    fd, tmp_path = tempfile.mkstemp(suffix=".xlsx", dir=out_dir)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in contents.items():
                archive.writestr(name, data)
        os.chmod(tmp_path, original_mode)
        os.replace(tmp_path, xlsx_path)
    except Exception:
        os.unlink(tmp_path)
        raise
HEADER_FONT = Font(bold=True)
THIN_SIDE = Side(style="thin")
THIN_BORDER = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)
COMMENT_AUTHOR = "PdfXlsx"

GRID_SOURCES = {"lines", "ocr-lines"}

MIN_COLUMN_WIDTH = 8
MAX_COLUMN_WIDTH = 60
_INVALID_SHEET_CHARS_RE = re.compile(r"[:\\/?*\[\]]")


def _safe_sheet_name(name: str, used: set[str]) -> str:
    cleaned = _INVALID_SHEET_CHARS_RE.sub("_", name)[:31]
    candidate = cleaned or "Лист"
    suffix = 2
    while candidate in used:
        trimmed = cleaned[: 31 - len(f" ({suffix})")] or "Лист"
        candidate = f"{trimmed} ({suffix})"
        suffix += 1
    used.add(candidate)
    return candidate


def _write_table(ws: Worksheet, table: TypedTable, origin_row: int, origin_col: int, settings: ConversionSettings) -> int:
    """Writes one table at (origin_row, origin_col) (0-indexed). Returns the
    0-indexed row just below the table, for stacking the next one."""
    draw_borders = table.source in GRID_SOURCES
    column_widths: dict[int, int] = {}

    for cell in table.cells:
        sheet_row = origin_row + cell.row + 1
        sheet_col = origin_col + cell.col + 1
        target = ws.cell(row=sheet_row, column=sheet_col, value=cell.value if cell.value != "" else None)
        if cell.number_format:
            target.number_format = cell.number_format
        if cell.is_header:
            target.font = HEADER_FONT
        if cell.is_uncertain and settings.highlight_uncertain_cells:
            target.fill = UNCERTAIN_FILL
            if cell.comment:
                target.comment = Comment(cell.comment, COMMENT_AUTHOR)
        target.alignment = Alignment(
            horizontal=cell.align_h or "left", vertical="center", wrap_text=cell.wrap_text
        )

        if cell.row_span > 1 or cell.col_span > 1:
            ws.merge_cells(
                start_row=sheet_row,
                start_column=sheet_col,
                end_row=sheet_row + cell.row_span - 1,
                end_column=sheet_col + cell.col_span - 1,
            )

        if draw_borders:
            for r in range(sheet_row, sheet_row + cell.row_span):
                for c in range(sheet_col, sheet_col + cell.col_span):
                    ws.cell(row=r, column=c).border = THIN_BORDER

        content_width = len(cell.display_text)
        column_widths[cell.col] = max(column_widths.get(cell.col, 0), content_width)

    for col_idx, width in column_widths.items():
        letter = get_column_letter(origin_col + col_idx + 1)
        target_width = max(MIN_COLUMN_WIDTH, min(MAX_COLUMN_WIDTH, width + 2))
        current = ws.column_dimensions[letter].width
        if current is None or target_width > current:
            ws.column_dimensions[letter].width = target_width

    return origin_row + table.n_rows + 1


def _write_paragraphs(ws: Worksheet, paragraphs: list[str], origin_row: int) -> int:
    row = origin_row
    for paragraph in paragraphs:
        ws.cell(row=row + 1, column=1, value=paragraph)
        row += 1
    return row


def write_document(result: DocumentResult, settings: ConversionSettings, output_path: str) -> None:
    wb = Workbook()
    first_sheet = wb.active
    used_names: set[str] = set()
    mode = settings.effective_sheet_split_mode()
    any_sheet_used = False

    def _take_first_sheet_or_create(name: str) -> Worksheet:
        nonlocal first_sheet, any_sheet_used
        safe_name = _safe_sheet_name(name, used_names)
        if not any_sheet_used:
            first_sheet.title = safe_name
            any_sheet_used = True
            return first_sheet
        return wb.create_sheet(title=safe_name)

    if mode == SheetSplitMode.PER_TABLE:
        table_counter_by_page: dict[int, int] = {}
        for table in result.tables:
            table_counter_by_page[table.page_index] = table_counter_by_page.get(table.page_index, 0) + 1
            idx = table_counter_by_page[table.page_index]
            ws = _take_first_sheet_or_create(f"Стр.{table.page_index + 1}_Табл.{idx}")
            _write_table(ws, table, origin_row=0, origin_col=0, settings=settings)
        for page in result.pages:
            if page.plain_text_paragraphs:
                ws = _take_first_sheet_or_create(f"Текст_стр.{page.page_index + 1}")
                _write_paragraphs(ws, page.plain_text_paragraphs, origin_row=0)
    else:
        tables_by_page: dict[int, list[TypedTable]] = {}
        for table in result.tables:
            tables_by_page.setdefault(table.page_index, []).append(table)
        for page in result.pages:
            page_tables = tables_by_page.get(page.page_index, [])
            if not page_tables and not page.plain_text_paragraphs:
                continue
            ws = _take_first_sheet_or_create(f"Стр. {page.page_index + 1}")
            row = 0
            for table in page_tables:
                row = _write_table(ws, table, origin_row=row, origin_col=0, settings=settings)
                row += 1
            if page.plain_text_paragraphs:
                _write_paragraphs(ws, page.plain_text_paragraphs, origin_row=row)

    if not any_sheet_used:
        first_sheet.title = _safe_sheet_name("Лист1", used_names)
        first_sheet.cell(row=1, column=1, value="Таблицы и текст не обнаружены")

    wb.save(output_path)
    _fix_comment_vml_drawings(output_path)
