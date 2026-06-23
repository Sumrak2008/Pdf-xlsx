"""User-configurable conversion settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class OcrLanguage(str, Enum):
    RUSSIAN = "rus"
    ENGLISH = "eng"
    RUSSIAN_ENGLISH = "rus+eng"

    @property
    def label_ru(self) -> str:
        return {
            OcrLanguage.RUSSIAN: "Русский",
            OcrLanguage.ENGLISH: "Английский",
            OcrLanguage.RUSSIAN_ENGLISH: "Русский + английский",
        }[self]


class SheetSplitMode(str, Enum):
    """How tables are distributed across worksheets of the output workbook."""

    PER_DOCUMENT_PAGE_GROUPS = "per_page"
    PER_TABLE = "per_table"


@dataclass(slots=True)
class ConversionSettings:
    ocr_language: OcrLanguage = OcrLanguage.RUSSIAN_ENGLISH
    highlight_uncertain_cells: bool = True
    ocr_confidence_threshold: int = 70
    """0-100. OCR words/cells below this confidence are marked uncertain."""
    sheet_per_page: bool = True
    sheet_per_table: bool = False
    save_report: bool = True
    output_dir: str | None = None
    ocr_dpi: int = 300
    min_free_disk_mb: float = 200.0

    def __post_init__(self) -> None:
        self.ocr_confidence_threshold = max(0, min(100, self.ocr_confidence_threshold))

    def effective_sheet_split_mode(self) -> SheetSplitMode:
        """Resolve the two independent checkboxes to one effective mode.

        "Per table" takes precedence when both are checked, since it is the
        more specific grouping. When neither is checked, "per page" is used
        as the predictable default (one PDF page == one worksheet).
        """
        if self.sheet_per_table:
            return SheetSplitMode.PER_TABLE
        return SheetSplitMode.PER_DOCUMENT_PAGE_GROUPS


@dataclass(slots=True)
class BatchJob:
    """A single PDF queued for conversion, plus the settings to apply to it."""

    pdf_path: str
    settings: ConversionSettings = field(default_factory=ConversionSettings)
