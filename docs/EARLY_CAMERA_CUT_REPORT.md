# Early camera cuts and complete temporal context

October 18, 2026. Release 0.16.0 fixes an observed camera-boundary bug and adds
guarded temporal features for contact-learning experiments. No learned contact
or doubles-mechanics model is installed by this release.

## Observed failure and resulting behavior

A public BWF source rally changes from a side/close-up view to the full court
at local frame 14. The previous detector returned no boundaries: its 15-frame
minimum scene length suppressed the first edit. Tracking retained the wrong
court and carried tracker and shuttle context across the edit.

The fixed scanner lets the first temporally supported cut through and applies
the usual 15-frame spacing to later visual cuts. It retains source PTS timing,
look-ahead, preceding-window support and timestamp-gap resets. This is still a
heuristic detector; minimum spacing and visual evidence can miss short edits.
It does not establish live/replay status or rally boundaries. Old tracking
artifacts remain immutable; rerun tracking to apply the new scanner.

The source is the [official BWF men's doubles final](https://www.youtube.com/watch?v=EpLD0HrwDJU).
The selected first-set 21-10 rally clip spans source clock hints 34873-34991.
These hints are not certified full-stream decode ordinals. Its SHA256 is
`3d1c8fba275b03c1af4b1f00c408d0e20e530178e23fbcaa1e6dfa2e365cdcfe`.
Consecutive source frames 13/14 visibly establish the edit. This local camera
boundary is separate from the unresolved service-contact time.

## Temporal feature guard

The new `contact_features` module samples observed arm/pose/shuttle descriptors.
Missing observations remain masked; it does not synthesize shuttle positions,
assign persistent players or classify mechanics.

Its evidence range includes the earlier point used for velocity and all
transitive component-selection history. Camera, scene, calibration and timing
guards inspect that complete range. Without this, a nominally valid window
could consume an excluded earlier observation. Weak source-contact intervals
crossing a camera boundary or excluded view remain unavailable references;
they are not moved to another shot or silently dropped from source counts.

An unlabelled compatibility audit of 63 completed train/validation clips covered
13,695 frames. All 11,918 retained feature vectors matched the frozen prototype
exactly; 8,707 evidence ranges widened and none were suppressed in those inputs.
This proves a property of these cached vectors, not timing or recognition
accuracy. It also cannot repair a cut missing from the input metadata.

## Corpus correction and verification

Both queued model trainers stopped before optimization or test predictions.
The old 74-rally extraction and partial next-rally stage artifacts are preserved.
A new full preflight scans all 203 clips. It found 227 camera ranges and 24
close-up-to-court transitions; nine existing cut sets changed. Adjacent source
frames support all 24 selected transitions on assistant first inspection.
[The frozen review](../data/manifests/source_camera_review.json) is assisted,
human-pending and not exhaustive camera truth.

For this fixed-camera research corpus, published court corners are checked
against white outline and green interior support in each camera range.
Unsupported close-ups stay explicitly unknown; they may contain a live serve.
This is research input preparation, not a general automatic court detector.
Source labels and their `training_ready=False` status remain unchanged.

The corrected CUDA run on the 119-frame failure case detects 14 in both stages:

- Player run `ee05fe65f8114f3f804c76d185fcb712`: precut IDs 1/2 and postcut
  IDs 3/4/5/6/11/12 are disjoint. Calibration is absent in the unsupported first
  view and applies to frames14-118 in the supported court view.
- Shuttle run `2f74cf35a1cb47539fa8e98f3a0f669f`: camera context restarts at 14;
  visible postcut points do not retain earlier component-selection history.
- Temporal features retain 93 valid frames and no contexts centered before 20.
  The ambiguous service supervision crosses the edit and stays unavailable.

Corrected extraction reuses old native bytes only when the complete new cut
set, annotation context, other perception code and pinned models agree. Changed
inputs are processed again. Runtime snapshots prevent later worktree changes
from altering a long running batch.

Verification records are local, gitignored research artifacts:
`.cache/early-cut-native-v2-verification.json`,
`.cache/contact-feature-context-audit.json`, and
`.cache/s2-contact-corpus-v2/preflight-summary.json`.
Generated early-edit tests cover cuts 5/10/14, VFR timing and bounded subranges.
Camera/scene/tracker and feature tests pass; final release checks are recorded
in the PR. Full-match contact, hitter, family/side and fault accuracy remain
unverified and unfinished.
