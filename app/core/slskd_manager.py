"""Runs the bundled slskd client as a hidden background process, so the user never sees or configures it.

First launch:  generate an API key and a Soulseek login (kept in the credential store), pick a free
               loopback port, write slskd.yml into the app's private data folder.
Every launch:  start slskd (no window, no logo, headless = no web UI), wait until its API answers.
On quit:       stop it.

The Soulseek password is never written to disk by us: it goes to slskd through environment variables.
slskd masks it in its own config output.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from ..config import APP_NAME, PREVIOUS_NAMES, Settings, data_dir
from ..media.tools import creation_flags
from .credentials import CredentialStore, new_api_key, new_password, new_soulseek_username

KEY_API = "slskd_api_key"
KEY_USER = "soulseek_username"
KEY_PASS = "soulseek_password"
KEY_WEB_USER = "slskd_web_username"
KEY_WEB_PASS = "slskd_web_password"
START_TIMEOUT_S = 40


class BackendUnavailable(RuntimeError):
    """The bundled client isn't here or won't start. Message is user-facing (no 'slskd' in it)."""


def bundled_slskd_dir() -> Path | None:
    """Where the packaged client lives: next to the frozen app, or vendor/slskd when run from source."""
    dirs = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "slskd")
        dirs.append(Path(sys.executable).parent / "slskd")
    dirs.append(Path(__file__).resolve().parents[2] / "vendor" / "slskd")
    override = os.environ.get("PROJECT_ARCHIVE_SLSKD_DIR")
    if override:
        dirs.insert(0, Path(override))
    return next((d for d in dirs if engine_exe(d) is not None), None)


# The firewall prompt names the program by its executable, so the build ships the engine renamed
# "<APP_NAME> Engine". The plain slskd name still works from source.
ENGINE_NAMES = (f"{APP_NAME} Engine", *(f"{n} Engine" for n in PREVIOUS_NAMES), "slskd")


def engine_exe(folder: Path) -> Path | None:
    suffix = ".exe" if sys.platform == "win32" else ""
    return next((folder / (n + suffix) for n in ENGINE_NAMES if (folder / (n + suffix)).is_file()), None)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


_AUTO = object()


class SlskdManager:
    def __init__(self, settings: Settings, creds: CredentialStore | None = None,
                 instance_dir: Path | None = None, binary_dir=_AUTO):
        self.settings = settings
        self.creds = creds or CredentialStore()
        self.instance_dir = instance_dir or data_dir() / "client"
        self.binary_dir: Path | None = bundled_slskd_dir() if binary_dir is _AUTO else binary_dir
        self.proc: subprocess.Popen | None = None
        self._log = None
        self.port: int | None = None
        self.last_error = ""

    # facts ---------------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self.binary_dir is not None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def api_key(self) -> str:
        return self.creds.get_or_create(KEY_API, new_api_key)

    @property
    def downloads_dir(self) -> Path:
        return self.instance_dir / "downloads"

    def soulseek_login(self) -> tuple[str, str]:
        """The account slskd logs in with: the user's own if they set one in Advanced, else one we made."""
        own = self.settings.soulseek_own_username.strip()
        if own:
            return own, self.creds.get("soulseek_own_password") or ""
        return (self.creds.get_or_create(KEY_USER, new_soulseek_username),
                self.creds.get_or_create(KEY_PASS, new_password))

    # config ------------------------------------------------------------------------------
    def write_config(self) -> Path:
        self.instance_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(exist_ok=True)
        (self.instance_dir / "incomplete").mkdir(exist_ok=True)
        self.port = self.port or free_port()
        web_user = self.creds.get_or_create(KEY_WEB_USER, lambda: "pa_" + new_password()[:12])
        web_pass = self.creds.get_or_create(KEY_WEB_PASS, new_password)
        shares = [self.settings.share_folder] if self.settings.share_folder.strip() else []
        cfg = {
            "headless": True,
            "remote_file_management": False,
            "directories": {"downloads": str(self.downloads_dir), "incomplete": str(self.instance_dir / "incomplete")},
            "shares": {"directories": shares},
            "web": {
                "port": self.port,
                "ip_address": "127.0.0.1",
                "https": {"disabled": True},
                "logging": False,
                "authentication": {
                    "disabled": False,
                    "username": web_user,
                    "password": web_pass,
                    "api_keys": {"project_archive": {"key": self.api_key, "role": "ReadWrite",
                                                     "cidr": "127.0.0.1/32,::1/128"}},
                },
            },
        }
        path = self.instance_dir / "slskd.yml"
        path.write_text(_yaml(cfg), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path

    # process ------------------------------------------------------------------------------
    def start(self, wait: bool = True) -> None:
        if self.running:
            return
        if not self.available:
            raise BackendUnavailable("The download engine isn't included in this build.")
        cfg = self.write_config()
        exe = engine_exe(self.binary_dir)
        user, password = self.soulseek_login()
        env = {**os.environ, "SLSKD_SLSK_USERNAME": user, "SLSKD_SLSK_PASSWORD": password,
               "NO_COLOR": "1", "DOTNET_CLI_TELEMETRY_OPTOUT": "1"}
        self._log = log = open(self.instance_dir / "engine.log", "ab")
        self.proc = subprocess.Popen(
            [str(exe), "--app-dir", str(self.instance_dir), "--config", str(cfg), "--headless", "--no-logo",
             "--no-config-watch"],
            cwd=str(self.binary_dir), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            shell=False, creationflags=creation_flags(),
        )
        if wait:
            self.wait_ready()

    def wait_ready(self, timeout: float = START_TIMEOUT_S) -> None:
        from ..adapters.slskd_adapter import SlskdAdapter
        adapter = SlskdAdapter(self.url, self.api_key, str(self.downloads_dir), timeout=3)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.running:
                self.last_error = "The download engine stopped unexpectedly."
                raise BackendUnavailable(self.last_error)
            st = adapter.health_check()
            if st.available:
                self.last_error = ""
                return
            time.sleep(0.5)
        self.last_error = "The download engine didn't start in time."
        self.stop()
        raise BackendUnavailable(self.last_error)

    def stop(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        self.proc = None
        if self._log:
            self._log.close()
            self._log = None

    def restart(self) -> None:
        self.stop()
        self.start()


def _yaml(value, indent: int = 0) -> str:
    """Minimal YAML writer for our own config: dicts, lists, strings, numbers, booleans, None."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        out = []
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:\n{_yaml(v, indent + 1)}")
            else:
                out.append(f"{pad}{k}: {_yaml(v, indent + 1)}")
        return "\n".join(out)
    if isinstance(value, list):
        if not value:
            return "[]"
        return "\n".join(f"{pad}- {_yaml(v, indent + 1)}" for v in value)
    if value is None:
        return "~"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))                 # JSON string literals are valid YAML scalars
