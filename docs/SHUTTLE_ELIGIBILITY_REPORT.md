# Public shuttle supervision eligibility audit

Task [#218](https://github.com/Ken0u/badminton-match-analyzer/issues/218), under
[localization roadmap #65](https://github.com/Ken0u/badminton-match-analyzer/issues/65).
Public text was retrieved October 24, 2026, beginning 04:18:31 UTC. The
[machine-readable audit](../data/manifests/shuttle_eligibility_audit_v1.json)
retains all **29 coordinate-corpus publication groups and both broadcast slots**.
It organizes evidence and identifies a label-version prerequisite; it does not
make any source eligible or demonstrate improved automatic annotation.

Training-ready rows remain **0 before / 0 after**. All four flags remain false:
`training_allowed`, `independent_test_allowed`, `model_deployment_allowed` and
`dataset_redistribution_allowed`. No detector, threshold, model, application
truth, prediction, reviewed annotation or split changed. Half smash remains
excluded; this audit measures none of the six requested families or stroke sides.

## Frozen baseline and scope

The pre-lookup baseline was sealed on the
[owning issue](https://github.com/Ken0u/badminton-match-analyzer/issues/218#issuecomment-6379760205)
at granted source `3fb8d80a88e016f673a688795b01c97ca1403fe3`, epoch 1. Its private
metadata receipt SHA256 is
`08b28ce473e116fdc1d912b67dd92453658e1de8efdb3373fed3645c418f757a`.
The public manifest records byte hashes and lengths of all nine baseline source
files. Those files and their original eligibility restrictions are unchanged.

The [#143 preparation report](SHUTTLE_SUPERVISION_REPORT.md) supplies the prior
aggregate census: 201 clips, 91,214 published rows and 91,579 native frames across
29 publication groups. All 12,235 rows from 25 incomplete CSVs remain quarantined;
365 unlabelled tails remain explicit. Its 68,643 structurally eligible visible
coordinate references are not training-ready rows or expert truth. None of
these counts was recomputed from raw inputs in this audit.

The [#145 diagnostic](SHUTTLE_CORPUS_DIAGNOSTIC_REPORT.md),
[#160 source preparation](SHUTTLE_SOURCE_PACKET_REPORT.md),
[#172 source assessments](SHUTTLE_SOURCE_ASSESSMENT_REPORT.md),
[#179 broadcast diagnostic](SHUTTLE_BROADCAST_BASELINE_REPORT.md) and
[#204 threshold experiment](SHUTTLE_THRESHOLD_REPORT.md) remain bound evidence.
Their processing, agreement and development results do not establish rights,
original-match disjointness or full-match annotation correctness. In particular,
a new metadata audit does not repeat, supersede or promote a rejected experiment.

This laptop has no local raw research media, coordinate corpus or external
checkpoint weights. No such inputs were acquired. Original source hashes and
native frame counts below are attributed prior public receipts, not newly
verified bytes. The separate #212 MSI grant and its source assessments, files,
jobs and resources were preserved. No consumed holdout inputs, protocols,
predictions, private membership or artifacts were accessed.

## Public evidence revalidation

Only six already-cited public text/metadata endpoints were retrieved, anonymously,
with no cookie jar or credential use. Each response was limited to 4 MiB and
required UTF-8 text/JSON. Redirects were not followed; all six returned HTTP 200.
The 106,405 response bytes, exact retrieval timestamps, URLs, content types,
lengths and SHA256s are recorded in the manifest and private receipts. No linked
image, archive, media, annotation CSV or checkpoint was fetched or executed.

| Public document | Result against #143 pin | What it supports |
| --- | --- | --- |
| [Creator description](https://hackmd.io/@TUIK/rJkRW54cU/download) | Byte-identical, 13,122 bytes | Named assertions for 23 professional training and 3 test matches; amateur self-play description and intended training/testing use |
| [Pinned upstream README](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/README.md) | Byte-identical, 9,325 bytes | Professional/amateur training layout, test namespace and explicit code/checkpoint MIT statement |
| [Pinned upstream LICENSE](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/LICENSE) | Byte-identical, 1,097 bytes | MIT grant expressly covering software and pretrained checkpoints; no dataset/media grant established |
| [Pinned upstream loader](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/dataset.py) | Byte-identical, 41,285 bytes | Distinct test-label directory described below; directory loading does not prove checkpoint membership |
| [Mirror tag commit metadata](https://api.github.com/repos/AnInsomniacy/tracknet-series-pytorch/commits/dataset-v1.0.0) | Byte-identical, 36,360 bytes | Tag resolves to `6d91a1bd28a9cab4b09e7d0460b2bb0a1afe6764` |
| [Mirror release metadata](https://api.github.com/repos/AnInsomniacy/tracknet-series-pytorch/releases/tags/dataset-v1.0.0) | Changed, 5,216 versus 5,215 pinned bytes | Current advertised asset identity still matches; retain changed response separately |

Five responses match the earlier hashes. The changed release response has SHA256
`0c037829c8b80c4f5ad7b84e2d7eb11fecb79305f603f6cb04706fce6cb253ac`;
the earlier response was
`fb7c4ceecc7614b8f3fc0655f0f89521afb065c40e2b4c31df140f9b0ecf1858`.
The original raw API snapshot is unavailable locally, so the exact changed fields
are not determined. No cause for that byte difference is claimed.

Release ID 319868491, asset ID 415867370, advertised size 1,731,120,724 bytes and
advertised digest
`f87ccd54318e2e6366f2e820ba8dc1a04203c132582fc664867f0d1029bef465`
match the prior archive identity. The release reports `immutable: false`.
These are metadata checks, not a fresh archive hash or creator authentication.
Its body advertises extracted frame folders, whereas the prior actual archive
census reports none. Preserve that conflict; do not substitute release prose for
observed archive contents. The earlier creator-link sign-in result remains
historical evidence; no SharePoint/archive access was retried here.

## Identity, rights and upstream membership

The manifest joins every existing publication group to its exact prior counts.
For the 26 professional/test groups it records the creator's player/event/round
assertions and row locator. Their reported per-group frame counts agree with the
prior census. The older creator introduction's 78,200-frame aggregate remains
separate from actual counts; it is not silently repaired. Three amateur sessions
lack named match assertions. None of the 29 groups has a verified canonical
original-media URL or group media hash in these bounded public descriptors.
The archive hash cannot be substituted for a match's source hash.

The two broadcast slots retain canonical public IDs `go2uajSiBnE` and
`H1setLK1tig`, titles/categories as assertions, and the prior selected-stream
hashes and counts (129,600 and 118,500 frames). They are the same source slots,
not replacements or newly downloaded videos. Official-channel origin and stream
bytes do not independently certify complete original-match identity, media-use
rights, original-match overlap or expert label quality.

The upstream README maps professional groups to `train/match1` through
`train/match23`, amateur groups to `train/match24` through `train/match26`, and
published Test to `test/match1` through `test/match3`. It also describes generated
validation data. The manifest calls these **documented layout aliases**, not
verified training, validation or pretraining membership of any checkpoint.
All exact membership fields remain unknown, including the broadcast slots.
Published Test is not a new independent holdout for this project.

The README and LICENSE explicitly include pretrained checkpoints in their MIT
statement. That is separate from the creator's intended training/testing purpose
and from dataset/media rights. The six documents establish no explicit applicable
dataset/media grant for the proposed use, mirror authenticity or derivative
deployment approval. This is a bounded evidence finding, not a declaration that
no permission exists elsewhere.

No complete cross-corpus original-match comparison was performed. All 31 overlap
fields remain unknown. Names, different encodes, current titles/upload years and
the narrow prior exact-ID search cannot prove independence. Existing known
overlaps elsewhere in the project remain preserved; this audit does not certify
their absence from these sources or inspect private consumed-holdout membership.

## Additional label-version prerequisite

In the pinned loader, `_gen_input_from_rally_dir` reads `corrected_csv` when
`data_mode` is `heatmap` and the rally path contains `test`; other paths read
`csv`. The previously imported archive report describes published
`ball_trajectory` CSVs. No equality between those published labels and upstream
`corrected_csv` labels has been established here. All three test publication
groups retain `UPSTREAM_LABEL_REVISION_UNRESOLVED`.

This is a code-path/provenance observation, not evidence that any particular
coordinate differs. No annotation CSV, corrected labels, checkpoint or prediction
was opened or compared. The original diagnostic's agreement to its frozen
published references remains valid within its stated scope; it must not become
an equivalence claim to the upstream paper's evaluation labels or performance.

## Measured effect and remaining dependencies

| Evidence dimension | Audit result |
| --- | ---: |
| Inventory units with explicit reason codes and all four false gates | 31/31 |
| Units with named public match assertions | 28/31 (26 corpus, 2 broadcast) |
| Units with canonical public video IDs / prior selected-stream hashes | 2/31 / 2/31 |
| Independently verified original-match identities | 0/31 |
| Units with resolved dataset and media grants | 0/31 |
| Completed cross-corpus overlap audits / exact checkpoint memberships | 0/31 / 0/31 |
| Public text responses matching prior pins | 5/6; one changed response retained |
| Upstream test groups needing label-version reconciliation | 3/3 |
| Training-ready rows, before / after | 0 / 0 |
| Eligibility flag changes | 0 |

The bounded change is a source-bound, machine-readable inventory and an explicit
test-label-version dependency. Evidence organization improves; detector recall,
event accuracy, persistent identity and full-match correctness are unmeasured.
No unsupported case was removed to improve a denominator.

Before a training/evaluation proposal can be eligible, obtain applicable dataset
and media-use evidence plus creator/archive provenance; link publication groups
to actual complete original sources; reconcile original-match overlaps and exact
checkpoint/pretraining membership; and resolve label-revision correspondence
under a separately granted, prospective protocol. Any missing evidence stays
unknown. An owner may provide rights-holder evidence or authorize a separately
frozen alternative-source proposal; this task cannot infer that authorization or
contact anyone on the owner's behalf. No new data acquisition follows from this
report. #212 continues independently; #62/#66/#67/#71 require their actual
scientific prerequisites and are not unlocked by this audit.

## Verification and delivery

Manifest checks cover exact group/source/count membership, public response and
baseline hashes, creator-table joins, reason-code coverage, unchanged predecessor
files, false eligibility flags, strict JSON, local links and UTF-8/LF. Repository,
Ruff, dependency and diff checks are required before submission. No new tests
mirror these documentation records, and no native inference is repeated.

Final check results, exact PR/main revisions, controller integration and public
wheel/source/both-image delivery receipts belong on
[#218](https://github.com/Ken0u/badminton-match-analyzer/issues/218). This report's
audit findings do not imply that pending software delivery has completed.
