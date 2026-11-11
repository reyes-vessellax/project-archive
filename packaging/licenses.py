"""Third-party licence texts for the Python packages bundled into the app.

PyInstaller drops each package's *.dist-info (where its LICENSE usually lives), so the build copies them out of the
build environment first: licenses/<package>/<the package's own licence files> plus a short INFO.txt (version,
licence name, home page), and Python's own licence. Run by packaging/build.py; testable on its own.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

# What the app bundles (the import names PyInstaller pulls in, as distribution names).
PACKAGES = ["PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "numpy", "mutagen", "yt-dlp", "certifi"]
_LICENCE_FILE = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.I)


def collect(dest: Path) -> list[str]:
    """Copy licence files for every bundled package found in this environment into dest. Returns what was found."""
    from importlib import metadata
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    found = []
    for name in PACKAGES:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        d = dest / name
        d.mkdir(exist_ok=True)
        for f in dist.files or []:
            if _LICENCE_FILE.search(Path(str(f)).name):
                src = Path(dist.locate_file(f))
                if src.is_file():
                    shutil.copy2(src, d / src.name)
        md = dist.metadata
        lic = f"{md.get('License-Expression') or ''} {md.get('License') or ''}"
        has_text = any(p.name != "INFO.txt" for p in d.iterdir())
        if not has_text and "LGPL" in lic:                  # PySide6/shiboken6 wheels carry no licence text at all
            here = Path(__file__).parent / "third_party"
            for t in ("LGPL-3.0.txt", "GPL-3.0.txt"):          # LGPL v3 is GPL v3 plus permissions: both texts
                if (here / t).is_file():
                    shutil.copy2(here / t, d / t)
        (d / "INFO.txt").write_text(
            f"{md.get('Name', name)} {dist.version}\n"
            f"Licence: {md.get('License-Expression') or md.get('License') or 'see the files in this folder'}\n"
            f"Home page: {md.get('Home-page') or md.get('Project-URL') or ''}\n", encoding="utf-8")
        found.append(name)
    for cand in (Path(sys.base_prefix) / "LICENSE.txt",
                 Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt"):
        if cand.is_file():
            (dest / "Python").mkdir(exist_ok=True)
            shutil.copy2(cand, dest / "Python" / "LICENSE.txt")
            found.append("Python")
            break
    return found
