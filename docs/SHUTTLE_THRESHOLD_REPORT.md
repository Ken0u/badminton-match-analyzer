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

Completed October 23, 2026: **reject the fixed 0.25 candidate**. It localizes
17/25 known visible references instead of 14/25, but adds one displaced visible
output and one false observation. This fails the predeclared disposition rule;
the application remains at 0.5. No second cutoff or replacement model is tried.

| Outcome | Stateless 0.5 control | Fixed 0.25 candidate | Original motion-selected application output |
| --- | ---: | ---: | ---: |
| Localized / visible support | 14/25 | 17/25 | 14/25 |
| Displaced / visible support | 1/25 | 2/25 | 1/25 |
| Missing / visible support | 10/25 | 6/25 | 10/25 |
| Any observed component agrees / visible support | 14/25 | 17/25 | 14/25 |
| Selected point within original uncertainty radius / visible support | 14/25 | 17/25 | 14/25 |
| False observations / confirmed negative support | 3/7 | 4/7 | 3/7 |
| Absence / confirmed negative support | 4/7 | 3/7 | 4/7 |
| Observed, unscored / unknown support | 11/28 | 19/28 | 11/28 |
| Absent, unscored / unknown support | 17/28 | 9/28 | 17/28 |
| Available / all cases | 60/60 | 60/60 | 60/60 |
| Unavailable / all cases | 0/60 | 0/60 | 0/60 |
| Observed components / all cases | 32 | 53 | 32 |

All 14 previously localized cases stay localized. Of ten missing cases, three
become localized, one becomes displaced and six remain missing; the original
displaced case stays displaced. The eight remaining candidate localization
failures have no agreeing observed component. Lowering this threshold recovers
some weak responses but does not solve the component-recall/distractor problem.
Equal aggregate control/application counts here do not establish general
equivalence between stateless extraction and temporal selection. Original
uncertainty sensitivity and primary localization are separate measures despite
their equal counts in this cohort.

All original groups remain below. V/N/U means localizable visible, confirmed
not-visible and unknown. Visible-unlocalizable support is zero throughout.
Difficulty groups overlap. Every case in every nonempty group is available;
unavailable support is zero. Empty groups remain explicit with undefined
localization/negative rates. Component totals include unscored unknown cases;
they are neither localization scores nor inferred physical shuttle counts.

| Group | Cases | V/N/U | Localized control | Localized candidate | False observations control/candidate | Components control/candidate |
| --- | ---: | --- | --- | --- | --- | --- |
| all | 60 | 25/7/28 | 14/25 | 17/25 | 3/7; 4/7 | 32/53 |
| difficulty:blur | 28 | 14/0/14 | 8/14 | 8/14 | undefined (0 support) | 15/28 |
| difficulty:camera_transition | 0 | 0/0/0 | undefined (0 support) | undefined (0 support) | undefined (0 support) | 0/0 |
| difficulty:distractor | 29 | 9/0/20 | 4/9 | 6/9 | undefined (0 support) | 15/27 |
| difficulty:fast_flight | 7 | 7/0/0 | 5/7 | 5/7 | undefined (0 support) | 6/7 |
| difficulty:non_play | 14 | 4/7/3 | 2/4 | 2/4 | 3/7; 4/7 | 8/11 |
| difficulty:occlusion | 0 | 0/0/0 | undefined (0 support) | undefined (0 support) | undefined (0 support) | 0/0 |
| difficulty:ordinary | 1 | 1/0/0 | 0/1 | 1/1 | undefined (0 support) | 0/1 |
| difficulty:small_far | 18 | 10/0/8 | 8/10 | 10/10 | undefined (0 support) | 13/17 |
| difficulty:unresolved | 28 | 0/0/28 | undefined (0 support) | undefined (0 support) | undefined (0 support) | 13/23 |
| disagreement:false | 20 | 5/7/8 | 4/5 | 4/5 | 3/7; 4/7 | 11/17 |
| disagreement:true | 40 | 20/0/20 | 10/20 | 13/20 | undefined (0 support) | 21/36 |
| selection:known_gap | 10 | 4/0/6 | 2/4 | 4/4 | undefined (0 support) | 2/12 |
| selection:uniform | 50 | 21/7/22 | 12/21 | 13/21 | 3/7; 4/7 | 30/41 |
| source:singles | 35 | 18/3/14 | 10/18 | 12/18 | 2/3; 2/3 | 19/36 |
| source:doubles | 25 | 7/4/14 | 4/7 | 5/7 | 1/4; 2/4 | 13/17 |
| state:not_visible | 7 | 0/7/0 | undefined (0 support) | undefined (0 support) | 3/7; 4/7 | 4/7 |
| state:unknown | 28 | 0/0/28 | undefined (0 support) | undefined (0 support) | undefined (0 support) | 13/23 |
| state:visible | 25 | 25/0/0 | 14/25 | 17/25 | undefined (0 support) | 15/23 |
| state:visible_unlocalizable | 0 | 0/0/0 | undefined (0 support) | undefined (0 support) | undefined (0 support) | 0/0 |

