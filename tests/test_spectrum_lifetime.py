"""A deleted SpectrumView must not stay connected to the shared player. A Library panel rebuilt while its track
was playing left lambdas firing at the dead view on every position tick: thousands of
"Internal C++ object (SpectrumView) already deleted" errors in users' logs."""
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtWidgets import QApplication, QWidget


def test_deleted_view_is_disconnected_from_player(capfd):
    app = QApplication.instance() or QApplication([])
    from app.ui.player import Player
    from app.ui.widgets import SpectrumView
    pl = Player.get()
    if not pl._ensure():
        pytest.skip("no audio backend")
    parent = QWidget()
    v = SpectrumView(); v.setParent(parent); v._audio = "/nowhere/track.mp3"
    assert v._ensure_player()
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete); app.processEvents()
    pl.media.setSource(QUrl.fromLocalFile("/nowhere/track.mp3"))     # the dead view's track is the one playing
    pl.media.positionChanged.emit(1234)
    pl.media.durationChanged.emit(5000)
    app.processEvents()
    pl.media.setSource(QUrl())
    assert "already deleted" not in capfd.readouterr().err
