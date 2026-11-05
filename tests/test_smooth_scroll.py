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
