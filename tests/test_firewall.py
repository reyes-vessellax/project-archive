"""Firewall helper: never prompts when a rule exists; platform-safe elsewhere."""
from pathlib import Path

from app.core import firewall


def test_non_windows_is_a_noop():
    if firewall.is_windows():
        return
    assert firewall.rule_exists(Path("/x/engine")) is None
    assert firewall.add_rule(Path("/x/engine")) is False


def test_rule_name_uses_app_name():
    from app.config import APP_NAME
    assert APP_NAME in firewall.RULE_NAME
