# Portable observed-stroke development recipe

October 20, 2026. The fixed R3 CPU training/validation experiment now has a
clone-contained module, CLI and [public parameter manifest](../data/manifests/portable_stroke_training_v1.json).
It reproduces the [observed-flight study](OBSERVED_STROKE_CONTEXT_REPORT.md).
This is conditional classification from precomputed weakly supervised features,
not complete contact detection, persistent identity or full-match accuracy. It
does not improve or install an application model. Half smash remains excluded.

## Inputs and usage

The clone supplies code and parameters. It does not supply original labels,
features, media, models or local receipts. Obtain legally available original
inputs with their pinned hashes. S2Doubles has no license file at the pinned
commit; keep labels, derived features and weights local, outside release assets.

The input root must contain the original corpus plan, its complete match-1 and
match-2 R3 metadata/NPZ pairs, feature recipe, pinned original `Match.csv` and a
copy of the public parameter manifest. Match 1 is the whole-match training group
`EpLD0HrwDJU`; match 2 is validation group `kbHgum5unYc`. Each has 67 clips. The
sealed source plan and original catalog prevent relabeling another source as a
group. Every original row remains in the manifest, including unavailable inputs.
No native perception or feature extraction runs here. No local helper script is
imported or executed.

Use the existing project virtual environment with the declared `learning` extra,
or an appropriate existing CPU/CUDA profile. Computation uses CPU tensors and two
threads even when PyTorch was compiled with CUDA. Do not migrate a research
environment to reproduce this command.

```text
python -m badminton.stroke_learning prepare --root <input-root> --plan <original-plan.json> --features <original-r3-features> --source-catalog <original-Match.csv> --protocol <public-parameter-manifest.json> --output <new-input-manifest.json>
python -m badminton.stroke_learning audit --root <input-root> --manifest <new-input-manifest.json> --manifest-sha256 <returned-sha256>
python -m badminton.stroke_learning train --workspace <real-app-workspace> --root <input-root> --manifest <new-input-manifest.json> --manifest-sha256 <frozen-sha256> --output <real-app-workspace>/.cache/<new-run>
```

The equivalent source-checkout entry point is `scripts/train_observed_strokes.py`.
Record the returned manifest hash before training. Paths inside that manifest
are relative to the explicit input root, so relocating an unchanged input tree
does not require a Windows-specific directory layout. The fixed protocol is
validated as typed JSON; changed parameters require a deliberately reviewed new
recipe, not an unnoticed argument override.

The real workspace must already own `data/processed/catalog.sqlite3`. The CLI
pins `BADMINTON_ROOT` and `BADMINTON_DATA_DIR` before application configuration
imports, refuses an already-loaded different configuration and uses that main
Store's actual `run_local_job` admission. It provides no research-Store bypass.
Output must be a new ignored workspace cache directory. An atomic exclusive
directory creation excludes another writer and refuses existing runs, including
partially completed ones. Inspect the original process, job and artifacts before
any retry; v1 does not resume or overwrite an earlier training attempt.

## Frozen behavior and receipts

The input audit checks the complete ordered clip list, original-source groups,
source/feature recipe hashes, metadata and NPZ bytes, per-clip source row counts,
row identities, finite float32 features, boolean availability and integer labels.
Changed inputs, path escapes, duplicate files/rows, overlapping sources and
substituted or partial splits fail. Parsing uses the exact hashed bytes rather
than reopening an unverified feature file.

The original architecture, seed, 300-epoch schedule, inverse-square-root class
weights, training-only normalization and validation-only selection/threshold
policy remain fixed. Each output learns only from its known labels. Unknown
truth stays distinct from unavailable features and confidence abstentions;
unavailable eligible rows remain misses in strict metrics. Selection ties retain
the earlier epoch. Unsupported or insufficiently evidenced classes remain
disabled instead of forcing labels.

Input and execution-code seals are checked again during progress and before
model publication. A new run preserves `attempt.json`, `inventory.json`,
`protocol.json`, `progress.json`, `selected.pt` and `validation.json`. The saved
validation report includes runtime, model/code/input hashes, selection history,
threshold evidence and the real main job ID. `completed.json` is published only
after the main job runner persists successful completion. Selected artifacts
are never replaced. The checkpoint is loaded with `weights_only=True` as a
serialization check, without another model prediction.

## Actual development reproduction

Windows Python 3.10, PyTorch 2.8.0+cu126 in CPU mode and NumPy 2.2.6 completed all
300 epochs under real main job `5ff31a0441e947fa8e397787f4aa245d`. The process
exited successfully, the durable job is completed, and the post-job completion
receipt exists. The original input/model inventory's 276 seals remain unchanged.

| Check | Result |
| --- | --- |
| Training / validation clips | 67 / 67 |
| Complete source rows | 624 / 672 |
| Available inputs | 608 / 662 |
| Selected epoch | 295, identical to original R3 |
| All selected tensor values | Bit-identical to original R3 |
| Normalization, support and thresholds | Identical |
| All 60 selection-history rows and validation metric fields | Identical |
| Validation eight-group family macro F1 | 0.5904365878913957 |
| Validation side balanced recall | 0.8943043884220354 |
| Validation conditional family/side accuracy | 0.5744047619047619 |

The reproduced checkpoint SHA-256 is
`79f3e397b4dfcf8359d0d400a1a6977a45ed01d3f4bf666e8e2499045806a257`;
the original is
`cae34a9f39cef5c0c45185c354c967ace2d81f9ea4750233ef9f8881e4b42dcc`.
The container metadata and provenance differ; saved tensor values agree exactly.
This observation does not promise bit identity across other PyTorch, NumPy, CPU
or operating-system runtimes. Compare values, selection and metrics while
recording the actual runtime, rather than treating a different archive hash as
proof of a different learned state.

The execution input manifest SHA-256 is
`8d0fe34c21cda1f877b11ad967d643275c0a58ae377737e2f7759508f651d8d0`.
The executed learner source SHA-256 is
`d7622c37916bf4144e5fe52d539e2cee6e9b1875a9c2c38f81367131288565c3`.
Local evidence remains under `.cache/portable64-reproduction-v1/` and
`.cache/portable64-original-comparison.json`; neither is supplied by a clone.

## Verification and limits

All 35 focused generated-input tests pass, including changed seals, source/split
overlap, unknown/unavailable denominators, partial-label learning, deterministic
selection, validation-normalization isolation, admission denial, changed inputs
during execution and immutable outputs. The complete Windows Python 3.10 run
passes 1,289 tests with four opt-in GPU checks skipped; generated-media checks
execute with FFmpeg/FFprobe on the verification PATH. Ruff, formatting, dependency
consistency and repository UTF-8/LF/JSON/link checks pass. Exact-revision CI,
independent controller review and integration receipts are recorded on
[the owning task](https://github.com/Ken0u/badminton-match-analyzer/issues/64).

These are development reproduction and software results. Published clocks,
hitter-foot association and mechanics remain weak supervision; rare-class,
contact, serve/rally-boundary, doubles attribution and persistent-identity
failures remain. The [consumed held-out comparison](HOLDOUT_RECOVERY_REPORT.md)
is preserved and was not reopened by this work. No production model is promoted;
test-informed improvements require another complete-source holdout.
