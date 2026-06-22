"""Exceptions with ready-to-display Russian messages.

Every exception that can reach the GUI carries a `user_message` that is
already in Russian and safe to show in a dialog or the log panel, so the
GUI layer never has to translate or interpret exception types itself.
"""

from __future__ import annotations


class PdfXlsxError(Exception):
    """Base class for all errors with a Russian user-facing message."""

    def __init__(self, user_message: str, *, technical_detail: str | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_detail = technical_detail


class CorruptPdfError(PdfXlsxError):
    """Raised when a PDF cannot be opened or parsed at all."""

    def __init__(self, file_name: str, technical_detail: str | None = None) -> None:
        super().__init__(
            f"Файл «{file_name}» повреждён или не является PDF-документом и не может быть открыт.",
            technical_detail=technical_detail,
        )


class EncryptedPdfError(PdfXlsxError):
    """Raised when a PDF is password-protected and cannot be read."""

    def __init__(self, file_name: str) -> None:
        super().__init__(
            f"Файл «{file_name}» защищён паролем. Снимите защиту и попробуйте снова."
        )


class OutputNotWritableError(PdfXlsxError):
    """Raised when the chosen output folder cannot be written to."""

    def __init__(self, folder: str, technical_detail: str | None = None) -> None:
        super().__init__(
            f"Нет доступа на запись в папку «{folder}». Выберите другую папку сохранения.",
            technical_detail=technical_detail,
        )


class InsufficientDiskSpaceError(PdfXlsxError):
    """Raised when free disk space is too low to safely process a file."""

    def __init__(self, folder: str, required_mb: float, available_mb: float) -> None:
        super().__init__(
            "Недостаточно свободного места на диске для обработки файла. "
            f"Требуется примерно {required_mb:.0f} МБ, доступно {available_mb:.0f} МБ "
            f"в «{folder}»."
        )


class OcrEngineUnavailableError(PdfXlsxError):
    """Raised when the bundled OCR engine cannot be located or started."""

    def __init__(self, technical_detail: str | None = None) -> None:
        super().__init__(
            "Не удалось запустить модуль распознавания текста (OCR). "
            "Переустановите программу из исходного ZIP-архива, не удаляя папку tools.",
            technical_detail=technical_detail,
        )


class ConversionCancelledError(PdfXlsxError):
    """Raised internally to unwind processing when the user cancels."""

    def __init__(self) -> None:
        super().__init__("Преобразование отменено пользователем.")
