"""Library: everything you've downloaded, with its facts, a search box, and Show in folder."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHeaderView, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QWidget
from ..media.musical import compatible_keys

from ..core import jobs as J
from ..core.rules import fmt_time
from ..core.service import ArchiveService
from . import theme as T
from .widgets import smooth, SpectrumView, button, hbox, label, page, vbox


def reveal_in_folder(path: Path) -> None:
    """Open the system file manager with the file selected (Finder / Explorer), not just the folder."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
            return
        if sys.platform == "win32":
            # Explorer wants the switch and the path as one argument: explorer /select,"C:\...\file.mp3"
            subprocess.Popen(f'explorer /select,"{path}"')
            return
    except OSError:
        pass
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


class LibraryPage(QWidget):
    open_job = Signal(str)
    COLS = ["Title", "Artist", "Mix", "BPM", "Key", "Format", "Bitrate", "Length", "Checked", "Added", "File"]
    WIDTHS = [210, 150, 100, 60, 50, 64, 84, 56, 80, 110, 160]
    C_BPM, C_KEY, C_FMT, C_KBPS, C_LEN, C_GRADE, C_ADDED, C_FILE = 3, 4, 5, 6, 7, 8, 9, 10

    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        self._rows: list[tuple[dict, dict | None]] = []
        outer, lay = page(spacing=18)
        root = vbox(self); root.addWidget(outer)

        head = hbox(spacing=12)
        self.title = label("Library", "h1"); head.addWidget(self.title, 0, Qt.AlignBottom)
        self.sub = label("", "mono"); head.addWidget(self.sub, 0, Qt.AlignBottom); head.addStretch(1)
        self.q = QLineEdit(); self.q.setObjectName("filter"); self.q.setPlaceholderText("Filter by title, artist, label…")
        self.q.setFixedWidth(300); self.q.textChanged.connect(self._filter)
        head.addWidget(self.q)
        self.folder_btn = button("Open downloads folder", "ghost", self._open_folder); head.addWidget(self.folder_btn)
        lay.addLayout(head)
        fl = hbox(spacing=10)
        fl.addWidget(label("BPM", "tag"))
        self.bpm_box = QLineEdit(); self.bpm_box.setPlaceholderText("e.g. 120-128"); self.bpm_box.setFixedWidth(120)
        self.bpm_box.textChanged.connect(lambda _: self._filter(self.q.text()))
        fl.addWidget(self.bpm_box); fl.addSpacing(16)
        fl.addWidget(label("MIXES WITH", "tag"))
        self.key_box = QComboBox(); self.key_box.addItem("Any key", "")
        for n in range(1, 13):
            for l in ("A", "B"):
                self.key_box.addItem(f"{n}{l}", f"{n}{l}")
        self.key_box.currentIndexChanged.connect(lambda _: self._filter(self.q.text()))
        fl.addWidget(self.key_box); fl.addSpacing(16)
        self.pl_label = label("PLAYLIST", "tag"); fl.addWidget(self.pl_label)
        self.pl_box = QComboBox(); self.pl_box.addItem("All tracks", "")
        self.pl_box.currentIndexChanged.connect(lambda _: self._filter(self.q.text()))
        fl.addWidget(self.pl_box); fl.addStretch(1)
        lay.addLayout(fl)

        self.tree = QTreeWidget(); self.tree.setColumnCount(len(self.COLS)); self.tree.setHeaderLabels(self.COLS)
        self.tree.setRootIsDecorated(False); self.tree.setSortingEnabled(True); self.tree.setAlternatingRowColors(False)
        self.tree.setIndentation(0)                          # the drop-down row sits flush with its track
        self.tree.setSelectionBehavior(QTreeWidget.SelectRows)
        hdr = self.tree.header(); hdr.setSectionResizeMode(QHeaderView.Interactive); hdr.setStretchLastSection(True)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)       # the File column just clips; full path on hover
        for i, w in enumerate(self.WIDTHS):
            self.tree.setColumnWidth(i, w)
        self.tree.sortByColumn(self.C_ADDED, Qt.DescendingOrder)
        self.tree.itemSelectionChanged.connect(self._selection)
        smooth(self.tree)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemDoubleClicked.connect(lambda *_: self._reveal())
        lay.addWidget(self.tree, 1)

        # the drop-down: built fresh each time it opens, as a full-width row under the clicked track
        self.panel: QFrame | None = None
        self.spectrum: SpectrumView | None = None
        self._accent = "#dc143c"
        self._child: QTreeWidgetItem | None = None
        self._anim = QTimer(self, interval=16, timeout=self._grow_step); self._grow_target = 0
        self.empty = label("Nothing downloaded yet. Approved tracks show up here.", "faint")
        lay.addWidget(self.empty)
        self._open_id: str | None = None
        self._just_expanded = False

    # ---------------------------------------------------------------- data
    def refresh(self):
        jobs = self.svc.db.jobs(states=(J.PROMOTED,), limit=5000)
        key = tuple((j["id"], j.get("final_path"), j.get("updated_at")) for j in jobs)
        if key == getattr(self, "_key", None):
            return                                           # nothing changed: don't rebuild (that closed the drop-down)
        self._key = key
        self._rows = [(j, self.svc.db.analysis(j["id"])) for j in jobs]
        names = sorted({j["playlist"] for j in jobs if j.get("playlist")}, key=str.lower)
        current = self.pl_box.currentData()
        self.pl_box.blockSignals(True); self.pl_box.clear(); self.pl_box.addItem("All tracks", "")
        for n in names:
            self.pl_box.addItem(n, n)
        self.pl_box.setCurrentIndex(max(0, self.pl_box.findData(current)))
        self.pl_box.blockSignals(False)
        self.pl_box.setVisible(bool(names)); self.pl_label.setVisible(bool(names))
        self._filter(self.q.text())

    def _filter(self, text: str):
        words = [w for w in text.lower().split() if w]
        keep = self._open_id
        scroll_at = self.tree.verticalScrollBar().value()
        self.tree.blockSignals(True)                         # rebuilding isn't a selection change
        self._park_panel()                                   # clear() would delete it with the rows
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        shown = 0
        for job, a in self._rows:
            f = (a or {}).get("facts", {}) if a else {}
            tags = f.get("tags", {}) or {}
            from ..adapters.base import parse_track
            p_artist, p_title, p_mix = parse_track(job["original_name"])
            meta, mu = (a or {}).get("meta") or {}, (a or {}).get("music") or {}
            artist = meta.get("artist") or tags.get("artist") or p_artist
            title = meta.get("title") or tags.get("title") or p_title
            mix = meta["mix"] if "mix" in meta else p_mix          # the check already dropped catalogue numbers
            bpm, cam = mu.get("bpm"), mu.get("camelot") or ""
            lo_hi = self._bpm_range()
            if lo_hi and (not bpm or not (lo_hi[0] <= bpm <= lo_hi[1])):
                continue
            want_pl = self.pl_box.currentData() if hasattr(self, "pl_box") else ""
            if want_pl and job.get("playlist") != want_pl:
                continue
            want_key = self.key_box.currentData() if hasattr(self, "key_box") else ""
            if want_key and cam not in compatible_keys(want_key):
                continue
            final = job.get("final_path") or ""
            hay = " ".join([artist, title, mix, tags.get("album", ""), Path(final).name, job["original_name"]]).lower()
            if words and not all(w in hay for w in words):
                continue
            grade = T.GRADE_LONG.get((a or {}).get("overall_status", ""), "")
            added = (job.get("updated_at") or "")[:10]
            kbps = f"{round(f['bitrate_bps'] / 1000)} {f.get('bitrate_mode') if f.get('bitrate_mode') in ('CBR','VBR') else 'kbps'}" if f.get("bitrate_bps") else ("lossless" if f.get("lossless") else "")
            it = QTreeWidgetItem([title, artist, mix, "", cam, (f.get("container") or "").upper(), kbps,
                                  fmt_time(f["duration_s"]) if f.get("duration_s") else "", grade, added, Path(final).name])
            if bpm:
                it.setData(self.C_BPM, Qt.DisplayRole, round(float(bpm), 1))      # sorts as a number
            from PySide6.QtGui import QColor
            pal = T.colours(getattr(self.svc.settings, "theme", "light"))
            it.setForeground(self.C_KEY, QColor(pal["accent"]))
            st = (a or {}).get("overall_status", "")
            if st:
                it.setForeground(self.C_GRADE, QColor(pal[{"PASS": "pass_", "WARN": "warn", "FAIL": "fail"}.get(st, "muted")]))
            it.setData(0, Qt.UserRole, job["id"]); it.setData(0, Qt.UserRole + 1, final)
            it.setToolTip(self.C_FILE, final)
            if not Path(final).exists():
                for c in range(self.tree.columnCount()):
                    it.setForeground(c, self.palette().mid())
                it.setText(self.C_FILE, Path(final).name + "  (moved or deleted)")
            self.tree.addTopLevelItem(it); shown += 1
        self.tree.setSortingEnabled(True)
        reselected = False
        if keep:
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                if it.data(0, Qt.UserRole) == keep:
                    it.setSelected(True); reselected = True; break
        self.tree.blockSignals(False)
        if keep and not reselected:
            self._collapse()
        elif keep and reselected:
            self._mount_panel(self._item_for(keep), animate=False)
        self.tree.verticalScrollBar().setValue(scroll_at)
        QTimer.singleShot(0, lambda v=scroll_at: self.tree.verticalScrollBar().setValue(v))
        total = len(self._rows)
        self.sub.setText(f"{shown} of {total} tracks" if words else f"{total} track{'s' if total != 1 else ''}")
        self.empty.setVisible(total == 0)

    # ---------------------------------------------------------------- actions
    def _selected(self):
        items = self.tree.selectedItems()
        return items[0] if items else None

    def _selection(self):
        it = self._selected()
        if it:
            self._expand(it)
        else:
            self._collapse()

    def _clicked(self, item, _col):
        # clicking the row that's already open closes the drop-down (selection changes arrive before clicks)
        if self._just_expanded:
            self._just_expanded = False
            return
        if self._open_id and item.data(0, Qt.UserRole) == self._open_id and self.panel is not None:
            self._collapse(); self.tree.clearSelection()

    def _build_panel(self) -> QFrame:
        panel = QFrame(); panel.setObjectName("card")
        pl = hbox(panel, (20, 16, 20, 16), 24)
        left = vbox(spacing=8)
        top = hbox(spacing=14)
        self.p_cover = QLabel(); self.p_cover.setFixedSize(72, 72); top.addWidget(self.p_cover, 0, Qt.AlignTop)
        names = vbox(spacing=3)
        self.p_title = label("", "h2"); self.p_artist = label("", "muted"); self.p_meta = label("", "faint")
        names.addWidget(self.p_title); names.addWidget(self.p_artist); names.addWidget(self.p_meta)
        top.addLayout(names, 1)
        self.p_preview = button("▶  Preview the drop", "small", lambda: self.spectrum and self.spectrum.play_preview())
        self.p_preview.setVisible(False)                   # downloaded tracks play in full
        left.addLayout(top)
        self.spectrum = SpectrumView(170); self.spectrum.set_accent(self._accent); left.addWidget(self.spectrum)
        self.p_note = label("", "faint"); left.addWidget(self.p_note)
        left.addStretch(1)
        pl.addLayout(left, 3)
        right = vbox(spacing=10)
        grid = QGridLayout(); grid.setHorizontalSpacing(18); grid.setVerticalSpacing(6)
        self.facts = {}
        for i, name in enumerate(("Verdict", "BPM", "Key", "Format", "Bitrate", "Rate", "Length", "Added", "File")):
            k = label(name.upper(), "tag"); v = label("", "monotext"); v.setWordWrap(True)
            grid.addWidget(k, i, 0, Qt.AlignTop); grid.addWidget(v, i, 1)
            self.facts[name] = v
        right.addLayout(grid)
        self.checks_host = vbox(spacing=4); right.addLayout(self.checks_host)
        right.addStretch(1)
        acts = hbox(spacing=10)
        self.btn_reveal = button("Show in folder", "primary", self._reveal)
        self.btn_close = button("Close", "ghost", self._collapse)
        acts.addWidget(self.btn_reveal); acts.addStretch(1); acts.addWidget(self.btn_close)
        right.addLayout(acts)
        pl.addLayout(right, 2)
        return panel

    def set_accent(self, colour: str):
        changed = getattr(self, "_accent", None) != colour
        self._accent = colour
        if changed and hasattr(self, "pl_box"):
            self._key = None                                 # theme changed: recolour the rows
            self.refresh()
        if self.spectrum is not None:
            try:
                self.spectrum.set_accent(colour)
            except RuntimeError:
                pass

    def _item_for(self, job_id: str):
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, Qt.UserRole) == job_id:
                return it
        return None

    def _park_panel(self):
        """Take the open panel out of the tree. The tree owns the widget, so it goes with the row."""
        self._anim.stop()
        if self.spectrum is not None:
            try:
                self.spectrum.stop()
            except RuntimeError:
                pass
        if self._child is not None:
            try:
                parent = self._child.parent()
                if parent is not None:
                    parent.removeChild(self._child)         # deletes the item widget (our panel) with it
            except RuntimeError:
                pass
            self._child = None
        self.panel = None; self.spectrum = None

    def _mount_panel(self, it, animate: bool = True):
        """Slide the panel open as a full-width row directly under `it`; it scrolls with the list."""
        if it is None:
            return
        self._park_panel()
        self.panel = self._build_panel()
        self.panel.setParent(self.tree.viewport()); self.panel.hide()
        self._fill_panel(it)
        child = QTreeWidgetItem(it)
        child.setFlags(Qt.ItemIsEnabled)
        child.setFirstColumnSpanned(True) if hasattr(child, "setFirstColumnSpanned") else None
        self._child = child
        self.panel.setMaximumHeight(16777215)
        self.panel.adjustSize()
        full = max(self.panel.sizeHint().height(), 260)
        self._grow_target = full
        self.panel.setFixedHeight(12 if animate else full)
        self.panel.setFixedWidth(max(300, self.tree.viewport().width() - 2))
        child.setSizeHint(0, self.panel.size())
        self.tree.setItemWidget(child, 0, self.panel)       # parented into the tree first, shown after
        self.panel.show()
        it.setExpanded(True)
        if animate:
            self._anim.start()
        else:
            self._grow_step()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.panel is not None and self._child is not None:
            try:
                self.panel.setFixedWidth(max(300, self.tree.viewport().width() - 2))
                self._child.setSizeHint(0, self.panel.size()); self.tree.doItemsLayout()
            except RuntimeError:
                pass

    def _grow_step(self):
        if self.panel is None:
            self._anim.stop(); return
        h = self.panel.height()
        step = max(10, (self._grow_target - h) // 4)
        nh = min(self._grow_target, h + step)
        self.panel.setFixedHeight(nh)
        if self._child is not None:
            self._child.setSizeHint(0, self.panel.size())
            self.tree.doItemsLayout()
        if nh >= self._grow_target:
            self._anim.stop()
            if self._child is not None:
                self.tree.scrollToItem(self._child, QTreeWidget.EnsureVisible)   # bring the panel into view; no jump to top

    def _collapse(self):
        self._park_panel()
        self._open_id = None
        self._just_expanded = False

    def _expand(self, it):
        job_id = it.data(0, Qt.UserRole)
        if not self.svc.db.job(job_id):
            return
        self._open_id = job_id
        self._just_expanded = True
        self._mount_panel(it)

    def _fill_panel(self, it):
        job_id = it.data(0, Qt.UserRole)
        job = self.svc.db.job(job_id)
        a = self.svc.db.analysis(job_id) or {}
        f = a.get("facts", {}) or {}
        final = job.get("final_path") or ""
        self.p_title.setText(it.text(0) + (f"  ·  {it.text(2)}" if it.text(2) else ""))
        self.p_artist.setText(it.text(1))
        meta, mu = a.get("meta") or {}, a.get("music") or {}
        self.p_meta.setText("  ·  ".join(x for x in (meta.get("label"), meta.get("year"), meta.get("genre")) if x))
        cov = meta.get("cover_path")
        pm = QPixmap(cov) if cov and Path(cov).exists() else QPixmap()
        self.p_cover.setVisible(not pm.isNull())
        if not pm.isNull():
            self.p_cover.setPixmap(pm.scaled(72, 72, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        exists = bool(final) and Path(final).exists()
        if a.get("spectrogram_path") and Path(a["spectrogram_path"]).exists():
            self.spectrum.show_png(a["spectrogram_path"], f.get("sample_rate_hz"), a.get("cutoff_hz"),
                                   audio=final if exists else None, duration_s=f.get("duration_s"))
            self.spectrum.set_preview(mu.get("drop_s"), None)
        elif exists:
            self.spectrum.clear_view("Drawing the spectrogram again…")
            self._redraw(job_id)
        else:
            self.spectrum.clear_view("No spectrogram; the file isn't where it was.")
        cut = a.get("cutoff_hz")
        self.p_note.setText(f"Energy reaches about {cut / 1000:.1f} kHz" if cut else "")
        status = a.get("overall_status", "")
        self.facts["Verdict"].setText(T.GRADE_LONG.get(status, "–"))
        fmt = (f.get("container") or "?").upper()
        self.facts["Format"].setText(fmt if (f.get("codec") or "").upper().startswith(fmt[:3]) or not f.get("codec") else f"{fmt} ({f['codec']})")
        self.facts["Bitrate"].setText(it.text(self.C_KBPS) or "–")
        self.facts["Rate"].setText(f"{f['sample_rate_hz'] / 1000:g} kHz" if f.get("sample_rate_hz") else "–")
        self.facts["Length"].setText(it.text(self.C_LEN) or "–")
        self.facts["BPM"].setText(f"{mu['bpm']:g}" if mu.get("bpm") else "–")
        self.facts["Key"].setText(f"{mu['camelot']}  ({mu['key']})" if mu.get("camelot") else "–")
        self.facts["Added"].setText(it.text(self.C_ADDED))

        self.facts["File"].setText(Path(final).name + ("" if exists else "  (moved or deleted)"))
        self.facts["File"].setToolTip(final)
        while self.checks_host.count():
            w = self.checks_host.takeAt(0).widget()
            if w:
                w.deleteLater()
        for c in sorted(a.get("checks", []), key=lambda c: {"FAIL": 0, "WARN": 1, "PASS": 2}.get(c["status"], 3)):
            row = QWidget(); hl = hbox(row, (0, 2, 0, 2), 10)
            word = T.GRADE_WORD.get(c["status"], c["status"])
            tag = label(word.upper(), "tag", word); tag.setFixedWidth(56); tag.setAlignment(Qt.AlignTop)
            import html as _h
            muted = T.colours(getattr(self.svc.settings, "theme", "light"))["muted"]
            txt = label(f"<b>{_h.escape(c['title'])}</b> — <span style='color: {muted}'>{_h.escape(c['message'])}</span>", wrap=True)
            hl.addWidget(tag); hl.addWidget(txt, 1)
            self.checks_host.addWidget(row)
        self.btn_reveal.setEnabled(exists)

    def _bpm_range(self) -> tuple[float, float] | None:
        import re as _re
        t = self.bpm_box.text().strip() if hasattr(self, "bpm_box") else ""
        m = _re.fullmatch(r"(\d{2,3}(?:\.\d+)?)\s*(?:-|–|to)\s*(\d{2,3}(?:\.\d+)?)", t)
        if m:
            lo, hi = sorted((float(m.group(1)), float(m.group(2))))
            return lo, hi
        m = _re.fullmatch(r"(\d{2,3}(?:\.\d+)?)", t)
        return (float(m.group(1)) - 1.5, float(m.group(1)) + 1.5) if m else None

    def _reveal(self):
        it = self._selected()
        if it:
            p = Path(it.data(0, Qt.UserRole + 1))
            if p.exists():
                reveal_in_folder(p)

    def _redraw(self, job_id: str):
        """The picture was pruned (we keep the newest ~100); decode the library file again, off the UI thread."""
        from PySide6.QtCore import QThreadPool
        from .widgets import Signals, Task
        if not hasattr(self, "_sig"):
            self._sig = Signals(); self._sig.done.connect(self._redrawn)
        self._sig_pool = getattr(self, "_sig_pool", QThreadPool())

        def work():
            try:
                self.svc.redraw_spectrogram(job_id)
            finally:
                self._sig.done.emit(job_id)
        self._sig_pool.start(Task(work, self._sig))

    def _redrawn(self, job_id: str):
        if self._open_id != job_id or self.panel is None:
            return
        it = self._item_for(job_id)
        if it is not None:
            try:
                self._fill_panel(it)
            except RuntimeError:
                pass

    def _emit_open(self):
        it = self._selected()
        if it:
            self.open_job.emit(it.data(0, Qt.UserRole))

    def _open_folder(self):
        d = self.svc.settings.downloads_dir()
        if not d.exists():
            d = Path(self.svc.settings.library_dir)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))
