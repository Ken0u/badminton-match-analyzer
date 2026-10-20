# Published shuttle-coordinate supervision preparation

Owning task: [issue 143](https://github.com/Ken0u/badminton-match-analyzer/issues/143), under [localization milestone 65](https://github.com/Ken0u/badminton-match-analyzer/issues/65). Completed source preparation, October 20, 2026: **201 published rally clips / 91,214 label rows are retained alongside 91,579 decoded native frames.** Twenty-five CSVs omit 365 trailing native frames; the frozen complete-coverage gate quarantines their 12,235 published rows. This is source-aligned preparation for future localization work, not improved detection accuracy. No model was trained, evaluated, installed or promoted; all training and deployment eligibility remains false.

The negative [fixed-resolution comparison](SHUTTLE_RESOLUTION_REPORT.md) left the true-component bottleneck unchanged. Stronger source-aligned supervision is a prerequisite for a subsequent detector experiment. This increment imports published coordinate labels, native clocks and publication groups without converting those labels into expert-reviewed application truth or selecting a new held-out benchmark. Parent 65 remains open.

## Source and permission boundaries

The [public source manifest](../data/manifests/shuttle_supervision_sources_v1.json) pins the [creator documentation](https://hackmd.io/@TUIK/rJkRW54cU), the [TrackNetV3 revision](https://github.com/qaz812345/TrackNetV3/tree/6eda442ada1740573f200f836d93edc9a541ee86), and a separately identified [public archive supplier](https://github.com/AnInsomniacy/tracknet-series-pytorch/releases/tag/dataset-v1.0.0). The creator's current SharePoint link redirected to Microsoft sign-in during the preflight. No credentials or access requests were submitted. The separate mirror archive matches its published SHA-256 and exact 1,731,120,724-byte size; this does not authenticate it as creator-supplied data.

The archive contains 492 members: 201 CSV files, 201 MP4 files and 90 directories. It supplies no extracted frame images, descriptions, license or usage documents. Thus there are no image-frame sidecar ordinals or image pixels to corroborate against the videos. Published CSV frame references are checked against actual native decode, with their publication provenance retained. The lack of source-image sidecars is not treated as evidence that image/annotation identity has been independently established.

The upstream repository states that its code and pretrained checkpoints are MIT licensed. That statement does not establish dataset/media rights, mirror authenticity or permission to train or distribute a derivative model. This task approves none of those. Dataset redistribution, training, model deployment and independent-test eligibility are explicitly false. Raw archives, video, labels, decoded clock records and local receipts stay ignored; no raw dataset content is included in the repository or application builds.

## Actual corpus and complete denominators

| Publication namespace | Groups | Clips / CSVs / videos | Native frames | Published rows | Structurally eligible visible coordinate references |
| --- | ---: | ---: | ---: | ---: | ---: |
| Amateur | 3 | 26 / 26 / 26 | 9,525 | 9,466 | 7,451 |
| Professional | 23 | 146 / 146 / 146 | 69,396 | 69,092 | 51,242 |
| Test | 3 | 29 / 29 / 29 | 12,658 | 12,656 | 9,950 |
| All | 29 | 201 / 201 / 201 | 91,579 | 91,214 | 68,643 |

All 201 CSVs use the supported `Frame,Visibility,X,Y` header and parse completely. All 201 videos decode with 1280x720 source geometry, zero rotation and usable increasing native PTS. No video/label orphan, duplicate video byte hash, unexpected visibility value, malformed coordinate, nonfinite coordinate or out-of-bounds coordinate was observed. There are 78,952 publisher-visible rows and 12,262 publisher-not-visible rows. These are publication states, not newly observed expert labels; the not-visible flag does not distinguish occlusion from leaving the image and does not provide an inferred hidden position.

The 26 named professional/test groups in the pinned creator tables are present. Their per-group native frame totals agree with those tables. The creator's older aggregate overview gives 78,200 frames; the actual Professional and Amateur partitions contain 78,921 native frames, including 69,396 Professional frames, before the separate 12,658 Test frames. The importer records the observed counts and the creator assertions separately, rather than forcing the archive into the older aggregate figure.

Exact native ordinal coverage is established for 176 clips, containing 78,979 published rows. The remaining 25 clips contain 12,235 published rows and 12,600 native frames: 10,309 of those published rows are visible and 1,926 are not visible. A read-only inspection of retained frame indices finds a contiguous zero-based published prefix in each of these files, followed by 365 unlabelled tail frames overall, without duplicate or extra ordinals. This describes the omission; it does not justify reconstructing missing labels, marking tails negative or relaxing the frozen complete-file alignment gate. Every affected row and every native frame remains in the output, including the original published ordinal and the complete independent source clock.

The 68,643 visible coordinate references pass only structural bounds and complete ordinal/clock coverage. This count is not localization accuracy or certified ground truth. The 25 incomplete CSVs stay quarantined as declared before acquisition, rather than retaining only convenient aligned examples. All 91,214 published rows and all 91,579 native frames remain in coverage denominators; training-ready rows remain zero.

## Source groups and unavailable labels

Groups below preserve the publication namespace and whole match/session grouping before any future split. A namespace such as Professional/match1 is distinct from Test/match1. Named creator assertions remain separate, unverified metadata; amateur session identities and cross-corpus/near-duplicate overlaps remain unresolved. No fresh train/validation/test selection is performed. The absence of duplicate MP4 bytes does not prove original-match disjointness across corpora or different encodes.

| Published group | Clips | Native frames | Published rows | Structurally eligible visible references | Quarantined clips | Unlabelled tail frames |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| amateur/match1 | 10 | 3,233 | 3,230 | 2,529 | 1 | 3 |
| amateur/match2 | 9 | 3,278 | 3,222 | 2,134 | 3 | 56 |
| amateur/match3 | 7 | 3,014 | 3,014 | 2,788 | 0 | 0 |
| professional/match1 | 12 | 3,298 | 3,298 | 2,664 | 0 | 0 |
| professional/match2 | 8 | 3,227 | 3,184 | 1,647 | 3 | 43 |
| professional/match3 | 7 | 3,190 | 3,166 | 1,280 | 3 | 24 |
| professional/match4 | 8 | 2,915 | 2,896 | 1,769 | 2 | 19 |
| professional/match5 | 6 | 3,371 | 3,371 | 3,072 | 0 | 0 |
| professional/match6 | 5 | 3,479 | 3,479 | 3,214 | 0 | 0 |
| professional/match7 | 5 | 3,161 | 3,134 | 1,916 | 2 | 27 |
| professional/match8 | 8 | 3,353 | 3,353 | 2,943 | 0 | 0 |
| professional/match9 | 9 | 3,203 | 3,203 | 2,949 | 0 | 0 |
| professional/match10 | 5 | 2,673 | 2,673 | 2,366 | 0 | 0 |
| professional/match11 | 5 | 2,791 | 2,791 | 2,418 | 0 | 0 |
| professional/match12 | 5 | 3,257 | 3,206 | 2,352 | 1 | 51 |
| professional/match13 | 6 | 2,608 | 2,589 | 1,091 | 2 | 19 |
| professional/match14 | 5 | 2,839 | 2,774 | 1,070 | 3 | 65 |
| professional/match15 | 5 | 2,673 | 2,673 | 2,327 | 0 | 0 |
| professional/match16 | 6 | 2,969 | 2,924 | 1,740 | 2 | 45 |
| professional/match17 | 6 | 2,932 | 2,932 | 2,731 | 0 | 0 |
| professional/match18 | 6 | 2,690 | 2,690 | 2,127 | 0 | 0 |
| professional/match19 | 5 | 2,828 | 2,828 | 2,363 | 0 | 0 |
| professional/match20 | 6 | 3,161 | 3,161 | 2,429 | 0 | 0 |
| professional/match21 | 7 | 2,678 | 2,678 | 2,453 | 0 | 0 |
| professional/match22 | 5 | 3,008 | 3,002 | 2,112 | 1 | 6 |
| professional/match23 | 6 | 3,092 | 3,087 | 2,209 | 1 | 5 |
| test/match1 | 11 | 4,222 | 4,222 | 3,602 | 0 | 0 |
| test/match2 | 7 | 4,233 | 4,231 | 2,756 | 1 | 2 |
| test/match3 | 11 | 4,203 | 4,203 | 3,592 | 0 | 0 |

The pinned TrackNetV3 documentation combines the Professional/Amateur sources into its training layout and uses the published Test namespace for upstream evaluation. Exact checkpoint membership is not re-established here. These are upstream/pretrained-source data, not a newly selected independent full-match holdout. No consumed holdout-63 inputs, predictions, protocols, private membership metadata or artifacts were accessed.

Native clocks do not certify live-court camera context, scene exclusions, calibration, exact serve/contact/rally boundaries, persistent identities, stroke families or forehand/backhand labels. Filename scores and rally clips are retained as publication identifiers, never substituted for those event times. This corpus also does not establish independently reviewed doubles or actual occlusion-category support. Those requirements and an independent full-match evaluation remain open.

## Execution, recovery and provenance

The portable entry point is `scripts/prepare_shuttle_supervision.py`, with `fetch` and `import` modes. Reproduction needs a repository clone, the pinned declaration/snapshots and original local source inputs; a clone alone does not contain the dataset or results. Pin `BADMINTON_ROOT` to the original root, `BADMINTON_DATA_DIR` to its existing real `data/processed` Store and `BADMINTON_WEIGHTS_DIR` to its original `models/weights` before imports. Obtain a genuine bounded data resource grant before heavy reproduction. An isolated research Store cannot supply admission.

Both actual stages used the real shared `run_local_job` admission and the genuine `data:windows-primary` reservation. The 76.031-second fetch verified all archive bytes before exclusive publication. After its process lifetime exited and Store job completed, the 61.312-second import used a separate ignored lineage, streamed/checked all selected members and decoded all 201 videos. These are acquisition/preparation wall times, not model inference speed. Python 3.10.5 / PyAV 16.1.0 and the other recorded library versions are bound in the runtime context. Torchvision was initialized before threaded PyAV; native FFmpeg logging restoration was preserved. No model or GPU inference ran.

PID, creation time, working directory, exact command, input/code/runtime context and Store job are recorded before data work. Fetch job `c07992ea6d9f466683a59c83380b453a` and import job `6b449ae83b5d4d85a2b5283cfa7f59d7` are completed; both original process lifetimes have exited. No existing process was stopped or restarted. Original datasets, caches, predictions, annotations, weights and environments remain unchanged.

Every archive member is censused before extraction, including unknown layouts. Original Windows ZIP names are checked before Python's normalization can hide a backslash. Unsafe, conflicting, encrypted, special or over-budget members fail before extraction. Outputs publish through flushed exclusive pending files without replacing existing evidence. Another research folder and the shared cache root cannot be adopted as a new output lineage. Consumer-copy races fail before admission, and context changes during work fail the actual Store job before completion.

Each complete clip checkpoint binds raw inputs, native PTS/geometry, all published rows and source assertions to the frozen context. Resume requires the recorded terminal receipt SHA, unchanged source/runtime/consumer bindings, unchanged complete-file seals, the original exited process lifetime and its matching terminal shared Store registration. Interrupted pending artifacts remain. Neither a timeout nor a missing observation handle is treated as process exit.

[Pre-data source checkpoint](https://github.com/Ken0u/badminton-match-analyzer/issues/143#issuecomment-6290270663) preserves executed source `afded3907ee73771e0a2fbb6ad73e4a6e93041f6` before acquisition. All 51 recorded Python consumer files were frozen and copied; final report edits change documentation only. No inputs, label semantics, ordinal policy, thresholds or eligibility criteria were tuned after opening this archive.

| Evidence | SHA-256 |
| --- | --- |
| Six-snapshot source declaration | `1536d95d96032414ac72a3635c9ff5a40dfbc7e8da1f513de59be7cffd0c1b9b` |
| Public source manifest | `4387319793df08dd410a39006584a0d9de97a20d4d9f7b85f094c6760fb9316e` |
| Dataset archive | `f87ccd54318e2e6366f2e820ba8dc1a04203c132582fc664867f0d1029bef465` |
| Executed context (51 consumers/runtime/source bindings) | `27232a130865084106e43fd3ba5e6610f6d8fa774016ea34c4920e47fa41ac2b` |
| Fetch terminal receipt | `bf9929504ce2fefa1e3639c558166bf15090bc15857cd7e7717fb2ead7637473` |
| Complete source audit report | `d6044119d4b939865dfbabc00dc94874e9a4a8da4dabfb7be391289522c0c4fa` |
| Import terminal receipt | `4c7029762fc07e80c0b79d50981b2c02fd7cbe52f0b8159ae75290f7a60e93f6` |

The acquisition code passes 37 focused regressions and 1,413 full-suite tests, with four optional GPU skips. Tests include actual VFR/native identity, real shared admission, unknown/orphan denominators, path safety, exclusive interrupted writes, source/clock/receipt tampering, PID reuse, consumer changes and output ownership. Ruff, formatting of 160 files, dependency and diff checks pass. Exact-final-head CI, genuine fresh independent review, controller integration and merged-main/full delivery are tracked on the owning issue and PR; they are not inferred from local checks.

No source preparation count is a model accuracy score. Next resolve source provenance/permissions and remaining alignment/scene/identity uncertainty, then freeze the appropriate source-separated development protocol for actual localization work. Broader singles/doubles and independent full-match correctness remain unproven.
