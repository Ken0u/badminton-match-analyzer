# Frontend parity and performance baseline

This is phase 1 of the [approved rewrite](FRONTEND_REWRITE.md), against the
working static frontend after playback proxies. It changes no application UI,
models, annotation schema or runtime toolchain. Generated software fixtures do
not establish badminton annotation accuracy.

Run `npm run test:frontend-baseline` from a locked review environment with
the locked `.venv` (`bin/python` on POSIX, `Scripts/python.exe` on Windows),
`npm ci` and Playwright Chromium installed. `FRONTEND_PYTHON` can name an
explicit locked interpreter. The harness defaults `PLAYWRIGHT_BROWSERS_PATH` to
this worktree's ignored `.cache/ms-playwright`; set that variable and run
`npx playwright install chromium` once if the locked test browser is absent.
The harness creates a new loopback application on an OS allocated port, verifies a random ownership token
and PID lifetime, and stops only that child after checking its creation time,
working directory and command. `BASE_URL` is refused. No existing app is driven.
All media, SQLite catalogs, raw reports, screenshots and the generated Python
launcher remain ignored under `.cache/`. A failure preserves its evidence and
returns a nonzero exit. No datasets, weights or real YouTube downloads are needed.

The launcher imports trusted generated helpers from `tests/media_fixtures.py`,
`tests/rally_fixture.py` and `scripts/pipeline_ui_test_server.py`. External
YouTube download and native perception/classifier functions are replaced. Two additional generated-output controls seed an explicitly synthetic
classification artifact and an unreviewed automatic-court artifact to exercise
review transitions. Neither runs a model or replaces production review code.
Production upload validation, ingestion, source hashing, timestamps, frame
extraction, proxy transcoding/mapping, SQLite revisions/admission, pipeline
planning/checkpoints, proposals, review, evaluation and exports remain real.
Synthetic prediction inputs are identified as `synthetic_qa`; they are never
accuracy evidence. The fixture app's real Store controls all its queued work.
A CPU-only `run_local_job` and a second Store on the same catalog verify shared
admission; no heavy inference or research Store is created.

## Frozen measurement protocol (version 1)

These definitions and ceilings are declared in `tests/frontend-fixtures.mjs`
before any measurements. Do not change them to accommodate a failing run.

- Chromium headless, viewport 1440 × 1080, device scale 1, no throttling; record
  browser version/executable hash, OS/CPU/memory, Node/Python/library versions,
  dependency locks, launcher/helper/UI/protocol hashes and source bytes/PTS.
- Overlay/seek: three warmup seeks then 20 sequential seeks through the fixed
  frame sequence on the generated 100-frame, 25 fps, 1000 × 600 rally source.
  Start immediately before dispatching the real frame-input change; finish
  after the exact source image loads, canvas redraw occurs for that frame and
  two animation frames permit paint. Includes localhost decode/network/cache.
  Record every sample; use nearest-rank p95. Ceiling: 2000 ms.
- Playback: three 2500 ms observations on that real 4-second source. Measure
  click-to-first source-frame advance, animation-frame intervals while playing,
  source-frame progression, displayed-frame lag and actual video frame callback
  metadata. Ceiling: first advance p95 1000 ms and animation interval p95 100 ms.
  UI overlay updates use `timeupdate`, so record their lag separately; a 250 ms
  browser event cadence is a known limit, not source-frame synchronization.
- Large timeline: 1000 reviewed events (unknown family and side) across source
  frames 0–999 in a 1300-frame, 10 fps, 640 × 360 generated source. Twenty fixed
  marker DOM `click()` calls measure handler-to-selected-editor/paint,
  independently of the image decoder and OS pointer routing. Ceiling: p95 500 ms.
  Also assert exact source image/frame after each click, without including decode in the interaction metric.
