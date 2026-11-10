import json
import time

from app.core.session import Session, SessionStore


def test_round_trip(tmp_path):
    st = SessionStore(tmp_path / "session.json")
    st.save(Session(page="library", search_text="night bus", filters={"lossless": True}, library_open_job="j1"), now=True)
    s = st.load()
    assert (s.page, s.search_text, s.filters, s.library_open_job) == ("library", "night bus", {"lossless": True}, "j1")


def test_missing_or_broken_file_means_fresh_start(tmp_path):
    p = tmp_path / "session.json"
    assert SessionStore(p).load() == Session()
    p.write_text("{not json")
    assert SessionStore(p).load().page == "home"


def test_unknown_keys_from_newer_versions_are_ignored(tmp_path):
    p = tmp_path / "session.json"
    p.write_text(json.dumps({"page": "batch", "something_new": 1}))
    assert SessionStore(p).load().page == "batch"


def test_debounced_but_always_the_latest(tmp_path):
    st = SessionStore(tmp_path / "session.json", min_interval_s=0.3)
    st.save(Session(search_text="a"), now=True)
    for t in ("b", "c", "d"):
        st.save(Session(search_text=t))                    # within the interval: not written yet
    assert st.load().search_text == "a"
    end = time.monotonic() + 3.0                           # slow CI runners: give the delayed write time to land
    while st.load().search_text != "d" and time.monotonic() < end:
        time.sleep(0.05)
    assert st.load().search_text == "d"


def test_no_temp_file_left_behind(tmp_path):
    st = SessionStore(tmp_path / "session.json")
    st.save(Session(page="ready"), now=True)
    assert [p.name for p in tmp_path.iterdir()] == ["session.json"]
