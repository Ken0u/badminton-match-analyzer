# Native evidence context on rally boundary proposals

[Issue #288](https://github.com/Ken0u/badminton-match-analyzer/issues/288)
connects newly generated rally proposals to the existing
[boundary evidence eligibility checks](BOUNDARY_EVIDENCE_EVALUATION_REPORT.md).
The producer previously emitted a boundary timing interval without its wider
candidate evidence range. Evaluation explicitly reported that legacy evidence
as unavailable, so reviewing only a narrow boundary interval could still earn
interval compatibility even when necessary pose observations were unreviewed.
This report distinguishes source evidence from uncertainty about the boundary.

Four generated reproductions on baseline
`8aa35420fdf89e2ec33cd7370e50d926f0bc681a` demonstrate the gap. Removing only
player observations outside the boundary interval removes the corresponding
serve or ending, while evaluation of the original proposal against boundary-only
coverage reports one interval match. No source image or scientific label is
needed to reproduce this behavior.

## Proposal provenance and comparison

New proposals carry paired native `context_start_frame` and
`context_end_frame` fields. This evidence range is **half-open**, unlike the
existing inclusive `start_frame`/`end_frame` boundary uncertainty. It includes
the actual quiet, launch/departure, incoming, fitting, settling and follow-up
windows used by the proposal, earlier observations needed for shuttle speed,
and source-time pose-lag dependencies. The ending range conservatively covers
the bounded follow-up anchor search as well as the evaluated quiet windows.
It stays inside the eligible continuous segment and does not use FPS conversion.

These ranges describe the proposal's direct cached-observation dependencies.
They do not establish accuracy, exact physical contacts, hitter identity,
complete upstream model context, floor contact or an in/out decision. Existing
source/camera/scene/court guards, detection thresholds, numerical evidence,
candidate IDs/count/order, uncertainty bounds/times and track/player hints remain
unchanged. Existing saved artifacts remain byte-identical; legacy missing
candidate evidence remains explicitly unavailable under the existing evaluator.
There is no evaluator, annotation-schema, model or default-policy change.

Generated singles and doubles cases have the same concrete bounds:

| Boundary | Inclusive timing | Half-open evidence | Boundary-only interval matches, before/after | Full-evidence matches after |
| --- | --- | --- | --- | --- |
| Serve | [21,28] | [4,32) | 1 / 0 | 1 |
| Rally ending | [37,40] | [6,71) | 1 / 0 | 1 |

All four original references and their original reviewed-frame denominators
remain. Each unsupported candidate is explicitly excluded for evidence outside
reviewed coverage. Reviewing the full declared evidence permits interval
compatibility again; that compatibility remains distinct from exact timing or
source correctness. Eight generated baseline comparisons across singles/doubles,
constant/variable/high-rate clocks and source offsets preserve all original
fields of 16 proposals after removing the two newly added metadata fields.

## Read-only cached development replay

Before source edits, a read-only SQLite connection froze the original two
development source metadata/calibration contexts, timestamps and four original
player/shuttle artifacts. Only inference-context fields feed proposal generation;
saved events, identity labels and scientific assessment documents are not used.
Original source metadata, annotation-document bytes, catalog, timestamps and
perception artifact hashes remain unchanged after replay. Recorded checkpoint
hashes bind the original small-pose and TrackNetV3 artifacts; no weights are
loaded and no inference is rerun.

| Development input | Preserved proposal | New half-open evidence |
| --- | --- | --- |
| Singles first view | Ending navigation frame 610 | [587,637) |
| Doubles first view | Serve navigation frame 331 | [307,335) |

Both current proposal documents, with the two new fields removed from each
candidate, equal their frozen baseline output in every field. The receipt
records original source/input/checkpoint/code hashes. This is cached development
logic replay, not fresh detector inference, source-image review, scientific label
scoring or an independent accuracy test. Images and model weights are not opened.

## Verification and remaining work

Instrumented generated tests record the windows actually returned during each
accepted proposal and check their source rows, previous-speed and pose-lag
dependencies against emitted bounds. Other checks cover variable and high-rate
clocks, nonzero frame/time offsets, both modes and boundary kinds, camera/clock/
missing/scene barriers, half-open endpoints, input immutability and actual saved
Store/API output. Existing clipped/missing/negative and context regressions remain.

Final local results: **449 focused / 4,423 full Python tests
pass**, with four optional full-suite skips. Ruff lint/format, dependencies,
repository UTF-8/LF/JSON/local links and whitespace checks pass. Executable/test
bytes remain stable throughout final verification and all recorded launcher,
worker and descendant lifetimes are independently terminal. Exact PR/main CI,
controller integration and independently verified complete public delivery are
recorded on the owning issue.

The first focused run is preserved: 441 passed and eight new provenance checks
failed because the initially declared ending context omitted the remaining
follow-up anchor search. The correction widened metadata bounds without changing
proposal acceptance, timing or numerical evidence. A lint-only unused new-test
variable and two formatter changes were corrected before testing. Subsequent
449-test focused verification and the complete earlier native replay are
preserved separately. The original full suite passed 4,362 tests with four optional skips. Final checks
include the nonoverlapping delivered #287 audio repair at
`4cb27902f80d4b51e728bd55faf977667523cdf9`; all owned implementation/test
bytes stayed identical across the normal merge of main.

No new scientific assessment, source image transfer, model inference/training,
dataset acquisition, held-out scoring or model promotion occurs. All 45 public
protocol manifests and original research remain unchanged. Complete scientific
references remain **0/2**, all four eligibility flags false, and #62/#66/#67/#71
remain incomplete. Correct provenance and software checks do not establish
correct automatic annotation throughout a badminton match.
