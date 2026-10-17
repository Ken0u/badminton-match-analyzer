# Bug review and implementation progress

Reviewed October 17, 2026. Fixes are implemented, with the checks listed below.

The latest increment adds an experimental pretrained singles family model through
the CLI, API, and explicit review UI. [The recognition report](SHOT_RECOGNITION_REPORT.md)
records the source mapping, seven-target CUDA smoke run, abstention behavior,
and missing accuracy evidence. It does not predict stroke side or support doubles.
New regressions cover mismatched input lineage, missing context/cuts, duplicate
targets, invalid classification provenance, and stale scores after contact/label
changes. Hitter views now use the current reviewed identity mapping instead of
retaining an old recognition hint. Video switching immediately disables the
recognition button until the selected video's runs load. Existing manual
forehand/backhand values survive loading a suggestion; raw artifacts and real
pilot annotations are unchanged.

Current local checks: **237 backend tests passed**, two optional GPU tests skipped
in the standard run; both opt-in CUDA tests passed separately. All three existing
browser suites and the new real-model recognition browser suite pass. Lint,
formatting, dependency consistency, and the built wheel's model/license/UI contents
were checked. Container checks remain part of the feature PR's CI.

Source-contract review also caught inconsistent hitter hints when the highest
individual source class belonged to a different family than the winning summed
family. Hitter court end now uses probability mass within the selected family;
tied court ends remain unknown. A targeted regression covers that disagreement.

The input/deployment increment adds bounded file uploads, YouTube imports, single-user authentication, persistent container configuration, and CI. [The import verification report](IMPORT_VERIFICATION.md) records an actual BWF YouTube-to-frame/playback API test. Import regressions caught a content-ID overwrite risk from publisher metadata and provenance loss on local-path re-import; publisher metadata is now nested and re-import retains it. Duplicate imports preserve reviewed revisions and do not accumulate duplicate source files. Shutdown admission failure also releases its job claim.

Additional input bugs fixed: rotated phone footage now uses one display orientation for browser-aligned review and CV coordinates; source bytes and timestamps remain unchanged. Download progress accumulates small updates until a visible update is due instead of staying at zero. Generated MP4 orientation tests and a Chromium comparison cover the rotation path. CI also exposed fresh-checkout directory and installed-package root assumptions; fixture paths and test setup now make those boundaries explicit.

Latest increment: reviewed identity mappings, clip completeness, manual shuttle labels, and contact/localization evaluation now work through the UI and API, with a CLI evaluator. Eight visually reviewed development contacts and six identity mappings are saved at annotation revision 2 across the two samples. See [the pilot report](PILOT_REPORT.md) for measured failures and remaining labeling work.

Two additional artifact bugs were found and fixed during this increment: player assignments could accept an artifact whose internal video or stage contradicted its completed job, and evaluation could return a server error for that mismatch. Both now return actionable validation errors. The editor also preserves `corrected` status across repeated edits.

Review/evaluation milestone checks: **84 standard backend tests passed**, with one optional GPU test skipped and both original browser suites passing. Subsequent import and contact increments add their focused regressions and CI checks; see their reports for current evidence.

Contact detection now handles supported short gaps as uncertain proposals and rejects smooth apex curvature. Timing bounds persist through review/export, and unresolved reviewed intervals cannot be used as exact evaluation labels. [The contact report](CONTACT_DETECTION_REPORT.md) records the unchanged pilot comparison: the false apex is removed, one additional hit is covered by an interval, and two hits remain missed.

