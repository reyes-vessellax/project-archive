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
import re
import shutil
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from ..adapters.base import Candidate, ConnectorError, ConnectorStatus, SearchResult, SourceAdapter, Transfer
from ..config import APP_NAME, Settings, data_dir
from ..storage.db import Database, now
from . import jobs as J
from .analyzer import analyze, sha256_file
from .rules import FAIL, WARN
from .safety import Rejected, is_inside, safe_filename, unique_path, validate_candidate
from .account import AccountStore
from .slskd_manager import BackendUnavailable, SlskdManager

# Wording the user sees for the connection. "slskd" never appears here.
MSG_LOCAL = "Local mode: drag tracks in to check them. Soulseek search is off."
MSG_STARTING = "Connecting to the server…"
MSG_TROUBLE = "Having trouble connecting to the server."
MSG_RECONNECT = "Reconnecting…"


class ActionBlocked(RuntimeError):
    """A user action isn't allowed right now. The message is shown to the user."""


class PreviewBusy(ActionBlocked):
    """The search said this copy was ready, but when asked the sharer put us in their line (their free slot
    went to someone else since the search). The window marks the copy as busy and tries another one."""


MAX_DOWNLOAD_RETRIES = 2            # the engine already makes 3 attempts of its own per request
RETRY_WAIT_S = (15, 45)

_BOT_USER = re.compile(r"(https?:|www\.|\.(com|net|org|io|co|xyz|site|store|shop|biz|info|me|tv|cc)(/|$))", re.I)


def clean_query(q: str) -> str:
    """Words go to the network as substrings to match against filenames, so a stray trailing dot or comma
    ("ulo s.", "weber,") makes a word that almost no filename contains. Strip punctuation from the ends of
    words; keep it inside ("a.m.", "drum&bass", "7'")."""
    out = []
    for w in q.split():
        core = w.strip(",;:!?\"'()[]{}")
        if core.endswith(".") and core.count(".") == 1:        # "s." -> "s", but "a.m." stays
            core = core[:-1]
        out.append(core or w)
    return " ".join(out)