- Same-host migration comparison: require identical protocol/fixture/helper
  hashes, host/browser/viewport/dependency setup and warmup/sample counts.
  Each p95 must satisfy its absolute ceiling and be at most the saved baseline
  p95 × 1.25 + 20 ms. The 20 ms floor tolerates clock/scheduling noise; it is
  not a claim of timer precision. Repeat both revisions three times on an idle
  host and compare the median of their p95s; retain every failure and raw run.
  CI is a correctness smoke and absolute-ceiling check only, unless its host is
  equivalently pinned. Other hosts cannot establish a relative speedup.

Each run writes `protocol.json` before browser measurements, `fixture-manifest.json`
with native PTS and source hashes, `environment.json`, `checks.json`,
`latencies.json`, screenshot evidence and process/cleanup receipts to its printed
`.cache/evidence/frontend-baseline-*` directory. Reports include observed values,
not hardcoded passing performance numbers. Later phases must keep these fixtures
and definitions or explicitly version a changed protocol and collect a new
baseline alongside the old one.

## Exact source bundles and cross-worktree reuse

A first run generates five sources and saves `source-bundle/manifest.json` in
its retained fixture root. `source-bundle.json` in the evidence names that path.
Set `FRONTEND_SOURCE_BUNDLE` to that directory for repeat/migration runs. Copy the
whole bundle into the destination worktree's `.cache/` when comparing another
checkout; no generated bundle is committed or required from a clone. Before
starting the app, the launcher verifies every source SHA-256 and all three helper
recipe hashes. It copies frozen bytes into its newly owned fixture root, then
runs production ingestion. Each run still gets a fresh catalog and process.
Do not edit a frozen manifest to bypass a mismatch.

Container encoders can emit different nonsemantic IDs (especially Matroska), so
freshly generated source bytes are not assumed identical. Such a fresh run is a
correctness/absolute-ceiling check; reuse the verified bundle for relative
performance. Compare canonical fixture records sorted by video name, containing
the exact keys `name`, `sha256`, `width`, `height`, `rotation`, `frames`,
`timestamps`, in that order, sorted with `a.name.localeCompare(b.name)`. The
Complete native PTS are retained. Catalog paths, random job/event IDs, PID,
port and timestamps of the run are not fixture semantics. All canonical source/PTS records must match;
unknown labels and unavailable input cases are never dropped.

## Parity matrix

The check names below refer to deterministic blocks in `tests/frontend-parity.mjs`.
An explicit boundary describes current behavior, not a claim of coverage.

| Area                     | Deterministic check and invariant                                                                                                                                                                                                                                                                     | Existing boundary                                                                                                                      |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Upload / YouTube         | `imports`: native oriented upload, invalid media/URL, canonical stubbed YouTube doubles, progress/error, duplicate import revision preservation                                                                                                                                                       | Network/download speed and public availability are not measured                                                                        |
| Library / drafts         | `selection`, `late-derived`: late annotation/player-run response cannot replace selected video; cancel/accept discard; edits during delayed save remain dirty; switching during save is refused                                                                                                       | Browser confirm is current discard UI; no cross-video draft cache                                                                      |
| Concurrent saves         | `conflict`: another API client saves first; stale UI PUT is 409, newer revision intact and local draft retained                                                                                                                                                                                       | Conflict requires explicit reload; no automatic merge                                                                                  |
| Source clock / proxies   | `source-clock`: exact native PTS, oriented dimensions, compatible proxy mapping, native/proxy quadrant pixel agreement and native frame image, final VFR long gap and JSON/CSV source identity                                                                                                        | Browser playback is not an exact source frame clock                                                                                    |
| Camera / scene / court   | `context`, `automatic-court`: camera correction invalidates suggestions and hides automatic court; replay disables proposals; overlap validation; court polygon save/expiry/removal                                                                                                                   | Broad saved manual court remains visible across a newly marked cut (measured gap); automatic geometry/segmentation accuracy unmeasured |
| Player identity          | `identity`: reviewed track interval is saved/exported and reflected in derived run with annotation revision; original artifact hash unchanged                                                                                                                                                         | Persistent identity recovery and doubles identity accuracy unsupported                                                                 |
| Shuttle                  | `review`: visible normalized click, explicit invisible null point, unknown review scene preserved, review coverage and saved-revision evaluation                                                                                                                                                      | Native canvas coordinates are checked; synthetic points are not real shuttle truth                                                     |
| Contact / strokes        | `processing`, `strokes`, `classification`: explicit suggestion acceptance, original artifacts unchanged; six families × two sides; synthetic family suggestion explicitly applied, manual side retained, changed-label score cleared; unknown hitter/family/side and provenance through export/reload | Native model quality and doubles recognition unsupported                                                                               |
| Rally                    | `rallies`: real generated-input proposals stay separate until accepted; serve contact interval vs terminal interval; unknown line call and provenance retained                                                                                                                                        | Winner/line call and exact interval truth unverified                                                                                   |
| Jobs                     | `processing`, `recovery`: visible progress, cooperative pause, resumed checkpoints/reuse, annotations unchanged; admitted CPU cancellation and stale PID-lifetime recovery                                                                                                                            | No GPU timing; process crash is represented by a mismatched lifetime record, not killing a research job                                |
| JSON / CSV               | `exports`: UI downloads parsed; source frame/time, IDs, revision/proposal lineage and unknowns retained; JSON includes all review fields                                                                                                                                                              | CSV is event-only and has no annotation revision column                                                                                |
| Keyboard / accessibility | `accessibility`: onboarding focus, Tab navigation, native button activation, arrow stepping, input shortcut guard, save shortcut, status roles/live text, focus after save/discard, label inventory                                                                                                   | Save/discard focus falls to BODY; canvas labeling is pointer-only; no claim of WCAG conformance or screen-reader testing               |
| Responsive / errors      | `accessibility`: 768 × 1024 horizontal fit, error/live feedback and browser page errors captured                                                                                                                                                                                                      | Other viewports and assistive technologies unmeasured                                                                                  |

