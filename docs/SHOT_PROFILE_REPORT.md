# Source-linked recorded shot profiles

Task [#374](https://github.com/Ken0u/badminton-match-analyzer/issues/374)
adds an independent adaptation of the abstract shot-profile idea in the
[design review](VISIONAI_DESIGN_REVIEW.md), following the delivered
[mini-court](MINI_COURT_REPORT.md). No reference code, assets, weights or text
are copied. This is a summary of recorded annotations, not a new recognition
model or evidence of complete automatic match accuracy.

## Behavior

The editor has a collapsible shot-profile panel. The default filter includes
reviewed and corrected events. An explicit all-recorded filter also includes
predictions and missing review status. The panel retains the counts of all
recorded shots, included/excluded shots, predicted and unknown review states,
and unresolved hitters. Missing status is never upgraded to reviewed.

Only shot events enter the clear/lift/net/drop/smash/drive grid. Other and
unknown family, plus unknown stroke side, remain separate visible entries.
Forehand and backhand counts share one selected collection with family totals,
proportional bars and source links. Serves are counted separately; rally endings
are excluded from the shot grid. No counts are adjusted to desired totals.

Every roster member, including zero-shot players and all four doubles players,
is displayed. Missing, orphaned and ambiguous hitter IDs remain unresolved.
The panel uses explicit annotation player IDs, not track IDs or court ends.
Duplicate event identity, repeated native contact frame, invalid source range
and invalid frame identity make the profile unavailable rather than silently
dropping or double-counting records. Existing API/schema validation remains.

The source ID, saved revision and current draft/saving state accompany every
profile. Counts immediately follow add/edit/delete, attribution, review-status
changes, save/discard/reload and video selection. Selecting another video resets
the profile filters. Native source jumps use the existing event editor and
preserve contact uncertainty. Source links are paginated in groups of ten;
keyboard controls and text tables accompany the proportional bars. The tables
scroll inside their own region on narrow screens.

Profiles summarize recorded events across the annotation document. They do not
certify that events occur in live play, that all real shots were annotated, or
that reviewed labels are independently correct. Display filters do not alter
JSON/CSV exports: those retain all saved event rows. The profile writes no
annotations, starts no inference and introduces no network service.

## Verification checkpoint

Initial type checking exposed a Windows collision between helper/component
module names that differed only in case. The new pure aggregation and component
are consolidated in `ShotProfile.tsx` within the granted paths. Failed local
check logs are retained. A fresh type check, 250 frontend tests and production
build then passed. An additional regression now refuses repeated native contact
frames. No existing assertion or check was removed.

The first production-browser attempt reached saved correction/export parity,
then its newly added fixture tried to click inside the profile after annotation
reload had recreated the panel closed. The corrected fixture explicitly reopens
it through its native summary, retaining the count, discard and source-jump
assertions. Production behavior and timeouts are unchanged; failed-run evidence
and complete cleanup receipts remain preserved.

The generated pure controls cover the exact family/side matrix, singles and
four-player doubles, zero-shot players, corrected/predicted/missing status,
unknowns, unresolved and ambiguous attribution, invalid identity/frames,
source-frame ordering, mutation safety, corrections and deletion. Production
browser controls cover draft/save/discard and exports, artificial four-player
readings, source seeks, keyboard/mobile operation and pagination. Artificial
readings remain distinct from actual saved generated annotations.

All 251 frontend tests, type checking, production build, API contract and staged
runtime/package parity checks pass. All 21 generated production-editor browser
groups pass, including the profile workflow and existing processing, review,
identity, exports, accessibility and performance coverage. The 390px screenshot
was inspected. Seek/timeline/playback-start p95 were 79.8/31.6/71.7 ms;
animation-frame p95 was 16.8 ms. These are generated local fixture measurements,
not a native-match throughput benchmark; all frozen ceilings are unchanged.

All 5,781 Python tests pass with 4 optional skips, alongside required
lint, formatting, dependency, repository and whitespace checks. Production
delivery passes 19 browser checks, eight library groups and 13 export groups.
A clean locked wheel installation verifies all 108 runtime files, 56 public
manifests, five HTTP assets, three SPA routes and authentication. The first
offline installation lacked a locked dependency in its cache; the separate
clean attempt fetched the unchanged lock into a disposable environment and
passed. Existing environments remain preserved.

Exact-head CI, controller/main verification and complete public package/both-image
delivery remain pending at this checkpoint. The owning issue records final
evidence. This software-only task accesses no private scientific media, labels
or predictions and runs no training or image assessment.
Accepted complete-rally references remain 0/2; full-match accuracy is unproven.
