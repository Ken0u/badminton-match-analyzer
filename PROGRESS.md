# Badminton match analyzer: resume checkpoint

Updated 2026-10-18T23:06:28.916995+00:00. This collaborator handoff is tracked in Git. Read the newest snapshot first; older process counts and release descriptions are dated evidence.

## Latest collaboration snapshot

Updated 2026-10-18T23:06:28.916995+00:00. **PROGRESS.md is tracked**, and root `AGENTS.md` supplies
repository guidance. This supersedes the original ignored-temp-file preference.
PR29 is MERGED into remote main at **cc1a37bae9bf944b4d879763a6608fb30c225bc2**,
with all six exact-head checks green (workflow39174812437, local receipt
`.cache/handoff-pr29-ci-e06d630.json`). The user-requested files are accessible on
GitHub main. Merged-main validation for this docs-only handoff still needs its
final observation.

Current branch **feat/broadcast-timeline-supervision**, based on that merged
handoff. Its completed BFMD implementation, tests, report and package are being
committed/published separately as proposed **0.25.0**. It is not yet a merged
release; consult Git/PR state before treating it as current main.

**A fresh clone does not contain local artifacts.** `.cache/` scripts, receipts,
weights, source datasets and normalized labels referenced below are local-only.
PIDs and tool session handles apply only to the source Windows workstation and
this session. Revalidate them there; do not start replacement work just because
another machine lacks these files. Reproduce from committed source manifests and
CLI commands after obtaining permitted inputs.

BFMD completed increment:
- `backend/badminton/bfmd_data.py`, `bfmd_manifest.json`, `import-bfmd` CLI,
  `tests/test_bfmd_data.py`, `docs/BFMD_TIMELINE_REPORT.md` and aggregate machine
  receipt. All35 reference-file hashes/sizes verified. Actual import retains
  **34020 records /19 matches**, with local ignored output `data/datasets/bfmd/v1`.
- Preserves451 conflicting point-type frames,943 partial choice records,
  1058metadata rallies/four metadata-only intervals and raw result provenance.
  Valid weak contact support survives family ambiguity. Five predicted Rally
  intervals cannot certify live context for37manual hits, so248hits lie outside
  active manual rally support (211 outside any source rally).16503weak contacts /
  10850family targets eligible; zero side-label-eligible/training-ready rows.
- Range/result-type/provenance/overlap checks, source mutation rejection,
  exclusive output locks and byte-identical repeat import are covered. No app
  Store is opened; no GPU/model/video inference runs; app annotations are unchanged.
- **745 passed /4optionalGPUskips**,66.66s; all38BFMD focused tests pass.
  `.cache/bfmd-full-tests-v2.xml`. Ruff109files/check/format, dependency checks,
  report links/JSON and diff check pass. A first test attempt hit the default
  system temp-directory permission boundary; a fresh workspace basetemp fixed it.
- Built0.25wheelSHA **d776411a6a926affa7e50d679c991e83ea076b25faf04cc346c4704a91ced624**.
  All72package files match final worktree and extracted
  `.cache/installed-release-0.25.0`. Actual packaged CLI help and actual35-file
  import succeed without loading Torch, reproducing identical normalized bytes.
  `.cache/bfmd-package-verification-v1.json`. No runtime dependency upgrade.

The original five-worker75-rally chain below is unchanged and still running.
Latest native **60/75clips /16720frames**; inspect worker/progress files
for current cache/audit counts and eventual completion. Evaluator and independent
result auditor are already armed behind all75input and parent-job completion
checks. No new holdout head predictions had opened at this checkpoint. Original
source, models, thresholds, frozen runtimes and all860/677denominators remain
unchanged; BFMD does not enter that experiment.

Next: publish/review the BFMD feature, observe exact-head CI before merging, then
verify merged-main checks/package parity. Continue observing SAME five workers;
when all75 frozen results/audit finish, assess full-denominator metrics and update
reports without retuning this holdout. Both increments are intermediate work;
full-match automatic annotation remains unverified and unfinished.

## Objective and user preferences

Goal remains ACTIVE and far from complete: a polished deployable app that fully and correctly annotates uploaded AND public online/YouTube badminton singles and doubles. Required: players and shuttle, serve/rally start/end, clear/lift/net/drop/smash/drive, each with forehand/backhand. Half smash is removed. User requests regular bug review/tests and appropriate branches, commits and PRs eventually merged. A completed experiment or release is not goal completion.

