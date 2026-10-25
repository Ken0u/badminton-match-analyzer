# Native source clocks in saved contact and recognition evaluation

[Issue #264](https://github.com/Ken0u/badminton-match-analyzer/issues/264)
repairs disagreement between a proposal's native frame and its declared source
time. Matching source hashes alone do not establish that those fields agree.

## Generated reproduction

On source `7939da84c308c5696c6e4df438edeeff2f0d9b20`, a registered contact
proposal at frame 5 (native time 0.2 seconds) can declare time 0.6 seconds and
match a reviewed contact at frame 15. Both the API and CLI return contact F1 1.0.
A recognition proposal with the same inconsistent timing receives drive-family
F1 1.0. Correct frame/time controls also pass. All four generated cases preserve
saved annotation and artifact bytes. No match footage, scientific labels or
model inference is used in this reproduction.

The defect arises because matching uses declared source times after frame-based
coverage checks, without comparing those times to the registered source clock.
A proposal can therefore receive timing and classification credit for a frame
far outside the requested temporal tolerance.

## Validation and compatibility

Contact and recognition evaluators accept optional keyword-only
`native_timestamps`, retaining their positional timing-tolerance argument.
When supplied, the clock must cover every native source frame with finite,
nonnegative, strictly increasing numeric times; booleans are invalid.
Reviewed/corrected contact times and every proposal representative time must
agree with their native frame. Supplied inclusive interval endpoint times must
agree with their corresponding native bounds. A fixed 20 microsecond allowance
accommodates timestamp serialization, matching the existing rally evaluator's
allowance. Frame rate is not used to reconstruct time.

Validation precedes scoring and includes candidates outside eligible review
coverage and requests without labels. Inconsistent inputs raise an actionable
validation error. Missing optional interval-time metadata remains supported;
neither missing values nor inconsistent values are written into artifacts.

The API and CLI supply the registered timestamp map for contact and recognition
evaluation. A missing, malformed or inconsistent map cannot silently downgrade
validation. Invalid requests return HTTP 422 or a CLI error without producing a
new report or overwriting an existing report. Recognition applies the clock
check before contact matching and classification credit. Combined evaluation
requests remain supported; shuttle and rally comparisons keep their contracts.

Reports expose `prediction_clock_status`: `validated` when the supplied native
clock and contact times pass checks, and `unavailable` for compatible direct
library calls that omit a clock. Unavailable does not mean verified. A verified
declared frame/time correspondence is not independent integrity or physical
accuracy of the underlying prediction.

Valid nearby proposals still use the requested source-time tolerance. Native
variable frame timing, inclusive uncertainty, camera boundaries, scene masks,
review gaps, unknown/assisted classification labels, abstentions and missing
prediction denominators retain their existing meanings. This repair does not
rescore real scientific results or change saved annotations, model outputs,
inference, defaults, dependencies or research acceptance.

## Verification and limits

Generated pure tests and registered API/CLI cases cover valid constant/variable
clocks, representative/interval inconsistencies, missing/invalid clocks,
no-label and excluded predictions, serialization tolerance, compatibility
status, unchanged inputs and rejected-report preservation. Existing contact,
source-hash, camera, recognition and rally evaluation checks remain required.
All **647 focused checks** and **3,831 full Python tests** pass, with four
optional skips. Ruff lint/format, dependency consistency, repository
UTF-8/LF/JSON/local links and whitespace checks pass. Executable/test bytes
remained unchanged during both verification runs; recorded process lifetimes
were checked after exit. The core subtask's first attempt encountered a missing
generated temporary-directory parent before one fixture setup; that directory
was created without changing the existing test. Its initial lint failure and
auxiliary shell inspection errors remain recorded. The final combined focused
and full verification runs pass on their first attempts.
Exact PR/main CI and public delivery receipts belong on the owning issue after
controller integration.

Complete scientific references remain **0/2**, with all four eligibility flags
false. Software provenance checks do not establish correct automatic badminton
annotations throughout an unseen match.
