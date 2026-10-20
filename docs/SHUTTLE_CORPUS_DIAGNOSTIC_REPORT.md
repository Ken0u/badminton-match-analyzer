# Frozen published-coordinate shuttle diagnostic

Owning task: [issue 145](https://github.com/Ken0u/badminton-match-analyzer/issues/145), under [localization roadmap 65](https://github.com/Ken0u/badminton-match-analyzer/issues/65). Completed native collection and fixed scoring, October 20, 2026: **all 201 clips / 91,579 native frames have predictions**, with zero unavailable outputs. The unchanged application tracker reaches **localization F1 0.975836 against eligible published references**. These familiar upstream-source agreement results establish neither an accuracy improvement nor independent full-match correctness. No model, app default or reviewed annotation is promoted.

The [source preparation](SHUTTLE_SUPERVISION_REPORT.md) retains 29 publication groups and all 91,214 original label rows. Twenty-five incomplete CSVs and all their 12,235 rows remain quarantined under the predeclared complete-file coverage rule. Their 365 unlabelled native tail frames also remain in coverage and receive raw predictions. The other 176 files contain 78,979 eligible published references: 68,643 publisher-visible and 10,336 publisher-not-visible rows. A publisher flag is publication metadata; it does not certify expert-observed visibility or physical absence.

The [fixed protocol](../data/manifests/shuttle_corpus_diagnostic_v1.json) was [published before native predictions](https://github.com/Ken0u/badminton-match-analyzer/issues/145#issuecomment-6292163621). Producer code `6a1f28ee1a71a27a81a45517d9e35784b731a12a` runs the existing checkpoint and unchanged application adapter: 512x288 input, 0.5 heatmap threshold, fixed CUDA precision, current automatic camera boundaries and observed component selection, and empty research-only manual annotations. All 58 recursive Python consumers, including native vendor code, match the committed producer bytes. Raw native collection and scoring are separate processes; [native output and terminal hashes were recorded before scoring](https://github.com/Ken0u/badminton-match-analyzer/issues/145#issuecomment-6294501848). No thresholds, samples, models, labels or normalization were selected from these outcomes.

Independent review subsequently reproduced two recovery defects: emitted terminals omitted their required sealed-history field, and a failed resumed attempt could forget earlier complete clips. The final repair changes only `resume_plan` and terminal metadata in `run`; the other 57 executed consumer files, inference adapter, model, inputs, scoring functions and frozen protocol remain byte-identical to the producer. New terminals retain the full completed set and history, and recovery validates every bound historical checkpoint and rejects conflicts. Legacy terminals without history receive an explicit preservation error; no original receipt or output is rewritten. The scientific execution and results above remain bound to producer `6a1f28e`, rather than claiming the repaired source produced new predictions. Generated CPU-stub tests exercise the corrected Store/recovery flow; no further CUDA inference or scoring was performed for this metadata repair.

All native frame ordinals and timestamps are retained. Every raw output and temporary clock projection was checked against its original source clock; 201 derived clock files agree exactly with the source-derived times. The execution records eight automatic cuts and zero repaired frames. Cut accuracy, live/replay context and semantic source alignment remain unreviewed. Complete native coverage cannot establish those properties.

Agreement is computed only on the 78,979 eligible published rows; all 91,214 rows and 91,579 frames remain explicit in the coverage and quarantine denominators. The fixed localization tolerance is 0.005 of the source diagonal, about 7.343 pixels for these 1280x720 sources. A wrong visible location contributes both a false detection and a miss. Missing known-positive outputs count as misses; unavailable negative outputs cannot become true negatives.

| Published-reference task | TP | FP | FN | TN | Precision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Visibility agreement | 67,073 | 1,139 | 1,570 | 9,197 | 0.983302 | 0.977128 | 0.980205 |
| Localization agreement | 66,774 | 1,438 | 1,869 | 9,197 | 0.978919 | 0.972772 | 0.975836 |

There are 1,570 publisher-visible references without a visible model output and 299 visible predictions outside the fixed coordinate tolerance. The latter account for the extra 299 localization false positives and misses. Against publisher-not-visible references, 1,139 predictions are visible and 9,197 are not visible. These counts describe agreement with the weak published references.

An observed component falls within the fixed tolerance for 66,810 of 68,643 eligible publisher-visible references. No component is nearby for 1,833; 36 have a nearby component but another location is selected. Thus 263 of the 299 wrong visible locations have no nearby component, while 36 are component-selection disagreements. This categorization inspects observed above-threshold components without choosing a replacement prediction or filling trajectories.

The conditional selected-coordinate error has support 67,073: every eligible publisher-visible row with a visible model prediction, including its wrong visible locations. Mean error is 1.768594 pixels, median 1.457738 and 90th percentile 3.092329. The 1,570 missing visible outputs remain misses in recall; they are not silently removed from that denominator. Conditional distance alone cannot describe complete detection performance.

| Publication partition | Clips | Native frames | Published rows | Eligible rows | Quarantined rows | Localization F1 | Visibility F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Amateur | 26 | 9,525 | 9,466 | 8,112 | 1,354 | 0.980442 | 0.982437 |
| Professional | 146 | 69,396 | 69,092 | 58,864 | 10,228 | 0.978308 | 0.983150 |
| Test | 29 | 12,658 | 12,656 | 12,003 | 653 | 0.959199 | 0.962913 |

All 29 publication groups are retained below. Names preserve original namespaces and publication grouping; exact original identities, cross-corpus overlaps and checkpoint membership remain unverified. Published Test is an upstream evaluation namespace. These partitions supply no new independent holdout.

| Published group | Clips | Native frames | Published rows | Eligible rows | Quarantined rows | TP | FP | FN | Localization F1 | No nearby component | Wrong selection |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| amateur/match1 | 10 | 3,233 | 3,230 | 2,790 | 440 | 2,512 | 74 | 17 | 0.982209 | 16 | 1 |
| amateur/match2 | 9 | 3,278 | 3,222 | 2,308 | 914 | 2,094 | 45 | 40 | 0.980108 | 39 | 1 |
| amateur/match3 | 7 | 3,014 | 3,014 | 3,014 | 0 | 2,763 | 93 | 25 | 0.979093 | 23 | 2 |
| professional/match1 | 12 | 3,298 | 3,298 | 3,298 | 0 | 2,591 | 77 | 73 | 0.971868 | 71 | 2 |
| professional/match2 | 8 | 3,227 | 3,184 | 2,035 | 1,149 | 1,595 | 45 | 52 | 0.970490 | 52 | 0 |
| professional/match3 | 7 | 3,190 | 3,166 | 1,455 | 1,711 | 1,269 | 18 | 11 | 0.988703 | 9 | 2 |
| professional/match4 | 8 | 2,915 | 2,896 | 2,242 | 654 | 1,740 | 41 | 29 | 0.980282 | 29 | 0 |
| professional/match5 | 6 | 3,371 | 3,371 | 3,371 | 0 | 3,042 | 42 | 30 | 0.988304 | 23 | 7 |
| professional/match6 | 5 | 3,479 | 3,479 | 3,479 | 0 | 3,160 | 65 | 54 | 0.981519 | 49 | 5 |
| professional/match7 | 5 | 3,161 | 3,134 | 2,047 | 1,087 | 1,881 | 36 | 35 | 0.981477 | 32 | 3 |
| professional/match8 | 8 | 3,353 | 3,353 | 3,353 | 0 | 2,911 | 105 | 32 | 0.977010 | 31 | 1 |
| professional/match9 | 9 | 3,203 | 3,203 | 3,203 | 0 | 2,937 | 62 | 12 | 0.987559 | 10 | 2 |
| professional/match10 | 5 | 2,673 | 2,673 | 2,673 | 0 | 2,275 | 19 | 91 | 0.976395 | 91 | 0 |
| professional/match11 | 5 | 2,791 | 2,791 | 2,791 | 0 | 2,369 | 17 | 49 | 0.986261 | 47 | 2 |
| professional/match12 | 5 | 3,257 | 3,206 | 2,437 | 769 | 2,329 | 17 | 23 | 0.991486 | 23 | 0 |
| professional/match13 | 6 | 2,608 | 2,589 | 1,558 | 1,031 | 1,085 | 49 | 6 | 0.975281 | 6 | 0 |
| professional/match14 | 5 | 2,839 | 2,774 | 1,118 | 1,656 | 1,026 | 7 | 44 | 0.975749 | 44 | 0 |
| professional/match15 | 5 | 2,673 | 2,673 | 2,673 | 0 | 2,234 | 44 | 93 | 0.970250 | 90 | 3 |
| professional/match16 | 6 | 2,969 | 2,924 | 1,876 | 1,048 | 1,509 | 57 | 231 | 0.912886 | 231 | 0 |
| professional/match17 | 6 | 2,932 | 2,932 | 2,932 | 0 | 2,617 | 65 | 114 | 0.966931 | 113 | 1 |
| professional/match18 | 6 | 2,690 | 2,690 | 2,690 | 0 | 2,093 | 38 | 34 | 0.983091 | 34 | 0 |
| professional/match19 | 5 | 2,828 | 2,828 | 2,828 | 0 | 2,347 | 18 | 16 | 0.992809 | 16 | 0 |
| professional/match20 | 6 | 3,161 | 3,161 | 3,161 | 0 | 2,384 | 92 | 45 | 0.972069 | 45 | 0 |
| professional/match21 | 7 | 2,678 | 2,678 | 2,678 | 0 | 2,423 | 50 | 30 | 0.983760 | 29 | 1 |
| professional/match22 | 5 | 3,008 | 3,002 | 2,457 | 545 | 2,102 | 37 | 10 | 0.988944 | 10 | 0 |
| professional/match23 | 6 | 3,092 | 3,087 | 2,509 | 578 | 2,188 | 86 | 21 | 0.976132 | 20 | 1 |
| test/match1 | 11 | 4,222 | 4,222 | 4,222 | 0 | 3,444 | 22 | 158 | 0.974533 | 158 | 0 |
| test/match2 | 7 | 4,233 | 4,231 | 3,578 | 653 | 2,523 | 61 | 233 | 0.944944 | 232 | 1 |
| test/match3 | 11 | 4,203 | 4,203 | 4,203 | 0 | 3,331 | 56 | 261 | 0.954578 | 260 | 1 |

Professional/match16 has the lowest group localization agreement, F1 0.912886, with 231 misses and no nearby observed component for each. Test/match2 and Test/match3 reach 0.944944 and 0.954578. These are diagnostic outcomes under one fixed recipe, with unknown semantic validity and no new model selection. They warrant source/scene/label investigation before choosing another model change.

Interpretation: the current adapter achieves strong agreement on these familiar published inputs. This is compatible with a functioning adapter on this corpus, but does not resolve the [14/25 developer-source localization result](SHUTTLE_VISIBILITY_REPORT.md) or identify a single cause for that gap. Domain differences, source-image/annotation identity, scene content and weak-label validity remain unresolved. Independent source-reviewed supervision and another complete-source holdout are required before broader accuracy or promotion claims.

These scores are not a replication of an upstream paper benchmark. The [pinned upstream evaluator](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/test.py) defaults to a four-input-pixel distance tolerance and filters Test samples outside its effective trajectories. Our predeclared source-diagonal tolerance, all-partition coverage and complete-file quarantines have different semantics. The [upstream documentation](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/README.md) also permits match-level or rally-level median images; this run uses the existing bounded per-camera application estimator. Original archived CSVs remain the references. No label-correction, dropping or inpainting policy is adopted after observing outcomes.

Reproduction requires a repository clone, the pinned ignored source-evidence bundle and corpus from task 143, the original checkpoint, CUDA and a genuine resource grant. A clone alone supplies none of those local data artifacts. Pin the original repository, shared data and weights roots before configuration imports and clear research-process GitHub credentials. `scripts/diagnose_shuttle_corpus.py run` uses the real existing shared Store admission. Temporary timestamp adapters create no application source registrations or isolated admission Store. Resume requires original-host exited-lifetime proof, matching terminal Store registration, unchanged frozen sources/runtime and an externally recorded complete receipt history. The separate `score` mode requires both the output index and its matching completed native terminal, with their recorded SHA-256 values. A timeout is never process-exit evidence.

Both actual native and fixed-score processes exited successfully with matching completed shared Store registrations. Detailed workstation lifecycle and runtime context remain local. Scoring has sealed lifetime/report bindings but no separately sealed launch-command/working-directory snapshot; independent review records that audit limitation. Evidence packaging verifies 671 files, including every raw output, complete clip checkpoint, derived clock, frozen consumer copy and native/score receipt relationship. No inference was repeated. The initial code passes 32 focused regressions and 1,445 full-suite tests with four existing optional GPU skips, plus Ruff, formatting, dependency, diff, UTF-8/LF/JSON/local-link and CLI checks. Source-clock record/list schema, real shared admission with generated CPU stubs, interruption/live-worker/PID-reuse/foreign-host gates, consumer-copy races and native-terminal/index binding are covered. The recovery repair adds emitted-receipt roundtrips, cumulative checkpoint retention before/partway through reuse and refused admission, and conflicting/tampered historical-checkpoint rejection; these checks use generated CPU stubs, not another scientific inference run.

The repaired code passes **40 focused tests and 1,453 full-suite tests**, with the same four optional GPU skips and existing deprecation warning. These software checks establish the recovery behavior exercised above, not annotation accuracy or a new native execution under the repaired source.

| Evidence | SHA-256 |
| --- | --- |
| Fixed protocol | `90fe79c46fa9014ff96b1b8bb372cc457eaf1bc767b1ec097dea73163f2e861d` |
| Prepared source evidence | `baa2019e2f8354e2d5a923d29870a5042c7b8b089f7ce3c221074f07b7bf76a4` |
| Original checkpoint | `df867641a02712b021f04548ff4b1208ddfdb47f629ab2094ceb978667e83b1a` |
| Native output index | `17d64a83b139cf648e4edcbd953e56501b6e24582c9dcad3f2e6e7828432baa5` |
| Matching native terminal | `9c0fac43f5fa501d79fe239ab415bfca0047abc94814b07626225c0fc555fa0f` |
| Fixed score report | `c9d99fd249d51cb0d8ff057314ca40d07ea1dd306a4eb2a9e362e886d7d05ce9` |
| Local complete evidence index (671 files) | `787217394686d73dfff09cd1819cd0ab59d93c71891fbf34ef463beb43172828` |

Raw archives, videos, labels, predictions, process details and receipts remain ignored. All training, model deployment, dataset redistribution and independent-test eligibility flags remain false. Dataset rights, mirror authenticity, scene/label validity, original identities and cross-corpus overlaps are unverified. No consumed holdout-63 artifacts were accessed. This diagnostic establishes no expert visibility truth, complete serves/rallies, persistent player identities, stroke families, forehand/backhand labels, doubles or unseen full-match correctness. The application model/defaults, reviewed annotations, source data and environments remain unchanged. Final exact-head independent review/CI, controller integration, merged-main verification and full candidate delivery are tracked on the owning issue and PR. Parent 65 and the overall accuracy goal remain open.
