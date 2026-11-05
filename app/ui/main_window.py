"""The window (design v5): onboarding until there's an account and a library folder, then the app:
top bar with tabs and the avatar menu, and the Home / Search / Review / Settings pages.

Widgets never touch files directly; everything goes through ArchiveService. Slow work runs on worker
threads: one pool for analyses (N parallel slots from Settings, the rest wait in the queue) and one
small pool for the engine and folder scans, so a busy analysis never blocks progress updates.
"""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import quote_plus

from PySide6.QtCore import QThreadPool, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox, QStackedWidget, QWidget

from ..adapters.base import Candidate, SearchResult
from ..config import APP_NAME
from ..core import jobs as J
from ..core.safety import Rejected
from ..core.service import ActionBlocked, ArchiveService
from ..media.tools import ToolMissing, find_tool
from . import theme as T
from .onboarding import Onboarding
from .pages import HomePage, ReviewPage, SearchPage
from .settings_page import SettingsPage
from .widgets import AvatarMenu, Signals, Task, TopBar, vbox

SEARCH_WAIT_S = 20            # keep collecting results for this long
SUPPORT_URL = "https://projectarchive.app/help/connection"      # FAQ page on the website (to be created)
FIREWALL_NOTE = (f"To download from other users, {APP_NAME} accepts incoming connections.\n\n"
                 "If Windows or macOS asks whether to allow this, choose Allow. Nothing is shared from your "
                 "computer unless you turn that on yourself in Settings.")

# Online store search. Not on a button right now; kept for a later "find it to buy" feature.
STORES = [
    ("Beatport", "https://www.beatport.com/search?q={}"),
    ("Bandcamp", "https://bandcamp.com/search?q={}"),
    ("Juno", "https://www.juno.co.uk/search/?q%5Ball%5D%5B%5D={}"),
    ("Traxsource", "https://www.traxsource.com/search?term={}"),
    ("Discogs", "https://www.discogs.com/search/?q={}&type=all"),
]


def open_store_search(query: str) -> None:
    for _name, url in STORES:
        QDesktopServices.openUrl(QUrl(url.format(quote_plus(query))))


