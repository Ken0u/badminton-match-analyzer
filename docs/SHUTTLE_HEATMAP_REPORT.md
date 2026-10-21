# Frozen development heatmap diagnostic

Completed October 21, 2026, for [issue 149](https://github.com/Ken0u/badminton-match-analyzer/issues/149), under [localization roadmap 65](https://github.com/Ken0u/badminton-match-analyzer/issues/65). **All 50 original target views reproduce the frozen baseline, and all 60 case heatmaps are available.** Fourteen of the 25 known-visible cases contain a cell above the original 0.5 threshold within the fixed source-label disk; eleven do not. This descriptive result leaves the baseline unchanged and supports no model, threshold or default promotion. Full-match annotation correctness remains unproven.

## Method and complete support

The [fixed public protocol](../data/manifests/shuttle_heatmap_protocol_v1.json) retains the [source-only visibility audit's](SHUTTLE_VISIBILITY_REPORT.md) original 60 familiar development cases: 25 visible/localizable, seven confirmed not visible, 28 unknown and zero visible/unlocalizable. Fifty were uniformly sampled and ten selected for known development gaps. These two-source agent assessments are not expert-certified or independent truth. No consumed holdout #63 inputs, predictions, protocols, private membership metadata or artifacts were accessed.

The narrow opt-in Python observer receives an isolated read-only float32 copy of each completed temporal-ensemble heatmap, with original native frame and PTS. Reenabling writes on the copy cannot change inference or another frame. Observer errors propagate to the admitted research job. Default inference allocates no observer copy or additional heatmap artifact and retains its persisted schema. Weights, 512x288 input, CUDA float16, sequence length 8, complete-view median background, source clocks/orientation/display geometry, camera resets, scene/calibration guards, component selection and 0.5 threshold remain unchanged.

Capture executes the same 50 complete unique core-owner camera/background views and retains exactly the 60 target heatmaps. Its 13,499 output rows count rows across those views, not unique whole-source frames or every decode/background/seek operation. Before coordinate-response interpretation, every native frame/time/camera/point/component/context structure passes the original full-row gate. Only confidence has the predeclared absolute tolerance 0.00001, with zero relative tolerance. There are zero differences under that gate, across all 50 views and 13,499 rows. The [earlier fixed-resolution comparison](SHUTTLE_RESOLUTION_REPORT.md) remains unchanged.

For known visible/localizable cases, cell centers map to source display pixels as `((column+0.5)*width/512, (row+0.5)*height/288)`. The nominal disk radius is `0.005*hypot(width,height)`, about 7.343 px for these 1280x720 sources. Statistics retain global maximum, deterministic first row-major global argmax, its distance to the frozen source label, local maximum and local/global ratio. A zero global response makes the ratio undefined; none occurred in these 60 heatmaps. These values are descriptive responses, without calibrated-probability or replacement-detection meaning. Unknown and negative states have no invented local coordinates.

The global first-argmax distance over 25 visible cases has minimum 1.274755 px, median 3.758324 px and maximum 808.789914 px. This is a raw peak diagnostic, separate from the application's selected component. The nominal local/global ratio ranges from 0.018982 to 1.000000, with median 1.000000; some labeled locations have much weaker response than an off-target peak. Nominal local peaks range from 0.004162 to 0.817969, with median 0.609814. These observations neither choose a new threshold nor recover a missed event. The baseline's 14 correct localizations, ten missing detections and one wrong localization on 25 visible cases remain the original outcomes; equality of aggregate counts does not equate a disk peak with a selected component centroid.

## Complete group availability and global responses

V/A/U means localizable visible / confirmed absent / unknown. Visible/unlocalizable, unavailable and uninterpreted counts are zero throughout. Availability is available/unavailable, and ranges are minimum / median / maximum. Empty groups remain explicit with undefined statistics. Difficulty groups overlap, and disagreement records any original assessor difference. All seven confirmed negatives are non-play; there is no established occlusion or camera-transition support. Unknowns remain in coverage and global-response summaries and never become negatives.

| Group | Cases | V/A/U | Available/unavailable | Global maximum, min / median / max |
| --- | ---: | ---: | ---: | --- |
| all | 60 | 25/7/28 | 60/0 | 0.013039 / 0.461252 / 0.817969 |
| difficulty:blur | 28 | 14/0/14 | 28/0 | 0.080640 / 0.546100 / 0.817969 |
| difficulty:camera_transition | 0 | 0/0/0 | 0/0 | undefined |
| difficulty:distractor | 29 | 9/0/20 | 29/0 | 0.069513 / 0.487915 / 0.784570 |
| difficulty:fast_flight | 7 | 7/0/0 | 7/0 | 0.080640 / 0.609814 / 0.817969 |
| difficulty:non_play | 14 | 4/7/3 | 14/0 | 0.013039 / 0.321928 / 0.789526 |
| difficulty:occlusion | 0 | 0/0/0 | 0/0 | undefined |
| difficulty:ordinary | 1 | 1/0/0 | 1/0 | 0.278483 / 0.278483 / 0.278483 |
| difficulty:small_far | 18 | 10/0/8 | 18/0 | 0.083038 / 0.661572 / 0.817969 |
| difficulty:unresolved | 28 | 0/0/28 | 28/0 | 0.069513 / 0.415033 / 0.784570 |
| disagreement:false | 20 | 5/7/8 | 20/0 | 0.013039 / 0.468362 / 0.789526 |
| disagreement:true | 40 | 20/0/20 | 40/0 | 0.069513 / 0.461252 / 0.817969 |
| selection:known_gap | 10 | 4/0/6 | 10/0 | 0.300282 / 0.422089 / 0.709082 |
| selection:uniform | 50 | 21/7/22 | 50/0 | 0.013039 / 0.553201 / 0.817969 |
| source:singles | 35 | 18/3/14 | 35/0 | 0.013039 / 0.434589 / 0.817969 |
| source:doubles | 25 | 7/4/14 | 25/0 | 0.014916 / 0.509607 / 0.784570 |
| state:not_visible | 7 | 0/7/0 | 7/0 | 0.013039 / 0.424591 / 0.789526 |
| state:unknown | 28 | 0/0/28 | 28/0 | 0.069513 / 0.415033 / 0.784570 |
| state:visible | 25 | 25/0/0 | 25/0 | 0.069714 / 0.609814 / 0.817969 |
| state:visible_unlocalizable | 0 | 0/0/0 | 0/0 | undefined |

## Nominal source-label response

Support counts known visible/localizable cases. The final column counts disks containing any cell strictly above the unchanged original 0.5 threshold; it is a descriptive cell-response count, not a new localization score. No disk is empty in this nominal support. All 60 cases retain their original states and availability.

| Group | Coordinate support | Local peak, min / median / max | Local/global ratio, min / median / max | Disk response above 0.5 / support |
| --- | ---: | --- | --- | ---: |
| all | 25 | 0.004162 / 0.609814 / 0.817969 | 0.018982 / 1.000000 / 1.000000 | 14/25 |
| difficulty:blur | 14 | 0.017682 / 0.596204 / 0.817969 | 0.066232 / 1.000000 / 1.000000 | 8/14 |
| difficulty:camera_transition | 0 | undefined | undefined | undefined (0 support) |
| difficulty:distractor | 9 | 0.019109 / 0.434589 / 0.702710 | 0.066232 / 1.000000 / 1.000000 | 4/9 |
| difficulty:fast_flight | 7 | 0.017682 / 0.609814 / 0.817969 | 0.159645 / 1.000000 / 1.000000 | 5/7 |
| difficulty:non_play | 4 | 0.004162 / 0.349273 / 0.751733 | 0.018982 / 0.532294 / 1.000000 | 2/4 |
| difficulty:occlusion | 0 | undefined | undefined | undefined (0 support) |
| difficulty:ordinary | 1 | 0.278483 / 0.278483 / 0.278483 | 1.000000 / 1.000000 / 1.000000 | 0/1 |
| difficulty:small_far | 10 | 0.349335 / 0.695984 / 0.817969 | 1.000000 / 1.000000 / 1.000000 | 8/10 |
| difficulty:unresolved | 0 | undefined | undefined | undefined (0 support) |
| disagreement:false | 5 | 0.199478 / 0.694043 / 0.780029 | 0.966445 / 1.000000 / 1.000000 | 4/5 |
| disagreement:true | 20 | 0.004162 / 0.508591 / 0.817969 | 0.018982 / 1.000000 / 1.000000 | 10/20 |
| selection:known_gap | 4 | 0.349335 / 0.508591 / 0.709082 | 1.000000 / 1.000000 / 1.000000 | 2/4 |
| selection:uniform | 21 | 0.004162 / 0.650684 / 0.817969 | 0.018982 / 1.000000 / 1.000000 | 12/21 |
| source:singles | 18 | 0.004162 / 0.616638 / 0.817969 | 0.018982 / 1.000000 / 1.000000 | 10/18 |
| source:doubles | 7 | 0.004503 / 0.609814 / 0.751733 | 0.064588 / 1.000000 / 1.000000 | 4/7 |
| state:not_visible | 0 | undefined | undefined | undefined (0 support) |
| state:unknown | 0 | undefined | undefined | undefined (0 support) |
| state:visible | 25 | 0.004162 / 0.609814 / 0.817969 | 0.018982 / 1.000000 / 1.000000 | 14/25 |
| state:visible_unlocalizable | 0 | undefined | undefined | undefined (0 support) |

## Separate radial-uncertainty sensitivity

The original label uncertainty supplies inner radius `max(0,tolerance-uncertainty)` and outer radius `tolerance+uncertainty`; neither is tuned. Fifteen of 25 inner disks contain no heatmap cell centers. Their local response and ratio stay undefined, rather than zero or a negative observation. The inner peak and ratio therefore have support 10: peak min/median/max 0.349335/0.678918/0.814258, ratio 0.950155/1.000000/1.000000. Eight of those ten nonempty inner disks contain an above 0.5 cell. All 25 outer disks are nonempty, fourteen with an above 0.5 cell; outer peak min/median/max 0.007664/0.609814/0.817969 and ratio 0.054768/1.000000/1.000000. These are sensitivity summaries under the original radial assumptions, without new truth or statistical confidence bounds.

Nonempty support is nonempty disks / visible-coordinate cases. Above0.5 denominators below are nonempty disks, so an empty inner disk cannot silently become a failed detection. A group with zero coordinate support has undefined response statistics.

| Group | Inner nonempty support | Inner peak median | Inner above 0.5 / nonempty | Outer nonempty support | Outer peak median | Outer above 0.5 / nonempty |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 10/25 | 0.678918 | 8/10 | 25/25 | 0.609814 | 14/25 |
| difficulty:blur | 2/14 | 0.736853 | 2/2 | 14/14 | 0.596204 | 8/14 |
| difficulty:camera_transition | 0/0 | undefined | undefined (0 support) | 0/0 | undefined | undefined (0 support) |
| difficulty:distractor | 4/9 | 0.542191 | 2/4 | 9/9 | 0.434589 | 4/9 |
| difficulty:fast_flight | 1/7 | 0.814258 | 1/1 | 7/7 | 0.609814 | 5/7 |
| difficulty:non_play | 1/4 | 0.659448 | 1/1 | 4/4 | 0.353026 | 2/4 |
| difficulty:occlusion | 0/0 | undefined | undefined (0 support) | 0/0 | undefined | undefined (0 support) |
| difficulty:ordinary | 0/1 | undefined | undefined (0 support) | 1/1 | 0.278483 | 0/1 |
| difficulty:small_far | 9/10 | 0.689258 | 7/9 | 10/10 | 0.695984 | 8/10 |
| difficulty:unresolved | 0/0 | undefined | undefined (0 support) | 0/0 | undefined | undefined (0 support) |
| disagreement:false | 3/5 | 0.668579 | 3/3 | 5/5 | 0.694043 | 4/5 |
| disagreement:true | 7/20 | 0.689258 | 5/7 | 20/20 | 0.508591 | 10/20 |
| selection:known_gap | 2/4 | 0.391516 | 0/2 | 4/4 | 0.508591 | 2/4 |
| selection:uniform | 8/21 | 0.695984 | 8/8 | 21/21 | 0.650684 | 12/21 |
| source:singles | 8/18 | 0.681079 | 6/8 | 18/18 | 0.616638 | 10/18 |
| source:doubles | 2/7 | 0.678918 | 2/2 | 7/7 | 0.609814 | 4/7 |
| state:not_visible | 0/0 | undefined | undefined (0 support) | 0/0 | undefined | undefined (0 support) |
| state:unknown | 0/0 | undefined | undefined (0 support) | 0/0 | undefined | undefined (0 support) |
| state:visible | 10/25 | 0.678918 | 8/10 | 25/25 | 0.609814 | 14/25 |
| state:visible_unlocalizable | 0/0 | undefined | undefined (0 support) | 0/0 | undefined | undefined (0 support) |

## Execution, interruption and provenance

Exact executed code is `4f81bf587dd2353ce705ea61cbbb4d95029c57e0`, on the epoch 2 granted base `9d7ee10b6bf474993b4781abdc533ebfdca751e8`. All 60 recursive consumer/config/script files were frozen from committed Git bytes before heatmaps, and remain unchanged in the final report update. The original historical starting main was `e4805cc7959f446b3dca3f7988522bba54a20c8b`; the authenticated renewed grant used current main after unrelated delivered work. No relevant baseline input or scientific policy changed.

The first actual worker exited abruptly after 22 sealed views without emitting its terminal. The original recorded lifetime was absent, not merely a lost tool handle. Authenticated original-host recovery preserved every original complete and partial artifact. The existing `Store.recover_jobs` API changed only its proven-dead registration to interrupted. An explicitly external recovery receipt records the missing worker terminal, unknown original exit code and no worker-success claim. Its conservative charge is 2,902 seconds, from process creation through the first durable absence observation; it is not measured native inference time. Detailed original-host proof, Store pre/post documents and operational helpers remain local for review. This was an audited operational recovery, not an automatically generated worker terminal or a tested general SIGKILL recovery command.

The exact committed CLI then reused all 22 completed views without inference and completed the remaining 28. Actual resumed lifetime exit code 0, matching real shared Store completion, sealed recovery history and all 50/60/13,499 output membership were verified before interpretation. One abandoned partial array from the unfinished first attempt remains separately preserved and uninterpreted; the complete output index contains exactly 60 case heatmaps, across 61 physical arrays. Its actual resumed-attempt elapsed time is 618.517 s, giving conservative charged cumulative time 3,520.517 s within the unchanged 3,600 s budget. Summed native inference time over the 50 unique completed views is 1,148.052 s; maximum per-view peak GPU tensor allocation is 385.4 decimal MB, not whole-process GPU memory. The separate admitted fixed CPU interpretation takes 12.757 s, excluding process startup and pre-admission input verification. All three recorded scientific process lifetimes have exited. The two capture Store outcomes remain interrupted and completed, and the interpretation Store job is completed.

Pre-run source/protocol/code/runtime hashes were [timestamped before capture](https://github.com/Ken0u/badminton-match-analyzer/issues/149#issuecomment-6304085710). The [explicit recovered interruption receipt](https://github.com/Ken0u/badminton-match-analyzer/issues/149#issuecomment-6304851314) was timestamped before resumed inference. [Complete raw-output seals](https://github.com/Ken0u/badminton-match-analyzer/issues/149#issuecomment-6305027849) preceded the sole fixed interpretation. All raw heatmaps, videos, labels, weights and detailed workstation/runtime/Store evidence remain ignored and are absent from packages and containers.

| Binding | SHA256 |
| --- | --- |
| Fixed protocol | `d33208aa15a34bf2c5ac7a0d72cd2796b358655658279c1d8091c6bef8aa5f6a` |
| Frozen experiment | `8892a4a7dc6d7312c82b627aefb52451f4c411ce75db45cd5a12aa9a7ee0bc68` |
| Original source inventory | `273e0749d148e952ad1fb0534363b3971e2584702f834ad2084c59e632990822` |
| Source packet | `3b22c07a3592728b6aa17e7d7c28f0089a8820b1373ace1289796d2e99e5466d` |
| Frozen labels | `fd25029ae49891f544989cdbfa20e5077571c1048c960e2d77ddee1fe7abd158` |
| Original baseline | `915f678fa2b5577dff37811ba92ff9077c300eefc788fcab2873c12c2ffc6f64` |
| Original TrackNet checkpoint | `df867641a02712b021f04548ff4b1208ddfdb47f629ab2094ceb978667e83b1a` |
| External pre-interpretation proof | `75bc16a21875e91dee8c625d58cdb28d6700b740409762628fe0bfd534ce2cb7` |
| Complete raw output index | `0bb911151ee2f85109e042cb2aa2759d7f3d7ca7e88a9552a1c6080bd1b2eeb8` |
| Completed resumed terminal | `14b93a05d127895ea4cff95f0fe4d23e7213d368183d749a605ebd358154f631` |
| Fixed interpretation report | `3e4489e694ac5d0433a1664db9d266cb4c979e5498fa551d3695133ee2cc85ba` |

## Reproduction and verification

Use a clone plus the original pinned ignored packet, labels, baseline/source graph, native media/clocks and checkpoint; these are not supplied by a clone and no implicit downloads occur. Obtain the real resource grant. Before imports, pin `BADMINTON_ROOT` to the original input root, `BADMINTON_DATA_DIR` to its real `data/processed` shared Store and `BADMINTON_WEIGHTS_DIR` to its original `models/weights`, clear `GH_TOKEN`/`GITHUB_TOKEN`, and use the project environment. Initialize torchvision before any threaded PyAV decoding and retain native FFmpeg logging restoration.

`python scripts/diagnose_shuttle_heatmaps.py freeze --root ROOT --output NEW_IGNORED_OUTPUT --packet ORIGINAL_PACKET_DIRECTORY --labels ORIGINAL_LABEL_DIRECTORY --baseline ORIGINAL_BASELINE_JSON` freezes the full context and returns its SHA256. Publish that hash before `capture --root ROOT --output NEW_IGNORED_OUTPUT --experiment-sha256 EXPERIMENT_SHA256`. A graceful interrupted resume additionally requires its externally recorded `--resume-receipt TERMINAL_JSON --resume-sha256 TERMINAL_SHA256`, original-host exit, matching terminal Store registration and unchanged context. An abrupt exit without a terminal is refused for audited original-host recovery; a timeout never permits rerunning successful views.

After actual complete output, original lifetime exit and Store completion, externally seal the raw index and matching completed terminal before `interpret --root ROOT --output NEW_IGNORED_OUTPUT --experiment-sha256 EXPERIMENT_SHA256 --index OUTPUT_INDEX_JSON --index-sha256 INDEX_SHA256 --terminal COMPLETED_TERMINAL_JSON --terminal-sha256 TERMINAL_SHA256`. The interpreter verifies all cases/views and the complete baseline gate before local-coordinate response calculation. A control mismatch retains every case/state/availability denominator and marks responses uninterpreted.

Author verification passes 1,492 Python tests with four existing optional GPU skips, Ruff lint/format, dependency checks, CLI help, UTF-8/LF/JSON/link checks and `git diff --check`. The 23 focused cases include observer isolation/default parity/failure, temporal weighting/short views/frame-time identity, disk geometry/ties/zero/nonfinite inputs, unknown/unavailable denominators, frozen-context tamper and five actual exited generated CPU-stub recovery processes with real Store/lifetime guards. Those generated recovery cases cover cooperative interruption, early/partial/refused attempts and preserved terminal histories; the actual abrupt recovery above has separately recorded operational evidence. Tests establish software behavior, not annotation accuracy. Exact final review, CI and controller integration/delivery evidence belong on the owning issue and PR.

## Remaining work

These familiar cases support diagnosis only. Twenty-eight unknowns, absent occlusion/transition support and radial label uncertainty remain material limitations. Wider independently reviewed source-only labels, especially blur, small/far shuttles, doubles, occlusion and transitions, are required before another source-separated improvement experiment. Preserve this packet and baseline, and establish fresh independent full-match evaluation for accuracy claims. No threshold sweep, training, trajectory filling, relabeling, best-cutoff selection, replacement prediction or model/default promotion occurred. Training, independent-test, model-deployment and dataset-redistribution eligibility all remain false. Parent 65 and the full application goal remain open.
