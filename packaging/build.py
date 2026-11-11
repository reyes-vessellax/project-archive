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

def make_icon(path: Path) -> bool:
    """Render the app mark into a multi-size .ico (PNG entries) so the exe, taskbar and shortcuts show it."""
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtWidgets import QApplication
        from app.ui import theme as T
        from app.ui.brand import icon_pixmap
        app = QApplication.instance() or QApplication([])
        T.load_fonts()
        import struct
        from PySide6.QtGui import QImage
        sizes = (16, 24, 32, 48, 64, 128, 256)
        blobs = []
        for s in sizes:
            pm = icon_pixmap(s)
            if s >= 256:                                     # PNG entry (what Windows expects at 256)
                buf = QBuffer(); buf.open(QIODevice.WriteOnly); pm.save(buf, "PNG"); blobs.append(bytes(buf.data()))
                continue
            # classic DIB entry: BITMAPINFOHEADER + bottom-up BGRA rows + empty AND mask (safest for taskbar/Explorer)
            img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
            rows = []
            for y in range(s - 1, -1, -1):
                line = bytes(img.constScanLine(y))[: s * 4]
                rows.append(line)
            xor = b"".join(rows)
            mask_row = ((s + 31) // 32) * 4
            and_mask = b"\x00" * (mask_row * s)
            hdr = struct.pack("<IiiHHIIiiII", 40, s, s * 2, 1, 32, 0, len(xor) + len(and_mask), 0, 0, 0, 0)
            blobs.append(hdr + xor + and_mask)
        header = struct.pack("<HHH", 0, 1, len(sizes))
        offset = 6 + 16 * len(sizes)
        entries = b""
        for s, b in zip(sizes, blobs):
            entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(b), offset)
            offset += len(b)
        path.write_bytes(header + entries + b"".join(blobs))
        print(f"icon: wrote {path} ({path.stat().st_size} bytes, {len(sizes)} sizes)")
        return True
    except Exception as e:                                  # noqa: BLE001
        print(f"NOTE: couldn't render the icon: {e}", file=sys.stderr)
        return False


def make_icns(path: Path) -> bool:
    """macOS wants .icns: render the mark at the standard sizes into an .iconset and let iconutil pack it."""
    try:
        import subprocess
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from app.ui import theme as T
        from app.ui.brand import icon_pixmap
        app = QApplication.instance() or QApplication([])
        T.load_fonts()
        iconset = path.with_suffix(".iconset")
        iconset.mkdir(parents=True, exist_ok=True)
        for s in (16, 32, 128, 256, 512):
            icon_pixmap(s).save(str(iconset / f"icon_{s}x{s}.png"), "PNG")
            icon_pixmap(s * 2).save(str(iconset / f"icon_{s}x{s}@2x.png"), "PNG")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(path)], check=True)
        print(f"icon: wrote {path} ({path.stat().st_size} bytes)")
        return True
    except Exception as e:                                  # noqa: BLE001
        print(f"NOTE: couldn't render the .icns: {e}", file=sys.stderr)
        return False


ICON = Path("build") / ("app.icns" if sys.platform == "darwin" else "app.ico")
ICON.parent.mkdir(exist_ok=True)
HAVE_ICON = make_icns(ICON) if sys.platform == "darwin" else make_icon(ICON)

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
    *(["--icon", str(ICON)] if HAVE_ICON else []),
    # Qt pieces a Widgets app never loads (QML/Quick, PDF, virtual keyboard, 3D, WebEngine...)
    *sum((["--exclude-module", m] for m in (
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtVirtualKeyboard", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets", "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
        "tkinter", "setuptools", "pkg_resources", "unittest", "pydoc", "doctest", "xmlrpc",   # (email stays: http.client needs it)
    )), []),
]
# Brand fonts and logo artwork live next to the UI code; PyInstaller only copies .py files unless told.
for sub in ("fonts", "brand_assets"):
    src = os.path.join("app", "ui", sub)
    if Path(src).is_dir():
        args += ["--add-data", f"{src}{os.pathsep}{src}"]
