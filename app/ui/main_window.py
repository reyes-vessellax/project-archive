"""The window (design v5): onboarding until there's an account and a library folder, then the app:
top bar with tabs and the avatar menu, and the Home / Search / Review / Settings pages.

Widgets never touch files directly; everything goes through ArchiveService. Slow work runs on worker
threads: one pool for analyses (N parallel slots from Settings, the rest wait in the queue) and one
small pool for the engine and folder scans, so a busy analysis never blocks progress updates.
"""
from __future__ import annotations

import time
import sys
from pathlib import Path
from urllib.parse import quote_plus

from PySide6.QtCore import QThreadPool, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox, QStackedWidget, QWidget

from ..adapters.base import Candidate, SearchResult
from ..config import APP_NAME, data_dir
from ..core import jobs as J
from ..core.safety import Rejected
from ..core.service import ActionBlocked, ArchiveService
from ..media.tools import ToolMissing, find_tool
from . import theme as T
from .onboarding import Onboarding
from .pages import HomePage, ReviewPage, SearchPage, row_data
from .library_page import LibraryPage, reveal_in_folder
from .settings_page import SettingsPage
from .tour import TourOverlay, default_steps
from .widgets import AvatarMenu, Sidebar, Signals, Task, hbox, vbox
from .batch_page import Batch, BatchPage, BatchSignals
from ..core import batch as B
from ..core import batch_runner as BR
from ..core import updater as U
from ..core.session import Session, SessionStore

def _applog(line: str) -> None:
    try:
        from datetime import datetime
        from ..config import data_dir
        with open(data_dir() / "app.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} ui: {line}\n")
    except Exception:
        pass


