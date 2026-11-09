"""Discover only offers records someone is sharing right now, in a good, previewable copy."""
from __future__ import annotations

import pytest

from app.adapters.base import Candidate, SearchResult
from app.core import discover_avail as DA
from app.core.discover import Release


def cand(user, name, ext="flac", kbps=None, free=True, q=0, locked=False):
    return Candidate("soulseek", user, f"@@x\\{name}.{ext}", 30_000_000, display_name=f"{name}.{ext}", extension=ext,
                     bitrate_kbps=kbps, free_slot=free, queue_length=q, locked=locked,
                     artist=name.split(" - ")[0], title=name.split(" - ")[1])


class FakeSvc:
    def __init__(self, results: dict):
        self.results, self.asked, self.adapter = results, [], object()
        self.search_budget = None

        class S: mp3_min_kbps = 320
        self.settings = S()

    def search(self, q, timeout_s=0, check_login=True):
        self.asked.append(q); return SearchResult(q, q, False)

    def search_status(self, sid):
        return True, 1, 1, ""

    def search_results(self, sid):
        return SearchResult(sid, sid, True, self.results.get(sid, []))

    def stop_search(self, sid): pass

    def forget_search(self, sid): pass


class MemDB:
    def __init__(self): self.d = {}
    def cache_get(self, k): return self.d.get(k)
    def cache_put(self, k, v):
        from datetime import datetime, timezone
        self.d[k] = (v, datetime.now(timezone.utc).isoformat())


class FakeEngine:
    def __init__(self): self.db = MemDB(); self.details_asked = 0

    class Lib:
        def owns(self, a, t): return t == "Owned Track"

    def library(self): return self.Lib()

    def release(self, rid):
        self.details_asked += 1
        return {"tracks": [("A", "Acid Tracks", ""), ("B", "Phuture Jacks", "")], "styles": []}


def test_ready_good_copy_is_found_and_chosen():
    good = cand("trax_head", "Phuture - Acid Tracks", "flac")
    queued = cand("slow", "Phuture - Acid Tracks", "wav", free=False, q=5)
    low = cand("lofi", "Phuture - Acid Tracks", "mp3", kbps=128)
    svc = FakeSvc({"Phuture Acid Tracks": [queued, low, good]})
    f = DA.verify(FakeEngine(), svc, Release(1, "Acid Tracks", "Phuture", 1987), "Trax Records")
    assert f.best is good and f.alts == [good] and f.track == "Acid Tracks"
    assert svc.asked == ["Phuture Acid Tracks"]                                # the title first: no Discogs call


def test_found_and_missed_are_remembered():
    good = cand("trax_head", "Phuture - Acid Tracks", "flac")
    eng, svc = FakeEngine(), FakeSvc({"Phuture Acid Tracks": [good]})
    rel = Release(1, "Acid Tracks", "Phuture", 1987)
    DA.verify(eng, svc, rel, "Trax"); svc.asked.clear()
    again = DA.verify(eng, svc, rel, "Trax")
    assert svc.asked == [] and again.best.user == "trax_head"                 # instant the second time
    miss = Release(2, "Nobody Has It", "Phuture", 1987)
    svc.results = {}                                                           # nobody shares anything from it
    assert DA.verify(eng, svc, miss, "Trax") is None
    n = len(svc.asked)
    assert DA.verify(eng, svc, miss, "Trax") is None and len(svc.asked) == n  # a known miss isn't searched again


def test_hi_res_reported_copies_are_not_offered():
    hi = cand("audiophile", "Phuture - Acid Tracks", "flac"); hi.sample_rate_hz = 96000
    assert DA.verify(FakeEngine(), FakeSvc({"Phuture Acid Tracks": [hi]}), Release(1, "Acid Tracks", "Phuture", 1987), "T") is None


def test_not_shared_right_now_is_not_shown():
    svc = FakeSvc({"Phuture Acid Tracks": [cand("slow", "Phuture - Acid Tracks", "wav", free=False, q=5)],
                   "Phuture Phuture Jacks": [cand("x", "Phuture - Phuture Jacks", "mp3", kbps=192)]})
    assert DA.verify(FakeEngine(), svc, Release(1, "Acid Tracks", "Phuture", 1987), "Trax") is None
    assert svc.asked == ["Phuture Acid Tracks", "Phuture Phuture Jacks"]        # A-side, then the next track


def test_owned_records_and_various_are_skipped():
    svc = FakeSvc({})

    assert DA.verify(FakeEngine(), svc, Release(1, "Owned Track", "Someone", 1990), "L") is None
    assert DA.verify(FakeEngine(), svc, Release(2, "Hits", "Various", 1990), "L") is None
    assert svc.asked == []                                                     # no searches wasted


def test_needs_the_network():
    svc = FakeSvc({}); svc.adapter = None
    with pytest.raises(DA.NotConnected):
        DA.verify(FakeEngine(), svc, Release(1, "Acid Tracks", "Phuture", 1987), "Trax")


def test_titles_and_artists():
    assert DA.first_artist("Jack Master Funk* / Farley") == "Jack Master Funk"
    r = Release(1, "Untitled EP", "X", 1990)
    assert DA.titles_to_try(r, {"tracks": [("A", "Get Up (Original Mix)", ""), ("B", "Get Up (Original Mix)", "")]}) == ["Get Up"]
    assert DA.titles_to_try(r, {"tracks": []}) == ["Untitled EP"]
