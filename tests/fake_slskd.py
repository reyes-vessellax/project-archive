"""A tiny stand-in for slskd's REST API, enough to test the adapter and the download flow.

It never touches the Soulseek network. "Downloading" a file means copying a fixture into the fake
downloads folder, in a subfolder named after the remote folder, the way slskd does.
"""
from __future__ import annotations

import json
import time
import shutil
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

API_KEY = "test-key"


class FakeSlskd:
    def __init__(self, downloads_dir: Path, library: dict[str, Path]):
        """library maps remote filename (e.g. r"@@peer\\Music\\Album\\track.mp3") -> local fixture file."""
        self.downloads_dir = downloads_dir
        self.library = library
        self.searches: dict[str, dict] = {}
        self.transfers: dict[str, dict] = {}        # id -> transfer row
        self.removed: list[str] = []                # transfer ids the app told us to forget
        self.auto_complete = True                   # finish downloads on the first status poll
        self.logged_in = True
        self.fail_next_download = False
        self.timeout_next_downloads = 0        # how many upcoming requests end "Completed, TimedOut"
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=None):
                data = json.dumps(body).encode() if body is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _auth(self) -> bool:
                if self.headers.get("X-API-Key") != API_KEY:
                    self._send(401, {"error": "unauthorized"})
                    return False
                return True

            def do_GET(self):
                if not self._auth():
                    return
                path = urlsplit(self.path).path
                parts = [unquote(p) for p in path.split("/") if p]      # ["api","v0",...]
                if parts[2:] == ["server"]:
                    return self._send(403)                        # like real slskd: Administrator role only
                if parts[2:] == ["application"]:
                    return self._send(200, {"version": {"current": "0.26.2.0"}, "server": {
                        "isConnected": True, "isLoggedIn": server.logged_in,
                        "username": "dj_test" if server.logged_in else None,
                        "state": "Connected, LoggedIn" if server.logged_in else "Connected"}})
                if parts[2:] == ["searches"]:
                    return self._send(200, [server._meta(k) for k in list(server.searches)])
                if parts[2] == "searches" and len(parts) == 4:
                    s = server.searches.get(parts[3])
                    if s:
                        return self._send(200, server._meta(parts[3]))
                    return self._send(200, s["meta"]) if s else self._send(404)
                if parts[2] == "searches" and len(parts) == 5 and parts[4] == "responses":
                    s = server.searches.get(parts[3])
                    if not s:
                        return self._send(404)
                    # like the real engine: nothing until the search has finished
                    return self._send(200, s["responses"] if server._finished(parts[3]) else [])
                if parts[2:4] == ["transfers", "downloads"] and len(parts) == 5:
                    rows = [t for t in server.transfers.values() if t["username"] == parts[4]]
                    return self._send(200, {"username": parts[4], "directories": [{"directory": "x", "files": rows}]})
                if parts[2:4] == ["transfers", "downloads"] and len(parts) == 6:
                    t = server.transfers.get(parts[5])
                    if not t:
                        return self._send(404)
                    server._advance(t)
                    return self._send(200, t)
                self._send(404)

            def do_POST(self):
                if not self._auth():
                    return
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"null")
                parts = [unquote(p) for p in urlsplit(self.path).path.split("/") if p]
                if parts[2:] == ["searches"]:
                    sid = body.get("id") or str(uuid.uuid4())
                    server.searches[sid] = server._make_search(sid, body["searchText"],
                                                               timeout_s=(body.get("searchTimeout") or 15000) / 1000)
                    return self._send(201, server._meta(sid))
                if parts[2:4] == ["transfers", "downloads"] and len(parts) == 5:
                    user = parts[4]
                    for f in body:
                        if f["filename"] not in server.library:
                            return self._send(500, {"error": "no such file"})
                        tid = str(uuid.uuid4())
                        server.transfers[tid] = {"id": tid, "username": user, "direction": "Download",
                                                 "filename": f["filename"], "size": f["size"], "state": "Queued, Remotely",
                                                 "percentComplete": 0.0, "bytesTransferred": 0}
                    return self._send(201)
                self._send(404)

            def do_DELETE(self):
                if not self._auth():
                    return
                parts = [unquote(p) for p in urlsplit(self.path).path.split("/") if p]
                if parts[2:] == ["transfers", "downloads", "all", "completed"]:
                    for k in [k for k, t in server.transfers.items() if t["state"].startswith("Completed")]:
                        server.removed.append(k); del server.transfers[k]
                    return self._send(204)
                if parts[2] == "searches" and len(parts) == 4:
                    server.searches.pop(parts[3], None); return self._send(204)
                if parts[2:4] == ["transfers", "downloads"] and len(parts) == 6:
                    t = server.transfers.get(parts[5])
                    if not t:
                        return self._send(404)
                    if "remove=true" in (urlsplit(self.path).query or ""):
                        server.removed.append(parts[5]); del server.transfers[parts[5]]
                    else:
                        t["state"] = "Completed, Cancelled"
                    return self._send(204)
                self._send(404)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    # behaviour -----------------------------------------------------------------------
    def _make_search(self, sid: str, text: str, timeout_s: float = 15.0) -> dict:
        words = text.lower().split()
        files = []
        for remote, local in self.library.items():
            if all(w in remote.lower() for w in words):
                files.append({"filename": remote, "size": local.stat().st_size,
                              "extension": local.suffix.lstrip("."), "bitRate": 320, "length": 40,
                              "isVariableBitRate": False, "sampleRate": 44100, "bitDepth": None, "isLocked": False})
        responses = [{"username": "peer_a", "hasFreeUploadSlot": True, "uploadSpeed": 500000, "queueLength": 0,
                      "fileCount": len(files), "files": files}] if files else []
        return {"meta": {"id": sid, "searchText": text, "state": "InProgress",
                         "responseCount": len(responses), "fileCount": len(files)},
                "responses": responses, "ends_at": time.monotonic() + min(timeout_s, self.search_seconds)}

    search_seconds = 0.6                        # tests shouldn't wait for a real 45 s search

    def _finished(self, sid: str) -> bool:
        s = self.searches.get(sid)
        return bool(s) and time.monotonic() >= s["ends_at"]

    def _meta(self, sid: str) -> dict:
        s = self.searches[sid]
        if not self._finished(sid):
            return {**s["meta"], "state": "InProgress"}
        return {**s["meta"], "state": s["meta"]["state"] if "Completed" in s["meta"]["state"] else "Completed, TimedOut"}

    def _advance(self, t: dict) -> None:
        if t["state"].startswith("Completed"):
            return
        if self.fail_next_download:
            self.fail_next_download = False
            t["state"] = "Completed, Errored"
            return
        if self.timeout_next_downloads > 0:
            self.timeout_next_downloads -= 1
            t["state"] = "Completed, TimedOut"
            return
        if not self.auto_complete:
            t["state"], t["percentComplete"] = "InProgress", 42.0
            return
        src = self.library[t["filename"]]
        parts = t["filename"].replace("\\", "/").split("/")
        folder = self.downloads_dir / parts[-2].replace("..", "_")
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, folder / parts[-1])
        t["state"], t["percentComplete"], t["bytesTransferred"] = "Completed, Succeeded", 100.0, t["size"]

    # lifecycle -----------------------------------------------------------------------
    def start(self) -> str:
        self.thread.start()
        host, port = self.httpd.server_address
        return f"http://127.0.0.1:{port}"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
