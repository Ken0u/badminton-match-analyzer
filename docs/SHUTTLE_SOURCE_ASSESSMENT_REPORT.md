# Independent source-only shuttle assessments

Task [#163](https://github.com/Ken0u/badminton-match-analyzer/issues/163),
October 21, 2026. This attempt is incomplete: both assessor sessions terminated
on upstream image-context payload limits. The preserved partial streams contain
96 and 68 recorded cases, respectively; neither is a complete sealed assessment.
No label comparison or adjudication began. No final aggregate support exists.
These are development agent observations, not expert-certified labels or measured
shuttle localization accuracy. Full automatic match annotation remains unproven.

The tested validator is preserved at `8e28052`; 77 generated tests pass. An ignored
exclusive snapshot preserves both partial streams and helpers byte-for-byte, with
receipt SHA256 `2b50fd6ff0881be2245a913469128a96778b214f77fc799cefae780aa5dbef6d`.
The two transport failures reported 24,553,068 and 93,567,391 request bytes against
a 15,728,640-byte upstream limit. A prospective successor needs a fresh grant and
protocol for bounded session segments with per-case provenance; this attempt's
frozen single-session requirement has not been silently relaxed.

## Frozen inputs and method

The [assessment protocol](../data/manifests/shuttle_source_assessment_protocol_v1.json)
was committed at `139701d9afd60351eb5efab530ccaa50e98a3ba7` and published before
either assessor visually inspected a selected image. Its SHA256 is
`f7a985e162e7d48f2c8cff8ee9f8d9c718a4acfa07239c6dfbb84c0f5466b95b`.
The deterministic blind-input receipt SHA256 is
`c86dbd69b2e3c02ee355cb32c538cc37bcb8a270848f9e630aea55e0ebcc351c`.

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

Two fresh assessor sessions separately inspect every available center at original
resolution. They receive only the committed protocol and source packet identities;
they cannot access each other's labels, prior assessments, research code,
predictions, heatmaps or application truth. Each original records its actual
session, inspected frame/hash identities, observations, uncertainty and unknowns.
These private per-case documents remain ignored.

The four visibility states are `visible_localizable`, `visible_unlocalizable`,
`not_visible` and `unknown`. Localizable points use oriented native pixel centers
with an explicit uncertainty radius. Other states carry no coordinates.
`not_visible` requires affirmative source evidence; failure to locate a tiny
object remains unknown. Neighboring context cannot supply a hidden center's point.

After both originals are complete and sealed, a distinct owning adjudicator must
inspect every raw label disagreement and every agreed negative. Disagreements
include visibility, coordinates, uncertainty, scene and difficulty tag sets.
The freeze preserves both original byte sequences, raw differences and explicit
source decisions. It never averages coordinates. Matching cases without a third
inspection retain only two-assessor agreement.

## Reproduction and limits

The validator and launcher verify the original packet/media seals, fixed case
membership, assessment provenance, coordinate/unknown conventions and required
adjudication. The launcher offers `verify`, `freeze` and `verify-freeze`; run
`python scripts/freeze_shuttle_source_assessments.py --help` for arguments.
An existing original packet root and ignored assessment documents are required;
a fresh clone does not include them.

A freeze uses a new exclusive ignored output directory. It copies small original
JSON documents, packet metadata and its consumer source, with hashes for every
file. Original videos, PNGs and full clocks remain in the preserved packet
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
