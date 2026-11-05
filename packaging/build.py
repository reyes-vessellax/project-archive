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
        from app.ui.brand import mark_pixmap
        app = QApplication.instance() or QApplication([])
        T.load_fonts()
        import struct
        sizes = (16, 24, 32, 48, 64, 128, 256)
        blobs = []
        for s in sizes:
            pm = mark_pixmap(s, "#ffffff", bg=T.colours("light")["accent"])
            buf = QBuffer(); buf.open(QIODevice.WriteOnly); pm.save(buf, "PNG"); blobs.append(bytes(buf.data()))
        header = struct.pack("<HHH", 0, 1, len(sizes))
        offset = 6 + 16 * len(sizes)
        entries = b""
        for s, b in zip(sizes, blobs):
            entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(b), offset)
            offset += len(b)
        path.write_bytes(header + entries + b"".join(blobs))
        return True
    except Exception as e:                                  # noqa: BLE001
        print(f"NOTE: couldn't render the icon: {e}", file=sys.stderr)
        return False


ICON = Path("build") / "app.ico"
ICON.parent.mkdir(exist_ok=True)
HAVE_ICON = make_icon(ICON)

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
# Everything we ship that isn't Python lives under _internal/vendor/<thing>/, so the folder reads:
#   <APP_NAME>.exe, _internal/{vendor/ffmpeg, vendor/engine, app, PySide6, numpy, python runtime}
if Path("vendor/ffmpeg").is_dir():
    args += ["--add-data", f"{os.path.join('vendor', 'ffmpeg')}{os.pathsep}{os.path.join('vendor', 'ffmpeg')}"]
else:
    print("NOTE: vendor/ffmpeg not found; the app will look for FFmpeg on the system.", file=sys.stderr)
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

# Files PyInstaller pulls in that the app never uses. Glob patterns, relative to _internal/.
JUNK = [
    "*.dist-info", "setuptools", "pkg_resources", "_distutils_hack",
    "PySide6/translations", "PySide6/qml", "PySide6/Qt6Qml*.dll", "PySide6/Qt6Quick*.dll", "PySide6/Qt6Pdf*.dll",
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
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
            removed += 1
    print(f"tidy: removed {removed} item(s) from {root}")


if internal is not None:
    tidy(internal)
    # The engine checks that its web-content folder exists even when headless; an empty one satisfies it.
    (internal / "vendor" / "engine" / "wwwroot").mkdir(parents=True, exist_ok=True)
    (internal / "vendor" / "engine" / "wwwroot" / "index.html").write_text("<!doctype html><title>headless</title>")
    # A README at the top so a curious user knows what the folders are.
    (out / "README.txt").write_text(
        f"{APP_NAME}\n\n"
        f"{APP_NAME}.exe        the app\n"
        "_internal/          everything the app needs to run; nothing in here needs touching\n"
        "  vendor/ffmpeg/    FFmpeg (decodes audio for the checks)         - FFMPEG-LICENSE.txt\n"
        "  vendor/engine/    the download engine                           - LICENSE\n"
        "  PySide6/, numpy/  user-interface and maths libraries\n"
        "  *.dll, *.pyd      the Python runtime\n\n"
        "Your settings, account and history are kept in your user profile, not in this folder,\n"
        "so you can replace this folder with a newer version at any time.\n", encoding="utf-8")
