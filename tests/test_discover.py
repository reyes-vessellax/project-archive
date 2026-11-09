"""Discover engine: MusicBrainz -> Discogs lookups (faked here, no network), cache, politeness, library matching."""
from __future__ import annotations

import json
import uuid

from app.core import jobs as J
from app.core.discover import Discover, LibraryIndex, Track, clean_name, _profile

MB_LABELS = {"labels": [{"id": "wax", "name": "Wax Trax! Records", "score": 100},
                        {"id": "trax", "name": "Trax Records", "score": 98}]}
MB_TRAX = {"relations": [{"type": "discogs", "url": {"resource": "https://www.discogs.com/label/267"}}]}
DG_LABEL = {"name": "Trax Records", "profile": "Chicago label run by [a=Larry Sherman].",
            "parent_label": None, "sublabels": [{"name": "Precision (2)"}], "uri": "https://www.discogs.com/label/267"}
DG_RELEASES = {"pagination": {"page": 1, "pages": 3, "items": 250},
               "releases": [{"id": 1, "title": "Yo Yo Get Funky", "artist": "Fast Eddie (2)", "year": 1988, "catno": "TX160",
                             "format": "12\""},
                            {"id": 2, "title": "Yo Yo Get Funky", "artist": "Fast Eddie (2)", "year": 1988, "catno": "TX160-R",
                             "format": "12\", RP"},
                            {"id": 3, "title": "Acid Tracks", "artist": "Phuture", "year": 1987, "catno": "TX142"}]}


class FakeNet:
    def __init__(self):
        self.calls = []

    def __call__(self, url, timeout=10.0):
        self.calls.append(url)
        if "musicbrainz.org/ws/2/label?" in url:
            return json.dumps(MB_LABELS).encode()
        if "musicbrainz.org/ws/2/label/trax" in url:
            return json.dumps(MB_TRAX).encode()
        if "musicbrainz.org/ws/2/label/wax" in url:
            return json.dumps({"relations": [{"url": {"resource": "https://www.discogs.com/label/999"}}]}).encode()
        if url.endswith("/labels/267"):
            return json.dumps(DG_LABEL).encode()
        if "/labels/267/releases" in url:
            return json.dumps(DG_RELEASES).encode()
        raise OSError("offline")


class Clock:
    def __init__(self):
        self.t, self.slept = 0.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s); self.t += s


def _own(db, artist, title, label="Trax Records", bpm=124.0, cam="8A", when="2026-11-01T10:00:00+00:00"):
    jid = str(uuid.uuid4())
    db.insert_job(id=jid, source_kind="manual", original_name=f"{artist} - {title}.mp3", state=J.PROMOTED,
                  created_at=when, updated_at=when)
    meta = {"artist": artist, "title": title, "label": label, "year": "1988"}
    db._con.execute("INSERT INTO analyses (job_id, overall_status, analysis_json) VALUES (?,?,?)",
                    (jid, "PASS", json.dumps({"meta": meta, "music": {"bpm": bpm, "camelot": cam}})))
    db._con.commit()
    return jid


def test_label_by_exact_name_then_catalogue_marks_owned(service):
    _own(service.db, "Fast Eddie", "Yo Yo Get Funky")
    net, clock = FakeNet(), Clock()
    d = Discover(service.db, fetch=net, sleep=clock.sleep, clock=clock.now)
    e = d.label("Trax Records")
    assert e.discogs_id == 267 and "Larry Sherman" in e.profile and ("Sub-label", "Precision") in e.related
    page = d.label_releases(e.discogs_id)
    assert (page.pages, page.total) == (3, 250)
    assert [(r.artist, r.title) for r in page.releases] == [("Phuture", "Acid Tracks"), ("Fast Eddie", "Yo Yo Get Funky")]
    assert page.releases[1].owned and not page.releases[0].owned            # by year; reissue folded in; owned ticked
    assert not any("label/wax" in u for u in net.calls)                      # never took Wax Trax! for Trax


def test_cache_answers_second_time_and_requests_are_spaced(service):
    net, clock = FakeNet(), Clock()
    d = Discover(service.db, fetch=net, sleep=clock.sleep, clock=clock.now)
    d.label("Trax Records")
    first = len(net.calls)
    assert all(s <= 2.5 for s in clock.slept) and clock.slept                # waited between requests
    d2 = Discover(service.db, fetch=net, sleep=clock.sleep, clock=clock.now)  # e.g. next app start
    d2.label("Trax Records")
    assert len(net.calls) == first                                            # all from the cache


