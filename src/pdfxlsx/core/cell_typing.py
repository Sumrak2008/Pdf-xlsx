"""Cell value type inference: RawCell (plain text) -> TypedCell (typed value).

The rules here follow directly from the project's correctness requirements:
never invent characters, never strip leading zeros, never silently convert
something that *might* be a code into a number, and default to text the
moment a type decision would require guessing. A cell is only converted to
a richer type (number/date/percent/currency) when the text matches a
pattern unambiguous enough that no plausible alternative reading exists.

Two independent forms of uncertainty are tracked, both surfaced the same
way (yellow fill + a review comment, applied later in xlsx_writer.py):

* OCR uncertainty - the recognized characters themselves might be wrong
  (confidence below `ConversionSettings.ocr_confidence_threshold`).
* Interpretation uncertainty - the characters are presumed correct, but
  more than one reasonable value follows from them (e.g. "01/02/2024" is
  equally readable as 1 February or 2 January). This is independent of
  OCR: it would exist just as much for a perfectly clean text-layer PDF.
"""

from __future__ import annotations

import re
from datetime import date

from pdfxlsx.core.config import ConversionSettings
from pdfxlsx.core.models import RawCell, RawTable, TypedCell, TypedTable

UNCERTAIN_COMMENT_BASE = "Требуется ручная проверка"

_LEADING_ZERO_CODE_RE = re.compile(r"^0\d+$")
_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_DECIMAL_DOT_RE = re.compile(r"^[+-]?\d+\.\d{1,2}$")
_DECIMAL_COMMA_RE = re.compile(r"^[+-]?\d+,\d{1,2}$")
_GROUPED_DOT_THOUSANDS_RE = re.compile(r"^[+-]?\d{1,3}(?:\.\d{3})+,\d{1,2}$")
_GROUPED_COMMA_THOUSANDS_RE = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+\.\d{1,2}$")
_GROUPED_SPACE_THOUSANDS_RE = re.compile(r"^[+-]?\d{1,3}(?: \d{3})+(?:[.,]\d{1,2})?$")
_PERCENT_RE = re.compile(r"^([+-]?\d+(?:[.,]\d+)?)\s*%$")

_CURRENCY_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"^([+-]?[\d .,]+)\s*(?:₽|руб\.?)$", re.IGNORECASE), "ru", '#,##0.00" ₽"'),
    (re.compile(r"^\$\s*([+-]?[\d .,]+)$"), "us", '"$"#,##0.00'),
    (re.compile(r"^([+-]?[\d .,]+)\s*(?:€|EUR)$", re.IGNORECASE), "eu", '#,##0.00" €"'),
]

_RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_RU_DATE_RE = re.compile(r"^(\d{1,2})\s+([а-яё]+)\s+(\d{4})$", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DOTTED_DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{2,4})$")
_SLASHED_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$")

DATE_NUMBER_FORMAT = "DD.MM.YYYY"
INTEGER_NUMBER_FORMAT = "0"
DECIMAL_NUMBER_FORMAT = "0.00"
PERCENT_NUMBER_FORMAT = "0.##%"


class _TypeResult:
    __slots__ = ("value", "display_text", "number_format", "extra_uncertain_reason")

    def __init__(
        self,
        value: object,
        display_text: str,
        number_format: str | None,
        extra_uncertain_reason: str | None = None,
    ) -> None:
        self.value = value
        self.display_text = display_text
        self.number_format = number_format
        self.extra_uncertain_reason = extra_uncertain_reason


def _as_text(raw_text: str) -> _TypeResult:
    return _TypeResult(value=raw_text, display_text=raw_text, number_format=None)


def _full_year(year: int) -> int:
    if year < 100:
        return 2000 + year if year < 70 else 1900 + year
    return year


def _try_date(text: str) -> _TypeResult | None:
    m = _ISO_DATE_RE.match(text)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        try:
            return _TypeResult(date(y, mo, d), text, DATE_NUMBER_FORMAT)
        except ValueError:
            return None

    m = _RU_DATE_RE.match(text)
    if m:
        day, month_name, year = m.groups()
        month = _RU_MONTHS.get(month_name.lower())
        if month is None:
            return None
        try:
            return _TypeResult(date(int(year), month, int(day)), text, DATE_NUMBER_FORMAT)
        except ValueError:
            return None

    m = _DOTTED_DATE_RE.match(text)
    if m:
        d, mo, y = (int(g) for g in m.groups())
        y = _full_year(y)
        try:
            return _TypeResult(date(y, mo, d), text, DATE_NUMBER_FORMAT)
        except ValueError:
            return None

    m = _SLASHED_DATE_RE.match(text)
    if m:
        a, b, y = (int(g) for g in m.groups())
        y = _full_year(y)
        # DD/MM vs MM/DD is genuinely ambiguous whenever both readings are
        # in range; only treat it as unambiguous when one of the two
        # numbers is not a valid month (must then be the day).
        a_valid_month, b_valid_month = 1 <= a <= 12, 1 <= b <= 12
        if a_valid_month and b_valid_month and a != b:
            try:
                value = date(y, b, a)  # DD/MM/YYYY: the convention used elsewhere in this codebase
            except ValueError:
                return None
            return _TypeResult(
                value, text, DATE_NUMBER_FORMAT, extra_uncertain_reason="неоднозначный формат даты"
            )
        day, month = (a, b) if not a_valid_month else (b, a)
        if not (1 <= month <= 12):
            return None
        try:
            return _TypeResult(date(y, month, day), text, DATE_NUMBER_FORMAT)
        except ValueError:
            return None
    return None


