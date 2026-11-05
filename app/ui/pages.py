"""The v5 pages: Home (queue + scope + counts), Search results, Review. Pure view code: they read
through ArchiveService and raise signals; MainWindow does the work and calls refresh()."""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFrame, QGridLayout, QHeaderView, QLineEdit, QSizePolicy, QTreeWidget, QTreeWidgetItem,
                               QWidget)

from ..adapters.base import Candidate, SearchResult
from ..core import jobs as J
from ..core.rules import fmt_time
from ..core.service import ArchiveService
from . import theme as T
from .widgets import QueueRow, SpectrumView, button, hbox, label, page, rule, scroll, set_tag, vbox


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
        return dict(tag="Down", title=title, artist=artist, pct=job.get("progress") or 0, meta=(job.get("message") or "")[:18], removable=False)
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
        qcol.addWidget(scroll(self.list_host), 1)
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
        # queue list
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
        self.list_host.setUpdatesEnabled(True)
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

    def _theme(self) -> str:
        return getattr(self.svc.settings, "theme", "light")
    pick = Signal(object)        # Candidate
    COLS = ["#", "Title", "Mix", "Artist", "Folder", "User", "Size", "Rate", "Length", "Speed"]
    WIDTHS = [40, 240, 120, 150, 150, 100, 70, 60, 60, 190]

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
        lay.addLayout(srow)
        head = hbox(spacing=12)
        self.title = label("Search", "h2"); head.addWidget(self.title)
        self.state = label("", "faint"); head.addWidget(self.state); head.addStretch(1)
        head.addWidget(label("What you see is what each source reports. Every file is checked before it can reach your library.", "faint"))
        lay.addLayout(head)
        self.tree = QTreeWidget(); self.tree.setColumnCount(len(self.COLS)); self.tree.setHeaderLabels(self.COLS)
        self.tree.setRootIsDecorated(False); self.tree.setSortingEnabled(False); self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionBehavior(QTreeWidget.SelectRows)
        hdr = self.tree.header(); hdr.setSectionResizeMode(QHeaderView.Interactive); hdr.setStretchLastSection(True)
        for i, w in enumerate(self.WIDTHS):
            self.tree.setColumnWidth(i, w)
        self.tree.itemDoubleClicked.connect(lambda *_: self._pick())
        self.tree.itemSelectionChanged.connect(self._selection)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.verticalScrollBar().valueChanged.connect(self._scrolled)
        lay.addWidget(self.tree, 1)
        # empty-state message sits where the rows would be, not up by the search bar
        self.empty = label("", "muted", wrap=True); self.empty.setParent(self.tree.viewport())
        self.empty.setAlignment(Qt.AlignCenter); self.empty.setStyleSheet("font-size: 15px; background: transparent;")
        self.empty.hide()
        self._ranked: list[Candidate] = []
        self._shown = 0
        self._more_item: QTreeWidgetItem | None = None
        self._phrases = ("Asking around", "Knocking on doors", "Still looking", "One second", "Checking the far corners",
                         "Waiting on the slow ones", "Almost there")
        self._anim_i = 0; self._anim_dots = 0; self._anim_query = ""
        self._anim = QTimer(self, interval=400, timeout=self._animate)
        self.tree.viewport().installEventFilter(self)
        row = hbox(spacing=12)
        self.btn = button("Check this file", "primary", self._pick); self.btn.setEnabled(False)
        row.addWidget(self.btn)
        row.addWidget(label("Lands in quarantine, gets checked, then waits for your decision.", "faint"))
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
        self._ranked = []; self._shown = 0; self._fill(0)
        self._anim_query = query; self._anim_i = 0; self._anim_dots = 0
        self.title.setText(f"Searching for “{query}”")
        self.state.setText("")
        self.search_btn.setText("Searching…"); self.search_btn.setEnabled(False)
        self._animate(); self._anim.start()

    def _animate(self):
        self._anim_dots = (self._anim_dots + 1) % 4
        if self._anim_dots == 0:
            self._anim_i = (self._anim_i + 1) % len(self._phrases)
        text = self._phrases[self._anim_i] + "." * (self._anim_dots or 3)
        if self.tree.topLevelItemCount() == 0:
            self._show_empty(f"{text}\nLooking for “{self._anim_query}”")
        else:
            self.state.setText(f"fastest first · {text.lower()}")

    def end_search(self):
        self._anim.stop()
        self.search_btn.setText("Search"); self.search_btn.setEnabled(self.q.isEnabled())

    def show_results(self, res: SearchResult, searching: bool, idle: str = ""):
        if not searching:
            self.end_search()
        n = len(res.candidates)
        if idle:
            self.title.setText("Search"); self.state.setText(""); self._ranked = []; self._fill(0); self._show_empty(idle); return
        self.title.setText(f"{n} source{'s' if n != 1 else ''}")
        skipped = sum(1 for c in res.candidates if c.note)
        locked = sum(1 for c in res.candidates if c.locked and not c.note)
        tail = (f" · {skipped} other format{'s' if skipped != 1 else ''} greyed" if skipped else "") + \
               (f" · {locked} locked" if locked else "")
        if res.error:
            self.state.setText("")
        elif searching:
            self.state.setText("fastest first · still collecting…" + tail)
        else:
            self.state.setText(("fastest first" + tail) if n else "")
        if n == 0:
            if res.error:
                self._show_empty(res.error)
            elif searching:
                pass                                            # the animation owns the empty area while searching
            else:
                self._show_empty("Nobody online is sharing a match right now.\nTry fewer words, or try again in a minute.")
        else:
            self._show_empty("")
        selected = self.tree.selectedItems()
        keep = selected[0].data(0, Qt.UserRole).key if selected and isinstance(selected[0].data(0, Qt.UserRole), Candidate) else None
        self._ranked = sorted(res.candidates, key=_rank)
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
                if c.note:
                    it.setText(9, c.note)
                    it.setToolTip(9, f"{c.note}: .{c.extension or '(none)'} isn't in your accepted formats (Settings → Checks).")
                elif c.locked:
                    it.setToolTip(9, "This user only shares that folder with people on their list. It can't be requested.")
            items.append(it)
        self.tree.addTopLevelItems(items)
        left = len(self._ranked) - self._shown
        if left > 0:
            more = QTreeWidgetItem([""] * len(self.COLS))
            more.setText(1, f"Load {min(PAGE_ROWS, left)} more  ({left} further down the list)")
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

    def _selection(self):
        items = self.tree.selectedItems()
        c = items[0].data(0, Qt.UserRole) if items else None
        self.btn.setEnabled(isinstance(c, Candidate) and not c.note and not c.locked)

    def _pick(self):
        items = self.tree.selectedItems()
        if items and isinstance(items[0].data(0, Qt.UserRole), Candidate):
            self.pick.emit(items[0].data(0, Qt.UserRole))


