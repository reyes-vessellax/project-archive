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
    lib = svc.settings.downloads_dir()
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
    # the copy was verified against the checked file BEFORE tags were added; the tagged result is recorded
    assert sha256_file(target) == service.db.analysis(job["id"])["final_sha256"]
    import subprocess
    pcm = lambda p: subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "s16le", "-"], capture_output=True).stdout
    assert pcm(target) == pcm(fixtures["mp3_320"])                      # tags only: the audio is identical
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
def test_tracks_never_expire_and_old_expired_rows_leave_the_queue(service, fixtures):
    job = service.stage(fixtures["mp3_320"])
    service.analyze(job["id"])
    service.db.update_job(job["id"], expires_at="2000-01-01T00:00:00+00:00")
    assert service.cleanup_expired() == 0
    assert service.db.job(job["id"])["state"] == J.READY       # still waiting for you, file intact
    assert Path(job["staged_path"]).exists()
    old = service.stage(fixtures["mp3_320"])
    service.db.update_job(old["id"], state=J.EXPIRED)            # expired under an older version
    assert service.cleanup_expired() == 1
    assert old["id"] not in {j["id"] for j in service.jobs()}


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


@needs_ffmpeg
def test_downloads_land_in_app_subfolder(service, fixtures):
    from app.config import APP_NAME
    job = service.stage(fixtures["mp3_320"]); service.analyze(job["id"])
    assert not service.settings.downloads_dir().exists()            # not created until the first download
    target = service.promote(job["id"])
    assert target.parent == Path(service.settings.library_dir) / APP_NAME
    assert sorted(p.name for p in Path(service.settings.library_dir).iterdir()) == [APP_NAME]   # library itself untouched


def test_library_named_after_app_is_not_nested(service, tmp_path):
    from app.config import APP_NAME
    s = service.settings; s.library_dir = str(tmp_path / APP_NAME); service.save_settings(s)
    assert service.settings.downloads_dir() == tmp_path / APP_NAME


@needs_ffmpeg
def test_clear_finished_hides_only_finished(service, fixtures):
    a = service.stage(fixtures["mp3_320"]); service.analyze(a["id"]); service.promote(a["id"])
    b = service.stage(fixtures["mp3_320"]); service.analyze(b["id"])                 # still waiting for a decision
    assert service.hide_finished() == 0                                               # the saved one already left by itself
    ids = {j["id"] for j in service.jobs()}
    assert b["id"] in ids and a["id"] not in ids
    assert service.db.job(a["id"])["state"] == J.PROMOTED                            # history intact; library page still lists it


@needs_ffmpeg
def test_promote_keeps_spectrogram(service, fixtures):
    a = service.stage(fixtures["mp3_320"]); service.analyze(a["id"])
    before = service.db.analysis(a["id"])["spectrogram_path"]
    service.promote(a["id"], override_warning=True)
    after = service.db.analysis(a["id"])["spectrogram_path"]
    assert after != before and Path(after).exists() and not Path(before).exists()


@needs_ffmpeg
def test_reset_everything_wipes_data_but_not_music(service, fixtures):
    a = service.stage(fixtures["mp3_320"]); service.analyze(a["id"]); service.promote(a["id"], override_warning=True)
    final = Path(service.db.job(a["id"])["final_path"])
    root = service.db.path.parent
    service.reset_everything()
    assert final.exists()
    assert not (root / "archive.db").exists()


@needs_ffmpeg
def test_spectrograms_are_capped_and_redrawn_on_demand(service, fixtures):
    service.settings.keep_spectrograms = 10                  # floor is 10
    ids = []
    for i in range(12):
        j = service.stage(fixtures["mp3_320"]); service.analyze(j["id"]); service.promote(j["id"], override_warning=True)
        ids.append(j["id"])
    keep_dir = service.db.path.parent / "spectrograms"
    assert len(list(keep_dir.glob("*.png"))) == 10
    oldest = ids[0]
    assert not Path(service.db.analysis(oldest)["spectrogram_path"]).exists()
    out = service.redraw_spectrogram(oldest)
    assert out and Path(out).exists() and service.db.analysis(oldest)["spectrogram_path"] == out
    assert len(list(keep_dir.glob("*.png"))) == 10          # the cap holds after a redraw too


