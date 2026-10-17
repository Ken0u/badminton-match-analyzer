# Shuttle component selection

October 17, 2026, version 0.14.0. The tracker now preserves all thresholded
TrackNet components and can choose a smaller observed component after an
implausible jump. This fixes a documented court-logo ghost near a public doubles
rally ending. It does not establish complete-match tracking or event accuracy.

## Observed failure and change

A uniform source-only review grid selected local frames 40..320 in steps of 20
from the public BWF doubles excerpt. Five shuttle centers could be located clearly;
ten frames remain unresolved and are not negative/invisible labels. Coordinates
and visual tolerances were frozen before testing new selection methods in
[data/manifests/shuttle_localization_review.json](../data/manifests/shuttle_localization_review.json).
The review is an assistant development pass, with human adjudication pending.
Earlier model counts were known, so it is not blinded or held-out evaluation.

At frame 320, the source shuttle is near (316, 506), outside the left sideline.
The old largest-area rule instead selected a stationary component on the court
logo near (659, 421), about 353 source pixels away. The same heatmap contains a
second component near the actual shuttle. This is a selection failure, rather
than a need to interpolate a missing shuttle point.

The new rule requires three coherent consecutive observations. If the largest
component would exceed the existing motion bound of six image diagonals per
second, and exactly one other observed component is reachable, that alternative
is selected. Actual source timestamps determine reachability. The rule does not
require constant velocity, so abrupt racket-contact direction changes remain
possible. Ambiguous alternatives, short or unstable history and a reachable
primary component retain the original largest-area choice. This deliberately
cannot resolve all ghosts, including plausible nearby false components.
The image-speed bound is a heuristic, not camera-invariant physics. Very fast
projected travel or an already wrong coherent history can still select wrongly;
broader independently labeled footage is required to measure those failures.

All components retain their source coordinates, heatmap bounding box, area and
peak response. Selected/largest IDs, the decision reason and a versioned recipe
are saved. A switched point carries its full transitive history bounds, not just
its immediate three predecessors. No coordinates are interpolated or shifted;
threshold 0.5, component-box centers and the pinned neural weights are unchanged.
The four smaller review errors are within visual label uncertainty, so this
increment does not introduce weighted-centroid localization.

History resets at missing observations, source discontinuities, camera views and
reviewed scene boundaries. Later scene edits invalidate affected dependencies in
copies without overwriting raw artifacts. Visual/audio contact context includes
those dependencies; rally and stroke-feature consumers reject excluded evidence.
Draft scene masks use the extended contact context before anything is saved.

## Actual CUDA and cached-heatmap verification

The [machine-readable record](shuttle-localization-verification.json) pins source,
code, native artifact and float32 averaged-heatmap hashes. The baseline localizer
is extracted from release 0.13.0, main 4a6cf1b. Replaying final code on identical
raw heatmaps reproduces native coordinates, confidence and visibility.

| Development excerpt | Frames | Changed selections | Native time | Visible frames |
| --- | ---: | ---: | ---: | ---: |
| Public doubles | 390 | 7 | 30.593 s | 301 |
| Original singles first view | 384 | 0 | 38.809 s | 344 |
| Original doubles first view | 588 | 0 | 58.169 s | 440 |

Each used CUDA with a measured 385.4 MB peak tensor allocation. These counts and
throughput are not accuracy measurements. Both original excerpts also reproduce
their earlier cached largest-component points exactly. The new public run passed
through the real API; all source frames, seven selection decisions and their
history flags were checked. No repaired points were emitted.

| Reviewed public source frame | Previous error | Current error | Visual review tolerance |
| --- | ---: | ---: | ---: |
| 100 | 1.77 px | 1.77 px | 3 px |
| 120 | 2.47 px | 2.47 px | 3 px |
| 140 | 1.46 px | 1.46 px | 3 px |
| 220 | 0.79 px | 0.79 px | 3 px |
| 320 | 353.07 px | 1.03 px | 5 px |

The changed frames are 312, 315, 316, 318, 319, 320 and 321. Source crops confirm
the shuttle's descent and bounce near the sideline; inspection of the additional
changed frames follows the experiment and is not independent ground truth. Five
positive coordinates cannot estimate full-video false detections or visibility
recall. No independently aligned coordinate labels cover the two original
first-view excerpts, so unchanged results there are regression evidence only.

Public generic contacts remain at frames 56, 72, 80, 117, 144 and 210. The serve
proposal remains 51 [44, 52], and there is still no ending proposal. Original
first-view contact and rally proposals are also unchanged. The ending detector's
in-court settling requirement excludes the outside-sideline landing, and other
motion/pose cues may also fail. This change must not be reported as recovered
contacts, a recognized shot type or a solved rally ending.

## Checks and next work

460 standard Python tests pass; four opt-in GPU tests are skipped in that suite.
The real short-clip shuttle API GPU test passes separately. Regressions cover
source PTS, direction changes, ambiguous components, missing observations,
unstable/short history, camera/scene resets, transitive evidence, immutable raw
artifacts, downstream masks and nonfinite heatmap rejection. The generated-media
browser workflow now exercises a real synthetic component switch and a draft
scene mask entirely before the contact's observed motion window, followed by
explicit save, lineage, export and reload. It also runs in CI without weights.

Main annotations remain revision 4 with six events per original video; all eight
shot-family/side labels remain unknown. Next work includes a fuller independently
adjudicated visibility/contact set, plausible-ghost association, missed contacts,
out-shot and fault endings, actual doubles recognition and resumable whole-match
processing. The full automatic analyzer remains unfinished.
