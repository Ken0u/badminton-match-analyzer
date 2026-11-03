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

The generated pure controls cover the exact family/side matrix, singles and
four-player doubles, zero-shot players, corrected/predicted/missing status,
unknowns, unresolved and ambiguous attribution, invalid identity/frames,
source-frame ordering, mutation safety, corrections and deletion. Production
browser controls cover draft/save/discard and exports, artificial four-player
readings, source seeks, keyboard/mobile operation and pagination. Artificial
readings remain distinct from actual saved generated annotations.

Final full project/browser checks, exact-head CI, controller/main verification
and public package/both-image delivery are pending at this checkpoint. The
owning issue records final evidence. This software-only task accesses no private
scientific media, labels or predictions and runs no training or image assessment.
Accepted complete-rally references remain 0/2; full-match accuracy is unproven.
