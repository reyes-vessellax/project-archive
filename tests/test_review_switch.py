"""Switching tracks on Ready: the previous track's check rows must vanish at once, not paint under the new ones."""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_switching_tracks_leaves_no_ghost_rows():
    from PySide6.QtWidgets import QApplication, QWidget
    from app.config import Settings
    from app.core import jobs as J
    from app.ui.pages import ReviewPage
    app = QApplication.instance() or QApplication([])
    p = ReviewPage(SimpleNamespace(settings=Settings())); p.resize(1300, 900); p.show()

    def job(i):
        return {"id": f"j{i}", "state": J.READY, "remote_user": "", "original_name": f"Artist - Track {i}.mp3", "message": "",
                "staged_path": "", "final_path": "", "source_kind": "manual", "progress": 100}

    def analysis(n):
        checks = [{"id": f"c{k}", "title": f"Check {k}", "status": "PASS", "message": "fine"} for k in range(n)]
        return {"overall_status": "PASS", "checks": checks, "decode": {"decoded_s": 40}, "decode_ok": True, "cutoff_hz": 20000,
                "facts": {"container": "mp3", "bitrate_kbps": 320, "sample_rate_hz": 44100, "duration_s": 40, "channels": 2,
                          "tags": {}}}

    p.show_job(job(1), analysis(5)); app.processEvents()
    host = p.checks.parentWidget()
    p.show_job(job(2), analysis(2))                        # no event loop in between: what the next paint would show
    in_layout = {p.checks.itemAt(i).widget() for i in range(p.checks.count())} - {None}
    stale = [w for w in host.findChildren(QWidget) if w.parentWidget() is host and w.isVisible() and w not in in_layout]
    assert stale == [], f"{len(stale)} old rows still visible"
    p.close()


def test_ready_list_highlights_the_open_track(window_with_jobs=None):
    """Opening a track highlights that row in the Ready list (it used to highlight the previous one)."""
    import os, tempfile, pathlib
    from PySide6.QtWidgets import QApplication
    from app.core import jobs as J
    app = QApplication.instance() or QApplication([])
    tmp = pathlib.Path(tempfile.mkdtemp()); os.environ["PROJECT_ARCHIVE_DATA"] = str(tmp / "data")
    from app.config import Settings
    from app.core.credentials import CredentialStore
    from app.core.service import ArchiveService
    from app.core.slskd_manager import SlskdManager
    from app.ui.main_window import MainWindow
    mgr = SlskdManager(Settings(), creds=CredentialStore(tmp / "s.json", use_keyring=False), instance_dir=tmp / "c", binary_dir=None)
    svc = ArchiveService(tmp / "data" / "a.db", manager=mgr)
    s = svc.settings; s.setup_done = True; s.tour_done = True; svc.save_settings(s)
    svc.accounts.sign_up("T", "t@example.com", "correct-horse-battery")
    for i in range(3):
        svc.db.insert_job(id=f"j{i}", state=J.READY, original_name=f"Artist - Track {i}.mp3", source_kind="manual",
                          created_at=f"2026-11-07T00:00:0{i}+00:00")
    w = MainWindow(svc); w.resize(1300, 800); w.show(); app.processEvents()
    for jid in ("j0", "j2", "j1"):
        w._open_job(jid); app.processEvents()
        lit = [w.review.rail.itemAt(i).widget().property("job_id") for i in range(w.review.rail.count())
               if w.review.rail.itemAt(i).widget() is not None and w.review.rail.itemAt(i).widget().property("selected") == "true"]
        assert lit == [jid], (jid, lit)
    w.close()
