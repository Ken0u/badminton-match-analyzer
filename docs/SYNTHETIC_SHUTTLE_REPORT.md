# Procedural synthetic shuttle adaptation

Owning task: [issue #305](https://github.com/Ken0u/badminton-match-analyzer/issues/305), under [localization roadmap #65](https://github.com/Ken0u/badminton-match-analyzer/issues/65).

**The single synthetic-only candidate does not demonstrate useful synthetic localization generalization and is not promoted.** On the untouched generated test, selected localization falls from 11/282 visible frames to 1/282; both variants produce false observations on all 102 negative frames. The installed model, 512x288 geometry and threshold 0.5 remain unchanged. This is a negative research result; software validation and procedural labels do not establish complete badminton annotation accuracy.

The prospectively fixed familiar-source comparison localizes 16/25 visible cases for the candidate and 14/25 for the unchanged control. These familiar labels are diagnostic only, not training/selection inputs or independent expert truth. All 60 cases and 28 unknowns remain.

## Fixed learning and evaluation sequence

The [public protocol](../data/manifests/shuttle_synthetic_protocol_v1.json) and exact code were timestamped before native model work. Own procedural RGB sources contain perspective lines, geometric actors/rackets, moving distractors and a bright parabolic shuttle with radius/intensity/blur variation and explicit absence/occlusion. There are 160 independent 24-frame source groups, split as 128 training, 16 validation and 16 test, with disjoint SHA-derived group seeds. The background is the uint8 median of the complete generated source. Coordinates describe the generated shuttle trajectory head; they do not certify physical badminton contacts or expert source truth.

One fixed pretrained initialization underwent four epochs at batch size one, fixed seed 20261025, AdamW learning rate/weight decay 0.0001, gradient norm clip 1, CUDA float16 autocast and float32 master parameters. Only the final decoder convolution weights and output weight/bias train. BatchNorm affine tensors/statistics and every other tensor stay frozen. Targets are sigma-1.5 truncated Gaussians with zero targets for absence/occlusion; the loss equally averages positive support and complementary pixel squared errors, retaining empty-positive frames.

Each epoch visits every training source once using the fixed group order/chunk schedule. Every validation source contributes its three disjoint eight-frame chunks. Minimum mean validation loss selects an epoch, earliest on ties. Epoch 4 was selected and sealed before the generated test opened once. Both variants then processed all 24 frames of every test source with the actual overlapping ensemble and observed-only selector. No alternate seed, loss, checkpoint selection, retest or result-driven recipe follows from the negative result.

No broadcast image, crop, label or downloaded texture enters training or selection. The familiar original source packet is used only afterward for the frozen diagnostic comparison; its four eligibility flags remain false. No consumed holdout was accessed, no new image assessment occurred, and no experimental checkpoint was installed.

## Training and untouched generated test

| Epoch | Mean training loss | Mean validation loss | Selected |
| --- | ---: | ---: | --- |
| 1 | 0.02725207 | 0.02002374 | no |
| 2 | 0.02351035 | 0.01584125 | no |
| 3 | 0.01707990 | 0.01065265 | no |
| 4 | 0.01388509 | 0.00903592 | yes |

| Generated test measure | Default control | Selected candidate |
| --- | ---: | ---: |
| All frames | 384 | 384 |
| Visible/negative denominator: visible | 282 | 282 |
| Visible/negative denominator: negative | 102 | 102 |
| Visibility TP | 282 | 282 |
| Visibility FP | 102 | 102 |
| Visibility FN | 0 | 0 |
| Visibility TN | 0 | 0 |
| Localization TP | 11 | 1 |
| Localization FP | 373 | 383 |
| Localization FN | 271 | 281 |
| Localization TN | 0 | 0 |
| Displaced visible outputs | 271 | 281 |
| Any agreeing observed component | 155 | 175 |
| Mean error over predicted visible pairs (px) | 183.525 | 191.741 |

Each variant makes 272 generated-test model calls. Visibility and localization are distinct: a displaced point counts as both localization FP and FN. More agreeing components alone does not establish successful selected localization. Generated group separation supplies a procedural test, not independent real-video generalization.

## Familiar-source control and diagnostic outcome

Both variants process all 50 complete original camera/background views and 13,499 output view rows, not only target neighborhoods. Original native PTS, display orientation, source identity, complete-view median backgrounds, cut/scene resets, temporal context and observed component selection are preserved. Rows are view rows, not unique frames or every decode operation.

The unchanged control reproduces original physical frame/PTS/camera/geometry/component/visibility/selection fields with zero differences before candidate real inference. Confidence alone uses absolute tolerance 0.00001 and relative tolerance zero. Historical comparison omits exactly the four prospectively declared selector-dependency fields; full current ancestry and scene resets are separately validated on every row. Legacy resolution/tiling protocols keep their original strict validation.

All 60 original cases remain: 25 localizable visible, 7 supported negatives and 28 unknown; no visible-unlocalizable truth or unavailable output occurs in this completed comparison. Unknowns stay unscored, retained in coverage. Difficulty groups overlap. Localization tolerance is 0.005 source diagonal; uncertainty bounds use frozen radial source-label uncertainty and are not statistical confidence intervals.

| Familiar diagnostic measure | Default control | Selected candidate |
| --- | ---: | ---: |
| Correct selected localization / known visible | 14/25 | 16/25 |
| Visibility TP/FP/FN/TN | 15/3/10/4 | 17/4/8/3 |
| Visibility precision/recall/F1 | 0.833/0.600/0.698 | 0.810/0.680/0.739 |
| Localization TP/FP/FN/TN | 14/4/11/4 | 16/5/9/3 |
| Localization precision/recall/F1 | 0.778/0.560/0.651 | 0.762/0.640/0.696 |
| Mean predicted-visible pair error (px) | 32.429 | 28.444 |
| Uncertainty-straddling cases | 7 | 8 |
| Localization recall uncertainty bounds | 0.280-0.560 | 0.320-0.640 |
| Displaced visible outputs | 1 | 1 |
| Missing observation on known visible | 10 | 8 |
| Any agreeing observed component | 14 | 16 |
| No agreeing observed component | 11 | 9 |
| Component-present selection failures | 0 | 0 |
| Complete camera views | 50 | 50 |
| Native output view rows | 13499 | 13499 |
| Actual model calls | 13149 | 13149 |
| Summed view elapsed seconds | 1407.031 | 1608.798 |
| Peak GPU tensor allocation (decimal MB) | 385.400 | 385.400 |

Times are observations on the RTX 3050 Ti Laptop GPU with incidental unrelated graphics load; they are not a controlled speed benchmark. Tensor allocation excludes other process/driver memory. Mean coordinate error conditions on predicted-positive pairs and includes displaced outliers.

## Complete group denominators

| Group | Cases | Visible/negative/unknown |
| --- | ---: | ---: |
| all | 60 | 25/7/28 |
| availability/no | 0 | 0/0/0 |
| availability/yes | 60 | 25/7/28 |
| difficulty/blur | 28 | 14/0/14 |
| difficulty/camera_transition | 0 | 0/0/0 |
| difficulty/distractor | 29 | 9/0/20 |
| difficulty/fast_flight | 7 | 7/0/0 |
| difficulty/non_play | 14 | 4/7/3 |
| difficulty/occlusion | 0 | 0/0/0 |
| difficulty/ordinary | 1 | 1/0/0 |
| difficulty/small_far | 18 | 10/0/8 |
| difficulty/unresolved | 28 | 0/0/28 |
| disagreement/no | 20 | 5/7/8 |
| disagreement/yes | 40 | 20/0/20 |
| selection/known_gap | 10 | 4/0/6 |
| selection/uniform | 50 | 21/7/22 |
| source/970dbd8adfe548d8 | 35 | 18/3/14 |
| source/c406a1187130b845 | 25 | 7/4/14 |
| state/not_visible | 7 | 0/7/0 |
| state/unknown | 28 | 0/0/28 |
| state/visible | 25 | 25/0/0 |
| state/visible_unlocalizable | 0 | 0/0/0 |

## Complete group visibility

| Group | Control TP/FP/FN/TN | Candidate TP/FP/FN/TN | Control precision/recall/F1 | Candidate precision/recall/F1 |
| --- | ---: | ---: | ---: | ---: |
| all | 15/3/10/4 | 17/4/8/3 | 0.833/0.600/0.698 | 0.810/0.680/0.739 |
| availability/no | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined |
| availability/yes | 15/3/10/4 | 17/4/8/3 | 0.833/0.600/0.698 | 0.810/0.680/0.739 |
| difficulty/blur | 9/0/5/0 | 10/0/4/0 | 1.000/0.643/0.783 | 1.000/0.714/0.833 |
| difficulty/camera_transition | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined |
| difficulty/distractor | 5/0/4/0 | 5/0/4/0 | 1.000/0.556/0.714 | 1.000/0.556/0.714 |
| difficulty/fast_flight | 6/0/1/0 | 6/0/1/0 | 1.000/0.857/0.923 | 1.000/0.857/0.923 |
| difficulty/non_play | 2/3/2/4 | 2/4/2/3 | 0.400/0.500/0.444 | 0.333/0.500/0.400 |
| difficulty/occlusion | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined |
| difficulty/ordinary | 0/0/1/0 | 1/0/0/0 | undefined/0.000/0.000 | 1.000/1.000/1.000 |
| difficulty/small_far | 8/0/2/0 | 8/0/2/0 | 1.000/0.800/0.889 | 1.000/0.800/0.889 |
| difficulty/unresolved | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined |
| disagreement/no | 4/3/1/4 | 5/4/0/3 | 0.571/0.800/0.667 | 0.556/1.000/0.714 |
| disagreement/yes | 11/0/9/0 | 12/0/8/0 | 1.000/0.550/0.710 | 1.000/0.600/0.750 |
| selection/known_gap | 2/0/2/0 | 2/0/2/0 | 1.000/0.500/0.667 | 1.000/0.500/0.667 |
| selection/uniform | 13/3/8/4 | 15/4/6/3 | 0.812/0.619/0.703 | 0.789/0.714/0.750 |
| source/970dbd8adfe548d8 | 10/2/8/1 | 11/2/7/1 | 0.833/0.556/0.667 | 0.846/0.611/0.710 |
| source/c406a1187130b845 | 5/1/2/3 | 6/2/1/2 | 0.833/0.714/0.769 | 0.750/0.857/0.800 |
| state/not_visible | 0/3/0/4 | 0/4/0/3 | 0.000/undefined/0.000 | 0.000/undefined/0.000 |
| state/unknown | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined |
| state/visible | 15/0/10/0 | 17/0/8/0 | 1.000/0.600/0.750 | 1.000/0.680/0.810 |
| state/visible_unlocalizable | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined |

## Complete group localization and component support

| Group | Control TP/FP/FN/TN | Candidate TP/FP/FN/TN | Control precision/recall/F1 | Candidate precision/recall/F1 | Agreeing components control/candidate | Recall uncertainty control/candidate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 14/4/11/4 | 16/5/9/3 | 0.778/0.560/0.651 | 0.762/0.640/0.696 | 14/25 / 16/25 | 0.280-0.560 / 0.320-0.640 |
| availability/no | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| availability/yes | 14/4/11/4 | 16/5/9/3 | 0.778/0.560/0.651 | 0.762/0.640/0.696 | 14/25 / 16/25 | 0.280-0.560 / 0.320-0.640 |
| difficulty/blur | 8/1/6/0 | 9/1/5/0 | 0.889/0.571/0.696 | 0.900/0.643/0.750 | 8/14 / 9/14 | 0.071-0.571 / 0.143-0.643 |
| difficulty/camera_transition | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| difficulty/distractor | 4/1/5/0 | 4/1/5/0 | 0.800/0.444/0.571 | 0.800/0.444/0.571 | 4/9 / 4/9 | 0.222-0.444 / 0.222-0.444 |
| difficulty/fast_flight | 5/1/2/0 | 5/1/2/0 | 0.833/0.714/0.769 | 0.833/0.714/0.769 | 5/7 / 5/7 | 0.143-0.714 / 0.143-0.714 |
| difficulty/non_play | 2/3/2/4 | 2/4/2/3 | 0.400/0.500/0.444 | 0.333/0.500/0.400 | 2/4 / 2/4 | 0.000-0.500 / 0.250-0.500 |
| difficulty/occlusion | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| difficulty/ordinary | 0/0/1/0 | 1/0/0/0 | undefined/0.000/0.000 | 1.000/1.000/1.000 | 0/1 / 1/1 | 0.000-0.000 / 0.000-1.000 |
| difficulty/small_far | 8/0/2/0 | 8/0/2/0 | 1.000/0.800/0.889 | 1.000/0.800/0.889 | 8/10 / 8/10 | 0.700-0.800 / 0.700-0.800 |
| difficulty/unresolved | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| disagreement/no | 4/3/1/4 | 5/4/0/3 | 0.571/0.800/0.667 | 0.556/1.000/0.714 | 4/5 / 5/5 | 0.400-0.800 / 0.600-1.000 |
| disagreement/yes | 10/1/10/0 | 11/1/9/0 | 0.909/0.500/0.645 | 0.917/0.550/0.688 | 10/20 / 11/20 | 0.250-0.500 / 0.250-0.550 |
| selection/known_gap | 2/0/2/0 | 2/0/2/0 | 1.000/0.500/0.667 | 1.000/0.500/0.667 | 2/4 / 2/4 | 0.000-0.500 / 0.000-0.500 |
| selection/uniform | 12/4/9/4 | 14/5/7/3 | 0.750/0.571/0.649 | 0.737/0.667/0.700 | 12/21 / 14/21 | 0.333-0.571 / 0.381-0.667 |
| source/970dbd8adfe548d8 | 10/2/8/1 | 11/2/7/1 | 0.833/0.556/0.667 | 0.846/0.611/0.710 | 10/18 / 11/18 | 0.278-0.556 / 0.333-0.611 |
| source/c406a1187130b845 | 4/2/3/3 | 5/3/2/2 | 0.667/0.571/0.615 | 0.625/0.714/0.667 | 4/7 / 5/7 | 0.286-0.571 / 0.286-0.714 |
| state/not_visible | 0/3/0/4 | 0/4/0/3 | 0.000/undefined/0.000 | 0.000/undefined/0.000 | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| state/unknown | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| state/visible | 14/1/11/0 | 16/1/9/0 | 0.933/0.560/0.700 | 0.941/0.640/0.762 | 14/25 / 16/25 | 0.280-0.560 / 0.320-0.640 |
| state/visible_unlocalizable | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |

## Paired aggregate outcome transitions

| Control outcome | Candidate outcome | Cases |
| --- | --- | ---: |
| correct_absence | correct_absence | 3 |
| correct_absence | false_detection | 1 |
| correct_localization | correct_localization | 14 |
| false_detection | false_detection | 3 |
| localization_error | localization_error | 1 |
| miss | correct_localization | 2 |
| miss | miss | 8 |

## Provenance, software validation and limits

Separate CPU inspection of all 104 serialized checkpoint tensors verifies exactly four allowed tensors changed and the other 100 match original contiguous bytes, including signed zero. Shapes/dtypes match and values are finite. This audit constructed no model, ran no forward/optimizer, initialized no CUDA context and opened no source labels. The earlier value-equality receipt remains preserved; the stronger byte-level audit receipt SHA256 is `2342ade292b7aa724be4fcda53b69f6b3c53d2e1efbe8399155b512c0b711393`.

An independent metadata-only lineage audit confirms all 160 split seeds are distinct, all 128 train groups and 16 validation groups are retained, validation group hashes match across all four epochs, and both test variants use identical pixels and procedural labels for all 16 test groups / 384 rows. All four checkpoint hashes and earliest-minimum validation selection match. No generation, model loading or metric recomputation occurred in this audit. Receipt SHA256 `ae3ff89a6dab5a5dfbe3d5df0aec09e70e80998d87957efd75d700162d5b8a57`.

Each native stage uses original shared Store admission under the committed GPU grant. Exact process lifetimes and admission/terminal records were checked privately before each transition and before final sealing. An observed timeout never establishes exit. Detailed operational metadata, source images, labels, predictions and candidate weights stay ignored locally. The original application metadata, annotation history, predictions and installed checkpoint remain unchanged.

The [prospective freeze](https://github.com/Ken0u/badminton-match-analyzer/issues/305#issuecomment-6401847972) precedes native work. The [terminal raw-output commitment](https://github.com/Ken0u/badminton-match-analyzer/issues/305#issuecomment-6402476886) precedes the sole familiar diagnostic scoring. Experiment `516ce8e313a1f84e2f116ef62776b3faea4cd12160767ff5be6f18651204d56a`; protocol `f2f788d4b72359446d367786055b7e902f9b3240fb0229c62ce793d1f4ea6a2a`; selected checkpoint `6713dcdb72a243feba9b1a084283b15d13b387bc7b539a3d00230b43863a93ff`; raw index `b341c2756fd0dc7e225f29463bce6a5024bd66a03b9d540d50e1caeeda06f8d7`; aggregate report `cc24d21671723c177a0a82c43604e282221be952fe787897c5340d4fe024b4c4`. All 81 frozen consumer files match tested committed source and copied bytes.

Local validation: **4,658 full Python tests pass**, with four optional skips; 154 focused tests and required Ruff, format, dependency, repository and whitespace checks pass. Recorded verification lifetimes are independently terminal. The first launcher referenced a nonexistent legacy test file and exited before tests; the corrected launcher and original evidence remain. Source bytes stayed fixed throughout native execution. The earlier rejected public checkpoint payload was replaced with aggregate/hash-only text; private process identifiers were not published by it.

The public source archive includes the new protocol explicitly through MANIFEST.in. Exact final-head PR/main CI, controller integration and independent complete public package/source/frontend/lock/all 47 public protocol/both image descriptor verification remain required; completion checkpoints belong on issue #305. Build checks and advertised image descriptor availability do not establish container layer bytes/runtime or annotation accuracy.

A separate source-inventory preflight confirms all 47 public manifests are explicitly declared without data wildcards, both new research modules occur among 97 tracked runtime files, and the six additional source-archive paths are declared. It performed no build, artifact execution or installation; actual final archive membership and byte parity remain separate requirements. Preflight receipt SHA256 `0047bd6825d0d2a1809854795efbe40390fa7367c272b6ba5dd60f8d140897f6`.

The small familiar two-source diagnostic is not expert truth or an independent test. Zero-support difficulty groups and 28 unknowns remain. Synthetic generated coordinates cannot certify real shuttle detection, contacts, serve/end times, identities or forehand/backhand shot labels. Complete scientific rally references remain **0/2**, all four source eligibility flags remain false, and #65/#62/#66/#67/#71 remain incomplete. Broader eligible source-aligned supervision and independent full-match validation remain necessary. No model/default promotion or further result-driven variant is authorized by this result.
