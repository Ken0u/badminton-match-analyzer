# Fixed overlapping-tile shuttle development comparison

Owning task: [issue #299](https://github.com/Ken0u/badminton-match-analyzer/issues/299), under [localization roadmap #65](https://github.com/Ken0u/badminton-match-analyzer/issues/65).
Completed native comparison, October 25, 2026: **the fixed tiling recipe does not improve localization or observed-component recall and is rejected for advancement.** Both variants localize 14/25 known visible shuttles. Tiling reduces false observations on supported negatives from 3/7 to 2/7, but increases displaced visible outputs from one to two and costs four times the model calls. The application stays at full frame 512x288 and threshold 0.5. This is familiar agent-labeled development evidence, not expert or unseen full-match truth.

The [public protocol](../data/manifests/shuttle_tiling_protocol_v1.json) fixed exactly two variants before predictions. Control uses unchanged 512x288 full-frame inference. Candidate resizes source RGB and the native-resolution complete-view median background to 768x432, crops four 512x288 tiles at (0,0), (256,0), (0,144), (256,144), and pixelwise max-fuses their heatmaps before unchanged temporal ensemble, components and selector. Checkpoint, length-eight sequences, CUDA float16 and threshold 0.5 remain fixed. No additional recipe, training, tuning, interpolation or image assessment follows from these results.

All 60 original cases remain: 25 localizable visible, 7 supported negatives, 28 unknown, zero visible-unlocalizable cases and zero unavailable outputs. Each variant processed all 50 original complete camera/background views and 13,499 output rows; these are view rows, not unique frames or all decode operations. Unknown truth remains unscored in accuracy denominators and retained in coverage. Overlapping difficulty groups do not form disjoint samples. Localization tolerance remains 0.005 source diagonal; wrong locations contribute both FP and FN. Uncertainty bounds use frozen radial source-label uncertainty and are not statistical confidence intervals.

The control reproduced every original physical frame/PTS/camera/geometry/point/component field with zero differences before candidate inference. Confidence alone used absolute tolerance 0.00001, relative 0. Exactly four prospectively named new dependency fields were omitted from historical comparison; full current selector ancestry and scene resets were independently replayed on every row. The legacy resolution protocol retains its strict gate. Original source, labels, application annotations and predictions, environments, checkpoint and all 78 executed consumer files remain unchanged.

## Overall outcome and observed cost

| Measure | Full-frame control | Four-tile candidate |
| --- | ---: | ---: |
| Correct localization / known visible | 14/25 | 14/25 |
| Visibility TP/FP/FN/TN | 15/3/10/4 | 16/2/9/5 |
| Visibility precision/recall/F1 | 0.833/0.600/0.698 | 0.889/0.640/0.744 |
| Localization TP/FP/FN/TN | 14/4/11/4 | 14/4/11/5 |
| Localization precision/recall/F1 | 0.778/0.560/0.651 | 0.778/0.560/0.651 |
| Coordinate error mean over predicted visible pairs (px) | 32.429 | 72.039 |
| Uncertainty-straddling cases | 7 | 7 |
| Localization recall uncertainty bounds | 0.280-0.560 | 0.280-0.560 |
| Displaced visible outputs | 1 | 2 |
| No selected observation on known visible | 10 | 9 |
| Observed true component present/absent | 14/11 | 14/11 |
| Component-present selection failures | 0 | 0 |
| Native output view rows | 13,499 | 13,499 |
| Actual sequence windows | 13,149 | 13,149 |
| Actual model calls | 13,149 | 52,596 |
| Sum of native view elapsed seconds | 1644.015 | 5051.468 |
| Peak GPU tensor allocation (decimal MB) | 385.400 | 385.400 |
| Whole admitted attempt elapsed seconds | 1665.307 | 5072.507 |

Timing is observational on the RTX 3050 Ti Laptop GPU (4 GB) under incidental unrelated graphics load. Candidate/control elapsed ratio is 3.073; this is not a controlled speed benchmark. Tensor allocation is not whole-process GPU memory. Coordinate means condition on different predicted-positive sets and include displaced outliers.

One visible miss becomes a correct localization, one correct localization becomes a miss, and another visible miss becomes a displaced detection. One false observation becomes correct absence. Both variants retain 14 agreeing observed components and zero component-present selection failures; the remaining eleven known visible cases have no agreeing stored component. Uniform-sample localizations fall from 12/21 to 11/21, while known-gap localizations rise from 2/4 to 3/4. Blur falls from 8/14 to 7/14; small/far rises from 8/10 to 9/10. These small, overlapping familiar groups do not justify advancement or an additional result-driven variant. Broader aligned supervision and source-separated validation remain necessary.

## Complete group denominators

Source/singles is `970dbd8adfe548d8`; source/doubles is `c406a1187130b845`. V/A/U means localizable visible/supported negative/unknown. Visible-unlocalizable and output-unavailable counts are zero in every group in both variants. Difficulty groups overlap. Undefined values mean no applicable support.

| Group | Cases | V/A/U |
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
| source/singles | 35 | 18/3/14 |
| source/doubles | 25 | 7/4/14 |
| state/not_visible | 7 | 0/7/0 |
| state/unknown | 28 | 0/0/28 |
| state/visible | 25 | 25/0/0 |
| state/visible_unlocalizable | 0 | 0/0/0 |

## Complete group visibility

Confusions are TP/FP/FN/TN. Precision/recall/F1 and localization are separate; presence alone is not localization.

| Group | Control confusion | Candidate confusion | Precision/recall/F1 control | Precision/recall/F1 candidate |
| --- | ---: | ---: | ---: | ---: |
| all | 15/3/10/4 | 16/2/9/5 | 0.833/0.600/0.698 | 0.889/0.640/0.744 |
| availability/no | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined |
| availability/yes | 15/3/10/4 | 16/2/9/5 | 0.833/0.600/0.698 | 0.889/0.640/0.744 |
| difficulty/blur | 9/0/5/0 | 9/0/5/0 | 1.000/0.643/0.783 | 1.000/0.643/0.783 |
| difficulty/camera_transition | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined |
| difficulty/distractor | 5/0/4/0 | 6/0/3/0 | 1.000/0.556/0.714 | 1.000/0.667/0.800 |
| difficulty/fast_flight | 6/0/1/0 | 6/0/1/0 | 1.000/0.857/0.923 | 1.000/0.857/0.923 |
| difficulty/non_play | 2/3/2/4 | 2/2/2/5 | 0.400/0.500/0.444 | 0.500/0.500/0.500 |
| difficulty/occlusion | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined |
| difficulty/ordinary | 0/0/1/0 | 0/0/1/0 | undefined/0.000/0.000 | undefined/0.000/0.000 |
| difficulty/small_far | 8/0/2/0 | 9/0/1/0 | 1.000/0.800/0.889 | 1.000/0.900/0.947 |
| difficulty/unresolved | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined |
| disagreement/no | 4/3/1/4 | 4/2/1/5 | 0.571/0.800/0.667 | 0.667/0.800/0.727 |
| disagreement/yes | 11/0/9/0 | 12/0/8/0 | 1.000/0.550/0.710 | 1.000/0.600/0.750 |
| selection/known_gap | 2/0/2/0 | 3/0/1/0 | 1.000/0.500/0.667 | 1.000/0.750/0.857 |
| selection/uniform | 13/3/8/4 | 13/2/8/5 | 0.812/0.619/0.703 | 0.867/0.619/0.722 |
| source/singles | 10/2/8/1 | 11/1/7/2 | 0.833/0.556/0.667 | 0.917/0.611/0.733 |
| source/doubles | 5/1/2/3 | 5/1/2/3 | 0.833/0.714/0.769 | 0.833/0.714/0.769 |
| state/not_visible | 0/3/0/4 | 0/2/0/5 | 0.000/undefined/0.000 | 0.000/undefined/0.000 |
| state/unknown | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined |
| state/visible | 15/0/10/0 | 16/0/9/0 | 1.000/0.600/0.750 | 1.000/0.640/0.780 |
| state/visible_unlocalizable | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined |

## Complete group localization and component support

Component counts are observed true component present/known localizable visible. A selected displaced point counts as both FP and FN. Bounds are frozen radial-uncertainty localization recall lower-upper.

| Group | Control confusion | Candidate confusion | Precision/recall/F1 control | Precision/recall/F1 candidate | Component control/candidate | Recall bounds control/candidate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 14/4/11/4 | 14/4/11/5 | 0.778/0.560/0.651 | 0.778/0.560/0.651 | 14/25 / 14/25 | 0.280-0.560 / 0.280-0.560 |
| availability/no | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| availability/yes | 14/4/11/4 | 14/4/11/5 | 0.778/0.560/0.651 | 0.778/0.560/0.651 | 14/25 / 14/25 | 0.280-0.560 / 0.280-0.560 |
| difficulty/blur | 8/1/6/0 | 7/2/7/0 | 0.889/0.571/0.696 | 0.778/0.500/0.609 | 8/14 / 7/14 | 0.071-0.571 / 0.000-0.500 |
| difficulty/camera_transition | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| difficulty/distractor | 4/1/5/0 | 5/1/4/0 | 0.800/0.444/0.571 | 0.833/0.556/0.667 | 4/9 / 5/9 | 0.222-0.444 / 0.333-0.556 |
| difficulty/fast_flight | 5/1/2/0 | 5/1/2/0 | 0.833/0.714/0.769 | 0.833/0.714/0.769 | 5/7 / 5/7 | 0.143-0.714 / 0.000-0.714 |
| difficulty/non_play | 2/3/2/4 | 2/2/2/5 | 0.400/0.500/0.444 | 0.500/0.500/0.500 | 2/4 / 2/4 | 0.000-0.500 / 0.000-0.500 |
| difficulty/occlusion | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| difficulty/ordinary | 0/0/1/0 | 0/0/1/0 | undefined/0.000/0.000 | undefined/0.000/0.000 | 0/1 / 0/1 | 0.000-0.000 / 0.000-0.000 |
| difficulty/small_far | 8/0/2/0 | 9/0/1/0 | 1.000/0.800/0.889 | 1.000/0.900/0.947 | 8/10 / 9/10 | 0.700-0.800 / 0.700-0.900 |
| difficulty/unresolved | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| disagreement/no | 4/3/1/4 | 4/2/1/5 | 0.571/0.800/0.667 | 0.667/0.800/0.727 | 4/5 / 4/5 | 0.400-0.800 / 0.400-0.800 |
| disagreement/yes | 10/1/10/0 | 10/2/10/0 | 0.909/0.500/0.645 | 0.833/0.500/0.625 | 10/20 / 10/20 | 0.250-0.500 / 0.250-0.500 |
| selection/known_gap | 2/0/2/0 | 3/0/1/0 | 1.000/0.500/0.667 | 1.000/0.750/0.857 | 2/4 / 3/4 | 0.000-0.500 / 0.250-0.750 |
| selection/uniform | 12/4/9/4 | 11/4/10/5 | 0.750/0.571/0.649 | 0.733/0.524/0.611 | 12/21 / 11/21 | 0.333-0.571 / 0.286-0.524 |
| source/singles | 10/2/8/1 | 10/2/8/2 | 0.833/0.556/0.667 | 0.833/0.556/0.667 | 10/18 / 10/18 | 0.278-0.556 / 0.278-0.556 |
| source/doubles | 4/2/3/3 | 4/2/3/3 | 0.667/0.571/0.615 | 0.667/0.571/0.615 | 4/7 / 4/7 | 0.286-0.571 / 0.286-0.571 |
| state/not_visible | 0/3/0/4 | 0/2/0/5 | 0.000/undefined/0.000 | 0.000/undefined/0.000 | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| state/unknown | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| state/visible | 14/1/11/0 | 14/2/11/0 | 0.933/0.560/0.700 | 0.875/0.560/0.683 | 14/25 / 14/25 | 0.280-0.560 / 0.280-0.560 |
| state/visible_unlocalizable | 0/0/0/0 | 0/0/0/0 | undefined/undefined/undefined | undefined/undefined/undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |

## Aggregate outcome transitions

These are paired known-case counts, not new labels or independent validation.

| Control outcome | Candidate outcome | Cases |
| --- | --- | ---: |
| correct_absence | correct_absence | 4 |
| correct_localization | correct_localization | 13 |
| correct_localization | miss | 1 |
| false_detection | correct_absence | 1 |
| false_detection | false_detection | 2 |
| localization_error | localization_error | 1 |
| miss | correct_localization | 1 |
| miss | localization_error | 1 |
| miss | miss | 8 |

## Provenance, software checks and limitations

The prospective freeze and terminal control/candidate receipts are checkpointed on #299. Real shared Store admission and current queue GPU ownership were used; original process lifetimes were independently verified terminal. Raw outputs were independently hashed and publicly timestamped before the sole frozen scoring stage. No raw video, image, label, prediction, checkpoint or credential is published.

Experiment SHA256 `d2a848ad17b20314da8e723d3da213736202a471532bdf114c0b7837a31a4098`; protocol `23d5c71bf0cc69be6d5ca8f80184f7dff4dc74a548d23891d2557c4c3ee1445b`; raw index `d9a595e37d26bf45231837eb59a669ccbe36aeb2d7b7c63960675b6ac93b4b11`; aggregate report `fff6a4f82c668edbec710b8c35f837aebdc21ec25b95f3c6ba085d9485fc0c5b`. The [raw-seal checkpoint](https://github.com/Ken0u/badminton-match-analyzer/issues/299#issuecomment-6399637889) precedes scoring.

Local validation: 4,605 full Python tests pass/four optional skips, 171 focused tests; required Ruff/format/pip/repository/diff checks pass. Packaging omission of the new public protocol was independently reproduced in an actual source archive, repaired with one explicit MANIFEST.in include, and verified in actual wheel/sdist bytes for all 46 public manifests. All 12 checks passed on packaging head `5e442cf`, including hosted clean-installed wheel/sdist and HTTP ownership/delivery. Final report-head CI/controller integration, merged-main checks and independent public delivery must be verified before declaring task delivery.

The familiar two-source packet is not expert gold truth or a held-out evaluation; zero-support camera-transition/occlusion groups and 28 unknowns remain. No full-match or scientific eligibility is inferred from software checks, same-model agreement, processing coverage or this experiment. Complete-rally references remain 0/2 and all four eligibility flags remain false. Roadmap #65 and full automatic singles/doubles contacts, serve/end, identities and stroke annotation accuracy remain open.
