"""Search results: click a heading to sort (again to flip), # back to best first; greyed rows stay last."""
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.adapters.base import Candidate, SearchResult


def cand(name, ext, size, kbps=None, speed=0, free=True, queue=0, note=""):
    return Candidate("soulseek", "u_" + name, f"/m/{name}.{ext}", size, display_name=f"{name}.{ext}", title=name,
                     artist=name[0].upper(), extension=ext, bitrate_kbps=kbps, free_slot=free, queue_length=queue,
                     upload_speed=speed, note=note)


@pytest.fixture
def page():
    from PySide6.QtWidgets import QApplication
    from app.config import Settings
    from app.ui.pages import SearchPage
    app = QApplication.instance() or QApplication([])
    svc = SimpleNamespace(settings=Settings(), already_have=lambda c: None)
    p = SearchPage(svc); p.resize(1200, 700); p.show()
    cands = [
        cand("alpha", "mp3", 9_000_000, 320, speed=2_000_000),
        cand("bravo", "wav", 50_000_000, speed=500_000),
        cand("charlie", "flac", 30_000_000, speed=9_000_000, free=False, queue=3),
        cand("delta", "wav", 48_000_000, speed=100_000),
        cand("echo", "aiff", 40_000_000, speed=7_000_000, note="Extension mismatch"),
    ]
    p.show_results(SearchResult("q", "1", True, cands), searching=False)
    app.processEvents()
    yield p, app
    p.close()


def names(p):
    out = []
    for i in range(p.tree.topLevelItemCount()):
        c = p.tree.topLevelItem(i).data(0, 0x0100)
        if isinstance(c, Candidate):
            out.append(c.title)
    return out


def test_default_is_fastest_first_with_greyed_last(page):
    p, _ = page
    assert names(p)[0] == "alpha" and names(p)[-1] == "echo"
    assert "fastest first" in p.state.text()


def test_heading_click_sorts_and_flips(page):
    p, app = page
    size = p.COLS.index("Size")
    p.sort_by(size); app.processEvents()
    assert names(p)[:4] == ["bravo", "delta", "charlie", "alpha"] and names(p)[-1] == "echo"
    assert "by size ↓" in p.state.text()
    p.sort_by(size); app.processEvents()
    assert names(p)[:4] == ["alpha", "charlie", "delta", "bravo"]
    p.sort_by(p.COLS.index("Title")); app.processEvents()
    assert names(p)[:4] == ["alpha", "bravo", "charlie", "delta"]
    p.sort_by(0); app.processEvents()
    assert names(p)[0] == "alpha" and "fastest first" in p.state.text()
    assert p.tree.header().sortIndicatorSection() == 0


def test_rate_groups_the_wavs_together(page):
    """A beta tester wanted 'just WAV': sorting by Rate puts each lossless format in its own block."""
    p, app = page
    p.sort_by(p.COLS.index("Rate")); app.processEvents()
    rows = names(p)
    assert rows[:3] == ["bravo", "delta", "charlie"] or rows[:3] == ["delta", "bravo", "charlie"], rows
    assert rows.index("alpha") > rows.index("charlie")         # lossy below lossless
