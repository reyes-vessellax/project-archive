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


# ---------------------------------------------------------------- runner (fake network, fake clock)
from app.adapters.base import SearchResult
from app.core import batch_runner as R


class FakeNet:
    def __init__(self, catalogue):
        self.catalogue, self.started = catalogue, []

    def search(self, q, timeout_s=0):
        self.started.append((q, clock.t)); return SearchResult(query=q, search_id=q, finished=False)

    def search_status(self, sid):
        return True, 1, 1, "Completed"

    def stop_search(self, sid): pass
    def forget_search(self, sid): pass

    def search_results(self, sid):
        return SearchResult(query=sid, search_id=sid, finished=True, candidates=self.catalogue.get(sid, []))


class clock:
    t = 0.0

    @staticmethod
    def now():
        return clock.t

    @staticmethod
    def sleep(s):
        clock.t += s


def test_runner_spaces_searches_skips_owned_and_picks_best():
    clock.t = 0.0
    good = _cand("Kessler Avenue - Night Bus (Extended Mix)", "flac")
    net = FakeNet({"Kessler Avenue Night Bus Extended Mix": [good], "Mira Vale Low Tide": []})
    items = [R.Item(B.Wanted("Kessler Avenue", "Night Bus", "Extended Mix")),
             R.Item(B.Wanted("Static", "Owned")),
             R.Item(B.Wanted("Mira Vale", "Low Tide"))]
    updates = []
    R.run(items, net, [("Static", "Owned")], lambda i, it: updates.append((i, it.status)),
          sleep=clock.sleep, clock=clock.now)
    assert [it.status for it in items] == ["found", "have", "not_found"]
    assert items[0].pick is good and items[0].detail.startswith("FLAC")
    assert len(net.started) == 2                                          # the owned one never hit the network
    assert net.started[1][1] - net.started[0][1] >= R.GAP_S               # spaced out


def test_runner_stops_when_asked():
    clock.t = 0.0
    net = FakeNet({})
    items = [R.Item(B.Wanted("A", f"Song {n}")) for n in range(5)]
    R.run(items, net, [], lambda i, it: None, should_stop=lambda: len(net.started) >= 2, sleep=clock.sleep, clock=clock.now)
    assert len(net.started) == 2


def test_runner_draws_from_the_shared_search_budget():
    """Batch, the Search page and the Wishlist share one budget: an empty bucket makes the batch wait."""
    from app.core.searching import Budget
    clock.t = 0.0
    net = FakeNet({})
    net.search_budget = Budget(burst=1, refill_s=1.0)
    net.search_budget.take()                                   # someone else just searched: bucket empty
    waits = []

    def sleep(s):
        waits.append(s); clock.sleep(s)
        import time as _t; _t.sleep(s)                          # the budget runs on the real clock
    items = [R.Item(B.Wanted("A", "Song"))]
    R.run(items, net, [], lambda i, it: None, sleep=sleep, clock=clock.now)
    assert len(net.started) == 1 and sum(waits) >= 0.5         # waited for a token before searching
    assert net.search_budget.wait_needed() > 0                 # and used it


def test_low_bitrate_copies_are_never_picked():
    """A beta batch picked an MP3 192 because it could start sooner. Below the bar it isn't a candidate."""
    w = B.Wanted("Kessler Avenue", "Night Bus")
    low = _cand("Kessler Avenue - Night Bus", "mp3", 192)
    good = _cand("Kessler Avenue - Night Bus", "mp3", 320, free=False, q=12)
    assert B.best([low, good], w) is good
    assert B.best([low], w) is None
    assert B.ranked([low, good, _cand("Kessler Avenue - Night Bus", "flac")], w)[0].extension == "flac"


def test_row_two_click_download_and_swap(monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from app.core import batch_runner as BR
    from app.ui.batch_page import Batch, BatchPage
    app = QApplication.instance() or QApplication([])
    w = B.Wanted("Kessler Avenue", "Night Bus")
    alts = B.ranked([_cand("Kessler Avenue - Night Bus", "flac"), _cand("Kessler Avenue - Night Bus", "mp3", 320)], w)
    it = BR.Item(w, status="found", alts=alts); BR.choose(it, alts[0])
    page = BatchPage(); page.add_batch(Batch("Set", items=[it])); app.processEvents()
    row = page._rows[0]
    got = []
    page.download_one.connect(lambda bid, i: got.append(i))
    row.go.click(); assert row.go.text() == "Download?" and got == []
    row.go.click(); assert got == [0] and row.go.text() == "Found"
    page._toggle_row(0); assert row.drop.isVisibleTo(row)
    page._choose(0, 1); assert it.pick is alts[1] and it.detail.startswith("MP3 320")
