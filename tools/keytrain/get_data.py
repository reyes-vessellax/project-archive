"""Download the GiantSteps audio (two-minute Beatport previews) for key training and testing.

    python -m tools.keytrain.get_data [--out DIR] [--only key|mtg]

  key  GiantSteps Key: 604 clips, the test set (human-checked keys)        ~0.9 GB
  mtg  GiantSteps MTG Key: 1,159 high-confidence clips, the training set   ~1.7 GB

Each file comes from the dataset's mirror at JKU Linz, with Beatport as a fallback, and is checked against the
dataset's MD5. Files already present and correct are skipped, so it is safe to re-run after an interruption.
The audio stays outside the repository (default: ~/digmart-keydata) and must never be committed.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
SETS = {
    "key": (HERE / "data" / "giantsteps_key.tsv",
            ["https://www.cp.jku.at/datasets/giantsteps/backup/", "https://geo-samples.beatport.com/lofi/"]),
    "mtg": (HERE / "data" / "giantsteps_mtg.tsv",
            ["https://www.cp.jku.at/datasets/giantsteps/mtg_key_backup/", "https://geo-samples.beatport.com/lofi/"]),
}
DEFAULT_OUT = Path.home() / "digmart-keydata"


def rows(tsv: Path) -> list[tuple[str, str, str]]:
    lines = tsv.read_text(encoding="utf-8").splitlines()[1:]
    return [tuple(l.split("\t")) for l in lines if l.strip()]


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def fetch(name: str, out: Path) -> tuple[int, int, int]:
    tsv, bases = SETS[name]
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    got = had = bad = 0
    items = rows(tsv)
    for n, (cid, md5, _key) in enumerate(items, 1):
        dest = folder / f"{cid}.mp3"
        if dest.exists() and _md5(dest) == md5:
            had += 1
            continue
        ok = False
        for base in bases:
            try:
                req = urllib.request.Request(base + f"{cid}.mp3", headers={"User-Agent": "DigMart-keytrain"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    dest.write_bytes(r.read())
                if _md5(dest) == md5:
                    ok = True
                    break
            except Exception:
                pass
        if ok:
            got += 1
        else:
            bad += 1
            dest.unlink(missing_ok=True)
            print(f"  failed {cid}", flush=True)
        if n % 50 == 0:
            print(f"  {name}: {n}/{len(items)}  downloaded {got}  already had {had}  failed {bad}", flush=True)
        time.sleep(0.2)
    return got, had, bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--only", choices=sorted(SETS))
    a = ap.parse_args(argv)
    bad_total = 0
    for name in ([a.only] if a.only else ["mtg", "key"]):
        print(f"{name} -> {a.out / name}", flush=True)
        got, had, bad = fetch(name, a.out)
        print(f"== {name}: downloaded {got}, already had {had}, failed {bad}", flush=True)
        bad_total += bad
    return 1 if bad_total else 0


if __name__ == "__main__":
    sys.exit(main())
