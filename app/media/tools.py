"""Locate and run FFmpeg / FFprobe safely: argument lists only, no shell, timeouts, bounded output."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

MAX_STDERR = 64 * 1024


class ToolMissing(RuntimeError):
    pass


def _bundled_dirs() -> list[Path]:
    dirs = []
    if getattr(sys, "frozen", False):                       # PyInstaller build
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        dirs += [base / "vendor" / "ffmpeg", base / "ffmpeg", Path(sys.executable).parent / "ffmpeg"]
    dirs.append(Path(__file__).resolve().parents[2] / "vendor" / "ffmpeg")
    return dirs


def find_tool(name: str, override: str = "") -> str:
    exe = name + (".exe" if sys.platform == "win32" else "")
    if override:                       # a folder holding ffmpeg + ffprobe, or the path of either one
        folder = Path(override)
        if folder.is_file():
            folder = folder.parent
        if (folder / exe).is_file():
            return str(folder / exe)
    for d in _bundled_dirs():
        if (d / exe).is_file():
            return str(d / exe)
    found = shutil.which(name)
    if found:
        return found
    raise ToolMissing(f"{name} was not found. Install FFmpeg or set its location in Settings.")


def creation_flags() -> int:
    # Stop a console window flashing up for every FFmpeg call on Windows.
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def run(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout, shell=False,
                              creationflags=creation_flags(), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:               # subprocess.run kills the child on timeout; report it cleanly
        raise RuntimeError(f"{Path(args[0]).name} didn't finish in {timeout:.0f}s") from e
    proc.stderr = proc.stderr[-MAX_STDERR:]
    return proc


def popen(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                            shell=False, creationflags=creation_flags(), env={**os.environ})
