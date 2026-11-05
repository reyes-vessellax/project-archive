"""Synthetic audio fixtures generated with FFmpeg at test time. No copyrighted audio is used or stored."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


def ff(*args: str) -> None:
    subprocess.run([FFMPEG, "-v", "error", "-y", *args], check=True)


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory) -> dict[str, Path]:
    if FFMPEG is None:
        pytest.skip("ffmpeg not installed")
    d = tmp_path_factory.mktemp("fixtures")
    src = d / "source.wav"
    # 40 s of full-band stereo pink noise + a tone
    ff("-f", "lavfi", "-i", "anoisesrc=d=40:c=pink:r=44100:a=0.3", "-f", "lavfi", "-i", "sine=f=440:d=40:r=44100",
       "-filter_complex", "[0][1]amix=inputs=2,aformat=channel_layouts=stereo", "-c:a", "pcm_s16le", str(src))
    out = {"source_wav": src}
    out["mp3_320"] = d / "real320.mp3"; ff("-i", str(src), "-c:a", "libmp3lame", "-b:a", "320k", str(out["mp3_320"]))
    out["mp3_192"] = d / "low192.mp3"; ff("-i", str(src), "-c:a", "libmp3lame", "-b:a", "192k", str(out["mp3_192"]))
    low = d / "low128.mp3"; ff("-i", str(src), "-c:a", "libmp3lame", "-b:a", "128k", str(low))
    out["fake_320"] = d / "fake320.mp3"; ff("-i", str(low), "-c:a", "libmp3lame", "-b:a", "320k", str(out["fake_320"]))
    out["fake_wav"] = d / "fakewav.wav"; ff("-i", str(low), "-c:a", "pcm_s16le", str(out["fake_wav"]))
    out["vbr"] = d / "vbr.mp3"; ff("-i", str(src), "-c:a", "libmp3lame", "-q:a", "0", str(out["vbr"]))
    out["flac"] = d / "track.flac"; ff("-i", str(src), "-c:a", "flac", str(out["flac"]))
    out["aiff"] = d / "track.aiff"; ff("-i", str(src), "-c:a", "pcm_s16be", str(out["aiff"]))
    out["mono"] = d / "mono.wav"; ff("-i", str(src), "-ac", "1", "-c:a", "pcm_s16le", str(out["mono"]))
    out["short"] = d / "short.mp3"; ff("-i", str(src), "-t", "10", "-c:a", "libmp3lame", "-b:a", "320k", str(out["short"]))
    out["renamed"] = d / "renamed.wav"; shutil.copy(out["mp3_320"], out["renamed"])
    data = out["mp3_320"].read_bytes()
    out["trunc_mp3"] = d / "truncated.mp3"; out["trunc_mp3"].write_bytes(data[: len(data) // 4])
    wav = src.read_bytes()
    out["trunc_wav"] = d / "truncated.wav"; out["trunc_wav"].write_bytes(wav[: len(wav) // 3])
    out["random"] = d / "random.mp3"; out["random"].write_bytes(os.urandom(200_000))
    out["zero"] = d / "zero.mp3"; out["zero"].write_bytes(b"")
    out["traversal_name"] = d / "..%2F..%2Fevil.mp3"; shutil.copy(out["mp3_320"], out["traversal_name"])
    return out


@pytest.fixture
def service(tmp_path, monkeypatch):
    """A service with NO bundled engine, so tests decide explicitly whether Soulseek is on."""
    monkeypatch.setenv("PROJECT_ARCHIVE_DATA", str(tmp_path / "data"))
    from app.config import Settings
    from app.core.credentials import CredentialStore
    from app.core.service import ArchiveService
    from app.core.slskd_manager import SlskdManager
    manager = SlskdManager(Settings(), creds=CredentialStore(tmp_path / "secrets.json", use_keyring=False),
                           instance_dir=tmp_path / "client", binary_dir=None)
    svc = ArchiveService(tmp_path / "data" / "archive.db", manager=manager)
    s = svc.settings
    s.library_dir = str(tmp_path / "library")
    s.staging_dir = str(tmp_path / "staging")
    svc.save_settings(s)
    yield svc
    svc.db.close()
