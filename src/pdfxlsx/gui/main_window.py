"""Main application window: file queue, settings, progress, log."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pdfxlsx.core.config import BatchJob, ConversionSettings, OcrLanguage
from pdfxlsx.core.models import DocumentResult
from pdfxlsx.core.pipeline import resolve_output_paths
from pdfxlsx.gui.widgets import FileDropListWidget
from pdfxlsx.gui.worker import ConversionWorker
from pdfxlsx.version import __version__

STATUS_PENDING = "ожидает"
STATUS_RUNNING = "обработка..."
STATUS_DONE = "готово"
STATUS_DONE_WITH_ISSUES = "готово (есть предупреждения)"
STATUS_FAILED = "ошибка"
STATUS_CANCELLED = "отменено"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"PdfXlsx — преобразование PDF в Excel {__version__}")
        self.resize(820, 640)

        self._worker: ConversionWorker | None = None
        self._items_by_path: dict[str, QListWidgetItem] = {}
        self._last_output_dir: Path | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addLayout(self._build_file_list_section())
        root.addWidget(self._build_settings_section())
        root.addLayout(self._build_progress_section())
        root.addWidget(self._build_log_section())
        root.addLayout(self._build_action_buttons())

    def _build_file_list_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Файлы для преобразования (можно перетащить сюда PDF-файлы):"))

        self.file_list = FileDropListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.files_dropped.connect(self._add_files)
        layout.addWidget(self.file_list)

        buttons = QHBoxLayout()
        add_btn = QPushButton("Добавить файлы…")
        add_btn.clicked.connect(self._browse_files)
        remove_btn = QPushButton("Удалить выбранные")
        remove_btn.clicked.connect(self._remove_selected)
        clear_btn = QPushButton("Очистить список")
        clear_btn.clicked.connect(self._clear_files)
        buttons.addWidget(add_btn)
        buttons.addWidget(remove_btn)
        buttons.addWidget(clear_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return layout

    def _build_settings_section(self) -> QGroupBox:
        box = QGroupBox("Параметры преобразования")
        form = QFormLayout(box)

        self.language_combo = QComboBox()
        for lang in OcrLanguage:
            self.language_combo.addItem(lang.label_ru, lang)
        self.language_combo.setCurrentIndex(
            list(OcrLanguage).index(OcrLanguage.RUSSIAN_ENGLISH)
        )
        form.addRow("Язык распознавания (OCR):", self.language_combo)

        self.highlight_checkbox = QCheckBox("Подсвечивать ячейки, требующие проверки")
        self.highlight_checkbox.setChecked(True)
        form.addRow(self.highlight_checkbox)

        self.confidence_spin = QSpinBox()
        self.confidence_spin.setRange(0, 100)
        self.confidence_spin.setValue(70)
        self.confidence_spin.setSuffix(" %")
        form.addRow("Порог уверенности OCR:", self.confidence_spin)

        self.sheet_per_page_checkbox = QCheckBox("Отдельный лист на каждую страницу")
        self.sheet_per_page_checkbox.setChecked(True)
        form.addRow(self.sheet_per_page_checkbox)

        self.sheet_per_table_checkbox = QCheckBox("Отдельный лист на каждую таблицу")
        form.addRow(self.sheet_per_table_checkbox)

        self.save_report_checkbox = QCheckBox("Сохранять отчёт о преобразовании (.txt)")
        self.save_report_checkbox.setChecked(True)
        form.addRow(self.save_report_checkbox)

        output_row = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("(по умолчанию — папка исходного PDF-файла)")
        output_browse_btn = QPushButton("Обзор…")
        output_browse_btn.clicked.connect(self._browse_output_dir)
        output_row.addWidget(self.output_dir_edit)
        output_row.addWidget(output_browse_btn)
        form.addRow("Папка сохранения результата:", output_row)

        return box

    def _build_progress_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        self.current_file_label = QLabel("Файлы не обрабатываются.")
        layout.addWidget(self.current_file_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        return layout

    def _build_log_section(self) -> QPlainTextEdit:
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Здесь будет отображаться ход преобразования…")
        return self.log_view

    def _build_action_buttons(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self.start_button = QPushButton("Начать преобразование")
        self.start_button.clicked.connect(self._start_conversion)
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_conversion)
        self.open_folder_button = QPushButton("Открыть папку с результатом")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        layout.addWidget(self.start_button)
        layout.addWidget(self.cancel_button)
        layout.addStretch(1)
        layout.addWidget(self.open_folder_button)
        return layout

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{timestamp}] {message}")

    def _browse_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Выберите PDF-файлы", "", "PDF-файлы (*.pdf)")
        if paths:
            self._add_files(paths)

    def _browse_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Выберите папку для сохранения результата")
        if directory:
            self.output_dir_edit.setText(directory)

    def _add_files(self, paths: list[str]) -> None:
        for path in paths:
            if path in self._items_by_path:
                continue
            item = QListWidgetItem(self._item_text(path, STATUS_PENDING))
            self.file_list.addItem(item)
            self._items_by_path[path] = item

    def _remove_selected(self) -> None:
        for item in self.file_list.selectedItems():
            path = next((p for p, i in self._items_by_path.items() if i is item), None)
            if path is not None:
                del self._items_by_path[path]
            self.file_list.takeItem(self.file_list.row(item))

    def _clear_files(self) -> None:
        self.file_list.clear()
        self._items_by_path.clear()

    @staticmethod
    def _item_text(path: str, status: str) -> str:
        return f"{Path(path).name} — {status}"

    def _set_item_status(self, path: str, status: str) -> None:
        item = self._items_by_path.get(path)
        if item is not None:
            item.setText(self._item_text(path, status))

    def _current_settings(self) -> ConversionSettings:
        output_dir = self.output_dir_edit.text().strip() or None
        return ConversionSettings(
            ocr_language=self.language_combo.currentData(),
            highlight_uncertain_cells=self.highlight_checkbox.isChecked(),
            ocr_confidence_threshold=self.confidence_spin.value(),
            sheet_per_page=self.sheet_per_page_checkbox.isChecked(),
            sheet_per_table=self.sheet_per_table_checkbox.isChecked(),
            save_report=self.save_report_checkbox.isChecked(),
            output_dir=output_dir,
        )

    def _start_conversion(self) -> None:
        if not self._items_by_path:
            QMessageBox.information(self, "Нет файлов", "Добавьте хотя бы один PDF-файл для преобразования.")
            return
        settings = self._current_settings()
        jobs = [BatchJob(pdf_path=path, settings=settings) for path in self._items_by_path]

        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self._log(f"Запуск преобразования {len(jobs)} файл(ов)…")

        self._worker = ConversionWorker(jobs)
        self._worker.file_started.connect(self._on_file_started)
        self._worker.page_progress.connect(self._on_page_progress)
        self._worker.file_finished.connect(self._on_file_finished)
        self._worker.file_failed.connect(self._on_file_failed)
        self._worker.batch_finished.connect(self._on_batch_finished)
        self._worker.start()

    def _cancel_conversion(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._log("Отмена запрошена. Завершается обработка текущей страницы…")
            self.cancel_button.setEnabled(False)

    def _on_file_started(self, path: str) -> None:
        self._set_item_status(path, STATUS_RUNNING)
        self.current_file_label.setText(f"Обработка: {Path(path).name}")
        self._log(f"Обработка файла: {Path(path).name}")

    def _on_page_progress(self, path: str, done: int, total: int) -> None:
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(done)

    def _on_file_finished(self, path: str, result: DocumentResult) -> None:
        uncertain = sum(1 for t in result.tables for c in t.cells if c.is_uncertain)
        if result.cancelled:
            self._set_item_status(path, STATUS_CANCELLED)
            self._log(f"Отменено: {Path(path).name}")
        elif uncertain:
            self._set_item_status(path, STATUS_DONE_WITH_ISSUES)
            self._log(
                f"Готово: {Path(path).name} (страниц: {result.page_count}, "
                f"ячеек на проверку: {uncertain})"
            )
        else:
            self._set_item_status(path, STATUS_DONE)
            self._log(f"Готово: {Path(path).name} (страниц: {result.page_count})")
        xlsx_path, _ = resolve_output_paths(path, self._current_settings())
        self._last_output_dir = xlsx_path.parent
        self.open_folder_button.setEnabled(True)

    def _on_file_failed(self, path: str, message: str) -> None:
        self._set_item_status(path, STATUS_FAILED)
        self._log(f"ОШИБКА при обработке {Path(path).name}: {message}")

    def _on_batch_finished(self) -> None:
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.current_file_label.setText("Преобразование завершено.")
        self._log("Преобразование завершено.")
        self._worker = None

    def _open_output_folder(self) -> None:
        if self._last_output_dir is not None and self._last_output_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_output_dir)))
