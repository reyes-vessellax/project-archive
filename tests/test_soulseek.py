"""Soulseek flow through a fake slskd: search -> pick -> download into quarantine -> check -> decide.

No Soulseek network access anywhere in these tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.base import Candidate, ConnectorError
from app.adapters.slskd_adapter import SlskdAdapter, remote_basename, remote_folder
from app.core import jobs as J
from app.core.service import ActionBlocked

from .conftest import needs_ffmpeg
from .fake_slskd import API_KEY, FakeSlskd

pytestmark = needs_ffmpeg

REMOTE_GOOD = r"@@peer\Music\Compilation Vol 2\Artist - Real Track.mp3"
REMOTE_LOW = r"@@peer\Music\Compilation Vol 2\Artist - Low Track.mp3"
REMOTE_BAD = r"@@peer\Music\Bootlegs\Artist - Cut Off Track.mp3"


@pytest.fixture
def slskd(tmp_path, fixtures):
    dl = tmp_path / "slskd-downloads"
    dl.mkdir()
    fake = FakeSlskd(dl, {REMOTE_GOOD: fixtures["mp3_320"], REMOTE_LOW: fixtures["mp3_192"],
                          REMOTE_BAD: fixtures["trunc_mp3"]})
    fake.url = fake.start()
    yield fake
    fake.stop()


@pytest.fixture
def connected(service, slskd):
    s = service.settings
    s.use_own_slskd = True                      # "Advanced: use my own slskd" pointed at the fake
    s.slskd_url, s.slskd_api_key, s.slskd_downloads_dir = slskd.url, API_KEY, str(slskd.downloads_dir)
    service.save_settings(s)
    return service


def search_all(svc, query: str):
    res = svc.search(query)
    return svc.search_results(res.search_id)


def library_files(svc):
    lib = Path(svc.settings.library_dir)
    return sorted(p.name for p in lib.iterdir()) if lib.exists() else []


# adapter ------------------------------------------------------------------------------
def test_remote_path_helpers():
    assert remote_basename(REMOTE_GOOD) == "Artist - Real Track.mp3"
    assert remote_folder(REMOTE_GOOD) == "Compilation Vol 2"
    assert remote_basename("plain.mp3") == "plain.mp3"


def test_plain_http_only_to_localhost():
    with pytest.raises(ConnectorError):
        SlskdAdapter("http://192.168.1.50:5030", "k", "")
    SlskdAdapter("http://localhost:5030", "k", "")                   # fine
    SlskdAdapter("https://slskd.example.net", "k", "")              # fine over TLS


def test_health_and_bad_key(slskd):
    good = SlskdAdapter(slskd.url, API_KEY, str(slskd.downloads_dir))
    st = good.health_check()
    assert st.available and st.logged_in and st.username == "dj_test"
    bad = SlskdAdapter(slskd.url, "wrong", str(slskd.downloads_dir))
    st = bad.health_check()
    assert not st.available and "API key" in st.message


def test_client_not_running():
    a = SlskdAdapter("http://127.0.0.1:1", "k", "")
    st = a.health_check()
    assert not st.available and "running" in st.message.lower()


def test_search_returns_normalised_candidates(slskd):
    a = SlskdAdapter(slskd.url, API_KEY, str(slskd.downloads_dir))
    res = a.search_results(a.search("artist track").search_id)
    assert res.finished and len(res.candidates) == 3
    c = next(c for c in res.candidates if c.remote_path == REMOTE_GOOD)
    assert c.user == "peer_a" and c.display_name == "Artist - Real Track.mp3" and c.folder == "Compilation Vol 2"
    assert c.bitrate_kbps == 320 and c.free_slot and c.extension == "mp3" and c.size > 0


def test_locate_download_by_name_and_size(slskd, fixtures):
    a = SlskdAdapter(slskd.url, API_KEY, str(slskd.downloads_dir))
    decoy = slskd.downloads_dir / "Other" ; decoy.mkdir()
    (decoy / "Artist - Real Track.mp3").write_bytes(b"wrong size")
    assert a.locate_download(REMOTE_GOOD, fixtures["mp3_320"].stat().st_size) is None
    real = slskd.downloads_dir / "Compilation Vol 2"; real.mkdir()
    (real / "Artist - Real Track.mp3").write_bytes(fixtures["mp3_320"].read_bytes())
    assert a.locate_download(REMOTE_GOOD, fixtures["mp3_320"].stat().st_size) == real / "Artist - Real Track.mp3"


# service flow ------------------------------------------------------------------------------
def test_local_mode_when_no_key(service):
    st = service.connector_status()
    assert not st.available and "Local mode" in st.message
    with pytest.raises(ActionBlocked):
        service.search("anything")


def test_search_filters_to_accepted_formats(connected, slskd, fixtures):
    slskd.library[r"@@peer\Music\notes.txt"] = fixtures["mp3_320"]       # a peer sharing non-audio
    res = search_all(connected, "music")
    assert all(c.extension == "mp3" for c in res.candidates)


def test_full_flow_pass_then_download_to_library(connected, slskd, fixtures):
    res = search_all(connected, "real track")
    cand = res.candidates[0]
    job = connected.request_download(cand)
    assert job["state"] == J.QUEUED and job["remote_user"] == "peer_a"

    staged = connected.poll_downloads()                       # fake finishes on first poll
    assert len(staged) == 1 and staged[0]["state"] == J.STAGING
    staged_path = Path(staged[0]["staged_path"])
    assert staged_path.is_file()
    assert not any(slskd.downloads_dir.rglob("*.mp3"))        # MOVED out of slskd's folder, not copied
    assert slskd.downloads_dir.is_dir()                       # ...but the downloads root itself is kept
    assert library_files(connected) == []                     # nothing reached the library yet

    a = connected.analyze(job["id"])
    assert a["overall_status"] == "PASS"
    target = connected.promote(job["id"])
    assert target.name == "Artist - Real Track.mp3" and target.exists()
    assert not staged_path.exists()
    assert connected.db.job(job["id"])["state"] == J.PROMOTED


def test_delete_leaves_nothing_on_disk(connected, slskd):
    cand = next(c for c in search_all(connected, "cut off").candidates)
    job = connected.request_download(cand)
    staged = connected.poll_downloads()[0]
    a = connected.analyze(job["id"])
    assert a["overall_status"] == "FAIL"
    with pytest.raises(ActionBlocked):
        connected.promote(job["id"], override_warning=True)   # FAIL can never be downloaded
    connected.reject(job["id"])
    assert not Path(staged["staged_path"]).exists()
    assert not any(slskd.downloads_dir.rglob("*.mp3"))
    assert library_files(connected) == []
    assert connected.db.job(job["id"])["state"] == J.REJECTED


def test_warn_needs_download_anyway(connected):
    cand = next(c for c in search_all(connected, "low track").candidates)
    job = connected.request_download(cand)
    connected.poll_downloads()
    assert connected.analyze(job["id"])["overall_status"] == "WARN"
    with pytest.raises(ActionBlocked):
        connected.promote(job["id"])
    connected.promote(job["id"], override_warning=True)
    assert connected.db.job(job["id"])["disposition"] == "promoted_override"


def test_progress_and_cancel(connected, slskd):
    slskd.auto_complete = False
    cand = next(c for c in search_all(connected, "real track").candidates)
    job = connected.request_download(cand)
    assert connected.poll_downloads() == []
    j = connected.db.job(job["id"])
    assert j["state"] == J.QUEUED and j["progress"] == 42.0 and j["message"] == "InProgress"
    with pytest.raises(ActionBlocked):
        connected.reject(job["id"])                           # can't delete what hasn't arrived
    connected.cancel(job["id"])
    assert connected.db.job(job["id"])["state"] == J.CANCELLED
    assert slskd.transfers[j["transfer_id"]]["state"] == "Completed, Cancelled"


def test_failed_download_becomes_error(connected, slskd):
    slskd.fail_next_download = True
    cand = next(c for c in search_all(connected, "real track").candidates)
    job = connected.request_download(cand)
    assert connected.poll_downloads() == []
    j = connected.db.job(job["id"])
    assert j["state"] == J.ERROR and "Errored" in j["message"]
    connected.reject(job["id"])                               # user can clear it from the queue


def test_same_file_not_queued_twice(connected):
    cand = next(c for c in search_all(connected, "real track").candidates)
    connected.request_download(cand)
    with pytest.raises(ActionBlocked):
        connected.request_download(cand)


def test_oversize_result_blocked(connected):
    cand = Candidate(source_kind="soulseek", user="peer_a", remote_path=REMOTE_GOOD, size=10 ** 12,
                     display_name="huge.mp3", extension="mp3")
    with pytest.raises(ActionBlocked):
        connected.request_download(cand)


def test_remote_name_is_sanitised(connected, slskd, fixtures):
    evil = r"@@peer\Music\..\..\CON.mp3"
    slskd.library[evil] = fixtures["mp3_320"]
    cand = Candidate(source_kind="soulseek", user="peer_a", remote_path=evil, size=fixtures["mp3_320"].stat().st_size,
                     display_name=remote_basename(evil), extension="mp3")
    job = connected.request_download(cand)
    staged = connected.poll_downloads()[0]
    p = Path(staged["staged_path"])
    assert p.name == "_CON.mp3"
    assert p.parent.parent == connected.settings.staging_root()


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3
    from app.storage.db import Database
    db_path = tmp_path / "old.db"
    con = sqlite3.connect(db_path)
    con.execute("""CREATE TABLE jobs (id TEXT PRIMARY KEY, source_kind TEXT NOT NULL, source_path TEXT,
                   source_size INTEGER, source_mtime REAL, original_name TEXT NOT NULL, staged_path TEXT,
                   state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT,
                   final_path TEXT, disposition TEXT, message TEXT)""")
    con.commit(); con.close()
    db = Database(db_path)
    db.insert_job(id="x", source_kind="soulseek", original_name="a.mp3", state="QUEUED", remote_user="u",
                  remote_path="p", remote_size=1, transfer_id="t", progress=0.5)
    assert db.job("x")["transfer_id"] == "t"
    db.close()
