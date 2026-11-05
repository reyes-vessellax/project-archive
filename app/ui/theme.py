"""Look and feel (design v5): two palettes, one stylesheet, bundled typefaces.

Everything visual is a token here so that light and dark share one layout. Pages set `objectName`s
and dynamic properties (e.g. `tag="Good"`) and the stylesheet does the rest.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QFontDatabase

FONT_DIR = Path(__file__).resolve().parent / "fonts"
SANS = "Sora"                 # body and UI
DISPLAY = "Sora"              # headlines: h1, big, hero search, counts, verdict, brand
MONO = "IBM Plex Mono"

PALETTES = {
    "light": dict(bg="#fbfbfa", panel="#ffffff", line="#ebebe7", text="#1b1b1a", muted="#6b6b66", faint="#a4a49e",
                  accent="#d2721e", soft="#f3f3f0", pass_="#2a8a55", warn="#b5741b", fail="#c43d3d", bar="#e6e6e2",
                  on_text="#fbfbfa", accent_text="#ffffff"),
    "dark": dict(bg="#111111", panel="#171717", line="#262626", text="#f2f2f0", muted="#9c9c97", faint="#66665f",
                 accent="#f0a24a", soft="#1f1f1f", pass_="#55c98a", warn="#e2a24a", fail="#ef6b6b", bar="#2a2a2a",
                 on_text="#111111", accent_text="#1a1000"),
}

# Word tags shown on queue rows and checks (design v5 wording).
TAG_COLOUR = {"Down": "accent", "Check": "text", "Wait": "faint", "Good": "pass_", "Look": "warn", "Broken": "fail",
              "Error": "fail", "Done": "pass_", "Gone": "faint"}
GRADE_WORD = {"PASS": "Good", "WARN": "Look", "FAIL": "Broken"}
GRADE_LONG = {"PASS": "Good", "WARN": "Have a look", "FAIL": "Broken"}


def load_fonts() -> None:
    if not FONT_DIR.is_dir():
        return
    for f in FONT_DIR.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(f))


def colours(theme: str) -> dict:
    return PALETTES.get(theme, PALETTES["light"])


def stylesheet(theme: str) -> str:
    c = colours(theme)
    sans = f'"{SANS}", "Segoe UI", system-ui, sans-serif'
    display = f'"{DISPLAY}", "{SANS}", "Segoe UI", system-ui, sans-serif'
    mono = f'"{MONO}", "Consolas", monospace'
    tags = "\n".join(
        f'QLabel#tag[tag="{word}"], QLabel#count[tag="{word}"], QLabel#verdict[tag="{word}"] {{ color: {c[key]}; }}'
        for word, key in TAG_COLOUR.items()
    )
    return f"""
* {{ font-family: {sans}; font-size: 13px; color: {c['text']}; }}
QMainWindow, QDialog, QWidget#page, QWidget#root {{ background: {c['bg']}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QToolTip {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['line']}; padding: 4px 8px; }}

/* top bar */
QWidget#topbar {{ background: {c['bg']}; }}
QPushButton#brand {{ background: none; border: none; font-family: {display}; font-weight: 800; font-size: 15px; padding: 6px 0; min-height: 0; border-radius: 0; }}
QPushButton#tab {{ background: none; border: none; border-bottom: 2px solid transparent; border-radius: 0; padding: 8px 2px; min-height: 0; color: {c['faint']}; font-weight: 600; font-size: 14px; }}
QPushButton#tab:hover {{ color: {c['text']}; }}
QPushButton#tab[active="true"] {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
QPushButton#avatar {{ background: {c['accent']}; color: {c['accent_text']}; border: none; border-radius: 16px; padding: 0; min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; font-weight: 800; font-size: 12px; }}
QLabel#status {{ color: {c['muted']}; }}
QLabel#statusdot {{ font-size: 16px; }}

