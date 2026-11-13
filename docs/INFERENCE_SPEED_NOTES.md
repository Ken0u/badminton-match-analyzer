# Inference speed: findings and deferred work

Written 2026-11-12. Nothing here has been changed in the code yet. The work
is deferred until the current training is finished, because the settings
below also shape the features the event and stroke models are trained on.

## What was measured

Recorded stage timings in `data/processed/*/runs/*.json` for `singles.mp4`
(8 min, 12,023 frames, 1280x720, 25 fps) on the laptop's RTX 2060:

| Stage | Time | Speed |
| --- | --- | --- |
| Shuttle (TrackNetV3, 512x288, seq_len 8) | about 17 min | 13 fps |
| Players (yolo11s-pose, imgsz 1280) | about 10 min | 23 fps |

Later runs of the same video took about 10 and 7 minutes, so speed varies
between runs. Contacts, rallies and the stroke model were not timed in these
records; they are small by comparison. There is no CPU measurement.

## Where the time goes

- `shuttle.py` slides the 8-frame TrackNet window one frame at a time and
  averages the overlapping heatmaps, so each frame goes through the network
  8 times: about 13,500 forward passes where non-overlapping windows would
  need about 1,700.
- `tracking.py` runs the small pose model at `imgsz=1280` on every frame
  (stride 1), one image per call.
- Neither stage batches. Peak GPU memory was 420 MB (shuttle) and 176 MB
  (players) of 6 GB. Not profiled, but the GPU is probably waiting on Python
  and decoding.
- The video is decoded about four times at full resolution: scene scan,
  players, the shuttle background median pass, shuttle inference.
- Each 60 s window has a 4 s halo on both sides, so 13,546 frames are
  processed for 12,023.

## Options, in rough order of payoff

1. Shuttle window step of 4 or 8 instead of 1 (4-8x fewer passes). Costs
   accuracy; needs measuring.
2. Players at 960 or 640 px, the nano model, or every second frame with
   interpolation. Costs accuracy; needs measuring.
3. Batching and a single decode pass. No accuracy cost.
4. ONNX or OpenVINO export, mainly for a CPU target.

## Things to keep in mind when picking this up

- Options 1 and 2 change the shuttle tracks and poses that the trained
  models consume. Measure them end to end with the trained models on the
  evaluation set, not just on tracking metrics. If a faster setting is
  adopted, training features may need re-extracting with it.
- Start by profiling one window to confirm the split between network time,
  decoding and Python overhead.
- A free-tier CPU host is unlikely to be enough even after all of this. The
  likely deployment is a GPU worker that starts per job and shuts down.
