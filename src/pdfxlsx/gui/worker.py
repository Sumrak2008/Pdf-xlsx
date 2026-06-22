"""Background thread that runs conversions so the UI thread never blocks.

One `ConversionWorker` processes a whole queued batch (sequentially - the
pipeline itself is single-threaded CPU/IO-bound work, so running several
files at once would only contend for the same CPU cores with no benefit).
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from pdfxlsx.core.config import BatchJob
from pdfxlsx.core.errors import PdfXlsxError
from pdfxlsx.core.models import DocumentResult
from pdfxlsx.core.pipeline import run_conversion


class ConversionWorker(QThread):
    file_started = Signal(str)
    page_progress = Signal(str, int, int)
    file_finished = Signal(str, DocumentResult)
    file_failed = Signal(str, str)
    batch_finished = Signal()

    def __init__(self, jobs: list[BatchJob], parent=None) -> None:
        super().__init__(parent)
        self._jobs = jobs
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        for job in self._jobs:
            if self._cancelled:
                break
            self.file_started.emit(job.pdf_path)
            try:
                result = run_conversion(
                    job.pdf_path,
                    job.settings,
                    cancel_check=lambda: self._cancelled,
                    progress_callback=lambda done, total, path=job.pdf_path: self.page_progress.emit(
                        path, done, total
                    ),
                )
                self.file_finished.emit(job.pdf_path, result)
            except PdfXlsxError as exc:
                self.file_failed.emit(job.pdf_path, exc.user_message)
            except Exception as exc:
                self.file_failed.emit(job.pdf_path, f"Непредвиденная ошибка: {exc}")
        self.batch_finished.emit()
