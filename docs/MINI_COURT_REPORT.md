# Synchronized player mini-court

Task [#345](https://github.com/Ken0u/badminton-match-analyzer/issues/345)
implements an independent adaptation of the court-explorer idea in the
[reference design review](VISIONAI_DESIGN_REVIEW.md). No reference code, assets,
weights or prose are copied. The predecessor #344 is delivered on main
`d7dadc28329871c74948fd04712e220b7d3ed464`, with exact main CI and independent
public package/image verification recorded on its issue.

## Behavior and limits

The existing editor now has a collapsible player court diagram beside desktop
playback and below playback on narrower screens. Its native details toggle
supports keyboard operation. Numbered markers correspond to the text legend;
provisional and unassigned identities also have dashed markers and explicit
labels. The map identifies its source frame and uses the existing native clock
without frame-rate interpolation or new inference.

Player positions use the bottom center of each observed display-space box as
an **estimated** foot anchor. These are approximate ground positions, not
verified anatomical coordinates. Four outer court corners define the court
plane in far-left, far-right, near-right, near-left order. Both modes share the
outer doubles boundary; singles sidelines and doubles service markings are
displayed separately. Far/near labels describe the current camera view and
never assign player identities or infer who changed ends.

Projection rejects missing/nonfinite/out-of-source corners, crossed or concave
quadrilaterals, collapsed edges, unstable equation pivots and projective
horizons. Bad source dimensions/boxes and unsupported projected positions stay
unavailable. The diagram includes a small visible court margin; farther points
are counted as unavailable rather than clamped onto the court. No airborne
shuttle projection, speed, power or movement-distance metric is produced.

Every redraw uses the current video, processing window and exact native frame.
Missing observations remain missing. Current camera corrections, timestamp
gaps and calibration expiry use the editor's existing context rules. Changed
tracking/court context, calibration editing and missing/expired calibration
clear positions. Saved and automatic geometry remain distinct; automatic
geometry is explicitly unreviewed. Replay/non-play scenes suppress the live
map. Missing/unknown scene review remains visibly unresolved.

Reviewed player/team labels require an actual current run/track assignment
covering that source frame. Cached inferred player IDs cannot supply reviewed
identity. Provisional actor labels additionally require a current analysis
plan and an eligible observation interval. Duplicate track IDs and conflicting
identity evidence do not establish a reviewed identity. Unassigned detections
remain visible without an assumed singles/doubles roster. No annotations or
original predictions are written by this visualization.

## Verification checkpoint

All 234 frontend tests pass, including generated perspective and rotated-display
projection grids, degenerate geometry, four-player doubles, variable-rate
source-frame selection, assignment/actor range expiry, duplicate identities,
scene exclusions and camera/calibration/window/source invalidation. Type checking
and the production frontend build pass. These generated checks establish
software behavior, not badminton annotation accuracy.

All 19 generated editor-browser groups pass, including singles/four-player
doubles, exact native-frame seeks, oriented variable-rate video changes,
calibration expiry, scene exclusions, native keyboard toggle and 390px layout.
Desktop and mobile screenshots were inspected. Existing processing, review,
identity, exports, accessibility and performance checks remain enabled. Measured
95th-percentile seek/timeline/playback-start latency was 81.9/31.5/86.5 ms;
animation-frame latency was 16.8 ms. These are generated local fixture timings,
not a native-match throughput benchmark, and all frozen ceilings are unchanged.

The first browser attempt exposed the summary's Space key reaching the editor's
global playback shortcut. Focused unmodified summary keys now retain their native
behavior; modified shortcuts still propagate. A later run exposed an existing
boundary-evaluation fixture expecting a match although proposal evidence starts
before the reviewed coverage. The unchanged baseline test/backend reproduces
that failure. The corrected test verifies exclusion with incomplete evidence
coverage and compatibility after full coverage, retaining uncertain timing and
the historical unknown revision. Its temporary positive-case coverage is
restored before downstream export checks. Failed attempts and cleanup evidence
are preserved rather than discarded.

The complete Python suite passes 5,599 tests with four optional skips. Ruff,
formatting, dependency, API-contract, repository/JSON/link/LF and whitespace
checks pass. The complete Python run retained stable source hashes; subsequent
edits are limited to the generated browser fixture and this report. The final
browser run exercises that fixture. No production Python or frontend source was
changed after its passing checks.

Local receipts are `.cache/minicourt345-checks-v1/verification.json`,
`.cache/minicourt345-browser-v4/result.json` and
`.cache/minicourt345-local-verification-v1.json` on the owning workstation;
these ignored artifacts are not supplied by a clone. Exact PR/controller/main
verification and complete public delivery remain pending at this checkpoint.
The owning issue records final delivery receipts.
The first hosted run, `40967880440`, caught omitted generated runtime assets:
source tests/build passed, while asset parity, package and container checks
correctly rejected the old shipped bundle/manifest. Those original logs and
source `034f104da5eaa16945bab498134e7794696d9cc7` are preserved. The bounded
repair requests three additional generated paths through the normal scope
extension before staging them; no source tests or parity checks are relaxed.
The committed extension retains epoch 1 and the original deadline, adding only
`backend/badminton/static/app.js`, `style.css` and `build-manifest.json`.
Expanded specification: `09b6b2451806297ef574e155b6dc9ef22f6641f9f6a9c1f03646ebe74b7430d3`.
The generated shipped files now match the production build, and all three
delivery/staging regressions pass. These files contain our own compiled frontend;
they introduce no dependency, reference-repository content or model change.
No native inference, scientific assessment, training or model promotion is part
of this task. Complete automatic full-match annotation remains unproven.
