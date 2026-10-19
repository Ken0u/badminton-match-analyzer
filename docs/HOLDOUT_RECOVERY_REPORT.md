# Frozen 75-rally evaluation recovery

Updated October 19, 2026. Issue [#63](https://github.com/Ken0u/badminton-match-analyzer/issues/63) is in progress. No recovered head scores are published yet.

The original one-shot workers exited after 67 complete native, feature and input-audit chains. Their launchers assume a clean start and cannot safely resume existing non-anchor work. The new `scripts/recover_frozen_holdout.py` keeps original worker/receipt files intact and writes a separate recovery lineage. A completed job alone is insufficient: reuse checks its source, native clock, complete range, frozen model, calibration, scene and camera context, and artifact bytes.

## Preserved starting point

Read-only inspection on the original Windows host verifies all 75 source clips, 21,610 native frames and 860 published rows. Both original eligible denominators remain 677; 183 unknown truth rows per task stay separate. The 67 complete chains cover 18,962 frames and 747 rows, including 567 eligible rows per task. Ordinal 67 already has a completed 260-frame player run; its shuttle run has no artifact. Eight rallies / 2,648 frames still need native completion. These counts describe processing and source supervision, not annotation accuracy.

All five recorded producer process identities are absent, and a fresh scan finds none of their scripts under a new PID. The old main parent and one research shuttle job still have stale running states. Inventory never constructs a Store or updates those records. During execution, the normal atomic Store admission may interrupt verified stale jobs; it never changes an old job to completed.

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

Generated software tests cover immutable publication, competing output locks, stopped/unverifiable process identities, source/runtime/model/cache changes, native stage reuse, successful parent release, actual shared Store denial before research inference, unknown/unavailable inputs, thresholds, strict metrics and independent saved-result auditing. Final native/evaluation evidence, independent review and complete project checks remain pending.

Independent preflight identified two gaps before any recovery inference or head predictions: the first result audit verified counts but omitted several saved summary/precision fields, and initial inventory alone did not guard changes during a multi-rally run. The revised audit independently verifies every published metric field, and execution rechecks sealed inputs between rallies and before completion. Generated corruption and between-case input-change regressions cover both repairs.
