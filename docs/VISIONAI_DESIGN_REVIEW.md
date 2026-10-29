# Badminton-VisionAI: independent design review

Reviewed 2026-10-29. Reference repository: https://github.com/amramer/Badminton-visionAI
Inspected source tree: `a17e47251b971aa7fda6d60d0424ffb3887030b6`.
Local comparison baseline: cached origin/main `d2a1e0121b011d22deca143d1b5395feed2b30c9`.
This design proposal is delivered by software-only task
[#344](https://github.com/Ken0u/badminton-match-analyzer/issues/344). It is not an
implemented dashboard feature, benchmark of the reference application or
amendment of task #342.
No reference source, model, assets or documentation were copied into our app.

## Useful ideas and independent adaptations

1. Synchronized court explorer. Add a mini-court beside the existing source
   player and event timeline. Show player ground positions only under current
   valid calibration and supported identity. Selecting a point seeks the exact
   source timestamp. Keep singles/doubles geometry and end changes explicit.
   A court-plane projection cannot supply airborne shuttle height or true speed.
2. Positioning analytics. Offer per-player/team occupancy heatmaps and optional
   front/middle/rear zone dwell times. Weight by native source PTS, not frame
   count divided by a nominal FPS. Exclude replay/non-play, stale geometry and
   identity gaps; expose eligible seconds and unknown seconds. Link every
   summary back to its contributing source intervals.
3. Shot profiles. Derive six-family and forehand/backhand summaries from the
   canonical versioned event records. Offer explicit reviewed-only and predicted
   filters. Support all four doubles players and unresolved attribution; count
   one contact once. Chart and timeline totals must derive from identical rows.
4. Rally navigation. Add rally cards with start/end uncertainty, event count,
   review coverage and source thumbnails. Click through to the synchronized
   editor. Missing or unresolved boundaries must remain visible.
5. Shareable match summary. Build printable reports from the same versioned
   analytics snapshot, with source/revision provenance and review coverage.
   Tactical claims must be supported by observations; uncertain recognition
   must not produce confident coaching recommendations.
6. Occlusion recovery as a separate research candidate. The reference uses
   TrackNet/InpaintNet. Investigate primary upstream methods and permitted
   weights independently if justified by our error analysis. Preserve observed
   versus repaired trajectories, never bridge cuts, and evaluate contact timing
   as well as point error. Do not install a model on the basis of a demo.

## Implementation findings that limit what to borrow

- `shot_detection/detector.py` invokes a user-configured Roboflow project/version
  on frames and attributes the highest-confidence detection using player-box
  overlap. It is not a supplied reproducible six-family/side temporal learner.
  We will retain our required clear/lift/net/drop/smash/drive taxonomy and
  separate stroke-side labels; no external inference service is introduced.
- `tracking/court_detection/court_detection.py:209` constructs an ImageNet ResNet
  and replaces its output layer with a 24-value head, without loading trained
  court-head weights in that path. Fixed/manual keypoints are another path.
  This inspected path does not establish a trained automatic court detector.
- `webapp/tabs/shot_profile.py:304` restricts its selected shot events to player
  IDs 1 and 2 and reconciles them with desired aggregate counts. Our charts
  should support four players and derive totals directly from event records.
- `analysis/metrics.py:246` differentiates projected ball coordinates and labels
  the result km/h, with squared velocity called power. A planar projection of
  an airborne shuttle is insufficient for true 3D speed or physical power.
  Preserve this distinction in our metric names and product claims.
- The README describes cache reuse from output-file existence. Preserve our
  stronger source/model/settings/clock/context lineage and invalidation rules.
- The reference publishes restrictive reuse terms. This review uses abstract
  feature ideas; any future dependencies come from separately assessed upstream
  sources. No reference code, text, assets or weights enter our distribution.

Source links:
- https://github.com/amramer/Badminton-visionAI#-features
- https://github.com/amramer/Badminton-visionAI/blob/a17e47251b971aa7fda6d60d0424ffb3887030b6/shot_detection/detector.py
- https://github.com/amramer/Badminton-visionAI/blob/a17e47251b971aa7fda6d60d0424ffb3887030b6/tracking/court_detection/court_detection.py
- https://github.com/amramer/Badminton-visionAI/blob/a17e47251b971aa7fda6d60d0424ffb3887030b6/analysis/metrics.py
- https://github.com/amramer/Badminton-visionAI/blob/a17e47251b971aa7fda6d60d0424ffb3887030b6/webapp/tabs/shot_profile.py

## Priority and verification before implementation

Normal original-host terminal-proof recovery has released expired #342 while
preserving its clock and zero-dispatch record. Software-only #344 delivers the
prepared validator and a shutdown repair, without source assessment or renewed
scientific runtime. Propose a focused mini-court/analytics task under the existing
product milestones, with a committed grant before implementation.
UI work can improve usefulness while source review and recognition
research continue, but must not be represented as a model-accuracy improvement.

Meaningful acceptance checks for that task: variable-rate dwell-time accounting;
camera/scene/calibration expiry; unknown IDs and doubles partner crossings;
event/chart/export parity after a saved correction; uncertainty and unsupported
interval display; browser seek synchronization and readable mobile layout.
Use required exact-head CI and controller/main verification for delivery.

## Verified project snapshot

- App ingestion, React review/export and resumable source processing exist.
  Complete automatic annotation accuracy remains unproven.
- Frozen 75-rally classification: R2/R3 six-family macro F1 0.380/0.465 and
  strict family/side accuracy 0.357/0.421 without confidence abstention. This
  uses weak published contact/hitter context on one singles match. Unavailable
  inputs count as misses; thresholded R3 strict joint accuracy is only 0.143.
- Familiar-source shuttle development diagnostic: parent/decoder localization
  F1 0.651/0.696; convolution 0.333. There are only 25 visible cases, seven
  negatives and 28 unknowns, with agent labels. No candidate was promoted.
- The later learned selector comparison produced unavailable output for all
  60 cases because scene context was unreviewed. That is not a usable gain.
- #342 has 870 prepared sheets. Its retained check receipt reports 5,585 tests
  passed / four skipped; all seven check processes are recorded terminal.
  Its latest retained science observation has zero jobs, sessions and image
  bytes. Current local Python/Codex process inspection found no training or
  assessor worker at that dated inspection. The accompanying scene-review
  software repair has separate generated regression evidence on #344.
- Complete independently accepted rally references remain 0/2 in these reports.
  The original checkout and its existing PROGRESS.md edit remain preserved.
