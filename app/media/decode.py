"""Full decode pass + spectrum in one streaming read, so memory stays small even for long files."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .tools import find_tool, popen

N_FFT = 4096
COLUMNS = 1000          # spectrogram width
MAX_FRAMES = 4000       # hard cap on spectra kept in memory (~33 MB at float32)
CHUNK = 1 << 20         # bytes read from FFmpeg per step


@dataclass
class DecodeResult:
    ok_exit: bool = False
    exit_code: int | None = None
    timed_out: bool = False
    decoded_s: float = 0.0
    sample_rate_hz: int = 0
    error_lines: list[str] = field(default_factory=list)
    error_count: int = 0
    peak: float = 0.0
    frames: np.ndarray | None = None     # (columns, N_FFT/2+1) power spectra

    def avg_spectrum_db(self) -> np.ndarray | None:
        if self.frames is None or len(self.frames) == 0:
            return None
        return 10 * np.log10(self.frames.mean(axis=0) + 1e-20)


def decode_and_analyze(path: Path, sample_rate_hz: int, expected_s: float | None,
                       ffmpeg_override: str = "", timeout: float = 600) -> DecodeResult:
    res = DecodeResult(sample_rate_hz=sample_rate_hz)
    exe = find_tool("ffmpeg", ffmpeg_override)
    args = [exe, "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
            "-ar", str(sample_rate_hz), "-f", "f32le", "-acodec", "pcm_f32le", "-"]
    proc = popen(args)

    err_buf: list[bytes] = []

    def drain_stderr():
        total = 0
        for line in proc.stderr:
            total += 1
            if len(err_buf) < 200:
                err_buf.append(line)
        err_buf.append(b"__COUNT__%d" % total)

    t = threading.Thread(target=drain_stderr, daemon=True)
    t.start()

    expected_samples = int((expected_s or 300) * sample_rate_hz)
    hop = max(N_FFT, expected_samples // COLUMNS)
    window = np.hanning(N_FFT).astype(np.float32)
    frames: list[np.ndarray] = []
    buf = np.zeros(0, dtype=np.float32)
    buf_start = 0            # absolute sample index of buf[0]
    next_pos = 0
    total = 0
    leftover = b""
    peak = 0.0
    started = time.monotonic()

    while True:
        if time.monotonic() - started > timeout:
            proc.kill()
            res.timed_out = True
            break
        raw = proc.stdout.read(CHUNK)
        if not raw:
            break
        raw = leftover + raw
        usable = len(raw) - (len(raw) % 4)
        leftover = raw[usable:]
        x = np.frombuffer(raw[:usable], dtype=np.float32)
        if x.size == 0:
            continue
        peak = max(peak, float(np.max(np.abs(x))))
        total += x.size
        buf = np.concatenate([buf, x])
        while next_pos + N_FFT <= buf_start + buf.size:
            i = next_pos - buf_start
            seg = buf[i:i + N_FFT] * window
            if len(frames) < MAX_FRAMES:               # a lying duration header can't grow this without bound
                frames.append((np.abs(np.fft.rfft(seg)) ** 2).astype(np.float32))
            next_pos += hop
        drop = max(0, min(next_pos, buf_start + buf.size) - buf_start)
        buf = buf[drop:]
        buf_start += drop

    try:
        proc.wait(timeout=30)
    except Exception:
        proc.kill()
        proc.wait(timeout=10)
    t.join(timeout=5)
    for stream in (proc.stdout, proc.stderr):          # pipes are OS handles; never leave them to the GC
        try:
            stream.close()
        except Exception:
            pass
    res.exit_code = proc.returncode
    res.ok_exit = proc.returncode == 0 and not res.timed_out
    res.decoded_s = total / sample_rate_hz if sample_rate_hz else 0.0
    res.peak = peak
    if err_buf and err_buf[-1].startswith(b"__COUNT__"):
        res.error_count = int(err_buf.pop()[9:])
    res.error_lines = [ln.decode("utf-8", "replace").strip() for ln in err_buf[:20]]
    res.frames = np.array(frames, dtype=np.float32) if frames else None
    return res


def estimate_cutoff_hz(avg_db: np.ndarray, sample_rate_hz: int, drop_db: float = 40.0) -> float | None:
    """Highest frequency that still carries real energy: within `drop_db` of the 1-8 kHz level."""
    freqs = np.fft.rfftfreq(N_FFT, 1 / sample_rate_hz)
    band = avg_db[(freqs > 1000) & (freqs < 8000)]
    if band.size == 0:
        return None
    ref = float(np.median(band))
    above = np.where(avg_db > ref - drop_db)[0]
    return float(freqs[above[-1]]) if above.size else None
