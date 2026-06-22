"""Per-document `<имя>_conversion_report.txt` generation.

Deliberately never includes the recognized text/values themselves - only
counts, flags, and short diagnostic messages - so the report cannot become
a second, uncontrolled copy of the document's actual content.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pdfxlsx.core.config import ConversionSettings
from pdfxlsx.core.models import DocumentResult

_METHOD_LABELS = {
    "direct": "прямое извлечение текста",
    "ocr": "распознавание (OCR)",
    "blank": "пустая страница",
    "failed": "ошибка обработки",
}


def _format_duration(seconds: float) -> str:
    minutes, secs = divmod(int(round(seconds)), 60)
    if minutes:
        return f"{minutes} мин {secs} с"
    return f"{secs} с"


def _count_uncertain_cells(result: DocumentResult) -> int:
    return sum(1 for table in result.tables for cell in table.cells if cell.is_uncertain)


def build_report_text(result: DocumentResult, settings: ConversionSettings) -> str:
    lines: list[str] = []
    source_name = Path(result.source_pdf).name
    lines.append(f"Отчёт о преобразовании: {source_name}")
    lines.append(f"Дата формирования отчёта: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Длительность обработки: {_format_duration(result.duration_seconds)}")
    lines.append("")

    by_method: dict[str, int] = {}
    for page in result.pages:
        by_method[page.extraction_method] = by_method.get(page.extraction_method, 0) + 1
    succeeded = sum(c for m, c in by_method.items() if m != "failed")

    lines.append("Страницы:")
    lines.append(f"  Всего страниц: {result.page_count}")
    lines.append(f"  Обработано успешно: {succeeded}")
    for method in ("direct", "ocr", "blank", "failed"):
        if by_method.get(method):
            lines.append(f"  {_METHOD_LABELS[method].capitalize()}: {by_method[method]}")
    rotated_pages = [p for p in result.pages if p.rotation_degrees]
    if rotated_pages:
        lines.append(f"  Страниц с обнаруженным и скорректированным поворотом: {len(rotated_pages)}")
    lines.append("")

    lines.append("Таблицы:")
    lines.append(f"  Всего найдено таблиц: {len(result.tables)}")
    by_strategy: dict[str, int] = {}
    for table in result.tables:
        by_strategy[table.source] = by_strategy.get(table.source, 0) + 1
    for strategy, count in sorted(by_strategy.items()):
        lines.append(f"  Стратегия «{strategy}»: {count}")
    lines.append("")

    uncertain_count = _count_uncertain_cells(result)
    lines.append("Качество распознавания:")
    lines.append(f"  Ячеек, требующих проверки: {uncertain_count}")
    if not settings.highlight_uncertain_cells:
        lines.append("  (подсветка неопределённых ячеек была отключена в настройках)")
    lines.append("")

    warnings = [(p.page_index, w) for p in result.pages for w in p.warnings]
    page_errors = [(p.page_index, p.error) for p in result.pages if p.error]
    if warnings or page_errors or result.errors:
        lines.append("Предупреждения и ошибки:")
        for page_index, error in page_errors:
            lines.append(f"  Страница {page_index + 1}: ОШИБКА: {error}")
        for page_index, warning in warnings:
            lines.append(f"  Страница {page_index + 1}: {warning}")
        for error in result.errors:
            lines.append(f"  {error}")
        lines.append("")

    if result.cancelled:
        lines.append("ВНИМАНИЕ: преобразование было отменено пользователем до завершения.")
        lines.append("")

    lines.append("Использованные локальные механизмы обработки:")
    if by_method.get("direct"):
        lines.append("  - Прямое извлечение текста и таблиц из структуры PDF (pdfplumber)")
    if by_method.get("ocr"):
        lines.append(f"  - Оптическое распознавание символов: Tesseract OCR, язык: {settings.ocr_language.label_ru}")
    lines.append("  - Вся обработка выполнена локально, без обращения к сети Интернет")
    lines.append("")

    lines.append("Известные ограничения:")
    lines.append("  Подробное описание см. в файле KNOWN_LIMITATIONS.md, поставляемом с программой.")
    if by_method.get("ocr"):
        lines.append("  На одной отсканированной странице восстанавливается не более одной основной таблицы.")
    lines.append("")

    lines.append("Примечание: данный отчёт не содержит распознанного текста или значений ячеек документа.")
    return "\n".join(lines) + "\n"


def write_report(result: DocumentResult, settings: ConversionSettings, output_path: str) -> None:
    Path(output_path).write_text(build_report_text(result, settings), encoding="utf-8")
