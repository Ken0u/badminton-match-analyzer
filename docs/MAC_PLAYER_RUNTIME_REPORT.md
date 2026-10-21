# Mac player/pose development diagnostic

Task [#176](https://github.com/Ken0u/badminton-match-analyzer/issues/176)
exercises actual automatic player/pose analysis on original development footage.
The [frozen manifest](../data/manifests/mac_player_runtime_v1.json) fixes the
source, native clock, annotation revision, both installed checkpoint hashes,
50 native frames and five overlay frames before inference. No held-out data,
downloads, threshold changes, training or model promotion are permitted.

On October 21, 2026, both installed models completed the frozen CPU run on
Stanleys-Laptop.local. The original singles excerpt is frames **[2000,2050)**,
PTS **80.00–81.96 seconds**, at native 1280 × 720 resolution. This reuses an
already inspected development source; it is not a new test set.

| Observed output | Lightweight / nano | Standard / small |
| --- | ---: | ---: |
| Processed native frames | 50 / 50 | 50 / 50 |
| Player observations | 100 | 100 |
| Frames with two detections | 50 | 50 |
| Frames without detections | 0 | 0 |
| Observations without tracker ID | 0 | 0 |
| Distinct provisional tracker IDs | 2 (`1`, `3`) | 2 (`1`, `3`) |
| Keypoints with confidence ≥0.25 | 1,553 | 1,575 |
| Tracking elapsed time | 7.160 s | 12.962 s |
| Tracking throughput | 6.98 frames/s | 3.86 frames/s |

These are model counts, not labelled precision/recall, keypoint correctness or
identity scores. A tracker ID is a local hypothesis, and does not identify a
named player. The run makes no model-selection decision. Total admitted job
wall time was 21.385 seconds, excluding the initial Python/vision-library
initialization. The existing tracking recipe, detector thresholds, 1280-pixel
inference size, stride 1 and both pinned weights were unchanged. Automatic court
calibration was disabled for both variants; existing manual context was retained.
No cuts were detected inside this two-second window. The camera range remains
`unknown`, with no reviewed scene exclusion; this does not certify a live scene.

All five preselected frames (2000, 2010, 2020, 2030, 2049) were inspected for
each model using contact sheets. Native-resolution frames 2030/nano and
2049/small were also inspected. Both models' boxes follow the near red-clad and
far yellow-clad players in these sampled views, including the far player's low
lunge. Pose markers are visible, with differences and uncertain arm positions
during fast motion. The ten panels are a sparse development inspection, not
independent keypoint labels, exhaustive frame review or cross-camera identity
adjudication. Extra confident keypoints do not establish greater accuracy.

The real shared catalog admitted job `378897f9c15d4fcca3e61ad8af8a8a83` through
`run_local_job`; it reached `completed`, and the original process (PID 51612,
creation time 1792613473.916743) exited with status 0. Both variants ran
sequentially on CPU. Torch 2.8.0, torchvision 0.23.0, Ultralytics 8.4.123 and
PyAV 16.1.0 were already installed. Nothing was downloaded or upgraded.

The executed code commit is `492489ff9e4103a43e395be54313f42ced109c9d`.
Later receipt-only repairs normalize inventory keys to slash-separated paths
on Windows and keep shared progress monotonic across both models and overlays.
They do not change detector/tracker code, weights, thresholds, native inputs or
the preserved predictions. Generated tests and fresh platform CI cover those
repairs; the 100 frozen model-frame calls are not repeated. The local ignored
directory `.cache/player-probe-176/.cache/actual-run-v1` contains
both original prediction JSON files, ten native overlays, two contact sheets,
before/after input inventories and the final receipt. Its 16 inventoried
artifacts have SHA-256 hashes in the receipt; total retained output including
the receipt is 2,908,460 bytes. Receipt SHA-256:
`f53efb9b366c18c3471132e153dbcee5c0bdf2223381cce4ce766c4cb106d871`.
Raw footage, model weights, annotations and images remain ignored and local.
They are not supplied by a clone or redistributed in this report.

Before/after checks verify byte-identical source video, timestamp map, catalog
video document, complete annotation history at revision 1, both model weights
and both original prediction files. New predictions are kept separate from
application runs and never become reviewed annotations. Failure receipts retain
completed and partial outputs rather than restarting an interrupted model.

Reproduction requires those exact existing local inputs, not merely a clone:

```sh
python scripts/probe_player_runtime.py \
  --root "$BADMINTON_ROOT" \
  --data "$BADMINTON_ROOT/data/processed" \
  --weights "$BADMINTON_ROOT/models/weights" \
  --manifest data/manifests/mac_player_runtime_v1.json \
  --output "$BADMINTON_ROOT/.cache/new-player-probe"
```

The launcher pins root/data/weights before application imports and refuses an
occupied output directory, changed inputs, missing shared Store or concurrent
processing job. Do not rerun merely because a terminal observation times out;
first verify the recorded process lifetime, shared job and durable artifacts.
Its cooperative 900-second and 64 MiB limits preserve partial evidence.

The 30 focused generated/injected regressions cover rotated native VFR frames,
complete PTS denominators, frozen-input guards, real shared admission, camera/
scene/calibration context, malformed predictions, preservation, interrupted
variants and runtime/output budgets. They use synthetic predictions and cannot
substitute for the actual inference above. Exact PR/main CI and public delivery
evidence belong on the owning issue.

This Mac currently lacks verified doubles footage and installed TrackNet/BST
weights. Shuttle localization, contacts, serves, rally endings and shot-family/
side inference were not exercised. Larger development windows, difficult
occlusions and independently adjudicated identity evidence remain work under
[#66](https://github.com/Ken0u/badminton-match-analyzer/issues/66); the MSI's
source-only shuttle work under
[#172](https://github.com/Ken0u/badminton-match-analyzer/issues/172) retains its
own reservation and scientific assessment requirements. No claim of automatic
full-match annotation accuracy, model promotion or running-app upgrade follows
from this diagnostic.
