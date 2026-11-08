"""The trainable key model and the scoring used to test it. numpy only.

Features: the same peak-above-the-floor spectrum DigMart's chroma uses (app.media.musical), tuned to A440, folded
into 12 notes for three bands (40-3000 Hz, bass 40-250 Hz, 250-3000 Hz) plus a log of the full-band chroma.

Model: a linear score for each of the 24 keys. The features are rotated so the candidate tonic sits at index 0,
and one weight vector per mode scores them, so every training track teaches all 12 transpositions at once.
Trained with softmax cross-entropy (Adam). A hidden layer was tried and did not help on this much data.
"""
from __future__ import annotations

import re

import numpy as np

from app.media import musical as M

BANDS = [(40, 3000), (40, 250), (250, 3000)]
NAMES = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7,
         "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
MIREX = {"exact": 1.0, "fifth": 0.5, "relative": 0.3, "parallel": 0.2, "other": 0.0}


def parse(text: str):
    """'D# minor' -> (3, True). None if it isn't a single major/minor key."""
    m = re.fullmatch(r"([A-G][#b]?)\s*(major|minor)", text.strip())
    return (NAMES[m.group(1)], m.group(2) == "minor") if m else None


def relation(got, want) -> str:
    (gt, gm), (wt, wm) = got, want
    if got == want:
        return "exact"
    if gm == wm and (gt - wt) % 12 in (5, 7):
        return "fifth"
    if gm != wm and ((not wm and gt == (wt + 9) % 12) or (wm and gt == (wt + 3) % 12)):
        return "relative"
    if gt == wt:
        return "parallel"
    return "other"


def _box(x: np.ndarray, size: int) -> np.ndarray:
    """Moving average along the last axis (kept here so these tools work with any version of the app)."""
    k = size // 2
    c = np.cumsum(np.pad(x, ((0, 0), (k + 1, k)), mode="edge"), axis=1)
    return (c[:, size:] - c[:, :-size]) / size


def spectrum(y: np.ndarray, sr: int = M.SR, n_fft: int = 16384, hop: int = 8192):
    """(freqs, tuned semitones from A440, summed peak energy) for one track."""
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    band = (freqs >= 30) & (freqs <= 4000)
    f = freqs[band]
    win = np.hanning(n_fft).astype(np.float32)
    total = np.zeros(int(band.sum()))
    n = 1 + (len(y) - n_fft) // hop
    for start in range(0, max(n, 0), 64):
        fr = M._frames(y[start * hop: (start + 64) * hop + n_fft], n_fft, hop)[:64]
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
        if abs(z) / (x[pk].sum() + 1e-12) > 0.05:
            semis = semis - np.angle(z) / (2 * np.pi)
    return f, semis, total


def features(f, semis, total) -> np.ndarray:
    """(4, 12): three band chromas + log of the full-band chroma. Index 0 = C."""
    cs = []
    for lo, hi in BANDS:
        m = (f >= lo) & (f <= hi)
        c = np.bincount((np.round(semis[m]).astype(int) + 9) % 12, weights=total[m], minlength=12)
        cs.append(c / (c.sum() + 1e-12))
    cs.append(np.log(cs[0] + 1e-3))
    return np.stack(cs)


def rolled(F: np.ndarray) -> np.ndarray:
    """(N, 4, 12) -> (N, 12 tonics, 48): features rotated so each candidate tonic sits at index 0."""
    return np.stack([np.roll(F, -t, axis=2).reshape(len(F), -1) for t in range(12)], 1)


def _softmax(L):
    p = np.exp(L - L.max(1, keepdims=True))
    return p / p.sum(1, keepdims=True)


class KeyModel:
    def __init__(self, U=None, b=None, mu=None, sd=None):
        self.U, self.b, self.mu, self.sd = U, b, mu, sd

    def logits(self, R):
        O = ((R - self.mu) / self.sd) @ self.U + self.b           # (N, 12, 2)
        return np.concatenate([O[..., 0], O[..., 1]], 1)            # (N, 24): 12 major then 12 minor

    def predict(self, R):
        k = self.logits(R).argmax(1)
        return [(int(i % 12), bool(i >= 12)) for i in k]

    def fit(self, R, y, l2=1e-2, epochs=150, lr=0.01, batch=128, seed=0):
        flat = R.reshape(-1, R.shape[-1])
        self.mu, self.sd = flat.mean(0), flat.std(0) + 1e-9
        Z = (R - self.mu) / self.sd
        d = Z.shape[-1]
        self.U, self.b = np.zeros((d, 2)), np.zeros(2)
        tgt = np.array([t + 12 * m for t, m in y])
        rng = np.random.default_rng(seed)
        mom = {"U": np.zeros_like(self.U), "b": np.zeros_like(self.b)}
        var = {"U": np.zeros_like(self.U), "b": np.zeros_like(self.b)}
        step = 0
        for _ in range(epochs):
            for bi in np.array_split(rng.permutation(len(Z)), max(1, len(Z) // batch)):
                Zb = Z[bi]
                O = Zb @ self.U + self.b
                P = _softmax(np.concatenate([O[..., 0], O[..., 1]], 1))
                P[np.arange(len(bi)), tgt[bi]] -= 1
                P /= len(bi)
                dO = np.stack([P[:, :12], P[:, 12:]], -1)
                g = {"U": np.einsum("btk,btd->dk", dO, Zb) + l2 * self.U, "b": dO.sum((0, 1))}
                step += 1
                for k, p in (("U", self.U), ("b", self.b)):
                    mom[k] = 0.9 * mom[k] + 0.1 * g[k]
                    var[k] = 0.999 * var[k] + 0.001 * g[k] ** 2
                    p -= lr * (mom[k] / (1 - 0.9 ** step)) / (np.sqrt(var[k] / (1 - 0.999 ** step)) + 1e-8)
        return self

    def save(self, path):
        np.savez(path, U=self.U, b=self.b, mu=self.mu, sd=self.sd, bands=np.array(BANDS))

    @classmethod
    def load(cls, path):
        z = np.load(path)
        return cls(z["U"], z["b"], z["mu"], z["sd"])


def score(pred, truth) -> dict:
    rel = [relation(p, t) for p, t in zip(pred, truth)]
    n = len(rel)
    out = {r: rel.count(r) / n for r in MIREX}
    out["weighted"] = sum(MIREX[r] for r in rel) / n
    out["n"] = n
    return out
