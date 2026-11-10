"""Library: everything you've downloaded, with its facts, a search box, and Show in folder."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPixmap
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHeaderView, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QWidget
from ..media.musical import compatible_keys

from ..core import jobs as J
from ..core.rules import fmt_time
from ..core.service import ArchiveService
from . import theme as T
from .widgets import KeepColourDelegate, smooth, SpectrumView, button, hbox, label, page, vbox


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


class PillDelegate(KeepColourDelegate):
    """The Checked column as a coloured pill (GOOD / LOOK / BROKEN, plus CLUB when it's club-ready)."""

    def __init__(self, parent, column: int):
        super().__init__(parent)
        self.column = column

    def paint(self, painter, option, index):
        if index.column() != self.column or not index.data():
            return super().paint(painter, option, index)
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QFont, QPainter
        from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
        opt = QStyleOptionViewItem(option); opt.text = ""
        option.widget.style().drawControl(QStyle.CE_ItemViewItem, opt, painter, option.widget)   # row background
        text = str(index.data())
        fg = index.data(Qt.ForegroundRole)
        col = fg.color() if hasattr(fg, "color") else QColor("#1f8a4c")
        painter.save(); painter.setRenderHint(QPainter.Antialiasing)
        f = QFont("IBM Plex Mono"); f.setPixelSize(10); f.setBold(True); painter.setFont(f)
        w = painter.fontMetrics().horizontalAdvance(text) + 14
        r = QRectF(option.rect.left() + 4, option.rect.center().y() - 9, w, 18)
        bg = QColor(col); bg.setAlpha(36)
        painter.setPen(Qt.NoPen); painter.setBrush(bg); painter.drawRoundedRect(r, 9, 9)
        painter.setPen(col); painter.drawText(r, int(Qt.AlignCenter), text)
        painter.restore()


class LibraryPage(QWidget):
    open_job = Signal(str)
    delete_job = Signal(str)          # move the file to the Trash and take it out of the library
    club_copy = Signal(str)           # make a verified club-ready copy
    crates_changed = Signal()
    COLS = ["Title", "Artist", "Mix", "BPM", "Key", "Format", "Bitrate", "Length", "Checked", "Added", "File"]
    WIDTHS = [200, 150, 80, 64, 50, 64, 96, 56, 128, 92, 160]
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
        self.export_btn = button("Export to Rekordbox", "ghost", self._export_rekordbox)
        self.export_btn.setToolTip("The tracks shown here as a Rekordbox playlist: BPM, key and a hot cue at the drop. "
                                   "Optionally copies the files to a USB stick.")
        head.addWidget(self.export_btn)
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
        self.tree.setObjectName("booth")                     # dense, fast rows (see theme)
        self.tree.setItemDelegate(PillDelegate(self.tree, self.C_GRADE))
        from PySide6.QtGui import QFont
        self._mono = QFont("IBM Plex Mono"); self._mono.setPixelSize(12)
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
        self.crate_id: str | None = None
        self._crate_members: set[str] = set()
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

    def set_crate(self, crate_id: str | None, name: str = ""):
        """Show one crate (None = the whole library)."""
        self.crate_id = crate_id
        self.crate_name = name if crate_id else None
        self._crate_members = self.svc.db.crate_jobs(crate_id) if crate_id else set()
        self.title.setText(name or "Library")
        self._key = None
        self.refresh()

    def _crate_menu(self):
        from PySide6.QtWidgets import QInputDialog, QMenu
        it = self._selected()
        if not it:
            return
        job_id = it.data(0, Qt.UserRole)
        m = QMenu(self)
        inside = self.svc.db.crates_of(job_id)
        for c in self.svc.db.crates():
            a = m.addAction(("✓  " if c["id"] in inside else "     ") + c["name"])
            a.triggered.connect(lambda _=False, cid=c["id"]: (self.svc.db.add_to_crate(cid, job_id), self.crates_changed.emit()))
        if self.svc.db.crates():
            m.addSeparator()
        new = m.addAction("New crate…")

        def make():
            name, ok = QInputDialog.getText(self, "New crate", "Crate name:")
            if ok and name.strip():
                cid = self.svc.db.create_crate(name)
                self.svc.db.add_to_crate(cid, job_id)
                self.crates_changed.emit()
        new.triggered.connect(make)
        m.exec(self.btn_crate.mapToGlobal(self.btn_crate.rect().bottomLeft()))

    def _remove_from_crate(self):
        it = self._selected()
        if it and self.crate_id:
            self.svc.db.remove_from_crate(self.crate_id, it.data(0, Qt.UserRole))
            self.crates_changed.emit()
            self.set_crate(self.crate_id, self.title.text())

    def _delete(self):
        it = self._selected()
        if it:
            self.delete_job.emit(it.data(0, Qt.UserRole))

    def _filter(self, text: str):
        """Typing in the filter (or picking a key, BPM range, playlist) hides and shows rows that already exist.
        The rows themselves are only built when the library changes (refresh), not on every keystroke."""
        if getattr(self, "_built_key", None) != getattr(self, "_key", None):
            self._build_items()
        words = [w for w in text.lower().split() if w]
        lo_hi = self._bpm_range()
        want_pl = self.pl_box.currentData() if hasattr(self, "pl_box") else ""
        want_key = self.key_box.currentData() if hasattr(self, "key_box") else ""
        compat = compatible_keys(want_key) if want_key else None
        keep = self._open_id
        shown, open_hidden = 0, False
        self.tree.setUpdatesEnabled(False)
        for it, rec in self._items:
            ok = True
            if lo_hi and (not rec["bpm"] or not (lo_hi[0] <= rec["bpm"] <= lo_hi[1])):
                ok = False
            elif self.crate_id and rec["id"] not in self._crate_members:
                ok = False
            elif want_pl and rec["playlist"] != want_pl:
                ok = False
            elif compat is not None and rec["cam"] not in compat:
                ok = False
            elif words and not all(w in rec["hay"] for w in words):
                ok = False
            if it.isHidden() == ok:
                it.setHidden(not ok)
            shown += ok
            if not ok and rec["id"] == keep:
                open_hidden = True
        self.tree.setUpdatesEnabled(True)
        if open_hidden:
            self._collapse()
        total = len(self._items) if not self.crate_id else sum(1 for _, r in self._items if r["id"] in self._crate_members)
        filtered = bool(words or lo_hi or want_pl or want_key)
        self.sub.setText(f"{shown} of {total} tracks" if filtered else f"{total} track{'s' if total != 1 else ''}")
        self.empty.setVisible(total == 0)

    def _build_items(self):
        """One row per library track, with what the filter needs worked out once (no file checks per keystroke)."""
        from PySide6.QtGui import QColor
        from ..adapters.base import parse_track
        self._built_key = getattr(self, "_key", None)
        keep = self._open_id
        scroll_at = self.tree.verticalScrollBar().value()
        self.tree.blockSignals(True)                         # rebuilding isn't a selection change
        self._park_panel()                                   # clear() would delete it with the rows
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        pal = T.colours(getattr(self.svc.settings, "theme", "light"))
        accent = QColor(pal["accent"])
        grade_col = {k: QColor(pal[v]) for k, v in (("PASS", "pass_"), ("WARN", "warn"), ("FAIL", "fail"))}
        mid = self.palette().mid()
        self._items = []
        items = []
        for job, a in self._rows:
            f = (a or {}).get("facts", {}) if a else {}
            tags = f.get("tags", {}) or {}
            p_artist, p_title, p_mix = parse_track(job["original_name"])
            meta, mu = (a or {}).get("meta") or {}, (a or {}).get("music") or {}
            artist = meta.get("artist") or tags.get("artist") or p_artist
            title = meta.get("title") or tags.get("title") or p_title
            mix = meta["mix"] if "mix" in meta else p_mix          # the check already dropped catalogue numbers
            bpm, cam = mu.get("bpm"), mu.get("camelot") or ""
            final = job.get("final_path") or ""
            fname = Path(final).name
            grade = T.GRADE_LONG.get((a or {}).get("overall_status", ""), "")
            added = (job.get("updated_at") or "")[:10]
            kbps = f"{round(f['bitrate_bps'] / 1000)} {f.get('bitrate_mode') if f.get('bitrate_mode') in ('CBR','VBR') else 'kbps'}" if f.get("bitrate_bps") else ("lossless" if f.get("lossless") else "")
            club = ((a or {}).get("club") or {})
            pill = {"Good": "GOOD", "Have a look": "LOOK", "Broken": "BROKEN"}.get(grade, grade.upper())
            if pill and club.get("ready") and not club.get("error"):
                pill += " · CLUB"
            it = QTreeWidgetItem([title, artist, mix, "", cam, (f.get("container") or "").upper(), kbps,
                                  fmt_time(f["duration_s"]) if f.get("duration_s") else "", pill, added, fname])
            for c in (self.C_BPM, self.C_KEY, self.C_FMT, self.C_KBPS, self.C_LEN, self.C_ADDED):
                it.setFont(c, self._mono)
            if bpm:
                it.setData(self.C_BPM, Qt.DisplayRole, round(float(bpm), 1))      # sorts as a number
            it.setForeground(self.C_KEY, accent)
            st = (a or {}).get("overall_status", "")
            if st:
                it.setForeground(self.C_GRADE, grade_col.get(st, mid))
            it.setData(0, Qt.UserRole, job["id"]); it.setData(0, Qt.UserRole + 1, final)
            it.setToolTip(self.C_FILE, final)
            if not Path(final).exists():
                for c in range(self.tree.columnCount()):
                    it.setForeground(c, mid)
                it.setText(self.C_FILE, fname + "  (moved or deleted)")
            hay = " ".join([artist, title, mix, tags.get("album", ""), fname, job["original_name"]]).lower()
            self._items.append((it, {"id": job["id"], "bpm": bpm, "cam": cam, "playlist": job.get("playlist"), "hay": hay}))
            items.append(it)
        self.tree.addTopLevelItems(items)
        self.tree.setSortingEnabled(True)
        reselected = False
        if keep:
            for it, rec in self._items:
                if rec["id"] == keep:
                    it.setSelected(True); reselected = True; break
        self.tree.blockSignals(False)
        if keep and not reselected:
            self._collapse()
        elif keep and reselected:
            self._mount_panel(self._item_for(keep), animate=False)
        self.tree.verticalScrollBar().setValue(scroll_at)
        QTimer.singleShot(0, lambda v=scroll_at: self.tree.verticalScrollBar().setValue(v))

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
        panel = QFrame(); panel.setObjectName("dropcard")
        outer = vbox(panel, (20, 14, 20, 14), 12)
        pl = hbox(spacing=24); outer.addLayout(pl)
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
        grid.setColumnStretch(0, 0); grid.setColumnStretch(1, 1)     # values sit right next to their labels
        self.facts = {}
        for i, name in enumerate(("Verdict", "BPM", "Key", "Format", "Bitrate", "Rate", "Length", "Added", "File")):
            k = label(name.upper(), "tag"); v = label("", "monotext"); v.setWordWrap(True)
            k.setFixedWidth(84); grid.addWidget(k, i, 0, Qt.AlignTop); grid.addWidget(v, i, 1)
            self.facts[name] = v
        right.addLayout(grid)
        self.checks_host = vbox(spacing=4); right.addLayout(self.checks_host)
        right.addStretch(1)
        acts = hbox(spacing=10)
        self.btn_reveal = button("Show in folder", "primary", self._reveal)
        self.btn_close = button("Close", "ghost", self._collapse)
        self.btn_crate = button("Add to crate ▾", "ghost", self._crate_menu)
        self.btn_uncrate = button("Remove from crate", "ghost", self._remove_from_crate)
        self.btn_club = button("Make a club-ready copy", "ghost", lambda: self._open_id and self.club_copy.emit(self._open_id))
        self.btn_club.setToolTip("Converts the format so every CDJ and Rekordbox loads it, proves the copy matches the "
                                 "original, then checks it like any new file. The original is never changed.")
        self.btn_delete = button("Delete from library", "danger", self._delete)
        self.btn_delete.setToolTip(f"Moves the file to the {'Recycle Bin' if sys.platform == 'win32' else 'Trash'} "
                                   "(you can still get it back from there)")
        acts.addWidget(self.btn_reveal); acts.addWidget(self.btn_crate); acts.addWidget(self.btn_uncrate); acts.addWidget(self.btn_club)
        acts.addStretch(1); acts.addWidget(self.btn_delete); acts.addWidget(self.btn_close)
        for b in (self.btn_reveal, self.btn_close, self.btn_crate, self.btn_uncrate, self.btn_delete, self.btn_club):
            b.setMinimumWidth(b.sizeHint().width() + 8)       # a squeezed button cut its own label off
        pl.addLayout(right, 2)
        outer.addLayout(acts)                                  # across the whole drop-down, under both columns
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
        width = max(300, self.tree.viewport().width() - 2)
        self.panel.setFixedWidth(width)                     # measure at the real width: measured narrow, the wrapped
        lay = self.panel.layout()                           # check text came out tall and left a big empty gap
        lay.activate()
        full = max(lay.heightForWidth(width) if lay.hasHeightForWidth() else self.panel.sizeHint().height(), 220)
        self._grow_target = full
        self.panel.setFixedHeight(12 if animate else full)
        self.panel.setFixedWidth(max(300, self.tree.viewport().width() - 2))
        child.setSizeHint(0, self.panel.size())
        self.tree.setItemWidget(child, 0, self.panel)       # parented into the tree first, shown after
        self.panel.show()
        it.setExpanded(True)
        self._scroll_to_panel = animate                            # only a row the user just opened is brought into view;
        if animate:                                          # a refresh re-mounting the panel must not move the list
            self._anim.start()
        else:
            self._grow_step()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.panel is not None and self._child is not None:
            try:
                self.panel.setFixedWidth(max(300, self.tree.viewport().width() - 2))
                self._child.setSizeHint(0, self.panel.size())
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
            self._child.setSizeHint(0, self.panel.size())   # the view re-measures just this row (a full
        if nh >= self._grow_target:                            # relayout was 70 ms a frame on a big library)
            self._anim.stop()
            if self._child is not None and getattr(self, "_scroll_to_panel", False):
                self._scroll_to_panel = False
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
        from ..media.metadata import clean_label
        self.p_meta.setText("  ·  ".join(x for x in (clean_label(meta.get("label") or ""), meta.get("year"), meta.get("genre")) if x))
        cov = meta.get("cover_path")
        pm = QPixmap(cov) if cov and Path(cov).exists() else QPixmap()
        self.p_cover.setVisible(not pm.isNull())
        if not pm.isNull():
            self.p_cover.setPixmap(pm.scaled(72, 72, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        exists = bool(final) and Path(final).exists()
        if a.get("spectrogram_path") and Path(a["spectrogram_path"]).exists():
            self.spectrum.show_png(a["spectrogram_path"], f.get("sample_rate_hz"), a.get("cutoff_hz"),
                                   audio=final if exists else None, duration_s=f.get("duration_s"))
            self.spectrum.set_cutoff_bad(next((c["status"] for c in a.get("checks", []) if c["id"] == "spectrum"), "PASS") != "PASS")
            self.spectrum.set_preview(mu.get("drop_s"), None)
            self.spectrum.set_track(it.text(0), it.text(1))
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
        self.facts["BPM"].setText((f"{mu['bpm']:g}" + ("  · from tags" if mu.get("bpm_from_tags") else ""))
                                  if mu.get("bpm") else "–")
        self.facts["Key"].setText((f"{mu['camelot']}  ({mu['key']})" + ("  · from tags" if mu.get("key_from_tags") else ""))
                                  if mu.get("camelot") else "–")
        self.facts["Added"].setText(it.text(self.C_ADDED))

        self.facts["File"].setText(Path(final).name + ("" if exists else "  (moved or deleted)"))
        self.facts["File"].setToolTip(final)
        self.btn_uncrate.setVisible(bool(self.crate_id))
        self.btn_delete.setEnabled(True)
        while self.checks_host.count():
            w = self.checks_host.takeAt(0).widget()
            if w:
                w.hide(); w.deleteLater()      # hidden now: no ghost rows painted over the new ones
        from .widgets import club_badges, club_heading
        club = (a.get("club") or {}).get("checks") or []
        rows = sorted(a.get("checks", []), key=lambda c: {"FAIL": 0, "WARN": 1, "PASS": 2}.get(c["status"], 3))
        rows += [None] + sorted(club, key=lambda c: {"FAIL": 0, "WARN": 1, "PASS": 2}.get(c["status"], 3)) if club else []
        for c in rows:
            if c is None:
                head = club_badges(a, getattr(self.svc.settings, "theme", "light"))
                if head is not None:
                    head.setContentsMargins(0, 10, 0, 2); self.checks_host.addWidget(head)
                continue
            row = QWidget(); hl = hbox(row, (0, 2, 0, 2), 10)
            word = T.GRADE_WORD.get(c["status"], c["status"])
            tag = label(word.upper(), "tag", word); tag.setFixedWidth(56); tag.setAlignment(Qt.AlignTop)
            import html as _h
            muted = T.colours(getattr(self.svc.settings, "theme", "light"))["muted"]
            txt = label(f"<b>{_h.escape(c['title'])}</b> — <span style='color: {muted}'>{_h.escape(c['message'])}</span>", wrap=True)
            hl.addWidget(tag); hl.addWidget(txt, 1)
            self.checks_host.addWidget(row)
        self.btn_reveal.setEnabled(exists)
        from ..media.clubcopy import needs_copy
        self.btn_club.setVisible(exists and needs_copy(a.get("club")))

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

    def _export_rekordbox(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from ..config import APP_VERSION
        from ..core.rekordbox import export, from_library
        ids = [rec["id"] for it, rec in getattr(self, "_items", []) if not it.isHidden()]
        tracks = from_library(self.svc, ids)
        if not tracks:
            QMessageBox.information(self, "Export to Rekordbox", "No tracks to export here (their files may have moved).")
            return
        name = getattr(self, "crate_name", None) or "DigMart"
        default = str(Path.home() / "Music" / f"{name} rekordbox.xml")
        path, _ = QFileDialog.getSaveFileName(self, "Save the Rekordbox playlist", default, "rekordbox xml (*.xml)")
        if not path:
            return
        usb = None
        if QMessageBox.question(self, "Export to Rekordbox",
                                f"Also copy the {len(tracks)} files to a USB stick or folder?\n\n"
                                "Yes: choose where; the playlist will point at the copies. No: it points at your "
                                "library files.") == QMessageBox.Yes:
            usb = QFileDialog.getExistingDirectory(self, "Copy the files to…", str(Path("/Volumes") if Path("/Volumes").exists() else Path.home()))
            if not usb:
                return
        try:
            out = export(tracks, Path(path), f"DigMart · {name}", Path(usb) if usb else None, APP_VERSION)
        except OSError as e:
            QMessageBox.warning(self, "Export to Rekordbox", f"Couldn't export: {e}")
            return
        QMessageBox.information(self, "Export to Rekordbox",
                                f"Saved {out.name} with {len(tracks)} tracks"
                                + (f", and copied the files to {usb}" if usb else "") + ".\n\n"
                                "In Rekordbox: Preferences → Advanced → rekordbox xml → choose this file. The playlist "
                                "appears under “rekordbox xml” in the tree; drag it into your collection. Hot cue A is "
                                "the start, B is the drop.")

    def _open_folder(self):
        d = self.svc.settings.downloads_dir()
        if not d.exists():
            d = Path(self.svc.settings.library_dir)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))
