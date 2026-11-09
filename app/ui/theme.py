"""Look and feel (design v5): two palettes, one stylesheet, bundled typefaces.

Everything visual is a token here so that light and dark share one layout. Pages set `objectName`s
and dynamic properties (e.g. `tag="Good"`) and the stylesheet does the rest.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QFontDatabase

FONT_DIR = Path(__file__).resolve().parent / "fonts"
SANS = "Open Sans"            # body and UI (DigMart brand guide: Open Sans Regular)
DISPLAY = "Poppins"           # headlines, numbers that should feel bold, brand (Poppins Bold / SemiBold)
MONO = "IBM Plex Mono"        # measured values and labels

# DigMart brand: black #000000, crimson #DC143C, yellow #FFD700, white #FFFFFF.
# Light: crimson leads (yellow text on white is unreadable). Dark: true black with yellow leading, like the logo.
# Verdict colours stay green / amber / red so Good / Have a look / Broken read at a glance.
PALETTES = {
    "light": dict(bg="#f6f4ef", panel="#fbfaf7", line="#e4e0d7", text="#141414", muted="#5f5a50", faint="#8a857a",
                  accent="#dc143c", soft="#fdedf0", sel="#b3102f", sel_text="#ffffff", keep_sel_colours=False, pass_="#1f8a4c", warn="#a8650f", fail="#a3162f", bar="#ebe7de",
                  on_text="#ffffff", accent_text="#ffffff", brand_yellow="#ffd700",
                  nav_bg="#151515", nav_text="#ffd24a", cta_bg="#151515", cta_text="#ffd24a",
                  disp_bg="#161616", disp_line="#2c2c2c", disp_text="#ffb000", disp_label="#8a8476", disp_sub="#b08d4a"),
    "dark": dict(bg="#000000", panel="#0f0f0f", line="#262626", text="#ffffff", muted="#a3a3a3", faint="#6e6e6e",
                 accent="#ffd700", soft="#211c00", sel="#a50f2d", sel_text="#ffffff", keep_sel_colours=False, pass_="#4cc38a", warn="#f0a742", fail="#ff5a6e", bar="#1f1f1f",
                 on_text="#000000", accent_text="#000000", brand_yellow="#ffd700",
                 nav_bg="#1c1c1c", nav_text="#ffd24a", cta_bg="#ffd700", cta_text="#000000",
                 disp_bg="#141414", disp_line="#2e2e2e", disp_text="#ffb000", disp_label="#8a8476", disp_sub="#b08d4a"),
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
QMainWindow, QDialog {{ background-color: {c['bg']}; }}
QWidget#page, QWidget#root {{ background: transparent; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QToolTip {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['line']}; padding: 4px 8px; }}

/* now playing bar (one player for the whole app) */
QFrame#nowplaying {{ background: {c['disp_bg']}; border-top: 1px solid {c['disp_line']}; }}
QFrame#nowplaying QLabel {{ background: transparent; color: #f2f2f0; }}
QFrame#nowplaying QLabel#faint {{ color: {c['disp_label']}; }}
QFrame#nowplaying QLabel#mono {{ color: {c['disp_text']}; font-size: 13px; }}
QFrame#nowplaying QSlider::groove:horizontal {{ height: 4px; background: #2c2c2c; border-radius: 2px; }}
QFrame#nowplaying QSlider::sub-page:horizontal {{ background: {c['disp_text']}; border-radius: 2px; }}
QFrame#nowplaying QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; background: {c['disp_text']}; }}
QFrame#nowplaying QSlider::handle:horizontal:hover {{ background: #ffd36b; }}
QPushButton#barplay {{ background: {c['disp_text']}; color: {c['disp_bg']}; border: none; border-radius: 18px; padding: 0; min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; }}
QPushButton#barplay:hover {{ background: #ffd36b; }}
QPushButton#barplay:pressed {{ background: #e09a00; }}
QPushButton#barstop {{ background: transparent; border: 1px solid #3a3a3a; border-radius: 15px; padding: 0; min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; }}
QPushButton#barstop:hover {{ border-color: {c['disp_text']}; }}

/* batch (design v6) */
QFrame#dropzone {{ background: {c['panel']}; border: 1px dashed {c['faint']}; border-radius: 3px; }}
QPlainTextEdit#bare {{ background: transparent; border: none; padding: 4px 2px; font-size: 14px; }}
QFrame#bcard {{ background: {c['panel']}; border: 1px solid {c['line']}; border-radius: 3px; }}
QFrame#bcard:hover {{ border-color: {c['faint']}; }}
QFrame#bcard[selected="true"] {{ background: {c['soft']}; border: 1px solid {c['accent']}; }}
QLabel#svc {{ font-family: {mono}; font-size: 10px; font-weight: 600; letter-spacing: 1.5px; }}
QLabel#cardtitle {{ font-family: {display}; font-size: 15px; font-weight: 700; }}
QFrame#stat {{ background: {c['panel']}; border: 1px solid {c['line']}; border-radius: 3px; }}
QLabel#statnum {{ font-family: {mono}; font-size: 26px; font-weight: 600; }}
QFrame#trow {{ border: none; border-bottom: 1px solid {c['line']}; }}
QLabel#rowtitle {{ font-weight: 600; font-size: 14px; }}
QLabel#fmt {{ font-family: {mono}; font-size: 11px; border: 1px solid {c['line']}; border-radius: 3px; padding: 2px 7px; }}
QLabel#pill {{ font-size: 12px; font-weight: 700; border-radius: 3px; padding: 3px 10px; background: {c['bar']}; color: {c['muted']}; }}
QLabel#pill[tone="pass_"] {{ background: {c['soft']}; color: {c['pass_']}; }}
QLabel#pill[tone="accent"] {{ background: {c['soft']}; color: {c['accent']}; }}
QLabel#pill[tone="fail"] {{ color: {c['fail']}; }}

/* sidebar (design v6) */
QWidget#sidebar {{ background: transparent; border-right: 1px solid {c['line']}; }}

/* top bar */
QWidget#topbar {{ background: {c['bg']}; }}
QLabel#brandname {{ font-family: {display}; font-weight: 700; font-size: 21px; color: {c['text']}; letter-spacing: -0.4px; }}
QPushButton#tab {{ background: none; border: none; border-bottom: 2px solid transparent; border-radius: 0; padding: 0 2px 6px 2px; min-height: 40px; color: {c['faint']}; font-weight: 600; font-size: 14px; }}
QPushButton#tab:hover {{ color: {c['text']}; }}
QPushButton#tab[active="true"] {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
QPushButton#avatar {{ background: {c['accent']}; color: {c['accent_text']}; border: none; border-radius: 16px; padding: 0; min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; font-weight: 800; font-size: 12px; }}
QLabel#status {{ color: {c['muted']}; }}
QLabel#statusdot {{ font-size: 16px; }}

/* text roles */
QLabel#h1 {{ font-family: {display}; font-size: 30px; font-weight: 700; }}
QLabel#h2 {{ font-size: 15px; font-weight: 700; }}
QLabel#big {{ font-family: {display}; font-size: 34px; font-weight: 700; }}
QLabel#muted {{ color: {c['muted']}; }}
QLabel#faint {{ color: {c['faint']}; }}
QLabel#mono {{ font-family: {mono}; font-size: 12px; color: {c['muted']}; }}
QFrame#display {{ background: {c['disp_bg']}; border: 1px solid {c['disp_line']}; border-radius: 3px; }}
QFrame#display QLabel {{ background: transparent; }}
QLabel#disptag {{ font-family: {mono}; font-size: 10px; letter-spacing: 2px; color: {c['disp_label']}; }}
QLabel#tile, QLabel#tilekey {{ font-family: {mono}; font-size: 28px; font-weight: 500; color: {c['disp_text']}; }}
QLabel#dispsub {{ font-family: {mono}; font-size: 11px; color: {c['disp_sub']}; }}
QLabel#monotext {{ font-family: {mono}; font-size: 13px; }}
QLabel#steplight {{ font-size: 18px; font-weight: 800; color: {c['faint']}; }}
QLabel#steplight[tag="Good"] {{ color: {c['pass_']}; }}
QLabel#steplight[tag="Down"] {{ color: {c['accent']}; }}
QLabel#steplight[tag="Broken"] {{ color: {c['fail']}; }}
QLabel#steplight[tag="Wait"] {{ color: {c['faint']}; }}
QLabel#tag {{ font-family: {mono}; font-size: 10px; font-weight: 500; letter-spacing: 1px; color: {c['faint']}; }}
{tags}
QLabel#tag[tag="Good"], QLabel#tag[tag="Look"], QLabel#tag[tag="Broken"], QLabel#tag[tag="Error"], QLabel#tag[tag="Down"] {{ font-weight: 700; }}
QLabel#verdict[tag="Error"] {{ color: {c['fail']}; }}
QProgressBar[tag="Error"]::chunk {{ background: {c['fail']}; }}
QWidget#row[tag="Error"] {{ border-left: 3px solid {c['fail']}; }}
QLabel#count {{ font-family: {display}; font-size: 26px; font-weight: 700; }}
QLabel#count[tag="Good"] {{ color: {c['pass_']}; }}
QLabel#count[tag="Look"] {{ color: {c['warn']}; }}
QLabel#count[tag="Broken"] {{ color: {c['fail']}; }}
QLabel#verdict {{ font-family: {display}; font-size: 22px; font-weight: 700; }}
QLabel#verdict[tag="Good"] {{ color: {c['pass_']}; }}
QLabel#verdict[tag="Look"] {{ color: {c['warn']}; }}
QLabel#verdict[tag="Broken"] {{ color: {c['fail']}; }}

/* inputs */
QLineEdit {{ background: transparent; border: none; border-bottom: 1px solid {c['line']}; padding: 8px 2px; font-size: 15px; selection-background-color: {c['accent']}; }}
QLineEdit:focus {{ border-bottom: 1px solid {c['accent']}; }}
QLineEdit#hero {{ font-family: {display}; font-size: 28px; font-weight: 600; padding: 12px 2px; }}
QLineEdit#filter {{ background: {c['panel']}; border: 1px solid {c['line']}; border-radius: 3px; padding: 8px 12px; font-size: 14px; }}
QLineEdit#filter:focus {{ border: 1px solid {c['accent']}; }}
QLineEdit#monoinput {{ font-family: {mono}; font-size: 13px; }}
QPlainTextEdit {{ background: {c['panel']}; border: 1px solid {c['line']}; border-radius: 3px; padding: 10px 12px; font-size: 14px; }}
QPlainTextEdit:focus {{ border: 1px solid {c['accent']}; }}
QSpinBox {{ background: transparent; border: none; border-bottom: 1px solid {c['line']}; padding: 6px 2px; font-size: 15px; }}
QCheckBox {{ spacing: 10px; font-size: 14px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid {c['faint']}; border-radius: 3px; background: {c['panel']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
QComboBox {{ background: transparent; border: none; border-bottom: 1px solid {c['line']}; padding: 6px 2px; font-size: 15px; }}
QComboBox QAbstractItemView {{ background: {c['panel']}; border: 1px solid {c['line']}; selection-background-color: {c['soft']}; }}

/* buttons */
QPushButton {{ font-weight: 700; font-size: 14px; border-radius: 3px; padding: 0 20px; min-height: 44px; }}
QPushButton#primary {{ background: {c['cta_bg']}; color: {c['cta_text']}; border: none; }}
QPushButton#primary:hover {{ background: {c['accent']}; color: {c['accent_text']}; }}
QPushButton#primary:disabled {{ background: {c['bar']}; color: {c['faint']}; }}
QPushButton#accent {{ background: {c['accent']}; color: {c['accent_text']}; border: none; }}
QPushButton#accent:hover {{ background: {c['text']}; color: {c['on_text']}; }}
QPushButton#ghost {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['line']}; border-radius: 3px; min-height: 40px; max-height: 40px; font-size: 13px; }}
QPushButton#ghost:hover {{ border-color: {c['accent']}; }}
QPushButton#danger {{ background: {c['panel']}; color: {c['fail']}; border: 1px solid {c['line']}; }}
QPushButton#danger:hover {{ border-color: {c['fail']}; }}
QPushButton#link {{ background: none; border: none; color: {c['text']}; font-weight: 600; font-size: 13px; min-height: 0; padding: 4px 0; text-align: left; }}
QPushButton#link:hover {{ color: {c['muted']}; }}
QPushButton#small {{ min-height: 30px; max-height: 30px; padding: 0 14px; font-size: 12px; border-radius: 3px; background: {c['accent']}; color: {c['accent_text']}; border: none; }}
QPushButton#small:hover {{ background: {c['text']}; color: {c['on_text']}; }}
QPushButton#play {{ background: {c['accent']}; color: {c['accent_text']}; border: none; border-radius: 13px; font-size: 10px; padding: 0; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; }}
QPushButton#play:hover {{ background: {c['text']}; color: {c['bg']}; }}
QPushButton#pillbtn {{ background: transparent; color: {c['pass_']}; border: 1px solid {c['pass_']}; border-radius: 3px; padding: 0 8px; min-height: 26px; max-height: 26px; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; }}
QPushButton#pillbtn:hover {{ background: {c['pass_']}; color: #ffffff; }}
QPushButton#pillbtn[armed="true"] {{ background: {c['accent']}; border-color: {c['accent']}; color: {c['accent_text']}; }}
QFrame#trowdrop {{ background: {c['panel']}; border-top: 1px dashed {c['line']}; }}
QPushButton#altrow {{ background: transparent; border: none; text-align: left; padding: 0 8px; min-height: 26px; max-height: 26px; font-family: "IBM Plex Mono"; font-size: 12px; color: {c['text']}; border-radius: 3px; }}
QPushButton#altrow:hover {{ background: {c['soft']}; }}
QPushButton#altrow:disabled {{ color: {c['accent']}; font-weight: 600; }}
QLabel#loadtitle {{ font-size: 20px; font-weight: 600; color: {c['text']}; letter-spacing: 0.2px; }}
QLabel#pip {{ background: {c['line']}; border-radius: 4px; }}
QLabel#pip[state="busy"] {{ background: {c['accent']}; }}
QLabel#pip[state="done"] {{ background: {c['pass_']}; }}
QLabel#pip[state="skip"] {{ background: {c['faint']}; }}
QLabel#pip[state="fail"] {{ background: {c['fail']}; }}
QPushButton#zoom {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['line']}; border-radius: 3px; padding: 0; min-height: 0; font-size: 14px; font-weight: 600; }}
QPushButton#zoom:hover {{ border-color: {c['accent']}; }}
QPushButton#zoom:disabled {{ color: {c['faint']}; border-color: {c['bar']}; }}
QPushButton#x {{ min-height: 0; padding: 0; border: none; background: none; color: {c['faint']}; font-size: 15px; font-weight: 500; min-width: 18px; max-width: 18px; max-height: 18px; }}
QPushButton#x:hover {{ color: {c['fail']}; }}
QPushButton#chip {{ background: {c['panel']}; border: 1px solid {c['line']}; border-radius: 3px; padding: 0 12px; min-height: 30px; max-height: 30px; font-size: 12px; font-weight: 600; color: {c['text']}; }}
QPushButton#chip:checked {{ background: {c['soft']}; border-color: {c['accent']}; color: {c['accent']}; }}
QPushButton#navitem {{ background: none; border: none; border-radius: 3px; text-align: left; padding: 9px 12px; min-height: 0; color: {c['muted']}; font-weight: 600; font-size: 14px; }}
QPushButton#navitem:hover {{ color: {c['text']}; }}
QPushButton#navitem[active="true"] {{ background: {c['nav_bg']}; color: {c['nav_text']}; }}

/* rows and lists */
QWidget#row {{ background: transparent; border-bottom: 1px solid {c['line']}; }}
QWidget#row:hover, QWidget#row[flash="true"] {{ background: {c['pass_']}22; border-color: {c['pass_']}; }}
QWidget#row[selected="true"] {{ background: {c['soft']}; border-radius: 3px; }}
QProgressBar {{ background: {c['bar']}; border: none; border-radius: 2px; max-height: 3px; min-height: 3px; }}
QProgressBar::chunk {{ background: {c['text']}; border-radius: 2px; }}
QProgressBar[tag="Down"]::chunk {{ background: {c['accent']}; }}
QProgressBar[tag="Good"]::chunk {{ background: {c['pass_']}; }}
QProgressBar[tag="Look"]::chunk {{ background: {c['warn']}; }}
QProgressBar[tag="Broken"]::chunk {{ background: {c['fail']}; }}
QProgressBar[tag="Wait"]::chunk {{ background: {c['bar']}; }}
QFrame#rule {{ background: {c['line']}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#card {{ background: {c['soft']}; border-radius: 3px; }}
QFrame#card[tag="Good"] {{ background: {c['panel']}; border: 1px solid {c['line']}; border-left: 4px solid {c['pass_']}; }}
QFrame#card[tag="Look"] {{ background: {c['panel']}; border: 1px solid {c['line']}; border-left: 4px solid {c['warn']}; }}
QFrame#card[tag="Broken"] {{ background: {c['panel']}; border: 1px solid {c['line']}; border-left: 4px solid {c['fail']}; }}
QFrame#dropcard {{ background: {c['panel']}; border: 1px solid {c['line']}; border-left: 4px solid {c['sel']}; border-top: none; }}
/* Discover */
QFrame#tile {{ background: {c['panel']}; border: 1px solid {c['line']}; border-top: 3px solid {c['line']}; border-radius: 3px; }}
QFrame#tile:hover {{ border-color: {c['line']}; border-top-color: {c['accent']}; background: {c['panel']}; }}
QLabel#tiletitle {{ font-family: {display}; font-size: 16px; font-weight: 700; }}
QLabel#tilemeta {{ font-family: {mono}; font-size: 11px; letter-spacing: 0.5px; color: {c['accent']}; }}
QLabel#section {{ font-family: {display}; font-size: 20px; font-weight: 700; margin-top: 6px; }}
QFrame#spin {{ background: {c['panel']}; border: 1px solid {c['line']}; border-left: 4px solid {c['accent']}; border-radius: 3px; }}
QLabel#spintitle {{ font-family: {display}; font-size: 26px; font-weight: 700; }}
QLabel#spinartist {{ font-size: 17px; color: {c['muted']}; }}
QLabel#clubhead {{ font-family: {mono}; font-size: 12px; font-weight: 700; letter-spacing: 1px; }}
QFrame#cover {{ background: transparent; border: none; }}
QLabel#covertitle {{ font-family: {display}; font-size: 14px; font-weight: 700; }}
QFrame#mixrow {{ background: {c['panel']}; border: 1px solid {c['line']}; border-left: 3px solid {c['accent']}; border-radius: 3px; }}
QPushButton#pulse {{ background: {c['sel']}; color: {c['sel_text']}; border: none; border-radius: 3px; padding: 0 16px; min-height: 34px; max-height: 34px; font-size: 13px; font-weight: 700; }}
QPushButton#pulse:hover {{ background: {c['accent']}; color: {c['accent_text']}; }}
QFrame#menu {{ background: {c['panel']}; border: 1px solid {c['line']}; border-radius: 3px; }}
QPushButton#menuitem {{ background: none; border: none; border-radius: 3px; text-align: left; padding: 10px 14px; min-height: 0; font-weight: 600; font-size: 14px; }}
QPushButton#menuitem:hover {{ background: {c['soft']}; }}

/* tables */
QTreeWidget {{ background: transparent; border: none; alternate-background-color: transparent; outline: 0; }}
QTreeWidget::item {{ padding: 9px 4px; border-bottom: 1px solid {c['line']}; }}
QTreeWidget::item:hover {{ background: {c['soft']}; }}
QTreeWidget::item:selected {{ background: {c['sel']}; color: {c['sel_text']}; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{ background: transparent; border: none; border-bottom: 1px solid {c['line']}; padding: 6px 4px; font-family: {mono}; font-size: 10px; letter-spacing: 1px; color: {c['faint']}; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['bar']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:vertical[idle="true"] {{ background: transparent; }}
QScrollBar::handle:vertical[idle="true"] {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; }}
QScrollBar::handle:horizontal {{ background: {c['bar']}; border-radius: 3px; }}
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
