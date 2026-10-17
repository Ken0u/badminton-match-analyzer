# Contact timing and short-gap recovery

October 17, 2026, version 0.13.0. The contact detector now models transitions
between source frames and uses bounded observed samples across nearby short
gaps. It improves review proposals on the new public doubles rally, while
substantial misses and attribution uncertainty remain. This is not a validated
full-match contact/shot analyzer.

## Changes

The prior observed-motion rule fixed a broken-line junction at a sampled frame.
A real hit between samples, plus finite heatmap resolution and localization
noise, could fail that fit even with clear direction change. The new path
profiles a shared two-dimensional junction across one source-frame interval.
It retains the existing abrupt-vs-quadratic error ratio and pixel-improvement
floor, adds an absolute residual limit and penalizes the extra fitted parameter.
The small-sample residual score counts eight parameters including noise for the
profiled broken line versus seven for the quadratic; gain must reach 6. These are
heuristic selection rules, not calibrated probabilities or a hypothesis test.

Additional proposals require at least three confident observations of a moving
wrist within the checked trajectory context. Multiple plausible tracks leave the
hitter unknown. In forecourt overlap, the nearest body/wrist can be the opponent;
proximity is not proof of hitter identity. No persistent player label is inferred
from an ambiguous hint.

The gap path can gather up to four actually observed samples on each side,
within 0.20 s of its bordering observations, with at least three per side. The
central gap remains bounded by 0.24 s. Every original intervening frame remains
available for timestamp, jump, scene and camera-cut checks. Missing shuttle
points are never filled or changed. Neighboring review intervals are deduplicated.
A supported profiled interval replaces an overlapping sampled-point proposal;
existing gap intervals remain available. Navigation stays on a real source frame.
Bounds combine profile support and source-frame quantization; they are possible
review ranges, not statistical confidence intervals.

Artifacts retain the method, recipe and complete evidence-window bounds. A scene
edit outside a proposal's timing range can invalidate its evidence: both the API
and unsaved editor view now enforce that context. Known legacy motion proposals
get a conservative derived window in a copy, explicitly marked as such; raw
artifacts stay unchanged. Player-only scene/cut flags are also honored.

Recognition no longer uses a contact whose context has become excluded. Evaluation
reports excluded candidate IDs and counts genuinely reviewed live hits as misses
when no usable prediction remains, preserving rather than hiding difficult gold
events. Invalid context bounds are rejected. Contact requests also reject changed
source files before queuing analysis. The editor's timing help covers uncertainty
generally and the event counter now uses the singular form for one event.

## Actual footage

The [machine-readable comparison](subframe-contact-verification.json) reruns
frozen v2 code from main 78498c6 and current v3 on identical cached perception
inputs, recording their hashes, run IDs, intervals, hints and runtime. No model
weights, raw detections or reviewed app labels were changed.

| Development input | v2 proposals | v3 proposals | v3 cached-input runtime |
| --- | ---: | ---: | ---: |
| Public doubles, 390 frames | 1 | 6 | 0.291 s |
| Original singles first view, 384 frames | 8 | 12 | 0.365 s |
| Original doubles first view, 588 frames | 12 | 20 | 0.449 s |
| Original singles pilot window | 5 | 6 | 0.234 s |
| Original doubles pilot window | 7 | 9 | 0.200 s |

The public excerpt has 13 published shot references, including its serve. Current
contact navigation frames are 56, 72, 80, 117, 144 and 210. The five additions were
inspected in native source crops: they align qualitatively with near-receiver,
far-backcourt return, near-receiver, net-shot and lift actions. This inspection
followed predictions and is development evidence, not independent adjudication.
The new forecourt hints remain ambiguous; human identity/timing review is needed.

These counts do not measure precision, recall or complete-event accuracy. The
published shot-start cues are not independently verified contact times; the
source-first manifest remains unchanged. Seven references still lack generic
contact proposals, and other views have unreviewed additions, including late
transitions near diving/terminal actions. The old singles pilot's two missing
contacts remain unresolved. No family/side correctness is established by adding
contact intervals. Out-shot endings, detection gaps, noisy trajectories, hitter
attribution and doubles recognition remain active work.

## Controlled checks and review workflow

The committed synthetic fixture has one known between-frame velocity change,
Gaussian 0.7 px error, 1.25 px quantization and a nearby moving wrist. Across seeds 0–99,
v2 matched 9/100 positive scenes and v3 matched 97/100 using interval containment
or half-frame point tolerance; v3 navigation alone met half-frame tolerance
on 92 scenes. Neither method emitted proposals on 100 noisy smooth-apex, 100
straight-flight or 100 stationary cases. This is a mathematical diagnostic, not
badminton accuracy; it varies localization noise on a small set of motion shapes.
The report records its fixture/code hashes and matching definition.

439 standard tests pass, with four unchanged opt-in GPU tests skipped. New
regressions cover subframe/VFR bounds, adjacent gaps, raw immutability, missing or
stationary wrists, sparse pose, cuts, source-time gaps, scenes, jumps, overlapping
players, evidence bounds and downstream scene-mask consistency. Perception
weights and inference math are unchanged, so cached real CUDA inputs are reused.

All five real-sample UI workflows and a new generated-media contact workflow
exercise interval review, draft context exclusions, explicit save, source/candidate
lineage, export and reload. The generated workflow uses no sample files or model
weights and runs in CI alongside upload and rally checks. It is available via
`scripts/contact_ui_test_server.py` on 8004 and `npm run test:contact-profile`.

The main originals remain at annotation revision 4 with six events each; all eight
original shot-family/side labels are still unknown. More reliable observation
and independently reviewed complete rallies remain necessary before claiming
automatic full-match correctness.
