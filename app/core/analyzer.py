"""Analysis pipeline: hash -> probe -> full decode + spectrum -> rules. Accepts only a local staged path."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from ..config import Settings
from ..media.decode import decode_and_analyze, estimate_cutoff_hz
from ..media.probe import probe, sniff_magic
from ..media.spectrogram import render
from ..media import metadata as md
from ..media.musical import analyze_music
import re

MIX_WORDS = re.compile(r"mix|edit|dub|remix|rmx|version|rework|re-work|vip|instrumental|extended|original|club|radio|bootleg|flip|acapella|remaster", re.I)
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

    progress("Quick checks")
    pre = rules.prechecks(path, path.suffix, facts, magic, settings)
    if any(c.status == rules.FAIL for c in pre):
        return _result(digest, facts, magic, None, None, None, pre)   # not worth decoding

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
        d.frames = None                             # tens of MB per track: release before the next slot starts
        del d

    checks = pre + rules.evaluate(path.suffix, facts, decode, cutoff, settings)
    out = _result(digest, facts, magic, decode, cutoff, spec_path, checks)
    if facts.readable and out["decode_ok"]:
        progress("Finding BPM, key and the drop")
        out["music"] = analyze_music(path, settings.ffmpeg_path).to_dict()
        progress("Looking up cover art and details")
        out["meta"] = describe(path, settings)
    return out


def describe(path: Path, settings: Settings, fetch=None) -> dict:
    """What the track is: the file's own tags first, the file name next, then an online lookup for the gaps.
    The cover is saved next to the staged file (cover.jpg/png)."""
    from ..adapters.base import parse_track
    fetch = fetch or md.http_get                               # looked up at call time (tests swap it out)
    tags = md.read_tags(path)
    f_artist, f_title, f_mix = parse_track(path.name)
    if f_mix and not MIX_WORDS.search(f_mix):
        f_mix = ""                                             # "[M.A.D 019]", "[Defected]": a catalogue/label, not a mix
    meta = md.Meta(title=tags["title"] or f_title, artist=tags["artist"] or f_artist, mix=f_mix,
                   album=tags["album"], label=tags["label"], genre=tags["genre"], year=tags["year"], source="file")
    if tags["title"] and f_mix and f_mix.lower() in tags["title"].lower():
        meta.mix = ""                                          # the tag already says "(Extended Mix)"
    cover = md.cover_from_file(path, path.parent / "cover") if tags["has_cover"] else None
    found = None
    if getattr(settings, "online_lookup", True) and (not cover or not (meta.label and meta.genre and meta.year)):
        found = md.lookup(meta.artist, meta.title, fetch)
    if found:
        for k in ("album", "label", "catalog", "year", "genre"):
            if not getattr(meta, k):
                setattr(meta, k, getattr(found, k))
        meta.sources = ["file"] + found.sources
        if not cover and found.cover_url:
            cover = md.download_cover(found.cover_url, path.parent / "cover", fetch)
    out = meta.to_dict()
    out["cover_path"] = str(cover) if cover else None
    out["had_tags"] = bool(tags["title"] or tags["artist"])
    return out


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
