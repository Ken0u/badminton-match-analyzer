# Observed flight context and validation comparisons

October 18, 2026. Version 0.17.0 adds an experimental feature builder for stroke
learning. It does not install a new contact, family or side model in the app.

October 19 update: the [original all-75-rally frozen comparison](HOLDOUT_RECOVERY_REPORT.md)
is complete after safe interruption recovery and independent recipe review.
All 21,610 native frames / 860 source rows / 677 eligible rows per task remain
preserved. Predeclared R3 achieves eight-group family macro F1 0.475, requested
six-family macro F1 0.465 and strict conditional family/side accuracy 0.421
without confidence abstention. Its unchanged validation thresholds reduce joint
accuracy to 0.143. These are weak-source conditional classifier results, not
complete event or persistent-identity accuracy; no model is promoted. The
preparation history below records the earlier access block, subsequently resolved.

## Feature contract

`badminton.stroke_context.StrokeContext` takes a video, completed native player
and shuttle observations, and current court/camera/scene annotations. Its default
371-value input combines:

- The existing two 126-value arm windows and their two availability masks.
- Nine global flight samples within 0.2 seconds of the navigation frame. These
  retain observed image position, displacement from an actual nearby observed
  anchor, source-time velocity, confidence/component information and masks.
- Six observed actor-size and court-plane foot hints, plus three anchor fields.

The anchor is an observed shuttle point, not an invented contact location.
Missing or repaired points never become coordinates. Court projection uses
confident CV ankles or an explicitly flagged box-foot fallback; it is not a
physical floor measurement or line call. No family, side, event, persistent-player
assignment, source-foot label or published hit/landing point enters a value.

The builder also accepts an explicit ordered flight-offset recipe up to 0.5
seconds on each side. The extended 15-sample recipe has 443 values. It requires
complete requested source-time context, without padding clip edges. The recipe
exports its actual offsets and dimensions.

Same-source hashes, aligned stride-1 observations, unchanged camera corrections
and the current player calibration signature are required. Scene, camera,
timestamp, calibration and transitive shuttle-selection guards cover all body,
flight and velocity dependencies. A single calibration must cover that complete
range. Denser samples can consume history outside the original body window;
a 60 fps regression verifies that this earlier history is included and excluded
scenes there block the input.

Inputs are copied when the builder starts. A regression caught a reference to a
caller's mutable annotation/video dictionary: later edits could otherwise mix a
new court with an old body window. Video, annotations and perception observations
now remain one inference snapshot.

## Controlled studies

Both studies reuse all 134 training/validation clips from the
[completed R2 evaluation](R2_LEARNING_REPORT.md), their frozen weak hitter
associations and navigation frames. Source reference counts remain 624/672.
The first 254 values match R2 exactly for retained rows. Hidden layers, seed,
normalization, training schedule, class weighting, selection objective and
threshold policy are unchanged; the input representation changes.

| Validation measure | R2 body | R3, 0.2-second flight | R4, 0.5-second flight |
| --- | ---: | ---: | ---: |
| Available training / validation rows | 608 / 662 | 608 / 662 | 573 / 633 |
| Family macro F1, eight source groups | 0.556 | 0.590 | 0.547 |
| Side balanced recall | 0.907 | 0.894 | 0.859 |
| Family/side tuple accuracy | 0.579 | 0.574 | 0.555 |
| Selected epoch | 80 | 295 | 220 |

R3 has the largest predeclared average family-F1/side-recall objective. It is
selected for a future independent comparison, while R4 is rejected. R3's family
gain is mixed: side and tuple results fall slightly, net and drive remain weak,
and validation clear support is only three. Its validation thresholds enable
lift, drop and serve; the other source groups lack sufficient accepted evidence.
This does not satisfy automatic six-family recognition.

R4 loses additional inputs to its broader context guards. Those unavailable
references remain in the denominators. Neither study opened new test predictions
or adjusted thresholds against the already known R2 test match. Validation
selection across these trials is not evidence of unseen accuracy.

The [aggregate evidence](../data/manifests/observed_stroke_context_evaluation.json)
pins recipes, models, thresholds and validation class results. Immutable local
runtime snapshots and training sources preserve both experiments. An audit of
all 134 cases verifies that the current default reproduces all 1,270 retained
371-value R3 vectors and their context ranges exactly. Annotations are unchanged.

## Independent source preparation

A new source for the from-scratch heads is the official BWF
[Chen Long / Chou Tien Chen 2019 group match](https://www.youtube.com/watch?v=-aOI9_JxoWc),
identified by the pinned ShuttleSet match table. Public metadata and three short
anchors were fetched without authentication at 1280x720, 25 fps. Source-only
inspection supports the weak clock/court/foot-coordinate convention at those
anchors, including the change of ends. Exact contact times and full mechanics
remain unadjudicated.

The source has a red court. The existing green-only research preflight cannot
be silently reused. The middle anchor also changes from a service close-up to
the wide court at local frame 24; native source frames 23/24 verify that cut.
The close-up remains unknown with unsupported court geometry. Its service
reference must not be replaced by a later return to make a feature available.
The [source review](../data/manifests/new_singles_source_review.json) was frozen
before native perception or head results on this source.

The fixed head-evaluation scope includes **all 75 published rallies**, 21,610
requested source frames and 860 source rows, including imperfect-label cases.
Only 677 have eligible family/side labels; other labels remain unavailable truth.
The original normalized labels, inherited split and training-ready status stay
unchanged. This source was excluded from the from-scratch S2Doubles heads; older
unrelated ShuttleSet-trained classifiers are not an unseen baseline here, and
upstream perception pretraining overlap is not established.

The subsequent full-scope fetch encountered YouTube's sign-in requirement and
stopped before downloading additional clips. No authentication or gate bypass
was attempted. The three downloaded anchors are preserved for unscored native
input checks; they did not replace the declared 75-rally head evaluation. At that
stage evaluation was pending access to the remaining media. Public access later
recovered all original clips, and the unchanged frozen comparison is now complete
in the [recovery report](HOLDOUT_RECOVERY_REPORT.md). Test-informed changes require
another complete-source holdout.

Those input checks completed on 939 actual CUDA source frames. Both stages
detect the reviewed cut at 24; tracker IDs 1/2/10 before it are disjoint from
11/12 afterward. Court validity and shuttle-selection history reset there.
There are 252 sampled finite 371-value feature packs, with main annotations
unchanged. At that input-check stage no family/side head predictions were opened. Reported visibility
counts and valid feature arrays do not establish localization or shot accuracy.

## Validation and next work

The standard suite covers 538 passing tests with four unchanged optional GPU
skips: the full run passed 537, then the added snapshot-mutation regression and
all 40 contact-feature/context tests passed. Ruff and formatting pass. New
checks cover source/court/camera staleness, missing/repaired points, true PTS
velocity, complete lineage, court-foot masks, label isolation, configurable
context and input immutability. No new learned labels are saved in the main app.

Next: broaden trustworthy raw-video training support for sparse/confused
families, make the supported training/inference recipe portable, complete the
fixed independent-source evaluation when its media is available, and continue
automatic court/scene/identity and resumable whole-match processing. The full
automatic annotation objective remains unverified and unfinished.

Local evidence includes `.cache/stroke-context-{learning,model}-r{3,4}/`,
`.cache/stroke-context-v2-parity.json`, `.cache/new-singles-holdout-protocol.json`,
`.cache/new-singles-source-review/` and `.cache/new-singles-input-checks/`.
