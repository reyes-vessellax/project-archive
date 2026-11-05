"""Secrets the app keeps for the user: the API key for the bundled client and the generated Soulseek login.

Stored in the operating system's credential vault when one is available (Windows Credential Manager,
macOS Keychain, via the optional `keyring` package). Otherwise in a JSON file in the private app data
folder, readable only by the user. Never in Settings, never in the database, never shown in the UI.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from ..config import APP_NAME, data_dir

try:                                        # optional: present in the packaged app
    import keyring                          # type: ignore
    from keyring.errors import KeyringError  # type: ignore
except Exception:                           # pragma: no cover
    keyring = None
    KeyringError = Exception

SERVICE = APP_NAME

# Generated Soulseek usernames look like a person, not a bot: "pa_" + two words + two digits.
_ADJ = ("velvet", "midnight", "copper", "neon", "amber", "dusty", "silver", "cobalt", "warm", "deep",
        "quiet", "hazy", "golden", "electric", "slow", "lunar", "crimson", "static", "loose", "soft")
_NOUN = ("fader", "groove", "crate", "needle", "reverb", "sampler", "cutter", "basement", "sunrise", "pulse",
         "shuffle", "echo", "bassline", "platter", "tempo", "vinyl", "mixer", "jukebox", "lowend", "dub")


class CredentialStore:
    def __init__(self, path: Path | None = None, use_keyring: bool | None = None):
        self.path = path or data_dir() / "secrets.json"
        self.use_keyring = keyring is not None if use_keyring is None else (use_keyring and keyring is not None)

    def get(self, name: str) -> str | None:
        if self.use_keyring:
            try:
                v = keyring.get_password(SERVICE, name)
                if v is not None:
                    return v
            except KeyringError:
                pass
        return self._file().get(name)

    def set(self, name: str, value: str) -> None:
        if self.use_keyring:
            try:
                keyring.set_password(SERVICE, name, value)
                return
            except KeyringError:
                pass
        d = self._file()
        d[name] = value
        self._write(d)

    def delete(self, name: str) -> None:
        if self.use_keyring:
            try:
                keyring.delete_password(SERVICE, name)
            except Exception:
                pass
        d = self._file()
        if name in d:
            del d[name]
            self._write(d)

    def get_or_create(self, name: str, make) -> str:
        v = self.get(name)
        if v is None:
            v = make()
            self.set(name, v)
        return v

    # file fallback ---------------------------------------------------------------------
    def _file(self) -> dict:
        try:
            return json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, d: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(d))
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)


def new_api_key() -> str:
    return secrets.token_urlsafe(32)


def new_password() -> str:
    return secrets.token_urlsafe(24)


def new_soulseek_username() -> str:
    return f"pa_{secrets.choice(_ADJ)}{secrets.choice(_NOUN)}{secrets.randbelow(90) + 10}"
