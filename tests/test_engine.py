"""The bundled engine: secrets, generated config, and (when a real slskd binary is available) a real
start -> API answers -> stop cycle. Set PROJECT_ARCHIVE_SLSKD_DIR to a folder holding slskd to run it."""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.config import Settings
from app.core.credentials import CredentialStore, new_api_key, new_soulseek_username
from app.core.slskd_manager import BackendUnavailable, SlskdManager, bundled_slskd_dir


@pytest.fixture
def creds(tmp_path):
    return CredentialStore(tmp_path / "secrets.json", use_keyring=False)


def test_credential_store_file_fallback(tmp_path, creds):
    assert creds.get("x") is None
    creds.set("x", "one")
    assert creds.get("x") == "one"
    assert CredentialStore(tmp_path / "secrets.json", use_keyring=False).get("x") == "one"   # persisted
    if os.name != "nt":
        assert oct((tmp_path / "secrets.json").stat().st_mode & 0o777) == "0o600"
    creds.delete("x")
    assert creds.get("x") is None
    v = creds.get_or_create("k", new_api_key)
    assert creds.get_or_create("k", new_api_key) == v                                       # stable


def test_generated_identity_looks_human():
    for _ in range(20):
        u = new_soulseek_username()
        assert re.fullmatch(r"pa_[a-z]{4,10}[a-z]{3,10}\d{2}", u), u
    assert len(new_api_key()) >= 32


def test_config_written_locked_to_loopback(tmp_path, creds):
    s = Settings(share_folder=str(tmp_path / "shared"))
    m = SlskdManager(s, creds=creds, instance_dir=tmp_path / "client", binary_dir=None)
    path = m.write_config()
    text = path.read_text()
    assert "headless: true" in text
    assert 'ip_address: "127.0.0.1"' in text
    assert "remote_file_management: false" in text
    assert f"port: {m.port}" in text and 1024 < m.port < 65536
    assert m.api_key in text and 'cidr: "127.0.0.1/32,::1/128"' in text
    assert "shared" in text                                                   # opt-in share folder passed through
    assert "SLSKD_SLSK" not in text
    user, password = m.soulseek_login()
    assert user.startswith("pa_") and len(password) > 20
    assert password not in text                                               # Soulseek password never on disk here
    assert m.downloads_dir.is_dir() and (tmp_path / "client" / "incomplete").is_dir()
    assert m.write_config() == path and m.soulseek_login() == (user, password)  # stable across launches


def test_own_account_overrides_generated(tmp_path, creds):
    s = Settings(soulseek_own_username="dj_real")
    creds.set("soulseek_own_password", "hunter2")
    m = SlskdManager(s, creds=creds, instance_dir=tmp_path / "client", binary_dir=None)
    assert m.soulseek_login() == ("dj_real", "hunter2")


def test_no_binary_is_a_clear_error(tmp_path, creds):
    m = SlskdManager(Settings(), creds=creds, instance_dir=tmp_path / "client", binary_dir=None)
    assert not m.available
    with pytest.raises(BackendUnavailable):
        m.start()


@pytest.mark.skipif(bundled_slskd_dir() is None, reason="no slskd binary available")
def test_real_engine_starts_and_answers(tmp_path, creds):
    m = SlskdManager(Settings(), creds=creds, instance_dir=tmp_path / "client")
    m.start()
    try:
        assert m.running
        from app.adapters.slskd_adapter import SlskdAdapter
        good = SlskdAdapter(m.url, m.api_key, str(m.downloads_dir)).health_check()
        assert good.available                                                 # API up, key accepted
        bad = SlskdAdapter(m.url, "not-the-key", str(m.downloads_dir)).health_check()
        assert not bad.available and "API key" in bad.message                 # key is enforced
    finally:
        m.stop()
    assert not m.running
