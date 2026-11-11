"""Club-ready: will this file load and sound right on a club or festival system?

Separate from the Good / Have a look / Broken verdict (which is about whether the file is what it claims).
Six things, each in plain English:

1. Decks can load it   Pioneer CDJs, XDJs and Rekordbox: MP3, WAV, AIFF everywhere; FLAC on CDJ-3000/NXS2 and newer
                        XDJs (XDJ-RX3), not older XDJs (RX2, RR) or pre-NXS2 CDJs; up to 96 kHz (48 on most XDJs).
                       32-bit float, 192 kHz, OGG/Opus/WMA won't load.
2. Mono-safe           Many club and festival rigs sum to mono. Out-of-phase stereo (bass in the "side") cancels:
                       the kick and bass vanish. Measured on a low-rate stereo decode.
3. Clipping            A master or rip pushed past full scale: flat-topped peaks that sound harsh on a big rig.
4. Loudness            Integrated loudness (LUFS) and true peak, so a track isn't far quieter or louder than a set.
5. Low end             Bass present (a rolled-off or thin bottom is usually a bad rip).
6. USB-safe            Huge embedded artwork slows CDJ browsing.

FAIL here = the decks can't load it, or the low end cancels in mono. Everything else is a WARN with the number.
Nothing here changes the file.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from ..core.rules import FAIL, PASS, WARN, Check
from .tools import find_tool, run

LOADS = {"mp3", "wav", "aiff", "aif", "flac", "m4a"}
TRACK_S = 90                 # shorter than this is a sample, a loop or an edit: no loudness / low-end verdicts


def club_checks(path: Path, facts, avg_spectrum_db=None, decode_sr: int | None = None, ffmpeg_override: str = "",
                timeout: float = 180.0) -> dict:
    checks = [_loads(path, facts)]
    stats = _measure(path, ffmpeg_override, timeout)
    dur = facts.duration_s or stats.get("duration") or 0
    checks.append(_mono(path, facts, ffmpeg_override, timeout))
    checks.append(_clipping(stats, dur))
    is_track = dur >= TRACK_S                                  # loudness and bass only mean something for a track
    if is_track:
        checks.append(_loudness(stats))
        if avg_spectrum_db is not None and decode_sr:
            checks.append(_low_end(avg_spectrum_db, decode_sr))
    checks.append(_usb(path))
    checks = [c for c in checks if c is not None]
    return {"ready": not any(c.status == FAIL for c in checks),
            "notes": sum(1 for c in checks if c.status == WARN),
            "checks": [c.to_dict() for c in checks],
            "lufs": stats.get("lufs"), "true_peak": stats.get("true_peak")}


# 1 ------------------------------------------------------------------------------------------------
def _loads(path: Path, f) -> Check:
    ext = path.suffix.lower().lstrip(".")
    codec = (f.codec or "").lower()
    if ext not in LOADS or codec.startswith(("vorbis", "opus", "wma")):
        return Check("club_load", FAIL, "Decks can load it", f".{ext} ({codec or '?'}) won't load on CDJs, XDJs or in Rekordbox.")
    if codec.startswith(("pcm_f32", "pcm_f64")) or (f.bit_depth or 0) > 24:
        return Check("club_load", FAIL, "Decks can load it",
                     "32-bit float audio: CDJs, XDJs and Rekordbox refuse it. A 24-bit copy plays everywhere.")
    sr = f.sample_rate_hz or 0
    if sr > 96000:
        return Check("club_load", FAIL, "Decks can load it", f"{sr / 1000:g} kHz: CDJs play up to 96 kHz, most XDJs up to 48 kHz.")
    if ext == "m4a":
        return Check("club_load", WARN, "Decks can load it",
                     "M4A/AAC loads in Rekordbox, on CDJ-2000NXS2/3000 and on XDJs, but older CDJs are fussier with it. "
                     "AIFF, WAV or MP3 play on every deck.")
    if sr in (88200, 96000):
        return Check("club_load", WARN, "Decks can load it",
                     f"{sr / 1000:g} kHz plays on CDJ-3000 and NXS2, but older CDJ-2000/900 and most XDJs only play "
                     "44.1 or 48 kHz. A club-ready copy plays on all of them.")
    if sr and sr not in (44100, 48000):
        return Check("club_load", WARN, "Decks can load it", f"Unusual sample rate ({sr} Hz); 44.1 or 48 kHz is safest.")
    detail = f"{ext.upper()}, {sr / 1000:g} kHz" + (f", {f.bit_depth}-bit" if f.bit_depth else "")
    if ext == "flac":
        return Check("club_load", PASS, "Decks can load it",
                     f"{detail}: plays in Rekordbox, on CDJ-3000/NXS2 and newer XDJs (XDJ-RX3). Older XDJs (RX2, RR) and pre-NXS2 "
                     "CDJs don't read FLAC: make a club-ready copy for those.")
    return Check("club_load", PASS, "Decks can load it", f"{detail}: plays on every CDJ and XDJ and in Rekordbox.")


# 2 ------------------------------------------------------------------------------------------------
def _mono(path: Path, f, override: str, timeout: float) -> Check | None:
    if (f.channels or 2) < 2:
        return Check("club_mono", PASS, "Mono-safe", "A mono file: nothing can cancel.")
    exe = find_tool("ffmpeg", override)
    sr = 11025
    try:
        proc = run([exe, "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0", "-t", "600", "-ac", "2",
                    "-ar", str(sr), "-f", "f32le", "-acodec", "pcm_f32le", "-"], timeout)
        x = np.frombuffer(proc.stdout, dtype="<f4")
    except Exception:
        return None
    if x.size < sr * 4:
        return None
    x = x[: x.size // 2 * 2].reshape(-1, 2).astype(np.float64)
    return mono_verdict(x[:, 0], x[:, 1], sr)


def mono_verdict(L: np.ndarray, R: np.ndarray, sr: int) -> Check:
    """What a mono-summed system does to it: the level lost overall, and the bass lost below 150 Hz.
    Bass is only judged when the file has real bass (a hat loop's "bass" is noise and proves nothing)."""
    eL, eR = float(np.dot(L, L)), float(np.dot(R, R))
    if eL < 1e-9 or eR < 1e-9:
        return Check("club_mono", PASS, "Mono-safe", "One side is silent; it sums to mono unchanged.")
    corr = float(np.dot(L, R) / np.sqrt(eL * eR))
    M = (L + R) / 2
    loss_all = 10 * np.log10(max(float(np.dot(M, M)), 1e-12) / ((eL + eR) / 2))   # 0 dB = identical sides
    n = 8192
    st_low = m_low = total = 0.0
    for i in range(0, len(M) - n, n * 4):                     # every 4th block is plenty
        fl, fr = np.fft.rfft(L[i:i + n]), np.fft.rfft(R[i:i + n])
        k = int(150 * n / sr)
        st_low += float(np.sum(np.abs(fl[1:k]) ** 2 + np.abs(fr[1:k]) ** 2)) / 2
        m_low += float(np.sum(np.abs((fl[1:k] + fr[1:k]) / 2) ** 2))
        total += float(np.sum(np.abs(fl) ** 2 + np.abs(fr) ** 2)) / 2
    has_bass = total > 0 and st_low / total > 0.05             # at least 5 % of the energy below 150 Hz
    loss_bass = 10 * np.log10(max(m_low, 1e-12) / st_low) if has_bass and st_low > 0 else 0.0
    if (has_bass and loss_bass < -6) or loss_all < -6:
        what = f"the bass drops {abs(loss_bass):.0f} dB" if has_bass and loss_bass < -6 else f"it drops {abs(loss_all):.0f} dB"
        return Check("club_mono", FAIL, "Mono-safe",
                     f"Out of phase: on a mono-summed system {what} (correlation {corr:+.2f}). "
                     "The kick and bass can vanish on a big rig.")
    if (has_bass and loss_bass < -3) or loss_all < -4:
        what = f"the bass drops {abs(loss_bass):.1f} dB" if has_bass and loss_bass < -3 else f"it drops {abs(loss_all):.1f} dB"
        return Check("club_mono", WARN, "Mono-safe",
                     f"Wide stereo: on a mono-summed system {what} (correlation {corr:+.2f}). It may lose weight there.")
    return Check("club_mono", PASS, "Mono-safe", f"Sums to mono cleanly (correlation {corr:+.2f}).")


# 3, 4 --------------------------------------------------------------------------------------------
def _measure(path: Path, override: str, timeout: float) -> dict:
    """One FFmpeg pass: astats (peak level, peak count, flat factor) and EBU R128 (LUFS, true peak)."""
    exe = find_tool("ffmpeg", override)
    try:
        proc = run([exe, "-nostdin", "-hide_banner", "-i", str(path), "-map", "0:a:0", "-t", "900",
                    "-af", "astats=metadata=0,ebur128=peak=true:framelog=quiet", "-f", "null", "-"], timeout)
        err = proc.stderr.decode("utf-8", "replace") if isinstance(proc.stderr, bytes) else (proc.stderr or "")
    except Exception:
        return {}
    return parse_stats(err)


def parse_stats(err: str) -> dict:
    out: dict = {}
    overall = err.split("Overall", 1)[1] if "Overall" in err else ""

    def grab(text, key):
        m = re.search(rf"{key}:\s*(-?[\d.]+|-?inf)", text)
        try:
            return float(m.group(1)) if m else None
        except ValueError:
            return None
    out["peak_db"] = grab(overall, r"Peak level dB")
    out["peak_count"] = grab(overall, r"Peak count")
    out["flat"] = grab(overall, r"Flat factor")
    summary = err.split("Summary:", 1)[1] if "Summary:" in err else ""
    out["lufs"] = grab(summary, r"\bI")
    tp = summary.split("True peak:", 1)[1] if "True peak:" in summary else ""
    out["true_peak"] = grab(tp, r"Peak")
    return out


def _clipping(st: dict, dur: float) -> Check | None:
    """Sustained clipping only: a master that sits on full scale hundreds of times, not a peak that touches it."""
    pk, n = st.get("peak_db"), st.get("peak_count") or 0
    if pk is None:
        return None
    per_min = n / max(dur / 60, 0.5)
    if pk >= -0.1 and n >= 500 and per_min >= 100:
        return Check("club_clip", WARN, "Clipping",
                     f"Sits on full scale {int(n):,} times: flat-topped peaks that turn harsh on a big system.")
    tp = st.get("true_peak")
    if tp is not None and tp > 2.0:
        return Check("club_clip", WARN, "Clipping", f"True peak {tp:+.1f} dBTP: hot enough to distort some converters.")
    return Check("club_clip", PASS, "Clipping", "No clipping found" + (f" (true peak {tp:+.1f} dBTP)." if tp is not None else "."))


def _loudness(st: dict) -> Check | None:
    i = st.get("lufs")
    if i is None or i <= -69:                                 # -70 is EBU R128's "nothing measurable", not a level
        return None
    if i < -20:
        return Check("club_loud", WARN, "Loudness", f"{i:.1f} LUFS: much quieter than most club records (about -14 to -6). "
                                                     "You'll need a lot more gain on this one.")
    if i > -4.5:
        return Check("club_loud", WARN, "Loudness", f"{i:.1f} LUFS: squashed very hard; it may sound flat and tiring loud.")
    return Check("club_loud", PASS, "Loudness", f"{i:.1f} LUFS: in the range of club records.")


# 5 ------------------------------------------------------------------------------------------------
def _low_end(avg_db: np.ndarray, sr: int) -> Check | None:
    p = 10 ** (np.asarray(avg_db, dtype=np.float64) / 10)
    n = (len(p) - 1) * 2
    hz = np.arange(len(p)) * sr / n
    low = p[(hz >= 30) & (hz < 120)].mean() if np.any((hz >= 30) & (hz < 120)) else 0
    mid = p[(hz >= 300) & (hz < 3000)].mean() if np.any((hz >= 300) & (hz < 3000)) else 0
    if low <= 0 or mid <= 0:
        return None
    diff = 10 * np.log10(low / mid)
    if diff < -20:
        return Check("club_low", WARN, "Low end", f"Little bass: it sits {abs(diff):.0f} dB under the mids. Fine for an "
                                                  "acapella, intro or tool; on a full track it usually means a rolled-off rip.")
    return Check("club_low", PASS, "Low end", "Bass is there.")


# 6 ------------------------------------------------------------------------------------------------
def _usb(path: Path) -> Check | None:
    try:
        import mutagen
        f = mutagen.File(str(path))
    except Exception:
        return None
    biggest = 0
    tags = getattr(f, "tags", None)
    if tags is not None and hasattr(tags, "getall"):
        biggest = max((len(a.data) for a in tags.getall("APIC")), default=0)
    elif getattr(f, "pictures", None):
        biggest = max(len(pic.data) for pic in f.pictures)
    if biggest > 1_500_000:
        return Check("club_usb", WARN, "USB-safe", f"Embedded artwork is {biggest / 1e6:.1f} MB; big covers make CDJ "
                                                   "browsing slow. Under 500 kB is plenty.")
    return Check("club_usb", PASS, "USB-safe", "Artwork and tags are a sensible size.")
