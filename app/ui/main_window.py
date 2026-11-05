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
from .pages import HomePage, ReviewPage, SearchPage, row_data
from .library_page import LibraryPage, reveal_in_folder
from .settings_page import SettingsPage
from .tour import TourOverlay, default_steps
from .widgets import AvatarMenu, Signals, Task, TopBar, vbox

def _applog(line: str) -> None:
    try:
        from datetime import datetime
        from ..config import data_dir
        with open(data_dir() / "app.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} ui: {line}\n")
    except Exception:
        pass


SEARCH_LADDER_S = (4, 10, 22, 40)   # engine searches per query, short to long; each one's rows land when it ends
SEARCH_FALLBACK_S = (6, 25)         # the one retry without the shakiest word, when nothing at all came back
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
        self.settings = SettingsPage(self.svc); self.library = LibraryPage(self.svc)
        for p in (self.home, self.searchp, self.review, self.settings, self.library):
            self.pages.addWidget(p)
        self.library.open_job.connect(self._open_job)
        self.home.clear_finished.connect(self._clear_finished)
        self.review.remove_job.connect(self._remove_entry)
        self.review.reveal.connect(self._reveal)
        self.root.addWidget(shell); self.shell = shell

        self.home.search.connect(self._search); self.searchp.search.connect(self._search)
        self.home.open_job.connect(self._open_job); self.home.remove_job.connect(self._remove_entry)
        self.home.review_all.connect(lambda: self._tab("ready")); self.home.add_files.connect(self._pick_files)
        self.searchp.pick.connect(self._pick_candidate)
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
        if not self._backend_started:
            self._backend_started = True
            QTimer.singleShot(0, self._start_backend)

    def _waiting_screen(self) -> bool:
        return self.root.currentWidget() is self.onboarding and self.onboarding.currentWidget() is self.onboarding.connecting

    def _refresh_account(self):
        a = self.svc.accounts.load()
        self.topbar.set_initials(a.initials if a else "?")

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
        self._connected = bool(st.logged_in) or not self.svc.managed_mode
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
        self.svc.stop_backend()
        super().closeEvent(e)

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

    def _ladder(self, q: str, secs_list, sent: str, dropped: str, keep_id: str | None = None):
        """Run one ladder of engine searches for q, streaming merged rows. Returns the id the page is keyed on."""
        from ..core import fuzzy
        rungs = []
        for i, secs in enumerate(secs_list):
            r = self.svc.search(q, timeout_s=secs, check_login=(i == 0 and keep_id is None))
            rungs.append({"res": r, "done": False})
        sid = keep_id or rungs[0]["res"].search_id
        if keep_id is None:
            self.search_id = sid
        self._last_count = 0
        started = time.monotonic()
        merged: dict[str, Candidate] = {}
        shown = -1
        delay = 0.4
        try:
            while True:
                    time.sleep(delay)
                    delay = min(1.2, delay * 1.3)
                    if self.search_id != sid:
                        return None                                         # a newer search took over
                    now = time.monotonic()
                    best_count = (0, 0)
                    for rung in rungs:
                        if rung["done"]:
                            continue
                        res = self.svc.search_results(rung["res"].search_id)
                        for c in res.candidates:
                            merged.setdefault(c.key, c)
                        done, n_resp, n_files, err = self.svc.search_status(rung["res"].search_id)
                        best_count = max(best_count, (n_resp, n_files))
                        if done:
                            rung["done"] = True
                            _applog(f"rung {rung['res'].search_id[:8]} ({len(res.candidates)} rows) done; merged={len(merged)}")
                            if rung["res"].search_id != sid:
                                self.io.start(Task(lambda s=rung["res"].search_id: self.svc.forget_search(s), self.signals))
                    all_done = all(r["done"] for r in rungs) or now - started > secs_list[-1] + 20
                    if len(merged) != shown or all_done:
                        shown = len(merged)
                        out = SearchResult(query=q, search_id=sid, finished=all_done, candidates=list(merged.values()))
                        out.sent, out.dropped = sent, dropped
                        if all_done:
                            self._last_count = len(merged)
                            # the fallback runs only when this one found nothing; keep "searching" on until then
                            self.search_running = False if (len(merged) or dropped or len(fuzzy.words(q)) < 2) else True
                        self.signals.results.emit(out)
                    self.signals.progress_search.emit(best_count[0], best_count[1], len(merged) > 0)
                    if all_done:
                        words = getattr(self, "_seen_words", set())
                        for c in merged.values():
                            words.update(fuzzy.words(c.display_name or ""))
                        self._seen_words = words
                        return sid
        finally:
            pass

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
