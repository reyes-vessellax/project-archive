"""Updates for live users: check, download in the background, verify, install on restart.

Safety model
- The update manifest is signed with an Ed25519 key that only the release pipeline holds (GitHub secret).
  The app ships with the PUBLIC key and refuses any manifest whose signature doesn't verify, so whoever
  controls the download host still can't push code to users.
- Each download must match the size and SHA-256 listed in the signed manifest.
- https only; never downgrades; never installs while running. "Restart to update" hands over to a small
  script that waits for the app to exit, swaps the app, keeps the old copy as a backup, and starts the new
  one. The new version removes the backup once it has started cleanly (see `finish_pending`).
- Running from source: never updates (the developer has git).

Manifest (latest.json), signature over the exact UTF-8 bytes of "manifest":
  {"manifest": "{\"version\":\"0.6.0\",\"notes\":\"...\",\"assets\":{\"windows-x64\":{\"url\":...,\"sha256\":...,\"size\":...}}}",
   "sig": "<base64 ed25519 signature>"}
"""
from __future__ import annotations

from . import net as _netmod

import base64
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..config import APP_NAME, APP_VERSION, FULL_VERSION, data_dir

# Where the signed manifest lives. Set when hosting is decided; empty = updater off.
UPDATE_URL = os.environ.get("DIGMART_UPDATE_URL",
                            "https://github.com/reyes-vessellax/project-archive/releases/latest/download/latest.json")
# Ed25519 public key (raw 32 bytes, base64). The matching private key never enters the repo.
PUBLIC_KEY_B64 = "FDru7AGMRiAKdgsnbzGQ5/97gcaQkHyYCdq+W37x1eE="


class UpdateError(RuntimeError):
    pass


@dataclass
class Update:
    version: str
    notes: str
    url: str
    sha256: str
    size: int


def platform_key() -> str:
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if sys.platform == "win32":
        return f"windows-{arch}"
    if sys.platform == "darwin":
        return f"macos-{arch}"
    return f"linux-{arch}"


def vtuple(v: str) -> tuple[int, ...]:
    out = []
    for part in v.strip().lstrip("v").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def is_newer(remote: str, local: str = FULL_VERSION) -> bool:
    return vtuple(remote) > vtuple(local)


def verify_manifest(doc: dict, public_key_b64: str = PUBLIC_KEY_B64) -> dict:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        raw = doc["manifest"]
        sig = base64.b64decode(doc["sig"])
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        key.verify(sig, raw.encode("utf-8"))
        return json.loads(raw)
    except (KeyError, ValueError, TypeError, InvalidSignature) as e:
        raise UpdateError("The update isn't signed by us, so it was ignored.") from e


def sign_manifest(manifest: dict, private_key_pem: bytes) -> dict:
    """Used by the release pipeline (packaging/make_manifest.py), never by the app."""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    raw = json.dumps(manifest, separators=(",", ":"), sort_keys=True)
    key = load_pem_private_key(private_key_pem, password=None)
    return {"manifest": raw, "sig": base64.b64encode(key.sign(raw.encode("utf-8"))).decode()}


def _get(url: str, timeout: float = 15.0) -> bytes:
    import urllib.request
    if not url.startswith("https://"):
        raise UpdateError("Update links must be https.")
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION} updater"})
    with _net_urlopen(req, timeout=timeout) as r:            # noqa: S310 - https enforced above
        return r.read(1024 * 1024)


def check(url: str = UPDATE_URL, fetch: Callable[[str], bytes] = _get, public_key_b64: str = PUBLIC_KEY_B64,
          local_version: str = FULL_VERSION) -> Update | None:
    """The newer update for this computer, or None. Raises UpdateError on a bad/forged manifest."""
    if not url or public_key_b64.startswith("REPLACE"):
        return None
    try:
        doc = json.loads(fetch(url).decode("utf-8"))
    except Exception as e:                                           # noqa: BLE001 - offline etc.
        raise UpdateError(f"Couldn't reach the update server ({type(e).__name__}: {str(e)[:120]}).") from e
    m = verify_manifest(doc, public_key_b64)
    if not is_newer(str(m.get("version", "0")), local_version):
        return None
    asset = (m.get("assets") or {}).get(platform_key())
    if not asset:
        return None
    if not str(asset.get("url", "")).startswith("https://"):
        raise UpdateError("Update links must be https.")
    return Update(version=str(m["version"]), notes=str(m.get("notes", "")), url=asset["url"],
                  sha256=str(asset["sha256"]).lower(), size=int(asset["size"]))


