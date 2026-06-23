"""Decide, per page and for the document as a whole, whether direct text
extraction is usable or OCR is required.

Classification is intentionally conservative: a page is only treated as
"text" when pdfplumber can see a meaningful number of embedded characters.
Anything else (image-only pages, or pages with too little embedded text to
trust) is routed to OCR so we never silently drop content.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pdfplumber

MIN_CHARS_FOR_TEXT_PAGE = 8
MIN_IMAGE_AREA_RATIO_FOR_SCAN = 0.5


class PageKind(str, Enum):
    TEXT = "text"
    SCANNED = "scanned"
    BLANK = "blank"


class DocumentKind(str, Enum):
    TEXT = "text"
    SCANNED = "scanned"
    MIXED = "mixed"
    EMPTY = "empty"


@dataclass(slots=True)
class PageClassification:
    index: int
    kind: PageKind
    char_count: int
    image_area_ratio: float
    rotation: int
    width: float
    height: float


@dataclass(slots=True)
class DocumentClassification:
    pages: list[PageClassification]
    kind: DocumentKind
    page_count: int


def _image_area_ratio(page: pdfplumber.page.Page) -> float:
    page_area = float(page.width) * float(page.height)
    if page_area <= 0:
        return 0.0
    covered = 0.0
    for img in page.images:
        x0 = max(0.0, float(img["x0"]))
        x1 = min(float(page.width), float(img["x1"]))
        top = max(0.0, float(img["top"]))
        bottom = min(float(page.height), float(img["bottom"]))
        w = max(0.0, x1 - x0)
        h = max(0.0, bottom - top)
        covered += w * h
    return min(1.0, covered / page_area)


def classify_page(page: pdfplumber.page.Page, index: int) -> PageClassification:
    char_count = len(page.chars)
    image_ratio = _image_area_ratio(page)
    rotation = int(page.rotation or 0) % 360

    if char_count >= MIN_CHARS_FOR_TEXT_PAGE:
        kind = PageKind.TEXT
    elif image_ratio >= MIN_IMAGE_AREA_RATIO_FOR_SCAN:
        kind = PageKind.SCANNED
    elif char_count > 0 or image_ratio > 0:
        # A little bit of text/image but below confident thresholds: still
        # worth an OCR pass rather than treating it as empty/blank.
        kind = PageKind.SCANNED
    else:
        kind = PageKind.BLANK

    return PageClassification(
        index=index,
        kind=kind,
        char_count=char_count,
        image_area_ratio=image_ratio,
        rotation=rotation,
        width=float(page.width),
        height=float(page.height),
    )


def classify_document(pdf_path: str | Path) -> DocumentClassification:
    pages: list[PageClassification] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            pages.append(classify_page(page, i))

    non_blank = [p for p in pages if p.kind != PageKind.BLANK]
    if not non_blank:
        doc_kind = DocumentKind.EMPTY
    elif all(p.kind == PageKind.TEXT for p in non_blank):
        doc_kind = DocumentKind.TEXT
    elif all(p.kind == PageKind.SCANNED for p in non_blank):
        doc_kind = DocumentKind.SCANNED
    else:
        doc_kind = DocumentKind.MIXED

    return DocumentClassification(pages=pages, kind=doc_kind, page_count=len(pages))
