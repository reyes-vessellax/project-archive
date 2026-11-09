"""Playback follows the system's default output (headphones plugged in after the app started)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeDev:
    def __init__(self, i):
        self._i = i

    def id(self):
        return self._i

    def isNull(self):
        return False


class FakeOut:
    def __init__(self):
        self.dev = FakeDev(b"speakers")

    def device(self):
        return self.dev

    def setDevice(self, d):
        self.dev = d


def test_switches_to_new_default(monkeypatch):
    from PySide6.QtMultimedia import QMediaDevices
    from PySide6.QtWidgets import QApplication
    from app.ui.player import Player
    QApplication.instance() or QApplication([])
    p = Player.__new__(Player)
    p.out = FakeOut()
    monkeypatch.setattr(QMediaDevices, "defaultAudioOutput", staticmethod(lambda: FakeDev(b"headphones")))
    Player.follow_default_output(p)
    assert p.out.device().id() == b"headphones"
