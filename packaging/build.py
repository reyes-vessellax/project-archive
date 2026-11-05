"""Build a desktop app folder with PyInstaller. Bundles FFmpeg from vendor/ffmpeg if present.

    python packaging/build.py      ->  dist/Project Archive/   (Windows)
                                       dist/Project Archive.app (macOS)

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
args = [
    os.path.join("app", "__main__.py"),
    "--name", "Project Archive",
    "--windowed",
    "--noconfirm",
    "--clean",
    "--paths", ".",
    "--distpath", "dist",
    "--workpath", "build",
    "--specpath", ".",
]
if Path("vendor/ffmpeg").is_dir():
    args += ["--add-data", f"{os.path.join('vendor', 'ffmpeg')}{os.pathsep}ffmpeg"]
else:
    print("NOTE: vendor/ffmpeg not found; the app will look for FFmpeg on the system.", file=sys.stderr)
PyInstaller.__main__.run(args)
