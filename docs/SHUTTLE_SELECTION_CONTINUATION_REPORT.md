# Archived familiar-source shuttle selection diagnostic

**No usable learned familiar-footage predictions were produced.** Every learned method returned unavailable for all 60 cases, with reason `unverified_or_excluded_source_context`. Strict localization F1 is therefore zero with all 25 known-visible cases counted as misses. Zero negative false detections reflects unavailable output and is not an improvement. The exact original baselines reproduce, but this result cannot establish how the learned scorers localize shuttles in eligible real footage. Source-context eligibility needs a separately scoped investigation or source review; no guard is weakened here.

Archival-only task [#334](https://github.com/Ken0u/badminton-match-analyzer/issues/334) reports the already-written remaining-only diagnostic from [#332](https://github.com/Ken0u/badminton-match-analyzer/issues/332) completed once using cached observations and the three unchanged fitted scorers from [#330](https://github.com/Ken0u/badminton-match-analyzer/issues/330). Its original familiar-stage failure remains preserved. No checkpoint winner is selected, no weights or thresholds change, and no application model/default is promoted. This small, previously inspected development sample does not establish independent real-footage accuracy or correct full-match annotation. Complete independent rally references remain **0/2**.

The [public protocol](../data/manifests/shuttle_selection_continuation_protocol_v1.json) retains all 50 views and 13,499 native rows per method. Every scored method retains all 60 cases: 25 visible, seven explicitly not visible and 28 unknown. Unknown truth stays unscored; unavailable predictions stay in the denominator. Original native PTS, display/source identity, scene exclusions and camera partitions are verified before selection. Only immediately adjacent eligible native frames support features; the scorer selects existing observed components without creating or moving coordinates.

## Original deadline and archival boundary

The original research AND delivery deadline was **2026-10-27 13:14:15 UTC**. The single cached worker finished successfully at **12:37:30.900 UTC**, before that deadline. The session resumed at 18:19 UTC; result verification, reporting, exact PR/main CI, controller integration and public delivery had not completed by the deadline. Therefore #332 remains an **incomplete protocol/delivery outcome**. Its issue and draft PR #333 were closed with transfer records after authenticated terminal-proof release; their branch, source, frozen consumers and all artifacts remain preserved. Separate archival-only task #334 permits no new scientific attempt and does not extend the old research clock or reset the cumulative output cap.

The sealed familiar result and original source/protocol/runtime/input/terminal hashes were pinned in #334 before its fresh grant. The archive checks only already-written result arithmetic, including every source/difficulty group, unknown/unavailable count and paired transition. It does not reopen original label rows, cached run rows or consumed generated-test rows, and cannot establish independent accuracy.

## Fixed comparison

| Method | Threshold | Baseline localization F1 | Selected localization F1 | Negative false detections, baseline / selected | Selected unavailable |
| --- | ---: | ---: | ---: | --- | ---: |
| control | 0.5 | 0.6512 | 0.0000 | 3 / 0 | 60 |
| decoder | 0.5 | 0.6957 | 0.0000 | 4 / 0 | 60 |
| convolution | 0.6 | 0.3333 | 0.0000 | 6 / 0 | 60 |

These are familiar development measurements. A localization error beyond the fixed image-diagonal tolerance counts as both a false detection and a miss. Unavailable known-visible output is a miss; unavailable negative output is not credited as a true negative. Results do not authorize retuning or deployment.

| Method / selector | Visibility TP / FP / FN / TN | Localization TP / FP / FN / TN | Mean visible-pair error (px) | Uncertainty-straddling cases |
| --- | --- | --- | ---: | ---: |
| control / baseline | 15 / 3 / 10 / 4 | 14 / 4 / 11 / 4 | 32.4295 | 7 |
| control / selected | 0 / 0 / 25 / 0 | 0 / 0 / 25 / 0 | unavailable | 0 |
| decoder / baseline | 17 / 4 / 8 / 3 | 16 / 5 / 9 / 3 | 28.4151 | 9 |
| decoder / selected | 0 / 0 / 25 / 0 | 0 / 0 / 25 / 0 | unavailable | 0 |
| convolution / baseline | 23 / 6 / 2 / 1 | 9 / 20 / 16 / 1 | 219.1291 | 5 |
| convolution / selected | 0 / 0 / 25 / 0 | 0 / 0 / 25 / 0 | unavailable | 0 |

## Component support, availability and paired outcomes

The component oracle asks whether any original candidate lies within tolerance; it is an upper bound on observed candidate support, not selected-point accuracy. Unavailable context remains explicit.

| Method / selector | Visible truth | Agreeing component | No agreeing component | Unavailable | Strict component recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| control / baseline | 25 | 14 | 11 | 0 | 0.5600 |
| control / selected | 25 | 0 | 0 | 25 | 0.0000 |
| decoder / baseline | 25 | 16 | 9 | 0 | 0.6400 |
| decoder / selected | 25 | 0 | 0 | 25 | 0.0000 |
| convolution / baseline | 25 | 17 | 8 | 0 | 0.6800 |
| convolution / selected | 25 | 0 | 0 | 25 | 0.0000 |

control / selected unavailable reasons: unverified_or_excluded_source_context: 60.


decoder / selected unavailable reasons: unverified_or_excluded_source_context: 60.


convolution / selected unavailable reasons: unverified_or_excluded_source_context: 60.


| Method | Baseline outcome to selected outcome | Cases |
| --- | --- | ---: |
| control | correct_absence -> unavailable_invisible_output | 4 |
| control | correct_localization -> unavailable_visible_output | 14 |
| control | false_detection -> unavailable_invisible_output | 3 |
| control | localization_error -> unavailable_visible_output | 1 |
| control | miss -> unavailable_visible_output | 10 |
| control | unknown_truth -> unknown_truth | 28 |
| decoder | correct_absence -> unavailable_invisible_output | 3 |
| decoder | correct_localization -> unavailable_visible_output | 16 |
| decoder | false_detection -> unavailable_invisible_output | 4 |
| decoder | localization_error -> unavailable_visible_output | 1 |
| decoder | miss -> unavailable_visible_output | 8 |
| decoder | unknown_truth -> unknown_truth | 28 |
| convolution | correct_absence -> unavailable_invisible_output | 1 |
| convolution | correct_localization -> unavailable_visible_output | 9 |
| convolution | false_detection -> unavailable_invisible_output | 6 |
| convolution | localization_error -> unavailable_visible_output | 14 |
| convolution | miss -> unavailable_visible_output | 2 |
| convolution | unknown_truth -> unknown_truth | 28 |

## Source and difficulty aggregates

Difficulty groups overlap; they must not be added together as independent cases. Zero-case groups do not supply evidence.

| Method / group | Cases | Unknown | Localization F1, baseline / selected | Unavailable, baseline / selected |
| --- | ---: | ---: | --- | --- |
| control / difficulty/blur | 28 | 14 | 0.6957 / 0.0000 | 0 / 28 |
| control / difficulty/distractor | 29 | 20 | 0.5714 / 0.0000 | 0 / 29 |
| control / difficulty/fast_flight | 7 | 0 | 0.7692 / 0.0000 | 0 / 7 |
| control / difficulty/non_play | 14 | 3 | 0.4444 / 0.0000 | 0 / 14 |
| control / difficulty/ordinary | 1 | 0 | 0.0000 / 0.0000 | 0 / 1 |
| control / difficulty/small_far | 18 | 8 | 0.8889 / 0.0000 | 0 / 18 |
| control / difficulty/unresolved | 28 | 28 | unavailable / unavailable | 0 / 28 |
| control / source/970dbd8adfe548d8 | 35 | 14 | 0.6667 / 0.0000 | 0 / 35 |
| control / source/c406a1187130b845 | 25 | 14 | 0.6154 / 0.0000 | 0 / 25 |
| decoder / difficulty/blur | 28 | 14 | 0.7500 / 0.0000 | 0 / 28 |
| decoder / difficulty/distractor | 29 | 20 | 0.5714 / 0.0000 | 0 / 29 |
| decoder / difficulty/fast_flight | 7 | 0 | 0.7692 / 0.0000 | 0 / 7 |
| decoder / difficulty/non_play | 14 | 3 | 0.4000 / 0.0000 | 0 / 14 |
| decoder / difficulty/ordinary | 1 | 0 | 1.0000 / 0.0000 | 0 / 1 |
| decoder / difficulty/small_far | 18 | 8 | 0.8889 / 0.0000 | 0 / 18 |
| decoder / difficulty/unresolved | 28 | 28 | unavailable / unavailable | 0 / 28 |
| decoder / source/970dbd8adfe548d8 | 35 | 14 | 0.7097 / 0.0000 | 0 / 35 |
| decoder / source/c406a1187130b845 | 25 | 14 | 0.6667 / 0.0000 | 0 / 25 |
| convolution / difficulty/blur | 28 | 14 | 0.4615 / 0.0000 | 0 / 28 |
| convolution / difficulty/distractor | 29 | 20 | 0.0000 / 0.0000 | 0 / 29 |
| convolution / difficulty/fast_flight | 7 | 0 | 0.3077 / 0.0000 | 0 / 7 |
| convolution / difficulty/non_play | 14 | 3 | 0.2857 / 0.0000 | 0 / 14 |
| convolution / difficulty/ordinary | 1 | 0 | 1.0000 / 0.0000 | 0 / 1 |
| convolution / difficulty/small_far | 18 | 8 | 0.4000 / 0.0000 | 0 / 18 |
| convolution / difficulty/unresolved | 28 | 28 | unavailable / unavailable | 0 / 28 |
| convolution / source/970dbd8adfe548d8 | 35 | 14 | 0.3889 / 0.0000 | 0 / 35 |
| convolution / source/c406a1187130b845 | 25 | 14 | 0.2222 / 0.0000 | 0 / 25 |

## Preservation and limits

The first #330 familiar attempt failed before scoring because packet-relative metadata was resolved from the repository root. Its original failure, source worktrees, frozen consumers, fitted scorers, thresholds and consumed generated test remain unchanged. The reusable cached recipe was extracted from the delivered repair, with a disposable before/after comparison proving identical results and all five output-file bytes across all three methods. The original generation, inference, fitting and test functions remain AST-identical. This continuation neither parses consumed generated-test rows nor reruns any predecessor stage.

Before opening familiar inputs, implementation review found that cumulative accounting omitted the actual `selectorremaining-*` root output namespace. A disposable regression reproduced the undercount, and adding that prefix made the regression pass. The earlier metadata-only freeze and frozen consumer copies remain preserved; they were never publicly sealed or used for scoring. Fresh full required checks and a separate new freeze pin the repaired consumer. Both output namespaces and all earlier attempts remain charged to the same cap. This was one diagnosed implementation repair, with zero scientific retries.

The exact new consumer, public protocol, runtime, inherited inputs and original terminal evidence were publicly sealed before familiar input reads. The single original CPU-only cached attempt used the real original shared Store admission. Archival task #334 did not restart, freeze, select, score, fit or infer anything; it read the sealed existing result only for aggregate arithmetic checks and reporting, while hashing original inputs as opaque bytes. No checkpoint loading, neural inference, optimization, video decoding, source/media/label acquisition, image transfer or assessor session occurred. App annotations, video records, installed weights and the original checkout/edit remain preserved. All four source-eligibility flags remain false.

The cached stage completed in 573.783 seconds. At the post-expiry archival preservation check, cumulative predecessor-plus-continuation-plus-archive retained outputs were 1,126,504,068 bytes across 172,903 files against the unchanged 4,294,967,296-byte cap. Borrowed immutable inputs remain separately recorded in the frozen experiment; no evidence was deleted or copied to reset accounting. Original grant: 2026-10-27 01:14:15 UTC. SAME immutable deadline: **2026-10-27 13:14:15 UTC**, including implementation, science and delivery. The continuation grant/lease does not extend that clock.

## Verification and provenance

Original exact-source pre-expiry checks: 241 focused tests and 5,362 full Python tests passed, with 4 optional full-suite skips. Ruff, formatting, dependency, repository/JSON/link and diff checks passed. Disposable controls cover nested packet provenance, fixed-recipe parity, source/input/runtime/fit/seal/terminal tampering, one-shot fencing, real Store admission, full denominators, unknown/unavailable handling, original clocks and cumulative budgets. These establish implementation behavior and preservation, not badminton accuracy. Fresh archival focused/full and required static/documentation checks, exact archive PR CI, controller integration, merged-main CI and full public source/wheel/manifests/images delivery are recorded on #334. Those later receipts cannot make the original missed #332 deadline compliant.

[Prospective source/protocol/runtime commitment](https://github.com/Ken0u/badminton-match-analyzer/issues/332#issuecomment-6441829645). Experiment SHA256 `be75300db6e3d12568f3a2195ffe699ab5e47c600f7e995f38a5c1eea3988044`; familiar result `0bfeec21581f436ca830edf6d9dfacc7989962925ccf6eaa5471cd644a76b971`; unchanged fits `61a2f32f846f4916bbf32afd882aeb4ff36e142dd1fb67051066e5918a9fccaa`; local preservation receipt `e17ff8d8e8c428aa733022a92fbd3c76890d9719d064991f40394e566d04f84a`. The public manifest pins all inputs and original delivered source; private labels, frame-level rows and media remain excluded.

This archives the completed worker output only. The original #332 complete-protocol/delivery requirement remains incomplete because its deadline was missed. The application still needs independent complete-rally references, stronger shuttle/contact and rally-boundary evidence, recognition across requested family/side classes, persistent singles/doubles identities, and evaluation across unseen full matches before full automatic correctness can be claimed.
