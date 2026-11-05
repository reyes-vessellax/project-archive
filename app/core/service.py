"""Application service: search -> download -> stage -> analyze -> promote / reject, cleanup and crash recovery.

The UI calls only these methods; it never moves files itself.

Two ways a track enters quarantine:
  * a local file the user adds or drops (copied; the original is never touched), or
  * a Soulseek result the user picked. The slskd client downloads it into its own folder, and as
    soon as it finishes we MOVE it into quarantine, so nothing unreviewed is left lying around.
    Reject then deletes it for good; Promote moves it into the library folder from Settings.
"""
from __future__ import annotations

import os
import shutil
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from ..adapters.base import Candidate, ConnectorError, ConnectorStatus, SearchResult, SourceAdapter, Transfer
from ..config import Settings, data_dir
from ..storage.db import Database, now
from . import jobs as J
from .analyzer import analyze, sha256_file
from .rules import FAIL, WARN
from .safety import Rejected, is_inside, safe_filename, unique_path, validate_candidate
from .slskd_manager import BackendUnavailable, SlskdManager

# Wording the user sees for the connection. "slskd" never appears here.
MSG_LOCAL = "Local mode: drag tracks in to check them. Soulseek search is off."
MSG_STARTING = "Connecting to the server…"
MSG_TROUBLE = "Having trouble connecting to the server."


class ActionBlocked(RuntimeError):
    """A user action isn't allowed right now. The message is shown to the user."""


