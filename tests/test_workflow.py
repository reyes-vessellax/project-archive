"""Staging, promotion, rejection, cleanup, recovery and path safety."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.core import jobs as J
from app.core.safety import Rejected, safe_filename, unique_path
from app.core.service import ActionBlocked

from .conftest import needs_ffmpeg


def library_files(svc):
    lib = Path(svc.settings.library_dir)
    return sorted(p.name for p in lib.iterdir()) if lib.exists() else []


@needs_ffmpeg
def test_nothing_reaches_library_before_promote(service, fixtures):
    job = service.stage(fixtures["mp3_320"])
    service.analyze(job["id"])
    assert library_files(service) == []
    assert fixtures["mp3_320"].exists()                       # original untouched


@needs_ffmpeg
def test_promote_pass_verifies_hash(service, fixtures):
    job = service.stage(fixtures["mp3_320"])
    a = service.analyze(job["id"])
    target = service.promote(job["id"])
    from app.core.analyzer import sha256_file
    assert sha256_file(target) == a["sha256"]
    assert service.db.job(job["id"])["state"] == J.PROMOTED
    assert not Path(job["staged_path"]).exists()


@needs_ffmpeg
def test_warn_needs_override(service, fixtures):
    job = service.stage(fixtures["mp3_192"])
    service.analyze(job["id"])
    with pytest.raises(ActionBlocked):
        service.promote(job["id"])
    service.promote(job["id"], override_warning=True)
    assert service.db.job(job["id"])["disposition"] == "promoted_override"


@needs_ffmpeg
def test_fail_never_promotes(service, fixtures):
    job = service.stage(fixtures["trunc_mp3"])
    service.analyze(job["id"])
    with pytest.raises(ActionBlocked):
        service.promote(job["id"], override_warning=True)
    assert library_files(service) == []


@needs_ffmpeg
def test_reject_removes_staged_copy_only(service, fixtures):
    job = service.stage(fixtures["mp3_320"])
    service.analyze(job["id"])
    service.reject(job["id"])
    assert not Path(job["staged_path"]).exists()
    assert fixtures["mp3_320"].exists()
    assert service.db.job(job["id"])["state"] == J.REJECTED
    assert library_files(service) == []


@needs_ffmpeg
def test_duplicate_names_never_overwrite(service, fixtures):
    names = []
    for _ in range(2):
        job = service.stage(fixtures["mp3_320"])
        service.analyze(job["id"])
        names.append(service.promote(job["id"]).name)
    assert names == ["real320.mp3", "real320 (2).mp3"]


@needs_ffmpeg
def test_staged_file_tampering_blocks_promotion(service, fixtures):
    job = service.stage(fixtures["mp3_320"])
    service.analyze(job["id"])
    with open(job["staged_path"], "ab") as f:
        f.write(b"tampered")
    with pytest.raises(ActionBlocked):
        service.promote(job["id"])


@needs_ffmpeg
def test_cleanup_expires_old_jobs(service, fixtures):
    job = service.stage(fixtures["mp3_320"])
    service.analyze(job["id"])
    service.db.update_job(job["id"], expires_at="2000-01-01T00:00:00+00:00")
    assert service.cleanup_expired() == 1
    assert service.db.job(job["id"])["state"] == J.EXPIRED
    assert not Path(job["staged_path"]).exists()


@needs_ffmpeg
def test_reconcile_after_crash(service, fixtures):
    job = service.stage(fixtures["mp3_320"])
    service.db.update_job(job["id"], state=J.ANALYZING)
    service.reconcile()
    assert service.db.job(job["id"])["state"] == J.ERROR
    service.analyze(job["id"])                                   # recoverable
    assert service.db.job(job["id"])["state"] == J.READY


@needs_ffmpeg
def test_watched_folder_waits_for_stable_file(service, fixtures, tmp_path):
    inc = tmp_path / "incoming"
    inc.mkdir()
    s = service.settings
    s.incoming_dir = str(inc)
    service.save_settings(s)
    (inc / "track.mp3").write_bytes(fixtures["mp3_320"].read_bytes())
    assert service.scan_incoming() == []                         # first sighting: wait
    assert len(service.scan_incoming()) == 1                     # unchanged: stage it
    assert service.scan_incoming() == []                         # never staged twice


def test_rejects_bad_inputs(service, tmp_path):
    (tmp_path / "empty.mp3").write_bytes(b"")
    (tmp_path / "evil.exe").write_bytes(b"MZ")
    (tmp_path / "folder.mp3").mkdir()
    for name in ["empty.mp3", "evil.exe", "folder.mp3", "missing.mp3"]:
        with pytest.raises(Rejected):
            service.stage(tmp_path / name)


def test_symlinks_rejected(service, tmp_path, fixtures):
    link = tmp_path / "link.mp3"
    try:
        link.symlink_to(fixtures["mp3_320"])
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted here")
    with pytest.raises(Rejected):
        service.stage(link)


def test_oversize_rejected(service, tmp_path):
    s = service.settings
    s.max_file_mb = 1
    service.save_settings(s)
    big = tmp_path / "big.wav"
    big.write_bytes(b"\0" * (2 * 1024 * 1024))
    with pytest.raises(Rejected):
        service.stage(big)


@pytest.mark.parametrize("raw, expected", [
    ("../../evil.mp3", "evil.mp3"),
    ("..\\..\\evil.mp3", "evil.mp3"),
    ("CON.mp3", "_CON.mp3"),
    ("nul.wav", "_nul.wav"),
    ('Track: "Mix" <Edit>?.MP3', "Track_ _Mix_ _Edit__.mp3"),
    ("   .mp3", "track.mp3"),
    ("trailing dots....mp3", "trailing dots.mp3"),
])
def test_safe_filename(raw, expected):
    assert safe_filename(raw) == expected


def test_unique_path(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"1")
    (tmp_path / "a (2).mp3").write_bytes(b"1")
    assert unique_path(tmp_path, "a.mp3").name == "a (3).mp3"
