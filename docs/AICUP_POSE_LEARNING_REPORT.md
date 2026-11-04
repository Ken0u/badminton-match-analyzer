# Static versus temporal weak pose learning

Task [#391](https://github.com/Ken0u/badminton-match-analyzer/issues/391) tests
whether short-window observed player motion improves conditional stroke family
and forehand/backhand classification over a matched-capacity static control.
The [original pose inputs](AICUP_POSE_PILOT_REPORT.md) and
[weak actor associations](AICUP_ACTOR_CORRESPONDENCE_REPORT.md) are consumed
historical experiments and must not be repeated. This follow-up introduces no
media decoding, perception inference, image transfer or application model change.
Implementation preparation is not a completed learning result.

## Fixed inputs and comparison

The [versioned protocol](../data/manifests/aicup_pose_learning_protocol_v1.json)
retains 45 clips, 24,273 native frames and all 784 published weak references:
431 training and 353 validation rows. Exactly 652 weakly paired rows supply
research inputs; 132 unresolved rows, including three censored H0 rows, remain
in evaluation denominators. True hitters, scene eligibility and original-match
independence remain unverified. Training-ready rows remain zero; permitting a
private weak-supervision experiment does not promote their scientific status.

Both contact endpoints `[H-1,H]` remain. For shoulders, elbows and wrists of the
provisional hitter then defender, observed joint coordinates are normalized by
that frame's observed box height and box center/bottom. Finite display bounds,
confidence at least 0.25, a unique observed track, current calibration and the
contact camera namespace are required. Unavailable joints retain zero values,
zero confidence and explicit masks. There is no interpolation or identity repair.

Each arm has 108 inputs. The temporal arm concatenates three 36-value blocks:
contact-center pose, mean pose over native slots `H-5..H+4`, and mean adjacent
observed velocity using exact rational PTS differences up to 0.1 seconds.
Geometry averages observed values only; confidence sums use nominal divisors
2, 10 and 9. Nonadjacent samples are never differentiated. Native offsets do
not imply a constant elapsed-time horizon. The static arm concatenates center,
center and zero velocity. Features contain no family/side target, winner,
landing position or published A/B identity; only the previously frozen weak
correspondence selects provisional tracks.

Both models use the same 108→64→32 ReLU/dropout-0.1 network and biased eight-family
and two-side heads. Each has 9,386 parameters. Exactly two CPU fits run, static
then temporal, with seed 20261104, two CPU threads, 300 epochs, batch 64 and
AdamW (learning rate 0.001, weight decay 0.01). Family/side losses weigh 1/0.5.
Normalization and inverse-square-root class weights use weakly paired training
rows only. Missing raw values/confidences remain zero in saved features; the
fixed train-only affine normalization retains their encoded missingness.
No unavailable row is removed from reporting. Unknown targets are not negatives.

Every five epochs, retain a private checkpoint and select by the mean of
supported eight-group family macro F1 and side balanced recall, then strict
joint correctness over all validation rows, then earlier epoch. Compare the
selected arms by the first two scores, retaining static on a tie. Unsupported
training classes cannot be predicted as known. No threshold search, seed sweep,
test read, tuning after results or automatic model installation is permitted.
Private loss histories are integrity-sealed observations; verification does not
claim to recreate optimizer steps. It reloads every selection checkpoint and
recomputes predictions, validation metrics, selection and final reports.

## Reproduction and execution

Use the real workstation's existing environment and private input paths; a clone
does not include them. A fresh committed grant fixes a four-hour scientific
deadline and 1 GiB cumulative output limit. Commit the tested code, run the
integrity-only freeze and publish its exact consumer/runtime/protocol/input and
prospective hashes before any real feature extraction or fitting.

```text
python scripts/compare_aicup_pose_learning.py freeze --workspace REAL_WORKSPACE --prepared ORIGINAL_PREPARATION --native ORIGINAL_NATIVE --actor-prospective ORIGINAL_ACTOR_PROSPECTIVE_JSON --audit ORIGINAL_ACTOR_AUDIT --protocol data/manifests/aicup_pose_learning_protocol_v1.json --granted-at ORIGINAL_GRANT_UNIX --deadline ORIGINAL_GRANT_PLUS_FOUR_HOURS --output NEW_PRIVATE_FREEZE
python scripts/compare_aicup_pose_learning.py run --prospective NEW_PRIVATE_FREEZE/prospective.json --prospective-sha256 PUBLISHED_HASH --output NEW_PRIVATE_RUN
python scripts/compare_aicup_pose_learning.py verify --prospective NEW_PRIVATE_FREEZE/prospective.json --prospective-sha256 PUBLISHED_HASH --output NEW_PRIVATE_RUN
```

The entire original extraction/two-fit operation requires real shared Store
admission with root/data pinned before configuration imports. An exclusive
cohort-bound execution claim prevents repeating it using another output/freeze.
Failures preserve partial evidence and consume the claim. Verification remains
read-only after the original deadline and never refits. Original producer seals
are checked individually; this consumer does not retroactively enter historical
producer inventories. Source/frame clocks, orientation, cameras, calibrations,
annotations and all unknowns remain intact.

Report every original fold/capture, each family, side and family/side support,
confusion, precision/recall/F1, unavailable cases and full-denominator joint
correctness. Conditional results explicitly name their narrower denominator.
Even a positive comparison is familiar development evidence, not independent
accuracy, automatic contact detection, persistent identity, verified doubles
support or complete full-match annotation. Complete scientific rally references
remain **0/2**. Exact PR/main checks and full public code delivery are separate
completion requirements; source rows, pose features and model weights stay private.

## Software verification before the original experiment

Seventy-two new generated controls and all 212 focused checks pass. The full
suite passes 6,126 tests with four optional skips; lint, formatting, dependency,
strict JSON, UTF-8/LF, local links and whitespace checks pass. Clean source/wheel
and installed HTTP verification checks 113 package files, 62 public manifests,
five frontend assets, three SPA routes and authentication. An earlier sandboxed
package attempt could not fetch the pinned build dependency; its failure is
preserved separately from the successful normal-network verification.

Generated review exposed a checkpoint substitution that retained identical
argmax predictions; each checkpoint now has an independent saved record and
weight digest checked alongside prediction/history reproduction. Tests also
reject a competing isolated Store, preserve both ambiguous contact endpoints,
mask invalid native gaps/cameras/joints, retain unavailable/unknown rows, and
verify all checkpoint selections without refitting. These are software controls,
not improved badminton accuracy. No original real-source fit has run at this
preparation checkpoint.

The original [#389](https://github.com/Ken0u/badminton-match-analyzer/issues/389)
lease and scientific window expired before a real-source freeze, extraction or
fit. Its tested source and timing incident are preserved in
[draft PR #390](https://github.com/Ken0u/badminton-match-analyzer/pull/390) and the
[owning preservation checkpoint](https://github.com/Ken0u/badminton-match-analyzer/issues/389#issuecomment-6641011191).
An authenticated original-host terminal-proof release was accepted before that
task was closed as superseded. This is a transfer, not scientific completion.
The fresh #391 grant supplies its own four-hour window; the old deadline is not
reset. Its adopted scientific code and recipe are byte-identical to the tested
preparation. Cumulative limits remain one original operation, two real CPU fits
and 1 GiB scientific output. No images, new inference or source replacements are
added. No original real fit has run at this continuation preparation checkpoint.

## Original comparison results

The single prospectively committed original operation completed both fixed CPU
fits on the unchanged source cohort. No third fit, seed/threshold sweep, held-out
test access, media decode, new perception inference, image transfer, eligibility
promotion, model installation or annotation edit occurred. All 784 original
references remain: 431 training and 353 validation, with 652 weak pairs and
132 unavailable rows, including three censored H0 rows. Unknown actual actors,
live scenes, source independence and usage/deployment rights remain unresolved.
Complete scientific rally references remain **0/2**.

The [prospective commitment](https://github.com/Ken0u/badminton-match-analyzer/issues/391#issuecomment-6641197055) binds tested consumer
`4e063b49974eb6fe7d97a831edb8ea7ac399cf62`, protocol
`5430cf84f9ddcc73d059b0e5f203657d9ff7d515310a527d222ee3f890eee88e` and prospective freeze
`8cc839a32af5c05b0a67b3c08a98a645531a0592752321f1d11581b2ad16f983`. Original execution completion
is `42500f898ad6a1fd4548d42dd233f25826be9f7ea8cc6248fb10ab735dc84dd3`. The original claim is consumed and must never
be replayed. Read-only verification is a separate operation, without fitting.

| Arm | Parameters | Selected epoch | Validation family macro F1 (8 groups) | Side balanced recall | Strict joint / all 353 rows | Joint given weak pair and known targets | Conditional rows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| static | 9386 | 195 | 0.415854 | 0.736626 | 40.51% (143/353) | 49.31% | 290 |
| temporal | 9386 | 185 | 0.398081 | 0.751182 | 37.11% (131/353) | 45.17% | 290 |

The frozen development selection chooses **static**. Temporal minus static validation family macro F1 is -0.017773; strict joint correctness changes by -3.40 percentage points. These are conditional weak-reference development results, not independent badminton accuracy or a causal guarantee outside this comparison. Selection does not authorize app promotion.

The requested-six-family macro F1 excludes other/serve only in this separately
named summary, never from source-row or full eight-group selection denominators:
static 0.367863, temporal 0.362654.

### Source-row and pose availability

| Fold | Rows | Weak pairs | Unavailable | Observed joint slots / nominal | Adjacent observed pairs / nominal |
| --- | ---: | ---: | ---: | --- | --- |
| train | 431 | 362 | 69 | 43316/51720 | 38946/46548 |
| validation | 353 | 290 | 63 | 34239/42360 | 30662/38124 |

These are observation/association coverage counts, not verified hitter or pose
accuracy. Masked values do not remove a weakly paired training row. Every unknown
target remains distinct from an unavailable input or a known negative.

### Full-denominator validation classes

All precision denominators below use predictions on known weak truth; unknown
truth is reported separately. Recall includes unanswered known rows as misses.
No support means unavailable recall, not zero-error evidence.

| Output | Class | Support | Static precision | Static recall | Static F1 | Temporal precision | Temporal recall | Temporal F1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| family | clear | 24 | 0.285714 | 0.333333 | 0.307692 | 0.238095 | 0.208333 | 0.222222 |
| family | lift | 71 | 0.457627 | 0.380282 | 0.415385 | 0.375000 | 0.338028 | 0.355556 |
| family | net | 129 | 0.623762 | 0.488372 | 0.547826 | 0.553191 | 0.403101 | 0.466368 |
| family | drop | 30 | 0.392857 | 0.366667 | 0.379310 | 0.387097 | 0.400000 | 0.393443 |
| family | smash | 48 | 0.709677 | 0.458333 | 0.556962 | 0.692308 | 0.562500 | 0.620690 |
| family | drive | 12 | 0.000000 | 0.000000 | 0.000000 | 0.200000 | 0.083333 | 0.117647 |
| family | other | 16 | 0.300000 | 0.187500 | 0.230769 | 0.125000 | 0.125000 | 0.125000 |
| family | serve | 23 | 0.909091 | 0.869565 | 0.888889 | 0.950000 | 0.826087 | 0.883721 |
| side | forehand | 193 | 0.934211 | 0.735751 | 0.823188 | 0.953642 | 0.746114 | 0.837209 |
| side | backhand | 160 | 0.855072 | 0.737500 | 0.791946 | 0.870504 | 0.756250 | 0.809365 |

| Family/side | Validation support | Static precision | Static recall | Static F1 | Temporal precision | Temporal recall | Temporal F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| clear/forehand | 19 | 0.296296 | 0.421053 | 0.347826 | 0.250000 | 0.263158 | 0.256410 |
| clear/backhand | 5 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| lift/forehand | 32 | 0.368421 | 0.218750 | 0.274510 | 0.357143 | 0.312500 | 0.333333 |
| lift/backhand | 39 | 0.475000 | 0.487179 | 0.481013 | 0.333333 | 0.307692 | 0.320000 |
| net/forehand | 57 | 0.525000 | 0.368421 | 0.432990 | 0.400000 | 0.210526 | 0.275862 |
| net/backhand | 72 | 0.557377 | 0.472222 | 0.511278 | 0.500000 | 0.444444 | 0.470588 |
| drop/forehand | 26 | 0.400000 | 0.307692 | 0.347826 | 0.347826 | 0.307692 | 0.326531 |
| drop/backhand | 4 | 0.375000 | 0.750000 | 0.500000 | 0.500000 | 1.000000 | 0.666667 |
| smash/forehand | 44 | 0.733333 | 0.500000 | 0.594595 | 0.702703 | 0.590909 | 0.641975 |
| smash/backhand | 4 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| drive/forehand | 7 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| drive/backhand | 5 | 0.000000 | 0.000000 | 0.000000 | 0.333333 | 0.200000 | 0.250000 |
| other/forehand | 8 | 0.250000 | 0.250000 | 0.250000 | 0.200000 | 0.250000 | 0.222222 |
| other/backhand | 8 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| serve/forehand | 0 | 0.000000 | unavailable | 0.000000 | 0.000000 | unavailable | 0.000000 |
| serve/backhand | 23 | 0.904762 | 0.826087 | 0.863636 | 1.000000 | 0.826087 | 0.904762 |

Sparse backhand cells and capture/domain separation limit interpretation. These
weak paired-reference classifications assume the published contact interval and
provisional actor association; they are not contact/event detection or persistent
identity results. No probability threshold was tuned.

### Static validation family confusion

Rows are weak truth; columns are predictions.

| Truth | clear | lift | net | drop | smash | drive | other | serve | unanswered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| clear | 8 | 1 | 1 | 7 | 3 | 4 | 0 | 0 | 0 |
| lift | 0 | 27 | 20 | 0 | 0 | 0 | 3 | 1 | 20 |
| net | 0 | 21 | 63 | 0 | 1 | 3 | 4 | 1 | 36 |
| drop | 9 | 2 | 1 | 11 | 5 | 2 | 0 | 0 | 0 |
| smash | 10 | 2 | 2 | 9 | 22 | 1 | 0 | 0 | 2 |
| drive | 1 | 2 | 6 | 1 | 0 | 0 | 0 | 0 | 2 |
| other | 0 | 4 | 7 | 0 | 0 | 1 | 3 | 0 | 1 |
| serve | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 20 | 2 |

Known targets 353; unknown targets 0; unanswered known targets 63; predictions on unknown truth 0.

### Static validation side confusion

Rows are weak truth; columns are predictions.

| Truth | forehand | backhand | unanswered |
| --- | ---: | ---: | ---: |
| forehand | 142 | 20 | 31 |
| backhand | 10 | 118 | 32 |

Known targets 353; unknown targets 0; unanswered known targets 63; predictions on unknown truth 0.

### Temporal validation family confusion

Rows are weak truth; columns are predictions.

| Truth | clear | lift | net | drop | smash | drive | other | serve | unanswered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| clear | 5 | 1 | 1 | 10 | 6 | 0 | 0 | 1 | 0 |
| lift | 0 | 24 | 24 | 0 | 0 | 0 | 3 | 0 | 20 |
| net | 0 | 31 | 52 | 0 | 0 | 3 | 7 | 0 | 36 |
| drop | 8 | 2 | 1 | 12 | 6 | 0 | 1 | 0 | 0 |
| smash | 8 | 0 | 3 | 8 | 27 | 0 | 0 | 0 | 2 |
| drive | 0 | 2 | 4 | 1 | 0 | 1 | 2 | 0 | 2 |
| other | 0 | 4 | 8 | 0 | 0 | 1 | 2 | 0 | 1 |
| serve | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 19 | 2 |

Known targets 353; unknown targets 0; unanswered known targets 63; predictions on unknown truth 0.

### Temporal validation side confusion

Rows are weak truth; columns are predictions.

| Truth | forehand | backhand | unanswered |
| --- | ---: | ---: | ---: |
| forehand | 144 | 18 | 31 |
| backhand | 7 | 121 | 32 |

Known targets 353; unknown targets 0; unanswered known targets 63; predictions on unknown truth 0.

### Capture/fold results

Captures are conservative source groups, not independently adjudicated original
match identities. Validation is familiar development evidence.

| Group | Rows | Weak pairs | Static family F1 | Temporal family F1 | Static strict joint | Temporal strict joint |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 784 | 652 | 0.671863 | 0.713909 | 60.20% | 62.88% |
| capture:bangkok | 132 | 116 | 0.865140 | 0.970414 | 79.55% | 87.88% |
| capture:birmingham | 24 | 21 | 0.921551 | 0.948413 | 83.33% | 87.50% |
| capture:jakarta_red | 121 | 95 | 0.852757 | 0.893233 | 76.86% | 78.51% |
| capture:kualalumpur | 30 | 25 | 0.735740 | 0.896259 | 60.00% | 83.33% |
| capture:odense | 353 | 290 | 0.415854 | 0.398081 | 40.51% | 37.11% |
| capture:osaka | 35 | 26 | 0.769048 | 0.917857 | 65.71% | 74.29% |
| capture:tokyo | 89 | 79 | 0.889791 | 0.963399 | 78.65% | 88.76% |
| train | 431 | 362 | 0.859304 | 0.940735 | 76.33% | 83.99% |
| validation | 353 | 290 | 0.415854 | 0.398081 | 40.51% | 37.11% |

### Fixed training histories

Every scheduled epoch ran. Loss is the mean of known-head batch losses for that
epoch, with the frozen class/head weights. Validation selection is evaluated
only every five epochs; a dash means no selection at that epoch. All original
private checkpoints, optimizer-observed loss histories and CPU/RNG receipts are
integrity sealed. Verification does not refit or claim to reconstruct optimizer
steps; it reloads all 120 selection checkpoints and reproduces their metrics.

| Epoch | Static loss | Temporal loss | Static selection score | Temporal selection score | Static strict validation joint | Temporal strict validation joint |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2.407532 | 2.407841 | - | - | - | - |
| 2 | 2.363823 | 2.351292 | - | - | - | - |
| 3 | 2.330800 | 2.308329 | - | - | - | - |
| 4 | 2.284933 | 2.248137 | - | - | - | - |
| 5 | 2.242692 | 2.191788 | 0.310764 | 0.313627 | 15.30% | 16.15% |
| 6 | 2.198256 | 2.135506 | - | - | - | - |
| 7 | 2.146834 | 2.060713 | - | - | - | - |
| 8 | 2.082429 | 1.989634 | - | - | - | - |
| 9 | 2.019059 | 1.900787 | - | - | - | - |
| 10 | 1.964185 | 1.825315 | 0.428104 | 0.471670 | 23.23% | 29.75% |
| 11 | 1.903011 | 1.749356 | - | - | - | - |
| 12 | 1.817230 | 1.653434 | - | - | - | - |
| 13 | 1.739771 | 1.549031 | - | - | - | - |
| 14 | 1.705782 | 1.504182 | - | - | - | - |
| 15 | 1.645782 | 1.422137 | 0.529408 | 0.550601 | 31.44% | 35.98% |
| 16 | 1.582035 | 1.332737 | - | - | - | - |
| 17 | 1.559670 | 1.317472 | - | - | - | - |
| 18 | 1.509599 | 1.276665 | - | - | - | - |
| 19 | 1.484162 | 1.224430 | - | - | - | - |
| 20 | 1.465572 | 1.209743 | 0.540714 | 0.553469 | 32.86% | 35.98% |
| 21 | 1.445009 | 1.162575 | - | - | - | - |
| 22 | 1.399329 | 1.126181 | - | - | - | - |
| 23 | 1.394851 | 1.128934 | - | - | - | - |
| 24 | 1.340190 | 1.054183 | - | - | - | - |
| 25 | 1.329866 | 1.027558 | 0.545979 | 0.547276 | 34.28% | 35.41% |
| 26 | 1.290182 | 0.973282 | - | - | - | - |
| 27 | 1.336052 | 1.014506 | - | - | - | - |
| 28 | 1.298788 | 0.991478 | - | - | - | - |
| 29 | 1.272185 | 0.927073 | - | - | - | - |
| 30 | 1.228451 | 0.893251 | 0.549321 | 0.555090 | 34.84% | 35.98% |
| 31 | 1.231276 | 0.884479 | - | - | - | - |
| 32 | 1.239115 | 0.876715 | - | - | - | - |
| 33 | 1.268742 | 0.878144 | - | - | - | - |
| 34 | 1.215946 | 0.867746 | - | - | - | - |
| 35 | 1.238713 | 0.832507 | 0.555453 | 0.552251 | 35.13% | 34.84% |
| 36 | 1.202948 | 0.820744 | - | - | - | - |
| 37 | 1.190474 | 0.775279 | - | - | - | - |
| 38 | 1.148114 | 0.750915 | - | - | - | - |
| 39 | 1.164210 | 0.756776 | - | - | - | - |
| 40 | 1.208570 | 0.778832 | 0.558826 | 0.566989 | 36.54% | 37.68% |
| 41 | 1.130130 | 0.692052 | - | - | - | - |
| 42 | 1.146169 | 0.710194 | - | - | - | - |
| 43 | 1.153674 | 0.702355 | - | - | - | - |
| 44 | 1.101729 | 0.645206 | - | - | - | - |
| 45 | 1.111567 | 0.680352 | 0.566971 | 0.569908 | 37.96% | 38.24% |
| 46 | 1.094377 | 0.663214 | - | - | - | - |
| 47 | 1.077425 | 0.640897 | - | - | - | - |
| 48 | 1.088894 | 0.626009 | - | - | - | - |
| 49 | 1.043651 | 0.589151 | - | - | - | - |
| 50 | 1.074695 | 0.590936 | 0.554572 | 0.560978 | 35.69% | 37.11% |
| 51 | 1.061805 | 0.619602 | - | - | - | - |
| 52 | 1.052696 | 0.585750 | - | - | - | - |
| 53 | 1.036725 | 0.566167 | - | - | - | - |
| 54 | 1.058904 | 0.589280 | - | - | - | - |
| 55 | 1.064158 | 0.543507 | 0.565875 | 0.563358 | 37.68% | 37.68% |
| 56 | 1.011734 | 0.556288 | - | - | - | - |
| 57 | 1.056578 | 0.574143 | - | - | - | - |
| 58 | 1.006000 | 0.515910 | - | - | - | - |
| 59 | 1.014115 | 0.531124 | - | - | - | - |
| 60 | 0.989045 | 0.497160 | 0.562869 | 0.568580 | 37.39% | 37.39% |
| 61 | 0.965407 | 0.478074 | - | - | - | - |
| 62 | 0.966904 | 0.453279 | - | - | - | - |
| 63 | 0.987326 | 0.486337 | - | - | - | - |
| 64 | 0.997500 | 0.492273 | - | - | - | - |
| 65 | 0.987383 | 0.460928 | 0.554443 | 0.557818 | 35.98% | 35.98% |
| 66 | 0.946788 | 0.445591 | - | - | - | - |
| 67 | 0.958959 | 0.485409 | - | - | - | - |
| 68 | 0.952493 | 0.446773 | - | - | - | - |
| 69 | 0.972179 | 0.455463 | - | - | - | - |
| 70 | 0.928997 | 0.435814 | 0.551177 | 0.554109 | 36.83% | 35.41% |
| 71 | 0.901991 | 0.433111 | - | - | - | - |
| 72 | 0.954392 | 0.442302 | - | - | - | - |
| 73 | 0.926204 | 0.407968 | - | - | - | - |
| 74 | 0.884931 | 0.429182 | - | - | - | - |
| 75 | 0.922139 | 0.422754 | 0.553389 | 0.563579 | 35.69% | 36.26% |
| 76 | 0.883838 | 0.394302 | - | - | - | - |
| 77 | 0.913231 | 0.424328 | - | - | - | - |
| 78 | 0.913868 | 0.392208 | - | - | - | - |
| 79 | 0.877088 | 0.359725 | - | - | - | - |
| 80 | 0.922167 | 0.380080 | 0.561523 | 0.566832 | 36.83% | 36.54% |
| 81 | 0.847603 | 0.375895 | - | - | - | - |
| 82 | 0.874031 | 0.378822 | - | - | - | - |
| 83 | 0.870752 | 0.365916 | - | - | - | - |
| 84 | 0.861925 | 0.327996 | - | - | - | - |
| 85 | 0.873459 | 0.362950 | 0.557289 | 0.562017 | 36.54% | 35.13% |
| 86 | 0.859079 | 0.336845 | - | - | - | - |
| 87 | 0.849296 | 0.328294 | - | - | - | - |
| 88 | 0.869508 | 0.321966 | - | - | - | - |
| 89 | 0.869707 | 0.342879 | - | - | - | - |
| 90 | 0.845616 | 0.334594 | 0.554621 | 0.564991 | 36.54% | 36.26% |
| 91 | 0.833196 | 0.325222 | - | - | - | - |
| 92 | 0.865154 | 0.331184 | - | - | - | - |
| 93 | 0.872177 | 0.331355 | - | - | - | - |
| 94 | 0.838277 | 0.319281 | - | - | - | - |
| 95 | 0.817370 | 0.291678 | 0.550089 | 0.554768 | 36.26% | 35.98% |
| 96 | 0.834984 | 0.288039 | - | - | - | - |
| 97 | 0.821900 | 0.329544 | - | - | - | - |
| 98 | 0.775634 | 0.260224 | - | - | - | - |
| 99 | 0.764921 | 0.260671 | - | - | - | - |
| 100 | 0.760897 | 0.290881 | 0.560218 | 0.557172 | 36.83% | 36.26% |
| 101 | 0.752081 | 0.256766 | - | - | - | - |
| 102 | 0.772335 | 0.265820 | - | - | - | - |
| 103 | 0.811306 | 0.258500 | - | - | - | - |
| 104 | 0.749967 | 0.279158 | - | - | - | - |
| 105 | 0.774991 | 0.253765 | 0.556280 | 0.562183 | 37.11% | 36.83% |
| 106 | 0.781523 | 0.286037 | - | - | - | - |
| 107 | 0.698920 | 0.253110 | - | - | - | - |
| 108 | 0.761069 | 0.282382 | - | - | - | - |
| 109 | 0.765092 | 0.250439 | - | - | - | - |
| 110 | 0.730788 | 0.254346 | 0.553103 | 0.561747 | 36.83% | 37.96% |
| 111 | 0.815287 | 0.258666 | - | - | - | - |
| 112 | 0.765371 | 0.228792 | - | - | - | - |
| 113 | 0.752413 | 0.223828 | - | - | - | - |
| 114 | 0.739569 | 0.268278 | - | - | - | - |
| 115 | 0.692719 | 0.226986 | 0.558510 | 0.556160 | 37.39% | 36.26% |
| 116 | 0.734440 | 0.225460 | - | - | - | - |
| 117 | 0.747318 | 0.228641 | - | - | - | - |
| 118 | 0.736202 | 0.260852 | - | - | - | - |
| 119 | 0.746538 | 0.236602 | - | - | - | - |
| 120 | 0.691631 | 0.235404 | 0.557995 | 0.560985 | 37.39% | 37.96% |
| 121 | 0.716914 | 0.216469 | - | - | - | - |
| 122 | 0.720150 | 0.249149 | - | - | - | - |
| 123 | 0.699585 | 0.212156 | - | - | - | - |
| 124 | 0.725424 | 0.229899 | - | - | - | - |
| 125 | 0.692374 | 0.198444 | 0.563032 | 0.560507 | 37.96% | 37.11% |
| 126 | 0.680217 | 0.206303 | - | - | - | - |
| 127 | 0.704699 | 0.223990 | - | - | - | - |
| 128 | 0.694255 | 0.210216 | - | - | - | - |
| 129 | 0.691216 | 0.203856 | - | - | - | - |
| 130 | 0.656541 | 0.179124 | 0.566187 | 0.560019 | 38.81% | 37.11% |
| 131 | 0.674252 | 0.191192 | - | - | - | - |
| 132 | 0.684317 | 0.212286 | - | - | - | - |
| 133 | 0.630820 | 0.173896 | - | - | - | - |
| 134 | 0.676322 | 0.175568 | - | - | - | - |
| 135 | 0.632519 | 0.194277 | 0.562297 | 0.562149 | 37.96% | 37.39% |
| 136 | 0.696760 | 0.212679 | - | - | - | - |
| 137 | 0.669363 | 0.197312 | - | - | - | - |
| 138 | 0.641228 | 0.220457 | - | - | - | - |
| 139 | 0.661340 | 0.197223 | - | - | - | - |
| 140 | 0.636976 | 0.182515 | 0.564272 | 0.560180 | 38.24% | 35.98% |
| 141 | 0.635036 | 0.177258 | - | - | - | - |
| 142 | 0.675024 | 0.189031 | - | - | - | - |
| 143 | 0.649334 | 0.170947 | - | - | - | - |
| 144 | 0.607054 | 0.162576 | - | - | - | - |
| 145 | 0.597398 | 0.164120 | 0.560876 | 0.564125 | 39.09% | 37.68% |
| 146 | 0.638998 | 0.187251 | - | - | - | - |
| 147 | 0.620490 | 0.188644 | - | - | - | - |
| 148 | 0.629372 | 0.175962 | - | - | - | - |
| 149 | 0.622205 | 0.182694 | - | - | - | - |
| 150 | 0.625970 | 0.160855 | 0.568673 | 0.554039 | 40.23% | 35.69% |
| 151 | 0.617167 | 0.176960 | - | - | - | - |
| 152 | 0.556611 | 0.169813 | - | - | - | - |
| 153 | 0.625120 | 0.156006 | - | - | - | - |
| 154 | 0.620609 | 0.163583 | - | - | - | - |
| 155 | 0.610083 | 0.169933 | 0.568858 | 0.547829 | 39.94% | 33.99% |
| 156 | 0.643106 | 0.177054 | - | - | - | - |
| 157 | 0.604973 | 0.193969 | - | - | - | - |
| 158 | 0.619721 | 0.166339 | - | - | - | - |
| 159 | 0.634923 | 0.191290 | - | - | - | - |
| 160 | 0.566591 | 0.154403 | 0.562865 | 0.560634 | 38.81% | 36.54% |
| 161 | 0.608805 | 0.174310 | - | - | - | - |
| 162 | 0.604692 | 0.157077 | - | - | - | - |
| 163 | 0.594972 | 0.133197 | - | - | - | - |
| 164 | 0.594891 | 0.167835 | - | - | - | - |
| 165 | 0.585805 | 0.139118 | 0.571669 | 0.562020 | 39.38% | 35.98% |
| 166 | 0.564711 | 0.129549 | - | - | - | - |
| 167 | 0.595470 | 0.159406 | - | - | - | - |
| 168 | 0.571437 | 0.135402 | - | - | - | - |
| 169 | 0.590872 | 0.143893 | - | - | - | - |
| 170 | 0.574613 | 0.146624 | 0.575072 | 0.565350 | 39.66% | 37.39% |
| 171 | 0.548097 | 0.135919 | - | - | - | - |
| 172 | 0.562147 | 0.136054 | - | - | - | - |
| 173 | 0.585779 | 0.153459 | - | - | - | - |
| 174 | 0.538903 | 0.118749 | - | - | - | - |
| 175 | 0.531804 | 0.134916 | 0.568469 | 0.571137 | 39.94% | 37.96% |
| 176 | 0.595159 | 0.130804 | - | - | - | - |
| 177 | 0.548075 | 0.152009 | - | - | - | - |
| 178 | 0.556231 | 0.140901 | - | - | - | - |
| 179 | 0.561850 | 0.109038 | - | - | - | - |
| 180 | 0.536992 | 0.130458 | 0.569838 | 0.568117 | 39.09% | 38.53% |
| 181 | 0.571094 | 0.154767 | - | - | - | - |
| 182 | 0.547137 | 0.130744 | - | - | - | - |
| 183 | 0.531456 | 0.114504 | - | - | - | - |
| 184 | 0.572883 | 0.132107 | - | - | - | - |
| 185 | 0.526859 | 0.118704 | 0.574186 | 0.574631 | 39.94% | 37.11% |
| 186 | 0.520478 | 0.146935 | - | - | - | - |
| 187 | 0.526008 | 0.128686 | - | - | - | - |
| 188 | 0.572828 | 0.122254 | - | - | - | - |
| 189 | 0.513052 | 0.137453 | - | - | - | - |
| 190 | 0.491666 | 0.094248 | 0.566428 | 0.567081 | 39.66% | 36.83% |
| 191 | 0.503686 | 0.102783 | - | - | - | - |
| 192 | 0.530853 | 0.140955 | - | - | - | - |
| 193 | 0.508578 | 0.145650 | - | - | - | - |
| 194 | 0.538022 | 0.107869 | - | - | - | - |
| 195 | 0.520718 | 0.124782 | 0.576240 | 0.558275 | 40.51% | 37.96% |
| 196 | 0.482954 | 0.140082 | - | - | - | - |
| 197 | 0.538986 | 0.110915 | - | - | - | - |
| 198 | 0.523402 | 0.129659 | - | - | - | - |
| 199 | 0.484432 | 0.122202 | - | - | - | - |
| 200 | 0.545579 | 0.114798 | 0.571788 | 0.557124 | 39.94% | 37.11% |
| 201 | 0.510345 | 0.138733 | - | - | - | - |
| 202 | 0.500508 | 0.123842 | - | - | - | - |
| 203 | 0.531111 | 0.121708 | - | - | - | - |
| 204 | 0.491099 | 0.093324 | - | - | - | - |
| 205 | 0.521878 | 0.115242 | 0.568710 | 0.569319 | 38.81% | 37.96% |
| 206 | 0.478480 | 0.120036 | - | - | - | - |
| 207 | 0.507472 | 0.121656 | - | - | - | - |
| 208 | 0.523464 | 0.119350 | - | - | - | - |
| 209 | 0.519894 | 0.109795 | - | - | - | - |
| 210 | 0.448945 | 0.090408 | 0.573628 | 0.562809 | 39.94% | 35.98% |
| 211 | 0.481225 | 0.121796 | - | - | - | - |
| 212 | 0.468247 | 0.099260 | - | - | - | - |
| 213 | 0.447285 | 0.122366 | - | - | - | - |
| 214 | 0.449077 | 0.105838 | - | - | - | - |
| 215 | 0.479792 | 0.098051 | 0.570753 | 0.562397 | 39.66% | 36.83% |
| 216 | 0.482196 | 0.091808 | - | - | - | - |
| 217 | 0.476018 | 0.103213 | - | - | - | - |
| 218 | 0.417542 | 0.079496 | - | - | - | - |
| 219 | 0.457656 | 0.137079 | - | - | - | - |
| 220 | 0.436574 | 0.094742 | 0.567591 | 0.557486 | 39.09% | 36.26% |
| 221 | 0.425386 | 0.108955 | - | - | - | - |
| 222 | 0.427329 | 0.115474 | - | - | - | - |
| 223 | 0.458200 | 0.097947 | - | - | - | - |
| 224 | 0.437758 | 0.082249 | - | - | - | - |
| 225 | 0.449937 | 0.088406 | 0.569178 | 0.561989 | 39.09% | 36.26% |
| 226 | 0.440507 | 0.110444 | - | - | - | - |
| 227 | 0.462585 | 0.086849 | - | - | - | - |
| 228 | 0.464464 | 0.099195 | - | - | - | - |
| 229 | 0.453179 | 0.095138 | - | - | - | - |
| 230 | 0.428900 | 0.086575 | 0.571276 | 0.557274 | 39.38% | 36.26% |
| 231 | 0.449149 | 0.117980 | - | - | - | - |
| 232 | 0.479225 | 0.087899 | - | - | - | - |
| 233 | 0.434656 | 0.094851 | - | - | - | - |
| 234 | 0.446849 | 0.091662 | - | - | - | - |
| 235 | 0.432204 | 0.095340 | 0.566205 | 0.569236 | 38.53% | 38.81% |
| 236 | 0.455701 | 0.103980 | - | - | - | - |
| 237 | 0.410698 | 0.103055 | - | - | - | - |
| 238 | 0.416737 | 0.072494 | - | - | - | - |
| 239 | 0.421124 | 0.095982 | - | - | - | - |
| 240 | 0.412790 | 0.100480 | 0.564655 | 0.564471 | 38.53% | 38.24% |
| 241 | 0.444691 | 0.075214 | - | - | - | - |
| 242 | 0.427718 | 0.090173 | - | - | - | - |
| 243 | 0.456081 | 0.068258 | - | - | - | - |
| 244 | 0.410340 | 0.074628 | - | - | - | - |
| 245 | 0.386393 | 0.075032 | 0.568173 | 0.557623 | 38.81% | 37.39% |
| 246 | 0.428195 | 0.083083 | - | - | - | - |
| 247 | 0.412171 | 0.071511 | - | - | - | - |
| 248 | 0.401920 | 0.083914 | - | - | - | - |
| 249 | 0.396383 | 0.088061 | - | - | - | - |
| 250 | 0.429855 | 0.102235 | 0.564091 | 0.562807 | 38.81% | 37.68% |
| 251 | 0.384683 | 0.092889 | - | - | - | - |
| 252 | 0.449209 | 0.078550 | - | - | - | - |
| 253 | 0.387152 | 0.076333 | - | - | - | - |
| 254 | 0.430479 | 0.100087 | - | - | - | - |
| 255 | 0.395445 | 0.084266 | 0.566442 | 0.560359 | 39.66% | 37.11% |
| 256 | 0.431775 | 0.080215 | - | - | - | - |
| 257 | 0.413838 | 0.122733 | - | - | - | - |
| 258 | 0.418753 | 0.063067 | - | - | - | - |
| 259 | 0.433684 | 0.077917 | - | - | - | - |
| 260 | 0.400901 | 0.080330 | 0.560858 | 0.559187 | 37.96% | 36.26% |
| 261 | 0.411193 | 0.076484 | - | - | - | - |
| 262 | 0.380303 | 0.087470 | - | - | - | - |
| 263 | 0.392418 | 0.101372 | - | - | - | - |
| 264 | 0.421151 | 0.085552 | - | - | - | - |
| 265 | 0.399338 | 0.078536 | 0.559623 | 0.559905 | 38.24% | 35.98% |
| 266 | 0.410407 | 0.073889 | - | - | - | - |
| 267 | 0.442461 | 0.079210 | - | - | - | - |
| 268 | 0.398721 | 0.069037 | - | - | - | - |
| 269 | 0.367722 | 0.085579 | - | - | - | - |
| 270 | 0.404279 | 0.112131 | 0.562800 | 0.563849 | 38.81% | 36.26% |
| 271 | 0.403510 | 0.097169 | - | - | - | - |
| 272 | 0.382423 | 0.100688 | - | - | - | - |
| 273 | 0.410624 | 0.094881 | - | - | - | - |
| 274 | 0.339341 | 0.063367 | - | - | - | - |
| 275 | 0.394352 | 0.091509 | 0.569790 | 0.554393 | 39.66% | 37.11% |
| 276 | 0.326469 | 0.072649 | - | - | - | - |
| 277 | 0.359006 | 0.064155 | - | - | - | - |
| 278 | 0.401389 | 0.082146 | - | - | - | - |
| 279 | 0.385742 | 0.098061 | - | - | - | - |
| 280 | 0.371930 | 0.064951 | 0.564420 | 0.556193 | 39.66% | 35.69% |
| 281 | 0.414920 | 0.074283 | - | - | - | - |
| 282 | 0.368609 | 0.056122 | - | - | - | - |
| 283 | 0.358255 | 0.065922 | - | - | - | - |
| 284 | 0.409146 | 0.087353 | - | - | - | - |
| 285 | 0.422491 | 0.085338 | 0.563296 | 0.559306 | 37.96% | 36.83% |
| 286 | 0.348962 | 0.074552 | - | - | - | - |
| 287 | 0.360918 | 0.053600 | - | - | - | - |
| 288 | 0.370676 | 0.076569 | - | - | - | - |
| 289 | 0.374713 | 0.064515 | - | - | - | - |
| 290 | 0.397351 | 0.097530 | 0.567363 | 0.561620 | 37.68% | 37.11% |
| 291 | 0.347286 | 0.072591 | - | - | - | - |
| 292 | 0.389930 | 0.078760 | - | - | - | - |
| 293 | 0.406011 | 0.065202 | - | - | - | - |
| 294 | 0.321045 | 0.071102 | - | - | - | - |
| 295 | 0.377777 | 0.073493 | 0.555758 | 0.559571 | 37.96% | 36.54% |
| 296 | 0.375554 | 0.077724 | - | - | - | - |
| 297 | 0.384721 | 0.060036 | - | - | - | - |
| 298 | 0.346636 | 0.089298 | - | - | - | - |
| 299 | 0.348758 | 0.070799 | - | - | - | - |
| 300 | 0.391355 | 0.099989 | 0.558299 | 0.562843 | 37.11% | 36.83% |

### Verification and next scientific requirement

The clone-contained verifier reproduces every original feature, mask, target,
checkpoint prediction, train-only normalization, class weight, selection and
aggregate without fitting. A separate arithmetic checker reconstructs all
169,344 static/temporal feature components from the original pose observations
and exact source clocks, verifies masks/targets and applies the selected saved
linear weights directly to independently recompute all 784 predictions per arm
and all train/validation headline metrics. This is independent calculation of
the fixed recipe, not independent semantic truth or a new model experiment.

Independent feature/prediction receipt SHA256: `2fa6a8b0c7ed35723402e05c649f2f24808cbaa646151b0b359b542875ac177d`. The original real Store job is durably completed; original input seals and annotations remain unchanged. Detailed rows, coordinates, weights and labels remain private.

Further development must preserve this result and use source-reviewed actor/scene
truth, broader balanced supervision and an independent source holdout before
claiming improved unseen accuracy or app promotion. Shuttle/contact/rally-end
accuracy, doubles identity and complete full-match annotation remain unresolved.
