# Fixed shuttle learning capacity comparison

Owning task: [#311](https://github.com/Ken0u/badminton-match-analyzer/issues/311), under
[localization roadmap #65](https://github.com/Ken0u/badminton-match-analyzer/issues/65).

**The fresh synthetic comparison is complete; the real-source comparison is incomplete
after interruption. No model is promoted.** Selected localization on the new generated
test is parent 1/262 visible frames, decoder 0/262 and convolution 13/262. Every method
produces false detections on all 122 negative frames. These results do not demonstrate
useful automatic shuttle localization or independent full-match accuracy. Application
defaults and installed weights remain unchanged.

## Frozen design and completed synthetic stages

The [public protocol](../data/manifests/shuttle_capacity_protocol_v1.json) fixes
namespace `synthetic-shuttle-capacity-v1`: 160 independently seeded 24-frame groups, 128
training/16 validation/16 test. Every SHA-derived seed differs from the historical #305
namespace. The independently versioned generator preserves the same owned procedural
distributions: perspective court lines, geometric actors/rackets, moving distractors and
a bright parabolic shuttle with radius/intensity/blur variation and explicit
absence/occlusion. Backgrounds are complete-source uint8 medians. Generated coordinates
describe procedural geometry, not expert badminton truth.

Two separately initialized recipes start from the pinned original parent: decoder
updates two up_block_3 convolution weights and predictor weight/bias (four tensors);
convolution updates all 17 convolution weights and predictor weight/bias (19 tensors).
Every BatchNorm affine parameter/statistic stays frozen and modules remain in eval mode.
Both use seed 20261025, identical order, four epochs, batch 1, AdamW learning
rate/weight decay 0.0001, gradient clip 1 and CUDA float16 autocast/GradScaler with
float32 parameters. Targets are sigma 1.5/support 4.5 Gaussian maps; balanced
support/complement squared error retains negative frames. Each epoch uses the fixed
cyclic eight-frame chunk per training group.

All 16 validation groups contribute all three disjoint chunks every epoch. Each recipe
selects minimum mean validation loss with earliest ties. Both independently selected
epoch 4; their hashes were publicly sealed before any new test generation. One test
reports all three methods on identical 16 complete groups/384 frames, with actual
overlapping ensemble and observed component selector, geometry 512x288/threshold 0.5. No
recipe, checkpoint choice, threshold or winner selection changed from test results.

| Method | Epoch | Training loss | Validation loss | Selected |
| --- | ---: | ---: | ---: | --- |
| decoder | 1 | 0.02568641 | 0.02413684 | no |
| decoder | 2 | 0.02058698 | 0.02045843 | no |
| decoder | 3 | 0.01532090 | 0.01565328 | no |
| decoder | 4 | 0.01358337 | 0.01255525 | yes |
| convolution | 1 | 0.01231885 | 0.00719203 | no |
| convolution | 2 | 0.00652023 | 0.00555828 | no |
| convolution | 3 | 0.00470328 | 0.00481534 | no |
| convolution | 4 | 0.00471578 | 0.00457621 | yes |

## Complete new generated test

| Measure | Parent | Decoder | Convolution |
| --- | ---: | ---: | ---: |
| frames | 384 | 384 | 384 |
| visible | 262 | 262 | 262 |
| negative | 122 | 122 | 122 |
| visibility tp | 262 | 262 | 262 |
| visibility fp | 122 | 122 | 122 |
| visibility fn | 0 | 0 | 0 |
| visibility tn | 0 | 0 | 0 |
| localization tp | 1 | 0 | 13 |
| localization fp | 383 | 384 | 371 |
| localization fn | 261 | 262 | 249 |
| localization tn | 0 | 0 | 0 |
| displaced | 261 | 262 | 249 |
| component agrees | 49 | 54 | 236 |
| mean error predicted visible px | 204.638 | 207.057 | 213.266 |

Each method makes 272 model calls. Displaced observed points count as both localization
FP and FN. Visibility, an agreeing component anywhere in the heatmap and the selected
component are separate measures. Mean error conditions on predicted-visible pairs and
includes displaced outliers; it is not an all-frame accuracy metric. The broader recipe
increases agreeing components, while selected localization and negative discrimination
remain poor. No result-driven selection or promotion follows.

## Interrupted real-source comparison and complete denominators

The planned parent control covers 50 complete original camera/background views/13499
view rows before either learned real-source method may run. The chain was interrupted
after 18 complete views/5436 rows; 32 views/8063 rows remain unprocessed. Its durable
exit code is 1073807364 (0x40010004). This code alone does not identify the cause. The
original worker terminal receipt is absent. Original-host inspection independently
confirmed every observed process lifetime absent before the stale running job was
changed to interrupted using `Store.recover_jobs`. No process was stopped or restarted
during recovery, no missing terminal was rewritten as success and all existing artifacts
are preserved.

All 18 complete control-view receipts pass source/model/PTS/camera/geometry and
selector-dependency validation. Partial physical comparison records 0 differences using
the frozen confidence absolute tolerance 0.00001/relative 0 and declared physical
projection. This partial comparison does not establish full control reproduction: the
full gate correctly refuses the 32 missing views. Both learned real-source variants
remain unstarted, with 50/50 views and 13499/13499 rows unavailable for each.

All 60 familiar cases remain in the planned denominator: 25 localizable visible, seven
supported negatives and 28 unknown. No familiar case is scored, and no partial available
subset or unknown label is converted into a negative. No familiar accuracy, group
metric, uncertainty bound or paired transition table is reported. Original
PTS/orientation/cut/scene/full-view background and physical-selection provenance remain
in preserved outputs. All four source eligibility flags remain false. Complete
scientific rally references remain 0/2.

The original four-hour deadline and 4 GiB output cap were preserved across ownership
recovery. Remaining control plus both learned full-view runs cannot fit the remaining
original clock; the incomplete outcome is retained instead of extending the clock,
changing recipes or reducing denominators. The planned selected-checkpoint CPU byte
audit and complete raw-output seal/scoring stages were not reached. Training receipts
record frozen tensor hashes and generated tests verify frozen BatchNorm behavior, but no
independent byte audit of the trained selected checkpoints is claimed.

## Verification, provenance and delivery

Local checks: **4907 full Python tests pass**, four optional skips; 194 focused tests
and required Ruff/format/dependency/repository/diff checks pass. Actual tiny-input
TrackNet updates verify exactly 4/19 eligible tensors with frozen BN; tests cover fresh
seed separation, loss/ties, both selections before test generation, identical test
inputs, tampering before decode, historical #305/default dispatch, complete negatives,
Store admission, native clock/provenance, control gating and one-shot test/scoring
outputs. Initial stale harness filename exited before tests; unknown-recipe validation
ordering and import sorting were corrected before final checks. Scientific executable
bytes remained fixed afterward.

Independent metadata auditing confirms 160 distinct fresh seeds with zero historical
overlap, identical 128 train/16 validation inputs across methods, validation hashes
stable across four epochs, all eight checkpoint hashes, both minimum-validation
selections and identical 16 test groups/384 frames for all three methods. This audit
generated no pixels, loaded no model and performed no familiar scoring. All 84 frozen
consumers match tested, committed and copied bytes.

Completed training/test stages and the interrupted control used genuine shared Store
admission and original-host GPU/data reservations. Original two-source app metadata,
saved annotations, predictions and installed model bytes remain unchanged. Images,
labels, weights, raw outputs and detailed operational receipts stay private/ignored. No
new image transfer/download/assessor, paid service, original-source training, historical
#305 selected-checkpoint/test access or consumed #63 holdout access occurred.

[Prospective source/protocol/runtime
freeze](https://github.com/Ken0u/badminton-match-analyzer/issues/311#issuecomment-6404348005);
[both selections before
test](https://github.com/Ken0u/badminton-match-analyzer/issues/311#issuecomment-6404431164).
Source `0d999657847913200042733ffe735156bf1922cc`; experiment
`780374cc379534d853680bafa0159bcad7d6ee5783f942a616a9dd00a40d40f3`; protocol
`b507610fef6183b9e1d80ab50ba923acaa2f89e87408912fb3c1b85b3a196389`; new test
`fb7824a1d23336fabaf0af018cae267dcdd951ef8882432aaa7e238402db33c8`; group audit
`7286feda50f948a57bf3da34a9898a972c01f23792d4cbf72cf750893254715c`; original-host
interruption recovery
`64e96991cd7c69cc1ff583d7d3ccf9236d2cb1893ceb073620dde3795fd23521`; incomplete native
audit `3a7f5f2b9bb1a1b313f75dd3b37f91ee70a5f4c4cc11e929f62efaf3bc98897e`. No complete
raw seal or familiar-scoring report exists.

Source inventory preflight confirms 100 runtime files and 48 public manifests, with
explicit inclusion of the new protocol and all previous manifests. It proves source
declarations only. Exact final-head PR/main CI, controller integration and independent
complete public source/wheel/frontend/lock/all 48-manifest/both image
manifest/config/descriptor verification remain delivery requirements. Artifacts are
never installed or executed during verification; descriptor availability does not prove
layer bytes, runtime or image-source parity.

This is a bounded incomplete research result, not full-match accuracy. Generated labels
and familiar-source agent labels cannot certify shuttle localization, contacts,
serve/end times, persistent player identities or forehand/backhand shot labels on unseen
matches. Roadmap 65/62/66/67/71 remain incomplete. No model/default promotion or further
result-driven recipe is authorized by this result.
