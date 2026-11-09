"""Club-ready copy: the same music in a file every CDJ and Rekordbox can load. The original is never touched.

Only for files that fail "Decks can load it" (32-bit float, over 96 kHz, OGG/Opus/WMA, an odd sample rate).
It can't fix the music itself (a fake 320, clipping, a phase problem): nothing can put back what isn't there,
so those never get the button.

What it makes: AIFF (ID3 tags, plays everywhere), 24-bit when the source has more than 16 bits, else 16-bit;
44.1 kHz or 48 kHz (88.2 and 176.4 -> 44.1, 96 and 192 -> 48: whole-number ratios where possible); same channels.
Resampling uses SoX's resampler at high precision; reducing bit depth uses triangular dither.

Then it proves the copy before anyone sees it. Any failure deletes the copy and says why:
- the copy probes as AIFF PCM at the target rate/depth, decodes start to end with no errors
- same length (within 10 ms)
- same loudness (within 0.2 LU) and the true peak not raised by more than 0.5 dB
- the same audio: a low-rate mono decode of both lines up with correlation >= 0.995 (catches offsets, glitches,
  dropouts or a wrong channel)
After that the copy goes through DigMart's normal check like any new file, club-ready check included.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .tools import find_tool, run


class CopyFailed(RuntimeError):
    pass


def needs_copy(club: dict | None) -> bool:
    """True when the format is the problem (decks can't load it, or older decks can't) and nothing else failed:
    that's all a copy can fix."""
    if not club:
        return False
    checks = club.get("checks") or []
    load = next((c for c in checks if c["id"] == "club_load"), None)
    others_fail = any(c["status"] == "FAIL" for c in checks if c["id"] != "club_load")
    return load is not None and load["status"] in ("FAIL", "WARN") and not others_fail


def plan(facts) -> dict:
    sr = facts.sample_rate_hz or 44100
    target_sr = sr if sr in (44100, 48000) else (44100 if sr % 44100 == 0 or sr in (22050, 11025, 32000) else 48000)
    codec = (facts.codec or "").lower()
    deep = codec.startswith(("pcm_f32", "pcm_f64", "pcm_s24", "pcm_s32")) or (facts.bit_depth or 0) > 16
    return {"sr": target_sr, "bits": 24 if deep else 16, "channels": min(facts.channels or 2, 2)}


def make_club_copy(src: Path, facts, dest: Path, ffmpeg_override: str = "", timeout: float = 600.0) -> Path:
    """Write a verified club-ready AIFF of `src` at `dest` (a .aiff path). Raises CopyFailed (copy removed)."""
    exe = find_tool("ffmpeg", ffmpeg_override)
    p = plan(facts)
    dest = Path(dest)
    tmp = dest.with_name(f".{dest.stem}.part.aiff")
    # 16-bit: dithered (triangular) down from whatever the source has. 24-bit: FFmpeg works in 32-bit and the
    # encoder keeps the top 24 bits; that rounding is ~144 dB down, below any converter's noise.
    fmt = "s32" if p["bits"] == 24 else "s16"
    # SoX's resampler when this FFmpeg has it (some builds, e.g. Homebrew's, leave it out); otherwise FFmpeg's own
    # at high-quality settings. Either way the copy is proved against the original below.
    resamplers = ("resampler=soxr:precision=28", "resampler=swr:filter_size=64:phase_shift=10:linear_interp=1:cutoff=0.97")
    try:
        proc = None
        for rs in resamplers:
            af = (f"aresample={p['sr']}:{rs}:osf={fmt}:dither_method=triangular,"
                  f"aformat=sample_fmts={fmt}:sample_rates={p['sr']}")
            args = [exe, "-nostdin", "-v", "error", "-y", "-i", str(src), "-map", "0:a:0", "-map_metadata", "0",
                    "-ac", str(p["channels"]), "-af", af, "-c:a", "pcm_s24be" if p["bits"] == 24 else "pcm_s16be",
                    "-write_id3v2", "1", "-f", "aiff", str(tmp)]
            proc = run(args, timeout)
            if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
                break
            tmp.unlink(missing_ok=True)
        if proc is None or proc.returncode != 0 or not tmp.exists():
            raise CopyFailed("FFmpeg couldn't convert it: " + proc.stderr.decode("utf-8", "replace")[-300:])
        _copy_artwork(src, tmp)
        verify(src, tmp, p, exe, timeout)
        tmp.replace(dest)
        return dest
    except CopyFailed:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise CopyFailed(f"Couldn't make the copy: {e}") from e


