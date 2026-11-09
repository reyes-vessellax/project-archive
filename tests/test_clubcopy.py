"""Club-ready copy: converts only what decks can't load, proves the copy, never touches the original."""
from __future__ import annotations

import hashlib

import pytest

from app.media.club import club_checks
from app.media.clubcopy import CopyFailed, make_club_copy, needs_copy, plan
from app.media.probe import probe
from tests.conftest import ff, needs_ffmpeg


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


@needs_ffmpeg
@pytest.mark.parametrize("name,args,want", [
    ("f32.wav", ["-c:a", "pcm_f32le"], ("pcm_s24be", 44100)),
    ("hi.wav", ["-ar", "192000", "-c:a", "pcm_s24le"], ("pcm_s24be", 48000)),
    ("hi96.flac", ["-ar", "96000", "-sample_fmt", "s32", "-c:a", "flac"], ("pcm_s24be", 48000)),
    ("x.ogg", ["-c:a", "vorbis", "-strict", "-2"], ("pcm_s16be", 44100)),
])
def test_copy_loads_on_decks_and_matches(tmp_path, fixtures, name, args, want):
    src = tmp_path / name
    try:
        ff("-i", str(fixtures["source_wav"]), "-t", "20", *args, str(src))
    except Exception:
        pytest.skip("this FFmpeg can't make that test file")
    before = _sha(src)
    f = probe(src)
    assert needs_copy(club_checks(src, f)) or name.endswith(".ogg")
    out = make_club_copy(src, f, tmp_path / "out.aiff")
    g = probe(out)
    assert (g.codec, g.sample_rate_hz) == want
    res = club_checks(out, g)
    assert next(c for c in res["checks"] if c["id"] == "club_load")["status"] == "PASS"
    assert _sha(src) == before                                   # the original is untouched
    assert not list(tmp_path.glob(".*part*"))                    # no leftovers


@needs_ffmpeg
def test_a_bad_copy_is_refused_and_removed(tmp_path, fixtures, monkeypatch):
    from app.media import clubcopy
    src = tmp_path / "f32.wav"
    ff("-i", str(fixtures["source_wav"]), "-t", "10", "-c:a", "pcm_f32le", str(src))
    monkeypatch.setattr(clubcopy, "_same_audio", lambda a, b, e, t: (0.5, 10.0, 10.0))   # pretend it came out wrong
    with pytest.raises(CopyFailed, match="match"):
        make_club_copy(src, probe(src), tmp_path / "out.aiff")
    assert not (tmp_path / "out.aiff").exists() and not list(tmp_path.glob(".*part*"))


def test_only_format_problems_get_a_copy():
    load_fail = {"ready": False, "checks": [{"id": "club_load", "status": "FAIL"}, {"id": "club_mono", "status": "PASS"}]}
    phase_fail = {"ready": False, "checks": [{"id": "club_load", "status": "FAIL"}, {"id": "club_mono", "status": "FAIL"}]}
    assert needs_copy(load_fail) and not needs_copy(phase_fail) and not needs_copy({"ready": True, "checks": []})
    hi_rate = {"ready": True, "checks": [{"id": "club_load", "status": "WARN"}]}
    assert needs_copy(hi_rate)                                   # 96 kHz: fine on new decks, a copy plays on all


def test_plan_targets():
    class F:
        def __init__(self, sr, codec, bits=None, ch=2):
            self.sample_rate_hz, self.codec, self.bit_depth, self.channels = sr, codec, bits, ch
    assert plan(F(96000, "pcm_s24le", 24)) == {"sr": 48000, "bits": 24, "channels": 2}
    assert plan(F(88200, "flac", 24)) == {"sr": 44100, "bits": 24, "channels": 2}
    assert plan(F(44100, "vorbis")) == {"sr": 44100, "bits": 16, "channels": 2}
    assert plan(F(44100, "pcm_f32le", 32, 6))["channels"] == 2


@needs_ffmpeg
def test_service_makes_a_checked_copy_and_leaves_the_original(service, fixtures, tmp_path):
    from app.core import jobs as J
    from app.core.service import ActionBlocked
    src = tmp_path / "Deep Cut.wav"
    ff("-i", str(fixtures["source_wav"]), "-c:a", "pcm_f32le", str(src))
    job = service.stage(src); service.analyze(job["id"])
    staged_before = _sha(__import__("pathlib").Path(service.db.job(job["id"])["staged_path"]))
    new = service.make_club_copy(job["id"])
    assert new["original_name"] == "Deep Cut (club-ready).aiff" and new["id"] != job["id"]
    a = service.analyze(new["id"])
    assert a["club"]["ready"] and service.db.job(new["id"])["state"] == J.READY
    assert _sha(__import__("pathlib").Path(service.db.job(job["id"])["staged_path"])) == staged_before
    good = service.stage(fixtures["mp3_320"]); service.analyze(good["id"])
    with pytest.raises(ActionBlocked):
        service.make_club_copy(good["id"])                       # nothing to fix: no copy


@needs_ffmpeg
def test_works_without_the_sox_resampler(tmp_path, fixtures, monkeypatch):
    """Homebrew's FFmpeg has no SoX resampler: the copy must still be made (and proved) with FFmpeg's own."""
    from app.media import clubcopy
    real_run = clubcopy.run

    def no_soxr(args, timeout):
        if any("resampler=soxr" in a for a in args):
            class P: returncode, stderr, stdout = 1, b"soxr not available", b""
            return P()
        return real_run(args, timeout)
    monkeypatch.setattr(clubcopy, "run", no_soxr)
    src = tmp_path / "hi.wav"
    ff("-i", str(fixtures["source_wav"]), "-t", "20", "-ar", "96000", "-c:a", "pcm_f32le", str(src))
    out = make_club_copy(src, probe(src), tmp_path / "out.aiff")
    assert (probe(out).codec, probe(out).sample_rate_hz) == ("pcm_s24be", 48000)