User now requests `PROGRESS.md` and root `AGENTS.md` in Git so collaborators can access them. This supersedes the earlier ignored-temp-file preference. Keep this handoff current and commit meaningful checkpoints. No five-hour usage meter is exposed; refresh before long runs, on usage warnings and before handing over. `.cache/`, local videos, datasets, private annotations, credentials and research weights remain ignored.

Workspace: `C:/Users/enkra/Documents/Projects/badminton-match-analyzer`, PowerShell. Use `.venv/Scripts/python.exe` (Python3.10), not system Python3.14. Root `AGENTS.md` now contains repository guidance. No skill was applied for ordinary Python/CV work.

Previous goal turn = PROGRESS: committed actual results, merged a fully green research increment, source-reviewed all75, launched full native preparation and a guarded automatic evaluation/audit chain. Do not call the goal complete/paused/blocked. Current workers are verified live, not inferred from lock files alone.

## Git and completed research increment

- Latest merged **main** is **4caf543212fedc9fb07c55c01aed83a9b29ba49e**, version **0.24.0**. The current handoff branch and local in-progress feature are described in the newest section below.
- **PR28 MERGED** https://github.com/Ken0u/badminton-match-analyzer/pull/28 at2026-10-18T22:37:58Z. Feature implementation398abd799e5caa2addf4745ae16251e71820b1d6; final report7070a391e577c9a4ada590565e7219b9a7bcb697. Feature branch remains `feat/visual-event-learning`.
- All SIX exact-final-head checks SUCCESS, workflow39172431500, `.cache/visual-pr28-ci-7070a39.json`. All SIX merged-main checks SUCCESS, workflow39173082267, `.cache/visual-main-ci-4caf543.json`: Python3.10/3.12, frontend, browser-import, review+CPU containers.
- Software: **707 passed /4 optional GPU skips**,65.29s, `.cache/visual-full-tests-v2.xml`; Ruff107files/check/format, dependency consistency and diff checks passed. Generated CPU Torch lifecycle/equivalence tests ran locally, not badminton accuracy tests. No Python/package edits since implementation398.
- Wheel `.cache/dist/badminton_match_analyzer-0.24.0-py3-none-any.whl`, SHA **b374688c80777b79894a2527ed975ebf738367e7785564a500bacec0ec8b4ba9**. All **70 package files** byte equal merged main, worktree and `.cache/installed-release-0.24.0`. Receipt `.cache/visual-merged-package-verification-v1.json`. Packaged CLI/lazy Torch import/admission conflict checked. No reason to repeat passing checks absent changes/failure.
- Tracked `docs/VISUAL_EVENT_LEARNING_REPORT.md`, `docs/visual-event-learning-verification.json`, README/PROJECT_PLAN/BUG_REVIEW now contain actual results and audits. `docs/FOLLOWUP_SUPERVISION_REPORT.md`, matching JSON and reviewed `docs/figures/visual-event-learning-v1.png` committed. No pending untracked docs.
- Prior main was aac6f110398dd57467b9daae011f8fc9116a2912/v0.23/PR27, not current. Do not rewind.
- GitHub destination verified: authenticated userKen0u, ownerKen0u/private repository/ADMIN. Initial push auto-review rejection was resolved through this read-only ownership proof and approval of exact push. No permission pending. Never bypass a future rejection.

## ONE live full75 preparation/evaluation chain: do not duplicate

Fresh liveness check 2026-10-18T22:49:52.056239+00:00: all five recorded workers verified by PID/lifetime/cwd/command, UIhealth200. Native 26/75 clips/7465 frames; cache 26/75; audit 26/75. Receipt `.cache/new-singles-all75-latest-live-check.json`. Older counts below are historical snapshots.

Latest verified state is `.cache/new-singles-all75-continuation-state.json`. Before any stop/restart inspect fresh PID + creation time + cwd + command, jobs and artifacts. A timeout/unknown observation handle alone is not terminal. Unified sessions use `write_stdin`; `functions.wait` only for exec cell IDs.

All listed scripts are under `.cache/`, cwd repo, with explicit BADMINTON_ROOT and BADMINTON_DATA_DIR pinned BEFORE config imports.

