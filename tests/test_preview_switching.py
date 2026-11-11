"""Reyes: "make sure there are no glitches when you're pressing play and switching through songs". A preview you
moved on from never plays, and its late messages never land on the song you're on now."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class Page:
    def __init__(self):
        self.states = []

    def set_preview_state(self, state, msg=""):
        self.states.append((state, msg))


def test_a_retired_preview_is_ignored_and_its_clip_deleted(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.ui import player as P
    from app.ui.main_window import MainWindow
    played = []

    class FakePlayer:
        def play(self, *a, **k): played.append(a)
        def stop(self): pass
        def playing(self): return False
    monkeypatch.setattr(P.Player, "get", staticmethod(lambda: FakePlayer()))
    w = MainWindow.__new__(MainWindow)
    w._pv_page, w._pv_gen = Page(), 1
    old = tmp_path / "old.wav"; old.write_bytes(b"x")
    w._stop_preview()                                         # moved on: preview 1 is retired
    w._pv_page.states.clear()
    for msg in ("PREVIEW_PROGRESS 1 Getting… 40%", "PREVIEW_BUSY 1 busy", "PREVIEW_FAILED 1 Preview cancelled.",
                f"PREVIEW_READY 1 {old}\t60\tOld song\tSomeone"):
        w._notice(msg)
    assert played == [] and w._pv_page.states == [] and not old.exists()
    cur = tmp_path / "new.wav"; cur.write_bytes(b"x")
    w._notice(f"PREVIEW_READY {w._pv_gen} {cur}\t60\tNew song\tSomeone")   # the current one plays
    assert len(played) == 1 and played[0][1] == "New song" and w._pv_page.states[-1][0] == "playing"
