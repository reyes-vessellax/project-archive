"""Send a report (roadmap #9): gather what support needs into one zip.

Until the accounts backend exists there is nowhere to upload it, so the zip is saved in the data folder's
"reports" and the user attaches it to an email. Nothing secret goes in: passwords, API keys and tokens
are left out of the settings, and lines in the logs that look like they carry one are masked.
"""
from __future__ import annotations

import json
import platform
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

TAIL_BYTES = 2_000_000                     # the end of each log is what matters; keeps the zip email-sized
_SECRET_KEY = re.compile(r"(pass|secret|token|api_?key|apikey)", re.I)
_SECRET_LINE = re.compile(r"((?:pass(?:word)?|secret|token|api[_-]?key|x-api-key|authorization)\s*[\"']?\s*[:=]\s*[\"']?)([^\s\"',}]+)", re.I)


def _tail(p: Path) -> str:
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return _SECRET_LINE.sub(lambda m: m.group(1) + "••••", text)


def safe_settings(d: dict) -> dict:
    return {k: ("••••" if _SECRET_KEY.search(k) and v else v) for k, v in d.items()}


def build(out_dir: Path, logs: dict[str, Path], settings: dict, note: str = "", extra: dict | None = None) -> Path:
    """Write the zip and return its path. logs: name in the zip -> file on disk (missing files are skipped)."""
    from ..config import APP_SLUG, FULL_VERSION
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest = out_dir / f"{APP_SLUG}-report-{stamp}.zip"
    about = {"app_version": FULL_VERSION, "os": platform.platform(), "machine": platform.machine(),
             "python": sys.version.split()[0], "made_at": datetime.now().astimezone().isoformat(timespec="seconds"),
             **(extra or {})}
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("about.json", json.dumps(about, indent=2))
        z.writestr("settings.json", json.dumps(safe_settings(settings), indent=2, default=str))
        if note.strip():
            z.writestr("note.txt", note.strip() + "\n")
        for name, p in logs.items():
            if p and Path(p).exists():
                z.writestr(name, _tail(Path(p)))
    return dest
