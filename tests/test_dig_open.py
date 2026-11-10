"""Discover crate rows: tapping a track opens its card under that row; tap again closes; tap another switches
(one card, never two). Spin picks from the rows, instantly."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_track_opens_in_place_closes_switches_and_spin_is_instant(service, tmp_path):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from app.adapters.base import Candidate
    from app.core.crates import CrateTrack
    from app.ui.discover_page import CrateRow, DiscoverPage
    app = QApplication.instance() or QApplication([])
    d = DiscoverPage(service); d.resize(1300, 900); d.show(); app.processEvents()
    rows = []
    for r in range(2):
        row = CrateRow(f"Label {r}"); row.tapped.connect(d._tap_tile)
        d.rows_box.addWidget(row); d.rows[row.name] = row
        tracks = [CrateTrack(f"Artist {r}{i}", f"Track {r}{i}", "", Candidate("soulseek", f"u{r}{i}", f"p{r}{i}", 1,
                  extension="flac", free_slot=True)) for i in range(5)]
        for t in tracks:
            t.alts = [t.best]
        row.fill(tracks); rows.append(row)
    app.processEvents()

    def open_cards():
        return [w for w in (d.track_card,) if w.isVisible()]

    a, b = rows[0].tiles[1], rows[1].tiles[3]
    d._tap_tile(rows[0], a); app.processEvents()
    assert open_cards() and d.track_card.parent() is not None and d.track_card.found.best is a.track.best
    assert d.track_card.mapTo(d, d.track_card.rect().topLeft()).y() > rows[0].area.mapTo(d, rows[0].area.rect().bottomLeft()).y()
    d._tap_tile(rows[1], b); app.processEvents()
    assert len(open_cards()) == 1 and d.track_card.found.best is b.track.best              # switched, still one
    d._tap_tile(rows[1], b); app.processEvents()
    assert open_cards() == [] and d._open_tile is None                                    # same again: closed
    # Spin only shows tracks whose preview already loaded
    calls = []

    def fake_preview(c, background=False, **kw):
        calls.append((c.user, background))
        if c.user == "u02":
            raise RuntimeError("busy source")
        w = tmp_path / f"{c.user}.wav"; w.write_bytes(b"RIFF"); return w, 30.0
    import random
    service.snippet_preview = fake_preview
    d._spins.clear(); d._spin_tried.clear()
    for _ in range(40):
        if d._spin_loading:
            app.processEvents(); d.auxpool.waitForDone(2000); app.processEvents(); continue
        if len(d._spin_tried) >= 10:
            break
        d._prefetch_spins()
    d.auxpool.waitForDone(3000); app.processEvents()
    assert calls and all(bg for _, bg in calls)                                           # background previews only
    shown = [f.best.user for f, _ in d._spins] + ([d.spin_bar.found.best.user] if d.spin_bar.found else [])
    assert shown and "u02" not in shown                                                   # a source that failed never shows
    d.deleteLater(); app.sendPostedEvents(None, QEvent.DeferredDelete)


def test_ready_spins_survive_a_restart_and_wheel_scrolls_the_page(service, tmp_path):
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    from app.adapters.base import Candidate
    from app.core.crates import CrateTrack
    from app.core.discover import Release
    from app.core.discover_avail import Found
    from app.ui.discover_page import CrateRow, DiscoverPage
    app = QApplication.instance() or QApplication([])
    d = DiscoverPage(service); d.resize(1200, 700); d.show(); app.processEvents()
    wav = d._spin_dir() / "abc.wav"; wav.write_bytes(b"RIFF")
    c = Candidate("soulseek", "u", "p", 1, extension="flac", free_slot=True)
    d._spins.append((Found(Release(0, "Rain", "Kerri Chandler", None), {}, "Shelter", "Rain", c, [c]), str(wav)))
    d._save_spins()
    d2 = DiscoverPage(service)                                        # next start-up
    assert [f.track for f, _ in d2._spins] == ["Rain"]
    # a vertical wheel over a row moves the page, not the row
    rows = []
    for r in range(4):
        row = CrateRow(f"L{r}"); d.rows_box.addWidget(row); rows.append(row)
        ts = [CrateTrack(f"A{i}", f"T{i}", "", Candidate("soulseek", f"u{r}{i}", f"p{r}{i}", 1, extension="flac", free_slot=True)) for i in range(20)]
        row.fill(ts)
    app.processEvents()
    page_bar = d.home_view.verticalScrollBar(); row_bar = rows[0].area.horizontalScrollBar()
    page_bar.setRange(0, 5000); row_bar.setRange(0, 3000)            # (offscreen layout doesn't size these by itself)
    before_p, before_r = page_bar.value(), row_bar.value()
    vp = rows[0].area.viewport()
    ev = QWheelEvent(QPointF(10, 10), QPointF(vp.mapToGlobal(QPoint(10, 10))), QPoint(0, 0), QPoint(0, -240),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(vp, ev)
    assert page_bar.value() > before_p and row_bar.value() == before_r
    for w in (d, d2):
        w.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)


def test_play_works_after_switching_genre(service):
    """Switching genre rebuilds the rows; the track card that lived in one of them must survive, so ▶ still plays."""
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from app.adapters.base import Candidate
    from app.core.crates import CrateTrack
    from app.ui.discover_page import CrateRow, DiscoverPage
    app = QApplication.instance() or QApplication([])
    service.adapter = object()                                         # "connected", so rows are built
    service.search = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no network in tests"))
    d = DiscoverPage(service); d.show(); app.processEvents()
    played = []
    d.preview.connect(played.append)

    def add_row():
        row = CrateRow("L"); row.tapped.connect(d._tap_tile); row.play_tapped.connect(d._play_tile)
        d.rows_box.addWidget(row); d.rows["L"] = row
        t = CrateTrack("A", "T", "", Candidate("soulseek", "u", "p", 1, extension="flac", free_slot=True)); t.alts = [t.best]
        row.fill([t]); app.processEvents()
        return row
    row = add_row()
    d._play_tile(row, row.tiles[0]); assert len(played) == 1
    d.set_era("chicago"); app.processEvents()                         # rows rebuilt
    row = add_row()
    d.set_preview_state(""); d._play_tile(row, row.tiles[0])
    assert len(played) == 2 and d.track_card.isVisible()
    d.deleteLater(); app.sendPostedEvents(None, QEvent.DeferredDelete)