# Everything we ship that isn't Python lives under _internal/vendor/<thing>/, so the folder reads:
#   <APP_NAME>.exe, _internal/{vendor/ffmpeg, vendor/engine, app, PySide6, numpy, python runtime}
if Path("vendor/ffmpeg").is_dir():
    args += ["--add-data", f"{os.path.join('vendor', 'ffmpeg')}{os.pathsep}{os.path.join('vendor', 'ffmpeg')}"]
else:
    print("NOTE: vendor/ffmpeg not found; the app will look for FFmpeg on the system.", file=sys.stderr)
from app.config import ENGINE_NAME, ENGINE_SOURCE_URL, ENGINE_VERSION   # noqa: E402

# Shipped with every copy (README.txt): thanks, licences and where the source is. Keep in step with README.md.
OPEN_SOURCE_NOTES = (
    "Open-source software in this app\n"
    "--------------------------------\n"
    f"Special thanks to the {ENGINE_NAME} team. The download engine ({APP_NAME} Engine) is {ENGINE_NAME} {ENGINE_VERSION},\n"
    "used unmodified and renamed, under the GNU Affero General Public License v3.0.\n"
    "  Licence:  _internal/vendor/engine/LICENSE\n"
    f"  Source:   {ENGINE_SOURCE_URL}\n"
    f"You may copy, study, change and share {ENGINE_NAME} under that licence; nothing in {APP_NAME}'s own terms limits that.\n\n"
    "FFmpeg (decodes audio for the checks), under the GNU General Public License v3.\n"
    "  Licence:  _internal/vendor/ffmpeg/FFMPEG-LICENSE.txt\n"
    "  Source:   https://github.com/FFmpeg/FFmpeg  (builds: https://github.com/BtbN/FFmpeg-Builds)\n\n"
    "Also inside: Python, Qt for Python (PySide6, LGPL), NumPy, Mutagen, yt-dlp and certifi, each under its own\n"
    "licence. Their licence texts are in the licenses/ folder (one folder per package).\n"
)

if Path("vendor/slskd").is_dir():
    args += ["--add-data", f"{os.path.join('vendor', 'slskd')}{os.pathsep}{os.path.join('vendor', 'engine')}"]
else:
    print("NOTE: vendor/slskd not found; Soulseek search will be off unless the user points to their own slskd.",
          file=sys.stderr)
PyInstaller.__main__.run(args)


# ------------------------------------------------------------------ tidy the output folder
import fnmatch  # noqa: E402
import shutil  # noqa: E402

out = Path("dist") / (APP_NAME + (".app" if sys.platform == "darwin" else ""))
internal = next((p for p in (out / "_internal", out / "Contents" / "Frameworks") if p.is_dir()), None)
resources = out / "Contents" / "Resources"                 # macOS: data files live here (Frameworks symlinks to them)

