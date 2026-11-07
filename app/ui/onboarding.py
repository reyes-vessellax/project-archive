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
from .widgets import button, hbox, label, rule, set_tag, vbox

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


class ConnectingPage(QWidget):
    """Shown while the engine starts and signs in. A spinner, three steps, then it closes itself."""
    done = Signal()

    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        outer, lay = _centered()
        root = vbox(self); root.addWidget(outer)
        lay.addWidget(_logo(svc))
        lay.addWidget(_steps(2))
        self.title = label("Getting things ready…", "big"); lay.addWidget(self.title)
        self.spinner = label("", "h1"); self.spinner.setStyleSheet("font-size: 28px; color: palette(mid);"); lay.addWidget(self.spinner)
        self.rows = {}
        for key, text in (("engine", "Starting the engine"), ("network", "Signing in to the network"),
                          ("port", "Asking the router to open your port"), ("shares", "Sharing your library")):
            r = hbox(spacing=12)
            dot = label("○", "steplight"); dot.setProperty("tag", ""); dot.setFixedWidth(26); txt = label(text, "muted")
            r.addWidget(dot); r.addWidget(txt); r.addStretch(1)
            lay.addLayout(r); self.rows[key] = (dot, txt)
        self.note = label("This takes a few seconds the first time. If your firewall asks to allow incoming connections, "
                          "choose Allow — that's how other users send you files.", "faint", wrap=True)
        lay.addWidget(self.note)
        lay.addStretch(1)
        self._frames = "◐◓◑◒"; self._i = 0
        self._spin = QTimer(self, interval=120, timeout=self._tick)

    def _tick(self):
        self._i = (self._i + 1) % len(self._frames)
        self.spinner.setText(self._frames[self._i])

    def start(self):
        self._spin.start()
        for dot, txt in self.rows.values():
            set_tag(dot, ""); txt.setObjectName("muted")

    def mark(self, key: str, state: str, note: str = ""):
        dot, txt = self.rows[key]
        dot.setText({"done": "✓", "busy": "●", "fail": "✕", "skip": "–"}.get(state, "○"))
        set_tag(dot, {"done": "Good", "busy": "Down", "fail": "Broken", "skip": "Wait"}.get(state, ""))
        base = txt.property("base") or txt.text()
        txt.setProperty("base", base)
        txt.setText(f"{base} — {note}" if note else base)
        if state == "busy":
            txt.setObjectName("")
        else:
            txt.setObjectName("muted")
        set_tag(txt, "")

    def finish(self):
        self._spin.stop()
        self.done.emit()


class Onboarding(QStackedWidget):
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
