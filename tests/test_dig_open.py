"""Today's dig: tapping a cover opens its card in place; tap again closes; tap another switches (one card, never two)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_dig_cover_opens_in_place_closes_and_switches(service):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from app.adapters.base import Candidate
    from app.core.discover import Release
    from app.core.discover_avail import Found
    from app.ui.discover_page import DiscoverPage
    app = QApplication.instance() or QApplication([])
    d = DiscoverPage(service); d.resize(1300, 900); d.show(); app.processEvents()
    d._dig_token = tok = next(d._tokens)
    fs = []
    for i in range(8):
        c = Candidate("soulseek", f"u{i}", "p", 1, extension="flac", free_slot=True)
        f = Found(Release(500 + i, f"Record {i}", f"Artist {i}", 1994), {}, "Relief Records", f"Record {i}", c, [c])
        fs.append(f); d._dig_found_one(tok, f)
    app.processEvents()

    def drawers():
        return [w for w in d.findChildren(type(d.dig_card)) if w.isVisible() and w is not d.spin_card]

    d._open_dig(fs[1]); app.processEvents()
    cover = d._dig_cards[501]
    assert len(drawers()) == 1 and d.dig_card.found is fs[1]
    assert d.dig_card.geometry().top() > cover.geometry().bottom()             # right under the tapped row
    d._open_dig(fs[6]); app.processEvents()
    assert len(drawers()) == 1 and d.dig_card.found is fs[6]                   # another: switches, still one card
    d._open_dig(fs[6]); app.processEvents()
    assert drawers() == [] and d._dig_open is None                             # same one again: closes
    d.deleteLater(); app.sendPostedEvents(None, QEvent.DeferredDelete)
