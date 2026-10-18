# Published contact and stroke supervision

October 18, 2026, version 0.23.0. This increment imports source-paired contact,
family and stroke-side labels for later model development. The current visual
proposal misses remain; no new detector or stroke head is installed.

## Why this data

The current complete-source native results still miss three of the four old
singles development contacts in frames 2000–2100 and two doubles contacts in
602–650. The doubles scene remains unconfirmed and cannot supply an accuracy
score. At several missing contacts, observed flanks do not meet under the linear
transition model. At singles 2077, the estimated junction lies approximately
0.020419 seconds before the gap, just outside a half-frame bound of 0.020 seconds.
These source-selected examples do not justify relaxing a detector threshold.

The author release for [A New Perspective for Shuttlecock Hitting Event
Detection](https://zenodo.org/records/14677727) supplies RGB rally clips with
published `HitFrame`, `BallType` and `Backhand` fields. This addresses the lack of
direct contact labels in larger action-interval releases. The new importer keeps
these published labels separate from app truth and model predictions.

## Source and mapping

The release is Zenodo record **14677727**, version 1.0.0. Its API declares
CC-BY-4.0. The original archive is `assets.zip`, 14,462,954,226 bytes, published
MD5 `aec0d95e266bd92e1ca2f8685b0c96d3`. Only its `datasets/part1.zip` member is
needed. A bounded HTTP range fetch checks the server's exact byte range,
decompresses that member, and verifies its CRC. The server supplied no ETag;
none is claimed as an identity check. The importer pins
the resulting full member's size and SHA-256 and checks every media/CSV member's
CRC and content hash. It does not claim to verify the entire outer archive MD5.
The packaged `aicup2023_manifest.json` records the exact member pin.

The selected member is 1,854,519,663 bytes with SHA-256
`1f14bb969a2a23fef58de76b22bd418d5848dc4f9f8ae6a364d365c1b4c9a07b`
and CRC32 `e60e3321`. A separate reread verifies the complete member SHA before
the actual CLI import.

The [official competition schema](https://sites.google.com/view/coachai-challenge-2023/tasks/track1)
and [original Chinese specification](https://www.aicup.tw/copy-of-%E8%B3%87%E6%96%99%E9%9B%86%E4%B8%8B%E8%BC%89)
define the following mappings:

| Published code | Normalized event/family |
| --- | --- |
| 1 / 2 | Short / long serve; no shot family |
| 3 | Clear |
| 4 | Drive |
| 5 | Smash |
| 6 | Net |
| 7 | Drop |
| 8 | Lift |
| 9 | Combined push/kill → other |

`Backhand=1` means backhand and `Backhand=2` means forehand; missing or other
values remain unknown. This differs from the 0/1 encoding in other corpora.
Round-head and court end cannot replace that field. Hitter A/B identifies the
far/near court end, not a persistent named player. A final winner flag is neither
the rally-ending timestamp nor an additional contact.

## Integrity and unresolved assumptions

The importer checks one archive handle throughout hashing and reading and rejects
a source changed during import. Duplicate names, unpaired labels/media,
mismatched clip IDs, unexpected paths, bad hashes/CRC, oversized CSVs and changed
output provenance fail before any normalized output is written. Archive paths
are indexed without extraction or execution.

Every published row and unlabelled media clip remains in the output. Malformed
frames, unknown family/side/hitter values, reversed timelines, stroke-order
errors, misplaced serves and premature winner markers remain explicit. Sequence
errors quarantine the clip's contact supervision rather than sorting or silently
dropping difficult rows.

Published HitFrame ordinals remain unchanged. The guide declares 30 FPS and
1280×720, but does not establish a universal zero/one-based ordinal convention.
An archive hash proves file identity, not contact timing. The source's numbered
rally clips also do not identify their original matches. The README describes
15 BWF and three self-recorded matches; clip partitions alone cannot establish
independent matches or absence of overlap with existing corpora. Normalized
splits therefore remain unassigned, media alignment unverified and training
readiness false pending those audits.

## Actual import and source inspection

The complete pinned archive imports **7,845** published contacts from all
**800** labelled training rallies and indexes all **169** unlabelled validation
clips. All media/label CRC and SHA checks pass. No byte-identical video occurs
across these clips; this does not rule out shared matches or overlapping footage.
The structural checks find no invalid source flags or sequences. That is a
format result, not proof that every published semantic label is correct.

| Family | Forehand | Backhand |
| --- | ---: | ---: |
| Clear | 639 | 74 |
| Lift | 695 | 696 |
| Net | 1,272 | 1,189 |
| Drop | 577 | 76 |
| Smash | 977 | 12 |
| Drive | 216 | 96 |
| Other | 257 | 269 |
| Serve | 159 | 641 |

The small backhand-smash class remains visible. It is not discarded or treated
as sufficient independent evaluation coverage.

A source-only protocol selected training clips 00001, 00004 and 00006 before
any new predictions, covering first/middle/final contact neighborhoods. All
1,151 frames decode with increasing PTS, 30 FPS and 1280×720. The raw-frame
sheets show two broadcast singles views and a self-recorded court with other
courts in view. Their contact neighborhoods are plausible, but rapid racket
motion and source sampling do not establish a universal exact ordinal base.
No contact, family or side label was rewritten from these pictures.

An exhaustive CPU audit then decodes **317,759 frames across all 969 clips**.
Every header count matches decoding; all clips are 1280×720 with increasing
source PTS and a 30 FPS clock. All published contacts fall within at least one
of the zero/one-based ordinal conventions. Nineteen clips have first contact
ordinal zero; targeted raw-frame inspection retains their unavailable pre-video
context and unresolved exact contact timing. These bounds are evidence about
published ordinals, not independent confirmation of each contact.

The full Python regression passes **687 tests**, with four unchanged optional
GPU checks skipped. New source-contract tests cover the mapping, unknowns,
sequence quarantine, raw preservation, unlabelled clips, duplicate media/names,
source pins/CRC, source mutation, output provenance and CLI success/errors.
No perception math or weights changed, so another GPU run is not required to
validate this import path.

The built wheel contains all 66 expected package files, byte-equal to the
worktree, including the source manifest. Its actual CLI imports the same full
archive and reproduces all three index outputs byte for byte. An independent
CSV/media reread checks every raw row, ordinal, side and court-end mapping and
every member hash. Both main sample exports remain unchanged. The
[machine-readable verification](aicup-contact-supervision-verification.json)
records the full audit, package and class counts. Raw videos and indexes remain
gitignored; no research predictions enter app annotations.

## Model audit and next work

The [author's source repository](https://github.com/wish44165/A-New-Perspective-for-Shuttlecock-Hitting-Event-Detection/tree/6c00ce3667c3f0bace1e90392b3a474a1312683f)
is pinned at `6c00ce3667c3f0bace1e90392b3a474a1312683f`. Its SwingNet notebook
expects background-removed optical-flow videos and imports `model_custom.py`.
That module is absent from the pinned tree, and the released conversion function
is a stub. Feeding RGB or guessed preprocessing to those weights would not be a
faithful reproduction, so no such checkpoint was downloaded or promoted.

The [official TrackNetV4 results](https://github.com/TrackNetV4/TrackNetV4/blob/cb7eea7988474771ceac7e880bbffc35bfa87bca/docs/RESULT.md)
were also checked: their download links point to placeholders. No supported
replacement shuttle checkpoint was established in this audit.

Next, review decoded source clocks/contact ordinals and original-match groups,
deduplicate against existing corpora, then freeze a direct-video learning
protocol with match-disjoint development and evaluation. The six families,
stroke side, contact/hitter and complete-rally outputs still require end-to-end
validation, including doubles and unseen full matches.
