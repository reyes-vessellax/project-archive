"""The v5 pages: Home (queue + scope + counts), Search results, Review. Pure view code: they read
through ArchiveService and raise signals; MainWindow does the work and calls refresh()."""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QLabel, QProgressBar, QFrame, QGridLayout, QHeaderView, QLineEdit, QSizePolicy, QTreeWidget, QTreeWidgetItem,
                               QWidget)

from ..adapters.base import Candidate, SearchResult
from ..core import jobs as J
from ..core.rules import fmt_time
from ..core.service import ArchiveService
from . import theme as T
from .widgets import KeepColourDelegate, keep_scroll, smooth, LevelStrip, QueueRow, SpectrumView, button, hbox, label, page, rule, scroll, set_tag, vbox


# ------------------------------------------------------------------ shared: a job -> row data
def _audio_path(job: dict) -> str | None:
    """The file to play for a job: the library copy once promoted, else the quarantined copy."""
    for key in ("final_path", "staged_path"):
        v = job.get(key)
        if v and Path(v).exists():
            return v
    return None


def row_data(job: dict, analysis: dict | None, steps: dict[str, str]) -> dict:
    """What the queue shows for one job: tag word, title, artist, progress, meta, removable."""
    st = job["state"]
    name = job["original_name"]
    tags = (analysis or {}).get("facts", {}).get("tags", {}) if analysis else {}
    if tags.get("artist") and tags.get("title"):
        title, artist = tags["title"], tags["artist"]
    else:
        from ..adapters.base import parse_track
        artist, title, mix = parse_track(name)
        title = f"{title}  ·  {mix}" if mix else title
        if not artist and job.get("remote_user"):
            artist = ""
    if st == J.QUEUED:
        return dict(tag="Down", title=title, artist=artist, pct=job.get("progress") or 0, meta="", removable=True)        # no engine status text
    if st == J.STAGING:
        return dict(tag="Check", title=title, artist=artist, pct=0, meta="", removable=False)
    if st == J.ANALYZING:
        step = steps.get(job["id"])
        return dict(tag="Check" if step else "Wait", title=title, artist=artist, pct=None, meta="", removable=False)
    if st == J.READY and analysis:
        # no "CLUB ✓ 1411 kbps" here: it squeezed the title out in a narrow window, and it's all in the details
        return dict(tag=T.GRADE_WORD[T.grade(analysis)], title=title, artist=artist, pct=100, meta="", removable=True)
    if st == J.PROMOTED:
        return dict(tag="Done", title=title, artist=artist, pct=None, meta="in library", removable=True)
    if st == J.ERROR:
        msg = (job.get("message") or "error")
        short = "download failed" if "ownload" in msg else ("couldn't stage" if "stage" in msg else ("check failed" if "nalysis" in msg else "error"))
        return dict(tag="Error", title=title, artist=artist, pct=None, meta=short, removable=True)
    return dict(tag="Gone", title=title, artist=artist, pct=None,
                meta={J.REJECTED: "deleted", J.CANCELLED: "cancelled", J.EXPIRED: "expired"}.get(st, st.lower()), removable=True)


# ------------------------------------------------------------------ home
class HomePage(QWidget):
    search = Signal(str)
    open_job = Signal(str)
    remove_job = Signal(str)
    clear_finished = Signal()
    review_all = Signal()
    add_files = Signal()

    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        self.steps: dict[str, str] = {}
        outer, lay = page()
        root = vbox(self); root.addWidget(outer)

        # search headline
        # The Queue tab (it was Home until Discover took that spot): downloads, checks, what's waiting for you.
        srow = hbox(spacing=16)
        tcol = vbox(spacing=2)
        tcol.addWidget(label("Queue", "pagetitle"))
        srow.addLayout(tcol, 1)
        self.q = QLineEdit(); self.q.hide()                  # kept for the window's search wiring; search lives on Discover/Search
        self.search_btn = button("Search", "accent", lambda: self.search.emit(self.q.text())); self.search_btn.hide()
        self.add_btn = button("Add files", "ghost", self.add_files.emit)
        srow.addWidget(self.add_btn)
        lay.addLayout(srow)
        r_ = QFrame(); r_.setObjectName("mastRule"); r_.setFixedHeight(3); lay.addWidget(r_)   # the masthead rule, like The Dig.

        body = hbox(spacing=40)
        lay.addLayout(body, 1)

        # queue column
        qcol = vbox(spacing=6)
        head = hbox(spacing=12); head.addWidget(label("Tracks", "h2")); head.addStretch(1)
        self.qnote = label("newest first", "faint"); head.addWidget(self.qnote)
        self.qnote.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)   # clips in a narrow list, never lands on its neighbours
        self.qnote.setAlignment(Qt.AlignRight | Qt.AlignVCenter); head.setStretch(1, 0); head.setStretch(2, 1)
        self.clear_btn = button("Clear finished", "link", self.clear_finished.emit); head.addWidget(self.clear_btn)
        qcol.addLayout(head)
        self.list_host = QWidget(); self.list_host.setObjectName("page")
        self.list = vbox(self.list_host, spacing=0); self.list.addStretch(1)
        self.list_scroll = scroll(self.list_host); qcol.addWidget(self.list_scroll, 1)
        self._queue_limit = QUEUE_ROWS
        self.more_btn = button("", "link", self._show_more); self.more_btn.hide()
        qcol.addWidget(self.more_btn, 0, Qt.AlignLeft)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)     # the list never scrolls sideways
        self.empty = label("Nothing in the queue. Find something on Discover or Search, or drop tracks onto the window.", "faint", wrap=True)
        qcol.addWidget(self.empty)
        qw = QWidget(); qw.setLayout(qcol); qw.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        body.addWidget(qw, 3)

        # right rail: scope + counts
        rail = vbox(spacing=18)
        scope_head = hbox(); scope_head.addWidget(label("Last checked", "h2")); scope_head.addStretch(1)
        self.scope_name = label("", "muted"); scope_head.addWidget(self.scope_name)
        rail.addLayout(scope_head)
        self.scope = SpectrumView(150); rail.addWidget(self.scope)
        facts = QGridLayout(); facts.setHorizontalSpacing(12); facts.setVerticalSpacing(2)
        self.fact_vals = {}
        for i, k in enumerate(("Format", "Bitrate", "Rate", "Length")):
            facts.addWidget(label(k.upper(), "tag"), 0, i)
            v = label("–", "monotext"); facts.addWidget(v, 1, i); self.fact_vals[k] = v
        rail.addLayout(facts)
        rail.addWidget(label("Ready for you", "h2"))
        counts = hbox(spacing=10)
        self.counts = {}
        for word, long in (("Good", "Good"), ("Look", "Have a look"), ("Broken", "Broken")):
            card = QFrame(); card.setObjectName("card"); card.setProperty("tag", word)   # coloured edge per verdict
            cl = vbox(card, (14, 12, 14, 12), 6)
            n = label("0", "count", word); cl.addWidget(n)
            cl.addWidget(label(long, "muted"))
            counts.addWidget(card); self.counts[word] = n
        rail.addLayout(counts)
        self.review_btn = button("Review 0 tracks →", "primary", self.review_all.emit)
        rail.addWidget(self.review_btn)
        rail.addStretch(1)
        rw = QWidget(); rw.setLayout(rail); rw.setMinimumWidth(320); rw.setMaximumWidth(420)
        body.addWidget(rw, 2)
        rw.hide()                                         # replaced by the selected track's details, right here
        self.detail_slot = vbox(spacing=0)
        body.addLayout(self.detail_slot, 4)

    def _show_more(self):
        self._queue_limit += QUEUE_ROWS
        self._last_key = None
        if hasattr(self, "_last_args"):
            self.refresh(*self._last_args)

    def set_connected(self, on: bool, message: str = ""):
        self.q.setEnabled(on)
        self.q.setPlaceholderText("Search for a track…" if on else (message or "Connecting…"))
        self.search_btn.setEnabled(on)

    def _mark_playing(self, *_):
        from .player import Player
        pl = Player.get()
        playing = pl.media is not None and pl.playing()
        for jid, row in getattr(self, "_row_widgets", {}).items():
            try:
                row.set_playing(bool(playing and pl.owns(self._audio_of.get(jid))))
            except RuntimeError:
                pass

    def refresh(self, jobs: list[dict], analyses: dict[str, dict | None]):
        # Rebuild the row widgets only when something visible changed; refresh() fires every poll.
        self._last_args = (jobs, analyses)
        self._audio_of = {j["id"]: j.get("final_path") or j.get("staged_path") for j in jobs}
        if not getattr(self, "_np_hooked", False):           # ♫ follows the player, whichever row is open
            from .player import Player
            Player.get().changed.connect(self._mark_playing); self._np_hooked = True
        rows = [(j["id"], row_data(j, analyses.get(j["id"]), self.steps)) for j in jobs]
        key = tuple((jid, d["tag"], d["title"], d["artist"], d["pct"], d["meta"], d["removable"]) for jid, d in rows)
        if key == getattr(self, "_last_key", None):
            return
        self._last_key = key
        prev_tags = getattr(self, "_prev_tags", {})
        changed = {jid for jid, d in rows if jid in prev_tags and prev_tags[jid] != d["tag"]}
        self._prev_tags = {jid: d["tag"] for jid, d in rows}
        # queue list: rows that already exist are updated in place, only new ones are built, and only the newest
        # QUEUE_ROWS are shown (a long history used to rebuild hundreds of rows on every 2-second poll)
        shown = rows[: self._queue_limit]
        self.more_btn.setVisible(len(rows) > len(shown))
        self.more_btn.setText(f"Show {len(rows) - len(shown)} older")
        existing: dict = getattr(self, "_row_widgets", {})
        wanted = [jid for jid, _ in shown]

        def rebuild():
            self.list_host.setUpdatesEnabled(False)
            keep = set(wanted)
            for jid in list(existing):
                if jid not in keep:
                    w = existing.pop(jid)
                    self.list.removeWidget(w); w.hide(); w.deleteLater()   # hidden now: no ghost rows
            order_now = [self.list.itemAt(i).widget().job_id for i in range(self.list.count() - 1)
                         if self.list.itemAt(i).widget() is not None]
            for jid, d in shown:
                row = existing.get(jid)
                if row is None:
                    row = QueueRow(jid, d["tag"], d["title"], d["artist"], d["pct"], d["meta"], d["removable"])
                    row.clicked.connect(self.open_job.emit); row.removed.connect(self.remove_job.emit)
                    existing[jid] = row
                else:
                    row.update_to(d["tag"], d["title"], d["artist"], d["pct"], d["meta"], d["removable"])
                if jid in changed:
                    row.flash()                               # the blip: this track just moved on
            if order_now != wanted:                           # new arrivals or a reorder: lay the rows out again
                for jid in wanted:
                    self.list.removeWidget(existing[jid])
                for i, jid in enumerate(wanted):
                    self.list.insertWidget(i, existing[jid])
            self.empty.setVisible(not jobs)
            self.list_host.setUpdatesEnabled(True)
        self._row_widgets = existing
        sel = getattr(self, "selected_id", None)                  # keep the open track highlighted after a refresh
        for jid, row in existing.items():
            row.set_selected(jid == sel)
        keep_scroll(self.list_scroll, rebuild)
        self._mark_playing()
        down = sum(1 for j in jobs if j["state"] == J.QUEUED)
        chk = sum(1 for j in jobs if j["state"] in (J.STAGING, J.ANALYZING))
        self.qnote.setText(f"{down} downloading · {chk} checking" if (down or chk) else "newest first")
        self.clear_btn.setVisible(any(j["state"] in J.FINAL or j["state"] == J.ERROR for j in jobs))
        # counts
        n = {"Good": 0, "Look": 0, "Broken": 0}
        for j in jobs:
            a = analyses.get(j["id"])
            if j["state"] == J.READY and a:
                g = T.grade(a)
                n[T.GRADE_WORD["FAIL" if g == "CLUB" else g]] += 1     # not club-ready counts with the unusable
        for k, v in n.items():
            self.counts[k].setText(str(v))
        total = sum(n.values())
        self.review_btn.setText(f"Review {total} track{'s' if total != 1 else ''} →" if total else "Nothing to review yet")
        self.review_btn.setEnabled(bool(total))
        # scope: most recent analysed track with a spectrogram
        for j in jobs:
            a = analyses.get(j["id"])
            if a and a.get("spectrogram_path") and Path(a["spectrogram_path"]).exists():
                f = a["facts"]
                self.scope_name.setText(row_data(j, a, self.steps)["title"])
                self.scope.show_png(a["spectrogram_path"], f.get("sample_rate_hz"), a.get("cutoff_hz"),
                                    audio=_audio_path(j), duration_s=f.get("duration_s"))
                self.fact_vals["Format"].setText((f.get("container") or "?").upper())
                self.fact_vals["Bitrate"].setText(_bitrate(f))
                self.fact_vals["Rate"].setText(f"{f['sample_rate_hz'] / 1000:g} kHz" if f.get("sample_rate_hz") else "?")
                self.fact_vals["Length"].setText(fmt_time(f["duration_s"]) if f.get("duration_s") else "?")
                break
        else:
            self.scope_name.setText("")
            self.scope.clear_view("The spectrogram of your most recent check appears here.")
            for v in self.fact_vals.values():
                v.setText("–")


