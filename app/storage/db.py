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
    progress REAL,
    hidden INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS analyses (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id),
    sha256 TEXT, detected_container TEXT, codec TEXT, duration REAL, bitrate INTEGER,
    bitrate_mode TEXT, sample_rate INTEGER, channels INTEGER, bit_depth INTEGER,
    decode_ok INTEGER, spectrum_path TEXT, overall_status TEXT, analysis_json TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS crates (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, created_at TEXT);
CREATE TABLE IF NOT EXISTS crate_items (crate_id TEXT NOT NULL, job_id TEXT NOT NULL, added_at TEXT,
    PRIMARY KEY (crate_id, job_id));
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, timestamp TEXT, event_type TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS wishes (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,            -- watching | checking | found | paused
    next_run_at TEXT,                -- when the standing search runs again (watching only)
    last_run_at TEXT,
    runs INTEGER NOT NULL DEFAULT 0,  -- searches made for this wish
    tries INTEGER NOT NULL DEFAULT 0, -- candidates sent to quarantine so far
    job_id TEXT,                     -- the candidate currently being checked / the one found
    candidates_json TEXT,            -- the remaining gated candidates from the last search
    last_seen INTEGER,               -- rows the last search returned (before the gate)
    found_at TEXT,
    seen INTEGER NOT NULL DEFAULT 1, -- 0 = found and not yet looked at (the bell counts these)
    note TEXT,
    playlist TEXT,                   -- batch import this wish belongs to (NULL for a single wish)
    position INTEGER,                -- its place in that playlist
    expect_s INTEGER,                -- expected length in seconds, when the playlist gave one
    expires_at TEXT,                 -- the standing order ends here unless renewed (status becomes expired)
    artist TEXT,                     -- the structured wish, when the user filled the form (any part may be empty)
    title TEXT,
    mix TEXT
);
CREATE TABLE IF NOT EXISTS discover_cache (url TEXT PRIMARY KEY, json TEXT NOT NULL, fetched_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS jobs_source ON jobs(source_path, source_size, source_mtime);
CREATE INDEX IF NOT EXISTS events_job ON events(job_id, event_type);
"""

# Columns added after the first release. Existing databases get them with ALTER TABLE.
MIGRATIONS = {
    "jobs": {"remote_user": "TEXT", "remote_path": "TEXT", "remote_size": "INTEGER",
             "transfer_id": "TEXT", "progress": "REAL", "hidden": "INTEGER NOT NULL DEFAULT 0",
             "retries": "INTEGER NOT NULL DEFAULT 0", "retry_at": "TEXT",
             "playlist": "TEXT",                        # batch playlist it came from (its library sub-folder)
             "origin": "TEXT",                          # "discover": dug ahead by Discover (hidden from the Queue)
             "discover_json": "TEXT"},                  # the record it came from (cover, label, year, era)
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
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

    def jobs_version(self) -> str:
        """Changes whenever any job row changes: cheap cache key."""
        with self._lock:
            row = self._con.execute("SELECT COUNT(*), MAX(updated_at) FROM jobs").fetchone()
        return f"{row[0]}:{row[1]}"

    def library_version(self) -> str:
        """Changes only when saved (PROMOTED) tracks change, not on every download progress tick."""
        with self._lock:
            row = self._con.execute("SELECT COUNT(*), MAX(updated_at) FROM jobs WHERE state = 'PROMOTED'").fetchone()
        return f"{row[0]}:{row[1]}"

    def update_job(self, job_id: str, **fields) -> None:
        fields["updated_at"] = now()
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock, self._con:
            self._con.execute(f"UPDATE jobs SET {sets} WHERE id = ?", (*fields.values(), job_id))

    def job(self, job_id: str) -> dict | None:
        with self._lock:
            row = self._con.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def jobs(self, states: tuple[str, ...] | None = None, limit: int = 500, include_hidden: bool = True) -> list[dict]:
        where, args = [], ()
        if states:
            where.append(f"state IN ({', '.join('?' * len(states))})")
            args = states
        if not include_hidden:
            where.append("hidden = 0")
        q = "SELECT * FROM jobs" + (" WHERE " + " AND ".join(where) if where else "")
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

    # Discover's cache of MusicBrainz / Discogs answers --------------------------------------
    def cache_get(self, url: str) -> tuple[dict, str] | None:
        with self._lock:
            row = self._con.execute("SELECT json, fetched_at FROM discover_cache WHERE url = ?", (url,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def cache_put(self, url: str, data: dict) -> None:
        with self._lock, self._con:
            self._con.execute("INSERT OR REPLACE INTO discover_cache VALUES (?,?,?)", (url, json.dumps(data), now()))

    def source_rows(self) -> list[dict]:
        """One row per network download, with what reputation needs (see core/reputation.py)."""
        q = """SELECT j.remote_user, j.state, j.staged_path, j.remote_size, a.overall_status,
                      (SELECT MIN(timestamp) FROM events e WHERE e.job_id = j.id AND e.event_type = 'requested') AS requested_at,
                      (SELECT MIN(timestamp) FROM events e WHERE e.job_id = j.id AND e.event_type = 'staged') AS staged_at
               FROM jobs j LEFT JOIN analyses a ON a.job_id = j.id
               WHERE j.remote_user IS NOT NULL AND j.remote_user != ''"""
        with self._lock:
            return [dict(r) for r in self._con.execute(q).fetchall()]

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

    # crates (the user's own groupings of library tracks) ------------------------------
    def crates(self) -> list[dict]:
        with self._lock:
            rows = self._con.execute(
                "SELECT c.id, c.name, COUNT(i.job_id) AS n FROM crates c LEFT JOIN crate_items i ON i.crate_id = c.id "
                "LEFT JOIN jobs j ON j.id = i.job_id AND j.state = 'PROMOTED' GROUP BY c.id ORDER BY c.name COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]

    def create_crate(self, name: str) -> str:
        import uuid
        name = " ".join(name.split())[:60]
        if not name:
            raise ValueError("Give the crate a name.")
        with self._lock, self._con:
            row = self._con.execute("SELECT id FROM crates WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
            if row:
                return row[0]
            cid = uuid.uuid4().hex[:12]
            self._con.execute("INSERT INTO crates VALUES (?,?,?)", (cid, name, now()))
            return cid

    def rename_crate(self, crate_id: str, name: str) -> None:
        name = " ".join(name.split())[:60]
        if name:
            with self._lock, self._con:
                self._con.execute("UPDATE crates SET name = ? WHERE id = ?", (name, crate_id))

    def delete_crate(self, crate_id: str) -> None:
        """Removes the crate only; the tracks stay in the library."""
        with self._lock, self._con:
            self._con.execute("DELETE FROM crate_items WHERE crate_id = ?", (crate_id,))
            self._con.execute("DELETE FROM crates WHERE id = ?", (crate_id,))

    def add_to_crate(self, crate_id: str, job_id: str) -> None:
        with self._lock, self._con:
            self._con.execute("INSERT OR IGNORE INTO crate_items VALUES (?,?,?)", (crate_id, job_id, now()))

    def remove_from_crate(self, crate_id: str, job_id: str) -> None:
        with self._lock, self._con:
            self._con.execute("DELETE FROM crate_items WHERE crate_id = ? AND job_id = ?", (crate_id, job_id))

    def crate_jobs(self, crate_id: str) -> set[str]:
        with self._lock:
            return {r[0] for r in self._con.execute("SELECT job_id FROM crate_items WHERE crate_id = ?", (crate_id,))}

    def crates_of(self, job_id: str) -> set[str]:
        with self._lock:
            return {r[0] for r in self._con.execute("SELECT crate_id FROM crate_items WHERE job_id = ?", (job_id,))}

    # wishes -------------------------------------------------------------------------
    def insert_wish(self, **wish) -> None:
        wish.setdefault("created_at", now())
        wish.setdefault("updated_at", wish["created_at"])
        cols = ", ".join(wish)
        with self._lock, self._con:
            self._con.execute(f"INSERT INTO wishes ({cols}) VALUES ({', '.join('?' * len(wish))})", tuple(wish.values()))

    def update_wish(self, wish_id: str, **fields) -> None:
        fields["updated_at"] = now()
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock, self._con:
            self._con.execute(f"UPDATE wishes SET {sets} WHERE id = ?", (*fields.values(), wish_id))

    def delete_wish(self, wish_id: str) -> None:
        with self._lock, self._con:
            self._con.execute("DELETE FROM wishes WHERE id = ?", (wish_id,))

    def wish(self, wish_id: str) -> dict | None:
        with self._lock:
            row = self._con.execute("SELECT * FROM wishes WHERE id = ?", (wish_id,)).fetchone()
        return dict(row) if row else None

    def wishes(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._con.execute("SELECT * FROM wishes ORDER BY created_at DESC").fetchall()]

    # settings / events ----------------------------------------------------------------
    def load_settings(self) -> dict:
        with self._lock:
            rows = self._con.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    def save_settings(self, d: dict) -> None:
        with self._lock, self._con:
            for k, v in d.items():
                self._con.execute("INSERT OR REPLACE INTO settings VALUES (?, ?, ?)", (k, json.dumps(v), now()))

    def event_message(self, job_id: str, event_type: str) -> str | None:
        """The message of the latest event of this type for a job (None if it never happened)."""
        with self._lock:
            row = self._con.execute("SELECT message FROM events WHERE job_id = ? AND event_type = ? ORDER BY id DESC LIMIT 1",
                                    (job_id, event_type)).fetchone()
        return row[0] if row else None

    def event(self, job_id: str | None, event_type: str, message: str = "") -> None:
        with self._lock, self._con:
            self._con.execute("INSERT INTO events (job_id, timestamp, event_type, message) VALUES (?,?,?,?)",
                              (job_id, now(), event_type, message[:500]))
