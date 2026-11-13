"""Discover rows are checked against MusicBrainz / Deezer, never trusted from a folder name."""
from __future__ import annotations

from app.core import rows as R
from tests.test_crates import FakeSvc, cand


class FakeEngine:
    """Discover._get stand-in: URL substring -> JSON."""
    def __init__(self, answers):
        from tests.test_discover_avail import MemDB
        self.answers, self.asked, self.db = answers, [], MemDB()

    def _get(self, host, url, days=7):
        self.asked.append(url)
        for k, v in self.answers.items():
            if k in url:
                return v
        return {}


def mb_artist(name, *tags, disamb=""):
    return {"artists": [{"name": name, "score": 100, "disambiguation": disamb, "tags": [{"name": t} for t in tags]}]}


def test_style_row_keeps_confirmed_drops_known_other_and_asks_deezer_for_unknown():
    svc = FakeSvc([cand("a", "Kerri Chandler - Rain", folder="Deep House Classics"),
                   cand("b", "Some Band - Deep House Of Pain", folder="Deep House Of Pain"),
                   cand("c", "Unknown Guy - Night Dub", folder="deep house edits")])
    eng = FakeEngine({"Kerri%20Chandler": mb_artist("Kerri Chandler", "deep house", "garage house"),
                      "Some%20Band": mb_artist("Some Band", "rock", "alternative")})
    out = R.style_row(svc, eng, "Deep house", deezer=lambda a: [])
    names = [t.artist for t in out]
    assert "Kerri Chandler" in names and "Some Band" not in names
    assert "Unknown Guy" in names                         # MusicBrainz doesn't know him; "dub"/"edits" in the path
    assert names[0] == "Kerri Chandler"                   # confirmed first


def test_disco_styles_accept_disco_artists():
    eng = FakeEngine({"Larry": mb_artist("Larry Levan", "disco", "boogie")})
    assert R.artist_fits(eng, "Larry Levan", "Disco edit") is True
    assert R.artist_fits(eng, "Larry Levan feat. Someone", "Disco edit") is True     # main artist is looked up
    assert R.artist_fits(FakeEngine({}), "Nobody", "Deep house") is None


def test_artist_crate_only_keeps_that_artists_tracks():
    svc = FakeSvc([cand("a", "Blaze - Lovelee Dae", folder="Blaze"),
                   cand("b", "Blaze Ya Dead Homie - Hatchet", folder="Blaze"),
                   cand("c", "Blaze feat. Palmer Brown - My Beat", folder="Blaze")])
    out = R.artist_crate(svc, "Blaze")
    assert sorted(t.title for t in out) == ["Lovelee Dae", "My Beat"]


def test_era_row_puts_records_from_the_era_first():
    era = {"key": "chicago", "name": "Chicago jack", "years": "1984–1990", "artists": ["Fast Eddie"]}
    svc = FakeSvc([cand("b", "Fast Eddie - New Thing 2019", folder="Fast Eddie"),
                   cand("c", "Fast Eddie - Unknown Track", folder="Fast Eddie"),
                   cand("a", "Fast Eddie - Yo Yo Get Funky", folder="Fast Eddie")])
    fe = [{"name": "Fast Eddie"}]
    eng = FakeEngine({"recording?": {"recordings": [
        {"title": "Yo Yo Get Funky", "first-release-date": "1988-05", "artist-credit": fe},
        {"title": "New Thing 2019", "first-release-date": "2019", "artist-credit": fe}]}})
    out = R.era_row(svc, eng, era, day=1, per_day=1)
    assert out[0].title == "Yo Yo Get Funky" and len(out) == 3     # in-era first; patchy dates never drop a track
    assert R.era_span("2010–now") == (2010, 9999)