## Collected baseline

Collected October 19, 2026 (Toronto; receipts use October 20 UTC), on Apple M2,
8 logical cores, 16 GiB RAM, macOS 15.1 / Darwin 24.1.0 arm64. Node 22.16.0,
Python 3.12.13, Chromium 156.0.8078.4 (locked Playwright build 1248, full Chromium
headless channel), viewport 1440 × 1080. No network/CPU throttling, thermal pinning
or background-load isolation was applied. The browser was installed only in the
task cache; no application or user-browser upgrade occurred.

Protocol SHA-256:
`e3150b1199b325e325e13c5dba3c6f851fa2448b5a7be8226ae84c305bfdacd8`.
Browser executable SHA-256:
`c8509aee32abd6977968e9999769980b7a420dea05402d90042d9e5b41db15ef`.
Frozen bundle manifest (recipes and sources, without local path) SHA-256:
`b18b90aeb704e6fc8517abf26c26c58ecc53173858e63ff42cea53ffc26bf66d`.
Host comparison fingerprint SHA-256:
`83fa7b9bed5ce3918003e73e8674410682636422e70ba66498b9d9a4891cf590`.
Canonical fixture record SHA-256:
`ae83e55189bfb8a9c86d9f1b7694481f831d0e15cf9eb95f8d04f97391f9cb5e`.
These digests use UTF-8 `JSON.stringify` of insertion-ordered objects; canonical
fixture fields/order are listed above. Full helper, UI and lockfile hashes and
installed Python library versions are retained in each raw protocol/environment
receipt. Source SHA-256 values below are the actual frozen bytes.

| Source             | Native source / display                                    | PTS seconds                    | Source SHA-256                                                     |
| ------------------ | ---------------------------------------------------------- | ------------------------------ | ------------------------------------------------------------------ |
| `oriented-vfr.mp4` | 4 frames, encoded 128 × 64, rotation 90°, display 64 × 128 | 0, .04, .12, .16               | `9f69b9d42dba07bf59d39ab8e9cb667a21c996a63bb716b760a5b4b6645137da` |
| `youtube-vfr.mp4`  | 4 frames, 128 × 64, doubles                                | 0, .04, .12, .16               | `e2512276210252ef51d4a6fc88a4b4ea67e1cb67f03ea434a52976483f30f376` |
| `long-gap-vfr.mkv` | 4 frames, 64 × 32, FFV1                                    | 0, .04, .08, .68; duration .72 | `1a006ad4c3257562f6aad192fdc813767590461046f34c34b4aed7abe4261363` |
| `rally-qa.mp4`     | 100 frames, 1000 × 600, 25 fps                             | i / 25, i = 0…99               | `2061dd5bad7193025c60f374d294525419dfe2c45309bbcea70d2b837d310c1a` |
| `pipeline-qa.mp4`  | 1300 frames, 640 × 360, 10 fps                             | i / 10, i = 0…1299             | `b3f25c62b7c946e75e07077d2623a8036210416f81863737c95eca75909a1161` |

