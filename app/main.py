"""Entry point: python -m app.main"""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from .config import APP_NAME
    from .core.service import ArchiveService
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    from .ui.theme import load_fonts
    load_fonts()
    win = MainWindow(ArchiveService())
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
