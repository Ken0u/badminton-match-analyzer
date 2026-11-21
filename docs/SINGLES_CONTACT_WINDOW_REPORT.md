# Singles contact-window expert v1 (local development)

Train with `training/train_stroke_window.py` and the project interpreter. Frozen comparison is the three-model ensemble, not the original single checkpoint; the application has not been changed. Candidate = 65% baseline family logits + 35% new expert logits at predicted calibrated contacts. Otherwise fall back to the baseline. The new weights alone are not the full candidate. Protocol, input hashes, weights, and full paired report are under `.cache/stroke-window-v1/`. Baseline and scorer hashes are in `protocol.json`; weight SHA-256 `565c3659d614d213b792c8d9abfcbaf66c06ecf2b74dcfdd8e2b71c013eb82cf`. The feature manifest covers training and validation files only.

## Training and evaluation

Fit a new temporal convolutional model from scratch on 4,677 AICup and 15,862 ShuttleSet matched labeled training contacts; 32 epochs, one seed, partial-label loss, end-of-training weight averaging. Input is a time-normalized 40-sample observed flight/pose window around a predicted contact; features use the predicted hitter, calibrated frames and same camera segment. The model does not see a manual contact, an identity label, or a prior human stroke label at inference. No 3D fit or raw pixels used. The baseline detector and the hitter/side/serve heads stayed frozen. Each historical baseline result reproduced exactly in this run. Both the blend weight and the decision rule were recorded before validation scoring. No final test split, full-match count benchmark or doubles evaluation.

| Corpus / tolerance | Baseline family macro F1 | Candidate family macro F1 | Net correctly labeled gain |
|---|---:|---:|---:|
| AICup ±2 | .86791 | .87047 | +7 / 1,503 |
| ShuttleSet ±2 | .80068 | .80275 | +4 / 2,036 |
| AICup ±4 | .87010 | .87149 | +7 / 1,651 |
| ShuttleSet ±4 | .79897 | .80032 | +3 / 2,062 |

At ±2 frames, 41 labels fixed and 30 formerly correct labels broken. ShuttleSet match-level net: +3, +1, -1, +1, 0. Clear and smash regressed on AICup; drive, push, block and drop regressed slightly on ShuttleSet. Lift improved in both. The predeclared development gate passed, but the aggregate advantage is small and not consistent across weak strokes. Preserve both candidates; keep the ensemble as the practical baseline pending fresh whole-match evidence. Preferred next research direction: test a short hitter/racket RGB crop that adds visual information absent from pose and shuttle tracks, not additional tuning of this blend on the same validation clips.
