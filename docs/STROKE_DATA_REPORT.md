# Stroke-label import and recognition evaluation

October 17, 2026. This increment prepares reproducible labels and measurements for
training the missing stroke-side head and validating family recognition. It does
not train a new model, certify imported video alignment, or establish full-match
accuracy. Real app annotations remain unchanged at pilot revision 2.

The subsequent [side-head baseline](STROKE_SIDE_REPORT.md) trains from the original
publishers' separately pinned feature archive. It does not change this raw-video
alignment gate or convert unverified source frames into application annotations.

## Source and interpretation

The source is the authors' [ShuttleSet repository](https://github.com/wywyWang/CoachAI-Projects/tree/45517f7d4cb936b03f3eabf939cc7959d39226fe/ShuttleSet),
commit `45517f7d4cb936b03f3eabf939cc7959d39226fe`. The packaged
`shuttleset_manifest.json` pins Git blob hashes for 107 source label/metadata files
and two interpretation references. The fetcher verifies downloaded bytes against
those immutable hashes; the importer rechecks every file it uses. Raw labels,
reference code, and derived indexes remain local and outside Git. They are never
executed or imported as application annotations.

The original authors' [cleaner](https://github.com/wywyWang/CoachAI-Projects/blob/45517f7d4cb936b03f3eabf939cc7959d39226fe/Stroke%20Forecasting/badmintoncleaner.py#L112)
explicitly fills blank backhand flags with zero. The adapter follows that source
convention: true becomes backhand, false/blank becomes forehand. Around-the-head
forehands remain forehand; a record with both flags true is excluded. Original
flag strings and all other CSV fields are retained for audit.

Source types use the six-family mapping described in the recognition report,
plus `other`, `unknown`, and serves. The additional original `driven flight` type
maps to drive. Non-target wrist-smash records remain `other`; half smash is not
an output family. These project mappings still require annotation-guide
adjudication before a final benchmark.

