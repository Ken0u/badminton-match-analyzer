# Badminton match analyzer

A badminton analysis app with file uploads, YouTube imports, player/shuttle tracking, and a reviewable rally and shot timeline. Complete automatic shot/rally analysis remains in development; current predictions need review.

The six target shot families are **clear, lift, net, drop, smash, and drive**, each with a separate forehand/backhand label. Serves and rally endings are separate events.

The [wrist-reach correction](docs/WRIST_REACH_REPORT.md) removes a reviewed floor-bounce contact when repeated observations of both wrists contradict player-box proximity. The [finite-wrist fix](docs/FINITE_WRIST_REPORT.md) also prevents invalid coordinates/confidence from bypassing proximity checks. Missing pose keeps the fallback available. These suggestions still require review; full contact accuracy is unverified.

The [observed-flight study](docs/OBSERVED_STROKE_CONTEXT_REPORT.md) adds guarded global flight and court-position hints for stroke learning. A controlled validation comparison improves family macro F1 from 0.556 to 0.590, while joint family/side results remain inadequate. No new model is installed. A declared independent-source evaluation remains pending after its media fetch encountered a sign-in requirement.

The [first raw-video learning evaluation](docs/R2_LEARNING_REPORT.md) is complete across 203 source rallies. Held-out weak-contact F1 is 0.790, while conditional family macro F1 is 0.498 and several requested classes fail. Neither experimental model is installed; these scores do not establish full-match correctness.

The [camera-context update](docs/EARLY_CAMERA_CUT_REPORT.md) fixes a missed early broadcast edit and preserves the complete evidence range for temporal contact features. Corrected source preparation now isolates unsupported close-ups from court views.

The [doubles data audit](docs/S2_DOUBLES_REPORT.md) adds a pinned public-label importer and an actual new-camera probe. It fixes single-stroke serve-fault exclusions and documents severe contact misses; it does not yet provide a trained doubles classifier.

The [terminal-action update](docs/TERMINAL_ACTION_REPORT.md) adds reviewable endings near calibrated court edges, recovering one public development ending while leaving its landing, line call and exact timing unverified. Missing contacts, faults/occlusions and complete-match accuracy remain open.

The [shuttle localization update](docs/SHUTTLE_LOCALIZATION_REPORT.md) preserves observed blob candidates and fixes an implausible jump to a court-logo ghost. A source-reviewed point improves from 353 px error to 1 px; missing contacts and the out-of-court ending remain unresolved.

The [contact timing update](docs/SUBFRAME_CONTACT_REPORT.md) adds between-frame and adjacent-gap review intervals with moving-wrist support and full evidence-context scene filtering. The public development rally now produces six contact proposals instead of one; substantial misses and uncertain hitter identities remain.

## Run the current application

From the project folder in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m badminton.cli serve
```

Open **http://127.0.0.1:8000**. The two supplied videos have been inspected and registered. Their first review windows have court calibration. Use another port with `serve --port 8002` if needed.

The viewer supports video playback, exact source-frame stepping, event creation/editing, per-camera court calibration, player names and handedness, annotation history, and JSON/CSV export. Save edits before exporting or starting a tracking run. Arrow keys step frames; Space toggles playback; 1/2/3 prepare a serve/shot/rally-ending event; Ctrl+S saves annotations.

For the whole video, expand **Full-match processing** and choose **Process / resume full match**. Completed stages are retained after a pause or restart; compatible tracking is reused if experimental recognition is turned off. Seek normally or choose a review window to load its overlays and proposals. Use **Use window tools** to return to separate short runs. Tracker IDs remain local to their window, and every proposed event or label needs review. CLI: `python -m badminton.cli process <video-id>`. See [the processing report](docs/FULL_MATCH_PROCESSING_REPORT.md) for validation status and remaining limits.

Use **Add a match** to upload a video or paste a YouTube video link and choose singles/doubles. Import progress and failures appear beside the form; completed videos appear in the library. Supported uploads are MP4, MOV, MKV, AVI, and WebM, limited to 2 GiB by default. Original content hashes and presentation timestamps are retained. Duplicate content preserves reviewed annotations and reuses the original source file. Some containers/codecs require exact-frame review when the browser cannot play them; playback transcoding is still pending.

YouTube support requires `pip install '.[youtube]'` and Node.js 22 or later. Public completed videos are supported; videos requiring sign-in, active streams, and playlists return an actionable error. The importer records the canonical URL, title, and channel separately from the local content ID. A real BWF rally import has been verified through download, decoding, exact-frame extraction, and HTTP media playback. Availability still depends on YouTube access from the server and downloader compatibility.

For containers, single-user authentication, persistent storage, model installation, and deployment checks, see [DEPLOYMENT.md](docs/DEPLOYMENT.md). Binding a non-loopback interface requires configured credentials or an explicit private-proxy override.

Player tracking draws tracker IDs and pose skeletons. Reviewed frame ranges map them to persistent players; contact suggestions use those mappings as hitter hints. Shuttle tracking adds a gold trajectory and visible/missing observations. Experimental singles models suggest shot families and forehand/backhand labels for review. Reviewed clips and manually marked shuttle points support reproducible reports. Automatic identity recovery, reliable serve/end detection, doubles recognition, and validated recognition on the app's YOLO inputs remain pending. See [PROJECT_PLAN.md](PROJECT_PLAN.md), [the annotation guide](docs/ANNOTATION_GUIDE.md), and [the pilot evaluation](docs/PILOT_REPORT.md).

## Fresh environment

The initial environment uses Windows, Python 3.10, and an NVIDIA GPU. Basic video review works without the tracking dependencies.

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev,youtube]'
```

