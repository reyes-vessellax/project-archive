"""The user's account, stored locally until the website backend exists.

Sign-up collects name, email and password. The password is never stored: only a salted PBKDF2 hash,
so sign-in works offline and the same screens can later talk to the backend instead. Profile fields
(DJ name, bio) live here too. Billing is deliberately absent: the UI shows the section, nothing is stored.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass, field, asdict

from ..storage.db import Database

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 10
MAX_PASSWORD = 256
BIO_MAX = 200


class AccountError(ValueError):
    """Shown to the user as-is."""


@dataclass
class Account:
    name: str = ""
    email: str = ""
    dj_name: str = ""
    bio: str = ""
    created_at: str = ""
    password_hash: str = ""                   # "pbkdf2$<iterations>$<salt hex>$<hash hex>"
    extra: dict = field(default_factory=dict)  # room for the backend's fields later

    @property
    def initials(self) -> str:
        parts = [p for p in self.name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or (self.email[:1].upper() if self.email else "?")

    @property
    def display_name(self) -> str:
        return self.dj_name or self.name or self.email


def _hash(password: str, salt: bytes | None = None, iterations: int = 200_000) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2${iterations}${salt.hex()}${digest.hex()}"


def _verify(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(candidate.hex(), digest)
    except (ValueError, AttributeError):
        return False


class AccountStore:
    KEY = "account"

    def __init__(self, db: Database):
        self.db = db

    def load(self) -> Account | None:
        d = self.db.load_settings().get(self.KEY)
        return Account(**{k: v for k, v in d.items() if k in Account.__dataclass_fields__}) if d else None

    def save(self, a: Account) -> None:
        self.db.save_settings({self.KEY: asdict(a)})

    # sign-up / sign-in ---------------------------------------------------------------------
    def sign_up(self, name: str, email: str, password: str) -> Account:
        name, email = name.strip(), email.strip().lower()
        if not name:
            raise AccountError("Please enter your name.")
        if not _EMAIL.match(email):
            raise AccountError("That email address doesn't look right.")
        if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
            raise AccountError(f"Use between {MIN_PASSWORD} and {MAX_PASSWORD} characters for your password.")
        from ..storage.db import now
        a = Account(name=name, email=email, created_at=now(), password_hash=_hash(password))
        self.save(a)
        return a

    def sign_in(self, email: str, password: str) -> Account:
        a = self.load()
        if len(password) > MAX_PASSWORD:
            raise AccountError("Email or password doesn't match.")
        if not a or a.email != email.strip().lower() or not _verify(password, a.password_hash):
            raise AccountError("Email or password doesn't match.")
        return a

    def change_password(self, current: str, new: str) -> None:
        a = self.load()
        if not a or not _verify(current, a.password_hash):
            raise AccountError("Your current password doesn't match.")
        if not MIN_PASSWORD <= len(new) <= MAX_PASSWORD:
            raise AccountError(f"Use between {MIN_PASSWORD} and {MAX_PASSWORD} characters for your new password.")
        a.password_hash = _hash(new)
        self.save(a)

    def update_profile(self, name: str, dj_name: str, bio: str, email: str) -> Account:
        a = self.load()
        if not a:
            raise AccountError("No account yet.")
        name, email = name.strip(), email.strip().lower()
        if not name:
            raise AccountError("Please enter your name.")
        if not _EMAIL.match(email):
            raise AccountError("That email address doesn't look right.")
        if len(bio) > BIO_MAX:
            raise AccountError(f"Keep your bio under {BIO_MAX} characters.")
        a.name, a.dj_name, a.bio, a.email = name, dj_name.strip(), bio.strip(), email
        self.save(a)
        return a

    def delete(self) -> None:
        self.db.save_settings({self.KEY: None})
