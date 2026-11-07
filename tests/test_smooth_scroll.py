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
    assert all(b >= a for a, b in zip(values, values[1:])), "scrolled backwards at some point"
    from app.ui.widgets import SmoothWheel
    assert bar.value() >= 25 * SmoothWheel.PX_PER_NOTCH * 0.9, bar.value()   # momentum carried most of the distance
    assert len(set(values)) > 30, "it jumped instead of gliding"
    tree.close()
