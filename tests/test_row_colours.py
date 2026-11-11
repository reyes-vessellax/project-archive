"""Reyes (light mode Queue): "the colors are off. Stuff's blending in." Rows read dark on light; hovered and
selected rows are the dark red with white words, in both themes."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _fg(w):
    return w.palette().color(w.foregroundRole()).name()


def test_queue_row_words_follow_the_highlight_in_both_themes():
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QEnterEvent
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    app = QApplication.instance() or QApplication([])
    from app.ui import theme as T
    from app.ui.widgets import QueueRow
    old = app.styleSheet()
    try:
        for theme in ("light", "dark"):
            c = T.colours(theme)
            app.setStyleSheet(T.stylesheet(theme))
            host = QWidget(); QVBoxLayout(host).addWidget(r := QueueRow("j", "Look", "Title", "Artist", None, "m", True))
            host.show(); app.processEvents()
            assert _fg(r.title) == c["text"].lower(), theme             # plain row: normal text, never white-on-light
            r.enterEvent(QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5))); app.processEvents()
            assert _fg(r.title) == _fg(r.artist) == "#ffffff", theme     # hover: white words on the red
            r.leaveEvent(QEvent(QEvent.Leave)); app.processEvents()
            assert _fg(r.title) == c["text"].lower(), theme
            r.set_selected(True); app.processEvents()
            assert _fg(r.title) == _fg(r.artist) == _fg(r.tag) == "#ffffff", theme
            r.set_selected(False); app.processEvents()
            assert _fg(r.artist) == c["muted"].lower(), theme
            host.close()
    finally:
        app.setStyleSheet(old)
