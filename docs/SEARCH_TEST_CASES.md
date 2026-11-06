# Search test cases (vs the incumbent client)

Re-run after each search change; note build, time-to-first-rows and final count from `app.log`.

| Query | 0.5.4 (4-rung ladder, throttled) | 0.5.5 | Notes |
|---|---|---|---|
| fletch | outperforms / comparable | | |
| norman weber | outperforms / comparable | | |
| Benjamin berg | slower, got results | | |
| ulo s. | notably slow; faster on incumbent | | trailing "." — strip punctuation from words (0.5.6) |
| guy gerber | notably slow; faster on incumbent | | |
| alan nieves | notably slow; faster on incumbent | | |
| garrett David | none; incumbent found | | check engine response count in app.log |
| Munir nadir | none; incumbent found | | |
| chinonegro | none; incumbent found | | |
| swagrecords | none; incumbent had only an ad page | | expected: ad bots are greyed |
| volpat | 121 vs ~60 | | |
| john summit | 999 users | | |

## Benchmark run (500-name list)

`docs/search_bench_list.txt` holds the comparison list. Run with the app closed:

    "Pied Piper.exe" --bench docs\search_bench_list.txt --limit 60

(one search per name, 15 s open, 10 s gap: ~25 min for 60 names; the full 500 is ~3.5 h). Results land in
`bench.csv` in the data folder: time to first rows, users/files at 5 s and at the end, pickable vs locked
vs other-format vs ad-bot. Fill the incumbent's counts for the same names by hand and compare.
