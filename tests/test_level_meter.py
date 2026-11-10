"""The level meter: real per-channel loudness, instant attack, smooth release, a peak marker that hangs then falls."""
import os

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.conftest import needs_ffmpeg


@needs_ffmpeg
def test_envelope_from_the_audio(fixtures):
    from app.ui.widgets import level_envelope
    left, right, hop = level_envelope(str(fixtures["source_wav"]))
    assert hop == 0.02 and abs(len(left) - 40 / 0.02) <= 2 and 0.3 < float(np.median(left)) < 1.0


def test_ballistics():
    from PySide6.QtWidgets import QApplication
    from app.ui.widgets import LevelStrip
    QApplication.instance() or QApplication([])
    m = LevelStrip()
    t = [0.0]
    m._clock = lambda: t[0]; m._last = 0.0
    loud = np.full(500, 0.9, np.float32); quiet = np.zeros(500, np.float32)
    m.set_envelope((np.concatenate([loud, quiet]), np.concatenate([loud, quiet]), 0.02))
    for i in range(6):                                   # 0.1 s of loud: up almost at once
        t[0] += 1 / 60; m.feed(5.0 + i / 60)
    assert m.level() > 0.85
    t[0] += 1 / 60; m.feed(10.5); first_drop = m.level()
    assert 0.75 < first_drop < 0.9                       # falls smoothly, not to zero in one frame
    peak = m._peak[0]
    for i in range(30):                                  # 0.5 s, frame by frame
        t[0] += 1 / 60; m.feed(10.5 + i / 60)
    assert m._peak[0] == peak                            # the peak marker hangs
    for i in range(60):                                  # another second
        t[0] += 1 / 60; m.feed(11.0 + i / 60)
    assert m._peak[0] < peak and m.level() < 0.1         # then floats down; the bar has dropped
