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
        import cryptography, mutagen, yt_dlp  # noqa: F401,E401  (tags, signed updates, playlist links)
        say(f"components: mutagen {mutagen.version_string}, yt-dlp {yt_dlp.version.__version__}, cryptography {cryptography.__version__}")
        say("audio playback: " + _audio_probe(exe_ffmpeg=find_tool("ffmpeg")))
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


def _audio_probe(exe_ffmpeg: str) -> str:
    """Can the bundled Qt play a file? Non-fatal: build machines usually have no sound device, but the
    media backend must at least load and report, never crash."""
    import os
    import subprocess
    import tempfile
    from pathlib import Path
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        dev = QMediaDevices.defaultAudioOutput()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            f = Path(tmp) / "probe.mp3"
            subprocess.run([exe_ffmpeg, "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=3", "-c:a", "libmp3lame",
                            "-b:a", "128k", str(f)], check=True, timeout=60)
            out = QAudioOutput(); player = QMediaPlayer(); player.setAudioOutput(out)
            player.setSource(QUrl.fromLocalFile(str(f))); player.play()
            loop = QEventLoop(); QTimer.singleShot(1500, loop.quit); loop.exec()
            pos, err = player.position(), player.errorString()
            player.stop(); player.setSource(QUrl())            # let go of the file before the folder is removed
            loop = QEventLoop(); QTimer.singleShot(300, loop.quit); loop.exec()
        return f"device={'none' if dev.isNull() else dev.description()!r} position_after_1.5s={pos}ms error={err!r}"
    except Exception as e:                                  # noqa: BLE001
        return f"backend unavailable: {e}"


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    if "--bench" in sys.argv:
        from app.bench import main as bench_main
        i = sys.argv.index("--bench")
        sys.exit(bench_main(sys.argv[i + 1:]))
    from app.main import main
    sys.exit(main())
