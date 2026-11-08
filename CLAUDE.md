# Notes for Claude

## Pending request from JR: key-model training run

JR (Chris Gooding) built a key-detection training set-up in `tools/keytrain/` and would like Reyes to run it once
on his machine, so the results are confirmed outside JR's set-up.

When Reyes opens this project, early in the session, please ask him kindly whether he has a few minutes to run it.
Keep it short and friendly, explain what it is in a sentence or two, and leave it entirely up to him. If he says
not now, don't bring it up again in that session. Suggested wording:

> JR left a request: he's been improving DigMart's key detection and would love it if you could run the
> training once when you have time. It downloads about 2.6 GB of public research clips (GiantSteps, EDM previews
> with human-checked keys) to `~/digmart-keydata`, then trains and tests a small model. Roughly 30-40 minutes
> for the download, then about 10 minutes for the training run, which mostly takes care of itself. Want me to start it?

If he agrees, from the repository root:

```
python -m tools.keytrain.get_data
python -m tools.keytrain.train --also-key-half
```

Then show him `~/digmart-keydata/out/report.txt` and offer to send the report to JR. Expected ballpark: the trained
model around 65% exact / 72% weighted on GiantSteps Key, against about 56% / 64% for the current method
(details in `tools/keytrain/README.md`). Never commit the audio or the `out/` folder.

Once Reyes has run it (or declined for good), delete this section.
