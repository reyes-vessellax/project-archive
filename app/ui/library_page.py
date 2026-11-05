"""Library: everything you've downloaded, with its facts, a search box, and Show in folder."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHeaderView, QLineEdit, QTreeWidget, QTreeWidgetItem, QWidget

from ..core import jobs as J
from ..core.rules import fmt_time
from ..core.service import ArchiveService
from . import theme as T
from .widgets import button, hbox, label, page, vbox


def reveal_in_folder(path: Path) -> None:
    """Open the system file manager with the file selected (Finder / Explorer), not just the folder."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
            return
    except OSError:
        pass
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


class LibraryPage(QWidget):
    open_job = Signal(str)
    COLS = ["Title", "Artist", "Mix", "Format", "Bitrate", "Length", "Checked", "Added", "File"]
    WIDTHS = [220, 150, 110, 70, 90, 60, 90, 130, 260]

    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        self._rows: list[tuple[dict, dict | None]] = []
        outer, lay = page(spacing=18)
        root = vbox(self); root.addWidget(outer)

        srow = hbox(spacing=16)
        self.q = QLineEdit(); self.q.setObjectName("hero"); self.q.setPlaceholderText("Search your downloads…")
        self.q.textChanged.connect(self._filter)
        srow.addWidget(self.q, 1)
        lay.addLayout(srow)

        head = hbox(spacing=12)
        self.title = label("Library", "h2"); head.addWidget(self.title)
        self.sub = label("", "faint"); head.addWidget(self.sub); head.addStretch(1)
        self.folder_btn = button("Open downloads folder", "ghost", self._open_folder); head.addWidget(self.folder_btn)
        lay.addLayout(head)

        self.tree = QTreeWidget(); self.tree.setColumnCount(len(self.COLS)); self.tree.setHeaderLabels(self.COLS)
        self.tree.setRootIsDecorated(False); self.tree.setSortingEnabled(True); self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionBehavior(QTreeWidget.SelectRows)
        hdr = self.tree.header(); hdr.setSectionResizeMode(QHeaderView.Interactive); hdr.setStretchLastSection(True)
        for i, w in enumerate(self.WIDTHS):
            self.tree.setColumnWidth(i, w)
        self.tree.sortByColumn(7, Qt.DescendingOrder)
        self.tree.itemSelectionChanged.connect(self._selection)
        self.tree.itemDoubleClicked.connect(lambda *_: self._reveal())
        lay.addWidget(self.tree, 1)

        row = hbox(spacing=10)
        self.btn_reveal = button("Show in folder", "primary", self._reveal); self.btn_reveal.setEnabled(False)
        self.btn_details = button("Details", "ghost", lambda: self._emit_open()); self.btn_details.setEnabled(False)
        row.addWidget(self.btn_reveal); row.addWidget(self.btn_details); row.addStretch(1)
        self.empty = label("Nothing downloaded yet. Approved tracks show up here.", "faint")
        row.addWidget(self.empty)
        lay.addLayout(row)

    # ---------------------------------------------------------------- data
    def refresh(self):
        jobs = self.svc.db.jobs(states=(J.PROMOTED,), limit=5000)
        self._rows = [(j, self.svc.db.analysis(j["id"])) for j in jobs]
        self._filter(self.q.text())

    def _filter(self, text: str):
        words = [w for w in text.lower().split() if w]
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        shown = 0
        for job, a in self._rows:
            f = (a or {}).get("facts", {}) if a else {}
            tags = f.get("tags", {}) or {}
            from ..adapters.base import parse_track
            p_artist, p_title, p_mix = parse_track(job["original_name"])
            artist = tags.get("artist") or p_artist
            title = tags.get("title") or p_title
            mix = p_mix
            final = job.get("final_path") or ""
            hay = " ".join([artist, title, mix, tags.get("album", ""), Path(final).name, job["original_name"]]).lower()
            if words and not all(w in hay for w in words):
                continue
            grade = T.GRADE_LONG.get((a or {}).get("overall_status", ""), "")
            added = (job.get("updated_at") or "")[:16].replace("T", " ")
            kbps = f"{round(f['bitrate_bps'] / 1000)} {f.get('bitrate_mode') if f.get('bitrate_mode') in ('CBR','VBR') else 'kbps'}" if f.get("bitrate_bps") else ("lossless" if f.get("lossless") else "")
            it = QTreeWidgetItem([title, artist, mix, (f.get("container") or "").upper(), kbps,
                                  fmt_time(f["duration_s"]) if f.get("duration_s") else "", grade, added, Path(final).name])
            it.setData(0, Qt.UserRole, job["id"]); it.setData(0, Qt.UserRole + 1, final)
            it.setToolTip(8, final)
            if not Path(final).exists():
                for c in range(self.tree.columnCount()):
                    it.setForeground(c, self.palette().mid())
                it.setText(8, Path(final).name + "  (moved or deleted)")
            self.tree.addTopLevelItem(it); shown += 1
        self.tree.setSortingEnabled(True)
        total = len(self._rows)
        self.sub.setText(f"{shown} of {total} tracks" if words else f"{total} track{'s' if total != 1 else ''}")
        self.empty.setVisible(total == 0)

    # ---------------------------------------------------------------- actions
    def _selected(self):
        items = self.tree.selectedItems()
        return items[0] if items else None

    def _selection(self):
        it = self._selected()
        path = Path(it.data(0, Qt.UserRole + 1)) if it else None
        self.btn_reveal.setEnabled(bool(path and path.exists()))
        self.btn_details.setEnabled(bool(it))

    def _reveal(self):
        it = self._selected()
        if it:
            p = Path(it.data(0, Qt.UserRole + 1))
            if p.exists():
                reveal_in_folder(p)

    def _emit_open(self):
        it = self._selected()
        if it:
            self.open_job.emit(it.data(0, Qt.UserRole))

    def _open_folder(self):
        d = self.svc.settings.downloads_dir()
        if not d.exists():
            d = Path(self.svc.settings.library_dir)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))
