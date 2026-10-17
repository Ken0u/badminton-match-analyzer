# First implementation and player-tracking baseline

October 17, 2026.

This report records the first player-tracking increment. Shuttle tracking, contact suggestions, and subsequent bug fixes are documented in [the latest review](BUG_REVIEW.md).

## Delivered

- A working local video review application at `http://127.0.0.1:8000`.
- Video ingestion with content hashes, actual source-frame timestamp maps, metadata, posters, and contact sheets for both samples.
- An annotation contract for serves, rally endings, and six shot families with forehand/backhand labels. Half smash is excluded.
- Event creation, editing, deletion, rally filtering, player details, and per-camera court calibration.
- SQLite annotation history, conflict detection, and JSON/CSV export. Delayed save responses preserve newer unsaved edits.
- A CUDA player/pose baseline using YOLO11n-pose and ByteTrack, with background jobs and review overlays. Tracker IDs remain separate from player identities.
- A compatible local environment, a frozen Windows/Python 3.10/CUDA dependency snapshot, and a checkpoint manifest with a pinned checksum.

This increment establishes the review and player-perception workflow. The manually reviewed contact/shot dataset, shuttle tracking, and automatic event/shot recognition are still pending. It does not complete the entire project plan or all of its pilot-labeling tasks.

## Footage audit

Both samples are 1280 × 720 at 25 fps, around eight minutes long, with audio. They contain edited highlights: full-court play, close-ups, alternative angles, and replay sequences. The singles sample also shows an end change. Automatic whole-video analysis will need camera/replay segmentation and support for partial rallies.

The initial tracking windows were visually inspected at one-second intervals:

| Video | Window | Source frames | Court calibration |
| --- | --- | --- | --- |
| Singles | 80–90 s | 2000–2249 | Applies to this window only |
| Doubles | 24–34 s | 600–849 | Applies to this window only |

No serve, contact, or shot-family labels were inferred from this sparse visual inspection. The real annotation database contains court calibration but no fabricated shot events. Browser-test events live in a separate QA database.

## Baseline experiments

Hardware: NVIDIA RTX 3050 Ti Laptop GPU, 4 GB VRAM. Runtime: Python 3.10, PyTorch 2.8.0+cu126, Ultralytics 8.4.178. Checkpoint: `yolo11n-pose.pt`. Tracking: ByteTrack, confidence threshold 0.25, native-resolution frames, saved court filter, frame stride 1.

A first singles run at model input size 640 missed the far-court player throughout the selected window. A single-frame comparison at 640/960/1280 showed that input size 1280 recovered that player. The baseline therefore now uses 1280.

| Experiment | Frames | Processing time | Throughput | Detection-count observations |
| --- | --- | --- | --- | --- |
| Singles, input 640 | 250 | 10.192 s | 24.53 frames/s | One player per frame; far player missed |
| Singles, input 1280 | 250 | 10.875 s | 22.99 frames/s | Two players on all 250 frames |
| Doubles, input 1280 | 250 | 10.901 s | 22.93 frames/s | Four players on 237 frames; three on 13 frames |

Throughput includes decoding, inference, and progress writes inside the tracking loop, and excludes importing libraries and loading the model. It is a measurement of these short local runs, not a full-match speed guarantee.

These are detection-count observations, **not detection or identity accuracy scores**. Consistent counts can still contain false detections or identity swaps. A manually labeled evaluation set is needed before reporting precision, recall, identity-switch rate, hitter accuracy, or stroke accuracy. Inspect the thirteen incomplete doubles frames to determine whether missed detections, overlap, or filtering is responsible.

The reviewed preview frames show both singles players and all four doubles players, with court geometry, boxes, and pose skeletons. Generated previews are in `data/processed/qa/singles-tracking.png` and `data/processed/qa/doubles-tracking.png`.

## Verification

- Six backend workflow tests pass. They cover real variable-frame-rate decoding, exact-frame extraction, timestamp normalization, annotation history, stale-save rejection, re-import preservation, invalid labels/identities/boundaries, court geometry, byte-range video streaming, source-path validation, and interrupted-job recovery.
- Browser checks pass for playback, exact-frame seeking, event creation/editing, court calibration, persistence, export, format switching, and responsive layout. Delayed-save and delayed-video-selection scenarios are included.
- Real GPU tracking completed through both the CLI (singles) and background API (doubles).
- Python lint checks pass; installed packages report no broken requirements.

## Next work

1. Add TrackNetV3 shuttle inference on these same windows, preserving missing/visible states and raw coordinates. Visually review the output before trajectory repair.
2. Label a pilot set of contact frames, hitters, serve/end boundaries, and the six shot families using the viewer. Include a second knowledgeable annotator for ambiguous strokes.
3. Build and evaluate contact detection and hitter attribution from shuttle tracks and pose. Add persistent player-to-track assignment, especially for doubles.
4. Train the first shot-family/stroke-side classifier using curated public and local labels, with match-separated validation.
5. Add camera/replay segmentation before extending the processing window to the complete edited samples.

