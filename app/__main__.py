"""Run with `python -m app`, or as the packaged app. `--self-test` checks the bundle can find FFmpeg."""
import sys


def self_test() -> int:
    """Exit code 0 = bundle is healthy. Windowed builds have no console, so don't rely on printing."""
    def say(msg):
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
    except Exception as e:
        say(f"self-test FAILED: {e}")
        return 1
    say("self-test ok")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    from app.main import main
    sys.exit(main())
