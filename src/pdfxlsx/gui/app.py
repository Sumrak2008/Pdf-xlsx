"""GUI entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from pdfxlsx.core.tempfiles import cleanup_stale_temp_dirs
from pdfxlsx.gui.main_window import MainWindow


def main() -> int:
    cleanup_stale_temp_dirs()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
