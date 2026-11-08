"""First launch: Account -> Your library -> Ready. Also the sign-in screen for an existing account.

Only local work happens here. When the backend exists, the same screens call it instead.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QStackedWidget, QWidget

from ..config import APP_NAME
from ..core.account import AccountError
from ..core.service import ArchiveService
from .widgets import CurrentStack, button, hbox, label, rule, set_tag, vbox

STEPS = ("Account", "Your library", "Ready")


def _steps(active: int) -> QWidget:
    w = QWidget(); lay = hbox(w, spacing=20)
    for i, name in enumerate(STEPS):
        item = QWidget(); il = hbox(item, spacing=8)
        dot = label("●", "tag"); dot.setProperty("tag", "Good" if i < active else ("Down" if i == active else ""))
        txt = label(name, "" if i == active else ("muted" if i < active else "faint"))
        txt.setStyleSheet("font-weight: 600;")
        il.addWidget(dot); il.addWidget(txt)
        lay.addWidget(item)
    lay.addStretch(1)
    return w


def _centered(inner_max: int = 480) -> tuple[QWidget, "vbox"]:
    outer = QWidget(); outer.setObjectName("page")
    row = hbox(outer, (24, 48, 24, 48))
    row.addStretch(1)
    col = QWidget(); col.setObjectName("page"); col.setMaximumWidth(inner_max)
    col.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    lay = vbox(col, spacing=26)
    row.addWidget(col, 10)
    row.addStretch(1)
    return outer, lay


def _logo(svc) -> QLabel:
    """The brand-kit main logo (burst + smiley, DigMart underneath) at the top of every first-run screen."""
    from .brand import _asset
    dark = getattr(svc.settings, "theme", "light") == "dark"
    pm = _asset("digmart-logo-dark.png" if dark else "digmart-logo.png").scaledToHeight(140 * 3, Qt.SmoothTransformation)
    pm.setDevicePixelRatio(3.0)
    lab = QLabel(); lab.setPixmap(pm); lab.setFixedSize(pm.deviceIndependentSize().toSize()); lab.setToolTip(APP_NAME)
    return lab


class SignUpPage(QWidget):
    done = Signal()
    switch = Signal()             # go to sign-in

    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        outer, lay = _centered()
        root = vbox(self); root.addWidget(outer)
        lay.addWidget(_logo(svc))
        lay.addWidget(_steps(0))
        lay.addWidget(label("Create your account", "big"))
        lay.addWidget(label("Your account is how you sign in on any computer. Your music stays on your machine.", "muted", wrap=True))
        self.name = self._field(lay, "Name", "Your name")
        self.email = self._field(lay, "Email", "you@example.com")
        self.pw = self._field(lay, "Password", "At least 10 characters", password=True)
        lay.addWidget(label("Use a password you don't use anywhere else.", "faint"))
        self.error = label("", "muted"); self.error.setStyleSheet("color: #c43d3d;"); self.error.setWordWrap(True)
        lay.addWidget(self.error)
        row = hbox(spacing=14)
        row.addWidget(button("Continue", "primary", self._submit))
        row.addWidget(label("Already have an account?", "faint"))
        row.addWidget(button("Sign in", "link", self.switch.emit))
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(label("By continuing you agree to the Terms of Service and Privacy Policy. A plan and payment "
                            "method are added later, from your account page.", "faint", wrap=True))
        lay.addStretch(1)
        for w in (self.name, self.email, self.pw):
            w.returnPressed.connect(self._submit)

    def _field(self, lay, title: str, placeholder: str, password: bool = False) -> QLineEdit:
        box = vbox(spacing=6)
        t = label(title); t.setStyleSheet("font-weight: 700;")
        e = QLineEdit(); e.setPlaceholderText(placeholder)
        if password:
            e.setEchoMode(QLineEdit.Password)
        box.addWidget(t); box.addWidget(e)
        lay.addLayout(box)
        return e

    def _submit(self):
        try:
            self.svc.accounts.sign_up(self.name.text(), self.email.text(), self.pw.text())
        except AccountError as e:
            self.error.setText(str(e)); return
        self.error.setText("")
        self.done.emit()


class SignInPage(QWidget):
    done = Signal()
    switch = Signal()             # go to sign-up

    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        outer, lay = _centered()
        root = vbox(self); root.addWidget(outer)
        lay.addWidget(_logo(svc))
        lay.addWidget(label("Welcome back", "big"))
        self.email = QLineEdit(); self.email.setPlaceholderText("Email")
        self.pw = QLineEdit(); self.pw.setPlaceholderText("Password"); self.pw.setEchoMode(QLineEdit.Password)
        lay.addWidget(self.email); lay.addWidget(self.pw)
        self.error = label("", "muted"); self.error.setStyleSheet("color: #c43d3d;"); lay.addWidget(self.error)
        row = hbox(spacing=14)
        row.addWidget(button("Sign in", "primary", self._submit))
        row.addWidget(button("Create an account instead", "link", self.switch.emit))
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.pw.returnPressed.connect(self._submit)

    def _submit(self):
        try:
            self.svc.accounts.sign_in(self.email.text(), self.pw.text())
        except AccountError as e:
            self.error.setText(str(e)); return
        self.done.emit()


class LibraryPage(QWidget):
    done = Signal()

    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        s = svc.settings
        outer, lay = _centered(520)
        root = vbox(self); root.addWidget(outer)
        lay.addWidget(_logo(svc))
        lay.addWidget(_steps(1))
        lay.addWidget(label("Where does your music live?", "big"))
        lay.addWidget(label(f"Pick the folder your DJ software already uses. Approved downloads go into a {APP_NAME} "
                            f"folder inside it, so they stay in one place.", "muted", wrap=True))
        t = label("Library folder"); t.setStyleSheet("font-weight: 700;"); lay.addWidget(t)
        row = hbox(spacing=12)
        self.folder = QLineEdit(s.library_dir if s.setup_done else str(Path.home() / "Music")); self.folder.setObjectName("monoinput")
        row.addWidget(self.folder, 1)
        row.addWidget(button("Choose…", "ghost", self._choose))
        lay.addLayout(row)
        self.found = label("", "muted"); lay.addWidget(self.found)
        self.folder.textChanged.connect(self._count)
        self.share = QCheckBox("Share this folder with the community")
        self.share.setChecked(True if not s.setup_done else bool(s.share_folder))
        self.share.setStyleSheet("font-weight: 700; font-size: 15px;")
        lay.addWidget(self.share)
        lay.addWidget(label("People who share get served first; accounts that share nothing wait at the back of every "
                            "queue. Turn it off any time in Settings.", "muted", wrap=True))
        self.error = label("", "muted"); self.error.setStyleSheet("color: #c43d3d;"); lay.addWidget(self.error)
        row2 = hbox(spacing=14)
        row2.addWidget(button("Continue", "primary", self._submit))
        row2.addWidget(label("Nothing reaches this folder until you approve it.", "faint"))
        row2.addStretch(1)
        lay.addLayout(row2)
        lay.addStretch(1)
        self._count()

    def _choose(self):
        d = QFileDialog.getExistingDirectory(self, "DJ music library", self.folder.text())
        if d:
            self.folder.setText(d)

    def _count(self):
        p = Path(self.folder.text().strip())
        if not p.is_dir():
            self.found.setText("This folder will be created."); return
        exts = {"." + e.lower() for e in self.svc.settings.extensions}
        n = size = 0
        try:
            for i, f in enumerate(p.rglob("*")):
                if i > 20000:
                    break
                if f.suffix.lower() in exts and f.is_file():
                    n += 1; size += f.stat().st_size
        except OSError:
            pass
        self.found.setText(f"Found {n:,} tracks · {size / 1e9:.0f} GB" if n else "No tracks found here yet — that's fine.")
        set_tag(self.found, "Good" if n else "")

    def _submit(self):
        folder = self.folder.text().strip()
        if not folder:
            self.error.setText("Please choose a folder."); return
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.error.setText(f"Can't use that folder: {e}"); return
        s = self.svc.settings
        s.library_dir = folder
        s.share_folder = folder if self.share.isChecked() else ""
        s.setup_done = True
        self.svc.save_settings(s)
        self.done.emit()


class ReadyPage(QWidget):
    done = Signal()

    def __init__(self, svc: ArchiveService):
        super().__init__()
        outer, lay = _centered()
        root = vbox(self); root.addWidget(outer)
        lay.addWidget(_logo(svc))
        lay.addWidget(_steps(2))
        lay.addWidget(label("You're set.", "big"))
        lay.addWidget(label("Search for a track, pick a source, and it lands in quarantine where it's checked before "
                            "anything reaches your library. If your firewall asks to allow incoming connections, choose "
                            "Allow — that's how other users send you files.", "muted", wrap=True))
        lay.addWidget(button(f"Open {APP_NAME}", "primary", self.done.emit))
        lay.addStretch(1)


class _LoaderMark(QWidget):
    """The smiley mark, breathing gently, inside a thin ring with an accent arc chasing round it."""
    SIZE = 168

    def __init__(self, svc):
        super().__init__()
        from .brand import _asset
        from . import theme as T
        self.setFixedSize(self.SIZE, self.SIZE)
        dark = getattr(svc.settings, "theme", "light") == "dark"
        self._c = T.colours("dark" if dark else "light")
        dpr = 3.0
        self._pm = _asset("digmart-mark-dark.png" if dark else "digmart-mark.png").scaledToWidth(int(112 * dpr), Qt.SmoothTransformation)
        self._pm.setDevicePixelRatio(dpr)
        self._t = 0.0
        self._done = False
        self._timer = QTimer(self, interval=16, timeout=self._step)

    def start(self):
        self._done = False; self._t = 0.0; self._timer.start()

    def stop(self, done: bool = True):
        self._done = done; self._timer.stop(); self.update()

    def _step(self):
        self._t += 0.016; self.update()

    def paintEvent(self, e):
        import math
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QColor, QPainter, QPen
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.SmoothPixmapTransform)
        s = self.SIZE; ring = QRectF(6, 6, s - 12, s - 12)
        track = QPen(QColor(self._c["line"])); track.setWidthF(2.0); p.setPen(track); p.drawEllipse(ring)
        arc = QPen(QColor(self._c["pass_"] if self._done else self._c["accent"])); arc.setWidthF(3.0); arc.setCapStyle(Qt.RoundCap)
        p.setPen(arc)
        if self._done:
            p.drawEllipse(ring)
        else:
            span = 70 + 50 * math.sin(self._t * 2.2)                       # the arc stretches and shrinks as it turns
            start = -(self._t * 300) % 360
            p.drawArc(ring, int(start * 16), int(-span * 16))
        scale = 1.0 + 0.025 * math.sin(self._t * 3.0)                     # a slow breath
        sz = self._pm.deviceIndependentSize()
        w, h = sz.width() * scale, sz.height() * scale
        p.drawPixmap(QRectF((s - w) / 2, (s - h) / 2, w, h), self._pm, QRectF(self._pm.rect()))
        p.end()


class ConnectingPage(QWidget):
    """Shown while the engine starts and signs in: the mark in a turning ring, one line saying what's happening,
    and a row of small dots for the steps. Nothing else. It closes itself when everything is ready."""
    done = Signal()
    STEPS = (("engine", "Starting the engine"), ("network", "Signing in to the network"),
             ("port", "Opening your port"), ("shares", "Sharing your library"))

    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        self.setObjectName("page"); self.setAttribute(Qt.WA_StyledBackground, True)
        root = vbox(self, (24, 24, 24, 24), 0)
        root.addStretch(3)
        self.mark_w = _LoaderMark(svc)
        root.addWidget(self.mark_w, 0, Qt.AlignHCenter)
        root.addSpacing(30)
        self.title = label("Getting things ready", "loadtitle"); self.title.setAlignment(Qt.AlignCenter)
        root.addWidget(self.title)
        root.addSpacing(8)
        self.sub = label("", "faint"); self.sub.setAlignment(Qt.AlignCenter); root.addWidget(self.sub)
        root.addSpacing(18)
        self.first_run = not svc.settings.setup_done          # sharing is a first-run question; later starts skip it
        keys = [k for k, _ in self.STEPS if k != "shares" or self.first_run]
        pips = hbox(spacing=10); pips.addStretch(1)
        self.pips = {}
        for k in keys:
            d = QLabel(); d.setObjectName("pip"); d.setFixedSize(8, 8); d.setProperty("state", "")
            pips.addWidget(d); self.pips[k] = d
        pips.addStretch(1)
        root.addLayout(pips)
        root.addStretch(4)
        self.note = label("If your firewall asks to allow incoming connections, choose Allow. That's how other "
                          "users send you files.", "faint", wrap=True)
        self.note.setAlignment(Qt.AlignCenter); self.note.setVisible(self.first_run)
        root.addWidget(self.note, 0, Qt.AlignHCenter)
        self.note.setMaximumWidth(460)
        self.state = {k: "" for k in keys}
        self.texts = dict(self.STEPS)

    def start(self):
        for k in self.state:
            self.state[k] = ""
        self._render()
        self.mark_w.start()

    def mark(self, key: str, state: str, note: str = ""):
        if key not in self.state:
            return
        self.state[key] = state
        if note:
            self.sub.setText(note)
        self._render()

    def _render(self):
        from . import theme as T
        for k, d in self.pips.items():
            d.setProperty("state", self.state[k]); T.repolish(d)
        busy = next((k for k in self.state if self.state[k] == "busy"), None)
        todo = next((k for k in self.state if not self.state[k]), None)
        key = busy or todo
        self.title.setText(self.texts[key] if key else "Ready")

    def finish(self):
        self.mark_w.stop(True)
        self.done.emit()


class Onboarding(CurrentStack):
    """Owns the four screens and emits `finished` when the user reaches the app."""
    finished = Signal()

    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        self.signup = SignUpPage(svc); self.signin = SignInPage(svc)
        self.library = LibraryPage(svc); self.ready = ReadyPage(svc); self.connecting = ConnectingPage(svc)
        for w in (self.signup, self.signin, self.library, self.ready, self.connecting):
            self.addWidget(w)
        self.signup.switch.connect(lambda: self.setCurrentWidget(self.signin))
        self.signin.switch.connect(lambda: self.setCurrentWidget(self.signup))
        self.signup.done.connect(self._after_account)
        self.signin.done.connect(self._after_account)
        self.library.done.connect(lambda: self.setCurrentWidget(self.ready))
        self.ready.done.connect(self.finished.emit)
        self.setCurrentWidget(self.signin if svc.accounts.load() else self.signup)

    def _after_account(self):
        if self.svc.settings.setup_done:
            self.finished.emit()
        else:
            self.setCurrentWidget(self.library)
