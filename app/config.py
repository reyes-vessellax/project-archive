"""Paths and default settings. Works the same on macOS and Windows."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

APP_NAME = "Project Archive"


def data_dir() -> Path:
    """Private per-user application data folder (database, staging/quarantine)."""
    override = os.environ.get("PROJECT_ARCHIVE_DATA")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


def default_library_dir() -> Path:
    return Path.home() / "Music" / "Project Archive Library"


@dataclass
class Settings:
    library_dir: str = str(default_library_dir())
    incoming_dir: str = ""                    # watched folder; empty = off
    staging_dir: str = ""                     # empty = <data_dir>/staging
    mp3_min_kbps: int = 320                   # warn below this (CBR)
    vbr_min_avg_kbps: int = 220               # warn below this average (VBR)
    retention_hours: int = 24                 # undecided staged files expire after this
    max_file_mb: int = 2048
    max_duration_minutes: int = 240
    extensions: list[str] = field(default_factory=lambda: ["mp3", "wav", "flac", "aiff", "aif"])
    ffmpeg_path: str = ""                     # empty = bundled copy, then PATH

    def staging_root(self) -> Path:
        return Path(self.staging_dir) if self.staging_dir else data_dir() / "staging"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)
