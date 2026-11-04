# Balanced AI CUP native pose-input pilot

Task [#385](https://github.com/Ken0u/badminton-match-analyzer/issues/385) prepares
development player/pose inputs from existing AI CUP sources. It performs no
training, shuttle inference, classifier inference or model installation.
Preparation and the single prospectively frozen native pass completed on
November 4, 2026. Full CLI verification passes for all 45 clips / 24,273 native
frames and all 784 retained source rows. The application has no new accuracy
result from this work; complete scientific rally references remain 0/2.

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

## Native results

The original process exited successfully and its real shared Store job is
durably completed. The verifier reproduces every native frame/PTS, cut/calibration
state, finite pose, original-row support record and clip receipt, with the frozen
source/model/code/runtime seals unchanged. Original shared video/annotation
history also matches. Completion SHA256 is
`fe0021fca0236d2701f86d2274b3799ffae7ca5a77fffaca419e296c13deb523`.
Native output occupies 71,178,460 bytes; preparation plus native output totals
222,793,927 bytes. No second pass, substitution or deadline extension occurred.

All 784 rows remain: 781 in-bounds published intervals have any-player
shoulder/elbow/wrist support, while three H0 rows remain censored and unavailable.
None of those intervals crosses a detected camera boundary; this does not certify
live play. There are 763 intervals with multiple provisional IDs across their two
frames, 18 with one and three with none. All correct hitters and scene labels
remain unadjudicated, and zero rows become training-ready.

| Fold | Clips | Native frames | References | In-bounds | Any-player wrist | H0 censored | Multiple track IDs | No-player frames |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Training | 22 | 13,487 | 431 | 430 | 430 | 1 | 425 | 3 |
| Validation | 23 | 10,786 | 353 | 351 | 351 | 2 | 338 | 0 |

| Capture context | Clips | Native frames | References | Any-player wrist | H0 censored |
| --- | ---: | ---: | ---: | ---: | ---: |
| Bangkok | 7 | 3,798 | 132 | 132 | 0 |
| Birmingham | 1 | 935 | 24 | 24 | 0 |
| Jakarta red court | 6 | 3,580 | 121 | 121 | 0 |
| Kuala Lumpur | 2 | 916 | 30 | 29 | 1 |
| Odense | 23 | 10,786 | 353 | 351 | 2 |
| Osaka | 2 | 1,104 | 35 | 35 | 0 |
| Tokyo | 4 | 3,154 | 89 | 89 | 0 |

Counts below include every source row in the selected clips, not just the 48
selected contacts. Serve and other stay separate from the six requested shot
families. These selected clips have no unknown family/side labels; unknown
semantics remain supported without changing their denominators.

| Source family | Side | Train references | Train any-player wrist | Validation references | Validation any-player wrist |
| --- | --- | ---: | ---: | ---: | ---: |
| Clear | Forehand | 36 | 36 | 19 | 19 |
| Clear | Backhand | 5 | 5 | 5 | 5 |
| Lift | Forehand | 37 | 37 | 32 | 32 |
| Lift | Backhand | 50 | 50 | 39 | 39 |
| Net | Forehand | 74 | 74 | 57 | 57 |
| Net | Backhand | 76 | 76 | 72 | 72 |
| Drop | Forehand | 34 | 34 | 26 | 26 |
| Drop | Backhand | 6 | 6 | 4 | 4 |
| Smash | Forehand | 52 | 52 | 44 | 44 |
| Smash | Backhand | 2 | 2 | 4 | 4 |
| Drive | Forehand | 10 | 10 | 7 | 7 |
| Drive | Backhand | 7 | 7 | 5 | 5 |
| Serve | Forehand | 3 | 3 | 0 | 0 |
| Serve | Backhand | 19 | 18 | 23 | 21 |
| Other | Forehand | 15 | 15 | 8 | 8 |
| Other | Backhand | 5 | 5 | 8 | 8 |

Across the full native timeline, 3 frames contain no observed player, 978 contain
one, 23,261 contain two and 31 contain three. These are detector counts, not
verified player counts or source-format labels. All 47,593 player-frame
observations contain 17 finite keypoints; zero confident keypoints fall outside
display bounds. Nine native frames lack valid automatic calibration. Two
player-frame observations lack wrist support despite complete any-player support
around the in-bounds references. Shoulder and elbow support is present on every
observed player-frame row. Correct dominant hand, pose and actor are unverified.

| Fold | Player-frame observations | Calibrated frames | No shoulder support | No elbow support | No wrist support | Confident points outside display |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Training | 26,780 | 13,478 | 0 | 0 | 2 | 0 |
| Validation | 20,813 | 10,786 | 0 | 0 | 0 | 0 |

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

The full verifier and a separate read-only audit pass. The documented aggregate
snippet is executed against the completed outputs and checked against all
fold/context/family/side counters; every retained row remains in the denominator.
This pilot measures available inputs for a later learning experiment; it does
not establish improved automatic badminton accuracy. Exact PR/main checks,
controller integration and public delivery remain separate requirements, with
source revisions and receipts recorded on the owning issue.

## Potential weak hitter supervision

The preserved source CSVs also contain `HitterLocationX/Y`,
`DefenderLocationX/Y` and `LandingX/Y`. The
[official schema](https://sites.google.com/view/coachai-challenge-2023/tasks/track1)
defines player positions in image pixels at a foot location, using a court-plane
projection when the player jumps. Landing describes a trajectory-end projection;
it is not an exact contact point or automatically a rally ending.

A post-hoc metadata-only review of the unchanged prepared rows finds finite,
integer, in-display coordinate pairs in every retained row for all three fields:
431/431 training and 353/353 validation, with no zero-origin pairs. All selected
media have zero display rotation. This checks numeric availability, not source
correctness, temporal correspondence or actual pose/hitter association. No
coordinate entered cohort selection, tracking, calibration or a learned feature.

These fields suggest a bounded next investigation: audit native correspondence
and the foot/projection convention before using them as weak actor supervision
for a temporal pose learner. Jump projections need separate treatment from
visible ankle or box-bottom positions. Correct hitter/scene labels and training
eligibility remain unresolved; this pilot creates neither associations nor new
truth, and runs no fit.

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
                "family:" + family, "side:" + ref["side"],
                "fold-family-side:" + ref["fold"] + "|" + family + "|" + ref["side"])
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
