"""Preview without downloading the track: read the header, jump to the middle, fetch ~20 s worth of bytes,
cut a clip, cancel, delete the partial. Busy copies are refused before anything is requested."""
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.adapters.base import Candidate, Transfer
from app.core import preview as pv
from app.core.service import ActionBlocked
from tests.conftest import FFMPEG, needs_ffmpeg


class FakeEngine:
    """Behaves like the engine: writes into incomplete/ a chunk per poll, and a new request RESUMES from
    wherever the partial file ends (it appends). Cancel stops writing; the partial stays on disk."""
    def __init__(self, src: Path, incomplete: Path, queued_polls=0, chunk_div=40):
        self.data, self.inc, self.queued = src.read_bytes(), incomplete, queued_polls
        self.chunk = max(4096, len(self.data) // chunk_div)
        self.sent, self.requests, self.cancelled, self.active = 0, 0, False, False
        self.offsets: list[int] = []

    def request_download(self, c):
        self.requests += 1
        self.path = self.inc / "u" / "Music" / Path(c.remote_path.replace("\\", "/")).name
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.pos = self.path.stat().st_size if self.path.exists() else 0
        self.offsets.append(self.pos)
        self.active = True
        return Transfer(transfer_id=f"t{self.requests}", user=c.user, remote_path=c.remote_path, size=c.size,
                        state="Requested")

    def transfer_status(self, t):
        if not self.active:
            return Transfer(t.transfer_id, t.user, t.remote_path, t.size, state="Completed, Cancelled", failed=True)
        if self.queued > 0:
            self.queued -= 1
            return Transfer(t.transfer_id, t.user, t.remote_path, t.size, state="Queued, Remotely")
        piece = self.data[self.pos:self.pos + self.chunk]
        with open(self.path, "ab") as fh:
            fh.write(piece)
        self.pos += len(piece); self.sent += len(piece)
        return Transfer(t.transfer_id, t.user, t.remote_path, t.size, state="InProgress", bytes_done=self.pos,
                        done=self.pos >= len(self.data))

    def cancel(self, t):
        self.cancelled, self.active = True, False
        return True


def _cand(src: Path, ext: str, **kw) -> Candidate:
    return Candidate(source_kind="soulseek", user="u", remote_path=f"Music\\Track.{ext}", size=src.stat().st_size,
                     display_name=f"Track.{ext}", title="Track", extension=ext, length_s=40, free_slot=True, **kw)


def _pcm(path: Path, ss: float = 0.0, t: float = 3.0) -> np.ndarray:
    raw = subprocess.run([FFMPEG, "-v", "error", "-ss", f"{ss}", "-t", f"{t}", "-i", str(path), "-ac", "1", "-ar", "44100",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32)


@needs_ffmpeg
@pytest.mark.parametrize("kind,ext", [("mp3_320", "mp3"), ("flac", "flac"), ("source_wav", "wav"), ("aiff", "aiff")])
def test_clip_comes_from_the_middle_without_the_bytes_before_it(service, fixtures, monkeypatch, kind, ext):
    monkeypatch.setattr("random.uniform", lambda a, b: 0.5)              # start at 20 s of 40
    inc = Path(service.manager.instance_dir) / "incomplete"
    eng = FakeEngine(fixtures[kind], inc)
    monkeypatch.setattr(service, "_adapter_or_block", lambda: eng)
    wav, start = service.snippet_preview(_cand(fixtures[kind], ext), seconds=10)
    assert abs(start - 20) < 0.01
    assert wav.exists() and wav.stat().st_size > 44100 * 4 * 8            # ~10 s of stereo audio
    assert eng.requests == 2 and eng.offsets[1] > len(eng.data) * 0.4     # second request resumed mid-file
    assert eng.sent < len(eng.data) * 0.45                                # far less than the 50% before the clip
    assert eng.cancelled and not eng.path.exists()                        # cancelled, partial deleted
    assert not (service.db.path.parent / "preview" / "partials.txt").exists()
    # it really is the audio at ~20 s: line it up against the source
    clip, ref = _pcm(wav, 0, 1.0), _pcm(fixtures[kind], 19.0, 3.0)
    corr = np.correlate(ref, clip, "valid") / (np.linalg.norm(clip) * np.sqrt(np.convolve(ref ** 2, np.ones(len(clip)), "valid")) + 1e-9)
    assert corr.max() > 0.9, corr.max()


@needs_ffmpeg
def test_other_formats_fall_back_to_the_start(service, fixtures, monkeypatch, tmp_path):
    src = tmp_path / "t.ogg"
    subprocess.run([FFMPEG, "-v", "error", "-i", str(fixtures["source_wav"]), "-c:a", "libvorbis", str(src)], check=True)
    service.settings.extensions = list(service.settings.extensions) + ["ogg"]
    eng = FakeEngine(src, Path(service.manager.instance_dir) / "incomplete")
    monkeypatch.setattr(service, "_adapter_or_block", lambda: eng)
    wav, start = service.snippet_preview(_cand(src, "ogg"), seconds=10)
    assert wav.exists() and eng.requests == 1               # straight from the start, no header trick
    assert not eng.path.exists()


def test_busy_copy_is_refused_before_any_request(service, fixtures, monkeypatch, tmp_path):
    src = tmp_path / "x.mp3"; src.write_bytes(b"\0" * 1000)
    eng = FakeEngine(src, Path(service.manager.instance_dir) / "incomplete")
    monkeypatch.setattr(service, "_adapter_or_block", lambda: eng)
    for kw in ({"free_slot": False}, {"queue_length": 4}):
        c = _cand(src, "mp3"); c.free_slot = kw.get("free_slot", True); c.queue_length = kw.get("queue_length", 0)
        with pytest.raises(ActionBlocked, match="wait"):
            service.snippet_preview(c)
    assert eng.requests == 0


@needs_ffmpeg
def test_queued_copy_says_so(service, fixtures, monkeypatch):
    import time
    eng = FakeEngine(fixtures["mp3_320"], Path(service.manager.instance_dir) / "incomplete", queued_polls=10_000)
    monkeypatch.setattr(service, "_adapter_or_block", lambda: eng)
    real = time.monotonic
    clock = {"t": real()}
    monkeypatch.setattr(time, "monotonic", lambda: clock.__setitem__("t", clock["t"] + 2) or clock["t"])
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with pytest.raises(ActionBlocked, match="wait"):
        service.snippet_preview(_cand(fixtures["mp3_320"], "mp3"))
    assert eng.cancelled


def test_purge_removes_clips_and_left_over_partials(service, tmp_path):
    out = service.db.path.parent / "preview"; out.mkdir(parents=True, exist_ok=True)
    (out / "old.wav").write_bytes(b"x")
    stray = tmp_path / "half.flac"; stray.write_bytes(b"x")
    (out / "partials.txt").write_text(str(stray) + "\n")
    assert service.purge_previews() == 2
    assert not stray.exists() and not list(out.glob("*.wav")) and not (out / "partials.txt").exists()


def test_header_readers():
    import struct
    fmt = struct.pack("<HHIIHH", 1, 2, 48000, 48000 * 6, 6, 24)
    wav = b"RIFF" + b"\0" * 4 + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"LIST" + struct.pack("<I", 3) + b"abc\0" \
        + b"data" + struct.pack("<I", 600)
    p = pv.wav_info(wav)
    assert (p.fmt, p.channels, p.rate, p.align, p.data_start) == ("s24le", 2, 48000, 6, len(wav))
    off, n, _ = pv.plan_offset("wav", wav, len(wav) + 48000 * 6 * 60, 60, 30, 10)
    assert (off - p.data_start) % 6 == 0 and n == 48000 * 6 * 10
    assert pv.flac_header(b"fLaC" + bytes([0, 0, 0, 34]) + b"\x11" * 34)[4] == 0x80
    assert pv.flac_header(b"ID3....") is None