def test_for_you_uses_related_artists_not_already_owned(service):
    import json, uuid
    from app.core import jobs as J
    db = service.db
    for a in ("Fast Eddie", "Fast Eddie", "Tyree"):
        jid = str(uuid.uuid4())
        db.insert_job(id=jid, source_kind="manual", original_name=f"{a} - x.mp3", state=J.PROMOTED,
                      created_at="2026-11-01T00:00:00+00:00", updated_at="2026-11-01T00:00:00+00:00")
        db._con.execute("INSERT INTO analyses (job_id, overall_status, analysis_json) VALUES (?,?,?)",
                        (jid, "PASS", json.dumps({"meta": {"artist": a}})))
    db._con.commit()
    assert R.library_artists(db)[0] == "Fast Eddie"

    def fetch(url, timeout=6.0):
        if "search/artist" in url and "fast" in url:
            return json.dumps({"data": [{"id": 1, "name": "Fast Eddie"}]}).encode()
        if "search/artist" in url and "tyree" in url:
            return json.dumps({"data": [{"id": 2, "name": "Tyree"}]}).encode()
        if "/artist/1/related" in url:
            return json.dumps({"data": [{"name": "Tyree"}, {"name": "Ralphi Rosario"}, {"name": "DSK"}]}).encode()
        return json.dumps({"data": []}).encode()
    picked, because = R.for_you_artists(db, day=5, fetch=fetch)
    assert "Tyree" not in picked                          # already in the library
    assert set(picked) <= {"Ralphi Rosario", "DSK"} and picked and because == ["Fast Eddie"]


def test_musicbrainz_no_is_overruled_only_by_a_deezer_dance_genre():
    svc = FakeSvc([cand("a", "Fisher - Losing It", folder="Tech House 2018"),
                   cand("b", "Taylor Swift - Shake It Off", folder="tech house remixes")])
    eng = FakeEngine({"Fisher": mb_artist("Fisher", disamb="American pop/rock duo"),
                      "Taylor": mb_artist("Taylor Swift", "pop", "country")})
    genres = {"Fisher": ["Dance", "Electro"], "Taylor Swift": ["Pop"]}
    out = R.style_row(svc, eng, "Tech house", deezer=lambda a: genres.get(a, []))
    assert [t.artist for t in out] == ["Fisher"]


def test_famous_namesake_is_vetoed_by_deezer():
    svc = FakeSvc([cand("a", "Drake - Hotline Bling", folder="Deep House Bootlegs")])
    eng = FakeEngine({"Drake": mb_artist("Drake", "deep house")})               # an obscure house DJ called Drake
    assert R.style_row(svc, eng, "Deep house", deezer=lambda a: ["Rap/Hip Hop"]) == []


def test_background_searches_leave_a_slot_for_the_user():
    from app.core.searching import Budget
    b = Budget(burst=2, refill_s=1000)
    assert b.take_background()                       # 2 free: background may take one
    assert not b.take_background(cancelled=lambda: True)   # 1 left: kept for the user
    b.take()                                         # the user's search goes straight through


def test_artists_known_for_the_style_come_first():
    svc = FakeSvc([cand("a", "Larry Heard - Housey", folder="Acid House Trax"),
                   cand("b", "Phuture - Acid Tracks", folder="Acid House Trax")])
    eng = FakeEngine({"Larry": mb_artist("Larry Heard", "house", "deep house"),
                      "Phuture": mb_artist("Phuture", "acid house", "chicago house")})
    out = R.style_row(svc, eng, "Acid house", deezer=lambda a: [])
    assert [t.artist for t in out] == ["Phuture", "Larry Heard"]


def test_each_song_once_and_no_artist_takes_over():
    from app.core.crates import CrateTrack
    from app.adapters.base import Candidate
    def t(a, title, mix=""):
        c = Candidate("soulseek", "u", f"p/{a}/{title}{mix}", 1, extension="flac", free_slot=True)
        return CrateTrack(a, title, mix, c, [c])
    rows = [t("Ron Trent", "Altered States"), t("Ron Trent", "Altered States", "Dub"), t("Ron Trent", "Morning Factory"),
            t("Ron Trent", "Foundation"), t("Ron Trent", "Space Ritual"), t("Larry Heard", "Mystery Of Love")]
    out = R.tidy(rows, per_artist=3)
    assert [x.title for x in out] == ["Altered States", "Morning Factory", "Foundation", "Mystery Of Love"]


def test_a_search_we_stopped_early_is_still_remembered():
    svc = FakeSvc([cand("a", "Blaze - Lovelee Dae", folder="Blaze")])
    orig = svc.search_results
    def stopped(sid):
        r = orig(sid); r.error = "The search was cancelled."; return r
    svc.search_results = stopped
    assert R.artist_crate(svc, "Blaze")
    from app.core import crates as C
    assert C.remembered(svc.db, "by Blaze")


