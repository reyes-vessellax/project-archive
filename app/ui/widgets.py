"""Reusable pieces of the v5 interface. No file or engine work happens here."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QSize, QPropertyAnimation, QRectF, QTimer, QUrl, QObject, QPoint, QRunnable, Qt, Signal
from PySide6.QtGui import QPainterPath, QPen, QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QLayout, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
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
            self._emit_failed(str(e))
        except Exception as e:                                      # keep the app alive, report it
            if _after_shutdown(e):
                return                                              # the app closed under a running task: nothing to report
            import traceback
            _applog("task crashed: " + traceback.format_exc())
            self._emit_failed(f"Unexpected error: {e}")

    def _emit_failed(self, msg: str):
        try:
            self.signals.failed.emit("", msg)
        except RuntimeError:                                        # the window that would show it is gone
            pass


def _after_shutdown(e: Exception) -> bool:
    """A background task outliving the app: the database closed or the receiving widget deleted mid-task."""
    import sqlite3
    msg = str(e)
    return (isinstance(e, sqlite3.ProgrammingError) and "closed database" in msg) or \
        (isinstance(e, RuntimeError) and ("Signal source has been deleted" in msg or "already deleted" in msg))


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


def _same_file(a: str, b: str) -> bool:
    """Two paths to the same file. Not a text compare: on Windows the player reports C:/x/y.wav and we hold
    C:\\x\\y.wav, so a text compare never matched (the play button and playhead didn't follow the track there)."""
    import os
    if not a or not b:
        return False
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


class EmptyState(QLabel):
    """An empty page says so the DigMart way: our emblem above one bold line (DESIGN.md). The emblem follows the
    theme (the dark file has a white outline) each time it's shown."""
    def __init__(self, text: str = ""):
        super().__init__()
        self.setObjectName("emptyState"); self.setAlignment(Qt.AlignCenter); self.setWordWrap(True)
        self.setTextFormat(Qt.RichText)
        self._text = text
        self._render()

    def setText(self, text: str) -> None:                # noqa: N802 (Qt name)
        self._text = text; self._render()

    def text(self) -> str:                               # noqa: N802
        return self._text

    def showEvent(self, e):
        self._render(); super().showEvent(e)

    def _render(self):
        import html as _h
        mark = Path(__file__).parent / "brand_assets" / ("digmart-mark-dark.png" if FX_THEME == "dark" else "digmart-mark.png")
        body = _h.escape(self._text).replace("\n", "<br>")
        super().setText(f"<div align='center'><img src='{mark.as_posix()}' width='96'><br><br>"
                        f"<span style='font-size:16px; font-weight:700'>{body}</span></div>" if self._text else "")


FX_THEME = "light"            # set by the window with the theme: shadows in light, a soft glow in dark
_NO_FX = {"link", "x", "zoom", "play", "menuitem", "tab", "avatar", "pill", "pillbtn", "altrow", "arrow", "barplay"}


class _HoverFx(QObject):
    """Buttons rise on hover (a soft shadow; a faint yellow glow in dark mode, where black doesn't show) and record
    tiles lift a few pixels too. Installed on each button and tile, not app-wide (that would see every event)."""
    def eventFilter(self, w, e):
        t = e.type()
        if t == QEvent.Enter and w.isEnabled():
            from PySide6.QtWidgets import QGraphicsDropShadowEffect
            fx = QGraphicsDropShadowEffect(w)
            dark = FX_THEME == "dark"
            fx.setBlurRadius(22 if w.property("lift") else 16); fx.setOffset(0, 0 if dark else 5)
            fx.setColor(QColor(255, 215, 0, 70) if dark else QColor(0, 0, 0, 80))
            w.setGraphicsEffect(fx)
            if w.property("lift") and w.layout() is not None:
                w.layout().setContentsMargins(0, 0, 0, 9)            # up 3 px, like pulling a record from the crate
        elif t in (QEvent.Leave, QEvent.Hide, QEvent.EnabledChange):
            if w.graphicsEffect() is not None:
                w.setGraphicsEffect(None)
            if w.property("lift") and w.layout() is not None:
                w.layout().setContentsMargins(0, 3, 0, 6)
        return False


_HOVER = None


def hover_fx(w: QWidget, lift: bool = False) -> QWidget:
    global _HOVER
    if _HOVER is None:
        _HOVER = _HoverFx(QApplication.instance())
    if lift:
        w.setProperty("lift", True)
    w.installEventFilter(_HOVER)
    return w


def button(text: str, role: str = "ghost", on_click=None, parent=None) -> QPushButton:
    b = QPushButton(text.replace("&", "&&"), parent)      # a bare & would become a keyboard mnemonic
    b.setObjectName(role)
    b.setCursor(Qt.PointingHandCursor)
    if role not in _NO_FX:
        hover_fx(b)
    if on_click:
        b.clicked.connect(on_click)
    return b


from PySide6.QtWidgets import QStackedWidget as _QStackedWidget


class CurrentStack(_QStackedWidget):
    """A stack that is only as big as the page showing. QStackedWidget asks for the largest page's size, so a
    tall sign-up screen kept the whole window 896 px tall long after sign-up: on a 768 px laptop the bottom
    of every page (Download / Delete) was off the screen."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.currentChanged.connect(lambda _i: self.updateGeometry())

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()

    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()


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
        from PySide6.QtWidgets import QAbstractItemView
        if isinstance(area, QAbstractItemView):              # item views default to jumping a whole row at a time:
            area.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)   # an open drop-down is one "row"
            area.verticalScrollBar().setSingleStep(24)
        area.viewport().installEventFilter(self)
        area.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Wheel and ev.angleDelta().y() != 0 and not ev.pixelDelta().y():
            if ev.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
                return False
            self.nudge(ev.angleDelta().y())
            ev.accept()
            return True
        return False

    def nudge(self, angle_dy: float) -> None:
        """Scroll by a wheel movement (120 = one notch), gliding. Anything that forwards a wheel to this area
        (a row inside the page, say) must come through here: moving the bar directly while a glide is running
        makes the page jump there and back."""
        notches = angle_dy / 120.0
        running = self.anim.state() == QPropertyAnimation.Running and self.target is not None
        base = self.target if running else self.bar.value()
        self.target = int(max(self.bar.minimum(), min(self.bar.maximum(), base - notches * self.PX_PER_NOTCH)))
        distance = abs(self.target - self.bar.value())
        if distance == 0:
            return
        ms = int(max(self.MIN_MS, min(self.MAX_MS, self.MIN_MS + distance * 0.9)))
        self.anim.stop()
        self.anim.setDuration(ms)
        self.anim.setStartValue(self.bar.value()); self.anim.setEndValue(self.target); self.anim.start()


def smooth(area) -> None:
    """Attach SmoothWheel to a scroll area / item view (idempotent)."""
    if not area.property("smoothwheel"):
        area.setProperty("smoothwheel", True)
        area._smoothwheel = SmoothWheel(area)


def keep_scroll(area, rebuild) -> None:
    """Rebuild the contents of a scroll area / view without the scroll position jumping to the top."""
    bar = area.verticalScrollBar()
    value = bar.value()
    rebuild()
    bar.setValue(value)
    QTimer.singleShot(0, lambda: bar.setValue(value))          # again after the layout has settled


class _UpDownScroll(QScrollArea):
    """Scrolls up and down only. The page is pinned to the visible width, so a long title or a row of tiles wraps
    or squeezes instead of making the whole page slide left and right."""
    def resizeEvent(self, e):
        super().resizeEvent(e)
        w = self.widget()
        if w is not None:
            w.setFixedWidth(self.viewport().width())


def scroll(inner: QWidget) -> QScrollArea:
    """A scroll area whose vertical bar never comes and goes. With the bar "as needed", wrapped text that just
    fits flips it on, the text re-wraps narrower and taller, the bar is needed, it isn't... and the page
    flickers (the Ready page did this every few seconds). The bar's lane is always there; the handle only
    shows when there is something to scroll."""
    s = _UpDownScroll()
    s.setWidgetResizable(True)
    s.setFrameShape(QFrame.NoFrame)
    s.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
    s.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)       # never sideways (the user asked)
    bar = s.verticalScrollBar()

    def idle(_lo=0, hi=0):
        on = hi <= 0
        if bar.property("idle") != on:
            bar.setProperty("idle", on)
            bar.style().unpolish(bar); bar.style().polish(bar)
    bar.rangeChanged.connect(idle); idle(0, bar.maximum())
    s.setWidget(inner)
    smooth(s)
    return s


def page(margins=(48, 28, 48, 40), spacing=24, max_width: int = 1600) -> tuple[QWidget, QVBoxLayout]:
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
        self.brand = Brand(); self.brand.clicked.connect(lambda: self.tab_clicked.emit("discover"))
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

    NAV = (("discover", "Discover"), ("search", "Search"), ("queue", "Queue"), ("wishlist", "Wishlist"), ("library", "Library"),
           ("batch", "Batch"))

    def __init__(self):
        super().__init__()
        self.setObjectName("sidebar")
        self._crate_btns: dict = {}
        self.setFixedWidth(232)
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = vbox(self, (14, 20, 14, 16), 2)
        from .brand import Brand
        self.brand = Brand(); self.brand.clicked.connect(lambda: self.tab_clicked.emit("discover"))
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
        self.set_active("discover")

    def set_active(self, key: str) -> None:
        key = "queue" if key == "ready" else key         # reviewing a checked track is part of the Queue tab
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
        # Queue = downloading, checking and waiting for you; the number that needs you comes first
        self.tabs["queue"].setText(f"Queue   ● {ready}" if ready else (f"Queue   {queue}" if queue else "Queue"))
        self.tabs["queue"].setToolTip(f"{ready} checked and waiting for you · {queue} downloading or checking")

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
        self.move(menu_pos(self, anchor))
        self.show()


def menu_pos(menu: QWidget, anchor: QWidget, gap: int = 8) -> QPoint:
    """Where a pop-up menu goes so it's always fully on screen: below the anchor if it fits, else above it (the
    avatar sits at the bottom-left); lined up with the anchor's left edge, else its right; then kept inside the
    screen whatever happens."""
    menu.adjustSize()
    w, h = menu.width(), menu.height()
    top_left = anchor.mapToGlobal(QPoint(0, 0))
    ax, ay, aw, ah = top_left.x(), top_left.y(), anchor.width(), anchor.height()
    scr = anchor.screen() or QApplication.primaryScreen()
    area = scr.availableGeometry() if scr else None
    if area is None:
        return QPoint(ax, ay + ah + gap)
    y = ay + ah + gap
    if y + h > area.bottom():
        y = ay - h - gap                                   # no room below: open upwards
    x = ax
    if x + w > area.right():
        x = ax + aw - w                                    # no room to the right: line up with the right edge
    x = max(area.left() + 4, min(x, area.right() - w - 4))
    y = max(area.top() + 4, min(y, area.bottom() - h - 4))
    return QPoint(x, y)


# ------------------------------------------------------------------ queue row
class QueueRow(QWidget):
    """One line of the queue: word tag, title/artist, progress, meta, and × when finished."""
    clicked = Signal(str)
    removed = Signal(str)

    def __init__(self, job_id: str, tag: str, title: str, artist: str, pct: float | None, meta: str, removable: bool):
        super().__init__()
        self.job_id = job_id
        self.setObjectName("row")
        self.setAttribute(Qt.WA_Hover, True)                 # :hover only fires with this…
        self.setAttribute(Qt.WA_StyledBackground, True)      # …and a plain QWidget only paints a background with this
        self.setProperty("tag", tag)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(48)
        lay = hbox(self, (4, 6, 12, 6), 12)
        lay.setSizeConstraint(QLayout.SetNoConstraint)       # see minimumSizeHint
        # × first, on the left, where the hand already is; a blank spacer keeps rows aligned when it's hidden
        # NOTE: every child is added to the layout BEFORE any setVisible(): a parentless widget that is shown
        # becomes its own top-level window for a frame — the "flashing dialog boxes" of 0.3/0.4.
        self.x = button("×", "x", lambda: self.removed.emit(self.job_id), parent=self)
        self.x.setToolTip("Cancel download" if tag == "Down" else "Remove from the list" if tag in ("Done", "Gone", "Error") else "Delete this track from quarantine")
        self.x.setFixedWidth(22)
        self.x_space = QWidget(self); self.x_space.setFixedWidth(22)
        lay.addWidget(self.x); lay.addWidget(self.x_space)
        self.x.setVisible(removable); self.x_space.setVisible(not removable)
        self.tag = label(tag.upper(), "tag", tag); self.tag.setFixedWidth(64); self.tag.setFixedHeight(20)
        lay.addWidget(self.tag, 0, Qt.AlignVCenter)
        names = vbox(spacing=2)
        self.title = label(title); self.title.setStyleSheet("font-weight: 600; font-size: 14px;")
        self.title.setToolTip(title)
        self.artist = label(artist or " ", "muted")
        for lbl in (self.title, self.artist):                # long names clip instead of pushing the row wider than the list
            lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            lbl.setMinimumWidth(90)                          # never squeezed to nothing in a narrow window
        names.addWidget(self.title); names.addWidget(self.artist)
        lay.addLayout(names, 1)
        self.now = label("♫", "nowplaying"); self.now.setToolTip("Playing now")   # which track the music is
        lay.addWidget(self.now, 0, Qt.AlignVCenter)
        self.now.hide()
        self.bar = QProgressBar(self); self.bar.setTextVisible(False); self.bar.setFixedWidth(150); self.bar.setRange(0, 100)
        self.bar.setValue(int(pct) if pct is not None else 0); self.bar.setProperty("tag", tag)
        lay.addWidget(self.bar)
        # a full bar on a finished track says nothing: hidden, and its room goes to the title
        self.bar.setVisible(pct is not None and pct < 100)
        self.meta = label(meta, "mono"); self.meta.setFixedWidth(150); self.meta.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.meta)
        self.meta.setVisible(bool(meta)); self.meta.setToolTip(meta)   # nothing to say: the title gets the room
        for w in (self.tag, self.title, self.artist, self.meta, self.bar, self.x_space):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)

    FULL = 150                                               # the bar's and the note's width when there is room

    def _fit(self) -> None:
        """Share a narrow row: the title keeps its room, the bar shrinks, and the note goes before anything overlaps."""
        room = self.width() - 250                            # what's left after ×, the tag and a readable title
        note = bool(self.meta.text())
        if note and room >= 2 * self.FULL:
            bar_w, meta_w = self.FULL, self.FULL
        elif note and room >= 170:
            bar_w = 70; meta_w = min(self.FULL, room - bar_w - 12)
        else:
            bar_w, meta_w = max(40, min(self.FULL, room)), 0
        if self.bar.width() != bar_w:
            self.bar.setFixedWidth(bar_w)
        if meta_w and self.meta.width() != meta_w:
            self.meta.setFixedWidth(meta_w)
        if self.meta.isVisibleTo(self) != bool(meta_w):
            self.meta.setVisible(bool(meta_w))

    def minimumSizeHint(self):                               # the row may get narrow: _fit shares what there is
        return QSize(240, 48)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.x.geometry().contains(e.pos()):
            self.clicked.emit(self.job_id)
        super().mousePressEvent(e)

    def set_playing(self, on: bool) -> None:
        if self.now.isVisible() != on:
            self.now.setVisible(on)

    def update_to(self, tag: str, title: str, artist: str, pct: float | None, meta: str, removable: bool) -> None:
        """Change this row in place (a download ticking along) instead of building a new one."""
        if self.property("tag") != tag:
            self.setProperty("tag", tag); T.repolish(self)
            self.tag.setText(tag.upper()); set_tag(self.tag, tag)
            self.bar.setProperty("tag", tag); T.repolish(self.bar)
            self.x.setToolTip("Cancel download" if tag == "Down" else "Remove from the list" if tag in ("Done", "Gone", "Error") else "Delete this track from quarantine")
        if self.title.text() != title:
            self.title.setText(title); self.title.setToolTip(title)
        if self.artist.text() != (artist or " "):
            self.artist.setText(artist or " ")
        self.bar.setValue(int(pct) if pct is not None else 0)
        self.bar.setVisible(pct is not None and pct < 100)
        if self.meta.text() != meta:
            self.meta.setText(meta); self.meta.setToolTip(meta)
        self._fit()
        if self.x.isVisible() != removable:
            self.x.setVisible(removable); self.x_space.setVisible(not removable)

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


from PySide6.QtWidgets import QStyledItemDelegate as _QStyledItemDelegate


class KeepColourDelegate(_QStyledItemDelegate):
    """A selected or opened row keeps its coloured text (the Key in accent, Good in green...). Qt paints selected
    text in one highlight colour, which turned the Key black whenever a Library row dropped down.
    Only paint() is overridden, and only selected coloured cells take the slow path: a Python hook on every
    size calculation made filtering a 2,000-track library lag."""

    keep_colours = True       # off in light mode: the selected row is solid crimson, so every cell reads in white

    def paint(self, painter, option, index):
        from PySide6.QtWidgets import QStyle
        if KeepColourDelegate.keep_colours and option.state & QStyle.State_Selected:
            fg = index.data(Qt.ForegroundRole)
            if fg is not None:
                from PySide6.QtGui import QPalette
                from PySide6.QtWidgets import QStyleOptionViewItem
                opt = QStyleOptionViewItem(option)
                opt.palette.setColor(QPalette.HighlightedText, fg.color() if hasattr(fg, "color") else QColor(fg))
                return super().paint(painter, opt, index)
        return super().paint(painter, option, index)


class StopButton(QPushButton):
    """Round stop control with a drawn square (a "■" glyph sits off-centre and changes size from font to font)."""
    NORMAL, HOVER = "#f2f2f0", "#ffb000"

    def __init__(self, parent=None):
        super().__init__("", parent)
        self.setAttribute(Qt.WA_Hover)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen); p.setBrush(QColor(self.HOVER if self.underMouse() else self.NORMAL))
        w, h = self.width(), self.height(); s = min(w, h) * 0.30
        p.drawRoundedRect(QRectF((w - s) / 2, (h - s) / 2, s, s), 1.5, 1.5)
        p.end()


def level_envelope(path: str, ffmpeg_override: str = "", hop_s: float = 0.02):
    """Left/right loudness of a track every hop_s seconds, 0..1 (-48 dBFS .. 0 dBFS): a blend of peak and RMS,
    which reads like a hardware meter. Decoded at a low rate, so a 6-minute track takes about a second."""
    import numpy as np
    from ..media.tools import find_tool, run
    sr = 8000
    r = run([find_tool("ffmpeg", ffmpeg_override), "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0",
             "-ac", "2", "-ar", str(sr), "-f", "f32le", "-acodec", "pcm_f32le", "-"], 120)
    x = np.frombuffer(r.stdout, dtype="<f4")
    hop = int(sr * hop_s)
    n = (len(x) // 2) // hop
    if n == 0:
        return None
    x = x[: n * hop * 2].reshape(n, hop, 2).astype(np.float32)
    rms = np.sqrt((x ** 2).mean(axis=1)) + 1e-9
    peak = np.abs(x).max(axis=1) + 1e-9
    to01 = lambda v: np.clip((20 * np.log10(v) + 48) / 48, 0, 1)
    env = 0.55 * to01(peak) + 0.45 * to01(rms * 1.414)          # (n, 2)
    return env[:, 0].copy(), env[:, 1].copy(), hop_s


class LevelStrip(QWidget):
    """Left/right LED meter (green -> amber -> red) while a track plays. Fed 60 times a second from the track's own
    loudness: rises instantly, falls smoothly, a peak marker hangs then floats down, and the top segment lights
    partially, so it glides instead of stepping."""
    SEGMENTS = 48
    ATTACK_S, RELEASE_S = 0.010, 0.30
    HOLD_S, PEAK_FALL = 0.8, 0.6              # peak marker: hang, then fall (fraction of the scale per second)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(16)
        import time as _t
        self._clock = _t.monotonic
        self._env = None                       # (left, right, hop_s)
        self._shown = [0.0, 0.0]
        self._peak = [0.0, 0.0]; self._peak_t = [0.0, 0.0]
        self._last = self._clock()

    def set_envelope(self, env) -> None:
        self._env = env

    def feed(self, pos_s: float | None, fallback: float = 0.0) -> None:
        """pos_s: playhead in seconds (None = stopped). Without an envelope yet, `fallback` (0..1) is used."""
        now = self._clock(); dt = max(0.0, min(0.1, now - self._last)); self._last = now
        if pos_s is None:
            targets = [0.0, 0.0]
        elif self._env is not None:
            left, right, hop = self._env
            f = pos_s / hop
            i = int(f)
            if i >= len(left) - 1:
                targets = [float(left[-1]), float(right[-1])]
            else:
                w = f - i                                       # between two readings: interpolate
                targets = [float(left[i] * (1 - w) + left[i + 1] * w), float(right[i] * (1 - w) + right[i + 1] * w)]
        else:
            targets = [fallback, fallback]
        for ch in (0, 1):
            cur, tgt = self._shown[ch], targets[ch]
            tau = self.ATTACK_S if tgt > cur else self.RELEASE_S
            cur += (tgt - cur) * (1 - pow(2.718281828, -dt / tau))
            self._shown[ch] = cur
            if cur >= self._peak[ch]:
                self._peak[ch], self._peak_t[ch] = cur, now
            elif now - self._peak_t[ch] > self.HOLD_S:
                self._peak[ch] = max(cur, self._peak[ch] - self.PEAK_FALL * dt)
        self.update()

    def set_level(self, v: float):                 # older callers: one value for both channels
        self.feed(0.0 if v <= 0 else 1.0, fallback=max(0.0, min(1.0, v))) if self._env is None else None

    def level(self) -> float:
        return max(self._shown)

    @staticmethod
    def _colour(i: int, n: int) -> QColor:
        return QColor("#2fb562") if i < n * 0.6 else QColor("#ffb000") if i < n * 0.82 else QColor("#dc143c")

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        n, gap = self.SEGMENTS, 2
        w = (self.width() - gap * (n - 1)) / n
        off = QColor(T.colours(getattr(self, "_theme", "light"))["bar"])
        p.setPen(Qt.NoPen)
        for ch, y in ((0, 1), (1, 9)):
            lit = self._shown[ch] * n
            pk = min(n - 1, int(self._peak[ch] * n))
            for i in range(n):
                x = i * (w + gap)
                p.setBrush(off); p.drawRoundedRect(QRectF(x, y, w, 6), 1, 1)
                part = max(0.0, min(1.0, lit - i))             # the top segment lights partly
                if part > 0:
                    c = self._colour(i, n); c.setAlphaF(0.35 + 0.65 * part)
                    p.setBrush(c); p.drawRoundedRect(QRectF(x, y, w, 6), 1, 1)
            if self._peak[ch] > 0.02:
                c = self._colour(pk, n); p.setBrush(c)
                p.drawRoundedRect(QRectF(pk * (w + gap), y, w, 6), 1, 1)
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
        # zoom: the part of the track on screen, as fractions 0..1 (Ctrl+scroll / pinch / + − buttons)
        self._v0, self._v1 = 0.0, 1.0
        self._press = None; self._dragged = False
        self.zoom_out_btn = button("−", "zoom", lambda: self.zoom(1 / 1.6), self)
        self.zoom_in_btn = button("+", "zoom", lambda: self.zoom(1.6), self)
        self.zoom_out_btn.setToolTip("Zoom out (Ctrl + scroll)"); self.zoom_in_btn.setToolTip("Zoom in (Ctrl + scroll)")
        for b in (self.zoom_out_btn, self.zoom_in_btn):
            b.setFixedSize(24, 22); b.hide()
        self.setMouseTracking(True)
        self.clear_view("")

    # ---------------------------------------------------------------- content
    def set_accent(self, colour: str) -> None:
        self._accent = colour
        self.update()

    def clear_view(self, text: str):
        self.stop()
        self._pix = None; self._audio = None
        self._v0, self._v1 = 0.0, 1.0
        self.setText(text)
        self.setObjectName("faint")
        self.play_btn.hide()
        self.update()

    def set_cutoff_bad(self, bad: bool) -> None:
        """The spectrum check didn't pass: mark the cutoff red and shade the missing highs."""
        self._cutoff_bad = bad; self.update()

    def show_png(self, path: str, sample_rate: int, cutoff_hz: float | None, audio: str | None = None,
                 duration_s: float | None = None):
        pix = QPixmap(path)
        if pix.isNull():
            self.clear_view("Spectrogram unavailable.")
            return
        self._pix, self._nyq, self._cutoff = pix, (sample_rate or 44100) / 2, cutoff_hz
        self._levels = None                                   # per-column loudness, computed on first use
        self._ensure_player()                                 # follow the shared player (▶ shows ❚❚ if this track plays)
        self._audio = audio if audio and Path(audio).exists() else None
        self._state_changed()                                 # AFTER the new track: ▶ unless THIS track is the one playing
        self._duration_ms = int((duration_s or 0) * 1000)
        self.setText("")
        self.play_btn.setVisible(self._audio is not None)
        self._v0, self._v1 = 0.0, 1.0
        self._place_button()
        self.update()

    # ---------------------------------------------------------------- zoom
    MAX_ZOOM = 16

    def zoomed(self) -> bool:
        return self._v1 - self._v0 < 0.999

    def _frac_at(self, x: float) -> float:
        r = self._image_rect()
        return self._v0 + (x - r.left()) / max(1, r.width()) * (self._v1 - self._v0)

    def _x_of(self, frac: float) -> float:
        r = self._image_rect()
        return r.left() + (frac - self._v0) / (self._v1 - self._v0) * r.width()

    def _set_view(self, v0: float, span: float):
        span = max(1 / self.MAX_ZOOM, min(1.0, span))
        v0 = max(0.0, min(1.0 - span, v0))
        self._v0, self._v1 = v0, v0 + span
        self._place_button(); self.update()

    def zoom(self, factor: float, anchor: float | None = None):
        """Zoom by `factor` (>1 in) keeping `anchor` (a fraction of the track; default: the middle of the view,
        or the playhead while playing) at the same place on screen."""
        if self._pix is None:
            return
        span = self._v1 - self._v0
        if anchor is None:
            pos = self.position_ms()
            anchor = pos / self._duration_ms if self._duration_ms > 0 and self.is_playing() else self._v0 + span / 2
        new = max(1 / self.MAX_ZOOM, min(1.0, span / factor))
        self._set_view(anchor - (anchor - self._v0) * new / span, new)

    def reset_zoom(self):
        self._set_view(0.0, 1.0)

    def wheelEvent(self, e):
        r = self._image_rect()
        if self._pix is None or not r.contains(e.position().toPoint()):
            return super().wheelEvent(e)
        dy, dx = e.angleDelta().y(), e.angleDelta().x()
        if e.modifiers() & (Qt.ControlModifier | Qt.MetaModifier) and dy:
            self.zoom(1.25 ** (dy / 120), self._frac_at(e.position().x())); e.accept(); return
        if self.zoomed() and (dx or e.modifiers() & Qt.ShiftModifier):
            d = dx or dy
            span = self._v1 - self._v0
            self._set_view(self._v0 - d / 120 * span * 0.15, span); e.accept(); return
        e.ignore()                                             # plain scroll still scrolls the page

    def event(self, e):
        if e.type() == QEvent.NativeGesture and self._pix is not None:          # trackpad pinch
            if e.gestureType() == Qt.ZoomNativeGesture:
                self.zoom(1 + e.value(), self._frac_at(e.position().x())); return True
        return super().event(e)

    def mouseDoubleClickEvent(self, e):
        if self._pix is not None and self.zoomed() and self._image_rect().contains(e.pos()):
            self.reset_zoom(); return
        super().mouseDoubleClickEvent(e)

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
            # bound methods, not lambdas: Qt drops these connections when this view is deleted (a lambda kept
            # firing at the dead widget many times a second - thousands of errors in the log)
            self._player.positionChanged.connect(self._on_position)
            self._player.durationChanged.connect(self._on_duration)
            pl.changed.connect(self._state_changed)
            return True
        except Exception:
            self._player = None
            return False

    def _mine(self) -> bool:
        if not self._audio or self._player is None:
            return False
        return _same_file(self._player.source().toLocalFile(), self._audio)

    def _on_position(self, _ms: int):
        if self._mine():
            self.update()

    def _on_duration(self, ms: int):
        if self._mine():
            self._got_duration(ms)

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
        y = self.height() - self.BAR + (self.BAR - 22) // 2 + 3
        self.zoom_in_btn.move(self.width() - 2 - 24, y)
        self.zoom_out_btn.move(self.width() - 2 - 24 - 28, y)
        for b in (self.zoom_in_btn, self.zoom_out_btn):
            b.setVisible(self._pix is not None); b.raise_()
        self.zoom_in_btn.setEnabled(self._v1 - self._v0 > 1 / self.MAX_ZOOM + 1e-6)
        self.zoom_out_btn.setEnabled(self.zoomed())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_button()

    def mousePressEvent(self, e):
        r = self._image_rect()
        if self._pix is not None and r.contains(e.pos()) and r.width() > 0 and e.button() == Qt.LeftButton:
            self._press = (e.pos().x(), self._v0); self._dragged = False
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        r = self._image_rect()
        if self._press is not None:
            x0, v0 = self._press
            if self.zoomed() and abs(e.pos().x() - x0) > 4:          # drag to move along a zoomed-in track
                self._dragged = True
                span = self._v1 - self._v0
                self._set_view(v0 - (e.pos().x() - x0) / max(1, r.width()) * span, span)
                self.setCursor(Qt.ClosedHandCursor)
            return
        if self._pix is not None and r.contains(e.pos()):
            self.setCursor(Qt.OpenHandCursor if self.zoomed() else Qt.PointingHandCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._press is not None:
            dragged, self._press = self._dragged, None
            self.setCursor(Qt.OpenHandCursor if self.zoomed() else Qt.PointingHandCursor)
            if not dragged and self._audio:
                self.seek_fraction(self._frac_at(e.pos().x()))   # a click (not a drag) jumps there
            return
        super().mouseReleaseEvent(e)

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
        dur_ms = self._duration_ms
        pos = self.position_ms()
        if self.zoomed() and dur_ms > 0 and self.is_playing() and self._press is None:
            f = pos / dur_ms                                   # keep the playhead on screen while zoomed in
            span = self._v1 - self._v0
            if f > self._v1 - span * 0.02 or f < self._v0:
                self._v0 = max(0.0, min(1 - span, f - span * 0.1))
                self._v1 = self._v0 + span
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        pw, ph = self._pix.width(), self._pix.height()
        p.drawPixmap(QRectF(r), self._pix, QRectF(self._v0 * pw, 0, (self._v1 - self._v0) * pw, ph))
        faint = self.palette().text().color(); faint.setAlpha(140)
        p.setPen(faint)
        small = QFont(T.MONO); small.setPointSizeF(7.5); p.setFont(small)
        for khz in range(0, int(self._nyq / 1000) + 1, 5):
            y = r.bottom() - int(r.height() * khz * 1000 / self._nyq)
            p.drawText(2, y + 3, f"{khz}k")
        if self._cutoff:
            y = r.bottom() - int(r.height() * self._cutoff / self._nyq)
            bad = getattr(self, "_cutoff_bad", False)
            if bad:                                             # the missing highs, shaded: what a transcode looks like
                p.fillRect(QRectF(r.left(), r.top(), r.width(), max(0, y - r.top())), QColor(220, 20, 60, 70))
            pen = p.pen(); pen.setColor(QColor("#ff3b5c" if bad else self._accent)); pen.setWidth(2); pen.setStyle(Qt.DashLine); p.setPen(pen)
            p.drawLine(r.left(), y, r.right(), y)
            p.setPen(QColor("#ffffff"))
            text = f"cutoff {self._cutoff / 1000:.1f} kHz" + ("  ·  highs missing" if bad else "")
            tw = p.fontMetrics().horizontalAdvance(text) + 12
            ly = y - 18 if y - 18 >= r.top() + 2 else y + 4
            p.fillRect(r.right() - tw - 4, ly, tw, 16, QColor(160, 10, 35, 200) if bad else QColor(0, 0, 0, 140))
            p.drawText(r.right() - tw + 2, ly + 12, text)
        # preview window + drop marker
        p.save(); p.setClipRect(r)
        if self._duration_ms > 0 and (self._prev_start is not None or self._drop_s is not None):
            dur = self._duration_ms / 1000
            if self._prev_start is not None:
                x0 = int(self._x_of(self._prev_start / dur))
                x1 = int(self._x_of(min(dur, self._prev_start + self._prev_len) / dur))
                p.fillRect(x0, r.top(), max(2, x1 - x0), r.height(), QColor(255, 255, 255, 46))
            if self._drop_s is not None:
                xd = int(self._x_of(self._drop_s / dur))
                pen = QPen(QColor("#ffffff")); pen.setWidth(2); p.setPen(pen)
                p.drawLine(xd, r.top(), xd, r.bottom())
                tag = f"preview {int(self._drop_s) // 60}:{int(self._drop_s) % 60:02d}"
                lx = xd + 4 if xd + 100 < r.right() else xd - 100           # bottom edge: never under the cutoff label
                p.fillRect(lx, r.bottom() - 21, 96, 17, QColor(0, 0, 0, 150))
                p.setPen(QColor("#ffffff")); p.drawText(lx + 5, r.bottom() - 8, tag)
        # playhead
        if self._audio and self._duration_ms > 0 and (pos > 0 or self.is_playing()):
            x = int(self._x_of(min(1.0, pos / self._duration_ms)))
            pen = QPen(QColor("#ffffff")); pen.setWidth(2); p.setPen(pen)
            p.drawLine(x, r.top(), x, r.bottom())
            p.setBrush(QColor("#ffffff")); p.setPen(Qt.NoPen)
            p.drawPolygon([QPoint(x - 5, r.top()), QPoint(x + 5, r.top()), QPoint(x, r.top() + 7)])
        p.restore()
        p.setPen(faint)
        base = self.height() - self.BAR // 2 + 7
        time_x = r.left() + (self.play_btn.width() + 10 if self.play_btn.isVisible() else 0)
        if self._audio and self._duration_ms > 0:
            p.drawText(time_x, base, f"{_mmss(pos)} / {_mmss(self._duration_ms)}")
        else:
            p.drawText(time_x, base, "0:00")
        if self.zoomed() and self._duration_ms > 0:
            a, b = self._v0 * self._duration_ms, self._v1 * self._duration_ms
            hint = f"{_mmss(a)} – {_mmss(b)}  ·  ×{1 / (self._v1 - self._v0):.0f}  ·  drag to move, double-click to fit"
        else:
            hint = "Ctrl + scroll to zoom"
        fm = p.fontMetrics()
        p.drawText(r.right() - 60 - fm.horizontalAdvance(hint), base, hint)
        p.end()


def _mmss(ms: int) -> str:
    s = max(0, int(ms // 1000))
    return f"{s // 60}:{s % 60:02d}"


def club_heading(a: dict, theme: str):
    """The CLUB-READY line under a track's checks (None when the track was checked before this existed)."""
    from . import theme as T
    club = (a or {}).get("club")
    if not club or club.get("error"):
        return None
    c = T.colours(theme)
    if club.get("ready"):
        text, colour = "CLUB-READY ✓", c["pass_"]
        note = f"  ·  {club['notes']} note{'s' if club['notes'] != 1 else ''}" if club.get("notes") else ""
    else:
        text, colour, note = "NOT CLUB-READY ✗", c["fail"], ""
    w = label(f"{text}{note}", "clubhead")
    w.setStyleSheet(f"color: {colour};")
    w.setToolTip("Will it load and sound right on a club or festival system? Separate from the verdict above.")
    return w


def club_badges(a: dict, theme: str):
    """CLUB-READY at a glance: CDJ ✓ · MONO ✓ · PEAK -0.3 dBTP · -8.1 LUFS · LOW END ✓ · USB ✓, each coloured by its
    result (green good, amber note, red problem). None for tracks checked before the club check existed."""
    club = (a or {}).get("club") or {}
    if not club or club.get("error"):
        return None
    from . import theme as T
    c = T.colours(theme)
    by_id = {x["id"]: x for x in club.get("checks") or []}
    names = [("club_load", "DECKS"), ("club_mono", "MONO"), ("club_clip", "PEAK"), ("club_loud", "LUFS"),
             ("club_low", "BASS"), ("club_usb", "USB")]
    w = QWidget(); lay = hbox(w, (0, 4, 0, 4), 5)
    head = label("CLUB-READY ✓" if club.get("ready") else "NOT CLUB-READY ✗", "clubhead")
    head.setToolTip("Club-ready: loads on every CDJ, mono-safe, not clipping, sensible loudness, real low end")
    head.setText("CLUB ✓" if club.get("ready") else "CLUB ✗")
    head.setStyleSheet(f"color: {c['pass_'] if club.get('ready') else c['fail']};")
    lay.addWidget(head); lay.addSpacing(2)
    for cid, name in names:
        x = by_id.get(cid)
        if not x:
            continue
        col = {"PASS": c["pass_"], "WARN": c["warn"], "FAIL": c["fail"]}.get(x["status"], c["muted"])
        text = name + " " + {"PASS": "✓", "WARN": "!", "FAIL": "✗"}.get(x["status"], "")
        if cid == "club_clip" and club.get("true_peak") is not None:
            text = f"PEAK {club['true_peak']:+.1f}"
        if cid == "club_loud" and club.get("lufs") is not None:
            text = f"{club['lufs']:.0f} LUFS"
        b = label(text, "clubbadge")
        h = col.lstrip("#")
        rgba = f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}, 0.16)" if len(h) == 6 else "transparent"
        b.setStyleSheet(f"color: {col}; background: {rgba};")
        b.setToolTip(f"{x['title']}: {x['message']}")
        lay.addWidget(b)
    lay.addStretch(1)
    return w
