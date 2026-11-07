"""One audio player for the whole app, and the "now playing" bar at the bottom of the window.

Every play button (review spectrogram, library drop-down, search preview) goes through Player.get(), so only one
thing ever plays at a time, and whatever plays is always visible in the bar with pause and stop.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtWidgets import QFrame, QSlider

from .widgets import button, hbox, label, vbox


class Player(QObject):
    changed = Signal()                     # source, state or title changed
    _inst: "Player | None" = None

    @classmethod
    def get(cls) -> "Player":
        if cls._inst is None:
            cls._inst = Player()
        return cls._inst

    def __init__(self):
        super().__init__()
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        self.media = QMediaPlayer(self)
        self.out = QAudioOutput(self)
        self.media.setAudioOutput(self.out)
        self.title, self.subtitle, self.path = "", "", ""
        self._stop_at = QTimer(self, singleShot=True, timeout=self.stop)
        self.media.playbackStateChanged.connect(lambda *_: self.changed.emit())
        self.media.errorOccurred.connect(lambda *_: self.changed.emit())

    def play(self, path: str, title: str, subtitle: str = "", start_s: float = 0.0, stop_after_s: float | None = None):
        """Play `path` (replacing whatever was playing). `stop_after_s` stops it by itself (previews)."""
        self._stop_at.stop()
        if self.media.source().toLocalFile() != path:
            self.media.stop()
            self.media.setSource(QUrl.fromLocalFile(path))
        self.title, self.subtitle, self.path = title, subtitle, path
        self.media.setPosition(int(start_s * 1000))
        self.media.play()
        start_ms = int(start_s * 1000)
        if start_ms > 0:                      # some backends ignore a seek before the media is loaded
            QTimer.singleShot(200, lambda: self.media.setPosition(start_ms) if self.media.position() < start_ms - 500 else None)
        if stop_after_s:
            self._stop_at.start(int(stop_after_s * 1000) + 200)
        self.changed.emit()

    def owns(self, path: str | None) -> bool:
        return bool(path) and self.media.source().toLocalFile() == path

    def playing(self) -> bool:
        from PySide6.QtMultimedia import QMediaPlayer
        return self.media.playbackState() == QMediaPlayer.PlayingState

    def toggle(self):
        if self.playing():
            self.media.pause()
        elif self.path:
            self.media.play()
        self.changed.emit()

    def stop(self):
        self._stop_at.stop()
        self.media.stop()
        self.media.setSource(QUrl())
        self.title = self.subtitle = self.path = ""
        self.changed.emit()


def _mmss(ms: int) -> str:
    s = max(0, ms // 1000)
    return f"{s // 60}:{s % 60:02d}"


class NowPlayingBar(QFrame):
    """Bottom bar: what's playing, play/pause, stop, position. Hidden when nothing is loaded."""

    def __init__(self):
        super().__init__()
        self.setObjectName("nowplaying")
        self.p = Player.get()
        lay = hbox(self, (20, 10, 20, 10), 14)
        self.btn = button("❚❚", "play", self.p.toggle); self.btn.setToolTip("Play / pause")
        self.stop_btn = button("■", "small", self.p.stop); self.stop_btn.setToolTip("Stop")
        names = vbox(spacing=0)
        self.title = label("", "rowtitle"); self.sub = label("", "faint")
        names.addWidget(self.title); names.addWidget(self.sub)
        self.pos = QSlider(Qt.Horizontal); self.pos.setRange(0, 1000)
        self.pos.sliderMoved.connect(lambda v: self.p.media.duration() and self.p.media.setPosition(int(v / 1000 * self.p.media.duration())))
        self.time = label("", "mono")
        lay.addWidget(self.btn); lay.addWidget(self.stop_btn); lay.addLayout(names, 2); lay.addWidget(self.pos, 3); lay.addWidget(self.time)
        self.tick = QTimer(self, interval=250, timeout=self._refresh)
        self.p.changed.connect(self._refresh)
        self.setVisible(False)

    def _refresh(self):
        has = bool(self.p.path)
        self.setVisible(has)
        if not has:
            self.tick.stop(); return
        self.tick.start()
        self.title.setText(self.p.title); self.sub.setText(self.p.subtitle)
        self.btn.setText("❚❚" if self.p.playing() else "▶")
        d, t = self.p.media.duration(), self.p.media.position()
        if not self.pos.isSliderDown():
            self.pos.setValue(int(1000 * t / d) if d > 0 else 0)
        self.time.setText(f"{_mmss(t)} / {_mmss(d)}" if d > 0 else _mmss(t))
