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
from .widgets import keep_scroll, smooth, LevelStrip, QueueRow, SpectrumView, button, hbox, label, page, rule, scroll, set_tag, vbox


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
        return dict(tag="Down", title=title, artist=artist, pct=job.get("progress") or 0, meta=(job.get("message") or "")[:18], removable=True)
    if st == J.STAGING:
        return dict(tag="Check", title=title, artist=artist, pct=0, meta="moving in", removable=False)
    if st == J.ANALYZING:
        step = steps.get(job["id"])
        return dict(tag="Check" if step else "Wait", title=title, artist=artist, pct=None, meta=(step or "waiting").lower().rstrip("…"), removable=False)
    if st == J.READY and analysis:
        f = analysis["facts"]
        kbps = f"{round(f['bitrate_bps'] / 1000)} kbps" if f.get("bitrate_bps") else (f.get("container") or "").upper()
        return dict(tag=T.GRADE_WORD[analysis["overall_status"]], title=title, artist=artist, pct=100, meta=kbps, removable=True)
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
        srow = hbox(spacing=16)
        self.q = QLineEdit(); self.q.setObjectName("hero"); self.q.setPlaceholderText("Search for a track…")
        self.q.returnPressed.connect(lambda: self.search.emit(self.q.text()))
        srow.addWidget(self.q, 1)
        self.search_btn = button("Search", "accent", lambda: self.search.emit(self.q.text()))
        srow.addWidget(self.search_btn)
        self.add_btn = button("Add files", "ghost", self.add_files.emit)
        srow.addWidget(self.add_btn)
        lay.addLayout(srow)

        body = hbox(spacing=40)
        lay.addLayout(body, 1)

        # queue column
        qcol = vbox(spacing=6)
        head = hbox(spacing=12); head.addWidget(label("Queue", "h2")); head.addStretch(1)
        self.qnote = label("newest first", "faint"); head.addWidget(self.qnote)
        self.clear_btn = button("Clear finished", "link", self.clear_finished.emit); head.addWidget(self.clear_btn)
        qcol.addLayout(head)
        self.list_host = QWidget(); self.list_host.setObjectName("page")
        self.list = vbox(self.list_host, spacing=0); self.list.addStretch(1)
        self.list_scroll = scroll(self.list_host); qcol.addWidget(self.list_scroll, 1)
        self.empty = label("Nothing in the queue. Search above, or drop tracks onto the window.", "faint", wrap=True)
        qcol.addWidget(self.empty)
        qw = QWidget(); qw.setLayout(qcol); qw.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        body.addWidget(qw, 3)

        # right rail: scope + counts
        rail = vbox(spacing=28)
        scope_head = hbox(); scope_head.addWidget(label("Last checked", "h2")); scope_head.addStretch(1)
        self.scope_name = label("", "muted"); scope_head.addWidget(self.scope_name)
        rail.addLayout(scope_head)
        self.scope = SpectrumView(170); rail.addWidget(self.scope)
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
            card = QFrame(); card.setObjectName("card")
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

    def set_connected(self, on: bool, message: str = ""):
        self.q.setEnabled(on)
        self.q.setPlaceholderText("Search for a track…" if on else (message or "Connecting…"))
        self.search_btn.setEnabled(on)

    def refresh(self, jobs: list[dict], analyses: dict[str, dict | None]):
        # Rebuild the row widgets only when something visible changed; refresh() fires every poll.
        rows = [(j["id"], row_data(j, analyses.get(j["id"]), self.steps)) for j in jobs]
        key = tuple((jid, d["tag"], d["title"], d["artist"], d["pct"], d["meta"], d["removable"]) for jid, d in rows)
        if key == getattr(self, "_last_key", None):
            return
        self._last_key = key
        prev_tags = getattr(self, "_prev_tags", {})
        changed = {jid for jid, d in rows if jid in prev_tags and prev_tags[jid] != d["tag"]}
        self._prev_tags = {jid: d["tag"] for jid, d in rows}
        # queue list (rebuilt in place; the scroll position stays where the user left it)
        def rebuild():
            while self.list.count() > 1:
                item = self.list.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.empty.setVisible(not jobs)
            self.list_host.setUpdatesEnabled(False)
            for jid, d in rows:
                row = QueueRow(jid, d["tag"], d["title"], d["artist"], d["pct"], d["meta"], d["removable"])
                row.clicked.connect(self.open_job.emit); row.removed.connect(self.remove_job.emit)
                self.list.insertWidget(self.list.count() - 1, row)
                if jid in changed:
                    row.flash()                               # the blip: this track just moved on
            self.list_host.setUpdatesEnabled(True)
        keep_scroll(self.list_scroll, rebuild)
        down = sum(1 for j in jobs if j["state"] == J.QUEUED)
        chk = sum(1 for j in jobs if j["state"] in (J.STAGING, J.ANALYZING))
        self.qnote.setText(f"{down} downloading · {chk} checking" if (down or chk) else "newest first")
        self.clear_btn.setVisible(any(j["state"] in J.FINAL or j["state"] == J.ERROR for j in jobs))
        # counts
        n = {"Good": 0, "Look": 0, "Broken": 0}
        for j in jobs:
            a = analyses.get(j["id"])
            if j["state"] == J.READY and a:
                n[T.GRADE_WORD[a["overall_status"]]] += 1
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
    COLS = ["#", "Title", "Mix", "Artist", "Folder", "User", "Size", "Rate", "Length", "Availability"]
    WIDTHS = [36, 180, 110, 140, 90, 80, 70, 56, 56, 170]

    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        outer, lay = page(spacing=20)
        root = vbox(self); root.addWidget(outer)
        srow = hbox(spacing=16)
        self.q = QLineEdit(); self.q.setObjectName("hero"); self.q.setPlaceholderText("Search for a track…")
        self.q.returnPressed.connect(lambda: self.search.emit(self.q.text()))
        srow.addWidget(self.q, 1)
        self.search_btn = button("Search", "accent", lambda: self.search.emit(self.q.text()))
        srow.addWidget(self.search_btn)
        self.watch_btn = button("Watch this search", "ghost", self._toggle_watch)
        self.watch_btn.setToolTip("Nobody has it? Keep asking every half hour for 30 days and tell me when it shows up.")
        self.watch_btn.setEnabled(False); self.q.textChanged.connect(lambda t: self.watch_btn.setEnabled(bool(t.strip())))
        srow.addWidget(self.watch_btn)
        lay.addLayout(srow)
        from .wishlist_page import WishForm
        self.wish_form = WishForm("Watch for this track. Fill in what you know, as much or as little as you like.")
        self.wish_form.hide()
        self.wish_form.submitted.connect(self._watch_go); self.wish_form.cancelled.connect(self.wish_form.hide)
        lay.addWidget(self.wish_form)
        head = hbox(spacing=12)
        self.title = label("Search", "h2"); head.addWidget(self.title)
        self.state = label("", "faint"); head.addWidget(self.state); head.addStretch(1)
        head.addWidget(label("What you see is what each source reports. Every file is checked before it can reach your library.", "faint"))
        lay.addLayout(head)
        # filters (design v6): format, ready now, mix kind, private
        from ..core.availability import Filters
        self.filters = Filters()
        fr = hbox(spacing=8)
        self._fbtns = {}
        for key, text in (("lossless", "Lossless"), ("mp3_320", "MP3 320"), ("ready_now", "Ready now"), ("show_private", "Show private")):
            b = button(text, "chip", lambda _=False, k=key: self._toggle_filter(k)); b.setCheckable(True)
            self._fbtns[key] = b; fr.addWidget(b)
        from PySide6.QtWidgets import QComboBox
        self.mix_box = QComboBox()
        for text, val in (("Any mix", ""), ("Extended", "extended"), ("Original", "original"), ("Radio edit", "radio"),
                          ("Dub", "dub"), ("Remix", "remix"), ("Edit", "edit")):
            self.mix_box.addItem(text, val)
        self.mix_box.currentIndexChanged.connect(lambda _: self._set_mix(self.mix_box.currentData()))
        fr.addWidget(self.mix_box); fr.addStretch(1)
        self.hidden_note = label("", "faint"); fr.addWidget(self.hidden_note)
        lay.addLayout(fr)
        self._last_res = None; self._last_searching = False
        self.tree = QTreeWidget(); self.tree.setColumnCount(len(self.COLS)); self.tree.setHeaderLabels(self.COLS)
        self.tree.setRootIsDecorated(False); self.tree.setSortingEnabled(False); self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionBehavior(QTreeWidget.SelectRows)
        hdr = self.tree.header(); hdr.setSectionResizeMode(QHeaderView.Interactive); hdr.setStretchLastSection(True)
        for i, w in enumerate(self.WIDTHS):
            self.tree.setColumnWidth(i, w)
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
        self.btn_pv.setToolTip("Downloads it into quarantine, then plays 20 seconds from the drop")
        row.addWidget(self.btn); row.addWidget(self.btn_pv)
        self.pv_note = label("Preview and Check both download into quarantine first; nothing reaches your library "
                             "until you decide.", "faint")
        row.addWidget(self.pv_note)
        self._previewing = False
        row.addStretch(1)
        lay.addLayout(row)

    def set_connected(self, on: bool):
        self.q.setEnabled(on); self.search_btn.setEnabled(on and not self._anim.isActive())
        self.btn.setEnabled(on and bool(self.tree.selectedItems()))

    def set_problem_sources(self, keys: dict[str, str]):
        """remote key -> short reason, for sources that already failed us (download errored, rejected, etc.)."""
        self._problems = keys

    def eventFilter(self, obj, ev):
        if obj is self.tree.viewport() and ev.type() == QEvent.Resize:
            self.empty.setGeometry(self.tree.viewport().rect().adjusted(40, 0, -40, 0))
        return False

    def _show_empty(self, text: str):
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

    def _set_mix(self, kind: str):
        self.filters.mix = kind or ""
        self._refilter()

    def set_filters(self, d: dict):
        from ..core.availability import Filters
        self.filters = Filters(**{k: v for k, v in (d or {}).items() if k in Filters.__dataclass_fields__})
        for k, b in self._fbtns.items():
            b.blockSignals(True); b.setChecked(bool(getattr(self.filters, k))); b.blockSignals(False)
        i = self.mix_box.findData(self.filters.mix)
        self.mix_box.blockSignals(True); self.mix_box.setCurrentIndex(max(0, i)); self.mix_box.blockSignals(False)

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
            bits = ([f"{hidden} hidden by filters"] if hidden else []) + ([f"{private} private hidden"] if private else [])
            self.hidden_note.setText(" · ".join(bits))
            res = replace(res, candidates=kept)
        n = len(res.candidates)
        if idle:
            self.title.setText("Search"); self.state.setText(""); self._ranked = []; self._fill(0); self._show_empty(idle); return
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
        self._ranked = self._sorted(sorted(res.candidates, key=lambda c: _rank(c, res.dropped)))
        if res.dropped:
            self.state.setText(f'Nothing matched “{res.query}” — showing results for “{res.sent}” (without “{res.dropped}”)'
                               + (" · still collecting…" if searching else ""))
        # keep whatever the user has already scrolled open, at least one page
        want = max(PAGE_ROWS, min(self._shown, len(self._ranked)))
        self._fill(want, keep)

    def _fill(self, count: int, keep=None):
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        self._more_item = None
        ranked = self._ranked[:count]
        self._shown = len(ranked)
        items = []
        for i, c in enumerate(ranked):
            it = QTreeWidgetItem([
                f"{i + 1:02d}", c.title or c.display_name, c.mix, c.artist, c.folder, c.user, f"{c.size / 1e6:.1f} MB",
                (f"{c.bitrate_kbps}" + ("v" if c.vbr else "")) if c.bitrate_kbps else (c.extension.upper() if c.extension in ("flac", "wav", "aiff", "aif") else "?"),
                fmt_time(c.length_s) if c.length_s else "?", _speed(c),
            ])
            it.setData(0, Qt.UserRole, c)
            it.setToolTip(1, c.display_name)
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

    PV_NOTE = "Preview and Check both download into quarantine first; nothing reaches your library until you decide."

    def _selection(self):
        items = self.tree.selectedItems()
        c = items[0].data(0, Qt.UserRole) if items else None
        ok = isinstance(c, Candidate) and not c.note and not c.locked
        self.btn.setEnabled(ok)
        self.btn_pv.setEnabled(self._previewing or self.btn.isEnabled())
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

    def set_preview_state(self, state: str, text: str = ""):
        """state: '' (idle), 'loading' (downloading + checking), 'playing'."""
        self._previewing = state == "playing"
        self.btn_pv.setText({"loading": "Getting preview…", "playing": "■  Stop"}.get(state, "▶  Preview"))
        self.btn_pv.setEnabled(state != "loading" and (state == "playing" or self.btn.isEnabled()))
        self.pv_note.setText(text or "Preview and Check both download into quarantine first; nothing reaches your "
                                     "library until you decide.")

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


