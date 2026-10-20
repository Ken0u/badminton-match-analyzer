# Manual court display at reviewed camera boundaries

Task [#130](https://github.com/Ken0u/badminton-match-analyzer/issues/130) fixes a
viewer error: a saved calibration covering frames 0–99 continued to draw at
frame 30 after reviewing a cut at 20, because stale tracking caused the viewer
to discard the run's cut context. The saved calibration and stale tracking flag
were correct; the polygon and status incorrectly implied applicability.

The viewer now computes display-effective ranges from current saved or unsaved
camera corrections, raw run boundaries and preceding cuts. Source PTS and known
timestamp gaps keep physical discontinuities separate even without a tracking
run. Explicit `not_cut` decisions remove ordinary cuts; removing a correction
restores raw cut evidence. A calibration stops before the first applicable cut;
one starting exactly at that cut applies independently. Explicit end-exclusive
ranges and manual priority over valid automatic geometry are preserved.

The original `effectiveCalibrations` and `courtSignature` contracts remain tied
to their original run context for persisted source/input guards. Automatic fits
still require the existing tracking, camera and court-signature checks. The new
display computation never writes annotations or predictions and does not admit
stale automatic geometry. Source frame identity, timestamps, correction records,
job admission and proposal guards are unchanged.

## Reproducible generated browser regression

Run from a locked review environment with Chromium available:

```sh
node tests/manual-court-boundary.mjs
```

`FRONTEND_PYTHON` may select the locked interpreter and
`PLAYWRIGHT_BROWSERS_PATH` may select the cached test browser, as documented in
[the frontend baseline](FRONTEND_BASELINE.md). This standalone command reuses
the public fixture API in `tests/frontend-fixtures.mjs`: it refuses `BASE_URL`,
creates a fresh generated catalog on an allocated loopback port, verifies a
random ownership token and process identity, and stops only its owned child.
All launchers, sources, native PTS, screenshots, exports and failure/cleanup
receipts remain ignored under `.cache/evidence/manual-court-*`. No model runs,
downloads, research data or existing application instances are involved.

The regression checks actual canvas pixels and court-status text before, at
and after cut 20; unsaved decisions; saved/reloaded stale tracking; absent
tracking; `not_cut`, correction removal and reapplication; explicit expiry and
replacement calibration; and valid versus stale automatic geometry. The no-run
case filters generated tracking jobs at the browser HTTP boundary, leaving the
fixture's saved artifacts and job catalog intact. Native JSON downloads and
saved-record comparisons retain the original broad calibration, events and
source identity. Exporting a draft is still blocked in the UI, and the saved
export API retains its original ranges. Original player/shuttle artifact hashes
are verified after all actions, and stale rally requests still return 422.

Direct helper checks additionally cover preceding cuts, protected timestamp
gaps, a removed previously applied correction, ordinary `not_cut` overrides,
manual/automatic priority, replacement ranges, original signature compatibility
and input immutability.

## Collected evidence

Collected October 19, 2026 (Toronto; raw receipts use October 20 UTC), with the
existing locked phase94 Python 3.12.13 environment and Chromium 156.0.8078.4.
No dependencies or running application were upgraded. Evidence paths below are
relative to the repair worktree's `.cache/evidence/`.

- `manual-court-63O34U`: the unmodified baseline reproduced the saved-cut bug at
  frame 30, with 6,872 court-colored canvas pixels and `Calibrated · frames
0–99`, while the derived API reported `requires_tracking_rerun=true`.
  Baseline `app.js` and `court-context.js` bytes, source hashes, original broad
  calibration export and owned-process cleanup receipt are retained.
- `manual-court-leYGlj`: the final repaired application passed 25 canvas/status
  observations, saved/exported range checks and immutable artifact checks, with
  no browser page errors. The polygon has zero court-colored pixels at and
  after the cut without separately applicable calibration; the preceding label
  reads `Calibrated · frames 0–19`. Native stage screenshots show the polygon
  before the cut and the clear source image at the cut. Sixteen direct range
  cases, five source-context assertions and the input-immutability assertion
  pass. Its owned child exited with SIGTERM. The earlier complete repair run
  `manual-court-Q4ipF4` is also retained.

Earlier fixture-startup and driver-development failures are retained: sandbox
loopback denial (`manual-court-IalL46`), an export-envelope assertion
(`manual-court-orOjmY`), and a test that initially awaited a download while the
UI correctly blocked unsaved export (`manual-court-aIFcKA`). None establishes an
application regression; all owned process cleanup receipts remain available.

The historical phase94 receipts, fixture/helper recipes, protocol version 1,
sample counts and ceilings remain unchanged. `tests/frontend-parity.mjs` now
expects no manual display after the new cut, while asserting the saved
calibration still ends at 100. This is an explicit approved repair, not a
reinterpretation of the old gap or a changed performance budget.

Three sequential full-suite runs passed 17/17 checks each, using an exact copy
of phase94's frozen source bundle and the same host, browser, helper recipes,
dependency locks, viewport and protocol hash. Native source/PTS canonical digest
remains `ae83e55189bfb8a9c86d9f1b7694481f831d0e15cf9eb95f8d04f97391f9cb5e`.
All owned children have cleanup receipts. The ignored
`manual-court-performance-comparison.json` retains every artifact digest and
unrounded value; its comparison script is retained alongside it.

| Run                        | Seek + overlay p95 ms | Timeline p95 ms | Playback first advance p95 ms | rAF interval p95 ms |
| -------------------------- | --------------------: | --------------: | ----------------------------: | ------------------: |
| `frontend-baseline-l1KjVh` |                  80.5 |            55.4 |                         268.5 |                16.7 |
| `frontend-baseline-kGeLn1` |                  65.9 |            51.3 |                         272.6 |                16.8 |
| `frontend-baseline-bjKw5R` |                  64.6 |            53.6 |                         269.6 |                16.7 |
| Median of run p95s         |                  65.9 |            53.6 |                         269.6 |                16.7 |
| Frozen relative ceiling    |                 102.1 |            65.8 |                         361.7 |                40.9 |

All absolute ceilings and the frozen baseline × 1.25 + 20 ms median comparison
pass. Timeline latency increased within that allowance; these runs do not
establish a speedup. As in phase94, no thermal pinning or background-load
isolation was applied. Playback overlay lag remains approximately 0.27 seconds.
JavaScript syntax checks, formatting checks for all six changed paths and
`git diff --check` also pass. Repository-wide checks, fresh independent review,
hosted CI, controller integration and delivery verification remain the owning
task's publication steps; this implementation report does not claim them.

These generated checks establish display behavior and record preservation.
They do not measure automatic court accuracy, full-match annotation accuracy,
model inference, GPU performance or persistent player identity.
