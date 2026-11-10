"""Discover row loading: refreshes and connection blips never restart searches (a stream of cancelled searches
once kept every row empty), multi-artist rows show their first artist's tracks before the rest land."""
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _track(artist, title):
    from app.adapters.base import Candidate
    from app.core.crates import CrateTrack
    c = Candidate("soulseek", "u", f"p/{artist}/{title}", 1, extension="flac", free_slot=True)
    return CrateTrack(artist, title, "", c, [c])


def test_rows_load_once_progressively_and_survive_refreshes(service, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.core import rows as R
    from app.ui.discover_page import DiscoverPage
    app = QApplication.instance() or QApplication([])
    calls, lock = [], threading.Lock()

    def note(x):
        with lock:
            calls.append(x)

    def style_row(svc, engine, nm, owns=None, cancelled=None):
        if svc is service:                       # a page left over from another test may still be searching
            note(("style", nm))
        time.sleep(0.05); return [_track("S " + nm, "t")]

    def artist_crate(svc, a, owns=None, cancelled=None, log=None, use_cache=True):
        if svc is service:
            note(("artist", a))
        time.sleep(0.05); return [_track(a, "t1"), _track(a, "t2")]

    def for_you_start(svc, day, owns=None, cancelled=None, **kw):
        note(("foryou", "")); time.sleep(0.05)
        return [_track("Tyree", "Acid Over")], ["Fast Eddie"], ["Ralphi Rosario", "DSK"]

    monkeypatch.setattr(R, "style_row", style_row)
    monkeypatch.setattr(R, "artist_crate", artist_crate)
    monkeypatch.setattr(R, "for_you_start", for_you_start)
    monkeypatch.setattr(R, "order_by_era", lambda engine, era, tracks, cancelled=None, cached_only=False: tracks)
    service.adapter = object()
    monkeypatch.setattr(service, "_build_adapter", lambda: None)   # saving settings keeps the fake connection
    d = DiscoverPage(service); d.resize(1300, 900); d.show()
    d.era = ""
    d._loaded_for = "not yet"
    d.refresh(service.jobs())

    def settle(s=3.0):
        end = time.monotonic() + s
        while time.monotonic() < end:
            app.processEvents(); time.sleep(0.01)
    for _ in range(10):                                   # the app refreshes often: must not restart anything
        d.refresh(service.jobs()); app.processEvents()
    service.adapter = None; d.refresh(service.jobs())     # a connection blip...
    service.adapter = object(); d.refresh(service.jobs())  # ...and back
    settle()
    styles = [c for c in calls if c[0] == "style"]
    assert len(styles) == len(set(styles)) == 5, calls    # each style searched exactly once
    fy = d.rows["For you"]
    assert len(fy.tiles) == 5 and "Because you play Fast Eddie" in fy.intro.text()       # 1 + 2 + 2 tracks, merged
    for name, kind in d._row_kind.items():
        assert d.rows[name].tiles, name                   # every row filled
    assert not d._loading
    assert not d.era_btns                                 # no genre pills: always the daily mix
    assert "Afro house" not in d._row_kind


def test_rows_fill_once_signed_in_without_any_other_event(service, monkeypatch):
    """The page opened before the engine signed in showed "Connect to the network…" forever (nothing told it)."""
    from PySide6.QtWidgets import QApplication
    from app.core import rows as R
    from app.ui.discover_page import DiscoverPage
    app = QApplication.instance() or QApplication([])
    asked = []
    monkeypatch.setattr(R, "style_row", lambda svc, engine, nm, owns=None, cancelled=None:
                        (asked.append(nm) if svc is service else None) or [_track("A " + nm, "t")])
    monkeypatch.setattr(R, "artist_crate", lambda svc, a, owns=None, cancelled=None, log=None, use_cache=True: [_track(a, "t")])
    monkeypatch.setattr(R, "for_you_start", lambda *a, **k: ([], [], []))
    monkeypatch.setattr(R, "order_by_era", lambda engine, era, tracks, cancelled=None, cached_only=False: tracks)
    monkeypatch.setattr(service, "_build_adapter", lambda: None)
    service.adapter = object()
    d = DiscoverPage(service); d.signed_in = False; d.resize(1300, 900); d.show()
    d._loaded_for = "not yet"; d.refresh(service.jobs()); app.processEvents()
    assert not asked and all(not r.tiles for r in d.rows.values())        # waiting, no searches yet
    d.signed_in = True                                                     # signs in; nobody calls refresh
    end = time.monotonic() + 5
    while time.monotonic() < end and len(asked) < 5:
        app.processEvents(); time.sleep(0.02)
    end = time.monotonic() + 1
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.02)
    assert len(asked) == 5 and all(d.rows[n].tiles for n, k in d._row_kind.items() if k == "STYLE")
