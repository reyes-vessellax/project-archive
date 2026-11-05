"""SQLite job history. Metadata only; audio bytes never go in the database."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    source_path TEXT,
    source_size INTEGER,
    source_mtime REAL,
    original_name TEXT NOT NULL,
    staged_path TEXT,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    final_path TEXT,
    disposition TEXT,
    message TEXT,
    remote_user TEXT,
    remote_path TEXT,
    remote_size INTEGER,
    transfer_id TEXT,
    progress REAL
);
CREATE TABLE IF NOT EXISTS analyses (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id),
    sha256 TEXT, detected_container TEXT, codec TEXT, duration REAL, bitrate INTEGER,
    bitrate_mode TEXT, sample_rate INTEGER, channels INTEGER, bit_depth INTEGER,
    decode_ok INTEGER, spectrum_path TEXT, overall_status TEXT, analysis_json TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, timestamp TEXT, event_type TEXT, message TEXT
);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS jobs_source ON jobs(source_path, source_size, source_mtime);
"""

# Columns added after the first release. Existing databases get them with ALTER TABLE.
MIGRATIONS = {
    "jobs": {"remote_user": "TEXT", "remote_path": "TEXT", "remote_size": "INTEGER",
             "transfer_id": "TEXT", "progress": "REAL"},
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._con = sqlite3.connect(str(path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        for table, cols in MIGRATIONS.items():
            have = {r[1] for r in self._con.execute(f"PRAGMA table_info({table})")}
            with self._con:
                for name, typ in cols.items():
                    if name not in have:
                        self._con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")

    def close(self):
        with self._lock:
            self._con.close()

    # jobs -----------------------------------------------------------------------
    def insert_job(self, **job) -> None:
        job.setdefault("created_at", now())
        job.setdefault("updated_at", job["created_at"])
        cols = ", ".join(job)
        with self._lock, self._con:
            self._con.execute(f"INSERT INTO jobs ({cols}) VALUES ({', '.join('?' * len(job))})", tuple(job.values()))

    def update_job(self, job_id: str, **fields) -> None:
        fields["updated_at"] = now()
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock, self._con:
            self._con.execute(f"UPDATE jobs SET {sets} WHERE id = ?", (*fields.values(), job_id))

    def job(self, job_id: str) -> dict | None:
        with self._lock:
            row = self._con.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def jobs(self, states: tuple[str, ...] | None = None, limit: int = 500) -> list[dict]:
        q, args = "SELECT * FROM jobs", ()
        if states:
            q += f" WHERE state IN ({', '.join('?' * len(states))})"
            args = states
        q += " ORDER BY created_at DESC LIMIT ?"
        with self._lock:
            return [dict(r) for r in self._con.execute(q, (*args, limit)).fetchall()]

    def find_source(self, path: str, size: int, mtime: float) -> dict | None:
        with self._lock:
            row = self._con.execute("SELECT * FROM jobs WHERE source_path = ? AND source_size = ? AND source_mtime = ?",
                                    (path, size, mtime)).fetchone()
        return dict(row) if row else None

    def find_remote(self, user: str, remote_path: str, states: tuple[str, ...]) -> dict | None:
        q = (f"SELECT * FROM jobs WHERE remote_user = ? AND remote_path = ? AND state IN "
             f"({', '.join('?' * len(states))}) LIMIT 1")
        with self._lock:
            row = self._con.execute(q, (user, remote_path, *states)).fetchone()
        return dict(row) if row else None

    # analyses ---------------------------------------------------------------------
    def save_analysis(self, job_id: str, a: dict) -> None:
        f = a["facts"]
        row = (job_id, a["sha256"], f.get("container"), f.get("codec"), f.get("duration_s"), f.get("bitrate_bps"),
               f.get("bitrate_mode"), f.get("sample_rate_hz"), f.get("channels"), f.get("bit_depth"),
               int(bool(a.get("decode_ok"))), a.get("spectrogram_path"), a["overall_status"], json.dumps(a))
        with self._lock, self._con:
            self._con.execute("INSERT OR REPLACE INTO analyses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)

    def analysis(self, job_id: str) -> dict | None:
        with self._lock:
            row = self._con.execute("SELECT analysis_json FROM analyses WHERE job_id = ?", (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    # settings / events ----------------------------------------------------------------
    def load_settings(self) -> dict:
        with self._lock:
            rows = self._con.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    def save_settings(self, d: dict) -> None:
        with self._lock, self._con:
            for k, v in d.items():
                self._con.execute("INSERT OR REPLACE INTO settings VALUES (?, ?, ?)", (k, json.dumps(v), now()))

    def event(self, job_id: str | None, event_type: str, message: str = "") -> None:
        with self._lock, self._con:
            self._con.execute("INSERT INTO events (job_id, timestamp, event_type, message) VALUES (?,?,?,?)",
                              (job_id, now(), event_type, message[:500]))
