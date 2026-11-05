"""Main window: candidate queue on the left, review panel on the right.

Widgets never touch files directly; everything goes through ArchiveService, and slow work runs on a
worker thread so the window stays responsive.
"""
from __future__ import annotations

import traceback
from pathlib import Path
from urllib.parse import quote_plus

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QPushButton, QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget)

from ..config import APP_NAME
from ..core import jobs as J
from ..core.rules import fmt_time
from ..core.safety import Rejected
from ..core.service import ActionBlocked, ArchiveService
from ..media.tools import ToolMissing, find_tool

COLORS = {"PASS": "#2e7d4f", "WARN": "#c98a12", "FAIL": "#b23b3b"}
STORES = [
    ("Beatport", "https://www.beatport.com/search?q={}"),
    ("Bandcamp", "https://bandcamp.com/search?q={}"),
    ("Juno", "https://www.juno.co.uk/search/?q%5Ball%5D%5B%5D={}"),
    ("Traxsource", "https://www.traxsource.com/search?term={}"),
    ("Discogs", "https://www.discogs.com/search/?q={}&type=all"),
]
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
"""


# --------------------------------------------------------------------------- worker plumbing
class Signals(QObject):
    progress = Signal(str, str)          # job_id, step
    done = Signal(str)                   # job_id
    failed = Signal(str, str)            # job_id or "", message


class Task(QRunnable):
    def __init__(self, fn, signals: Signals):
        super().__init__()
        self.fn, self.signals = fn, signals

    def run(self):
        try:
            self.fn()
        except (Rejected, ActionBlocked, ToolMissing) as e:
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


# --------------------------------------------------------------------------- settings dialog
class SettingsDialog(QDialog):
    def __init__(self, svc: ArchiveService, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.svc = svc
        s = svc.settings
        form = QFormLayout(self)
        self.library = self._folder_row(form, "Library folder", s.library_dir)
        self.incoming = self._folder_row(form, "Watched Incoming folder", s.incoming_dir, "Off (leave empty)")
        self.mp3 = self._spin(form, "Warn if MP3 below (kbps)", s.mp3_min_kbps, 64, 320)
        self.vbr = self._spin(form, "Warn if VBR average below (kbps)", s.vbr_min_avg_kbps, 64, 320)
        self.hours = self._spin(form, "Delete undecided files after (hours)", s.retention_hours, 1, 24 * 30)
        self.maxmb = self._spin(form, "Max file size (MB)", s.max_file_mb, 10, 8192)
        self.exts = QLineEdit(", ".join(s.extensions)); form.addRow("Accepted formats", self.exts)
        self.ffmpeg = self._folder_row(form, "FFmpeg folder (optional)", s.ffmpeg_path, "Bundled / system")
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save); bb.rejected.connect(self.reject)
        form.addRow(bb)

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
        s.mp3_min_kbps, s.vbr_min_avg_kbps = self.mp3.value(), self.vbr.value()
        s.retention_hours, s.max_file_mb = self.hours.value(), self.maxmb.value()
        s.extensions = [e.strip().lower().lstrip(".") for e in self.exts.text().split(",") if e.strip()]
        s.ffmpeg_path = self.ffmpeg.text().strip()
        self.svc.save_settings(s)
        self.accept()


# --------------------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        self.pool = QThreadPool(); self.pool.setMaxThreadCount(1)        # one analysis at a time
        self.signals = Signals()
        self.signals.progress.connect(self._on_progress)
        self.signals.done.connect(lambda _id: self.refresh())
        self.signals.failed.connect(self._on_failed)
        self.steps: dict[str, str] = {}
        self.selected: str | None = None

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
        self.clean_timer = QTimer(self, interval=3600 * 1000, timeout=lambda: (svc.cleanup_expired(), self.refresh()))
        self.clean_timer.start()

    # layout -----------------------------------------------------------------------
    def _build(self):
        top = QHBoxLayout()
        title = QLabel(f"<b style='font-size:16px'>{APP_NAME}</b>")
        self.status = QLabel()
        add = QPushButton("Add files…"); add.clicked.connect(self._pick_files)
        self.search = QLineEdit(); self.search.setPlaceholderText("Artist - track"); self.search.setMaximumWidth(260)
        self.search.returnPressed.connect(self._find)
        find = QPushButton("Find in stores"); find.clicked.connect(self._find)
        settings = QPushButton("Settings"); settings.clicked.connect(self._settings)
        for w in (title, self.status): top.addWidget(w)
        top.addStretch()
        for w in (self.search, find, add, settings): top.addWidget(w)

        self.queue = QListWidget(); self.queue.currentItemChanged.connect(self._select)
        drop_hint = QLabel("Drag tracks anywhere onto this window"); drop_hint.setAlignment(Qt.AlignCenter)
        drop_hint.setStyleSheet("color: gray; padding: 8px;")
        left = QVBoxLayout(); left.addWidget(self.queue); left.addWidget(drop_hint)
        lw = QWidget(); lw.setLayout(left); lw.setMinimumWidth(300)

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

        self.btn_save = QPushButton("Save to Library", objectName="primary"); self.btn_save.clicked.connect(lambda: self._promote(False))
        self.btn_anyway = QPushButton("Save to Library anyway", objectName="warn"); self.btn_anyway.clicked.connect(lambda: self._promote(True))
        self.btn_reject = QPushButton("Reject"); self.btn_reject.clicked.connect(self._reject)
        self.btn_rerun = QPushButton("Re-check"); self.btn_rerun.clicked.connect(self._rerun)
        self.btn_open = QPushButton("Open staging folder"); self.btn_open.clicked.connect(self._open_folder)
        actions = QHBoxLayout()
        for b in (self.btn_save, self.btn_anyway, self.btn_reject): actions.addWidget(b)
        actions.addStretch()
        for b in (self.btn_rerun, self.btn_open): actions.addWidget(b)

        right = QVBoxLayout()
        right.addLayout(head); right.addWidget(self.facts); right.addWidget(self.spectrum, 3)
        right.addWidget(QLabel("<b>Checks</b>")); right.addWidget(cs, 2); right.addLayout(actions)
        rw = QWidget(); rw.setLayout(right)

        split = QSplitter(); split.addWidget(lw); split.addWidget(rw); split.setStretchFactor(1, 1)
        root = QVBoxLayout(); root.addLayout(top); root.addWidget(split, 1)
        cw = QWidget(); cw.setLayout(root); self.setCentralWidget(cw)
        self._show_job(None)

    # data -> view -----------------------------------------------------------------
    def refresh(self):
        keep = self.selected
        self.queue.blockSignals(True)
        self.queue.clear()
        for job in self.svc.jobs():
            a = self.svc.db.analysis(job["id"]) if job["state"] not in (J.STAGING, J.ANALYZING) else None
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
        watching = self.svc.settings.incoming_dir
        self.status.setText(f"   Local mode · {'watching ' + Path(watching).name if watching else 'folder watching off'}"
                            f" · library: {Path(self.svc.settings.library_dir).name}")

    def _badge(self, job, a) -> str:
        st = job["state"]
        if st in (J.STAGING, J.ANALYZING):
            return self.steps.get(job["id"], "Copying…" if st == J.STAGING else "Checking…")
        if st == J.READY and a:
            return f"{a['overall_status']} · ready for review"
        return {J.PROMOTED: "Saved to library", J.REJECTED: "Rejected", J.EXPIRED: "Expired (cleaned up)",
                J.ERROR: "Error: " + (job.get("message") or "")}.get(st, st)

    def _select(self, cur, _prev):
        self.selected = cur.data(Qt.UserRole) if cur else None
        self._show_job(self.selected)

    def _show_job(self, job_id):
        job = self.svc.db.job(job_id) if job_id else None
        a = self.svc.db.analysis(job_id) if job else None
        for b in (self.btn_save, self.btn_anyway, self.btn_reject, self.btn_rerun, self.btn_open):
            b.setVisible(bool(job)); b.setEnabled(False)
        if not job:
            self.name.setText("Drop a track in to check it"); self.grade.setText("")
            for v in self.fact_labels.values(): v.setText("–")
            self.checks.setText(""); self.spectrum.clear_view("Spectrogram appears here after the check.")
            return
        self.name.setText(job["original_name"])
        busy = job["state"] in (J.STAGING, J.ANALYZING)
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
            self.checks.setText(f"<p>{self.steps.get(job_id, 'Working…') if busy else (job.get('message') or '')}</p>")
            self.spectrum.clear_view("Checking…" if busy else "No spectrogram.")

        self.btn_save.setVisible(bool(ready) and status == "PASS"); self.btn_save.setEnabled(bool(ready))
        self.btn_anyway.setVisible(bool(ready) and status == "WARN"); self.btn_anyway.setEnabled(bool(ready))
        self.btn_reject.setEnabled(job["state"] in (J.READY, J.ERROR))
        self.btn_rerun.setEnabled(job["state"] in (J.READY, J.ERROR) and bool(job["staged_path"]))
        self.btn_open.setEnabled(bool(job["staged_path"]) and Path(job["staged_path"]).parent.exists())
        if job["state"] == J.PROMOTED and job.get("final_path"):
            self.btn_open.setText("Show in library"); self.btn_open.setEnabled(Path(job["final_path"]).exists())
        else:
            self.btn_open.setText("Open staging folder")

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

    def _analyze(self, job_id: str):
        try:
            self.svc.analyze(job_id, lambda step: self.signals.progress.emit(job_id, step))
        finally:
            self.steps.pop(job_id, None)
            self.signals.done.emit(job_id)

    def _scan_incoming(self):
        def work():
            for job in self.svc.scan_incoming():
                self.signals.done.emit(job["id"])
                self._analyze(job["id"])
        if self.svc.settings.incoming_dir and self.pool.activeThreadCount() == 0:
            self.pool.start(Task(work, self.signals))

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
            self.statusBar().showMessage(f"Saved to {target}", 8000)
        except ActionBlocked as e:
            QMessageBox.warning(self, APP_NAME, str(e))
        self.refresh()

    def _reject(self):
        if not self.selected:
            return
        try:
            self.svc.reject(self.selected)
            self.statusBar().showMessage("Rejected. Staged copy deleted; your original file wasn't touched.", 8000)
        except ActionBlocked as e:
            QMessageBox.warning(self, APP_NAME, str(e))
        self.refresh()

    def _rerun(self):
        if self.selected:
            jid = self.selected
            self.pool.start(Task(lambda: self._analyze(jid), self.signals))

    def _open_folder(self):
        job = self.svc.db.job(self.selected) if self.selected else None
        if not job:
            return
        path = Path(job["final_path"]).parent if job["state"] == J.PROMOTED and job.get("final_path") \
            else Path(job["staged_path"]).parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _find(self):
        q = self.search.text().strip()
        if not q:
            self.search.setFocus()
            return
        for _name, url in STORES:
            QDesktopServices.openUrl(QUrl(url.format(quote_plus(q))))

    def _settings(self):
        if SettingsDialog(self.svc, self).exec():
            self.refresh()
            self._check_ffmpeg()

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
