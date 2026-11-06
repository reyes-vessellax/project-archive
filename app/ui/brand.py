"""The placeholder mark: a "pp" monogram tile, drawn in code so it follows the theme's accent colour.
An original glyph of our own — not any existing logo — so it can ship in test builds without question.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..config import APP_NAME
from . import theme as T


def paint_mark(p: QPainter, rect: QRectF, colour: QColor, text_colour: QColor | None = None) -> None:
    """A rounded teal tile with a tight lowercase "pp" in the display face."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    size = rect.width()
    p.setPen(Qt.NoPen); p.setBrush(colour)
    p.drawRoundedRect(rect, size * 0.22, size * 0.22)
    f = QFont(T.DISPLAY); f.setPixelSize(max(6, int(size * 0.62))); f.setWeight(QFont.ExtraBold)
    f.setLetterSpacing(QFont.AbsoluteSpacing, -size * 0.06)
    p.setFont(f); p.setPen(text_colour or QColor("#ffffff"))
    p.drawText(rect.adjusted(0, -size * 0.06, 0, -size * 0.06), Qt.AlignCenter, "pp")
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
