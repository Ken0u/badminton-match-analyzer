# Frozen 75-rally evaluation recovery

Updated October 19, 2026. The original 75-rally native/input audit and frozen R2/R3 comparison are complete, tracked in issue [#63](https://github.com/Ken0u/badminton-match-analyzer/issues/63) and [PR #107](https://github.com/Ken0u/badminton-match-analyzer/pull/107). R3's strict conditional family/side accuracy is **0.421** without confidence abstention and **0.143** with its unchanged validation thresholds. These results do not support automatic model integration or complete annotation claims.

The original one-shot workers exited after 67 complete native, feature and input-audit chains. Their launchers assume a clean start and cannot safely resume existing non-anchor work. The new `scripts/recover_frozen_holdout.py` keeps original worker/receipt files intact and writes a separate recovery lineage. A completed job alone is insufficient: reuse checks its source, native clock, complete range, frozen model, calibration, scene and camera context, and artifact bytes.

## Preserved starting point

Read-only inspection on the original Windows host verified all 75 source clips, 21,610 native frames and 860 published rows. Both original eligible denominators remain 677; 183 unknown truth rows per task stay separate. At recovery start, 67 complete chains covered 18,962 frames and 747 rows, including 567 eligible rows per task. Ordinal 67 already had a completed 260-frame player run; its shuttle run had no artifact. Eight rallies / 2,648 frames needed native completion. These counts describe processing and source supervision, not annotation accuracy.

All five recorded original producer process identities were absent, and a fresh scan found none of their scripts under a new PID. The old main parent and one research shuttle job had stale running states. Inventory constructed no Store and updated no records. Normal atomic admission subsequently marked those stale jobs interrupted, preserving their history; neither was falsely completed.

Recovery reused all 67 original native/feature/audit chains and ordinal 67's player artifact. It ran exactly 15 missing native stages, created eight new receipt sets, recomputed the full input audit across all 75 rallies, and completed genuine native, feature and evaluation main jobs. The native parent took 311.2 seconds, the full feature/input audit 50.6 seconds, and fixed CPU head inference/scoring 1.6 seconds, excluding process startup/preflight. Main annotations, original worker records, old receipt bytes, source/model/runtime bytes and original predictions remain intact. The seven previously pristine research documents received only the frozen published court/source-view setup.

| Frozen input                   | SHA-256                                                            |
| ------------------------------ | ------------------------------------------------------------------ |
| Holdout protocol               | `99b13bb12f0cacfee316547ee656ac69a0b6f273de20e75c80eb49e19892c6ed` |
| Source-view support            | `1b2e035e536e6ef74b1704b37275fab0e30d74c58fb3d2e45c4cd656f1df8b78` |
| Normalized labels              | `2fb3fdca1bd544179367b5bcc0cd3679c7001fb1f697e5cf29e69b327801a881` |
| R2 selected checkpoint         | `ef71574cac55f1cf5441e1ba11cbf2f4b9eafa31298d2078e87a7018d22ae10e` |
| R3 selected checkpoint         | `cae34a9f39cef5c0c45185c354c967ace2d81f9ea4750233ef9f8881e4b42dcc` |
| Ordinal 67 reusable player run | `49541b86baf3266718f595cc699967da138810436b5b9b5bc775a5f414d58242` |

## Reproduction contract

The clone supplies orchestration and generated-fixture tests. Original datasets, media, frozen runtimes, helper scripts, models and receipts are local ignored inputs and must be available legally with their original hashes. Missing or changed inputs fail; this command does not download replacement data or install models.

A version-1 JSON manifest names sealed `protocol` and `view_support` entries (`path`, `sha256`), sealed `inputs`, `runtimes` with relative file/hash maps, and original `producers` with sealed worker/script entries. It also names `main_data`, `research_data`, `native_receipts`, `feature_receipts`, `input_audit_receipts` and `expected` totals (`clips`, `frames`, `rows`, `family_eligible`, `side_eligible`). The execution section names the sealed native/feature runtime roots, `labels`, `court_path`, explicit `source_receipt_directory`, `pack_helper`, `association_helper`, R2/R3 `models` directories and pinned `reusable_artifacts`. Include both selected checkpoints/selections, perception weights, all source-clock receipts and original protocol/helper files in the seals.

Use a dedicated ignored output directory; never reuse an original producer directory:

```powershell
.venv/Scripts/python.exe scripts/recover_frozen_holdout.py --workspace <original-workspace> --manifest <sealed-manifest>
.venv/Scripts/python.exe scripts/recover_frozen_holdout.py --workspace <original-workspace> --manifest <sealed-manifest> --phase native --output .cache/holdout-recovery
.venv/Scripts/python.exe scripts/recover_frozen_holdout.py --workspace <original-workspace> --manifest <sealed-manifest> --phase features --output .cache/holdout-recovery
.venv/Scripts/python.exe scripts/recover_frozen_holdout.py --workspace <original-workspace> --manifest <sealed-manifest> --phase evaluate --output .cache/holdout-recovery --preflight <independent-review-receipt>
.venv/Scripts/python.exe scripts/recover_frozen_holdout.py --workspace <original-workspace> --manifest <sealed-manifest> --phase audit-results --output .cache/holdout-recovery
```

Native and feature phases require a fresh process with the appropriate frozen runtime. ROOT/DATA/WEIGHTS are pinned before app imports, and torchvision initializes before native decoding, including the shuttle-first resumed case. Native work requires CUDA. The real shared main Store must admit work before the research Store is constructed. An OS lock prevents competing writers to one output lineage; attempt records retain process identity, database backups, input inventory, parent admission and stage retry links.

Existing receipts are never replaced. New receipts and complete-stage artifacts are reused after validation. Ambiguous, partial or inconsistent artifacts stop recovery for inspection rather than silently overwriting evidence. Exact code bytes are pinned for each phase; changing execution code requires deliberate review before further execution. Every feature row is audited again, including reused caches. All 75 native/cache/audit chains and actual successful parent release must precede evaluation.

The independent preflight receipt records `schema_version: 1`, `verdict: "approve"`, the exact `code_sha256`, frozen `protocol_sha256`, complete `manifest_sha256`, a real `reviewer_session`, empty `blockers` and concrete `evidence`. This records an actual independent code/recipe inspection; an implementation agent must never manufacture that verdict. It is separate from final exact-head PR review and controller integration.

## Frozen evaluation and limits

R2 uses 254 values; R3 uses 371, at the identical R2 navigation frame, with exact common-254 parity. Published feet select a CV track and never become predictive feature values. Preserve the original selected heads, validation normalization, support masks, clipping and thresholds. Unavailable descriptors remain unanswered in both strict 677-row denominators. Saved probabilities and predictions receive a separate count/confusion/joint recomputation without new model inference. Partial saved predictions stop for inspection; completed model artifacts are not predicted again on resume.

This is conditional classification using published weak contact clocks, hitter association and court geometry. It does not measure automatic event detection, exact contacts, persistent identity, doubles performance or complete full-match annotation correctness. R3 was selected before this holdout; do not rank or tune models from its outcomes. Test-informed changes need another holdout. Neither model is promoted or installed by this work.

Generated software tests cover immutable publication, competing output locks, stopped/unverifiable process identities, source/runtime/model/cache changes, native stage reuse, successful parent release, actual shared Store denial before research inference, unknown/unavailable inputs, thresholds, strict metrics and independent saved-result auditing. Windows Python 3.10 passes 950 tests with four optional skips after incorporating verified main; 23 focused recovery tests pass. Ruff, formatting, dependency, tracked text/JSON/link checks and all 12 CI checks pass on implementation head `b9f9f6e64d8d5ec28318b2d91980968ec4bf071c`. Final report revisions are subject to exact-head CI and independent review through PR #107.

Independent preflight identified two gaps before any recovery inference or head predictions: the first result audit verified counts but omitted several saved summary/precision fields, and initial inventory alone did not guard changes during a multi-rally run. The revised audit independently verifies every published metric field, and execution rechecks sealed inputs between rallies and before completion. Generated corruption and between-case input-change regressions cover both repairs.

## Frozen results

Both models have descriptors for 724/860 source rows and 568/677 eligible rows. The 109 eligible rows with unavailable inputs remain unanswered and count as misses; the 183 unknown truth rows remain in the source accounting without becoming negative labels. The eight source groups include 227 `other` and 65 `serve` eligible rows alongside 385 rows from the six requested families. The six-family macro F1 below averages those six per-class F1 values computed from the complete eight-group confusion matrix.

| Model / fixed mode                 | Family answered / 677 | Strict family accuracy | Strict side accuracy | Strict family/side accuracy | Six-family macro F1 |
| ---------------------------------- | --------------------: | ---------------------: | -------------------: | --------------------------: | ------------------: |
| R2, no confidence abstention       |                   568 |                  0.381 |                0.759 |             0.357 (242/677) |               0.380 |
| R3, no confidence abstention       |                   568 |                  0.458 |                0.762 |             0.421 (285/677) |               0.465 |
| R2, original validation thresholds |                   295 |                  0.196 |                0.759 |             0.192 (130/677) |               0.196 |
| R3, original validation thresholds |                   199 |                  0.154 |                0.762 |              0.143 (97/677) |               0.102 |

R2/R3 eight-group macro F1 without confidence abstention is 0.404/0.475; these are different aggregates from the requested six-family values. Side answers cover 568/677 eligible rows in both modes. R3 was selected on validation before opening this source; these outcomes do not select another model, threshold or representation.

| Requested family | Eligible support | R2 F1, no confidence abstention | R3 F1, no confidence abstention | R3 F1, validation thresholds |
| ---------------- | ---------------: | ------------------------------: | ------------------------------: | ---------------------------: |
| Clear            |               56 |                           0.526 |                           0.742 |                        0.000 |
| Lift             |               54 |                           0.454 |                           0.486 |                        0.486 |
| Net              |              175 |                           0.509 |                           0.657 |                        0.000 |
| Drop             |               19 |                           0.186 |                           0.125 |                        0.125 |
| Smash            |               37 |                           0.500 |                           0.508 |                        0.000 |
| Drive            |               44 |                           0.105 |                           0.275 |                        0.000 |

Backhand drop and backhand smash have zero source support; this evaluation cannot certify them. Clear has only five backhand references. Without confidence abstention, R3 recognizes only nine complete drive/side tuples among 44 drive rows and two drop/side tuples among 19 drop rows. Its original validation thresholds answer no clear, net, smash or drive references correctly. No threshold was changed to rescue these test outcomes.

The source is one original singles match. Seventy-five rallies do not provide 75 independent match domains. Published source times/feet/corners are weak conditional supervision, not exact contacts, independently adjudicated mechanics, automatic serve/rally boundaries or persistent identities. Perception pretraining overlap is unestablished. Preserve this consumed holdout result, improve alignment/coverage and recognition using development sources, and freeze another complete-source holdout before evaluating test-informed changes. Neither model is installed or promoted.

## Execution evidence

The genuine independent preflight was published [before head predictions](https://github.com/Ken0u/badminton-match-analyzer/issues/63#issuecomment-6270525192). Frozen orchestration SHA-256 is `7bdfb1149c9684b178bf67997dc4138d329af5201733e22bd400abe35a4fae9f`; its 359-input manifest SHA-256 is `61c57c285790773136975e8b6f16afcd3d473ea571a53ff3a5a0c69d10a7fef5`, with original 54-file native / 55-file feature runtime maps. The independent preflight receipt SHA-256 is `556c94bf0dba39ab19b75eb58a08ef77083dde195037207d2c5dd8bbf63a315a`.

| Completed phase                          | Genuine main job                   | Completion receipt SHA-256                                         |
| ---------------------------------------- | ---------------------------------- | ------------------------------------------------------------------ |
| Native, all 75                           | `18711a15dd5a4772bc0e2eb4cbe0a127` | `b27a6e93a215825fd6f96bd6da2c6ac1c125876445d75d71f8f680b043482ede` |
| Features/full input audit                | `92f3e41c33da4db8863493b5a7203c87` | `4e1cbd4141bbee14f5671084a85aa14b99f51345e9997c5d6c9bcca4939b46c6` |
| Frozen CPU evaluation                    | `5d7f40c23de34fcfa5b593e47864a4ac` | `70e48a15f6520c02a67f0d86d4455beb284e8397aa4d117bade58c24631629b2` |
| Saved-result recomputation, no inference | Not a GPU/model job                | `f8aca7e1c90bcdb65ef6fbd462bc6cdf555f72d1e683793695a845572a79ef5f` |

Local proofs live under `.cache/holdout63-recovery-v1/attempts/`; they are not clone contents. Each model's saved probability/prediction artifact is hashed by the evaluation proof, and the result audit verifies all saved class/summary/availability/joint fields without loading weights again. The old native parent `9620824f51f8406f8da41529fd2cd504` remains interrupted. No data, weights, raw labels or private annotations are redistributed in this report.

A separate read-only reviewer independently recomputed every saved prediction and metric using its own JSON/SQLite/NumPy logic, without importing the recovery scorer/auditor or any application package, constructing a Store, loading weights or running inference. It verified all 75 transitive chains, 359 input seals, 109 runtime files, the original 67 chains plus ordinal 67's player run, raw main and original 68 initialized research annotations, and actual completed/released parents. Its independent receipt `.cache/holdout63-independent-results-audit.json` has SHA-256 `e2fc946c246d8b0273a16504f26b57d944b6a5958ef5beb56e69e9e4b577f7b2`. Generated checks and this numerical audit do not independently adjudicate badminton semantics.