| Role | Unified session | Actual PID / creation time | Script | Durable artifact directory |
| --- | --- | --- | --- | --- |
| GPU player/shuttle producer | **78070** | **7464 /1792363049.4145043** | `prepare-new-singles-all75-native-v4.py` | `.cache/new-singles-all75-native-v4` |
| CPU R2/R3 input cache | **22311** | **11376 /1792363233.4496484** | `cache-new-singles-all75-features-v2.py` | `.cache/new-singles-all75-features-v2` |
| Independent CPU input audit | **17561** | **3324 /1792363419.2631607** | `audit-new-singles-all75-inputs-v1.py` | `.cache/new-singles-all75-input-audit-v1` |
| Frozen CPU classifier evaluator | **29593** | **9104 /1792363598.4113605** | `evaluate-new-singles-all75-r2-r3-v2.py` | `.cache/new-singles-all75-r2-r3-evaluation-v2` |
| Independent saved-result audit | **3535** | **18516 /1792363654.4246716** | `audit-new-singles-all75-results-v1.py` | `.cache/new-singles-all75-results-audit-v1` |

GPU producer owns shared MAIN admission job **9620824f51f8406f8da41529fd2cd504**, RUNNING. Research Store **`.cache/new-singles-input-data`**. Latest native **20/75 clips /6752 frames /630.11s**; CPU cache20clips/273rows/235R2+R3 available/160eligible. Input audit19clips/6448frames (briefly behind). Evaluator waits for ALL75 input audit; result auditor waits for frozen evaluation. **No new holdout head predictions opened yet.** Inspect fresh status rather than treating these numbers as final.

Producer uses verified frozen **`.cache/live-release-0.16.1`**, YOLOsmall stride1 + TrackNet, every native frame. All54 package files match wheel SHA **56747c133c3c15cb492db66c4c1488d9be72e2bc524c07e44a6d69251247c144**. Three anchor native runs/annotations reused unchanged;72new clips receive source-only research geometry/unknown-prefix annotations. Main app annotations are untouched.

CPU cache uses frozen **`.cache/native-runtime-stroke-r3/backend`** and its snapshot hashes. R2 body254D, R3 observed-flight371D. Original R2 weak bags/navigation/pack_hitter reused. `.cache/new_singles_feature_tools_v1.py` adapts only hitter/opponent coordinate fields to the same R2 foot-association radii/support/margins. Source feet SUPERVISE a CV track choice; they never enter predictive feature values. R2/R3 body implementations match as UTF8 text despite raw CRLF/LF hash difference; common254 values are asserted equal on every available R3 pack.

All860 rows retained; exactly677 family and677 side eligible, unknown/ineligible labels=-1. Missing inputs remain unanswered in strict eligible denominators. No head predictions during preparation. This is conditional on published weak contact timing, hitter association and court corners, NOT automatic hit/hitter/persistent-ID or full annotation accuracy.

The input auditor independently checks all native clocks/PTS, frame counts, source/artifact hashes, calibration masks, disjoint track IDs across cuts, finite cache dimensions/masks/missing zeros, complete feature context isolation and repeated hitter-foot support. It does not establish localization/semantic truth. Each directory has protocol/worker/progress/per-case receipts and eventually completed.json.

Evaluator v2 waits for full input-audit proof AND the specific main native parent job to become completed before claiming MAIN admission. This fixes a real sequencing race: the native completion file is written just before run_local_job releases its lock. It preserves original model/normalization/threshold selection, CPU only. Result auditor independently recomputes full-row predictions/masks and metrics from saved probabilities and original validation thresholds, without new inference or GT writes.

Original frozen model hashes (do not retune or choose winner from test):
- R2 `.cache/yolo-stroke-model-v2/selected.pt`, SHA **ef71574cac55f1cf5441e1ba11cbf2f4b9eafa31298d2078e87a7018d22ae10e**, epoch80. Selection JSON SHAc52755e6a366cc45e88ebdcd035a4e747c9d0b3fe9ac26e9c37798ec56c5afa9.
- R3 `.cache/stroke-context-model-r3/selected.pt`, SHA **cae34a9f39cef5c0c45185c354c967ace2d81f9ea4750233ef9f8881e4b42dcc**, epoch295. Selection JSON SHAba9da58051f6bf30d6892d433776ad1a18c9008cbf8d9e8c7f77c3e3b26d1faa. R3 is the predeclared selected representation. R4 rejected, no new R4 or old forbidden test3 predictions.
- Closed-set and original validation-abstaining scores will both be reported across all75/all677 eligible. No models installed automatically. Any result-informed training change requires another holdout.

