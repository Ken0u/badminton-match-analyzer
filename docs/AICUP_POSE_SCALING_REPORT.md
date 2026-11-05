# Broader weak pose training with a fixed validation set

Task [#394](https://github.com/Ken0u/badminton-match-analyzer/issues/394) tests
whether broader existing training supervision improves the static pose
classifier from the [completed learning comparison](AICUP_POSE_LEARNING_REPORT.md).
Its frozen specification is
`2c839533cfaf3c7d603e84d044fd4d12c2ee0d753c30175adaa974c606c9d17e`.
This is preparation for one private development experiment. No original
data-scaling operation, new native inference or new fit has run at this
checkpoint; generated parity, scientific results and delivery remain pending.

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
on success and failure before this design is used on real inputs. Final
verification of the compressed-cache change remains pending at this checkpoint.

New decoding is bounded to 282,394 frame visits and new model observations to
141,197 frames. There is no new pass on the original 45 clips, shuttle
inference, model acquisition, CPU fallback or repeated failed pass. Initialize
torchvision before threaded PyAV and retain native FFmpeg logging restoration
before media opening and closing.

A fresh committed task grant permits at most 12 hours from its grant timestamp.
The single original scientific operation has at most eight hours from its first
published admission commitment, and must finish no later than grant plus
12 hours. Lease renewal and a different output path extend neither bound.
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

Before this change, the stable source passed 6,275 Python tests with four optional
skips, plus required tooling and clean package/HTTP checks. Those results do not
verify this later cache change or establish scientific accuracy. Fresh focused,
full and package verification is required before any original operation.

An interruption expired epoch 1 before any scientific freeze, claim, source
processing or fit. The controller accepted original-host terminal proof and
issued epoch 2; original scientific bounds remain preserved. A metadata-only
forecast from 45 completed native clips (24,273 frames in 4,860.661 seconds)
projects about 28,274.657 seconds for 141,197 new frames before clock scanning,
compression, feature construction, fitting and verification. This is a linear
forecast, not a benchmark of the new cache. The original interrupted window has
insufficient forecast headroom. No scientific operation will be launched under
that window; a separately specified bounded follow-up must preserve this task's
unexecuted evidence and original deadline rather than reset it implicitly.
