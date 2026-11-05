"""Paths and default settings. Works the same on macOS and Windows."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# The product name, in ONE place. "Pied Piper" is a placeholder (a dev-time joke) until the real name is
# chosen; every visible use of the name reads this constant (window title, dialogs, engine, data folder).
APP_NAME = "Pied Piper"
APP_SLUG = "PiedPiper"                    # for file and artifact names that shouldn't carry a space
APP_VERSION = "0.4.8"                     # keep in step with pyproject.toml; the build names the artifact with it
PREVIOUS_NAMES = ("DEADWAX", "Project Archive")   # earlier placeholders; existing installs are migrated from them


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
    return Path.home() / "Music"


DOWNLOADS_SUBFOLDER = APP_NAME        # approved downloads go to <library>/<APP_NAME>/, created on first download


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
    firewall_notice_shown: bool = False       # legacy flag (0.2/0.3.0-0.3.3); kept so old settings still load
    firewall_done_for: str = ""               # engine path we last confirmed a firewall rule for (or the user declined)
    tour_done: bool = False                   # first-launch walkthrough finished or skipped
    share_folder: str = ""                    # opt-in: a folder to share back on Soulseek (empty = off)
    listen_port: int = 0                      # the engine's Soulseek port; picked once (49152-65535) and kept
    upnp: bool = True                         # ask the router to open that port (UPnP) so results reach us directly
    # Advanced only. By default the app runs its own bundled copy of slskd (the Soulseek engine) with a
    # generated API key and a generated Soulseek login; the user never sees any of it.
    use_own_slskd: bool = False               # point the app at an slskd the user already runs instead
    slskd_url: str = "http://127.0.0.1:5030"
    slskd_api_key: str = ""
    slskd_downloads_dir: str = ""             # the folder that slskd saves finished downloads into
    soulseek_own_username: str = ""           # use the user's own Soulseek account (password in the credential store)

    def staging_root(self) -> Path:
        return Path(self.staging_dir) if self.staging_dir else data_dir() / "staging"

    def downloads_dir(self) -> Path:
        """Where approved tracks land: one tidy folder inside the user's library, named after the app.
        If the user pointed the library at that folder itself, don't nest another one."""
        lib = Path(self.library_dir)
        return lib if lib.name.lower() == DOWNLOADS_SUBFOLDER.lower() else lib / DOWNLOADS_SUBFOLDER

    @property
    def own_slskd_configured(self) -> bool:
        return self.use_own_slskd and bool(self.slskd_api_key.strip())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)