For the GPU tracking environment used on this laptop:

```powershell
.\.venv\Scripts\python.exe -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu126
.\.venv\Scripts\python.exe -m pip install -e '.[dev,tracking,download,youtube,recognition]'
.\.venv\Scripts\python.exe scripts/download_models.py --kind all
```

The CUDA wheels are a large download. For a different machine, select a suitable PyTorch build using its [official installation instructions](https://pytorch.org/get-started/locally/). Inference falls back to CPU when CUDA is unavailable. Large pretrained weights and generated data stay outside Git; the download script records and checks each checkpoint's SHA-256. The small project-trained side head and its training report are packaged under `backend/badminton/assets/`. The vendored TrackNet and BST models include their upstream MIT licenses and pinned source manifests.

`requirements.lock` records the verified Windows/Python 3.10/CUDA environment. Recreate that exact environment with `python -m pip install -r requirements.lock` after creating the virtual environment. The lock includes the optional tracking and test packages.

## Inspect and register videos

Place videos inside the project folder, then import from the sidebar or run:

```powershell
.\.venv\Scripts\python.exe -m badminton.cli ingest singles.mp4 --mode singles
.\.venv\Scripts\python.exe -m badminton.cli ingest doubles.mp4 --mode doubles
.\.venv\Scripts\python.exe scripts/seed_sample_calibrations.py
```

Ingestion decodes all video frames once, stores their actual presentation timestamps, creates a sparse contact sheet, and registers a content hash. Re-importing preserves annotations. The calibration seeding script is specifically for these two sample files and does not create shot labels.

Both samples are edited highlights, with replay angles and close-ups. The initial experiments use inspected full-court windows at **80–90 seconds in singles** and **24–34 seconds in doubles**. Camera/replay segmentation remains necessary before automatic analysis of the complete highlights.

## Run the player baseline

In the viewer, seek to a suitable full-court section and choose **Track players**. Saved court calibration filters detections to the playing area. **Find court automatically when needed** is enabled by default: supported visible markings produce an unreviewed, dashed court overlay for uncovered camera views. Ambiguous or changing views stay uncalibrated. Manual corners take priority; automatic fits never save annotations. Disable the checkbox, send `auto_calibrate: false` to the tracking API, or pass `--no-auto-court` in the CLI to opt out. A background job reports progress; completed results are loaded as overlays. See [the court report](docs/AUTOMATIC_COURT_REPORT.md) for development evidence and limits.

The equivalent CLI experiments are:

```powershell
.\.venv\Scripts\python.exe -m badminton.cli track 970dbd8adfe548d8 --start 80 --duration 10
.\.venv\Scripts\python.exe -m badminton.cli track c406a1187130b845 --start 24 --duration 10
```

Standard player tracking uses pinned `yolo11s-pose.pt` and ByteTrack. Choose Lightweight in the viewer or `--player-model nano` on track/download commands for `yolo11n-pose.pt`. Both checkpoints are verified by SHA256 before loading. Results retain boxes, keypoints, confidence, source frame/time, actual model/device, speed and court snapshot. Tracker IDs are separate from persistent players. Runs are limited to two minutes.

After tracking players and the shuttle at every frame in a calibrated view, choose **Suggest rally boundaries**. Experimental serve/end intervals open as drafts; inspect the source, add and save explicitly. Hitter identity stays unknown. Missing candidates do not establish that no rally occurred. Camera, scene or court edits invalidate affected cached proposals. See [the rally proposal report](docs/RALLY_PROPOSAL_REPORT.md) for actual outputs, tests and accuracy limits.

```powershell
.\.venv\Scripts\python.exe -m badminton.cli rallies VIDEO_ID --players-run PLAYER_JOB_ID --shuttle-run SHUTTLE_JOB_ID
```

The first runs processed both 250-frame windows at about 23 frames per second. The model input size is 1280 because the initial 640-size run missed the far singles player. See [the baseline report](docs/BASELINE_REPORT.md) for observations and limitations.

## Shuttle tracking and contact review

Choose **Track shuttle** for the same window. This uses the official TrackNetV3 checkpoint with eight-frame overlapping predictions. A gold dot/trail shows raw detections; gaps remain missing. The current local baseline processes approximately 8–9 source frames per second on these samples.

```powershell
.\.venv\Scripts\python.exe -m badminton.cli track 970dbd8adfe548d8 --stage shuttle --start 80 --duration 10
.\.venv\Scripts\python.exe -m badminton.cli track c406a1187130b845 --stage shuttle --start 24 --duration 10
```

Then choose **Suggest contacts**. If a player run covers the window, suggestions include nearby temporary track IDs. Click a suggestion, inspect the surrounding frames, choose the rally/hitter/family/side, and add/save the event. Its original proposal remains linked in exported data. Suggestions do not modify annotations automatically and do not establish contact-detection accuracy. Use `unknown` for labels the footage cannot resolve.

**Use audio support** is an experimental, default-off option requiring player tracking over the window. It adds uncertain review intervals only when a sound onset also has shuttle-gap and moving-wrist evidence. Crowd/shoe sounds can produce false proposals; missing audio leaves visual suggestions available. API: add `include_audio: true` to the contacts request. [The audio report](docs/AUDIO_CONTACT_REPORT.md) records the development comparison and timing limitations. [The direct-video report](docs/DIRECT_VIDEO_REPORT.md) records the separate public-source YOLO/recognition probe and remaining alignment work.

Short occlusions may produce **Review possible contact** cards with a frame range supported by trajectory and wrist evidence. Their navigation frame is an estimate. Review the entire interval; saved events retain editable inclusive timing bounds. Clear those bounds only after identifying the contact frame. The detector filters smooth apexes, preserves raw gaps, and still misses some hits. See [the contact report](docs/CONTACT_DETECTION_REPORT.md).

For an obscured terminal moment, select **Rally end** and expand **Rally end timing uncertainty**. Keep inclusive earliest/latest source frames containing the event's navigation frame; a final racket contact alone does not establish the ending. Bounds survive editing, history, and JSON/CSV export. [The first boundary audit](docs/RALLY_BOUNDARY_REPORT.md) records source-reviewed opening/terminal intervals for the first full-court view in each sample, with unresolved timing and human adjudication pending. It does not establish automatic serve/end detection or exhaustive shot truth.

The equivalent API is `POST /api/videos/<id>/track` with `stage: "players"` or `"shuttle"`, followed by `POST /api/videos/<id>/contacts` with `shuttle_run_id` and optional `player_run_id`. All processing jobs, including CLI ingestion, share admission control within the project database.

## Experimental singles shot labels

After tracking both players and the shuttle on every frame of the same calibrated window, choose **Suggest shot labels**. The BST-0 checkpoint uses a centered one-second pose/shuttle clip around saved reviewed shots and contact proposals. Missing context, camera cuts, or insufficient observations produce an abstention. A separate small head proposes forehand/backhand for confident target-family results, using the predicted hitter court end. Select a result to load an editor draft, inspect the footage, correct the family/hitter/timing/side, then update and save. Inference never saves labels automatically. Existing manually entered stroke sides are preserved. An unknown side is filled only when its reviewed hitter mapping agrees with the suggestion; conflicting or unresolved hitters keep it unknown in the editor.

Install the `tracking,recognition` extras and fetch `scripts/download_models.py --kind stroke` (also included in `--kind all`). The CPU/GPU container targets include these dependencies. The review target keeps working without PyTorch. API: `POST /api/videos/<id>/recognize` with `player_run_id`, `shuttle_run_id`, and optional matching `contacts_run_id`. CLI example using the cached sample runs:

```powershell
.\.venv\Scripts\python.exe -m badminton.cli recognize 970dbd8adfe548d8 --players-run b8bdae17e8374a20bbf16f554c551f19 --shuttle-run ad0696c19b4b4be0beddf592a641cca0 --contacts-run 1f287c4134aa4633ad694d33c2ce9b42
```

Scores are uncalibrated model rankings. Both models transfer published MMPose features to the app's YOLO poses, and direct-video recognition accuracy remains unvalidated. On a filtered published-feature test subset, family macro F1 is 0.827 and the side head's closed-set balanced accuracy is 0.942 with known hitter court end. These component results do not establish uploaded-video accuracy. [The side-training report](docs/STROKE_SIDE_REPORT.md) includes coverage, strict misses, rare-class support, and the 0.718 conditional family/court-end/side tuple result. The app supports singles recognition only; complete rally annotations remain unfinished.

## Reviewed identities and accuracy

Expand **Camera changes** and choose **Scan camera changes** for a full-video list of possible edits. Click a candidate and step across the source frames to inspect it. New tracking runs automatically separate detected views: player IDs reset into disjoint ranges, shuttle windows/backgrounds are separate, and old court calibration expires after a detected cut. Confirm the court again for each view. Camera cuts do not imply rally boundaries or identify replays. Older tracking artifacts need rerunning to gain this behavior. CLI: `python -m badminton.cli segments <video-id>`; API: `POST /api/videos/<id>/segments`. [The camera report](docs/CAMERA_BOUNDARY_REPORT.md) records the sample/GPU checks and detection limits.

Use the same panel to confirm/reject a detected cut or add a missing cut. Save corrections before processing; affected cached tracking must be rerun when its effective boundaries change. Physical timestamp gaps cannot be joined. Add non-overlapping scene ranges with an exclusive end frame after inspecting the entire interval. Reviewed replay, non-play, and explicitly unknown ranges suppress contact/shot suggestions; live status does not certify that every contact has been labeled. Removing a range restores the raw perception view; request new contacts and shot labels to recover previously omitted suggestions. Original predictions, other labels, revision history, and JSON exports are preserved. [The scene-review report](docs/SCENE_REVIEW_REPORT.md) records the source-verified intro labels, correction tests, and remaining automatic scene-classification work.

Expand **Assign tracks to players** to map a loaded run's tracker to A/B/C/D for a reviewed source-frame range. Mapping ranges include the start and exclude the end. Confirm crossings and end changes; mappings never extend into another run automatically. Removing a mapping clears that identity from the overlay and future hints without changing saved events or raw model artifacts.

In **Reviewed clips & accuracy**, record a continuous clip, its live/replay status, and whether **every contact** is labeled. Inspect the full interval and add missed contacts before checking completeness. Contact scoring uses only complete live clips fully covered by the selected run. Unknown scenes, replays, incomplete clips, and unlabeled parts of the video are excluded explicitly.

Mark shuttle positions on separate exact source frames, or label the shuttle not visible. Marking a position hides the model trajectory; ambiguous frames can remain unlabeled. Cyan crosshairs show saved review points. **Measure saved labels** reports precision, recall, F1, and sample counts. Download the JSON report for matching errors, coverage, tolerances, source hashes, run IDs, and annotation revision. Wrong shuttle localization counts as both a false detection and a miss; missing output never earns a correct-absence result.

When a recognition run is loaded, **Measure saved labels** also reports per-family errors, abstention coverage, stroke-side results, and complete-event F1 where independent labels exist. Classifier-assisted labels are excluded to prevent self-evaluation. Missing family truth yields unavailable metrics. A supported-class average with fewer than six represented families is not a six-family benchmark. Recognition results are conditional on supplied contacts and reviewed track-player mappings, rather than unattended video accuracy.

The equivalent API is `POST /api/videos/<id>/evaluate` with optional `contacts_run_id`, `shuttle_run_id`, and `recognition_run_id` (at least one required). CLI usage:

```powershell
.\.venv\Scripts\python.exe -m badminton.cli evaluate 970dbd8adfe548d8 --contacts-run 70357b1ea6ca48288dacfea0a02c65ba --shuttle-run ad0696c19b4b4be0beddf592a641cca0 --output .cache/singles-evaluation.json
```

Run IDs above refer to the cached local experiments. Use the IDs returned by your jobs after rerunning models. The small development pilot is recorded in `data/manifests/pilot_review.json`; [the pilot report](docs/PILOT_REPORT.md) describes its evidence, limits, and reproducible import command.

## Public stroke labels

The pinned ShuttleSet importer creates a separate local label index for recognition training and evaluation. It preserves original rows, source frames/times, subtype labels, and player identities; applies published quality exclusions; and freezes splits by original match. It does not populate the app's annotations or certify video alignment.

```powershell
.\.venv\Scripts\python.exe scripts/fetch_shuttleset.py
.\.venv\Scripts\python.exe -m badminton.cli import-shuttleset data/datasets/shuttleset/source --output data/datasets/shuttleset/v2
.\.venv\Scripts\python.exe -m badminton.cli evaluate 970dbd8adfe548d8 --recognition-run 69bf12fd32c74b359b9cb4bfcf6866d7 --output .cache/recognition-evaluation.json
```

[The data/evaluation report](docs/STROKE_DATA_REPORT.md) describes the actual imported counts, side-label convention, known-error quarantine, FPS discrepancies, evaluation gates, and required footage alignment. Raw public labels and videos stay outside Git.

Mapping v2 preserves legitimate single-stroke terminal serves; the original side-head report and feature recipe use their unchanged v1 index. Importers refuse to overwrite an existing output directory with different source, mapping or split provenance. Keep new experiments in separately named directories. [The doubles audit](docs/S2_DOUBLES_REPORT.md) provides the additional doubles commands and current data limits.

The [FineBadminton source audit](docs/FINEBADMINTON_REPORT.md) adds a pinned
singles action/side index with 20,757 records and a separate exact join to 414
published contact-frame references. Action intervals never become contact times
or rally endings. Raw labels, missing fields and cross-publication discrepancies
remain visible; training readiness and match splits require separate verification.

```powershell
.\.venv\Scripts\python.exe -m badminton.cli import-finebadminton LOCAL_SOURCE_DIR --output data/datasets/finebadminton/v1
```

The report specifies the two pinned source publications and expected local file
layout. No dataset video, automatic download or new model is bundled.

## Storage

```text
data/manifests/                 Sample provenance and inspected windows (tracked)
data/processed/catalog.sqlite3  Video catalog, annotation revisions, and jobs
data/processed/<video-id>/      Timestamp map, audit images, and tracking runs
data/datasets/                 Pinned public source labels and normalized indexes
models/weights/                Locally downloaded model files
```

Annotations use optimistic revisions: stale saves are rejected rather than overwriting edits from another window. Revisions are retained in SQLite and accessible through `/api/videos/<id>/revisions/<revision>`. JSON exports contain video metadata and the saved annotation document. CSV exports contain one row per event, including proposal provenance where applicable. Recovery marks jobs from stopped workers as interrupted and preserves live workers in other instances. Retry interrupted clips explicitly. A changed source file must be imported again before analysis.

## Checks

```powershell
New-Item -ItemType Directory -Path .cache -Force | Out-Null
.\.venv\Scripts\python.exe -m pytest -q --basetemp .cache/pytest
.\.venv\Scripts\ruff.exe check backend tests scripts
```

[The decoder reliability report](docs/DECODER_SHUTDOWN_REPORT.md) records the native threaded-shutdown fix and source-video checks. Media contexts retain native FFmpeg diagnostics and complete vision-library initialization before player decoding.

The real-checkpoint GPU test is opt-in and uses an isolated database:

```powershell
$env:BADMINTON_GPU_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest -q tests/test_gpu_integration.py --basetemp .cache/pytest-gpu
Remove-Item Env:BADMINTON_GPU_TESTS
```

Browser checks use an isolated database and the real sample media. In one terminal:

```powershell
.\.venv\Scripts\python.exe scripts/ui_test_server.py
```

In another terminal:

```powershell
npm ci
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) '.cache\ms-playwright'
npx playwright install chromium
npm run test:ui
npm run test:recognition
```

These checks exercise playback, exact-frame images, event correction/export, reviewed identities, clip completeness, shuttle marking, camera/scene corrections, accuracy reports, switching, and responsive layout. The review-tools check requires cached player/shuttle/contact runs for both samples and is restricted to the isolated server on port 8001. Screenshots go to `data/processed/qa/`. The isolated QA annotations are illustrative test events, not badminton ground truth.