def _speed(c: Candidate) -> str:
    if c.locked:
        return "Locked"
    rate = f"{c.upload_speed / 1e6:.1f} MB/s" if (c.upload_speed or 0) >= 1e6 else (f"{c.upload_speed / 1e3:.0f} kB/s" if c.upload_speed else "")
    if c.free_slot:
        return f"Free slot · {rate}".rstrip(" ·")
    if c.queue_length is not None:
        return f"{c.queue_length} ahead · {rate}".rstrip(" ·") if c.queue_length < 999 else "Queue full"
    return rate or "?"


def _rank(c: Candidate):
    return (1 if (c.locked or c.note) else 0, 0 if c.free_slot else 1,
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
        rail.addWidget(scroll(self.rail_host), 1)
        rail.addWidget(label("↑↓ move · ⏎ download · ⌫ delete", "mono"))
        rw = QWidget(); rw.setLayout(rail); rw.setMinimumWidth(240); rw.setMaximumWidth(300)
        body.addWidget(rw, 1)

        # detail
        det = vbox(spacing=22)
        head = hbox(spacing=20)
        names = vbox(spacing=4)
        self.source = label("", "tag"); self.h1 = label("", "h1"); self.h1.setWordWrap(True); self.artist = label("", "muted")
        self.artist.setStyleSheet("font-size: 15px;")
        names.addWidget(self.source); names.addWidget(self.h1); names.addWidget(self.artist)
        head.addLayout(names, 1)
        verdict = vbox(spacing=4); verdict.setAlignment(Qt.AlignRight)
        self.verdict = label("", "verdict"); self.verdict.setAlignment(Qt.AlignRight)
        self.verdict_sub = label("", "faint"); self.verdict_sub.setAlignment(Qt.AlignRight)
        verdict.addWidget(self.verdict); verdict.addWidget(self.verdict_sub)
        head.addLayout(verdict)
        det.addLayout(head)

        det.addWidget(rule())
        facts = QGridLayout(); facts.setHorizontalSpacing(14); facts.setVerticalSpacing(4)
        self.facts = {}
        for i, k in enumerate(("Format", "Bitrate", "Rate", "Length", "Channels", "Plays")):
            facts.addWidget(label(k.upper(), "tag"), 0, i)
            v = label("–", "monotext"); facts.addWidget(v, 1, i); self.facts[k] = v
        det.addLayout(facts)
        det.addWidget(rule())

        sh = hbox(); sh.addWidget(label("Spectrogram", "h2")); sh.addStretch(1)
        self.spec_note = label("", "muted"); sh.addWidget(self.spec_note)
        det.addLayout(sh)
        self.spectrum = SpectrumView(180); det.addWidget(self.spectrum)

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
        self.btn_open = button("Open folder", "ghost", lambda: self.open_folder.emit(self.job_id))
        self.btn_reveal = button("Show in folder", "ghost", lambda: self.reveal.emit(self.job_id))
        self.btn_remove = button("Remove from list", "ghost", lambda: self.remove_job.emit(self.job_id))
        self.btn_remove.setToolTip("Takes it off the queue. Downloaded files stay in your library.")
        for b in (self.btn_save, self.btn_anyway, self.btn_delete, self.btn_cancel, self.btn_remove):
            actions.addWidget(b)
        actions.addStretch(1)
        actions.addWidget(self.btn_rerun); actions.addWidget(self.btn_reveal); actions.addWidget(self.btn_open)
        det.addWidget(self.actions_host)
        dw = QWidget(); dw.setLayout(det)
        body.addWidget(dw, 3)
        self.show_job(None, None)

    def set_busy(self, on: bool):
        """While a Download/Delete is being carried out off-thread, the decision buttons can't be pressed twice."""
        if on:
            for b in (self.btn_save, self.btn_anyway, self.btn_delete, self.btn_remove):
                b.setEnabled(False)
        # when it's over, the next refresh() sets every button from the job's real state

    def set_rail(self, jobs: list[dict], analyses: dict[str, dict | None], steps: dict[str, str]):
        while self.rail.count() > 1:
            item = self.rail.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        shown = jobs
        self.rail_count.setText(str(sum(1 for j in shown if j["state"] == J.READY)))
        for j in shown:
            d = row_data(j, analyses.get(j["id"]), steps)
            w = QWidget(); w.setObjectName("row"); w.setCursor(Qt.PointingHandCursor); w.setProperty("tag", d["tag"])
            hl = hbox(w, (4, 9, 10, 9), 10)
            if d["removable"]:
                x = button("×", "x", lambda _=False, jid=j["id"]: self.remove_job.emit(jid)); x.setToolTip("Remove from the list")
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
            w.setProperty("selected", "true" if j["id"] == self.job_id else "false")
            self.rail.insertWidget(self.rail.count() - 1, w)

    def show_job(self, job: dict | None, a: dict | None, steps: dict[str, str] | None = None):
        self.job_id = job["id"] if job else None
        for b in (self.btn_save, self.btn_anyway, self.btn_delete, self.btn_cancel, self.btn_rerun, self.btn_open, self.btn_reveal, self.btn_remove):
            b.setVisible(bool(job))
        while self.checks.count():
            item = self.checks.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not job:
            self.source.setText(""); self.h1.setText("Pick a track from the list"); self.artist.setText("")
            self.verdict.setText(""); self.verdict_sub.setText("")
            for v in self.facts.values(): v.setText("–")
            self.spectrum.clear_view(""); self.spec_note.setText("")
            return
        d = row_data(job, a, steps or {})
        src = "from a soulseek user" if job.get("remote_user") else job.get("source_kind", "")
        self.source.setText(f"{(a or {}).get('facts', {}).get('tags', {}).get('album') or ''}  ·  {src}".strip(" ·").upper())
        self.h1.setText(d["title"]); self.artist.setText(d["artist"])
        busy = job["state"] in (J.STAGING, J.ANALYZING, J.QUEUED)
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
            played = dec.get("decoded_s")
            dec_ok = a.get("decode_ok") and next((c for c in a["checks"] if c["id"] == "decode"), {}).get("status") != "FAIL"
            self.facts["Plays"].setText("–" if played is None else ("All the way" if dec_ok else f"Stops at {fmt_time(played)}"))
            if a.get("spectrogram_path") and Path(a["spectrogram_path"]).exists():
                self.spectrum.show_png(a["spectrogram_path"], f.get("sample_rate_hz"), a.get("cutoff_hz"),
                                       audio=_audio_path(job), duration_s=f.get("duration_s"))
            else:
                self.spectrum.clear_view("Spectrogram unavailable." if job["state"] not in J.FINAL else "Staged copy removed.")
            cut = a.get("cutoff_hz")
            self.spec_note.setText(f"Energy reaches about {cut / 1000:.1f} kHz" if cut else "")
            for c in sorted(a["checks"], key=lambda c: {"FAIL": 0, "WARN": 1, "PASS": 2}[c["status"]]):
                row = QWidget(); hl = hbox(row, (0, 10, 0, 10), 14)
                word = T.GRADE_WORD[c["status"]]
                t = label(word.upper(), "tag", word); t.setFixedWidth(56); t.setAlignment(Qt.AlignTop)
                txt = label(f"<b>{html.escape(c['title'])}</b> — <span style='color: palette(mid)'>{html.escape(c['message'])}</span>", wrap=True)
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
        self.btn_cancel.setVisible(job["state"] == J.QUEUED)
        finished = job["state"] in J.FINAL
        self.btn_delete.setVisible(job["state"] != J.QUEUED and not finished); self.btn_delete.setEnabled(job["state"] in (J.READY, J.ERROR))
        self.btn_remove.setVisible(finished)
        self.btn_rerun.setEnabled(job["state"] in (J.READY, J.ERROR) and bool(job["staged_path"]))
        done = job["state"] == J.PROMOTED and bool(job.get("final_path")) and Path(job["final_path"]).exists()
        self.btn_reveal.setVisible(done)
        self.btn_open.setVisible(not done)
        self.btn_open.setText("Open folder")
        target = Path(job["final_path"]).parent if job["state"] == J.PROMOTED and job.get("final_path") else \
            (Path(job["staged_path"]).parent if job.get("staged_path") else None)
        self.btn_open.setEnabled(bool(target and target.exists()))
