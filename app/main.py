"""Entry point: python -m app.main"""
from __future__ import annotations

import sys


def _log_crashes(path) -> None:
    """Windowed builds have no console; anything uncaught goes to app.log in the data folder."""
    import traceback
    from datetime import datetime

    def hook(exc_type, exc, tb):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n---- {datetime.now().isoformat(timespec='seconds')} ----\n")
                f.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except OSError:
            pass
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = hook


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from .config import APP_NAME
    from .core.service import ArchiveService
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # One copy at a time: two copies would start two engines on the same account.
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QMessageBox
    from .config import data_dir
    data_dir().mkdir(parents=True, exist_ok=True)
    _log_crashes(data_dir() / "app.log")
    lock = QLockFile(str(data_dir() / "app.lock")); lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, f"{APP_NAME} is already running. Look for its window (or its icon in the taskbar).")
        return 0
    from .ui.theme import load_fonts
    load_fonts()
    win = MainWindow(ArchiveService())
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
