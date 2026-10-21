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
`.cache/player-audit-183/.cache/source-packet-v1`. Independent image assessment
is **not yet complete**: automatic approval review rejected sending these
private frames to fresh Codex sessions without explicit image-export
authorization. No external assessment process started, no assessment documents
or scores exist, and cached prediction contents remain unopened. The prepared
packet and its hashes are preserved while that authorization is pending.
This checkpoint contains no observed localization or identity result.

Generated tests reproduce and prevent four scoring races involving changed
packet, image, stream-seal and adjudication-seal bytes. Scoring rechecks every
sealed source artifact inside shared admission before writing a score; failure
retains a failed Store job and attempt receipt without a successful score.
All 120 focused generated tests and the complete local suite pass (1,957 passed,
six existing skips). Ruff, formatting of 179 files, dependency consistency,
repository validation, local document links and UTF-8/LF checks also pass.
The independent scientific assessments, final fresh code review, exact-head/main
CI and full public delivery are still required before this task is complete.
Exact verification receipts and scientific results will be added after the
frozen assessment protocol is complete. Shuttle, contact, shot-family/side, serve and
rally-end correctness are outside this player-only increment. The MSI shuttle
task [#179](https://github.com/Ken0u/badminton-match-analyzer/issues/179)
has separate Windows/CUDA input requirements. Doubles, unseen-source generalization,
cross-camera identities and full-match annotation correctness remain open.
