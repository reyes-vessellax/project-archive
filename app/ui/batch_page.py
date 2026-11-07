"""Batch page: paste a playlist link or a list (or pick a folder), find a good copy of each track, then
download + check them all. Every file still goes through quarantine and the normal check; nothing is saved
to the library without the user deciding."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView, QPlainTextEdit, QTreeWidget, QTreeWidgetItem, QWidget

from . import theme as T
from .widgets import button, hbox, label, page

STATUS_TEXT = {"waiting": ("Waiting", "faint"), "searching": ("Searching…", "accent"), "found": ("Found", "pass_"),
               "not_found": ("Not found", "fail"), "have": ("Already have it", "muted"), "queued": ("Downloading", "accent"),
               "error": ("Problem", "fail")}


class BatchSignals(QObject):
    loaded = Signal(str, object)        # playlist name, list[batch_runner.Item]
    item = Signal(int, object)          # index, Item
    finished = Signal()
    error = Signal(str)


class BatchPage(QWidget):
    start = Signal(str)                 # pasted text or link
    choose_folder = Signal()
    stop = Signal()
    download_all = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        self.items: list = []
        outer, lay = page(spacing=16, max_width=1240)
        root = hbox(self); root.addWidget(outer)

        lay.addWidget(label("Batch", "h1"))
        lay.addWidget(label("Paste a playlist link from YouTube, SoundCloud, Spotify or Apple Music, paste a list of tracks "
                            "(one per line, or a CSV), or pick a folder of low-quality files to upgrade. Only the track names "
                            "are read. Each track is searched once, then every pick is downloaded into quarantine and checked "
                            "like any other.", "muted", wrap=True))
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Paste a playlist link, or one track per line:  Artist - Title (Mix)")
        self.input.setFixedHeight(120)
        lay.addWidget(self.input)
        acts = hbox(spacing=10)
        self.btn_find = button("Find these tracks", "accent", lambda: self.start.emit(self.input.toPlainText().strip()))
        self.btn_folder = button("Choose a folder…", "ghost", self.choose_folder.emit)
        self.btn_stop = button("Stop", "ghost", self.stop.emit); self.btn_stop.setVisible(False)
        acts.addWidget(self.btn_find); acts.addWidget(self.btn_folder); acts.addWidget(self.btn_stop); acts.addStretch(1)
        lay.addLayout(acts)

        head = hbox(spacing=12)
        self.name = label("", "h2"); self.summary = label("", "mono")
        self.btn_all = button("Download and check", "accent", self.download_all.emit); self.btn_all.setVisible(False)
        head.addWidget(self.name); head.addWidget(self.summary); head.addStretch(1); head.addWidget(self.btn_all)
        lay.addLayout(head)
        self.message = label("", "muted", wrap=True); self.message.setVisible(False); lay.addWidget(self.message)

        self.tree = QTreeWidget(); self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["From the list", "Best copy we found", "Availability", "Status"])
        self.tree.setRootIsDecorated(False); self.tree.setUniformRowHeights(True); self.tree.setAlternatingRowColors(False)
        h = self.tree.header(); h.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, w in ((1, 200), (2, 170), (3, 150)):
            h.setSectionResizeMode(col, QHeaderView.Interactive); h.resizeSection(col, w)
        lay.addWidget(self.tree, 1)
        self.empty = label("Your list shows up here: what we found for each track, how soon it can start, and what "
                           "you already have.", "faint", wrap=True)
        lay.addWidget(self.empty)
        self.tree.setVisible(False)

    # ------------------------------------------------------------------ view updates
    def set_running(self, running: bool) -> None:
        self.btn_find.setEnabled(not running); self.btn_folder.setEnabled(not running)
        self.btn_stop.setVisible(running)
        self._update_summary()

    def show_message(self, text: str) -> None:
        self.message.setText(text); self.message.setVisible(bool(text))

    def set_items(self, name: str, items: list) -> None:
        self.items = items
        self.name.setText(name)
        self.tree.setVisible(bool(items)); self.empty.setVisible(not items)
        self.tree.clear()
        for it in items:
            self.tree.addTopLevelItem(QTreeWidgetItem(["", "", "", ""]))
        for i, it in enumerate(items):
            self.update_item(i, it)
        self.show_message("" if items else "No tracks found in that. Check the link, or paste the track names instead.")

    def update_item(self, i: int, it) -> None:
        row = self.tree.topLevelItem(i)
        if row is None:
            return
        w = it.wanted
        row.setText(0, w.label); row.setToolTip(0, w.source)
        row.setText(1, it.detail); row.setText(2, it.avail)
        text, tone = STATUS_TEXT.get(it.status, (it.status, "muted"))
        row.setText(3, text)
        c = T.colours(getattr(self, "_theme", "light"))
        row.setForeground(3, QColor(c.get(tone, c["muted"])))
        self._update_summary()

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        for i, it in enumerate(self.items):
            self.update_item(i, it)

    def _update_summary(self) -> None:
        n = {k: sum(1 for it in self.items if it.status == k) for k in STATUS_TEXT}
        if not self.items:
            self.summary.setText(""); self.btn_all.setVisible(False); return
        parts = [f"{n['found']} found"]
        if n["queued"]:
            parts.append(f"{n['queued']} downloading")
        if n["have"]:
            parts.append(f"{n['have']} already have")
        if n["not_found"]:
            parts.append(f"{n['not_found']} not found")
        left = n["waiting"] + n["searching"]
        if left:
            parts.append(f"{left} to go")
        self.summary.setText(" · ".join(parts))
        self.btn_all.setText(f"Download and check {n['found']}")
        self.btn_all.setVisible(n["found"] > 0)
