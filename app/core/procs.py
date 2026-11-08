"""Keep exactly one engine alive, and only while the app is.

Every build of the app signs into the same Soulseek account (the one created silently for this user).
If an engine from an earlier run is still around — the app was killed from Task Manager, crashed, or an
old build's engine never exited — the two sign-ins kick each other off the server in turns and searches
come back empty. So before starting, we end any engine we started before (pid file) and any process
with one of our engine names, and we attach the new engine to a Windows Job Object that ends it the
moment the app process ends, however it ends.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def kill_pid(pid: int) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=20,
                           creationflags=_no_window())
        else:
            os.kill(pid, 9)
    except Exception:
        pass


def kill_by_name(names: tuple[str, ...], keep_pid: int | None = None) -> int:
    """End every process whose image name is one of ours. Returns how many we asked to end."""
    n = 0
    try:
        if sys.platform == "win32":
            for name in names:
                image = name + ".exe"
                out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                                     capture_output=True, text=True, timeout=20, creationflags=_no_window()).stdout
                for line in out.splitlines():
                    parts = [p.strip('"') for p in line.split('","')]
                    if len(parts) > 1 and parts[0].lower() == image.lower() and parts[1].isdigit():
                        pid = int(parts[1])
                        if pid != keep_pid:
                            kill_pid(pid); n += 1
        else:
            for name in names:
                out = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True, timeout=10).stdout
                for p in out.split():
                    if p.isdigit() and int(p) != keep_pid:
                        kill_pid(int(p)); n += 1
    except Exception:
        pass
    return n


class JobObject:
    """Windows: a job that kills its processes when the last handle closes (i.e. when we die)."""

    def __init__(self):
        self.handle = None
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.windll.kernel32
            self._k32 = k32
            h = k32.CreateJobObjectW(None, None)
            if not h:
                return

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount",
                            "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            JobObjectExtendedLimitInformation = 9
            if not k32.SetInformationJobObject(h, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)):
                k32.CloseHandle(h); return
            self.handle = h
        except Exception:
            self.handle = None

    def assign(self, pid: int) -> bool:
        if not self.handle:
            return False
        try:
            PROCESS_SET_QUOTA, PROCESS_TERMINATE = 0x0100, 0x0001
            k32 = self._k32
            ph = k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
            if not ph:
                return False
            ok = bool(k32.AssignProcessToJobObject(self.handle, ph))
            k32.CloseHandle(ph)
            return ok
        except Exception:
            return False
