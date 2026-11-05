"""Main window: candidate queue on the left, search results or the review panel on the right.

Flow: search Soulseek -> pick a result -> it downloads straight into quarantine -> checked -> the user
chooses Download to Library (PASS), Download anyway (WARN) or Delete. FAIL can only be deleted.

Widgets never touch files directly; everything goes through ArchiveService. Slow work runs on worker
threads: one pool for analyses (N parallel slots from Settings, the rest wait in the queue) and one
single-threaded pool for talking to slskd and scanning folders, so a busy analysis never blocks progress
updates.
"""
from __future__ import annotations

import time
import traceback
from pathlib import Path
from urllib.parse import quote_plus

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSpinBox,
                               QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..adapters.base import Candidate, ConnectorError, SearchResult
from ..config import APP_NAME
from ..core import jobs as J
from ..core.rules import fmt_time
from ..core.safety import Rejected
from ..core.service import ActionBlocked, ArchiveService
from ..media.tools import ToolMissing, find_tool

COLORS = {"PASS": "#2e7d4f", "WARN": "#c98a12", "FAIL": "#b23b3b"}
SEARCH_WAIT_S = 20            # keep collecting Soulseek results for this long
SUPPORT_URL = "https://projectarchive.app/help/connection"      # FAQ page on the website (to be created)
FIREWALL_NOTE = ("To download from other users, Project Archive accepts incoming connections.\n\n"
                 "If Windows or macOS asks whether to allow this, choose Allow. Nothing is shared from your "
                 "computer unless you turn that on yourself in Settings.")

# Online store search. Not wired to a button right now; kept for a later "find it to buy" feature.
STORES = [
    ("Beatport", "https://www.beatport.com/search?q={}"),
    ("Bandcamp", "https://bandcamp.com/search?q={}"),
    ("Juno", "https://www.juno.co.uk/search/?q%5Ball%5D%5B%5D={}"),
    ("Traxsource", "https://www.traxsource.com/search?term={}"),
    ("Discogs", "https://www.discogs.com/search/?q={}&type=all"),
]


def open_store_search(query: str) -> None:
    """Open the query on each store's search page in the default browser."""
    for _name, url in STORES:
        QDesktopServices.openUrl(QUrl(url.format(quote_plus(query))))


STYLE = """
QMainWindow, QWidget { font-size: 13px; }
QPushButton { padding: 6px 12px; }
QPushButton#primary { background: #1f5f8b; color: white; border: none; border-radius: 4px; font-weight: 600; }
QPushButton#primary:disabled { background: #9db3c4; }
QPushButton#warn { background: #c98a12; color: white; border: none; border-radius: 4px; font-weight: 600; }
QListWidget { border: none; }
QListWidget::item { padding: 6px 4px; border-bottom: 1px solid palette(mid); }
QListWidget::item:selected { background: #1f5f8b; color: white; }
QFrame#facts { border: 1px solid palette(mid); border-radius: 4px; }
QTreeWidget { border: 1px solid palette(mid); }
"""


# --------------------------------------------------------------------------- worker plumbing
class Signals(QObject):
    progress = Signal(str, str)          # job_id, step
    done = Signal(str)                   # job_id (or "" = just refresh)
    failed = Signal(str, str)            # job_id or "", message
    results = Signal(object)             # SearchResult
    status = Signal(object)              # ConnectorStatus
    staged = Signal(str)                 # job_id that finished downloading and needs analysis


class Task(QRunnable):
    def __init__(self, fn, signals: Signals):
        super().__init__()
        self.fn, self.signals = fn, signals

    def run(self):
        try:
            self.fn()
        except (Rejected, ActionBlocked, ToolMissing, ConnectorError) as e:
            self.signals.failed.emit("", str(e))
        except Exception as e:                                      # keep the app alive, report it
            traceback.print_exc()
            self.signals.failed.emit("", f"Unexpected error: {e}")