The seek/playback scene has two synthetic players, 100 synthetic shuttle rows,
15 reviewed events at measurement time, two manual shuttle labels, one reviewed
identity interval and two review windows (including an explicitly unknown window).
The large timeline replaces its one accepted synthetic contact with exactly 1000
reviewed unknown-family/unknown-side events. These are density inputs, not truth.

Three sequential expanded runs each passed **17/17** deterministic blocks and
all frozen timing ceilings. Their protocol/harness/helper/UI/lock hashes,
canonical source/PTS records and host/browser environment match exactly.
Raw evidence names are below, relative to `.cache/evidence/`.

| Run                        | Seek + overlay p95 ms | Timeline p95 ms | Playback first advance p95 ms | rAF interval p95 ms | Overlay lag p95 seconds |
| -------------------------- | --------------------: | --------------: | ----------------------------: | ------------------: | ----------------------: |
| `frontend-baseline-3HSX1o` |                  65.7 |            36.1 |                         273.4 |                16.8 |                   .2691 |
| `frontend-baseline-yUIKgC` |                  65.7 |            37.8 |                         265.4 |                16.7 |                   .2709 |
| `frontend-baseline-VvMj6g` |                  66.2 |            36.6 |                         280.7 |                16.7 |                   .2714 |
| Median of run p95s         |              **65.7** |        **36.6** |                     **273.4** |            **16.7** |               **.2709** |

`frontend-baseline-comparison.json` contains every artifact digest, the exact
unrounded values and verified equality of protocol, source records and host.
The source bundle used for all three runs is named by their `source-bundle.json`;
it was generated without private assets using the committed helpers and is
reusable byte-for-byte as explained above. All three owned children have PID/lifetime cleanup receipts.
`review-desktop.png`, `oriented-proxy.png`, `vfr-gap.png`, `large-timeline.png`,
`oriented-pixel-comparison.json` and accessibility inventories accompany each run.
The full-page tablet capture in this Chromium contains repeated sticky viewport
tiles; it is retained as raw output and is insufficient evidence of vertical
layout. The live 768 × 1024 horizontal-fit check passes; use an ordinary viewport
capture in the fresh browser review. This phase makes no layout-conformance claim.

Observed legacy limitations are part of this baseline: playback overlay lag is
about 0.27 seconds because the viewer follows `timeupdate`; a broad manual court
still displays after adding a cut, although stale proposals are rejected; save
and accepted discard can leave keyboard focus on BODY.
[Follow-up #130](https://github.com/Ken0u/badminton-match-analyzer/issues/130)
records the bounded manual-court repair; this baseline preserves the observed
legacy behavior. Automatic court fits do
hide on camera edits, and explicit manual range expiry works. Direct FFV1 browser
playback is unsupported; exact frames and the real compatible proxy work.
CSV exports contain events and provenance but no revision column or non-event
review fields. The JSON export/evaluation report carries saved revision and
source identity. No real YouTube throughput, model inference speed, GPU work,
badminton accuracy, screen reader behavior or cross-host speedup is established.

Development receipts are retained alongside the final runs. Early failed runs
cover sandbox loopback denial, absent cached test browser, fixture driver/data
repairs and the discovered manual-court gap. No failed timing sample was removed
or accommodated by increasing a budget. The first complete intermediate
14-check run was `frontend-baseline-6IuOIL`; final runs use the expanded 17-check
suite and are the comparison baseline.
