# Independent source-only shuttle assessments

Task [#172](https://github.com/Ken0u/badminton-match-analyzer/issues/172),
October 21, 2026. Both predecessor source streams are complete and sealed;
the remaining blind adjudication and exclusive freeze are in progress.
These are development agent observations, not expert-certified labels or measured
shuttle localization accuracy. Full automatic match annotation remains unproven.

Predecessor [#164](https://github.com/Ken0u/badminton-match-analyzer/issues/164)
completed both 128-case streams in 64 genuinely distinct source sessions. Their
indexes and originals were sealed before comparison: 74 cases had raw field
differences and six additional cases were agreed negatives. All 80 require
source adjudication, in 20 fresh four-center sessions under the unchanged v2
protocol. An offline interruption exceeded #164's four-hour calendar window and
lease before any adjudication started. Original-host checks verified all 63 CLI
attempts (60 successful and three failed without originals), coordinator exits
and no Store worker. An exclusive preservation snapshot has receipt SHA256
`342aedebf1b1c7c48092c426cff5f5b8a4f4a079be87587a23d8249e8e2534f5`.
The controller released the incomplete task; its branch, draft PR #165, tests
and CI remain preserved. No completed delivery is claimed for #164.

The separately granted #172 phase carries those sealed streams unchanged. Its
four-hour remaining-phase limit begins at its own grant; it does not reset or
claim compliance with #164's expired limit. One cumulative 256 MiB output
ledger includes predecessor failures, tests, the interruption snapshot and all
new adjudication, freeze and review output. Original media remain in place.

The previous [#163 attempt](https://github.com/Ken0u/badminton-match-analyzer/issues/163)
is incomplete and was controller-released, then closed as superseded. Both
single-session assessments terminated on upstream image-context payload limits;
their preserved partial streams contain 96 and 68 recorded cases. Neither is a
complete sealed assessment. No comparison or adjudication began. The tested
validator was preserved at `8e28052`, with 77 generated tests passing. An ignored
exclusive snapshot preserves both partial streams and helpers byte-for-byte, with
receipt SHA256 `2b50fd6ff0881be2245a913469128a96778b214f77fc799cefae780aa5dbef6d`.
The two transport failures reported 24,553,068 and 93,567,391 request bytes against
a 15,728,640-byte upstream limit. The successor received a fresh grant and
published its prospective v2 protocol before reinspection. Every case is assessed
again in both new streams; partial #163 labels are not transplanted. Original
branches, protocol, incomplete labels and failure snapshots remain preserved.

## Frozen inputs and method

The original [v1 protocol](../data/manifests/shuttle_source_assessment_protocol_v1.json)
was committed at `139701d9afd60351eb5efab530ccaa50e98a3ba7` and published before
either assessor visually inspected a selected image. Its SHA256 is
`f7a985e162e7d48f2c8cff8ee9f8d9c718a4acfa07239c6dfbb84c0f5466b95b`.
The deterministic blind-input receipt SHA256 is
`c86dbd69b2e3c02ee355cb32c538cc37bcb8a270848f9e630aea55e0ebcc351c`.

The prospective [v2 protocol](../data/manifests/shuttle_source_assessment_protocol_v2.json)
was committed at `e86ddd18d03607730fd87c2eddf66839a4eb0eb5` and published before
new inspection. Its SHA256 is
`79653290b0dd8c1d09c244fce14019447cc6c1bf5402e27aa08bd498133a3a42`;
the new blind-input receipt SHA256 is
`603b62afeea3f1fc2ab3f88d0337b65fb69eba72d02cb0ebb029261464f2000c`.
V1 remains byte-identical. V2 changes prospective session/provenance handling;
it retains the original case selection, source seals and annotation conventions.

The unchanged native packets prepared in
[#160](https://github.com/Ken0u/badminton-match-analyzer/issues/160) contain:

| Public source identity | Category assertion | Native frames | Selected centers |
| --- | --- | ---: | ---: |
| `go2uajSiBnE` | Singles | 129,600 | 64 |
| `H1setLK1tig` | Doubles | 118,500 | 64 |

Centers remain `floor(j * (N - 1) / 63)`, for `j = 0..63`. Each center has
requested offsets -2 through +2, retaining clamped edge memberships. There are
128 cases, 640 requested memberships and 632 unique original oriented
1920-by-1080 PNGs. Deduplicating stored images does not shrink case denominators.
Source category metadata does not independently certify match identity.

Before assessment, credential-free identity checks reverified both raw source
hashes, 248,100 native clock identities, 56 frozen consumer hashes, every PNG's
hash/bytes/header geometry and the original unknown templates. No new media
acquisition, native decoding, inference or training is part of this task.

Two independent assessment streams each cover every available center at original
resolution. Each is planned as 32 genuinely fresh sessions of four centers, with a
6 MiB cap on unique inspected PNG bytes per session. Sessions receive only the
committed protocol, blind source identities and assigned cases;
they cannot access other labels, prior assessments, research code,
predictions, heatmaps or application truth. Each immutable original segment
records its actual session, inspected frame/hash identities, observations,
uncertainty and unknowns. The complete index binds its exact segment inventory,
byte hashes and case/session membership. Canonical tool-assigned session locators
identify genuine spawned sessions; inherited environment IDs cannot impersonate
new sessions. These private documents remain ignored. No single-session
whole-sample inspection is claimed.

The four visibility states are `visible_localizable`, `visible_unlocalizable`,
`not_visible` and `unknown`. Localizable points use oriented native pixel centers
with an explicit uncertainty radius. Other states carry no coordinates.
`not_visible` requires affirmative source evidence; failure to locate a tiny
object remains unknown. Neighboring context cannot supply a hidden center's point.

After both complete indexes and all original segments are sealed, distinct
bounded source-only adjudication sessions coordinated by the owner must
inspect every raw label disagreement and every agreed negative. Disagreements
include visibility, coordinates, uncertainty, scene and difficulty tag sets.
The freeze preserves all original index/segment bytes, raw differences and explicit
source decisions. It never averages coordinates. Matching cases without a third
inspection retain only two-assessor agreement.

## Reproduction and limits

The validator and launcher verify the original packet/media seals, fixed case
membership, exact segment inventories and global session separation, assessment
provenance, coordinate/unknown conventions and required
adjudication. The launcher offers `verify`, `freeze` and `verify-freeze`; run
`python scripts/freeze_shuttle_source_assessments.py --help` for arguments.
An existing original packet root and ignored assessment documents are required;
a fresh clone does not include them.

A freeze uses a new exclusive ignored output directory. It copies original
stream indexes and segments, small packet metadata and its consumer source,
with hashes for every file. Original videos, PNGs and full clocks remain in the preserved packet
lineage and are reverified there. Copying the PNGs alone would exceed this task's
256 MiB new-output limit. Failed partial output is preserved and cannot be reused
as an exclusive destination.

All four usage flags remain false: `training_allowed`, `independent_test_allowed`,
`model_deployment_allowed` and `dataset_redistribution_allowed`. Public availability
does not establish media rights. Original-match overlap, upstream checkpoint
membership, independence, semantic full-match completeness and balanced difficult
case support remain unresolved. A case-level scene observation does not certify
whole-match live/replay segmentation.

Image hashes and software validation establish identity and consistency; they
cannot prove actual visual inspection or assessor independence. Agreement and
adjudicated support are not accuracy against independent human truth. Parent
[#65](https://github.com/Ken0u/badminton-match-analyzer/issues/65) remains open.
A model experiment requires a separate frozen task; this assessment authorizes no
training, test reuse, eligibility change or application/model promotion.