class ArchiveService:
    def __init__(self, db_path: Path | None = None,
                 adapter_factory: Callable[["ArchiveService"], SourceAdapter | None] | None = None,
                 manager: SlskdManager | None = None):
        self.db = Database(db_path or data_dir() / "archive.db")
        self.settings = Settings.from_dict(self.db.load_settings())
        self._lock = threading.RLock()
        self._seen: dict[str, tuple[int, float]] = {}    # incoming path -> (size, mtime) last scan
        self.manager = manager or SlskdManager(self.settings)
        self._adapter_factory = adapter_factory or _default_adapter
        self.adapter: SourceAdapter | None = None
        self.backend_state = "stopped"                   # stopped | starting | running | failed
        self.backend_error = ""
        self._build_adapter()

    # settings ---------------------------------------------------------------------
    def save_settings(self, s: Settings) -> None:
        self.settings = s
        self.manager.settings = s
        self.db.save_settings(s.to_dict())
        self._build_adapter()

    def _build_adapter(self) -> None:
        try:
            self.adapter = self._adapter_factory(self)
        except ConnectorError:
            self.adapter = None

    @property
    def managed_mode(self) -> bool:
        """True when the app runs its own bundled Soulseek engine (the normal case)."""
        return not self.settings.use_own_slskd and self.manager.available

    # bundled engine lifecycle -----------------------------------------------------------
    def start_backend(self) -> None:
        """Start the bundled engine (blocking, up to ~40 s). Call from a worker thread."""
        if not self.managed_mode:
            return
        self.backend_state, self.backend_error = "starting", ""
        try:
            self.manager.start()
            self.backend_state = "running"
            self._build_adapter()
        except BackendUnavailable as e:
            self.backend_state, self.backend_error = "failed", str(e)
            self.adapter = None

    def stop_backend(self) -> None:
        self.manager.stop()
        if self.managed_mode:
            self.backend_state = "stopped"

    # Soulseek search -----------------------------------------------------------------------
    def connector_status(self) -> ConnectorStatus:
        if self.managed_mode:
            if self.backend_state == "starting":
                return ConnectorStatus(available=False, message=MSG_STARTING)
            if self.backend_state in ("failed", "stopped") or not self.manager.running:
                return ConnectorStatus(available=False, message=MSG_TROUBLE)
            st = self.adapter.health_check() if self.adapter else ConnectorStatus(available=False, message=MSG_TROUBLE)
            if not st.available:
                st.message = MSG_TROUBLE
            elif not st.logged_in:
                st.message = "Connecting to Project Archive…"
            else:
                st.message = "Connected to Project Archive"
            return st
        if not self.settings.own_slskd_configured:
            return ConnectorStatus(available=False, message=MSG_LOCAL)
        if self.adapter is None:
            return ConnectorStatus(available=False, message="Check the slskd URL under Advanced in Settings.")
        return self.adapter.health_check()

    def search(self, query: str) -> SearchResult:
        return self._adapter_or_block().search(query)

    def search_results(self, search_id: str) -> SearchResult:
        exts = {e.lower().lstrip(".") for e in self.settings.extensions}
        res = self._adapter_or_block().search_results(search_id)
        res.candidates = [c for c in res.candidates if c.extension in exts]
        return res

    def request_download(self, cand: Candidate) -> dict:
        """User picked a search result: ask the client to download it and track it as a QUEUED job."""
        adapter = self._adapter_or_block()
        with self._lock:
            if self.db.find_remote(cand.user, cand.remote_path, tuple(J.NON_FINAL)):
                raise ActionBlocked("That file is already in your queue.")
            name = safe_filename(cand.display_name or "track")
            s = self.settings
            if cand.size > s.max_file_mb * 1024 * 1024:
                raise ActionBlocked(f"That file is {cand.size / 1e6:.0f} MB, over the {s.max_file_mb} MB limit in Settings.")
            job_id = str(uuid.uuid4())
            expires = (datetime.now(timezone.utc) + timedelta(hours=s.retention_hours)).isoformat(timespec="seconds")
            self.db.insert_job(id=job_id, source_kind=cand.source_kind, source_path=None, original_name=name,
                               state=J.QUEUED, expires_at=expires, remote_user=cand.user, remote_path=cand.remote_path,
                               remote_size=cand.size, progress=0.0, message="Requested")
        try:
            t = adapter.request_download(cand)
        except ConnectorError as e:
            self.db.update_job(job_id, state=J.ERROR, message=f"Download request failed: {e}")
            raise ActionBlocked(str(e)) from e
        self.db.update_job(job_id, transfer_id=t.transfer_id, message=t.state or "Queued")
        self.db.event(job_id, "requested", f"{cand.user}: {cand.display_name}")
        return self.db.job(job_id)

    def poll_downloads(self) -> list[dict]:
        """Update progress of every queued download; move finished ones into quarantine.
        Returns the jobs that just became STAGING and now need analysis."""
        if self.adapter is None:
            return []
        ready = []
        for job in self.db.jobs(states=(J.QUEUED,)):
            if not job["transfer_id"]:
                continue
            t = Transfer(transfer_id=job["transfer_id"], user=job["remote_user"], remote_path=job["remote_path"],
                         size=job["remote_size"] or 0, state="")
            try:
                t = self.adapter.transfer_status(t)
            except ConnectorError as e:
                self.db.update_job(job["id"], message=f"Waiting for slskd: {e}")
                continue
            if t.done and t.local_path:
                try:
                    ready.append(self._stage_file(job["id"], t.local_path, move=True))
                    _tidy_empty_subfolder(t.local_path.parent, getattr(self.adapter, "downloads_dir", None))
                except Exception as e:
                    self.db.update_job(job["id"], state=J.ERROR, message=f"Couldn't move the download into quarantine: {e}")
            elif t.failed:
                self.db.update_job(job["id"], state=J.ERROR, message=f"Download failed: {t.state}")
            else:
                self.db.update_job(job["id"], progress=t.percent, message=t.state)
        return ready

    def cancel(self, job_id: str) -> None:
        with self._lock:
            job = self._require(job_id)
            if job["state"] != J.QUEUED:
                raise ActionBlocked("Only a download that is still in progress can be cancelled.")
            if self.adapter and job["transfer_id"]:
                self.adapter.cancel(Transfer(transfer_id=job["transfer_id"], user=job["remote_user"],
                                             remote_path=job["remote_path"], size=job["remote_size"] or 0, state=""))
            self._transition(job, J.CANCELLED)
            self.db.update_job(job_id, disposition="cancelled")
            self.db.event(job_id, "cancelled")

    # staging -----------------------------------------------------------------------
    def stage(self, source: Path, source_kind: str = "manual") -> dict:
        """Copy a local candidate into its own quarantine folder. The original is never touched."""
        source = Path(source)
        size = validate_candidate(source, self.settings.extensions, self.settings.max_file_mb * 1024 * 1024)
        job_id = str(uuid.uuid4())
        expires = (datetime.now(timezone.utc) + timedelta(hours=self.settings.retention_hours)).isoformat(timespec="seconds")
        st = source.stat()
        self.db.insert_job(id=job_id, source_kind=source_kind, source_path=str(source), source_size=size,
                           source_mtime=st.st_mtime, original_name=source.name, state=J.STAGING, expires_at=expires)
        return self._stage_file(job_id, source, move=False)

    def _stage_file(self, job_id: str, source: Path, move: bool) -> dict:
        """Put `source` into the job's quarantine folder, copying (local file) or moving (finished download)."""
        s = self.settings
        job = self._require(job_id)
        if job["state"] == J.QUEUED:
            self._transition(job, J.STAGING)
        root = s.staging_root()
        root.mkdir(parents=True, exist_ok=True)
        name = safe_filename(job["original_name"])
        job_dir = root / job_id
        staged = job_dir / name
        try:
            size = validate_candidate(source, s.extensions, s.max_file_mb * 1024 * 1024)
            if not move:
                _check_space(root, size)
            job_dir.mkdir(parents=True)
            if move:
                _move(source, staged)
            else:
                tmp = job_dir / (name + ".part")
                shutil.copyfile(source, tmp)
                os.replace(tmp, staged)
            if not is_inside(staged, root):
                raise Rejected("Unsafe file name.")
        except Exception as e:
            shutil.rmtree(job_dir, ignore_errors=True)
            self.db.update_job(job_id, state=J.ERROR, message=f"Couldn't stage: {e}")
            raise
        self.db.update_job(job_id, staged_path=str(staged), progress=100.0, message="Staged")
        self.db.event(job_id, "staged", job["source_kind"])
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
                raise ActionBlocked("Failed files can't be downloaded to the library.")
            if status == WARN and not override_warning:
                raise ActionBlocked("This track has warnings. Use 'Download anyway' to confirm.")
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
                raise ActionBlocked("Wait until the check finishes before deleting.")
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
                if job["state"] == J.QUEUED and self.adapter and job["transfer_id"]:
                    self.adapter.cancel(Transfer(transfer_id=job["transfer_id"], user=job["remote_user"],
                                                 remote_path=job["remote_path"], size=job["remote_size"] or 0, state=""))
                self._remove_staging(job)
                self.db.update_job(job["id"], state=J.EXPIRED, disposition="expired")
                n += 1
        return n

    def reconcile(self) -> None:
        """Run at startup: repair jobs interrupted by a crash or quit. Never deletes ambiguous files.
        QUEUED downloads are left alone: slskd keeps downloading while we're closed, and poll_downloads picks them up."""
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

    def hide(self, job_id: str) -> None:
        """Remove a finished entry from the queue panel. History is kept; nothing on disk changes."""
        job = self._require(job_id)
        if job["state"] not in J.FINAL and job["state"] != J.ERROR:
            raise ActionBlocked("Finish or cancel this track before removing it from the list.")
        if job["state"] == J.ERROR:
            self._remove_staging(job)                       # an errored track's staged copy goes too
        self.db.update_job(job_id, hidden=1)

    # helpers --------------------------------------------------------------------------
    def jobs(self) -> list[dict]:
        """What the queue panel shows: everything the user hasn't removed."""
        return self.db.jobs(include_hidden=False)

    def _adapter_or_block(self) -> SourceAdapter:
        if self.managed_mode:
            if self.backend_state == "starting":
                raise ActionBlocked("Still connecting to the server. Try again in a moment.")
            if self.adapter is None:
                raise ActionBlocked(MSG_TROUBLE + " Use 'Try again' in the status bar.")
            return self.adapter
        if not self.settings.own_slskd_configured:
            raise ActionBlocked(MSG_LOCAL)
        if self.adapter is None:
            raise ActionBlocked("Check the slskd URL under Advanced in Settings.")
        return self.adapter

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


def _default_adapter(svc: "ArchiveService") -> SourceAdapter | None:
    from ..adapters.slskd_adapter import SlskdAdapter
    s = svc.settings
    if svc.managed_mode:
        m = svc.manager
        return SlskdAdapter(m.url, m.api_key, str(m.downloads_dir)) if m.running else None
    if not s.own_slskd_configured:
        return None
    return SlskdAdapter(s.slskd_url, s.slskd_api_key, s.slskd_downloads_dir)


def _move(src: Path, dst: Path) -> None:
    """Move across volumes safely: rename when possible, otherwise copy to a .part file, then swap."""
    try:
        os.replace(src, dst)
    except OSError:
        tmp = dst.with_name(dst.name + ".part")
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
        src.unlink()


def _tidy_empty_subfolder(folder: Path, root: Path | None) -> None:
    """Remove the empty subfolder the client made for a download, never the downloads root itself."""
    try:
        if root and folder.resolve() != root.resolve() and is_inside(folder, root) \
                and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        pass


def _check_space(folder: Path, needed: int) -> None:
    free = shutil.disk_usage(folder).free
    if free < needed * 2 + 200 * 1024 * 1024:
        raise Rejected("Not enough free disk space to stage this file safely.")
