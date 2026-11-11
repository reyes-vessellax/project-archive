"""Reyes: "a music thing by the song that's playing whenever I click into another song". ♫ follows the player."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_queue_row_shows_the_note_only_for_the_playing_track(monkeypatch):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from app.ui import player as P
    from app.ui.widgets import QueueRow
    from app.ui.pages import HomePage
    playing_path = "/music/a.flac"

    class FakePlayer:
        media = object()
        def playing(self): return True
        def owns(self, p): return p == playing_path
    monkeypatch.setattr(P.Player, "get", staticmethod(lambda: FakePlayer()))
    page = HomePage.__new__(HomePage)
    a, b = QueueRow("a", "Good", "A", "x", 100, "", True), QueueRow("b", "Good", "B", "y", 100, "", True)
    page._row_widgets = {"a": a, "b": b}
    page._audio_of = {"a": "/music/a.flac", "b": "/music/b.flac"}
    HomePage._mark_playing(page)
    assert not a.now.isHidden() and b.now.isHidden()