Preserved terminal research-helper failures, NOT live workers or production regressions:
- Native-v3 failed before any new model stage: frozen0.16.1 Store has jobs(), not job(). v4 corrected lookup; separate artifacts, no GPU repetition.
- CPUfeatures-v1 wrote valid case0 then JSON failed on numpyint64 counts. v2 uses Pythonint counts/new output; CPU-only recomputation.
- Evaluator-v1 (oldsession30259/PID7636) explicitly stopped after fresh identity and no-prediction proof, before any test head prediction, to fix lock sequencing. `.cache/new-singles-all75-r2-r3-evaluation-v1/stopped-before-predictions.json`. v2 above supersedes it. Do not rerun old helpers/overwrite workers.

## Frozen source75: recovered and verified, not a substitute source

Original `.cache/new-singles-holdout-protocol.json` SHA **99b13bb12f0cacfee316547ee656ac69a0b6f273de20e75c80eb49e19892c6ed**, v2ALL75 rallies/860rows/677eligible, no exclusions. Exact URL https://www.youtube.com/watch?v=-aOI9_JxoWc, official BWF channelUChh-akEbUM8_6ghGVnJd6cQ, ChouTienChen/ChenLong2019WTFinals, format398/1280x720/25fps/3817seconds. Older gated status is superseded: after ordinary anonymous BWF metadata checks succeeded, one normal recheck of original source succeeded. No cookies/auth/alternate clients/cached signedURLs or bypass; no protocol/source substitution.

`.cache/new-singles-source-access-v2/source.mp4`,309811368bytes SHA **76c75c4bcecff975926c91fb94ad1e3e4b49df96f376db5b06c46f76c8ac11c5**. Acquisition43924terminal0. Local producer51913terminal0, `.cache/new-singles-source-fetch-local-v2/progress.json` completed75; media `data/datasets/shuttleset/media/new-source-match2-rallies`.72new clips pin fresh parentSHA;3anchor bytes/provenance reused, not retroactively claimed from new bytes.

Verification25706terminal0: ALL75/**21610 selected native rally frames**/860rows, every cliphash/source+localPTS/rowbounds checked. `.cache/new-singles-source-verification-v2/completed.json`, ledgerSHA **2a42203c04418f0b199736bc36297bee83013e2f8d2be0bf04e3d033c5e446ee**. Not all95425broadcastframes. Normalized labels `data/datasets/shuttleset/v2/strokes.jsonl` SHA **2fb3fdca1bd544179367b5bcc0cd3679c7001fb1f697e5cf29e69b327801a881**. Source first/mid/last-cue sheets27images viewed, not exact contact/semantic adjudication.

CPUpreflight37500complete: `.cache/new-singles-all75-preflight-v2/completed.json`,75registered/21610frames/860rows/26camera cuts, main and3anchor annotations unchanged, no new inference. Source-view review then viewed ALL8sheets/300samples (4perclip),2sheets/30wipeframes plus prior26cutpairs/52images. `.cache/new-singles-all75-view-review-v3/frozen-view-support.json` SHA **1b2e035e536e6ef74b1704b37275fab0e30d74c58fb3d2e45c4cd656f1df8b78**. Stable wide court at samples; continuity between samples inferred, not independent dense human truth. First clean wipe frames: request4frame26,31frame24,46frame23. Prefixes stay unknown/un-calibrated; other cuts begin court support at cut; no-cut cases at0. Three anchor geometry annotations unchanged. Original protocol and labels unchanged.

## Completed RGB baseline: inadequate, not promoted

Root `.cache/visual-event-learning-v1`. ALL800clips/264791frames,3380.107s extraction complete; source scanner exactly equals prior merged-main scanner on every frame/cut/reason/PTS. Full independent cache audit complete. Equivalence/integrity is not camera accuracy.

