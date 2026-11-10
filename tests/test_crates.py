"""Crates: one search per label, ready-now good copies only, one entry per track, remembered."""
from __future__ import annotations

from app.adapters.base import Candidate, SearchResult
from app.core import crates as C


def cand(user, name, ext="flac", kbps=None, free=True, q=0, folder="Dance Mania - DM 012", locked=False, note=""):
    a, t = name.split(" - ", 1)
    return Candidate("soulseek", user, f"@@x\\{folder}\\{name}.{ext}", 60_000_000, display_name=f"{name}.{ext}",
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



def test_phrase_and_not_dance_paths():
    rock = cand("x", "Lamb Of God - Redneck", "flac", folder="Live in Chicago\\House of Blues 2004")
    metal = cand("y", "Some Band - Chicago House Party", "flac", folder="Death Metal\\Chicago House Party")
    good = cand("z", "Marshall Jefferson - Move Your Body", "flac", folder="Chicago House Classics Vol 2")
    out = C.build([rock, metal, good], query="Chicago house")
    assert [t.artist for t in out] == ["Marshall Jefferson"]
    trax = cand("a", "Phuture - Acid Tracks", "flac", folder="Trax Records - TX142")
    other = cand("b", "Phuture - Acid Tracks", "flac", folder="Some Compilation")
    assert len(C.build([trax], query="Trax Records")) == 1 and C.build([other], query="Trax Records") == []


def test_non_dance_artists_are_dropped_unknown_kept():
    from tests.test_discover_avail import MemDB
    tracks = C.build([cand("a", "Lamb Of God - Redneck", "flac"), cand("b", "Phuture - Acid Tracks", "flac"),
                      cand("c", "Obscure Producer - White Label Jam", "flac")])
    genres = {"Lamb Of God": ["Rock", "Metal"], "Phuture": ["Electro", "Techno/House"], "Obscure Producer": []}
    asked = []

    def lookup(a):
        asked.append(a); return genres[a]
    db = MemDB()
    kept = C.dance_only(db, tracks, lookup=lookup)
    assert [t.artist for t in kept] == ["Phuture", "Obscure Producer"]
    C.dance_only(db, tracks, lookup=lookup)
    assert len(asked) == 3                                                  # remembered: each artist asked once


def test_plural_folder_names_count():
    t = cand("a", "Dimitri From Paris - Love Train", "flac", folder="Disco Edits 2019")
    assert len(C.build([t], query="Disco edit")) == 1


def test_stricter_dance_rules():
    from app.core.crates import DANCE_CUE, NOT_DANCE
    for ok in ("Tino - Rock Ya Body", "Daft Punk - Da Funk", "Rock The House (Club Mix)", "Garage House Classics"):
        assert not NOT_DANCE.search(ok), ok
    for bad in ("Fleet Foxes - Folk Sessions", "Bach - Prelude in C", "Indie Rock Hits 2009", "Lamb of God - Hard Rock",
                "Chicago Blues Masters"):
        assert NOT_DANCE.search(bad), bad
    prelude_classical = cand("p", "Some Pianist - Prelude No 1", "flac", folder="Prelude")
    prelude_label = cand("q", "Sharon Redd - Beat The Street", "flac", folder="Prelude Records - PRL D 621")
    assert C.build([prelude_classical], query="Prelude Records", kind="label") == []
    assert len(C.build([prelude_label], query="Prelude Records", kind="label")) == 1
    from tests.test_discover_avail import MemDB
    unknown_folk = C.build([cand("u", "Unknown Singer - Lonesome Road", "flac", folder="Field Recordings")])
    unknown_dance = C.build([cand("v", "Unknown DJ - Jack Trax", "flac", folder="Chicago House 12in")])
    kept = C.dance_only(MemDB(), unknown_folk + unknown_dance, lookup=lambda a: [])
    assert [t.artist for t in kept] == ["Unknown DJ"]


def test_club_length_only():
    from app.core.crates import club_length, length_s
    long_mp3 = cand("a", "Marshall Jefferson - Move Your Body", "mp3", 320); long_mp3.length_s = 418
    short = cand("b", "Marshall Jefferson - Move Your Body", "mp3", 320); short.length_s = 200
    radio = cand("c", "Marshall Jefferson - Move Your Body (Radio Edit)", "flac"); radio.length_s = 260
    radio.mix = "Radio Edit"
    wav_unknown = cand("d", "Phuture - Acid Tracks", "wav"); wav_unknown.size = 75_000_000   # ~7 min at CD quality
    tiny_wav = cand("e", "Phuture - Acid Tracks", "wav"); tiny_wav.size = 20_000_000          # ~2 min
    assert club_length(long_mp3) and not club_length(short) and not club_length(radio)
    assert abs(length_s(wav_unknown) - 425) < 5 and club_length(wav_unknown) and not club_length(tiny_wav)
    out = C.build([long_mp3, short, radio])
    assert [t.best.user for t in out] == ["a"]


def test_radio_in_a_name_is_not_a_radio_edit():
    keep = Candidate("soulseek", "u", "p/Radio Slave - Koma Koma.flac", 60_000_000, extension="flac",
                     display_name="Radio Slave - Koma Koma.flac", artist="Radio Slave", title="Koma Koma")
    assert C.club_length(keep)
    for name in ("Track (Radio Edit)", "Track (Radio)", "Track [radio mix]"):
        c = Candidate("soulseek", "u", f"p/{name}.flac", 60_000_000, extension="flac", display_name=name)
        assert not C.club_length(c), name
