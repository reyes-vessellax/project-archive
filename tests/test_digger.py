"""Discover's shelf: only tracks that are downloaded, Good and club-ready; bounded, polite digging."""
from __future__ import annotations

import json

import pytest

from app.core import digger
from app.core import jobs as J
from tests.conftest import ff, needs_ffmpeg


def _dug(service, path, info=None):
    job = service.stage(path)
    service.db.update_job(job["id"], origin="discover", hidden=1,
                          discover_json=json.dumps(info or {"release_id": hash(str(path)) % 10**6, "era": "acid"}))
    service.analyze(job["id"])
    return job["id"]


@needs_ffmpeg
def test_only_good_and_club_ready_tracks_are_on_the_shelf(service, fixtures, tmp_path):
    good = _dug(service, fixtures["mp3_320"])
    f32 = tmp_path / "float.wav"; ff("-i", str(fixtures["source_wav"]), "-c:a", "pcm_f32le", str(f32))
    not_club = _dug(service, f32)
    fake = _dug(service, fixtures["fake_320"])                       # a transcode: not Good
    digger.tidy(service)
    assert [j["id"] for j, _, _ in digger.shelf(service)] == [good]
    assert service.db.job(not_club)["state"] == J.REJECTED and service.db.job(fake)["state"] == J.REJECTED
    assert all(j["id"] != good for j in service.jobs())              # not cluttering the Queue
    assert [j["id"] for j, _, _ in digger.shelf(service, "acid")] == [good] and digger.shelf(service, "detroit") == []


@needs_ffmpeg
def test_take_puts_it_in_the_library(service, fixtures):
    jid = _dug(service, fixtures["mp3_320"])
    target = digger.take(service, jid)
    j = service.db.job(jid)
    assert j["state"] == J.PROMOTED and j["hidden"] == 0 and target.exists() and digger.shelf(service) == []


def test_fill_is_bounded_and_never_repeats(service, monkeypatch):
    from app.adapters.base import Candidate
    from app.core import discover_avail
    from app.core.discover import Release
    asked = []
    rel = Release(42, "Acid Tracks", "Phuture", 1987)
    found = discover_avail.Found(rel, {"tracks": [], "styles": []}, "Trax", "Acid Tracks",
                                 Candidate("soulseek", "u", "p", 1, extension="flac", free_slot=True), [])
    monkeypatch.setattr(discover_avail, "spin_found", lambda *a, **k: found)

    def request(cand, origin="", info=None, playlist=""):
        jid = f"j{len(asked)}"
        service.db.insert_job(id=jid, source_kind="soulseek", original_name="t.flac", state=J.QUEUED,
                              origin=origin, hidden=1, discover_json=json.dumps(info))
        asked.append(info["release_id"])
    monkeypatch.setattr(service, "request_download", request)
    assert digger.fill(service, None, ["Trax"]) == 1 and asked == [42]
    assert digger.fill(service, None, ["Trax"]) == 0                  # same record again: not re-downloaded
    found.release = Release(43, "Other", "Phuture", 1987)
    assert digger.fill(service, None, ["Trax"]) == 1                  # second download in flight
    found.release = Release(44, "Third", "Phuture", 1987)
    assert digger.fill(service, None, ["Trax"]) == 0                  # MAX_INFLIGHT reached: waits
