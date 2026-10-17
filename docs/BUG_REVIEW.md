# Bug review and implementation progress

Reviewed October 17, 2026. Fixes are implemented, with the checks listed below.

The terminal-action increment removes an incorrect in-court-only ending gate:
a true shuttle can settle beside a sideline. The bounded surround retains every
existing motion, visibility and quiet-player requirement. The public development
excerpt now proposes end 319 [316,330], with line call and exact landing unverified;
original first views and partial pilots are unchanged. [The report](TERMINAL_ACTION_REPORT.md)
records 481 passing standard tests, real cached-input API and generated browser
checks. Missing contacts, faults and the original doubles ending remain open.

The shuttle-selection increment fixes a verified jump to a stationary court-logo
component even though the true shuttle is present as a smaller observed blob.
Source-time reachability selects a unique plausible alternative while retaining
all raw component evidence. Full transitive history now controls scene exclusions
and downstream contact/rally/recognition inputs. [The report](SHUTTLE_LOCALIZATION_REPORT.md)
records the 353-to-1-pixel development example, unchanged original excerpts,
460 passing standard tests, a real GPU API check and generated browser coverage.
The missing contacts and outside-sideline ending remain open.

The contact-timing increment fixes a sampled-frame assumption that rejected
between-frame transitions, and short gaps no longer require consecutive immediate
observations on both sides. Profiled proposals carry uncertain timing and leave
ambiguous hitters unknown. [The report](SUBFRAME_CONTACT_REPORT.md) records actual
one-to-six public-rally output, controlled negatives, remaining misses and the
unvalidated accuracy limits. Source/scene guards also cover complete evidence
windows in the editor, recognition and evaluation. Excluded context does not
erase valid gold events from metrics. 439 standard tests pass, plus real-sample
and generated-media browser checks; no reviewed main labels were changed.

The doubles source audit found a concrete normalization bug: a one-stroke serve
fault carries terminal phase 3, but the existing importer rejected that serve.
Mapping version 2 preserves the serve and terminal roles, recovering 17 otherwise
eligible ShuttleSet rows without changing old indices or models. The new doubles
importer also handles nine such rows and preserves unknown timing/side semantics.
[The audit](S2_DOUBLES_REPORT.md) records the pinned labels and an actual public
source excerpt. At that increment, v2 native contact inference found only one
proposal against 13 published references; timing is not yet adjudicated. Missing
observations and the abrupt-fit gate are concrete next targets, alongside out-shot endings.
Current checks: 400 standard tests passed with four unchanged opt-in GPU tests
skipped, plus actual CUDA processing of the new 390-frame source excerpt and
both real label-import CLI paths. The new wheel preserves existing tracking,
decoder and model-asset bytes; source/mapping/split overwrite guards are tested.

The rally increment adds experimental serve/end proposals and pinned standard/
lightweight pose selection. [The report](RALLY_PROPOSAL_REPORT.md) records actual
outputs and missing boundaries. A variable-rate timing regression caught a
pose-lag lookup that shortened quiet-motion windows; source PTS now controls the
lag. Isolated shuttle jumps cannot supply sustained launch evidence. Scene,
camera and court edits invalidate proposal context, including unsaved drafts;
new player runs preserve court snapshots and reject stale geometry. Current
checks:379 standard tests passed,4 optional CUDA checks passed separately,
plus generated-media boundary browser checks. Real labels remain unchanged.

The preceding native run found a decoder-shutdown deadlock after its final frame.
Two native traces confirmed a main thread waiting for FFmpeg teardown while a
decoder worker waited for the Python logging callback's GIL. Torchvision can
install that callback during lazy initialization. Managed media contexts now
restore FFmpeg's native callback before opening/closing; player tracking finishes
vision-library initialization before any decoder starts. This preserves threaded
source decoding and prevents this callback/teardown cycle.

[The decoder report](DECODER_SHUTDOWN_REPORT.md) records the reproduced failure,
completed 114-frame CUDA rerun, and actual full-view perception findings. Current
checks: **340 standard tests passed**, two optional GPU tests skipped and passed
separately, plus fresh generated-media browser checks. Native diagnostic/error
behavior and repeated threaded seek/early-close have bounded subprocess
regressions. The opt-in recognition fixture now compares candidate IDs/counts
with actual in-range shot targets, preserving newly saved serves/endings.

The latest source audit exposed an annotation gap: an occluded rally ending could
only be saved as an exact frame plus free-text notes. The editor and contract now
preserve separate inclusive terminal bounds for rally endings. Those bounds
survive reload, edits, history, and JSON/CSV export; invalid/mixed contact and
terminal intervals are rejected. Changing event kind clears draft timing so a
racket-contact interval cannot silently become terminal timing.

[The boundary report](RALLY_BOUNDARY_REPORT.md) records four source-only opening/
ending intervals, with unresolved timing and human adjudication pending. It does
not certify every intervening contact or an automatic rally detector. Current
standard checks: **338 tests passed**, with the two optional CUDA checks skipped;
this increment changes annotation contracts/UI and no model inference math.
Generated-media browser checks exercise terminal add/reload/clear/history/kind
changes and duplicate-import preservation.

The reviewed-scene increment adds editable camera corrections and half-open
live/replay/non-play/unknown ranges. [The scene report](SCENE_REVIEW_REPORT.md)
records the source-verified 250-frame intro review and an isolated real CUDA
override probe. Raw model artifacts and reviewed events remain intact. Changed
effective boundaries require new tracking; masked scenes suppress contact and
recognition suggestions and conflicting exhaustive evaluation windows.

