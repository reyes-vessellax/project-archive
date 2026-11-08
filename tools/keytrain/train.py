"""Train the key model on GiantSteps MTG and test it on GiantSteps Key (which it never trains on).

    python -m tools.keytrain.get_data            # once: downloads ~2.6 GB to ~/digmart-keydata
    python -m tools.keytrain.train [--data DIR] [--also-key-half]

Writes to <data>/out/:
  keymodel.npz   the trained weights (a few KB)
  report.txt     the scores, next to DigMart's current method on the same clips
Features are cached in <data>/out/features_*.npz, so a second run only retrains (seconds).

--also-key-half  also trains on half of GiantSteps Key and tests on the other half (more data; smaller test).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from tools.keytrain import model as K
from tools.keytrain.get_data import DEFAULT_OUT, SETS, rows


def _one(path: str):
    from app.media.musical import decode_low, estimate_key
    y = decode_low(Path(path))
    cur = estimate_key(y)
    return K.features(*K.spectrum(y)), (K.parse(cur[0]) if cur else None)


def load_set(name: str, data: Path, out: Path):
    cache = out / f"features_{name}.npz"
    items = [(cid, K.parse(key)) for cid, _md5, key in rows(SETS[name][0])]
    items = [(cid, k) for cid, k in items if k and (data / name / f"{cid}.mp3").exists()]
    if cache.exists():
        z = np.load(cache, allow_pickle=True)
        if list(z["ids"]) == [c for c, _ in items]:
            return [c for c, _ in items], z["F"], [k for _, k in items], list(z["current"])
    print(f"decoding {len(items)} {name} clips ...", flush=True)
    t = time.time()
    with ProcessPoolExecutor(max(1, (os.cpu_count() or 2) - 1)) as ex:
        res = list(ex.map(_one, [str(data / name / f"{c}.mp3") for c, _ in items], chunksize=8))
    F = np.stack([r[0] for r in res])
    current = [r[1] for r in res]
    np.savez(cache, ids=np.array([c for c, _ in items]), F=F, current=np.array(current, dtype=object))
    print(f"  done in {time.time() - t:.0f}s", flush=True)
    return [c for c, _ in items], F, [k for _, k in items], current


def line(label: str, s: dict) -> str:
    return (f"{label:44s} n={s['n']:4d}  exact {s['exact']:6.1%}  weighted {s['weighted']:6.1%}  "
            f"fifth {s['fifth']:5.1%}  relative {s['relative']:5.1%}  parallel {s['parallel']:5.1%}  other {s['other']:5.1%}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--also-key-half", action="store_true")
    a = ap.parse_args(argv)
    out = a.data / "out"
    out.mkdir(parents=True, exist_ok=True)

    mi, MF, MY, _ = load_set("mtg", a.data, out)
    gi, GF, GY, GC = load_set("key", a.data, out)
    if len(MY) < 500 or len(GY) < 300:
        print(f"not enough audio (mtg {len(MY)}, key {len(GY)}): run  python -m tools.keytrain.get_data  first")
        return 2

    report = [f"DigMart key model, trained {time.strftime('%Y-%m-%d %H:%M')}",
              f"training clips (GiantSteps MTG): {len(MY)}   test clips (GiantSteps Key): {len(GY)}", ""]
    cur_ok = [i for i, c in enumerate(GC) if c]
    report.append(line("current DigMart method, GiantSteps Key", K.score([GC[i] for i in cur_ok], [GY[i] for i in cur_ok])))

    m = K.KeyModel().fit(K.rolled(MF), MY)
    report.append(line("trained model (MTG only), GiantSteps Key", K.score(m.predict(K.rolled(GF)), GY)))
    m.save(out / "keymodel.npz")

    if a.also_key_half:
        A = np.array([int(hashlib.md5(i.encode()).hexdigest(), 16) % 2 == 0 for i in gi])
        F2 = np.concatenate([MF, GF[A]])
        Y2 = MY + [y for y, x in zip(GY, A) if x]
        m2 = K.KeyModel().fit(K.rolled(F2), Y2)
        YB = [y for y, x in zip(GY, A) if not x]
        report.append(line("current method, Key half B", K.score([c for c, x in zip(GC, A) if not x and c],
                                                                 [y for y, c, x in zip(GY, GC, A) if not x and c])))
        report.append(line("trained (MTG + Key half A), Key half B", K.score(m2.predict(K.rolled(GF[~A])), YB)))

    report += ["", "Published reference (Korzeniowski & Widmer 2018, CNN): exact 67.9%  weighted 74.6%",
               "MIREX weighted: exact 1, fifth 0.5, relative 0.3, parallel 0.2.", ""]
    text = "\n".join(report)
    (out / "report.txt").write_text(text, encoding="utf-8")
    print("\n" + text)
    print(f"saved {out / 'keymodel.npz'} and {out / 'report.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