def test_track_numbers_and_punctuation_dont_make_a_song_twice():
    """Reyes: "definitely duplicate tracks". Real rows had '01. Mic Newman' and '03. Mic Newman' as two artists."""
    from app.core.crates import CrateTrack, build, clean_part
    from app.adapters.base import Candidate
    assert clean_part("01. Mic Newman") == "Mic Newman" and clean_part("A1 - Move Your Body") == "Move Your Body"
    assert clean_part("07 - Prescription + Oxymoron") == "Prescription + Oxymoron" and clean_part("808 State") == "808 State"
    def t(a, title, mix=""):
        c = Candidate("soulseek", "u", f"p/{a}/{title}{mix}", 1, extension="flac", free_slot=True)
        return CrateTrack(a, title, mix, c, [c])
    rows = [t("01. Mic Newman", "The Fidelity"), t("03. Mic Newman", "The Fidelity"),
            t("Stevie Wonder", "01 - Too High"), t("Stevie Wonder", "Too High"),
            t("ScHoolboy Q", "Prescription + Oxymoron"), t("ScHoolboy Q", "07 - Prescription Oxymoron"),
            t("Kyodai", "Mi Rumba", "Genius Of Time Mix"), t("Kyodai", "Mi Rumba", "Genius Of Time Remix")]
    assert len(R.tidy(rows)) == 4
    c1 = Candidate("soulseek", "a", "p/x/01. Mic Newman - The Fidelity.flac", 60_000_000, extension="flac", free_slot=True,
                   display_name="01. Mic Newman - The Fidelity.flac", artist="01. Mic Newman", title="The Fidelity")
    c2 = Candidate("soulseek", "b", "p/y/03. Mic Newman - The Fidelity.flac", 60_000_000, extension="flac", free_slot=True,
                   display_name="03. Mic Newman - The Fidelity.flac", artist="03. Mic Newman", title="The Fidelity")
    out = build([c1, c2])
    assert len(out) == 1 and out[0].artist == "Mic Newman" and len(out[0].alts) == 2   # one entry, two copies


def test_spellings_quotes_and_bracketed_numbers_dont_make_a_song_twice():
    """Reyes: "still hella duplicates in discover and for you". Real For you row: seven copies of one Farley song."""
    from app.core.crates import CrateTrack
    from app.adapters.base import Candidate
    def t(a, title, mix=""):
        c = Candidate("soulseek", "u", f"p/{a}/{title}{mix}", 1, extension="flac", free_slot=True)
        return CrateTrack(a, title, mix, c, [c])
    farley = [t("Farley Jackmaster Funk", "Love cant turn around"), t("Farley Jackmaster Funk", "Love Can't Turn Around"),
              t("Farley Jackmaster Funk", "Love Can-t Turn Around"),
              t("Farley 'Jackmaster' Funk & Jessie Saunders feat. Daryl Pandy", "Love Can't Turn Around", "12 Extended"),
              t("01 Farley Jackmaster Funk & Jesse Saunders", "Love Can't Turn Around"),
              t("Farley ''Jackmaster'' Funk & Jesse Saunders", "Love Can't Turn Around"),
              t("[B1] Farley Jackmaster Funk feat. Daryl Pandy", "Love Can't Turn Around", "Farley Remix #2")]
    silk = [t("Steve 'Silk' Hurley featuring Sharon Pass", "The Word Is Love"),
            t("Steve Silk Hurley feat. Sharon Pass", "The Word Is Love")]
    adonis = [t("Adonis", "We're Rocking Down the House"), t("adonis", "were rocking down the house (down break (remastered))"),
              t("[04] Adonis", "Lost in the Sound"), t("Adonis", "Lost in the Sound")]
    assert len(R.tidy(farley)) == 1 and len(R.tidy(silk)) == 1 and len(R.tidy(adonis)) == 2
    assert len(R.tidy([t("808 State", "Pacific"), t("State", "Pacific")])) == 2       # a name, not a track number
    # one artist however it's spelled, for the per-artist limit too
    out = R.tidy([t("Farley 'Jackmaster' Funk", "It's U"), t("Farley Jackmaster Funk", "The Acid Life")], per_artist=1)
    assert len(out) == 1
