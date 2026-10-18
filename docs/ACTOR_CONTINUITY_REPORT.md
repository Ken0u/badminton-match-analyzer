# Actor continuity across processing windows

Separate full-match windows previously gave the same observed person unrelated
tracker IDs even when both runs contained the same source frames. A final CPU
stage now links well-supported repeated observations and exposes provisional
anonymous actor hints in the viewer. Raw tracker IDs, reviewed player mappings,
events and exports remain separate.

This begins automatic identity continuity. It does not establish player names,
a complete roster, identity across camera cuts or recovery from every mistake
inside an individual tracker run.

## Linking evidence and conflict guards

Inputs must be complete stride-one player runs from the same source hash,
ordered by source range. Their common frames must agree on source PTS and actual
global camera-segment starts. A tracker ID reused across camera segments is an
input error. Only calibrated live observations with finite in-frame boxes and
detection confidence at least 0.25 supply identity evidence.

For each common source frame, boxes must match mutually and unambiguously:
intersection over union at least 0.70, with at least 0.15 separation from either
observation's alternative match. A link requires five supporting frames spanning
at least 160 ms and agreement on at least 85% of frames where both tracks are
eligible and present. These are engineering guards, not calibrated probabilities
or validated operating points for arbitrary footage.

Track components merge only within the same detected camera segment. Tracks
observed together cannot belong to one component, including through transitive
links. If a track has competing supported partners that are observed together,
all its proposed links are quarantined. This avoids selecting one convenient
branch of an apparent identity switch. Ambiguous or insufficient evidence stays
unlinked.

Each provisional actor ID is deterministic for its source, camera and earliest
member. The output retains run/track membership, exact supporting source frames,
geometric scores and rejected-link reasons. Eligible observation ranges remain
discontinuous: an ID is never displayed merely because a weak/excluded frame
falls between a track's first and last eligible observations.

## Pipeline and viewer

Full-match processing runs `identities` after the per-window stages. Its immutable
checkpoint depends on every player artifact hash and the processing context.
The three-window fixture now has 17 stages; nine-window sources have 47. Pausing
at actor linking retains all finished perception; identical resume reuses the
actor stage, and disabling recognition still reuses compatible actor evidence.
No extra GPU model or dependency is required.

The run API serves the actor artifact and marks it stale when camera, scene or
court context changes. The viewer loads it once, switches safely between windows
and videos, and shows **Actor N?** hints on supported tracks and contact cards.
Reviewed names take priority. Automatic hints never populate the hitter editor,
create reviewed mappings or save event labels. The processing panel explicitly
calls the groups unreviewed; the count is not the number of match participants.

A screenshot also exposed the older queued notice remaining after completion.
The processing tool now updates its own queued/pause notice when that job ends.
It leaves a newer save/error message alone.

## Actual cached-source checks

The linker runs on all nine original player windows from each complete supplied
video, using the immutable perception artifacts verified in the 0.19.0 report.
This is CPU postprocessing of actual native detections, not another GPU run.
All player receipts are checked and the original bytes remain unchanged; Torch
is never imported by the linker verification.

| Source | Source frames represented by the input windows | Camera-scoped track components | Components linked across windows | Accepted links |
| --- | --- | --- | --- | --- |
| Singles | 12,023 | 49 | 10 | 10 |
| Doubles | 12,148 | 126 | 25 | 25 |

The component totals include separate fragments and camera views; they do not
describe 49 or 126 players. No ambiguous-link rejections occur in these two
development outputs, so generated negative controls remain necessary. These
counts are **unadjudicated hypotheses**, not independent identity accuracy.
Within-run tracker errors can still carry into a linked hypothesis.

The frozen final linker SHA256 is
`399c89408ad76b4d10f199b2427467b9a451f6e7217612d0fb2b93b9aa5c79f8`.
Evidence is `.cache/overlap-actor-native-v3`, including source receipts, the
frozen linker and complete outputs. The earlier output retained identical
components and links; the final version adds the exact observation-range guard.
An initial verification helper failed before admission because of a missing
import; the corrected helper did not rerun perception.

Read-only native UI checks replay the existing perception with the new actor
artifact in a separate store. Two source-window boundaries per format verify
that changed tracker IDs retain their provisional actor labels, with unchanged
annotations and no page errors. Source overlays were visually inspected.
This checks integration and display, not independently adjudicated people.
Evidence: `.cache/actor-native-browser-v2.json` and
`.cache/actor-native-ui-preparation-v2.json`; the latter explicitly records the
cached-perception derivation. Original analysis manifests are untouched.

## Regression checks and remaining requirements

Twenty linker checks exercise changed ID/order, transitive continuity, camera
separation, PTS/source mismatches, ambiguous doubles boxes, overlap switches,
competing-partner forks, missing evidence and discontinuous observation ranges.
Pipeline/API tests cover hash-backed reuse, cancellation before the final stage,
unchanged reviewed annotations and context staleness.

The full backend suite passes **633 tests**, with four optional GPU skips.
Generated 130-second browser checks pass pause/resume, source-window navigation,
stable actor hints, disappearance/reappearance through a weak-detection gap,
explicit unknown-hitter saving and all-17-stage reuse. Formatting and lint pass.
The final browser regression also verifies the completion notice for the exact
submitted job, avoiding a previous completed job's display state.

Next, independently review difficult within-run switches and camera transitions,
then add suitable appearance and temporal evidence for cross-view continuity.
Uniform similarity alone is insufficient to distinguish doubles partners.
End changes, replays, occlusion recovery and named/persistent player attribution
remain required, along with the outstanding scene, contact/rally and shot-model
accuracy work. Full-match correctness remains unproven.
