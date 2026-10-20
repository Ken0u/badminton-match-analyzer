# Fixed TrackNet resolution development comparison

Owning task: [issue 141](https://github.com/Ken0u/badminton-match-analyzer/issues/141), under [localization milestone 65](https://github.com/Ken0u/badminton-match-analyzer/issues/65). Completed native comparison, October 20, 2026: **768x432 does not improve overall localization or observed-component recall and is not promoted.** Both fixed variants localize 14/25 known visible shuttles. The larger input reduces false visibility detections from 3 to 2, but loses one correct localization while recovering another, increases conditional coordinate error and costs substantially more time and memory. The application default remains 512x288. Milestone 65 remains open; this is familiar development evidence, not unseen or full-match accuracy.

## Frozen method and coverage

The [source-only visibility audit](SHUTTLE_VISIBILITY_REPORT.md) found ten visible misses with no observed component at the unchanged 0.5 threshold. Its wrong-location true shuttle was also absent from the component list. Re-ranking existing components cannot recover these missing components. The [public protocol](../data/manifests/shuttle_resolution_protocol_v1.json) therefore compares exactly 512x288 and 768x432, with the same TrackNet checkpoint, sequence length 8, CUDA float16 and threshold 0.5. No weights were trained, downloaded or installed; no labels, thresholds, uncertainty radii or variants were tuned after predictions.

All 60 cases remain: 25 known localizable visible, 7 confirmed not visible and 28 unknown. There are zero visible-unlocalizable cases and zero unavailable outputs. Labels were independently agent-assessed from source before baseline predictions were opened in task 139; they are not expert-certified or held-out truth. Fifty cases were uniformly sampled and ten selected for known development gaps. Difficulty tags overlap. Occlusion and camera-transition groups have zero support, with undefined scores.

Each variant processed all 50 original complete target camera/background views (25 per source) and produced 13,499 native view rows. This is the count of output rows across views, not unique source frames or all decode operations: median-background passes, overlapping ensemble windows and seek preroll add work. The 512 control reproduced every baseline row's frame/PTS/camera/geometry/point/component/context structure with zero differences; confidence alone had the predeclared absolute tolerance 0.00001 and zero relative tolerance. Original-baseline and control target metrics agree exactly in every reported group. The gate passed before any 768 inference or scoring.

Localization uses the fixed 0.005 source-diagonal tolerance (7.343 pixels for these 1280x720 sources). A wrong-location prediction contributes both FP and FN. Visibility scores only presence/absence and can therefore improve without localization improving. Unknown truth stays outside known-label accuracy denominators while remaining in the coverage tables. Missing outputs would remain unavailable, not negatives or omitted cases. Radial label uncertainty supplies lower/upper recall bounds; it is not tuned to prediction error.

## Overall outcome and cost

| Measure | 512x288 control / original | 768x432 candidate |
| --- | ---: | ---: |
| Correct localization / known visible | 14/25 | 14/25 |
| Visibility TP/FP/FN/TN | 15/3/10/4 | 16/2/9/5 |
| Visibility precision / recall / F1 | 0.833 / 0.600 / 0.698 | 0.889 / 0.640 / 0.744 |
| Localization TP/FP/FN/TN | 14/4/11/4 | 14/4/11/5 |
| Localization precision / recall / F1 | 0.778 / 0.560 / 0.651 | 0.778 / 0.560 / 0.651 |
| Correct absence / known absent | 4/7 | 5/7 |
| Wrong-location visible predictions | 1 | 2 |
| No selected detection on visible cases | 10 | 9 |
| True-shuttle component present / absent | 14 / 11 | 14 / 11 |
| Nominal component-present selection failures | 0 | 0 |
| Coordinate error, mean over visible predicted pairs | 32.429 px (15 pairs) | 72.073 px (16 pairs) |
| Uncertainty-straddling cases | 7 | 7 |
| Localization recall bounds | 0.280-0.560 | 0.280-0.560 |
| Nominal correct frames / 32 known cases | 18/32 | 19/32 |
| Complete views / native view rows | 50 / 13,499 | 50 / 13,499 |
| Sum of per-view native inference elapsed time | 1,134.979 s | 1,959.932 s |
| Whole admitted attempt elapsed time | 1,154.316 s | 1,979.245 s |
| Peak GPU tensor allocation (decimal MB) | 385.4 | 778.6 |

The candidate takes 1.727 times the summed native inference time and 2.020 times the peak tensor allocation on the same RTX 3050 Ti Laptop GPU (4 GB, driver 581.80). Tensor allocation is not whole-process GPU memory. Runtime includes each complete view's processing, not only the 60 scored target frames. The two coordinate means condition on different predicted-positive sets and include wrong-location outliers; neither is an unconditional localization-error estimate.

Among known cases, one visible miss becomes correct, one correct localization becomes a miss, one visible miss becomes a wrong-location detection, and one false detection becomes correct absence. Both variants have 11 nominally absent true-shuttle components; all 14 nominally present true components are selected correctly. Thus this fixed resolution change does not remove the aggregate component-recall bottleneck. Blur localization falls from 8/14 to 7/14; small/far localization rises from 8/10 to 9/10. The uniform sample falls from 12/21 to 11/21 correct visible localizations; the four known-visible gap cases rise from 2/4 to 3/4. These small, overlapping development subgroups do not justify model promotion or a new tuning round on this packet.

## Complete group denominators

V/A/U means localizable visible / confirmed absent / unknown. Visible-unlocalizable and output-unavailable counts are zero in every group for both variants. The availability grouping describes baseline availability; both variants also have full output availability. No group or unknown case was removed.

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

## Complete group visibility and localization

Confusion counts are TP/FP/FN/TN. Counts include wrong-location FP+FN for localization. All metrics below use the unchanged protocol; undefined means no applicable support, not a zero score. Source/singles is `970dbd8adfe548d8`; source/doubles is `c406a1187130b845`.

| Group | Visibility 512 | Visibility 768 | Visibility F1 512 / 768 |
| --- | ---: | ---: | ---: |
| all | 15/3/10/4 | 16/2/9/5 | 0.698 / 0.744 |
| availability/no | 0/0/0/0 | 0/0/0/0 | undefined / undefined |
| availability/yes | 15/3/10/4 | 16/2/9/5 | 0.698 / 0.744 |
| difficulty/blur | 9/0/5/0 | 9/0/5/0 | 0.783 / 0.783 |
| difficulty/camera_transition | 0/0/0/0 | 0/0/0/0 | undefined / undefined |
| difficulty/distractor | 5/0/4/0 | 6/0/3/0 | 0.714 / 0.800 |
| difficulty/fast_flight | 6/0/1/0 | 6/0/1/0 | 0.923 / 0.923 |
| difficulty/non_play | 2/3/2/4 | 2/2/2/5 | 0.444 / 0.500 |
| difficulty/occlusion | 0/0/0/0 | 0/0/0/0 | undefined / undefined |
| difficulty/ordinary | 0/0/1/0 | 0/0/1/0 | 0.000 / 0.000 |
| difficulty/small_far | 8/0/2/0 | 9/0/1/0 | 0.889 / 0.947 |
| difficulty/unresolved | 0/0/0/0 | 0/0/0/0 | undefined / undefined |
| disagreement/no | 4/3/1/4 | 4/2/1/5 | 0.667 / 0.727 |
| disagreement/yes | 11/0/9/0 | 12/0/8/0 | 0.710 / 0.750 |
| selection/known_gap | 2/0/2/0 | 3/0/1/0 | 0.667 / 0.857 |
| selection/uniform | 13/3/8/4 | 13/2/8/5 | 0.703 / 0.722 |
| source/singles | 10/2/8/1 | 11/1/7/2 | 0.667 / 0.733 |
| source/doubles | 5/1/2/3 | 5/1/2/3 | 0.769 / 0.769 |
| state/not_visible | 0/3/0/4 | 0/2/0/5 | 0.000 / 0.000 |
| state/unknown | 0/0/0/0 | 0/0/0/0 | undefined / undefined |
| state/visible | 15/0/10/0 | 16/0/9/0 | 0.750 / 0.780 |
| state/visible_unlocalizable | 0/0/0/0 | 0/0/0/0 | undefined / undefined |

Component counts are true-shuttle component-present / known-visible cases. Bounds are radial-uncertainty localization recall lower-upper, not confidence intervals. All nominally present components were selected correctly in both variants, including every subgroup.

| Group | Localization 512 | Localization 768 | Localization F1 512 / 768 | Component 512 / 768 | Recall bounds 512 / 768 |
| --- | ---: | ---: | ---: | ---: | ---: |
| all | 14/4/11/4 | 14/4/11/5 | 0.651 / 0.651 | 14/25 / 14/25 | 0.280-0.560 / 0.280-0.560 |
| availability/no | 0/0/0/0 | 0/0/0/0 | undefined / undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| availability/yes | 14/4/11/4 | 14/4/11/5 | 0.651 / 0.651 | 14/25 / 14/25 | 0.280-0.560 / 0.280-0.560 |
| difficulty/blur | 8/1/6/0 | 7/2/7/0 | 0.696 / 0.609 | 8/14 / 7/14 | 0.071-0.571 / 0.000-0.500 |
| difficulty/camera_transition | 0/0/0/0 | 0/0/0/0 | undefined / undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| difficulty/distractor | 4/1/5/0 | 5/1/4/0 | 0.571 / 0.667 | 4/9 / 5/9 | 0.222-0.444 / 0.333-0.556 |
| difficulty/fast_flight | 5/1/2/0 | 5/1/2/0 | 0.769 / 0.769 | 5/7 / 5/7 | 0.143-0.714 / 0.000-0.714 |
| difficulty/non_play | 2/3/2/4 | 2/2/2/5 | 0.444 / 0.500 | 2/4 / 2/4 | 0.000-0.500 / 0.000-0.500 |
| difficulty/occlusion | 0/0/0/0 | 0/0/0/0 | undefined / undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| difficulty/ordinary | 0/0/1/0 | 0/0/1/0 | 0.000 / 0.000 | 0/1 / 0/1 | 0.000-0.000 / 0.000-0.000 |
| difficulty/small_far | 8/0/2/0 | 9/0/1/0 | 0.889 / 0.947 | 8/10 / 9/10 | 0.700-0.800 / 0.700-0.900 |
| difficulty/unresolved | 0/0/0/0 | 0/0/0/0 | undefined / undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| disagreement/no | 4/3/1/4 | 4/2/1/5 | 0.667 / 0.727 | 4/5 / 4/5 | 0.400-0.800 / 0.400-0.800 |
| disagreement/yes | 10/1/10/0 | 10/2/10/0 | 0.645 / 0.625 | 10/20 / 10/20 | 0.250-0.500 / 0.250-0.500 |
| selection/known_gap | 2/0/2/0 | 3/0/1/0 | 0.667 / 0.857 | 2/4 / 3/4 | 0.000-0.500 / 0.250-0.750 |
| selection/uniform | 12/4/9/4 | 11/4/10/5 | 0.649 / 0.611 | 12/21 / 11/21 | 0.333-0.571 / 0.286-0.524 |
| source/singles | 10/2/8/1 | 10/2/8/2 | 0.667 / 0.667 | 10/18 / 10/18 | 0.278-0.556 / 0.278-0.556 |
| source/doubles | 4/2/3/3 | 4/2/3/3 | 0.615 / 0.615 | 4/7 / 4/7 | 0.286-0.571 / 0.286-0.571 |
| state/not_visible | 0/3/0/4 | 0/2/0/5 | 0.000 / 0.000 | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| state/unknown | 0/0/0/0 | 0/0/0/0 | undefined / undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |
| state/visible | 14/1/11/0 | 14/2/11/0 | 0.700 / 0.683 | 14/25 / 14/25 | 0.280-0.560 / 0.280-0.560 |
| state/visible_unlocalizable | 0/0/0/0 | 0/0/0/0 | undefined / undefined | 0/0 / 0/0 | undefined-undefined / undefined-undefined |

## Execution, recovery and evidence

The portable runner is `scripts/compare_shuttle_resolution.py`. Its `freeze` command verifies the original source/label/native-cache graph and seals the protocol, all 56 consumer source files, installed runtime versions, GPU/driver inventory and complete native target views. This run used Python 3.10.5, Torch 2.8.0+cu126, torchvision 0.23.0+cu126, NumPy 2.2.6, PyAV 16.1.0, Pillow 12.3.0 and OpenCV 4.14.0.94. The experiment/source bytes were frozen and [publicly timestamped before native predictions](https://github.com/Ken0u/badminton-match-analyzer/issues/141#issuecomment-6287921113). Executed consumer bytes match implementation commit `bd7537ed108adec363685cce0af584e75a049c32`; the final report changes documentation only.

Pin `BADMINTON_ROOT` to the original input root, `BADMINTON_DATA_DIR` to its real `data/processed` shared Store and `BADMINTON_WEIGHTS_DIR` to the original `models/weights` before imports. The frozen native cache supplies comparison inputs, never job admission. Both native jobs used actual shared `run_local_job` admission plus the genuine queue GPU reservation, torchvision initialization before threaded PyAV, and existing native FFmpeg restoration. PID lifetime, creation time, working directory, command, admission and terminal receipts bind each actual Store registration. Both original process lifetimes have exited; Store jobs `8c148e36c8b64c9ea092feb5f80b3477` and `644e6b322f57469a8643e56841d5e415` are completed. Nothing was stopped, adopted or restarted on a timeout.

The [complete control gate was recorded before the candidate launch](https://github.com/Ken0u/badminton-match-analyzer/issues/141#issuecomment-6288310455). After both workers exited, an external checksum index sealed all 100 native run files, 100 completed-view manifests and nine admission/terminal/device/gate/prior-lifetime documents. Its hash was [publicly timestamped before first candidate aggregate scoring](https://github.com/Ken0u/badminton-match-analyzer/issues/141#issuecomment-6288895491). The exact frozen `report` CLI then verified inputs, code and output seals before and after scoring. The external index binds raw candidate bytes because the report JSON carries aggregate results without repeating every candidate file seal. Raw sources, labels, weights, outputs and receipts remain ignored and are not supplied by a clone.

| Evidence | SHA-256 |
| --- | --- |
| Source inventory | `273e0749d148e952ad1fb0534363b3971e2584702f834ad2084c59e632990822` |
| Source packet | `3b22c07a3592728b6aa17e7d7c28f0089a8820b1373ace1289796d2e99e5466d` |
| Frozen labels | `fd25029ae49891f544989cdbfa20e5077571c1048c960e2d77ddee1fe7abd158` |
| Original native baseline index | `915f678fa2b5577dff37811ba92ff9077c300eefc788fcab2873c12c2ffc6f64` |
| TrackNet checkpoint | `df867641a02712b021f04548ff4b1208ddfdb47f629ab2094ceb978667e83b1a` |
| Public protocol | `95aaf88d546d8f8c72fb5483e36f12037286e8091c85f1a962eed554ca3d30cc` |
| Frozen experiment | `fffbc3a767eab9ab63b95b1978c447cd9edca0ba5ceed26579e6c46330941ef8` |
| Complete control gate | `9193cedcf9daf3df79106fc38d1dadb86e814dbcb1d98c847df02e25425eea4f` |
| Pre-scoring output index (209 files) | `8c7daa0f10fbbffdf604fbf989967f5cb66823fd8a087123169ec6bb1705b012` |
| Exact frozen CLI report | `b0fd6fc7cd723401f2588e526567925e5ad85be5f1bd6b830d62d641991f9b36` |

Generated regression checks caught a torn checkpoint publication and a valid relative-path CLI freeze being rejected before inference. Checkpoints now flush/fsync pending bytes and publish exclusively with an atomic hard link, preserving interrupted pending artifacts and existing final evidence; input verification normalizes paths before checking containment. Twenty-three resolution tests and the complete 1,376-test suite pass (four optional GPU skips). Ruff, formatting, dependency and diff checks pass; exact-final-head CI and independent review are tracked on the PR rather than inferred from these local results.

No application labels, original predictions, caches, source files, weights or defaults were overwritten. No consumed holdout-63 inputs or metadata were accessed. This experiment does not establish accuracy for unseen matches, persistent identities, serves, rally boundaries or strokes. The next localization evidence needs genuinely supported occlusions, broader source-separated singles/doubles cases and independent full-match validation before any promotion. Keep milestone 65 open.
