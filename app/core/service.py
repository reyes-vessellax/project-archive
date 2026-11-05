"""Application service: stage -> analyze -> promote / reject, cleanup and crash recovery.

The UI calls only these methods; it never moves files itself.
"""
from __future__ import annotations

import os
import shutil
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from ..config import Settings, data_dir
from ..storage.db import Database, now
from . import jobs as J
from .analyzer import analyze, sha256_file
from .rules import FAIL, WARN
from .safety import Rejected, is_inside, safe_filename, unique_path, validate_candidate


class ActionBlocked(RuntimeError):
    """A user action isn't allowed right now. The message is shown to the user."""


class ArchiveService:
    def __init__(self, db_path: Path | None = None):
        self.db = Database(db_path or data_dir() / "archive.db")
        self.settings = Settings.from_dict(self.db.load_settings())
        self._lock = threading.RLock()
        self._seen: dict[str, tuple[int, float]] = {}    # incoming path -> (size, mtime) last scan

    # settings ---------------------------------------------------------------------
    def save_settings(self, s: Settings) -> None:
        self.settings = s
        self.db.save_settings(s.to_dict())

    # staging -----------------------------------------------------------------------
    def stage(self, source: Path, source_kind: str = "manual") -> dict:
        """Copy a candidate into its own quarantine folder. The original is never touched."""
        s = self.settings
        source = Path(source)
        size = validate_candidate(source, s.extensions, s.max_file_mb * 1024 * 1024)
        root = s.staging_root()
        root.mkdir(parents=True, exist_ok=True)
        _check_space(root, size)

        job_id = str(uuid.uuid4())
        name = safe_filename(source.name)
        job_dir = root / job_id
        staged = job_dir / name
        expires = (datetime.now(timezone.utc) + timedelta(hours=s.retention_hours)).isoformat(timespec="seconds")
        st = source.stat()
        self.db.insert_job(id=job_id, source_kind=source_kind, source_path=str(source), source_size=size,
                           source_mtime=st.st_mtime, original_name=source.name, state=J.STAGING,
                           expires_at=expires)
        try:
            job_dir.mkdir(parents=True)
            tmp = job_dir / (name + ".part")
            shutil.copyfile(source, tmp)
            os.replace(tmp, staged)
            if not is_inside(staged, root):
                raise Rejected("Unsafe file name.")
        except Exception as e:
            shutil.rmtree(job_dir, ignore_errors=True)
            self.db.update_job(job_id, state=J.ERROR, message=f"Couldn't stage: {e}")
            raise
        self.db.update_job(job_id, staged_path=str(staged))
        self.db.event(job_id, "staged", source_kind)
        return self.db.job(job_id)

    # analysis -----------------------------------------------------------------------
    def analyze(self, job_id: str, progress: Callable[[str], None] = lambda s: None) -> dict:
        job = self._require(job_id)
        self._transition(job, J.ANALYZING)
        try:
            result = analyze(Path(job["staged_path"]), self.settings, progress)
        except Exception as e:
            self.db.update_job(job_id, state=J.ERROR, message=f"Analysis failed: {e}")
            raise
        self.db.save_analysis(job_id, result)
        self.db.update_job(job_id, state=J.READY, message=result["overall_status"])
        return result

    # decisions -------------------------------------------------------------------------
    def promote(self, job_id: str, override_warning: bool = False) -> Path:
        with self._lock:
            job = self._require(job_id)
            analysis = self.db.analysis(job_id)
            if job["state"] != J.READY or not analysis:
                raise ActionBlocked("This track isn't ready for review yet.")
            status = analysis["overall_status"]
            if status == FAIL:
                raise ActionBlocked("Failed files can't be promoted.")
            if status == WARN and not override_warning:
                raise ActionBlocked("This track has warnings. Use 'Save to Library anyway' to confirm.")
            staged = Path(job["staged_path"])
            if not staged.is_file() or sha256_file(staged) != analysis["sha256"]:
                self.db.update_job(job_id, state=J.ERROR, message="Staged file changed or disappeared.")
                raise ActionBlocked("The staged file changed after it was checked. Re-run the analysis.")

            library = Path(self.settings.library_dir)
            library.mkdir(parents=True, exist_ok=True)
            target = unique_path(library, safe_filename(job["original_name"]))
            self._transition(job, J.PROMOTING)
            self.db.update_job(job_id, final_path=str(target))
            tmp = target.with_name(f".{target.name}.{job_id[:8]}.part")
            try:
                shutil.copyfile(staged, tmp)
                if sha256_file(tmp) != analysis["sha256"]:
                    raise OSError("copy verification failed")
                if target.exists():                      # appeared meanwhile: never overwrite
                    target = unique_path(library, target.name)
                os.replace(tmp, target)
            except Exception as e:
                tmp.unlink(missing_ok=True)
                self.db.update_job(job_id, state=J.READY, final_path=None, message=f"Save failed: {e}")
                raise ActionBlocked(f"Couldn't save to the library: {e}") from e
            self.db.update_job(job_id, state=J.PROMOTED, final_path=str(target),
                               disposition="promoted_override" if status == WARN else "promoted")
            self.db.event(job_id, "promoted", str(target))
            shutil.rmtree(staged.parent, ignore_errors=True)
            return target

    def reject(self, job_id: str) -> None:
        with self._lock:
            job = self._require(job_id)
            if job["state"] not in (J.READY, J.ERROR):
                raise ActionBlocked("Wait until the check finishes before rejecting.")
            self._remove_staging(job)
            self._transition(job, J.REJECTED)
            self.db.update_job(job_id, disposition="rejected")
            self.db.event(job_id, "rejected")

    # housekeeping ----------------------------------------------------------------------------
    def cleanup_expired(self) -> int:
        n = 0
        stamp = now()
        for job in self.db.jobs(states=(J.READY, J.ERROR, J.QUEUED, J.DISCOVERED)):
            if job["expires_at"] and job["expires_at"] < stamp:
                self._remove_staging(job)
                self.db.update_job(job["id"], state=J.EXPIRED, disposition="expired")
                n += 1
        return n

    def reconcile(self) -> None:
        """Run at startup: repair jobs interrupted by a crash or quit. Never deletes ambiguous files."""
        for job in self.db.jobs(states=(J.STAGING, J.ANALYZING, J.PROMOTING)):
            staged = Path(job["staged_path"]) if job["staged_path"] else None
            if job["state"] == J.PROMOTING:
                final = Path(job["final_path"]) if job["final_path"] else None
                a = self.db.analysis(job["id"])
                if final and final.is_file() and a and sha256_file(final) == a["sha256"]:
                    self.db.update_job(job["id"], state=J.PROMOTED, disposition="promoted")
                    if staged:
                        shutil.rmtree(staged.parent, ignore_errors=True)
                    continue
            if staged and staged.is_file():
                self.db.update_job(job["id"], state=J.ERROR, message="Interrupted. Re-run the analysis.")
            else:
                self.db.update_job(job["id"], state=J.ERROR, message="Interrupted and the staged file is missing.")

    def scan_incoming(self) -> list[dict]:
        """Stage files in the watched folder once their size and modified time stop changing."""
        folder = self.settings.incoming_dir
        if not folder or not Path(folder).is_dir():
            return []
        exts = {e.lower() for e in self.settings.extensions}
        staged = []
        for p in sorted(Path(folder).iterdir()):
            if p.is_symlink() or not p.is_file() or p.suffix.lower().lstrip(".") not in exts:
                continue
            st = p.stat()
            sig = (st.st_size, st.st_mtime)
            prev = self._seen.get(str(p))
            self._seen[str(p)] = sig
            if prev != sig or st.st_size == 0:
                continue                                   # still downloading (or first sighting)
            if self.db.find_source(str(p), st.st_size, st.st_mtime):
                continue                                   # already handled this exact file
            try:
                with open(p, "rb"):
                    pass                                   # still locked by the downloader on Windows?
                staged.append(self.stage(p, "folder"))
            except PermissionError:
                continue
            except Rejected as e:
                self.db.event(None, "skipped", f"{p.name}: {e}")
        return staged

    # helpers --------------------------------------------------------------------------
    def jobs(self) -> list[dict]:
        return self.db.jobs()

    def _require(self, job_id: str) -> dict:
        job = self.db.job(job_id)
        if not job:
            raise ActionBlocked("Unknown track.")
        return job

    def _transition(self, job: dict, new: str) -> None:
        J.check(job["state"], new)
        self.db.update_job(job["id"], state=new)
        job["state"] = new

    def _remove_staging(self, job: dict) -> None:
        if job["staged_path"]:
            folder = Path(job["staged_path"]).parent
            if is_inside(folder, self.settings.staging_root()):    # never delete outside quarantine
                shutil.rmtree(folder, ignore_errors=True)


def _check_space(folder: Path, needed: int) -> None:
    free = shutil.disk_usage(folder).free
    if free < needed * 2 + 200 * 1024 * 1024:
        raise Rejected("Not enough free disk space to stage this file safely.")
