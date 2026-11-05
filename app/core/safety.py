"""Untrusted-input handling: which files we accept, and safe filenames on macOS and Windows."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_NAME = 150


class Rejected(ValueError):
    """The file can't be staged. The message is shown to the user."""


def validate_candidate(path: Path, extensions: list[str], max_bytes: int) -> int:
    """Return the size in bytes if the file may be staged, otherwise raise Rejected."""
    if path.is_symlink():
        raise Rejected("Shortcuts/symlinks aren't accepted. Add the real file instead.")
    if not path.exists():
        raise Rejected("File no longer exists.")
    if path.is_dir():
        raise Rejected("That's a folder. Add audio files instead.")
    if not path.is_file():
        raise Rejected("Not a regular file.")
    ext = path.suffix.lower().lstrip(".")
    if ext not in {e.lower().lstrip(".") for e in extensions}:
        raise Rejected(f".{ext or '(none)'} files aren't accepted. Allowed: {', '.join(extensions)}.")
    size = path.stat().st_size
    if size == 0:
        raise Rejected("File is empty (0 bytes).")
    if size > max_bytes:
        raise Rejected(f"File is {size / 1e6:.0f} MB, over the {max_bytes / 1e6:.0f} MB limit.")
    return size


def safe_filename(name: str) -> str:
    """Strip anything that could escape a folder or break on Windows. Never returns an empty name."""
    name = unicodedata.normalize("NFC", Path(name.replace("\\", "/")).name)
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = BAD_CHARS.sub("_", stem).strip(" .") or "track"
    ext = BAD_CHARS.sub("", ext).strip(" .").lower()
    if stem.split(".")[0].upper() in WINDOWS_RESERVED:
        stem = "_" + stem
    stem = stem[:MAX_NAME]
    return f"{stem}.{ext}" if ext else stem


def unique_path(folder: Path, filename: str) -> Path:
    """'Track.mp3', then 'Track (2).mp3', ... Never overwrites an existing file."""
    cand = folder / filename
    stem, suffix = cand.stem, cand.suffix
    n = 2
    while cand.exists():
        cand = folder / f"{stem} ({n}){suffix}"
        n += 1
    return cand


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
