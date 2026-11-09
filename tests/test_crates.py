"""Crates: one search per label, ready-now good copies only, one entry per track, remembered."""
from __future__ import annotations

from app.adapters.base import Candidate, SearchResult
from app.core import crates as C


def cand(user, name, ext="flac", kbps=None, free=True, q=0, folder="Dance Mania - DM 012", locked=False, note=""):
    a, t = name.split(" - ", 1)
    return Candidate("soulseek", user, f"@@x\\{folder}\\{name}.{ext}", 20_000_000, display_name=f"{name}.{ext}",
                     folder=folder, artist=a, title=t, extension=ext, bitrate_kbps=kbps, free_slot=free, queue_length=q,
                     locked=locked, note=note)


def test_build_keeps_ready_good_copies_one_per_track():
    cs = [cand("a", "DJ Funk - Pump It Up", "mp3", 320), cand("b", "DJ Funk - Pump It Up", "flac"),
          cand("c", "DJ Deeon - Freak Like Me", "mp3", 192),                 # under the quality bar
          cand("d", "Paul Johnson - Feel My M.F. Bass", "wav", free=False, q=4),   # not ready now
          cand("e", "Parris Mitchell - Ghetto Shout Out", "flac", locked=True),    # private
          cand("f", "DJ Milton - Ghetto House", "flac", note="Ad bot"),
          cand("g", "Jammin Gerald - Get On Up", "aiff")]
    out = C.build(cs)
    assert [(t.artist, t.title) for t in out] == [("DJ Funk", "Pump It Up"), ("Jammin Gerald", "Get On Up")]
    pump = out[0]
    assert pump.best.extension == "flac" and len(pump.alts) == 2 and pump.catno == "DM 012"


def test_owned_tracks_are_left_out():
    out = C.build([cand("a", "DJ Funk - Pump It Up", "flac")], owns=lambda a, t: t == "Pump It Up")
    assert out == []


class FakeSvc:
    def __init__(self, cands):
        from tests.test_discover_avail import MemDB
        self.db, self.adapter, self.search_budget, self.asked, self.cands = MemDB(), object(), None, [], cands

        class S: mp3_min_kbps = 320
        self.settings = S()

    def search(self, q, timeout_s=0, check_login=True): self.asked.append(q); return SearchResult(q, q, False)
    def search_status(self, sid): return True, 1, len(self.cands), ""
    def search_results(self, sid): return SearchResult(sid, sid, True, self.cands)
    def stop_search(self, sid): pass
    def forget_search(self, sid): pass


def test_one_search_fills_the_crate_and_is_remembered():
    svc = FakeSvc([cand("a", "DJ Funk - Pump It Up", "flac"), cand("b", "Jammin Gerald - Get On Up", "aiff")])
    first = C.crate(svc, "Dance Mania")
    assert len(first) == 2 and svc.asked == ["Dance Mania"]
    again = C.crate(svc, "dance mania")
    assert [t.title for t in again] == ["Pump It Up", "Get On Up"] and svc.asked == ["Dance Mania"]   # instant


def test_offline_gives_none():
    svc = FakeSvc([]); svc.adapter = None
    assert C.crate(svc, "Trax Records") is None
