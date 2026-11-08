"""Windows Firewall: find out whether the engine is already allowed, and allow it in one step.

Windows shows its own "allow this app?" prompt the first time a program listens for connections, once
per executable PATH. Every unzipped test build is a new path, so testers kept seeing it. Here we:
  * ask Windows whether a rule for this exact engine path already exists (no prompt, no admin), and
  * when it doesn't, add one named after the app with a single elevation prompt (the user sees the
    standard UAC dialog naming the app, not the engine).
On macOS and Linux there is nothing to do; the OS prompt, if any, is left alone.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ..config import APP_NAME

RULE_NAME = f"{APP_NAME} downloads"


def _flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def is_windows() -> bool:
    return sys.platform == "win32"


def rule_exists(exe: Path) -> bool | None:
    """True/False when we could ask Windows, None when we couldn't (not Windows, PowerShell missing...)."""
    if not is_windows():
        return None
    script = (
        "$p = [IO.Path]::GetFullPath($env:DW_EXE).ToLowerInvariant(); "
        "$r = Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Program -and ([IO.Path]::GetFullPath($_.Program).ToLowerInvariant()) -eq $p } | "
        "Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object { $_.Enabled -eq 'True' -and $_.Action -eq 'Allow' }; "
        "if ($r) { 'YES' } else { 'NO' }"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=20, creationflags=_flags(),
                             env={**os.environ, "DW_EXE": str(exe)})
        text = out.stdout.strip().splitlines()
        return text[-1].strip() == "YES" if text else None
    except Exception:
        return None


def add_rule(exe: Path) -> bool:
    """Add an inbound+outbound allow rule for the engine, named after the app. One UAC prompt."""
    if not is_windows():
        return False
    inner = (
        f"New-NetFirewallRule -DisplayName '{RULE_NAME}' -Direction Inbound -Action Allow -Program '{exe}' -Profile Any | Out-Null; "
        f"New-NetFirewallRule -DisplayName '{RULE_NAME} (out)' -Direction Outbound -Action Allow -Program '{exe}' -Profile Any | Out-Null"
    )
    # Start-Process -Verb RunAs shows the standard elevation dialog; -Wait lets us report the outcome.
    script = (
        "$p = Start-Process powershell -Verb RunAs -Wait -PassThru -WindowStyle Hidden "
        f"-ArgumentList '-NoProfile','-NonInteractive','-Command',\"{inner}\"; "
        "exit $p.ExitCode"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=180, creationflags=_flags())
        return out.returncode == 0
    except Exception:
        return False