def looks_like_ad_bot(user: str) -> bool:
    """Accounts named after a web shop (e.g. "https://www.rawzik.com") answer every search with their
    catalogue and never deliver; every request to one times out. Grey them out up front."""
    return bool(user) and bool(_BOT_USER.search(user.strip()))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ArchiveService:
    def __init__(self, db_path: Path | None = None,
                 adapter_factory: Callable[["ArchiveService"], SourceAdapter | None] | None = None,
                 manager: SlskdManager | None = None):
        self.db = Database(db_path or data_dir() / "archive.db")
        from .searching import Budget
        self.search_budget = Budget()     # one bucket: the user's searches, Batch and the Wishlist
        from .wishlist import Wishlist
        self.wishlist = Wishlist(self)
        self.settings = Settings.from_dict(self.db.load_settings())
        self._lock = threading.RLock()
        self._seen: dict[str, tuple[int, float]] = {}    # incoming path -> (size, mtime) last scan
        self.accounts = AccountStore(self.db)
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
        self.phase = "engine"
        try:
            had_port = self.settings.listen_port
            self.manager.start()
            self.phase = "signin"
            if self.settings.listen_port != had_port:              # picked on first start: keep it
                self.db.save_settings(self.settings.to_dict())
            self.backend_state = "running"
            self._build_adapter()
        except BackendUnavailable as e:
            self.backend_state, self.backend_error = "failed", str(e)
            self.adapter = None
            return
        self.phase = "port"
        self.open_port()
        self.phase = "ready"

    port_open: bool = False
    port_note: str = ""
    phase: str = ""                  # engine | signin | port | ready — what the start-up screen lights up

    def open_port(self) -> None:
        """Ask the router to forward the engine's port (UPnP). Best effort; a few seconds; call off the UI thread."""
        from . import upnp
        port = int(self.settings.listen_port or 0)
        if not port or not self.settings.upnp:
            self.port_open, self.port_note = False, "Port forwarding is off (Settings → Advanced)." if port else ""
            return
        try:
            self.port_open, self.port_note = upnp.open_port(port, f"{APP_NAME} downloads")
        except Exception as e:                                  # noqa: BLE001
            self.port_open, self.port_note = False, f"Couldn't talk to the router: {e}"
        try:
            from datetime import datetime as _dt
            with open(self.db.path.parent / "app.log", "a", encoding="utf-8") as f:
                f.write(f"{_dt.now().isoformat(timespec='seconds')} port: {self.port_note}\n")
        except OSError:
            pass

    def reset_everything(self) -> None:
        """Start fresh: stop the engine, drop the database, quarantine, engine instance and logs. The Soulseek
        login in the OS keyring is kept, so no second network account is created. The app must quit after this."""
        import shutil
        self.stop_backend()
        root = self.db.path.parent
        try:
            self.db.close()
        except Exception:
            pass
        for p in list(root.iterdir()):
            if p.name == "app.lock":
                continue
            try:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
            except OSError:
                pass

    def watchdog(self) -> bool:
        """Call from a timer (off the UI thread): if the engine process died, start it again.
        Returns True when a restart was attempted."""
        if not self.managed_mode or self.backend_state not in ("running", "failed"):
            return False
        if self.manager.running:
            return False
        import time as _t
        last = getattr(self, "_last_restart", 0.0)
        if _t.monotonic() - last < 20:
            return False                                      # don't thrash
        self._last_restart = _t.monotonic()
        self.backend_state = "restarting"
        try:
            self.manager.stop()
        except Exception:
            pass
        self.start_backend()
        try:
            with open(self.db.path.parent / "app.log", "a", encoding="utf-8") as f:
                from datetime import datetime as _dt
                f.write(f"{_dt.now().isoformat(timespec='seconds')} watchdog: engine was down; restarted -> {self.backend_state} {self.backend_error}\n")
        except OSError:
            pass
        return True

    def stop_backend(self) -> None:
        self.manager.stop()
        if self.managed_mode:
            self.backend_state = "stopped"

    # Soulseek search -----------------------------------------------------------------------
    def connector_status(self) -> ConnectorStatus:
        if self.managed_mode:
            if self.backend_state == "starting":
                return ConnectorStatus(available=False, message=MSG_STARTING)
            if self.backend_state == "restarting":
                return ConnectorStatus(available=False, message=MSG_RECONNECT)
            if self.backend_state in ("failed", "stopped") or not self.manager.running:
                return ConnectorStatus(available=False, message=MSG_TROUBLE)
            st = self.adapter.health_check() if self.adapter else ConnectorStatus(available=False, message=MSG_TROUBLE)
            if not st.available:
                st.message = MSG_TROUBLE
            elif not st.logged_in:
                st.message = f"Connecting to {APP_NAME}…"
            else:
                st.message = f"Connected to {APP_NAME}"
            return st
        if not self.settings.own_slskd_configured:
            return ConnectorStatus(available=False, message=MSG_LOCAL)
        if self.adapter is None:
            return ConnectorStatus(available=False, message="Check the slskd URL under Advanced in Settings.")
        return self.adapter.health_check()

    def search(self, query: str, timeout_s: float = 45.0, check_login: bool = True) -> SearchResult:
        adapter = self._adapter_or_block()
        self._searches_started = getattr(self, "_searches_started", 0) + 1
        if check_login and self.managed_mode and not self.adapter_logged_in():
            raise ActionBlocked("Still signing in. Search opens as soon as you're connected.")
        return adapter.search(clean_query(query), timeout_s=timeout_s)

    def search_status(self, search_id: str) -> tuple[bool, int, int, str]:
        return self._adapter_or_block().search_status(search_id)

    # already-have-it ------------------------------------------------------------------------
    def have_index(self) -> dict:
        """What's already here, keyed for quick matching: the same remote file, or the same artist+title
        (mix words ignored). Cached per DB change."""
        key = self.db.jobs_version() if hasattr(self.db, "jobs_version") else None
        cache = getattr(self, "_have", None)
        if cache and cache[0] == key and key is not None:
            return cache[1]
        from ..adapters.base import parse_track
        from .fuzzy import words
        idx = {"remote": {}, "title": {}}
        for j in self.db.jobs(include_hidden=True, limit=5000):
            if j["state"] in (J.REJECTED, J.CANCELLED, J.EXPIRED):
                continue
            where = "library" if j["state"] == J.PROMOTED else ("queue" if j["state"] not in J.FINAL else None)
            if where is None:
                continue
            a = self.db.analysis(j["id"]) if j["state"] == J.PROMOTED else None
            f = (a or {}).get("facts", {}) or {}
            kbps = round(f["bitrate_bps"] / 1000) if f.get("bitrate_bps") else None
            when = (j.get("updated_at") or "")[:10]
            entry = {"where": where, "name": j["original_name"], "kbps": kbps, "lossless": bool(f.get("lossless")),
                     "when": when, "job_id": j["id"]}
            if j.get("remote_user") and j.get("remote_path"):
                idx["remote"][(j["remote_user"], j["remote_path"])] = entry
            artist, title, _mix = parse_track(j["original_name"])
            tkey = " ".join(words(title))
            if tkey:
                idx["title"].setdefault(tkey, []).append((" ".join(words(artist)), entry))
        self._have = (key, idx)
        return idx

    def already_have(self, cand) -> dict | None:
        """The library/queue entry that looks like this candidate, or None."""
        from ..adapters.base import parse_track
        from .fuzzy import edit_distance, words
        idx = self.have_index()
        hit = idx["remote"].get((cand.user, cand.remote_path))
        if hit:
            return hit
        artist, title, _mix = parse_track(cand.display_name or cand.remote_path.rsplit("\\", 1)[-1])
        tkey = " ".join(words(title)); akey = " ".join(words(artist))
        if not tkey:
            return None
        for key, entries in idx["title"].items():
            if key == tkey or (len(tkey) > 6 and edit_distance(key, tkey, 2) <= 2):
                for a, entry in entries:
                    if not akey or not a or akey == a or akey in a or a in akey:
                        return entry
        return None

    def stop_search(self, search_id: str) -> None:
        try:
            self._adapter_or_block().stop_search(search_id)
        except Exception:
            pass

    def forget_search(self, search_id: str) -> None:
        try:
            self._adapter_or_block().forget_search(search_id)
        except Exception:
            pass

    def adapter_logged_in(self) -> bool:
        try:
            return bool(self.adapter and self.adapter.health_check().logged_in)
        except Exception:
            return False

    def search_results(self, search_id: str) -> SearchResult:
        exts = {e.lower().lstrip(".") for e in self.settings.extensions}
        res = self._adapter_or_block().search_results(search_id)
        for c in res.candidates:                           # shown greyed rather than hidden, so counts match other clients
            if looks_like_ad_bot(c.user):
                c.note = "Ad bot"                           # answers every search with a shop's catalogue, never sends a byte
            elif c.extension not in exts:
                c.note = "Extension mismatch"
        return res

    @property
    def download_pacer(self):
        """One pacer for every batch, so two playlists downloading at once still share the same few slots."""
        if getattr(self, "_pacer", None) is None:
            from .pacer import DownloadPacer
            self._pacer = DownloadPacer(lambda: [j.get("remote_user") or "" for j in self.db.jobs(states=(J.QUEUED,))
                                                 if "Remotely" not in (j.get("message") or "")])
        return self._pacer

    # ---------------------------------------------------------------- search preview
    def _preview_dir(self) -> Path:
        out = self.db.path.parent / "preview"
        out.mkdir(parents=True, exist_ok=True)
        return out

    def purge_previews(self) -> int:
        """Delete every preview clip and any partial download a preview left behind (a crash mid-preview).
        Runs at start-up, before each new preview and when the app closes; nothing from a preview stays."""
        out, n = self._preview_dir(), 0
        for f in list(out.glob("*.wav")) + list(out.glob("chunk.*")):
            try:
                f.unlink(); n += 1
            except OSError:
                pass
        ledger = out / "partials.txt"
        if ledger.exists():
            for line in ledger.read_text(encoding="utf-8", errors="replace").splitlines():
                q = Path(line.strip())
                if line.strip() and q.is_file():
                    try:
                        q.unlink(); n += 1
                    except OSError:
                        pass
            ledger.unlink(missing_ok=True)
        return n

    def _preview_roots(self) -> list[Path]:
        return [Path(getattr(self.manager, "instance_dir", Path("/nonexistent"))) / "incomplete",
                Path(self.settings.slskd_downloads_dir or getattr(self.manager, "downloads_dir", "/nonexistent"))]

    @staticmethod
    def _find_named(roots: list[Path], name: str) -> Path | None:
        import os
        for root in roots:                                  # incomplete folder first, then downloads
            if root.is_dir():
                for dirpath, _, files in os.walk(root):
                    if name in files:
                        return Path(dirpath) / name
        return None

    def snippet_preview(self, cand: Candidate, seconds: float = 20.0, should_stop=lambda: False,
                        progress=lambda msg: None, timeout_s: float = 60.0) -> tuple[Path, float]:
        """Hear ~20 seconds from somewhere in the middle of a track WITHOUT downloading it.

        The engine resumes a partial download from where the partial file ends, so: fetch the first few KB
        (the header), stop, pad the partial file out to a random point in the middle, ask again, and the sharer
        sends from there. Only about 20 seconds' worth of bytes travel. The clip is cut into a small WAV and the
        partial file is deleted. MP3, FLAC, WAV and AIFF work this way; other formats fetch from the start.
        Copies with a wait are refused before anything is requested. Returns (wav, start_s)."""
        import random
        import time as _time
        from ..media.tools import find_tool, run
        from . import preview as pv
        adapter = self._adapter_or_block()
        if cand.locked:
            raise ActionBlocked("That copy is private; it can't be previewed.")
        ext = (cand.extension or "").lower()
        if ext not in {e.lower().lstrip(".") for e in self.settings.extensions}:
            raise ActionBlocked(f".{cand.extension or '(none)'} files can't be previewed.")
        if not cand.free_slot or (cand.queue_length or 0) > 0:
            raise ActionBlocked("That copy has a wait, so it can't be previewed. Pick one that's Ready now.")
        length = float(cand.length_s or 0) or (cand.size * 8 / (cand.bitrate_kbps * 1000) if cand.bitrate_kbps else 360.0)
        seconds = min(seconds, max(5.0, length - 2))
        start = max(0.0, min(length * random.uniform(0.30, 0.60), length - seconds - 1))
        name = cand.remote_path.replace("\\", "/").split("/")[-1]
        roots = self._preview_roots()
        self.purge_previews()
        out = self._preview_dir()
        ledger = out / "partials.txt"
        wav = out / f"{uuid.uuid4().hex[:10]}.wav"
        ff = find_tool("ffmpeg", self.settings.ffmpeg_path)
        began = _time.monotonic()
        seen: set[Path] = set()

        def note(part: Path) -> None:                       # remembered so a crash can't leave it behind
            if part not in seen:
                seen.add(part)
                with open(ledger, "a", encoding="utf-8") as fh:
                    fh.write(str(part) + "\n")

        def release(t) -> None:
            """Stop the transfer and wait until the engine lets go of the file (on Windows it holds it locked)."""
            try:
                adapter.cancel(t)
            except Exception:
                pass
            t_end = _time.monotonic() + 8
            while _time.monotonic() < t_end:
                try:
                    st = adapter.transfer_status(t)
                    if st.failed or st.done:
                        break
                except Exception:
                    break
                _time.sleep(0.15)
            part = self._find_named(roots, name)
            last, t_end = -1, _time.monotonic() + 5
            while part is not None and part.exists() and _time.monotonic() < t_end:
                try:
                    with open(part, "r+b"):
                        pass
                    size = part.stat().st_size
                    if size == last:
                        return
                    last = size
                except OSError:
                    pass
                _time.sleep(0.15)

        def fetch(target: int, label: str) -> Path:
            """Ask for the file and wait until the partial holds `target` bytes (or the whole file came)."""
            t = adapter.request_download(cand)
            queued_since = None
            try:
                while True:
                    if should_stop():
                        raise ActionBlocked("Preview cancelled.")
                    if _time.monotonic() - began > timeout_s:
                        raise ActionBlocked("That copy is too slow to preview. Try one that's Ready now.")
                    st = adapter.transfer_status(t)
                    if st.failed and not st.done:
                        raise ActionBlocked("That copy wouldn't send. Try another one.")
                    state = st.state or ""
                    if "Queued" in state:
                        queued_since = queued_since or _time.monotonic()
                        waited = _time.monotonic() - queued_since
                        if "Remotely" in state and waited > 2.5:
                            # the search said "ready", but the sharer's free slot has gone since: they queued us
                            cand.free_slot, cand.queue_length = False, max(1, cand.queue_length or 0)
                            raise PreviewBusy("That copy was ready when you searched, but the sharer is busy now "
                                              "and put you in their line.")
                        if waited > 8:
                            raise ActionBlocked("Your other downloads are using every slot right now, so the preview "
                                                "couldn't start. Try again when one finishes."
                                                if "Locally" in state else
                                                "That copy has a wait, so it can't be previewed yet. "
                                                "Try one that's Ready now.")
                        progress("Waiting for the sharer…")
                    else:
                        queued_since = None
                    part = self._find_named(roots, name)
                    if part is not None:
                        note(part)
                    have = part.stat().st_size if part is not None and part.exists() else 0
                    if part is not None and (have >= target or st.done):
                        return part
                    progress(f"{label}… {min(99, int(100 * have / max(target, 1)))}%")
                    _time.sleep(0.2)
            finally:
                release(t)

        def read(part: Path, offset: int, n: int) -> bytes:
            with open(part, "rb") as fh:
                fh.seek(offset)
                return fh.read(n)

        def cut(args: list[str], ss: float | None) -> bool:
            cmd = [ff, "-v", "error", "-nostdin", "-y"] + args
            if ss:
                cmd += ["-ss", f"{ss:.2f}"]
            run(cmd + ["-t", f"{seconds:.2f}", "-vn", "-ac", "2", "-ar", "44100", str(wav)], timeout=60)
            return wav.exists() and wav.stat().st_size > 44100 * 4 * 2          # at least ~2 s of audio

        chunk = out / f"chunk.{ext or 'bin'}"
        try:
            if ext in pv.MIDDLE:
                progress("Reading the file's header…")
                part = fetch(pv.HEAD_BYTES[ext], "Reading the file's header")
                head = read(part, 0, 256 * 1024)
                plan = pv.plan_offset(ext, head, cand.size, length, start, seconds)
                if plan is not None:
                    offset, nbytes, extra = plan
                    if part.stat().st_size < offset + nbytes:
                        if part.stat().st_size < offset:
                            with open(part, "r+b") as fh:          # pad out to the middle; the engine resumes there
                                fh.truncate(offset)
                        part = fetch(offset + nbytes, "Getting a preview from the middle")
                    data = read(part, offset, nbytes)
                    if len(data) > nbytes // 4 and data.strip(b"\0"):
                        chunk.write_bytes(pv.chunk_bytes(ext, extra, data))
                        progress("Cutting the preview…")
                        if cut(pv.decode_args(ext, extra, str(chunk)), None):
                            return wav, start
                # header unreadable or the slice didn't decode: fall through to the slow way
            start = min(start, length * 0.33)
            need = int(cand.size * min(1.0, (start + seconds + 4) / max(length, 1)) + 256 * 1024)
            part = self._find_named(roots, name)
            if part is not None and part.exists():
                part.unlink(missing_ok=True)                        # start clean; a padded file has holes
            part = fetch(need, "Getting a preview")
            progress("Cutting the preview…")
            for s0 in (start, 0.0):
                if cut(["-i", str(part)], s0):
                    return wav, s0
            raise ActionBlocked("Couldn't cut a preview from that copy. Try another one.")
        finally:
            chunk.unlink(missing_ok=True)
            leftover = self._find_named(roots, name)
            for p in seen | ({leftover} if leftover is not None else set()):
                if p in seen and p.exists():                        # only what THIS preview wrote
                    try:
                        p.unlink()
                    except OSError:
                        pass
            if ledger.exists() and all(not p.exists() for p in seen):
                ledger.unlink(missing_ok=True)

    def request_download(self, cand: Candidate, playlist: str = "") -> dict:
        """User picked a search result: ask the client to download it and track it as a QUEUED job."""
        adapter = self._adapter_or_block()
        with self._lock:
            if self.db.find_remote(cand.user, cand.remote_path, tuple(J.NON_FINAL)):
                raise ActionBlocked("That file is already in your queue.")
            name = safe_filename(cand.display_name or "track")
            s = self.settings
            if cand.size > s.max_file_mb * 1024 * 1024:
                raise ActionBlocked(f"That file is {cand.size / 1e6:.0f} MB, over the {s.max_file_mb} MB limit in Settings.")
            if cand.extension.lower() not in {e.lower().lstrip(".") for e in s.extensions}:
                raise ActionBlocked(f".{cand.extension or '(none)'} files aren't accepted.")
            if looks_like_ad_bot(cand.user):
                raise ActionBlocked("That source is a shop's advertising account; it never sends files.")
            job_id = str(uuid.uuid4())
            expires = (datetime.now(timezone.utc) + timedelta(hours=s.retention_hours)).isoformat(timespec="seconds")
            self.db.insert_job(id=job_id, source_kind=cand.source_kind, source_path=None, original_name=name,
                               state=J.QUEUED, expires_at=expires, remote_user=cand.user, remote_path=cand.remote_path,
                               remote_size=cand.size, progress=0.0, message="Requested", playlist=playlist or None)
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
                self.db.update_job(job["id"], message="Waiting for the engine…")
                continue
            if t.done and t.local_path:
                try:
                    ready.append(self._stage_file(job["id"], t.local_path, move=True))
                    _tidy_empty_subfolder(t.local_path.parent, getattr(self.adapter, "downloads_dir", None))
                except Exception as e:
                    self.db.update_job(job["id"], state=J.ERROR, message=f"Couldn't move the download into quarantine: {e}")
                self.adapter.forget(t)                       # the engine has nothing more to do with it
            elif t.failed:
                self.adapter.forget(t)
                tries = int(job.get("retries") or 0)
                if "TimedOut" in (t.state or "") and tries < MAX_DOWNLOAD_RETRIES:
                    # the peer never got the transfer going; usually transient, so try again after a pause
                    wait = RETRY_WAIT_S[min(tries, len(RETRY_WAIT_S) - 1)]
                    retry_at = (datetime.now(timezone.utc) + timedelta(seconds=wait)).isoformat(timespec="seconds")
                    self.db.update_job(job["id"], transfer_id=None, retries=tries + 1, retry_at=retry_at, progress=0.0,
                                       message=f"No answer from the source. Retrying in {wait} s ({tries + 1} of {MAX_DOWNLOAD_RETRIES})…")
                    self.db.event(job["id"], "retry_scheduled", t.state or "")
                else:
                    self.db.update_job(job["id"], state=J.ERROR, message=f"Download failed: {t.state}")
            else:
                self.db.update_job(job["id"], progress=t.percent, message=t.state)
        # jobs waiting to be re-requested
        for job in self.db.jobs(states=(J.QUEUED,)):
            if job.get("transfer_id") or not job.get("retry_at"):
                continue
            if job["retry_at"] <= now_iso():
                self._rerequest(job)
        return ready

    def _rerequest(self, job: dict) -> None:
        cand = Candidate(source_kind=job["source_kind"], user=job["remote_user"], remote_path=job["remote_path"],
                         size=job["remote_size"] or 0, display_name=job["original_name"])
        try:
            t = self.adapter.request_download(cand)
            self.db.update_job(job["id"], transfer_id=t.transfer_id, retry_at=None, message=t.state or "Requested again")
            self.db.event(job["id"], "requested_again", str(job.get("retries") or 0))
        except ConnectorError as e:
            self.db.update_job(job["id"], state=J.ERROR, message=f"Download request failed: {e}")

    def retry_download(self, job_id: str) -> dict:
        """Ask the same source again, right now (the review page's Retry download)."""
        job = self.db.job(job_id)
        if not job or not job.get("remote_user"):
            raise ActionBlocked("This track didn't come from the network, so there is nothing to retry.")
        if self.adapter is None:
            raise ActionBlocked("Not connected yet.")
        if job.get("transfer_id"):
            try:
                self.adapter.forget(Transfer(transfer_id=job["transfer_id"], user=job["remote_user"],
                                             remote_path=job["remote_path"], size=job["remote_size"] or 0, state=""))
            except ConnectorError:
                pass
        self.db.update_job(job_id, state=J.QUEUED, transfer_id=None, retry_at=None, progress=0.0, hidden=0,
                           retries=int(job.get("retries") or 0), message="Asking the source again…")
        self._rerequest(self.db.job(job_id))
        return self.db.job(job_id)

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
            if move and isinstance(e, Rejected):
                try:                                   # we asked for it, we don't keep it: nothing unreviewed stays
                    source.unlink()
                except OSError:
                    pass
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

            library = self.settings.downloads_dir()              # <library>/<app name>, made on first download
            if job.get("playlist") and self.settings.playlist_folders:
                # one folder per batch playlist; a slash in the name is part of the name, not a sub-folder
                library = library / safe_filename(job["playlist"].replace("/", " - ").replace("\\", " - "))
            library.mkdir(parents=True, exist_ok=True)
            target = unique_path(library, safe_filename(job["original_name"]))
            self._transition(job, J.PROMOTING)
            self.db.update_job(job_id, final_path=str(target))
            tmp = target.with_name(f".{target.name}.{job_id[:8]}.part")
            try:
                shutil.copyfile(staged, tmp)
                if sha256_file(tmp) != analysis["sha256"]:
                    raise OSError("copy verification failed")
                self._tag_for_library(tmp, analysis, target.suffix)   # Rekordbox-ready tags + cover, on the copy only
                analysis["final_sha256"] = sha256_file(tmp)
                self.db.save_analysis(job_id, analysis)   # so crash recovery recognises the tagged copy
                if target.exists():                      # appeared meanwhile: never overwrite
                    target = unique_path(library, target.name)
                os.replace(tmp, target)
            except Exception as e:
                tmp.unlink(missing_ok=True)
                self.db.update_job(job_id, state=J.READY, final_path=None, message=f"Save failed: {e}")
                raise ActionBlocked(f"Couldn't save to the library: {e}") from e
            # hidden=1: a saved track leaves the Ready list by itself (it lives on in the Library page)
            self.db.update_job(job_id, state=J.PROMOTED, final_path=str(target), hidden=1,
                               disposition="promoted_override" if status == WARN else "promoted")
            self.db.event(job_id, "promoted", str(target))
            self._keep_spectrogram(job_id, analysis)        # the library page keeps showing it after staging is gone
            self._keep_cover(job_id, analysis)
            shutil.rmtree(staged.parent, ignore_errors=True)
            return target

    def remove_from_library(self, job_id: str, trash=None) -> Path | None:
        """Take a track out of the library. The file goes to the Trash/Recycle Bin (recoverable) via `trash`
        (a callable that returns True on success); the history row is kept but hidden, and crates forget it."""
        job = self._require(job_id)
        if job["state"] != J.PROMOTED:
            raise ActionBlocked("That track isn't in your library.")
        final = Path(job["final_path"]) if job.get("final_path") else None
        if final and final.exists():
            if trash is None or not trash(final):
                raise ActionBlocked("Couldn't move the file to the Trash. Is it open in another app?")
        with self._lock:
            self.db.update_job(job_id, state=J.REJECTED, disposition="removed_from_library", hidden=1)
            for cid in self.db.crates_of(job_id):
                self.db.remove_from_crate(cid, job_id)
            self.db.event(job_id, "removed_from_library", str(final or ""))
        return final

    def _tag_for_library(self, path: Path, analysis: dict, ext: str) -> None:
        """Best effort: a tagging problem never blocks the save (the audio was already verified)."""
        from ..media import metadata as md
        meta = analysis.get("meta") or {}
        try:
            m = md.Meta(**{k: meta.get(k, "") or "" for k in ("title", "mix", "artist", "album", "label", "catalog",
                                                              "year", "genre")})
            cover = Path(meta["cover_path"]) if meta.get("cover_path") else None
            analysis["tags_written"] = md.write_tags(path, m, analysis.get("music"), cover, ext)
        except Exception as e:                          # noqa: BLE001
            analysis["tags_written"] = []
            analysis["tags_error"] = str(e)[:200]

    def _keep_spectrogram(self, job_id: str, analysis: dict) -> None:
        src = analysis.get("spectrogram_path")
        if not src or not Path(src).exists():
            return
        keep_dir = self.db.path.parent / "spectrograms"
        try:
            keep_dir.mkdir(parents=True, exist_ok=True)
            dst = keep_dir / f"{job_id}.png"
            shutil.copyfile(src, dst)
            analysis["spectrogram_path"] = str(dst)
            self.db.save_analysis(job_id, analysis)
            self._prune_spectrograms(keep_dir)
        except OSError:
            pass

    def _keep_cover(self, job_id: str, analysis: dict) -> None:
        meta = analysis.get("meta") or {}
        src = Path(meta["cover_path"]) if meta.get("cover_path") else None
        if not src or not src.is_file():
            return
        try:
            keep_dir = self.db.path.parent / "covers"
            keep_dir.mkdir(parents=True, exist_ok=True)
            dst = keep_dir / f"{job_id}{src.suffix}"
            shutil.copyfile(src, dst)
            meta["cover_path"] = str(dst)
            self.db.save_analysis(job_id, analysis)
        except OSError:
            pass

    def _prune_spectrograms(self, keep_dir: Path) -> int:
        """Keep the newest N pictures; the rest can be redrawn from the library file when opened."""
        cap = max(10, int(self.settings.keep_spectrograms or 100))
        pngs = sorted(keep_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        removed = 0
        for p in pngs[cap:]:
            try:
                p.unlink(); removed += 1
            except OSError:
                pass
        return removed

    def redraw_spectrogram(self, job_id: str) -> str | None:
        """Draw the spectrogram again from the library copy (for a track whose picture was pruned).
        Decode only; no re-grading. Returns the new path, or None if the file is gone."""
        job = self._require(job_id)
        a = self.db.analysis(job_id)
        src = Path(job.get("final_path") or "")
        if not a or not src.exists():
            return None
        from ..media.decode import decode_and_analyze
        from ..media.spectrogram import render
        f = a.get("facts", {}) or {}
        sr = int(f.get("sample_rate_hz") or 44100)
        keep_dir = self.db.path.parent / "spectrograms"
        keep_dir.mkdir(parents=True, exist_ok=True)
        d = decode_and_analyze(src, sr, f.get("duration_s"), self.settings.ffmpeg_path,
                               timeout=max(120.0, (f.get("duration_s") or 600) * 1.5))
        try:
            out = render(d.frames, keep_dir / f"{job_id}.png")
        finally:
            d.frames = None
        a["spectrogram_path"] = str(out)
        self.db.save_analysis(job_id, a)
        self._prune_spectrograms(keep_dir)
        return str(out)

    def reject(self, job_id: str) -> None:
        with self._lock:
            job = self._require(job_id)
            if job["state"] not in (J.READY, J.ERROR):
                raise ActionBlocked("Wait until the check finishes before deleting.")
            self._remove_staging(job)
            self._transition(job, J.REJECTED)
            self.db.update_job(job_id, disposition="rejected", hidden=1)    # deleted: nothing left to look at
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

    def engine_housekeeping(self) -> None:
        """Periodic: tell the engine to drop finished transfers and old searches."""
        if self.adapter is not None:
            try:
                self.adapter.housekeeping()
            except Exception:
                pass

    def reconcile(self) -> None:
        """Run at startup: repair jobs interrupted by a crash or quit. Never deletes ambiguous files.
        QUEUED downloads are left alone: slskd keeps downloading while we're closed, and poll_downloads picks them up."""
        for job in self.db.jobs(states=(J.STAGING, J.ANALYZING, J.PROMOTING)):
            staged = Path(job["staged_path"]) if job["staged_path"] else None
            if job["state"] == J.PROMOTING:
                final = Path(job["final_path"]) if job["final_path"] else None
                a = self.db.analysis(job["id"])
                if final and final.is_file() and a and sha256_file(final) in (a["sha256"], a.get("final_sha256")):
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

    def hide_finished(self) -> int:
        """Remove every finished entry (downloaded, deleted, cancelled, expired, errored) from the queue panel."""
        n = 0
        for job in self.db.jobs(include_hidden=False):
            if job["state"] in J.FINAL or job["state"] == J.ERROR:
                self.hide(job["id"]); n += 1
        return n

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
