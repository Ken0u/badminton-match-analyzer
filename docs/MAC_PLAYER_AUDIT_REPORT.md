# Sparse Mac player development audit

Task [#183](https://github.com/Ken0u/badminton-match-analyzer/issues/183)
continues the approved player-identity roadmap
[#66](https://github.com/Ken0u/badminton-match-analyzer/issues/66), following
the actual CPU execution diagnostic
[#176](https://github.com/Ken0u/badminton-match-analyzer/issues/176).
Execution counts alone do not measure localization or identity correctness.
This increment compares one existing prediction artifact with independent
automated source-image assessments. Those assessments are not human gold
labels, and the previously used singles source is development footage.

The [frozen manifest](../data/manifests/mac_player_audit_v1.json) fixes the
source, original clock, annotation revision, existing run bytes and all eleven
native sample frames before predictions are opened. Frames 434 through 684,
every 25 frames inclusive, sample the existing `[434,685)` player window.
There is no new inference, model selection, threshold tuning or promotion.

Two genuinely fresh source-only sessions inspect the same unmodified native
images independently. Each records every visible on-court person, native pixel
box, source actor continuity and unknown/occluded cases. Neither receives model
overlays, predictions, tracker IDs or the other assessment. Both original
documents are sealed with raw byte hashes before comparison. A separate
source-only adjudication pass preserves disagreements and unresolved cases
before the cached prediction artifact is opened. These are automated visual
assessments; their agreement cannot establish human annotation reliability.

The fixed scorer uses deterministic one-to-one maximum total intersection over
union (IoU), considering only pairs with IoU at least 0.5. Unknown people,
incomplete frames, unavailable localizations and excluded scenes remain in
explicit denominators. Only adjacent sampled, eligible source actors in one
view and uninterrupted cached camera/scene context contribute identity
transitions. Sampled ID changes, ID reuse and fragments are distinct outputs;
none is a complete-run identity-switch score. `court_view` describes the visible
image, without certifying that it is live rather than a replay.

Source preparation uses the real shared Store admission and exact native frame/
PTS/orientation validation. Original video, clock, annotation history and
prediction files are hashed before and after admitted work. Raw source images,
private assessment documents and predictions remain ignored and local. The
launcher preserves immutable seals, failed-attempt receipts and existing output;
it never writes application annotations or promotes a model.

On October 21, source preparation completed through shared Store job
`fc9bcdea98d44168818534916fe21e73`, with actual process exit 0 and unchanged
source, clock, annotation history and original run files. The eleven native
1280 × 720 PNGs cover PTS 17.36–27.36 seconds and occupy 9,505,180 bytes.
Packet SHA-256:
`2df667caa140df6c5f4b15c9d423faab23272fb1cacd27ef53f2848cd3fe3b34`.
The preparation executed commit `c745204047cdadd844db65b70e1aeea6c301131c`;
its receipt records exact launcher/core source hashes. No model ran.

The local ignored packet is
`.cache/player-audit-183/.cache/source-packet-v1`. After the owner explicitly
approved sending only these eleven private frames to Codex, two genuine fresh
read-only source sessions completed independently. Their actual thread IDs are
`01a16086-bb4b-7283-8275-5fc72522f7c7` and
`01a16086-c06b-77a3-99e1-b7972ed6adb9`. Each received the same eleven source
images, read packet/hash evidence only, and had no predictions or other
assessment supplied. Both original JSON documents remain unchanged. Their raw
SHA-256 values are:

- Stream A: `2e71d3327200a93c3a74d7df3aca7801febbb5f88f69d36d53c5c06285c5db03`.
- Stream B: `d6393b9c9316c7de818b65be22b85f1639393c7d9c98b723eb362bfca574ce57`.

A third fresh source-only session,
`01a16089-8171-7b51-a749-6bd991d7a44a`, compared the originals against the
same images. It retained 24 disagreement records covering box boundaries,
occlusion, actor descriptors and continuity across views. All eleven frames and
22 person observations remain present; both source streams enumerate two
people in each frame. The adjudication does not bridge the changed close-up at
659 or the return to a wide view at 684. These are automated assessments, not
independent human gold labels. Adjudication raw SHA-256:
`c5c096f6913d44fd826be2635992e3d6216956c1ef5fd09dca45a8ef362a25ab`.

Both original streams were sealed before adjudication; the adjudication was
sealed before the first cached-prediction content read. The shared Store then
completed scoring job `2edb315aa48b41b0a41c61d7d2420bd8`. Actual scoring process
75256 (creation time 1792621124.269885) exited 0; all source inputs, original
prediction files, images and seals remained unchanged. No inference or source
decoding was repeated. Scoring executed code
`a2c85fcf28a8362244687ddb93bdf1726d56c64c`. Score SHA-256:
`fb519bede2d29f9fef3c08c1b99c4e506df7fca352b6690e0323bbf7153eb202`.

| Frozen sampled result | Count |
| --- | ---: |
| Sampled/scored native frames | 11 / 11 |
| Source person observations / localizable | 22 / 22 |
| Raw/scored predictions | 23 / 23 |
| One-to-one matches at IoU ≥0.5 | 20 |
| Unmatched eligible source people | 2 |
| Unmatched predictions | 3 |
| Unknown actors / unlocalizable people | 0 / 0 |
| Identity-ineligible observations after matching | 2 |
| Sampled transition candidates / eligible | 24 / 14 |
| Ineligible transitions retained | 10 |
| Same-ID / changed-ID eligible transitions | 14 / 0 |

Matched IoU ranges from 0.602 to 0.985, mean 0.864, conditional on the twenty
matches. The far player has no matched prediction at frame 584 during motion;
the partly occluded person has none at close-up frame 659. Three extra
predictions at 684 remain unmatched source observations, without turning that
count into a calibrated false-positive rate. Parent inspection of native source
images 584 and 659 corroborates motion/occlusion context after all labels were
sealed; it did not change any labels or thresholds. The original cached cuts
639 and 683 block cross-view transitions. Ten transition candidates remain
ineligible because an endpoint lacks a match or the view/camera changes; zero
eligible sampled ID changes cannot rule out switches between the samples.
Five view-scoped source-actor groups each use one matched local track ID, with
no sampled ID reuse across source actors in a view. They are not named players,
roster counts or complete identities. No tracker change or promotion follows
from these results. Motion, occlusion and extras are concrete development
failure cases for a separately frozen follow-up.

Generated tests reproduce and prevent four scoring races involving changed
packet, image, stream-seal and adjudication-seal bytes. Scoring rechecks every
sealed source artifact inside shared admission before writing a score; failure
retains a failed Store job and attempt receipt without a successful score.
The initial complete local suite passed (1,957 passed, six existing skips).
Hosted CI then exposed an unconditional optional `torchvision` import in the
decoder-only launcher and generated fixture. The repair initializes vision
before decoding when installed, permits a runtime without model extras, and
propagates broken installed-runtime errors. No images or inference were repeated.
All 123 focused generated tests pass with installed vision; the complete minimal
Python 3.12 suite passes 1,946 tests with 17 existing optional skips, including
every audit test. Ruff, formatting of 179 files, dependency consistency,
repository validation, local document links and UTF-8/LF checks also pass.
Exact scoring-head CI 39682709322 passes, including Windows/macOS. Revision,
browser groups 18/13/8 and installed-package HTTP receipts were audited against
the exact source. This aggregate report changes afterward; fresh final-head
code review, exact-head/main CI and full public delivery are still required
before this task is complete. Verification receipts belong on the owning issue.
Shuttle, contact, shot-family/side, serve and
rally-end correctness are outside this player-only increment. The MSI shuttle
task [#179](https://github.com/Ken0u/badminton-match-analyzer/issues/179)
has separate Windows/CUDA input requirements. Doubles, unseen-source generalization,
cross-camera identities and full-match annotation correctness remain open.
