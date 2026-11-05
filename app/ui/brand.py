"""The placeholder mark: a small pipe (the instrument), drawn in code so it follows the theme's accent colour.
An original glyph of our own — not any existing logo — so it can ship in test builds without question.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..config import APP_NAME
from . import theme as T


def paint_mark(p: QPainter, rect: QRectF, colour: QColor) -> None:
    """A pipe lying at a slant with three finger holes and a short breath-line off the mouthpiece."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(rect.center())
    p.rotate(-28)
    L, W = rect.width() * 0.92, rect.height() * 0.26
    body = QRectF(-L / 2, -W / 2, L, W)
    path = QPainterPath()
    path.addRoundedRect(body, W / 2, W / 2)
    p.setPen(Qt.NoPen); p.setBrush(colour); p.drawPath(path)
    # mouthpiece: slightly narrower cap on the left
    p.drawRoundedRect(QRectF(-L / 2 - W * 0.25, -W * 0.34, W * 0.9, W * 0.68), W * 0.3, W * 0.3)
    # holes
    hole = W * 0.34
    p.setBrush(QColor(255, 255, 255, 235))
    for x in (-L * 0.08, L * 0.12, L * 0.32):
        p.drawEllipse(QPointF(x, 0), hole / 2, hole / 2)
    # a breath line: two short arcs off the far end
    pen = QPen(colour); pen.setWidthF(max(1.0, W * 0.18)); pen.setCapStyle(Qt.RoundCap); p.setPen(pen); p.setBrush(Qt.NoBrush)
    for i, r in enumerate((W * 0.9, W * 1.45)):
        p.drawArc(QRectF(L / 2 - r + W * 0.1, -r, 2 * r, 2 * r), -40 * 16, 80 * 16)
    p.restore()


def mark_pixmap(size: int, colour: str, bg: str | None = None, dpr: float = 1.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr)); pm.setDevicePixelRatio(dpr)
    pm.fill(QColor(bg) if bg else Qt.transparent)
    p = QPainter(pm)
    if bg:                                            # app icon: a rounded tile with the mark in white
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen); p.setBrush(QColor(bg)); p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
        paint_mark(p, QRectF(size * 0.12, size * 0.12, size * 0.76, size * 0.76), QColor("#ffffff"))
    else:
        paint_mark(p, QRectF(0, 0, size, size), QColor(colour))
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
        self.mark = QLabel(); self.mark.setFixedSize(26, 26)
        self.name = QLabel(APP_NAME.lower()); self.name.setObjectName("brandname")
        lay.addWidget(self.mark); lay.addWidget(self.name)
        self.set_theme("light")

    def set_theme(self, theme: str):
        c = T.colours(theme)
        self.mark.setPixmap(mark_pixmap(26, c["accent"], dpr=2.0))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
