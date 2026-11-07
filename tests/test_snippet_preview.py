"""Preview without downloading the whole track: partial file -> 10 s clip -> transfer cancelled, partial deleted."""
from pathlib import Path

import pytest

from app.adapters.base import Candidate, Transfer
from app.core.service import ActionBlocked
from tests.conftest import needs_ffmpeg


class FakeEngine:
    """Writes the real file into incomplete/ a chunk at a time, like the engine does while downloading."""
    def __init__(self, src: Path, incomplete: Path, queued_polls=0):
        self.data, self.inc, self.queued = src.read_bytes(), incomplete, queued_polls
        self.written, self.cancelled = 0, False

    def request_download(self, c):
        self.path = self.inc / "Music" / Path(c.remote_path.replace("\\\\", "/")).name
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return Transfer(transfer_id="t1", user=c.user, remote_path=c.remote_path, size=c.size, state="Requested")

    def transfer_status(self, t):
        if self.queued > 0:
            self.queued -= 1
            return Transfer(t.transfer_id, t.user, t.remote_path, t.size, state="Queued, Remotely")
        self.written = min(len(self.data), self.written + len(self.data) // 8)
        self.path.write_bytes(self.data[: self.written])
        return Transfer(t.transfer_id, t.user, t.remote_path, t.size, state="InProgress", bytes_done=self.written,
                        done=self.written >= len(self.data))

    def cancel(self, t):
        self.cancelled = True
        return True


def _cand(src: Path, ext: str) -> Candidate:
    return Candidate(source_kind="soulseek", user="u", remote_path=f"Music\\\\Track.{ext}", size=src.stat().st_size,
                     display_name=f"Track.{ext}", title="Track", extension=ext, length_s=40, free_slot=True)


@needs_ffmpeg
@pytest.mark.parametrize("kind,ext", [("mp3_320", "mp3"), ("flac", "flac"), ("source_wav", "wav")])
def test_snippet_without_the_whole_file(service, fixtures, monkeypatch, kind, ext):
    inc = Path(service.manager.instance_dir) / "incomplete"
    eng = FakeEngine(fixtures[kind], inc)
    monkeypatch.setattr(service, "_adapter_or_block", lambda: eng)
    wav, start = service.snippet_preview(_cand(fixtures[kind], ext), seconds=10)
    assert wav.exists() and wav.stat().st_size > 44100 * 4 * 8            # ~10 s of stereo audio
    assert eng.written < len(eng.data)                                    # stopped before the whole file
    assert eng.cancelled                                                  # rest of the download cancelled
    assert not eng.path.exists()                                          # partial file deleted
    assert 0 <= start <= 40


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
