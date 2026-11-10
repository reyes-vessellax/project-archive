"""Entry point: python -m app.main"""
from __future__ import annotations

import os
import sys


LOG_MAX_BYTES = 5_000_000


def rotate_log(path, max_bytes: int = LOG_MAX_BYTES) -> None:
    """At start-up (only the running copy, after the lock): a log over max_bytes becomes app.log.1, replacing the
    one before, so the log never grows without end. Reports send the tail of the current one."""
    from pathlib import Path
    p = Path(path)
    try:
        if p.stat().st_size > max_bytes:
            p.replace(p.with_name(p.name + ".1"))
    except OSError:
        pass


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


class _WindowLog:
    """Writes one line to app.log whenever a top-level window is shown. Cheap, and it names stray popups."""

    def __init__(self, app, path):
        from PySide6.QtCore import QEvent, QObject
        self.path = path
        outer = self

        class F(QObject):
            def eventFilter(self, obj, ev):
                if ev.type() == QEvent.Show and hasattr(obj, "isWindow") and obj.isWindow() \
                        and obj.objectName() != "qtooltip_label":
                    outer.note(obj)
                return False
        self.f = F(app)
        app.installEventFilter(self.f)

    def note(self, w):
        try:
            from datetime import datetime
            import traceback
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat(timespec='seconds')} window shown: {type(w).__name__} "
                        f"name={w.objectName()!r} title={w.windowTitle()!r} flags={int(w.windowFlags()):#x} "
                        f"size={w.width()}x{w.height()}\n")
                if type(w).__name__ not in ("MainWindow", "AvatarMenu", "QMessageBox", "QFileDialog"):
                    f.write("".join(traceback.format_stack(limit=12)))
        except Exception:
            pass


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from .config import APP_NAME
    from .core.service import ArchiveService
    from .ui.main_window import MainWindow

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_NAME}.desktop")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # One copy at a time: two copies would start two engines on the same account.
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QMessageBox
    from .config import data_dir
    data_dir().mkdir(parents=True, exist_ok=True)
    _log_crashes(data_dir() / "app.log")
    try:                                                    # a fresh update started fine: drop the old copy
        from .core.updater import finish_pending
        finish_pending()
    except Exception:
        pass
    lock = QLockFile(str(data_dir() / "app.lock")); lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, f"{APP_NAME} is already running. Look for its window (or its icon in the taskbar).")
        return 0
    rotate_log(data_dir() / "app.log")
    from .ui.theme import load_fonts
    load_fonts()
    if os.environ.get("DIGMART_LOG_WINDOWS"):              # debugging only: it sees every event the app handles
        global _wlog                                       # (tests/test_no_stray_windows.py guards stray popups)
        _wlog = _WindowLog(app, data_dir() / "app.log")
    from .ui.brand import app_icon
    app.setWindowIcon(app_icon())
    win = MainWindow(ArchiveService())
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
