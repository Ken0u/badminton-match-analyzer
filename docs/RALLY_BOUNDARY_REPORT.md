# First full-view rally boundary audit

Prepared October 17, 2026. The first full-court view of each supplied highlight
was selected from the source camera sequence before running perception on those
views. Both include service preparation, an exchange, and stopped play. This
audit records uncertain opening/terminal intervals; it does not provide
exhaustive intermediate contact labels or a reliable serve/end detector.

## Source evidence and limits

The [manifest](../data/manifests/rally_boundary_review.json) retains both source
hashes, inspected views, reviewer provenance, and detailed event notes. Source
overviews sampled singles [255, 639) and doubles [278, 866). Opening/ending
neighborhoods were inspected frame by frame, including native-scale crops of
the racket/terminal regions. The reviewer already knew the earlier doubles
pilot, so this is not a blinded independent benchmark.

| Source boundary | Navigation frame | Inclusive possible frames | Status |
| --- | --- | --- | --- |
| Singles serve, near red player A | 260 | 259–263 | Exact contact/side unadjudicated |
| Singles terminal moment | 612 | 590–620 | Net-fault/ground-contact moment unresolved |
| Doubles serve, far front player | 328 | 325–330 | Exact contact, persistent identity, side unresolved |
| Doubles terminal moment | 816 | 810–824 | Dive/obscured terminal contact needs review |

Navigation frames are convenient source locations, not measured exact event
times. The wide singles terminal interval is intentionally retained: inspecting
the final racket contact and subsequent shuttle/players did not resolve a
precise terminal fault/landing. The doubles near player receives the far player's
serve; that distinction was checked before recording the source events.
The subsequent 3–5 to 4–5 scoreboard update supports a likely live-play
interpretation, but is not itself the ending timestamp.

These are an assistant's first visual pass with human timing/scene/identity
adjudication pending. No model output was copied into the new boundary times.
No live scene range or exhaustive-contact review window is created by the
importer. The original doubles scene remains unknown and unscored. The singles
opening exchange uses a new rally ID; the doubles boundaries use the existing
R1 because the uninterrupted source view includes that pilot's four contacts.
The eight prior shot events and their unknown family/side labels are preserved.

## Annotation gap fixed

Previously, rally endings could not retain structured timing uncertainty. A
reviewer had to choose an exact-looking frame and explain ambiguity only in
notes. `rally_end` now supports `terminal_start_frame`/`terminal_end_frame`, with
inclusive bounds containing its navigation frame. `serve`/`shot` retain their
separate `contact_start_frame`/`contact_end_frame`. The schema rejects missing,
reversed, out-of-source, and wrong-kind intervals.

The editor presents **Rally end timing uncertainty**, preserves bounds while
editing/reloading, and shows them on the timeline. **Use exact rally-end frame**
clears the interval only when the reviewer chooses it. Kind changes clear draft
timing fields to prevent contact-to-terminal carryover. Saved history retains
the previous interval. JSON and CSV export both kinds of uncertainty. Older
records remain readable with null terminal bounds.

The importer verifies original source bytes and the inspected-view bounds,
normalizes navigation times from source PTS, preflights both videos, refuses
conflicting saved IDs, and preserves unrelated annotations. Repeating an
unchanged import is a no-op. Upgrade/restart the server before saving new fields:

```powershell
.\.venv\Scripts\python.exe scripts/import_rally_boundary_review.py
.\.venv\Scripts\python.exe scripts/import_rally_boundary_review.py --apply
```

## Verification and next evidence

The standard suite passes 338 tests with two optional GPU checks skipped.
Contract regressions cover VFR time normalization, paired/inclusive bounds,
source limits, event-kind separation, optimistic revisions, history/JSON/CSV,
source changes, importer conflicts/idempotence, and preserved original labels.
Generated-media browser QA checks invalid paired bounds, add/save/reload,
clearing/restoring terminal uncertainty, kind switching, history, and duplicate
import preservation. All five existing UI browser suites and the separate
real-model recognition browser suite pass. Python/frontend formatting,
dependency consistency, and the built 0.10.0 wheel's schema/export/UI plus
packaged model/license contents were checked. No inference math changed in this
increment.

These intervals are not sufficient for strict boundary F1, complete-rally IoU,
or model training. Adjudicate exact contacts/endings or adopt an explicitly
separate interval metric, label every intermediate contact and difficult
shuttle frame, and confirm live/replay context before evaluation. Then compare
actual source-video player/shuttle/contact inputs with automatic serve/end and
shot predictions. Reliable full-match segmentation, doubles identities and shot
recognition, rare/left-handed strokes, and unseen-match validation remain open.
