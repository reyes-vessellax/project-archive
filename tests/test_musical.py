"""BPM, key and preview-window detection on synthetic tracks (no copyrighted audio)."""
from __future__ import annotations

import wave

import numpy as np
import pytest

from app.media import musical
from tests.conftest import needs_ffmpeg

SR = musical.SR


def _kick_track(bpm: float, seconds: float, sr: int = SR) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    y = np.zeros_like(t)
    beat = 60.0 / bpm
    kick_len = int(0.12 * sr)
    kt = np.arange(kick_len) / sr
    kick = np.sin(2 * np.pi * (50 + 80 * np.exp(-kt * 40)) * kt) * np.exp(-kt * 25)
    hat_len = int(0.03 * sr)
    hat = np.random.default_rng(1).standard_normal(hat_len) * np.exp(-np.arange(hat_len) / sr * 150) * 0.2
    n = 0
    while n * beat < seconds:
        i = int(n * beat * sr)
        y[i: i + kick_len] += kick[: len(y[i: i + kick_len])]
        j = int((n + 0.5) * beat * sr)                     # off-beat hat
        y[j: j + hat_len] += hat[: len(y[j: j + hat_len])]
        n += 1
    return y


def _chord(freqs: list[float], seconds: float, sr: int = SR) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    return sum(np.sin(2 * np.pi * f * t) for f in freqs) / len(freqs)


A_MINOR = [110.0, 220.0, 261.63, 329.63, 440.0, 523.25]    # A, C, E across octaves
C_MAJOR = [130.81, 261.63, 329.63, 392.0, 523.25, 659.25]  # C, E, G


def _dance_track(bpm=124.0, intro=60.0, body=60.0) -> np.ndarray:
    total = intro + body
    drums = _kick_track(bpm, total)
    pad = _chord(A_MINOR, total) * 0.25
    y = drums * 0.5 + pad
    gain = np.where(np.arange(len(y)) < intro * SR, 0.12, 1.0)  # quiet intro, then the drop
    return (y * gain * 0.6).astype(np.float32)


@pytest.mark.parametrize("bpm", [122.0, 124.0, 128.0, 174.0])
def test_bpm(bpm):
    y = _kick_track(bpm, 60).astype(np.float32)
    got = musical.estimate_bpm(y)
    assert got is not None
    assert abs(got - bpm) <= 0.5 or abs(got * 2 - bpm) <= 1.0   # half-time is acceptable for DnB


def test_bpm_fractional():
    got = musical.estimate_bpm(_kick_track(123.5, 90).astype(np.float32))
    assert got is not None and abs(got - 123.5) <= 0.2


def test_key_minor_and_camelot():
    y = (_chord(A_MINOR, 30) * 0.5).astype(np.float32)
    key, camelot, conf = musical.estimate_key(y)
    assert (key, camelot) == ("A minor", "8A")
    assert 0.0 <= conf <= 1.0


def test_key_major():
    key, camelot, _ = musical.estimate_key((_chord(C_MAJOR, 30) * 0.5).astype(np.float32))
    assert (key, camelot) == ("C major", "8B")


def test_preview_starts_just_before_the_drop():
    y = _dance_track(intro=60, body=60)
    drop, start = musical.find_preview(y)
    assert drop is not None and 57 <= drop <= 62
    assert start == pytest.approx(drop - musical.LEAD_IN_S, abs=0.01)


def test_preview_without_a_drop_picks_the_loudest_stretch():
    rng = np.random.default_rng(0)
    y = rng.standard_normal(SR * 90).astype(np.float32) * 0.05
    y[SR * 50: SR * 75] *= 8                               # a loud 25 s section, no sharp rise into it
    ramp = np.linspace(1, 8, SR * 20)
    y[SR * 30: SR * 50] *= ramp.astype(np.float32)
    drop, start = musical.find_preview(y)
    assert 48 <= start <= 56
    assert start + musical.PREVIEW_S <= 90


def test_short_or_silent_audio_gives_nothing():
    assert musical.analyze_samples(np.zeros(SR * 30, dtype=np.float32)).bpm is None
    assert musical.analyze_samples(np.ones(SR * 2, dtype=np.float32) * 0.1).bpm is None


@needs_ffmpeg
def test_full_pipeline_through_ffmpeg(tmp_path):
    y = _dance_track(bpm=124.0, intro=40, body=50)
    pcm = (np.clip(y, -1, 1) * 32767).astype("<i2")
    p = tmp_path / "track.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    m = musical.analyze_music(p)
    assert m.bpm is not None and abs(m.bpm - 124.0) <= 0.5
    assert m.camelot == "8A"
    assert m.drop_s is not None and 37 <= m.drop_s <= 42


# ------------------------------------------------------------------- BPM/key the file already carries
from app.media.musical import bpm_from_tag, key_from_tag, prefer_tags


@pytest.mark.parametrize("tag,want", [
    ("Am", ("A minor", "8A")), ("A minor", ("A minor", "8A")), ("8A", ("A minor", "8A")), ("08B", ("C major", "8B")),
    ("1m", ("A minor", "8A")), ("1d", ("C major", "8B")), ("G#m", ("Ab minor", "1A")), ("Abm", ("Ab minor", "1A")),
    ("F#maj", ("F# major", "2B")), ("C", ("C major", "8B")), ("Dbm", ("C# minor", "12A")), ("12B", ("E major", "12B")),
    ("", None), ("o", None), ("Unknown", None), ("13A", None),
])
def test_key_tags_in_every_notation(tag, want):
    assert key_from_tag(tag) == want


def test_bpm_tag_must_be_plausible():
    assert bpm_from_tag("124") == 124.0 and bpm_from_tag("128,00") == 128.0
    assert bpm_from_tag("0") is None and bpm_from_tag("") is None and bpm_from_tag("fast") is None


def test_tags_win_and_measurement_is_kept():
    mu = prefer_tags({"bpm": 123.9, "key": "D minor", "camelot": "7A"}, {"bpm": "124", "key": "Am"})
    assert mu["bpm"] == 124.0 and mu["bpm_from_tags"] and mu["bpm_measured"] == 123.9
    assert (mu["key"], mu["camelot"], mu["key_from_tags"]) == ("A minor", "8A", True)
    assert mu["camelot_measured"] == "7A"
    plain = prefer_tags({"bpm": 120.0, "key": "C major", "camelot": "8B"}, {"bpm": "", "key": ""})
    assert "bpm_from_tags" not in plain and plain["camelot"] == "8B"
