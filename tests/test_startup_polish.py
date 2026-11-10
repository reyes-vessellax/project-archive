"""Start-up waits for Discover's rows; checked queue rows show the name, not 'CLUB ✓ 1411 kbps'."""
from PySide6.QtWidgets import QApplication


def _app():
    return QApplication.instance() or QApplication([])


def test_checked_queue_row_has_no_club_or_bitrate_text_and_keeps_its_title():
    from app.core import jobs as J
    from app.ui.pages import row_data
    from app.ui.widgets import QueueRow
    app = _app()
    job = {"id": "j1", "state": J.READY, "original_name": "Adrien Calvet - Your Mind.aiff", "remote_user": "u"}
    analysis = {"overall_status": "PASS", "facts": {"bitrate_bps": 1411000}, "club": {"ready": True}}
    d = row_data(job, analysis, {})
    assert d["meta"] == "" and "Your Mind" in d["title"]
    row = QueueRow("j1", **d); row.resize(300, 48); row.show(); app.processEvents()
    assert not row.meta.isVisible() and row.title.width() >= 90          # narrow window: the name is still there
    row.update_to(**{**d, "tag": "Down", "meta": "42%", "pct": 42}); app.processEvents()
    assert row.meta.isVisible() and row.meta.text() == "42%"             # other states still say what's happening
    row.close(); row.deleteLater(); app.processEvents()


def test_discover_reports_how_many_rows_are_ready():
    from app.ui.discover_page import DiscoverPage
    page = DiscoverPage.__new__(DiscoverPage)                            # only the bookkeeping, no widgets
    page.rows = {"For you": 1, "Chicago": 2, "Deep house": 3}
    page._loading = {"For you", "Chicago", "Deep house"}; page._row_tracks = {}; page._offline_rows = []
    assert page.warm() == (0, 3)
    page._row_tracks["Chicago"] = ["t"]                                  # first tracks landed, more still coming
    assert page.warm() == (1, 3)
    page._loading = {"For you"}                                          # Deep house finished with nothing
    assert page.warm() == (2, 3)
    page._offline_rows = ["For you"]                                     # not signed in yet: nothing counts
    assert page.warm() == (0, 3)
    assert "discover" in dict(__import__("app.ui.onboarding", fromlist=["ConnectingPage"]).ConnectingPage.STEPS)
