from app.main import rotate_log


def test_big_log_rotates_small_stays(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("x" * 50)
    rotate_log(log, max_bytes=100)
    assert log.exists() and not (tmp_path / "app.log.1").exists()
    log.write_text("y" * 200)
    rotate_log(log, max_bytes=100)
    assert not log.exists() and (tmp_path / "app.log.1").read_text() == "y" * 200
    rotate_log(log, max_bytes=100)                       # no log yet: nothing happens
