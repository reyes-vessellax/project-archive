"""No widget may ever be shown as its own top-level window except the ones we mean (main window, avatar
menu, dialogs). Drives the real window through the flows that used to flash: queue rows appearing and
changing state, search results, the review rail, the library drop-down."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_soulseek import connected, slskd  # noqa: F401
from tests.test_workflow import needs_ffmpeg

ALLOWED = {"MainWindow", "AvatarMenu", "QMessageBox", "QFileDialog", "TourOverlay"}


@needs_ffmpeg
def test_nothing_strays_to_top_level(connected, fixtures):
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    strays = []

    class Watch(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Show and hasattr(obj, "isWindow") and obj.isWindow() \
                    and type(obj).__name__ not in ALLOWED and obj.objectName() != "qtooltip_label":
                strays.append(f"{type(obj).__name__} name={obj.objectName()!r} size={obj.width()}x{obj.height()}")
            return False
    watch = Watch(); app.installEventFilter(watch)
    s = connected.settings; s.setup_done = True; s.tour_done = True; connected.save_settings(s)
    connected.accounts.sign_up("T", "t@example.com", "correct-horse-battery")
    w = MainWindow(connected); w.resize(1200, 800); w.show()

    def spin(sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            app.processEvents(); time.sleep(0.01)
    spin(0.3)
    # queue rows in every state: queued-looking (progress bar), checked (×), promoted
    a = connected.stage(fixtures["mp3_320"]); w.refresh(); spin(0.1)
    connected.analyze(a["id"]); w.refresh(); spin(0.1)
    connected.promote(a["id"], override_warning=True); w.refresh(); spin(0.1)
    b = connected.stage(fixtures["mp3_192"]); connected.analyze(b["id"]); w.refresh(); spin(0.1)
    w._tab("ready"); spin(0.1)
    w._tab("library"); spin(0.1)
    it = w.library.tree.topLevelItem(0)
    if it:
        it.setSelected(True); spin(0.1)
    w._search("artist"); spin(2.0)
    w._tab("queue"); spin(0.1)
    w._menu(); spin(0.1)
    app.removeEventFilter(watch)
    w.close()
    assert strays == [], strays
