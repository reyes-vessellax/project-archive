"""Batch page (design v6): every playlist you drop in becomes its own batch.

Left: one card per playlist (service colour, name, counts, progress). Right: the selected playlist with
stat tiles, a progress bar, and one row per track (what we found, how soon it can start, status).
Every pick still goes through quarantine and the normal check; tracks saved from a batch land in a
folder named after the playlist.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QProgressBar, QSizePolicy, QWidget

from . import theme as T
from .widgets import button, hbox, label, scroll, vbox

STATUS = {"waiting": ("Waiting", "faint"), "searching": ("Searching", "accent"), "found": ("Found", "pass_"),
          "not_found": ("Not found", "fail"), "have": ("Already have", "muted"), "queued": ("Downloading", "accent"),
          "turn": ("Waiting its turn", "faint"),
          "error": ("Problem", "fail")}
SERVICE_COLOUR = {"YouTube": "#d9473f", "Spotify": "#2f9e5b", "SoundCloud": "#e8772e", "Apple Music": "#d6407a",
                  "Folder": "#6b7cff", "List": "#8a8f98", "CSV": "#8a8f98"}


@dataclass
class Batch:
    name: str
    service: str = "List"
    items: list = field(default_factory=list)          # batch_runner.Item
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def count(self, *states) -> int:
        return sum(1 for it in self.items if it.status in states)

    @property
    def done(self) -> int:
        return len(self.items) - self.count("waiting", "searching")

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "service": self.service, "items": [it.to_dict() for it in self.items]}


class BatchSignals(QObject):
    loaded = Signal(str, str, object)      # playlist name, service, list[Item]
    item = Signal(str, int, object)        # batch id, index, Item
    finished = Signal(str)                 # batch id
    error = Signal(str)


def _bar(value: int, total: int) -> QProgressBar:
    b = QProgressBar(); b.setTextVisible(False); b.setFixedHeight(4); b.setRange(0, max(1, total)); b.setValue(value)
    b.setProperty("tag", "Down")
    return b


class BatchCard(QFrame):
    clicked = Signal(str)
    remove = Signal(str)

    def __init__(self, batch: Batch):
        super().__init__()
        self.batch_id = batch.id
        self.setObjectName("bcard"); self.setCursor(Qt.PointingHandCursor)
        lay = vbox(self, (14, 12, 12, 12), 6)
        top = hbox(spacing=8)
        self.svc = label(batch.service.upper(), "svc")
        self.svc.setStyleSheet(f"color: {SERVICE_COLOUR.get(batch.service, '#8a8f98')};")
        x = button("×", "x", lambda: self.remove.emit(self.batch_id)); x.setToolTip("Remove this batch from the list")
        top.addWidget(self.svc); top.addStretch(1); top.addWidget(x)
        lay.addLayout(top)
        self.name = label(batch.name, "cardtitle"); self.name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.name.setToolTip(batch.name)
        lay.addWidget(self.name)
        self.meta = label("", "faint"); lay.addWidget(self.meta)
        self.bar = _bar(0, 1); lay.addWidget(self.bar)
        self.update_from(batch)

    def update_from(self, b: Batch):
        n = len(b.items)
        bits = [f"{n} track{'s' if n != 1 else ''}"]
        if b.count("found", "queued", "turn"):
            bits.append(f"{b.count('found', 'queued')} found")
        if b.count("waiting", "searching"):
            bits.append(f"{b.count('waiting', 'searching')} to go")
        self.meta.setText(" · ".join(bits))
        self.bar.setRange(0, max(1, n)); self.bar.setValue(b.done)

    def set_selected(self, on: bool):
        self.setProperty("selected", "true" if on else "false"); T.repolish(self)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.batch_id)


class TrackRow(QFrame):
    """One track. Click it to see the other copies that were found and swap to one; press Found, then
    Download?, to get just this track."""
    toggled = Signal(int)                  # row index: open / close the drop-down
    chosen = Signal(int, int)              # row index, alternative index
    download = Signal(int)                 # row index

    def __init__(self, n: int):
        super().__init__()
        self.index = n - 1
        self.setObjectName("trow")
        outer = vbox(self, (0, 0, 0, 0), 0)
        head = QWidget(); outer.addWidget(head); self.head = head
        lay = hbox(head, (6, 10, 6, 10), 14)
        self.num = label(f"{n:02d}", "mono"); self.num.setFixedWidth(26); lay.addWidget(self.num)
        names = vbox(spacing=1)
        self.title = label("", "rowtitle"); self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.artist = label("", "faint")
        names.addWidget(self.title); names.addWidget(self.artist)
        lay.addLayout(names, 1)
        self.pick = label("", "fmt"); lay.addWidget(self.pick)
        self.avail = label("", "muted"); self.avail.setFixedWidth(150); self.avail.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.avail)
        self.status = label("", "pill"); self.status.setFixedWidth(118); self.status.setAlignment(Qt.AlignCenter)
        self.go = button("Found", "pillbtn", self._go); self.go.setFixedWidth(118)
        lay.addWidget(self.status); lay.addWidget(self.go)
        self._armed = False
        self.drop = QFrame(); self.drop.setObjectName("trowdrop"); self.drop.hide()
        self.drop_lay = vbox(self.drop, (46, 4, 6, 10), 2)
        outer.addWidget(self.drop)
        self._alts: list = []
        self._item = self._drop_for = None

    def _go(self):
        if not self._armed:                     # first press: ask
            self._armed = True
            self.go.setText("Download?"); self.go.setProperty("armed", True); T.repolish(self.go)
            self.go.setToolTip("Press again to download this track; it's checked before it reaches your library")
            return
        self._disarm()
        self.download.emit(self.index)

    def _disarm(self):
        self._armed = False
        self.go.setText("Found"); self.go.setProperty("armed", False); T.repolish(self.go)
        self.go.setToolTip("Press to download just this track")

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and len(self._alts) > 1 and e.position().y() <= self.head.height():
            self.toggled.emit(self.index)
        super().mouseReleaseEvent(e)

    def set_open(self, on: bool):
        on = on and len(self._alts) > 1
        if on and self._drop_for is not self._item:            # the copies list is only built when it's opened
            self._fill_drop(self._item)
            self._drop_for = self._item
        self.drop.setVisible(on)

    def _fill_drop(self, it):
        while self.drop_lay.count():
            w = self.drop_lay.takeAt(0).widget()
            if w:
                w.hide(); w.deleteLater()
        if len(self._alts) <= 1:
            return
        self.drop_lay.addWidget(label("OTHER COPIES · click one to use it instead", "tag"))
        from ..core.availability import availability
        from ..core.batch_runner import describe_pick
        for j, c in enumerate(self._alts):
            mine = c is it.pick
            speed = f"{c.upload_speed / 1e6:.1f} MB/s" if c.upload_speed else "speed unknown"
            text = f"{'●' if mine else '○'}  {describe_pick(c)}  ·  {availability(c).label}  ·  {speed}  ·  {c.user}"
            b = button(text, "altrow", lambda _=False, j=j: self.chosen.emit(self.index, j))
            b.setProperty("current", mine); b.setEnabled(not mine); b.setFixedHeight(26)
            self.drop_lay.addWidget(b)

    def update_from(self, it):
        w = it.wanted
        self.title.setText(f"{w.title}  ({w.mix})" if w.mix else w.title); self.title.setToolTip(w.label)
        self.artist.setText(w.artist or "Unknown artist")
        pick = it.detail if it.status in ("found", "queued", "turn") else ""
        self.pick.setText(pick); self.pick.setVisible(bool(pick))
        self.avail.setText(it.avail if it.status in ("found", "queued", "turn") else (it.detail if it.status in ("not_found", "have", "error") else ""))
        word, tone = STATUS.get(it.status, (it.status, "muted"))
        self.status.setText(word); self.status.setProperty("tone", tone); T.repolish(self.status)
        found = it.status == "found" and it.pick is not None
        self.go.setVisible(found); self.status.setVisible(not found)
        if not found:
            self._disarm()
        self._alts = list(it.alts or []) if found else []
        self.setCursor(Qt.PointingHandCursor if len(self._alts) > 1 else Qt.ArrowCursor)
        self.setToolTip("Click to see the other copies found" if len(self._alts) > 1 else "")
        was_open = self.drop.isVisible()
        self._item, self._drop_for = it, None                  # rebuilt next time it opens (or now, if open)
        self.set_open(was_open)


class LinkBox(QPlainTextEdit):
    """Enter adds the playlist; Shift+Enter starts a new line (for typing a list of tracks by hand).
    A pasted multi-line list keeps its lines."""
    submit = Signal()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            self.submit.emit(); e.accept(); return
        super().keyPressEvent(e)


class BatchPage(QWidget):
    start = Signal(str)                 # pasted text or link
    choose_folder = Signal()
    stop = Signal()
    download_all = Signal(str)          # batch id
    download_one = Signal(str, int)     # batch id, track index
    changed = Signal(str)               # batch id (a pick was swapped)
    removed = Signal(str)               # batch id

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        self.batches: list[Batch] = []
        self.selected: str | None = None
        self._cards: dict[str, BatchCard] = {}
        self._rows: list[TrackRow] = []
        root = vbox(self, (36, 28, 36, 24), 18)

        head = hbox(spacing=12)
        head.addWidget(label("Batch", "pagetitle"), 0, Qt.AlignBottom)
        head.addStretch(1)
        root.addLayout(head)
        r_ = QFrame(); r_.setObjectName("mastRule"); r_.setFixedHeight(3); root.addWidget(r_)   # the masthead rule, like The Dig.

        # add a playlist: link or list, or a folder; or drag a link onto the window
        add = QFrame(); add.setObjectName("dropzone")
        al = hbox(add, (14, 12, 12, 12), 12)
        self.input = LinkBox(); self.input.setObjectName("bare"); self.input.setFixedHeight(48)
        self.input.submit.connect(self._go)
        self.input.setPlaceholderText("Paste a YouTube, SoundCloud, Spotify or Apple Music playlist link and press Enter, "
                                      "or a list of tracks (Artist - Title; Shift+Enter for a new line). You can also "
                                      "drag a link onto this window.")
        al.addWidget(self.input, 1)
        self.btn_find = button("Add playlist", "primary", self._go)
        self.btn_folder = button("Folder…", "ghost", self.choose_folder.emit); self.btn_folder.setToolTip(
            "Pick a folder of low-quality files and find better copies of each")
        al.addWidget(self.btn_find, 0, Qt.AlignVCenter); al.addWidget(self.btn_folder, 0, Qt.AlignVCenter)
        root.addWidget(add)
        self.message = label("", "muted", wrap=True); self.message.setVisible(False); root.addWidget(self.message)

        body = hbox(spacing=24); root.addLayout(body, 1)
        # left: one card per playlist
        rail = QWidget(); rail.setObjectName("page"); rail.setFixedWidth(290)
        rl = vbox(rail, spacing=8)
        rl.addWidget(label("YOUR BATCHES", "tag"))
        self.card_host = QWidget(); self.card_host.setObjectName("page")
        self.card_lay = vbox(self.card_host, spacing=8); self.card_lay.addStretch(1)
        rl.addWidget(scroll(self.card_host), 1)
        body.addWidget(rail)

        # right: the selected playlist
        self.detail = QWidget(); self.detail.setObjectName("page")
        dl = vbox(self.detail, spacing=14)
        th = hbox(spacing=10)
        self.d_svc = label("", "svc"); th.addWidget(self.d_svc, 0, Qt.AlignVCenter); th.addStretch(1)
        self.btn_stop = button("Pause", "ghost", self.stop.emit)
        self.btn_all = button("Download and check", "primary", lambda: self.selected and self.download_all.emit(self.selected))
        th.addWidget(self.btn_stop); th.addWidget(self.btn_all)
        dl.addLayout(th)
        self.d_title = label("", "h1"); self.d_title.setWordWrap(True); dl.addWidget(self.d_title)
        tiles = hbox(spacing=12)
        self.tiles = {}
        for key, text in (("found", "Found"), ("left", "To go"), ("have", "Already have"), ("missing", "Not found")):
            f = QFrame(); f.setObjectName("stat"); fl = vbox(f, (16, 12, 16, 12), 2)
            num = label("0", "statnum"); fl.addWidget(num); fl.addWidget(label(text.upper(), "tag"))
            self.tiles[key] = num; tiles.addWidget(f, 1)
        dl.addLayout(tiles)
        self.d_bar = _bar(0, 1); self.d_bar.setFixedHeight(6); dl.addWidget(self.d_bar)
        self.d_note = label("", "faint", wrap=True); dl.addWidget(self.d_note)
        self.row_host = QWidget(); self.row_host.setObjectName("page")
        self.row_lay = vbox(self.row_host, spacing=0); self.row_lay.addStretch(1)
        dl.addWidget(scroll(self.row_host), 1)
        body.addWidget(self.detail, 1)

        self.empty = label("Drop in a playlist to start. Each playlist you add gets its own batch here, and the tracks you "
                           "keep from it are saved together in a folder with the playlist's name.", "muted", wrap=True)
        self.empty.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        body.addWidget(self.empty, 1)
        self._refresh_visibility()

    # ------------------------------------------------------------------ actions
    def _go(self):
        text = self.input.toPlainText().strip()
        if text:
            self.start.emit(text)

    def take_input(self):
        self.input.clear()

    # ------------------------------------------------------------------ batches
    @property
    def items(self) -> list:
        """The selected batch's items (kept for callers that think in one list)."""
        b = self.batch(self.selected)
        return b.items if b else []

    def batch(self, batch_id: str | None) -> Batch | None:
        return next((b for b in self.batches if b.id == batch_id), None)

    def add_batch(self, b: Batch, select: bool = True) -> None:
        self.batches.insert(0, b)
        card = BatchCard(b); card.clicked.connect(self.select); card.remove.connect(self._remove)
        self._cards[b.id] = card
        self.card_lay.insertWidget(0, card)
        if select or self.selected is None:
            self.select(b.id)
        self._refresh_visibility()

    def _remove(self, batch_id: str):
        b = self.batch(batch_id)
        if not b:
            return
        self.batches.remove(b)
        card = self._cards.pop(batch_id); self.card_lay.removeWidget(card); card.hide(); card.deleteLater()
        if self.selected == batch_id:
            self.selected = None
            if self.batches:
                self.select(self.batches[0].id)
        self._refresh_visibility()
        self.removed.emit(batch_id)

    def select(self, batch_id: str):
        self.selected = batch_id
        for bid, c in self._cards.items():
            c.set_selected(bid == batch_id)
        b = self.batch(batch_id)
        while self.row_lay.count() > 1:
            w = self.row_lay.takeAt(0).widget()
            if w:
                w.hide(); w.deleteLater()      # hidden now (no ghost rows); Qt frees it safely later
        self._rows = []
        if not b:
            return
        self.d_title.setText(b.name)
        self.d_svc.setText(b.service.upper()); self.d_svc.setStyleSheet(f"color: {SERVICE_COLOUR.get(b.service, '#8a8f98')};")
        for i, it in enumerate(b.items):
            r = TrackRow(i + 1); r.update_from(it)
            r.toggled.connect(self._toggle_row); r.chosen.connect(self._choose)
            r.download.connect(lambda idx, bid=b.id: self.download_one.emit(bid, idx))
            self.row_lay.insertWidget(self.row_lay.count() - 1, r); self._rows.append(r)
        self._update_head(b)

    def _toggle_row(self, i: int):
        for j, r in enumerate(self._rows):                   # one drop-down open at a time
            r.set_open(j == i and not r.drop.isVisible())

    def _choose(self, i: int, j: int):
        from ..core.batch_runner import choose
        b = self.batch(self.selected)
        if not b or not (0 <= i < len(b.items)):
            return
        it = b.items[i]
        if it.status != "found" or not it.alts or not (0 <= j < len(it.alts)):
            return
        choose(it, it.alts[j])
        self._rows[i].update_from(it)
        self.changed.emit(b.id)

    def update_item(self, batch_id: str, i: int, it) -> None:
        b = self.batch(batch_id)
        if not b:
            return
        if batch_id in self._cards:
            self._cards[batch_id].update_from(b)
        if batch_id == self.selected and 0 <= i < len(self._rows):
            self._rows[i].update_from(it)
            self._update_head(b)

    def _update_head(self, b: Batch):
        self.tiles["found"].setText(str(b.count("found", "queued", "turn")))
        self.tiles["left"].setText(str(b.count("waiting", "searching")))
        self.tiles["have"].setText(str(b.count("have")))
        self.tiles["missing"].setText(str(b.count("not_found", "error")))
        self.d_bar.setRange(0, max(1, len(b.items))); self.d_bar.setValue(b.done)
        found = b.count("found")
        self.btn_all.setText(f"Download and check {found}"); self.btn_all.setVisible(found > 0)

    def set_running(self, running: bool, note: str = "") -> None:
        self.btn_stop.setVisible(running)
        self.d_note.setText(note)

    def show_message(self, text: str) -> None:
        self.message.setText(text); self.message.setVisible(bool(text))

    def set_theme(self, theme: str) -> None:
        pass                                  # colours come from the stylesheet

    def _refresh_visibility(self):
        has = bool(self.batches)
        self.detail.setVisible(has); self.empty.setVisible(not has)
