"""Club-ready checks on synthetic audio (no copyrighted material)."""
from __future__ import annotations

import numpy as np
import pytest

from app.core.rules import FAIL, PASS, WARN
from app.media.club import club_checks, mono_verdict, parse_stats
from app.media.probe import probe
from tests.conftest import FFMPEG, ff, needs_ffmpeg


def _status(res, cid):
    return next(c for c in res["checks"] if c["id"] == cid)["status"]


def test_mono_verdict_phase():
    sr = 11025
    t = np.arange(sr * 8) / sr
    bass = np.sin(2 * np.pi * 55 * t)
    hats = 0.1 * np.random.default_rng(1).standard_normal(t.size)
    assert mono_verdict(bass + hats, bass + hats, sr).status == PASS
    assert mono_verdict(bass + hats, -bass + hats, sr).status == FAIL          # bass flipped on one side
    assert mono_verdict(bass, np.zeros_like(bass), sr).status == PASS          # one side silent: nothing cancels


def test_parse_ffmpeg_stats():
    err = """[Parsed_astats_0 @ 0x1] Overall
[Parsed_astats_0 @ 0x1] Peak level dB: -0.000000
[Parsed_astats_0 @ 0x1] Flat factor: 3.5
[Parsed_astats_0 @ 0x1] Peak count: 4200.000000
[Parsed_ebur128_1 @ 0x2] Summary:
  Integrated loudness:
    I:          -7.3 LUFS
  True peak:
    Peak:        1.4 dBFS"""
    st = parse_stats(err)
    assert st == {"peak_db": -0.0, "peak_count": 4200.0, "flat": 3.5, "lufs": -7.3, "true_peak": 1.4}


@needs_ffmpeg
def test_good_file_is_club_ready(fixtures):
    p = fixtures["mp3_320"]
    res = club_checks(p, probe(p))
    assert res["ready"] and _status(res, "club_load") == PASS and _status(res, "club_mono") == PASS


@needs_ffmpeg
@pytest.mark.parametrize("args,why", [
    (["-c:a", "pcm_f32le"], "32-bit float"),
    (["-ar", "192000", "-c:a", "pcm_s24le"], "kHz"),
])
def test_decks_cant_load(tmp_path, fixtures, args, why):
    p = tmp_path / "t.wav"
    ff("-i", str(fixtures["source_wav"]), "-t", "8", *args, str(p))
    res = club_checks(p, probe(p))
    load = next(c for c in res["checks"] if c["id"] == "club_load")
    assert not res["ready"] and load["status"] == FAIL and why in load["message"]


@needs_ffmpeg
def test_out_of_phase_bass_fails(tmp_path):
    p = tmp_path / "phase.wav"
    ff("-f", "lavfi", "-i", "sine=f=55:d=10:r=44100", "-filter_complex",
       "[0]asplit[a][b];[b]volume=-1[bi];[a][bi]join=inputs=2:channel_layout=stereo", "-c:a", "pcm_s16le", str(p))
    res = club_checks(p, probe(p))
    assert _status(res, "club_mono") == FAIL and not res["ready"]


@needs_ffmpeg
def test_clipped_and_quiet(tmp_path, fixtures):
    hot = tmp_path / "hot.wav"
    ff("-i", str(fixtures["source_wav"]), "-t", "10", "-af", "volume=24dB", "-c:a", "pcm_s16le", str(hot))
    assert _status(club_checks(hot, probe(hot)), "club_clip") == WARN
    quiet = tmp_path / "quiet.wav"
    ff("-i", str(fixtures["source_wav"]), "-t", "10", "-af", "volume=-24dB", "-c:a", "pcm_s16le", str(quiet))
    assert _status(club_checks(quiet, probe(quiet)), "club_loud") == WARN


@needs_ffmpeg
def test_analysis_carries_club_result(service, fixtures):
    job = service.stage(fixtures["mp3_320"])
    a = service.analyze(job["id"])
    assert a["club"]["ready"] and {c["id"] for c in a["club"]["checks"]} >= {"club_load", "club_mono", "club_loud"}
    assert a["overall_status"] in ("PASS", "WARN")                    # the verdict is unchanged by club notes
