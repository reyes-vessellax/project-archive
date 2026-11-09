"""Settings as a page with a left list. Account first; Advanced last and plain."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QLineEdit, QMessageBox,
                               QPlainTextEdit, QSpinBox, QStackedWidget, QWidget)

from ..core.account import BIO_MAX, AccountError
from ..config import APP_NAME
from ..core.service import ArchiveService
from .widgets import button, hbox, label, page, rule, scroll, set_active, vbox

SECTIONS = (("account", "Account"), ("library", "Library & sharing"), ("checks", "Checks"),
            ("appearance", "Appearance"), ("advanced", "Advanced"))


class SettingsPage(QWidget):
    saved = Signal()                  # settings changed (may need engine restart / restyle)
    sign_out = Signal()
    account_changed = Signal()

    def __init__(self, svc: ArchiveService):
        super().__init__()
        self.svc = svc
        outer, lay = page(spacing=0)
        root = vbox(self); root.addWidget(outer)
        body = hbox(spacing=48); lay.addLayout(body, 1)

        nav = vbox(spacing=2)
        nav.addWidget(label("Settings", "h1"))
        nav.addSpacing(10)
        self.nav_btns = {}
        for key, text in SECTIONS:
            b = button(text, "navitem", lambda _=False, k=key: self.show_section(k))
            self.nav_btns[key] = b; nav.addWidget(b)
        nav.addStretch(1)
        nw = QWidget(); nw.setLayout(nav); nw.setFixedWidth(200)
        body.addWidget(nw)

        self.stack = QStackedWidget()
        self.sections = {"account": self._account(), "library": self._library(), "checks": self._checks(),
                         "appearance": self._appearance(), "advanced": self._advanced()}
        for w in self.sections.values():
            host = QWidget(); host.setObjectName("page"); hl = vbox(host); hl.addWidget(w); hl.addStretch(1)
            self.stack.addWidget(scroll(host))
        body.addWidget(self.stack, 1)
        self.show_section("account")

    def show_section(self, key: str):
        for k, b in self.nav_btns.items():
            set_active(b, k == key)
        self.stack.setCurrentIndex(list(self.sections).index(key))
        self.reload()

    # ---------------------------------------------------------------- sections
    def _field(self, lay, title: str, widget, hint: str = ""):
        box = vbox(spacing=6)
        t = label(title); t.setStyleSheet("font-weight: 700;")
        box.addWidget(t); box.addWidget(widget)
        if hint:
            box.addWidget(label(hint, "faint", wrap=True))
        lay.addLayout(box)

    def _section(self, title: str, note: str = "") -> tuple[QWidget, "vbox"]:
        w = QWidget(); w.setMaximumWidth(640)
        lay = vbox(w, spacing=22)
        lay.addWidget(label(title, "h2"))
        if note:
            lay.addWidget(label(note, "muted", wrap=True))
        return w, lay

    def _account(self) -> QWidget:
        w = QWidget(); w.setMaximumWidth(640); lay = vbox(w, spacing=40)
        # profile
        prof = vbox(spacing=18)
        head = hbox(spacing=18)
        self.avatar = button("?", "avatar"); self.avatar.setEnabled(False)
        self.avatar.setStyleSheet("min-width: 72px; max-width: 72px; min-height: 72px; max-height: 72px; border-radius: 36px; font-size: 24px;")
        head.addWidget(self.avatar)
        hv = vbox(spacing=4)
        hv.addWidget(label("Profile", "h2"))
        hv.addWidget(label("Shown on your account only. Other users on the network see your network name.", "faint", wrap=True))
        hv.addWidget(button("Change photo", "ghost", lambda: QMessageBox.information(self, "Photo", "Profile photos arrive with the online account.")), alignment=Qt.AlignLeft)
        head.addLayout(hv, 1)
        prof.addLayout(head)
        grid = QGridLayout(); grid.setHorizontalSpacing(22)
        self.name = QLineEdit(); self.dj = QLineEdit(); self.dj.setPlaceholderText("Optional")
        for col, (t, e) in enumerate((("Name", self.name), ("DJ name", self.dj))):
            tl = label(t); tl.setStyleSheet("font-weight: 700;")
            grid.addWidget(tl, 0, col); grid.addWidget(e, 1, col)
        prof.addLayout(grid)
        self.bio = QPlainTextEdit(); self.bio.setPlaceholderText("A line or two about what you play."); self.bio.setFixedHeight(80)
        self.bio_left = label("", "faint")
        self.bio.textChanged.connect(lambda: self.bio_left.setText(f"{max(0, BIO_MAX - len(self.bio.toPlainText()))} characters left"))
        self._field(prof, "Bio", self.bio)
        prof.addWidget(self.bio_left)
        lay.addLayout(prof)
        # sign in
        lay.addWidget(rule())
        si = vbox(spacing=18); si.addWidget(label("Sign in", "h2"))
        grid2 = QGridLayout(); grid2.setHorizontalSpacing(22)
        self.email = QLineEdit(); self.pw = QLineEdit(); self.pw.setEchoMode(QLineEdit.Password); self.pw.setText("••••••••••••"); self.pw.setReadOnly(True)
        for col, (t, e) in enumerate((("Email", self.email), ("Password", self.pw))):
            tl = label(t); tl.setStyleSheet("font-weight: 700;")
            grid2.addWidget(tl, 0, col); grid2.addWidget(e, 1, col)
        si.addLayout(grid2)
        si.addWidget(button("Change password", "ghost", self._change_password), alignment=Qt.AlignLeft)
        lay.addLayout(si)
        # plan & billing (inert)
        lay.addWidget(rule())
        pb = vbox(spacing=14)
        ph = hbox(); ph.addWidget(label("Plan & billing", "h2")); ph.addStretch(1); ph.addWidget(label("coming soon", "mono"))
        pb.addLayout(ph)
        card = QFrame(); card.setObjectName("card"); cl = hbox(card, (16, 14, 16, 14), 12)
        ct = vbox(spacing=2)
        ct.addWidget(label("Free plan", "h2")); ct.addWidget(label("Paid plans, invoices and payment methods will appear here.", "muted"))
        cl.addLayout(ct, 1)
        for text in ("Update card", "Invoices"):
            b = button(text, "ghost"); b.setEnabled(False); cl.addWidget(b)
        pb.addWidget(card)
        lay.addLayout(pb)
        # actions
        lay.addWidget(rule())
        act = hbox(spacing=12)
        act.addWidget(button("Save changes", "primary", self._save_account))
        act.addStretch(1)
        act.addWidget(button("Sign out", "ghost", self.sign_out.emit))
        act.addWidget(button("Delete account…", "danger", self._delete_account))
        lay.addLayout(act)
        return w

    def _library(self) -> QWidget:
        w, lay = self._section("Library & sharing")
        self.library = QLineEdit(); self.library.setObjectName("monoinput")
        row = hbox(spacing=12); row.addWidget(self.library, 1); row.addWidget(button("Choose…", "ghost", lambda: self._choose(self.library)))
        box = vbox(spacing=6); t = label("Your library folder"); t.setStyleSheet("font-weight: 700;")
        box.addWidget(t); box.addLayout(row)
        from ..config import APP_NAME, APP_NAME
        box.addWidget(label(f"Approved downloads go into a {APP_NAME} folder inside it.", "faint"))
        lay.addLayout(box)
        self.share = QCheckBox("Share my library folder with other users")
        lay.addWidget(self.share)
        lay.addWidget(label("People who share get served first; accounts that share nothing wait at the back of every queue.", "faint", wrap=True))
        self.incoming = QLineEdit(); self.incoming.setObjectName("monoinput"); self.incoming.setPlaceholderText("Off (leave empty)")
        row2 = hbox(spacing=12); row2.addWidget(self.incoming, 1); row2.addWidget(button("Choose…", "ghost", lambda: self._choose(self.incoming)))
        box2 = vbox(spacing=6); t2 = label("Watched folder"); t2.setStyleSheet("font-weight: 700;")
        box2.addWidget(t2); box2.addLayout(row2); box2.addWidget(label("Anything that lands in this folder is checked automatically.", "faint"))
        lay.addLayout(box2)
        lay.addWidget(button("Save changes", "primary", self._save_settings), alignment=Qt.AlignLeft)
        return w

    def _checks(self) -> QWidget:
        w, lay = self._section("Checks", "Checks never change a file. They tell you what it is; you decide.")
        self.mp3 = QSpinBox(); self.mp3.setRange(64, 320); self.mp3.setSuffix(" kbps")
        self.vbr = QSpinBox(); self.vbr.setRange(64, 320); self.vbr.setSuffix(" kbps")
        self.slots = QSpinBox(); self.slots.setRange(1, 16)
        self.hours = QSpinBox(); self.hours.setRange(1, 24 * 30); self.hours.setSuffix(" hours")
        self.maxmb = QSpinBox(); self.maxmb.setRange(10, 8192); self.maxmb.setSuffix(" MB")
        self.exts = QLineEdit(); self.exts.setObjectName("monoinput")
        self._field(lay, "Warn if an MP3 is below", self.mp3)
        self._field(lay, "Warn if a VBR MP3 averages below", self.vbr)
        self._field(lay, "Check this many tracks at once", self.slots, "More is faster on a strong computer.")
        self._field(lay, "Delete undecided tracks after", self.hours)
        self._field(lay, "Largest file to accept", self.maxmb)
        self._field(lay, "Accepted formats", self.exts, "Comma separated.")
        lay.addWidget(button("Save changes", "primary", self._save_settings), alignment=Qt.AlignLeft)
        return w

    def _appearance(self) -> QWidget:
        w, lay = self._section("Appearance")
        self.theme = QComboBox(); self.theme.addItems(["Light", "Dark"])
        self._field(lay, "Theme", self.theme)
        lay.addWidget(button("Save changes", "primary", self._save_settings), alignment=Qt.AlignLeft)
        return w

    def _advanced(self) -> QWidget:
        w, lay = self._section("Advanced", "For people who already run their own tools. Everything here is optional.")
        self.own_user = QLineEdit(); self.own_user.setPlaceholderText("Leave empty to use the built-in account")
        self.own_pass = QLineEdit(); self.own_pass.setEchoMode(QLineEdit.Password)
        self._field(lay, "Use my own Soulseek username", self.own_user)
        self._field(lay, "Soulseek password", self.own_pass)
        self.upnp = QCheckBox("Ask the router to open the download port automatically (UPnP)")
        self.upnp.setToolTip("Other users deliver search results and files straight to you when this port is reachable. "
                             "Off, or with a router that refuses, everything still works through the slower indirect route.")
        lay.addWidget(self.upnp)
        self.port_note = label("", "faint"); lay.addWidget(self.port_note)
        self.use_own = QCheckBox("Use an slskd I already run instead of the built-in engine")
        lay.addWidget(self.use_own)
        self.slskd_url = QLineEdit(); self.slskd_url.setObjectName("monoinput")
        self.slskd_key = QLineEdit(); self.slskd_key.setEchoMode(QLineEdit.Password)
        self.slskd_dl = QLineEdit(); self.slskd_dl.setObjectName("monoinput")
        self.ffmpeg = QLineEdit(); self.ffmpeg.setObjectName("monoinput"); self.ffmpeg.setPlaceholderText("Bundled / system")
        self._field(lay, "slskd URL", self.slskd_url)
        self._field(lay, "slskd API key", self.slskd_key)
        self._field(lay, "slskd downloads folder", self.slskd_dl)
        self._field(lay, "FFmpeg folder", self.ffmpeg)
        row = QHBoxLayout(); row.setSpacing(10)
        row.addWidget(button("Save changes", "primary", self._save_settings))
        row.addWidget(button("Open logs folder", "ghost", self._open_logs))
        row.addWidget(button("Send a report…", "ghost", self._send_report)); row.addStretch(1)
        row.addWidget(button("Start fresh…", "danger", self._start_fresh))
        lay.addLayout(row)
        lay.addWidget(label("If something goes wrong, Send a report gathers the logs into one zip for you to email us "
                            "(no passwords or keys go in it). Start fresh wipes this "
                            "computer's account, queue, history and quarantine (your music is not touched) and closes the app.", "faint", wrap=True))
        return w

    def _start_fresh(self):
        if QMessageBox.question(self, "Start fresh", f"Wipe {APP_NAME}'s account, queue, history and quarantine on this "
                                "computer and close the app? Downloaded music stays where it is.") != QMessageBox.Yes:
            return
        from PySide6.QtWidgets import QApplication
        self.svc.reset_everything()
        QApplication.instance().quit()

    def _send_report(self):
        from PySide6.QtWidgets import QInputDialog
        note, ok = QInputDialog.getMultiLineText(
            self, "Send a report", "What happened? (optional — what you were doing, what you expected)")
        if not ok:
            return
        try:
            path = self.svc.make_report(note)
        except OSError as e:
            QMessageBox.warning(self, "Send a report", f"Couldn't make the report: {e}")
            return
        from .library_page import reveal_in_folder
        reveal_in_folder(path)
        QMessageBox.information(self, "Send a report",
                                f"Saved {path.name}. Its folder is open now: attach the zip to an email to us. "
                                "It holds the app's logs and settings, with passwords and keys left out.")

    def _open_logs(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from ..config import data_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir())))

    # ---------------------------------------------------------------- data
    def reload(self):
        s = self.svc.settings
        a = self.svc.accounts.load()
        if a:
            self.avatar.setText(a.initials); self.name.setText(a.name); self.dj.setText(a.dj_name)
            self.bio.setPlainText(a.bio); self.email.setText(a.email)
        self.library.setText(s.library_dir); self.share.setChecked(bool(s.share_folder)); self.incoming.setText(s.incoming_dir)
        self.mp3.setValue(s.mp3_min_kbps); self.vbr.setValue(s.vbr_min_avg_kbps); self.slots.setValue(s.max_concurrent_analyses)
        self.hours.setValue(s.retention_hours); self.maxmb.setValue(s.max_file_mb); self.exts.setText(", ".join(s.extensions))
        self.theme.setCurrentIndex(1 if s.theme == "dark" else 0)
        self.own_user.setText(s.soulseek_own_username); self.own_pass.setText("")
        self.own_pass.setPlaceholderText("(unchanged)" if self.svc.manager.creds.get("soulseek_own_password") else "")
        self.use_own.setChecked(s.use_own_slskd); self.slskd_url.setText(s.slskd_url); self.slskd_key.setText(s.slskd_api_key)
        self.upnp.setChecked(bool(s.upnp))
        port = s.listen_port
        self.port_note.setText((f"Download port {port}: " + (self.svc.port_note or "not checked yet")) if port else "")
        self.slskd_dl.setText(s.slskd_downloads_dir); self.ffmpeg.setText(s.ffmpeg_path)

    def _choose(self, edit: QLineEdit):
        d = QFileDialog.getExistingDirectory(self, "Choose a folder", edit.text())
        if d:
            edit.setText(d)

    def _save_settings(self):
        s = self.svc.settings
        s.library_dir = self.library.text().strip() or s.library_dir
        s.share_folder = s.library_dir if self.share.isChecked() else ""
        s.incoming_dir = self.incoming.text().strip()
        s.mp3_min_kbps, s.vbr_min_avg_kbps = self.mp3.value(), self.vbr.value()
        s.max_concurrent_analyses = self.slots.value()
        s.retention_hours, s.max_file_mb = self.hours.value(), self.maxmb.value()
        s.extensions = [e.strip().lower().lstrip(".") for e in self.exts.text().split(",") if e.strip()] or s.extensions
        s.theme = "dark" if self.theme.currentIndex() == 1 else "light"
        s.soulseek_own_username = self.own_user.text().strip()
        if self.own_pass.text():
            self.svc.manager.creds.set("soulseek_own_password", self.own_pass.text())
        elif not s.soulseek_own_username:
            self.svc.manager.creds.delete("soulseek_own_password")
        s.use_own_slskd = self.use_own.isChecked()
        s.upnp = self.upnp.isChecked()
        s.slskd_url = self.slskd_url.text().strip() or "http://127.0.0.1:5030"
        s.slskd_api_key = self.slskd_key.text().strip(); s.slskd_downloads_dir = self.slskd_dl.text().strip()
        s.ffmpeg_path = self.ffmpeg.text().strip()
        self.svc.save_settings(s)
        self.saved.emit()

    def _save_account(self):
        try:
            self.svc.accounts.update_profile(self.name.text(), self.dj.text(), self.bio.toPlainText(), self.email.text())
        except AccountError as e:
            QMessageBox.warning(self, "Account", str(e)); return
        self.reload(); self.account_changed.emit()

    def _change_password(self):
        from PySide6.QtWidgets import QInputDialog
        cur, ok = QInputDialog.getText(self, "Change password", "Current password:", QLineEdit.Password)
        if not ok: return
        new, ok = QInputDialog.getText(self, "Change password", "New password (10+ characters):", QLineEdit.Password)
        if not ok: return
        try:
            self.svc.accounts.change_password(cur, new)
        except AccountError as e:
            QMessageBox.warning(self, "Account", str(e)); return
        QMessageBox.information(self, "Account", "Password changed.")

    def _delete_account(self):
        if QMessageBox.question(self, "Delete account", "Delete your account on this computer? Your music and your "
                                "library are not touched.") == QMessageBox.Yes:
            self.svc.accounts.delete()
            self.sign_out.emit()
