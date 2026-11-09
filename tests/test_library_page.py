"""Library drop-down: every track opens, not just the first one (0.7.3 regression: an attribute named like the
Show-in-folder method overwrote it after the first open, so later clicks crashed)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.conftest import needs_ffmpeg


@needs_ffmpeg
def test_tracks_open_one_after_another(service, fixtures):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from app.ui.library_page import LibraryPage
    app = QApplication.instance() or QApplication([])
    for f in ("mp3_320", "flac", "aiff"):
        job = service.stage(fixtures[f]); service.analyze(job["id"]); service.promote(job["id"])
    page = LibraryPage(service); page.resize(1200, 800); page.show(); page.refresh(); app.processEvents()
    rows = [page.tree.topLevelItem(i) for i in range(page.tree.topLevelItemCount())]
    assert len(rows) == 3
    for _ in range(2):                                   # twice round, so a re-open is covered too
        for it in rows:
            page.tree.setCurrentItem(it); app.processEvents()
            assert page.panel is not None and callable(page._reveal)
            assert page.panel.isVisible()
    page.deleteLater(); app.sendPostedEvents(None, QEvent.DeferredDelete)