# --------------------------------------------------------------------------- spectrogram view
class SpectrumView(QLabel):
    AXIS = 52

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(220)
        self.setAlignment(Qt.AlignCenter)
        self._pix: QPixmap | None = None
        self._nyq = 22050
        self._cutoff = None
        self.clear_view("Spectrogram appears here after the check.")

    def clear_view(self, text: str):
        self._pix = None
        self.setText(text)
        self.update()

    def show_png(self, path: str, sample_rate: int, cutoff_hz: float | None):
        pix = QPixmap(path)
        if pix.isNull():
            self.clear_view("Spectrogram unavailable.")
            return
        self._pix, self._nyq, self._cutoff = pix, (sample_rate or 44100) / 2, cutoff_hz
        self.setText("")
        self.update()

    def paintEvent(self, e):
        if self._pix is None:
            return super().paintEvent(e)
        p = QPainter(self)
        r = self.rect().adjusted(self.AXIS, 4, -4, -18)
        p.drawPixmap(r, self._pix)
        p.setPen(self.palette().text().color())
        small = QFont(self.font()); small.setPointSizeF(max(8.0, small.pointSizeF() - 2)); p.setFont(small)
        for khz in range(0, int(self._nyq / 1000) + 1, 5):
            y = r.bottom() - int(r.height() * khz * 1000 / self._nyq)
            p.drawLine(r.left() - 5, y, r.left(), y)
            p.drawText(2, y + 4, f"{khz} kHz")
        if self._cutoff:
            y = r.bottom() - int(r.height() * self._cutoff / self._nyq)
            p.setPen(QColor("#4fc3f7"))
            p.drawLine(r.left(), y, r.right(), y)
            p.drawText(r.right() - 150, y - 4, f"energy stops ~{self._cutoff / 1000:.1f} kHz")
        p.setPen(self.palette().text().color())
        p.drawText(r.left(), self.height() - 3, "time →")
        p.end()


# --------------------------------------------------------------------------- first-run setup
SHARE_TEXT = ("Share this folder with other Soulseek users. This is how the community works: people who share "
              "get served first, and accounts that share nothing wait at the back of every queue.")


