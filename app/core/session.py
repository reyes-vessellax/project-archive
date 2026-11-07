"""Auto save: where you were in the app, so closing, quitting or a crash puts you straight back.

Downloads, checks, decisions and the library already live in the database. This file holds the rest:
the page, the selected track, the search box and filters, the open Library row and filter, the batch
list in progress, the window size. Written atomically (temp file + replace) and at most every 2 s, so a
crash mid-write can never leave a broken file; a broken or missing file just means a fresh start.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class Session:
    page: str = "home"                  # home | search | ready | library | batch | settings
    selected_job: str = ""
    search_text: str = ""
    filters: dict = field(default_factory=dict)       # availability.Filters as a dict
    library_filter: str = ""
    library_open_job: str = ""
    library_scroll: int = 0
    batch_name: str = ""
    batch_items: list = field(default_factory=list)   # [{artist, title, mix, source, status, job_id}]
    batches: list = field(default_factory=list)       # [{id, name, service, items: [...]}], newest first
    batch_selected: str = ""
    window: list = field(default_factory=list)        # [x, y, w, h]
    maximized: bool = False
    saved_at: float = 0.0


class SessionStore:
    def __init__(self, path: Path, min_interval_s: float = 2.0):
        self.path = path
        self.min_interval_s = min_interval_s
        self._lock = threading.Lock()
        self._last_write = 0.0
        self._pending: Session | None = None
        self._timer: threading.Timer | None = None

    def load(self) -> Session:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            known = {f.name for f in fields(Session)}
            return Session(**{k: v for k, v in raw.items() if k in known})
        except (OSError, ValueError, TypeError):
            return Session()

    def save(self, s: Session, now: bool = False) -> None:
        """Debounced: call it on every change; it writes at most every `min_interval_s`, and always the latest."""
        with self._lock:
            self._pending = s
            wait = self.min_interval_s - (time.monotonic() - self._last_write)
            if now or wait <= 0:
                self._write_locked()
            elif self._timer is None:
                self._timer = threading.Timer(wait, self.flush)
                self._timer.daemon = True
                self._timer.start()

    def flush(self) -> None:
        with self._lock:
            self._write_locked()

    def _write_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        s, self._pending = self._pending, None
        if s is None:
            return
        s.saved_at = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(asdict(s), f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            self._last_write = time.monotonic()
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
