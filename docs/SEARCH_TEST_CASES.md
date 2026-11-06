# Search test cases (vs the incumbent client)

Re-run after each search change; note build, time-to-first-rows and final count from `app.log`.

| Query | 0.5.4 (4-rung ladder, throttled) | 0.5.7 (one search, stop on plateau) | Notes |
|---|---|---|---|
| fletch | outperforms / comparable | | |
| norman weber | outperforms / comparable | | |
| Benjamin berg | slower, got results | | |
| ulo s. | notably slow; faster on incumbent | 361 rows / 95 users, 6.8 s | trailing "." — strip punctuation from words (0.5.6) |
| guy gerber | notably slow; faster on incumbent | 4,938 rows / 330 users, 6.0 s | |
| alan nieves | notably slow; faster on incumbent | | |
| garrett David | none; incumbent found | 4,488 rows / 315 users, 6.1 s | check engine response count in app.log |
| Munir nadir | none; incumbent found | 345 rows / 46 users, 6.8 s | |
| chinonegro | none; incumbent found | 2,114 rows / 172 users, 8.4 s | |
| swagrecords | none; incumbent had only an ad page | | expected: ad bots are greyed |
| volpat | 121 vs ~60 | | |
| john summit | 999 users | | |
| jay de lys | 0 in the throttled window; 1,427 after 7 quiet min | | throttle, not matching |
| janeret | | 0 after 40 s | re-check on a quiet account |
| brennan | | 4,436 rows / 235 users, 13.3 s | |
| josh butler | | 2,377 rows / 246 users, 6.8 s | |
| silat beksi | | 3,768 rows / 155 users, 6.8 s | |

## Benchmark run (500-name list)

`docs/search_bench_list.txt` holds the comparison list. Run with the app closed:

    "Pied Piper.exe" --bench docs\search_bench_list.txt --limit 60

(one search per name, 15 s open, 10 s gap: ~25 min for 60 names; the full 500 is ~3.5 h). Results land in
`bench.csv` in the data folder: time to first rows, users/files at 5 s and at the end, pickable vs locked
vs other-format vs ad-bot. Fill the incumbent's counts for the same names by hand and compare.
