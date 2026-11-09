"""Metadata: name matching, online lookup (with fake responses, never the real internet), Rekordbox tag writing."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.core import jobs as J
from app.media import metadata as md
from tests.conftest import needs_ffmpeg

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def fake_web(routes: dict[str, object]):
    """fetch(url) -> the first route whose key is in the url; dicts are returned as JSON."""
    seen = []

    def fetch(url, timeout=0):
        seen.append(url)
        for key, body in routes.items():
            if key in url:
                return json.dumps(body).encode() if isinstance(body, (dict, list)) else body
        raise OSError("no route")
    fetch.seen = seen
    return fetch


DEEZER_SEARCH = {"data": [
    {"title": "Night Bus (Extended Mix)", "title_short": "Night Bus", "artist": {"name": "Kessler Avenue"},
     "album": {"id": 42, "title": "Night Bus EP", "cover_xl": "https://cdn.example/cover1000.jpg"}},
]}
DEEZER_ALBUM = {"label": "Lowtide Records", "release_date": "2025-03-14", "genres": {"data": [{"name": "Dance"}]}}


def test_matching_ignores_mix_feat_and_punctuation():
    assert md.similar("Night Bus (Extended Mix)", "Night Bus") == 1.0
    assert md.similar("Café del Mar", "Cafe Del Mar") == 1.0
    assert md.artist_ok("Kessler Avenue", "Kessler Avenue & Mira Vale")
    assert not md.artist_ok("Kessler Avenue", "Someone Else")
    assert md.similar("Night Bus", "Day Train") < md.MATCH


def test_lookup_takes_label_year_genre_and_cover_from_deezer():
    fetch = fake_web({"api.deezer.com/search": DEEZER_SEARCH, "api.deezer.com/album/42": DEEZER_ALBUM})
    m = md.lookup("Kessler Avenue", "Night Bus", fetch)
    assert m and m.source == "Deezer"
    assert (m.label, m.year, m.genre) == ("Lowtide Records", "2025", "Dance")
    assert m.cover_url == "https://cdn.example/cover1000.jpg"


def test_lookup_rejects_a_different_track():
    wrong = {"data": [{"title": "Day Train", "title_short": "Day Train", "artist": {"name": "Kessler Avenue"},
                       "album": {"id": 1, "cover_xl": "https://cdn.example/x.jpg"}}]}
    fetch = fake_web({"api.deezer.com/search": wrong, "musicbrainz.org": {"recordings": []},
                      "itunes.apple.com": {"results": []}})
    assert md.lookup("Kessler Avenue", "Night Bus", fetch) is None


def test_lookup_falls_back_to_itunes_for_the_cover():
    fetch = fake_web({"api.deezer.com/search": {"data": []}, "musicbrainz.org": {"recordings": []},
                      "itunes.apple.com": {"results": [{"trackName": "Night Bus (Extended Mix)", "artistName": "Kessler Avenue",
                                                        "collectionName": "Night Bus", "releaseDate": "2025-03-14T00:00:00Z",
                                                        "primaryGenreName": "House",
                                                        "artworkUrl100": "https://is1.example/100x100bb.jpg"}]}})
    m = md.lookup("Kessler Avenue", "Night Bus", fetch)
    assert m and m.source == "iTunes" and m.cover_url.endswith("1000x1000bb.jpg") and m.genre == "House"


def test_only_artist_and_title_leave_the_machine():
    fetch = fake_web({"api.deezer.com/search": DEEZER_SEARCH, "api.deezer.com/album/42": DEEZER_ALBUM})
    md.lookup("Kessler Avenue", "Night Bus", fetch)
    assert all(u.startswith("https://") for u in fetch.seen)
    assert not any("/Users/" in u or "\\" in u for u in fetch.seen)


def test_cover_download_refuses_non_images(tmp_path):
    assert md.download_cover("https://x/cover", tmp_path / "c", fake_web({"x/cover": b"<html>nope</html>"})) is None
    assert md.download_cover("http://x/cover", tmp_path / "c", fake_web({"x/cover": JPEG})) is None   # https only
    got = md.download_cover("https://x/cover", tmp_path / "c", fake_web({"x/cover": JPEG}))
    assert got and got.suffix == ".jpg" and got.read_bytes() == JPEG


def test_classic_key():
    assert md.classic_key("A minor") == "Am"
    assert md.classic_key("Eb major") == "Eb"
    assert md.classic_key("") == ""


MUSIC = {"bpm": 123.96, "key": "A minor", "camelot": "8A", "drop_s": 200.0}
META = md.Meta(title="Night Bus", mix="Extended Mix", artist="Kessler Avenue", album="Night Bus EP",
               label="Lowtide Records", year="2025", genre="Deep House")


@needs_ffmpeg
@pytest.mark.parametrize("kind", ["mp3_320", "flac", "aiff", "source_wav"])
def test_rekordbox_tags_round_trip(fixtures, tmp_path, kind):
    f = tmp_path / fixtures[kind].name
    shutil.copy(fixtures[kind], f)
    cover = tmp_path / "cover.jpg"; cover.write_bytes(JPEG)
    written = md.write_tags(f, META, MUSIC, cover)
    t = md.read_tags(f)
    assert t["title"] == "Night Bus (Extended Mix)"
    assert (t["artist"], t["label"], t["genre"], t["year"]) == ("Kessler Avenue", "Lowtide Records", "Deep House", "2025")
    assert (t["bpm"], t["key"]) == ("124", "Am")
    assert t["has_cover"] and "cover" in written


@needs_ffmpeg
def test_existing_tags_are_kept(fixtures, tmp_path):
    f = tmp_path / "t.mp3"; shutil.copy(fixtures["mp3_320"], f)
    md.write_tags(f, md.Meta(title="Their Title", artist="Their Artist"), None, None)
    md.write_tags(f, META, MUSIC, None)
    t = md.read_tags(f)
    assert (t["title"], t["artist"]) == ("Their Title", "Their Artist")   # never overwritten
    assert t["label"] == "Lowtide Records" and t["bpm"] == "124"          # gaps filled, measured values written


@needs_ffmpeg
def test_part_file_is_tagged_as_its_real_type(fixtures, tmp_path):
    f = tmp_path / ".track.flac.abcd.part"; shutil.copy(fixtures["flac"], f)
    md.write_tags(f, META, MUSIC, None, ext=".flac")
    final = tmp_path / "track.flac"; f.rename(final)
    assert md.read_tags(final)["title"] == "Night Bus (Extended Mix)"


@needs_ffmpeg
def test_save_writes_tags_and_crash_recovery_still_recognises_the_file(service, fixtures):
    job = service.stage(fixtures["flac"])
    a = service.analyze(job["id"])
    assert "music" in a and "meta" in a                                   # measured + described during the check
    target = service.promote(job["id"])
    a2 = service.db.analysis(job["id"])
    assert a2["final_sha256"] and target.is_file()
    # simulate a crash right after the move: recovery must accept the tagged file as the finished save
    service.db.update_job(job["id"], state=J.PROMOTING)
    service.reconcile()
    assert service.db.job(job["id"])["state"] == J.PROMOTED


@needs_ffmpeg
def test_offline_lookup_never_blocks_the_check(service, fixtures):
    job = service.stage(fixtures["mp3_320"])
    a = service.analyze(job["id"])                                       # network is disabled in tests
    assert a["overall_status"] in ("PASS", "WARN") and a["meta"]["cover_path"] is None


@needs_ffmpeg
def test_catalogue_number_in_brackets_is_not_a_mix(fixtures, tmp_path):
    from app.config import Settings
    from app.core.analyzer import describe
    f = tmp_path / "TINO - ROCK YA BODY [M.A.D 019].mp3"; shutil.copy(fixtures["mp3_320"], f)
    g = tmp_path / "Kessler Avenue - Night Bus (Extended Mix).mp3"; shutil.copy(fixtures["mp3_320"], g)
    s = Settings(); s.online_lookup = False
    assert describe(f, s)["mix"] == ""
    assert describe(g, s)["mix"] == "Extended Mix"


def test_download_sites_are_not_labels():
    from app.media.metadata import clean_label, is_site_name
    for junk in ("DJDownloadMe.com", "www.musicpool.ru", "Promo Only", "320kbps", "[none]", "Not On Label", "MP3 Pool",
                 "https://x.example", "Unknown Label"):
        assert clean_label(junk) == "", junk
    for real in ("Trax Records", "Dance Mania", "KMS", "Strictly Rhythm", "Downtown 161", "Relief Records"):
        assert clean_label(real) == real
    assert is_site_name("DJDownloadMe.com") and not is_site_name("Fast Eddie")
