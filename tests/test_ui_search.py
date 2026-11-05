"""The whole search path through the real window: press Search, rows must appear."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_soulseek import API_KEY, connected, slskd  # noqa: F401  (fixtures)


@pytest.fixture
def window(connected):
    from PySide6.QtWidgets import QApplication
    from app.ui import theme as T
    from app.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    s = connected.settings; s.setup_done = True; s.tour_done = True; connected.save_settings(s)
    connected.accounts.sign_up("T", "t@example.com", "correct-horse-battery")
    w = MainWindow(connected); w.resize(1200, 800); w.show()
    yield w, app
    w.close()


def spin(app, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.02)


def test_pressing_search_shows_rows(window):
    w, app = window
    spin(app, 0.5)
    w._search("artist")
    for _ in range(150):
        spin(app, 0.1)
        foot = w.searchp._foot_item
        if w.searchp.tree.topLevelItemCount() > 0 and foot is not None and "All results shown" in foot.text(1):
            break
    assert w.searchp.tree.topLevelItemCount() > 0, (w.searchp.title.text(), w.searchp.empty.text(), w.statusBar().currentMessage())
    assert "result" in w.searchp.title.text()
    assert w.searchp._foot_item is not None and "All results shown" in w.searchp._foot_item.text(1)
    assert not w.searchp.empty.isVisible()
