# Resumable full-match processing

Full-match processing now runs the existing perception and proposal stages on
every source frame, rather than requiring separate short-window requests.
This is processing coverage, not complete or correct match annotation. The
family/side models, persistent identities and event recall remain incomplete;
the saved annotations and exports still require explicit review.

## Behavior

The UI has a **Full-match processing** panel with process/resume, cooperative
pause, window navigation and a return to the existing window tools. Seeking
loads the matching completed window, so the browser does not download all pose
rows for a long video. Automatic court detection and the selected player model
carry through. Experimental singles family/side suggestions can be disabled;
doubles recognition explicitly reports unavailable labels.

CLI: `python -m badminton.cli process <video-id>`; options are `--player-model`,
`--no-auto-court` and `--no-recognition`. API: `POST /api/videos/<id>/analysis`,
`GET /api/videos/<id>/analysis/<job-id>` and
`POST /api/videos/<id>/analysis/<job-id>/pause`. New requests with identical
inputs reuse completed stages. A pause keeps admission until the worker
acknowledges it and releases model resources.

A complete camera scan runs first. Sixty-second core windows partition all
source frames once; four-second temporal halos support contacts, rally context
and recognition near window edges. Decoding uses imported PTS, including VFR.
Processing edges never become fabricated camera cuts. Preceding source cuts
and timestamp gaps remain part of the view context, so an expired court cannot
be revived by starting a new window.

Each window runs players, shuttle, contacts, rally proposals and the supported
recognition stage sequentially. Raw halo evidence is preserved; the UI and
summary count proposals owned by the core containing their navigation frame.
This prevents showing identical overlap proposals twice. Timing/model jitter
near a boundary still needs independent event evaluation. Tracker IDs remain
scoped to their source run; this does not invent persistent player identity
across independent windows or camera views.

## Checkpoints and integrity

Recipes record source metadata/hash, exact timestamp digest, model settings,
code/model assets, installed library versions and camera/scene/court context.
Stage keys include relevant settings and input artifact hashes. Disabling
recognition reuses finished perception instead of repeating GPU tracking.
Reviewed events, identities and source shuttle labels do not enter automatic
features or targets. Current identity assignments are applied during review.

Only completed, validated artifacts are registered for review. Frame stages
must cover every requested source frame and PTS. Files receive SHA256 receipts
and stable run IDs, which also preserve review references after resume. Missing
registration or a stop between registration and manifest persistence can be
recovered. Changed cached bytes fail rather than silently replacing evidence.
New source/context/model recipes retain separate progress. Processing never
saves predicted courts or events as reviewed annotations.

One admitted parent owns processing; child stages do not claim competing
workers. Cancellation requests survive stale progress snapshots. Context edits
pause the old snapshot, while label-only edits preserve compatible caches.
Whole-source manifests distinguish processing completion from annotation
correctness: `fully_annotated` remains false.

## Checks so far

- Full regression run: **597 passed, four optional GPU skips**. After the
  nominal-frame-rate recipe guard, 109 focused pipeline/camera/context checks
  passed. Lint and source formatting pass.
- Generated 130-second media exercises three windows without downloaded
  checkpoints. API checks cover complete source coverage, immutable reuse,
  pause/admission, current-context edits, changed sources and unavailable
  doubles recognition. Interrupted registration, missing frames and corrupted
  artifacts have explicit failure/recovery tests.
- Browser checks pass pause/resume, seeking across core boundaries, halo
  ownership, explicit annotation save and all-16-stage reuse after label edits.
  Its generated fixture uses synthetic perception, not badminton ground truth.
  The rendered full-source review interface was visually inspected.
- Actual CUDA validation of **both complete supplied videos**, with empty
  manual annotations, is running under an immutable snapshot. No completed
  native result or accuracy claim is made yet. This remains a release gate.

Native protocol/evidence: `.cache/native-runtime-pipeline-v1` contains the frozen
60-file package and source hashes. `.cache/pipeline-native-v1` records worker,
parent job, progress, source counts and eventual summaries; the separate store
is `.cache/pipeline-native-data-v1`. The scope is all 12,023 singles and 12,148
doubles frames. The new 75-rally external-source head evaluation remains gated
and is not replaced by these development videos.

## Remaining requirements

Verify actual whole-source completion and byte-identical resume, exercise the
native review interface, then pass exact-head CI before merging and activating
the release. Automatic identity continuity, reliable scene/live/replay handling,
complete contact/serve/end recall, all requested family/side combinations and
unseen full-match correctness remain open. Large source timestamp gaps that
exceed the bounded inference interval also need expanded handling; frames are
not silently skipped.