The bug review fixed two reversible-view issues: applying a review twice could
clear an already-stale tracking flag, and removing a scene override could discard
the original scene evidence. Staleness now remains latched until tracking is
rerun, and removing an override restores its original scene value. Benchmark
helpers now use the same scene masks and stale-input guards as the app. Browser
fixtures regenerate proposals to avoid depending on a previous test's filters.

Current standard checks: **329 backend tests passed**, two opt-in GPU tests
skipped and passed separately. Camera/scene browser checks cover draft masks,
overlap validation, save/history/export preservation, stale-input rejection,
and editing/removing corrections. The source scenes are a first visual pass,
not adjudicated event truth. Automatic live/replay classification, full-rally
evaluation, and full-match correctness remain unproven.

The preceding increment adds queued full-video camera scans and separates new
tracking runs at detected edits. [The camera report](CAMERA_BOUNDARY_REPORT.md)
records 65/69 candidate cuts on the samples, six inspected transition pairs, and
an 80-frame CUDA probe across two edits. ByteTrack IDs no longer collide after
reset, TrackNet backgrounds/windows stay within each detected view, and stale
court calibration expires. Contacts now honor player-run cuts as well as shuttle
cuts. These are camera/timestamp boundaries, not replay or rally labels.

Browser inspection found a source-review mismatch while seeking: the old image
could remain visible with the newly selected frame number. A loading cover now
hides that stale view until the requested exact source image arrives. A delayed
request regression checks both the pending and loaded states.

Current local checks: **313 backend tests passed**, two opt-in GPU tests skipped
in the standard suite and passed separately. Browser checks include full-video
boundary navigation and generated two-view upload media for CI. Source hashes,
VFR timestamps, incomplete decoding, artifact lineage, shared job admission,
tracker reset, short temporal segments, and calibration renewal are covered.
Independent cut accuracy, scene corrections/live-replay recognition, and the full
automatic match pipeline remain open.

The preceding increment probes the actual public-source video through YOLO,
TrackNet, and recognition. Both diagnostic windows abstain, and contact alignment
remains unverified; the cached-feature benchmark must not be presented as
raw-video accuracy. [The direct-video report](DIRECT_VIDEO_REPORT.md) records
the source lineage, timing ambiguity, and actual CUDA artifacts.

An opt-in audio/vision contact aid adds uncertain intervals containing the two
previously missed singles pilot labels, with no reviewed labels changed.
[The audio report](AUDIO_CONTACT_REPORT.md) records the four-contact development
comparison, tighter timing results, doubles false-positive concern, and why audio
remains default-off. Duplicate sounds near the same shuttle gap now share one
proposal; conflicting hitter evidence cannot replace the visual hint. Audio
decoding preserves the video's time origin and splits missing/discontinuous PTS.
Missing audio falls back to visual suggestions; changed source bytes still fail.

Previous increment's checks: **299 backend tests passed**, two opt-in GPU tests skipped
in the standard suite; both pass separately. The new source probe ran on CUDA;
all four browser suites pass, including the optional audio request and review
intervals. Source timing, complete-rally labels,
YOLO-domain recognition quality, and full-video correctness remain open.

The preceding increment trains and packages an experimental forehand/backhand head
from pinned published MMPose features. [The side report](STROKE_SIDE_REPORT.md)
records its 12,520 usable clips, frozen split/selection protocol, confidence
coverage, rare-class gaps, and much lower conditional family/hitter/side result.
The editor preserves an existing manual side even when the model disagrees and
does not apply another hitter's side suggestion. Family logits are unchanged by
descriptor capture; all seven cached singles family outputs matched exactly.

New regressions cover archive traversal/links, altered feature bytes, duplicate
joins, match leakage, train-only normalization, nonfinite inputs, partial model
installs, and checkpoint-pointer traversal. Training now writes a versioned model
before committing its metadata pointer and shares processing admission with the
app. A packaged CPU-loadable 161 KB head makes new installations usable without
requiring the full training dataset.

Previous increment's local checks: **269 backend tests passed**, two opt-in GPU tests skipped
in the standard run; both real GPU checks passed separately, and all four browser
suites passed. Direct-video alignment and YOLO-domain recognition accuracy remain
unverified; these checks do not establish full-match correctness.

The data/evaluation increment adds a source-verified ShuttleSet label index and
recognition metrics that exclude classifier-assisted labels. Tests cover the
risk of accepting a model draft and then reporting it as correct ground truth;
that event is now explicitly excluded from recognition accuracy. Abstentions
remain misses in supported-class and complete-event metrics. Unrepresented
families never receive an invented six-class macro score. Published known-error
records quarantine whole affected rallies; original labels remain intact.
The source snapshot contains both 25- and 30-fps evidence, so the importer keeps
source frame/time references and leaves media alignment unverified. See
[the data report](STROKE_DATA_REPORT.md) for counts, conventions, and remaining work.

Latest local checks: **259 backend tests passed**, with two optional GPU tests
skipped; all four local browser suites passed, including recognition metrics and
exclusion of classifier-assisted labels. The previous increment's real GPU
inference checks remain applicable; this change adds no model/inference math.

The first family-model increment added an experimental singles baseline through
the CLI, API, and explicit review UI. [The recognition report](SHOT_RECOGNITION_REPORT.md)
records the source mapping, seven-target CUDA smoke run, abstention behavior,
and missing accuracy evidence. That original version predicted family only;
doubles recognition remains unsupported.
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
| Singles, 80Ã¢â‚¬â€œ90 s | 250 | 227 | 30.449 s | 8.21 frames/s | 8 |
| Doubles, 24Ã¢â‚¬â€œ34 s | 250 | 211 | 28.819 s | 8.67 frames/s | 9 |

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

