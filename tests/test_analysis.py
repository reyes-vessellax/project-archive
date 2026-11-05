"""Fixture matrix from spec section 11.1: each file type produces a truthful result."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.core.analyzer import analyze
from app.media.probe import probe

from .conftest import needs_ffmpeg

pytestmark = needs_ffmpeg


def run(path):
    import shutil, tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    staged = d / path.name
    shutil.copy(path, staged)
    return analyze(staged, Settings())


def status(result, check_id):
    return next(c["status"] for c in result["checks"] if c["id"] == check_id)


def test_real_320_passes(fixtures):
    r = run(fixtures["mp3_320"])
    assert r["overall_status"] == "PASS", r["checks"]
    assert r["facts"]["bitrate_mode"] == "CBR"
    assert r["facts"]["bitrate_bps"] == 320000
    assert r["cutoff_hz"] > 19000
    assert r["spectrogram_path"]


def test_192_warns_with_numbers(fixtures):
    r = run(fixtures["mp3_192"])
    c = next(c for c in r["checks"] if c["id"] == "bitrate")
    assert c["status"] == "WARN" and "192 kbps" in c["message"] and "320 kbps" in c["message"]


def test_fake_320_flagged_by_spectrum(fixtures):
    r = run(fixtures["fake_320"])
    assert status(r, "bitrate") == "PASS"          # it really is encoded at 320...
    assert status(r, "spectrum") == "WARN"         # ...but the spectrum gives it away
    assert r["cutoff_hz"] < 17500


def test_wav_from_mp3_warns_but_never_claims_master(fixtures):
    r = run(fixtures["fake_wav"])
    assert status(r, "spectrum") == "WARN"
    text = " ".join(c["message"] for c in r["checks"]).lower()
    for claim in ("verified", "authentic", "true master", "original master", "genuine lossless"):
        assert claim not in text


def test_vbr_not_called_cbr(fixtures):
    r = run(fixtures["vbr"])
    assert r["facts"]["bitrate_mode"] == "VBR"
    assert "VBR" in next(c["message"] for c in r["checks"] if c["id"] == "bitrate")


def test_renamed_extension_detected(fixtures):
    r = run(fixtures["renamed"])
    assert r["facts"]["container"] == "mp3"
    assert status(r, "format") == "WARN"


@pytest.mark.parametrize("key", ["trunc_mp3", "trunc_wav"])
def test_truncated_files_fail(fixtures, key):
    r = run(fixtures[key])
    assert status(r, "decode") == "FAIL", r["checks"]
    assert r["overall_status"] == "FAIL"


@pytest.mark.parametrize("key", ["random"])
def test_garbage_fails_without_crash(fixtures, key):
    r = run(fixtures[key])
    assert r["overall_status"] == "FAIL"


@pytest.mark.parametrize("key", ["flac", "aiff", "source_wav"])
def test_lossless_formats_pass(fixtures, key):
    r = run(fixtures[key])
    assert r["overall_status"] == "PASS", r["checks"]
    assert r["facts"]["bit_depth"] == 16


def test_mono_and_short_warn(fixtures):
    assert status(run(fixtures["mono"]), "channels") == "WARN"
    assert status(run(fixtures["short"]), "duration") == "WARN"


def test_probe_reports_unknown_not_zero(fixtures):
    f = probe(fixtures["mp3_320"])
    assert f.bit_depth is None                     # MP3 has no bit depth: unknown, never 0