QUEUE_ROWS = 150


def _bitrate(f: dict) -> str:
    if not f.get("bitrate_bps"):
        return "lossless" if f.get("lossless") else "?"
    mode = f.get("bitrate_mode")
    return f"{round(f['bitrate_bps'] / 1000)} {mode if mode in ('CBR', 'VBR') else 'kbps'}"


# ------------------------------------------------------------------ search results
MAX_ROWS = 400          # kept for callers; the list now pages
PAGE_ROWS = 100


class SearchPage(QWidget):
    search = Signal(str)
    filters_changed = Signal()
    preview = Signal(object)          # Candidate: download it and play 20 s from the drop
    watch = Signal(str, str, str)     # artist, title, mix: a standing search on the Wishlist
    stop_preview = Signal()

    def _theme(self) -> str:
        return getattr(self.svc.settings, "theme", "light")
    pick = Signal(object)        # Candidate
    COLS = ["#", "Title", "Mix", "Artist", "Folder", "User", "Size", "Rate", "Length", "Availability", "Source"]
    WIDTHS = [36, 170, 110, 130, 80, 125, 70, 56, 56, 170, 64]

    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        outer, lay = page(spacing=18)
        root = vbox(self); root.addWidget(outer)
        # masthead, like every page: the big title, the thick rule, a line about where results come from
        mh = hbox(spacing=16)
        mh.addWidget(label("Search", "pagetitle"), 0, Qt.AlignBottom); mh.addStretch(1)
        mh.addWidget(label("EVERYONE'S LIBRARIES · FASTEST AND BEST FIRST", "strap"), 0, Qt.AlignBottom)
        lay.addLayout(mh)
        r_ = QFrame(); r_.setObjectName("mastRule"); r_.setFixedHeight(3); lay.addWidget(r_)
        srow = hbox(spacing=12)
        self.q = QLineEdit(); self.q.setObjectName("searchbar"); self.q.setPlaceholderText("Artist, track, label or mix…")
        self.q.returnPressed.connect(lambda: self.search.emit(self.q.text()))
        srow.addWidget(self.q, 1)
        self.search_btn = button("Search", "accent", lambda: self.search.emit(self.q.text()))
        self.search_btn.setFixedHeight(56); self.search_btn.setMinimumWidth(120)   # as tall as the search box
        srow.addWidget(self.search_btn)
        self.watch_btn = button("Watch this search", "ghost", self._toggle_watch)
        self.watch_btn.setToolTip("Nobody has it? Keep asking every half hour for 30 days and tell me when it shows up.")
        self.watch_btn.setEnabled(False); self.q.textChanged.connect(lambda t: self.watch_btn.setEnabled(bool(t.strip())))
        srow.addWidget(self.watch_btn)
        self.watch_btn.hide()        # only after a search that found nothing downloadable: if it's there, just get it
        lay.addLayout(srow)
        from .wishlist_page import WishForm
        self.wish_form = WishForm("Watch for this track. Fill in what you know, as much or as little as you like.")
        self.wish_form.hide()
        self.wish_form.submitted.connect(self._watch_go); self.wish_form.cancelled.connect(self.wish_form.hide)
        lay.addWidget(self.wish_form)
        head = hbox(spacing=12)
        self.title = label("", "secTitle"); head.addWidget(self.title)
        _set_title = self.title.setText

        def _title(t, _set=_set_title):                       # no empty heading taking up a line before a search
            _set(t); self.title.setVisible(bool(t))
        self.title.setText = _title
        self._head_row = head
        self.state = label("", "faint"); head.addWidget(self.state); head.addStretch(1)
        head_w = QWidget(); head_w.setLayout(head); lay.addWidget(head_w)
        _set_state = self.state.setText

        def _state(t, _set=_set_state):                       # the whole heading line only takes room when it says something
            _set(t); head_w.setVisible(bool(t) or bool(self.title.text()))
        self.state.setText = _state
        _set_t2 = self.title.setText

        def _title2(t, _set=_set_t2):
            _set(t); head_w.setVisible(bool(t) or bool(self.state.text()))
        self.title.setText = _title2
        head_w.hide()
        # filters: a file-type drop-down, Lossless, 320 only (MP3s), ready now, private
        from PySide6.QtWidgets import QComboBox
        from ..core.availability import FORMATS, Filters
        self.filters = Filters()
        fr = hbox(spacing=8)
        self.fmt_box = QComboBox()
        self.fmt_box.addItem("Any file type", "")
        for key, text in FORMATS:
            self.fmt_box.addItem(text, key)
        self.fmt_box.setToolTip("Show only one file type")
        self.fmt_box.currentIndexChanged.connect(lambda _: self._set_format(self.fmt_box.currentData()))
        fr.addWidget(self.fmt_box)
        self._fbtns = {}
        for key, text, tip in (("lossless", "Lossless", "FLAC, WAV and AIFF only"),
                               ("mp3_320", "320 only", "MP3s must say 320 kbps (the check confirms it after download)"),
                               ("ready_now", "Ready now", "Only sources with a free slot right now"),
                               ("club_length", "4 min+", "Club length: 4 minutes or longer, no radio or short edits"),
                               ("show_private", "Show private", "Include folders their owner only shares with friends")):
            b = button(text, "chip", lambda _=False, k=key: self._toggle_filter(k)); b.setCheckable(True)
            b.setToolTip(tip)
            self._fbtns[key] = b; fr.addWidget(b)
        fr.addStretch(1)
        self.hidden_note = label("", "faint"); fr.addWidget(self.hidden_note)
        lay.addLayout(fr)
        self._last_res = None; self._last_searching = False
        self.tree = QTreeWidget(); self.tree.setColumnCount(len(self.COLS)); self.tree.setHeaderLabels(self.COLS)
        self.tree.setItemDelegate(KeepColourDelegate(self.tree))
        self.tree.setRootIsDecorated(False); self.tree.setSortingEnabled(False); self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionBehavior(QTreeWidget.SelectRows)
        hdr = self.tree.header(); hdr.setSectionResizeMode(QHeaderView.Fixed); hdr.setStretchLastSection(False)
        for i, w in enumerate(self.WIDTHS):
            self.tree.setColumnWidth(i, w)
        # Columns are fixed (dragging a border squashed the others): Title, Folder and Availability share the
        # slack, so the table always fills its width and never scrolls sideways.
        for c in ("Title", "Folder", "Availability"):
            hdr.setSectionResizeMode(self.COLS.index(c), QHeaderView.Stretch)
        hdr.setMinimumSectionSize(self.MIN_COL); hdr.setSectionsMovable(False)
        self._fitting = False
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)     # never sideways (the user asked)
        self.tree.setTextElideMode(Qt.ElideRight)
        # click a heading to sort by it (again to flip); # puts the list back to best first
        self._sort: tuple[int, bool] | None = None
        hdr = self.tree.header(); hdr.setSectionsClickable(True); hdr.setSortIndicatorShown(True)
        hdr.setSortIndicator(0, Qt.AscendingOrder); hdr.sectionClicked.connect(self.sort_by)
        self.tree.itemDoubleClicked.connect(lambda *_: self._pick())
        self.tree.itemSelectionChanged.connect(self._selection)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.verticalScrollBar().valueChanged.connect(self._scrolled)
        smooth(self.tree)
        lay.addWidget(self.tree, 1)
        # empty-state message sits where the rows would be, not up by the search bar
        self.empty = label("", "muted", wrap=True); self.empty.setParent(self.tree.viewport())
        self.empty.setAlignment(Qt.AlignCenter); self.empty.setStyleSheet("font-size: 15px; background: transparent;")
        self.empty.hide()
        self._ranked: list[Candidate] = []
        self._shown = 0
        self._more_item: QTreeWidgetItem | None = None
        self._foot_item: QTreeWidgetItem | None = None
        self._phrases = ("Asking around", "Knocking on doors", "Still looking", "One second", "Checking the far corners",
                         "Waiting on the slow ones", "Almost there")
        self._anim_i = 0; self._anim_dots = 0; self._anim_query = ""
        self._anim = QTimer(self, interval=400, timeout=self._animate)
        self.tree.viewport().installEventFilter(self)
        row = hbox(spacing=12)
        self.btn = button("Check this file", "primary", self._pick); self.btn.setEnabled(False)
        self.btn_pv = button("▶  Preview", "ghost", self._preview_clicked); self.btn_pv.setEnabled(False)
        self.btn_pv.setToolTip("Plays about 20 seconds from the middle. Only those seconds are fetched, and nothing is kept.")
        row.addWidget(self.btn); row.addWidget(self.btn_pv)
        self.pv_note = label(self.PV_NOTE, "faint", wrap=True)
        row.addWidget(self.pv_note, 1)
        self._previewing = False
        # the actions sit right above the results, next to what you picked, not at the far bottom of the page
        lay.insertLayout(lay.indexOf(self.tree), row)

    def set_connected(self, on: bool):
        self.q.setEnabled(on); self.search_btn.setEnabled(on and not self._anim.isActive())
        self.btn.setEnabled(on and bool(self.tree.selectedItems()))

    def set_problem_sources(self, keys: dict[str, str]):
        """remote key -> short reason, for sources that already failed us (download errored, rejected, etc.)."""
        self._problems = keys

    def eventFilter(self, obj, ev):
        if obj is self.tree.viewport() and ev.type() == QEvent.Resize:
            self.empty.setGeometry(self.tree.viewport().rect().adjusted(40, 0, -40, 0))
            self._fit_columns()
        return False

    # ------------------------------------------------------------ column widths
    FLEX = ("Title", "Folder", "Availability")       # these absorb what the others don't use
    MIN_COL = 34

    def _col_resized(self, col: int, _old: int, _new: int):
        if not self._fitting:
            self._fit_columns(dragged=col)

    def _fit_columns(self, dragged: int | None = None):
        """Make the columns add up to the table's width. The slack goes to the flexible columns (right of the
        dragged one first), then to any other column to its right; if nothing can give, the drag stops there."""
        hdr = self.tree.header()
        width = self.tree.viewport().width()
        if width <= 0 or self._fitting:
            return
        self._fitting = True
        try:
            n = len(self.COLS)
            w = [hdr.sectionSize(i) for i in range(n)]
            flex = [self.COLS.index(c) for c in self.FLEX]
            start = (dragged + 1) if dragged is not None else 0
            order = ([i for i in flex if i >= start and i != dragged] + [i for i in range(start, n) if i not in flex and i != dragged]
                     + [i for i in flex if i < start and i != dragged])
            delta = width - sum(w)
            if delta > 0:                                             # room to spare: share it between the flexible ones
                takers = [i for i in order if i in flex] or order
                for k, i in enumerate(takers):
                    add = delta // (len(takers) - k); w[i] += add; delta -= add
            else:
                for i in order:                                       # too wide: take it back, never below the minimum
                    if delta >= 0:
                        break
                    give = min(-delta, max(0, w[i] - self.MIN_COL)); w[i] -= give; delta += give
                if delta < 0 and dragged is not None:                 # nothing left to give: the dragged column stops
                    w[dragged] = max(self.MIN_COL, w[dragged] + delta)
            for i in range(n):
                if hdr.sectionSize(i) != w[i]:
                    hdr.resizeSection(i, w[i])
        finally:
            self._fitting = False

    def _show_empty(self, text: str):
        if text:                                             # our mark above the message, not just grey text
            from pathlib import Path as _P
            from . import widgets as _w
            mark = _P(__file__).parent / "brand_assets" / ("digmart-mark-dark.png" if _w.FX_THEME == "dark" else "digmart-mark.png")
            self.empty.setTextFormat(Qt.RichText); self.empty.setAlignment(Qt.AlignCenter)
            text = (f"<div align='center'><img src='{mark.as_posix()}' width='120'><br><br>"
                    f"<span style='font-size:17px; font-weight:700'>{html.escape(text).replace(chr(10), '<br>')}</span></div>")
        self.empty.setText(text)
        self.empty.setGeometry(self.tree.viewport().rect().adjusted(40, 0, -40, 0))
        self.empty.setVisible(bool(text)); self.empty.raise_()

    def begin_search(self, query: str):
        """The moment Search is pressed: old rows go, the header names the new query, the text starts moving."""
        self._ranked = []; self._shown = 0
        self._anim_query = query; self._anim_i = 0; self._anim_dots = 0; self._prog = (0, 0, False); self._dropped = ""
        self._fill(0)
        self.title.setText(f"Searching for “{query}”")
        self.state.setText("")
        self.search_btn.setText("Searching…"); self.search_btn.setEnabled(False)
        self._animate(); self._anim.start()

    def set_progress(self, responses: int, files: int, more: bool):
        self._prog = (responses, files, more)

    def _set_foot(self, dots: str = "…"):
        """The last row of the list: what's still happening, or that nothing more is coming."""
        if self._foot_item is None:
            return
        r, f, _ = getattr(self, "_prog", (0, 0, False))
        n = len(self._ranked)
        if self._anim.isActive():
            found = f" · {r} user{'s' if r != 1 else ''} · {f} file{'s' if f != 1 else ''} so far" if r else ""
            self._foot_item.setText(1, f"Finding more{dots}{found}")
        else:
            self._foot_item.setText(1, f"All results shown · {n} file{'s' if n != 1 else ''}" if n else "")

    def _animate(self):
        self._anim_dots = (self._anim_dots + 1) % 4
        if self._anim_dots == 0:
            self._anim_i = (self._anim_i + 1) % len(self._phrases)
        text = self._phrases[self._anim_i] + "." * (self._anim_dots or 3)
        r, f, more = getattr(self, "_prog", (0, 0, False))
        found = f"{r} user{'s' if r != 1 else ''} · {f} file{'s' if f != 1 else ''} so far" if r else ""
        if not self._ranked:
            self._show_empty(f"{text}\nLooking for “{self._anim_query}”" + (f"\n{found}" if found else ""))
        elif getattr(self, "_dropped", ""):
            pass                                                # the fallback banner stays put
        else:
            self.state.setText(f"fastest first · {text.lower()}")
        self._set_foot("." * (self._anim_dots or 3))

    def end_search(self):
        self._anim.stop()
        self.search_btn.setText("Search"); self.search_btn.setEnabled(self.q.isEnabled())
        self._set_foot()

    # ------------------------------------------------------------------ filters
    def _toggle_filter(self, key: str):
        setattr(self.filters, key, self._fbtns[key].isChecked())
        self._refilter()

    def _set_format(self, key: str):
        self.filters.formats = [key] if key else []
        self._refilter()

    def set_filters(self, d: dict):
        from ..core.availability import Filters
        self.filters = Filters(**{k: v for k, v in (d or {}).items() if k in Filters.__dataclass_fields__})
        self.filters.mix = ""
        if len(self.filters.formats) > 1:
            self.filters.formats = []                       # the drop-down holds one type
        for k, b in self._fbtns.items():
            b.blockSignals(True); b.setChecked(bool(getattr(self.filters, k))); b.blockSignals(False)
        i = self.fmt_box.findData(self.filters.formats[0] if self.filters.formats else "")
        self.fmt_box.blockSignals(True); self.fmt_box.setCurrentIndex(max(0, i)); self.fmt_box.blockSignals(False)

    def _refilter(self):
        if self._last_res is not None:
            self.show_results(self._last_res, self._last_searching, _refilter=True)
        self.filters_changed.emit()

    def show_results(self, res: SearchResult, searching: bool, idle: str = "", _refilter: bool = False):
        if not searching and not _refilter:
            self.end_search()
        if not idle:
            self._last_res, self._last_searching = res, searching
            from dataclasses import replace
            from ..core.availability import apply as apply_filters
            kept, hidden, private = apply_filters(res.candidates, self.filters)
            if getattr(self, "dance_only", False):           # Discover's search: dance and electronic music only
                from ..core.crates import NOT_DANCE
                n0 = len(kept)
                kept = [c for c in kept if not NOT_DANCE.search(c.remote_path or c.display_name or "")]
                hidden += n0 - len(kept)
            bits = ([f"{hidden} hidden by filters"] if hidden else []) + ([f"{private} private hidden"] if private else [])
            self.hidden_note.setText(" · ".join(bits))
            res = replace(res, candidates=kept)
        n = len(res.candidates)
        if idle:
            self.watch_btn.hide()
            self.title.setText(""); self.state.setText(""); self._ranked = []; self._fill(0); self._show_empty(idle); return
        gettable = any(not c.locked and not c.note for c in res.candidates)
        self.watch_btn.setVisible(not searching and not gettable and bool(self.q.text().strip()))
        self.title.setText(f"{n} result{'s' if n != 1 else ''}")
        skipped = sum(1 for c in res.candidates if c.note == "Extension mismatch")
        bots = sum(1 for c in res.candidates if c.note == "Ad bot")
        locked = sum(1 for c in res.candidates if c.locked and not c.note)
        tail = (f" · {skipped} other format{'s' if skipped != 1 else ''} greyed" if skipped else "") + \
               (f" · {locked} locked" if locked else "") + (f" · {bots} ad bot{'s' if bots != 1 else ''}" if bots else "")
        if res.error:
            self.state.setText("")
        elif searching:
            self.state.setText(f"{self._order_name()} · still collecting…" + tail)
        else:
            self.state.setText((self._order_name() + tail) if n else "")
        if n == 0:
            if res.error:
                self._show_empty(res.error)
            elif searching:
                pass                                            # the animation owns the empty area while searching
            else:
                self._show_empty("Nobody online is sharing a match right now.\nTry fewer words, or press “Watch this search” "
                                 "and it will be asked for again every half hour for 30 days.")
        else:
            self._show_empty("")
        selected = self.tree.selectedItems()
        keep = selected[0].data(0, Qt.UserRole).key if selected and isinstance(selected[0].data(0, Qt.UserRole), Candidate) else None
        self._dropped = res.dropped
        reps = self._reps()
        self._ranked = self._sorted(sorted(res.candidates, key=lambda c: _rank(c, res.dropped, reps.get(c.user))))
        if res.dropped:
            self.state.setText(f'Nothing matched “{res.query}” — showing results for “{res.sent}” (without “{res.dropped}”)'
                               + (" · still collecting…" if searching else ""))
        # keep whatever the user has already scrolled open, at least one page
        want = max(PAGE_ROWS, min(self._shown, len(self._ranked)))
        self._fill(want, keep)

    def _reps(self) -> dict:
        try:
            return self.svc.source_reputation()
        except Exception:                                   # reputation is a nicety; never break search over it
            return {}

    def _fill(self, count: int, keep=None):
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        self._more_item = None
        ranked = self._ranked[:count]
        self._shown = len(ranked)
        reps = self._reps()
        items = []
        for i, c in enumerate(ranked):
            it = QTreeWidgetItem([
                f"{i + 1:02d}", c.title or c.display_name, c.mix, c.artist, c.folder, c.user, f"{c.size / 1e6:.1f} MB",
                (f"{c.bitrate_kbps}" + ("v" if c.vbr else "")) if c.bitrate_kbps else (c.extension.upper() if c.extension in ("flac", "wav", "aiff", "aif") else "?"),
                fmt_time(c.length_s) if c.length_s else "?", _speed(c), "",
            ])
            rep = reps.get(c.user)
            if rep is not None:
                it.setText(10, rep.label())
                tone = rep.tone()
                if tone:
                    it.setForeground(10, QColor(T.colours(self._theme())[tone]))
            it.setToolTip(10, rep.sentence() if rep is not None else "You haven't downloaded from this source before.")
            it.setData(0, Qt.UserRole, c)
            it.setToolTip(1, c.display_name)
            it.setToolTip(5, c.user)
            if not (c.locked or c.note):                        # wait in colour: green ready, amber a wait, red hours
                from ..core.availability import availability
                tone = availability(c).tone
                if tone in ("pass_", "warn", "fail"):
                    it.setForeground(9, QColor(T.colours(self._theme())[tone]))
            problem = getattr(self, "_problems", {}).get(c.key)
            if problem:
                red = QColor(T.colours(self._theme())["fail"])
                for col in range(self.tree.columnCount()):
                    it.setForeground(col, red)
                it.setText(9, f"⚠ {problem}")
                it.setToolTip(9, f"This source failed before: {problem}")
            elif c.locked or c.note:
                for col in range(self.tree.columnCount()):
                    it.setForeground(col, self.palette().mid())
                if c.note == "Ad bot":
                    it.setText(9, c.note)
                    it.setToolTip(9, "This account is a web shop's advertising bot. It answers every search and never sends a file.")
                elif c.note:
                    it.setText(9, c.note)
                    it.setToolTip(9, f"{c.note}: .{c.extension or '(none)'} isn't in your accepted formats (Settings → Checks).")
                elif c.locked:
                    it.setToolTip(9, "This user only shares that folder with people on their list. It can't be requested.")
            items.append(it)
        self.tree.addTopLevelItems(items)
        left = len(self._ranked) - self._shown
        self._foot_item = None
        if left <= 0 and (items or self._anim.isActive()):
            foot = QTreeWidgetItem([""] * len(self.COLS))
            foot.setFlags(foot.flags() & ~Qt.ItemIsSelectable)
            foot.setForeground(1, self.palette().mid())
            foot.setFirstColumnSpanned(True) if hasattr(foot, "setFirstColumnSpanned") else None
            self.tree.addTopLevelItem(foot)
            self._foot_item = foot
            self._set_foot()
        if left > 0:
            more = QTreeWidgetItem([""] * len(self.COLS))
            more.setText(1, f"Load {min(PAGE_ROWS, left)} more  ({left} further down the list"
                            + (" · still finding more)" if self._anim.isActive() else " · search finished)"))
            more.setData(0, Qt.UserRole, "more")
            more.setFlags(more.flags() & ~Qt.ItemIsSelectable)
            more.setForeground(1, QColor(T.colours(self._theme())["accent"]))
            font = more.font(1); font.setBold(True); more.setFont(1, font)
            more.setFirstColumnSpanned(True) if hasattr(more, "setFirstColumnSpanned") else None
            self.tree.addTopLevelItem(more)
            self._more_item = more
        for it in items:
            if keep is not None and it.data(0, Qt.UserRole).key == keep:
                it.setSelected(True); break
        self.tree.setUpdatesEnabled(True)

    # ---- column sorting -----------------------------------------------------------------
    NUMERIC = {"Size", "Rate", "Length"}           # big-first on the first click; text columns A→Z first

    def _order_name(self) -> str:
        if not getattr(self, "_sort", None):
            return "fastest first"
        col, desc = self._sort
        name = self.COLS[col].lower()
        if name == "availability":
            return "readiest first" if not desc else "slowest first"
        return f"by {name}" + (" ↓" if desc else " ↑")

    @staticmethod
    def _col_key(name: str):
        from ..core.availability import LOSSLESS, availability
        lossless = lambda c: (c.extension or "").lower() in LOSSLESS
        return {
            "Title": lambda c: (c.title or c.display_name or "").lower(),
            "Mix": lambda c: (c.mix or "").lower(),
            "Artist": lambda c: (c.artist or "").lower(),
            "Folder": lambda c: (c.folder or "").lower(),
            "User": lambda c: (c.user or "").lower(),
            "Size": lambda c: c.size or 0,
            # lossless above lossy, grouped by format (all the WAVs together), then by bitrate
            "Rate": lambda c: (1, (c.extension or "").lower(), 0) if lossless(c) else (0, "", c.bitrate_kbps or 0),
            "Length": lambda c: c.length_s or 0,
            "Availability": lambda c: (availability(c).rank, -(c.upload_speed or 0)),
        }.get(name)

    def _sorted(self, ranked: list) -> list:
        """The chosen column's order over the best-first list. Greyed rows (locked, ad bots, other formats)
        stay at the bottom whatever the sort."""
        if not getattr(self, "_sort", None):
            return ranked
        col, desc = self._sort
        key = self._col_key(self.COLS[col])
        if key is None:
            return ranked
        ok = [c for c in ranked if not (c.locked or c.note)]
        grey = [c for c in ranked if c.locked or c.note]
        return sorted(ok, key=key, reverse=desc) + sorted(grey, key=key, reverse=desc)

    def sort_by(self, col: int):
        """Header click. # = best first; the same heading again flips the direction."""
        hdr = self.tree.header()
        if col <= 0 or col >= len(self.COLS) or self._col_key(self.COLS[col]) is None:
            self._sort = None
            hdr.setSortIndicator(0, Qt.AscendingOrder)
        else:
            desc = (not self._sort[1]) if (self._sort and self._sort[0] == col) else (self.COLS[col] in self.NUMERIC)
            self._sort = (col, desc)
            hdr.setSortIndicator(col, Qt.DescendingOrder if desc else Qt.AscendingOrder)
        if self._last_res is not None:
            self.show_results(self._last_res, self._last_searching, _refilter=True)
            self.tree.verticalScrollBar().setValue(0)

    def load_more(self):
        if self._shown < len(self._ranked):
            selected = self.tree.selectedItems()
            keep = selected[0].data(0, Qt.UserRole).key if selected and isinstance(selected[0].data(0, Qt.UserRole), Candidate) else None
            at = self.tree.verticalScrollBar().value()
            self._fill(self._shown + PAGE_ROWS, keep)
            self.tree.verticalScrollBar().setValue(at)

    def _clicked(self, item, _col):
        if item is self._more_item:
            self.load_more()

    def _scrolled(self, value: int):
        bar = self.tree.verticalScrollBar()
        if self._more_item is not None and bar.maximum() > 0 and value >= bar.maximum():
            self.load_more()

    def _toggle_watch(self):
        if self.wish_form.isVisible():
            self.wish_form.hide(); return
        self.wish_form.prefill(self.q.text()); self.wish_form.show()

    def _watch_go(self, artist: str, title: str, mix: str):
        self.wish_form.hide()
        self.watch.emit(artist, title, mix)

    PV_NOTE = "Preview fetches only the seconds it plays. Check this file downloads it into quarantine; nothing reaches your library until you decide."

    def _selection(self):
        items = self.tree.selectedItems()
        c = items[0].data(0, Qt.UserRole) if items else None
        ok = isinstance(c, Candidate) and not c.note and not c.locked
        self.btn.setEnabled(ok)
        self._pv_ok = ok          # any usable row; a copy that turns out busy is swapped for another ready one
        self.btn_pv.setEnabled(self._previewing or self._pv_ok)
        self.btn_pv.setToolTip("Plays about 20 seconds from the middle. Only those seconds are fetched, and nothing is kept."
                               if self._pv_ok or not ok else "This copy can't be previewed.")
        # already have it? (same remote file, or same artist + title in the library or the queue)
        self._armed_key = None
        have = None
        if ok and hasattr(self.svc, "already_have"):
            try:
                have = self.svc.already_have(c)
            except Exception:
                have = None
        self._have = have
        if have:
            kb = "lossless" if have["lossless"] else (f"{have['kbps']} kbps" if have["kbps"] else "")
            where = "in your library" if have["where"] == "library" else "already in the queue"
            self.pv_note.setText(f"You may already have this: “{_short(have['name'])}” is {where}"
                                 + (f" · {kb}" if kb else "") + (f" · {have['when']}" if have["when"] else "")
                                 + ". Click again to check this one anyway.")
            self.btn.setObjectName("ghost")
        else:
            if not self._previewing:
                self.pv_note.setText(self.PV_NOTE)
            self.btn.setObjectName("primary")
        self.btn.setText("Check this file")
        T.repolish(self.btn)

    def _preview_clicked(self):
        if self._previewing:
            self.stop_preview.emit(); return
        items = self.tree.selectedItems()
        if items and isinstance(items[0].data(0, Qt.UserRole), Candidate):
            self.preview.emit(items[0].data(0, Qt.UserRole))

    def mark_busy(self, cand) -> None:
        """A copy that said "Ready now" queued us when asked: show it as waiting, and stop offering a preview."""
        if cand is None:
            return
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            c = it.data(0, Qt.UserRole)
            if isinstance(c, Candidate) and c.key == cand.key:
                c.free_slot, c.queue_length = False, max(1, c.queue_length or 0)
                it.setText(9, "Busy now · queued you")
                it.setForeground(9, QColor(T.colours(self._theme())["warn"]))
                it.setToolTip(9, "It was ready when you searched; when asked, the sharer put you in their line.")
                if it.isSelected():
                    self._selection()
                break

    def ready_alternative(self, cand, tried: set):
        """Another copy of the same track (same title and mix, same artist) that says it's ready, fastest first."""
        def norm(x):
            return " ".join((x or "").lower().split())
        same = [c for c in self._ranked if isinstance(c, Candidate) and c.key not in tried and c.free_slot
                and not (c.queue_length or 0) and not c.locked and not c.note
                and norm(c.title) == norm(cand.title) and norm(c.mix) == norm(cand.mix)
                and norm(c.artist) == norm(cand.artist)
                and (c.extension or "").lower() in {e.lower().lstrip(".") for e in self.svc.settings.extensions}]
        return max(same, key=lambda c: c.upload_speed or 0) if same else None

    def set_preview_state(self, state: str, text: str = ""):
        """state: '' (idle), 'loading' (downloading + checking), 'playing'."""
        self._previewing = state == "playing"
        self.btn_pv.setText({"loading": "Getting preview…", "playing": "■  Stop"}.get(state, "▶  Preview"))
        self.btn_pv.setEnabled(state != "loading" and (state == "playing" or getattr(self, "_pv_ok", False)))
        self.pv_note.setText(text or self.PV_NOTE)

    def _pick(self):
        items = self.tree.selectedItems()
        if not (items and isinstance(items[0].data(0, Qt.UserRole), Candidate)):
            return
        c = items[0].data(0, Qt.UserRole)
        if getattr(self, "_have", None) and getattr(self, "_armed_key", None) != c.key:
            self._armed_key = c.key                           # first click: the note is the answer; second sends
            self.btn.setText("Check it anyway")
            return
        self.btn.setText("Check this file")
        self.pick.emit(c)


