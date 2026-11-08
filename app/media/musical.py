"""Musical facts for DJs: tempo (BPM), key (with Camelot code) and where the track gets going (the drop).

Everything is measured from a low-rate mono decode (11,025 Hz is plenty for rhythm and pitch below 2 kHz),
so this adds about a second per track. All of it is an estimate and is labelled as one in the UI.

- BPM: onset envelope (spectral flux) -> autocorrelation with a dance-music tempo prior -> refined on
  multi-beat lags for ~0.05 BPM precision.
- Key: notes standing above the spectral floor (a long FFT, tuning corrected), root from the
  Krumhansl-Kessler profiles, major/minor from the third. See estimate_key.
- Preview window: the drop (the biggest rise into the track's loudest stretch), started a couple of
  seconds early so you hear it land; if there's no clear drop, the loudest steady 20 seconds.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .tools import find_tool, run

SR = 11025
PREVIEW_S = 20.0
LEAD_IN_S = 2.0          # start the preview this long before the drop

NOTES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
# Camelot wheel: pitch class -> number, for major (B) and minor (A) keys.
CAMELOT_MAJOR = {0: 8, 7: 9, 2: 10, 9: 11, 4: 12, 11: 1, 6: 2, 1: 3, 8: 4, 3: 5, 10: 6, 5: 7}
CAMELOT_MINOR = {9: 8, 4: 9, 11: 10, 6: 11, 1: 12, 8: 1, 3: 2, 10: 3, 5: 4, 0: 5, 7: 6, 2: 7}
KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


@dataclass
class Musical:
    bpm: float | None = None
    key: str | None = None              # "A minor"
    camelot: str | None = None          # "8A"
    key_confidence: float | None = None  # 0..1, correlation margin; low = ambiguous
    drop_s: float | None = None         # where the drop lands, if there is a clear one
    preview_start_s: float | None = None
    preview_len_s: float = PREVIEW_S

    def to_dict(self) -> dict:
        return asdict(self)


def compatible_keys(camelot: str) -> set[str]:
    """Harmonic mixing on the Camelot wheel: same key, one step either way, or the relative major/minor."""
    try:
        n, letter = int(camelot[:-1]), camelot[-1].upper()
    except (ValueError, IndexError):
        return set()
    other = "B" if letter == "A" else "A"
    return {f"{n}{letter}", f"{n % 12 + 1}{letter}", f"{(n - 2) % 12 + 1}{letter}", f"{n}{other}"}


def decode_low(path: Path, ffmpeg_override: str = "", max_s: float = 1200.0, timeout: float = 120.0) -> np.ndarray:
    exe = find_tool("ffmpeg", ffmpeg_override)
    args = [exe, "-v", "error", "-nostdin", "-i", str(path), "-t", str(max_s), "-vn", "-ac", "1", "-ar", str(SR),
            "-f", "f32le", "-"]
    proc = run(args, timeout=timeout)
    return np.frombuffer(proc.stdout, dtype="<f4").astype(np.float32)


def analyze_music(path: Path, ffmpeg_override: str = "", timeout: float = 120.0) -> Musical:
    try:
        y = decode_low(path, ffmpeg_override, timeout=timeout)
    except Exception:
        return Musical()
    return analyze_samples(y)


def analyze_samples(y: np.ndarray, sr: int = SR) -> Musical:
    if y.size < sr * 8 or not np.isfinite(y).all() or float(np.max(np.abs(y))) < 1e-4:
        return Musical()
    m = Musical()
    m.bpm = estimate_bpm(y, sr)
    key = estimate_key(y, sr)
    if key:
        m.key, m.camelot, m.key_confidence = key
    m.drop_s, m.preview_start_s = find_preview(y, sr)
    return m


# ------------------------------------------------------------------------------------------- tempo
def _frames(y: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    n = 1 + (len(y) - n_fft) // hop
    if n <= 0:
        return np.zeros((0, n_fft), dtype=np.float32)
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    return y[idx]


def onset_envelope(y: np.ndarray, sr: int = SR, n_fft: int = 1024, hop: int = 128) -> tuple[np.ndarray, float]:
    win = np.hanning(n_fft).astype(np.float32)
    env_parts = []
    prev = None
    step = 4096                                    # frames per batch keeps memory flat on long tracks
    total = 1 + (len(y) - n_fft) // hop
    for start in range(0, max(total, 0), step):
        seg = y[start * hop: (start + step) * hop + n_fft]
        fr = _frames(seg, n_fft, hop)[:step]
        if not len(fr):
            break
        mag = np.log1p(100.0 * np.abs(np.fft.rfft(fr * win, axis=1)))
        if prev is not None:
            mag_full = np.vstack([prev[None, :], mag])
        else:
            mag_full = np.vstack([mag[:1], mag])
        flux = np.maximum(np.diff(mag_full, axis=0), 0.0).sum(axis=1)
        env_parts.append(flux)
        prev = mag[-1]
    env = np.concatenate(env_parts) if env_parts else np.zeros(0)
    if env.size:
        # remove the slow trend so loud sections don't dominate, keep the peaks
        k = int(sr / hop)                           # ~1 s moving average
        trend = np.convolve(env, np.ones(k) / k, mode="same")
        env = np.maximum(env - trend, 0.0)
    return env.astype(np.float64), sr / hop


def _acf(x: np.ndarray) -> np.ndarray:
    x = x - x.mean()
    n = 1 << int(np.ceil(np.log2(2 * len(x))))
    f = np.fft.rfft(x, n)
    r = np.fft.irfft(f * np.conj(f), n)[: len(x)]
    return r / (r[0] + 1e-12)


def estimate_bpm(y: np.ndarray, sr: int = SR, lo: float = 70.0, hi: float = 180.0) -> float | None:
    env, fps = onset_envelope(y, sr)
    if env.size < fps * 8 or env.max() <= 0:
        return None
    r = _acf(env)

    def score(bpm: float) -> float:
        # comb over 1..16 beats with linear interpolation: long lags give fine tempo resolution
        s = 0.0
        for k in range(1, 17):
            lag = k * 60.0 * fps / bpm
            i = int(lag)
            if i + 1 >= len(r):
                break
            s += (r[i] + (lag - i) * (r[i + 1] - r[i])) * (1.0 if k % 4 else 1.5)
        return s

    def prior(b: float) -> float:                                  # dance music clusters around 120-130
        return float(np.exp(-0.5 * (np.log2(b / 124.0) / 0.6) ** 2))

    grid = np.arange(lo, hi, 0.5)
    raw = np.array([score(b) for b in grid])
    best = float(grid[int(np.argmax(raw))])
    # The prior only settles double/half-time (the classic ambiguity); it never picks a 2/3 or 3/2 tempo.
    cands = [b for b in (best, best * 2, best / 2) if lo <= b < hi]
    best = max(cands, key=lambda b: score(b) * (0.7 + 0.3 * prior(b)))
    fine = np.arange(best - 0.6, best + 0.6, 0.02)
    best = float(fine[int(np.argmax([score(b) for b in fine]))])
    if abs(best - round(best)) <= 0.08:              # most club tracks sit on a whole number
        best = float(round(best))
    return round(best, 2)


# --------------------------------------------------------------------------------------------- key
def _box(x: np.ndarray, size: int) -> np.ndarray:
    """Moving average along the last axis (numpy only)."""
    k = size // 2
    c = np.cumsum(np.pad(x, ((0, 0), (k + 1, k)), mode="edge"), axis=1)
    return (c[:, size:] - c[:, :-size]) / size


def chroma(y: np.ndarray, sr: int = SR, n_fft: int = 16384, hop: int = 8192) -> np.ndarray:
    """How much of each of the 12 notes the track holds, 40 Hz-3 kHz.

    Tested against 97 Rekordbox-analysed club tracks (see tools/accuracy.py), each choice earned its place:
    - a long FFT (0.7 Hz resolution) so bass notes land on the right semitone;
    - only what stands above the local spectral floor counts: hats, noise and the body of a kick sit on the
      floor, notes stick out of it (this alone took agreement with Rekordbox from ~45% to ~55%);
    - every moment votes equally (per-frame normalisation), so a loud drop doesn't drown the breakdown;
    - tuning: vinyl rips and pitched edits sit up to half a semitone off A440; the offset is measured from
      the spectral peaks and taken out before notes are counted.
    """
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    band = (freqs >= 40.0) & (freqs <= 3000.0)
    f = freqs[band]
    win = np.hanning(n_fft).astype(np.float32)
    n = 1 + (len(y) - n_fft) // hop
    total = np.zeros(int(band.sum()))
    for start in range(0, max(n, 0), 64):
        fr = _frames(y[start * hop: (start + 64) * hop + n_fft], n_fft, hop)[:64]
        if not len(fr):
            break
        X = np.abs(np.fft.rfft(fr * win, axis=1))[:, band]
        X = np.maximum(X - _box(X, 41), 0.0)
        total += (X / (X.sum(axis=1, keepdims=True) + 1e-9)).sum(axis=0)
    semis = 12 * np.log2(f / 440.0)
    sel = (f >= 100) & (f <= 1500)
    x, s = total[sel], semis[sel]
    if x.size > 2:
        pk = np.r_[False, (x[1:-1] > x[:-2]) & (x[1:-1] > x[2:]), False]
        z = np.sum(x[pk] * np.exp(2j * np.pi * (s[pk] - np.round(s[pk]))))
        if abs(z) / (x[pk].sum() + 1e-12) > 0.05:                   # only when the peaks agree on an offset
            semis = semis - np.angle(z) / (2 * np.pi)
    c = np.bincount((np.round(semis).astype(int) + 9) % 12, weights=total, minlength=12)   # 0 = C
    return c / (c.sum() + 1e-12)


MINOR_PRIOR = 0.06      # club music leans minor; a small nudge, not a rule (major tracks still come out major)
THIRD_RATIO = 0.5       # minor unless the major third clearly outweighs the minor third


def estimate_key(y: np.ndarray, sr: int = SR) -> tuple[str, str, float] | None:
    """Root from the Krumhansl-Kessler profiles; major or minor from the third above that root.
    Deciding the mode separately fixed the commonest mistake: calling a minor club track its parallel major."""
    c = chroma(y, sr)
    if not np.isfinite(c).all() or c.max() <= 0:
        return None
    s_maj = np.array([np.corrcoef(c, np.roll(KK_MAJOR, t))[0, 1] for t in range(12)])
    s_min = np.array([np.corrcoef(c, np.roll(KK_MINOR, t))[0, 1] for t in range(12)]) + MINOR_PRIOR
    t_maj, t_min = int(np.argmax(s_maj)), int(np.argmax(s_min))
    tonic = t_maj if s_maj[t_maj] > s_min[t_min] else t_min
    minor = c[(tonic + 3) % 12] >= THIRD_RATIO * c[(tonic + 4) % 12]
    mode = "minor" if minor else "major"
    camelot = f"{CAMELOT_MINOR[tonic]}A" if minor else f"{CAMELOT_MAJOR[tonic]}B"
    ranked = np.sort(np.concatenate([s_maj, s_min]))[::-1]
    best = float(s_min[tonic] if minor else s_maj[tonic])
    confidence = max(0.0, min(1.0, (ranked[0] - ranked[1]) * 5 + max(0.0, best) * 0.5))
    return f"{NOTES[tonic]} {mode}", camelot, round(confidence, 2)


# ----------------------------------------------------------------------------------------- preview
def loudness_per_second(y: np.ndarray, sr: int = SR) -> np.ndarray:
    n = len(y) // sr
    if n == 0:
        return np.zeros(0)
    rms = np.sqrt(np.mean(y[: n * sr].reshape(n, sr) ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-9)


def find_preview(y: np.ndarray, sr: int = SR, length: float = PREVIEW_S) -> tuple[float | None, float | None]:
    """(drop_s, preview_start_s). The preview always lies inside the track."""
    db = loudness_per_second(y, sr)
    n = len(db)
    L = int(length)
    if n <= L:
        return None, 0.0
    # smooth over 4 s so single hits and short fills don't count as a section
    smooth = np.convolve(db, np.ones(4) / 4, mode="same")
    loud_level = np.percentile(smooth, 85)
    floor = np.percentile(smooth, 20)

    span = 8
    cands = []
    for t in range(span, int(n * 0.85) - span):
        before = smooth[t - span: t].mean()
        after = smooth[t: t + span].mean()
        # a drop: a clear rise (>= 4 dB) that lands in the loud part of the track
        if after - before >= 4.0 and after >= loud_level - 1.5:
            cands.append((after - before, t))
    sharp = []
    for rise, t in cands:
        # the 4 s smoothing blurs the edge: pin it to the sharpest one-second jump nearby. A build-up that
        # just gets gradually louder has no sharp edge, so it isn't a drop.
        lo, hi = max(1, t - 5), min(n - 1, t + 3)
        jumps = np.diff(db[lo - 1: hi + 1])[: hi - lo + 1]
        if jumps.max() >= 3.0:
            sharp.append((rise, lo + int(np.argmax(jumps))))
    if sharp:
        # the FIRST big drop is the one you'd preview; later ones usually follow a breakdown
        top = max(r for r, _ in sharp)
        drop = min(t for r, t in sharp if r >= 0.7 * top)
        start = max(0.0, min(drop - LEAD_IN_S, n - length))
        return float(drop), float(start)

    # no clear drop: the loudest 20 s with no dead spots (penalise the quietest second in the window)
    best_s, best_score = 0, -1e9
    for s in range(0, n - L + 1):
        w = db[s: s + L]
        score = w.mean() + 0.5 * w.min() - (5.0 if w.min() < floor else 0.0)
        if score > best_score:
            best_s, best_score = s, score
    return None, float(best_s)
