# Observed shuttle component selection

Task [#330](https://github.com/Ken0u/badminton-match-analyzer/issues/330), under [localization roadmap #65](https://github.com/Ken0u/badminton-match-analyzer/issues/65).

The generated train/validation, fitting and single test stages completed; the familiar-source comparison failed before scoring and remains incomplete. It compares the original observed-component selector with a separately fitted logistic scorer and abstention for each of three unchanged neural checkpoints. Results are research evidence; application defaults, neural weights and source eligibility are unchanged. Full-match annotation accuracy remains unproven and complete scientific rally references remain **0/2**.

The [public protocol](../data/manifests/shuttle_selection_protocol_v1.json) fixes 128 training, 16 validation and 32 test source groups, each containing 24 native frames at 512×288. Fresh namespace `synthetic-shuttle-selection-v1` has 176 unique seeds with no overlap against the two prior namespaces. Generator geometry is unchanged from the owned capacity generator. Training-only normalization and the fixed 500-step class-balanced fit precede validation-only threshold choice. Every fit and threshold was publicly sealed before generating the single new test. Familiar sources were read only afterward.

## Fitted methods

| Method | Training frames | Positive candidates | Negative candidates | Available | Validation threshold |
| --- | ---: | ---: | ---: | --- | ---: |
| control | 3072 | 1010 | 19549 | True | 0.5000 |
| decoder | 3072 | 1192 | 19838 | True | 0.5000 |
| convolution | 3072 | 2251 | 20918 | True | 0.6000 |

## Fresh generated test

| Method | Frames | Visible / negative | Baseline localization F1 | Learned localization F1 | Negative false detections, baseline / learned | Agreeing components | Learned unavailable |
| --- | ---: | --- | ---: | ---: | --- | ---: | ---: |
| control | 768 | 586 / 182 | 0.0059 | 0.4399 | 182 / 48 | 250 | 0 |
| decoder | 768 | 586 / 182 | 0.0133 | 0.4582 | 182 / 63 | 328 | 0 |
| convolution | 768 | 586 / 182 | 0.2674 | 0.4644 | 182 / 136 | 581 | 0 |

Every method retains all 768 frames. An observed point outside localization tolerance contributes both a false positive and a miss. Negative false detections are measured only against explicit negative truth. An unavailable negative contributes neither a true negative nor a false detection; its availability count remains explicit. Component agreement is an oracle over observed candidates, not selected-point correctness. No checkpoint winner or post-test threshold is selected.

Generated improvement criterion (higher localization F1 with no increase in negative false detections): control: True, decoder: True, convolution: True.

| Method / selector | Localization TP / FP / FN / TN | Visibility TP / FP / FN / TN | Displaced | Mean predicted-visible error (px) |
| --- | --- | --- | ---: | ---: |
| control / baseline | 4 / 764 / 582 / 0 | 586 / 182 / 0 / 0 | 582 | 188.8143 |
| control / selected | 216 / 180 / 370 / 134 | 348 / 48 / 238 / 134 | 132 | 85.7505 |
| decoder / baseline | 9 / 759 / 577 / 0 | 586 / 182 / 0 / 0 | 577 | 202.4803 |
| decoder / selected | 255 / 272 / 331 / 119 | 464 / 63 / 122 / 119 | 209 | 91.8048 |
| convolution / baseline | 181 / 587 / 405 / 0 | 586 / 182 / 0 / 0 | 405 | 143.7906 |
| convolution / selected | 274 / 320 / 312 / 46 | 458 / 136 / 128 / 46 | 184 | 81.7548 |

| Method | Generated paired localization outcome | Frames |
| --- | --- | ---: |
| control | displaced->displaced | 132 |
| control | displaced->fn | 235 |
| control | displaced->tp | 215 |
| control | fp->fp | 48 |
| control | fp->tn | 134 |
| control | tp->fn | 3 |
| control | tp->tp | 1 |
| decoder | displaced->displaced | 204 |
| decoder | displaced->fn | 121 |
| decoder | displaced->tp | 252 |
| decoder | fp->fp | 63 |
| decoder | fp->tn | 119 |
| decoder | tp->displaced | 5 |
| decoder | tp->fn | 1 |
| decoder | tp->tp | 3 |
| convolution | displaced->displaced | 146 |
| convolution | displaced->fn | 113 |
| convolution | displaced->tp | 146 |
| convolution | fp->fp | 136 |
| convolution | fp->tn | 46 |
| convolution | tp->displaced | 38 |
| convolution | tp->fn | 15 |
| convolution | tp->tp | 128 |

## Incomplete familiar-source diagnostic

The planned comparison retains all 50 original views / 13,499 native rows per method and all 60 familiar cases: 25 visible, seven negative and 28 unknown. The attempt failed in source-provenance validation because the reader resolved packet-relative metadata from the repository root. Cached views, packet, labels and baseline were read, but the failure preceded the familiar opening marker, baseline reproduction and learned scoring. No familiar metrics or selected outputs were produced. All 60 planned cases remain unscored; unknown truth is never converted to a negative. No input, case or method is dropped to hide this failure.

The failed shared-Store job, original traceback and terminal process evidence are preserved. Dependent scientific work stopped; no familiar retry, refitting, threshold change or generated-test repetition occurred. A reader-only dispatch correction now resolves source metadata relative to the sealed packet parent. Its disposable integration regression uses a nested packet directory and original relative provenance. The correction was made after the consumed test and did not produce the generated results above. Original scientific source and frozen consumers remain unchanged. A familiar-only continuation needs a separately frozen and granted follow-up; this report does not claim that comparison passed. All four source eligibility flags remain false.

## Source support and limitations

The scorer selects an existing component without moving its coordinates. Its original observed confidence remains separate from classifier probability. Only immediately adjacent native frames in the same eligible source segment can support motion features. No interpolation, source replacement, real-media inference, external image transfer, neural-weight training or application promotion occurred. A scorer cannot recover a shuttle absent from all observed components. Procedural geometry and this small familiar diagnostic do not establish performance on arbitrary badminton broadcasts, persistent player identities, contacts, rally boundaries or shot labels.

## Runtime and verification

| Admitted stage | Elapsed seconds | Peak allocated tensor MiB |
| --- | ---: | ---: |
| fit | 63.635 | not applicable |
| trainval | 785.317 | 367.4990 |
| test | 237.193 | 367.4990 |
| familiar (failed; launcher wall clock) | 59.665 | unavailable |

All heavy stages use the original shared Store admission. Exact consumer/protocol/checkpoint hashes, per-group cache completion seals, process identities, terminal artifacts and original grant clock remain preserved. Recovery from the interrupted implementation did not reset the 12-hour deadline or the 4 GiB retained-output cap. Resource accounting charges all preserved task outputs, checks current experiment growth at every progress checkpoint and refreshes the full inventory periodically. A metadata-only benchmark reduced 100 subsequent checks to 0.027 seconds after a 20.86-second initial inventory.

Verification includes 163 focused cases, a fresh full Python suite on the repaired publication source (results recorded on the owning issue), Ruff, formatting, dependency, repository, JSON/link and diff checks. Earlier missing-FFmpeg skips and a formatting failure remain preserved; the final full run uses the configured portable tools. These software checks establish implementation behavior and integrity, not badminton accuracy. Exact final PR/main CI, controller integration and complete public delivery are separate requirements recorded on the owning issue.

[Prospective source/protocol/environment freeze](https://github.com/Ken0u/badminton-match-analyzer/issues/330#issuecomment-6439221189); [all fitted scorers and thresholds sealed before test](https://github.com/Ken0u/badminton-match-analyzer/issues/330#issuecomment-6439617979). Frozen source head `5bd4559728db70dae3effb4a26c88a570124b159`. Experiment SHA256 `73cb4577be8638045bafcb61a852fe2e52e29971869729898a964531e42a35d0`; fits `61a2f32f846f4916bbf32afd882aeb4ff36e142dd1fb67051066e5918a9fccaa`; generated test `0d1f89d51ba40d67efc72846fed0adb2f5a0090b51a2813315859fa379ea2cb2`; familiar diagnostic absent (failed before scoring).

Original grant: 2026-10-27 01:14:15 UTC; immutable deadline: 2026-10-27 13:14:15 UTC. At final scientific verification, new retained task outputs total 517,434,401 bytes against the 4,294,967,296-byte cap. Borrowed immutable inputs are accounted separately: 227,842,448 bytes in directly registered artifacts, and 256,651,141 bytes across 426 uniquely referenced files including inherited raw views, source clocks and selected-checkpoint provenance. Existing ledgers remain preserved; none is copied or deleted to reset the new-output cap.
