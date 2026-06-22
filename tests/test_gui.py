from __future__ import annotations

import pytest

from pdfxlsx.core.config import OcrLanguage

pytestmark = pytest.mark.gui


def test_add_and_remove_files(qapp, make_table_pdf):
    from pdfxlsx.gui.main_window import MainWindow

    pdf_path = make_table_pdf([["A", "B"], ["1", "2"]])
    window = MainWindow()
    window._add_files([str(pdf_path)])
    assert str(pdf_path) in window._items_by_path
    assert window.file_list.count() == 1

    window.file_list.item(0).setSelected(True)
    window._remove_selected()
    assert window.file_list.count() == 0
    assert str(pdf_path) not in window._items_by_path


def test_add_files_deduplicates(qapp, make_table_pdf):
    from pdfxlsx.gui.main_window import MainWindow

    pdf_path = make_table_pdf([["A", "B"], ["1", "2"]])
    window = MainWindow()
    window._add_files([str(pdf_path)])
    window._add_files([str(pdf_path)])
    assert window.file_list.count() == 1


def test_current_settings_reflects_ui_controls(qapp):
    from pdfxlsx.gui.main_window import MainWindow

    window = MainWindow()
    window.highlight_checkbox.setChecked(False)
    window.confidence_spin.setValue(55)
    window.sheet_per_table_checkbox.setChecked(True)
    window.save_report_checkbox.setChecked(False)
    window.language_combo.setCurrentIndex(list(OcrLanguage).index(OcrLanguage.ENGLISH))

    settings = window._current_settings()
    assert settings.highlight_uncertain_cells is False
    assert settings.ocr_confidence_threshold == 55
    assert settings.sheet_per_table is True
    assert settings.save_report is False
    assert settings.ocr_language == OcrLanguage.ENGLISH


def test_start_conversion_runs_worker_and_reports_completion(qapp, make_table_pdf, tmp_path, qtbot_sleep):
    from pdfxlsx.gui.main_window import MainWindow

    pdf_path = make_table_pdf([["Наименование", "Количество"], ["Товар А", "1"]], path=tmp_path / "doc.pdf")
    window = MainWindow()
    window._add_files([str(pdf_path)])
    window._start_conversion()

    assert window._worker is not None
    qtbot_sleep(window._worker)

    assert window.start_button.isEnabled() is True
    assert window.cancel_button.isEnabled() is False
    assert window.open_folder_button.isEnabled() is True
    log_text = window.log_view.toPlainText()
    assert "Готово" in log_text
    assert "Преобразование завершено" in log_text


def test_start_conversion_with_no_files_shows_message(qapp, monkeypatch):
    from pdfxlsx.gui import main_window as mw

    pdf_path_module_calls = []
    monkeypatch.setattr(
        mw.QMessageBox, "information", staticmethod(lambda *a, **k: pdf_path_module_calls.append(a))
    )
    window = mw.MainWindow()
    window._start_conversion()
    assert len(pdf_path_module_calls) == 1
    assert window._worker is None
