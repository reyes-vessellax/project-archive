"""Search benchmark: run a list of queries through the real engine, one at a time, with pacing that
stays under the network's throttle, and record what came back and how fast.

    "Pied Piper.exe" --bench docs/search_bench_list.txt [--limit 50] [--per 15] [--gap 10]

Writes bench.csv and bench.log into the data folder (Settings → Advanced → Open logs folder).
Columns: n, query, first_rows_s, users_5s, files_5s, users_end, files_end, pickable, locked,
other_format, ad_bots, error. The app must be closed (one engine per account).
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import datetime
from pathlib import Path


def run(list_path: Path, limit: int | None, per_s: float, gap_s: float) -> int:
    from .config import data_dir
    from .core.service import ArchiveService
    out_dir = data_dir(); out_dir.mkdir(parents=True, exist_ok=True)
    csv_path, log_path = out_dir / "bench.csv", out_dir / "bench.log"
    log = open(log_path, "a", encoding="utf-8")

    def say(msg: str):
        log.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n"); log.flush()
        if sys.stdout:
            print(msg, flush=True)

    queries = [q.strip() for q in list_path.read_text(encoding="utf-8", errors="replace").splitlines() if q.strip()]
    if limit:
        queries = queries[:limit]
    say(f"bench: {len(queries)} queries, {per_s:.0f}s each, {gap_s:.0f}s gap -> about {len(queries) * (per_s + gap_s + 2) / 60:.0f} min")

    svc = ArchiveService()
    svc.start_backend()
    if svc.backend_state != "running":
        say(f"bench: engine didn't start: {svc.backend_error}"); return 2
    for _ in range(120):
        if svc.adapter_logged_in():
            break
        time.sleep(1)
    else:
        say("bench: never signed in"); return 2
    say(f"bench: signed in; port note: {svc.port_note}")

    new = not csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["n", "query", "first_rows_s", "users_5s", "files_5s", "users_end", "files_end",
                        "pickable", "locked", "other_format", "ad_bots", "error", "when"])
        for n, q in enumerate(queries, 1):
            svc.engine_housekeeping()
            t0 = time.monotonic()
            first = None; users5 = files5 = 0
            try:
                res = svc.search(q, timeout_s=per_s)
                sid = res.search_id
                while True:
                    time.sleep(0.5)
                    done, users, files, err = svc.search_status(sid)
                    el = time.monotonic() - t0
                    if first is None and files > 0:
                        first = round(el, 1)
                    if el <= 5.2:
                        users5, files5 = users, files
                    if done or el > per_s + 15:
                        break
                final = svc.search_results(sid)
                c = final.candidates
                row = [n, q, first if first is not None else "", users5, files5, users, files,
                       sum(1 for x in c if not x.note and not x.locked), sum(1 for x in c if x.locked and not x.note),
                       sum(1 for x in c if x.note == "Extension mismatch"), sum(1 for x in c if x.note == "Ad bot"),
                       err or "", datetime.now().isoformat(timespec="seconds")]
                svc.forget_search(sid)
            except Exception as e:                           # noqa: BLE001
                row = [n, q, "", 0, 0, 0, 0, 0, 0, 0, 0, f"{type(e).__name__}: {e}", datetime.now().isoformat(timespec="seconds")]
            w.writerow(row); f.flush()
            say(f"{n:4d} {q!r:34} first={row[2]!s:>5} 5s={row[3]}u/{row[4]}f end={row[5]}u/{row[6]}f pickable={row[7]} {row[11]}")
            time.sleep(gap_s)
    svc.stop_backend()
    say(f"bench: done -> {csv_path}")
    log.close()
    return 0


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="--bench")
    ap.add_argument("list", type=Path)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--per", type=float, default=15.0, help="seconds each search is left open")
    ap.add_argument("--gap", type=float, default=10.0, help="seconds between searches")
    a = ap.parse_args(argv)
    return run(a.list, a.limit, a.per, a.gap)