# One network search per query (the network throttles accounts that send more; four per query made a
# session go dark by the third query). We stop it ourselves when results dry up. Deadlines in seconds.
SEARCH_LADDER_S = (40,)             # deadline for a normal search
SEARCH_FALLBACK_S = (25,)           # the one retry without the shakiest word, when nothing at all came back
SEARCH_MIN_S = 3.0                  # never stop before this: the first wave is still arriving
SEARCH_QUIET_S = 2.5                # stop once nothing new has arrived for this long (after SEARCH_MIN_S)
# Client-side budget so we never trip the network's own throttle: a small burst, then roughly one
# network search every SEARCH_REFILL_S on average. Over the line, the server simply stops answering for
# minutes, which looks like "no results" to the user; under it, every search comes back.
SEARCH_BURST = 4
SEARCH_REFILL_S = 6.0
SUPPORT_URL = "https://projectarchive.app/help/connection"      # FAQ page on the website (to be created)
FIREWALL_ASK = (f"To download from other users, {APP_NAME} needs to accept incoming connections.\n\n"
                f"Allow it now? Windows will ask you to confirm once. Nothing is shared from your computer "
                f"unless you turn that on yourself in Settings.")

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
        self.signals.done.connect(self._after_decision)          # before refresh: pick the next track first
        self.signals.done.connect(lambda _id: self.refresh())
        self.signals.done.connect(self._search_buttons_settle)
        self.signals.notice.connect(self._notice)
        self._acache: dict[str, dict] = {}                   # finished analyses never change; read each once
        self.signals.failed.connect(self._on_failed)
        self.signals.results.connect(self._on_results)
        self.signals.progress_search.connect(lambda r, f, more: self.searchp.set_progress(r, f, more))
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
        self._connected = False

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
        self.hk_timer = QTimer(self, interval=10 * 60 * 1000, timeout=lambda: self.io.start(Task(svc.engine_housekeeping, self.signals)))
        self.hk_timer.start()
        self.sessions = SessionStore(data_dir() / "session.json")
        self.session = self.sessions.load()
        self._update_zip = None; self._update_cmd = None
        self.update_timer = QTimer(self, interval=6 * 3600 * 1000, timeout=self._check_updates); self.update_timer.start()
        QTimer.singleShot(60_000, self._check_updates)
        if self.session.window and len(self.session.window) == 4:
            self.setGeometry(*self.session.window)
        if self.session.maximized:
            self.showMaximized()
        if svc.accounts.load() and svc.settings.setup_done:
            self._enter_app()
        else:
            self.root.setCurrentWidget(self.onboarding)

    # ---------------------------------------------------------------- build
    def _build(self):
        self.root = QStackedWidget(); self.setCentralWidget(self.root)
        self.onboarding = Onboarding(self.svc); self.onboarding.finished.connect(self._enter_app)
        self.root.addWidget(self.onboarding)

        shell = QWidget(); shell.setObjectName("root"); sl = hbox(shell)
        self.topbar = Sidebar(); self.topbar.tab_clicked.connect(self._tab); self.topbar.avatar_clicked.connect(self._menu)
        self.topbar.update_clicked.connect(self._install_update)
        sl.addWidget(self.topbar)
        self.pages = QStackedWidget(); sl.addWidget(self.pages, 1)
        self.home = HomePage(self.svc); self.searchp = SearchPage(self.svc); self.review = ReviewPage(self.svc)
        self.settings = SettingsPage(self.svc); self.library = LibraryPage(self.svc); self.batchp = BatchPage()
        for p in (self.home, self.searchp, self.review, self.settings, self.library, self.batchp):
            self.pages.addWidget(p)
        self.library.open_job.connect(self._open_job)
        self.batchp.start.connect(self._batch_start); self.batchp.choose_folder.connect(self._batch_folder)
        self.batchp.stop.connect(self._batch_stop); self.batchp.download_all.connect(self._batch_download_all)
        self.batchp.removed.connect(lambda _id: self._save_session())
        self.bsig = BatchSignals(); self.bsig.loaded.connect(self._batch_loaded); self.bsig.item.connect(self.batchp.update_item)
        self.bsig.item.connect(lambda *_: self._save_session()); self.bsig.error.connect(self._batch_error)
        self.bsig.finished.connect(self._batch_finished)
        self._batches_running = 0
        self.batch_pool = QThreadPool(); self.batch_pool.setMaxThreadCount(1)
        self._batch_stop_flag = False
        self.home.clear_finished.connect(self._clear_finished)
        self.review.remove_job.connect(self._remove_entry)
        self.review.reveal.connect(self._reveal)
        self.root.addWidget(shell); self.shell = shell

        self.home.search.connect(self._search); self.searchp.search.connect(self._search)
        self.home.open_job.connect(self._open_job); self.home.remove_job.connect(self._remove_entry)
        self.home.review_all.connect(lambda: self._tab("ready")); self.home.add_files.connect(self._pick_files)
        self.searchp.pick.connect(self._pick_candidate)
        self.searchp.filters_changed.connect(lambda: self._save_session())
        self.review.select.connect(self._open_job)
        self.review.promote.connect(self._promote); self.review.reject.connect(self._reject)
        self.review.cancel.connect(self._cancel); self.review.rerun.connect(self._recheck)
        self.review.retry.connect(self._retry_download)
        self.review.open_folder.connect(self._open_folder)
        self.settings.saved.connect(self._settings_saved); self.settings.sign_out.connect(self._sign_out)
        self.settings.account_changed.connect(self._refresh_account)
        self.apply_theme()

    def _brand_theme(self):
        from .brand import app_icon
        self.topbar.brand.set_theme(self.svc.settings.theme)
        self.setWindowIcon(app_icon(self.svc.settings.theme))

    def apply_theme(self):
        theme = self.svc.settings.theme
        if getattr(self, "_applied_theme", None) != theme:
            self._applied_theme = theme
            QApplication.instance().setStyleSheet(T.stylesheet(theme))
        if hasattr(self, "home"):
            accent = T.colours(self.svc.settings.theme)["accent"]
            self.home.scope.set_accent(accent); self.review.spectrum.set_accent(accent); self.library.set_accent(accent)
        if hasattr(self, "topbar"):
            self._brand_theme()

    def _enter_app(self):
        self._refresh_account()
        self.refresh()
        self._check_ffmpeg()
        if self.svc.managed_mode and not self._connected:
            self.onboarding.connecting.start()
            self.onboarding.connecting.mark("engine", "busy")
            self.onboarding.setCurrentWidget(self.onboarding.connecting)
            self.root.setCurrentWidget(self.onboarding)
            self._connect_deadline = time.monotonic() + 90
            self._wait_timer = QTimer(self, interval=700, timeout=self._poll_status); self._wait_timer.start()
        else:
            self.root.setCurrentWidget(self.shell)
            self._maybe_start_tour()
        self._restore_session()
        if not self._backend_started:
            self._backend_started = True
            QTimer.singleShot(0, self._start_backend)

    def _waiting_screen(self) -> bool:
        return self.root.currentWidget() is self.onboarding and self.onboarding.currentWidget() is self.onboarding.connecting

    def _refresh_account(self):
        a = self.svc.accounts.load()
        self.topbar.set_initials(a.initials if a else "?", (a.name if a else "") or "Account")

    # ---------------------------------------------------------------- navigation
    def _tab(self, key: str):
        self.topbar.set_active(key)
        if key == "queue":
            self.pages.setCurrentWidget(self.home)
        elif key == "ready":
            if not self.selected or not self.svc.db.job(self.selected):
                self.selected = next((j["id"] for j in self.svc.jobs() if j["state"] == J.READY), None) or \
                                (self._jobs[0]["id"] if self._jobs else None)
            self._show_review()
        elif key == "search":
            self.pages.setCurrentWidget(self.searchp)          # last results stay as they were
            if not self.search_id:
                self.searchp.show_results(SearchResult(query="", search_id="", finished=True), searching=False,
                                          idle="Type something above and press Enter.")
        elif key == "library":
            self.library.refresh()
            self.pages.setCurrentWidget(self.library)
        elif key == "batch":
            self.pages.setCurrentWidget(self.batchp)
        self._page_key = key
        self._save_session()

    def _menu(self):
        menu = AvatarMenu(self)                           # built on click, destroyed on close
        menu.picked.connect(self._menu_pick)
        menu.show_for(self.svc.accounts.load(), self.topbar.avatar, self.svc.settings.theme)

    def _menu_pick(self, key: str):
        if key in ("account", "settings", "appearance"):
            self.settings.show_section({"account": "account", "settings": "library", "appearance": "appearance"}[key])
            self.pages.setCurrentWidget(self.settings); self.topbar.set_active("")
        elif key == "help":
            QDesktopServices.openUrl(QUrl(SUPPORT_URL))
        elif key == "tour":
            self._start_tour()
        elif key == "whatsnew":
            QMessageBox.information(self, APP_NAME, "0.3: new look, light and dark; sign-up and your account page; "
                                    "search results with Title, Mix and Artist; fastest sources first.")
        elif key == "signout":
            self._sign_out()

    # ---------------------------------------------------------------- tour
    def _start_tour(self):
        if getattr(self, "_tour", None):
            return
        self._tab("queue")
        self._tour = TourOverlay(self, default_steps(), self._tour_navigate)
        self._tour.finished.connect(self._tour_finished)

    def _tour_navigate(self, page: str):
        if page == "ready":
            if not self.selected:
                self.selected = next((j["id"] for j in self._jobs if j["state"] == J.READY), None) or \
                                (self._jobs[0]["id"] if self._jobs else None)
            self._show_review(); self.topbar.set_active("ready")
        elif page == "settings":
            self.pages.setCurrentWidget(self.settings); self.topbar.set_active("")
        else:
            self._tab("queue")

    def _tour_finished(self, completed: bool):
        self._tour = None
        s = self.svc.settings; s.tour_done = True; self.svc.save_settings(s)
        self._tab("queue")
        self.statusBar().showMessage("You can replay the tour any time from your avatar menu." if not completed else
                                     "Tour finished. Happy digging.", 6000)

    def _maybe_start_tour(self):
        if not self.svc.settings.tour_done and self.root.currentWidget() is self.shell:
            QTimer.singleShot(400, self._start_tour)

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
        analyses = {j["id"]: self._analysis(j) for j in jobs}
        self._jobs, self._analyses = jobs, analyses
        # sources that already let us down, so the search table can flag them in red
        problems = {}
        for j in self.svc.db.jobs(include_hidden=True):
            if not (j.get("remote_user") and j.get("remote_path")):
                continue
            key = f"{j['remote_user']}\n{j['remote_path']}"
            if j["state"] == J.ERROR:
                problems[key] = "failed before"
            else:
                a = self._analysis(j)
                if a and a["overall_status"] == "FAIL":
                    problems[key] = "broken file"
        self.searchp.set_problem_sources(problems)
        self.home.steps = self.steps
        self.home.refresh(jobs, analyses)
        ready = sum(1 for j in jobs if j["state"] == J.READY)
        active = sum(1 for j in jobs if j["state"] in (J.QUEUED, J.STAGING, J.ANALYZING))
        self.topbar.set_counts(active, ready)
        if self.pages.currentWidget() is self.review:
            self._refresh_review()
        elif self.pages.currentWidget() is self.library:
            self.library.refresh()

    def _analysis(self, job: dict) -> dict | None:
        if job["state"] in (J.STAGING, J.ANALYZING, J.QUEUED):
            return None
        a = self._acache.get(job["id"])
        if a is None:
            a = self.svc.db.analysis(job["id"])
            if a is not None and job["state"] == J.PROMOTED or (a is not None and job["state"] in J.FINAL):
                self._acache[job["id"]] = a                  # settled: cache; READY rows may be re-checked, so re-read those
        return a

    def _refresh_review(self):
        job = self.svc.db.job(self.selected) if self.selected else None
        a = self._analyses.get(self.selected) if job else None
        self.review.set_rail(self._jobs, self._analyses, self.steps)
        self.review.show_job(job, a, self.steps)

    def _after_decision(self, job_id: str):
        """After Download to Library / Delete the track has left the Ready list: move on to the next one waiting."""
        if self.selected != job_id:
            return
        job = self.svc.db.job(job_id)
        if job and job.get("hidden"):
            waiting = [j["id"] for j in self.svc.jobs() if j["state"] == J.READY]
            self.selected = waiting[0] if waiting else None

    def _clear_finished(self):
        n = self.svc.hide_finished()
        if self.selected and not self.svc.db.job(self.selected) or (self.selected and self.svc.db.job(self.selected).get("hidden")):
            self.selected = None
        self.refresh()
        self.statusBar().showMessage(f"Cleared {n} finished track{'s' if n != 1 else ''} from the list.", 4000)

    def _reveal(self, job_id: str):
        job = self.svc.db.job(job_id)
        if job and job.get("final_path") and Path(job["final_path"]).exists():
            reveal_in_folder(Path(job["final_path"]))

    def _remove_entry(self, job_id: str):
        """× on a queue row. Finished entries just leave the list; a checked track is deleted from quarantine."""
        job = self.svc.db.job(job_id)
        if not job:
            return
        if self.selected == job_id:
            self.selected = None
        if job["state"] in (J.READY, J.ERROR):
            name = row_data(job, self._analyses.get(job_id), self.steps)["title"]
            self.statusBar().showMessage(f"Deleted “{name}” from quarantine. It was never saved to your library.", 6000)

            def work():
                try:
                    self.svc.reject(job_id)
                except ActionBlocked:
                    pass
                self.svc.hide(job_id)
                self.signals.done.emit(job_id)
            self.io.start(Task(work, self.signals))
        else:
            self.svc.hide(job_id)
            self.refresh()

    # ---------------------------------------------------------------- engine
    def _start_backend(self):
        if not self.svc.managed_mode:
            self._poll_status(); return
        self._ensure_firewall()
        self._trouble_shown = False
        self.svc.backend_state = "starting"
        self._poll_status()

        def work():
            self.svc.start_backend()
            self.signals.status.emit(self.svc.connector_status())
            if self.svc.port_note:
                self.signals.notice.emit(self.svc.port_note)
        self.io.start(Task(work, self.signals))

    def _ensure_firewall(self):
        """Ask Windows whether the engine is already allowed; only if it isn't, offer to allow it (once per path)."""
        from ..core import firewall
        from ..core.slskd_manager import engine_exe
        if not firewall.is_windows() or not self.svc.manager.binary_dir:
            return
        exe = engine_exe(self.svc.manager.binary_dir)
        if exe is None:
            return
        s = self.svc.settings
        if s.firewall_done_for == str(exe):
            return                                          # already handled for this exact build
        exists = firewall.rule_exists(exe)
        if exists:                                          # the user allowed it before (our rule or Windows' own)
            s.firewall_done_for = str(exe); self.svc.save_settings(s); return
        if exists is None:                                  # couldn't ask; don't nag, let Windows do its thing once
            s.firewall_done_for = str(exe); self.svc.save_settings(s); return
        box = QMessageBox(self); box.setWindowTitle(APP_NAME); box.setIcon(QMessageBox.Question)
        box.setText(FIREWALL_ASK)
        allow = box.addButton("Allow", QMessageBox.AcceptRole); box.addButton("Not now", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is allow:
            if not firewall.add_rule(exe):
                self.statusBar().showMessage("Couldn't add the firewall rule. If Windows asks later, choose Allow.", 8000)
        s.firewall_done_for = str(exe); self.svc.save_settings(s)   # either way, don't ask again for this build

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
        was = self._connected
        self._connected = bool(st.logged_in) or not self.svc.managed_mode
        if self._connected and not was and self.svc.adapter is not None and not getattr(self, "_batches_resumed", False):
            self._batches_resumed = True
            QTimer.singleShot(3000, self._batch_resume_all)      # unfinished playlists carry on once connected
        self.home.set_connected(self._connected, st.message)
        self.searchp.set_connected(self._connected)
        if self._waiting_screen():
            c = self.onboarding.connecting
            phase = getattr(self.svc, "phase", "")
            if phase in ("signin", "port", "ready") or st.available:
                c.mark("engine", "done")
                c.mark("network", "done" if st.logged_in else "busy")
            if phase == "port":
                c.mark("port", "busy")
            elif phase == "ready":
                port = self.svc.settings.listen_port
                if not self.svc.settings.upnp:
                    c.mark("port", "skip", "off in Settings")
                else:
                    c.mark("port", "done" if self.svc.port_open else "fail",
                           f"port {port} open" if self.svc.port_open else "router said no; using the slow route")
            if st.logged_in:
                c.mark("shares", "done" if self.svc.settings.share_folder else "skip",
                       "" if self.svc.settings.share_folder else "nothing shared yet")
            failed = self.svc.backend_state == "failed"
            timed_out = time.monotonic() > getattr(self, "_connect_deadline", 0)
            settled = phase == "ready" or phase == ""                 # don't close the screen mid-port-check
            if (self._connected and settled) or failed or timed_out:
                if getattr(self, "_wait_timer", None):
                    self._wait_timer.stop()
                c.finish()
                self.root.setCurrentWidget(self.shell)
                if self._connected:
                    self.io.start(Task(self.svc.engine_housekeeping, self.signals))   # clear leftovers from last run
                self._maybe_start_tour()
                if failed:
                    self._connection_trouble()
                elif timed_out and not self._connected:
                    self.statusBar().showMessage("Still signing in. You can add local files meanwhile.", 8000)
        elif self.svc.managed_mode and self.svc.backend_state == "failed" and self.root.currentWidget() is self.shell:
            self._connection_trouble()
        if self.svc.managed_mode and st.available and not st.logged_in:
            QTimer.singleShot(2000, self._poll_status)      # poll faster while signing in

    def closeEvent(self, e):
        self._batch_stop_flag = True
        self._save_session(now=True)
        self.svc.stop_backend()
        super().closeEvent(e)

    # ---------------------------------------------------------------- auto save
    def _save_session(self, now: bool = False):
        if not hasattr(self, "sessions"):
            return
        s = self.session
        s.page = getattr(self, "_page_key", s.page)
        s.selected_job = self.selected or ""
        g = self.normalGeometry() if self.isMaximized() else self.geometry()
        s.window, s.maximized = [g.x(), g.y(), g.width(), g.height()], self.isMaximized()
        s.search_text = self.searchp.q.text()
        from dataclasses import asdict
        s.filters = asdict(self.searchp.filters)
        s.batches = [b.to_dict() for b in self.batchp.batches]
        s.batch_selected = self.batchp.selected or ""
        s.batch_name, s.batch_items = "", []
        self.sessions.save(s, now=now)

    def _restore_session(self):
        s = self.session
        saved = list(s.batches)
        if s.batch_items:                                   # 0.6.0-dev sessions had a single list
            saved.append({"name": s.batch_name or "Batch", "service": "List", "items": s.batch_items})
        for d in reversed(saved):                           # stored newest first; add oldest first
            items = []
            for x in d.get("items", []):
                st = x.get("status", "waiting")
                items.append(BR.Item(B.Wanted(x.get("artist", ""), x.get("title", ""), x.get("mix", ""), x.get("source", "")),
                                     status="waiting" if st in ("searching", "found") else st,   # picks aren't kept: find again
                                     detail="" if st in ("searching", "found") else x.get("detail", "")))
            b = Batch(name=d.get("name", "Batch"), service=d.get("service", "List"), items=items)
            if d.get("id"):
                b.id = d["id"]
            self.batchp.add_batch(b, select=False)
        if s.batch_selected and self.batchp.batch(s.batch_selected):
            self.batchp.select(s.batch_selected)
        self.searchp.q.setText(s.search_text or "")
        self.searchp.set_filters(s.filters or {})
        if s.selected_job and self.svc.db.job(s.selected_job):
            self.selected = s.selected_job
        if s.page in ("queue", "search", "ready", "library", "batch"):
            self._tab(s.page)

    def moveEvent(self, e):
        super().moveEvent(e); self._save_session()

    def resizeEvent(self, e):
        super().resizeEvent(e); self._save_session()

    # ---------------------------------------------------------------- batch
    def _library_names(self) -> list[tuple[str, str]]:
        out = []
        for j in self.svc.db.jobs(states=(J.PROMOTED,), limit=20000):
            a = self.svc.db.analysis(j["id"]) or {}
            m = a.get("meta") or {}
            if m.get("title"):
                out.append((m.get("artist", ""), f"{m['title']} ({m['mix']})" if m.get("mix") else m["title"]))
            else:
                from ..adapters.base import parse_track
                art, t, mix = parse_track(j["original_name"])
                out.append((art, f"{t} ({mix})" if mix else t))
        return out

    def _batch_start(self, text: str):
        if not text:
            self.batchp.show_message("Paste a playlist link or some track names first.")
            return
        self.batchp.show_message("Reading the playlist…")

        def work():
            try:
                first = text.split()[0]
                if first.lower().startswith(("https://", "http://")) and len(text.split()) == 1:
                    name, wanted = B.from_link(first)
                    svc = B.service_of(first) or "List"
                else:
                    wanted = B.parse_text(text)
                    svc = "CSV" if wanted and wanted[0].source == "CSV" else "List"
                    name = f"Pasted list · {len(wanted)} tracks"
            except B.LinkUnreadable as e:
                self.bsig.error.emit(str(e)); return
            self.bsig.loaded.emit(name, svc, [BR.Item(w) for w in wanted])
        self.io.start(Task(work, self.signals))

    def _batch_folder(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "Choose a folder of tracks to upgrade")
        if not d:
            return

        def work():
            wanted = B.from_folder(Path(d))
            self.bsig.loaded.emit(f"Upgrade · {Path(d).name}", "Folder", [BR.Item(w) for w in wanted])
        self.io.start(Task(work, self.signals))

    def _batch_error(self, msg: str):
        self.batchp.show_message(msg)

    def _batch_loaded(self, name: str, service: str, items: list):
        if not items:
            self.batchp.show_message("No tracks found in that. Check the link, or paste the track names instead.")
            return
        self.batchp.show_message("")
        self.batchp.take_input()
        b = Batch(name=name, service=service, items=items)
        self.batchp.add_batch(b)
        self._tab("batch")
        self._save_session()
        self._batch_run(b)

    def _batch_run(self, b: Batch):
        if self.svc.adapter is None:
            self.batchp.set_running(False, "Not connected yet. The playlist is saved; it's searched as soon as you're connected.")
            return
        self._batch_stop_flag = False
        self._batches_running += 1
        self.batchp.set_running(True, f"Searching one track every {int(BR.GAP_S)} seconds so the network doesn't slow your "
                                      "account down. Playlists are searched one after another; keep using the app meanwhile.")
        library = self._library_names()

        def work():
            try:
                BR.run(b.items, self.svc, library, lambda i, it: self.bsig.item.emit(b.id, i, it),
                       should_stop=lambda: self._batch_stop_flag)
            finally:
                self.bsig.finished.emit(b.id)
        self.batch_pool.start(Task(work, self.signals))      # one thread: playlists run one after another

    def _batch_finished(self, _batch_id: str):
        self._batches_running = max(0, self._batches_running - 1)
        if not self._batches_running:
            self.batchp.set_running(False, "")
        self._save_session()

    def _batch_stop(self):
        self._batch_stop_flag = True
        self.batchp.set_running(False, "Paused. Add a playlist or reopen the app to carry on where it left off.")

    def _batch_resume_all(self):
        """On start-up (once connected): finish any playlist that still has tracks to search."""
        for b in reversed(self.batchp.batches):
            if b.count("waiting"):
                self._batch_run(b)

    def _batch_download_all(self, batch_id: str):
        b = self.batchp.batch(batch_id)
        if not b:
            return
        picks = [(i, it) for i, it in enumerate(b.items) if it.status == "found" and it.pick is not None]

        def work():
            for i, it in picks:
                try:
                    job = self.svc.request_download(it.pick, playlist=b.name)
                    it.status = "queued"
                    self.signals.done.emit(job["id"])
                except ActionBlocked as e:
                    it.status, it.detail = "error", str(e)[:120]
                self.bsig.item.emit(b.id, i, it)
        self.io.start(Task(work, self.signals))
        self.batchp.set_running(self._batches_running > 0,
                                f"Downloading {len(picks)} track(s) from “{b.name}” into quarantine. Each shows up under Ready "
                                f"once checked; the ones you keep go into a “{b.name}” folder in your library.")

    # ---------------------------------------------------------------- updates
    def _check_updates(self):
        if not getattr(sys, "frozen", False):
            return                                          # running from source: git is the updater

        def work():
            try:
                u = U.check()
                if u is None:
                    return
                zp = U.download(u)
                cmd = U.stage_install(zp)
                self._update_cmd, self._update_version = cmd, u.version
                self.signals.notice.emit(f"UPDATE_READY {u.version}")
            except U.UpdateError as e:
                _applog(f"update: {e}")
        self.io.start(Task(work, self.signals))

    def _install_update(self):
        if not self._update_cmd:
            return
        self._save_session(now=True)
        U.launch_installer(self._update_cmd)
        self.close()
        QApplication.instance().quit()

    # ---------------------------------------------------------------- search
    def _search(self, q: str):
        q = q.strip()
        if not q:
            return
        if self.svc.managed_mode and not self._connected:
            self.statusBar().showMessage("Still connecting. Search opens as soon as you're signed in.", 5000)
            return
        self.home.q.setText(q); self.searchp.q.setText(q)
        self.pages.setCurrentWidget(self.searchp); self.topbar.set_active("search")
        self.search_id = None                                    # results from the previous search stop landing
        self.searchp.begin_search(q)
        self.home.search_btn.setText("Searching…"); self.home.search_btn.setEnabled(False)
        self.search_running = True

        def work():
            """The engine releases a search's results when that search ends, so one query becomes a ladder of
            engine searches (short to long). Each rung that finishes adds its rows to the list, so the page
            fills top-down while the longer rungs keep collecting. If the engine does hand out live rows for
            a running search, those are used too. If nothing at all comes back, one more try without the
            word most likely to be a typo (and the header says so)."""
            sid = None
            try:
                # the previous query's searches, finished or not, out of the engine before new ones go in:
                # every live search costs the engine memory and the network goodwill
                for old in list(getattr(self, "_active_rungs", [])):
                    self.svc.forget_search(old)
                self._active_rungs = []
                self.svc.engine_housekeeping()
                sid = self._ladder(q, SEARCH_LADDER_S, sent=q, dropped="")
                if sid is None:
                    return
                if self._last_count == 0 and self.search_id == sid:
                    from ..core import fuzzy
                    dropped = fuzzy.shakiest_word(q, self._known_words())
                    if dropped:
                        reduced = " ".join(w for w in q.split() if w.lower().strip("'\"") != dropped)
                        _applog(f"no results for {q!r}; trying without {dropped!r}: {reduced!r}")
                        self._ladder(reduced, SEARCH_FALLBACK_S, sent=reduced, dropped=dropped, keep_id=sid)
            except Exception as e:
                import traceback
                _applog("search failed: " + traceback.format_exc())
                self.search_running = False                 # before the emit, so the buttons come back
                self.signals.results.emit(SearchResult(query=q, search_id=sid, finished=True,
                                                       error=f"The search stopped: {e}"))
                raise
            finally:
                self.search_running = False
                self.signals.done.emit("")
        self.io.start(Task(work, self.signals))

    def _known_words(self) -> set[str]:
        """Words we've seen in result names this session plus the library's own file names."""
        from ..core import fuzzy
        known = set(getattr(self, "_seen_words", set()))
        try:
            for j in self.svc.db.jobs(include_hidden=True, limit=2000):
                known.update(fuzzy.words(j.get("original_name") or ""))
        except Exception:
            pass
        return known

    def _take_search_token(self) -> None:
        """Token bucket for network searches; blocks (off the UI thread) until one is available."""
        now = time.monotonic()
        tokens, last = getattr(self, "_bucket", (SEARCH_BURST, now))
        tokens = min(SEARCH_BURST, tokens + (now - last) / SEARCH_REFILL_S)
        if tokens < 1:
            wait = (1 - tokens) * SEARCH_REFILL_S
            self.signals.notice.emit(f"Pacing… the network limits how often we can ask. Next search in {wait:.0f} s.")
            _applog(f"search budget: waiting {wait:.1f}s")
            time.sleep(wait)
            now = time.monotonic(); tokens = 1
        self._bucket = (tokens - 1, now)

    def _ladder(self, q: str, secs_list, sent: str, dropped: str, keep_id: str | None = None):
        """ONE network search per query (what the other clients do, and all the network tolerates), stopped
        by us the moment it's ripe: the engine only hands out a search's rows once it has ended, so we watch
        its live counts and end it when they stop growing (or at the deadline), then read everything it got.
        Returns the id the page is keyed on. secs_list[-1] is the deadline."""
        from ..core import fuzzy
        deadline = float(secs_list[-1])
        self._take_search_token()
        res = self.svc.search(q, timeout_s=deadline + 10, check_login=(keep_id is None))
        sid_engine = res.search_id
        sid = keep_id or sid_engine
        if keep_id is None:
            self.search_id = sid
        self._last_count = 0
        t0 = time.monotonic()
        history: list[tuple[float, int]] = []                  # (elapsed, files) samples
        stopped = False
        delay = 0.35
        while True:
            time.sleep(delay)
            delay = min(0.8, delay * 1.25)
            if self.search_id != sid:
                self.svc.stop_search(sid_engine)
                return None                                     # a newer search took over
            done, n_users, n_files, err = self.svc.search_status(sid_engine)
            el = time.monotonic() - t0
            history.append((el, n_files))
            self.signals.progress_search.emit(n_users, n_files, False)
            if not done and not stopped and self._ripe(history, el, deadline):
                self.svc.stop_search(sid_engine); stopped = True
                _applog(f"search {sid_engine[:8]} {q!r} stopped at {el:.1f}s with {n_users} users / {n_files} files")
                continue
            if done or el > deadline + 25:
                final = self.svc.search_results(sid_engine); final.query = q
                final.search_id = sid; final.finished = True
                final.sent, final.dropped = sent, dropped
                if err:
                    final.error = err
                n = len(final.candidates)
                _applog(f"search {sid_engine[:8]} {q!r} done at {el:.1f}s: {n} rows from {n_users} users")
                self._last_count = n
                self.search_running = False if (n or dropped or len(fuzzy.words(q)) < 2) else True
                self.signals.results.emit(final)
                words = getattr(self, "_seen_words", set())
                for c in final.candidates:
                    words.update(fuzzy.words(c.display_name or ""))
                self._seen_words = words
                if sid_engine != sid:
                    self.io.start(Task(lambda s=sid_engine: self.svc.forget_search(s), self.signals))
                return sid

    @staticmethod
    def _ripe(history, el: float, deadline: float) -> bool:
        """Stop when the flow of results has dried up — not before SEARCH_MIN_S, never after the deadline.
        A plateau is: nothing new for SEARCH_QUIET_S, or growth under 3% over the last SEARCH_QUIET_S once
        we already hold a good number of files."""
        if el >= deadline:
            return True
        if el < SEARCH_MIN_S:
            return False
        files_now = history[-1][1]
        if files_now == 0:
            return False                                        # rare query: give the far corners time
        past = [f for (t, f) in history if t <= el - SEARCH_QUIET_S]
        if not past:
            return False
        then = past[-1]
        grew = files_now - then
        return grew == 0 or (files_now >= 200 and grew < files_now * 0.03)

    def _search_buttons_settle(self, _id: str = ""):
        """Whatever path a search took to its end, the two Search buttons must read "Search" again."""
        if not self.search_running:
            self.home.search_btn.setText("Search"); self.home.search_btn.setEnabled(self._connected)
            self.searchp.end_search()

    def _on_results(self, res: SearchResult):
        _applog(f"on_results id={str(res.search_id)[:8]} mine={str(self.search_id)[:8]} n={len(res.candidates)} running={self.search_running}")
        if res.search_id == self.search_id:
            self.searchp.show_results(res, searching=self.search_running)
            if not self.search_running:
                self.home.search_btn.setText("Search"); self.home.search_btn.setEnabled(self._connected)
        self._last_results = res

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

    def _recheck(self, job_id: str):
        """Re-check from the review page: show it at once (CHECK tag, moving dots, button greyed)."""
        job = self.svc.db.job(job_id)
        if not job or not job.get("staged_path"):
            self.statusBar().showMessage("Nothing to re-check: the file never arrived. Use Retry download.", 6000); return
        self.steps[job_id] = "Re-checking…"
        self.svc.db.update_job(job_id, state=J.ANALYZING, message="Re-checking…")
        self._acache.pop(job_id, None)
        self.refresh()
        self._start_analysis(job_id)

    def _retry_download(self, job_id: str):
        self.review.set_busy(True)

        def work():
            try:
                self.svc.retry_download(job_id)
                self.signals.notice.emit("Asked the source again.")
            except ActionBlocked as e:
                self.signals.notice.emit(str(e))
            finally:
                self.signals.done.emit(job_id)
        self.io.start(Task(work, self.signals))

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
        """Background problems show in the status strip, once, never as a popup."""
        self.refresh()
        if message != getattr(self, "_last_notice", None):
            self._last_notice = message
            self.statusBar().showMessage(message, 8000)
            QTimer.singleShot(8500, lambda: setattr(self, "_last_notice", None))

    def _pick_files(self):
        exts = " ".join(f"*.{e}" for e in self.svc.settings.extensions)
        files, _ = QFileDialog.getOpenFileNames(self, "Add tracks", "", f"Audio ({exts})")
        self._enqueue_paths([Path(f) for f in files])

    # ---------------------------------------------------------------- decisions
    def _promote(self, job_id: str, override: bool):
        """Hash-check + copy happen off the UI thread; the row shows SAVING meanwhile."""
        self.review.set_busy(True)

        def work():
            try:
                target = self.svc.promote(job_id, override_warning=override)
                self.signals.notice.emit(f"Downloaded to {target}")
            except ActionBlocked as e:
                self.signals.notice.emit(str(e))
            finally:
                self.signals.done.emit(job_id)
        self.io.start(Task(work, self.signals))

    def _reject(self, job_id: str):
        self.review.set_busy(True)

        def work():
            try:
                self.svc.reject(job_id)
                self.signals.notice.emit("Deleted from quarantine. Nothing was saved to your computer.")
            except ActionBlocked as e:
                self.signals.notice.emit(str(e))
            finally:
                self.signals.done.emit(job_id)
        self.io.start(Task(work, self.signals))

    def _notice(self, message: str):
        if message.startswith("UPDATE_READY "):
            self.topbar.set_update(f"Update to {message.split()[1]} · restart")
            return
        self.review.set_busy(False)
        self.statusBar().showMessage(message, 8000)

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
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        web = [u.toString() for u in md.urls() if u.scheme() in ("http", "https")]
        if not web and md.hasText() and md.text().strip().lower().startswith("https://"):
            web = [md.text().strip().split()[0]]
        if web and B.service_of(web[0]):                    # a playlist link dragged from the browser
            self._tab("batch"); self._batch_start(web[0]); return
        self._enqueue_paths([Path(u.toLocalFile()) for u in md.urls() if u.isLocalFile()])

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
