# Fixed development shuttle-component threshold comparison

Owning task: [#204](https://github.com/Ken0u/badminton-match-analyzer/issues/204),
under [localization roadmap #65](https://github.com/Ken0u/badminton-match-analyzer/issues/65).
This is one prospectively fixed offline development hypothesis. The application
and its default 0.5 threshold remain unchanged. Full automatic badminton
annotation accuracy remains unproven.

## Hypothesis and frozen scope

The [existing heatmap diagnostic](SHUTTLE_HEATMAP_REPORT.md) exposes weak responses
at some missed visible shuttle locations. Its published development summaries
motivate exactly one alternative: the existing largest thresholded component
extractor at 0.25, compared with the same stateless extractor at 0.5. The
[new protocol](../data/manifests/shuttle_threshold_protocol_v1.json) fixes this
choice before alternate predictions. There is no threshold sweep, cutoff
optimization, relabeling, model training, new inference or default promotion.

Both paired extractors use strictly greater-than masks, 8-connectivity, the
bounding-box center in source display coordinates and the first-largest tie
rule. These stateless center predictions are distinct from the original
application's motion-selected observations, which are reported separately.
Sixty center heatmaps cannot measure complete trajectories or event accuracy.

Inputs are the original sealed 60 heatmaps from 50 complete camera views with
13,499 native output rows. The unindexed partial array from the historical
interruption remains preserved and uninterpreted. All 25 localizable visible,
7 confirmed-not-visible and 28 unknown cases remain; visible-unlocalizable
support is zero. These familiar agent source assessments are development
references, not expert truth or an independent holdout. All seven negatives
are non-play, and occlusion/camera-transition support is absent.

The component reconstruction gate verifies every original heatmap against its
0.5 component identities/order, boxes, areas, coordinates and confidence, with
only the original absolute confidence tolerance 0.00001. Native ordinal, PTS,
source geometry, camera membership, complete-view seals and the original
successful control report remain bound. No alternative prediction is made
until every control passes. Missing or incompatible inputs retain all cases
as unavailable and prevent comparable scoring.

The primary localization disk remains 0.005 times the source display diagonal.
The original assessment uncertainty radius is a separate sensitivity measure.
Selected localization and any observed component agreement remain separate.
Unknowns never become negatives; unavailable visible outputs remain misses in
the original denominator. Group reports retain source, visibility, difficulty,
uniform/known-gap selection and assessor disagreement, including empty groups.

The fixed candidate advances only to a separately granted broader temporal
experiment if it strictly improves primary visible localization without adding
false observations or displaced visible outputs, with complete compatible
support. Every other compatible outcome rejects this candidate. Neither outcome
authorizes model/default promotion or an independent accuracy claim.

## Execution and current result

Prospective code and input freezing, the actual admitted comparison, separate
post-exit interpretation, required full checks and controller integration/delivery
are pending at this initial pre-execution revision. Results will be recorded
without changing the frozen scientific code or protocol.

## Reproduction and verification

A clone supplies code and the public protocol, not the ignored original
capture, labels or baseline. Obtain a genuine task/data reservation and use the
existing environment. Before Python imports, pin `BADMINTON_ROOT` to the
original input root, `BADMINTON_DATA_DIR` to its real `data/processed` Store and
`BADMINTON_WEIGHTS_DIR` to the original `models/weights`. Clear account credential
variables; credentials are not inputs. No media decoding or weights loading
occurs. Both actual comparison and interpretation use `run_local_job` admission.

`python scripts/compare_shuttle_threshold.py freeze --root ROOT --output NEW_OUTPUT --capture ORIGINAL_CAPTURE --control-report ORIGINAL_CONTROL_REPORT`
verifies the pinned original envelopes and seals the new protocol, recursive
consumer bytes, runtime and complete input graph. Timestamp its returned
experiment SHA256 before running
`python scripts/compare_shuttle_threshold.py run --root ROOT --output NEW_OUTPUT --experiment-sha256 EXPERIMENT_SHA256`.

Before interpreting, independently observe that the recorded comparison
process lifetime has exited and its Store job is completed, then externally
seal the raw output and terminal. Run
`python scripts/compare_shuttle_threshold.py interpret --root ROOT --output NEW_OUTPUT --experiment-sha256 EXPERIMENT_SHA256 --terminal TERMINAL --terminal-sha256 TERMINAL_SHA256`.
The interpreter rechecks the original PID/creation identity, exact Store owner,
completed job/result binding, context, input and output seals. A timeout or
missing observation handle never establishes exit. Each context admits only
one attempt; interrupted attempts remain preserved for audited recovery and
cannot be silently rerun. The comparison budget is 300 seconds; the owning
task additionally caps all new outputs at 128 MiB and runtime at three hours.

Twenty-eight focused generated tests pass before scientific execution. They
cover strict thresholds/connectivity/ties, complete source and control gates,
invalid/truncated/nonfinite arrays, context tampering, retained unknown and
unavailable support, actual Store admission, a live-lifetime refusal, exclusive
attempts and seven actual exited generated workers with matching or invalid
terminal/Store/input/output proof. These tests establish software behavior,
not badminton accuracy. Raw arrays, labels, candidate point records and detailed
process/Store evidence remain ignored; only protocol, code and aggregate
results are published. No consumed holdout #63 inputs, protocols, predictions,
private membership or artifacts are used.
