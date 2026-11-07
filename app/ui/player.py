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
        # The audio device is opened on the first play, not at start-up: creating QAudioOutput with no
        # output device (remote desktop, an unplugged interface, a headless test box) crashes Qt.
        self.media = None
        self.out = None
        self.volume = 0.8                      # 0..1, one volume for the whole app (Settings.volume)
        self.title, self.subtitle, self.path = "", "", ""
        self._stop_at = QTimer(self, singleShot=True, timeout=self.stop)

    def _ensure(self) -> bool:
        if self.media is not None:
            return True
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            self.media = QMediaPlayer(self)
            self.out = QAudioOutput(self)
            self.out.setVolume(self.volume)
            self.media.setAudioOutput(self.out)
            self.media.playbackStateChanged.connect(lambda *_: self.changed.emit())
            self.media.errorOccurred.connect(lambda *_: self.changed.emit())
            return True
        except Exception:
            self.media = self.out = None
            return False

    def set_volume(self, v: float) -> None:
        self.volume = max(0.0, min(1.0, float(v)))
        if self.out is not None:
            self.out.setVolume(self.volume)
        self.changed.emit()

    def duration(self) -> int:
        return self.media.duration() if self.media is not None else 0

    def position(self) -> int:
        return self.media.position() if self.media is not None else 0

    def seek(self, ms: int) -> None:
        if self.media is not None:
            self.media.setPosition(int(ms))

    def play(self, path: str, title: str, subtitle: str = "", start_s: float = 0.0, stop_after_s: float | None = None):
        """Play `path` (replacing whatever was playing). `stop_after_s` stops it by itself (previews)."""
        self._stop_at.stop()
        if not self._ensure():
            return
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
        return bool(path) and self.media is not None and self.media.source().toLocalFile() == path

    def playing(self) -> bool:
        if self.media is None:
            return False
        from PySide6.QtMultimedia import QMediaPlayer
        return self.media.playbackState() == QMediaPlayer.PlayingState

    def toggle(self):
        if self.playing():
            self.media.pause()
        elif self.path and self._ensure():
            self.media.play()
        self.changed.emit()

    def stop(self):
        self._stop_at.stop()
        if self.media is not None:
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
        self.pos.sliderMoved.connect(lambda v: self.p.duration() and self.p.seek(v / 1000 * self.p.duration()))
        self.time = label("", "mono")
        self.vol = QSlider(Qt.Horizontal); self.vol.setObjectName("vol"); self.vol.setRange(0, 100)
        self.vol.setFixedWidth(90); self.vol.setValue(int(round(self.p.volume * 100))); self.vol.setToolTip("Volume")
        self.vol.valueChanged.connect(self._vol_moved)
        self.on_volume = None                  # the window sets this to remember the volume in Settings
        lay.addWidget(self.btn); lay.addWidget(self.stop_btn); lay.addLayout(names, 2); lay.addWidget(self.pos, 3); lay.addWidget(self.time)
        lay.addWidget(label("vol", "faint")); lay.addWidget(self.vol)
        self.tick = QTimer(self, interval=250, timeout=self._refresh)
        self.p.changed.connect(self._refresh)
        self.setVisible(False)

    def _vol_moved(self, value: int):
        self.p.set_volume(value / 100)
        self.vol.setToolTip(f"Volume · {value}%")
        if self.on_volume:
            self.on_volume(value / 100)

    def set_volume(self, v: float):
        """Seed from Settings at start-up (does not call on_volume back)."""
        self.p.set_volume(v)
        self.vol.blockSignals(True); self.vol.setValue(int(round(v * 100))); self.vol.blockSignals(False)

    def _refresh(self):
        has = bool(self.p.path)
        self.setVisible(has)
        if not has:
            self.tick.stop(); return
        self.tick.start()
        self.title.setText(self.p.title); self.sub.setText(self.p.subtitle)
        self.btn.setText("❚❚" if self.p.playing() else "▶")
        d, t = self.p.duration(), self.p.position()
        if not self.pos.isSliderDown():
            self.pos.setValue(int(1000 * t / d) if d > 0 else 0)
        self.time.setText(f"{_mmss(t)} / {_mmss(d)}" if d > 0 else _mmss(t))
