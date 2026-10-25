# Contact and recognition evaluation across camera edits

[Issue #258](https://github.com/Ken0u/badminton-match-analyzer/issues/258)
repairs a reproduced measurement error in saved contact and recognition
evaluation. It changes evaluation, without changing model outputs, contact
proposal generation or reviewed annotations.

## Reproduced defect

On main `3a35287f5d8991c08717d4ab31dec14b59e4d2fe`, a generated reviewed hit at
frame 19 / 0.76 seconds matched a proposal at frame 20 / 0.80 seconds across a
known camera cut at frame 20. A complete live review window covered both sides.
The evaluator reported one true positive and F1 1.0 at its 0.12-second tolerance.
It merged review coverage without separating camera views.

The recognition evaluator inherited that timing match. Matching family, side
and hitter values on the post-cut proposal falsely credited the pre-cut
reference as a correct family, hitter and complete event. Separate generated
reproductions preserve both effects, including a valid unchanged calibration
signature; the defect does not depend on stale court metadata.

## Corrected domain and matching

Eligible reviewed coverage is still exhaustive and live. Touching review
windows can merge, but the resulting ranges split at each applicable known
camera cut. Representative-time matching, tighter-tolerance matching and
inclusive interval support all use those separated ranges. The example now
retains 40 reviewed frames, one reference and one proposal, with zero matches,
one missed reference and one false proposal. Neither side of the edit is
dropped to improve the result.

A proposal's inclusive possible-contact bounds and any declared half-open
evidence context must fit within one uninterrupted eligible range. A proposal
spanning a camera cut or unreviewed gap is excluded with its ID and reason;
its navigation frame cannot shorten its evidence into an eligible event.
An interval ending on the last frame before a cut belongs to the earlier view;
an interval starting at the cut belongs to the following view. An evidence range
ending at the cut is half-open and does not include the following view.

Recognition consumes the contact evaluator's exact eligible reference and
proposal IDs and its camera-separated matches. Proposals excluded for reviewed
scene, coverage or camera context cannot reappear as family false positives or
complete-event claims. Eligible unmatched proposals still count as false outputs;
eligible unanswered references still count as misses. Unknown and model-assisted
labels retain their existing exclusions.

## Available context and limitations

Known cuts come from saved run/court context and applicable reviewed camera
additions. Malformed cut metadata and changed known camera/court context produce
validation errors. Legacy artifacts without camera metadata remain supported,
with the lack of known context explicit. An empty known cut list is not evidence
that every real edit was detected. This repair does not discover camera cuts,
certify scene labels or reconstruct an unavailable source clock.

The evaluator preserves native source times and existing optimal one-to-one
matching within each permitted range. It does not derive times from nominal FPS.
Existing partial-run, non-live and uncertain-reference review-window exclusions
remain. No completeness declaration or exact physical contact is inferred from
an accepted proposal, last stroke or clip edge.

## Verification

Generated regressions cover cuts in supported metadata locations, stale and
malformed context, cut/coverage edges, touching and gapped windows, crossing
uncertainty/evidence ranges, empty negatives, missed predictions, singles and
doubles, optimal matching and input immutability. API/CLI tests use registered
completed generated runs and compare their results with pure evaluation while
checking saved annotation and artifact bytes remain unchanged. No model runs.
All **139 focused tests** pass. The first full run passed 3,341 tests with four
optional skips, but a final source edit overlapped pytest startup by 0.103
seconds. Its exact import timing cannot be established, so that run is preserved
without claiming final-source full verification. A fresh full run uses unchanged
code/tests, including two later API stale-cut cases. An initial API/CLI parity
assertion also overlooked the CLI's existing `schema_version` field; only the
test expectation was corrected. Original attempts remain preserved.

The final unchanged-source run passes **3,343 Python tests**, with four optional
skips, including all **139 focused tests**. Ruff lint/format, dependency
consistency, repository UTF-8/LF/JSON/local links and whitespace checks pass.
All executable/test files predate this final run, and recorded verification
process lifetimes are independently absent after exit. Exact PR/main CI and
public delivery evidence belong on the owning issue after controller integration.

Scientific complete-rally references remain **0/2**, with all four research
eligibility flags false. No private scientific images or labels are accessed,
no new assessment or image transfer occurs, and no model is trained or promoted.
This repair makes future measurements respect known camera context. It does not
establish badminton annotation accuracy or complete #62, #66, #67 or #71.
