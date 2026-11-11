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


def test_switching_track_shows_play_not_the_other_tracks_pause(tmp_path):
    """Queue: a track plays, you open another: its button showed ❚❚ (the first track's state)."""
    app = QApplication.instance() or QApplication([])
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QPixmap
    from app.ui.player import Player
    from app.ui.widgets import SpectrumView
    pl = Player.get()
    if not pl._ensure():
        pytest.skip("no audio backend")
    png = tmp_path / "s.png"; pm = QPixmap(20, 10); pm.fill(); pm.save(str(png))
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    a.write_bytes(b"RIFF"); b.write_bytes(b"RIFF")
    v = SpectrumView()
    v.show_png(str(png), 44100, None, audio=str(a))
    pl.media.setSource(QUrl.fromLocalFile(str(a)))
    v.is_playing = lambda: v._mine()                      # "playing" = the player holds this view's track
    v._state_changed(); assert v.play_btn.toolTip().startswith("Pause")
    v.show_png(str(png), 44100, None, audio=str(b))        # open another track while the first one plays
    assert v.play_btn.toolTip().startswith("Play")
    pl.media.setSource(QUrl())