The uniform subset improves from 12/21 to 13/21 localized visible references;
the development known-gap subset improves from 2/4 to 4/4. Those subsets are not
interchangeable evaluation populations. The latter also changes all six unknown
cases from absent to observed without establishing their truth. The full
cohort remains the decision denominator.

## Execution and provenance

Executed scientific source is `6b7a796d084034bf06bd1f77de022985bba29444`, on
granted base `5cd85946483ffe39dc238051bc06e26a9d1b264d`. All 66 recursive
consumer files match committed Git bytes; final result edits affect this
report only. The [pre-run checkpoint](https://github.com/Ken0u/badminton-match-analyzer/issues/204#issuecomment-6357023933)
timestamps code, protocol and experiment before any alternate prediction.

The real shared Store admitted the single CPU comparison. It took 2.047 seconds,
including control reconstruction, source revalidation and output publication;
this excludes process startup and preceding input freezing. No media decode,
GPU inference or weights loading occurs. All 60 controls pass. Independent
original-host observation proves the recorded comparison lifetime absent and
its matching Store registration completed. The [raw-output commitment](https://github.com/Ken0u/badminton-match-analyzer/issues/204#issuecomment-6357041368)
precedes the sole fixed interpretation. That separate interpreter also exits
successfully, with its own completed shared Store registration independently
verified. A successful diagnostic job does not mean a successful candidate.

| Binding | SHA256 |
| --- | --- |
| Fixed new protocol | `b9b749920189f49cc584f3111dfb6e38038e454d6785b69db2d408fccdd32b61` |
| Frozen new experiment | `5ea1e32151c7417345cc9760ed9a68690360572077d7d828675ea5c6acd6c1ec` |
| Complete raw comparison | `e197e28ce15938fb0b989ede305eb658c630ff8007862bd89223b1677782837e` |
| Completed comparison terminal | `f693e6b67b5aacf5a7677804696faf08409488a56e6f7323e32ea104fed58225` |
| Fixed interpreted report | `852bb4b49a12f08007a7c6775fb5b98fb1e5af3a9c3f973036c28a8deb432aae` |

The corrected full local suite passes 2,108 tests with four optional skips,
Ruff/format (188 files), dependency and scoped documentation/whitespace checks.
The existing Starlette/httpx deprecation warning remains. The first full local
runner lacked the existing FFmpeg tool path and reported 1,950 passes / 162
skips; its evidence is retained separately and does not support the final
coverage claim. No source code changed between those runs. Final exact-head CI,
controller integration, exact-main CI and full public package/both-image
delivery remain pending at this report revision; completion receipts belong
on the owning issue and PR.

## Remaining accuracy work

This rejection closes neither parent #65 nor the full application goal. Do not
install the candidate or turn unknown cases into negative supervision. Next
improve true-component recall and distractor separation using source-aligned
development supervision after resolving its permissions, original-match overlap
and eligibility; evaluate automatic scene context separately. Broader temporal
and unseen-source evaluation, reliable contacts/serves/endings, persistent
identity, all six family/side combinations and doubles remain required. No
model is trained or promoted here, and all four research eligibility flags
remain false.


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
