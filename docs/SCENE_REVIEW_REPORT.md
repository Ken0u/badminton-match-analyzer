# Reviewed camera and scene ranges

Prepared October 17, 2026. Camera corrections and scene ranges now persist with
annotation revisions, drive new processing, and update review views. This adds
manual scene control; automatic live/replay classification remains unfinished.

## Behavior

In **Camera changes**, inspect a detected transition, confirm or reject it, or
enter the first frame after a missing cut. Save before starting analysis. New
player/shuttle runs use the effective cuts for tracker resets, separate TrackNet
contexts/backgrounds, and court-calibration expiry. A preceding confirmed cut
also expires calibration that began in an earlier view. Source timestamp
discontinuities cannot be joined. Raw detected cuts remain in each artifact.

Existing perception is immutable. If effective boundaries or a preceding
confirmed cut differ from those used by a cached run, contact/classification
requests reject it with an instruction to rerun tracking. Confirming an already
detected cut does not itself require a rerun. Changing notes does not invalidate
processing. A previously stale derived view stays stale when reviewed again.

Scene ranges include their start and exclude their end. They cannot overlap and
must remain within source bounds. Supported values are `live`, `replay`,
`non_play`, and `unknown`. Explicit replay/non-play/unknown ranges block contact
suggestions; recognition also abstains if its temporal context overlaps one.
Unlabeled footage can still produce proposals for review. A live label does not
declare contacts exhaustive or establish event accuracy.

Draft exclusions immediately disable existing suggestion cards. Saved ranges
apply to processing and views without deleting raw detections or saved events.
Removing a range restores the underlying perception scene value, including any
original scene evidence. Generate contacts/shot labels again to recover
suggestions omitted by an earlier mask. Evaluation skips an entire complete-live
review window if a conflicting non-live scene range overlaps it, reporting the
reason instead of scoring contradictory coverage. Shuttle point localization
remains a separate point metric.

## Source review

The tracked [manifest](../data/manifests/scene_review.json) records the exact
content hashes and reviewer provenance. Every source frame in both selected
ranges was decoded and inspected in a contact sheet, with larger source samples
and adjacent cut pairs. Both show an animated player graphic followed by a BWF
highlights title card.

| Sample content ID | Reviewed range | Source time | Scene |
| --- | --- | --- | --- |
| `970dbd8adfe548d8` | [130, 255), 125 frames | [5.20, 10.20) s | non-play |
| `c406a1187130b845` | [153, 278), 125 frames | [6.12, 11.12) s | non-play |

This is an assistant's first visual pass, with human adjudication pending. It
adds no shot family, side, contact, rally, or identity truth. The eight existing
pilot contacts remain unchanged; their family/side labels remain unknown. No
other footage is certified as live. Reproduce the idempotent source-hash-checked
import after upgrading the application:

```powershell
.\.venv\Scripts\python.exe scripts/import_scene_review.py
.\.venv\Scripts\python.exe scripts/import_scene_review.py --apply
```

The first command previews; the second saves new revisions while preserving
unrelated labels. Conflicting scene IDs are rejected rather than overwritten.

## Verification

An isolated actual CUDA run used singles frames [630, 710). Deliberate QA-only
corrections rejected real detected cut 639 and added a synthetic cut at 650;
raw cuts [639, 683] became [650, 683]. Both player and shuttle stages returned
all 80 source frames with the corrected segmentation and no stale-input flag.
A synthetic replay range [650, 683) tagged all 33 corresponding rows. These
intentional false labels tested override behavior, not boundary/scene accuracy;
they were never applied to the real catalog. Player/shuttle elapsed times were
5.594/8.315 s, with peak PyTorch allocations 101.9/430.3 MB. The small
[machine report](scene-review-verification.json) records the probe and lineage.

The standard suite passes 329 tests with two optional GPU checks skipped; both
real-checkpoint CUDA checks pass separately. Regressions cover schema ambiguity,
source bounds, immutable/reversible scene views, physical gaps, repeated stale
views, context exclusions, conflicting evaluation coverage, revision history,
and idempotent source-verified imports. Browser coverage includes add/edit/remove,
draft exclusions, overlaps, persistence, export, and stale input rejection;
generated import fixtures exercise scene/cut save and duplicate-import
preservation without source media or model weights in CI. All five local UI
suites and the separate real-model recognition browser suite pass; the import
suite also passes against a fresh generated-media server. Python/frontend
formatting, dependency consistency, and the built 0.9.0 wheel's scene module,
UI, model asset, and licenses were checked.

## Remaining work

Only two short non-play ranges have this review. There is no independent
full-video cut/scene benchmark, automatic replay detector, or demonstrated
full-match event accuracy. Expand independently reviewed complete rallies and
scene boundaries, adjudicate public-source contact alignment, then measure and
improve contact/serve/end and direct-video shot recognition. Four-player
identity recovery, doubles recognition, automatic calibration, and resumable
whole-match processing remain required for the end goal.
