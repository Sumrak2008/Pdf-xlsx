"""Synthetic PDF generator covering the 16 required test scenarios.

Run as a script to materialize all 16 PDFs into a directory for manual,
visual inspection of the application:

    python tools/synthetic_pdfs.py [output_dir]

`tests/test_scenarios.py` imports the same functions directly so there is
exactly one definition of each fixture shared between the manual-demo use
case and the automated end-to-end test suite.

The bundled DejaVu font (tools/fonts/, Bitstream Vera license - see
DEJAVU_LICENSE.txt there) is used so Cyrillic text renders correctly
regardless of fonts installed on the machine generating these PDFs.
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import PageBreak, SimpleDocTemplate, Table, TableStyle

FONTS_DIR = Path(__file__).resolve().parent / "fonts"

_FONT_REGISTERED = False


def _ensure_font_registered() -> None:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    pdfmetrics.registerFont(TTFont("DejaVuSans", str(FONTS_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(FONTS_DIR / "DejaVuSans-Bold.ttf")))
    _FONT_REGISTERED = True


def _table_style(spans: list[tuple[tuple[int, int], tuple[int, int]]] | None = None) -> TableStyle:
    style = [
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
    ]
    for start, end in spans or []:
        style.append(("SPAN", start, end))
    return TableStyle(style)


def _table_pdf(
    out_path: Path,
    rows: list[list[str]],
    spans: list[tuple[tuple[int, int], tuple[int, int]]] | None = None,
    col_widths: list[float] | None = None,
) -> Path:
    _ensure_font_registered()
    doc = SimpleDocTemplate(str(out_path), pagesize=letter)
    t = Table(rows, colWidths=col_widths)
    t.setStyle(_table_style(spans))
    doc.build([t])
    return out_path


def _borderless_text_pdf(
    out_path: Path, rows: list[list[str]], col_xs: list[int] | None = None
) -> Path:
    _ensure_font_registered()
    c = canvas.Canvas(str(out_path), pagesize=letter)
    c.setFont("DejaVuSans", 11)
    xs = col_xs or [80, 200, 350, 450]
    y = 700
    for row in rows:
        for x, text in zip(xs, row, strict=False):
            c.drawString(x, y, text)
        y -= 30
    c.save()
    return out_path


def _rasterize_first_page(pdf_path: Path, dpi: int = 300) -> Image.Image:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    bitmap = doc[0].render(scale=dpi / 72.0)
    return bitmap.to_pil().convert("RGB")


def _image_to_pdf(image: Image.Image, out_path: Path) -> Path:
    width_pt, height_pt = letter
    c = canvas.Canvas(str(out_path), pagesize=letter)
    c.drawImage(ImageReader(image), 0, 0, width=width_pt, height=height_pt)
    c.save()
    return out_path


def _merge_pdfs(out_path: Path, *parts: Path) -> Path:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for part in parts:
        writer.append(PdfReader(str(part)))
    with open(out_path, "wb") as f:
        writer.write(f)
    return out_path


# ---------------------------------------------------------------------------
# 1. Direct extraction, bordered table, Russian text.
# ---------------------------------------------------------------------------
def scenario_01_text_table_russian(out_dir: Path) -> Path:
    return _table_pdf(
        out_dir / "01_text_table_russian.pdf",
        rows=[
            ["Наименование", "Количество", "Цена"],
            ["Болт М6х20", "150", "12.50"],
            ["Гайка М6", "150", "5.00"],
        ],
        col_widths=[220, 100, 100],
    )


# ---------------------------------------------------------------------------
# 2. Direct extraction, bordered table, English text.
# ---------------------------------------------------------------------------
def scenario_02_text_table_english(out_dir: Path) -> Path:
    return _table_pdf(
        out_dir / "02_text_table_english.pdf",
        rows=[
            ["Item", "Quantity", "Price"],
            ["Bolt M6x20", "150", "12.50"],
            ["Nut M6", "150", "5.00"],
        ],
        col_widths=[220, 100, 100],
    )


# ---------------------------------------------------------------------------
# 3. Direct extraction, mixed Russian + English text in the same table.
# ---------------------------------------------------------------------------
def scenario_03_mixed_language_table(out_dir: Path) -> Path:
    return _table_pdf(
        out_dir / "03_mixed_language_table.pdf",
        rows=[
            ["Code", "Наименование", "Currency", "Цена"],
            ["A-001", "Болт М6х20 ГОСТ 7798-70", "USD", "12.50"],
            ["A-002", "Nut M6 DIN 934", "USD", "5.00"],
        ],
        col_widths=[70, 220, 70, 80],
    )


# ---------------------------------------------------------------------------
# 4. Direct extraction, borderless table (pdfplumber whitespace/"text"
#    strategy, no OCR involved at all).
# ---------------------------------------------------------------------------
def scenario_04_borderless_table_direct(out_dir: Path) -> Path:
    return _borderless_text_pdf(
        out_dir / "04_borderless_table_direct.pdf",
        rows=[
            ["Код", "Наименование", "Кол-во", "Цена"],
            ["001", "Болт М6", "150", "12.50"],
            ["002", "Гайка М6", "150", "5.00"],
        ],
    )


# ---------------------------------------------------------------------------
# 5. Direct extraction, table with a merged header cell (column span).
# ---------------------------------------------------------------------------
def scenario_05_merged_header_table(out_dir: Path) -> Path:
    return _table_pdf(
        out_dir / "05_merged_header_table.pdf",
        rows=[
            ["Сведения о товаре", "", ""],
            ["Код", "Наименование", "Цена"],
            ["001", "Болт М6", "12.50"],
        ],
        spans=[((0, 0), (2, 0))],
        col_widths=[80, 220, 80],
    )


# ---------------------------------------------------------------------------
# 6. Direct extraction, multi-page document where the middle page is blank
#    (covers both multi-page handling and the blank-page-skip rule).
# ---------------------------------------------------------------------------
def scenario_06_multi_page_with_blank(out_dir: Path) -> Path:
    _ensure_font_registered()
    out_path = out_dir / "06_multi_page_with_blank.pdf"
    doc = SimpleDocTemplate(str(out_path), pagesize=letter)
    flowables = []
    for rows in (
        [["Наименование", "Количество"], ["Товар А", "1"]],
        None,  # blank page
        [["Наименование", "Количество"], ["Товар Б", "2"]],
    ):
        if rows is not None:
            t = Table(rows, colWidths=[220, 100])
            t.setStyle(_table_style())
            flowables.append(t)
        else:
            from reportlab.platypus import Spacer

            flowables.append(Spacer(1, 1))
        flowables.append(PageBreak())
    flowables.pop()  # drop the trailing page break so we get exactly 3 pages
    doc.build(flowables)
    return out_path


# ---------------------------------------------------------------------------
# 7. Direct extraction, a table plus free-form paragraph text outside it.
# ---------------------------------------------------------------------------
def scenario_07_table_with_paragraph_text(out_dir: Path) -> Path:
    _ensure_font_registered()
    out_path = out_dir / "07_table_with_paragraph_text.pdf"
    c = canvas.Canvas(str(out_path), pagesize=letter)
    c.setFont("DejaVuSans", 11)
    c.drawString(80, 730, "Сопроводительное письмо к накладной №42")
    c.drawString(80, 712, "Просим подтвердить получение товара в течение трёх дней.")
    c.save()

    table_pdf = _table_pdf(
        out_dir / "_07_table_part.pdf",
        rows=[["Наименование", "Количество"], ["Товар А", "1"], ["Товар Б", "2"]],
        col_widths=[220, 100],
    )
    return _combine_text_and_table(out_path, table_pdf)


def _combine_text_and_table(text_pdf: Path, table_pdf: Path) -> Path:
    """Overlay table_pdf's single page onto text_pdf's single page."""
    from pypdf import PdfReader, PdfWriter

    text_reader = PdfReader(str(text_pdf))
    table_reader = PdfReader(str(table_pdf))
    base_page = text_reader.pages[0]
    base_page.merge_translated_page(table_reader.pages[0], 0, -260)
    writer = PdfWriter()
    writer.add_page(base_page)
    with open(text_pdf, "wb") as f:
        writer.write(f)
    table_pdf.unlink(missing_ok=True)
    return text_pdf


# ---------------------------------------------------------------------------
# 8. OCR extraction, scanned bordered (ruled-grid) table, clean image.
# ---------------------------------------------------------------------------
def scenario_08_scanned_table_clean(out_dir: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        source = _table_pdf(
            Path(tmp) / "source.pdf",
            rows=[
                ["Наименование", "Количество"],
                ["Товар А", "10"],
                ["Товар Б", "20"],
            ],
            col_widths=[220, 100],
        )
        image = _rasterize_first_page(source, dpi=300)
        return _image_to_pdf(image, out_dir / "08_scanned_table_clean.pdf")


# ---------------------------------------------------------------------------
# 9. OCR extraction, scanned borderless table (word-clustering strategy).
# ---------------------------------------------------------------------------
def scenario_09_scanned_table_borderless(out_dir: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        source = _borderless_text_pdf(
            Path(tmp) / "source.pdf",
            rows=[
                ["Код", "Наименование", "Кол-во", "Цена"],
                ["001", "Болт М6", "150", "12.50"],
                ["002", "Гайка М6", "150", "5.00"],
            ],
        )
        image = _rasterize_first_page(source, dpi=300)
        return _image_to_pdf(image, out_dir / "09_scanned_table_borderless.pdf")


# ---------------------------------------------------------------------------
# 10. OCR extraction, scanned table - intended to be run with a strict
#     (high) confidence threshold setting so some cells are flagged
#     uncertain deterministically rather than depending on image noise.
# ---------------------------------------------------------------------------
def scenario_10_scanned_table_for_uncertain_highlighting(out_dir: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        source = _table_pdf(
            Path(tmp) / "source.pdf",
            rows=[
                ["Наименование", "Количество", "Цена"],
                ["Товар А", "150", "12.50"],
                ["Товар Б", "200", "7.00"],
            ],
            col_widths=[220, 100, 100],
        )
        image = _rasterize_first_page(source, dpi=300)
        return _image_to_pdf(
            image, out_dir / "10_scanned_table_for_uncertain_highlighting.pdf"
        )


# ---------------------------------------------------------------------------
# 11. OCR extraction, scanned table degraded with blur + noise (low-quality
#     scan robustness: must not crash, should still recover at least some
#     content).
# ---------------------------------------------------------------------------
def scenario_11_low_quality_noisy_scan(out_dir: Path) -> Path:
    import numpy as np

    with tempfile.TemporaryDirectory() as tmp:
        source = _table_pdf(
            Path(tmp) / "source.pdf",
            rows=[
                ["Наименование", "Количество"],
                ["Товар А", "10"],
                ["Товар Б", "20"],
            ],
            col_widths=[220, 100],
        )
        image = _rasterize_first_page(source, dpi=300)
        image = image.filter(ImageFilter.GaussianBlur(radius=1.6))
        arr = np.asarray(image).astype(np.int16)
        rng = np.random.default_rng(42)
        noise = rng.normal(0, 22, arr.shape).astype(np.int16)
        arr = np.clip(arr + noise, 0, 255).astype("uint8")
        image = Image.fromarray(arr, mode="RGB")
        return _image_to_pdf(image, out_dir / "11_low_quality_noisy_scan.pdf")


# ---------------------------------------------------------------------------
# 12. Rotation via the PDF's own /Rotate flag on an otherwise normal text
#     page (must route to OCR per the rotation rule, not direct extraction).
# ---------------------------------------------------------------------------
def scenario_12_rotated_text_page_rotate_flag(out_dir: Path) -> Path:
    from pypdf import PdfReader, PdfWriter

    with tempfile.TemporaryDirectory() as tmp:
        source = _table_pdf(
            Path(tmp) / "source.pdf",
            rows=[["Наименование", "Количество"], ["Товар А", "150"], ["Товар Б", "200"]],
            col_widths=[220, 100],
        )
        reader = PdfReader(str(source))
        writer = PdfWriter()
        page = reader.pages[0]
        page.rotate(90)
        writer.add_page(page)
        out_path = out_dir / "12_rotated_text_page_rotate_flag.pdf"
        with open(out_path, "wb") as f:
            writer.write(f)
        return out_path


# ---------------------------------------------------------------------------
# 13. Rotation baked into the scanned pixels with no /Rotate flag at all
#     (must be detected and corrected via Tesseract OSD).
# ---------------------------------------------------------------------------
def scenario_13_rotated_scanned_page_baked_in(out_dir: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        source = _table_pdf(
            Path(tmp) / "source.pdf",
            rows=[
                ["Наименование", "Количество", "Цена"],
                ["Товар А", "150", "12.50"],
                ["Товар Б", "200", "7.00"],
                ["Товар В", "300", "9.00"],
            ],
            col_widths=[220, 100, 100],
        )
        image = _rasterize_first_page(source, dpi=300)
        rotated = image.rotate(-90, expand=True)  # simulate a sideways-fed scan
        return _image_to_pdf(rotated, out_dir / "13_rotated_scanned_page_baked_in.pdf")


# ---------------------------------------------------------------------------
# 14. Mixed document: one normal text page followed by one scanned
#     (image-only) page - DocumentKind.MIXED.
# ---------------------------------------------------------------------------
def scenario_14_mixed_text_and_scanned_pages(out_dir: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        text_page = _table_pdf(
            Path(tmp) / "text_page.pdf",
            rows=[["Наименование", "Количество"], ["Товар А", "1"]],
            col_widths=[220, 100],
        )
        scan_source = _table_pdf(
            Path(tmp) / "scan_source.pdf",
            rows=[["Наименование", "Количество"], ["Товар Б", "2"]],
            col_widths=[220, 100],
        )
        image = _rasterize_first_page(scan_source, dpi=300)
        scanned_page = _image_to_pdf(image, Path(tmp) / "scanned_page.pdf")
        return _merge_pdfs(
            out_dir / "14_mixed_text_and_scanned_pages.pdf", text_page, scanned_page
        )


# ---------------------------------------------------------------------------
# 15. Error handling: a corrupt / not-a-PDF file.
# ---------------------------------------------------------------------------
def scenario_15_corrupt_pdf(out_dir: Path) -> Path:
    out_path = out_dir / "15_corrupt_pdf.pdf"
    out_path.write_bytes(b"this is not a valid PDF file at all")
    return out_path


# ---------------------------------------------------------------------------
# 16. Error handling: a password-protected (encrypted) PDF.
# ---------------------------------------------------------------------------
def scenario_16_encrypted_pdf(out_dir: Path) -> Path:
    from pypdf import PdfReader, PdfWriter

    with tempfile.TemporaryDirectory() as tmp:
        source = _table_pdf(
            Path(tmp) / "source.pdf",
            rows=[["Наименование", "Количество"], ["Товар А", "1"]],
            col_widths=[220, 100],
        )
        reader = PdfReader(str(source))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.encrypt(user_password="secret", owner_password=None)
        out_path = out_dir / "16_encrypted_pdf.pdf"
        with open(out_path, "wb") as f:
            writer.write(f)
        return out_path


SCENARIOS: list[tuple[str, Callable[[Path], Path]]] = [
    ("01_text_table_russian", scenario_01_text_table_russian),
    ("02_text_table_english", scenario_02_text_table_english),
    ("03_mixed_language_table", scenario_03_mixed_language_table),
    ("04_borderless_table_direct", scenario_04_borderless_table_direct),
    ("05_merged_header_table", scenario_05_merged_header_table),
    ("06_multi_page_with_blank", scenario_06_multi_page_with_blank),
    ("07_table_with_paragraph_text", scenario_07_table_with_paragraph_text),
    ("08_scanned_table_clean", scenario_08_scanned_table_clean),
    ("09_scanned_table_borderless", scenario_09_scanned_table_borderless),
    (
        "10_scanned_table_for_uncertain_highlighting",
        scenario_10_scanned_table_for_uncertain_highlighting,
    ),
    ("11_low_quality_noisy_scan", scenario_11_low_quality_noisy_scan),
    ("12_rotated_text_page_rotate_flag", scenario_12_rotated_text_page_rotate_flag),
    ("13_rotated_scanned_page_baked_in", scenario_13_rotated_scanned_page_baked_in),
    ("14_mixed_text_and_scanned_pages", scenario_14_mixed_text_and_scanned_pages),
    ("15_corrupt_pdf", scenario_15_corrupt_pdf),
    ("16_encrypted_pdf", scenario_16_encrypted_pdf),
]


def generate_all(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    return [fn(out_dir) for _, fn in SCENARIOS]


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tools") / "test_pdfs"
    paths = generate_all(out_dir)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
