"""Wishlist page: standing searches. Nobody has it today? Watch for it: asked for again every half hour for
30 days, and the first copy that passes the quality bar lands on Ready (the sidebar shows a count).
Whole playlists go to Batch; this page is for the one-off tracks you're waiting on."""
from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLineEdit, QWidget

from ..core.service import ArchiveService
from ..core.wishlist import WISH_DAYS, Wishlist, split_query, wish_label
from .widgets import button, hbox, keep_scroll, label, rule, scroll, vbox

# his theme's tag colours: Good (found), Down (being checked), Wait (watching / paused), Error (expired)
TAGS = {"watching": ("Wait", "WATCHING"), "checking": ("Down", "CHECKING"), "found": ("Good", "FOUND"),
        "paused": ("Wait", "PAUSED"), "expired": ("Error", "EXPIRED")}


def _ago(iso: str | None) -> str:
    if not iso:
        return "not yet"
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    s = int((datetime.now(timezone.utc) - then).total_seconds())
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} h ago"
    return f"{s // 86400} d ago"


class WishForm(QFrame):
    """Artist · Title · Mix, any of them optional, and a Watch button. Inline, never a dialog."""
    submitted = Signal(str, str, str)
    cancelled = Signal()

    def __init__(self, prompt: str = "Fill in what you know, as much or as little as you like.", cancel: bool = True):
        super().__init__()
        self.setObjectName("dropzone")
        lay = vbox(self, (16, 14, 16, 14), 10)
        lay.addWidget(label(prompt, "muted"))
        row = hbox(spacing=10)
        self.artist = QLineEdit(); self.artist.setPlaceholderText("Artist")
        self.title = QLineEdit(); self.title.setPlaceholderText("Title")
        self.mix = QLineEdit(); self.mix.setPlaceholderText("Mix (optional)")
        for e in (self.artist, self.title, self.mix):
            e.returnPressed.connect(self._go)
        row.addWidget(self.artist, 3); row.addWidget(self.title, 4); row.addWidget(self.mix, 3)
        self.btn = button("Watch", "primary", self._go); row.addWidget(self.btn)
        if cancel:
            row.addWidget(button("Cancel", "ghost", self.cancelled.emit))
        lay.addLayout(row)
        lay.addWidget(label(f"Asked for again every half hour for {WISH_DAYS} days. Leave Mix empty to skip remixes and "
                            "edits; name one to insist on it.", "faint", wrap=True))
        self.artist.textChanged.connect(self._check); self.title.textChanged.connect(self._check); self._check()

    def _check(self):
        self.btn.setEnabled(bool(self.artist.text().strip() or self.title.text().strip()))

    def prefill(self, query: str):
        a, t, m = split_query(query)
        self.artist.setText(a); self.title.setText(t); self.mix.setText(m)
        (self.title if not t else self.artist if not a else self.mix).setFocus()

    def _go(self):
        if self.btn.isEnabled():
            self.submitted.emit(self.artist.text().strip(), self.title.text().strip(), self.mix.text().strip())

    def clear(self):
        for e in (self.artist, self.title, self.mix):
            e.clear()


