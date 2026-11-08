"""Updater: only our signed builds install; downloads are verified; archives can't escape; never downgrades."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import stat
import sys
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core import updater as U


@pytest.fixture
def keys():
    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = base64.b64encode(priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    return pem, pub


def manifest(version="9.9.9", url="https://dl.example/app.zip", data=b"zipbytes"):
    return {"version": version, "notes": "New things",
            "assets": {U.platform_key(): {"url": url, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}}}


def test_versions():
    assert U.is_newer("0.6.0", "0.5.8") and U.is_newer("0.5.10", "0.5.9") and U.is_newer("v1.0", "0.9.9")
    assert not U.is_newer("0.5.8", "0.5.8") and not U.is_newer("0.5.7", "0.5.8")


def test_signed_update_is_offered(keys):
    pem, pub = keys
    doc = U.sign_manifest(manifest(), pem)
    u = U.check("https://x/latest.json", lambda url: json.dumps(doc).encode(), pub, "0.5.8")
    assert u and u.version == "9.9.9" and u.url == "https://dl.example/app.zip"


def test_forged_or_tampered_manifest_is_refused(keys):
    pem, pub = keys
    doc = U.sign_manifest(manifest(), pem)
    tampered = dict(doc, manifest=doc["manifest"].replace("dl.example", "evil.example"))
    with pytest.raises(U.UpdateError, match="signed"):
        U.check("https://x", lambda url: json.dumps(tampered).encode(), pub, "0.5.8")
    other_pem = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                           serialization.NoEncryption())
    forged = U.sign_manifest(manifest(), other_pem)
    with pytest.raises(U.UpdateError):
        U.check("https://x", lambda url: json.dumps(forged).encode(), pub, "0.5.8")


def test_no_downgrade_and_no_http(keys):
    pem, pub = keys
    old = U.sign_manifest(manifest(version="0.1.0"), pem)
    assert U.check("https://x", lambda url: json.dumps(old).encode(), pub, "0.5.8") is None
    plain = U.sign_manifest(manifest(url="http://dl.example/app.zip"), pem)
    with pytest.raises(U.UpdateError, match="https"):
        U.check("https://x", lambda url: json.dumps(plain).encode(), pub, "0.5.8")


def test_updater_off_until_configured():
    assert U.check("", lambda url: b"", "abc") is None
    assert U.check("https://x", lambda url: b"", "REPLACE_WITH_PUBLIC_KEY") is None


def test_download_verifies_size_and_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(U, "updates_dir", lambda: tmp_path / "updates")
    data = b"real update bytes" * 1000
    good = U.Update("9.9.9", "", "https://dl/x.zip", hashlib.sha256(data).hexdigest(), len(data))
    path = U.download(good, opener=lambda url: io.BytesIO(data))
    assert path.read_bytes() == data
    bad = U.Update("9.9.8", "", "https://dl/x.zip", hashlib.sha256(b"other").hexdigest(), len(data))
    with pytest.raises(U.UpdateError):
        U.download(bad, opener=lambda url: io.BytesIO(data))
    assert not list((tmp_path / "updates").glob("*.part"))


def _zip(entries: dict) -> Path:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, (data, mode) in entries.items():
            zi = zipfile.ZipInfo(name)
            zi.external_attr = mode << 16
            z.writestr(zi, data)
    return buf


def test_extract_refuses_path_escapes(tmp_path):
    zp = tmp_path / "evil.zip"
    zp.write_bytes(_zip({"App.app/x": (b"1", 0o644), "../../outside.txt": (b"2", 0o644)}).getvalue())
    with pytest.raises(U.UpdateError):
        U.safe_extract(zp, tmp_path / "out")
    assert not (tmp_path / "outside.txt").exists()


def test_extract_refuses_symlink_escapes(tmp_path):
    zp = tmp_path / "evil.zip"
    zp.write_bytes(_zip({"App.app/Contents/link": (b"/etc/passwd", stat.S_IFLNK | 0o777)}).getvalue())
    with pytest.raises(U.UpdateError):
        U.safe_extract(zp, tmp_path / "out")


def test_extract_keeps_exec_bits_and_internal_links(tmp_path):
    zp = tmp_path / "ok.zip"
    zp.write_bytes(_zip({"App.app/Contents/MacOS/App": (b"#!", 0o755),
                         "App.app/Contents/Frameworks/cur": (b"MacOS", stat.S_IFLNK | 0o777)}).getvalue())
    top = U.safe_extract(zp, tmp_path / "out")
    assert top.name == "App.app"
    assert os.access(top / "Contents/MacOS/App", os.X_OK)
    assert (top / "Contents/Frameworks/cur").is_symlink()


@pytest.mark.skipif(sys.platform == "win32", reason="mac/linux swap script")
def test_stage_install_writes_a_swap_script(tmp_path, monkeypatch):
    app = tmp_path / "Applications" / "Pied Piper.app" / "Contents" / "MacOS"
    app.mkdir(parents=True); (app / "Pied Piper").write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "Pied Piper"))
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(U, "updates_dir", lambda: tmp_path / "updates")
    zp = tmp_path / "u.zip"
    zp.write_bytes(_zip({"Pied Piper.app/Contents/MacOS/Pied Piper": (b"new", 0o755)}).getvalue())
    cmd = U.stage_install(zp)
    script = Path(cmd[-1]).read_text()
    assert "Pied Piper.app.previous" in script and "kill -0" in script and "open " in script
    assert (tmp_path / "updates" / "staged" / "Pied Piper.app").is_dir()


def test_never_updates_from_source():
    assert U.install_target() is None


def test_windows_swap_script_is_safe(tmp_path, monkeypatch):
    """Windows: unpack beside the app (same drive), retry the rename, always start an app again, never run
    from inside the app folder."""
    app_dir = tmp_path / "D" / "DigMart"
    app_dir.mkdir(parents=True); (app_dir / "DigMart.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_dir / "DigMart.exe"))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(U, "updates_dir", lambda: tmp_path / "C" / "AppData" / "DigMart" / "updates")
    zp = tmp_path / "u.zip"
    zp.write_bytes(_zip({"DigMart/DigMart.exe": (b"new", 0o644)}).getvalue())
    cmd = U.stage_install(zp)
    script = Path(cmd[-1]).read_text()
    assert (tmp_path / "D" / "DigMart.update" / "DigMart").is_dir()           # same drive as the app
    assert "for ($i = 0; $i -lt 30" in script and "Rename-Item" in script     # retried
    assert script.count("Start-Process -FilePath") == 2                      # old app back if it fails, new if it works
    assert "DigMart Engine" in script                                        # waits for the engine to let go
    assert cmd[0] == "powershell" and "-File" in cmd
    seen = {}
    monkeypatch.setattr(U.subprocess, "Popen", lambda c, **kw: seen.update(kw))
    U.launch_installer(cmd)
    assert seen["cwd"] == str(tmp_path / "C" / "AppData" / "DigMart" / "updates")   # not inside the app folder
