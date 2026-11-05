"""First-launch walkthrough: a dimmed overlay with a spotlight on one control at a time and a card
explaining it. Next / Back, and an out-of-the-way but always visible "Skip tour".

Steps name widgets; the overlay finds them on screen each time it draws, so it follows the real layout
at any window size. Nothing here touches the service.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QRegion
from PySide6.QtWidgets import QFrame, QLabel, QWidget

from ..config import APP_NAME
from .widgets import button, hbox, label, vbox


@dataclass
class Step:
    target: str                      # attribute path on the window, e.g. "home.q" or "topbar.avatar"; "" = no spotlight
    title: str
    body: str
    page: str = "queue"              # tab to show for this step: queue | ready | search | settings


def default_steps() -> list[Step]:
    return [
        Step("", f"Welcome to {APP_NAME}",
             "A quick tour of the five things you'll use. It takes about a minute, and you can skip it any time."),
        Step("home.q", "Search",
             "Type an artist, a track, a label, and press Enter. Results come from other users' libraries, "
             "fastest sources first."),
        Step("home.list_host", "Queue",
             "Everything you've asked for, newest first. The word on the left says where it is: DOWN (downloading), "
             "CHECK (being checked), WAIT (its turn is next), then GOOD, LOOK or BROKEN once it's been checked. "
             "The × at the left clears a finished row; Clear finished clears them all."),
        Step("home.scope", "Last checked",
             "The spectrogram of the most recent track we checked. A real 320 reaches up to about 20 kHz; a file "
             "made from a low-quality MP3 stops short, and the line shows where."),
        Step("home.review_btn", "Ready for you",
             "Nothing reaches your library on its own. When tracks are checked they wait here for your decision."),
        Step("review.btn_save", "Download or Delete",
             f"On a checked track: Download to Library moves it into your {APP_NAME} folder. Delete removes it for good. "
             "GOOD gets a plain Download; LOOK asks you to confirm; BROKEN can only be deleted.", page="ready"),
        Step("home.add_btn", "Add your own files",
             "Not everything comes from the network. Use Add files, or drag tracks onto the window, to check files you "
             "already have.", page="queue"),
        Step("topbar.tabs.library", "Library",
             "Everything you've downloaded, with its facts. Search it, and use Show in folder to jump straight to the "
             "file on disk."),
        Step("topbar.avatar", "Your account",
             "Settings, appearance (light or dark), help and sign-out live here. Your library folder and what you "
             "share are under Settings → Library & sharing."),
        Step("", "That's it",
             "Search for something you've been hunting for. If a result turns out broken, you'll know before it ever "
             "touches your library."),
    ]


class TourOverlay(QWidget):
    """Covers the whole window; paints the dim + spotlight; hosts the card and the skip button."""
    finished = Signal(bool)          # True = completed, False = skipped

    def __init__(self, window: QWidget, steps: list[Step], navigate: Callable[[str], None]):
        super().__init__(window)
        self.win = window
        self.steps = steps
        self.navigate = navigate
        self.i = 0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.StrongFocus)

        # card
        self.card = QFrame(self); self.card.setObjectName("menu"); self.card.setFixedWidth(360)
        cl = vbox(self.card, (20, 18, 20, 16), 10)
        self.step_lbl = label("", "tag"); cl.addWidget(self.step_lbl)
        self.title = label("", "h2"); self.title.setStyleSheet("font-size: 17px; font-weight: 800;"); cl.addWidget(self.title)
        self.body = label("", "muted", wrap=True); self.body.setStyleSheet("font-size: 14px; line-height: 1.5;"); cl.addWidget(self.body)
        row = hbox(spacing=8)
        self.back = button("Back", "ghost", self._back); self.back.setStyleSheet("min-height: 36px; padding: 0 14px;")
        self.next = button("Next", "primary", self._next); self.next.setStyleSheet("min-height: 36px; padding: 0 18px; border-radius: 18px;")
        row.addWidget(self.back); row.addStretch(1); row.addWidget(self.next)
        cl.addLayout(row)

        # skip: small, bottom-right, always visible
        self.skip = button("Skip tour", "ghost", lambda: self._end(False))
        self.skip.setParent(self)
        self.skip.setStyleSheet("QPushButton { min-height: 32px; padding: 0 14px; border-radius: 16px; font-size: 12px; "
                                "background: rgba(255,255,255,0.92); color: #1b1b1a; border: 1px solid rgba(0,0,0,0.15); }"
                                "QPushButton:hover { background: #ffffff; }")
        self.skip.setToolTip("You can replay the tour any time from the avatar menu")

        window.installEventFilter(self)
        self.setGeometry(window.rect())
        self.raise_(); self.show(); self.setFocus()
        self._show_step()

    # ---------------------------------------------------------------- flow
    def _end(self, completed: bool):
        self.win.removeEventFilter(self)
        self.hide(); self.deleteLater()
        self.finished.emit(completed)

    def _next(self):
        if self.i >= len(self.steps) - 1:
            self._end(True); return
        self.i += 1; self._show_step()

    def _back(self):
        if self.i > 0:
            self.i -= 1; self._show_step()

    def _show_step(self):
        s = self.steps[self.i]
        self.navigate(s.page)
        self.step_lbl.setText(f"{self.i + 1} OF {len(self.steps)}")
        self.title.setText(s.title); self.body.setText(s.body)
        self.back.setVisible(self.i > 0)
        self.next.setText("Done" if self.i == len(self.steps) - 1 else "Next")
        self.card.adjustSize()
        self._layout(); self.update()

    # ---------------------------------------------------------------- geometry
    def _target_rect(self) -> QRect | None:
        s = self.steps[self.i]
        if not s.target:
            return None
        obj = self.win
        for part in s.target.split("."):
            obj = obj.get(part) if isinstance(obj, dict) else getattr(obj, part, None)
            if obj is None:
                return None
        if not obj.isVisible():
            return None
        top_left = obj.mapTo(self.win, QPoint(0, 0))
        return QRect(top_left, obj.size()).adjusted(-8, -6, 8, 6)

    def _layout(self):
        self.setGeometry(self.win.rect())
        W, H = self.width(), self.height()
        self.skip.adjustSize(); self.skip.move(W - self.skip.width() - 24, H - self.skip.height() - 44)
        self.skip.raise_()
        r = self._target_rect()
        cw, ch = self.card.width(), self.card.sizeHint().height()
        self.card.resize(cw, ch)
        if r is None:
            x, y = (W - cw) // 2, (H - ch) // 2
        else:
            # prefer below the target, else above, else beside; keep inside the window
            if r.bottom() + 16 + ch < H - 70:
                x, y = r.left(), r.bottom() + 16
            elif r.top() - 16 - ch > 0:
                x, y = r.left(), r.top() - 16 - ch
            else:
                x, y = (r.right() + 16 if r.right() + 16 + cw < W else r.left() - 16 - cw), max(16, r.top())
            x = max(16, min(x, W - cw - 16)); y = max(16, min(y, H - ch - 70))
        self.card.move(x, y)

    def eventFilter(self, obj, ev):
        if obj is self.win and ev.type() in (QEvent.Resize, QEvent.Move, QEvent.LayoutRequest):
            self._layout(); self.update()
        return False

    # ---------------------------------------------------------------- painting
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        dim = QPainterPath(); dim.addRect(QRectF(self.rect()))
        r = self._target_rect()
        if r is not None:
            hole = QPainterPath(); hole.addRoundedRect(QRectF(r), 12, 12)
            dim = dim.subtracted(hole)
            p.setPen(QColor(210, 114, 30)); p.setBrush(Qt.NoBrush)
            pen = p.pen(); pen.setWidth(2); p.setPen(pen)
            p.drawRoundedRect(QRectF(r), 12, 12)
        p.fillPath(dim, QColor(0, 0, 0, 150))
        p.end()

    def mousePressEvent(self, e):
        # clicks inside the spotlight go through to the app (so people can try the control); elsewhere they advance
        r = self._target_rect()
        if r is not None and r.contains(e.pos()):
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(250, lambda: self.setAttribute(Qt.WA_TransparentForMouseEvents, False))
            e.ignore(); return
        if not self.card.geometry().contains(e.pos()) and not self.skip.geometry().contains(e.pos()):
            self._next()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._next()
        elif e.key() == Qt.Key_Left:
            self._back()
        elif e.key() == Qt.Key_Escape:
            self._end(False)
