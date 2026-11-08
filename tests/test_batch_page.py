"""Each playlist is its own batch; switching never leaves old rows behind; batches survive a restart."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core import batch as B
from app.core import batch_runner as BR
from app.ui.batch_page import Batch, BatchPage, TrackRow

_KEEP = []    # pages live as long as the window in the app; never let Python free them mid-test


def _page():
    p = BatchPage(); _KEEP.append(p)
    return p


def _batch(name, n, service="YouTube"):
    return Batch(name, service, [BR.Item(B.Wanted("Artist", f"{name} {i}")) for i in range(n)])


def test_each_playlist_is_its_own_batch_and_rows_never_ghost():
    app = QApplication.instance() or QApplication([])
    p = _page()
    a, b = _batch("Warm-up", 9), _batch("Peak", 3, "SoundCloud")
    p.add_batch(a); p.add_batch(b)
    assert [x.name for x in p.batches] == ["Peak", "Warm-up"]            # newest first, both kept
    assert p.selected == b.id
    p.select(a.id); app.processEvents()
    live = [r for r in p.row_host.findChildren(TrackRow) if not r.isHidden()]
    assert len(live) == 9                                                # only the selected playlist's rows exist
    p.select(b.id); app.processEvents()
    assert len([r for r in p.row_host.findChildren(TrackRow) if not r.isHidden()]) == 3


def test_progress_and_counts_follow_the_runner():
    app = QApplication.instance() or QApplication([])
    p = _page()
    a = _batch("Warm-up", 4); p.add_batch(a)
    a.items[0].status = "found"; p.update_item(a.id, 0, a.items[0])
    a.items[1].status = "have"; p.update_item(a.id, 1, a.items[1])
    assert p.tiles["found"].text() == "1" and p.tiles["have"].text() == "1" and p.tiles["left"].text() == "2"
    assert p.btn_all.text() == "Download and check 1"


def test_batches_round_trip_through_auto_save(tmp_path):
    from app.core.session import Session, SessionStore
    st = SessionStore(tmp_path / "s.json")
    a, b = _batch("Warm-up", 2), _batch("Peak", 1)
    st.save(Session(batches=[b.to_dict(), a.to_dict()], batch_selected=a.id), now=True)
    s = st.load()
    assert [d["name"] for d in s.batches] == ["Peak", "Warm-up"] and s.batch_selected == a.id
    assert s.batches[1]["items"][0]["title"] == "Warm-up 0"
