# Preserved scene-support census

Task [#378](https://github.com/Ken0u/badminton-match-analyzer/issues/378)
continues the preserved metadata-only census draft from
[#376](https://github.com/Ken0u/badminton-match-analyzer/issues/376), applied to the incomplete
[#359 assessment](SHUTTLE_SCENE_FRESH_ASSESSMENT_REPORT.md), following the
[source-context audit](SHUTTLE_CONTEXT_AUDIT_REPORT.md) and
[quota-dispatch repair](SHUTTLE_SCENE_QUOTA_FAILURE_REPORT.md).

The census separates complete known-scene agreement, complete live stable-camera
support and mixed or excluded views. Agreement at a center frame cannot certify
the rest of its view. Declared partitions retain their historical source
membership; they are not independently reviewed edits. All overlapping native
occurrences, unknowns, conflicts and unavailable readings remain explicit.

## Prospective protocol and input boundary

The [public protocol](../data/manifests/shuttle_scene_support_protocol_v1.json)
commits exact new consumer hashes and the opaque original-evidence inventory
before scientific scene fields are read. Historical lane/session/comparison
seals, terminal metadata, source clocks and global execution identities are
verified. A failed session cannot contribute accepted labels, and absent
adjudication terminals remain absent. Only the original comparison engine is
used to reproduce the unchanged original result.

The original denominator remains 13,499 native occurrences, 50 views, 60 cases
and 870 sheets. Historical original comparison: 1,052 agreement, 2,133 conflict,
2,915 unknown and 7,399 unavailable occurrences. These are development evidence
from agent assessments, not expert truth or an accuracy measurement.

No image/media/model/prediction bytes are read, no assessor is launched and no
Store or annotation is changed. Hypothetical costs use original sheet sizes and
original batch membership, including their context and overlap; they authorize
no new dispatch, replacement or runtime. The private ledger retains frame,
source, view, sheet, batch and execution provenance. Each occurrence explicitly
lists all original overlapping batches, failed or unattempted original
assessments, and failed or unattempted adjudication. Public artifacts contain
aggregate counts and hashes only.

## Verification and execution status

Generated regression tests exercise full-view versus center-only coverage,
unknown/excluded scenes, edits, half-open case membership, overlapping views,
failed/missing sessions, global identities, historical seals, source/consumer
mutation, private-field suppression and exclusive/bounded CLI output. The
initial test run exposed Windows newline translation in a generated fixture;
the fixture now writes exact LF bytes and the failed receipt remains preserved.

The one-shot metadata census completed on November 4, 2026 (UTC), after the
[prospective issue commitment](https://github.com/Ken0u/badminton-match-analyzer/issues/378#issuecomment-6622951188)
published source `324787e8b80b5c27ec96f020ae398432259be710` and protocol SHA256
`b172a6d3d6e07d971848dfcd3f204fa20f8502ba760c7e0a0d9ae264704aef39`.
The fixed deadline is November 4 at 08:36:27 UTC; execution completed at
04:58:19 UTC. The inherited engine/task identity and expired predecessor clock
remain explicit in the protocol's continuation object.

The fresh isolated Python 3.10 review environment passes 5,789 tests with
35 skips; the focused scene/support suite passes 266 tests. Ruff, formatting,
dependencies, repository/LF/JSON/link and whitespace checks pass. Frontend
types, 251 unit tests, build, staged assets, contracts and delivery checks pass.
Clean wheel/source verification matches 109 package files, five frontend files
and 57 public manifests, including the corrected protocol inclusion; installed
HTTP checks pass. These are software checks, not scientific accuracy evidence.
A separate structural output check verifies consistent occurrence-to-batch/attempt
links, all native/unique denominators and private-field suppression. All 1,943
original metadata/source files remain unchanged; the frozen consumer separately
reproduces the original comparison exactly. Aggregate SHA256 is
`9da4270b4b55ed6703e001d3e730f5f5fdceb9ebd867065336bbfda527f1df0d`.
The completion receipt and private ledger remain local. Exact
PR/controller/main/public-delivery verification remains pending; owning-issue
checkpoints carry those revisions and receipts.

The original #376 four-hour window expired before complete checks or the census.
Its final generated-test receipt falls after that deadline and is preserved as
an overrun. Archival PR #377 is closed without merge; its source and failures
remain intact. #378 has a fresh committed grant and fixed four-hour deadline,
with no reuse of the old scientific runtime. The archived CI exposed a missing
source-distribution inclusion for the public protocol; the continuation adds
that explicit MANIFEST.in entry without weakening package verification.

Reproduce with the matching ignored original artifacts and private bindings:

```sh
python scripts/audit_shuttle_scene_support.py --root ORIGINAL_NAMESPACE --protocol data/manifests/shuttle_scene_support_protocol_v1.json --bindings PRIVATE_BINDINGS.json --output NEW_PRIVATE_DIRECTORY
```

A clone does not contain those original artifacts. Source/input changes are
rejected; partial output without a completion receipt is not a completed census.
The fixed task clock, output budget and old scientific deadlines remain separate.

## Measured support and review gaps

The census preserves **13,499 native occurrences / 13,299 unique source frames**,
50 views, 50 declared partitions, 60 cases and 870 sheets. The 200 repeated
occurrences remain in their original views; they are not extra independent
source frames. The original 1,052 agreements, 2,133 conflicts, 2,915 unknowns and
7,399 unavailable occurrences reproduce exactly.

| Agreed scene/transition or unresolved category | Native occurrences |
| --- | ---: |
| Live, with expected within-view transition | 927 |
| Non-play | 125 |
| Replay | 0 |
| Live with an agreed edit | 0 |
| Conflict | 2,133 |
| Unknown | 2,915 |
| Unavailable | 7,399 |

Zero agreed replay/edit labels do not establish their absence from the videos.
The 1,052 supported unique frames have agreement across all their retained
occurrences; 12,247 unique frames have no supported occurrence. There are no
mixed supported/unresolved unique frames in this result.

| Coverage question | Supported / retained |
| --- | ---: |
| Complete known-scene views | 1 / 50 |
| Complete live, stable-camera views | **0 / 50** |
| Complete known mixed/excluded views | 1 / 50 |
| Views with incomplete scene evidence | 49 / 50 |
| Cases with known center agreement | 2 / 60 |
| Cases whose whole view has known scene agreement | 1 / 60 |
| Cases whose whole view has live, stable-camera support | **0 / 60** |
| Declared partitions with every cell live/same-camera agreed | 0 / 50 |

The sole complete known-scene view is entirely non-play. Of the two agreed
centers, one is live and one non-play; the other centers retain six conflicts,
22 unknowns and 30 unavailable readings. A live center supplies no whole-view
support.

| Hashed original-source group | Views / cases | Occurrences / unique frames | Complete known views | Complete live views |
| --- | ---: | ---: | ---: | ---: |
| `40d527e5cb14ecf1` | 25 / 35 | 7,248 / 7,248 | 1 | 0 |
| `f76dc2685371f1a5` | 25 / 25 | 6,251 / 6,051 | 0 | 0 |

The second group is entirely unavailable. The first retains all 927 live and
125 non-play agreements, 2,133 conflicts, 2,915 unknowns and 1,148 unavailable
occurrences. No majority vote or frame interpolation supplies missing labels.

Historical execution retains 183 distinct sessions and 183
distinct threads. Original A has 34 successful / 41 failed sessions; original B
has 33 / 42. Adjudication has zero successful / 33 failed sessions and 42
unattempted schedule slots. All attempted sessions have resolved terminal
metadata, but the adjudication terminal seal remains absent. Process completion
does not convert failed sessions into scientific readings.

Review gaps cover **12,447 occurrences / 12,247 unique frames**, 806 sheets and
74 original batches. Hypothetically repeating those original batches requires
324,275,244 image bytes / 74 sessions for one pass, or 648,550,488 bytes / 148
sessions for two fresh passes, before adjudication. Original batch context and
overlap account for 862 unique sheets / 314,279,226 unique image bytes. These
are metadata costs, not an authorized schedule or a recommendation to repeat
the failed assessment unchanged.

Overlapping diagnostic flags retain 7,399 occurrences with a missing original
lane, 28 with a same-lane overlap conflict, zero cross-view conflicts, 12,445
with either lane's scene unknown and 7,412 with an unknown transition. Two have
the same known scene in both lanes but unresolved transition evidence. These
flags overlap and must not be summed into another denominator.

## Remaining scientific work

The preserved assessment cannot support any complete live view for the archived
selector comparison. The next source-review proposal must address the measured
missing/failed coverage and scene/transition conflicts with a viable bounded
collection/adjudication method. Repeating the old assessment unchanged is not
established as a solution. Partial live-frame agreement cannot replace those
requirements. This census creates no application scene ranges and grants no
old selector eligibility. All four research eligibility flags remain false;
complete independent rally references remain **0/2**. No model is promoted and
full automatic badminton annotation accuracy remains unproven.
