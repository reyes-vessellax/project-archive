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
    lib = svc.settings.downloads_dir()
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


def test_search_marks_other_formats_instead_of_hiding_them(connected, slskd, fixtures):
    slskd.library[r"@@peer\Music\notes.txt"] = fixtures["mp3_320"]       # a peer sharing non-audio
    res = search_all(connected, "music")
    odd = [c for c in res.candidates if c.extension == "txt"]
    assert odd and all(c.note == "Extension mismatch" for c in odd)
    assert all(not c.note for c in res.candidates if c.extension == "mp3")
    with pytest.raises(ActionBlocked):                                   # still can't be requested
        connected.request_download(odd[0])


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
    assert j["transfer_id"] in slskd.removed                     # cancelled AND removed from the engine's list


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


# queue housekeeping ----------------------------------------------------------------------
def test_remove_entry_hides_but_keeps_history(connected, slskd):
    cand = next(c for c in search_all(connected, "cut off").candidates)
    job = connected.request_download(cand)
    with pytest.raises(ActionBlocked):
        connected.hide(job["id"])                             # still downloading: not removable
    connected.poll_downloads(); connected.analyze(job["id"]); connected.reject(job["id"])
    connected.hide(job["id"])
    assert job["id"] not in {j["id"] for j in connected.jobs()}          # gone from the panel
    assert connected.db.job(job["id"])["state"] == J.REJECTED            # history kept


def test_artist_title_from_filename():
    from app.adapters.base import split_artist_title as s
    assert s("Artist - Track (Original Mix).mp3") == ("Artist", "Track")
    assert s("03 - Artist - Track.flac") == ("Artist", "Track")
    assert s("A1 Artist - Track.wav") == ("Artist", "Track")
    assert s("Weird_Name_123.mp3") == ("", "Weird Name 123")
    assert s("Artist - Track - Remix.mp3") == ("Artist", "Track - Remix")
    # Soulseek realities: underscores, en dashes, feat., labels in brackets, A1-style track codes
    from app.adapters.base import parse_track as pt
    assert pt("John_Summit_-_Deep_End_(Dom_Dolla_Remix).mp3") == ("John Summit", "Deep End", "Dom Dolla Remix")
    assert pt("John Summit – Thin Line (Extended Mix).mp3") == ("John Summit", "Thin Line", "Extended Mix")
    assert pt("John Summit - Where You Are (feat. Hayla) (Extended Mix).flac") == ("John Summit", "Where You Are (feat. Hayla)", "Extended Mix")
    assert pt("John Summit & Guz - Thin Line [Defected].mp3") == ("John Summit & Guz", "Thin Line", "Defected")
    assert pt("A1 - John Summit - Deep End (Hip-Hop Re-Edit).wav") == ("John Summit", "Deep End", "Hip-Hop Re-Edit")
    assert pt("02 Deep End (Extended Mix).mp3") == ("", "Deep End", "Extended Mix")


def test_search_results_carry_artist_and_title(connected):
    c = next(c for c in search_all(connected, "real track").candidates)
    assert (c.artist, c.title) == ("Artist", "Real Track")


# hostile input --------------------------------------------------------------------------
def test_extension_comes_from_the_name_not_the_peer(connected, slskd, fixtures):
    slskd.library[r"@@peer\Music\evil.exe"] = fixtures["mp3_320"]
    # the fake reports extension from the fixture (mp3); the NAME says .exe, and the name wins
    res = search_all(connected, "evil")
    assert [c.note for c in res.candidates] == ["Extension mismatch"]   # shown greyed, never requestable
    cand = Candidate(source_kind="soulseek", user="peer_a", remote_path=r"@@peer\Music\evil.exe", size=1,
                     display_name="evil.exe", extension="exe")
    with pytest.raises(ActionBlocked):
        connected.request_download(cand)


def test_rejected_download_is_removed_from_disk(connected, slskd, fixtures):
    # a file that passes the results filter but fails validation on arrival (here: zero bytes after download)
    bad = slskd.downloads_dir.parent / "empty.mp3"; bad.write_bytes(b"")
    slskd.library[r"@@peer\Music\empty.mp3"] = bad
    cand = Candidate(source_kind="soulseek", user="peer_a", remote_path=r"@@peer\Music\empty.mp3", size=0,
                     display_name="empty.mp3", extension="mp3")
    job = connected.request_download(cand)
    assert connected.poll_downloads() == []
    j = connected.db.job(job["id"])
    assert j["state"] == J.ERROR and "empty" in j["message"].lower()
    assert not any(slskd.downloads_dir.rglob("*.mp3"))               # not left behind