@needs_ffmpeg
def test_saved_track_leaves_ready_list_but_stays_in_library(service, fixtures):
    job = service.stage(fixtures["mp3_320"])
    service.analyze(job["id"])
    assert job["id"] in [j["id"] for j in service.jobs()]
    service.promote(job["id"])
    assert job["id"] not in [j["id"] for j in service.jobs()]                     # gone from Ready, no × needed
    assert job["id"] in [j["id"] for j in service.db.jobs(states=(J.PROMOTED,))]  # still in the Library


@needs_ffmpeg
def test_deleted_track_leaves_ready_list(service, fixtures):
    job = service.stage(fixtures["mp3_320"])
    service.analyze(job["id"])
    service.reject(job["id"])
    assert job["id"] not in [j["id"] for j in service.jobs()]


@needs_ffmpeg
def test_batch_track_saves_into_its_playlist_folder(service, fixtures):
    job = service.stage(fixtures["mp3_320"])
    service.db.update_job(job["id"], playlist="Friday warm-up")
    service.analyze(job["id"])
    target = service.promote(job["id"])
    assert target.parent.name == "Friday warm-up"
    assert target.parent.parent == service.settings.downloads_dir()


@needs_ffmpeg
def test_remove_from_library_trashes_file_and_forgets_crates(service, fixtures, tmp_path):
    job = service.stage(fixtures["mp3_320"]); service.analyze(job["id"])
    target = service.promote(job["id"])
    cid = service.db.create_crate("Warm-up")
    service.db.add_to_crate(cid, job["id"])
    assert service.db.crates()[0]["n"] == 1
    trashed = []
    service.remove_from_library(job["id"], trash=lambda p: (trashed.append(p), p.rename(tmp_path / p.name), True)[-1])
    assert trashed == [target] and not target.exists()
    assert job["id"] not in [j["id"] for j in service.db.jobs(states=(J.PROMOTED,))]
    assert service.db.crate_jobs(cid) == set()


def test_crates_basics(service):
    a = service.db.create_crate("  Peak   time ")
    assert service.db.create_crate("peak time") == a              # same name (any case) -> same crate
    service.db.rename_crate(a, "Peak")
    assert [c["name"] for c in service.db.crates()] == ["Peak"]
    service.db.delete_crate(a)
    assert service.db.crates() == []
@needs_ffmpeg
def test_prechecks_stop_non_audio_before_decoding(service, tmp_path):
    exe = tmp_path / "Artist - Track.mp3"
    exe.write_bytes(b"MZ" + b"\x00" * 200_000)                 # a Windows program wearing an .mp3 name
    j = service.stage(exe); a = service.analyze(j["id"])
    assert a["overall_status"] == "FAIL"
    assert any(c["title"] == "Not an audio file" and "Windows program" in c["message"] for c in a["checks"])
    assert a.get("decode") is None                            # never decoded


@needs_ffmpeg
def test_prechecks_pass_real_audio(service, fixtures):
    j = service.stage(fixtures["mp3_320"]); a = service.analyze(j["id"])
    assert not any(c["id"] == "precheck" and c["status"] == "FAIL" for c in a["checks"])


def test_start_fresh_leaves_other_files_in_a_shared_data_folder(service):
    """Audit (High): Start fresh deleted everything in the data folder. Pointed at a shared folder
    (PROJECT_ARCHIVE_DATA), that would take other files with it. Now only DigMart's own entries go."""
    root = service.db.path.parent
    (root / "my notes.txt").write_text("not DigMart's")
    (root / "Some Album").mkdir()
    (root / "Some Album" / "track.flac").write_bytes(b"x")
    (root / "spin").mkdir(exist_ok=True)
    service.reset_everything()
    assert (root / "my notes.txt").exists() and (root / "Some Album" / "track.flac").exists()
    assert not (root / "spin").exists() and not service.db.path.exists()


def test_stale_discover_lookups_are_pruned(service):
    """Audit (Low): the Discover cache was never pruned."""
    db = service.db
    db.cache_put("discover:crate4:deep house", {"tracks": []})
    db.cache_put("https://musicbrainz.org/ws/2/artist?x", {"artists": []})
    db._con.execute("UPDATE discover_cache SET fetched_at = '2020-01-01T00:00:00+00:00'")
    db._con.commit()
    db.cache_put("discover:crate4:acid house", {"tracks": []})            # fresh: stays
    assert db.prune_cache() == 2
    assert db.cache_get("discover:crate4:acid house") and not db.cache_get("discover:crate4:deep house")
