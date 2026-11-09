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


@needs_ffmpeg
def test_shelf_card_opens_in_place_and_closes(service, fixtures, tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from app.ui.discover_page import DiscoverPage
    app = QApplication.instance() or QApplication([])
    ids = []
    for i in range(6):
        p = tmp_path / f"t{i}.mp3"
        ff("-i", str(fixtures["source_wav"]), "-af", f"volume=-{i}dB", "-c:a", "libmp3lame", "-b:a", "320k", str(p))
        ids.append(_dug(service, p, {"release_id": 100 + i}))
    d = DiscoverPage(service); d.resize(1200, 900); d.show(); d.refresh_shelf(); app.processEvents()
    first = ids[-1]                                                  # newest first
    assert len(d._shelf_cards) == 6, [(service.db.analysis(i) or {}).get("overall_status") for i in ids]
    d._toggle_card(first); app.processEvents()
    drawer = d.shelf_flow._drawer[0].widget()
    card = d._shelf_cards[first]
    assert drawer.isVisible() and drawer.geometry().top() > card.geometry().bottom()   # right under its row
    later = [c for c in d._shelf_cards.values() if c.geometry().top() > card.geometry().top()]
    assert all(c.geometry().top() > drawer.geometry().bottom() for c in later)          # pushes the rest down
    d._toggle_card(first); app.processEvents()
    assert d.shelf_flow._drawer is None                                                  # same card again: closes
    d._toggle_card(ids[0]); d._toggle_card(ids[1]); app.processEvents()
    assert d.shelf_flow._drawer[1] is d._shelf_cards[ids[1]]                             # another: switches
    d.deleteLater(); app.sendPostedEvents(None, QEvent.DeferredDelete)
