"""Run with `python -m app`, or as the packaged app. `--self-test` checks the bundle can find FFmpeg."""
import sys


def self_test() -> int:
    """Exit code 0 = bundle is healthy. Windowed builds have no console, so everything is also written
    to self-test.log next to the executable (or the current folder) for CI to print."""
    from pathlib import Path
    log_path = (Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()) / "self-test.log"
    log = open(log_path, "w", encoding="utf-8")

    def say(msg):
        log.write(msg + "\n"); log.flush()
        if sys.stdout:
            print(msg)
    try:
        from app.media.tools import find_tool, run
        for tool in ("ffmpeg", "ffprobe"):
            exe = find_tool(tool)
            if run([exe, "-version"], timeout=30).returncode != 0:
                raise RuntimeError(f"{tool} didn't run")
            say(f"{tool} -> {exe}")
        import app.ui.main_window  # noqa: F401  (imports Qt and the whole UI)
        # The bundled Soulseek engine: generate a throwaway config, start it, make sure the API answers, stop it.
        import tempfile
        from pathlib import Path
        from app.config import Settings
        from app.core.credentials import CredentialStore
        from app.core.slskd_manager import SlskdManager, bundled_slskd_dir
        if bundled_slskd_dir() is None:
            say("engine: not bundled (Soulseek search off)")
        else:
            # Firewall lookup must work on Windows and must never raise.
            from app.core import firewall
            from app.core.slskd_manager import engine_exe
            exe = engine_exe(bundled_slskd_dir())
            say(f"firewall rule for engine: {firewall.rule_exists(exe)!r} (None = couldn't ask)")
            with tempfile.TemporaryDirectory() as tmp:
                m = SlskdManager(Settings(), creds=CredentialStore(Path(tmp) / "s.json", use_keyring=False),
                                 instance_dir=Path(tmp) / "client")
                try:
                    m.start()
                    say(f"engine: ok on {m.url}")
                except Exception as e:
                    say(f"engine: FAILED: {e}")
                    eng = Path(tmp) / "client" / "engine.log"
                    if eng.exists():
                        say("---- engine.log ----\n" + eng.read_text("utf-8", "replace")[-6000:])
                    raise
                finally:
                    m.stop()
    except Exception as e:
        say(f"self-test FAILED: {e}")
        log.close()
        return 1
    say("self-test ok")
    log.close()
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    from app.main import main
    sys.exit(main())
