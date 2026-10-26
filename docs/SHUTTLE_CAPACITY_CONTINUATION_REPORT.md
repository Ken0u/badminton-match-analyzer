# Remaining real-source shuttle capacity diagnostics

Task [#313](https://github.com/Ken0u/badminton-match-analyzer/issues/313), under [localization roadmap #65](https://github.com/Ken0u/badminton-match-analyzer/issues/65).

The fixed remaining real-source comparison is complete. All three methods are reported without choosing or promoting one. These are familiar-source development diagnostics against agent labels; they do not establish independent badminton accuracy. Installed weights and application defaults remain unchanged. Complete scientific rally references remain **0/2**.

## Preserved predecessor and fixed continuation

The [predecessor report](SHUTTLE_CAPACITY_REPORT.md), original experiment and expired deadline remain unchanged. Its generated test remains negative: selected localization parent 1/262, decoder 0/262 and convolution 13/262, with false detections on all 122 negatives for every method. That test, training and selections were not repeated. The original real-source worker terminal is absent and its recovered Store job remains interrupted. This continuation does not recast that historical job as successful.

The [continuation protocol](../data/manifests/shuttle_capacity_continuation_protocol_v1.json) binds all 84 predecessor consumer files, the two unchanged epoch-4 validation-selected checkpoints, original source/native clocks, full-view median backgrounds, camera/scene boundaries and current selector dependencies. Its 86 consumer files were frozen before selected-tensor reads or inference. The new four-hour deadline starts at the original committed #313 grant; lease renewals do not restart it. The cumulative 4 GiB limit includes retained #311 outputs and failures.

A separately admitted CPU audit reads every selected tensor against the original parent: 104 exact names/shapes/dtypes and finite values per method. Decoder changes exactly four eligible tensors and preserves 100 byte-identical tensors; convolution changes exactly 19 and preserves 85. All BatchNorm affine parameters and buffers remain byte-identical. The audit constructs no model and executes no forward pass or optimizer.

The parent control references exactly 18 inherited complete views / 5,436 rows under their original hashes and interrupted-job provenance, then computes only the remaining 32 views / 8,063 rows. Across all 50 views / 13,499 rows, original physical observations reproduce with zero differences before either learned variant runs. Confidence uses absolute tolerance 0.00001 / relative 0. Exactly four declared selector-dependency fields are projected historically while their current context is independently validated; legacy strict controls are unchanged.

Both fixed learned methods then process all 50 identical full camera/background views with native 512×288 input, sequence length eight, CUDA float16, actual overlapping ensemble and observed component selector at threshold 0.5. No source, recipe, checkpoint, threshold or method selection follows from these outcomes. Each method retains 13,499 view rows and 13,149 model calls; these are not unique source frames or every decode operation.

## Complete familiar-source diagnostic

All 60 cases remain: 25 localizable visible, seven supported negatives and 28 unknown. All outputs are available; no visible-unlocalizable case occurs here. Unknowns remain unscored. Localization tolerance is 0.005 of the source diagonal, and displaced outputs count as both FP and FN. Radial-uncertainty recall bounds describe label sensitivity, not statistical confidence intervals. Mean error conditions on predicted-visible pairs and includes displaced outliers.

| Measure | Parent | Decoder | Convolution |
| --- | ---: | ---: | ---: |
| visibility TP/FP/FN/TN | 15/3/10/4 | 17/4/8/3 | 23/6/2/1 |
| visibility precision/recall/F1 | 0.833/0.600/0.698 | 0.810/0.680/0.739 | 0.793/0.920/0.852 |
| localization TP/FP/FN/TN | 14/4/11/4 | 16/5/9/3 | 9/20/16/1 |
| localization precision/recall/F1 | 0.778/0.560/0.651 | 0.762/0.640/0.696 | 0.310/0.360/0.333 |
| Mean predicted-visible error (px) | 32.429 | 28.415 | 219.129 |
| Uncertainty-straddling cases | 7 | 9 | 5 |
| Localization recall uncertainty bounds | 0.280–0.560 | 0.280–0.640 | 0.160–0.360 |
| Agreeing observed components | 14 | 16 | 17 |
| No agreeing component | 11 | 9 | 8 |
| View inference seconds | 1293.718 | 1163.218 | 1165.301 |
| Peak GPU tensor allocation (decimal MB) | 385.400 | 385.400 | 385.400 |

Parent cost includes inherited view timings; these are observed timings on an RTX 3050 Ti laptop under incidental graphics load, not a controlled speed comparison. Tensor allocation excludes driver and other-process memory.

## Overlapping group accounting

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

Groups overlap and do not represent independent samples. Zero-support groups remain with undefined rates.

### Group visibility

| Group | Method | TP/FP/FN/TN | Precision/recall/F1 | Agreeing components/visible | Recall uncertainty bounds |
| --- | --- | ---: | ---: | ---: | ---: |
| all | control | 15/3/10/4 | 0.833/0.600/0.698 | 14/25 | 0.280–0.560 |
| all | decoder | 17/4/8/3 | 0.810/0.680/0.739 | 16/25 | 0.280–0.640 |
| all | convolution | 23/6/2/1 | 0.793/0.920/0.852 | 17/25 | 0.160–0.360 |
| availability/no | control | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| availability/no | decoder | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| availability/no | convolution | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| availability/yes | control | 15/3/10/4 | 0.833/0.600/0.698 | 14/25 | 0.280–0.560 |
| availability/yes | decoder | 17/4/8/3 | 0.810/0.680/0.739 | 16/25 | 0.280–0.640 |
| availability/yes | convolution | 23/6/2/1 | 0.793/0.920/0.852 | 17/25 | 0.160–0.360 |
| difficulty/blur | control | 9/0/5/0 | 1.000/0.643/0.783 | 8/14 | 0.071–0.571 |
| difficulty/blur | decoder | 10/0/4/0 | 1.000/0.714/0.833 | 9/14 | 0.071–0.643 |
| difficulty/blur | convolution | 12/0/2/0 | 1.000/0.857/0.923 | 10/14 | 0.143–0.429 |
| difficulty/camera_transition | control | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/camera_transition | decoder | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/camera_transition | convolution | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/distractor | control | 5/0/4/0 | 1.000/0.556/0.714 | 4/9 | 0.222–0.444 |
| difficulty/distractor | decoder | 5/0/4/0 | 1.000/0.556/0.714 | 4/9 | 0.222–0.444 |
| difficulty/distractor | convolution | 8/0/1/0 | 1.000/0.889/0.941 | 5/9 | 0.000–0.000 |
| difficulty/fast_flight | control | 6/0/1/0 | 1.000/0.857/0.923 | 5/7 | 0.143–0.714 |
| difficulty/fast_flight | decoder | 6/0/1/0 | 1.000/0.857/0.923 | 5/7 | 0.143–0.714 |
| difficulty/fast_flight | convolution | 6/0/1/0 | 1.000/0.857/0.923 | 6/7 | 0.143–0.286 |
| difficulty/non_play | control | 2/3/2/4 | 0.400/0.500/0.444 | 2/4 | 0.000–0.500 |
| difficulty/non_play | decoder | 2/4/2/3 | 0.333/0.500/0.400 | 2/4 | 0.000–0.500 |
| difficulty/non_play | convolution | 4/6/0/1 | 0.400/1.000/0.571 | 2/4 | 0.250–0.500 |
| difficulty/occlusion | control | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/occlusion | decoder | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/occlusion | convolution | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/ordinary | control | 0/0/1/0 | undefined/0.000/0.000 | 0/1 | 0.000–0.000 |
| difficulty/ordinary | decoder | 1/0/0/0 | 1.000/1.000/1.000 | 1/1 | 0.000–1.000 |
| difficulty/ordinary | convolution | 1/0/0/0 | 1.000/1.000/1.000 | 1/1 | 0.000–1.000 |
| difficulty/small_far | control | 8/0/2/0 | 1.000/0.800/0.889 | 8/10 | 0.700–0.800 |
| difficulty/small_far | decoder | 8/0/2/0 | 1.000/0.800/0.889 | 8/10 | 0.700–0.800 |
| difficulty/small_far | convolution | 10/0/0/0 | 1.000/1.000/1.000 | 8/10 | 0.300–0.400 |
| difficulty/unresolved | control | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/unresolved | decoder | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/unresolved | convolution | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| disagreement/no | control | 4/3/1/4 | 0.571/0.800/0.667 | 4/5 | 0.400–0.800 |
| disagreement/no | decoder | 5/4/0/3 | 0.556/1.000/0.714 | 5/5 | 0.400–1.000 |
| disagreement/no | convolution | 5/6/0/1 | 0.455/1.000/0.625 | 5/5 | 0.400–0.600 |
| disagreement/yes | control | 11/0/9/0 | 1.000/0.550/0.710 | 10/20 | 0.250–0.500 |
| disagreement/yes | decoder | 12/0/8/0 | 1.000/0.600/0.750 | 11/20 | 0.250–0.550 |
| disagreement/yes | convolution | 18/0/2/0 | 1.000/0.900/0.947 | 12/20 | 0.100–0.300 |
| selection/known_gap | control | 2/0/2/0 | 1.000/0.500/0.667 | 2/4 | 0.000–0.500 |
| selection/known_gap | decoder | 2/0/2/0 | 1.000/0.500/0.667 | 2/4 | 0.000–0.500 |
| selection/known_gap | convolution | 4/0/0/0 | 1.000/1.000/1.000 | 3/4 | 0.000–0.000 |
| selection/uniform | control | 13/3/8/4 | 0.812/0.619/0.703 | 12/21 | 0.333–0.571 |
| selection/uniform | decoder | 15/4/6/3 | 0.789/0.714/0.750 | 14/21 | 0.333–0.667 |
| selection/uniform | convolution | 19/6/2/1 | 0.760/0.905/0.826 | 14/21 | 0.190–0.429 |
| source/970dbd8adfe548d8 | control | 10/2/8/1 | 0.833/0.556/0.667 | 10/18 | 0.278–0.556 |
| source/970dbd8adfe548d8 | decoder | 11/2/7/1 | 0.846/0.611/0.710 | 11/18 | 0.278–0.611 |
| source/970dbd8adfe548d8 | convolution | 16/2/2/1 | 0.889/0.889/0.889 | 11/18 | 0.222–0.389 |
| source/c406a1187130b845 | control | 5/1/2/3 | 0.833/0.714/0.769 | 4/7 | 0.286–0.571 |
| source/c406a1187130b845 | decoder | 6/2/1/2 | 0.750/0.857/0.800 | 5/7 | 0.286–0.714 |
| source/c406a1187130b845 | convolution | 7/4/0/0 | 0.636/1.000/0.778 | 6/7 | 0.000–0.286 |
| state/not_visible | control | 0/3/0/4 | 0.000/undefined/0.000 | 0/0 | undefined–undefined |
| state/not_visible | decoder | 0/4/0/3 | 0.000/undefined/0.000 | 0/0 | undefined–undefined |
| state/not_visible | convolution | 0/6/0/1 | 0.000/undefined/0.000 | 0/0 | undefined–undefined |
| state/unknown | control | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| state/unknown | decoder | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| state/unknown | convolution | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| state/visible | control | 15/0/10/0 | 1.000/0.600/0.750 | 14/25 | 0.280–0.560 |
| state/visible | decoder | 17/0/8/0 | 1.000/0.680/0.810 | 16/25 | 0.280–0.640 |
| state/visible | convolution | 23/0/2/0 | 1.000/0.920/0.958 | 17/25 | 0.160–0.360 |
| state/visible_unlocalizable | control | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| state/visible_unlocalizable | decoder | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| state/visible_unlocalizable | convolution | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |

### Group localization

| Group | Method | TP/FP/FN/TN | Precision/recall/F1 | Agreeing components/visible | Recall uncertainty bounds |
| --- | --- | ---: | ---: | ---: | ---: |
| all | control | 14/4/11/4 | 0.778/0.560/0.651 | 14/25 | 0.280–0.560 |
| all | decoder | 16/5/9/3 | 0.762/0.640/0.696 | 16/25 | 0.280–0.640 |
| all | convolution | 9/20/16/1 | 0.310/0.360/0.333 | 17/25 | 0.160–0.360 |
| availability/no | control | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| availability/no | decoder | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| availability/no | convolution | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| availability/yes | control | 14/4/11/4 | 0.778/0.560/0.651 | 14/25 | 0.280–0.560 |
| availability/yes | decoder | 16/5/9/3 | 0.762/0.640/0.696 | 16/25 | 0.280–0.640 |
| availability/yes | convolution | 9/20/16/1 | 0.310/0.360/0.333 | 17/25 | 0.160–0.360 |
| difficulty/blur | control | 8/1/6/0 | 0.889/0.571/0.696 | 8/14 | 0.071–0.571 |
| difficulty/blur | decoder | 9/1/5/0 | 0.900/0.643/0.750 | 9/14 | 0.071–0.643 |
| difficulty/blur | convolution | 6/6/8/0 | 0.500/0.429/0.462 | 10/14 | 0.143–0.429 |
| difficulty/camera_transition | control | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/camera_transition | decoder | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/camera_transition | convolution | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/distractor | control | 4/1/5/0 | 0.800/0.444/0.571 | 4/9 | 0.222–0.444 |
| difficulty/distractor | decoder | 4/1/5/0 | 0.800/0.444/0.571 | 4/9 | 0.222–0.444 |
| difficulty/distractor | convolution | 0/8/9/0 | 0.000/0.000/0.000 | 5/9 | 0.000–0.000 |
| difficulty/fast_flight | control | 5/1/2/0 | 0.833/0.714/0.769 | 5/7 | 0.143–0.714 |
| difficulty/fast_flight | decoder | 5/1/2/0 | 0.833/0.714/0.769 | 5/7 | 0.143–0.714 |
| difficulty/fast_flight | convolution | 2/4/5/0 | 0.333/0.286/0.308 | 6/7 | 0.143–0.286 |
| difficulty/non_play | control | 2/3/2/4 | 0.400/0.500/0.444 | 2/4 | 0.000–0.500 |
| difficulty/non_play | decoder | 2/4/2/3 | 0.333/0.500/0.400 | 2/4 | 0.000–0.500 |
| difficulty/non_play | convolution | 2/8/2/1 | 0.200/0.500/0.286 | 2/4 | 0.250–0.500 |
| difficulty/occlusion | control | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/occlusion | decoder | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/occlusion | convolution | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/ordinary | control | 0/0/1/0 | undefined/0.000/0.000 | 0/1 | 0.000–0.000 |
| difficulty/ordinary | decoder | 1/0/0/0 | 1.000/1.000/1.000 | 1/1 | 0.000–1.000 |
| difficulty/ordinary | convolution | 1/0/0/0 | 1.000/1.000/1.000 | 1/1 | 0.000–1.000 |
| difficulty/small_far | control | 8/0/2/0 | 1.000/0.800/0.889 | 8/10 | 0.700–0.800 |
| difficulty/small_far | decoder | 8/0/2/0 | 1.000/0.800/0.889 | 8/10 | 0.700–0.800 |
| difficulty/small_far | convolution | 4/6/6/0 | 0.400/0.400/0.400 | 8/10 | 0.300–0.400 |
| difficulty/unresolved | control | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/unresolved | decoder | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| difficulty/unresolved | convolution | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| disagreement/no | control | 4/3/1/4 | 0.571/0.800/0.667 | 4/5 | 0.400–0.800 |
| disagreement/no | decoder | 5/4/0/3 | 0.556/1.000/0.714 | 5/5 | 0.400–1.000 |
| disagreement/no | convolution | 3/8/2/1 | 0.273/0.600/0.375 | 5/5 | 0.400–0.600 |
| disagreement/yes | control | 10/1/10/0 | 0.909/0.500/0.645 | 10/20 | 0.250–0.500 |
| disagreement/yes | decoder | 11/1/9/0 | 0.917/0.550/0.688 | 11/20 | 0.250–0.550 |
| disagreement/yes | convolution | 6/12/14/0 | 0.333/0.300/0.316 | 12/20 | 0.100–0.300 |
| selection/known_gap | control | 2/0/2/0 | 1.000/0.500/0.667 | 2/4 | 0.000–0.500 |
| selection/known_gap | decoder | 2/0/2/0 | 1.000/0.500/0.667 | 2/4 | 0.000–0.500 |
| selection/known_gap | convolution | 0/4/4/0 | 0.000/0.000/0.000 | 3/4 | 0.000–0.000 |
| selection/uniform | control | 12/4/9/4 | 0.750/0.571/0.649 | 12/21 | 0.333–0.571 |
| selection/uniform | decoder | 14/5/7/3 | 0.737/0.667/0.700 | 14/21 | 0.333–0.667 |
| selection/uniform | convolution | 9/16/12/1 | 0.360/0.429/0.391 | 14/21 | 0.190–0.429 |
| source/970dbd8adfe548d8 | control | 10/2/8/1 | 0.833/0.556/0.667 | 10/18 | 0.278–0.556 |
| source/970dbd8adfe548d8 | decoder | 11/2/7/1 | 0.846/0.611/0.710 | 11/18 | 0.278–0.611 |
| source/970dbd8adfe548d8 | convolution | 7/11/11/1 | 0.389/0.389/0.389 | 11/18 | 0.222–0.389 |
| source/c406a1187130b845 | control | 4/2/3/3 | 0.667/0.571/0.615 | 4/7 | 0.286–0.571 |
| source/c406a1187130b845 | decoder | 5/3/2/2 | 0.625/0.714/0.667 | 5/7 | 0.286–0.714 |
| source/c406a1187130b845 | convolution | 2/9/5/0 | 0.182/0.286/0.222 | 6/7 | 0.000–0.286 |
| state/not_visible | control | 0/3/0/4 | 0.000/undefined/0.000 | 0/0 | undefined–undefined |
| state/not_visible | decoder | 0/4/0/3 | 0.000/undefined/0.000 | 0/0 | undefined–undefined |
| state/not_visible | convolution | 0/6/0/1 | 0.000/undefined/0.000 | 0/0 | undefined–undefined |
| state/unknown | control | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| state/unknown | decoder | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| state/unknown | convolution | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| state/visible | control | 14/1/11/0 | 0.933/0.560/0.700 | 14/25 | 0.280–0.560 |
| state/visible | decoder | 16/1/9/0 | 0.941/0.640/0.762 | 16/25 | 0.280–0.640 |
| state/visible | convolution | 9/14/16/0 | 0.391/0.360/0.375 | 17/25 | 0.160–0.360 |
| state/visible_unlocalizable | control | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| state/visible_unlocalizable | decoder | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |
| state/visible_unlocalizable | convolution | 0/0/0/0 | undefined/undefined/undefined | 0/0 | undefined–undefined |

## Paired outcomes

| Learned method | Parent outcome | Learned outcome | Cases |
| --- | --- | --- | ---: |
| decoder | correct_absence | correct_absence | 3 |
| decoder | correct_absence | false_detection | 1 |
| decoder | correct_localization | correct_localization | 14 |
| decoder | false_detection | false_detection | 3 |
| decoder | localization_error | localization_error | 1 |
| decoder | miss | correct_localization | 2 |
| decoder | miss | miss | 8 |
| convolution | correct_absence | correct_absence | 1 |
| convolution | correct_absence | false_detection | 3 |
| convolution | correct_localization | correct_localization | 7 |
| convolution | correct_localization | localization_error | 7 |
| convolution | false_detection | false_detection | 3 |
| convolution | localization_error | localization_error | 1 |
| convolution | miss | correct_localization | 2 |
| convolution | miss | localization_error | 6 |
| convolution | miss | miss | 2 |

The remaining 28 paired cases retain unknown truth and are not scored as negatives.

## Provenance and verification

[Prospective source/protocol/runtime freeze](https://github.com/Ken0u/badminton-match-analyzer/issues/313#issuecomment-6408508513); [complete raw-output seal before sole scoring](https://github.com/Ken0u/badminton-match-analyzer/issues/313#issuecomment-6409368292). Experiment SHA256 `c15ae687689784f4bd9d05bcbd3747b89286925c861298db7f09c090657c39e5`; protocol `7b4dfb6a3d1054ccfdf5f5f4bdf4e1f7d73d1511ca3c9f84da99e943a0534857`; raw index `a0a383d3df756f0095d0025b414385d8294aa77df5fb286d69a174d377daa4df`; CPU tensor audit `b1cb459ae27fb8138389cde4675be4b72b716f6e719f174cfe75b5e997824602`; aggregate diagnostic report `6bba95cb4317a6b579f2d71fc3a47ea814538abaef7dfbbb538761b7483fe910`.

The tensor audit and three remaining native stages use genuine original shared Store admission with current host GPU/data grants, credential-cleared original root/data/weights pins, torchvision initialization before threaded PyAV, and native FFmpeg logging restoration. Actual observed PID/creation-time/cwd/command identities, completed Store jobs, worker terminals and independently absent lifetimes were checked before transitions and raw publication. Original interrupted provenance is retained separately. Application metadata, annotations, predictions and installed weights are unchanged.

Final fixed-byte verification before native work: **4,944 Python tests pass**, four optional skips; **231 focused tests pass**. Required Ruff, formatting, dependency, repository UTF-8/LF/JSON/link and diff checks pass. Executable bytes remain identical across tests, commit and native consumers. Initial interrupted or source-changing test attempts remain preserved and are not counted as final verification.

The six scoped paths add a separately versioned module/CLI/protocol/report, meaningful generated regressions and explicit packaging of the 49th public manifest. Exact final-head PR/main CI, controller integration and independent source/wheel/frontend/lock/all-49-manifest/both-image manifest/config/descriptor delivery are separate requirements recorded on issue #313. Verification never installs or executes downloaded build artifacts. Descriptor availability alone does not establish container layer-byte, runtime or image-source parity.

No new training, synthetic test, source-image transfer, assessor, download, paid service or model promotion occurred in this phase. Old #305 selected weights/test and the consumed #63 holdout stay untouched. Raw media, labels, checkpoint files and detailed operational artifacts remain private and ignored. All four source eligibility flags remain false. Roadmap #65 and reference-dependent #62/#66/#67/#71 remain incomplete; familiar-source agreement does not certify shuttle accuracy, contacts, serves/ends, persistent identities or forehand/backhand shot labels throughout unseen matches.