class MainWindow(QMainWindow):
    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        self.pool = QThreadPool(); self.pool.setMaxThreadCount(max(1, svc.settings.max_concurrent_analyses))
        self.io = QThreadPool(); self.io.setMaxThreadCount(3)
        self._polling = self._scanning = False
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
        self._trouble_shown = False
        self._backend_started = False
        self._jobs: list[dict] = []
        self._analyses: dict[str, dict | None] = {}

        self.setWindowTitle(APP_NAME)
        self.resize(1280, 860)
        self.setAcceptDrops(True)
        self.apply_theme()
        self._build()

        svc.reconcile()
        svc.cleanup_expired()
        self.scan_timer = QTimer(self, interval=3000, timeout=self._scan_incoming); self.scan_timer.start()
        self.poll_timer = QTimer(self, interval=2000, timeout=self._poll_downloads); self.poll_timer.start()
        self.status_timer = QTimer(self, interval=15000, timeout=self._poll_status); self.status_timer.start()
        self.clean_timer = QTimer(self, interval=3600 * 1000, timeout=lambda: (svc.cleanup_expired(), self.refresh()))
        self.clean_timer.start()
        if svc.accounts.load() and svc.settings.setup_done:
            self._enter_app()
        else:
            self.root.setCurrentWidget(self.onboarding)

    # ---------------------------------------------------------------- build
    def _build(self):
        self.root = QStackedWidget(); self.setCentralWidget(self.root)
        self.onboarding = Onboarding(self.svc); self.onboarding.finished.connect(self._enter_app)
        self.root.addWidget(self.onboarding)

        shell = QWidget(); shell.setObjectName("root"); sl = vbox(shell)
        self.topbar = TopBar(); self.topbar.tab_clicked.connect(self._tab); self.topbar.avatar_clicked.connect(self._menu)
        sl.addWidget(self.topbar)
        self.pages = QStackedWidget(); sl.addWidget(self.pages, 1)
        self.home = HomePage(self.svc); self.searchp = SearchPage(self.svc); self.review = ReviewPage(self.svc)
        self.settings = SettingsPage(self.svc)
        for p in (self.home, self.searchp, self.review, self.settings):
            self.pages.addWidget(p)
        self.root.addWidget(shell); self.shell = shell
        self.menu = AvatarMenu(self); self.menu.picked.connect(self._menu_pick)

        self.home.search.connect(self._search); self.searchp.search.connect(self._search)
        self.home.open_job.connect(self._open_job); self.home.remove_job.connect(self._remove_entry)
        self.home.review_all.connect(lambda: self._tab("ready")); self.home.add_files.connect(self._pick_files)
        self.searchp.pick.connect(self._pick_candidate)
        self.review.select.connect(self._open_job)
        self.review.promote.connect(self._promote); self.review.reject.connect(self._reject)
        self.review.cancel.connect(self._cancel); self.review.rerun.connect(self._start_analysis)
        self.review.open_folder.connect(self._open_folder)
        self.settings.saved.connect(self._settings_saved); self.settings.sign_out.connect(self._sign_out)
        self.settings.account_changed.connect(self._refresh_account)
        self.apply_theme()

    def apply_theme(self):
        QApplication.instance().setStyleSheet(T.stylesheet(self.svc.settings.theme))
        if hasattr(self, "home"):
            accent = T.colours(self.svc.settings.theme)["accent"]
            self.home.scope.set_accent(accent); self.review.spectrum.set_accent(accent)

    def _enter_app(self):
        self.root.setCurrentWidget(self.shell)
        self._refresh_account()
        self.refresh()
        self._check_ffmpeg()
        if not self._backend_started:
            self._backend_started = True
            QTimer.singleShot(0, self._start_backend)

    def _refresh_account(self):
        a = self.svc.accounts.load()
        self.topbar.set_initials(a.initials if a else "?")

    # ---------------------------------------------------------------- navigation
    def _tab(self, key: str):
        self.topbar.set_active(key)
        if key == "queue":
            self.pages.setCurrentWidget(self.home)
        elif key == "ready":
            if not self.selected:
                self.selected = next((j["id"] for j in self.svc.jobs() if j["state"] == J.READY), None)
            self._show_review()
        elif key == "library":
            lib = Path(self.svc.settings.library_dir)
            lib.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(lib)))
            self.topbar.set_active("queue" if self.pages.currentWidget() is self.home else "ready")

    def _menu(self):
        self.menu.show_for(self.svc.accounts.load(), self.topbar.avatar, self.svc.settings.theme)

    def _menu_pick(self, key: str):
        if key in ("account", "settings", "appearance"):
            self.settings.show_section({"account": "account", "settings": "library", "appearance": "appearance"}[key])
            self.pages.setCurrentWidget(self.settings); self.topbar.set_active("")
        elif key == "help":
            QDesktopServices.openUrl(QUrl(SUPPORT_URL))
        elif key == "whatsnew":
            QMessageBox.information(self, APP_NAME, "0.3: new look, light and dark; sign-up and your account page; "
                                    "search results with Title, Mix and Artist; fastest sources first.")
        elif key == "signout":
            self._sign_out()

    def _sign_out(self):
        self.onboarding.setCurrentWidget(self.onboarding.signin if self.svc.accounts.load() else self.onboarding.signup)
        self.root.setCurrentWidget(self.onboarding)

    def _open_job(self, job_id: str):
        self.selected = job_id
        self.topbar.set_active("ready")
        self._show_review()

    def _show_review(self):
        self.pages.setCurrentWidget(self.review)
        self._refresh_review()

    # ---------------------------------------------------------------- data -> view
    def refresh(self):
        jobs = self.svc.jobs()
        analyses = {j["id"]: (self.svc.db.analysis(j["id"]) if j["state"] not in (J.STAGING, J.ANALYZING, J.QUEUED) else None)
                    for j in jobs}
        self._jobs, self._analyses = jobs, analyses
        self.home.steps = self.steps
        self.home.refresh(jobs, analyses)
        ready = sum(1 for j in jobs if j["state"] == J.READY)
        active = sum(1 for j in jobs if j["state"] in (J.QUEUED, J.STAGING, J.ANALYZING))
        self.topbar.set_counts(active, ready)
        if self.pages.currentWidget() is self.review:
            self._refresh_review()

    def _refresh_review(self):
        job = self.svc.db.job(self.selected) if self.selected else None
        a = self._analyses.get(self.selected) if job else None
        self.review.set_rail(self._jobs, self._analyses, self.steps)
        self.review.show_job(job, a, self.steps)

    def _remove_entry(self, job_id: str):
        try:
            self.svc.hide(job_id)
        except ActionBlocked as e:
            QMessageBox.warning(self, APP_NAME, str(e)); return
        if self.selected == job_id:
            self.selected = None
        self.refresh()

    # ---------------------------------------------------------------- engine
    def _start_backend(self):
        if not self.svc.managed_mode:
            self._poll_status(); return
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
        if self._trouble_shown:
            return
        self._trouble_shown = True
        box = QMessageBox(self); box.setWindowTitle(APP_NAME); box.setIcon(QMessageBox.Warning)
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

    def _poll_status(self):
        self.io.start(Task(lambda: self.signals.status.emit(self.svc.connector_status()), self.signals))

    def _on_status(self, st):
        c = T.colours(self.svc.settings.theme)
        colour = c["pass_"] if st.logged_in else (c["warn"] if st.available else c["faint"])
        chk = sum(1 for j in self._jobs if j["state"] in (J.STAGING, J.ANALYZING))
        down = sum(1 for j in self._jobs if j["state"] == J.QUEUED)
        slots = self.svc.settings.max_concurrent_analyses
        detail = f"{min(chk, slots)}/{slots} checking · {down} downloading" if (chk or down) else ""
        self.topbar.set_status(st.message, colour, detail)
        if self.svc.managed_mode and self.svc.backend_state == "failed" and self.root.currentWidget() is self.shell:
            self._connection_trouble()

    def closeEvent(self, e):
        self.svc.stop_backend()
        super().closeEvent(e)

    # ---------------------------------------------------------------- search
    def _search(self, q: str):
        q = q.strip()
        if not q:
            return
        self.home.q.setText(q); self.searchp.q.setText(q)
        self.pages.setCurrentWidget(self.searchp); self.topbar.set_active("")
        self.searchp.show_results(SearchResult(query=q, search_id="", finished=False), searching=True)
        self.search_running = True

        def work():
            res = self.svc.search(q)
            self.search_id = res.search_id
            started = time.monotonic()
            while True:
                time.sleep(1.0)
                if self.search_id != res.search_id:
                    return
                latest = self.svc.search_results(res.search_id); latest.query = q
                self.signals.results.emit(latest)
                if latest.finished or time.monotonic() - started > SEARCH_WAIT_S:
                    self.search_running = False
                    self.signals.results.emit(latest)
                    return
        self.io.start(Task(work, self.signals))

    def _on_results(self, res: SearchResult):
        if res.search_id == self.search_id:
            self.searchp.show_results(res, searching=self.search_running)

    def _pick_candidate(self, cand: Candidate):
        def work():
            job = self.svc.request_download(cand)
            self.signals.done.emit(job["id"])
        self.io.start(Task(work, self.signals))
        self.statusBar().showMessage(f"Requested “{cand.title or cand.display_name}”. It goes to quarantine first.", 6000)

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

    # ---------------------------------------------------------------- analysis
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
                self.signals.done.emit(job["id"]); self.signals.staged.emit(job["id"])
        self.io.start(Task(work, self.signals))

    def _on_progress(self, job_id, step):
        self.steps[job_id] = step
        self.refresh()

    def _on_failed(self, _job_id, message):
        self.refresh()
        QMessageBox.warning(self, APP_NAME, message)

    def _pick_files(self):
        exts = " ".join(f"*.{e}" for e in self.svc.settings.extensions)
        files, _ = QFileDialog.getOpenFileNames(self, "Add tracks", "", f"Audio ({exts})")
        self._enqueue_paths([Path(f) for f in files])

    # ---------------------------------------------------------------- decisions
    def _promote(self, job_id: str, override: bool):
        try:
            target = self.svc.promote(job_id, override_warning=override)
            self.statusBar().showMessage(f"Downloaded to {target}", 8000)
        except ActionBlocked as e:
            QMessageBox.warning(self, APP_NAME, str(e))
        self.refresh()

    def _reject(self, job_id: str):
        try:
            self.svc.reject(job_id)
            self.statusBar().showMessage("Deleted from quarantine. Nothing was saved to your computer.", 8000)
        except ActionBlocked as e:
            QMessageBox.warning(self, APP_NAME, str(e))
        self.refresh()

    def _cancel(self, job_id: str):
        def work():
            self.svc.cancel(job_id); self.signals.done.emit(job_id)
        self.io.start(Task(work, self.signals))

    def _open_folder(self, job_id: str):
        job = self.svc.db.job(job_id)
        if not job:
            return
        path = Path(job["final_path"]).parent if job["state"] == J.PROMOTED and job.get("final_path") \
            else Path(job["staged_path"]).parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ---------------------------------------------------------------- settings
    def _settings_saved(self):
        s = self.svc.settings
        self.pool.setMaxThreadCount(max(1, s.max_concurrent_analyses))
        self.apply_theme()
        now = (s.share_folder, s.soulseek_own_username, s.use_own_slskd)
        if getattr(self, "_engine_cfg", now) != now:
            self.svc.stop_backend(); self._start_backend()
        else:
            self._poll_status()
        self._engine_cfg = now
        self._check_ffmpeg()
        self.refresh()

    def _check_ffmpeg(self):
        s = self.svc.settings
        self._engine_cfg = (s.share_folder, s.soulseek_own_username, s.use_own_slskd)
        try:
            find_tool("ffmpeg", s.ffmpeg_path); find_tool("ffprobe", s.ffmpeg_path)
        except ToolMissing as e:
            QMessageBox.critical(self, APP_NAME, f"{e}\n\nChecks are disabled until FFmpeg is available.")

    # ---------------------------------------------------------------- drag & drop / keys
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self._enqueue_paths([Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()])

    def keyPressEvent(self, e):
        if self.pages.currentWidget() is self.review and self.selected:
            ids = [j["id"] for j in self._jobs if j["state"] == J.READY]
            if e.key() in (Qt.Key_Up, Qt.Key_Down) and ids:
                i = ids.index(self.selected) if self.selected in ids else -1
                self._open_job(ids[max(0, i - 1) if e.key() == Qt.Key_Up else min(len(ids) - 1, i + 1)]); return
            if e.key() in (Qt.Key_Return, Qt.Key_Enter):
                a = self._analyses.get(self.selected)
                if a and a["overall_status"] != "FAIL":
                    self._promote(self.selected, a["overall_status"] == "WARN"); return
            if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                self._reject(self.selected); return
        super().keyPressEvent(e)
