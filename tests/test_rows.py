"""Discover rows are checked against MusicBrainz / Deezer, never trusted from a folder name."""
from __future__ import annotations

from app.core import rows as R
from tests.test_crates import FakeSvc, cand


class FakeEngine:
    """Discover._get stand-in: URL substring -> JSON."""
    def __init__(self, answers): self.answers, self.asked = answers, []

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


def test_era_row_checks_first_release_year():
    era = {"key": "chicago", "name": "Chicago jack", "years": "1984–1990", "artists": ["Fast Eddie"]}
    svc = FakeSvc([cand("a", "Fast Eddie - Yo Yo Get Funky", folder="Fast Eddie"),
                   cand("b", "Fast Eddie - New Thing 2019", folder="Fast Eddie"),
                   cand("c", "Fast Eddie - Unknown Track", folder="Fast Eddie")])
    eng = FakeEngine({"Yo%20Yo": {"recordings": [{"title": "Yo Yo Get Funky", "first-release-date": "1988-05"}]},
                      "New%20Thing": {"recordings": [{"title": "New Thing 2019", "first-release-date": "2019"}]}})
    out = R.era_row(svc, eng, era, day=1, per_day=1)
    assert sorted(t.title for t in out) == ["Unknown Track", "Yo Yo Get Funky"]     # unknown year stays
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
