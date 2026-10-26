# New real-video supervision: qualification before acquisition

Observed October 26, 2026 (UTC), under [task #315](https://github.com/Ken0u/badminton-match-analyzer/issues/315).
Five primary-source leads were checked after the fixed-checkpoint comparison
in [#313](SHUTTLE_CAPACITY_CONTINUATION_REPORT.md). None becomes training-ready
through this inspection. No dataset files, annotations, media or weights were
acquired; no external code execution, inference, image assessment or training
ran. Existing eligibility flags and application models are unchanged.
Complete scientific rally references remain **0/2**; full annotation accuracy
is unproven.

The [evidence inventory](supervision-source-discovery.json) records exact observed
response hashes, sizes, URLs, failures and separate qualification dimensions.
Author-reported counts remain separate from observed file metadata. These five
leads differ from the existing [TrackNet corpus](SHUTTLE_SUPERVISION_REPORT.md)
and [eligibility audit](SHUTTLE_ELIGIBILITY_REPORT.md); they do not resolve those
corpora's unknowns.

## Source decisions

| Candidate | What the primary evidence establishes | Next prerequisite |
| --- | --- | --- |
| ETH One-Shot shuttle, 2026 | Actual project Dataset link and a public folder listing; semi-automatic labels are author-reported. | Establish applicable dataset/media terms and original sequence grouping, then freeze acquisition inventory. |
| Ko/Hew self-recorded shuttle, 2022 | Four listed singles videos; linked labels are not established. | Establish annotations, recording terms and whether camera views share physical events. |
| Cartron Shuttlecock v1 | Web-readable dataset page reports detection labels and preprocessing; direct request returns 403. | Verify permitted export access, terms, original sources and grouping before acquisition. |
| NIE service-detection related data | Released file inventory contains a judgement table. | This release does not supply the advertised detector-training corpus; a separate release would be needed. |
| Beihang Fine-Badminton, 2026 | Open archive metadata and temporal action-label claims, with conflicting usage statements. | Resolve terms and source overlap before a separately granted acquisition. |

### ETH: a genuine dataset link outside the README

The [pinned repository](https://github.com/leggedrobotics/shuttle_detection/tree/745a82916e919313e6db319a12ea873082192666)
has a placeholder download target. Its [project page](https://sites.google.com/leggedrobotics.com/shuttlecockfinder/startseite)
instead links the [processed dataset folder](https://drive.google.com/drive/folders/1neBfC7-Fp-l53muxZiIbIET6lYH5xv9s?usp=sharing).
The bounded root listing shows 33 background/difficulty folders, two COCO
folders and an `old` folder. It is not a recursive or complete census.
Difficulty partitions do not establish independent sources. The authors report
20,510 frames across 11 backgrounds. Repository AGPL software licensing does
not establish the linked data/media terms; those remain unresolved in the
inspected material. No linked files were downloaded.

### Ko/Hew: recording availability does not establish labels

The [pinned creator README](https://github.com/astrochialinko/Badminton-Shuttlecock-Tracking/blob/adcb6d922a969a2b22f05f936bc546504fabda10/README.md)
reports 2,098 self-recorded frames. The [linked root listing](https://drive.google.com/drive/folders/1mNntqLRaQkIhUmLZPC19Yc7HXesgBrpQ?usp=share_link)
exposes `MS_side.mp4`, `MS_top.mp4`, `WS_side.mp4` and `WS_top.mp4`.
That observation supplies neither coordinate annotations nor independent
physical-source groups. Repository MIT is recorded separately from unverified
recording/annotation terms. No video was acquired.

### Cartron: page claims and failed direct access stay separate

The [version-one primary page](https://universe.roboflow.com/mathieu-cartron/shuttlecock-cqzy3/dataset/1)
reports 8,053 images, partitioned 5,617/1,620/816, with auto-orientation,
640x640 stretching, no augmentation and CC BY 4.0. These are page-reported
assertions from the web reader, not an acquired export or raw-page hash
verification. The direct request returned HTTP 403; its error bytes and failed
attempt are preserved without retry or access bypass. Original media provenance,
native clocks and match separation remain unresolved. A secondary project's
claim of three matches is not adopted as verified source grouping.

### NIE: inspect the released files rather than infer them from the paper

The [creator release](https://researchdata.nie.edu.sg/dataset.xhtml?persistentId=doi:10.25340/R4/A2AE4H)
and its [public API metadata](https://researchdata.nie.edu.sg/api/datasets/:persistentId/?persistentId=doi:10.25340/R4/A2AE4H)
identify released version 1.0 under CC BY-NC 4.0. Its one advertised file is a
627-byte service-judgement table, with a 23,444-byte original spreadsheet.
No detector-training image corpus is advertised in this version's file list.
The table itself was not acquired and must not be treated as shuttle-coordinate
supervision. This finding concerns this release, not all possible creator data.

### Beihang: a distinct temporal-action release with unresolved terms

The [Zenodo release](https://zenodo.org/records/20292976) advertises ten videos,
980,703 frames and 9,817 actions across 29 categories. The archive metadata
specifies 6,455,837,331 bytes and MD5 `cb3fcaca0ae9b08c564ac2a19ae4e7a0`;
archive bytes were not acquired or verified. API licensing says CC BY 4.0 while
the description restricts distribution to noncommercial academic research and
retains original owners' media copyright. This conflict remains unresolved.

The [paper](https://arxiv.org/html/2605.23355v1) describes a larger 31-match
corpus and 25 fps resampling. Action intervals cannot certify exact contacts,
serves or rally endings. This is distinct from the already imported
[iLearn Finebadminton-20K](FINEBADMINTON_REPORT.md). Source overlap with that
corpus, ShuttleSet, BFMD, AI CUP and consumed holdouts must be audited before
selecting training or evaluation sources.

## Reproduction limits and next work

There were nine new bounded document/metadata responses, totaling 327,693 body
bytes, including the retained 403. Five earlier planning responses are referenced
separately. Their raw UTF-8 response bytes remain ignored locally; committed
hashes permit comparison when those bytes are available. Some earlier planning
captures omitted status, final URL or content type; those fields remain null
rather than being reconstructed. Dynamic pages may change; a successful fetch
and matching hash establish observed bytes, not data correctness or rights.
The error hash seals only the error response. Root listings remain incomplete
observations, and no hidden contents are inferred.

The first inspection command stopped at the 403. A separate explicit continuation
read only the two untouched metadata endpoints, retained the original failure
and validated existing response hashes; no successful or failed request was
repeated. Local rendering initially encountered an omitted planning status field;
the corrected inventory preserves it as null. These are evidence-handling events,
not scientific acquisitions or changes to eligibility.

The next data task should first resolve ETH's applicable data terms and source
inventory, or Beihang's contradictory terms and original-match correspondence.
It must freeze exact acquisition inputs and budgets through a fresh grant before
downloading data. Cartron also needs a permitted export route. Ko/Hew requires
available labels; the observed NIE release is unsuitable for coordinate learning.
No new external message, authentication, image-transfer allowance, model
promotion or deployment authorization follows from this report.

Local verification passes all 39 existing package regressions, repository checks,
Ruff lint/format and dependency checks. A separate audit matches all 14 cited
response hashes and sizes, the new-response byte ledger, advertised file metadata,
null fields, the retained 403 and unchanged historical plan text around the new
increment. Exact PR/main/public-delivery records belong on the owning issue.
These checks establish documentation integrity, not badminton annotation accuracy.
No source has been selected for training, and the complete product objective
remains open.
