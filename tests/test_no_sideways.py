"""Nothing scrolls left and right: long titles, tiles and wide content wrap or squeeze instead."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_scroll_pages_never_go_sideways():
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget
    from app.ui.widgets import scroll
    app = _app()
    inner = QWidget(); lay = QHBoxLayout(inner)
    for _ in range(6):                                   # a row of tiles wider than the page
        t = QLabel("4:05 44.1 kHz FLAC"); t.setMinimumWidth(300); lay.addWidget(t)
    lay.addWidget(QLabel("A Very Long Track Title (Extended Club Mix Featuring Somebody Remastered 2024)" * 2))
    s = scroll(inner); s.resize(900, 500); s.show(); app.processEvents()
    assert s.horizontalScrollBar().maximum() == 0
    assert inner.width() <= s.viewport().width()
    s.close(); s.deleteLater(); app.processEvents()


def test_dig_the_crate_title_wraps(service):
    from app.ui.discover_page import SpinBar
    app = _app()
    bar = SpinBar()
    for lb in (bar.where, bar.title, bar.sub):
        lb.setText("Extremely Long Words In Every Line " * 10)
    bar.resize(900, 200); bar.show(); app.processEvents()
    assert bar.minimumSizeHint().width() < 800           # ~500 on macOS; Windows fonts run up to ~40% wider
    bar.close(); bar.deleteLater(); app.processEvents()


def test_search_table_never_goes_sideways(service):
    from app.adapters.base import Candidate, SearchResult
    from app.ui.pages import SearchPage
    app = _app()
    page = SearchPage(service); page.resize(1000, 700); page.show(); app.processEvents()
    long = "Somebody - A Very Long Track Title (Extended Club Mix) [Remastered Anniversary Edition 2024]"
    cands = [Candidate("soulseek", f"user{i}", f"@@x\\\\Some Very Long Folder Name Deep House Classics 1988-1996\\\\{long}.flac",
                       60_000_000, display_name=f"{long}.flac", artist="Somebody", title=long, extension="flac",
                       free_slot=True) for i in range(5)]
    page.show_results(SearchResult("q", "q", True, cands), searching=False); app.processEvents()
    assert page.tree.horizontalScrollBar().maximum() == 0
    page.close(); page.deleteLater(); app.processEvents()


def test_account_menu_stays_on_screen_from_the_bottom_left():
    """The avatar moved to the bottom-left of the sidebar; its menu opened below and to the left, off screen."""
    from PySide6.QtWidgets import QPushButton, QWidget
    from app.ui.widgets import AvatarMenu, menu_pos
    app = _app()
    win = QWidget(); win.resize(1200, 800); win.show(); app.processEvents()
    area = win.screen().availableGeometry()
    win.move(area.left(), area.bottom() - 800)
    avatar = QPushButton("R", win); avatar.setGeometry(10, 760, 32, 32); avatar.show(); app.processEvents()
    menu = AvatarMenu(win) if AvatarMenu.__init__.__code__.co_argcount > 1 else AvatarMenu()
    p = menu_pos(menu, avatar)
    assert area.left() <= p.x() and p.x() + menu.width() <= area.right() + 1
    assert area.top() <= p.y() and p.y() + menu.height() <= area.bottom() + 1
    menu.close(); menu.deleteLater(); win.close(); win.deleteLater(); app.processEvents()