Fixed100/100 training epochs, training total1017.38s,4665 positive bags/13995samples. Validation finalized epoch25/threshold0.5 BEFORE test: contactF1 .5475099297, tupleF1 .1863733578. ALL200testclips/1454 weak references/653predictions:
- Contact167TP/486FP/1287FN, F1 **.15851922164214524**.
- Full time+family+side+court-end tuple29TP/624FP/1425FN, F1 **.027527289985761746**.
- Six requested-family macro tupleF1 **.02866163873656312**. Net and drive zero predictions.
- Hall149clips/993refs:contactF1 .1403508772,tupleF1 .0285899935. Paris51clips/461refs:.2077464789/.0246478873.
- Conditional over ONLY167 timing matches:family .23353293,side .77245509,court-end .70658683. Never substitute for full annotation accuracy.
- Backhand smash6TRAIN/6VAL/0TEST, unvalidated. No persistent identity, doubles, full-match or rally-end correctness established. Source weak labels are not independent human truth. No test tuning or app promotion.

Artifacts: frozen-protocol.json, features/completed.json, cache-audit/completed.json, main-admission-completed.json, run/history.jsonl(100rows), run/protocol.json, run/selected.{json,pt}, run/normalization.npz, run/completed.json, heads-run-completed.json, test.json, results-audit.json. CPU audit exactly recomputes all metrics. Old feature84603/guard2763/trainer22767/cache27962/result8826 work is DONE; PID15188 absent. Do not duplicate it.

WeightsSHA f518e8442edd89f817c1f365c258f294af26e3f5ec22afa4b2ec950bb37199f3; selectionSHA2aacc87a40981a0d332e796469c670b90f634c887abe1776611988b4292d2e22; testSHAc1d9fb18de0d19a07662f0d9ec217f591da5b7c60429d7a07b6d2e0681a4ae7e.

Capture manifestSHA7e97f6101cb7339a339bc0f8b0ab4e6142c0e0157101217fbac93a0bf933afc5; learningmanifestSHA3a7c907671673ec17e4296ded59d7a0f78d40283d7fe4b22fcb7e48f8c05211e. Whole contextsTRAINBangkok/KualaLumpur/Birmingham/Osaka/Tokyo/Jakarta red+blue,VALOdense,TESThall+Paris.424/176/200clips/4684/1707/1454refs,169unlabelled clips excluded.43matchnames unresolved;175hallclips deliberately pooled. Conservative groups, not proof of global source independence.

Generic ImageNetMobileNetV3Small SHA047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f; full orientedRGB512x288letterbox/2x2pool=>2304float16, trueTRAINpixelmirrors/no annotation-derived features. Context31bins+/-0.5s30Hz,nearest<=.025,gap<=.1,3distinctflankobs,maskeveryhiddenlayer,no cutcrossing. H interval[max(0,H-1),H],H0censored/allrefs retained. Seed20261018/hidden128/dilations1,2,4,8/dropout.1/100ep/eval5/AdamW.001wd.01/2negexcl.2/train-onlynorm. Frozen validation tupleF1 selection, tiecontactF1/earlierepoch/grid.1..9/.95/NMS.16/tol2/30s. No fake exact contact/rally-end targets from winners/laststroke/clipedge.

## Live UI and shared-state rules

UI **http://127.0.0.1:8000**, health200 verified at this checkpoint. Same verified64-file **0.22.0** runtime; no research models installed. Actual **PID11132 creation1792363287.8197672**, wrapper7860, cwdrepo, script`.cache/serve-live-release-0.22.0-detached-v2.py`. Hidden Start-Process launch session**65903** may remain open because children; do not stop it. Identity`.cache/live-0.22.0-detached-v2-identity.json` phase serving; logs`.cache/live-0.22.0-detached-v2{.log,.err.log}`. Startup before-proof`.cache/live-0.22.0-detached-v2-before.json` preserves main annotations and native job.

Old UI11404/2508 and older1808/16988 all absent, portclosed verified before restore; session43683unknown. Do not kill reused historical numericIDs. Check fresh process/lifetime/cwd/cmd/listener/jobs first.

Both supplied annotation files remain revision4/sixevents each, unknown family/side. Original feature wrapper once omitted explicit root and queried EMPTY isolatedStore. Preservation proof is REAL main-annotations-before-adoption.json plus adoption/completion, never empty original main-annotations-before.json. Future frozen launchers MUST pin root/data before config imports and own the real main admission lock.

