"""Clicking a record in Discover searches inside Discover; Back returns to the same spot."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_find_stays_in_discover_and_back_returns(service):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from app.ui.discover_page import DiscoverPage
    app = QApplication.instance() or QApplication([])
    d = DiscoverPage(service); d.resize(1200, 800); d.show(); app.processEvents()
    asked = []
    d.find.connect(asked.append)
    d.q.setText("Phuture Acid Tracks"); d._search_typed()
    assert asked == ["Phuture Acid Tracks"]
    d.home_view.verticalScrollBar().setValue(300)
    where = d.home_view.verticalScrollBar().value()
    d.show_find("Phuture Acid Tracks"); app.processEvents()
    assert d.stack.currentWidget() is d.find_view and d.finder is not None
    d.back(); app.processEvents()
    assert d.stack.currentWidget() is d.home_view and d.home_view.verticalScrollBar().value() == where
    d.deleteLater(); app.sendPostedEvents(None, QEvent.DeferredDelete)
