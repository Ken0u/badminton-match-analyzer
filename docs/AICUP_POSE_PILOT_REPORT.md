# Balanced AI CUP native pose-input pilot

Task [#385](https://github.com/Ken0u/badminton-match-analyzer/issues/385) prepares
development player/pose inputs from existing AI CUP sources. It performs no
training, shuttle inference, classifier inference or model installation.
Preparation completed on November 4, 2026. The single prospectively frozen
native observation is running; final coverage and verification remain pending.
The application has no new accuracy result from this work; complete scientific
rally references remain 0/2.

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

## Prepared cohort and prospective freeze

The original development pool contains 6,391 rows. The fixed rule selected 48
contacts with no family/side/fold shortfalls; deduplication produces 45 full clips
and 24,273 native frames. All 784 source reference rows in those clips remain,
including three H0 contacts censored at the left clip boundary. The selected
clips happen to contain no unknown family or side labels; this does not establish
their absence from the corpus or certify the labels' correctness.

| Original fold | Selected contacts | Full clips | Native frames | Retained reference rows |
| --- | ---: | ---: | ---: | ---: |
| Training | 24 | 22 | 13,487 | 431 |
| Validation | 24 | 23 | 10,786 | 353 |
| Total | 48 | 45 | 24,273 | 784 |

Training capture contexts contribute Tokyo 4, Kuala Lumpur 2, Osaka 2, Jakarta
red court 6, Bangkok 7 and Birmingham 1 clips. The 23 validation clips use the
original Odense context. These capture contexts are not independently resolved
original-match identities. Selected media occupy 145,607,402 bytes; the prepared
snapshot occupies 151,615,467 bytes, below the frozen ceilings.

The [prospective commitment](https://github.com/Ken0u/badminton-match-analyzer/issues/385#issuecomment-6629881943)
was published before native inference. It binds consumer commit
`2d471a0140b4fd3a72c6fe122cfb3cc2b0d33b7b`, preparation freeze
`24110a19919ba0307fbeff375d64ea973ab535ac6bf8b63f2b78cf7ff8563dea`, and protocol
`014bd53437c78b1a9bc94a2fba5e7cd83f2b2d99bf8effe60e076f278429ed1a`, together
with the source, model, code/runtime, cohort, native-clock and camera inventories.
The scientific window is eight hours from the original grant; a lease renewal
does not extend it. No repeated native pass follows from a failure.

The frozen runtime uses Windows, Python 3.10.5, torch 2.8.0+cu126, torchvision
0.23.0+cu126, ultralytics 8.4.178, PyAV 16.1.0, numpy 2.2.6, OpenCV 4.14.0.94
and scenedetect 0.7.2 on CUDA 12.6 / RTX 3050 Ti. Existing standard small-pose
weights and the tracker recipe are unchanged.

## Coverage interpretation and remaining work

Support means at least one shoulder, elbow or wrist with confidence at least
0.25 on any observed player on either frame of an in-bounds published `[H-1,H]`
interval. Joint observation totals can repeat across players and the two frames.
They are not counts of correct contacts, distinct hitters or verified poses.
H0 remains unavailable; camera-crossing and unsupported intervals stay explicit.

Every retained row has unresolved hitter/scene truth and remains ineligible for
training. Candidate actor ambiguity is preserved even if only one player was
observed: a missed player is not evidence that the visible player hit the shot.
The singles processing placeholder does not certify source format. No shuttle
pass, classification, fitting, model promotion or annotation update occurs.

Final reporting requires the unchanged native pass to terminate, reproduction
of all support/clip receipts from original rows and native outputs, verification
of every frame/PTS and code/runtime/model/source seal, and durable completion in
the real Store. Per-fold/context/family/side support must retain all 784 rows,
including unavailable cases. Final PR, merged-main and public delivery are still
pending. This pilot measures available inputs for a later learning experiment;
it does not establish improved automatic badminton accuracy.

## Software verification

The tested consumer passes 60 new generated tests and 138 focused tests. The
corrected full run passes 5,974 tests, with four optional GPU skips and one
existing dependency deprecation warning. Ruff, formatting, dependency,
repository and whitespace checks pass. Clean source/wheel/installed-HTTP checks
cover 111 runtime files, 60 public manifests, five frontend assets, three SPA
routes and authentication.

The first full invocation preserved nine existing broadcast-fixture failures
caused by sandbox ownership and 164 missing-tool skips. A run as the workstation
owner with the existing pinned FFmpeg/Node tools passes the full suite; neither
Git trust settings nor checks were weakened. These software checks establish
implementation behavior, not scientific annotation accuracy. Documentation-only
report updates require fresh text/link/package checks, not another native pass.

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

After `verify` succeeds, the following read-only snippet reproduces interval
support counts by fold, capture context, family and side. It requires the full
completion denominator and prints no individual source rows. Track counts are
distinct provisional IDs across the two interval frames, not verified actors;
zero also includes censored/unavailable intervals. Report these beside joint
availability so observing the other player cannot be mistaken for hitter support.

```python
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

prepared, output = map(Path, sys.argv[1:])
freeze = json.loads((prepared / "freeze.json").read_bytes())
completion = json.loads((output / "completion.json").read_bytes())
assert completion["summary"]["clips"] == len(freeze["clips"])
counts = defaultdict(Counter)
seen = set()
for number, clip in enumerate(freeze["clips"]):
    rows = json.loads((output / f"clip-{number:02d}" / "support.json").read_bytes())
    for row in rows:
        ref = row["reference"]
        assert ref["id"] not in seen
        seen.add(ref["id"])
        family = "serve" if ref["kind"] == "serve" else (ref["family"] or "unknown")
        tracks = {p["track_id"] for p in row["pose_observations"] if p["track_id"] is not None}
        keys = ("all", "fold:" + ref["fold"], "context:" + clip["context"],
                "family:" + family, "side:" + ref["side"])
        for key in keys:
            c = counts[key]
            c["references"] += 1
            c["in_bounds"] += row["interval_available"]
            c["censored_H0"] += row["censored_H0"]
            c["cross_camera"] += row["crosses_camera_boundary"]
            c["multiple_observed_tracks"] += len(tracks) > 1
            c["no_observed_track"] += not tracks
            c["unresolved_hitter"] += row["correct_hitter"] is None
            for joint in ("shoulders", "elbows", "wrists"):
                c[joint] += any(p[joint] > 0 for p in row["pose_observations"])
            assert not row["training_ready"]
cohort = json.loads((prepared / "cohort.json").read_bytes())
assert seen == {r["id"] for r in cohort["reference_rows"]}
print(json.dumps(dict(counts), indent=2, sort_keys=True))
```
