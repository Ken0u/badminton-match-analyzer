# Follow-up supervision audit

Snapshot: October 18, 2026. This source audit ran while the fixed AI CUP RGB
experiment was extracting features. **None of these sources entered that
experiment**, its normalization, validation selection or test fold. The original
S2 holdout protocol remains frozen; its previously blocked public source has
now been acquired without authentication. No new data or derived model is installed in the
app, and source annotations are kept outside Git.

## Full-broadcast timelines: BFMD

The [official repository](https://github.com/Ning-D/BFMD/tree/c7c7e8e4c815085dda42746f16e07f1172503312)
and [dataset page](https://ning-d.github.io/BFMD-Dataset/) link an anonymous public
annotation folder. The repository distinguishes manual timelines from inferred
hit sequences and model-generated court/shuttle tracks. Its dataset page limits
use to non-commercial academic research and prohibits redistribution. Those
restrictions must remain visible when considering deployment assets.

The local audit acquired 35 reference files (14,709,189 bytes): metadata, indexes,
manual timeline/hit exports and documentation. It did not acquire videos,
inferred-hit files, generated tracks, captions, weights or executable helpers.
The exact content hashes and file IDs are retained in the local receipts.

| Actual snapshot | Singles | Doubles |
| --- | ---: | ---: |
| Match exports |12|7|
| Generic hit markers |11,301|5,450|
| Rally interval markers |1,054|634|
| Hit markers outside every source rally interval |0|211|
| Results whose `origin` is not manual |0|5|

The 19 exports contain 16,751 generic hit markers and 1,688 rally markers. These are
counts of published source records, not independently verified true contacts or
rallies. Specific integration hazards are:

- One singles file has 451 frames carrying conflicting point-family labels,
  including clear/lift and net-shot/net-kill pairs. Do not choose one silently.
- Four intervals appear in singles metadata but not in the manual timeline
  exports. The metadata directory also includes a backup file; the index has a
  `TOTAL` row; one match metadata object has a singleton-list wrapper.
- Doubles exports include a partial `choices` layer in one match, beyond the
  generic-hit schema described in the README. It contains 943 entries, some empty,
  and uses action intervals as well as point ranges. It does not provide complete
  structured forehand/backhand and individual-hitter labels across the corpus.
- Five results marked `prediction` occur inside an `annotations` container.
  Container membership alone must never promote a result to manual truth.
- Source documentation declares 30 fps, but the original source videos and decoded
  clocks have not been verified locally. A matching YouTube duration alone does
  not establish frame correspondence or the ordinal convention.

BFMD is a useful candidate for learning/evaluating live/replay intervals and
contact/bounce/net events. It does not yet establish independent full-match
accuracy, correct line calls, persistent identities or all family/side targets.

## Broader doubles strokes: DShuttleNet

The [paper](https://arxiv.org/abs/2610.14016) links the
[version 7 dataset](https://www.kaggle.com/datasets/anonymousay58dki/dshuttlenet/versions/7).
Anonymous public metadata resolved dataset 10314057. The 10,263,241-byte archive
was acquired without authentication; all seven expected CSV sizes and CRCs were
checked. Its SHA-256 is
`e3896a016f8cf22116d3c7d4412fe986350747549aa3bed74ca3c7dc213524b4`.
Kaggle declares **CC BY-NC-SA 4.0** for the dataset; the paper's separate CC BY
license must not be substituted for the dataset terms.

The release contains 58 matches and 134 sets. Raw tables have 4,846 rallies and
58,359 shots; the processed table has 4,483 rallies and 54,141 shots. Raw hitter
IDs, four-player coordinates and a 0/1 backhand field offer stronger future doubles
supervision. The actual video clock, field semantics and full-match overlap still
need verification before using them as source-aligned targets.

The processed table **omits all frame/time columns**. Each of its 54,141 unique
shot IDs joins an original raw shot, where `time`, `start_frame_num` and
`end_frame_num` are retained. Those are published source intervals, not certified
exact contacts or terminal times. They must not be replaced with row numbers or
nominal-FPS guesses.

The audit also finds 21 missing shot types, 25 retained nonzero flaw flags, one
reversed source interval and three intervals that fail source-rally containment
(overlapping issue counts). The 4,218 omitted raw shots are entire omitted
rallies; exclusion is not explained by a simple per-row flaw filter. Retain the
published versions and explicit exclusions rather than relabeling them.

Three matches are the same 2022 Indonesia Masters matches already used in the S2
experiments: Alfian/Ardianto versus Liang/Wang; Liang/Wang versus
Sukamuljo/Gideon; and Zheng/Huang versus Gicquel/Delrue. Their DShuttleNet IDs are
5/6/7. They must be quarantined from a new independent evaluation. This leaves
55 candidate matches, **not 55 proven independent sources**: compare the remaining
full matches with the other corpora and supplied sample videos first.

## Other sources checked

The official [F3Set repository](https://github.com/F3Set/F3Set/tree/04c6013d0aab13a3f92be58aed958becbcac392d/data/f3set-badminton)
provides 112 clip records and 1,692 events with frame indices and fine-grained
labels. Five exact parent-video names occur in both its published training and
validation folds. Alternate edits/compilations may overlap further. Its badminton
README asks users to contact the authors for videos; no contact was sent and no
replacement video version was guessed. This is currently a label/schema
candidate, not a ready independent video benchmark.

The already imported Finebadminton-20K release contains 77 backhand-smash action
records. Most have no published exact contact frame. Their action intervals
cannot be relabeled as exact contacts to fill the current test gap.

The separate [2026 Fine-Badminton release](https://zenodo.org/records/20292976)
was checked at metadata level only. Its description restricts use to non-commercial
research while the API license field says CC BY 4.0. That inconsistency is
unresolved. Its 6.46 GB archive was not downloaded, and its terms must not be
inherited from the differently named 2025 FineBadminton dataset.

## Recovery of the original frozen source

After normal anonymous metadata extraction succeeded for both new BWF source
listings, one standard recheck of the unchanged original ShuttleSet source also
succeeded. The original URL, format 398, 25 fps, 75-rally scope and label/model
protocol were preserved. No cookies, credentials, alternate clients or cached
signed URLs were used.

The original 63-minute BWF source was downloaded once: 309,811,368 bytes, SHA-256
`76c75c4bcecff975926c91fb94ad1e3e4b49df96f376db5b06c46f76c8ac11c5`.
This is acquisition evidence, not source-contact adjudication or model accuracy.
The source protocol SHA remains
`99b13bb12f0cacfee316547ee656ac69a0b6f273de20e75c80eb49e19892c6ed`.
All 75 original rally requests are prepared and decoded: **21,610 native rally
frames and 860 source rows**, with every clip hash and selected source/local PTS
checked. The three prior anchor clips retain their original bytes and provenance;
no new parent-byte identity is retroactively claimed for them. Three predeclared
source sheets (27 samples) were viewed; exact timing and semantics remain
unadjudicated. CPU preflight of all 75 clips also verifies 26 camera cuts. Both
cut sheets were reviewed: close-ups, replay angles and transition wipes precede
wide court views, with lingering post-cut overlays in request ordinals 4/31/46.
A detected cut alone cannot establish immediate clean live play. Main annotations
and the three existing anchor annotations are unchanged. Full native perception
and head predictions remain pending. This resumes the original evaluation scope
rather than substituting one of the newly found datasets.

## Reproducibility and next use

Local evidence is under `.cache/new-corpora-source-audit-v1`: pinned repository
trees and Git-blob-verified F3Set files, BFMD content receipts and
`bfmd-snapshot-audit.json`, and the DShuttleNet archive receipt,
`dshuttlenet-v7-source-audit.json` and `dshuttlenet-v7-filter-review.json`.

The [frozen RGB experiment](VISUAL_EVENT_LEARNING_REPORT.md) is now complete and
rejected for app promotion. A follow-up importer should preserve raw
fields, separate manual/inferred/model output, retain missing/ambiguous labels,
quarantine structural conflicts and canonicalize complete source matches before
splitting. Native source media/clock checks and independent human review remain
necessary. Use appropriate rights for any deployment assets. New sources expand
available evidence; they do not replace the original complete annotation goal or
erase the pending original 75-rally model evaluation.
