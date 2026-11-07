"""Reusable pieces of the v5 interface. No file or engine work happens here."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QSize, QPropertyAnimation, QRectF, QTimer, QUrl, QObject, QPoint, QRunnable, Qt, Signal
from PySide6.QtGui import QPainterPath, QPen, QColor, QFont, QPainter, QPixmap
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
    progress_search = Signal(int, int, bool)   # responses so far, files so far, first rows already shown


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
class WrapLabel(QLabel):
    """A word-wrapping label that always asks for the height its text needs at its current width.

    Plain QLabel + setWordWrap inside nested layouts reports a stale height when the window is
    resized, and the last line of a two-line description gets clipped (seen on the review page's
    check rows at some window widths). Pinning the minimum height on every resize fixes it.

    Its minimum WIDTH is kept small on purpose: a fresh wrapped label reports its unwrapped text width
    as the minimum until the first layout pass, and inside a scroll area that made the whole column
    jump wider (and taller) for one frame on every refresh — the 0.6.0–0.6.3 "UI glitch"."""
    MIN_W = 80

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def minimumSizeHint(self):
        base = super().minimumSizeHint()
        w = self.width() if self.width() > self.MIN_W else 0
        return QSize(min(self.MIN_W, base.width()), self.heightForWidth(w) if w else base.height())

    def sizeHint(self):
        base = super().sizeHint()
        return QSize(min(base.width(), 600), base.height())

    def _fit(self):
        w = self.width()
        if w > self.MIN_W:
            self.setMinimumHeight(self.heightForWidth(w))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit()


def label(text: str = "", role: str = "", tag: str = "", wrap: bool = False, tip: str = "") -> QLabel:
    w = WrapLabel(text) if wrap else QLabel(text)
    if role:
        w.setObjectName(role)
    if tag:
        w.setProperty("tag", tag)
    if wrap:
        w.setWordWrap(True)
    if tip:
        w.setToolTip(tip)
    return w


def button(text: str, role: str = "ghost", on_click=None, parent=None) -> QPushButton:
    b = QPushButton(text.replace("&", "&&"), parent)      # a bare & would become a keyboard mnemonic
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


class SmoothWheel(QObject):
    """Browser-feel wheel scrolling for any QAbstractScrollArea: per-pixel, a fixed distance per notch
    (like Chrome's ~100 px), an ease-out glide, and momentum — notches that arrive mid-glide add to the
    distance and lengthen the glide instead of restarting it. Trackpads send pixel deltas and are left
    to Qt, which already handles them natively."""
    PX_PER_NOTCH = 72
    MIN_MS, MAX_MS = 240, 600

    def __init__(self, area):
        super().__init__(area)
        self.area = area
        self.bar = area.verticalScrollBar()
        self.anim = QPropertyAnimation(self.bar, b"value", self)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.target = None
        try:
            area.setVerticalScrollMode(area.ScrollPerPixel)      # item views default to jumping a row at a time
        except Exception:
            pass
        area.viewport().installEventFilter(self)
        area.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Wheel and ev.angleDelta().y() != 0 and not ev.pixelDelta().y():
            if ev.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
                return False
            notches = ev.angleDelta().y() / 120.0
            running = self.anim.state() == QPropertyAnimation.Running and self.target is not None
            base = self.target if running else self.bar.value()
            self.target = int(max(self.bar.minimum(), min(self.bar.maximum(), base - notches * self.PX_PER_NOTCH)))
            distance = abs(self.target - self.bar.value())
            if distance == 0:
                ev.accept(); return True
            ms = int(max(self.MIN_MS, min(self.MAX_MS, self.MIN_MS + distance * 0.9)))
            self.anim.stop()
            self.anim.setDuration(ms)
            self.anim.setStartValue(self.bar.value()); self.anim.setEndValue(self.target); self.anim.start()
            ev.accept()
            return True
        return False


def smooth(area) -> None:
    """Attach SmoothWheel to a scroll area / item view (idempotent)."""
    if not area.property("smoothwheel"):
        area.setProperty("smoothwheel", True)
        SmoothWheel(area)


def keep_scroll(area, rebuild) -> None:
    """Rebuild the contents of a scroll area / view without the scroll position jumping to the top."""
    bar = area.verticalScrollBar()
    value = bar.value()
    rebuild()
    bar.setValue(value)
    QTimer.singleShot(0, lambda: bar.setValue(value))          # again after the layout has settled


def scroll(inner: QWidget) -> QScrollArea:
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setFrameShape(QFrame.NoFrame)
    s.setWidget(inner)
    smooth(s)
    return s


def page(margins=(48, 28, 48, 40), spacing=24, max_width: int = 1180) -> tuple[QWidget, QVBoxLayout]:
    """A centred, width-capped content column — the v5 page grid."""
    outer = QWidget(); outer.setObjectName("page")
    row = hbox(outer)
    col = QWidget(); col.setObjectName("page"); col.setMaximumWidth(max_width)
    col.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    m = (min(margins[0], 36), margins[1], min(margins[2], 36), margins[3])
    lay = vbox(col, m, spacing)
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


class Sidebar(QWidget):
    """Left navigation (design v6): brand, pages, update notice, connection status, account.
    Same interface as TopBar so the window logic doesn't care which one it has."""
    tab_clicked = Signal(str)           # "queue" | "search" | "wishlist" | "ready" | "library" | "batch"
    avatar_clicked = Signal()
    update_clicked = Signal()
    crate_clicked = Signal(str, str)    # crate id, name
    new_crate = Signal()
    crate_menu = Signal(str, str, object)   # id, name, global QPoint (right-click: rename / delete)

    NAV = (("queue", "Home"), ("search", "Search"), ("wishlist", "Wishlist"), ("ready", "Ready"), ("library", "Library"),
           ("batch", "Batch"))

    def __init__(self):
        super().__init__()
        self.setObjectName("sidebar")
        self._crate_btns: dict = {}
        self.setFixedWidth(232)
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = vbox(self, (14, 20, 14, 16), 2)
        from .brand import Brand
        self.brand = Brand(); self.brand.clicked.connect(lambda: self.tab_clicked.emit("queue"))
        bw = QWidget(); bl = hbox(bw, (0, 4, 0, 22)); bl.addWidget(self.brand)
        lay.addWidget(bw)
        self.tabs: dict[str, QPushButton] = {}
        self._names = dict(self.NAV)
        for key, text in self.NAV:
            b = button(text, "navitem", lambda _=False, k=key: self.tab_clicked.emit(k))
            b.setCursor(Qt.PointingHandCursor)
            self.tabs[key] = b
            lay.addWidget(b)
        lay.addSpacing(18)
        ch = QWidget(); chl = hbox(ch, (12, 0, 4, 4), 6)
        chl.addWidget(label("CRATES", "tag")); chl.addStretch(1)
        add = button("+", "x", self.new_crate.emit); add.setToolTip("New crate"); chl.addWidget(add)
        lay.addWidget(ch)
        self.crate_host = QWidget(); self.crate_lay = vbox(self.crate_host, spacing=2)
        lay.addWidget(self.crate_host)
        self.crate_empty = button("+ New crate", "navitem", self.new_crate.emit)
        lay.addWidget(self.crate_empty)
        lay.addStretch(1)
        self.update_btn = button("", "accent", self.update_clicked.emit)
        self.update_btn.setVisible(False)
        lay.addWidget(self.update_btn); lay.addSpacing(10)
        st = QWidget(); sl = hbox(st, (10, 0, 6, 0), 8)
        self.dot = label("●", "statusdot"); self.status = label("", "mono"); self.status.setWordWrap(True)
        sl.addWidget(self.dot); sl.addWidget(self.status, 1)
        lay.addWidget(st)
        self.counts = label("", "mono"); self.counts.setContentsMargins(10, 0, 0, 0); lay.addWidget(self.counts)
        lay.addSpacing(10)
        acc = QWidget(); al = hbox(acc, (6, 0, 0, 0), 10)
        self.avatar = button("?", "avatar", self.avatar_clicked.emit)
        self.account_name = label("Account", "muted")
        al.addWidget(self.avatar); al.addWidget(self.account_name, 1)
        lay.addWidget(acc)
        self.set_active("queue")

    def set_active(self, key: str) -> None:
        for k, b in self.tabs.items():
            set_active(b, k == key)
        for cid, b in self._crate_btns.items():
            set_active(b, key == f"crate:{cid}")

    def set_crates(self, crates: list[dict]) -> None:
        while self.crate_lay.count():
            w = self.crate_lay.takeAt(0).widget()
            if w:
                w.hide(); w.deleteLater()
        self._crate_btns = {}
        for c in crates:
            b = button(f"{c['name']}   {c['n']}" if c["n"] else c["name"], "navitem",
                       lambda _=False, cid=c["id"], n=c["name"]: self.crate_clicked.emit(cid, n))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda pos, cid=c["id"], n=c["name"], btn=b: self.crate_menu.emit(cid, n, btn.mapToGlobal(pos)))
            b.setToolTip("Right-click to rename or delete")
            self.crate_lay.addWidget(b); self._crate_btns[c["id"]] = b
        self.crate_empty.setVisible(not crates)

    def set_counts(self, queue: int, ready: int) -> None:
        self.tabs["queue"].setText(f"Home   {queue}" if queue else "Home")
        self.tabs["ready"].setText(f"Ready   {ready}" if ready else "Ready")

    def set_wish_count(self, found: int) -> None:
        """How many wishes turned up and haven't been looked at yet."""
        self.tabs["wishlist"].setText(f"Wishlist   ● {found}" if found else "Wishlist")

    def set_status(self, message: str, colour: str, detail: str = "") -> None:
        self.dot.setStyleSheet(f"color: {colour};")
        short = message.split(":")[0].split(". ")[0].strip()
        self.status.setText((short if len(short) <= 26 else short[:24] + "…").lower())
        self.status.setToolTip(message)
        self.counts.setText(detail)
        self.counts.setVisible(bool(detail))

    def set_initials(self, initials: str, name: str = "") -> None:
        self.avatar.setText(initials)
        if name:
            self.account_name.setText(name)

    def set_update(self, text: str) -> None:
        self.update_btn.setText(text)
        self.update_btn.setVisible(bool(text))


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
        # NOTE: every child is added to the layout BEFORE any setVisible(): a parentless widget that is shown
        # becomes its own top-level window for a frame — the "flashing dialog boxes" of 0.3/0.4.
        self.x = button("×", "x", lambda: self.removed.emit(self.job_id), parent=self)
        self.x.setToolTip("Cancel download" if tag == "Down" else "Remove from the list" if tag in ("Done", "Gone", "Error") else "Delete this track from quarantine")
        self.x.setFixedWidth(22)
        self.x_space = QWidget(self); self.x_space.setFixedWidth(22)
        lay.addWidget(self.x); lay.addWidget(self.x_space)
        self.x.setVisible(removable); self.x_space.setVisible(not removable)
        self.tag = label(tag.upper(), "tag", tag); self.tag.setFixedWidth(60)
        lay.addWidget(self.tag)
        names = vbox(spacing=2)
        self.title = label(title); self.title.setStyleSheet("font-weight: 600; font-size: 15px;")
        self.title.setToolTip(title)
        self.artist = label(artist or " ", "muted")
        names.addWidget(self.title); names.addWidget(self.artist)
        lay.addLayout(names, 1)
        self.bar = QProgressBar(self); self.bar.setTextVisible(False); self.bar.setFixedWidth(150); self.bar.setRange(0, 100)
        self.bar.setValue(int(pct) if pct is not None else 0); self.bar.setProperty("tag", tag)
        lay.addWidget(self.bar)
        self.bar.setVisible(pct is not None)
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

    def flash(self) -> None:
        """A short green blip when this track just moved to the next stage."""
        self.setProperty("flash", "true"); T.repolish(self)

        def off():
            try:
                self.setProperty("flash", "false"); T.repolish(self)
            except RuntimeError:
                pass                                          # the row was rebuilt meanwhile
        QTimer.singleShot(900, off)


