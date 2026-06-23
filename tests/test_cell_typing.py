from __future__ import annotations

from datetime import date

import pytest

from pdfxlsx.core.cell_typing import infer_cell_type, type_cell
from pdfxlsx.core.config import ConversionSettings
from pdfxlsx.core.models import RawCell


@pytest.mark.parametrize(
    "text,expected_value",
    [
        ("007", "007"),
        ("000123", "000123"),
        ("0", 0),
        ("42", 42),
        ("-13", -13),
        ("12.50", 12.50),
        ("1875.00", 1875.00),
        ("12,50", 12.50),
        ("1 234.56", 1234.56),
        ("1,234.56", 1234.56),
        ("1.234,56", 1234.56),
    ],
)
def test_numeric_and_leading_zero_rules(text, expected_value):
    result = infer_cell_type(text)
    assert result.value == expected_value


def test_leading_zero_code_keeps_text_type_not_int():
    result = infer_cell_type("007")
    assert isinstance(result.value, str)
    assert result.value == "007"


@pytest.mark.parametrize(
    "text,expected_codes",
    [
        ("M6x20", "M6x20"),
        ("ГОСТ 7798-70", "ГОСТ 7798-70"),
        ("ABC-123", "ABC-123"),
        ("Болт М6", "Болт М6"),
    ],
)
def test_technical_codes_stay_text(text, expected_codes):
    result = infer_cell_type(text)
    assert result.value == expected_codes
    assert isinstance(result.value, str)


def test_percent():
    result = infer_cell_type("12.5%")
    assert result.value == pytest.approx(0.125)
    assert result.number_format == "0.##%"


def test_currency_rub():
    result = infer_cell_type("1 234.56 руб.")
    assert result.value == pytest.approx(1234.56)
    assert "₽" in result.number_format


def test_currency_usd():
    result = infer_cell_type("$99.99")
    assert result.value == pytest.approx(99.99)


def test_iso_date():
    result = infer_cell_type("2024-01-15")
    assert result.value == date(2024, 1, 15)


def test_dotted_date_ru_convention():
    result = infer_cell_type("15.01.2024")
    assert result.value == date(2024, 1, 15)


def test_russian_month_name_date():
    result = infer_cell_type("15 января 2024")
    assert result.value == date(2024, 1, 15)


def test_ambiguous_slashed_date_flagged_uncertain():
    result = infer_cell_type("01/02/2024")
    assert result.value == date(2024, 2, 1)
    assert result.extra_uncertain_reason is not None


def test_unambiguous_slashed_date_not_flagged():
    result = infer_cell_type("31/01/2024")
    assert result.value == date(2024, 1, 31)
    assert result.extra_uncertain_reason is None


def test_empty_text():
    result = infer_cell_type("")
    assert result.value == ""


def test_type_cell_low_ocr_confidence_marks_uncertain():
    settings = ConversionSettings(ocr_confidence_threshold=70)
    cell = RawCell(text="42", row=1, col=0, confidence=50.0, source="ocr")
    typed = type_cell(cell, settings, is_header=False)
    assert typed.is_uncertain is True
    assert "Требуется ручная проверка" in typed.comment
    assert "50" in typed.comment


def test_type_cell_high_confidence_not_uncertain():
    settings = ConversionSettings(ocr_confidence_threshold=70)
    cell = RawCell(text="42", row=1, col=0, confidence=95.0, source="ocr")
    typed = type_cell(cell, settings, is_header=False)
    assert typed.is_uncertain is False
    assert typed.comment is None


def test_type_cell_text_source_never_ocr_uncertain():
    settings = ConversionSettings(ocr_confidence_threshold=70)
    cell = RawCell(text="42", row=1, col=0, confidence=100.0, source="text")
    typed = type_cell(cell, settings, is_header=False)
    assert typed.is_uncertain is False


def test_highlight_disabled_suppresses_uncertain_flag():
    settings = ConversionSettings(ocr_confidence_threshold=70, highlight_uncertain_cells=False)
    cell = RawCell(text="42", row=1, col=0, confidence=10.0, source="ocr")
    typed = type_cell(cell, settings, is_header=False)
    assert typed.is_uncertain is False
    assert typed.comment is None


def test_header_cell_is_marked_and_centered():
    settings = ConversionSettings()
    cell = RawCell(text="Наименование", row=0, col=0, confidence=100.0, source="text")
    typed = type_cell(cell, settings, is_header=True)
    assert typed.is_header is True
    assert typed.align_h == "center"


def test_numeric_cell_right_aligned():
    settings = ConversionSettings()
    cell = RawCell(text="42", row=1, col=0, confidence=100.0, source="text")
    typed = type_cell(cell, settings, is_header=False)
    assert typed.align_h == "right"


def test_long_text_wraps():
    settings = ConversionSettings()
    cell = RawCell(text="Очень длинное наименование товара для теста", row=1, col=0, confidence=100.0, source="text")
    typed = type_cell(cell, settings, is_header=False)
    assert typed.wrap_text is True
