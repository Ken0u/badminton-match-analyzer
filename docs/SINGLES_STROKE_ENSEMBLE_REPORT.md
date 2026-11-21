# Singles stroke-family upgrade — November 18, 2026, local revamp

**Candidate:** `.cache/stroke-sequence-v1/singles_family_ensemble.ts`. A self-contained TorchScript research artifact, not the active application model. SHA-256 `654d3abe534d40f0bf3985d6941426be5635719aad5d23b14d84bc19c7bf4b17`. The win came from averaging three frozen family-logit heads, not from the extra learned sequence layer. The other four outputs come directly from the installed model. No downloads, VM, UI changes or automatic model promotion.

| Paired development validation | Installed | Three-model mean | Trained sequence head |
| --- | ---: | ---: | ---: |
| ShuttleSet known contacts classified correctly | 1696/2019 | **1718/2019** | 1711/2019 |
| ShuttleSet six-family macro F1 | .8361 | **.8459** | .8432 |
| ShuttleSet weak-family macro F1 (drive/lift/push/block/drop) | .7179 | **.7344** | .7264 |
| AICup known contacts classified correctly | 1450/1646 | **1466/1646** | 1465/1646 |
| AICup six-family macro F1 | .8516 | **.8701** | .8655 |

ShuttleSet per-family F1 (installed -> ensemble): drive .5900 -> .6108, push .5870 -> .6107, block .7990 -> .8235, lift .7584 -> .7685, drop .8549 -> .8582. AICup drive .5909 -> .6519. ShuttleSet matched-correct changes by original match: 35 +6, 36 +4, 37 +4, 38 -4, 41 +12. AICup validation is 176 clips from one capture group (Odense), not 176 independent tournaments. These are historical validation sources, not fresh acceptance data. No test clips were scored by this run.

The new recurrent sequence head was fitted for 16 fixed epochs using 15,862 matched family labels across 30 training matches. It sees all three expert score vectors, the predicted hitter's joints, shuttle displacement and neighboring predicted contacts; only family changes. The frozen three-expert comparator beat the trained head overall. Same candidate events for all arms; all results use the same one-to-one timing window. Of 4,241 published ShuttleSet validation rows, 2,118 had usable families and 2,019 were matched. AICup: 1,707 reference contacts; 1,646 matched. These results do not establish full-match player counts, court-cut robustness, or doubles gains.

Reproduction: run `training/train_stroke_sequence.py`, `training/eval_stroke_sequence_transfer.py`, then `training/export_stroke_family_ensemble.py` with the project interpreter. Requires the local feature corpus and three hash-pinned inputs recorded in `protocol.json`; the run's exact trainer snapshot is `trainer.frozen.py` in its artifact folder. The candidate returns `(hit, hitter, family, side, serve)` logits on the existing normalized 30-fps singles input. Load with `torch.jit.load`; do not rename it to `events.pt` (different format). Export smoke checks checked parity at three lengths; on the local RTX 2060 a synthetic 300-frame event forward measured 16.54 ms installed vs 26.60 ms ensemble (median of 12; excludes upstream tracking). Runtime choice remains unchanged.

Next gate: freeze the candidate, select new source-disjoint whole singles matches, count corrected **and introduced** family errors on raw video, compare per-player stroke counts and measure complete processing time. Do not keep optimizing on the five matches above. For doubles a separate candidate and independent reference evaluation are required.

## Replay of the original VM validation benchmark

`training/replay_stroke_family_validation.py` uses the original validation split, feature readers, v2 teacher alignment, deterministic varied clip ends, 0.7 threshold and `train_events.score` at both tolerances. No retraining or held-out test use. Same 176 AICup clips (1,707 reference contacts) and 398 ShuttleSet rallies (4,127 contacts, five matches). Teacher alignment count reproduces: 3,859/4,127. Report: `.cache/stroke-sequence-v1/historical-validation-replay.json`. Checkpoint/scorer hashes, baseline discrepancies, full confusion matrices and paired counts are included.

| Family macro F1, matched contacts | Archived installed | Local installed | Local ensemble |
|---|---:|---:|---:|
| AICup, 2 frames | .85028 | .85054 | .86791 |
| ShuttleSet, 2 frames | .78560 | .78518 | .80068 |
| AICup, 4 frames | .84918 | .84942 | .87010 |
| ShuttleSet, 4 frames | .78390 | .78347 | .79897 |

At two frames AICup: 45 fixed/31 introduced, +14 on 1,503 matched known labels. ShuttleSet: 68 fixed/39 introduced, +29 on 2,036; by match +7,+6,+6,-3,+13. Complete-event F1 improves by about .007 on each corpus. The local replay did not reproduce every archived prediction; the maximum family macro F1 deviation across these four baseline rows is below .00043. Use the local paired comparison for the candidate delta. Match IDs and capture group counts limit generalization; the archived validation settings are not a new sealed test.