Import torchvision BEFORE threadedPyAV. Preserve av_runtime.open_media nativeFFmpeg logging beforeopen ANDfinallybeforeclose. Windows trackedfilesLF (`newline="\n"`), explicitUTF8reads. Do not silently normalize frozen snapshotbytes; preserve hash provenance. Raw PowerShell stdin CJK can corrupttext; use apply_patch/Unicode escapes. No recursive delete/move without resolved-path checking. No gratuitous dependency upgrades.

## Broader supervision remains separate

Read committed `docs/FOLLOWUP_SUPERVISION_REPORT.md` and `docs/followup-supervision-verification.json` before new data work. Source receipts/raw files `.cache/new-corpora-source-audit-v1`, not Git. None entered current RGB experiment. No external source code executed or messages sent.

BFMD: pinned Ning-D/BFMDc7c7e8e4c815085dda42746f16e07f1172503312.35public referencefiles/14709189bytes,12singles+7doubles,16751genericHITmarkers/1688Rallyintervals.451familyframe conflicts/4metadata-onlyrallies/211doubleshits outside rallies/5prediction-origin results inside annotations. Partial doubles choices not complete side/hitter truth. Originalvideo30fps convention not decoded clock proof. Terms noncommercialacademic/no redistribution; do not bundle data/derived models as unrestricted deployment assets. Two ordinary BWF metadata checks succeeded; no BFMDvideos downloaded.

DShuttleNet: arxiv2610.14016/DOI10.34740/kaggle/dsv/16097938 ->Kaggle anonymousay58dki/dshuttlenet/v7 dataset10314057. DatasetCCBY-NC-SA4.0, not paperCCBY4.7CSVarchive10263241bytes SHAe3896a016f8cf22116d3c7d4412fe986350747549aa3bed74ca3c7dc213524b4.58matches134sets/raw4846rallies58359shots/processed4483rallies54141shots. Processed drops ALLtime/framefields; allshotIDs joinraw.21blanktypes/25retainedflaw1/1reverseinterval/3outside-rallyintervals.4218omittedshots are entire363rallies, not simple flawfilter;19retainedrallies have flawedshots. Video clock/contact/backhand0/1semantics unverified. Exact priorS2matches overlapDIDs5/6/7: quarantineall3 for new independence;55others candidates only.

F3Set commit04c6013d0aab13a3f92be58aed958becbcac392d:112clips1692events, five exact parentvideos overlapTRAIN/VAL, badmintonREADME asks contactauthorsforvideos; no messages/guessed substitutes. ExistingFinebadminton20K has77BHsmashactionintervals, not exactcontacts. Separate2026Fine-BadmintonZenodo20292976 metadataonly6.455GB notdownloaded; textnoncommercial vsAPIlicenseCCBY4 conflict unresolved. Do not inherit different2025datasetterms.

## Next actions

1. Poll SAME five workers above. They are already armed to complete native inputs, all75 audit, frozen CPU model evaluation and saved-result recomputation. No extra GPU work. On timeout inspect fresh identities/jobs/artifacts; never restart solely from observation failure. On real failure preserve original artifacts/error and inspect the cause before a deliberate continuation.
2. After `.cache/new-singles-all75-results-audit-v1/completed.json`, read full677-denominator closed-set/validation-abstaining R2/R3 metrics, all16family-side cells, unavailable cases and all860 accounting. R3 is predeclared; do not choose/tune from test. These conditional weak-source scores still do not establish automatic/full-match accuracy or fully unseen upstream pretraining.
3. Update the observed-flight/follow-up/project/bug reports with actual all75 evidence, including source-view first-pass limitations. Make a new appropriate branch from cleanmain for changes, commit/review/push verifiedorigin, all6exact-headCI then merge and verifymergedmain. CurrentPR28 is already done, not pending. Do not install inadequate models.
4. Continue meaningful development toward full match/serve/end/shuttle/identity/doubles and source-aligned balanced supervision, preserving unknowns and source-level splits. New corpora require native-clock/rights/overlap/field-quality checks. Any result-informed model change needs another holdout. Independent human full-match review remains necessary evidence.
5. Keep verified UI running/mainannotations untouched, shared admission correct, native logging fix intact, and refresh this tracked handoff at milestones/before yielding.

Prior full checkpoint archived at `.cache/progress-checkpoints/PROGRESS-before-20261018T224939Z.md`. Older rejected-model/source-provenance details are in that archive and earlier `.cache/progress-checkpoints/` snapshots; read them only as historical evidence, not live status.
