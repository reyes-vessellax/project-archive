"""Build a desktop app folder with PyInstaller. Bundles FFmpeg from vendor/ffmpeg and the Soulseek engine
(slskd) from vendor/slskd when present.

    python packaging/build.py      ->  dist/<APP_NAME>/     (Windows)
                                       dist/<APP_NAME>.app  (macOS)

Uses paths relative to the repo root, because PyInstaller splits some arguments on ':' (macOS) and
the repo may live in a folder whose name contains one.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from app.config import APP_NAME  # noqa: E402

args = [
    os.path.join("app", "__main__.py"),
    "--name", APP_NAME,
    "--windowed",
    "--noconfirm",
    "--clean",
    "--paths", ".",
    "--distpath", "dist",
    "--workpath", "build",
    "--specpath", ".",
    "--hidden-import", "PySide6.QtMultimedia",
]
if Path("vendor/ffmpeg").is_dir():
    args += ["--add-data", f"{os.path.join('vendor', 'ffmpeg')}{os.pathsep}ffmpeg"]
else:
    print("NOTE: vendor/ffmpeg not found; the app will look for FFmpeg on the system.", file=sys.stderr)
if Path("vendor/slskd").is_dir():
    args += ["--add-data", f"{os.path.join('vendor', 'slskd')}{os.pathsep}slskd"]
else:
    print("NOTE: vendor/slskd not found; Soulseek search will be off unless the user points to their own slskd.",
          file=sys.stderr)
PyInstaller.__main__.run(args)
