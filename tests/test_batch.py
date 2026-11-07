import json

import pytest

from app.adapters.base import Candidate, parse_track
from app.core import batch as B


def test_tidy_youtube_titles():
    assert B.tidy("Kessler Avenue - Night Bus (Official Video)") == "Kessler Avenue - Night Bus"
    assert B.tidy("PREMIERE: Kessler Avenue - Night Bus [Lowtide Records]") == "Kessler Avenue - Night Bus [Lowtide Records]"
    assert B.tidy("Night Bus (Extended Mix) | Lowtide Records") == "Night Bus (Extended Mix)"
    assert B.tidy("Night Bus [FREE DOWNLOAD]") == "Night Bus"


def test_topic_channel_gives_the_artist():
    w = B.wanted_from_title("Night Bus", "Kessler Avenue - Topic", "YouTube")
    assert (w.artist, w.title) == ("Kessler Avenue", "Night Bus")


def test_mix_is_kept_separately():
    w = B.wanted_from_title("Kessler Avenue - Night Bus (Extended Mix) (Official Audio)")
    assert (w.artist, w.title, w.mix) == ("Kessler Avenue", "Night Bus", "Extended Mix")
    assert w.query == "Kessler Avenue Night Bus Extended Mix"


def test_pasted_list_numbered_and_m3u():
    text = "1. Kessler Avenue - Night Bus\n2) Mira Vale - Low Tide (Dub)\n\n#EXTM3U\n#EXTINF:402,Ostrander - Paper Lanterns\n/Users/me/Music/x.mp3\n"
    got = [(w.artist, w.title, w.mix) for w in B.parse_text(text)]
    assert got == [("Kessler Avenue", "Night Bus", ""), ("Mira Vale", "Low Tide", "Dub"), ("Ostrander", "Paper Lanterns", "")]


def test_csv_export():
    text = 'Track Name,Artist Name(s),Album Name\n"Night Bus - Extended Mix","Kessler Avenue, Mira Vale",EP\nLow Tide,Mira Vale,X\n'
    got = [(w.artist, w.title) for w in B.parse_text(text)]
    assert got[0][0] == "Kessler Avenue" and got[0][1].startswith("Night Bus")
    assert got[1] == ("Mira Vale", "Low Tide")


def test_duplicates_removed():
    assert len(B.parse_text("A - Song\na - song\nA - Song (Dub)")) == 2


def test_spotify_embed_page_is_read():
    payload = {"props": {"pageProps": {"state": {"data": {"entity": {"name": "Friday warm-up", "trackList": [
        {"title": "Night Bus - Extended Mix", "subtitle": "Kessler Avenue, Mira Vale"},
        {"title": "Low Tide", "subtitle": "Mira Vale"}]}}}}}}
    html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script></html>'.encode()
    name, items = B.from_link("https://open.spotify.com/playlist/37i9dQZF1DX", lambda u, t: html)
    assert name == "Friday warm-up"
    assert [(w.artist, w.title) for w in items][1] == ("Mira Vale", "Low Tide")
    assert items[0].artist == "Kessler Avenue"


def test_unreadable_links_say_what_to_do():
    with pytest.raises(B.LinkUnreadable, match="Paste"):
        B.from_link("https://open.spotify.com/playlist/abc", lambda u, t: b"<html>nothing</html>")
    with pytest.raises(B.LinkUnreadable):
        B.from_link("http://open.spotify.com/playlist/abc")
    with pytest.raises(B.LinkUnreadable):
        B.from_link("https://example.com/list")


def test_already_have():
    lib = [("Kessler Avenue", "Night Bus (Extended Mix)")]
    assert B.already_have(B.Wanted("Kessler Avenue", "Night Bus", "Extended Mix"), lib)
    assert B.already_have(B.Wanted("Kessler Avenue", "Night Bus"), lib)
    assert not B.already_have(B.Wanted("Kessler Avenue", "Night Bus", "Dub"), lib)


def _cand(name, ext="flac", kbps=None, free=True, q=0, locked=False):
    a, t, m = parse_track(name + "." + ext)
    return Candidate(source_kind="soulseek", user="u" + name, remote_path=name, size=40_000_000, display_name=name + "." + ext,
                     artist=a, title=t, mix=m, extension=ext, bitrate_kbps=kbps, free_slot=free, queue_length=q,
                     upload_speed=2_000_000, locked=locked)


def test_best_copy_prefers_right_mix_then_quality_then_ready():
    w = B.Wanted("Kessler Avenue", "Night Bus", "Extended Mix")
    cands = [
        _cand("Kessler Avenue - Night Bus (Radio Edit)"),
        _cand("Kessler Avenue - Night Bus (Extended Mix)", "mp3", 192),
        _cand("Kessler Avenue - Night Bus (Extended Mix)", "flac", free=False, q=40),
        _cand("Kessler Avenue - Night Bus (Extended Mix)", "flac"),
        _cand("Someone Else - Night Bus (Extended Mix)"),
        _cand("Kessler Avenue - Night Bus (Extended Mix)", "flac", locked=True),
    ]
    got = B.best(cands, w)
    assert got is cands[3]


def test_no_match_returns_none():
    assert B.best([_cand("Other - Thing")], B.Wanted("Kessler Avenue", "Night Bus")) is None
