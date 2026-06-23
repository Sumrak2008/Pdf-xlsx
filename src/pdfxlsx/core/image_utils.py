"""Page rasterization and orientation correction for the OCR path.

Two independent sources of rotation are handled:

1. The PDF page's own `/Rotate` attribute (set by the document author or by
   scanning software that knows the page was fed in sideways). This is
   applied while rendering, via `pypdfium2`.
2. Rotation "baked into" the pixels themselves, with no `/Rotate` flag at
   all (e.g. a photographed/scanned page that was simply fed in sideways
   and the scanner did not record that fact). This is detected after
   rendering using Tesseract's orientation-and-script-detection (OSD) and
   corrected by physically rotating the rasterized image.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pypdfium2 as pdfium
from PIL import Image

from pdfxlsx.core import ocr_engine

logger = logging.getLogger(__name__)

OSD_MIN_CONFIDENCE = 0.5


@dataclass(slots=True)
class RasterizedPage:
    image: Image.Image
    pdf_rotation_applied: int
    osd_rotation_applied: int


def _quarter_turn_for_pdfium(pdf_rotation_degrees: int) -> int:
    """Convert a PDF /Rotate value to the argument pypdfium2 expects.

    Empirically verified: pypdfium2's `Page.render(rotation=...)` rotates
    the opposite direction of the PDF's own clockwise `/Rotate` convention,
    so the two must be combined as `(360 - flag) % 360`.
    """
    return (360 - (pdf_rotation_degrees % 360)) % 360


def rasterize_page(
    pdf_doc: pdfium.PdfDocument,
    page_index: int,
    dpi: int,
    correct_baked_in_rotation: bool = True,
) -> RasterizedPage:
    page = pdf_doc[page_index]
    pdf_rotation = page.get_rotation() % 360
    scale = dpi / 72.0
    bitmap = page.render(scale=scale, rotation=_quarter_turn_for_pdfium(pdf_rotation))
    image = bitmap.to_pil().convert("RGB")

    osd_applied = 0
    if correct_baked_in_rotation and pdf_rotation == 0:
        image, osd_applied = detect_and_fix_orientation(image)

    return RasterizedPage(
        image=image, pdf_rotation_applied=pdf_rotation, osd_rotation_applied=osd_applied
    )


def detect_and_fix_orientation(image: Image.Image) -> tuple[Image.Image, int]:
    """Detect baked-in rotation via Tesseract OSD and return a corrected copy.

    Returns `(image, 0)` unchanged if OSD found no rotation or was not
    confident enough to act on. This is a best-effort heuristic: OSD can
    fail to reach a confident verdict on pages with little or unevenly
    distributed text, in which case the page is left as rendered and the
    limitation is reported.
    """
    try:
        osd = ocr_engine.detect_orientation(image)
    except Exception as exc:  # OSD is best-effort; never let it abort processing.
        logger.warning("OSD orientation detection failed: %s", exc)
        return image, 0
    if osd is None:
        return image, 0
    rotate_degrees, confidence = osd
    if rotate_degrees == 0 or confidence < OSD_MIN_CONFIDENCE:
        return image, 0
    return rotate_image(image, rotate_degrees), rotate_degrees


def rotate_image(image: Image.Image, degrees_clockwise: int) -> Image.Image:
    return image.rotate(-degrees_clockwise, expand=True)