/* text roles */
QLabel#h1 {{ font-family: {display}; font-size: 30px; font-weight: 800; }}
QLabel#h2 {{ font-size: 15px; font-weight: 700; }}
QLabel#big {{ font-family: {display}; font-size: 34px; font-weight: 800; }}
QLabel#muted {{ color: {c['muted']}; }}
QLabel#faint {{ color: {c['faint']}; }}
QLabel#mono {{ font-family: {mono}; font-size: 12px; color: {c['muted']}; }}
QLabel#monotext {{ font-family: {mono}; font-size: 13px; }}
QLabel#tag {{ font-family: {mono}; font-size: 10px; font-weight: 500; letter-spacing: 1px; color: {c['faint']}; }}
{tags}
QLabel#tag[tag="Good"], QLabel#tag[tag="Look"], QLabel#tag[tag="Broken"], QLabel#tag[tag="Error"], QLabel#tag[tag="Down"] {{ font-weight: 700; }}
QLabel#verdict[tag="Error"] {{ color: {c['fail']}; }}
QProgressBar[tag="Error"]::chunk {{ background: {c['fail']}; }}
QWidget#row[tag="Error"] {{ border-left: 3px solid {c['fail']}; }}
QLabel#count {{ font-family: {display}; font-size: 26px; font-weight: 800; }}
QLabel#count[tag="Good"] {{ color: {c['pass_']}; }}
QLabel#count[tag="Look"] {{ color: {c['warn']}; }}
QLabel#count[tag="Broken"] {{ color: {c['fail']}; }}
QLabel#verdict {{ font-family: {display}; font-size: 22px; font-weight: 800; }}
QLabel#verdict[tag="Good"] {{ color: {c['pass_']}; }}
QLabel#verdict[tag="Look"] {{ color: {c['warn']}; }}
QLabel#verdict[tag="Broken"] {{ color: {c['fail']}; }}

