"""Release pipeline: build the signed update manifest (latest.json).

    python packaging/make_manifest.py --version 0.6.0 --base-url https://.../download/v0.6.0 \
        --notes "What's new" windows-x64=dist/PiedPiper-0.6.0-windows-x64.zip macos-arm64=...zip

The signing key comes from the PIEDPIPER_SIGNING_KEY environment variable (PEM, Ed25519) - a GitHub
secret in CI. It is never written to disk or printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.updater import sign_manifest  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--notes", default="")
    ap.add_argument("--out", default="dist/latest.json")
    ap.add_argument("assets", nargs="+", help="platform=path, e.g. windows-x64=dist/x.zip")
    a = ap.parse_args()
    key = os.environ.get("PIEDPIPER_SIGNING_KEY", "").encode()
    if not key:
        print("PIEDPIPER_SIGNING_KEY is not set", file=sys.stderr)
        return 2
    if not a.base_url.startswith("https://"):
        print("--base-url must be https", file=sys.stderr)
        return 2
    assets = {}
    for spec in a.assets:
        plat, _, path = spec.partition("=")
        p = Path(path)
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        assets[plat] = {"url": f"{a.base_url.rstrip('/')}/{p.name}", "sha256": h, "size": p.stat().st_size}
    doc = sign_manifest({"version": a.version, "notes": a.notes, "assets": assets}, key)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=1))
    print(f"wrote {a.out} for {', '.join(assets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