# ------------------------------------------------------------------ spectrogram
class PlayButton(QPushButton):
    """Round play/pause control drawn by hand, so the pause bars sit close together on every font."""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self._playing = False

    def set_playing(self, on: bool):
        self._playing = on; self.update()

    def paintEvent(self, e):
        super().paintEvent(e)                                  # background + hover from the stylesheet
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen); p.setBrush(self.palette().buttonText().color())
        w, h = self.width(), self.height(); cx, cy = w / 2, h / 2
        if self._playing:
            bw, bh, gap = w * 0.13, h * 0.38, w * 0.1
            p.drawRoundedRect(QRectF(cx - gap / 2 - bw, cy - bh / 2, bw, bh), 1.2, 1.2)
            p.drawRoundedRect(QRectF(cx + gap / 2, cy - bh / 2, bw, bh), 1.2, 1.2)
        else:
            s = h * 0.38
            path = QPainterPath(); path.moveTo(cx - s * 0.42, cy - s * 0.5); path.lineTo(cx + s * 0.58, cy)
            path.lineTo(cx - s * 0.42, cy + s * 0.5); path.closeSubpath(); p.drawPath(path)
        p.end()


class LevelStrip(QWidget):
    """A row of LED segments (green -> amber -> red) showing the level while a track plays."""
    SEGMENTS = 40

    def __init__(self):
        super().__init__()
        self.setFixedHeight(12)
        self._level, self._shown = 0.0, 0.0

    def set_level(self, v: float):
        self._level = max(0.0, min(1.0, v))
        # fast attack, slower release, like a real meter
        self._shown = self._level if self._level > self._shown else self._shown * 0.86 + self._level * 0.14
        self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        n, gap = self.SEGMENTS, 3
        w = (self.width() - gap * (n - 1)) / n
        lit = int(round(self._shown * n))
        off = QColor(T.colours(getattr(self, "_theme", "light"))["bar"])
        for i in range(n):
            if i < lit:
                c = QColor("#2fb562") if i < n * 0.55 else QColor("#ffb000") if i < n * 0.75 else QColor("#dc143c")
            else:
                c = off
            p.setPen(Qt.NoPen); p.setBrush(c)
            p.drawRect(QRectF(i * (w + gap), 2, w, 8))
        p.end()


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
        self._drop_s = None; self._prev_start = None; self._prev_len = 20.0
        self._prev_timer = None
        self.play_btn = PlayButton(self); self.play_btn.setObjectName("play"); self.play_btn.setCursor(Qt.PointingHandCursor)
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
        self._pix, self._nyq, self._cutoff = pix, (sample_rate or 44100) / 2, cutoff_hz
        self._levels = None                                   # per-column loudness, computed on first use
        self._ensure_player()                                 # follow the shared player (▶ shows ❚❚ if this track plays)
        self._state_changed()
        self._audio = audio if audio and Path(audio).exists() else None
        self._duration_ms = int((duration_s or 0) * 1000)
        self.setText("")
        self.play_btn.setVisible(self._audio is not None)
        self._place_button()
        self.update()

    def current_level(self) -> float:
        """0..1 loudness at the playhead, read from the spectrogram's brightness (what the level strip shows)."""
        if self._pix is None or not self.is_playing() or self._duration_ms <= 0:
            return 0.0
        if self._levels is None:
            import numpy as np
            img = self._pix.toImage().convertToFormat(self._pix.toImage().Format.Format_Grayscale8)
            a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width()]
            col = a.astype(float).mean(axis=0)
            lo, hi = np.percentile(col, 5), np.percentile(col, 99)
            self._levels = np.clip((col - lo) / max(1.0, hi - lo), 0, 1)
        i = int(len(self._levels) * min(0.999, self.position_ms() / self._duration_ms))
        return float(self._levels[i])

    def set_preview(self, drop_s: float | None, start_s: float | None, length_s: float = 20.0):
        """Mark the drop and the 20-second preview window on the picture."""
        self._drop_s, self._prev_start, self._prev_len = drop_s, start_s, length_s
        self.update()

    def play_preview(self):
        """Play the preview window through the shared player; it stops by itself."""
        if not self._audio or self._prev_start is None:
            return
        from .player import Player
        Player.get().play(self._audio, getattr(self, "_title", "") or Path(self._audio).stem, getattr(self, "_subtitle", ""),
                          self._prev_start, stop_after_s=self._prev_len)

    # ---------------------------------------------------------------- playback
    # Playback goes through the app-wide Player (ui/player.py): one thing plays at a time, shown in the bottom bar.
    def set_track(self, title: str, subtitle: str = ""):
        self._title, self._subtitle = title, subtitle

    def _ensure_player(self) -> bool:
        if self._player is not None:
            return True
        try:
            from .player import Player
            pl = Player.get()
            if not pl._ensure():                 # no audio device: play buttons do nothing rather than crash
                return False
            self._player = pl.media
            self._player.positionChanged.connect(lambda _: self.update() if self._mine() else None)
            self._player.durationChanged.connect(lambda ms: self._got_duration(ms) if self._mine() else None)
            pl.changed.connect(self._state_changed)
            return True
        except Exception:
            self._player = None
            return False

    def _mine(self) -> bool:
        return bool(self._audio) and self._player is not None and self._player.source().toLocalFile() == self._audio

    def _got_duration(self, ms: int):
        if ms > 0:
            self._duration_ms = ms
        self.update()

    def _state_changed(self, *_):
        playing = self.is_playing()
        cb = getattr(self, "on_playing", None)
        if cb:
            cb(playing)
        self.play_btn.set_playing(playing)
        self.play_btn.setToolTip("Pause (space)" if playing else "Play (space)")
        self.update()

    def is_playing(self) -> bool:
        if self._player is None or not self._mine():
            return False
        from PySide6.QtMultimedia import QMediaPlayer
        return self._player.playbackState() == QMediaPlayer.PlayingState

    def toggle(self):
        if not self._audio or not self._ensure_player():
            return
        from .player import Player
        if self._mine():
            Player.get().toggle(); return
        Player.get().play(self._audio, getattr(self, "_title", "") or Path(self._audio).stem, getattr(self, "_subtitle", ""))

    def stop(self):
        if self._player is not None and self._mine():
            from .player import Player
            Player.get().stop()
        self.update()

    def position_ms(self) -> int:
        return self._player.position() if self._player is not None and self._mine() else 0

    def seek_fraction(self, f: float):
        if not self._audio or not self._ensure_player() or self._duration_ms <= 0:
            return
        from .player import Player
        start = max(0.0, min(1.0, f)) * self._duration_ms / 1000
        if self._mine():
            self._player.setPosition(int(start * 1000))
            if not self.is_playing():
                Player.get().toggle()
        else:
            Player.get().play(self._audio, getattr(self, "_title", "") or Path(self._audio).stem, getattr(self, "_subtitle", ""), start)

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
            ly = y - 18 if y - 18 >= r.top() + 2 else y + 4
            p.fillRect(r.right() - 112, ly, 108, 16, QColor(0, 0, 0, 140))
            p.drawText(r.right() - 108, ly + 12, f"cutoff {self._cutoff / 1000:.1f} kHz")
        # preview window + drop marker
        if self._duration_ms > 0 and (self._prev_start is not None or self._drop_s is not None):
            dur = self._duration_ms / 1000
            if self._prev_start is not None:
                x0 = r.left() + int(r.width() * self._prev_start / dur)
                x1 = r.left() + int(r.width() * min(dur, self._prev_start + self._prev_len) / dur)
                p.fillRect(x0, r.top(), max(2, x1 - x0), r.height(), QColor(255, 255, 255, 46))
            if self._drop_s is not None:
                xd = r.left() + int(r.width() * self._drop_s / dur)
                pen = QPen(QColor("#ffffff")); pen.setWidth(2); p.setPen(pen)
                p.drawLine(xd, r.top(), xd, r.bottom())
                tag = f"drop {int(self._drop_s) // 60}:{int(self._drop_s) % 60:02d}"
                lx = xd + 4 if xd + 82 < r.right() else xd - 82            # bottom edge: never under the cutoff label
                p.fillRect(lx, r.bottom() - 21, 78, 17, QColor(0, 0, 0, 150))
                p.setPen(QColor("#ffffff")); p.drawText(lx + 5, r.bottom() - 8, tag)
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
