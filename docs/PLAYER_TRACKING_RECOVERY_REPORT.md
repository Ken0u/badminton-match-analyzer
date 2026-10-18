# Motion-corroborated player track continuity

Player detections fragment during brief occlusion and rapid changes of pose.
The proposed correction retains the existing ByteTrack observations and uses a
second motion association to corroborate short joins between disjoint fragments.
It does not replace baseline boxes with a different tracker, interpolate missing
players or identify a roster member. Integrated native validation is pending;
the live app remains on the prior verified release.

## Why the first two replacements were rejected

The old detector gate of 0.25 removes ByteTrack's entire second matching band,
above 0.10 and below 0.25. This was confirmed against installed Ultralytics
8.4.178 and its explicit 0.10 tracking default. The
[ByteTrack paper](https://arxiv.org/abs/2110.06864) describes using weaker
observations to recover existing objects.

Passing the missing band to ByteTrack fixes that input mismatch and passes a
real CPU recovery regression. However, a controlled CUDA comparison over all
18 original player windows finds three additional same-player breaks around
824-831, 5559-5586 and 9511-9517. It recovers only one of 11 frozen reviewed
continuations. It is not promoted as a better default.

A standalone BoT-SORT candidate uses an XYWH motion model and sparse optical-flow
camera compensation, with ReID disabled. It recovers four reviewed continuations
but transfers an ID between distinct doubles partners around frames 1351-1358.
Source sheets show the transition from old track 164 to old track 161 and back;
the tracks coexist elsewhere in that camera view. This replacement is also not
promoted. Fragment counts alone would have missed the identity error.

Both experiments retain all 18 original windows, representing the complete
12,023-frame singles and 12,148-frame doubles sources. Their 27,294 inference
frames include repeated overlap halos. They hold the pose checkpoint, CUDA
input size, stride, source clocks, camera scan and unreviewed automatic court
geometry fixed. Only player inference is fresh. Original raw bytes and saved
annotations remain unchanged. Those controls do not establish unseen accuracy.

## Corroboration instead of replacement

The integrated candidate runs one detector pass at confidence 0.10 per source
frame. Strong detections at least 0.25 feed the baseline ByteTrack association;
the full input feeds the motion association. Only strong observations supply
published geometry and correspondence. Weak boxes remain internal association
input. No ReID checkpoint, training or extra detector pass is required.

Raw baseline IDs remain in `baseline_track_id`. The output keeps baseline boxes,
confidence, pose and missing observations. Raw strong `motion_players` remain
in each frame for audit. Within-run canonical tracker IDs can join only when:

- Corresponding boxes have mutual unique IoU at least 0.70, separated from either
  alternative by at least 0.15.
- Each entire eligible baseline track has at least 85% supporting correspondence,
  at least five source frames and at least 160 ms of source-time support.
- The baseline fragments never coexist; the observed gap is at most 400 ms and
  stays in one calibrated, live camera view.
- Neither track branches to counterparts that are observed together. Even a
  brief conflicting correspondence quarantines the node; strongest-edge selection
  cannot erase it. Excluded and uncalibrated co-presence remains negative evidence.
- Transitive links cannot merge co-present baseline tracks. Strided runs remain
  unlinked, and every camera reset retains a separate ID namespace.

These are engineering guards, not calibrated identity probabilities or validated
operating points for arbitrary matches. Baseline within-run errors can remain.
The proof retains supporting source frames, coverage, camera, gaps and ambiguous
IDs. Automatic continuity remains unreviewed and never supplies saved labels.

The CPU prototype over all original baseline and second-candidate motion windows
accepts seven joins: two singles and five doubles. Of the 11 source-reviewed
same-player pairs, three join and eight remain separate; all four different
opponent pairs remain separate. The 17 unknown cases stay unknown, even when a
tracker links them. The production pure linker reproduces those seven maps and
adds full source/input validation and excluded-scene co-presence guards. That
cached-input result does not substitute for fresh integrated inference.

## Context and review safety

Continuity uses evidence throughout the player window. Changing a scene range
away from a current contact can therefore invalidate its player association.
Player artifacts record the source scene signature. Changed scene, camera or
court context marks the continuity stale, restores baseline IDs in the API view
and requires tracking again. Raw artifact bytes are never rewritten.

The API restores baseline IDs before applying current reviewed mappings, so a
name attached to a now-invalid canonical ID cannot silently appear on a baseline
fragment. Dependent contact, rally and recognition contexts retain the scene
signature of the whole player window and become stale after an affected edit.
Reviewed documents and their history remain intact.

## Validation status and limits

Before new tracker or embedding outputs, all 32 temporally close old-track pairs
were inspected as source frames and crops: 11 positive, four different opponents
and 17 unresolved mixed/occluded or same-uniform alternatives. Boundary-window
duplicates are retained. This is coding-agent visual development review, not
independent human ground truth. Unknown and unavailable cases remain in reports.

Twenty pure corroboration tests cover valid and transitive joins, cuts, source
PTS, bad input, short/weak/missing evidence, ambiguous boxes, brief switches,
excluded co-presence, stride and cancellation. Actual CPU engines check the weak
association band, independent ID namespaces, pose indices and cut resets.
Scene/API regressions exercise stale remote evidence and reviewed-name safety.
Final full regression and integrated native results are pending.

Evidence is preserved in `.cache/bytetrack-native-v1`, `v2` and `v3` ledgers and
corresponding data/runtime directories, `.cache/dual-consensus-prototype-v1`,
`.cache/dual-consensus-production-v2` and `.cache/person-reid-pairs-v1`.
The first pure verification helper compared an eligible-only prototype map to
production's additional uncalibrated self-maps; its corrected comparison checks
all prototype entries and requires every additional entry to map only to itself.
No perception was rerun for that verification-helper correction.

The [fixed OSNet study](PLAYER_APPEARANCE_REPORT.md) exposes a same-uniform false
match and does not install that model. Cross-camera identities, end changes,
replays, remaining baseline switches and reliable player detection still need
work. Complete shuttle/contact, serve/end, family/side and doubles recognition
remain unproven. No tracker increment establishes fully correct match annotation.
