"""Thin wrapper around Tesseract OCR (via pytesseract) using only the
bundled, portable binary and language data - never the system PATH.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytesseract
from PIL import Image
from pytesseract import Output

from pdfxlsx.core import paths
from pdfxlsx.core.errors import OcrEngineUnavailableError

logger = logging.getLogger(__name__)

_configured = False


@dataclass(slots=True)
class Word:
    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int

    @property
    def x0(self) -> int:
        return self.left

    @property
    def x1(self) -> int:
        return self.left + self.width

    @property
    def y0(self) -> int:
        return self.top

    @property
    def y1(self) -> int:
        return self.top + self.height


def configure() -> None:
    """Point pytesseract at the bundled tesseract binary and tessdata.

    Raises OcrEngineUnavailableError if neither a bundled nor (in dev mode)
    a system installation can be found.
    """
    global _configured
    exe = paths.tesseract_executable()
    if exe is None:
        raise OcrEngineUnavailableError("tesseract executable not found")
    pytesseract.pytesseract.tesseract_cmd = str(exe)
    tessdata = paths.tessdata_prefix()
    if tessdata is None:
        raise OcrEngineUnavailableError("tessdata directory not found")
    import os

    os.environ["TESSDATA_PREFIX"] = str(tessdata)
    _configured = True


def _ensure_configured() -> None:
    if not _configured:
        configure()


def detect_orientation(image: Image.Image) -> tuple[int, float] | None:
    """Returns (rotate_degrees_clockwise_to_fix, confidence) or None."""
    _ensure_configured()
    try:
        osd_text = pytesseract.image_to_osd(image)
    except pytesseract.TesseractError as exc:
        logger.debug("OSD inconclusive: %s", exc)
        return None
    rotate = 0
    confidence = 0.0
    for line in osd_text.splitlines():
        if line.startswith("Rotate:"):
            rotate = int(line.split(":")[1].strip())
        elif line.startswith("Orientation confidence:"):
            confidence = float(line.split(":")[1].strip())
    return rotate, confidence


def ocr_words(image: Image.Image, lang: str, psm: int = 6) -> list[Word]:
    """Word-level OCR with bounding boxes and per-word confidence (0-100)."""
    _ensure_configured()
    config = f"--oem 1 --psm {psm}"
    data = pytesseract.image_to_data(image, lang=lang, config=config, output_type=Output.DICT)
    words: list[Word] = []
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        if not text:
            continue
        conf_raw = data["conf"][i]
        try:
            conf = float(conf_raw)
        except (TypeError, ValueError):
            conf = -1.0
        if conf < 0:
            continue
        words.append(
            Word(
                text=text,
                confidence=conf,
                left=int(data["left"][i]),
                top=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
            )
        )
    return words


def ocr_plain_text(image: Image.Image, lang: str, psm: int = 3) -> str:
    _ensure_configured()
    config = f"--oem 1 --psm {psm}"
    return pytesseract.image_to_string(image, lang=lang, config=config)
