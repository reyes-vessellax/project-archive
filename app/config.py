"""Paths and default settings. Works the same on macOS and Windows."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# The product name, in ONE place. "DEADWAX" is a placeholder until the real name is chosen; every
# visible use of the name reads this constant (window title, dialogs, bundled engine, data folder).
APP_NAME = "DEADWAX"
PREVIOUS_NAMES = ("Project Archive",)      # earlier placeholder; existing installs are migrated from it


def data_dir() -> Path:
    """Private per-user application data folder (database, staging/quarantine, engine)."""
    override = os.environ.get("PROJECT_ARCHIVE_DATA")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    current = base / APP_NAME
    if not current.exists():
        for old in PREVIOUS_NAMES:                # keep the user's account, history and engine identity
            prev = base / old
            if prev.is_dir():
                try:
                    prev.rename(current)
                except OSError:
                    return prev
                break
    return current


def default_library_dir() -> Path:
    return Path.home() / "Music" / f"{APP_NAME} Library"


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
    max_concurrent_analyses: int = 5          # analysis slots; further tracks wait in the queue
    setup_done: bool = False                  # first-run setup (library folder + sharing) completed
    theme: str = "light"                      # light | dark
    firewall_notice_shown: bool = False       # one-time explanation before the first engine start
    share_folder: str = ""                    # opt-in: a folder to share back on Soulseek (empty = off)
    # Advanced only. By default the app runs its own bundled copy of slskd (the Soulseek engine) with a
    # generated API key and a generated Soulseek login; the user never sees any of it.
    use_own_slskd: bool = False               # point the app at an slskd the user already runs instead
    slskd_url: str = "http://127.0.0.1:5030"
    slskd_api_key: str = ""
    slskd_downloads_dir: str = ""             # the folder that slskd saves finished downloads into
    soulseek_own_username: str = ""           # use the user's own Soulseek account (password in the credential store)

    def staging_root(self) -> Path:
        return Path(self.staging_dir) if self.staging_dir else data_dir() / "staging"

    @property
    def own_slskd_configured(self) -> bool:
        return self.use_own_slskd and bool(self.slskd_api_key.strip())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)
