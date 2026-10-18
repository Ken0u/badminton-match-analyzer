# Automatic court calibration

Player tracking now finds visible badminton courts when saved manual geometry
does not cover the current camera view. The default is enabled in the UI and
API; `--no-auto-court` disables it in the CLI. Manual geometry takes priority.
Automatic fits stay in the tracking artifact as **unreviewed** geometry and
appear as dashed overlays. They never save court annotations or event labels.

## Geometry and abstention

The detector resizes RGB input to at most 640 pixels on its longest side and
extracts local grayscale brightness contrast. Hough line families generate
convex court hypotheses. A perspective template checks the doubles boundary,
singles sidelines, doubles long-service lines, short-service lines and center
service markings. Dimensions follow the badminton [BWF court diagram (2025, Diagram A)](https://badminton.dk/wp-content/uploads/2025/11/Section-4.1-Laws-of-Badminton-26-April-2025-V5.0-1-.pdf): 6.10 by 13.40 m, 5.18 m singles width, short service 1.98 m
from the net and doubles long service 0.76 m inside the baseline. The net cord
is not treated as floor paint. No reference corners enter inference, and no
surface hue or downloaded model is required.

Fits require support across outer and inner markings, including both singles
sidelines and short-service lines. Distinct hypotheses within 0.05 fit score
are ambiguous. Scores measure image/template agreement, not correctness
probabilities. Plain rectangles, incomplete markings and small images can
remain uncalibrated; there is no guessed full-frame fallback.

Each uncovered camera/scene interval samples up to five unique source frames.
At least three unambiguous detections must span 60% of the interval, and all
accepted fits must agree within 0.012 in normalized corner distance. The chosen
fit is an actual observed sample, not averaged or interpolated geometry.
Disagreement leaves the interval uncalibrated. Sampling is a static-view check;
it cannot prove that unsampled frames never move. Reviewed non-live/unknown
scene intervals are excluded from automatic court search.

New tracking records retain automatic calibrations, sample frames/source PTS,
candidate support, method and unreviewed status. Courts expire at camera cuts.
Current manual intervals override derived intervals, and the same effective
geometry reaches rally proposals, stroke features and the experimental singles
classifier. A shared signature invalidates affected player filtering and new
saved contact/recognition proposals after court edits. Existing saved events
remain unchanged. Legacy artifacts retain their original geometry contract;
old proposals without court provenance cannot gain that provenance retroactively.

## Verification

The frozen manifest `data/manifests/court_detector_development.json` contains
16 development images selected before detector outputs: 14 full courts and
two closeups, spanning the supplied singles/doubles footage and local public
green/red footage. Source/image hashes are recorded. Reference corners are
existing manual or source-assisted published geometry, pending independent
human adjudication. This is neither unseen evaluation nor exact court truth.

All 14 full courts produce a selected fit; both closeups abstain. Against those
weak references, polygon IoU ranges from 0.956 to 0.985 and mean corner distance
from 2.6 to 7.3 pixels on 1280×720 images. Individual CPU calls take about
0.03–0.20 seconds on the development machine. Some reference/paint differences
are visible; the references were not moved to improve these numbers. Reproduce
with local hash-matching images:

```powershell
python scripts/evaluate_courts.py --output .cache/court-evaluation-new
```

Actual CUDA player tracking used **empty** manual calibrations and annotations:

| Development excerpt | Source frames, exclusive end | Calibrated / processed | Cut frames |
| --- | --- | --- | --- |
| Supplied singles | 255–639 | 384 / 384 | 255 |
| Supplied doubles | 278–866 | 588 / 588 | 278 |
| Red-court closeup/return | 0–145 | 121 / 145 | 24 |

The red closeup stays uncalibrated; the following court view is detected
independently. These coverage counts demonstrate integration, not localization
or match-analysis accuracy. Main and isolated native annotations are unchanged.
The immutable runtime, source manifest, worker identity and complete outputs
are preserved under `.cache/native-runtime-autocourt-v1`,
`.cache/automatic-court-native-v1` and its separate native store.

An actual cached-input API check produces contacts/rallies with derived courts,
builds 222 finite source-guarded stroke-context packs and rejects changed court
geometry. Raw input artifacts remain byte-identical. No new stroke head
predictions or full-source evaluation were opened. The separate API test store
contains deliberate manual QA edits, not native empty-annotation evidence.

Regression checks: **581 passed, four optional GPU tests skipped**. Synthetic
tests cover red/green/blue floors, portrait/rotated geometry, incomplete courts,
plain rectangles, two competing courts, temporal coverage and moving fits.
Context tests cover manual priority, cuts, malformed persisted geometry,
non-mutation, feature parity and stale proposals. Browser checks pass automatic
default/opt-out requests, unreviewed overlays, draft camera staleness, and the
existing proposal save/export/reload workflow. Numerical detection/tracking code
matches the native snapshot; subsequent changes add saved-proposal staleness
metadata and review behavior.

A separate read-only browser check loads all three actual native runs, verifies
unreviewed overlays on singles/doubles/red courts and the uncalibrated closeup,
and preserves annotation equality. Screenshots were visually inspected. The
first multi-video browser attempt waited on the previous video's shared model
name and raced video selection; waiting for the selected title fixes the QA
script. No inference job was restarted for that observation failure.

## Remaining work

This is a visible-marking baseline. Obscured or nonstandard paint, narrow views,
multiple adjacent courts, slow pans/zooms, graphics and unusual camera angles
need broader independent evaluation. Detecting a painted court does not identify
live play or a replay, establish player identities, classify strokes, measure
physical shuttle height or determine in/out calls. Automatic identity recovery,
resumable full-match processing, accurate serve/end/contact recognition and all
requested family/side combinations remain incomplete. The sign-in-gated
75-rally source evaluation remains pending.
