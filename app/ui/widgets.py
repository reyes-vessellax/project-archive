"""Reusable pieces of the v5 interface. No file or engine work happens here."""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRunnable, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..adapters.base import ConnectorError
from ..config import APP_NAME
from ..core.safety import Rejected
from ..core.service import ActionBlocked
from ..media.tools import ToolMissing
from . import theme as T


# ------------------------------------------------------------------ worker plumbing
class Signals(QObject):
    progress = Signal(str, str)          # job_id, step
    done = Signal(str)                   # job_id (or "" = just refresh)
    failed = Signal(str, str)            # job_id or "", message
    results = Signal(object)             # SearchResult
    status = Signal(object)              # ConnectorStatus
    staged = Signal(str)                 # job_id that finished downloading and needs analysis


class Task(QRunnable):
    def __init__(self, fn, signals: Signals):
        super().__init__()
        self.fn, self.signals = fn, signals

    def run(self):
        try:
            self.fn()
        except (Rejected, ActionBlocked, ToolMissing, ConnectorError) as e:
            self.signals.failed.emit("", str(e))
        except Exception as e:                                      # keep the app alive, report it
            import traceback
            traceback.print_exc()
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
    tab_clicked = Signal(str)           # "queue" | "ready" | "library"
    avatar_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("topbar")
        lay = hbox(self, (48, 22, 48, 0), 22)
        self.brand = button(APP_NAME, "brand", lambda: self.tab_clicked.emit("queue"))
        lay.addWidget(self.brand)
        self.tabs: dict[str, QPushButton] = {}
        for key, text in (("queue", "Queue"), ("ready", "Ready"), ("library", "Library")):
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
                          (None, None), ("help", "Help & FAQ"), ("whatsnew", "What's new"), (None, None), ("signout", "Sign out")):
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
        lay = hbox(self, (8, 10, 8, 10), 16)
        self.tag = label(tag.upper(), "tag", tag); self.tag.setFixedWidth(64)
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
        self.x = button("×", "x", lambda: self.removed.emit(self.job_id)); self.x.setToolTip("Remove from the list")
        self.x.setVisible(removable)
        lay.addWidget(self.x)
        for w in (self.tag, self.title, self.artist, self.meta, self.bar):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.job_id)
        super().mouseReleaseEvent(e)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", "true" if on else "false")
        T.repolish(self)


# ------------------------------------------------------------------ spectrogram
class SpectrumView(QLabel):
    """The PNG from the analysis with a kHz axis and the cutoff line, drawn in the theme's accent."""
    AXIS = 44

    def __init__(self, min_height: int = 180):
        super().__init__()
        self.setMinimumHeight(min_height)
        self.setAlignment(Qt.AlignCenter)
        self._pix: QPixmap | None = None
        self._nyq = 22050
        self._cutoff = None
        self._accent = "#d2721e"
        self.clear_view("")

    def set_accent(self, colour: str) -> None:
        self._accent = colour
        self.update()

    def clear_view(self, text: str):
        self._pix = None
        self.setText(text)
        self.setObjectName("faint")
        self.update()

    def show_png(self, path: str, sample_rate: int, cutoff_hz: float | None):
        pix = QPixmap(path)
        if pix.isNull():
            self.clear_view("Spectrogram unavailable.")
            return
        self._pix, self._nyq, self._cutoff = pix, (sample_rate or 44100) / 2, cutoff_hz
        self.setText("")
        self.update()

    def paintEvent(self, e):
        if self._pix is None:
            return super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(self.AXIS, 2, -2, -16)
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
        p.setPen(faint)
        p.drawText(r.left(), self.height() - 3, "0:00")
        p.drawText(r.right() - 36, self.height() - 3, "time →")
        p.end()