class WishRow(QWidget):
    open_job = Signal(str)
    pause = Signal(str, bool)
    again = Signal(str)
    remove = Signal(str)

    def __init__(self, w: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("row"); self.setMinimumHeight(64)
        tagword, text = TAGS.get(w["status"], ("Wait", w["status"].upper()))
        lay = hbox(self, (4, 10, 8, 10), 14)
        t = label(text, "tag", tagword); t.setFixedWidth(80); t.setAlignment(Qt.AlignTop); lay.addWidget(t)
        col = vbox(spacing=3)
        col.addWidget(label(wish_label(w), "rowtitle"))
        bits = [w["note"]] if w.get("note") else []
        meta = [f"checked {_ago(w.get('last_run_at'))}"] if w["status"] in ("watching", "checking") else []
        if w.get("runs"):
            meta.append(f"{w['runs']} search{'es' if w['runs'] != 1 else ''}")
        left = Wishlist.days_left(w)
        if w["status"] in ("watching", "checking", "paused") and left is not None:
            meta.append(f"{left} day{'s' if left != 1 else ''} left")
        col.addWidget(label(" · ".join(bits + meta), "faint", wrap=True))
        lay.addLayout(col, 1)
        if w["status"] == "found" and w.get("job_id"):
            lay.addWidget(button("Open", "small", lambda: self.open_job.emit(w["job_id"])))
            lay.addWidget(button("Keep looking", "ghost", lambda: self.again.emit(w["id"])))
        elif w["status"] == "expired":
            lay.addWidget(button(f"Watch {WISH_DAYS} more days", "ghost", lambda: self.again.emit(w["id"])))
        elif w["status"] == "paused":
            lay.addWidget(button("Resume", "ghost", lambda: self.pause.emit(w["id"], False)))
        elif w["status"] in ("watching", "checking"):
            if w.get("job_id") and w["status"] == "checking":
                lay.addWidget(button("See it", "ghost", lambda: self.open_job.emit(w["job_id"])))
            lay.addWidget(button("Pause", "ghost", lambda: self.pause.emit(w["id"], True)))
        x = button("×", "x", lambda: self.remove.emit(w["id"])); x.setToolTip("Forget this wish")
        lay.addWidget(x)


class WishlistPage(QWidget):
    add = Signal(str, str, str)      # artist, title, mix
    open_job = Signal(str)
    open_batch = Signal()
    pause = Signal(str, bool)
    again = Signal(str)
    remove = Signal(str)

    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        self.setObjectName("page")
        root = vbox(self, (40, 28, 40, 28), 16)
        head = hbox(spacing=14)
        head.addWidget(label("Wishlist", "h1"), 0, Qt.AlignBottom)
        head.addStretch(1)
        self.count = label("", "faint"); head.addWidget(self.count, 0, Qt.AlignBottom)
        root.addLayout(head)
        self.form = WishForm("Watch for a track. Fill in what you know.", cancel=False)
        self.form.submitted.connect(self._add)
        root.addWidget(self.form)
        brow = hbox(spacing=10)
        brow.addWidget(label("A whole playlist?", "faint"))
        brow.addWidget(button("Use Batch", "link", self.open_batch.emit)); brow.addStretch(1)
        root.addLayout(brow)
        self.rows_host = QWidget(); self.rows_host.setObjectName("page")
        self.rows = vbox(self.rows_host, spacing=0); self.rows.addStretch(1)
        self.area = scroll(self.rows_host); root.addWidget(self.area, 1)
        self.empty = label("Nothing on the wishlist. When a search comes up empty, press “Watch this search” "
                           "and it will be asked for again every half hour.", "muted", wrap=True)
        root.addWidget(self.empty)

    def _add(self, artist: str, title: str, mix: str):
        self.add.emit(artist, title, mix); self.form.clear()

    def refresh(self):
        wishes = self.svc.wishlist.all()
        n = len(wishes); found = sum(1 for w in wishes if w["status"] == "found")
        self.count.setText((f"{n} wish{'es' if n != 1 else ''}" + (f" · {found} found" if found else "")) if n else "")
        self.empty.setVisible(not wishes)
        self.area.setVisible(bool(wishes))

        def rebuild():
            self.rows_host.setUpdatesEnabled(False)
            while self.rows.count() > 1:
                item = self.rows.takeAt(0)
                if item.widget():
                    item.widget().hide(); item.widget().deleteLater()
            order = {"found": 0, "checking": 1, "watching": 2, "paused": 3, "expired": 4}
            for w in sorted(wishes, key=lambda w: (order.get(w["status"], 9), w.get("created_at") or "")):
                r = WishRow(w, self.rows_host)
                r.open_job.connect(self.open_job); r.pause.connect(self.pause); r.again.connect(self.again)
                r.remove.connect(self.remove)
                self.rows.insertWidget(self.rows.count() - 1, r)
                self.rows.insertWidget(self.rows.count() - 1, rule())
            self.rows_host.setUpdatesEnabled(True)
        keep_scroll(self.area, rebuild)
