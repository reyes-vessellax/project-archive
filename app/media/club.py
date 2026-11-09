"""Club-ready: will this file load and sound right on a club or festival system?

Separate from the Good / Have a look / Broken verdict (which is about whether the file is what it claims).
Six things, each in plain English:

1. Decks can load it   Pioneer CDJs / Rekordbox: MP3, WAV, AIFF, FLAC (AAC too); up to 96 kHz; 16 or 24 bit.
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
SR_OK = (44100, 48000, 88200, 96000)


def club_checks(path: Path, facts, avg_spectrum_db=None, decode_sr: int | None = None, ffmpeg_override: str = "",
                timeout: float = 180.0) -> dict:
    checks = [_loads(path, facts)]
    stats = _measure(path, ffmpeg_override, timeout)
    checks.append(_mono(path, facts, ffmpeg_override, timeout))
    checks.append(_clipping(stats))
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
        return Check("club_load", FAIL, "Decks can load it", f".{ext} ({codec or '?'}) won't load on CDJs or in Rekordbox.")
    if codec.startswith(("pcm_f32", "pcm_f64")) or (f.bit_depth or 0) > 24:
        return Check("club_load", FAIL, "Decks can load it",
                     "32-bit float audio: CDJs and Rekordbox refuse it. A 24-bit copy plays everywhere.")
    sr = f.sample_rate_hz or 0
    if sr > 96000:
        return Check("club_load", FAIL, "Decks can load it", f"{sr / 1000:g} kHz: CDJs play up to 96 kHz.")
    if ext == "m4a":
        return Check("club_load", WARN, "Decks can load it",
                     "M4A/AAC loads in Rekordbox and on CDJs, but older players and USB sticks are fussier with it. "
                     "AIFF, WAV, FLAC or MP3 are the safe picks.")
    if sr and sr not in SR_OK:
        return Check("club_load", WARN, "Decks can load it", f"Unusual sample rate ({sr} Hz); 44.1 or 48 kHz is safest.")
    detail = f"{ext.upper()}, {sr / 1000:g} kHz" + (f", {f.bit_depth}-bit" if f.bit_depth else "")
    return Check("club_load", PASS, "Decks can load it", f"{detail}: plays on CDJs and in Rekordbox.")


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
    """Overall phase correlation, plus what happens to the bass (< 150 Hz) when the system sums to mono."""
    eL, eR = float(np.dot(L, L)), float(np.dot(R, R))
    if eL < 1e-9 or eR < 1e-9:
        return Check("club_mono", PASS, "Mono-safe", "One side is silent; it sums to mono unchanged.")
    corr = float(np.dot(L, R) / np.sqrt(eL * eR))
    M, S = (L + R) / 2, (L - R) / 2
    n = 8192
    low_m = low_s = 0.0
    for i in range(0, len(M) - n, n * 4):                     # every 4th block is plenty
        fm, fs = np.fft.rfft(M[i:i + n]), np.fft.rfft(S[i:i + n])
        k = int(150 * n / sr)
        low_m += float(np.sum(np.abs(fm[1:k]) ** 2)); low_s += float(np.sum(np.abs(fs[1:k]) ** 2))
    bass_side = low_s / (low_m + low_s + 1e-12)                # share of the bass that disappears in mono
    if bass_side > 0.5 or corr < -0.2:
        return Check("club_mono", FAIL, "Mono-safe",
                     f"Out of phase: on a mono-summed system about {bass_side * 100:.0f}% of the bass cancels "
                     f"(correlation {corr:+.2f}). The kick and bass can vanish on a big rig.")
    if bass_side > 0.2 or corr < 0.2:
        return Check("club_mono", WARN, "Mono-safe",
                     f"Very wide stereo (correlation {corr:+.2f}, {bass_side * 100:.0f}% of the bass in the sides). "
                     "It may lose weight on a mono system.")
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


def _clipping(st: dict) -> Check | None:
    pk, n, flat = st.get("peak_db"), st.get("peak_count"), st.get("flat")
    if pk is None:
        return None
    if pk >= -0.05 and ((n or 0) >= 200 or (flat or 0) >= 1.0):
        return Check("club_clip", WARN, "Clipping",
                     f"Hits full scale {int(n or 0):,} times: flat-topped peaks that turn harsh on a big system.")
    tp = st.get("true_peak")
    if tp is not None and tp > 1.0:
        return Check("club_clip", WARN, "Clipping", f"True peak {tp:+.1f} dBTP: it overshoots once converted to analogue.")
    return Check("club_clip", PASS, "Clipping", "No clipping found" + (f" (true peak {tp:+.1f} dBTP)." if tp is not None else "."))


def _loudness(st: dict) -> Check | None:
    i = st.get("lufs")
    if i is None:
        return None
    if i < -20:
        return Check("club_loud", WARN, "Loudness", f"{i:.1f} LUFS: much quieter than club records (about -10 to -6). "
                                                     "You'll be riding the gain.")
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
        return Check("club_low", WARN, "Low end", f"Thin bottom: the bass sits {abs(diff):.0f} dB under the mids "
                                                  "(a rolled-off rip, or a track with little bass).")
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
