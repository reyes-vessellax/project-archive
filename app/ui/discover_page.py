"""Discover: the home page. Dig for classic and underground house, starting from what you own.

Views (one stack, a Back link between them):
- home:   search, what's waiting, Era crates, your labels, artists you play, mixes with your new tracks
- era:    a hand-picked crate (core/eras.py): its labels and artists
- entity: a label or artist from Discogs: profile, related names, the whole catalogue by year with what you
          own ticked; Search for it / Watch it / open the artist or label

Every network lookup runs off the UI thread; a late answer for a view the user already left is dropped.
"""
from __future__ import annotations

import itertools
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QLabel, QHeaderView, QLayout, QLineEdit, QSizePolicy, QStackedWidget, QTreeWidget,
                               QTreeWidgetItem, QWidget)

from ..core.discover import Discover, Entity, Page, Release
from ..core.eras import ERAS, era as find_era
from . import theme as T
from .widgets import KeepColourDelegate, button, hbox, label, page, scroll, smooth, vbox


# ------------------------------------------------------------------------------------------ building blocks
class FlowLayout(QLayout):
    """Left-to-right, wrapping: chips and tiles that reflow with the window."""

    def __init__(self, parent=None, spacing: int = 8, cell: int = 0):
        """cell > 0: a grid that fills the row. As many columns of at least `cell` px as fit, each stretched so
        the row ends flush with the page (no ragged gap on the right)."""
        super().__init__(parent)
        self._items, self._sp, self._cell = [], spacing, cell
        self._drawer = None            # (QWidgetItem, anchor widget): shown full width right under the anchor's row
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items) + (1 if self._drawer else 0)

    def itemAt(self, i):
        if 0 <= i < len(self._items):
            return self._items[i]
        return self._drawer[0] if self._drawer and i == len(self._items) else None

    def takeAt(self, i):
        if 0 <= i < len(self._items):
            return self._items.pop(i)
        if self._drawer and i == len(self._items):
            item, self._drawer = self._drawer[0], None
            return item
        return None

    def open_drawer(self, widget, anchor):
        """Show `widget` full width directly under the row holding `anchor` (moves it if it was open elsewhere)."""
        from PySide6.QtWidgets import QWidgetItem
        self._drawer = None
        self.addChildWidget(widget)
        self._drawer = (QWidgetItem(widget), anchor)
        widget.show()
        self.invalidate()

    def close_drawer(self):
        if self._drawer:
            w = self._drawer[0].widget()
            self._drawer = None
            if w is not None:
                w.hide()
            self.invalidate()

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._lay(QRect(0, 0, w, 0), True)

    def setGeometry(self, r):
        super().setGeometry(r); self._lay(r, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def clear(self):
        self.close_drawer()
        while self._items:
            w = self._items.pop().widget()
            if w is not None:
                w.setParent(None); w.deleteLater()

    def _lay(self, r: QRect, test: bool) -> int:
        if self._cell:
            return self._grid(r, test)
        x, y, line = r.x(), r.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            if x + hint.width() > r.right() + 1 and line > 0:
                x, y, line = r.x(), y + line + self._sp, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._sp
            line = max(line, hint.height())
        return y + line - r.y()


    def _grid(self, r: QRect, test: bool) -> int:
        if not self._items:
            return 0
        cols = max(1, (r.width() + self._sp) // (self._cell + self._sp))
        cw = (r.width() - self._sp * (cols - 1)) // cols
        y = r.y()
        drawer, anchor = (self._drawer or (None, None))
        for start in range(0, len(self._items), cols):
            row = self._items[start:start + cols]
            h = 0
            for it in row:
                w = it.widget()
                hh = w.heightForWidth(cw) if (w is not None and w.hasHeightForWidth()) else -1
                h = max(h, hh if hh > 0 else it.sizeHint().height(), it.minimumSize().height())
            if not test:
                for i, it in enumerate(row):
                    it.setGeometry(QRect(r.x() + i * (cw + self._sp), y, cw, h))
            y += h + self._sp
            if drawer is not None and any(it.widget() is anchor for it in row):
                w = drawer.widget()
                dh = max(w.sizeHint().height(), w.minimumSizeHint().height())
                if not test:
                    drawer.setGeometry(QRect(r.x(), y, r.width(), dh))
                y += dh + self._sp
        return y - self._sp - r.y()


class Tile(QFrame):
    """A clickable card: a bold name, a mono line, an optional muted note."""
    clicked = Signal()

    def __init__(self, title: str, meta: str = "", note: str = "", width: int = 0, tall: bool = False):
        super().__init__()
        self.setObjectName("tile"); self.setAttribute(Qt.WA_Hover); self.setCursor(Qt.PointingHandCursor)
        if width:
            self.setFixedWidth(width)
        lay = vbox(self, (16, 14, 16, 14), 4)
        t = label(title, "tiletitle"); t.setWordWrap(True); lay.addWidget(t)
        if meta:
            lay.addWidget(label(meta, "tilemeta"))
        if note:
            n = label(note, "muted", wrap=True); lay.addWidget(n)
        lay.addStretch(1)
        if tall:
            self.setMinimumHeight(132)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


# Sleeve colours for records without art: the brand's black, crimson, yellow and cream, picked by label name
_SLEEVES = [("#141414", "#ffd700", "#8a857a"), ("#dc143c", "#ffffff", "#ffd1d9"), ("#ffd700", "#141414", "#6b5a00"),
            ("#efe9dc", "#141414", "#8a857a"), ("#2a2a2a", "#ffffff", "#9a9a9a"), ("#a50f2d", "#ffd700", "#f3b7c2")]


class CoverArt(QWidget):
    """A square record cover that fills its column. Without art it's a typographic sleeve (label, title, cat #) in
    brand colours, the way a white-label or company sleeve looks, instead of the same grey disc everywhere.
    It can also show a play overlay on hover and an animated level while its track plays."""

    def __init__(self):
        super().__init__()
        self._pm = None
        self._sleeve = None                     # (label, title, catno)
        self._hover_play = False                # show ▶ on hover (tiles)
        self._playing = False
        self._phase = 0.0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setAttribute(Qt.WA_Hover)

    def set_sleeve(self, label_: str, title: str, catno: str = ""):
        self._sleeve = (label_ or "", title or "", catno or ""); self.update()

    def set_playing(self, on: bool):
        from PySide6.QtCore import QTimer
        self._playing = on
        if on and not hasattr(self, "_eq"):
            self._eq = QTimer(self, interval=60, timeout=self._eq_step)
        if hasattr(self, "_eq"):
            self._eq.start() if on else self._eq.stop()
        self.update()

    def _eq_step(self):
        self._phase += 0.35; self.update()

    def event(self, e):
        from PySide6.QtCore import QEvent
        if e.type() in (QEvent.HoverEnter, QEvent.HoverLeave):
            self.update()
        return super().event(e)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return w

    def sizeHint(self):
        return QSize(150, 150)

    def set_pixmap(self, pm):
        self._pm = pm; self.update()

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.SmoothPixmapTransform)
        side = min(self.width(), self.height())
        r = QRect(0, 0, self.width(), side)
        if self._pm is not None and not self._pm.isNull():
            pm = self._pm.scaled(r.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(r, pm, QRect((pm.width() - r.width()) // 2, (pm.height() - r.height()) // 2, r.width(), r.height()))
        elif self._sleeve:
            self._paint_sleeve(p, r)
        else:
            p.fillRect(r, QColor(128, 128, 128, 40))
        p.setRenderHint(QPainter.Antialiasing)
        if self._playing:                                         # animated level bars over the cover
            import math
            p.fillRect(r, QColor(0, 0, 0, 110))
            bw, gap = max(4, side // 18), max(3, side // 30)
            x0 = r.center().x() - (3 * bw + 2 * gap) // 2
            for i in range(3):
                h = side * (0.18 + 0.22 * (0.5 + 0.5 * math.sin(self._phase * (1.3 + i * 0.4) + i * 1.7)))
                p.setPen(Qt.NoPen); p.setBrush(QColor("#ffd700"))
                p.drawRoundedRect(QRect(int(x0 + i * (bw + gap)), int(r.center().y() + side * 0.2 - h), bw, int(h)), 2, 2)
        elif self._hover_play and self.underMouse():               # ▶ to play the drop
            p.fillRect(r, QColor(0, 0, 0, 70))
            d = max(34, side // 3)
            c = r.center()
            p.setPen(Qt.NoPen); p.setBrush(QColor(220, 20, 60))
            p.drawEllipse(c, d // 2, d // 2)
            from PySide6.QtGui import QPolygonF
            from PySide6.QtCore import QPointF
            t = d * 0.18
            p.setBrush(QColor("#ffffff"))
            p.drawPolygon(QPolygonF([QPointF(c.x() - t * 0.8, c.y() - t * 1.2), QPointF(c.x() - t * 0.8, c.y() + t * 1.2),
                                     QPointF(c.x() + t * 1.3, c.y())]))
        p.end()

    def _paint_sleeve(self, p, r):
        import zlib
        from PySide6.QtGui import QFont
        lab, title, cat = self._sleeve
        bg, fg, sub = _SLEEVES[zlib.crc32(f"{lab}|{cat or title}".lower().encode()) % len(_SLEEVES)]
        p.fillRect(r, QColor(bg))
        p.setRenderHint(QPainter.Antialiasing)
        side = r.height()
        c = r.center()
        p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 40))                     # the centre hole of a company sleeve
        p.drawEllipse(c, int(side * 0.19), int(side * 0.19))
        pad = int(side * 0.08)
        f = QFont("Poppins"); f.setBold(True); f.setPixelSize(max(10, int(side * 0.115)))
        p.setFont(f); p.setPen(QColor(fg))
        p.drawText(QRect(r.left() + pad, r.top() + pad, r.width() - 2 * pad, int(side * 0.36)),
                   int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap), (lab or "").upper()[:40])
        f2 = QFont("Open Sans"); f2.setPixelSize(max(9, int(side * 0.075)))
        p.setFont(f2)
        tr = QRect(r.left() + pad, int(r.bottom() - pad - side * 0.22), r.width() - 2 * pad, int(side * 0.22))
        p.drawText(tr, int(Qt.AlignLeft | Qt.AlignBottom | Qt.TextWordWrap),
                   p.fontMetrics().elidedText(title, Qt.ElideRight, (r.width() - 2 * pad) * 2))
        if cat:
            f3 = QFont("IBM Plex Mono"); f3.setPixelSize(max(8, int(side * 0.065))); p.setFont(f3); p.setPen(QColor(sub))
            p.drawText(QRect(r.left() + pad, r.top() + int(side * 0.42), r.width() - 2 * pad, int(side * 0.1)),
                       int(Qt.AlignLeft), cat)


class CoverCard(QFrame):
    def set_open(self, on: bool):
        self.setProperty("open", on); self.style().unpolish(self); self.style().polish(self)

    """One record: cover, title, artist, year and cat #. Click = search for it."""
    clicked = Signal()

    def __init__(self, r: Release):
        super().__init__()
        self.setObjectName("cover"); self.setAttribute(Qt.WA_Hover); self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{r.artist} – {r.title}\n{r.year or ''}  {r.catno or ''}\nClick to search for it")
        lay = vbox(self, (0, 0, 0, 8), 4)
        self.art = CoverArt(); lay.addWidget(self.art)
        t = label(r.title, "covertitle"); t.setWordWrap(False); lay.addWidget(t)
        a = label(r.artist, "muted"); lay.addWidget(a)
        lay.addWidget(label("  ·  ".join(str(x) for x in (r.year, r.catno) if x and str(x).lower() != "none"), "tilemeta"))
        for w in (t, a):
            w.setMinimumWidth(10)

    def set_image(self, data: bytes):
        pm = QPixmap()
        if pm.loadFromData(data):
            self.art.set_pixmap(pm)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class RecordCard(QFrame):
    """A record someone is sharing right now: cover, details, the copy we found, and what you can do with it.
    Play the drop previews ~20 s of that copy (nothing kept); Check this file downloads it into quarantine."""
    play = Signal(object)              # Candidate
    stop = Signal()
    check = Signal(object)             # Candidate
    watch = Signal(str, str)           # artist, title
    open_label = Signal(str)

    def __init__(self, tag: str, extra=None):
        super().__init__()
        self.setObjectName("spin")
        self.found = None
        self._previewing = False
        self._img_token = None
        sb = hbox(self, (20, 20, 24, 20), 24)
        self.art = CoverArt(); self.art.setFixedWidth(220); self.art.setMinimumHeight(220)
        sb.addWidget(self.art, 0, Qt.AlignTop)
        info = vbox(spacing=6)
        info.addWidget(label(tag, "tilemeta"))
        self.title = label("", "spintitle"); self.title.setWordWrap(True)
        self.artist = label("", "spinartist")
        self.meta = label("", "tilemeta"); self.meta.setWordWrap(True)
        self.copy = label("", "copyline"); self.copy.setWordWrap(True)
        self.status = label("", "muted", wrap=True)
        for w in (self.title, self.artist, self.meta, self.copy, self.status):
            info.addWidget(w)
        info.addStretch(1)
        acts = hbox(spacing=10)
        self.b_play = button("▶  Play the drop", "accent", self._play)
        self.b_play.setToolTip("About 20 seconds from the drop, straight from the person sharing it. Nothing is kept.")
        self.b_check = button("Check this file", "primary", lambda: self.found and self.check.emit(self.found.best))
        self.b_check.setToolTip("Download this copy into quarantine and check it. Nothing reaches your library until you say so.")
        self.b_watch = button("Watch it", "ghost", lambda: self.found and self.watch.emit(self.found.release.artist, self.found.track))
        self.b_label = button("Open the label", "ghost", lambda: self.found and self.open_label.emit(self.found.label))
        for b in (self.b_play, self.b_check, self.b_watch, self.b_label):
            acts.addWidget(b); b.setEnabled(False)
        acts.addStretch(1)
        if extra is not None:
            acts.addWidget(extra)
        info.addLayout(acts)
        sb.addLayout(info, 1)

    def show_found(self, f):
        self.found = f
        r, det = f.release, f.details
        other = f.track.lower() != r.title.lower()
        self.title.setText(f.track if other else r.title)
        self.artist.setText(r.artist + (f"   ·   from “{r.title}”" if other else ""))
        styles = ", ".join(det.get("styles") or [])
        self.meta.setText("  ·  ".join(str(x) for x in (f.label, r.year, r.catno if r.catno and r.catno.lower() != "none" else "",
                                                        styles) if x))
        c = f.best
        fmt = (c.extension or "").upper() + (f" {c.bitrate_kbps}" if c.bitrate_kbps and (c.extension or "").lower() == "mp3" else "")
        more = f"  ·  {len(f.alts) - 1} more ready" if len(f.alts) > 1 else ""
        self.copy.setText(f"READY NOW  ·  {fmt}  ·  {c.size / 1e6:.0f} MB  ·  shared by {c.user}{more}")
        self.status.setText("Plays on decks as listed. Check this file confirms the real quality and club-ready.")
        for b in (self.b_play, self.b_check, self.b_watch, self.b_label):
            b.setEnabled(True)
        self.set_preview_state("", "Plays on decks as listed. Check this file confirms the real quality and club-ready.")
        self.art.set_pixmap(None)

    def update_meta(self, f):
        """Details that arrived after the card was shown (style, catalogue number)."""
        if self.found is not f:
            return
        r, det = f.release, f.details
        styles = ", ".join(det.get("styles") or [])
        self.meta.setText("  ·  ".join(str(x) for x in (f.label, r.year, r.catno if r.catno and r.catno.lower() != "none" else "",
                                                        styles) if x))

    def message(self, text: str):
        self.found = None
        self.title.setText(text); self.artist.setText(""); self.meta.setText(""); self.copy.setText(""); self.status.setText("")
        for b in (self.b_play, self.b_check, self.b_watch, self.b_label):
            b.setEnabled(False)
        self.art.set_pixmap(None)

    def _play(self):
        if self._previewing:
            self.stop.emit()
        elif self.found:
            self.play.emit(self.found.best)

    def set_preview_state(self, state: str, msg: str = ""):
        self._previewing = state in ("loading", "playing")
        self.b_play.setText("■  Stop" if self._previewing else "▶  Play the drop")
        self.status.setText(msg)


class ElideLabel(QLabel):
    """One line that ends in "…" when it doesn't fit, measured with the font it's actually drawn in."""

    def __init__(self, text: str, role: str = ""):
        super().__init__()
        self._full = text
        if role:
            self.setObjectName(role)
        self.setMinimumWidth(10)

    def paintEvent(self, e):
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        p.setFont(self.font()); p.setPen(self.palette().color(self.foregroundRole()))
        r = self.contentsRect()
        p.drawText(r, int(self.alignment() | Qt.AlignVCenter), self.fontMetrics().elidedText(self._full, Qt.ElideRight, r.width()))
        p.end()

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(min(fm.horizontalAdvance(self._full), 2000), fm.height() + 2)


class TrackTile(QFrame):
    """One track in a crate row: cover, title, artist, format. Tap: its card opens under the row."""
    clicked = Signal(object)

    def __init__(self, t, label_name: str = ""):
        super().__init__()
        self.track = t
        self._label_name = label_name
        self.setObjectName("cover"); self.setCursor(Qt.PointingHandCursor); self.setFixedWidth(158)
        lay = vbox(self, (0, 0, 0, 6), 2)
        self.art = CoverArt(); self.art.setFixedSize(158, 158); lay.addWidget(self.art)
        self.art._hover_play = True
        self.art.set_sleeve(getattr(self, "_label_name", "") or t.folder.split(" - ")[0][:30], t.title, t.catno)
        lay.addSpacing(6)
        tip = f"{t.artist} – {t.title}" + (f" ({t.mix})" if t.mix else "")
        for text, role in ((t.title, "covertitle"), (t.artist, "muted")):
            lb = ElideLabel(text, role); lb.setToolTip(tip)                       # "…" instead of a cut-off word
            lay.addWidget(lb)
        ext = (t.best.extension or "").upper()
        lay.addWidget(label(ext + (f" {t.best.bitrate_kbps}" if ext == "MP3" and t.best.bitrate_kbps else ""), "fmtbadge"))

    def set_image(self, data: bytes):
        pm = QPixmap()
        if pm.loadFromData(data):
            self.art.set_pixmap(pm)

    def set_open(self, on: bool):
        self.setProperty("open", on); self.style().unpolish(self); self.style().polish(self)

    play_clicked = Signal(object)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            pos = e.position().toPoint()
            if self.art.geometry().contains(pos):
                self.play_clicked.emit(self)          # the cover: open it AND play the drop
            else:
                self.clicked.emit(self)
        super().mouseReleaseEvent(e)


class CrateRow(QWidget):
    """A label's crate: a header, a sideways strip of tracks shared right now, and room for the open card."""
    tapped = Signal(object, object)    # row, tile
    play_tapped = Signal(object, object)
    see_all = Signal(str)

    def __init__(self, name: str, tag: str = ""):
        super().__init__()
        self.name = name
        lay = vbox(self, (0, 0, 0, 0), 8)
        head = hbox(spacing=12)
        if tag:
            head.addWidget(label(tag, "tilemeta"), 0, Qt.AlignBottom)
        head.addWidget(label(name, "rowtitle"))
        self.count = label("", "faint"); head.addWidget(self.count, 0, Qt.AlignBottom)
        head.addStretch(1)
        self.more = button("See everything  →", "link", lambda: self.see_all.emit(self.name))
        head.addWidget(self.more, 0, Qt.AlignBottom)
        self.b_left = button("‹", "arrow", lambda: self._page(-1)); self.b_right = button("›", "arrow", lambda: self._page(1))
        head.addWidget(self.b_left, 0, Qt.AlignBottom); head.addWidget(self.b_right, 0, Qt.AlignBottom)
        lay.addLayout(head)
        from PySide6.QtWidgets import QScrollArea
        self.strip_host = QWidget(); self.strip_host.setObjectName("page")
        self.strip = hbox(self.strip_host, (0, 0, 0, 0), 14); self.strip.addStretch(1)
        self.area = QScrollArea(); self.area.setWidget(self.strip_host); self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.NoFrame); self.area.setFixedHeight(236)
        self.area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)     # the ‹ › buttons and trackpad swipes move it
        self.area.viewport().installEventFilter(self)
        self.area.horizontalScrollBar().valueChanged.connect(lambda _v: self._arrows())
        self.area.horizontalScrollBar().rangeChanged.connect(lambda *_: self._arrows())
        lay.addWidget(self.area)
        self.note = label("", "faint"); lay.addWidget(self.note); self.note.hide()
        self._skeleton()
        self.drawer_slot = vbox(spacing=0); lay.addLayout(self.drawer_slot)
        self.tiles: list[TrackTile] = []

    def _skeleton(self):
        """Grey placeholder tiles while the row loads (the row looks like itself straight away)."""
        self._ghosts = []
        for _ in range(8):
            g = QFrame(); g.setObjectName("ghost"); g.setFixedSize(158, 222)
            self.strip.insertWidget(self.strip.count() - 1, g); self._ghosts.append(g)
        self._arrows()

    def _page(self, direction: int):
        bar = self.area.horizontalScrollBar()
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        anim = QPropertyAnimation(bar, b"value", self)
        anim.setDuration(260); anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(bar.value())
        anim.setEndValue(max(0, min(bar.maximum(), bar.value() + direction * max(172, self.area.viewport().width() - 172))))
        anim.start(); self._anim = anim

    def _arrows(self):
        bar = self.area.horizontalScrollBar()
        self.b_left.setEnabled(bar.value() > 0); self.b_right.setEnabled(bar.value() < bar.maximum())
        self.b_left.setVisible(bar.maximum() > 0); self.b_right.setVisible(bar.maximum() > 0)

    def eventFilter(self, obj, ev):
        """An up/down wheel over a row scrolls the PAGE (it used to scroll the row sideways). Sideways swipes
        still move the row."""
        from PySide6.QtCore import QEvent
        if ev.type() == QEvent.Wheel:
            d = ev.angleDelta()
            if abs(d.x()) > abs(d.y()):
                bar = self.area.horizontalScrollBar(); bar.setValue(bar.value() - d.x())
                return True
            page = self.parent()
            while page is not None and not hasattr(page, "verticalScrollBar"):
                page = page.parent()
            if page is not None:
                vb = page.verticalScrollBar(); vb.setValue(vb.value() - d.y())
            return True
        return False

    def fill(self, tracks):
        for g in getattr(self, "_ghosts", []):
            g.setParent(None); g.deleteLater()
        self._ghosts = []
        for t in self.tiles:
            t.setParent(None); t.deleteLater()
        self.tiles = []
        for tr in tracks:
            tile = TrackTile(tr, self.name); tile.clicked.connect(lambda tl: self.tapped.emit(self, tl))
            tile.play_clicked.connect(lambda tl: self.play_tapped.emit(self, tl))
            self.strip.insertWidget(self.strip.count() - 1, tile); self.tiles.append(tile)
        self.count.setText(f"{len(tracks)} ready now" if tracks else "")
        self.note.setVisible(not tracks)
        self.area.setVisible(bool(tracks))
        if not tracks:
            self.note.setText("Nobody's sharing this in good quality right now. Tomorrow brings different labels.")
        self.area.horizontalScrollBar().setValue(0)
        self._arrows()

    def offline(self):
        for g in getattr(self, "_ghosts", []):
            g.setParent(None); g.deleteLater()
        self._ghosts = []
        self.note.setText("Connect to the network to see what people are sharing."); self.note.show(); self.area.hide()
        self._arrows()


class SpinBar(QFrame):
    """Dig the crate: one random track from today's rows, its preview already loaded. Dig again shows the next and
    plays it straight away, like flicking through a crate."""
    play = Signal(object)
    stop = Signal()
    check = Signal(object)
    spin = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("spinbar")
        self.found = None
        self._previewing = False
        self._img_token = None
        outer = vbox(self, (18, 14, 18, 14), 10)
        head = hbox(spacing=12)
        head.addWidget(label("Dig the crate", "rowtitle"))
        head.addWidget(label("A random track from today's labels and styles, ready to hear. Not your thing? Dig again.",
                             "faint"), 1, Qt.AlignBottom)
        outer.addLayout(head)
        lay = hbox(spacing=16)
        self.art = CoverArt(); self.art.setFixedSize(76, 76); lay.addWidget(self.art)
        txt = vbox(spacing=2)
        self.where = label("", "tilemeta")
        self.title = label("Finding you a track…", "spinbartitle")
        self.sub = label("", "muted")
        txt.addWidget(self.where); txt.addWidget(self.title); txt.addWidget(self.sub)
        lay.addLayout(txt, 1)
        self.b_play = button("▶  Play", "ghost", self._play)
        self.b_spin = button("Dig again", "accent", self.spin.emit)
        self.b_spin.setToolTip("The next random track: it starts playing straight away")
        self.b_check = button("Check this file", "primary", lambda: self.found and self.check.emit(self.found.best))
        self.b_check.setToolTip("Download this copy, check its quality and club-readiness, and put it in your Queue")
        for b in (self.b_play, self.b_spin, self.b_check):
            lay.addWidget(b)
        outer.addLayout(lay)
        self.b_play.setEnabled(False); self.b_check.setEnabled(False)
        self.status = None

    def show_found(self, f):
        self.found = f
        self.title.setText(f.track)
        c = f.best
        ext = (c.extension or "").upper() + (f" {c.bitrate_kbps}" if c.bitrate_kbps and (c.extension or "").lower() == "mp3" else "")
        self.sub.setText(f"{f.release.artist}")
        bpm, cam = f.details.get("bpm"), f.details.get("camelot")
        self.where.setText("  ·  ".join(x for x in (f.label, f.release.catno, ext, f"≈ {bpm} BPM" if bpm else "",
                                                     cam or "", "ready now") if x))
        self.b_play.setEnabled(True); self.b_check.setEnabled(True); self.b_check.setText("Check this file")
        self.set_preview_state("")
        self.art.set_pixmap(None)

    def _play(self):
        if self._previewing:
            self.stop.emit()
        elif self.found:
            self.play.emit(self.found.best)

    def set_preview_state(self, state: str, msg: str = ""):
        self._previewing = state in ("loading", "playing")
        self.b_play.setText("■  Stop" if self._previewing else "▶  Play")
        if msg:
            self.sub.setText(msg)
        elif self.found:
            self.sub.setText(self.found.release.artist)


def chip(text: str, on_click) -> "QWidget":
    b = button(text, "chip", on_click)
    b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return b


class _Bridge(QObject):
    done = Signal(int, object)          # token, result (or an Exception)
    found = Signal(int, object)         # dig token, Found
    thumb = Signal(int, int, object)    # token, release id, image bytes


class _Job(QRunnable):
    def __init__(self, fn, token: int, bridge: _Bridge):
        super().__init__(); self.fn, self.token, self.bridge = fn, token, bridge

    def run(self):
        try:
            res = self.fn()
        except Exception as e:                                   # shown as a friendly line, never a crash
            res = e
        try:
            self.bridge.done.emit(self.token, res)
        except RuntimeError:
            pass                                                  # page gone (app closing)


# ------------------------------------------------------------------------------------------ the page
class DiscoverPage(QWidget):
    find = Signal(str)                 # search for this inside Discover (its own finder; Back returns here)
    preview = Signal(object)           # Candidate: play the drop (the window runs it, like on Search)
    stop_preview = Signal()
    pick = Signal(object)              # Candidate: Check this file
    watch = Signal(str, str, str)      # artist, title, mix
    go = Signal(str)                   # sidebar key: "queue", "wishlist", "library"

    def __init__(self, svc, engine: Discover | None = None):
        super().__init__()
        self.svc = svc
        self.engine = engine or Discover(svc.db)
        self.pool = QThreadPool(self); self.pool.setMaxThreadCount(1)     # one polite queue of lookups
        self.thumbs = QThreadPool(self); self.thumbs.setMaxThreadCount(2)
        self.vpool = QThreadPool(self); self.vpool.setMaxThreadCount(1)     # "who's sharing it" checks, one at a time
        self.auxpool = QThreadPool(self); self.auxpool.setMaxThreadCount(2)  # covers from Deezer, loading spins
        self.bridge = _Bridge(); self.bridge.done.connect(self._done); self.bridge.thumb.connect(self._thumb)
        self._tokens = itertools.count(1)
        self._want: dict[int, callable] = {}
        self._history: list[tuple] = []
        self._view_token = 0
        root = vbox(self)
        self.stack = QStackedWidget(); root.addWidget(self.stack)
        self._build_home()
        self._build_era()
        self._build_entity()
        self._build_find()
        self.stack.setCurrentWidget(self.home_view)

    # ---- plumbing ---------------------------------------------------------------------------
    def _run(self, fn, then) -> int:
        tok = next(self._tokens)
        self._want[tok] = then
        self.pool.start(_Job(fn, tok, self.bridge))
        return tok

    def _run_aux(self, fn, then) -> int:
        tok = next(self._tokens)
        self._want[tok] = then
        self.auxpool.start(_Job(fn, tok, self.bridge))
        return tok

    def _run_bg(self, fn, then) -> int:
        """Long work (network searches) on its own queue, so label and artist lookups never wait behind it."""
        tok = next(self._tokens)
        self._want[tok] = then
        self.vpool.start(_Job(fn, tok, self.bridge))
        return tok

    def _done(self, tok: int, res):
        then = self._want.pop(tok, None)
        if then is not None:
            then(res)

    def _theme(self) -> str:
        return getattr(self.svc.settings, "theme", "light")

    # ---- home ------------------------------------------------------------------------------
    def _build_home(self):
        outer, lay = page(spacing=22)
        host = QWidget(); host.setObjectName("page"); vbox(host).addWidget(outer)
        self.home_view = scroll(host); smooth(self.home_view)
        self.stack.addWidget(self.home_view)

        top = hbox(spacing=16)
        head = vbox(spacing=2)
        head.addWidget(label("Discover", "h1"))
        head.addWidget(label("What people are sharing right now, label by label. Play the drop, check the file.", "muted"))
        top.addLayout(head, 1)
        self.q = QLineEdit(); self.q.setPlaceholderText("Search a track, artist or label…"); self.q.setMinimumWidth(340)
        self.q.returnPressed.connect(self._search_typed)
        top.addWidget(self.q, 0, Qt.AlignBottom)
        lay.addLayout(top)

        self.pulse = hbox(spacing=10)
        self.pulse_waiting = button("", "pulse", lambda: self.go.emit("queue"))
        self.pulse_found = button("", "pulse", lambda: self.go.emit("wishlist"))
        self.pulse_down = button("", "pulse", lambda: self.go.emit("queue"))
        for b in (self.pulse_waiting, self.pulse_found, self.pulse_down):
            self.pulse.addWidget(b); b.hide()
        self.pulse.addStretch(1)
        lay.addLayout(self.pulse)

        # genre pills: what fills the page (its labels' rows and its style rows)
        from ..core.eras import GENRES, genre as find_genre
        self.era_btns = {}
        fl = FlowLayout(spacing=8)
        for key, name, dot in [("", "Everything", "")] + [(g["key"], g["name"], g["dot"]) for g in GENRES]:
            b = button(name, "genre", lambda _=False, k=key: self.set_era(k)); b.setCheckable(True)
            if dot:                                          # a small colour dot per genre
                pm = QPixmap(24, 24); pm.fill(Qt.transparent)
                pp = QPainter(pm); pp.setRenderHint(QPainter.Antialiasing); pp.setPen(Qt.NoPen)
                pp.setBrush(QColor(dot)); pp.drawEllipse(5, 5, 14, 14); pp.end()
                b.setIcon(QIcon(pm)); b.setIconSize(QSize(10, 10))
            self.era_btns[key] = b; fl.addWidget(b)
        fw = QWidget(); fw.setLayout(fl); lay.addWidget(fw)
        self.era = getattr(self.svc.settings, "discover_era", "") or ""
        if self.era and not find_genre(self.era):
            self.era = ""                                   # an old era key from before genres

        self.spin_bar = SpinBar()
        self.spin_bar.play.connect(lambda c: self._spin_play())
        self.spin_bar.stop.connect(self._spin_play)
        self._spins: list = []; self._spin_loading = False; self._spin_tried: set = set()
        from .player import Player

        def _player_changed():
            pl = Player.get()
            if self.spin_bar._previewing and (not pl.playing() or pl.path != getattr(self, "_spin_wav", None)):
                self.spin_bar.set_preview_state("")
        Player.get().changed.connect(_player_changed)
        try:
            self._load_spins()                                # last session's ready spins: instant first spin
        except Exception:
            pass
        self.spin_bar.check.connect(lambda c: self._card_check(self.spin_bar, c))
        self.spin_bar.spin.connect(self._dig_again)
        lay.addWidget(self.spin_bar)

        self.labels_head = self._section("Labels", "")
        self.labels_note = self.labels_head.itemAt(self.labels_head.count() - 1).widget() if self.labels_head.count() > 1 else None
        lay.addLayout(self.labels_head)
        self.rows_box = vbox(spacing=34); lay.addLayout(self.rows_box)
        self.styles_head_w = QWidget(); sh = vbox(self.styles_head_w, (0, 18, 0, 0), 4)
        sh.addWidget(label("Styles", "section"))
        sh.addWidget(label("Across every label: what people are sharing right now, by sound.", "faint", wrap=True))
        lay.addWidget(self.styles_head_w)
        self.styles_box = vbox(spacing=34); lay.addLayout(self.styles_box)
        self.rows: dict[str, CrateRow] = {}

        # the card a tapped track opens (one at a time, moved to the row it belongs to)
        self.track_card = RecordCard("READY NOW"); self.track_card.hide()
        self.track_card.play.connect(lambda c: self._card_play(self.track_card, c))
        self.track_card.stop.connect(self.stop_preview.emit)
        self.track_card.check.connect(lambda c: self._card_check(self.track_card, c))
        self.track_card.watch.connect(lambda a, t: self.watch.emit(a, t, ""))
        self.track_card.open_label.connect(lambda nm: self.find.emit(nm))
        self.track_card.b_label.setText("More from this label")
        self._open_tile = None
        self._active_card = self.spin_bar
        self._tiles_token = next(self._tokens)
        self._tiles_by_img: dict[int, list] = {}

        lay.addStretch(1)
        self._loaded_for = None

    def _section(self, title: str, note: str = ""):
        box = vbox(spacing=4)
        box.addWidget(label(title, "section"))
        if note:
            box.addWidget(label(note, "faint", wrap=True))
        return box

    def refresh(self, jobs: list[dict] | None = None):
        jobs = jobs if jobs is not None else self.svc.jobs()
        from ..core import jobs as J
        waiting = sum(1 for j in jobs if j["state"] == J.READY)
        active = sum(1 for j in jobs if j["state"] in (J.QUEUED, J.STAGING, J.ANALYZING))
        try:
            found = self.svc.wishlist.unseen()
        except Exception:
            found = 0
        self._pulse(self.pulse_waiting, waiting, f"{waiting} checked and waiting for you  →")
        self._pulse(self.pulse_found, found, f"{found} wishlist find{'s' if found != 1 else ''}  →")
        self._pulse(self.pulse_down, active, f"{active} downloading or checking  →")
        self._load_rows()

    # ---- crate rows ------------------------------------------------------------------------------
    def _row_labels(self) -> list[str]:
        from ..core.eras import ESSENTIAL_LABELS, genre as find_genre
        g = find_genre(self.era) if self.era else None
        if g:
            return list(dict.fromkeys(g["labels"]))
        return [n for n, _ in ESSENTIAL_LABELS]

    def set_era(self, key: str):
        self.era = key
        s = self.svc.settings
        if getattr(s, "discover_era", "") != key:
            s.discover_era = key; self.svc.save_settings(s)
        self._loaded_for = None
        self._load_rows()

    def _load_rows(self):
        """Build the rows for the current era and fill each from memory or ONE search, top to bottom."""
        from datetime import date
        from ..core.eras import label_of_the_day
        for k, b in self.era_btns.items():
            b.setChecked(k == self.era)
        connected = getattr(self.svc, "adapter", None) is not None
        want = (self.era, connected)
        if self._loaded_for == want:
            return
        self._loaded_for = want
        self._close_card()
        self.track_card.setParent(self); self.track_card.hide()   # keep it alive: it lived inside a row being removed
        for box in (self.rows_box, self.styles_box):
            while box.count():
                w = box.takeAt(0).widget()
                if w:
                    w.setParent(None); w.deleteLater()
        self.rows = {}
        self._tiles_by_img = {}
        from ..core.eras import STYLES, todays_labels
        from ..core.eras import genre as find_genre
        g = find_genre(self.era) if self.era else None
        if g:
            names = [(n, "") for n in g["labels"]] + [(st, "STYLE") for st in g["styles"]]
        else:
            labels = todays_labels(date.today().toordinal(), 8)
            styles = list(STYLES)
            names = [(labels[0], "LABEL OF THE DAY")]
            for i, lb in enumerate(labels[1:]):           # a style row after every second label
                names.append((lb, ""))
                if i % 2 == 1 and styles:
                    names.append((styles.pop(0), "STYLE"))
            names += [(st, "STYLE") for st in styles]
        self._row_kind = {n: tag for n, tag in names}
        names_only = [n for n, _ in names]
        for name, tag in names:
            row = CrateRow(name, "LABEL OF THE DAY" if tag == "LABEL OF THE DAY" else "")
            row.tapped.connect(self._tap_tile); row.see_all.connect(self.find.emit)
            row.play_tapped.connect(self._play_tile)
            (self.styles_box if tag == "STYLE" else self.rows_box).addWidget(row); self.rows[name] = row
            if not connected:
                row.offline()
        self.styles_head_w.setVisible(any(tag == "STYLE" for _, tag in names))
        self.spin_bar.title.setText("Finding you a track…" if connected else "Connect to the network to dig the crate.")
        if not connected:
            return
        names = names_only
        gen = self._rows_gen = next(self._tokens)
        lib = self.engine.library()
        svc = self.svc
        from ..core.crates import crate
        for name in names:
            def work(nm=name):
                return crate(svc, nm, owns=lib.owns, cancelled=lambda: self._rows_gen != gen,
                             kind="style" if self._row_kind.get(nm) == "STYLE" else "label")

            def then(res, nm=name):
                if self._rows_gen != gen or nm not in self.rows:
                    return
                if isinstance(res, Exception) or res is None:
                    self.rows[nm].fill([]); return
                self.rows[nm].fill(res)
                self._covers_for(nm, res)
                self._prefetch_spins()
            self._run_bg(work, then)

    def _covers_for(self, name: str, tracks):
        """Covers from Discogs: match the crate's tracks to the label's records (cached after the first time)."""
        import zlib
        eng = self.engine
        row = self.rows.get(name)

        def paint():
            for tile in (row.tiles if row else []):
                if tile.track.thumb:
                    rid = zlib.crc32(tile.track.thumb.encode()) & 0x7FFFFFFF
                    self._tiles_by_img.setdefault(rid, []).append(tile)
            todo = {}
            for rid, tiles in self._tiles_by_img.items():
                if tiles and tiles[0].track.thumb:
                    todo[rid] = tiles[0].track.thumb
            self._fetch_images(list(todo.items()), self._tiles_token)

        if all(t.thumb for t in tracks):
            paint(); return
        is_style = self._row_kind.get(name) == "STYLE"

        def work():
            from ..media.metadata import deezer_cover
            recs = []
            ent = None if is_style else eng.label(name)
            if not ent or not ent.discogs_id:
                for t in tracks:                             # styles (and labels Discogs doesn't know): Deezer
                    if not t.thumb:
                        t.thumb = deezer_cover(t.artist, t.title)
                return []
            first = eng.label_releases(ent.discogs_id, 1)
            recs += first.releases
            for pg in range(2, min(first.pages, 3) + 1):
                recs += eng.label_releases(ent.discogs_id, pg).releases
            return recs

        def then(recs):
            if isinstance(recs, Exception) or recs is None or row is None:
                return
            from ..core.discover import norm
            for t in tracks:
                if t.thumb:
                    continue
                a = norm(t.artist)
                for r in recs:
                    if r.thumb and a and a in norm(r.artist) and (norm(t.title) in norm(r.title) or norm(r.title) in norm(t.title)
                                                                  or (t.catno and t.catno.replace(" ", "").lower() in (r.catno or "").replace(" ", "").lower())):
                        t.thumb = r.thumb; break
            missing = [t for t in tracks if not t.thumb]
            from ..core.crates import remember
            if not missing:
                remember(self.svc.db, name, tracks); paint(); return
            paint()

            def dz():
                from ..media.metadata import deezer_cover
                for t in missing:
                    t.thumb = deezer_cover(t.artist, t.title)
                return True

            def dz_then(_):
                remember(self.svc.db, name, tracks); paint()
            self._run_aux(dz, dz_then)
        self._run(work, then)

    def _found_for(self, row_name: str, t):
        from ..core.discover import Release
        from ..core.discover_avail import Found
        rel = Release(0, t.title, t.artist, None, t.catno, "", row_name, t.thumb)
        return Found(rel, {"cover": t.thumb}, row_name, t.title + (f" ({t.mix})" if t.mix else ""), t.best, list(t.alts))

    def _tap_tile(self, row, tile):
        """Tap a track: its card opens under that row. Tap it again: closed. Tap another: that one opens."""
        if self._open_tile is tile:
            self._close_card(); return
        self._close_card()
        self._open_tile = tile
        tile.set_open(True)
        row.drawer_slot.addWidget(self.track_card)
        f = self._found_for(row.name, tile.track)
        self._show_found(self.track_card, f)
        self.track_card.show()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(60, lambda: self.home_view.ensureWidgetVisible(self.track_card, 0, 30))

    def _play_tile(self, row, tile):
        """Cover clicked: open its card (if it isn't already) and play the drop."""
        if self._open_tile is not tile:
            self._tap_tile(row, tile)
        if not self.track_card._previewing:
            self._card_play(self.track_card, self.track_card.found.best)

    def _sync_eq(self):
        tile = self._open_tile
        for row in self.rows.values():
            for t in row.tiles:
                try:
                    t.art.set_playing(t is tile and self.track_card._previewing)
                except RuntimeError:
                    pass

    def _close_card(self):
        if self._open_tile is not None:
            try:
                self._open_tile.set_open(False)
            except RuntimeError:
                pass
        self._open_tile = None
        if self.track_card._previewing:
            self.stop_preview.emit()
        self.track_card.hide()

    SPINS_READY = 3

    def _dig_again(self):
        self._dig_pressed = True
        self.spin()

    def spin(self):
        """Show the next spin: one whose preview is already loaded, so it plays the moment you press ▶."""
        from .player import Player
        if self.spin_bar._previewing:
            Player.get().stop()
        if not self._spins:
            self.spin_bar.title.setText("Finding you a track…"); self.spin_bar.sub.setText("")
            self._prefetch_spins(); return
        f, wav = self._spins.pop(0)
        old = getattr(self, "_spin_wav", None)
        if old:
            Path(old).unlink(missing_ok=True)
        self._spin_wav = wav
        self._save_spins()
        self._show_found(self.spin_bar, f)
        if getattr(self, "_dig_pressed", False):                  # "Dig again": it plays straight away
            self._dig_pressed = False
            self._spin_play()
        self._prefetch_spins()

    SPIN_KEEP_HOURS = 3

    def _save_spins(self):
        """Ready spins survive a restart (the clip is already here), so the first spin after opening is instant."""
        import json
        from dataclasses import asdict
        items = [(f, w) for f, w in self._spins if Path(w).exists()]
        data = [{"wav": w, "label": f.label, "track": f.track, "artist": f.release.artist, "title": f.release.title,
                 "catno": f.release.catno, "thumb": f.release.thumb, "best": asdict(f.best),
                 "bpm": f.details.get("bpm", ""), "camelot": f.details.get("camelot", ""),
                 "alts": [asdict(c) for c in f.alts]} for f, w in items]
        try:
            (self._spin_dir() / "ready3.json").write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    def _load_spins(self):
        import json, time as _t
        from ..adapters.base import Candidate
        from ..core.discover import Release
        from ..core.discover_avail import Found
        d = self._spin_dir()
        keep = set()
        try:
            data = json.loads((d / "ready3.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = []
        for x in data:
            w = Path(x.get("wav", ""))
            if not w.exists() or _t.time() - w.stat().st_mtime > self.SPIN_KEEP_HOURS * 3600:
                continue
            best = Candidate(**x["best"])
            rel = Release(0, x.get("title", ""), x.get("artist", ""), None, x.get("catno", ""), "", x.get("label", ""), x.get("thumb", ""))
            self._spins.append((Found(rel, {"cover": x.get("thumb", ""), "bpm": x.get("bpm", ""), "camelot": x.get("camelot", "")},
                                      x.get("label", ""), x.get("track", ""), best,
                                      [Candidate(**c) for c in x.get("alts") or []] or [best]), str(w)))
            keep.add(w.name)
        for f in d.glob("*.wav"):                                  # anything else is left over: tidy
            if f.name not in keep:
                f.unlink(missing_ok=True)

    def _prefetch_spins(self):
        """Keep SPINS_READY tracks loaded: pick from every row on the page, load its preview in the background,
        and only keep it if the preview actually came through (a busy or broken source never reaches Spin)."""
        import random
        if self._spin_loading or len(self._spins) >= self.SPINS_READY:
            if self.spin_bar.found is None and self._spins:
                self.spin()
            return
        pool = [(name, tl.track) for name, row in self.rows.items() for tl in row.tiles]
        tried = self._spin_tried
        pool = [(n, t) for n, t in pool if t.best.key not in tried]
        if not pool:
            return
        name, t = random.choice(pool)
        tried.add(t.best.key)
        self._spin_loading = True
        svc, spin_dir = self.svc, self._spin_dir()
        cands = list(t.alts) or [t.best]

        def work():
            import shutil as _sh
            for c in cands[:2]:
                try:
                    wav, start = svc.snippet_preview(c, background=True, timeout_s=20)   # a slow source is skipped
                except Exception:
                    continue
                dest = spin_dir / Path(wav).name
                _sh.move(str(wav), dest)
                try:                                           # BPM and key from the clip, shown on the Dig bar
                    from ..media.musical import analyze_music
                    m = analyze_music(dest, svc.settings.ffmpeg_path)
                    c._music = (f"{m.bpm:.0f}" if m.bpm else "", m.camelot or "")
                except Exception:
                    c._music = ("", "")
                return c, str(dest), start
            return None

        def then(res):
            self._spin_loading = False
            if res and not isinstance(res, Exception):
                c, wav, _start = res
                t.best = c
                f = self._found_for(name, t)
                bpm, cam = getattr(c, "_music", ("", ""))
                f.details["bpm"], f.details["camelot"] = bpm, cam
                self._spins.append((f, wav))
                self._save_spins()
                if self.spin_bar.found is None:
                    self.spin()
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1500 if res else 4000, self._prefetch_spins)
        self._run_aux(work, then)

    def _spin_dir(self) -> Path:
        d = Path(self.svc.db.path).parent / "spin"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _spin_play(self):
        from .player import Player
        if self.spin_bar._previewing:
            Player.get().stop(); self.spin_bar.set_preview_state(""); return
        wav, f = getattr(self, "_spin_wav", None), self.spin_bar.found
        if wav and f and Path(wav).exists():
            Player.get().next_art = self.spin_bar.art._pm
            Player.get().play(wav, f.track, f"{f.release.artist} · preview · not downloaded", stop_after_s=21)
            self.spin_bar.set_preview_state("playing", "Playing the drop. Check this file to download it.")

    def _show_found(self, card, f):
        if card._previewing:
            self.stop_preview.emit()
        card.show_found(f)
        tok = next(self._tokens)
        card._img_token = tok
        url = f.details.get("cover") or f.release.thumb
        if url:
            import zlib
            self._fetch_images([(zlib.crc32(url.encode()) & 0x7FFFFFFF, url)], tok)

    def _card_play(self, card, cand):
        if self._active_card is not card and self._active_card._previewing:
            self.stop_preview.emit()
        self._active_card = card
        from .player import Player
        Player.get().next_art = card.art._pm                  # the bar at the bottom shows this cover
        self.preview.emit(cand)

    def _card_check(self, card, cand):
        self.pick.emit(cand)
        card.b_check.setEnabled(False); card.b_check.setText("Requested ✓")

    # the window drives previews through these (same as the Search page)
    @property
    def _previewing(self) -> bool:
        return self._active_card._previewing

    def set_preview_state(self, state: str, msg: str = ""):
        self._active_card.set_preview_state(state, msg)
        self._sync_eq()

    def mark_busy(self, cand):
        f = self._active_card.found
        if f and cand in f.alts:
            f.alts.remove(cand)

    def ready_alternative(self, failed, tried: set):
        f = self._active_card.found
        return next((c for c in (f.alts if f else []) if c.key not in tried and c is not failed), None)

    @staticmethod
    def _pulse(b, n: int, text: str):
        b.setText(text); b.setVisible(n > 0)

    def _search_typed(self):
        if self.q.text().strip():
            self.find.emit(self.q.text().strip())

    # ---- era crate -------------------------------------------------------------------------
    def _build_era(self):
        outer, lay = page(spacing=22)
        host = QWidget(); host.setObjectName("page"); vbox(host).addWidget(outer)
        self.era_view = scroll(host); smooth(self.era_view)
        self.stack.addWidget(self.era_view)
        self.era_back = button("←  Back", "link", self.back); lay.addWidget(self.era_back, 0, Qt.AlignLeft)
        self.era_title = label("", "h1"); self.era_years = label("", "tilemeta")
        th = hbox(spacing=14); th.addWidget(self.era_title); th.addWidget(self.era_years, 0, Qt.AlignBottom); th.addStretch(1)
        lay.addLayout(th)
        self.era_blurb = label("", "muted", wrap=True); lay.addWidget(self.era_blurb)
        lay.addLayout(self._section("Labels", "Each opens its whole catalogue, oldest first."))
        self.era_labels = FlowLayout(spacing=14, cell=220)
        w = QWidget(); w.setLayout(self.era_labels); lay.addWidget(w)
        lay.addLayout(self._section("Artists"))
        self.era_artists = FlowLayout(spacing=8)
        w = QWidget(); w.setLayout(self.era_artists); lay.addWidget(w)
        lay.addWidget(label("A starter crate. Missing someone? It's one line in app/core/eras.py.", "faint"))
        lay.addStretch(1)

    def open_era(self, key: str, remember: bool = True):
        e = find_era(key)
        if not e:
            return
        if remember:
            self._history.append(("era", key))
        self.era_title.setText(e["name"]); self.era_years.setText(e["years"]); self.era_blurb.setText(e["blurb"])
        self.era_labels.clear(); self.era_artists.clear()
        try:
            owned = {n.lower(): c for n, c in self.engine.library().labels(500)}
        except Exception:
            owned = {}
        for name in e["labels"]:
            n = owned.get(name.lower(), 0)
            t = Tile(name, f"{n} in your library" if n else "Open the catalogue")
            t.clicked.connect(lambda nm=name: self.open_entity("label", nm))
            self.era_labels.addWidget(t)
        for name in e["artists"]:
            self.era_artists.addWidget(chip(name, lambda _=False, nm=name: self.open_entity("artist", nm)))
        self.stack.setCurrentWidget(self.era_view)
        self.era_view.verticalScrollBar().setValue(0)

    # ---- label / artist --------------------------------------------------------------------
    COLS = ["", "Year", "Artist", "Title", "Label · Cat #", "Format", "Have"]

    def _build_entity(self):
        outer, lay = page(spacing=14)
        self.entity_view = QWidget(); self.entity_view.setObjectName("page"); vbox(self.entity_view).addWidget(outer)
        self.stack.addWidget(self.entity_view)
        self.ent_back = button("←  Back", "link", self.back); lay.addWidget(self.ent_back, 0, Qt.AlignLeft)
        th = hbox(spacing=14)
        self.ent_kind = label("", "tag"); self.ent_title = label("", "h1")
        th.addWidget(self.ent_title); th.addWidget(self.ent_kind, 0, Qt.AlignBottom); th.addStretch(1)
        self.ent_discogs = button("View on Discogs ↗", "link", self._open_discogs); th.addWidget(self.ent_discogs, 0, Qt.AlignBottom)
        lay.addLayout(th)
        self.ent_meta = label("", "tilemeta"); lay.addWidget(self.ent_meta)
        self.ent_profile = label("", "muted", wrap=True); self.ent_profile.setMaximumHeight(66); lay.addWidget(self.ent_profile)
        self.ent_related = FlowLayout(spacing=8)
        rw = QWidget(); rw.setLayout(self.ent_related); lay.addWidget(rw)

        fr = hbox(spacing=8)
        self.f_new = button("Hide what I have", "chip", self._filter); self.f_new.setCheckable(True)
        self.f_vinyl = button("Vinyl only", "chip", self._filter); self.f_vinyl.setCheckable(True)
        self.f_text = QLineEdit(); self.f_text.setPlaceholderText("Filter this list…"); self.f_text.setMaximumWidth(260)
        self.f_text.textChanged.connect(self._filter)
        for w in (self.f_new, self.f_vinyl):
            fr.addWidget(w)
        fr.addWidget(self.f_text); fr.addStretch(1)
        self.ent_count = label("", "faint"); fr.addWidget(self.ent_count)
        lay.addLayout(fr)

        self.tree = QTreeWidget(); self.tree.setColumnCount(len(self.COLS)); self.tree.setHeaderLabels(self.COLS)
        self.tree.setItemDelegate(KeepColourDelegate(self.tree))
        self.tree.setRootIsDecorated(False); self.tree.setUniformRowHeights(True)
        self.tree.setIconSize(QSize(34, 34))
        hdr = self.tree.header(); hdr.setSectionResizeMode(QHeaderView.Interactive); hdr.setStretchLastSection(False)
        for i, w in enumerate((48, 56, 200, 280, 210, 150, 52)):
            self.tree.setColumnWidth(i, w)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        self.tree.itemDoubleClicked.connect(lambda *_: self._search_selected())
        self.tree.itemSelectionChanged.connect(self._selection)
        smooth(self.tree)
        lay.addWidget(self.tree, 1)
        self.ent_state = label("", "muted", wrap=True); lay.addWidget(self.ent_state)

        acts = hbox(spacing=10)
        self.b_search = button("Search for it", "accent", self._search_selected)
        self.b_watch = button("Watch it", "ghost", self._watch_selected)
        self.b_watch.setToolTip("Keep asking the network for it every half hour, and tell me when a good copy shows up.")
        self.b_artist = button("Open the artist", "ghost", self._open_selected_artist)
        self.b_label = button("Open the label", "ghost", self._open_selected_label)
        for b in (self.b_search, self.b_watch, self.b_artist, self.b_label):
            acts.addWidget(b); b.setEnabled(False)
        acts.addStretch(1)
        self.b_more = button("Load more", "ghost", self._load_more); acts.addWidget(self.b_more); self.b_more.hide()
        lay.addLayout(acts)
        self._rows: list[Release] = []
        self._ent: Entity | None = None
        self._page_no = self._pages = 1

    def open_entity(self, kind: str, name: str, discogs_id: int | None = None, remember: bool = True):
        if remember:
            self._history.append(("entity", kind, name, discogs_id))
        self._ent = None; self._rows = []; self._page_no = self._pages = 1
        self.tree.clear(); self.b_more.hide(); self._selection()
        self.ent_title.setText(name); self.ent_kind.setText(kind.upper())
        self.ent_meta.setText(""); self.ent_profile.setText(""); self.ent_related.clear(); self.ent_discogs.hide()
        self.ent_count.setText("")
        self.ent_state.setText(f"Looking up {name} on MusicBrainz and Discogs…  (the first time takes a few seconds; "
                               "after that it's instant)")
        self.ent_state.show()
        self.b_artist.setVisible(kind == "label"); self.b_label.setVisible(kind == "artist")
        self.stack.setCurrentWidget(self.entity_view)
        eng = self.engine
        tok_holder = {}

        def work():
            ent = eng.label(name, discogs_id) if kind == "label" else eng.artist(name, discogs_id)
            pg = None
            if ent.discogs_id:
                pg = (eng.label_releases if kind == "label" else eng.artist_releases)(ent.discogs_id, 1)
            return ent, pg

        def then(res):
            if self._view_token != tok_holder["t"]:
                return                                       # the user moved on
            if isinstance(res, Exception):
                self.ent_state.setText("Couldn't reach Discogs just now. Check the connection and try again in a minute.")
                return
            ent, pg = res
            self._show_entity(ent, pg)
        tok_holder["t"] = self._view_token = self._run(work, then)

    def _show_entity(self, ent: Entity, pg: Page | None):
        self._ent = ent
        self.ent_title.setText(ent.name)
        if ent.discogs_id is None:
            self.ent_state.setText(f"Couldn't find “{ent.name}” as a {ent.kind} on Discogs. Check the spelling "
                                   "(Discogs spells it the way the record does), or try Search.")
            return
        self.ent_discogs.setVisible(bool(ent.url))
        self.ent_profile.setText(ent.profile[:420] + ("…" if len(ent.profile) > 420 else ""))
        self.ent_profile.setToolTip(ent.profile[:2000])
        for rel, nm in ent.related[:10]:
            if nm:
                k = "label" if ent.kind == "label" else "artist"
                self.ent_related.addWidget(chip(f"{rel}: {nm}", lambda _=False, n=nm, kk=k: self.open_entity(kk, n)))
        if pg is not None:
            self._pages = pg.pages
            self._add_rows(pg.releases)
            self._total = pg.total
        self._update_meta()
        self._load_rest()

    MAX_PAGES = 30                     # 3,000 releases: every house label we know of fits

    def _load_rest(self):
        """Fetch the remaining pages one after another (Discogs allows one every couple of seconds; cached after)
        so the whole catalogue is there to filter and scroll, not just its first two years."""
        if not self._ent or self._page_no >= min(self._pages, self.MAX_PAGES):
            self.b_more.hide(); self._update_meta(); return
        ent, nxt, view = self._ent, self._page_no + 1, self._view_token
        fn = self.engine.label_releases if ent.kind == "label" else self.engine.artist_releases
        self.b_more.setText(f"Loading the rest…  ({self._page_no} of {min(self._pages, self.MAX_PAGES)})")
        self.b_more.setEnabled(False); self.b_more.show()

        def then(res):
            if self._view_token != view:
                return
            if isinstance(res, Exception):
                self.b_more.setEnabled(True); self.b_more.setText("Load more"); return
            self._page_no = res.page
            self._add_rows(res.releases)
            self._update_meta()
            self._load_rest()
        self._run(lambda: fn(ent.discogs_id, nxt), then)

    def _update_meta(self):
        if not self._ent:
            return
        have = sum(1 for r in self._rows if r.owned)
        years = [r.year for r in self._rows if r.year]
        span = f"{min(years)}–{max(years)}" if years else ""
        bits = [f"{getattr(self, '_total', len(self._rows)):,} releases on Discogs", span,
                f"you have {have}" if have else "you have none of these yet"]
        self.ent_meta.setText("  ·  ".join(b for b in bits if b))

        self.ent_state.setVisible(not self._rows)
        if not self._rows:
            self.ent_state.setText("Discogs lists no releases here.")
        self._filter()

    def _add_rows(self, rels: list[Release]):
        c = T.colours(self._theme())
        items = []
        from ..core.discover import norm
        seen = getattr(self, "_seen", None)
        if seen is None or not self._rows:
            seen = self._seen = set()
        for r in rels:
            k = (norm(r.artist), norm(r.title))
            if k in seen:
                continue                                     # a reissue on a later page: the first pressing is shown
            seen.add(k)
            labcat = " · ".join(x for x in (r.label, r.catno) if x and x.lower() != "none")
            it = QTreeWidgetItem(["", str(r.year or "—"), r.artist, r.title, labcat, r.format,
                                  "✓" if r.owned else ""])
            it.setData(0, Qt.UserRole, len(self._rows))
            it.setToolTip(3, r.title); it.setToolTip(2, r.artist); it.setToolTip(5, r.format)
            if r.owned:
                it.setForeground(6, QColor(c["pass_"]))
                it.setToolTip(6, "Already in your library")
            self._rows.append(r)
            items.append(it)
        self.tree.addTopLevelItems(items)
        self._fetch_thumbs(items)

    def _filter(self):
        text = self.f_text.text().strip().lower()
        hide_have, vinyl = self.f_new.isChecked(), self.f_vinyl.isChecked()
        shown = 0
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            r = self._rows[it.data(0, Qt.UserRole)]
            hide = (hide_have and r.owned) or (vinyl and not any(v in r.format for v in ('12"', '7"', '10"', "LP", "Vinyl"))) \
                or (text and text not in f"{r.artist} {r.title} {r.label} {r.catno} {r.year}".lower())
            it.setHidden(bool(hide))
            shown += not hide
        self.ent_count.setText(f"{shown} shown" if self._rows else "")

    def _load_more(self):
        self._load_rest()                                    # after a network hiccup: carry on where it stopped

    # ---- thumbnails (lazy, cached on disk) -----------------------------------------------------
    def _thumb_dir(self) -> Path:
        from ..config import data_dir
        d = data_dir() / "discover_thumbs"; d.mkdir(parents=True, exist_ok=True)
        return d

    def _fetch_thumbs(self, items):
        view = self._view_token
        todo = []
        for it in items:
            r = self._rows[it.data(0, Qt.UserRole)]
            if not r.thumb:
                continue
            p = self._thumb_dir() / f"{r.id}.jpg"
            if p.exists():
                self._set_icon(it, p.read_bytes())
            else:
                todo.append((r.id, r.thumb, p))
        if not todo:
            return
        bridge = self.bridge

        class Fetch(QRunnable):
            def run(self_inner):
                from ..media.metadata import http_get
                import time
                for rid, url, p in todo[:120]:
                    if not url.startswith("https://"):
                        continue
                    try:
                        data = http_get(url, 8.0)
                        p.write_bytes(data)
                        bridge.thumb.emit(view, rid, data)
                    except Exception:
                        pass
                    time.sleep(0.15)
        self.thumbs.start(Fetch())

    def _fetch_images(self, todo: list[tuple[int, str]], token: int):
        """(release id, image url) -> bridge.thumb(token, id, bytes), cached on disk."""
        bridge, d = self.bridge, self._thumb_dir()
        cached = [(rid, d / f"{rid}.jpg") for rid, _ in todo if (d / f"{rid}.jpg").exists()]
        for rid, p in cached:
            self._thumb(token, rid, p.read_bytes())
        rest = [(rid, url, d / f"{rid}.jpg") for rid, url in todo if not (d / f"{rid}.jpg").exists()]
        if not rest:
            return

        class Fetch(QRunnable):
            def run(self_inner):
                from ..media.metadata import http_get
                import time
                for rid, url, p in rest:
                    if not url.startswith("https://"):
                        continue
                    try:
                        data = http_get(url, 8.0); p.write_bytes(data)
                        bridge.thumb.emit(token, rid, data)
                    except Exception:
                        pass
                    time.sleep(0.15)
        self.thumbs.start(Fetch())

    def _thumb(self, view: int, rid: int, data):
        for card in (self.spin_bar, self.track_card):
            if card._img_token == view:
                pm = QPixmap()
                if pm.loadFromData(data):
                    card.art.set_pixmap(pm)
                return
        if view == self._tiles_token:
            for tile in self._tiles_by_img.get(rid, []):
                try:
                    tile.set_image(data)
                except RuntimeError:
                    pass
            return
        if view != self._view_token:
            return
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if self._rows[it.data(0, Qt.UserRole)].id == rid:
                self._set_icon(it, data)

    @staticmethod
    def _set_icon(it, data: bytes):
        pm = QPixmap()
        if pm.loadFromData(data):
            it.setIcon(0, QIcon(pm.scaled(68, 68, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)))

    # ---- actions ----------------------------------------------------------------------------
    def _current(self) -> Release | None:
        items = self.tree.selectedItems()
        return self._rows[items[0].data(0, Qt.UserRole)] if items else None

    def _selection(self):
        r = self._current()
        for b in (self.b_search, self.b_watch, self.b_artist, self.b_label):
            b.setEnabled(r is not None)
        if r is not None:
            self.b_label.setEnabled(bool(r.label))
            self.b_artist.setEnabled(r.artist.lower() not in ("various", "unknown artist"))

    def _search_selected(self):
        r = self._current()
        if r:
            self.find.emit(r.query)

    def _watch_selected(self):
        r = self._current()
        if r:
            a = "" if r.artist.lower() in ("various", "unknown artist") else r.artist
            self.watch.emit(a, r.title, "")

    def _open_selected_artist(self):
        r = self._current()
        if r:
            self.open_entity("artist", r.artist.split(" / ")[0].split(", ")[0])

    def _open_selected_label(self):
        r = self._current()
        if r and r.label:
            self.open_entity("label", r.label)

    def _open_discogs(self):
        if self._ent and self._ent.url.startswith("https://www.discogs.com/"):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(self._ent.url))

    # ---- find: search for a record without leaving Discover ----------------------------------------
    def _build_find(self):
        from .pages import SearchPage
        self.find_view = QWidget(); self.find_view.setObjectName("page")
        fl = vbox(self.find_view, (0, 0, 0, 0), 0)
        bar = QWidget(); bl = hbox(bar, (36, 18, 36, 0), 14)
        bl.addWidget(button("←  Back", "link", self.back))
        self.find_note = label("", "faint"); bl.addWidget(self.find_note); bl.addStretch(1)
        fl.addWidget(bar)
        self.finder = SearchPage(self.svc)        # its own results, separate from the Search tab
        self.finder.dance_only = True
        fl.addWidget(self.finder, 1)
        self.stack.addWidget(self.find_view)

    def show_find(self, q: str):
        """Called by the window just before it starts the search here."""
        here = self.stack.currentWidget()
        if here is not self.find_view:
            self._history.append(("find", q, here))
        self.find_note.setText(f"In Discover  ·  back takes you to where you were")
        self.stack.setCurrentWidget(self.find_view)

    def back(self):
        last = self._history.pop() if self._history else None
        if last and last[0] == "find":
            self.stack.setCurrentWidget(last[2])                # exactly as you left it: scroll, selection, list
            return
        self._view_token = next(self._tokens)                 # drop any lookup still on its way
        if not self._history:
            self.stack.setCurrentWidget(self.home_view); return
        last = self._history[-1]
        if last[0] == "era":
            self.open_era(last[1], remember=False)
        else:
            self.open_entity(last[1], last[2], last[3], remember=False)

    def show_home(self):
        self._history.clear(); self._view_token = next(self._tokens)
        self.stack.setCurrentWidget(self.home_view)
