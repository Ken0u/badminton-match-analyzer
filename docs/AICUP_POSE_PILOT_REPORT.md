# Balanced AI CUP native pose-input pilot

Task [#385](https://github.com/Ken0u/badminton-match-analyzer/issues/385) prepares
development player/pose inputs from existing AI CUP sources. It performs no
training, shuttle inference, classifier inference or model installation.
Preparation and native observation have not yet run. The application has no
new accuracy result from this work; complete scientific rally references remain
0/2.

The [fixed protocol](../data/manifests/aicup_pose_pilot_protocol_v1.json) selects
at most two eligible original contact rows per requested family/side in each
original training and validation capture fold. Selection sorts the SHA256 of
UTF-8 `aicup-pose-pilot-v1|fold|record-id`. Shortfalls remain explicit. Selected
clips are deduplicated in first-selected-row order and every original reference
row in those clips remains, including serves, other/unknown labels and censored
or unavailable intervals. Half smash is excluded. Capture groups can contain
multiple matches; exact original-match independence remains unresolved.

Targets come directly from original CSV bytes through the canonical importer,
with pinned label/media and group/index hashes. The normalized record index is
hashed for identity, never used as target authority. Held-out CSV members and
media are fenced before opening; no test model, features or predictions enter
the pilot. The author source declares CC BY 4.0; original media rights and
upstream pretraining overlaps remain separate limitations.

Preparation records integer native PTS and rational time bases separately from
the rounded app timestamps. Source orientation, final duration and every frame
ordinal are preserved. The camera scan is frozen before model observation;
camera boundaries do not establish live play. Unknown scene, source mode and
actor truth remain explicit. The tracker uses a singles processing placeholder
only for its expected-count diagnostic, never as verified match format.

One unchanged standard small-pose pass processes each selected full clip at
native stride 1, with the existing dual-tracker recipe and provisional automatic
court calibration. The real shared Store admits the entire native operation;
private data folders cannot grant competing GPU work. Runtime/source/model/code
seals and deadline/budget checks preserve partial failures. Pose availability
around ambiguous published `[H-1,H]` intervals is reported without choosing the
correct hitter; H0 remains censored. A finite wrist or provisional track ID is
neither an exact contact nor verified player identity.

## Reproduction

Use the project tracking environment and existing pinned archive/index/model;
a clone supplies reproducible consumers and protocol, not these private inputs.
First test and commit the consumer and fixed protocol. Run `prepare` with the
original grant time and an eight-hour deadline. Publish its exact source commit,
freeze hash, protocol/model/runtime/source/cohort/clock hashes prospectively
before `run`. The following arguments are placeholders, not new authorization.

```text
python scripts/prepare_aicup_pose_pilot.py prepare --archive PART1_ZIP --index EXISTING_INDEX --model EXISTING_SMALL_POSE --groups backend/badminton/aicup_capture_groups_v1.json --protocol data/manifests/aicup_pose_pilot_protocol_v1.json --granted-at ORIGINAL_GRANT_UNIX --deadline ORIGINAL_GRANT_PLUS_EIGHT_HOURS --output NEW_PRIVATE_PREPARATION
python scripts/prepare_aicup_pose_pilot.py run --workspace REAL_WORKSPACE --prepared NEW_PRIVATE_PREPARATION --freeze-sha256 PROSPECTIVELY_PUBLISHED_HASH --output REAL_WORKSPACE/.cache/NEW_PRIVATE_RUN
python scripts/prepare_aicup_pose_pilot.py verify --prepared NEW_PRIVATE_PREPARATION --freeze-sha256 PROSPECTIVELY_PUBLISHED_HASH --output REAL_WORKSPACE/.cache/NEW_PRIVATE_RUN
```

Limits are 48 selected rows/clips, 32,000 model-observed frames, 1 GiB selected
media and 4 GiB total new retained output. No substitutions, truncation, repeated
native passes or renewed scientific runtime follow from failure. Only aggregate
coverage and public protocol/code belong in the repository; detailed cohorts,
source rows, media, poses and Store/process receipts remain private.