# Files PyInstaller pulls in that the app never uses. Glob patterns, relative to _internal/.
JUNK = [
    "*.dist-info", "setuptools", "pkg_resources", "_distutils_hack",
    "PySide6/translations", "PySide6/qml", "PySide6/Qt6Qml*.dll", "PySide6/Qt6Quick*.dll", "PySide6/Qt6Pdf*.dll",
    # macOS frameworks of the same modules
    "PySide6/Qt/lib/QtQml*.framework", "PySide6/Qt/lib/QtQuick*.framework", "PySide6/Qt/lib/QtPdf*.framework",
    "PySide6/Qt/lib/QtVirtualKeyboard.framework", "PySide6/Qt/lib/QtSvg*.framework", "PySide6/Qt/lib/QtWebEngine*.framework",
    "PySide6/Qt/lib/QtDesigner*.framework", "PySide6/Qt/lib/QtQuick3D*.framework", "PySide6/Qt/translations",
    "PySide6/Qt/qml", "PySide6/Qt/plugins/platforminputcontexts", "PySide6/Qt/plugins/virtualkeyboard",
    "PySide6/Qt6VirtualKeyboard.dll", "PySide6/Qt6Svg*.dll",
    "PySide6/plugins/platforminputcontexts", "PySide6/plugins/generic", "PySide6/plugins/iconengines",
    "PySide6/plugins/imageformats/qpdf.dll", "PySide6/plugins/imageformats/qtga.dll",
    "PySide6/plugins/imageformats/qwbmp.dll", "PySide6/plugins/imageformats/qicns.dll",
    "PySide6/plugins/imageformats/qtiff.dll", "PySide6/plugins/imageformats/qwebp.dll",
    "PySide6/plugins/multimedia/windowsmediaplugin.dll",         # the ffmpeg media plugin plays everything we need
    "PySide6/Qt6MultimediaWidgets.dll", "PySide6/QtMultimediaWidgets.pyd",
    "PySide6/plugins/platforms/qdirect2d.dll", "PySide6/plugins/platforms/qminimal.dll",
    "numpy-*/licenses/numpy",                                     # the LICENSE.txt stays; the per-folder copies go
    "vendor/engine/wwwroot", "vendor/engine/config", "vendor/engine/etc",   # headless: no web UI, example config or XML docs
]


def tidy(root: Path) -> None:
    removed = 0
    for pattern in JUNK:
        for p in list(root.glob(pattern)):
            if p.is_symlink():                                 # macOS: Frameworks/ holds symlinks into Resources/
                p.unlink(missing_ok=True)
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
            removed += 1
    print(f"tidy: removed {removed} item(s) from {root}")


if internal is not None:
    tidy(internal)
    if resources.is_dir():
        tidy(resources)
    if sys.platform == "darwin":
        # tidy() may leave links whose target is gone (Frameworks <-> Resources mirror each other); codesign
        # refuses a bundle with a dangling link
        dangling = [p for p in out.rglob("*") if p.is_symlink() and not p.exists()]
        for p in dangling:
            p.unlink()
        print(f"tidy: removed {len(dangling)} dangling link(s)")
    # The engine checks that its web-content folder exists even when headless; an empty one satisfies it.
    for eng in (internal / "vendor" / "engine", resources / "vendor" / "engine"):
        if not eng.is_dir():
            continue
        www = eng / "wwwroot"
        if www.is_symlink() and not www.exists():
            www.unlink()                                       # dangling link left by tidy()
        if www.is_symlink():
            continue                                           # points at the real one; done below
        www.mkdir(parents=True, exist_ok=True)
        (www / "index.html").write_text("<!doctype html><title>headless</title>")
    # Licence texts of the bundled Python packages (PyInstaller dropped their dist-info folders above).
    sys.path.insert(0, str(Path(__file__).parent))
    import licenses  # noqa: E402
    lic_dir = (resources if sys.platform == "darwin" and resources.is_dir() else internal) / "licenses"
    print("licences: " + ", ".join(licenses.collect(lic_dir)))
    # A README at the top so a curious user knows what the folders are (Windows folder layout only).
    (out / "README.txt" if sys.platform != "darwin" else Path("dist") / "README.txt").write_text(
        f"{APP_NAME}\n\n"
        f"{APP_NAME}.exe        the app\n"
        "_internal/          everything the app needs to run; nothing in here needs touching\n"
        "  vendor/ffmpeg/    FFmpeg (decodes audio for the checks)         - FFMPEG-LICENSE.txt\n"
        "  vendor/engine/    the download engine                           - LICENSE\n"
        "  PySide6/, numpy/  user-interface and maths libraries\n"
        "  *.dll, *.pyd      the Python runtime\n\n"
        "Your settings, account and history are kept in your user profile, not in this folder,\n"
        "so you can replace this folder with a newer version at any time.\n\n"
        + OPEN_SOURCE_NOTES, encoding="utf-8")
