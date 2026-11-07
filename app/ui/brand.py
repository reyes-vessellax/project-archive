"""The DigMart mark (brand guide 2026-11): starburst + smiley, drawn in code so it is sharp at every size."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..config import APP_NAME
from . import theme as T


# DigMart mark: a crimson starburst with a black outline and white core, and a yellow smiley in the middle.
# Spike lengths vary a little (like the hand-drawn logo) but are fixed, so the mark is identical everywhere.
_SPIKES = (1.00, 0.86, 0.97, 0.82, 1.00, 0.88, 0.95, 0.84, 0.99, 0.86, 0.93, 0.83)


def _burst(cx: float, cy: float, outer: float, inner: float) -> QPolygonF:
    import math
    pts = []
    n = len(_SPIKES)
    for i in range(n * 2):
        a = -math.pi / 2 + i * math.pi / n
        r = outer * _SPIKES[i // 2] if i % 2 == 0 else inner
        pts.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
    return QPolygonF(pts)


def paint_mark(p: QPainter, rect: QRectF, colour: QColor | None = None, text_colour: QColor | None = None,
               mono: bool = False) -> None:
    """The DigMart starburst + smiley. `mono` draws the icon-only outline version in `colour`."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    s = min(rect.width(), rect.height())
    cx, cy = rect.center().x(), rect.center().y()
    ink = QColor("#000000") if not mono else QColor(colour or "#000000")
    line = max(1.0, s * 0.03)
    pen = QPen(ink, line); pen.setJoinStyle(Qt.MiterJoin)
    if mono:
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawPolygon(_burst(cx, cy, s * 0.48, s * 0.30))
    else:
        p.setPen(pen); p.setBrush(QColor("#dc143c"))
        p.drawPolygon(_burst(cx, cy, s * 0.48, s * 0.30))
        p.setPen(Qt.NoPen); p.setBrush(QColor("#ffffff"))
        p.drawPolygon(_burst(cx, cy, s * 0.31, s * 0.235))
    # smiley
    r = s * 0.19
    p.setPen(QPen(ink, max(1.0, s * 0.035)))
    p.setBrush(Qt.NoBrush if mono else QColor("#ffd700"))
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.setPen(Qt.NoPen); p.setBrush(ink)
    ew, eh = r * 0.16, r * 0.30
    for dx in (-0.36, 0.36):
        p.drawEllipse(QPointF(cx + dx * r, cy - r * 0.22), ew, eh)
    smile = QPen(ink, max(1.0, s * 0.032)); smile.setCapStyle(Qt.RoundCap)
    p.setPen(smile); p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(cx - r * 0.62, cy - r * 0.55, r * 1.24, r * 1.12), -20 * 16, -140 * 16)
    p.restore()


def mark_pixmap(size: int, colour: str, bg: str | None = None, dpr: float = 1.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr)); pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)                                  # the tile itself is drawn; corners stay clear
    p = QPainter(pm)
    paint_mark(p, QRectF(0, 0, size, size), QColor(bg or colour))
    p.end()
    return pm


def app_icon(theme: str = "light") -> QIcon:
    c = T.colours(theme)
    icon = QIcon()
    for s in (16, 32, 48, 64, 128, 256):
        icon.addPixmap(mark_pixmap(s, "#ffffff", bg=c["accent"]))
    return icon


class Brand(QWidget):
    """Top-left: the mark + the name. Clicking it goes home."""
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
        self.mark = QLabel(); self.mark.setFixedSize(34, 34)
        self.name = QLabel(APP_NAME); self.name.setObjectName("brandname")
        lay.addWidget(self.mark); lay.addWidget(self.name)
        self.set_theme("light")

    def set_theme(self, theme: str):
        c = T.colours(theme)
        self.mark.setPixmap(mark_pixmap(34, c["accent"], dpr=2.0))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
