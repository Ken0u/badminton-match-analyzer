# Rally endings near court edges

October 17, 2026, version 0.15.0. Ending proposals now include a bounded region
beside and behind the calibrated court. This recovers one development ending
that was rejected solely because its settled shuttle lay beyond a sideline.
The result remains a review interval, not a verified landing, fault or line call.

## Failure and behavior

On the public BWF doubles excerpt, the corrected shuttle trace descends beside
the near left sideline, bounces and settles while players become quieter. At
local frame 330, the observed 0.48-second tail fits inside the existing 7.34 px
stationary radius: its maximum distance from the median is 7.071 px. The abrupt
settling fit beats a smooth quadratic and full-player quiet followup reaches the
existing 0.75 coverage threshold. The old final check still rejects the point
because its court-plane hint is approximately (-0.04489, 0.71295).

An ending can occur outside the playing lines. The new search region extends
0.12 of each calibrated court axis beyond its bounds. This is a bounded heuristic
region, not a physical distance or certified floor mask. The other incoming
motion, fit, visibility, complete-player and quiet-followup requirements are
unchanged. Static ghosts, smooth apices, missing tails, cuts, scene exclusions and
clip edges cannot supply an ending by themselves. Points beyond the bounded
surround still abstain. A far out shot, inaccurate court geometry, occluded
landing or fault without a visible settled shuttle can still be missed.

Ending evidence records the region and projected position as a hint, with
`line_call_verified: false`. Perspective projection cannot prove floor contact,
decide in/out or identify a fault. The UI marks near-edge candidates with
**verify landing**, and the draft notes preserve the unverified landing/fault/line
call. Clicking a suggestion still requires explicit review, add and save. No
winner, score, player identity or exact terminal time is assigned from this hint.
Serve rules and the neural perception models are unchanged.

## Real-source evidence

The [machine-readable comparison](terminal-action-verification.json) pins frozen
v1 source from main cacc4d1, current code, input hashes and the real API artifact.
It uses identical cached CUDA perception inputs; no GPU rerun was needed for
this geometry-only change. The source-first broad ending interval [300, 330] in
[data/manifests/s2_source_anchor_review.json](../data/manifests/s2_source_anchor_review.json)
predates inference, remains unchanged and awaits human adjudication. It is not
an exact contact label or exhaustive event benchmark.

| Development input | Previous proposals | Current proposals |
| --- | --- | --- |
| Public doubles, corrected shuttle | Serve 51 [44,52] | Same serve; end 319 [316,330] |
| Original singles first view | End 610 [607,621] | Same ending |
| Original doubles first view | Serve 331 [324,331] | Same serve; ending still missed |
| Original singles partial pilot | None | None |
| Original doubles partial pilot | None | None |
| Public doubles, old ghost-corrupted shuttle | Serve only | Serve only |

The new ending's inclusive interval overlaps the preexisting broad source review.
Source crops show the descent/bounce near frame 320, but the navigation estimate
319 is not an adjudicated exact ending. The interval is about 0.47 seconds wide.
Subsequent frame inspection is development evidence, not independent ground truth.
The older bad shuttle trace still fails the motion evidence checks: widening the
region does not repair detections. This recovery depends on the prior component
selection improvement as well as the new terminal region.

Cached-input proposal runtimes were 0.172/0.099/0.239 seconds for the public,
singles and doubles first views, excluding perception. These few development
inputs cannot establish full-match ending precision/recall. Generic contact
proposals remain unchanged, with several missed public contacts. Pairing one
possible serve and ending does not make the intermediate rally fully annotated.

## Verification and next steps

481 standard Python tests pass; four unchanged opt-in GPU tests are skipped.
New checks cover all four court edges and a corner for singles/doubles, points
beyond the surround, VFR source timestamps, unknown line calls and the same
static/apex/missing/pose/cut/scene failure cases. The real API uses the cached
public native inputs, validates source timestamps and emits the same two review
intervals without changing annotations. Generated-media browser QA covers the
near-edge guidance, unknown hitter/mechanics, draft scene/court staleness,
explicit save, terminal interval and provenance export, notes and reload. The
workflow remains in CI without sample files or model weights.

Main originals retain annotation revision 4 and six events each. All eight shot
family/side labels remain unknown; no model proposal was copied into main truth.
Broader independent complete-rally/contact/visibility labels, fault/occlusion
handling, missed contacts, doubles recognition and resumable whole-match analysis
remain necessary before claiming full automatic correctness.