The published [BST issue list](https://github.com/Va6lue/BST-Badminton-Stroke-type-Transformer/blob/c93acfa736ed784ba7bea4ec9d360001dea9b728/ShuttleSet/flaw_shot_records.csv)
identifies erroneous labels/times, duplicate records, non-court views, and whole
unusable matches. We exclude affected original rallies without silently applying
revised labels. Native flaw flags also exclude the complete affected rally,
following the authors' cleaner. Invalid fields, conflicting side flags, repeated
or reversed frames, and broken stroke order stay in the index with reasons and
are excluded from usable labels.

## Frozen match splits and imported evidence

The [published BST split](https://github.com/Va6lue/BST-Badminton-Stroke-type-Transformer/blob/c93acfa736ed784ba7bea4ec9d360001dea9b728/ShuttleSet/gen_my_dataset.py#L222)
assigns complete original matches to train, validation, and test. Matches
9/10/12/27 are quarantined according to the published problems. Duplicate source
video URLs or split overlap fail validation. The importer preserves original
winner/loser identity metadata; it does not infer identity from current court end.

| Split | Matches | Raw rows |
| --- | --- | --- |
| Train | 30 | 25,748 |
| Validation | 5 | 4,241 |
| Test | 5 | 3,499 |
| Quarantine | 4 | 2,996 |
| Total | 44 | 36,484 |

This pinned snapshot contains 104 sets and 3,683 distinct match/set/rally keys.
The [paper](https://arxiv.org/abs/2306.04948) reports 36,492 strokes and 3,685 rallies;
we report the actual snapshot counts rather than adding records to match the
publication. All 36,484 source rows are retained.

The current conservative checks leave **21,709 label-eligible records**:

| Mapped label | Eligible rows |
| --- | --- |
| Clear | 1,685 |
| Lift | 3,471 |
| Net | 4,860 |
| Drop | 1,285 |
| Smash | 1,609 |
| Drive | 1,073 |
| Other | 5,594 |
| Serve | 2,132 |

Eligible side labels comprise 12,779 forehands and 8,930 backhands under the
source convention. These are label-index counts, not verified model accuracy or
independently adjudicated annotation quality. Exclusion counts can overlap;
`docs/shuttleset-import-summary.json` records the exact source/index hashes and
statistics. A repeat import produces identical index bytes.

## Timing and media gate

Frame numbers and coarse recorded times are preserved separately. The importer
does not choose an application timestamp or copy a frame number into the app.
The paper describes a 30-fps preparation setting, while the current source labels
provide mixed timing evidence. Comparing frame/FPS to the recorded second gives
19 match candidates at 25 fps, 24 at 30 fps, and one at 29.97 fps. These are
diagnostics, not verified source frame rates.

For example, match 1's first set has 542 rows. All agree with the recorded second
at 25 fps; none agree at 30 fps. Applying 30 fps would shift those labels by
roughly 76–298 seconds over that set. The importer therefore reports **zero
training-ready records** until actual source footage is linked and verified.
Frame-number origin, changed uploads, source offsets, and variable timestamps
remain alignment concerns even if an FPS candidate fits.

The `server == 3` terminal-stroke marker is retained as metadata. It is not
converted into a rally-end event: the final racket contact does not establish
the observable end of play.

## Recognition measurements

`POST /api/videos/<id>/evaluate` accepts `recognition_run_id`; the CLI supports
`evaluate --recognition-run <id>`. When a matching recognition run is loaded,
**Measure saved labels** includes its report in the browser and JSON download.

The evaluator uses the same fully covered, exhaustive live-review windows and
one-to-one source-time matching as contact evaluation. It reports per-class
precision/recall/F1 and confusion counts, answered-label coverage, an average over
supported requested families, stroke-side balanced accuracy where both sides
have support, hitter results, and strict complete-event metrics. The six-family
macro score stays null unless all six requested families have label support.
Unknown truth is excluded; abstentions and absent outputs count as unanswered.
Unmatched emitted labels count as false positives.

Events with classification provenance are excluded from recognition accuracy,
including corrected model drafts. This prevents accepting a suggestion and then
counting agreement with it as independent evidence. Such contacts still take
part in matching so missing independent class truth does not create a false
positive. Family, side, and hitter all need known independent truth for strict
complete-event scoring; unresolved prediction timing cannot earn an exact match.

These results are conditional on supplied contacts and reviewed tracker-to-player
mappings. Ground-truth contact inputs cannot establish automatic contact
detection, and human identity mappings cannot establish automatic identity
recovery. Input/current annotation revisions and model/run hashes stay in the
downloaded report. A full-video release still needs an entirely predicted path
evaluated on independent, unseen full matches.

The actual singles pilot export is `docs/pilot-recognition-evaluation.json`.
It has **zero known family labels**, so family accuracy and the six-family macro
score are unavailable. It does not convert the six model suggestions into truth.
The real pilot remains unchanged. Browser tests use deliberately artificial
isolated labels solely to verify rendering, counts, and assisted-label exclusion.

## Reproduce and continue

```powershell
.\.venv\Scripts\python.exe scripts/fetch_shuttleset.py
.\.venv\Scripts\python.exe -m badminton.cli import-shuttleset data/datasets/shuttleset/source --output data/datasets/shuttleset/v1
.\.venv\Scripts\python.exe -m badminton.cli evaluate 970dbd8adfe548d8 --recognition-run 69bf12fd32c74b359b9cb4bfcf6866d7 --output .cache/recognition-evaluation.json
```

Next, obtain a permitted subset of the original train/validation footage, verify
several independently inspected contact anchors across each source, and record
its hash/timestamp mapping and coordinate scaling. Extract cached pose/shuttle
clips only after that alignment passes, then train and validate the stroke-side
head and compare family-head adaptation. Keep published test matches frozen and
acquire additional unseen matches for final product evaluation. Continue complete
local rally labeling, missed-contact work, rally boundaries, and the four-player
doubles extension.
