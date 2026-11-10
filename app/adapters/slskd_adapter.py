"""Soulseek search and download through a locally installed slskd client (https://github.com/slskd/slskd).

slskd owns the Soulseek login, the network connection and the transfers. We only talk to its local
REST API with an API key. Nothing here implements the Soulseek protocol.

Setup the user does once (documented in the README):
  1. Install and run slskd, enter their Soulseek credentials in slskd.yml.
  2. Add an API key under web.authentication.api_keys in slskd.yml.
  3. Paste the slskd URL, the API key and slskd's downloads folder into the app's Settings (Advanced).

Everything slskd returns about remote files is untrusted metadata; our own analysis decides.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import threading
import uuid
from pathlib import Path
from urllib import error, parse, request

from ..core.safety import clean_text, safe_filename
from .base import Candidate, ConnectorError, ConnectorStatus, SearchResult, SourceAdapter, Transfer, parse_track

API = "/api/v0"
MAX_BODY = 64 * 1024 * 1024          # never read more than this from the client


def _log(line: str) -> None:
    """Search-path diagnostics into app.log (the data folder). Cheap, append-only, never raises."""
    try:
        from datetime import datetime
        from ..config import data_dir
        with open(data_dir() / "app.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} engine: {line}\n")
    except Exception:
        pass
LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]"}
_SPLIT = re.compile(r"[\\/]")


def remote_basename(remote_path: str) -> str:
    """Peers report Windows-style paths ("@@abc\\Music\\Track.mp3"); take the last component."""
    parts = [p for p in _SPLIT.split(remote_path) if p]
    return parts[-1] if parts else remote_path


def remote_folder(remote_path: str) -> str:
    parts = [p for p in _SPLIT.split(remote_path) if p]
    return parts[-2] if len(parts) >= 2 else ""


class SlskdAdapter(SourceAdapter):
    source_kind = "soulseek"

    def __init__(self, base_url: str, api_key: str, downloads_dir: str, timeout: float = 20.0):
        self.base_url = (base_url or "http://127.0.0.1:5030").rstrip("/")
        self.api_key = api_key or ""
        self.downloads_dir = Path(downloads_dir) if downloads_dir else None
        self.timeout = timeout
        host = parse.urlsplit(self.base_url)
        if host.scheme not in ("http", "https"):
            raise ConnectorError("The engine address must start with http:// or https://.")
        if host.scheme == "http" and (host.hostname or "") not in LOOPBACK:
            # Spec 9.1: the client API should stay on this machine unless it's protected by TLS.
            raise ConnectorError("Plain http to the engine is only allowed on this computer (localhost). Use https for a remote one.")

    # HTTP ------------------------------------------------------------------------------
    # One keep-alive connection per thread: search polls every few hundred ms, and a fresh TCP
    # handshake per call was a visible share of the latency.
    _local = threading.local()

    def _conn(self) -> http.client.HTTPConnection:
        conns = getattr(self._local, "conns", None)
        if conns is None:
            conns = self._local.conns = {}
        c = conns.get(self.base_url)
        if c is None:
            u = parse.urlsplit(self.base_url)
            cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
            c = conns[self.base_url] = cls(u.hostname, u.port, timeout=self.timeout)
        return c

    def _drop_conn(self) -> None:
        conns = getattr(self._local, "conns", {})
        c = conns.pop(self.base_url, None)
        if c:
            try:
                c.close()
            except Exception:
                pass

    def _call(self, method: str, path: str, body=None, query: dict | None = None):
        url = API + path + ("?" + parse.urlencode(query) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": "application/json", "Connection": "keep-alive"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        for attempt in (0, 1):                      # one retry if a kept-alive socket went stale
            conn = self._conn()
            try:
                conn.request(method, url, body=data, headers=headers)
                resp = conn.getresponse()
                raw = resp.read(MAX_BODY)
                status = resp.status
                break
            except (http.client.HTTPException, ConnectionError, OSError) as e:
                self._drop_conn()
                if attempt == 1 or isinstance(e, (ConnectionRefusedError, TimeoutError)):
                    if isinstance(e, TimeoutError):
                        raise ConnectorError("The engine didn't answer in time.") from e
                    raise ConnectorError("Can't reach the engine. Is it running?") from e
        if "/searches" in path:
            _log(f"{method} {path} -> {status} {len(raw)} bytes")
        if status in (401, 403):
            raise ConnectorError("The engine rejected the API key.")
        if status == 404:
            raise ConnectorError(f"The engine doesn't know that item ({method} {path}).")
        if status >= 400:
            raise ConnectorError(f"The engine answered with an error ({status}).")
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError as e:
            raise ConnectorError("The engine returned something unexpected.") from e

    # contract ------------------------------------------------------------------------------
    def health_check(self) -> ConnectorStatus:
        # /application works with any key role; /server needs Administrator and answers 403 otherwise.
        try:
            app = self._call("GET", "/application") or {}
        except ConnectorError as e:
            return ConnectorStatus(available=False, message=str(e))
        s = app.get("server") or {}
        logged = bool(s.get("isLoggedIn")) or "LoggedIn" in str(s.get("state", ""))
        user = str(s.get("username") or "")
        msg = f"Connected to Soulseek as {user}" if logged and user else \
              ("Connected to Soulseek" if logged else "Signing in to Soulseek…")
        return ConnectorStatus(available=True, logged_in=logged, username=user, message=msg)

    def search(self, query: str, timeout_s: float = 45.0) -> SearchResult:
        query = " ".join(query.split())
        if len(query) < 2:
            raise ConnectorError("Type at least two characters to search.")
        sid = str(uuid.uuid4())
        _log(f"search POST {sid[:8]} {query!r}")
        self._call("POST", "/searches", {"id": sid, "searchText": query[:200],
                                         "searchTimeout": int(timeout_s * 1000), "fileLimit": 20000,
                                         "filterResponses": True, "responseLimit": 2000,
                                         "minimumResponseFileCount": 1})
        return SearchResult(query=query, search_id=sid, finished=False)

    def search_status(self, search_id: str) -> tuple[bool, int, int, str]:
        """The engine only exposes a search's responses once it has finished; while it runs, the search
        record still carries live counts, which is what the waiting screen shows."""
        meta = self._call("GET", f"/searches/{search_id}") or {}
        state = str(meta.get("state", ""))
        error = ""
        if "Errored" in state:
            error = "The search couldn't run. You may have lost the connection; it reconnects on its own."
        elif "Cancelled" in state and search_id not in getattr(self, "_stopped", set()):
            error = "The search was cancelled."         # not when WE ended it (deadline or results dried up)
        return "Completed" in state, _int(meta.get("responseCount")) or 0, _int(meta.get("fileCount")) or 0, error

    def forget_search(self, search_id: str) -> None:
        self._call("DELETE", f"/searches/{search_id}")

    def stop_search(self, search_id: str) -> None:
        """End a running search now. The engine keeps every response it has received and marks the search
        'Completed, Cancelled'; the responses become readable at once."""
        self._stopped = getattr(self, "_stopped", set()); self._stopped.add(search_id)
        self._call("PUT", f"/searches/{search_id}")

    def search_results(self, search_id: str) -> SearchResult:
        # includeResponses=true carries whatever the engine has in memory; the separate /responses
        # endpoint only answers once the search has finished. Use the first, fall back to the second.
        meta = self._call("GET", f"/searches/{search_id}", query={"includeResponses": "true"}) or {}
        state = str(meta.get("state", ""))
        finished = "Completed" in state
        error = ""
        if "Errored" in state:
            error = "The search couldn't run. You may have lost the connection; it reconnects on its own."
        elif "Cancelled" in state and search_id not in getattr(self, "_stopped", set()):
            error = "The search was cancelled."
        rows = meta.get("responses") or []
        if not rows and finished:
            rows = self._call("GET", f"/searches/{search_id}/responses") or []
        cands = []
        for r in rows:
            user = str(r.get("username") or "")
            files = [(f, False) for f in (r.get("files") or [])] + [(f, True) for f in (r.get("lockedFiles") or [])]
            for f, locked in files:
                path = str(f.get("filename") or "")
                if not user or not path:
                    continue
                name = clean_text(remote_basename(path))
                artist, title, mix = parse_track(name)
                try:
                    size = max(0, int(f.get("size") or 0))
                except (TypeError, ValueError):
                    size = 0
                cands.append(Candidate(
                    source_kind=self.source_kind, user=user, remote_path=path,
                    size=size, display_name=name, folder=clean_text(remote_folder(path)), artist=artist, title=title, mix=mix,
                    extension=Path(name).suffix.lstrip(".").lower(),          # from the NAME; the peer's field is untrusted
                    bitrate_kbps=_int(f.get("bitRate")), vbr=f.get("isVariableBitRate"),
                    length_s=_int(f.get("length")), sample_rate_hz=_int(f.get("sampleRate")),
                    bit_depth=_int(f.get("bitDepth")), free_slot=r.get("hasFreeUploadSlot"),
                    queue_length=_int(r.get("queueLength")), upload_speed=_int(r.get("uploadSpeed")),
                    locked=locked or bool(f.get("isLocked")),
                ))
        _log(f"search_results {search_id[:8]} state={state!r} responses={len(rows)} candidates={len(cands)}")
        return SearchResult(query=str(meta.get("searchText") or ""), search_id=search_id,
                            finished=finished, candidates=cands, state=state, error=error)

    def request_download(self, candidate: Candidate) -> Transfer:
        if candidate.locked:
            raise ConnectorError("That peer has locked this file; it can't be requested.")
        user = parse.quote(candidate.user, safe="")
        self._call("POST", f"/transfers/downloads/{user}", [{"filename": candidate.remote_path, "size": candidate.size}])
        t = self._find_transfer(candidate.user, candidate.remote_path)
        if t is None:
            raise ConnectorError("The download was accepted but isn't listed yet. Try again in a moment.")
        return t

    def transfer_status(self, transfer: Transfer) -> Transfer:
        user = parse.quote(transfer.user, safe="")
        try:
            row = self._call("GET", f"/transfers/downloads/{user}/{transfer.transfer_id}")
        except ConnectorError as e:
            if "doesn't know" in str(e):               # the engine dropped it from its list
                t = self._find_transfer(transfer.user, transfer.remote_path)
                if t:
                    return self._with_local(t)
                transfer.failed, transfer.state = True, "Removed from client"
                return transfer
            raise
        return self._with_local(_transfer_from(row or {}))

    def cancel(self, transfer: Transfer) -> bool:
        user = parse.quote(transfer.user, safe="")
        try:
            self._call("DELETE", f"/transfers/downloads/{user}/{transfer.transfer_id}", query={"remove": "true"})
            return True
        except ConnectorError:
            return False

    def forget(self, transfer: Transfer) -> None:
        user = parse.quote(transfer.user, safe="")
        try:                                        # remove=true drops it from the client's list; it's already done
            self._call("DELETE", f"/transfers/downloads/{user}/{transfer.transfer_id}", query={"remove": "true"})
        except ConnectorError:
            pass

    def housekeeping(self) -> None:
        """Completed downloads out of the client's list, old searches gone, nothing left lurking."""
        try:
            self._call("DELETE", "/transfers/downloads/all/completed")
        except ConnectorError:
            pass
        try:
            for s in self._call("GET", "/searches") or []:
                if "Completed" in str(s.get("state", "")) and s.get("id"):
                    self._call("DELETE", f"/searches/{s['id']}")
        except ConnectorError:
            pass

    # helpers ---------------------------------------------------------------------------------
    def _find_transfer(self, user: str, remote_path: str) -> Transfer | None:
        data = self._call("GET", f"/transfers/downloads/{parse.quote(user, safe='')}") or {}
        for d in data.get("directories") or []:
            for f in d.get("files") or []:
                if f.get("filename") == remote_path:
                    return _transfer_from(f)
        return None

    def _with_local(self, t: Transfer) -> Transfer:
        if t.done and t.local_path is None:
            t.local_path = self.locate_download(t.remote_path, t.size)
            if t.local_path is None:
                t.done, t.failed, t.state = False, True, "Finished, but the file wasn't found in the downloads folder"
        return t

    def locate_download(self, remote_path: str, size: int) -> Path | None:
        """slskd saves a finished file under its downloads folder (in a subfolder named after the
        remote folder). Don't trust any path: find it by exact name and size, newest first."""
        if not self.downloads_dir or not self.downloads_dir.is_dir():
            return None
        name = remote_basename(remote_path)
        wanted = {name, safe_filename(name), _slskd_sanitised(name)}
        best: tuple[float, Path] | None = None
        for root, dirs, files in os.walk(self.downloads_dir):
            dirs[:] = [d for d in dirs if not Path(root, d).is_symlink()]
            for fname in files:
                if fname not in wanted and _slskd_sanitised(fname) not in wanted:
                    continue
                p = Path(root, fname)
                if p.is_symlink() or not p.is_file():
                    continue
                st = p.stat()
                if size and st.st_size != size:
                    continue
                if best is None or st.st_mtime > best[0]:
                    best = (st.st_mtime, p)
        return best[1] if best else None


_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _slskd_sanitised(name: str) -> str:
    """slskd replaces characters Windows can't store with underscores when it saves a file."""
    return _ILLEGAL.sub("_", name)


def _transfer_from(row: dict) -> Transfer:
    state = str(row.get("state") or "")
    completed = state.startswith("Completed")
    return Transfer(
        transfer_id=str(row.get("id") or ""), user=str(row.get("username") or ""),
        remote_path=str(row.get("filename") or ""), size=int(row.get("size") or 0), state=state,
        percent=float(row.get("percentComplete") or 0.0), bytes_done=int(row.get("bytesTransferred") or 0),
        done=completed and "Succeeded" in state, failed=completed and "Succeeded" not in state,
    )


def _int(v) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None
