# Experimental rally-boundary proposals

October 17, 2026, version 0.11.0.

The API, CLI and editor now propose uncertain serve/end intervals from cached
player poses and shuttle observations. This is a development review aid, with
substantial missing detections; it does not establish complete rally coverage,
terminal-contact accuracy or correct server identity.

## Behavior

Track players and the shuttle at stride 1 in a calibrated view, then choose
**Suggest rally boundaries**. Clicking a candidate opens a draft with inclusive
timing bounds. Serve bounds use contact fields; endings use terminal fields.
Hitter and stroke side remain unknown. Add and save explicitly after inspecting
the source. Proposals never replace saved events or raw inference artifacts.

A possible serve needs observed quiet body/wrist context, sustained shuttle
departure near a low wrist, service-area feet and an observed opponent. Partial
doubles context is recorded. Proximity remains an unconfirmed track hint.
A possible ending needs incoming motion, an observed in-court stationary tail,
a settling fit better than a smooth quadratic apex, and subsequent full-player
quiet context. Missing observations, cuts, clip edges, last hits and silence
cannot alone supply this evidence. Faults, out shots, occlusions and walking
players are still difficult; these cues are not ground-contact measurements.
The tool does not invent a missing boundary to pair a rally.

Source timestamps, video/stage/hash when recorded, ordering, stride, reviewed
scenes, camera cuts and court context are checked. API/CLI compare input times
against registered source PTS. A VFR regression caught and fixed a pose-lag
lookup error: floating-point rounding could select a later frame and shorten
motion windows. Consecutive launch-motion links exclude isolated heatmap jumps.

Artifacts retain run/model lineage, source hash, annotation revision, recipe and
camera/scene/court signatures. Changed context disables cached cards, including
unsaved edits outside the candidate interval. New player runs record their court
snapshot and reject reuse after it changes. Older inputs explicitly report
`legacy_unverified_snapshot`; their historical geometry is not reconstructed.
Identity/event-only changes do not invalidate motion evidence.

## Standard and lightweight player models

Standard now defaults to pinned `yolo11s-pose.pt`; `yolo11n-pose.pt` remains the
Lightweight choice in the UI/API/CLI/downloader. Both require SHA256 verification
before loading and refuse arbitrary paths. See the publisher's
[YOLO11 documentation](https://docs.ultralytics.com/models/yolo11/).

On 114 selected difficult doubles frames, nano produced exactly 4 filtered boxes
on 56 frames, small on 94. Source overlays showed some recovered far-player
detections. This selected output-count comparison is not independent accuracy.
Small still misses people/poses. Full-view measurements on the RTX 3050 Ti Laptop:

| View | Frames | Nano elapsed / fps | Small elapsed / fps | Small peak allocated VRAM |
| --- | ---: | --- | --- | ---: |
| Singles [255,639) | 384 | 14.014s / 27.40 | 17.099s / 22.46 | 175.6MB |
| Doubles [278,866) | 588 | 17.356s / 33.88 | 22.442s / 26.20 | 175.6MB |

These sequential 1280 px pose-stage measurements include scanning/decoding, not
whole-app memory or full-match throughput. Nano peak allocation was 101.9 MB.
Existing nano artifacts and tracker namespaces remain unchanged.

## Actual development outputs

The [machine-readable record](rally-proposal-verification.json) preserves source,
input digests, run IDs, model/runtime metadata, diagnostics and evidence.
The research catalog has approximate court geometry and NO event truth.
Source-first boundary labels were frozen before perception, manifest SHA256
`e88827aaa2672e8b2bf8c11a1e19a417d2d4d4c0dc698e057f57b69db5fd6001`.

| View | Actual candidate | Source-first interval | Missing output |
| --- | --- | --- | --- |
| Singles | End navigation frame 610, inclusive[607,621] | Unresolved end[590,620] | Serve |
| Doubles | Serve navigation frame 331, inclusive[324,331] | Uncertain serve[325,330] | End |

Navigation frames are estimates. Doubles track 8 is doubtful due to overlap, so
the editor leaves the hitter blank. Both emitted intervals overlap broad source
intervals, but these await independent adjudication and intermediate contacts
are not exhaustive. No precision/recall/F1 or timing-error claim is justified.
These development views cannot be an independent test set. Cached-input proposal
processing took 0.245/0.227 s; expensive perception is separate.

The main originals remain at annotation revision 4 with 6 events each. No reviewed
labels were added. Complete live-rally/contact/visibility labels, doubles
recognition, automatic identity/calibration and resumable whole-match analysis
remain required before claiming full-match correctness.

## Verification

379 standard tests passed, 4 opt-in CUDA checks skipped; all 4 passed separately
(shuttle, default-small player, explicit-nano player, recognition). Detector/API
regressions cover launch/settling, apex/ghost/jump negatives, missing/partial
players/joints, camera/PTS gaps, scenes, court expiry, identity changes, VFR,
clipped views, source mismatch, staleness, raw immutability and independence from
event labels. Generated-media browser checks exercise actual model-choice POSTs,
draft scene/court invalidation, explicit add/save, interval/provenance export and
reload without sample media or weights. That browser suite also runs in CI.
Actual inference and full-view outputs are development evidence, not accuracy
validation.
