"""Turn decoded spectra into a PNG. Pure numpy + zlib, so the engine needs no UI library."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

HEIGHT = 512
# warm "amber readout" map (design v7): black -> deep brown -> orange -> amber -> pale gold.
# Monotonic in brightness, so quiet vs loud and the frequency cutoff stay easy to read.
STOPS = np.array([[8, 5, 3], [42, 18, 4], [98, 40, 3], [168, 78, 0], [222, 128, 6],
                  [255, 176, 0], [255, 214, 92], [255, 244, 200]], dtype=np.float32)


def _colormap(v: np.ndarray) -> np.ndarray:
    pos = np.clip(v, 0, 1) * (len(STOPS) - 1)
    lo = np.floor(pos).astype(int)
    hi = np.minimum(lo + 1, len(STOPS) - 1)
    t = (pos - lo)[..., None]
    return (STOPS[lo] * (1 - t) + STOPS[hi] * t).astype(np.uint8)


def render(frames: np.ndarray, out: Path, floor_db: float = -110.0) -> Path:
    db = 10 * np.log10(frames + 1e-20)                    # (cols, bins)
    db -= db.max()
    bins = db.shape[1]
    edges = np.linspace(0, bins, HEIGHT + 1).astype(int)
    pooled = np.stack([db[:, a:max(b, a + 1)].max(axis=1) for a, b in zip(edges[:-1], edges[1:])], axis=1)
    img = _colormap((pooled - floor_db) / -floor_db)       # (cols, HEIGHT, 3)
    img = np.transpose(img, (1, 0, 2))[::-1]               # rows = freq, high at top
    write_png(out, np.ascontiguousarray(img))
    return out


def write_png(path: Path, rgb: np.ndarray) -> None:
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    Path(path).write_bytes(png)
