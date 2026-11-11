"""Audit (Low): the bundled Python packages' licence texts weren't shipped (PyInstaller drops dist-info)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))


def test_licence_texts_are_collected_for_bundled_packages(tmp_path):
    import licenses
    found = licenses.collect(tmp_path / "licenses")
    assert "PySide6" in found or "PySide6_Essentials" in found and "numpy" in found
    for name in found:
        d = tmp_path / "licenses" / name
        assert any(p.is_file() and p.name != "INFO.txt" for p in d.iterdir()), name     # a real licence text each
