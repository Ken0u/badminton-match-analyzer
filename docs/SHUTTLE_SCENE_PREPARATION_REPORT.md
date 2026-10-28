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
evidence and ownership revocation. Full software checks and actual-source
preparation/audit are pending at this pre-decode checkpoint. Exact PR CI,
controller integration, merged-main checks and public delivery remain required.
