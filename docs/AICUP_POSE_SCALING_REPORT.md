# Broader weak pose training with a fixed validation set

Task [#398](https://github.com/Ken0u/badminton-match-analyzer/issues/398) prepares
the first actual API dispatch of the unchanged operation frozen under
[#397](https://github.com/Ken0u/badminton-match-analyzer/issues/397), testing
whether broader existing training supervision improves the static pose
classifier from the [completed learning comparison](AICUP_POSE_LEARNING_REPORT.md).
Its frozen specification is
`6a4c4140d9d9762227d9d203b7e379ecaf304658526f86b069c8d68012aceb67`.
The private development operation started and failed during the fifth new
clip's pose pass after a free-RAM guard fired. Four new clips completed;
no classifier fit or validation comparison ran. The operation and corrective
invocation are consumed; partial evidence is preserved and must not be restarted.
Scientific completion and improved accuracy remain unestablished.
It inherits tested preparation from superseded, unexecuted
[#394](https://github.com/Ken0u/badminton-match-analyzer/issues/394), whose
original deadline and evidence remain preserved. #397 explicitly provided a
costed sixteen-hour task window and one twelve-hour operation; its failed CLI
attempt did not perform science. The recovery preserves #397's
original scientific deadline and adds no scientific runtime.

The preceding experiment selected static over temporal pose: validation
eight-group family macro F1 was 0.415854 versus 0.398081, and strict joint
family/side correctness was 143/353 versus 131/353. Those results remain
preserved. The original preparation, actor audit and two learning fits are
consumed operations, not work to repeat.

## Fixed cohort and control

Only the existing pinned AI CUP archive, original clip index, capture groups
and native-clock ledger are inputs. Original CSV bytes and the reviewed
normalizer determine ordered targets and weak hitter/defender coordinates;
a normalized cache cannot redefine them. Held-out/test members and unlabelled
clips are excluded before opening their CSV or media members. The source folds
and the original validation membership remain unchanged.

| Cohort | Clips | Native frames | Published references | New perception |
| --- | ---: | ---: | ---: | --- |
| Original training inputs reused | 22 | 13,487 | 431 | None |
| Additional training inputs | 402 | 141,197 | 4,253 | One small-pose CUDA pass per clip |
| Expanded training total | 424 | 154,684 | 4,684 | Additional clips only |
| Original validation reused | 23 | 10,786 | 353 | None |
| Final development cohort | 447 | 165,470 | 5,037 | 402 additional clips only |

The added compressed media total is 825,568,691 bytes. All 784 original feature
rows are reused from their sealed outputs, including unavailable inputs and
censored H0 rows. Original native caches are never decoded or regenerated.
The control is the already selected #391 static model, statistics, features
and predictions on the same 353 validation rows. It is neither refitted nor
reselected. Historical producer dependencies are checked against their retained
original revisions and artifact inventories; adding a new consumer does not
retroactively change an old inventory.

The author's source declares CC BY 4.0. Original media and deployment rights,
original-match independence, upstream pretraining, actual hitters and live-scene
truth remain unresolved. Capture groups are not independently verified match
identities. These are private weak-supervision inputs, not verified training
eligibility or application truth. Unknown targets and unavailable inputs remain
distinct, with every original reference retained in reporting.

## Unchanged features and one fit

Each new reference uses the unchanged
[weak correspondence rules](AICUP_ACTOR_CORRESPONDENCE_REPORT.md) independently
at both inclusive contact endpoints `[H-1,H]`. Confident observed ankles and
box-bottom representations must agree on the same distinct hitter/defender
tracks, in a valid camera/calibration context. Minimum confidence is 0.25,
maximum distance is 0.5 of the candidate's box height, and the minimum margin
is 0.25. Missing observations, ties, conflicting pairs and H0 censoring remain
unresolved; gates are not tuned to increase coverage.

The static representation remains 108 values: contact-center shoulders,
elbows and wrists for provisional hitter then defender, repeated center pose,
and zero velocity. Coordinates use observed box height and center/bottom;
missing coordinates and confidence retain zero values with explicit masks.
Source coordinates select weak associations but are not classifier features.
There is no new temporal representation, interpolation, identity repair or
scene-label inference.

Exactly one new CPU fit uses the weakly paired expanded training rows and the
unchanged 108-to-64-to-32 network with eight family groups and two sides
(9,386 parameters). Its recipe is seed 20261104, two CPU threads, 300 epochs,
batch 64, ReLU, dropout 0.1 and AdamW with learning rate 0.001 and weight decay
0.01. Family/side loss weights remain 1/0.5. Mean, standard deviation with a
0.05 floor, clipping at 10 and inverse-square-root supported-class weights use
training inputs only. Unsupported classes cannot be predicted as known.

All 60 selection checkpoints are retained, one every five epochs. Selection
uses the original mean of supported eight-group family macro F1 and side
balanced recall, then strict joint correctness, then earlier epoch. Unknowns
are not negatives and unavailable rows are not removed from validation.
There is no extra fit, seed/threshold search, augmentation, test access or
post-result protocol change. A mixed or negative result remains reported.

## Native preparation and bounded execution

The runner design combines exact native PTS observation and the unchanged
incremental camera detector in the first decode pass. A second pass retains
losslessly compressed native arrays for one clip, supplying pixel-identical
display frames to the
unchanged automatic-court and dual-tracker small-pose recipe. This avoids
extra camera/court decoding while preserving stride 1, source orientation,
native frame identity, camera boundaries and calibration expiry. Generated
tests cover parity, exact decoder accounting and adapter restoration
on success and failure before this design is used on real inputs. The inherited
compressed-cache implementation passed all 129 scaling controls and the full
6,308-test suite, with four optional skips, plus required tooling and clean
package/HTTP checks. Fresh verification of this task's bound changes remains
required before the original operation.

New decoding is bounded to 282,394 frame visits and new model observations to
141,197 frames. There is no new pass on the original 45 clips, shuttle
inference, model acquisition, CPU fallback or repeated failed pass. Initialize
torchvision before threaded PyAV and retain native FFmpeg logging restoration
before media opening and closing.

A fresh committed task grant permits at most 16 hours from its grant timestamp.
The single original scientific operation has at most twelve hours from its first
published admission commitment, and must finish no later than grant plus
16 hours. Lease renewal and a different output path extend neither bound.
Cumulative new scientific outputs are limited to 4 GiB (4,294,967,296 bytes),
including preparation, inference, features, weights and failure evidence.
One cohort-bound exclusive execution claim prevents another original operation.
Source mutations stop work with partial evidence preserved.

Before real preparation, inference, feature construction or fitting, commit
the tested consumers and publish exact source, model, protocol, runtime,
producer/control/input inventories and the prospective commitment. All actual
scientific stages require the real shared Store's `run_local_job` admission,
with `BADMINTON_ROOT` and `BADMINTON_DATA_DIR` pinned before configuration imports.
An isolated research Store is not admission. Retain PID, creation time, cwd,
command, Store state and durable receipts. An observation timeout does not prove
exit and does not authorize restart or process signals.

## Reproduction and verification

Use the existing original-host inputs and environment. A clone supplies code
and public protocol, not the private media, features, labels or weights. These
commands describe the bounded interface; they do not authorize repeating a
consumed operation or using an expired grant.

```text
python scripts/scale_aicup_pose_learning.py freeze --workspace REAL --prepared ORIGINAL --native ORIGINAL --actor-prospective ORIGINAL --audit ORIGINAL --control ORIGINAL391 --control-prospective ORIGINAL391_FREEZE/prospective.json --clock-ledger ORIGINAL_JSONL --protocol data/manifests/aicup_pose_scaling_protocol_v1.json --granted-at GRANT_UNIX --committed-at FIRST_ADMISSION_COMMITMENT_UNIX --deadline FIXED_DEADLINE --output NEW_FREEZE --run-output NEW_OUTPUT
python scripts/scale_aicup_pose_learning.py run --prospective NEW_FREEZE/prospective.json --prospective-sha256 HASH --output NEW_OUTPUT
python scripts/scale_aicup_pose_learning.py verify --prospective NEW_FREEZE/prospective.json --prospective-sha256 HASH --output NEW_OUTPUT
python scripts/scale_aicup_pose_learning.py arithmetic --prospective NEW_FREEZE/prospective.json --prospective-sha256 HASH --output NEW_OUTPUT --receipt NEW_PRIVATE_RECEIPT.json
```

Freeze reserves the single immutable cohort claim and binds the exact new run
directory. A second freeze or a different run directory cannot restart it. The
first run creates its dispatch directory exclusively; a failure leaves that
directory and its shared Store job intact.

Read-only verification must reproduce canonical rows, original cache/control
integrity, native PTS/camera/calibration inventories, new features and masks,
train-only statistics/class weights, all 60 checkpoint predictions and metrics,
final selection and the fixed control comparison without decoding or refitting.
A separate arithmetic implementation checks candidate/control predictions,
full 353-row metrics, source/feature counts and representative raw-pose feature
calculations without importing the feature producer.

Report every source, fold, capture, family, side and family/side group, with
support, unavailable counts, confusion, precision/recall/F1, strict joint
correctness and explicitly named conditional denominators. Required generated
regressions, full Python/lint/format/dependency/repository checks, clean
source/wheel/installed-HTTP checks, exact controller PR/main verification and
complete public delivery remain separate completion requirements.

Broader training quantity does not establish correct labels or improved unseen
accuracy. No research model is installed or promoted. Complete scientific rally
references remain **0/2**; automatic contacts, rally boundaries, persistent
identity, doubles support and correct full-match annotation remain unresolved.

## Memory and runtime preflight

Metadata-only costing found a largest conservative raw-frame cache of
5,219,942,400 bytes, exceeding the workstation's observed free RAM. The replacement
retains zlib-level-1 native arrays or raw planes in RAM with native format,
shape, dtype, SHA256,
colorspace, color range, PTS and rational time base. Every packed frame must
reconstruct identical RGB and BGR pixels. Compressed pixels are capped at the
smaller of half initial free RAM and 1 GiB; admission requires 512 MiB free plus
64 MiB initial headroom, and live checks retain the 512 MiB reserve. At most
16 reconstructed frames belong to the LRU. It writes no frame/image files and
does not add native source decoding or model observations.

All 129 scaling controls now pass, including exact packed-RGB plane reconstruction
for formats PyAV cannot expose directly as NumPy arrays. The initial generated
FFV1 case exposed that format gap; another failed fixture had omitted an existing
arithmetic completion receipt. Both failures remain preserved and are corrected.
Color/clock parity, LRU recency/eviction, exact memory boundaries, low-memory
failure and adapter restoration are generated checks, not accuracy measurements.

The compressed-cache preparation source `78b5dfe` passed 6,308 Python tests with
four optional skips, required tooling and clean package/HTTP checks (114 package
files, 63 public manifests, five assets, three SPA routes and authentication).
Earlier failed generated fixtures and the network-restricted package attempt
remain preserved separately. These software checks do not establish scientific
accuracy. Fresh focused, full and package verification of #397's changes is
required before any original operation.

In #394, an interruption expired epoch 1 before any scientific freeze, claim, source
processing or fit. The controller accepted original-host terminal proof and
issued epoch 2; original scientific bounds remain preserved. A metadata-only
forecast from 45 completed native clips (24,273 frames in 4,860.661 seconds)
projects about 28,274.657 seconds for 141,197 new frames before clock scanning,
compression, feature construction, fitting and verification. This is a linear
forecast, not a benchmark of the new cache. The original interrupted window has
insufficient forecast headroom. No scientific operation will be launched under
that window. The controller accepted its terminal release before #394 was
closed as superseded, with its branch, tests and unexecuted evidence retained.
The separately specified #397 follow-up preserves identical cohorts, recipe,
control, output/decode/model budgets and original unknowns. Its fresh grant
supplied the explicit 16-hour task / 12-hour operation bounds above; the old
deadline is never reset implicitly. No new real-source processing or fit has
run at this preparation checkpoint.

## Preserved pre-dispatch CLI failure in #397

Preparation commit `8bc2b0270e6350281421d7590855627cfdfc1178` passed all
131 focused scaling checks, the full 6,310-test suite with four optional skips,
required tooling and clean package/installed-HTTP verification. Its exact source,
inputs, runtime, original producer/control seals and immutable cohort claim were
[published before launch](https://github.com/Ken0u/badminton-match-analyzer/issues/397#issuecomment-6652039292).
The prospective SHA256 is
`5603570cf1a40bd8dfee776c9a21b3ac44ac6e0c68073810da917ebd964c6be6`;
its original deadline remains `1793905768.8576179`. These records remain unchanged.

The original invocation exited with code 1 before entering `run`: argparse
supplied `prospective`, while both `run` and `verify` accept `prospective_path`.
The terminal process identity and failed stderr are preserved. There is no run
output directory, dispatch receipt, shared Store job, source decode, model
observation, new feature or fit. The launcher conservatively records its original
invocation as consumed; no second invocation, new freeze, claim deletion or
source substitution is permitted against that published commitment.

The corrected parser retains the public `--prospective` option and explicitly
binds its internal destination. Two real subprocess regressions reproduce the
failure for both commands, and the generated shared-Store run/completion/verify
test now exercises the public parser in both directions. All three controls
failed on the original source before applying the fix. Corrected source
`bb0c7e1f27cffcb24ce0978b3793b20d84289a68` passed 133 focused controls,
6,312 full tests with four optional skips, required tooling and clean
package/installed-HTTP checks. The tested branch and all failure evidence are
preserved; the controller accepted terminal ownership release and #397 was
closed as superseded, without claiming successful science.

## Specific API-entry recovery in #398

The follow-up grants exactly one corrective API invocation after that specific
pre-entry failure. It grants neither a second scientific operation nor extra
scientific time. The source remains `8bc2b02`, the original prospective and
permanent cohort claim remain byte-identical, and the reserved output stays
`.cache/pose397-run-v1`. The deadline is still November 5, 2026 at
19:09:28.8576179 UTC (`1793905768.8576179`). Insufficient forecast headroom
prevents admission; a renewed lease never extends this deadline.

The [fixed recovery protocol](../data/manifests/aicup_pose_dispatch_recovery_protocol_v1.json)
and `scripts/recover_aicup_pose_dispatch.py` bind the exact predecessor failure,
original commitment and committed epoch-1 grant. Preparation verifies an isolated
clean snapshot of the original scientific source plus its original runtime,
inputs and control seals. A credential-filtered `python -I -B` child loads only
that snapshot's backend and calls the original `run(prospective_path=...,
prospective_sha256=..., output=...)` directly. The corrected public parser stays
in the delivery branch; it does not replace bytes in the scientific freeze.

Preparation creates one exclusive companion under the original freeze directory,
containing immutable failure proof, integrity receipts and dispatch intent.
Its exact source/protocol/runtime/proof/intent hashes must be published before
dispatch. An exclusive start receipt consumes the corrective invocation even if
launch fails. Missing process identity or interrupted observation remains
unknown, never evidence of exit or permission to restart. Logs have two fixed
1 MiB slots, with overflow drained and recorded; terminal evidence has a reserved
64 KiB slot. All companion files and actual claim bytes count against the
original 4 GiB budget, including the unchanged runner's per-stage checks.

Generated controls cover the actual isolated API entry, original shared-Store
completion and read-only verification, stale/mismatched grants, changed or
contradictory proof, source/import mutations, process identity loss, existing
output/Store work, original clocks/headroom, exact byte accounting and exclusive
intent/dispatch. These are software safeguards. Accepted complete-rally
references remain 0/2; experimental weights are not installed in the app.

## Terminal memory failure and CI dependency diagnosis

Wrapper source `eceb0600bd0e23d70038a19b2f738461367f3862` passed 194 focused
controls and 6,373 full tests with four optional skips, required tooling and
clean package/installed-HTTP checks. Its
[exact prospective intent](https://github.com/Ken0u/badminton-match-analyzer/issues/398#issuecomment-6653173324)
was published before corrective dispatch. The original API reached real shared
Store admission and completed four new clips, covering 2,200 frames, 4,400 decode
visits and their retained native outputs/features. The fifth clip's 1,051 frames
completed both source decodes, then its tracking iterator raised
`Insufficient free RAM for bounded native clip cache` when available RAM fell
below the original 512 MiB floor. The source cache had finished loading; this
was a runtime memory guard during pose iteration, not a failure before decoding.

Total source decode visits are therefore 6,502. Exactly 2,200 model observations
belong to completed receipts; the failed clip's exact partial observation count
was not durably recorded and must remain unknown, bounded by 1,051 additional
observations (at most 3,251 total). The failure receipt's 4,400/2,200 counters
cover completed clips only and must not be presented as whole-attempt totals.
The failed clip has source/clock/camera/perception-start evidence but no final
player result or feature receipt. All five clips and every original reference
remain in the cohort; no unavailable row is silently dropped.

The worker exited 1, the shared Store job is durably failed, the exact original
process lifetimes are absent, and the wrapper terminal receipt reports failure.
No fit-start or completion receipt exists. Model fitting, validation metrics,
original full-result verification and separate arithmetic remain unexecuted.
This is an incomplete scientific attempt, not a negative classifier result.
Both the CLI invocation and corrective invocation stay consumed; original
source, freeze, permanent claim, partial output and deadline stay intact.
There is no retry, threshold reduction, CPU fallback or process termination.
Memory observations are insufficient to attribute the transient pressure to
one application. Other applications, environments and research artifacts remain
preserved. Further execution requires a separately specified continuation;
this failed operation cannot be replayed under a new output or lease.

Draft PR #399's lean Python/macOS/Windows CI profiles also exposed 26 test
failures/errors from unconditional optional `torch`/`torchvision` imports.
The same failures reproduced locally with those imports unavailable. A test-only
repair uses per-test/fixture `importorskip` for genuine learning-runtime cases,
leaving other controls active: 167 pass / 27 optional cases skip without those
libraries; all 194 pass with the learning runtime. This changes no workflow,
dependency, production function or scientific source. Fresh exact-head CI and
controller delivery remain required; the PR stays draft while scientific
failure disposition and follow-up planning remain open.
