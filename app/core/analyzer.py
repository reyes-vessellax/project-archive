"""Analysis pipeline: hash -> probe -> full decode + spectrum -> rules. Accepts only a local staged path."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from ..config import Settings
from ..media.decode import decode_and_analyze, estimate_cutoff_hz
from ..media.probe import probe, sniff_magic
from ..media.spectrogram import render
from . import rules

Progress = Callable[[str], None]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def analyze(path: Path, settings: Settings, progress: Progress = lambda s: None) -> dict:
    progress("Fingerprinting")
    digest = sha256_file(path)

    progress("Probing")
    facts = probe(path, settings.ffmpeg_path)
    magic = sniff_magic(path)

    decode = None
    cutoff = None
    spec_path = None
    if facts.readable:
        if facts.duration_s and facts.duration_s > settings.max_duration_minutes * 60:
            checks = [rules.Check("format", rules.FAIL, "Length",
                                  f"Longer than the {settings.max_duration_minutes}-minute limit in Settings.")]
            return _result(digest, facts, magic, None, None, None, checks)
        progress("Decoding")
        sr = facts.sample_rate_hz or 44100
        timeout = max(120.0, (facts.duration_s or 600) * 1.5)
        d = decode_and_analyze(path, sr, facts.duration_s, settings.ffmpeg_path, timeout=timeout)
        decode = {"ok_exit": d.ok_exit, "exit_code": d.exit_code, "timed_out": d.timed_out,
                  "decoded_s": round(d.decoded_s, 3), "error_count": d.error_count,
                  "error_lines": d.error_lines, "peak": d.peak}
        progress("Generating spectrum")
        avg = d.avg_spectrum_db()
        if avg is not None:
            cutoff = estimate_cutoff_hz(avg, sr)
            try:
                spec_path = str(render(d.frames, path.parent / "spectrum.png"))
            except Exception:                       # spectrum is optional; never fabricate one
                spec_path = None

    checks = rules.evaluate(path.suffix, facts, decode, cutoff, settings)
    return _result(digest, facts, magic, decode, cutoff, spec_path, checks)


def _result(digest, facts, magic, decode, cutoff, spec_path, checks) -> dict:
    return {
        "sha256": digest,
        "facts": facts.to_dict(),
        "magic": magic,
        "decode": decode,
        "decode_ok": bool(decode and decode["ok_exit"]),
        "cutoff_hz": cutoff,
        "spectrogram_path": spec_path,
        "checks": [c.to_dict() for c in checks],
        "overall_status": rules.overall(checks),
    }
