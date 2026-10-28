# Exhaustive source-scene gallery preparation

Issue [#340](https://github.com/Ken0u/badminton-match-analyzer/issues/340)
prepares evidence for future coarse scene review of the two supplied familiar
singles/doubles videos. The archived comparison rejected all 60 cases because
the original scene-review lists provide no verified live context; see the
[metadata diagnosis](SHUTTLE_CONTEXT_AUDIT_REPORT.md). This preparation does not
resolve that scientific rejection or establish annotation accuracy.

The [frozen protocol](../data/manifests/shuttle_scene_preparation_protocol_v1.json)
binds both original media hashes, the projected inventory and corrected context
diagnostics. Every original method shares the same 50 views and 60 cases.
Expected coverage is 13,499 native frame occurrences in 870 chronological
16-cell sheets. Views, duplicate occurrences, camera-context partitions, native
PTS/time bases and display orientation remain explicit. Each cell contains the
whole source image at reduced resolution with native-frame and clock captions;
partial sheets mark unused cells as empty. Partition boundaries are retained
metadata, not independently verified camera edits or semantic scene labels.

Only the projected source/frame inventory, context metadata and the two original
videos enter this task. Original scientific labels, predictions, weights and
application annotations remain separate. No model, external assessment CLI or
image-transfer client runs. All derived images, frame manifests and input paths
stay in ignored local storage. Training, independent-test, deployment and
redistribution eligibility remain false; complete rally references remain 0/2.

The producer has separate `freeze`, `prepare` and `audit` stages in
[the CLI](../scripts/prepare_shuttle_scene_review.py). Use the project Python
environment with the granted checkout's `backend` on `PYTHONPATH`:

```text
python scripts/prepare_shuttle_scene_review.py freeze --root ORIGINAL_ROOT --protocol PROTOCOL.json --bindings BINDINGS.json --grant GRANT.json --ownership OWNERSHIP.json --output ORIGINAL_ROOT/.cache/NEW_OUTPUT
python scripts/prepare_shuttle_scene_review.py prepare --root ORIGINAL_ROOT --protocol PROTOCOL.json --bindings BINDINGS.json --grant GRANT.json --ownership OWNERSHIP.json --output ORIGINAL_ROOT/.cache/NEW_OUTPUT --context-sha256 FROZEN_CONTEXT_SHA256
python scripts/prepare_shuttle_scene_review.py audit --root ORIGINAL_ROOT --protocol PROTOCOL.json --bindings BINDINGS.json --grant GRANT.json --ownership OWNERSHIP.json --output ORIGINAL_ROOT/.cache/NEW_OUTPUT --context-sha256 FROZEN_CONTEXT_SHA256
```

Bindings map the protocol's artifact names to relative paths below the original
root. Grant and ownership JSON must represent the current committed task claim;
the ownership observation must be recent. Preserve original failed attempts and
use an exclusive ignored output. Freeze tested producer/protocol/helper hashes
before source decode. Preparation and audit require the existing real shared
Store and normal admission, with root/data/weights pinned before configuration
imports. An isolated worktree Store cannot authorize this processing. An audit
requires the preparation process to be absent and its original Store job to be
completed. Both stages recheck original input/producer hashes and ownership
before success. These checks detect observable changes; they do not provide
filesystem snapshot isolation against every transient write.

The audit independently decodes the original native clocks and checks complete
view membership, partitions, image hashes/formats/dimensions and retained file
membership. It recomputes packing and aggregate costs. The prospective schedule
keeps views separate, uses at most 6 MiB and 20 images per session and counts one
preceding-sheet overlap against both limits. It costs two independent passes and
a separate one-pass adjudication reserve from actual JPEG bytes. Infeasible
packing keeps the full denominator and produces no partial substitute schedule.
No session is started by generating this plan. Future review requires a separate
frozen task specifying actual payload, destination and limits. Thumbnail detail
may be insufficient; unknown scenes and boundaries then need native-source
adjudication rather than inferred labels.

## Verification checkpoint

Generated tests cover VFR/nonzero clocks, four display rotations, aspect
preservation, every-frame coverage, source/camera partitions, partial sheets,
overlap byte accounting, infeasible packing, source/metadata mutation, strict
JSON and safe paths, exclusive output, shared admission, terminal process
evidence and ownership revocation. All 49 focused tests are included in the
full result: **5,465 passed / four optional skips**. Ruff, formatting, dependency,
repository/JSON/link/UTF-8-LF and diff checks pass. The tested producer was
committed and its hashes published before original source decode.

## Actual preparation and audit: October 28, 2026

Both original media hashes remain unchanged. Sequential decoding covers all
24,171 original source frames (12,023 singles and 12,148 doubles), retaining all
**50 views / 60 cases / 13,499 frame occurrences / 870 JPEG sheets**. The 421
unused cells are marked empty. No case or duplicate frame occurrence is dropped.
Each sheet is 1280x864 with 4x4 source-aspect-preserving 320x180 cells and captions.

| Audited item | Result |
| --- | ---: |
| Unique derived image bytes | 315,622,932 |
| Retained output bytes, including manifests and terminal receipts | 325,100,421 |
| Sessions per prospective pass | 75 |
| Image occurrences per pass, including overlaps | 895 |
| Repeated overlap images per pass | 25 |
| Image payload bytes per pass, including overlaps | 325,618,950 |
| Sessions for two independent original passes | 150 |
| Image payload bytes for those two passes | 651,237,900 |
| Separate one-pass adjudication reserve: sessions | 75 |
| Separate adjudication reserve: image payload bytes | 325,618,950 |
| New assessor sessions / image bytes transferred | 0 / 0 |

The actual-byte schedule is feasible under both frozen session caps. The reserve
is a prospective ceiling, not permission to start assessment. All original
contexts, results and expired scientific clocks remain preserved.

Preparation and audit each completed through real shared Store admission. The
separate audit verified preparation-process absence and original Store completion,
independently decoded every native source clock/orientation, checked all image
hashes/formats/dimensions and exact tile memberships, and recomputed the complete
packing/aggregate. Both stage process lifetimes are now absent with completed
Store records. This is software/provenance evidence; no one has reviewed the
scenes in this task, and neither coarse-scene accuracy nor continuous live play
has been established.

Public provenance: protocol SHA256 `77f9bd3f5c77dba491d5fef594e08499255b428ee976e7aed3f025d90743022d`;
gallery-manifest SHA256 `89ac499a8ee143d66f66c6d622ad191fad043263acfef27f593dc3870e333a37`;
prospective-plan SHA256 `87eb616cfb7fe9707c081c7bde9fffa04a15ce0d0cecf47256026ec4aea761d2`;
aggregate SHA256 `c73642b84576b1750e2944009769a6c3948e3e509aa1fd8bef014841e40deb5c`;
audit-verification SHA256 `c4aca2acc0f90c9a0344e934a5bfa0c4e1a17d33d7e3d47c9abbd5c3560b80e2`.
The hashed private artifacts and images are not included in the repository or
candidate packages. Reproduction requires the original permitted inputs and a
fresh grant; a clone supplies code and public protocol only.

Next: obtain separately frozen authority for two independent coarse scene passes
and bounded adjudication of these actual images. Until such source evidence is
accepted, retain unknown/excluded context and the archived scientific rejection.
Exact PR CI, controller integration, merged-main checks and complete public
delivery remain required for this implementation. No running application or
model is automatically upgraded.
