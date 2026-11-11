"""Render every DigMart page, light and dark, to one folder: the design review kit (see DESIGN.md).

    python -m tools.screens                 # your real library (a copy), into ~/Desktop/DigMart screens/
    python -m tools.screens --demo          # made-up library (no personal data), e.g. to share
    python -m tools.screens --out DIR --themes dark

Nothing is changed: the database is copied to a temp folder, the network engine is never started (Discover is filled
with demo rows; covers still come from Deezer unless --offline). Writes one PNG per page per theme plus REPORT.txt
(the Queue panel fit check, and any page that failed to render).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import traceback
import uuid
from datetime import date
from pathlib import Path

DEMO_LIB = [("Fast Eddie", "Yo Yo Get Funky", "DJ International", 125.5, "10A"),
            ("Marshall Jefferson", "Move Your Body", "Trax Records", 124.0, "10A"),
            ("Phuture", "Acid Tracks", "Trax Records", 124.6, "9A"), ("Moodymann", "Shades Of Jae", "KDJ", 112.0, "8A"),
            ("Kerri Chandler", "Rain", "Shelter", 123.0, "11A"), ("Ron Trent", "Altered States", "Prescription", 123.0, "11A")]
DEMO_ROWS = {
    "for_you": [("Phuture", "Acid Tracks"), ("Farley Jackmaster Funk", "Love Can't Turn Around"),
                ("Marshall Jefferson", "Move Your Body"), ("Tyree", "Turn Up The Bass"),
                ("Steve Poindexter", "Computer Madness"), ("Royal House", "Can You Party")],
    "era": [("Frankie Knuckles", "Your Love"), ("Adonis", "No Way Back"), ("Lil Louis", "French Kiss"),
            ("Armando", "Land Of Confusion"), ("Joe Smooth", "Promised Land")],
    "style": [("Kerri Chandler", "Rain"), ("Ron Trent", "Altered States"), ("Theo Parrish", "Summertime Is Here"),
              ("Moodymann", "Shades Of Jae"), ("Blaze", "Lovelee Dae"), ("Chez Damier", "Untitled")],
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(Path.home() / "Desktop" / "DigMart screens"))
    ap.add_argument("--demo", action="store_true", help="made-up library instead of a copy of yours")
    ap.add_argument("--offline", action="store_true", help="no network at all (sleeves instead of covers)")
    ap.add_argument("--themes", default="light,dark")
    ap.add_argument("--size", default="1440x860", help="window size (default: a 15-inch laptop)")
    args = ap.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    tmp = Path(tempfile.mkdtemp(prefix="digmart-screens-"))
    data = tmp / "data"; data.mkdir()
    os.environ["PROJECT_ARCHIVE_DATA"] = str(data)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    if args.offline:
        socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))
    real = _real_data_dir()
    use_real = not args.demo and (real / "archive.db").exists()
    if use_real:
        shutil.copy2(real / "archive.db", data / "archive.db")
        for d in ("spectrograms", "covers", "discover_thumbs"):
            if (real / d).exists():
                os.symlink(real / d, data / d)

    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from app.ui import theme as T
    T.load_fonts()
    from app.config import Settings
    from app.core import jobs as J
    from app.core.credentials import CredentialStore
    from app.core.service import ArchiveService
    from app.core.slskd_manager import SlskdManager
    mgr = SlskdManager(Settings(), creds=CredentialStore(tmp / "s.json", use_keyring=False), instance_dir=tmp / "client",
                       binary_dir=None)
    svc = ArchiveService(data / "archive.db", manager=mgr)
    if not use_real:
        _demo_library(svc, J)
    s = svc.settings; s.setup_done = True; s.tour_done = True; svc.save_settings(s)
    if not svc.accounts.load():
        svc.accounts.sign_up("Demo DJ", "demo@example.com", "correct-horse-battery")
    _demo_discover(svc)

    from app.ui.main_window import MainWindow
    w = MainWindow(svc)
    W, H = (int(x) for x in args.size.split("x"))
    w.resize(W, H); w.show()

    def spin(sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            app.processEvents(); time.sleep(0.01)

    report, n = [f"DigMart screens · {date.today()} · {W}x{H} · {'your library (copy)' if use_real else 'demo library'}"], 0
    spin(1.0)
    for theme in [t.strip() for t in args.themes.split(",") if t.strip()]:
        svc.settings.theme = theme; w.apply_theme(); spin(0.4)

        def shot(name, prep):
            nonlocal n
            try:
                prep(); spin(0.8)
                w.grab().save(str(out / f"{n:02d} {name} ({theme}).png")); n += 1
            except Exception:
                report.append(f"FAILED {name} ({theme}):\n" + traceback.format_exc())

        def discover():
            w.discover.signed_in = True; w._tab("discover"); d = w.discover
            d._loaded_for = None; d.refresh(); spin(3.0)
            row = d.rows.get("For you")
            if row is not None and row.tiles:                 # no previews load here: show a track in Dig the crate
                f = d._found_for("For you", row.tiles[0].track); f.details.update(bpm=124, camelot="9A")
                d._show_found(d.spin_bar, f); d.spin_bar.set_year(f, 1987); spin(1.0)
            d.home_view.verticalScrollBar().setValue(0)
        shot("Discover", discover)
        shot("Discover, scrolled", lambda: w.discover.home_view.verticalScrollBar().setValue(900))
        shot("Search", lambda: w._tab("search"))
        shot("Queue", lambda: w._tab("queue"))
        jobs = [j for j in svc.jobs() if j["state"] in (J.READY, J.PROMOTED)]
        if jobs:
            worst = 0
            for j in jobs[:20]:
                w._open_job(j["id"]); spin(0.4)
                worst = max(worst, w.review.det_scroll.verticalScrollBar().maximum())
            w._open_job(jobs[0]["id"])
            shot("Queue, track open", lambda: None)
            report.append(f"Queue panel ({theme}): {'fits' if worst == 0 else f'needs {worst} px of scrolling'} "
                          f"(checked {min(len(jobs), 20)} tracks)")

        def library_open():
            w._tab("library"); lp = w.library
            if lp.tree.topLevelItemCount():
                it = lp.tree.topLevelItem(0); lp.tree.setCurrentItem(it); it.setSelected(True)
        shot("Library", lambda: w._tab("library"))
        shot("Library, track open", library_open)
        shot("Wishlist", lambda: w._tab("wishlist"))
        shot("Batch", lambda: w._tab("batch"))
        shot("Settings", lambda: w._menu_pick("settings"))
    _sleeves(out, report)
    (out / "REPORT.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report)); print(f"\n{n} screens in {out}", flush=True)
    w.close(); shutil.rmtree(tmp, ignore_errors=True)
    os._exit(0)


def _real_data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "DigMart"
    return Path.home() / "Library" / "Application Support" / "DigMart"


def _demo_library(svc, J) -> None:
    db = svc.db
    for i, (a, t, lab, bpm, cam) in enumerate(DEMO_LIB):
        jid = str(uuid.uuid4()); when = f"2026-11-0{1 + i}T10:00:00+00:00"
        db.insert_job(id=jid, source_kind="manual", original_name=f"{a} - {t}.flac",
                      state=J.READY if i < 2 else J.PROMOTED, created_at=when, updated_at=when)
        db._con.execute("INSERT INTO analyses (job_id, overall_status, analysis_json) VALUES (?,?,?)", (jid, "PASS", json.dumps({
            "overall_status": "PASS", "meta": {"artist": a, "title": t, "label": lab, "year": 1987 + i},
            "music": {"bpm": bpm, "camelot": cam, "key": "A minor"},
            "facts": {"container": "flac", "duration_s": 400 + i * 20, "sample_rate_hz": 44100, "channels": 2},
            "checks": [{"id": "x", "status": "PASS", "title": "Plays all the way through", "message": "Decoded with no errors."}]})))
    db._con.commit()


def _demo_discover(svc) -> None:
    """Discover without the network engine: demo rows (real artists, so Deezer covers resolve)."""
    from app.adapters.base import Candidate
    from app.core import rows as R
    from app.core.crates import CrateTrack
    exts = ["flac", "wav", "mp3", "aiff"]

    def tracks(key):
        out = []
        for i, (a, t) in enumerate(DEMO_ROWS[key]):
            c = Candidate("soulseek", f"u{i}", f"p/{a}/{t}", 60_000_000, extension=exts[i % 4],
                          bitrate_kbps=320 if exts[i % 4] == "mp3" else None, free_slot=True, artist=a, title=t)
            out.append(CrateTrack(a, t, "", c, [c, c], "", "", ""))
        return out
    R.for_you_start = lambda *a, **k: (tracks("for_you"), ["Fast Eddie", "Adonis"], [])
    R.artist_crate = lambda *a, **k: tracks("era")
    R.order_by_era = lambda engine, era, ts, *a, **k: ts
    R.style_row = lambda *a, **k: tracks("style")
    svc.adapter = object()
    svc._build_adapter = lambda: None


def _sleeves(out: Path, report: list) -> None:
    """The no-cover sleeves, every colour, at tile size and large."""
    try:
        import zlib
        from app.ui import discover_page as dp
        names = dp._sleeve_names("light")
        from PySide6.QtGui import QImage, QPainter
        sheet = QImage(len(names) * 260 + 20, 280, QImage.Format_RGB32); sheet.fill(0x1e1e1e)
        p = QPainter(sheet)
        found, i = {}, 0
        while len(found) < len(names) and i < 5000:
            a, t = f"Artist {i}", "Track Title"
            found.setdefault(zlib.crc32(f"{a}|{t}".lower().encode()) % len(names), (a, t)); i += 1
        for k in range(len(names)):
            c = dp.CoverArt(); c.setFixedSize(240, 240); c.set_sleeve(*found.get(k, ("Artist", "Track")), "")
            p.drawImage(20 + k * 260, 20, c.grab().toImage())
        p.end(); sheet.save(str(out / "99 Sleeves (no cover art).png"))
    except Exception:
        report.append("FAILED sleeves:\n" + traceback.format_exc())


if __name__ == "__main__":
    sys.exit(main())