def test_offline_uses_stale_cache(service):
    d = Discover(service.db, fetch=FakeNet(), sleep=lambda s: None)
    d.label("Trax Records")
    service.db._con.execute("UPDATE discover_cache SET fetched_at = '2000-01-01T00:00:00+00:00'"); service.db._con.commit()
    dead = Discover(service.db, fetch=lambda u, t=0: (_ for _ in ()).throw(OSError("offline")), sleep=lambda s: None)
    assert dead.label("Trax Records").discogs_id == 267


def test_unknown_label_comes_back_without_id(service):
    d = Discover(service.db, fetch=lambda u, t=0: b'{"labels": []}', sleep=lambda s: None)
    assert d.label("Nobody Records").discogs_id is None


def test_library_labels_artists_and_mixes(service):
    db = service.db
    a = _own(db, "Fast Eddie", "Yo Yo Get Funky", bpm=125.0, cam="8A", when="2026-11-09T10:00:00+00:00")
    _own(db, "Marshall Jefferson", "Move Your Body", bpm=124.0, cam="8A")
    _own(db, "Phuture", "Acid Tracks", bpm=62.5, cam="9A")                       # half time, next key
    _own(db, "Moodymann", "Shades", label="KDJ", bpm=110.0, cam="8A")           # too slow
    _own(db, "Frankie Knuckles & Jamie Principle", "Baby Wants To Ride", bpm=124.5, cam="3B")  # key clash
    idx = Discover(db, fetch=FakeNet(), sleep=lambda s: None).library()
    assert idx.labels()[0] == ("Trax Records", 4)
    assert ("Jamie Principle", 1) in idx.artists(20)
    new = idx.recent(1)[0]
    assert new.job_id == a
    assert [t.title for t in idx.mixes_with(new)] == ["Move Your Body", "Acid Tracks"]


def test_names_and_profiles_are_tidied():
    assert clean_name("Fast Eddie (2)") == "Fast Eddie" and clean_name("Lil Louis*") == "Lil Louis"
    assert _profile("By [a=Larry Heard] on [l=Trax Records]. [url=http://x]site[/url] [b]bold[/b]") == \
        "By Larry Heard on Trax Records. site bold"
    idx = LibraryIndex([Track("1", "Mr. Fingers", "Can You Feel It", "", "", None, "", "")])
    idx._titles = {"mr fingers": {"can you feel it"}}
    assert idx.owns("Mr. Fingers", "Can You Feel It (Vocal)") and not idx.owns("Mr. Fingers", "Washing Machine")


def test_busy_server_is_retried(service):
    import urllib.error
    net, clock, n = FakeNet(), Clock(), {"busy": 2}

    def flaky(url, timeout=10.0):
        if n["busy"]:
            n["busy"] -= 1
            raise urllib.error.HTTPError(url, 503, "busy", {}, None)
        return net(url, timeout)
    d = Discover(service.db, fetch=flaky, sleep=clock.sleep, clock=clock.now)
    assert d.label("Trax Records").discogs_id == 267 and max(clock.slept) >= 2.0


def test_same_named_artist_picks_the_house_one(service):
    mb = {"artists": [{"id": "band", "name": "Fast Eddie", "score": 91, "disambiguation": "UK mod band", "tags": [{"name": "mod"}]},
                      {"id": "eddie", "name": "“Fast” Eddie Smith", "score": 100, "disambiguation": "Chicago house producer"}]}

    def net(url, timeout=10.0):
        if "artist?query" in url:
            return json.dumps(mb).encode()
        if "artist/eddie" in url:
            return json.dumps({"relations": [{"url": {"resource": "https://www.discogs.com/artist/1234"}}]}).encode()
        if "artist/band" in url:
            return json.dumps({"relations": [{"url": {"resource": "https://www.discogs.com/artist/9999"}}]}).encode()
        if url.endswith("/artists/1234"):
            return json.dumps({"name": "Fast Eddie"}).encode()
        raise OSError(url)
    assert Discover(service.db, fetch=net, sleep=lambda s: None).artist("Fast Eddie").discogs_id == 1234
