"""The engine (slskd) version is set once, in app/config.py; everything that names it must agree."""
import re
from pathlib import Path

from app.config import ENGINE_NAME, ENGINE_SOURCE_URL, ENGINE_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_engine_version_is_named_the_same_everywhere():
    assert ENGINE_NAME == "slskd" and re.fullmatch(r"\d+\.\d+\.\d+", ENGINE_VERSION)
    assert ENGINE_SOURCE_URL.endswith("/tree/" + ENGINE_VERSION)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    thanks = readme[readme.index("## Thanks and open-source licences"):]
    assert "Special thanks to the **slskd** team" in thanks and "AGPL-3.0" in thanks
    assert ENGINE_SOURCE_URL in thanks and f"slskd](https://github.com/slskd/slskd)\n{ENGINE_VERSION}" in thanks
    assert readme.rstrip().endswith("[`docs/ENGINE_UPDATES.md`](docs/ENGINE_UPDATES.md).")     # it's the last section
    manager = (ROOT / "app/core/slskd_manager.py").read_text(encoding="utf-8")
    assert manager.startswith("# Special thanks to the slskd team") and f"version {ENGINE_VERSION} " in manager[:400]


def test_builds_read_the_version_instead_of_repeating_it():
    ci = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
    assert ci.count("from app.config import ENGINE_VERSION") == 2            # Windows and macOS jobs
    assert not re.search(r'SLSKD_VERSION:\s*"', ci)                           # no hard-coded copy left
    build = (ROOT / "packaging/build.py").read_text(encoding="utf-8")
    assert "OPEN_SOURCE_NOTES" in build and "ENGINE_SOURCE_URL" in build     # the shipped README.txt carries the notes
