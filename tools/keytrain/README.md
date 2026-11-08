# Key training (GiantSteps)

DigMart's key detection is measured against **human-checked keys** from the GiantSteps datasets
(Beatport EDM previews), not against Rekordbox. This folder downloads the clips, trains a small key
model on one set and tests it on the other.

## Run it

From the repository root, with the app's Python environment (numpy + FFmpeg; nothing new to install):

```
python -m tools.keytrain.get_data     # ~2.6 GB to ~/digmart-keydata, about 30-40 min, safe to re-run
python -m tools.keytrain.train        # decodes once (~10 min), trains in seconds, prints the scores
```

Results land in `~/digmart-keydata/out/`: `report.txt` (scores) and `keymodel.npz` (weights, a few KB).
`--also-key-half` adds a run that also trains on half the test set and tests on the other half.

## Datasets

| Set | Clips | Used for | Labels |
|---|---|---|---|
| GiantSteps Key | 604 | testing only | `data/giantsteps_key.tsv` |
| GiantSteps MTG Key | 1,159 (confidence 2, single key) | training | `data/giantsteps_mtg.tsv` |

The two sets share no tracks. The audio is never stored in the repository.

## Results so far (Nov 2026)

| Method | Exact | MIREX weighted |
|---|---|---|
| DigMart now (spectral peaks + Krumhansl profiles + third rule) | 55.8% | 64.3% |
| Trained on 300 GiantSteps Key tracks (tested on the other 293) | 59.0% | 67.1% |
| **Trained on MTG (tested on all 604 Key clips)** | **64.9%** | **72.2%** |
| Published CNN (Korzeniowski & Widmer 2018) | 67.9% | 74.6% |

Settings were chosen on 200 held-back MTG clips only, so the Key-set score is a fair test.
A hidden layer (8–32 units) did not beat the linear model at this data size.
On JR's own 97 tracks, agreement with Rekordbox was 58% (model) vs 61% (current), within noise.

## Licensing

Not yet shipped in the app. The weights are learned from Beatport audio and from GiantSteps labels
(CC BY-SA 4.0, share-alike). Whether they can ship in a commercial build is a question for the attorney.