def _try_percent(text: str) -> _TypeResult | None:
    m = _PERCENT_RE.match(text)
    if not m:
        return None
    number_text = m.group(1).replace(",", ".")
    try:
        value = float(number_text) / 100.0
    except ValueError:
        return None
    return _TypeResult(value, text, PERCENT_NUMBER_FORMAT)


def _try_currency(text: str) -> _TypeResult | None:
    for pattern, _tag, number_format in _CURRENCY_PATTERNS:
        m = pattern.match(text)
        if not m:
            continue
        number_text = m.group(1).strip()
        parsed = _try_plain_number(number_text)
        if parsed is None:
            continue
        return _TypeResult(parsed.value, text, number_format)
    return None


def _try_plain_number(text: str) -> _TypeResult | None:
    if _LEADING_ZERO_CODE_RE.match(text):
        return None  # a code, not a number - handled by the caller as text
    if _INTEGER_RE.match(text):
        try:
            return _TypeResult(int(text), text, INTEGER_NUMBER_FORMAT)
        except ValueError:
            return None
    if _DECIMAL_DOT_RE.match(text):
        return _TypeResult(float(text), text, DECIMAL_NUMBER_FORMAT)
    if _DECIMAL_COMMA_RE.match(text):
        return _TypeResult(float(text.replace(",", ".")), text, DECIMAL_NUMBER_FORMAT)
    if _GROUPED_DOT_THOUSANDS_RE.match(text):
        return _TypeResult(float(text.replace(".", "").replace(",", ".")), text, DECIMAL_NUMBER_FORMAT)
    if _GROUPED_COMMA_THOUSANDS_RE.match(text):
        return _TypeResult(float(text.replace(",", "")), text, DECIMAL_NUMBER_FORMAT)
    if _GROUPED_SPACE_THOUSANDS_RE.match(text):
        return _TypeResult(float(text.replace(" ", "").replace(",", ".")), text, DECIMAL_NUMBER_FORMAT)
    return None


def infer_cell_type(text: str) -> _TypeResult:
    """Pick the most specific type that the text unambiguously supports.

    Order matters: percent/currency/date markers are checked before plain
    numbers since they have more specific surrounding syntax (a trailing
    "%", a currency symbol, date separators) that plain-number patterns
    would otherwise also partially match.
    """
    stripped = text.strip()
    if not stripped:
        return _TypeResult(value="", display_text="", number_format=None)
    if _LEADING_ZERO_CODE_RE.match(stripped):
        return _as_text(stripped)
    for try_fn in (_try_date, _try_percent, _try_currency, _try_plain_number):
        result = try_fn(stripped)
        if result is not None:
            return result
    return _as_text(stripped)


def _build_comment(
    settings: ConversionSettings, source: str, confidence: float, extra_reason: str | None
) -> tuple[bool, str | None]:
    reasons: list[str] = []
    ocr_uncertain = source == "ocr" and confidence < settings.ocr_confidence_threshold
    if extra_reason:
        reasons.append(extra_reason)
    if ocr_uncertain:
        reasons.append(f"уверенность распознавания: {confidence:.0f}%")
    if not reasons:
        return False, None
    return True, f"{UNCERTAIN_COMMENT_BASE} ({'; '.join(reasons)})"


def _align_for(value: object, is_header: bool) -> str:
    if is_header:
        return "center"
    if isinstance(value, int | float | date):
        return "right"
    return "left"


def type_cell(cell: RawCell, settings: ConversionSettings, is_header: bool) -> TypedCell:
    result = infer_cell_type(cell.text)
    is_uncertain, comment = _build_comment(settings, cell.source, cell.confidence, result.extra_uncertain_reason)
    if not settings.highlight_uncertain_cells:
        is_uncertain, comment = False, None
    return TypedCell(
        value=result.value,
        display_text=result.display_text,
        number_format=result.number_format,
        row=cell.row,
        col=cell.col,
        row_span=cell.row_span,
        col_span=cell.col_span,
        is_uncertain=is_uncertain,
        comment=comment,
        is_header=is_header,
        align_h=_align_for(result.value, is_header),
        wrap_text=isinstance(result.value, str) and len(result.value) > 25,
    )


def type_table(
    raw_table: RawTable, settings: ConversionSettings, page_index: int, table_index_on_page: int
) -> TypedTable:
    cells = [type_cell(cell, settings, is_header=cell.row == 0) for cell in raw_table.cells]
    return TypedTable(
        n_rows=raw_table.n_rows,
        n_cols=raw_table.n_cols,
        cells=cells,
        page_index=page_index,
        table_index_on_page=table_index_on_page,
        source=raw_table.strategy,
    )
