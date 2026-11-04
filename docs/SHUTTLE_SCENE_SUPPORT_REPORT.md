# Preserved scene-support census

Task [#376](https://github.com/Ken0u/badminton-match-analyzer/issues/376)
implements a metadata-only census of the incomplete
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
source, view, sheet, batch and execution provenance. Public artifacts contain
aggregate counts and hashes only.

## Verification and execution status

Generated regression tests exercise full-view versus center-only coverage,
unknown/excluded scenes, edits, half-open case membership, overlapping views,
failed/missing sessions, global identities, historical seals, source/consumer
mutation, private-field suppression and exclusive/bounded CLI output. The
initial test run exposed Windows newline translation in a generated fixture;
the fixture now writes exact LF bytes and the failed receipt remains preserved.

The original scientific census has not run at this preparation checkpoint.
Required full software checks, prospective publication, the actual one-shot
census and exact PR/controller/main/public-delivery verification remain pending.
Owning-issue checkpoints carry exact revisions, measured checks and receipts.

Reproduce with the matching ignored original artifacts and private bindings:

```sh
python scripts/audit_shuttle_scene_support.py --root ORIGINAL_NAMESPACE --protocol data/manifests/shuttle_scene_support_protocol_v1.json --bindings PRIVATE_BINDINGS.json --output NEW_PRIVATE_DIRECTORY
```

A clone does not contain those original artifacts. Source/input changes are
rejected; partial output without a completion receipt is not a completed census.
The fixed task clock, output budget and old scientific deadlines remain separate.

## Remaining scientific work

Measured gaps will determine the next separately scoped source-review or
diagnostic proposal. This census creates no application scene ranges and grants
no old selector eligibility. All four research eligibility flags remain false;
complete independent rally references remain **0/2**. No model is promoted and
full automatic badminton annotation accuracy remains unproven.
