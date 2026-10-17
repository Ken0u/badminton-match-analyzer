# Camera-boundary baseline

Prepared October 17, 2026. Full-video camera scans and processing across detected
edits are implemented. This is one part of full-video reliability: it does not
identify live play, replay, serves, rally ends, or persistent identities.

## Processing behavior

**Camera changes -> Scan camera changes** runs a queued CPU scan over every
source frame. Candidate buttons seek to the first frame after a possible edit.
Step backward/forward to inspect the transition. Each half-open camera range has
unknown scene status; a camera cut is never saved as a rally event. Existing
annotations, review coverage, and exports remain unchanged.

API: `POST /api/videos/<id>/segments`; retrieve the completed job's artifact using
the normal `/runs/<job_id>` endpoint. CLI:

```powershell
.\.venv\Scripts\python.exe -m badminton.cli segments 970dbd8adfe548d8
```

The scan uses pinned PySceneDetect 0.7.2's
[AdaptiveDetector](https://www.scenedetect.com/docs/head/api/detectors.html), with
threshold ratio 3, minimum content value 15, minimum scene length 15 frames, and
two-frame look-ahead. Images are reduced to at most 320 pixels wide. Decoding,
display rotation, frame indices, and exported times use the existing source-PTS
path. Nominal FPS supplies the detector's typed frame coordinates; it does not
generate event times or resample VFR footage. A source-time gap above the larger
of 100 ms and 2.5 nominal frame intervals also splits context; normal low-rate
footage is not treated as a cut at every frame. Short-window scans include surrounding source frames for the
rolling detector. Source-hash checks and shared processing admission still apply.

New player and shuttle runs automatically scan their requested window:

- ByteTrack resets at detected boundaries. New views receive disjoint numeric
  track IDs, preventing an old reviewed identity from silently attaching to a
  new person through counter reuse. These are temporary track IDs.
- A calibration that began before a detected cut expires for subsequent player
  filtering. Confirm a new calibration for the new view; recognition abstains
  when its input reports invalid camera calibration. A cut at the first requested
  frame is handled too. Only boundaries found within this run are available to
  expire calibration; this is not global camera-view identification.
- TrackNet computes each view's background separately and clears its temporal
  window and ensemble accumulators. Short segments repeat their own final frame
  solely for model shape padding. No real frames or heatmaps cross a detected cut.
- Contacts now honor the union of player and shuttle cut metadata. Previously
  they considered only shuttle cuts. Recognition also rejects crossing contexts.

Older runs remain immutable and do not acquire new cut metadata automatically.
Rerun tracking to use this preprocessing. The 120-second tracking-window limit
still applies; only the camera scan currently processes the full video at once.

Browser inspection also exposed an old-image/new-frame-number mismatch while an
exact-frame request was pending. A loading cover now hides the stale image and
overlay until the requested source image arrives. A delayed-response browser
regression checks the cover and the final exact-frame image.

## Actual sample evidence

[The machine report](camera-boundary-verification.json) records source hashes,
run IDs, all boundaries, six inspected example pairs, and a real GPU probe.

| Sample | Source frames scanned | Candidate boundaries | Scan elapsed |
| --- | --- | --- | --- |
| Singles | 12,023 | 65 | 24.802 s |
| Doubles | 12,148 | 69 | 19.737 s |

The first three candidates in each video visibly show edits into graphics,
court views, or close-ups. Neither existing 250-frame tracking pilot contains a
detected cut. These observations are not cut precision/recall: no exhaustive
independent boundary labels exist yet, and difficult negatives were not scored.

An isolated CUDA probe processed singles frames 630–709, including detected cuts
639 and 683. Both tracking stages returned all 80 exact source frames. Player
ID sets were disjoint across the three views; filtering calibration expired
after 639. Player/shuttle processing took 5.611/7.583 seconds, with peak GPU
allocations 101.9/430.3 MB. The probe deliberately used a QA-only calibration
spanning the cut to test invalidation; it did not create reviewed event truth.
More people can appear after filtering expires, so counts are not player accuracy.

Generated-media tests cover abrupt cuts, VFR timing, source-time gaps, gradual
lighting change, source mutation, look-ahead at a clip edge, job admission,
artifact lineage, and annotation preservation. Model-independent temporal tests
cover segments shorter than, equal to, and longer than TrackNet's eight frames;
tracker tests cover stride-skipped cuts, ID reuse, and calibration expiration and
renewal. Browser QA covers full-sample scans and generated two-view media in CI.

## Remaining work

Fast cuts inside the 15-frame minimum, the first suppressed frames, and the last
two source frames may be missed. Gradual transitions, flashes, fast camera motion,
and unfamiliar broadcasts need independent evaluation. False boundaries can
split useful contexts. There is no correction editor for these raw candidates
yet. No scene range is automatically certified as live or replay.

Next, add reviewed camera/scene corrections, evaluate transitions against an
independent full-video audit, and distinguish live court play from replay and
non-play before running a whole-video event pipeline. Complete live-rally labels,
serve/end detection, YOLO-domain recognition validation, doubles recognition,
automatic calibration/identity recovery, and resumable full-match processing all
remain required for the original end goal.