def _short(name: str, n: int = 48) -> str:
    base = name.rsplit(".", 1)[0] if "." in name else name
    return base if len(base) <= n else base[: n - 1] + "…"


def _speed(c: Candidate) -> str:
    from ..core.availability import availability
    return availability(c).label


def _speed_raw(c: Candidate) -> str:
    if c.locked:
        return "Locked"
    rate = f"{c.upload_speed / 1e6:.1f} MB/s" if (c.upload_speed or 0) >= 1e6 else (f"{c.upload_speed / 1e3:.0f} kB/s" if c.upload_speed else "")
    if c.free_slot:
        return f"Free slot · {rate}".rstrip(" ·")
    if c.queue_length is not None:
        return f"{c.queue_length} ahead · {rate}".rstrip(" ·") if c.queue_length < 999 else "Queue full"
    return rate or "?"


def _rank(c: Candidate, dropped: str = "", rep=None):
    """Best first. Source history is a tie-breaker (before reported speed), except that a source which has
    never delivered and failed twice sinks below every working one."""
    from ..core.fuzzy import closeness
    return (1 if (c.locked or c.note) else 0, 1 if (rep is not None and rep.never_delivers) else 0,
            0 if c.free_slot else 1,
            closeness(c.display_name or "", dropped) if dropped else 0,     # fallback: near-misses of the typo first
            c.queue_length if c.queue_length is not None else 1_000_000,
            -max(-3, min(3, rep.score)) if rep is not None else 0,
            -(c.upload_speed or 0), -(c.bitrate_kbps or 0))