class SetupDialog(QDialog):
    """Shown once on first launch (the in-app part of sign-up). Asks for the DJ library folder, which is
    both where approved downloads go and what is shared back to Soulseek."""

    def __init__(self, svc: ArchiveService, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setModal(True)
        self.svc = svc
        s = svc.settings
        default = s.library_dir if s.setup_done else str(Path.home() / "Music")
        lay = QVBoxLayout(self)
        title = QLabel(f"<b style='font-size:18px'>Welcome to {APP_NAME}</b>"); lay.addWidget(title)
        intro = QLabel("Two quick things and you're set."); intro.setStyleSheet("color: gray;"); lay.addWidget(intro)

        lay.addWidget(QLabel("<b>1. Where is your DJ music library?</b>"))
        hint = QLabel("Approved downloads go here. Pick the folder your DJ software already uses."); hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;"); lay.addWidget(hint)
        self.library = QLineEdit(default)
        btn = QPushButton("Choose…")
        btn.clicked.connect(lambda: (d := QFileDialog.getExistingDirectory(self, "DJ music library", self.library.text())) and self.library.setText(d))
        row = QHBoxLayout(); row.addWidget(self.library); row.addWidget(btn); lay.addLayout(row)

        lay.addWidget(QLabel("<b>2. Share it back</b>"))
        self.share = QCheckBox(SHARE_TEXT); self.share.setChecked(True if not s.setup_done else bool(s.share_folder))
        lay.addWidget(self.share)

        bb = QDialogButtonBox(QDialogButtonBox.Ok); bb.button(QDialogButtonBox.Ok).setText("Let's go")
        bb.accepted.connect(self._save); lay.addWidget(bb)
        self.resize(560, 300)

    def _save(self):
        folder = self.library.text().strip()
        if not folder:
            QMessageBox.warning(self, APP_NAME, "Please choose a folder.")
            return
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Can't use that folder: {e}")
            return
        s = self.svc.settings
        s.library_dir = folder
        s.share_folder = folder if self.share.isChecked() else ""
        s.setup_done = True
        self.svc.save_settings(s)
        self.accept()


# --------------------------------------------------------------------------- settings dialog
class SettingsDialog(QDialog):
    def __init__(self, svc: ArchiveService, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.svc = svc
        s = svc.settings
        outer = QVBoxLayout(self)
        form = QFormLayout(); outer.addLayout(form)
        form.addRow(QLabel("<b>Folders</b>"))
        self.library = self._folder_row(form, "Download to (your library folder)", s.library_dir)
        self.incoming = self._folder_row(form, "Watched Incoming folder", s.incoming_dir, "Off (leave empty)")
        self.share_lib = QCheckBox("Share my library folder with other Soulseek users (recommended: you get served first)")
        self.share_lib.setChecked(bool(s.share_folder)); form.addRow(self.share_lib)
        form.addRow(QLabel("<b>Checks</b>"))
        self.mp3 = self._spin(form, "Warn if MP3 below (kbps)", s.mp3_min_kbps, 64, 320)
        self.vbr = self._spin(form, "Warn if VBR average below (kbps)", s.vbr_min_avg_kbps, 64, 320)
        self.slots = self._spin(form, "Check this many tracks at once", s.max_concurrent_analyses, 1, 16)
        self.hours = self._spin(form, "Delete undecided files after (hours)", s.retention_hours, 1, 24 * 30)
        self.maxmb = self._spin(form, "Max file size (MB)", s.max_file_mb, 10, 8192)
        self.exts = QLineEdit(", ".join(s.extensions)); form.addRow("Accepted formats", self.exts)

        # Advanced: hidden until opened. Everything in here is for people who know what slskd is.
        self.adv = QGroupBox("Advanced"); self.adv.setCheckable(True); self.adv.setChecked(False)
        adv = QFormLayout(); self.adv_body = QWidget(); self.adv_body.setLayout(adv)
        self.own_user = QLineEdit(s.soulseek_own_username); self.own_user.setPlaceholderText("Leave empty to use the built-in account")
        adv.addRow("Use my own Soulseek username", self.own_user)
        self.own_pass = QLineEdit(); self.own_pass.setEchoMode(QLineEdit.Password)
        self.own_pass.setPlaceholderText("(unchanged)" if svc.manager.creds.get("soulseek_own_password") else "")
        adv.addRow("Soulseek password", self.own_pass)
        self.use_own = QCheckBox("Use an slskd I already run instead of the built-in engine"); self.use_own.setChecked(s.use_own_slskd)
        adv.addRow(self.use_own)
        self.slskd_url = QLineEdit(s.slskd_url); adv.addRow("slskd URL", self.slskd_url)
        self.slskd_key = QLineEdit(s.slskd_api_key); self.slskd_key.setEchoMode(QLineEdit.Password)
        adv.addRow("slskd API key", self.slskd_key)
        self.slskd_dl = self._folder_row(adv, "slskd downloads folder", s.slskd_downloads_dir)
        self.ffmpeg = self._folder_row(adv, "FFmpeg folder (optional)", s.ffmpeg_path, "Bundled / system")
        box = QVBoxLayout(self.adv); box.addWidget(self.adv_body)
        self.adv_body.setVisible(False); self.adv.toggled.connect(self.adv_body.setVisible)
        outer.addWidget(self.adv)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save); bb.rejected.connect(self.reject)
        outer.addWidget(bb)

    def _folder_row(self, form, label, value, placeholder=""):
        edit = QLineEdit(value); edit.setPlaceholderText(placeholder)
        btn = QPushButton("Choose…")
        btn.clicked.connect(lambda: (d := QFileDialog.getExistingDirectory(self, label, edit.text())) and edit.setText(d))
        row = QHBoxLayout(); row.addWidget(edit); row.addWidget(btn)
        w = QWidget(); w.setLayout(row); row.setContentsMargins(0, 0, 0, 0)
        form.addRow(label, w)
        return edit

    def _spin(self, form, label, value, lo, hi):
        sp = QSpinBox(); sp.setRange(lo, hi); sp.setValue(value); form.addRow(label, sp)
        return sp

    def _save(self):
        s = self.svc.settings
        s.library_dir = self.library.text().strip() or s.library_dir
        s.incoming_dir = self.incoming.text().strip()
        s.share_folder = s.library_dir if self.share_lib.isChecked() else ""
        s.soulseek_own_username = self.own_user.text().strip()
        if self.own_pass.text():
            self.svc.manager.creds.set("soulseek_own_password", self.own_pass.text())
        elif not s.soulseek_own_username:
            self.svc.manager.creds.delete("soulseek_own_password")
        s.use_own_slskd = self.use_own.isChecked()
        s.slskd_url = self.slskd_url.text().strip() or "http://127.0.0.1:5030"
        s.slskd_api_key = self.slskd_key.text().strip()
        s.slskd_downloads_dir = self.slskd_dl.text().strip()
        s.mp3_min_kbps, s.vbr_min_avg_kbps = self.mp3.value(), self.vbr.value()
        s.max_concurrent_analyses = self.slots.value()
        s.retention_hours, s.max_file_mb = self.hours.value(), self.maxmb.value()
        s.extensions = [e.strip().lower().lstrip(".") for e in self.exts.text().split(",") if e.strip()]
        s.ffmpeg_path = self.ffmpeg.text().strip()
        self.svc.save_settings(s)
        self.accept()


# --------------------------------------------------------------------------- search results page
class ResultsPage(QWidget):
    COLS = ["File", "Folder", "User", "Size", "Bitrate", "Length", "Queue", "Speed"]

    def __init__(self, on_pick, on_back):
        super().__init__()
        self.on_pick = on_pick
        self.title = QLabel("Search Soulseek for a track"); self.title.setStyleSheet("font-size:16px; font-weight:600;")
        self.hint = QLabel("Results are what other users' clients report. Pick one and it is checked before anything "
                           "reaches your library."); self.hint.setStyleSheet("color: gray;"); self.hint.setWordWrap(True)
        self.tree = QTreeWidget(); self.tree.setColumnCount(len(self.COLS)); self.tree.setHeaderLabels(self.COLS)
        self.tree.setRootIsDecorated(False); self.tree.setAlternatingRowColors(True); self.tree.setSortingEnabled(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.itemDoubleClicked.connect(lambda *_: self._pick())
        self.tree.itemSelectionChanged.connect(lambda: self.btn_pick.setEnabled(bool(self.tree.selectedItems())))
        self.btn_pick = QPushButton("Check this file", objectName="primary"); self.btn_pick.setEnabled(False)
        self.btn_pick.clicked.connect(self._pick)
        self.btn_back = QPushButton("Back to review"); self.btn_back.clicked.connect(on_back)
        row = QHBoxLayout(); row.addWidget(self.btn_pick); row.addStretch(); row.addWidget(self.btn_back)
        lay = QVBoxLayout(self); lay.addWidget(self.title); lay.addWidget(self.hint); lay.addWidget(self.tree, 1); lay.addLayout(row)

    def show_results(self, res: SearchResult, searching: bool):
        n = len(res.candidates)
        state = "searching…" if searching else "done"
        self.title.setText(f"“{res.query}” · {n} file{'s' if n != 1 else ''} · {state}")
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for c in sorted(res.candidates, key=_rank):
            it = QTreeWidgetItem([
                c.display_name, c.folder, c.user, f"{c.size / 1e6:.1f} MB",
                (f"{c.bitrate_kbps} kbps" + (" VBR" if c.vbr else "")) if c.bitrate_kbps else "?",
                fmt_time(c.length_s) if c.length_s else "?",
                "free slot" if c.free_slot else (str(c.queue_length) if c.queue_length is not None else "?"),
                f"{c.upload_speed / 1e3:.0f} kB/s" if c.upload_speed else "?",
            ])
            it.setData(0, Qt.UserRole, c)
            if c.locked:
                it.setForeground(0, QColor("gray")); it.setText(0, c.display_name + "  (locked)")
            self.tree.addTopLevelItem(it)
        self.tree.setSortingEnabled(True)
        for i in range(1, len(self.COLS)):
            self.tree.resizeColumnToContents(i)

    def _pick(self):
        items = self.tree.selectedItems()
        if items:
            self.on_pick(items[0].data(0, Qt.UserRole))


def _rank(c: Candidate):
    """Likely-fastest first: free slots, short queues, then the bitrate the peer claims."""
    return (0 if c.free_slot else 1, c.queue_length if c.queue_length is not None else 1_000_000,
            -(c.bitrate_kbps or 0), -(c.upload_speed or 0))


# --------------------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        self.pool = QThreadPool(); self.pool.setMaxThreadCount(max(1, svc.settings.max_concurrent_analyses))
        self.io = QThreadPool(); self.io.setMaxThreadCount(3)                # slskd calls + folder scans
        self._polling = False
        self._scanning = False
        self.signals = Signals()
        self.signals.progress.connect(self._on_progress)
        self.signals.done.connect(lambda _id: self.refresh())
        self.signals.failed.connect(self._on_failed)
        self.signals.results.connect(self._on_results)
        self.signals.status.connect(self._on_status)
        self.signals.staged.connect(self._start_analysis)
        self.steps: dict[str, str] = {}
        self.selected: str | None = None
        self.search_id: str | None = None
        self.search_running = False

        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE)
        self._build()

        svc.reconcile()
        svc.cleanup_expired()
        self.refresh()
        self._check_ffmpeg()
        self.scan_timer = QTimer(self, interval=3000, timeout=self._scan_incoming); self.scan_timer.start()
        self.poll_timer = QTimer(self, interval=2000, timeout=self._poll_downloads); self.poll_timer.start()
        self.status_timer = QTimer(self, interval=15000, timeout=self._poll_status); self.status_timer.start()
        self.clean_timer = QTimer(self, interval=3600 * 1000, timeout=lambda: (svc.cleanup_expired(), self.refresh()))
        self.clean_timer.start()
        self._trouble_shown = False
        QTimer.singleShot(0, self._start_backend)

    # bundled engine ----------------------------------------------------------------------
    def _start_backend(self):
        if not self.svc.settings.setup_done:
            SetupDialog(self.svc, self).exec()
            self.refresh()
        if not self.svc.managed_mode:
            self._poll_status()
            return
        if not self.svc.settings.firewall_notice_shown:
            QMessageBox.information(self, APP_NAME, FIREWALL_NOTE)
            s = self.svc.settings; s.firewall_notice_shown = True; self.svc.save_settings(s)
        self._trouble_shown = False
        self.svc.backend_state = "starting"
        self._poll_status()

        def work():
            self.svc.start_backend()
            self.signals.status.emit(self.svc.connector_status())
        self.io.start(Task(work, self.signals))

    def _connection_trouble(self):
        """One small dialog, once per failure: try again, or open the help page on the website."""
        if self._trouble_shown:
            return
        self._trouble_shown = True
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Warning)
        box.setText("Having trouble connecting to the server.")
        box.setInformativeText("Please try again. If it keeps happening, the help page explains what to check.")
        retry = box.addButton("Try again", QMessageBox.AcceptRole)
        help_ = box.addButton("Help", QMessageBox.HelpRole)
        box.addButton("Not now", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is retry:
            self._start_backend()
        elif box.clickedButton() is help_:
            QDesktopServices.openUrl(QUrl(SUPPORT_URL))

    def closeEvent(self, e):
        self.svc.stop_backend()
        super().closeEvent(e)

    # layout -----------------------------------------------------------------------
    def _build(self):
        top = QHBoxLayout()
        title = QLabel(f"<b style='font-size:16px'>{APP_NAME}</b>")
        self.status = QLabel()
        self.btn_retry = QPushButton("Try again"); self.btn_retry.setVisible(False); self.btn_retry.clicked.connect(self._start_backend)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search Soulseek: artist, track, label…")
        self.search.setMinimumWidth(320); self.search.returnPressed.connect(self._search)
        find = QPushButton("Search Soulseek", objectName="primary"); find.clicked.connect(self._search)
        add = QPushButton("Add local files…"); add.clicked.connect(self._pick_files)
        settings = QPushButton("Settings"); settings.clicked.connect(self._settings)
        for w in (title, self.status, self.btn_retry): top.addWidget(w)
        top.addStretch()
        for w in (self.search, find, add, settings): top.addWidget(w)

        self.queue = QListWidget(); self.queue.currentItemChanged.connect(self._select)
        drop_hint = QLabel("Search above, or drag local tracks anywhere onto this window"); drop_hint.setAlignment(Qt.AlignCenter)
        drop_hint.setStyleSheet("color: gray; padding: 8px;"); drop_hint.setWordWrap(True)
        left = QVBoxLayout(); left.addWidget(self.queue); left.addWidget(drop_hint)
        lw = QWidget(); lw.setLayout(left); lw.setMinimumWidth(300)

        # review page
        self.name = QLabel("Select a track"); self.name.setStyleSheet("font-size:16px; font-weight:600;")
        self.grade = QLabel()
        head = QHBoxLayout(); head.addWidget(self.name, 1); head.addWidget(self.grade)

        self.facts = QFrame(objectName="facts"); self.fact_labels = {}
        grid = QGridLayout(self.facts)
        for i, key in enumerate(["Format", "Bitrate", "Sample rate", "Bit depth", "Length", "Channels", "Plays through"]):
            k = QLabel(key); k.setStyleSheet("color: gray; font-size: 11px;")
            v = QLabel("–"); v.setStyleSheet("font-weight: 600;")
            grid.addWidget(k, 0, i); grid.addWidget(v, 1, i)
            self.fact_labels[key] = v

        self.spectrum = SpectrumView()
        self.checks = QLabel(); self.checks.setWordWrap(True); self.checks.setTextFormat(Qt.RichText)
        self.checks.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        cs = QScrollArea(); cs.setWidget(self.checks); cs.setWidgetResizable(True); cs.setMinimumHeight(150)

        self.btn_save = QPushButton("Download to Library", objectName="primary"); self.btn_save.clicked.connect(lambda: self._promote(False))
        self.btn_anyway = QPushButton("Download anyway", objectName="warn"); self.btn_anyway.clicked.connect(lambda: self._promote(True))
        self.btn_reject = QPushButton("Delete"); self.btn_reject.clicked.connect(self._reject)
        self.btn_cancel = QPushButton("Cancel download"); self.btn_cancel.clicked.connect(self._cancel)
        self.btn_rerun = QPushButton("Re-check"); self.btn_rerun.clicked.connect(self._rerun)
        self.btn_open = QPushButton("Open staging folder"); self.btn_open.clicked.connect(self._open_folder)
        self.btn_results = QPushButton("Search results"); self.btn_results.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        actions = QHBoxLayout()
        for b in (self.btn_save, self.btn_anyway, self.btn_reject, self.btn_cancel): actions.addWidget(b)
        actions.addStretch()
        for b in (self.btn_rerun, self.btn_open, self.btn_results): actions.addWidget(b)

        review = QVBoxLayout()
        review.addLayout(head); review.addWidget(self.facts); review.addWidget(self.spectrum, 3)
        review.addWidget(QLabel("<b>Checks</b>")); review.addWidget(cs, 2); review.addLayout(actions)
        self.review_page = QWidget(); self.review_page.setLayout(review)

        self.results_page = ResultsPage(self._pick_candidate, lambda: self.pages.setCurrentIndex(1))
        self.pages = QStackedWidget(); self.pages.addWidget(self.results_page); self.pages.addWidget(self.review_page)
        self.pages.setCurrentIndex(1)

        split = QSplitter(); split.addWidget(lw); split.addWidget(self.pages); split.setStretchFactor(1, 1)
        root = QVBoxLayout(); root.addLayout(top); root.addWidget(split, 1)
        cw = QWidget(); cw.setLayout(root); self.setCentralWidget(cw)
        self._show_job(None)

    # data -> view -----------------------------------------------------------------
    def refresh(self):
        keep = self.selected
        self.queue.blockSignals(True)
        self.queue.clear()
        for job in self.svc.jobs():
            a = self.svc.db.analysis(job["id"]) if job["state"] not in (J.STAGING, J.ANALYZING, J.QUEUED) else None
            badge = self._badge(job, a)
            item = QListWidgetItem(f"{job['original_name']}\n{badge}")
            item.setData(Qt.UserRole, job["id"])
            if a and job["state"] == J.READY:
                item.setForeground(QColor(COLORS[a["overall_status"]]))
            elif job["state"] in J.FINAL:
                item.setForeground(QColor("gray"))
            self.queue.addItem(item)
            if job["id"] == keep:
                self.queue.setCurrentItem(item)
        self.queue.blockSignals(False)
        self._show_job(keep)

    def _badge(self, job, a) -> str:
        st = job["state"]
        if st == J.QUEUED:
            pct = job.get("progress") or 0
            return f"Downloading {pct:.0f}% · {job.get('message') or ''}".rstrip(" ·")
        if st in (J.STAGING, J.ANALYZING):
            return self.steps.get(job["id"], "Copying…" if st == J.STAGING else "Waiting for a free slot…")
        if st == J.READY and a:
            return f"{a['overall_status']} · ready for review"
        return {J.PROMOTED: "Downloaded to library", J.REJECTED: "Deleted", J.EXPIRED: "Expired (cleaned up)",
                J.CANCELLED: "Cancelled", J.ERROR: "Error: " + (job.get("message") or "")}.get(st, st)

    def _select(self, cur, _prev):
        self.selected = cur.data(Qt.UserRole) if cur else None
        if self.selected:
            self.pages.setCurrentIndex(1)
        self._show_job(self.selected)

    def _show_job(self, job_id):
        job = self.svc.db.job(job_id) if job_id else None
        a = self.svc.db.analysis(job_id) if job else None
        for b in (self.btn_save, self.btn_anyway, self.btn_reject, self.btn_cancel, self.btn_rerun, self.btn_open):
            b.setVisible(bool(job)); b.setEnabled(False)
        self.btn_results.setVisible(self.search_id is not None)
        if not job:
            self.name.setText("Search Soulseek above, or drop a track in to check it"); self.grade.setText("")
            for v in self.fact_labels.values(): v.setText("–")
            self.checks.setText(""); self.spectrum.clear_view("Spectrogram appears here after the check.")
            return
        self.name.setText(job["original_name"])
        busy = job["state"] in (J.STAGING, J.ANALYZING, J.QUEUED)
        ready = job["state"] == J.READY and a
        status = a["overall_status"] if a else None
        self.grade.setText(f"<b style='color:{COLORS[status]}; font-size:18px'>{status}</b>" if a and not busy else "")
        if a and not busy:
            f, d = a["facts"], a.get("decode") or {}
            kbps = f"{round(f['bitrate_bps'] / 1000)} kbps" if f.get("bitrate_bps") else "unknown"
            mode = f.get("bitrate_mode")
            self.fact_labels["Format"].setText(f"{(f.get('container') or '?').upper()} / {f.get('codec') or '?'}")
            self.fact_labels["Bitrate"].setText(f"{kbps} {mode if mode not in ('unknown', None) else ''}".strip())
            self.fact_labels["Sample rate"].setText(f"{f['sample_rate_hz'] / 1000:g} kHz" if f.get("sample_rate_hz") else "unknown")
            self.fact_labels["Bit depth"].setText(f"{f['bit_depth']}-bit" if f.get("bit_depth") else "n/a")
            self.fact_labels["Length"].setText(fmt_time(f["duration_s"]) if f.get("duration_s") else "unknown")
            self.fact_labels["Channels"].setText({1: "Mono", 2: "Stereo"}.get(f.get("channels"), str(f.get("channels") or "?")))
            played = d.get("decoded_s")
            self.fact_labels["Plays through"].setText("–" if played is None else
                                                     ("Yes" if a.get("decode_ok") and next((c for c in a["checks"] if c["id"] == "decode"), {}).get("status") != "FAIL"
                                                      else f"No ({fmt_time(played)})"))
            self.checks.setText("".join(
                f"<p><b style='color:{COLORS[c['status']]}'>{c['status']}</b> &nbsp;<b>{c['title']}</b><br>{c['message']}</p>"
                for c in sorted(a["checks"], key=lambda c: {"FAIL": 0, "WARN": 1, "PASS": 2}[c["status"]])))
            if a.get("spectrogram_path") and Path(a["spectrogram_path"]).exists():
                self.spectrum.show_png(a["spectrogram_path"], f.get("sample_rate_hz"), a.get("cutoff_hz"))
            else:
                self.spectrum.clear_view("Spectrogram unavailable." if job["state"] not in J.FINAL else
                                         "Staged copy removed; spectrogram no longer stored.")
        else:
            for v in self.fact_labels.values(): v.setText("–")
            if job["state"] == J.QUEUED:
                src = f"from {job['remote_user']}" if job.get("remote_user") else ""
                self.checks.setText(f"<p>Downloading {src} into quarantine… {job.get('progress') or 0:.0f}%<br>"
                                    f"{job.get('message') or ''}</p><p style='color:gray'>It is checked as soon as it "
                                    f"arrives. Nothing reaches your library until you decide.</p>")
            else:
                self.checks.setText(f"<p>{self.steps.get(job_id, 'Working…') if busy else (job.get('message') or '')}</p>")
            self.spectrum.clear_view("Checking…" if busy else "No spectrogram.")

        self.btn_save.setVisible(bool(ready) and status == "PASS"); self.btn_save.setEnabled(bool(ready))
        self.btn_anyway.setVisible(bool(ready) and status == "WARN"); self.btn_anyway.setEnabled(bool(ready))
        self.btn_cancel.setVisible(job["state"] == J.QUEUED); self.btn_cancel.setEnabled(job["state"] == J.QUEUED)
        self.btn_reject.setVisible(job["state"] != J.QUEUED); self.btn_reject.setEnabled(job["state"] in (J.READY, J.ERROR))
        self.btn_rerun.setEnabled(job["state"] in (J.READY, J.ERROR) and bool(job["staged_path"]))
        self.btn_open.setEnabled(bool(job["staged_path"]) and Path(job["staged_path"]).parent.exists())
        if job["state"] == J.PROMOTED and job.get("final_path"):
            self.btn_open.setText("Show in library"); self.btn_open.setEnabled(Path(job["final_path"]).exists())
        else:
            self.btn_open.setText("Open staging folder")

    # Soulseek search ------------------------------------------------------------------
    def _search(self):
        q = self.search.text().strip()
        if not q:
            self.search.setFocus()
            return
        self.pages.setCurrentIndex(0)
        self.results_page.show_results(SearchResult(query=q, search_id="", finished=False), searching=True)
        self.search_running = True

        def work():
            res = self.svc.search(q)
            self.search_id = res.search_id
            started = time.monotonic()
            while True:
                time.sleep(1.0)
                if self.search_id != res.search_id:               # a newer search replaced this one
                    return
                latest = self.svc.search_results(res.search_id)
                latest.query = q
                self.signals.results.emit(latest)
                if latest.finished or time.monotonic() - started > SEARCH_WAIT_S:
                    self.search_running = False
                    self.signals.results.emit(latest)
                    return
        self.io.start(Task(work, self.signals))

    def _on_results(self, res: SearchResult):
        if res.search_id == self.search_id:
            self.results_page.show_results(res, searching=self.search_running)
            self.btn_results.setVisible(True)

    def _pick_candidate(self, cand: Candidate):
        def work():
            job = self.svc.request_download(cand)
            self.signals.done.emit(job["id"])
        self.io.start(Task(work, self.signals))
        self.statusBar().showMessage(f"Requested “{cand.display_name}” from {cand.user}. It goes to quarantine first.", 6000)

    def _poll_downloads(self):
        if self.svc.adapter is None or self._polling:
            return
        self._polling = True

        def work():
            try:
                jobs = self.svc.poll_downloads()
            finally:
                self._polling = False
            self.signals.done.emit("")
            for job in jobs:
                self.signals.staged.emit(job["id"])
        self.io.start(Task(work, self.signals))

    def _poll_status(self):
        self.io.start(Task(lambda: self.signals.status.emit(self.svc.connector_status()), self.signals))

    def _on_status(self, st):
        colour = "#2e7d4f" if st.logged_in else ("#c98a12" if st.available else "gray")
        self.status.setText(f"   <span style='color:{colour}'>●</span> {st.message}")
        self.status.setToolTip(st.message)
        failed = self.svc.managed_mode and self.svc.backend_state == "failed"
        self.btn_retry.setVisible(failed)
        if failed:
            self._connection_trouble()

    # actions ---------------------------------------------------------------------
    def _enqueue_paths(self, paths: list[Path]):
        for p in paths:
            self.pool.start(Task(lambda p=p: self._stage_and_analyze(p), self.signals))

    def _stage_and_analyze(self, path: Path, source_kind="manual"):
        try:
            job = self.svc.stage(path, source_kind)
        except Rejected as e:
            raise Rejected(f"{path.name}: {e}")
        self.signals.done.emit(job["id"])
        self._analyze(job["id"])

    def _start_analysis(self, job_id: str):
        self.pool.start(Task(lambda: self._analyze(job_id), self.signals))

    def _analyze(self, job_id: str):
        try:
            self.svc.analyze(job_id, lambda step: self.signals.progress.emit(job_id, step))
        finally:
            self.steps.pop(job_id, None)
            self.signals.done.emit(job_id)

    def _scan_incoming(self):
        if not self.svc.settings.incoming_dir or self._scanning:
            return
        self._scanning = True

        def work():
            try:
                jobs = self.svc.scan_incoming()
            finally:
                self._scanning = False
            for job in jobs:
                self.signals.done.emit(job["id"])
                self.signals.staged.emit(job["id"])
        self.io.start(Task(work, self.signals))

    def _on_progress(self, job_id, step):
        self.steps[job_id] = step + "…"
        self.refresh()

    def _on_failed(self, _job_id, message):
        self.refresh()
        QMessageBox.warning(self, APP_NAME, message)

    def _pick_files(self):
        exts = " ".join(f"*.{e}" for e in self.svc.settings.extensions)
        files, _ = QFileDialog.getOpenFileNames(self, "Add tracks", "", f"Audio ({exts})")
        self._enqueue_paths([Path(f) for f in files])

    def _promote(self, override: bool):
        if not self.selected:
            return
        try:
            target = self.svc.promote(self.selected, override_warning=override)
            self.statusBar().showMessage(f"Downloaded to {target}", 8000)
        except ActionBlocked as e:
            QMessageBox.warning(self, APP_NAME, str(e))
        self.refresh()

    def _reject(self):
        if not self.selected:
            return
        try:
            self.svc.reject(self.selected)
            self.statusBar().showMessage("Deleted from quarantine. Nothing was saved to your computer.", 8000)
        except ActionBlocked as e:
            QMessageBox.warning(self, APP_NAME, str(e))
        self.refresh()

    def _cancel(self):
        if not self.selected:
            return
        jid = self.selected

        def work():
            self.svc.cancel(jid)
            self.signals.done.emit(jid)
        self.io.start(Task(work, self.signals))

    def _rerun(self):
        if self.selected:
            self._start_analysis(self.selected)

    def _open_folder(self):
        job = self.svc.db.job(self.selected) if self.selected else None
        if not job:
            return
        path = Path(job["final_path"]).parent if job["state"] == J.PROMOTED and job.get("final_path") \
            else Path(job["staged_path"]).parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _settings(self):
        s = self.svc.settings
        before = (s.share_folder, s.soulseek_own_username, s.use_own_slskd)
        if SettingsDialog(self.svc, self).exec():
            s = self.svc.settings
            self.pool.setMaxThreadCount(max(1, s.max_concurrent_analyses))
            self.refresh()
            self._check_ffmpeg()
            if (s.share_folder, s.soulseek_own_username, s.use_own_slskd) != before:
                self.svc.stop_backend()                    # engine config changed: restart it quietly
                self._start_backend()
            else:
                self._poll_status()

    def _check_ffmpeg(self):
        try:
            find_tool("ffmpeg", self.svc.settings.ffmpeg_path); find_tool("ffprobe", self.svc.settings.ffmpeg_path)
        except ToolMissing as e:
            QMessageBox.critical(self, APP_NAME, f"{e}\n\nChecks are disabled until FFmpeg is available.")

    # drag & drop ------------------------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self._enqueue_paths([Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()])