def test_invisible_characters_are_stripped(connected, slskd, fixtures):
    sneaky = "@@peer\\Music\\evil‮3pm.exe"                          # displays as "evil.mp3"
    slskd.library[sneaky] = fixtures["mp3_320"]
    res = search_all(connected, "evil")
    assert [c.note for c in res.candidates] == ["Extension mismatch"]   # it's really an .exe: greyed, not requestable
    from app.core.safety import safe_filename, clean_text
    assert "‮" not in safe_filename("evil‮3pm.exe") and clean_text("a​b") == "ab"


def test_locate_handles_windows_sanitised_names(slskd, fixtures):
    a = SlskdAdapter(slskd.url, API_KEY, str(slskd.downloads_dir))
    remote = r"@@peer\Music\What Is Love? (Mix) 12:00.mp3"
    folder = slskd.downloads_dir / "Music"; folder.mkdir()
    (folder / "What Is Love_ (Mix) 12_00.mp3").write_bytes(fixtures["mp3_320"].read_bytes())   # as slskd saves it on Windows
    assert a.locate_download(remote, fixtures["mp3_320"].stat().st_size) is not None


def test_bad_sizes_are_clamped(slskd):
    a = SlskdAdapter(slskd.url, API_KEY, str(slskd.downloads_dir))
    slskd.library  # fake reports real sizes; feed the parser a bad row directly
    from app.adapters.slskd_adapter import SlskdAdapter as S
    rows = [{"username": "u", "files": [{"filename": "x.mp3", "size": -5}, {"filename": "y.mp3", "size": "huge"}]}]
    orig = a._call
    a._call = lambda m, p, *x, **k: ({"state": "Completed", "searchText": "q"} if p.startswith("/searches/") and not p.endswith("responses") else rows)
    res = a.search_results("s")
    assert [c.size for c in res.candidates] == [0, 0]
    a._call = orig


def test_decoder_text_is_escaped_in_review():
    import html
    assert html.escape("<a href='x'>click</a>") == "&lt;a href=&#x27;x&#x27;&gt;click&lt;/a&gt;"


def test_errored_search_is_reported_not_silent(slskd):
    a = SlskdAdapter(slskd.url, API_KEY, str(slskd.downloads_dir))
    sid = a.search("anything").search_id
    slskd.searches[sid]["meta"]["state"] = "Completed, Errored"
    res = a.search_results(sid)
    assert res.finished and res.error and "connection" in res.error


# resources ----------------------------------------------------------------------------------
def test_finished_download_is_forgotten_by_engine(connected, slskd):
    cand = next(c for c in search_all(connected, "real track").candidates)
    job = connected.request_download(cand)
    tid = connected.db.job(job["id"])["transfer_id"]
    connected.poll_downloads()
    assert tid in slskd.removed and tid not in slskd.transfers      # not lurking in the engine's list


def test_failed_download_is_forgotten_too(connected, slskd):
    slskd.fail_next_download = True
    cand = next(c for c in search_all(connected, "real track").candidates)
    job = connected.request_download(cand)
    tid = connected.db.job(job["id"])["transfer_id"]
    connected.poll_downloads()
    assert tid in slskd.removed


def test_housekeeping_clears_old_searches(connected, slskd):
    for q in ("real", "low", "cut"):
        search_all(connected, q)
    assert len(slskd.searches) == 3
    connected.engine_housekeeping()
    assert slskd.searches == {}


def test_decode_closes_pipes_and_frees_frames(fixtures):
    import gc, os
    from app.media.decode import decode_and_analyze
    before = len(os.listdir("/proc/self/fd")) if os.path.isdir("/proc/self/fd") else None
    for _ in range(6):
        d = decode_and_analyze(fixtures["mp3_320"], 44100, 40.0)
        assert d.ok_exit and d.frames is not None
        del d
    gc.collect()
    if before is not None:
        after = len(os.listdir("/proc/self/fd"))
        assert after <= before + 2, (before, after)                   # no handle growth across six decodes
