"""DigMart brand: the logo artwork from the brand kit, plus the wordmark set in the kit's Poppins Bold."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..config import APP_NAME
from . import theme as T


# The DigMart mark is the artwork from the brand kit itself (app/ui/brand_assets/), never a redraw.
ASSETS = Path(__file__).resolve().parent / "brand_assets"
_cache: dict[str, QPixmap] = {}


def _asset(name: str) -> QPixmap:
    if name not in _cache:
        _cache[name] = QPixmap(str(ASSETS / name))
    return _cache[name]


def paint_mark(p: QPainter, rect: QRectF, colour: QColor | None = None, text_colour: QColor | None = None,
               mono: bool = False) -> None:
    """Draw the brand-kit mark (starburst + smiley), fitted and centred in `rect`; `mono` = the kit's outline icon."""
    pm = _asset("digmart-icon-outline.png" if mono else "digmart-mark.png")
    if pm.isNull():
        return
    scaled = pm.scaled(int(rect.width() * 4), int(rect.height() * 4), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    w = rect.width() if scaled.width() / rect.width() >= scaled.height() / rect.height() else rect.height() * scaled.width() / scaled.height()
    h = w * scaled.height() / scaled.width()
    target = QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h)
    p.save(); p.setRenderHint(QPainter.SmoothPixmapTransform); p.drawPixmap(target, scaled, QRectF(scaled.rect())); p.restore()


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
    """Top-left: the brand-kit mark + the brand-kit wordmark (white in dark mode). Clicking it goes home."""
    clicked = Signal()
    H = 34                                           # mark height in the sidebar (logical px)

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(APP_NAME)
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(10)
        self.mark = QLabel(); self.name = QLabel()
        lay.addWidget(self.mark); lay.addWidget(self.name, 0, Qt.AlignVCenter)
        self.set_theme("light")

    @staticmethod
    def _sized(name: str, height: int) -> QPixmap:
        pm = _asset(name).scaledToHeight(height * 3, Qt.SmoothTransformation)   # 3x: sharp on Retina
        pm.setDevicePixelRatio(3.0)
        return pm

    def set_theme(self, theme: str):
        mark = self._sized("digmart-mark.png", self.H)
        word = self._sized("digmart-wordmark-white.png" if theme == "dark" else "digmart-wordmark.png", 20)
        self.mark.setPixmap(mark); self.mark.setFixedSize(mark.deviceIndependentSize().toSize())
        self.name.setPixmap(word); self.name.setFixedSize(word.deviceIndependentSize().toSize())

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
