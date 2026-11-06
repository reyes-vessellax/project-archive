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


def test_zero_results_retries_without_the_shaky_word(window, slskd):
    w, app = window
    spin(app, 0.3)
    w._search("artist trak")                                   # "trak" matches nothing; "artist" does
    for _ in range(200):
        spin(app, 0.1)
        foot = w.searchp._foot_item
        if w.searchp.tree.topLevelItemCount() > 0 and foot is not None and "All results shown" in foot.text(1):
            break
    assert w.searchp.tree.topLevelItemCount() > 0
    assert "without “trak”" in w.searchp.state.text(), w.searchp.state.text()


def test_ripe_stops_on_plateau_but_waits_for_rare_queries():
    from app.ui.main_window import MainWindow, SEARCH_MIN_S, SEARCH_QUIET_S
    ripe = MainWindow._ripe
    # popular: 100 files by 2 s, then flat -> stop once quiet for SEARCH_QUIET_S after SEARCH_MIN_S
    h = [(0.5, 20), (1.0, 60), (2.0, 100), (3.0, 100), (4.0, 100)]
    assert not ripe(h, 4.0, 40)                                   # quiet only 2 s so far
    h.append((5.5, 100))
    assert ripe(h, 5.5, 40)                                       # 100 at 2.0, still 100 at 5.5 -> quiet >= 3 s
    # still growing: keep going
    g = [(1, 50), (3, 120), (5, 200), (7, 260)]
    assert not ripe(g, 7, 40)
    # big and only trickling (<3 % over the quiet window): stop
    big = [(1, 500), (4, 900), (7, 1000), (10, 1010)]
    assert ripe(big, 10, 40)
    # rare: nothing yet -> wait for the far corners, right up to the deadline
    r = [(1, 0), (5, 0), (9, 0), (20, 0)]
    assert not ripe(r, 20, 40)
    assert ripe(r + [(40, 0)], 40, 40)