def _rank(c: Candidate, dropped: str = ""):
    from ..core.fuzzy import closeness
    return (1 if (c.locked or c.note) else 0, 0 if c.free_slot else 1,
            closeness(c.display_name or "", dropped) if dropped else 0,     # fallback: near-misses of the typo first
            c.queue_length if c.queue_length is not None else 1_000_000,
            -(c.upload_speed or 0), -(c.bitrate_kbps or 0))


# ------------------------------------------------------------------ review
class ReviewPage(QWidget):
    promote = Signal(str, bool)      # job_id, override
    reject = Signal(str)
    cancel = Signal(str)
    rerun = Signal(str)
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
        rw = QWidget(); rw.setLayout(rail); rw.setMinimumWidth(240); rw.setMaximumWidth(300)
        body.addWidget(rw, 1)

        # detail
        det = vbox(spacing=22)
        head = hbox(spacing=20)
        self.cover = QLabel(); self.cover.setFixedSize(104, 104); self.cover.setObjectName("cover")
        self.cover.setAlignment(Qt.AlignCenter); self.cover.setScaledContents(False)
        head.addWidget(self.cover, 0, Qt.AlignTop)
        names = vbox(spacing=4)
        self.source = label("", "tag"); self.h1 = label("", "h1"); self.h1.setWordWrap(True); self.artist = label("", "muted")
        self.artist.setStyleSheet("font-size: 15px;")
        self.meta_line = label("", "muted")
        names.addWidget(self.source); names.addWidget(self.h1); names.addWidget(self.artist); names.addWidget(self.meta_line)
        head.addLayout(names, 1)
        verdict = vbox(spacing=4); verdict.setAlignment(Qt.AlignRight)
        self.verdict = label("", "verdict"); self.verdict.setAlignment(Qt.AlignRight)
        self.verdict_sub = label("", "faint"); self.verdict_sub.setAlignment(Qt.AlignRight)
        verdict.addWidget(self.verdict); verdict.addWidget(self.verdict_sub)
        head.addLayout(verdict)
        det.addLayout(head)

        det.addWidget(rule())
        facts = hbox(spacing=12)
        self.facts, self.fact_subs = {}, {}
        from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect
        for k in ("BPM", "Key", "Length", "Format"):
            tile = QFrame(); tile.setObjectName("display")
            tl = vbox(tile, (16, 12, 16, 12), 2)
            tl.addWidget(label(k.upper(), "disptag"))
            v = label("–", "tile"); tl.addWidget(v)
            glow = QGraphicsDropShadowEffect(v); glow.setOffset(0, 0); glow.setBlurRadius(14)
            glow.setColor(QColor(255, 176, 0, 110)); v.setGraphicsEffect(glow)             # the amber readout glow
            sub = label("", "dispsub"); tl.addWidget(sub)
            self.facts[k], self.fact_subs[k] = v, sub
            facts.addWidget(tile, 1)
        for k in ("Bitrate", "Rate", "Channels", "Plays"):           # shown together on one quiet line below
            self.facts[k] = label("")
        det.addLayout(facts)
        self.facts_detail = label("", "muted"); det.addWidget(self.facts_detail)
        det.addWidget(rule())

        # download progress (only while the track is still coming in)
        self.dl_host = QWidget(); dl = vbox(self.dl_host, spacing=6)
        dh = hbox(); self.dl_title = label("Downloading", "h2"); dh.addWidget(self.dl_title); dh.addStretch(1)
        self.dl_pct = label("", "monotext"); dh.addWidget(self.dl_pct); dl.addLayout(dh)
        self.dl_bar = QProgressBar(self.dl_host); self.dl_bar.setTextVisible(False); self.dl_bar.setRange(0, 100); self.dl_bar.setFixedHeight(6)
        self.dl_bar.setProperty("tag", "Down"); dl.addWidget(self.dl_bar)
        self.dl_note = label("", "muted"); dl.addWidget(self.dl_note)
        det.addWidget(self.dl_host); self.dl_host.hide()
        sh = hbox(spacing=12); sh.addWidget(label("Spectrogram", "h2"))
        self.btn_preview = button("▶  Preview the drop", "small", lambda: self.spectrum.play_preview())
        self.btn_preview.setToolTip("Plays 20 seconds starting just before the drop")
        self.btn_preview.setVisible(False)                 # downloaded tracks play in full; preview lives in Search
        sh.addStretch(1)
        self.spec_note = label("", "muted"); sh.addWidget(self.spec_note)
        det.addLayout(sh)
        self.spectrum = SpectrumView(180); det.addWidget(self.spectrum)
        lv = hbox(spacing=12); lv.addWidget(label("LEVEL", "disptag"))
        self.level = LevelStrip(); lv.addWidget(self.level, 1)
        det.addLayout(lv)
        # the meter only ticks while something plays (an always-on timer steals time from animations)
        self._level_timer = QTimer(self, interval=50, timeout=self._tick_level)
        self.spectrum.on_playing = lambda on: self._level_timer.start() if on else None

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
        actions.addWidget(self.btn_rerun); actions.addWidget(self.btn_reveal); actions.addWidget(self.btn_open)
        det.addWidget(self.actions_host)
        dw = QWidget(); dw.setLayout(det)
        body.addWidget(dw, 3)
        self.show_job(None, None)

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
        self.level.set_level(self.spectrum.current_level())
        if not self.spectrum.is_playing() and self.level._shown < 0.01:
            self._level_timer.stop()                       # fell back to zero after playback stopped

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
                        w.setProperty("selected", want); T.repolish(w)
            return
        self._rail_key = key
        keep_scroll(self.rail_scroll, lambda: self._build_rail(jobs, analyses, steps))

    def _build_rail(self, jobs, analyses, steps):
        while self.rail.count() > 1:
            item = self.rail.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
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
        self.dl_host.setVisible(bool(job) and job["state"] == J.QUEUED)
        self._dots.stop()
        while self.checks.count():
            item = self.checks.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
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
        src = "from a soulseek user" if job.get("remote_user") else {"manual": "added by you", "watched": "from your incoming folder"}.get(
            job.get("source_kind", ""), job.get("source_kind", ""))
        when = (job.get("updated_at") or "")[11:16]
        where = {"PROMOTED": "in your library"}.get(job["state"], "in quarantine")
        self.source.setText(f"{where}  ·  {'checked ' + when if when and a else 'checking'}  ·  {src}".upper())
        self.h1.setText(d["title"]); self.artist.setText(d["artist"])
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
        if job["state"] in (J.STAGING, J.ANALYZING):
            self._dots.start()                                 # the verdict sub-line keeps moving while we check
        status = a["overall_status"] if a and not busy else None
        if status:
            set_tag(self.verdict, T.GRADE_WORD[status]); self.verdict.setText(T.GRADE_LONG[status])
            issues = sum(1 for c in a["checks"] if c["status"] != "PASS")
            self.verdict_sub.setText({0: "Nothing to worry about", 1: "1 thing to check"}.get(issues, f"{issues} things to check")
                                     if status != "FAIL" else "Can't be used")
        elif job["state"] == J.ERROR:
            set_tag(self.verdict, "Error"); self.verdict.setText("Error")
            self.verdict_sub.setText(d["meta"])
        else:
            set_tag(self.verdict, d["tag"]); self.verdict.setText(d["tag"] if busy else "")
            self.verdict_sub.setText(d["meta"] if busy else (job.get("message") or ""))
        if a and not busy:
            f, dec = a["facts"], a.get("decode") or {}
            self.facts["Format"].setText((f.get("container") or "?").upper())
            self.facts["Bitrate"].setText(_bitrate(f))
            self.facts["Rate"].setText(f"{f['sample_rate_hz'] / 1000:g} kHz" if f.get("sample_rate_hz") else "?")
            self.facts["Length"].setText(fmt_time(f["duration_s"]) if f.get("duration_s") else "?")
            self.facts["Channels"].setText({1: "Mono", 2: "Stereo"}.get(f.get("channels"), str(f.get("channels") or "?")))
            mu, me = a.get("music") or {}, a.get("meta") or {}
            self.facts["BPM"].setText(f"{mu['bpm']:.2f}".rstrip("0").rstrip(".") if mu.get("bpm") else "–")
            self.facts["Key"].setText(mu["camelot"] if mu.get("camelot") else "–")
            self.fact_subs["Key"].setText(mu.get("key", "") if mu.get("camelot") else "")
            self.facts["Key"].setToolTip(mu.get("key", ""))
            self.facts_key_name = mu.get("key", "")
            self.facts["Key"].setToolTip("Estimated from the audio (Camelot code and key name)")
            bits = [me.get("label"), me.get("year"), me.get("genre")]
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
                self.spectrum.set_preview(mu.get("drop_s"), None)        # mark the drop; no preview window here
                self.spectrum.set_track(d["title"], d["artist"])
            else:
                self.spectrum.clear_view("Spectrogram unavailable." if job["state"] not in J.FINAL else "Staged copy removed.")
            cut = a.get("cutoff_hz")
            self.spec_note.setText(f"Energy reaches about {cut / 1000:.1f} kHz" if cut else "")
            for c in sorted(a["checks"], key=lambda c: {"FAIL": 0, "WARN": 1, "PASS": 2}[c["status"]]):
                row = QWidget(); hl = hbox(row, (0, 10, 0, 10), 14)
                word = T.GRADE_WORD[c["status"]]
                t = label(word.upper(), "tag", word); t.setFixedWidth(56); t.setAlignment(Qt.AlignTop)
                muted = T.colours(getattr(self.svc.settings, "theme", "light"))["muted"]
                txt = label(f"<b>{html.escape(c['title'])}</b> — <span style='color: {muted}'>{html.escape(c['message'])}</span>", wrap=True)
                txt.setTextFormat(Qt.RichText)
                hl.addWidget(t); hl.addWidget(txt, 1)
                self.checks.addWidget(row); self.checks.addWidget(rule())
        else:
            for v in self.facts.values(): v.setText("–")
            self.spectrum.clear_view("Checking…" if busy else "No spectrogram."); self.spec_note.setText("")
            if job["state"] == J.QUEUED:
                self.checks.addWidget(label(f"Downloading into quarantine… {job.get('progress') or 0:.0f}%  ·  {job.get('message') or ''}", "muted", wrap=True))
            elif busy:
                self.checks.addWidget(label("Being checked. Results appear here in a moment.", "muted"))
            elif job.get("message"):
                self.checks.addWidget(label(job["message"], "muted", wrap=True))
        ready = job["state"] == J.READY and bool(a)
        self.btn_save.setVisible(ready and status == "PASS")
        self.btn_anyway.setVisible(ready and status == "WARN")
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
