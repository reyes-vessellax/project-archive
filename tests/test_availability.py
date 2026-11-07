from app.adapters.base import Candidate
from app.core import availability as av


def cand(**kw) -> Candidate:
    base = dict(source_kind="soulseek", user="u", remote_path="a\\Artist - Track.flac", size=48_000_000,
                extension="flac", title="Track", artist="Artist")
    base.update(kw)
    return Candidate(**base)


def test_ready_now_shows_download_time():
    a = av.availability(cand(free_slot=True, upload_speed=2_000_000))
    assert a.word == "Ready now" and a.detail.endswith("sec") and a.rank == 0


def test_waits_are_broad_never_minutes_to_the_second():
    assert av.availability(cand(free_slot=False, queue_length=3)).label == "Short wait · few min"
    assert av.availability(cand(free_slot=False, queue_length=13)).label == "Long wait · 10+ min"
    assert av.availability(cand(free_slot=False, queue_length=200)).word == "Very long wait"
    assert av.availability(cand(free_slot=False, queue_length=999)).word == "Busy"
    assert av.availability(cand(locked=True)).word == "Private"


def test_slow_peer_says_minutes():
    a = av.availability(cand(free_slot=True, upload_speed=50_000))
    assert "min" in a.detail


def test_format_filters():
    flac = cand(extension="flac")
    mp3_320 = cand(extension="mp3", bitrate_kbps=320)
    mp3_192 = cand(extension="mp3", bitrate_kbps=192)
    f = av.Filters(lossless=True, mp3_320=True)
    assert [av.passes(c, f) for c in (flac, mp3_320, mp3_192)] == [True, True, False]
    assert all(av.passes(c, av.Filters()) for c in (flac, mp3_320, mp3_192))     # no format chosen = any


def test_ready_now_and_private_filters():
    waiting = cand(free_slot=False, queue_length=4)
    private = cand(locked=True)
    kept, hidden, priv = av.apply([waiting, private, cand(free_slot=True)], av.Filters(ready_now=True))
    assert len(kept) == 1 and hidden == 1 and priv == 1


def test_mix_filter():
    ext = cand(title="Night Bus", mix="Extended Mix")
    radio = cand(title="Night Bus", mix="Radio Edit")
    plain = cand(title="Night Bus", mix="")
    assert [av.mix_kind_matches(c, "extended") for c in (ext, radio, plain)] == [True, False, False]
    assert av.mix_kind_matches(radio, "radio") and not av.mix_kind_matches(radio, "edit")
    assert av.mix_kind_matches(plain, "original")
