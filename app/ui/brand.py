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


def icon_pixmap(size: int) -> QPixmap:
    """The application icon: the kit's burst + smiley (no wordmark) on a black rounded tile."""
    return _asset("digmart-app-icon.png").scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def app_icon(theme: str = "light") -> QIcon:
    icon = QIcon()
    for s in (16, 32, 48, 64, 128, 256, 512, 1024):
        icon.addPixmap(icon_pixmap(s))
    return icon


class Brand(QWidget):
    """Top of the sidebar: the burst + smiley mark on its own (no wordmark; the window title says DigMart).
    Dark mode uses the same artwork with its black outline shown white."""
    clicked = Signal()
    H = 78                                           # mark height in the sidebar (logical px)

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(APP_NAME)
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        self.logo = QLabel()
        lay.addStretch(1); lay.addWidget(self.logo); lay.addStretch(1)
        self.set_theme("light")

    def set_theme(self, theme: str):
        pm = _asset("digmart-mark-dark.png" if theme == "dark" else "digmart-mark.png")
        pm = pm.scaledToHeight(self.H * 3, Qt.SmoothTransformation)          # 3x: sharp on Retina
        pm.setDevicePixelRatio(3.0)
        self.logo.setPixmap(pm); self.logo.setFixedSize(pm.deviceIndependentSize().toSize())

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
