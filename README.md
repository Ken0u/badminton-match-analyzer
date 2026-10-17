# Badminton match analyzer

A local workspace for inspecting badminton videos, tracking players and the shuttle, and creating reviewed rally and shot annotations.

The six target shot families are **clear, lift, net, drop, smash, and drive**, each with a separate forehand/backhand label. Serves and rally endings are separate events.

## Run the current application

From the project folder in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m badminton.cli serve
```

Open **http://127.0.0.1:8000**. The two supplied videos have been inspected and registered. Their first review windows have court calibration. Use another port with `serve --port 8002` if needed.

The viewer supports video playback, exact source-frame stepping, event creation/editing, per-camera court calibration, player names and handedness, annotation history, and JSON/CSV export. Save edits before exporting or starting a tracking run. Arrow keys step frames; Space toggles playback; 1/2/3 prepare a serve/shot/rally-ending event; Ctrl+S saves annotations.

Player tracking draws tracker IDs and pose skeletons. Reviewed frame ranges map them to persistent players; contact suggestions use those mappings as hitter hints. Shuttle tracking adds a gold trajectory and visible/missing observations. Reviewed clips and manually marked shuttle points support reproducible accuracy reports. Automatic identity recovery, serve/end detection, and stroke classification remain pending. See [PROJECT_PLAN.md](PROJECT_PLAN.md), [the annotation guide](docs/ANNOTATION_GUIDE.md), and [the pilot evaluation](docs/PILOT_REPORT.md).

## Fresh environment

The initial environment uses Windows, Python 3.10, and an NVIDIA GPU. Basic video review works without the tracking dependencies.

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
```

For the GPU tracking environment used on this laptop:

```powershell
.\.venv\Scripts\python.exe -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu126
.\.venv\Scripts\python.exe -m pip install -e '.[dev,tracking,download]'
.\.venv\Scripts\python.exe scripts/download_models.py --kind all
```

The CUDA wheels are a large download. For a different machine, select a suitable PyTorch build using its [official installation instructions](https://pytorch.org/get-started/locally/). The tracking code falls back to CPU when CUDA is unavailable. Model files and generated data stay outside Git; the download script records and checks each checkpoint's SHA-256. The vendored TrackNet model includes its upstream MIT license and pinned source manifest.

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

In the viewer, seek to a suitable full-court section and choose **Track players**. Saved court calibration filters detections to the playing area. A background job reports progress; completed results are loaded as overlays.

The equivalent CLI experiments are:

```powershell
.\.venv\Scripts\python.exe -m badminton.cli track 970dbd8adfe548d8 --start 80 --duration 10
.\.venv\Scripts\python.exe -m badminton.cli track c406a1187130b845 --start 24 --duration 10
```

This baseline uses the publisher's `yolo11n-pose.pt` checkpoint and ByteTrack. Results include bounding boxes, keypoints, confidence, source frame/time, model/device, processing speed, and the calibration revision. Tracker IDs are intentionally separate from the annotation's persistent player IDs. Initial runs are limited to two minutes.

The first runs processed both 250-frame windows at about 23 frames per second. The model input size is 1280 because the initial 640-size run missed the far singles player. See [the baseline report](docs/BASELINE_REPORT.md) for observations and limitations.

## Shuttle tracking and contact review

Choose **Track shuttle** for the same window. This uses the official TrackNetV3 checkpoint with eight-frame overlapping predictions. A gold dot/trail shows raw detections; gaps remain missing. The current local baseline processes approximately 8–9 source frames per second on these samples.

```powershell
.\.venv\Scripts\python.exe -m badminton.cli track 970dbd8adfe548d8 --stage shuttle --start 80 --duration 10
.\.venv\Scripts\python.exe -m badminton.cli track c406a1187130b845 --stage shuttle --start 24 --duration 10
```

Then choose **Suggest contacts**. If a player run covers the window, suggestions include nearby temporary track IDs. Click a suggestion, inspect the surrounding frames, choose the rally/hitter/family/side, and add/save the event. Its original proposal remains linked in exported data. Suggestions do not modify annotations automatically and do not establish contact-detection accuracy. Use `unknown` for labels the footage cannot resolve.

The equivalent API is `POST /api/videos/<id>/track` with `stage: "players"` or `"shuttle"`, followed by `POST /api/videos/<id>/contacts` with `shuttle_run_id` and optional `player_run_id`. All processing jobs, including CLI ingestion, share admission control within the project database.

## Reviewed identities and accuracy

Expand **Assign tracks to players** to map a loaded run's tracker to A/B/C/D for a reviewed source-frame range. Mapping ranges include the start and exclude the end. Confirm crossings and end changes; mappings never extend into another run automatically. Removing a mapping clears that identity from the overlay and future hints without changing saved events or raw model artifacts.

In **Reviewed clips & accuracy**, record a continuous clip, its live/replay status, and whether **every contact** is labeled. Inspect the full interval and add missed contacts before checking completeness. Contact scoring uses only complete live clips fully covered by the selected run. Unknown scenes, replays, incomplete clips, and unlabeled parts of the video are excluded explicitly.

Mark shuttle positions on separate exact source frames, or label the shuttle not visible. Marking a position hides the model trajectory; ambiguous frames can remain unlabeled. Cyan crosshairs show saved review points. **Measure saved labels** reports precision, recall, F1, and sample counts. Download the JSON report for matching errors, coverage, tolerances, source hashes, run IDs, and annotation revision. Wrong shuttle localization counts as both a false detection and a miss; missing output never earns a correct-absence result.

The equivalent API is `POST /api/videos/<id>/evaluate` with optional `contacts_run_id` and `shuttle_run_id` (at least one required). CLI usage:

```powershell
.\.venv\Scripts\python.exe -m badminton.cli evaluate 970dbd8adfe548d8 --contacts-run 70357b1ea6ca48288dacfea0a02c65ba --shuttle-run ad0696c19b4b4be0beddf592a641cca0 --output .cache/singles-evaluation.json
```

Run IDs above refer to the cached local experiments. Use the IDs returned by your jobs after rerunning models. The small development pilot is recorded in `data/manifests/pilot_review.json`; [the pilot report](docs/PILOT_REPORT.md) describes its evidence, limits, and reproducible import command.

## Storage

```text
data/manifests/                 Sample provenance and inspected windows (tracked)
data/processed/catalog.sqlite3  Video catalog, annotation revisions, and jobs
data/processed/<video-id>/      Timestamp map, audit images, and tracking runs
models/weights/                Locally downloaded model files
```

Annotations use optimistic revisions: stale saves are rejected rather than overwriting edits from another window. Revisions are retained in SQLite and accessible through `/api/videos/<id>/revisions/<revision>`. JSON exports contain video metadata and the saved annotation document. CSV exports contain one row per event, including proposal provenance where applicable. Recovery marks jobs from stopped workers as interrupted and preserves live workers in other instances. Retry interrupted clips explicitly. A changed source file must be imported again before analysis.

## Checks

```powershell
New-Item -ItemType Directory -Path .cache -Force | Out-Null
.\.venv\Scripts\python.exe -m pytest -q --basetemp .cache/pytest
.\.venv\Scripts\ruff.exe check backend tests scripts
```

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
```

These checks exercise playback, exact-frame images, event correction/export, reviewed identities, clip completeness, shuttle marking, accuracy reports, switching, and responsive layout. The review-tools check requires cached player/shuttle/contact runs for both samples and is restricted to the isolated server on port 8001. Screenshots go to `data/processed/qa/`. The isolated QA annotations are illustrative test events, not badminton ground truth.