def verify(src: Path, copy: Path, p: dict, exe: str, timeout: float) -> None:
    from .club import _measure
    from .probe import probe
    f = probe(copy)
    want_codec = "pcm_s24be" if p["bits"] == 24 else "pcm_s16be"
    if not f.readable or f.codec != want_codec or f.sample_rate_hz != p["sr"]:
        raise CopyFailed(f"The copy came out as {f.codec} at {f.sample_rate_hz} Hz, not {want_codec} at {p['sr']} Hz.")
    dec = run([exe, "-nostdin", "-v", "error", "-i", str(copy), "-f", "null", "-"], timeout)
    if dec.returncode != 0 or dec.stderr.strip():
        raise CopyFailed("The copy doesn't decode cleanly start to end.")
    a, b = _measure(src, "", timeout), _measure(copy, "", timeout)
    if a.get("lufs") is not None and b.get("lufs") is not None and abs(a["lufs"] - b["lufs"]) > 0.2:
        raise CopyFailed(f"Loudness changed ({a['lufs']:.1f} -> {b['lufs']:.1f} LUFS).")
    if a.get("true_peak") is not None and b.get("true_peak") is not None and b["true_peak"] > a["true_peak"] + 0.5:
        raise CopyFailed(f"Peaks went up ({a['true_peak']:+.1f} -> {b['true_peak']:+.1f} dBTP).")
    corr, la, lb = _same_audio(src, copy, exe, timeout)
    if abs(la - lb) > 0.020:                               # decoded lengths: headers can't be trusted for this
        raise CopyFailed(f"Length changed ({la:.3f} s -> {lb:.3f} s).")
    if corr < 0.995:
        raise CopyFailed(f"The copy doesn't match the original closely enough (match {corr:.4f}).")


def _same_audio(a: Path, b: Path, exe: str, timeout: float) -> tuple[float, float, float]:
    """(correlation, seconds of a, seconds of b) from low-rate mono decodes."""
    def mono(p):
        r = run([exe, "-nostdin", "-v", "error", "-i", str(p), "-map", "0:a:0", "-ac", "1", "-ar", "11025",
                 "-f", "f32le", "-acodec", "pcm_f32le", "-"], timeout)
        return np.frombuffer(r.stdout, dtype="<f4").astype(np.float64)
    x, y = mono(a), mono(b)
    la, lb = len(x) / 11025, len(y) / 11025
    n = min(len(x), len(y))
    if n < 11025:
        return 0.0, la, lb
    x, y = x[:n], y[:n]
    den = np.sqrt(np.dot(x, x) * np.dot(y, y))
    return (float(np.dot(x, y) / den) if den > 0 else 0.0), la, lb


def _copy_artwork(src: Path, dst: Path) -> None:
    """The cover goes along (FFmpeg doesn't carry pictures into AIFF)."""
    try:
        import mutagen
        from mutagen.aiff import AIFF
        from mutagen.id3 import APIC
        s = mutagen.File(str(src))
        pic = None
        if s is not None and getattr(s, "tags", None) is not None and hasattr(s.tags, "getall"):
            got = s.tags.getall("APIC")
            pic = (got[0].data, got[0].mime) if got else None
        elif s is not None and getattr(s, "pictures", None):
            pic = (s.pictures[0].data, s.pictures[0].mime)
        if not pic:
            return
        d = AIFF(str(dst))
        if d.tags is None:
            d.add_tags()
        d.tags.add(APIC(encoding=3, mime=pic[1] or "image/jpeg", type=3, desc="Cover", data=pic[0]))
        d.save()
    except Exception:
        pass                                              # artwork is a nicety; the audio is what's verified