# ------------------------------------------------------------------ review
class ReviewPage(QWidget):
    promote = Signal(str, bool)      # job_id, override
    reject = Signal(str)
    cancel = Signal(str)
    rerun = Signal(str)
    club_copy = Signal(str)          # make a verified club-ready copy of this track
    open_folder = Signal(str)
    reveal = Signal(str)
    remove_job = Signal(str)
    retry = Signal(str)
    select = Signal(str)

    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        self.job_id: str | None = None
        outer, lay = page(spacing=0)
        root = vbox(self); root.addWidget(outer)
        body = hbox(spacing=40); lay.addLayout(body, 1)

        # rail
        rail = vbox(spacing=2)
        rh = hbox(); rh.addWidget(label("Ready for you", "h2")); rh.addStretch(1)
        self.rail_count = label("", "faint"); rh.addWidget(self.rail_count)
        rail.addLayout(rh); rail.addSpacing(8)
        self.rail_host = QWidget(); self.rail_host.setObjectName("page")
        self.rail = vbox(self.rail_host, spacing=2); self.rail.addStretch(1)
        self.rail_scroll = scroll(self.rail_host); rail.addWidget(self.rail_scroll, 1)
        rail.addWidget(label("↑↓ move · ⏎ download · ⌫ delete", "mono"))
        rw = QWidget(); rw.setLayout(rail); rw.setMinimumWidth(280); rw.setMaximumWidth(360)
        body.addWidget(rw, 2)
        self.rail_w = rw

        # detail
        det = vbox(spacing=8)                           # compact: the whole track fits without scrolling
        head = hbox(spacing=18)
        self.cover = QLabel(); self.cover.setFixedSize(84, 84); self.cover.setObjectName("cover")
        self.cover.setAlignment(Qt.AlignCenter); self.cover.setScaledContents(False)
        head.addWidget(self.cover, 0, Qt.AlignTop)
        names = vbox(spacing=4)
        self.source = label("", "tag"); self.h1 = label("", "h1"); self.h1.setWordWrap(True); self.artist = label("", "muted")
        self.artist.setStyleSheet("font-size: 15px;")
        self.meta_line = label("", "muted")
        names.addWidget(self.source); names.addWidget(self.h1); names.addWidget(self.artist); names.addWidget(self.meta_line)
        head.addLayout(names, 1)
        det.addLayout(head)

        det.addWidget(rule())
        facts = hbox(spacing=12)
        self.facts, self.fact_subs = {}, {}
        from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect
        for k in ("BPM", "Key", "Length", "Format"):
            tile = QFrame(); tile.setObjectName("display")
            tl = vbox(tile, (10, 5, 10, 5), 0)                 # small: the checks below get the room
            tl.addWidget(label(k.upper(), "disptag"))
            v = label("–", "tilesm"); tl.addWidget(v)
            glow = QGraphicsDropShadowEffect(v); glow.setOffset(0, 0); glow.setBlurRadius(14)
            glow.setColor(QColor(255, 176, 0, 110)); v.setGraphicsEffect(glow)             # the amber readout glow
            sub = label("", "dispsub"); tl.addWidget(sub)
            self.facts[k], self.fact_subs[k] = v, sub
            facts.addWidget(tile, 1)
        for k in ("Bitrate", "Rate", "Channels", "Plays"):           # shown together on one quiet line below
            self.facts[k] = label("")
        det.addLayout(facts)
        self.facts_detail = label("", "muted"); det.addWidget(self.facts_detail)
        self.facts_detail.hide()             # bitrate, rate and "plays all the way through" are in the checks below
        det.addWidget(rule())

        # download progress (only while the track is still coming in)
        self.dl_host = QWidget(); dl = vbox(self.dl_host, spacing=6)
        dh = hbox(); self.dl_title = label("Downloading", "h2"); dh.addWidget(self.dl_title); dh.addStretch(1)
        self.dl_pct = label("", "monotext"); dh.addWidget(self.dl_pct); dl.addLayout(dh)
        self.dl_bar = QProgressBar(self.dl_host); self.dl_bar.setTextVisible(False); self.dl_bar.setRange(0, 100); self.dl_bar.setFixedHeight(6)
        self.dl_bar.setProperty("tag", "Down"); dl.addWidget(self.dl_bar)
        self.dl_note = label("", "muted"); dl.addWidget(self.dl_note)
        det.addWidget(self.dl_host); self.dl_host.hide()
        sh = hbox(spacing=12); sh.addWidget(label("SPECTROGRAM", "disptag"))
        self.btn_preview = button("▶  Preview", "small", lambda: self.spectrum.play_preview())
        self.btn_preview.setToolTip("Plays a 20-second preview")
        self.btn_preview.setVisible(False)                 # downloaded tracks play in full; preview lives in Search
        sh.addStretch(1)
        self.spec_note = label("", "muted"); sh.addWidget(self.spec_note)
        self._spec_head = QWidget(); self._spec_head.setLayout(sh); self._spec_head.hide()   # the picture shows the cutoff itself
        det.addWidget(self._spec_head)
        self.spectrum = SpectrumView(138); det.addWidget(self.spectrum)      # big: the part you read
        self.level_host = QWidget(); lv = hbox(self.level_host, spacing=12); lv.addWidget(label("LEVEL", "disptag"))
        self.level = LevelStrip(); lv.addWidget(self.level, 1)
        det.addWidget(self.level_host)
        self.level_host.setVisible(False)                  # an empty meter is noise: it shows while a track plays
        # the meter only ticks while something plays (an always-on timer steals time from animations)
        self._level_timer = QTimer(self, interval=16, timeout=self._tick_level)     # ~60 fps
        self._lv_pos, self._lv_t, self._lv_audio = -1, 0.0, None
        self.spectrum.on_playing = self._on_playing

        self.checks_host = QWidget(); self.checks_host.setObjectName("page")
        self.checks = vbox(self.checks_host, spacing=0)
        det.addWidget(self.checks_host)
        det.addStretch(1)

        self.actions_host = QWidget(); actions = hbox(self.actions_host, spacing=10)
        self.btn_save = button("Download to Library", "primary", lambda: self.promote.emit(self.job_id, False))
        self.btn_anyway = button("Download anyway", "primary", lambda: self.promote.emit(self.job_id, True))
        self.btn_delete = button("Delete", "danger", lambda: self.reject.emit(self.job_id))
        self.btn_cancel = button("Cancel download", "ghost", lambda: self.cancel.emit(self.job_id))
        self.btn_rerun = button("Re-check", "ghost", lambda: self.rerun.emit(self.job_id))
        self.btn_club = button("Make a club-ready copy", "ghost", lambda: self.club_copy.emit(self.job_id))
        self.btn_club.setToolTip("Converts the format so every CDJ and Rekordbox loads it, proves the copy matches the "
                                 "original, then checks it like any new file. The original is never changed.")
        self.btn_club.hide()
        self.btn_retry = button("Retry download", "primary", lambda: self.retry.emit(self.job_id))
        self.btn_retry.setToolTip("Ask the same source for the file again")
        self.btn_open = button("Open folder", "ghost", lambda: self.open_folder.emit(self.job_id))
        self.btn_reveal = button("Show in folder", "ghost", lambda: self.reveal.emit(self.job_id))
        self.btn_remove = button("Remove from list", "ghost", lambda: self.remove_job.emit(self.job_id))
        self.btn_remove.setToolTip("Takes it off the queue. Downloaded files stay in your library.")
        self._dots = QTimer(self, interval=450, timeout=self._tick_dots); self._dot_n = 0
        for b in (self.btn_save, self.btn_anyway, self.btn_retry, self.btn_delete, self.btn_cancel, self.btn_remove):
            actions.addWidget(b)
        actions.addStretch(1)
        actions.addWidget(self.btn_rerun); actions.addWidget(self.btn_club); actions.addWidget(self.btn_reveal); actions.addWidget(self.btn_open)
        # the verdict sits right where the decision is made, above Download / Delete
        self.verdict = label("", "verdict"); self.verdict_sub = label("", "faint")
        vrow = hbox(spacing=12); vrow.addWidget(self.verdict, 0, Qt.AlignBottom)
        vrow.addWidget(self.verdict_sub, 0, Qt.AlignBottom); vrow.addStretch(1)
        # the details scroll on short screens; the verdict and buttons stay pinned at the bottom
        dw = QWidget(); dw.setObjectName("page"); dw.setLayout(det)
        self.det_scroll = scroll(dw)
        col = vbox(spacing=12); col.addWidget(self.det_scroll, 1); col.addWidget(rule())
        col.addLayout(vrow); col.addWidget(self.actions_host)
        cw = QWidget(); cw.setLayout(col)
        body.addWidget(cw, 5)
        self.show_job(None, None)

    def embed(self):
        """Shown inside the Queue tab: the Queue's own list replaces this page's list."""
        self.rail_w.hide()
        self.layout().setContentsMargins(0, 0, 0, 0)

    def _on_playing(self, on: bool):
        if on:
            self.level_host.setVisible(True); self._level_timer.start()
            self._load_envelope()

    def _load_envelope(self):
        """The meter reads the track's real loudness (every 20 ms, both channels), worked out in the background
        the first time it plays. Until then it falls back to the spectrogram."""
        audio = getattr(self.spectrum, "_audio", None)
        if not audio or audio == self._lv_audio:
            return
        self._lv_audio = audio
        self.level.set_envelope(None)
        from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal as _Sig
        from .widgets import level_envelope

        class _B(QObject):
            ready = _Sig(str, object)
        if not hasattr(self, "_env_bridge"):
            self._env_bridge = _B()
            self._env_bridge.ready.connect(lambda a, env: self.level.set_envelope(env) if a == self._lv_audio else None)
        bridge, ff = self._env_bridge, getattr(self.svc.settings, "ffmpeg_path", "")

        class _Job(QRunnable):
            def run(self_inner):
                try:
                    bridge.ready.emit(audio, level_envelope(audio, ff))
                except Exception:
                    pass
        QThreadPool.globalInstance().start(_Job())

    def _tick_dots(self):
        self._dot_n = (self._dot_n + 1) % 4
        base = self.verdict_sub.text().rstrip(".")
        self.verdict_sub.setText(base + "." * (self._dot_n or 3))

    def set_busy(self, on: bool):
        """While a Download/Delete is being carried out off-thread, the decision buttons can't be pressed twice."""
        for b in (self.btn_save, self.btn_anyway, self.btn_remove, self.btn_retry):
            b.setEnabled(not on)
        self.btn_delete.setEnabled(not on and self.btn_delete.property("can") is True)

    def _tick_level(self):
        import time as _t
        playing = self.spectrum.is_playing()
        pos = self.spectrum.position_ms()
        now = _t.monotonic()
        if pos != self._lv_pos:                              # the player reports ~10x a second: glide in between
            self._lv_pos, self._lv_t = pos, now
        est_s = (pos + (now - self._lv_t) * 1000) / 1000 if playing else None
        self.level.feed(est_s, fallback=self.spectrum.current_level())
        if not playing and self.level.level() < 0.01:
            self._level_timer.stop()                       # fell back to zero after playback stopped
            self.level_host.setVisible(False)

    def set_rail(self, jobs: list[dict], analyses: dict[str, dict | None], steps: dict[str, str]):
        rows = [(j["id"], row_data(j, analyses.get(j["id"]), steps)) for j in jobs]
        key = tuple((jid, d["tag"], d["title"], d["removable"]) for jid, d in rows)
        self.rail_count.setText(str(sum(1 for j in jobs if j["state"] == J.READY)))
        if key == getattr(self, "_rail_key", None):
            # nothing structural changed: just move the highlight (no rebuild, no scroll jump)
            for i in range(self.rail.count()):
                w = self.rail.itemAt(i).widget()
                if w is not None and w.property("job_id"):
                    want = "true" if w.property("job_id") == self.job_id else "false"
                    if w.property("selected") != want:
                        w.setProperty("selected", want); T.repolish_tree(w)
            return
        self._rail_key = key
        keep_scroll(self.rail_scroll, lambda: self._build_rail(jobs, analyses, steps))

    def _build_rail(self, jobs, analyses, steps):
        while self.rail.count() > 1:
            item = self.rail.takeAt(0)
            if item.widget():
                item.widget().hide(); item.widget().deleteLater()   # hidden now: no ghost rows painted over the new ones
        shown = jobs
        for j in shown:
            d = row_data(j, analyses.get(j["id"]), steps)
            w = QWidget(); w.setObjectName("row"); w.setCursor(Qt.PointingHandCursor); w.setProperty("tag", d["tag"])
            hl = hbox(w, (4, 9, 10, 9), 10)
            if d["removable"]:
                x = button("×", "x", lambda _=False, jid=j["id"]: self.remove_job.emit(jid)); x.setToolTip("Cancel download" if j["state"] == J.QUEUED else "Remove from the list")
            else:
                x = QWidget(); x.setAttribute(Qt.WA_TransparentForMouseEvents)
            x.setFixedWidth(22); hl.addWidget(x)
            t = label(d["tag"].upper(), "tag", d["tag"]); t.setFixedWidth(56)
            n = label(d["title"]); n.setStyleSheet("font-weight: 600;"); n.setToolTip(d["title"])
            n.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)      # long titles clip instead of pushing × off the rail
            hl.addWidget(t); hl.addWidget(n, 1)
            for lbl in (t, n):
                lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            w.mouseReleaseEvent = lambda e, jid=j["id"]: self.select.emit(jid)
            w.setProperty("job_id", j["id"])
            w.setProperty("selected", "true" if j["id"] == self.job_id else "false")
            self.rail.insertWidget(self.rail.count() - 1, w)

    def show_job(self, job: dict | None, a: dict | None, steps: dict[str, str] | None = None):
        self.job_id = job["id"] if job else None
        if not job:
            for b in (self.btn_save, self.btn_anyway, self.btn_delete, self.btn_cancel, self.btn_rerun, self.btn_open, self.btn_reveal, self.btn_remove, self.btn_retry):
                b.hide()
        # (with a job, every button is decided below; showing them all first made the row ~1300 px wide for a
        #  frame on every refresh and the column jumped)
        self.dl_host.setVisible(False)                 # downloading happens in the background: no progress text here
        self._dots.stop()
        while self.checks.count():
            item = self.checks.takeAt(0)
            if item.widget():
                item.widget().hide(); item.widget().deleteLater()   # hidden now: no ghost rows painted over the new ones
        if not job:
            self.source.setText(""); self.h1.setText("Pick a track from the list"); self.artist.setText("")
            for v in self.fact_subs.values(): v.setText("")
            self.meta_line.setText(""); self.cover.clear(); self.cover.setVisible(False); self.btn_preview.setVisible(False)
            self.verdict.setText(""); self.verdict_sub.setText("")
            for v in self.facts.values(): v.setText("–")
            self.facts_detail.setText("")
            self.spectrum.clear_view(""); self.spec_note.setText("")
            return
        d = row_data(job, a, steps or {})
        src = "" if job.get("remote_user") else {"manual": "added by you", "watched": "from your incoming folder"}.get(
            job.get("source_kind", ""), "")
        when = (job.get("updated_at") or "")[11:16]
        where = {"PROMOTED": "in your library"}.get(job["state"], "in quarantine")
        busy0 = job["state"] in (J.STAGING, J.ANALYZING, J.QUEUED)
        self.source.setText("  ·  ".join(x for x in (where, f"checked {when}" if when and a and not busy0 else "", src) if x).upper())
        self.h1.setText(d["title"]); self.artist.setText(d["artist"])
        n = len(d["title"] or "")                          # long titles get smaller, not cut: the panel still fits
        self.h1.setStyleSheet("" if n <= 26 else "font-size: 22px;" if n <= 44 else "font-size: 18px;")
        busy = job["state"] in (J.STAGING, J.ANALYZING, J.QUEUED)
        if job["state"] == J.QUEUED:
            pct = float(job.get("progress") or 0)
            self.dl_bar.setValue(int(pct)); self.dl_pct.setText(f"{pct:.0f}%")
            msg = job.get("message") or ""
            self.dl_title.setText("Downloading" if pct > 0 else "Waiting for the source")
            self.dl_note.setText({"Queued, Remotely": "In line at the source — it starts when they have a free slot.",
                                  "Queued, Locally": "Queued here; starts in a moment.",
                                  "Requested": "Asking the source…", "InProgress": "Receiving the file…",
                                  "Initializing": "Starting up the transfer…"}.get(msg, msg))

        status = T.grade(a) if a and not busy else None
        if status:
            set_tag(self.verdict, T.GRADE_WORD[status]); self.verdict.setText(T.GRADE_LONG[status])
            issues = sum(1 for c in a["checks"] if c["status"] != "PASS")
            self.verdict_sub.setText({0: "Nothing to worry about", 1: "1 thing to check"}.get(issues, f"{issues} things to check")
                                     if status not in ("FAIL", "CLUB") else
                                     "Can't be used" if status == "FAIL" else "Fine file, won't work on a club system")
        elif job["state"] == J.ERROR:
            set_tag(self.verdict, "Error"); self.verdict.setText("Error")
            self.verdict_sub.setText(d["meta"])
        else:
            set_tag(self.verdict, d["tag"]); self.verdict.setText(d["tag"] if busy else "")
            self.verdict_sub.setText("" if busy else (job.get("message") or ""))   # no percentages or step text
        if a and not busy:
            f, dec = a["facts"], a.get("decode") or {}
            self.facts["Format"].setText((f.get("container") or "?").upper())
            self.facts["Bitrate"].setText(_bitrate(f))
            self.facts["Rate"].setText(f"{f['sample_rate_hz'] / 1000:g} kHz" if f.get("sample_rate_hz") else "?")
            self.facts["Length"].setText(fmt_time(f["duration_s"]) if f.get("duration_s") else "?")
            self.facts["Channels"].setText({1: "Mono", 2: "Stereo"}.get(f.get("channels"), str(f.get("channels") or "?")))
            mu, me = a.get("music") or {}, a.get("meta") or {}
            self.facts["BPM"].setText(f"{mu['bpm']:.2f}".rstrip("0").rstrip(".") if mu.get("bpm") else "–")
            self.facts["BPM"].setToolTip("From the file's own tags" if mu.get("bpm_from_tags") else "Measured from the audio")
            self.fact_subs["BPM"].setText("from tags" if mu.get("bpm") and mu.get("bpm_from_tags") else "")
            self.facts["Key"].setText(mu["camelot"] if mu.get("camelot") else "–")
            key_sub = mu.get("key", "") if mu.get("camelot") else ""
            if key_sub and mu.get("key_from_tags"):
                key_sub += " · from tags"
            self.fact_subs["Key"].setText(key_sub)
            self.facts_key_name = mu.get("key", "")
            self.facts["Key"].setToolTip("From the file's own tags (Camelot code and key name)" if mu.get("key_from_tags")
                                         else "Estimated from the audio (Camelot code and key name)")
            from ..media.metadata import clean_label
            bits = [clean_label(me.get("label") or ""), me.get("year"), me.get("genre")]
            self.meta_line.setText("  ·  ".join(b for b in bits if b))
            self.meta_line.setToolTip("From " + ", ".join(me.get("sources") or ["the file"]) if me else "")
            cov = me.get("cover_path")
            pm = QPixmap(cov) if cov and Path(cov).exists() else QPixmap()
            self.cover.setVisible(not pm.isNull())
            if not pm.isNull():
                self.cover.setPixmap(pm.scaled(104, 104, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
            played = dec.get("decoded_s")
            dec_ok = a.get("decode_ok") and next((c for c in a["checks"] if c["id"] == "decode"), {}).get("status") != "FAIL"
            self.facts["Plays"].setText("–" if played is None else ("All the way" if dec_ok else f"Stops at {fmt_time(played)}"))
            self.fact_subs["Format"].setText(self.facts["Rate"].text() if self.facts["Rate"].text() not in ("?", "–") else "")
            self.facts_detail.setText("  ·  ".join(x for x in (self.facts["Bitrate"].text(), self.facts["Rate"].text(),
                                                             self.facts["Channels"].text(),
                                                             "plays all the way through" if dec_ok else self.facts["Plays"].text().lower())
                                                    if x and x not in ("?", "–")))
            if a.get("spectrogram_path") and Path(a["spectrogram_path"]).exists():
                self.spectrum.show_png(a["spectrogram_path"], f.get("sample_rate_hz"), a.get("cutoff_hz"),
                                       audio=_audio_path(job), duration_s=f.get("duration_s"))
                self.spectrum.set_cutoff_bad(next((c["status"] for c in a.get("checks", []) if c["id"] == "spectrum"), "PASS") != "PASS")
                self.spectrum.set_preview(mu.get("drop_s"), None)        # mark the drop; no preview window here
                self.spectrum.set_track(d["title"], d["artist"])
            else:
                self.spectrum.clear_view("Spectrogram unavailable." if job["state"] not in J.FINAL else "Staged copy removed.")
            cut = a.get("cutoff_hz")
            self.spec_note.setText(f"Energy reaches about {cut / 1000:.1f} kHz" if cut else "")
            from .widgets import club_badges, club_heading
            club = (a.get("club") or {}).get("checks") or []
            # every check with what it found (problems first); the facts boxes are small so it all fits
            rows = sorted(a["checks"], key=lambda c: {"FAIL": 0, "WARN": 1, "PASS": 2}[c["status"]])
            rows += [None] + sorted(club, key=lambda c: {"FAIL": 0, "WARN": 1, "PASS": 2}[c["status"]]) if club else []
            # every check on one line: its result, its name and what it found (hover for the full text); the club
            # checks are the CLUB badges below (hover each for its detail). Together they fit without scrolling.
            from .discover_page import ElideLabel
            for c in [c for c in rows if c is not None][:len(a["checks"])]:
                cell = QWidget(); hl = hbox(cell, (0, 3, 0, 3), 10)
                word = T.GRADE_WORD[c["status"]]
                t = label(word.upper(), "tag", word); t.setFixedWidth(52)
                txt = ElideLabel(f"{c['title']} — {c['message']}", "")
                txt.setToolTip(f"{c['title']}: {c['message']}"); txt.setStyleSheet("font-size: 12px;")
                hl.addWidget(t); hl.addWidget(txt, 1)
                self.checks.addWidget(cell)
            if club:
                head = club_badges(a, getattr(self.svc.settings, "theme", "light"))
                if head is not None:
                    head.setContentsMargins(0, 2, 0, 0); self.checks.addWidget(head)
        else:
            for v in self.facts.values(): v.setText("–")
            self.spectrum.clear_view("" if busy else "No spectrogram."); self.spec_note.setText("")
            if busy:
                pass                                           # downloading / checking: quietly, in the background
            elif job.get("message"):
                self.checks.addWidget(label(job["message"], "muted", wrap=True))
        ready = job["state"] == J.READY and bool(a)
        from ..media.clubcopy import needs_copy
        self.btn_club.setVisible(bool(a) and job["state"] in (J.READY, J.PROMOTED) and needs_copy(a.get("club")))
        self.btn_save.setVisible(ready and status == "PASS")
        self.btn_anyway.setVisible(ready and status in ("WARN", "CLUB"))
        for b in (self.btn_save, self.btn_anyway, self.btn_remove, self.btn_retry):
            b.setEnabled(True)                                 # a previous Download/Delete may have greyed them
        self.btn_cancel.setVisible(job["state"] == J.QUEUED)
        finished = job["state"] in J.FINAL
        self.btn_delete.setVisible(job["state"] != J.QUEUED and not finished)
        self.btn_delete.setProperty("can", job["state"] in (J.READY, J.ERROR)); self.btn_delete.setEnabled(job["state"] in (J.READY, J.ERROR))
        self.btn_remove.setVisible(finished)
        dl_failed = job["state"] == J.ERROR and bool(job.get("remote_user")) and not job.get("staged_path")
        self.btn_retry.setVisible(dl_failed)
        self.btn_rerun.setVisible(not dl_failed and job["state"] != J.QUEUED)
        self.btn_rerun.setText("Re-checking…" if job["state"] in (J.STAGING, J.ANALYZING) else "Re-check")
        self.btn_rerun.setEnabled(job["state"] not in (J.STAGING, J.ANALYZING))
        self.btn_rerun.setEnabled(job["state"] in (J.READY, J.ERROR) and bool(job["staged_path"]))
        done = job["state"] == J.PROMOTED and bool(job.get("final_path")) and Path(job["final_path"]).exists()
        self.btn_reveal.setVisible(done)
        self.btn_open.setVisible(not done)
        self.btn_open.setText("Open folder")
        target = Path(job["final_path"]).parent if job["state"] == J.PROMOTED and job.get("final_path") else \
            (Path(job["staged_path"]).parent if job.get("staged_path") else None)
        self.btn_open.setEnabled(bool(target and target.exists()))