/* inputs */
QLineEdit {{ background: transparent; border: none; border-bottom: 1px solid {c['line']}; padding: 8px 2px; font-size: 15px; selection-background-color: {c['accent']}; }}
QLineEdit:focus {{ border-bottom: 1px solid {c['accent']}; }}
QLineEdit#hero {{ font-family: {display}; font-size: 28px; font-weight: 600; padding: 12px 2px; }}
QLineEdit#monoinput {{ font-family: {mono}; font-size: 13px; }}
QPlainTextEdit {{ background: transparent; border: none; border-bottom: 1px solid {c['line']}; padding: 6px 2px; font-size: 15px; }}
QPlainTextEdit:focus {{ border-bottom: 1px solid {c['accent']}; }}
QSpinBox {{ background: transparent; border: none; border-bottom: 1px solid {c['line']}; padding: 6px 2px; font-size: 15px; }}
QCheckBox {{ spacing: 10px; font-size: 14px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid {c['faint']}; border-radius: 4px; background: {c['panel']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
QComboBox {{ background: transparent; border: none; border-bottom: 1px solid {c['line']}; padding: 6px 2px; font-size: 15px; }}
QComboBox QAbstractItemView {{ background: {c['panel']}; border: 1px solid {c['line']}; selection-background-color: {c['soft']}; }}

/* buttons */
QPushButton {{ font-weight: 700; font-size: 14px; border-radius: 22px; padding: 0 20px; min-height: 44px; }}
QPushButton#primary {{ background: {c['text']}; color: {c['on_text']}; border: none; }}
QPushButton#primary:hover {{ background: {c['accent']}; color: {c['accent_text']}; }}
QPushButton#primary:disabled {{ background: {c['bar']}; color: {c['faint']}; }}
QPushButton#accent {{ background: {c['accent']}; color: {c['accent_text']}; border: none; }}
QPushButton#accent:hover {{ background: {c['text']}; color: {c['on_text']}; }}
QPushButton#ghost {{ background: transparent; color: {c['muted']}; border: 1px solid {c['line']}; min-height: 40px; font-size: 13px; }}
QPushButton#ghost:hover {{ color: {c['text']}; }}
QPushButton#danger {{ background: transparent; color: {c['fail']}; border: 1px solid {c['line']}; }}
QPushButton#danger:hover {{ border-color: {c['fail']}; }}
QPushButton#link {{ background: none; border: none; color: {c['text']}; font-weight: 600; font-size: 13px; min-height: 0; padding: 4px 0; text-align: left; }}
QPushButton#link:hover {{ color: {c['muted']}; }}
QPushButton#small {{ min-height: 30px; padding: 0 12px; font-size: 12px; border-radius: 15px; background: {c['text']}; color: {c['on_text']}; border: none; }}
QPushButton#play {{ background: {c['accent']}; color: {c['accent_text']}; border: none; border-radius: 13px; font-size: 10px; padding: 0; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; }}
QPushButton#play:hover {{ background: {c['text']}; color: {c['bg']}; }}
QPushButton#x {{ min-height: 0; padding: 0; border: none; background: none; color: {c['faint']}; font-size: 15px; font-weight: 500; min-width: 18px; max-width: 18px; max-height: 18px; }}
QPushButton#x:hover {{ color: {c['fail']}; }}
QPushButton#navitem {{ background: none; border: none; border-radius: 8px; text-align: left; padding: 9px 12px; min-height: 0; color: {c['muted']}; font-weight: 600; font-size: 14px; }}
QPushButton#navitem:hover {{ color: {c['text']}; }}
QPushButton#navitem[active="true"] {{ background: {c['soft']}; color: {c['text']}; }}

/* rows and lists */
QWidget#row {{ background: transparent; border-bottom: 1px solid {c['line']}; }}
QWidget#row:hover, QWidget#row[selected="true"] {{ background: {c['soft']}; border-radius: 8px; }}
QProgressBar {{ background: {c['bar']}; border: none; border-radius: 2px; max-height: 3px; min-height: 3px; }}
QProgressBar::chunk {{ background: {c['text']}; border-radius: 2px; }}
QProgressBar[tag="Down"]::chunk {{ background: {c['accent']}; }}
QProgressBar[tag="Good"]::chunk {{ background: {c['pass_']}; }}
QProgressBar[tag="Look"]::chunk {{ background: {c['warn']}; }}
QProgressBar[tag="Broken"]::chunk {{ background: {c['fail']}; }}
QProgressBar[tag="Wait"]::chunk {{ background: {c['bar']}; }}
QFrame#rule {{ background: {c['line']}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#card {{ background: {c['soft']}; border-radius: 10px; }}
QFrame#menu {{ background: {c['panel']}; border: 1px solid {c['line']}; border-radius: 14px; }}
QPushButton#menuitem {{ background: none; border: none; border-radius: 8px; text-align: left; padding: 10px 14px; min-height: 0; font-weight: 600; font-size: 14px; }}
QPushButton#menuitem:hover {{ background: {c['soft']}; }}

/* tables */
QTreeWidget {{ background: transparent; border: none; alternate-background-color: transparent; outline: 0; }}
QTreeWidget::item {{ padding: 9px 4px; border-bottom: 1px solid {c['line']}; }}
QTreeWidget::item:hover {{ background: {c['soft']}; }}
QTreeWidget::item:selected {{ background: {c['soft']}; color: {c['text']}; }}
QHeaderView::section {{ background: transparent; border: none; border-bottom: 1px solid {c['line']}; padding: 6px 4px; font-family: {mono}; font-size: 10px; letter-spacing: 1px; color: {c['faint']}; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['bar']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; }}
QScrollBar::handle:horizontal {{ background: {c['bar']}; border-radius: 4px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QSplitter::handle {{ background: transparent; }}
QMessageBox {{ background: {c['panel']}; }}
QMessageBox QPushButton {{ min-height: 36px; padding: 0 16px; border: 1px solid {c['line']}; background: transparent; }}
"""


def repolish(widget) -> None:
    """Re-apply the stylesheet after a dynamic property (tag=, active=) changes."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