| Confirmed issue | Resulting fix | Verification |
| --- | --- | --- |
| CLI analysis and web jobs used different admission controls, allowing concurrent workers. CLI ingestion was also uncoordinated. | All CLI/web processing uses an atomic SQLite job claim shared by project instances. | Two competing stores admit exactly one worker. |
| Constructing another app instance marked live jobs as interrupted. | Recovery checks the worker PID and process creation time; live workers survive another instance starting. Recovery updates run inside a transaction. | Live-worker recovery and stale process-lifetime regression checks. |
| Job updates used `INSERT OR REPLACE`, changing row order whenever progress changed. | Updates preserve the original job row, so the newest run means the newest submitted run. | Shared-job workflow exercised through CLI, API, and browser. |
| The calibration flag was true whenever any calibration existed, even outside the selected window. | Results count calibrated frames inside the processed range and report complete coverage only when all processed frames are covered. | A clip outside an existing calibration reports zero calibrated frames. |
| Replacing a video after ingestion could silently misalign saved frames and tracks with different footage. | Source hashes are checked and cached against file size/mtime; changed sources return a clear conflict before playback/frame extraction/processing. | Changed-file API regression checks. |
| Nonfinite CLI times could create empty or invalid analysis ranges. | CLI and API ranges use shared timestamp-based validation; NaN/infinite CLI arguments are rejected. | Finite-range and VFR checks. |
| A pending save could respond after a video switch and affect the newly loaded document. | Switching waits for an in-flight save to finish. New edits made during the save remain unsaved and preserved. Tracking-result responses also check the selection generation. | Browser delayed-save/switch and delayed-response checks. |
| Duplicate serve/shot contacts or the same accepted proposal could be saved more than once. | Contact-frame uniqueness and proposal provenance are validated. | Schema regression checks and browser proposal acceptance/export. |
| Ingestion wrote timestamp JSON directly, allowing a reader to encounter a partial file. | Timestamp maps and result artifacts are replaced atomically. | Ingestion, re-import, and frame-access workflows pass. |
| A completed job with a missing run file returned an internal server error. | Run and contact endpoints return a recoverable not-found response and a rerun instruction. | Missing-artifact API regression check. |

Player-model cleanup now runs on failures as well as success. Media responses infer the container MIME type. Unsupported/missing video frames display an actionable viewer error.

## New processing capability

Added the official TrackNetV3 model architecture and checkpoint, with the upstream MIT license, pinned source commit, and SHA-256 provenance. The adapter uses actual source timestamps, a bounded background sample, eight-frame overlapping windows, and raw shuttle heatmap observations. Missing positions remain null. It does not interpolate or repair trajectories.

| Inspected window | Source frames | Visible detections | Processing time | Throughput | Contact proposals |
| --- | --- | --- | --- | --- | --- |
| Singles, 80–90 s | 250 | 227 | 30.449 s | 8.21 frames/s | 8 |
| Doubles, 24–34 s | 250 | 211 | 28.819 s | 8.67 frames/s | 9 |

The model used CUDA with float16 inference and peaked at approximately 385 MB of PyTorch-allocated GPU memory; this excludes driver/library memory. The timings cover background estimation, decoding, inference, and processing-loop progress writes, and exclude loading the model. These are measurements of the selected local windows.

The visible counts are **model outputs, not localization accuracy**. Sampled annotated frames were inspected visually. Some fast or occluded shuttles are missed. The sparse visual inspection is not a labeled evaluation dataset.

Contact suggestions combine changes in shuttle motion with nearby player boxes/wrists. Track IDs are hints, with persistent hitter identity and stroke labels left unknown. Scores are heuristic ranking scores, not calibrated probabilities. False proposals and missed hits remain possible. The viewer requires explicit review/add/save before a suggestion becomes an annotation; its source run and candidate ID remain in JSON/CSV exports.

## Checks completed

- 17 standard backend tests pass.
- The opt-in real-GPU API test passes, including a five-frame clip shorter than the eight-frame model window, exact source timestamps, padding, and no automatic annotation edits.
- Browser checks pass for video/frame review, saved edits, conflict-sensitive workflows, court calibration, singles/doubles switching, and contact proposal review/export. The optional proposal check uses cached real analysis runs when available.
- Both full 250-frame shuttle experiments completed on the local GPU. Player and shuttle overlays and the proposal panels were inspected visually.
- Python lint, frontend formatting, and dependency consistency checks pass.

The first small partial-rally pilot, evaluator, and reviewed player-to-track assignments are implemented. Contact recall on that singles pilot is poor, so the next milestone is better contact detection plus a larger, independently reviewed set of complete rallies. A pretrained singles family baseline now exists, but held-out family evaluation, automated serve/end detection, stroke-side prediction, doubles recognition, automatic identity recovery, and full-highlight replay/camera segmentation remain pending. All real pilot family/side labels remain unknown.

