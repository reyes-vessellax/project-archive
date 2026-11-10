import os, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_wheel_glides_instead_of_jumping():
    from PySide6.QtCore import QPoint, QPointF, Qt, QEvent
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem
    from app.ui.widgets import smooth
    app = QApplication.instance() or QApplication([])
    tree = QTreeWidget(); tree.setColumnCount(1); tree.resize(300, 200)
    for i in range(300):
        tree.addTopLevelItem(QTreeWidgetItem([f"row {i}"]))
    tree.show(); app.processEvents()
    smooth(tree)
    bar = tree.verticalScrollBar()
    ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                     Qt.ScrollBegin, False)
    app.sendEvent(tree.viewport(), ev)
    app.processEvents()
    mid = bar.value()
    end = time.monotonic() + 0.4
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.01)
    final = bar.value()
    assert final > 0, "the wheel did nothing"
    assert mid < final, "it jumped straight to the end instead of gliding"
    tree.close()


def test_rapid_ticks_build_momentum_and_stay_monotonic():
    """Stress: 25 notches in 250 ms on a 20,000-row list must keep gliding forward, never jump back,
    and end well past a single notch's distance."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem
    from app.ui.widgets import smooth
    app = QApplication.instance() or QApplication([])
    tree = QTreeWidget(); tree.setColumnCount(1); tree.resize(300, 300)
    tree.addTopLevelItems([QTreeWidgetItem([f"row {i}"]) for i in range(20000)])
    tree.show(); app.processEvents()
    smooth(tree)
    bar = tree.verticalScrollBar()
    values = []
    t0 = time.monotonic()
    sent = 0
    while time.monotonic() - t0 < 1.2:
        if sent < 25 and time.monotonic() - t0 >= sent * 0.01:
            ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, -120), Qt.NoButton,
                             Qt.NoModifier, Qt.ScrollUpdate, False)
            app.sendEvent(tree.viewport(), ev); sent += 1
        app.processEvents(); values.append(bar.value()); time.sleep(0.005)
    settle = time.monotonic() + 3.0                          # a slow machine (CI) needs longer to finish the glide
    while time.monotonic() < settle:
        before = bar.value()
        for _ in range(10):
            app.processEvents(); time.sleep(0.01)
        values.append(bar.value())
        if bar.value() == before:
            break
    assert all(b >= a for a, b in zip(values, values[1:])), "scrolled backwards at some point"
    from app.ui.widgets import SmoothWheel
    assert bar.value() >= 25 * SmoothWheel.PX_PER_NOTCH * 0.9, bar.value()   # momentum carried most of the distance
    assert len(set(values)) > 15, "it jumped instead of gliding"   # a jump is 1-2 values; slow CI runners draw fewer frames
    tree.close()


def test_wheel_over_a_discover_row_joins_the_page_glide_instead_of_fighting_it(service):
    """A wheel over a row of tiles moved the page's bar directly while the page was still gliding from the last
    wheel: the page jumped 120 px, snapped back, and jumped again (the 'tearing' on Discover)."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QPixmap, QWheelEvent
    from PySide6.QtWidgets import QApplication
    from app.adapters.base import Candidate
    from app.core.crates import CrateTrack
    from app.ui.discover_page import CoverArt, DiscoverPage
    app = QApplication.instance() or QApplication([])
    page = DiscoverPage(service); page.resize(1200, 700); page.show(); page.refresh([]); app.processEvents()

    def track(i):
        c = Candidate("soulseek", "u", f"x\\A{i} - T{i}.flac", 5_000_000, display_name=f"A{i} - T{i}.flac", artist=f"A{i}",
                      title=f"T{i}", extension="flac", length_s=400, free_slot=True)
        return CrateTrack(artist=f"A{i}", title=f"T{i}", mix="", best=c, alts=[c])
    for row in page.rows.values():
        row.fill([track(i) for i in range(8)])
    for _ in range(5):
        app.processEvents()
    bar = page.home_view.verticalScrollBar()
    assert bar.maximum() > 600
    row = next(iter(page.rows.values()))

    def wheel(target):
        app.sendEvent(target, QWheelEvent(QPointF(20, 20), QPointF(20, 20), QPoint(0, 0), QPoint(0, -120), Qt.NoButton,
                                          Qt.NoModifier, Qt.NoScrollPhase, False))
    seen = [bar.value()]
    for n in range(6):                                       # page, row, page, row… like a hand scrolling down the page
        wheel(page.home_view.viewport() if n % 2 == 0 else row.area.viewport())
        end = time.monotonic() + 0.05
        while time.monotonic() < end:
            app.processEvents(); seen.append(bar.value()); time.sleep(0.005)
    end = time.monotonic() + 0.8
    while time.monotonic() < end:
        app.processEvents(); seen.append(bar.value()); time.sleep(0.01)
    assert all(b >= a for a, b in zip(seen, seen[1:])), "the page jumped back while scrolling down"
    assert max(b - a for a, b in zip(seen, seen[1:])) < 100, "the page jumped instead of gliding"
    assert seen[-1] >= 6 * 72 - 5                            # all six notches counted

    art = CoverArt(); art.resize(150, 150); art.set_pixmap(QPixmap(600, 600)); art.show(); app.processEvents()
    art.grab(); first = art._fit[1].cacheKey(); art.grab()
    assert art._fit[1].cacheKey() == first                   # the scaled cover is reused, not remade on each paint
    art.close(); page.close(); page.deleteLater(); app.processEvents()
