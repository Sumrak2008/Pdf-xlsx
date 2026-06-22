"""Shared pytest fixtures.

`make_table_pdf` and `make_borderless_pdf` build tiny synthetic PDFs on the
fly for unit tests that need a real PDF rather than calling pipeline
internals on bare images. The bundled DejaVu font (tools/fonts/, Bitstream
Vera license - see DEJAVU_LICENSE.txt there) is used so Cyrillic text
renders correctly in any environment, including CI, without depending on
whatever fonts happen to be installed on the runner.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

FONTS_DIR = Path(__file__).resolve().parent.parent / "tools" / "fonts"

_FONT_REGISTERED = False


def _ensure_font_registered() -> None:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    pdfmetrics.registerFont(TTFont("DejaVuSans", str(FONTS_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(FONTS_DIR / "DejaVuSans-Bold.ttf")))
    _FONT_REGISTERED = True


@pytest.fixture
def make_table_pdf(tmp_path):
    """Build a ruled (bordered) table PDF. Returns the output path."""

    def _make(
        rows: list[list[str]],
        path: Path | None = None,
        spans: list[tuple[tuple[int, int], tuple[int, int]]] | None = None,
        col_widths: list[float] | None = None,
    ) -> Path:
        _ensure_font_registered()
        out = path or (tmp_path / "table.pdf")
        doc = SimpleDocTemplate(str(out), pagesize=letter)
        t = Table(rows, colWidths=col_widths)
        style = [
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
        ]
        for start, end in spans or []:
            style.append(("SPAN", start, end))
        t.setStyle(TableStyle(style))
        doc.build([t])
        return out

    return _make


@pytest.fixture
def make_borderless_pdf(tmp_path):
    """Build a borderless table as plain positioned text. Returns the output path."""

    def _make(rows: list[list[str]], path: Path | None = None, col_xs: list[int] | None = None) -> Path:
        _ensure_font_registered()
        out = path or (tmp_path / "borderless.pdf")
        c = canvas.Canvas(str(out), pagesize=letter)
        c.setFont("DejaVuSans", 11)
        xs = col_xs or [80, 200, 350, 450]
        y = 700
        for row in rows:
            for x, text in zip(xs, row, strict=False):
                c.drawString(x, y, text)
            y -= 30
        c.save()
        return out

    return _make


@pytest.fixture
def render_page():
    """Rasterize a PDF's first page to a PIL Image at the given DPI."""

    def _render(pdf_path: Path, dpi: int = 300, page_index: int = 0):
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(str(pdf_path))
        page = doc[page_index]
        bitmap = page.render(scale=dpi / 72.0)
        return bitmap.to_pil().convert("RGB")

    return _render
