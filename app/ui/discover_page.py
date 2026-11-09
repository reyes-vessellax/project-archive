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
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QFrame, QHeaderView, QLayout, QLineEdit, QSizePolicy, QStackedWidget, QTreeWidget,
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
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

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


class CoverArt(QWidget):
    """A square record cover that fills its column (placeholder disc until the image arrives)."""

    def __init__(self):
        super().__init__()
        self._pm = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return w

    def sizeHint(self):
        return QSize(150, 150)

    def set_pixmap(self, pm):
        self._pm = pm; self.update()

    def paintEvent(self, e):
        from PySide6.QtGui import QPainter
        p = QPainter(self); p.setRenderHint(QPainter.SmoothPixmapTransform)
        side = min(self.width(), self.height())
        r = QRect(0, 0, self.width(), side)
        if self._pm is not None and not self._pm.isNull():
            pm = self._pm.scaled(r.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(r, pm, QRect((pm.width() - r.width()) // 2, (pm.height() - r.height()) // 2, r.width(), r.height()))
        else:
            p.fillRect(r, QColor(128, 128, 128, 40))
            p.setPen(Qt.NoPen); p.setBrush(QColor(20, 20, 20, 160))
            c = r.center(); rad = side * 0.38
            p.drawEllipse(c, int(rad), int(rad))
            p.setBrush(QColor(220, 20, 60)); p.drawEllipse(c, int(rad * 0.3), int(rad * 0.3))
        p.end()


class CoverCard(QFrame):
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
        self.status.setText("")
        for b in (self.b_play, self.b_check, self.b_watch, self.b_label):
            b.setEnabled(True)
        self.set_preview_state("")
        self.art.set_pixmap(None)

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
        self.bridge = _Bridge(); self.bridge.done.connect(self._done); self.bridge.thumb.connect(self._thumb)
        self.bridge.found.connect(self._dig_found_one)
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
        outer, lay = page(spacing=26)
        host = QWidget(); host.setObjectName("page"); vbox(host).addWidget(outer)
        self.home_view = scroll(host); smooth(self.home_view)
        self.stack.addWidget(self.home_view)

        head = vbox(spacing=4)
        head.addWidget(label("Discover", "h1"))
        head.addWidget(label("House music from the first Chicago 12\"s to this year's records. Dig through the labels, artists and "
                             "eras behind it.", "muted", wrap=True))
        lay.addLayout(head)

        srow = hbox(spacing=16)
        self.q = QLineEdit(); self.q.setObjectName("hero"); self.q.setPlaceholderText("Search for a track, artist or label…")
        self.q.returnPressed.connect(self._search_typed)
        srow.addWidget(self.q, 1)
        srow.addWidget(button("Search", "accent", self._search_typed))
        srow.addWidget(button("Dig a label", "ghost", self._dig_typed))
        lay.addLayout(srow)

        self.pulse = hbox(spacing=10)
        self.pulse_waiting = button("", "pulse", lambda: self.go.emit("queue"))
        self.pulse_found = button("", "pulse", lambda: self.go.emit("wishlist"))
        self.pulse_down = button("", "pulse", lambda: self.go.emit("queue"))
        for b in (self.pulse_waiting, self.pulse_found, self.pulse_down):
            self.pulse.addWidget(b); b.hide()
        self.pulse.addStretch(1)
        lay.addLayout(self.pulse)

        # Spin the crate: one random record that someone is sharing right now
        self.spin_again = button("↻  Spin again", "primary", self.spin)
        self.spin_card = RecordCard("SPIN THE CRATE  ·  SOMEONE'S SHARING THIS RIGHT NOW", extra=self.spin_again)
        self.spin_card.message("Finding a record someone is sharing right now…")
        lay.addWidget(self.spin_card)
        self._found_next = None; self._spin_busy = False

        # Today's dig: records from one label (a different one each day), only the ones someone is sharing now
        dig_head = hbox(spacing=12)
        dig_head.addWidget(label("Today's dig", "section"))
        self.dig_label = label("", "tilemeta"); dig_head.addWidget(self.dig_label, 0, Qt.AlignBottom)
        dig_head.addStretch(1)
        self.dig_open = button("Open the whole label  →", "link", lambda: self._dig_name and self.open_entity("label", self._dig_name))
        dig_head.addWidget(self.dig_open, 0, Qt.AlignBottom)
        lay.addLayout(dig_head)
        self.dig_note = label("Looking for records people are sharing right now…", "faint"); lay.addWidget(self.dig_note)
        self.dig_flow = FlowLayout(spacing=14, cell=150)
        dw = QWidget(); dw.setLayout(self.dig_flow); lay.addWidget(dw)
        self.dig_card = RecordCard("TODAY'S DIG"); self.dig_card.hide()
        lay.addWidget(self.dig_card)
        self._dig_name, self._dig_token, self._dig_cards, self._dig_found = "", -1, {}, {}
        for card in (self.spin_card, self.dig_card):
            card.play.connect(lambda c, cd=card: self._card_play(cd, c))
            card.stop.connect(self.stop_preview.emit)
            card.check.connect(lambda c, cd=card: self._card_check(cd, c))
            card.watch.connect(lambda a, t: self.watch.emit(a, t, ""))
            card.open_label.connect(lambda nm: self.open_entity("label", nm))
        self._active_card = self.spin_card

        lay.addLayout(self._section("Era crates", "Hand-picked doors into house, every era. Open one to dig its labels and artists."))
        eras = FlowLayout(spacing=14, cell=200)
        for e in ERAS:
            t = Tile(e["name"], e["years"], e["blurb"], tall=True)
            t.clicked.connect(lambda k=e["key"]: self.open_era(k))
            eras.addWidget(t)
        ew = QWidget(); ew.setLayout(eras); lay.addWidget(ew)

        from ..core.eras import ESSENTIAL_LABELS
        lay.addLayout(self._section("Essential labels", "Old and new cornerstones. Every record they put out, by year."))
        ess = FlowLayout(spacing=14, cell=200)
        for name, city in ESSENTIAL_LABELS:
            t = Tile(name, city.upper())
            t.clicked.connect(lambda nm=name: self.open_entity("label", nm))
            ess.addWidget(t)
        sw = QWidget(); sw.setLayout(ess); lay.addWidget(sw)

        lay.addLayout(self._section("Artists you play", "Open one for their whole catalogue, aliases and groups."))
        self.artists_flow = FlowLayout(spacing=8)
        aw = QWidget(); aw.setLayout(self.artists_flow); lay.addWidget(aw)
        self.artists_empty = label("The artists in your library show up here.", "faint"); lay.addWidget(self.artists_empty)
        lay.addStretch(1)

    def _section(self, title: str, note: str = ""):
        box = vbox(spacing=4)
        box.addWidget(label(title, "section"))
        if note:
            box.addWidget(label(note, "faint", wrap=True))
        return box

    def refresh(self, jobs: list[dict] | None = None):
        """Cheap: the library index is cached until a job changes."""
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
        self._load_dig()
        if self.spin_card.found is None and not self._spin_busy:
            self._prefetch_spin(show=True)
        try:
            lib = self.engine.library()
        except Exception:
            return
        key = (len(lib.tracks), lib.tracks[-1].job_id if lib.tracks else "")
        if getattr(self, "_lib_key", None) == key:
            return
        self._lib_key = key
        self.artists_flow.clear()
        for name, n in lib.artists(30):
            self.artists_flow.addWidget(chip(f"{name}  ·  {n}", lambda _=False, nm=name: self.open_entity("artist", nm)))
        self.artists_empty.setVisible(not lib.artists(1))

    # ---- spin the crate --------------------------------------------------------------------------
    def _spin_labels(self) -> list[str]:
        from ..core.eras import ESSENTIAL_LABELS
        names = [n for n, _ in ESSENTIAL_LABELS] + [l for e in ERAS for l in e["labels"]]
        return list(dict.fromkeys(names))

    def _connected(self) -> bool:
        return getattr(self.svc, "adapter", None) is not None

    def spin(self):
        """Show the record that's ready (instant), then find the next one in the background."""
        if self._found_next is not None:
            self._show_found(self.spin_card, self._found_next); self._found_next = None
            self._prefetch_spin()
            return
        if self._spin_busy:
            return
        self.spin_again.setText("Finding one…"); self.spin_again.setEnabled(False)
        self._prefetch_spin(show=True)

    def _prefetch_spin(self, show: bool = False):
        if self._spin_busy:
            return
        if not self._connected():
            self.spin_card.message("Discover only shows records someone is sharing right now, so it needs the network. "
                                   "It fills in as soon as you're connected.")
            return
        self._spin_busy = True
        eng, svc, labels = self.engine, self.svc, self._spin_labels()
        from ..core.discover_avail import spin_found

        def then(res):
            self._spin_busy = False
            self.spin_again.setText("↻  Spin again"); self.spin_again.setEnabled(True)
            if isinstance(res, Exception) or res is None:
                if show or self.spin_card.found is None:
                    self.spin_card.message("Nobody's sharing those right now. Spin again in a moment.")
                return
            if show or self.spin_card.found is None:
                self._show_found(self.spin_card, res); self._prefetch_spin()
            else:
                self._found_next = res
        self._run_bg(lambda: spin_found(eng, svc, labels), then)

    def _show_found(self, card, f):
        if card._previewing:
            self.stop_preview.emit()
        card.show_found(f)
        tok = next(self._tokens)
        card._img_token = tok
        url = f.details.get("cover") or f.release.thumb
        if url:
            self._fetch_images([(-f.release.id, url)], tok)

    def _card_play(self, card, cand):
        if self._active_card is not card and self._active_card._previewing:
            self.stop_preview.emit()
        self._active_card = card
        self.preview.emit(cand)

    def _card_check(self, card, cand):
        self.pick.emit(cand)
        card.status.setText("Requested. It downloads into quarantine, gets checked, then waits in your Queue.")
        card.b_check.setEnabled(False)

    # the window drives previews through these (same as the Search page)
    @property
    def _previewing(self) -> bool:
        return self._active_card._previewing

    def set_preview_state(self, state: str, msg: str = ""):
        self._active_card.set_preview_state(state, msg)

    def mark_busy(self, cand):
        f = self._active_card.found
        if f and cand in f.alts:
            f.alts.remove(cand)

    def ready_alternative(self, failed, tried: set):
        f = self._active_card.found
        return next((c for c in (f.alts if f else []) if c.key not in tried and c is not failed), None)

    # ---- today's dig ---------------------------------------------------------------------------
    DIG_RECORDS = 8           # shown (each one checked as shared right now)
    DIG_TRIES = 18            # records looked at to find them

    def _load_dig(self):
        from datetime import date
        from ..core.eras import label_of_the_day
        name = label_of_the_day(date.today().toordinal())
        if name == self._dig_name and (self._dig_cards or getattr(self, "_dig_busy", False)):
            return
        if not self._connected():
            self.dig_note.setText("Today's dig shows records people are sharing right now; it fills in once you're connected.")
            return
        self._dig_name, self._dig_busy = name, True
        self.dig_label.setText(name.upper())
        self.dig_flow.clear(); self._dig_cards = {}; self._dig_found = {}
        self.dig_note.setText("Looking for records people are sharing right now…"); self.dig_note.show()
        eng, svc, day = self.engine, self.svc, date.today().toordinal()
        tok = self._dig_token = next(self._tokens)
        bridge = self.bridge
        from ..core.discover_avail import verify

        def work():
            ent = eng.label(name)
            if not ent.discogs_id:
                return 0
            first = eng.label_releases(ent.discogs_id, 1)
            page = first if first.pages <= 1 else eng.label_releases(ent.discogs_id, 1 + (day * 7) % min(first.pages, 30))
            pool, seen = [], set()
            for r in page.releases:
                if r.thumb and r.year and r.artist.lower() not in ("various", "unknown artist") and r.artist not in seen:
                    seen.add(r.artist); pool.append(r)
            shown = 0
            for r in pool[:self.DIG_TRIES]:
                if shown >= self.DIG_RECORDS or self._dig_token != tok:
                    break
                try:
                    f = verify(eng, svc, r, ent.name, cancelled=lambda: self._dig_token != tok)
                except Exception:
                    f = None
                if f:
                    shown += 1
                    bridge.found.emit(tok, f)
            return shown

        def then(res):
            self._dig_busy = False
            if isinstance(res, Exception):
                self.dig_note.setText("Couldn't reach Discogs just now; trying again in a minute.")
                from PySide6.QtCore import QTimer
                self._dig_name = ""
                QTimer.singleShot(60_000, self._load_dig)
                return
            if not self._dig_cards:
                self.dig_note.setText(f"Nobody's sharing {name} records right now. Tomorrow's dig is a different label.")
            else:
                self.dig_note.hide()
        self._run_bg(work, then)

    def _dig_found_one(self, tok: int, f):
        if tok != self._dig_token:
            return
        r = f.release
        card = CoverCard(r)
        card.clicked.connect(lambda ff=f: self._open_dig(ff))
        self.dig_flow.addWidget(card); self._dig_cards[r.id] = card; self._dig_found[r.id] = f
        self.dig_note.setText(f"{len(self._dig_cards)} found so far, still looking…")
        self._fetch_images([(r.id, r.thumb)], self._dig_token)

    def _open_dig(self, f):
        """Click a cover: its card opens right under the covers, ready to play and check."""
        self.dig_card.show()
        self._show_found(self.dig_card, f)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, lambda: self.home_view.ensureWidgetVisible(self.dig_card, 0, 40))

    @staticmethod
    def _pulse(b, n: int, text: str):
        b.setText(text); b.setVisible(n > 0)

    def _search_typed(self):
        if self.q.text().strip():
            self.find.emit(self.q.text().strip())

    def _dig_typed(self):
        name = self.q.text().strip()
        if name:
            self.open_entity("label", name)

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
        for card in (self.spin_card, self.dig_card):
            if card._img_token == view:
                pm = QPixmap()
                if pm.loadFromData(data):
                    card.art.set_pixmap(pm)
                return
        if view == self._dig_token and rid in self._dig_cards:
            try:
                self._dig_cards[rid].set_image(data)
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
