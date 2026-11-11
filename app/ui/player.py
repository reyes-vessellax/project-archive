"""One audio player for the whole app, and the "now playing" bar at the bottom of the window.

Every play button (review spectrogram, library drop-down, search preview) goes through Player.get(), so only one
thing ever plays at a time, and whatever plays is always visible in the bar with pause and stop.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtWidgets import QFrame, QSlider, QStyle, QStyleOptionSlider, QWidget

from .widgets import PlayButton, StopButton, hbox, label, vbox




def _same_file(a: str, b: str) -> bool:
    """Same file, not same text: Windows paths come back with forward slashes."""
    import os
    if not a or not b:
        return False
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))

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
        self.art = None                        # QPixmap of the cover, when the caller had one (shown in the bar)
        self.next_art = None                   # set just before play() by pages that know the cover
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
            # Follow the system's output: plug in headphones (or pick AirPods / an interface in the OS) and
            # playback moves there. A QAudioOutput otherwise stays on the device it was created with.
            from PySide6.QtMultimedia import QMediaDevices
            self._devices = QMediaDevices(self)
            self._devices.audioOutputsChanged.connect(self.follow_default_output)
            self.follow_default_output()
            self.media.playbackStateChanged.connect(lambda *_: self.changed.emit())
            self.media.errorOccurred.connect(lambda *_: self.changed.emit())
            return True
        except Exception:
            self.media = self.out = None
            return False

    def follow_default_output(self) -> None:
        """Point playback at the current default output device, if it changed."""
        if self.out is None:
            return
        try:
            from PySide6.QtMultimedia import QMediaDevices
            dev = QMediaDevices.defaultAudioOutput()
            if not dev.isNull() and dev.id() != self.out.device().id():
                self.out.setDevice(dev)
        except Exception:
            pass                                      # never let a device hiccup stop playback

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
        self.follow_default_output()                  # the OS doesn't always announce a change; check on every play
        if not _same_file(self.media.source().toLocalFile(), path):
            self.media.stop()
            self.media.setSource(QUrl.fromLocalFile(path))
        self.title, self.subtitle, self.path = title, subtitle, path
        self.art, self.next_art = self.next_art, None
        self.media.setPosition(int(start_s * 1000))
        self.media.play()
        start_ms = int(start_s * 1000)
        if start_ms > 0:                      # some backends ignore a seek before the media is loaded
            QTimer.singleShot(200, lambda: self.media.setPosition(start_ms) if self.media.position() < start_ms - 500 else None)
        if stop_after_s:
            self._stop_at.start(int(stop_after_s * 1000) + 200)
        self.changed.emit()

    def owns(self, path: str | None) -> bool:
        return bool(path) and self.media is not None and _same_file(self.media.source().toLocalFile(), path)

    def playing(self) -> bool:
        if self.media is None:
            return False
        from PySide6.QtMultimedia import QMediaPlayer
        return self.media.playbackState() == QMediaPlayer.PlayingState

    def toggle(self):
        if self.playing():
            self.media.pause()
        elif self.path and self._ensure():
            self.follow_default_output()
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


class SeekSlider(QSlider):
    """Position bar: click anywhere to jump there, or drag; the seek happens when you let go.
    (A plain QSlider only steps a little towards the click, which felt like seeking was broken.)"""
    seek = Signal(float)                      # 0..1

    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.setRange(0, 1000)
        self.setCursor(Qt.PointingHandCursor)

    def _value_at(self, x: float) -> int:
        opt = QStyleOptionSlider(); self.initStyleOption(opt)
        handle = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self).width()
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), int(x - handle / 2),
                                              max(1, self.width() - handle))

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        self.setSliderDown(True); self.setValue(self._value_at(e.position().x())); e.accept()

    def mouseMoveEvent(self, e):
        if self.isSliderDown():
            self.setValue(self._value_at(e.position().x())); e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.isSliderDown():
            self.setValue(self._value_at(e.position().x())); self.setSliderDown(False)
            self.seek.emit(self.value() / self.maximum()); e.accept()
        else:
            super().mouseReleaseEvent(e)


class NowPlayingBar(QFrame):
    """Bottom bar: what's playing, play/pause, stop, position. Hidden when nothing is loaded."""

    def __init__(self):
        super().__init__()
        self.setObjectName("nowplaying")
        self.p = Player.get()
        lay = hbox(self, (16, 8, 20, 8), 18)
        self.btn = PlayButton(); self.btn.setObjectName("barplay"); self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.clicked.connect(self.p.toggle); self.btn.setToolTip("Play / pause")
        self.stop_btn = StopButton(); self.stop_btn.setObjectName("barstop"); self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.clicked.connect(self.p.stop); self.stop_btn.setToolTip("Stop")
        names = vbox(spacing=0)
        self.title = label("", "bartitle"); self.sub = label("", "faint")
        names.addWidget(self.title); names.addWidget(self.sub)
        self.pos = SeekSlider()
        self.pos.seek.connect(lambda f: self.p.duration() and self.p.seek(f * self.p.duration()))
        self.pos.valueChanged.connect(lambda _: self.pos.isSliderDown() and self._refresh())
        self.time = label("", "mono")
        self.vol = QSlider(Qt.Horizontal); self.vol.setObjectName("vol"); self.vol.setRange(0, 100)
        self.vol.setFixedWidth(90); self.vol.setValue(int(round(self.p.volume * 100))); self.vol.setToolTip("Volume")
        self.vol.valueChanged.connect(self._vol_moved)
        self.on_volume = None                  # the window sets this to remember the volume in Settings
        # three parts: what's playing | controls over the scrubber | volume
        from .discover_page import CoverArt
        self.art = CoverArt(); self.art.setFixedSize(46, 46)
        left = hbox(spacing=12); left.addWidget(self.art); left.addLayout(names, 1)
        lw = QWidget(); lw.setLayout(left); lw.setMinimumWidth(220)
        center = vbox(spacing=4)
        ctl = hbox(spacing=10); ctl.addStretch(1); ctl.addWidget(self.btn); ctl.addWidget(self.stop_btn); ctl.addStretch(1)
        center.addLayout(ctl)
        self.time_l = label("", "mono"); self.time_r = label("", "mono")
        scrub = hbox(spacing=10); scrub.addWidget(self.time_l); scrub.addWidget(self.pos, 1); scrub.addWidget(self.time_r)
        center.addLayout(scrub)
        cw = QWidget(); cw.setLayout(center)
        right = hbox(spacing=8); right.addStretch(1); right.addWidget(label("VOL", "faint")); right.addWidget(self.vol)
        rw = QWidget(); rw.setLayout(right); rw.setMinimumWidth(160)
        lay.addWidget(lw, 3); lay.addWidget(cw, 4); lay.addWidget(rw, 2)
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
        self.btn.set_playing(self.p.playing())
        d, t = self.p.duration(), self.p.position()
        if self.pos.isSliderDown():
            t = int(d * self.pos.value() / 1000)              # show where you're about to jump
        else:
            self.pos.setValue(int(1000 * t / d) if d > 0 else 0)
        self.time.setText(f"{_mmss(t)} / {_mmss(d)}" if d > 0 else _mmss(t))
        self.time_l.setText(_mmss(t)); self.time_r.setText(_mmss(d) if d > 0 else "")
        art = self.p.art
        if art is not getattr(self, "_shown_art", object()):
            self._shown_art = art
            self.art.set_pixmap(art)
            self.art.set_sleeve("", self.p.title, "")
