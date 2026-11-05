"""Reusable pieces of the v5 interface. No file or engine work happens here."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, QObject, QPoint, QRunnable, Qt, Signal
from PySide6.QtGui import QPen, QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..adapters.base import ConnectorError
from ..config import APP_NAME
from ..core.safety import Rejected
from ..core.service import ActionBlocked
from ..media.tools import ToolMissing
from . import theme as T


# ------------------------------------------------------------------ worker plumbing
def _applog(line: str) -> None:
    try:
        from datetime import datetime
        from ..config import data_dir
        with open(data_dir() / "app.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} task: {line}\n")
    except Exception:
        pass


class Signals(QObject):
    progress = Signal(str, str)          # job_id, step
    done = Signal(str)                   # job_id (or "" = just refresh)
    failed = Signal(str, str)            # job_id or "", message
    results = Signal(object)             # SearchResult
    status = Signal(object)              # ConnectorStatus
    staged = Signal(str)                 # job_id that finished downloading and needs analysis
    notice = Signal(str)


class Task(QRunnable):
    def __init__(self, fn, signals: Signals):
        super().__init__()
        self.fn, self.signals = fn, signals

    def run(self):
        try:
            self.fn()
        except (Rejected, ActionBlocked, ToolMissing, ConnectorError) as e:
            _applog(f"task failed: {type(e).__name__}: {e}")
            self.signals.failed.emit("", str(e))
        except Exception as e:                                      # keep the app alive, report it
            import traceback
            _applog("task crashed: " + traceback.format_exc())
            self.signals.failed.emit("", f"Unexpected error: {e}")


# ------------------------------------------------------------------ small helpers
def label(text: str = "", role: str = "", tag: str = "", wrap: bool = False, tip: str = "") -> QLabel:
    w = QLabel(text)
    if role:
        w.setObjectName(role)
    if tag:
        w.setProperty("tag", tag)
    if wrap:
        w.setWordWrap(True)
    if tip:
        w.setToolTip(tip)
    return w


def button(text: str, role: str = "ghost", on_click=None) -> QPushButton:
    b = QPushButton(text.replace("&", "&&"))      # a bare & would become a keyboard mnemonic
    b.setObjectName(role)
    b.setCursor(Qt.PointingHandCursor)
    if on_click:
        b.clicked.connect(on_click)
    return b


def rule() -> QFrame:
    f = QFrame()
    f.setObjectName("rule")
    f.setFrameShape(QFrame.NoFrame)
    return f


def vbox(parent=None, margins=(0, 0, 0, 0), spacing=0) -> QVBoxLayout:
    lay = QVBoxLayout(parent) if parent else QVBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay


def hbox(parent=None, margins=(0, 0, 0, 0), spacing=0) -> QHBoxLayout:
    lay = QHBoxLayout(parent) if parent else QHBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay


def set_tag(widget, tag: str) -> None:
    widget.setProperty("tag", tag)
    T.repolish(widget)


def set_active(widget, active: bool) -> None:
    widget.setProperty("active", "true" if active else "false")
    T.repolish(widget)


def scroll(inner: QWidget) -> QScrollArea:
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setFrameShape(QFrame.NoFrame)
    s.setWidget(inner)
    return s


def page(margins=(48, 28, 48, 40), spacing=24, max_width: int = 1180) -> tuple[QWidget, QVBoxLayout]:
    """A centred, width-capped content column — the v5 page grid."""
    outer = QWidget(); outer.setObjectName("page")
    row = hbox(outer)
    row.addStretch(1)
    col = QWidget(); col.setObjectName("page"); col.setMaximumWidth(max_width)
    col.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    lay = vbox(col, margins, spacing)
    row.addWidget(col, 20)
    row.addStretch(1)
    return outer, lay


# ------------------------------------------------------------------ top bar
class TopBar(QWidget):
    tab_clicked = Signal(str)           # "queue" | "search" | "ready" | "library"
    avatar_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("topbar")
        lay = hbox(self, (48, 22, 48, 4), 22)
        from .brand import Brand
        self.brand = Brand(); self.brand.clicked.connect(lambda: self.tab_clicked.emit("queue"))
        lay.addWidget(self.brand)
        self.tabs: dict[str, QPushButton] = {}
        for key, text in (("queue", "Queue"), ("search", "Search"), ("ready", "Ready"), ("library", "Library")):
            b = button(text, "tab", lambda _=False, k=key: self.tab_clicked.emit(k))
            self.tabs[key] = b
            lay.addWidget(b)
        lay.addStretch(1)
        self.dot = label("●", "statusdot")
        self.status = label("", "status")
        self.counts = label("", "mono")
        lay.addWidget(self.dot); lay.addWidget(self.status); lay.addSpacing(6); lay.addWidget(self.counts)
        self.avatar = button("?", "avatar", self.avatar_clicked.emit)
        lay.addWidget(self.avatar)
        self.set_active("queue")

    def set_active(self, key: str) -> None:
        for k, b in self.tabs.items():
            set_active(b, k == key)

    def set_counts(self, queue: int, ready: int) -> None:
        self.tabs["queue"].setText(f"Queue  {queue}" if queue else "Queue")
        self.tabs["ready"].setText(f"Ready  {ready}" if ready else "Ready")

    def set_status(self, message: str, colour: str, detail: str = "") -> None:
        self.dot.setStyleSheet(f"color: {colour};")
        self.status.setText(message)
        self.status.setToolTip(message)
        self.counts.setText(detail)

    def set_initials(self, initials: str) -> None:
        self.avatar.setText(initials)


class AvatarMenu(QFrame):
    """The popup under the avatar: name, DJ name + plan, then the items."""
    picked = Signal(str)

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setObjectName("menu")
        self.setAttribute(Qt.WA_DeleteOnClose)            # exists only while open: nothing to flash later
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(280)
        lay = vbox(self, (8, 8, 8, 8), 2)
        head = QWidget(); h = hbox(head, (14, 10, 14, 12), 12)
        self.initials = button("?", "avatar"); self.initials.setEnabled(False)
        h.addWidget(self.initials)
        names = vbox(spacing=2)
        self.name = label("", "h2"); self.sub = label("", "muted")
        names.addWidget(self.name); names.addWidget(self.sub)
        h.addLayout(names, 1)
        lay.addWidget(head)
        lay.addWidget(rule())
        self.appearance = None
        for key, text in (("account", "Account & profile"), ("settings", "Settings"), ("appearance", "Appearance"),
                          (None, None), ("help", "Help & FAQ"), ("tour", "Take the tour"), ("whatsnew", "What's new"),
                          (None, None), ("signout", "Sign out")):
            if key is None:
                lay.addWidget(rule()); continue
            b = button(text, "menuitem", lambda _=False, k=key: (self.close(), self.picked.emit(k)))
            if key == "appearance":
                self.appearance = b
            lay.addWidget(b)

    def show_for(self, account, anchor: QWidget, theme: str) -> None:
        if account:
            self.initials.setText(account.initials)
            self.name.setText(account.name)
            self.sub.setText(f"{account.dj_name + ' · ' if account.dj_name else ''}Free plan")
        if self.appearance:
            self.appearance.setText(f"Appearance        {theme.title()}")
        pos = anchor.mapToGlobal(QPoint(anchor.width() - self.width(), anchor.height() + 8))
        self.move(pos)
        self.show()


# ------------------------------------------------------------------ queue row
class QueueRow(QWidget):
    """One line of the queue: word tag, title/artist, progress, meta, and × when finished."""
    clicked = Signal(str)
    removed = Signal(str)

    def __init__(self, job_id: str, tag: str, title: str, artist: str, pct: float | None, meta: str, removable: bool):
        super().__init__()
        self.job_id = job_id
        self.setObjectName("row")
        self.setProperty("tag", tag)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(60)
        lay = hbox(self, (4, 10, 12, 10), 12)
        # × first, on the left, where the hand already is; a blank spacer keeps rows aligned when it's hidden
        self.x = button("×", "x", lambda: self.removed.emit(self.job_id))
        self.x.setToolTip("Remove from the list" if tag in ("Done", "Gone", "Error") else "Delete this track from quarantine")
        self.x.setFixedWidth(22)
        self.x.setVisible(removable)
        self.x_space = QWidget(); self.x_space.setFixedWidth(22); self.x_space.setVisible(not removable)
        lay.addWidget(self.x); lay.addWidget(self.x_space)
        self.tag = label(tag.upper(), "tag", tag); self.tag.setFixedWidth(60)
        lay.addWidget(self.tag)
        names = vbox(spacing=2)
        self.title = label(title); self.title.setStyleSheet("font-weight: 600; font-size: 15px;")
        self.title.setToolTip(title)
        self.artist = label(artist or " ", "muted")
        names.addWidget(self.title); names.addWidget(self.artist)
        lay.addLayout(names, 1)
        self.bar = QProgressBar(); self.bar.setTextVisible(False); self.bar.setFixedWidth(150); self.bar.setRange(0, 100)
        self.bar.setValue(int(pct) if pct is not None else 0); self.bar.setProperty("tag", tag)
        self.bar.setVisible(pct is not None)
        lay.addWidget(self.bar)
        self.meta = label(meta, "mono"); self.meta.setFixedWidth(120); self.meta.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.meta)
        for w in (self.tag, self.title, self.artist, self.meta, self.bar, self.x_space):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.x.geometry().contains(e.pos()):
            self.clicked.emit(self.job_id)
        super().mousePressEvent(e)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", "true" if on else "false")
        T.repolish(self)


# ------------------------------------------------------------------ spectrogram
class SpectrumView(QLabel):
    """The PNG from the analysis with a kHz axis and the cutoff line, drawn in the theme's accent.
    When given the audio file, a small play button appears: press it and a playhead crawls across the
    spectrogram while the track plays. Click anywhere on the picture to jump there."""
    AXIS = 44
    BAR = 34                      # bottom strip: play control + time

    def __init__(self, min_height: int = 180):
        super().__init__()
        self.setMinimumHeight(min_height)
        self.setAlignment(Qt.AlignCenter)
        self._pix: QPixmap | None = None
        self._nyq = 22050
        self._cutoff = None
        self._accent = "#d2721e"
        self._audio: str | None = None
        self._duration_ms = 0
        self._player = None
        self._out = None
        self.play_btn = QPushButton("▶", self); self.play_btn.setObjectName("play"); self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setFixedSize(26, 26); self.play_btn.clicked.connect(self.toggle); self.play_btn.hide()
        self.play_btn.setToolTip("Play (space)")
        self.clear_view("")

    # ---------------------------------------------------------------- content
    def set_accent(self, colour: str) -> None:
        self._accent = colour
        self.update()

    def clear_view(self, text: str):
        self.stop()
        self._pix = None; self._audio = None
        self.setText(text)
        self.setObjectName("faint")
        self.play_btn.hide()
        self.update()

    def show_png(self, path: str, sample_rate: int, cutoff_hz: float | None, audio: str | None = None,
                 duration_s: float | None = None):
        pix = QPixmap(path)
        if pix.isNull():
            self.clear_view("Spectrogram unavailable.")
            return
        if audio != self._audio:
            self.stop()
        self._pix, self._nyq, self._cutoff = pix, (sample_rate or 44100) / 2, cutoff_hz
        self._audio = audio if audio and Path(audio).exists() else None
        self._duration_ms = int((duration_s or 0) * 1000)
        self.setText("")
        self.play_btn.setVisible(self._audio is not None)
        self._place_button()
        self.update()

    # ---------------------------------------------------------------- playback
    def _ensure_player(self) -> bool:
        if self._player is not None:
            return True
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            self._out = QAudioOutput(self)
            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(self._out)
            self._player.positionChanged.connect(lambda _: self.update())
            self._player.durationChanged.connect(self._got_duration)
            self._player.playbackStateChanged.connect(self._state_changed)
            self._player.errorOccurred.connect(lambda *_: self._state_changed())
            return True
        except Exception:
            self._player = None
            return False

    def _got_duration(self, ms: int):
        if ms > 0:
            self._duration_ms = ms
        self.update()

    def _state_changed(self, *_):
        playing = self.is_playing()
        self.play_btn.setText("❚❚" if playing else "▶")
        self.play_btn.setToolTip("Pause (space)" if playing else "Play (space)")
        self.update()

    def is_playing(self) -> bool:
        if self._player is None:
            return False
        from PySide6.QtMultimedia import QMediaPlayer
        return self._player.playbackState() == QMediaPlayer.PlayingState

    def toggle(self):
        if not self._audio or not self._ensure_player():
            return
        if self.is_playing():
            self._player.pause(); return
        if self._player.source().toLocalFile() != self._audio:
            self._player.setSource(QUrl.fromLocalFile(self._audio))
        self._player.play()

    def stop(self):
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())
        self.update()

    def position_ms(self) -> int:
        return self._player.position() if self._player is not None else 0

    def seek_fraction(self, f: float):
        if not self._audio or not self._ensure_player() or self._duration_ms <= 0:
            return
        if self._player.source().toLocalFile() != self._audio:
            self._player.setSource(QUrl.fromLocalFile(self._audio))
        self._player.setPosition(int(max(0.0, min(1.0, f)) * self._duration_ms))
        if not self.is_playing():
            self._player.play()

    # ---------------------------------------------------------------- geometry
    def _image_rect(self):
        return self.rect().adjusted(self.AXIS, 2, -2, -self.BAR)

    def _place_button(self):
        self.play_btn.move(self.AXIS, self.height() - self.BAR + (self.BAR - self.play_btn.height()) // 2 + 3)
        self.play_btn.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_button()

    def mousePressEvent(self, e):
        r = self._image_rect()
        if self._pix is not None and self._audio and r.contains(e.pos()) and r.width() > 0:
            self.seek_fraction((e.pos().x() - r.left()) / r.width())
            return
        super().mousePressEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space and self._audio:
            self.toggle(); return
        super().keyPressEvent(e)

    # ---------------------------------------------------------------- painting
    def paintEvent(self, e):
        if self._pix is None:
            return super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._image_rect()
        p.drawPixmap(r, self._pix)
        faint = self.palette().text().color(); faint.setAlpha(140)
        p.setPen(faint)
        small = QFont(T.MONO); small.setPointSizeF(7.5); p.setFont(small)
        for khz in range(0, int(self._nyq / 1000) + 1, 5):
            y = r.bottom() - int(r.height() * khz * 1000 / self._nyq)
            p.drawText(2, y + 3, f"{khz}k")
        if self._cutoff:
            y = r.bottom() - int(r.height() * self._cutoff / self._nyq)
            pen = p.pen(); pen.setColor(QColor(self._accent)); pen.setWidth(2); pen.setStyle(Qt.DashLine); p.setPen(pen)
            p.drawLine(r.left(), y, r.right(), y)
            p.setPen(QColor("#ffffff"))
            p.fillRect(r.right() - 112, y - 18, 108, 16, QColor(0, 0, 0, 120))
            p.drawText(r.right() - 108, y - 6, f"cutoff {self._cutoff / 1000:.1f} kHz")
        # playhead
        pos = self.position_ms()
        if self._audio and self._duration_ms > 0 and (pos > 0 or self.is_playing()):
            x = r.left() + int(r.width() * min(1.0, pos / self._duration_ms))
            pen = QPen(QColor("#ffffff")); pen.setWidth(2); p.setPen(pen)
            p.drawLine(x, r.top(), x, r.bottom())
            p.setBrush(QColor("#ffffff")); p.setPen(Qt.NoPen)
            p.drawPolygon([QPoint(x - 5, r.top()), QPoint(x + 5, r.top()), QPoint(x, r.top() + 7)])
        p.setPen(faint)
        base = self.height() - self.BAR // 2 + 7
        time_x = r.left() + (self.play_btn.width() + 10 if self.play_btn.isVisible() else 0)
        if self._audio and self._duration_ms > 0:
            p.drawText(time_x, base, f"{_mmss(pos)} / {_mmss(self._duration_ms)}")
        else:
            p.drawText(time_x, base, "0:00")
        p.drawText(r.right() - 36, base, "time →")
        p.end()


def _mmss(ms: int) -> str:
    s = max(0, int(ms // 1000))
    return f"{s // 60}:{s % 60:02d}"
