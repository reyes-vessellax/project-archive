"""The first-run tour points at real controls (a renamed widget would leave a step pointing at nothing), it covers
every page in the sidebar, and Help & FAQ has its guide to open."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_every_tour_step_finds_its_control(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QWidget
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PROJECT_ARCHIVE_DATA", str(tmp_path / "data"))
    from app.config import Settings
    from app.core.credentials import CredentialStore
    from app.core.service import ArchiveService
    from app.core.slskd_manager import SlskdManager
    from app.ui.main_window import GUIDE_PDF, MainWindow
    from app.ui.tour import default_steps
    mgr = SlskdManager(Settings(), creds=CredentialStore(tmp_path / "s.json", use_keyring=False),
                       instance_dir=tmp_path / "c", binary_dir=None)
    svc = ArchiveService(tmp_path / "a.db", manager=mgr)
    s = svc.settings; s.setup_done = True; s.tour_done = True; svc.save_settings(s)
    svc.accounts.sign_up("T", "t@example.com", "correct-horse-battery")
    w = MainWindow(svc)
    steps = default_steps()
    for st in steps:
        if not st.target:
            continue
        obj = w
        for part in st.target.split("."):
            obj = obj.get(part) if isinstance(obj, dict) else getattr(obj, part, None)
        if st.target.startswith("discover.rows."):
            continue                                      # rows exist once Discover has filled in
        assert isinstance(obj, QWidget), st.target
    covered = {st.target.split(".")[-1] for st in steps}
    for page in ("search", "wishlist", "library", "batch"):
        assert page in covered, f"the tour never shows {page}"
    assert GUIDE_PDF.exists()
    w.close()