def updates_dir() -> Path:
    return data_dir() / "updates"


def download(u: Update, progress: Callable[[int, int], None] = lambda done, total: None,
             opener: Callable[[str], object] | None = None) -> Path:
    """Stream to updates/<version>.zip.part, verify size + SHA-256, then rename. Returns the verified zip."""
    import urllib.request
    d = updates_dir(); d.mkdir(parents=True, exist_ok=True)
    final = d / f"{APP_NAME.replace(' ', '')}-{u.version}-{platform_key()}.zip"
    if final.is_file() and final.stat().st_size == u.size and _sha256(final) == u.sha256:
        return final
    part = final.with_suffix(".zip.part")
    h, done = hashlib.sha256(), 0
    resp = opener(u.url) if opener else _net_urlopen(  # noqa: S310 - https checked in check()
        urllib.request.Request(u.url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION} updater"}), timeout=30)
    with resp as r, open(part, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            done += len(chunk)
            if done > u.size:
                break
            h.update(chunk); f.write(chunk); progress(done, u.size)
    if done != u.size or h.hexdigest() != u.sha256:
        part.unlink(missing_ok=True)
        raise UpdateError("The update download didn't match what we published, so it was thrown away.")
    os.replace(part, final)
    return final


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------ install
def install_target() -> Path | None:
    """The thing to replace: the .app bundle on macOS, the app folder on Windows. None when not frozen."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        for p in exe.parents:
            if p.suffix == ".app":
                return p
        return None
    return exe.parent


def safe_extract(zip_path: Path, dest: Path) -> Path:
    """Extract with no path escapes; returns the single top-level item (the .app or the app folder)."""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if root not in target.parents and target != root:
                raise UpdateError("The update archive tried to write outside its folder.")
            mode = (info.external_attr >> 16) & 0o777
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:      # symlink (macOS frameworks use them)
                link = z.read(info).decode()
                resolved = (target.parent / link).resolve()
                if Path(link).is_absolute() or (root not in resolved.parents and resolved != root):
                    raise UpdateError("The update archive has a link that points outside it.")
                os.symlink(link, target)
                continue
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            if mode:
                os.chmod(target, mode)
    tops = [p for p in dest.iterdir()]
    if len(tops) != 1:
        raise UpdateError("The update archive isn't laid out the way we expect.")
    return tops[0]


def stage_install(zip_path: Path) -> list[str]:
    """Unpack next to the current app and write the swap script. Returns the command to run on quit."""
    target = install_target()
    if target is None:
        raise UpdateError("Updates install only in the packaged app.")
    work = updates_dir() / "staged"
    if sys.platform == "win32":
        # Unpack beside the app (same drive): PowerShell can't move a folder from %APPDATA% to another drive.
        side = target.with_name(target.name + ".update")
        try:
            shutil.rmtree(side, ignore_errors=True); side.mkdir(parents=True, exist_ok=True); work = side
        except OSError:
            pass                                                      # read-only parent: fall back to the user folder
    shutil.rmtree(work, ignore_errors=True)
    new = safe_extract(zip_path, work)
    backup = target.with_name(target.name + ".previous")
    pid = os.getpid()
    if sys.platform == "win32":
        exe_name = Path(sys.executable).name.replace("'", "''")
        target_s, new_s, backup_s, work_s = (str(p).replace("'", "''") for p in (target, new, backup, work))
        log_s = str(updates_dir().parent / "update.log").replace("'", "''")
        engines = ", ".join("'" + n.replace("'", "''") + "'" for n in _engine_names())
        script = updates_dir() / "apply_update.ps1"
        script.parent.mkdir(parents=True, exist_ok=True)
        # Windows holds files briefly after a process ends (the engine, Defender scanning the new files, an
        # Explorer window on the folder), so the rename is retried for ~30 s. Whatever happens, an app is
        # started again at the end: the new one if the swap worked, the old one if it didn't.
        script.write_text(
            "$ErrorActionPreference = 'Continue'\n"
            f"$t = '{target_s}'; $n = '{new_s}'; $b = '{backup_s}'; $w = '{work_s}'; $log = '{log_s}'\n"
            "function Log($m) { Add-Content -Path $log -Value ((Get-Date -Format s) + ' ' + $m) }\n"
            f"Wait-Process -Id {pid} -Timeout 60 -ErrorAction SilentlyContinue\n"
            f"foreach ($e in @({engines})) {{ Get-Process -Name $e -ErrorAction SilentlyContinue | "
            "Wait-Process -Timeout 15 -ErrorAction SilentlyContinue }\n"
            "Start-Sleep -Milliseconds 800\n"
            "if (Test-Path $b) { Remove-Item -Recurse -Force $b -ErrorAction SilentlyContinue }\n"
            "$ok = $false\n"
            "for ($i = 0; $i -lt 30 -and -not $ok; $i++) {\n"
            "  try { Rename-Item -Path $t -NewName (Split-Path $b -Leaf) -ErrorAction Stop; $ok = $true }\n"
            "  catch { Start-Sleep -Seconds 1 }\n"
            "}\n"
            "if (-not $ok) { Log 'update: the app folder stayed in use; kept the current version'; "
            f"Start-Process -FilePath (Join-Path $t '{exe_name}'); exit 1 }}\n"
            "try { Move-Item -Path $n -Destination $t -ErrorAction Stop; Log 'update: installed' }\n"
            "catch { Log ('update: move failed, restoring: ' + $_); Rename-Item -Path $b -NewName (Split-Path $t -Leaf) }\n"
            "if ($w -ne $n -and (Test-Path $w)) { Remove-Item -Recurse -Force $w -ErrorAction SilentlyContinue }\n"
            f"Start-Process -FilePath (Join-Path $t '{exe_name}')\n", encoding="utf-8")
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script)]
    script = updates_dir() / "apply_update.sh"
    q = lambda p: "'" + str(p).replace("'", "'\\''") + "'"                       # noqa: E731
    script.write_text(
        "#!/bin/sh\nset -e\n"
        f"while kill -0 {pid} 2>/dev/null; do sleep 0.3; done\n"
        f"rm -rf {q(backup)}\n"
        f"mv {q(target)} {q(backup)}\n"
        f"if ! mv {q(new)} {q(target)}; then mv {q(backup)} {q(target)}; exit 1; fi\n"
        f"open {q(target)}\n", encoding="utf-8")
    script.chmod(0o700)
    return ["/bin/sh", str(script)]


def _engine_names() -> tuple[str, ...]:
    try:
        from .slskd_manager import ENGINE_NAMES
        return tuple(ENGINE_NAMES)
    except Exception:                                                    # noqa: BLE001
        return ()


def launch_installer(cmd: list[str]) -> None:
    """Start the swap script detached; the caller then quits the app.
    It runs from the updates folder: on Windows a process whose working folder is inside the app folder
    (the default when the app was double-clicked) would stop that folder from being renamed."""
    d = updates_dir(); d.mkdir(parents=True, exist_ok=True)
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True,
          "cwd": str(d)}
    if sys.platform == "win32":
        kw["creationflags"] = 0x00000008 | 0x00000200 | getattr(subprocess, "CREATE_NO_WINDOW", 0)  # DETACHED | NEW_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)                                          # noqa: S603 - our own script, fixed args


def finish_pending() -> None:
    """On start-up of a new version: it runs, so drop the previous copy and the downloaded files."""
    target = install_target()
    if target is not None:
        shutil.rmtree(target.with_name(target.name + ".previous"), ignore_errors=True)
        shutil.rmtree(target.with_name(target.name + ".update"), ignore_errors=True)
    shutil.rmtree(updates_dir(), ignore_errors=True)


def _net_urlopen(req, timeout=15.0):
    return _netmod.urlopen(req, timeout=timeout)
