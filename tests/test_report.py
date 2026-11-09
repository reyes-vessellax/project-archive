"""Send a report (roadmap #9): one zip with logs, settings without secrets, and the user's note."""
from __future__ import annotations

import json
import zipfile

from app.core import report


def test_zip_has_logs_note_and_no_secrets(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("start\nlogin password=hunter2 ok\nheader X-API-Key: abc123\n", encoding="utf-8")
    out = report.build(tmp_path / "reports", {"app.log": log, "engine.log": tmp_path / "missing.log"},
                       {"slskd_api_key": "abc123", "theme": "dark", "soulseek_password": ""}, note="Search froze")
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert names == {"about.json", "settings.json", "note.txt", "app.log"}
        text = z.read("app.log").decode()
        assert "hunter2" not in text and "abc123" not in text and "start" in text
        st = json.loads(z.read("settings.json"))
        assert st["slskd_api_key"] == "••••" and st["theme"] == "dark"
        assert z.read("note.txt").decode().strip() == "Search froze"
        assert "app_version" in json.loads(z.read("about.json"))


def test_long_logs_keep_their_end(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "TAIL_BYTES", 10)
    log = tmp_path / "app.log"; log.write_text("x" * 100 + "THE END", encoding="utf-8")
    assert report._tail(log).endswith("THE END") and len(report._tail(log)) == 10


def test_service_report(service):
    p = service.make_report("hello")
    assert p.exists() and p.suffix == ".zip"
