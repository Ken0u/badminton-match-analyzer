# MatchAnalysis format (schema version 1)

One JSON document per match. The match page and every statistic read only
this document; they never read processing plans, stage runs or annotations.
Models and the builder are in `backend/badminton/match_analysis.py`;
TypeScript types come from the OpenAPI contract in
`backend/frontend/src/api/generated/`.

## Where it lives and how it is made

- File: `<data dir>/<video id>/match_analysis.json`, next to `metadata.json`
  and `timestamps.json`. Local data; not committed.
- Build: `python -m badminton.cli match-analysis <video id>
  [--analysis-key KEY] [--identity persons.json]`. It reads the newest
  completed full-match processing plan (or the one given), checks the hash of
  every stage output it reads, and writes the file atomically. It runs no
  inference. `--schema` prints the JSON Schema.
- Read: `GET /api/videos/{video_id}/match-analysis` returns the stored file.
  It never builds on request: 404 means the video is unknown or the document
  has not been built yet. Step 2b's processing job will build it at the end.

## Rules

- **Unknown is `null`**, never a guess. Version 1 has no shuttle speed,
  height or 3D position; `shot.landing` and `rally.outcome` are always `null`
  (step 3 fills them).
- **Frames** are source frame indices; `time_s` and `*_s` are source seconds
  from `timestamps.json`. Ranges are half-open unless noted.
- **Court metres**: x across the court, 0 to 6.1, from the far-left outer
  (doubles) sideline; y along the court, 0 to 13.4, from the far baseline;
  net at y = 6.7. "Far" is the end away from the camera. Singles sidelines are
  x = 0.46 and 5.64.
- **Player positions** are the bottom centre of the person box (the feet),
  projected through the camera view's homography. Positions more than 2 m
  outside the outer lines, or in frames without a court fit, are `null`.
- **Shuttle positions** are normalized image coordinates (0..1 of the frame
  width and height), not court positions.
- Scores (`confidence`, `family_score`, `side_score`) are uncalibrated model
  outputs, not probabilities of being right.

## Top level

| Field | Contents |
|---|---|
| `schema_version` | `1` |
| `video` | `id`, `name`, `mode` (singles/doubles), `fps`, `frame_count`, `duration_s`, `width`, `height` |
| `players` | persons: `id` (`P1`..`P4`), `name` (empty until confirmed), `team` (`T1`/`T2`), `handedness` (`null` = unknown), `thumbnail` (path relative to the video's data folder, or `null`) |
| `identity` | how person ids were given: `source` (`supplied` or `per_view_fallback`), `method`, `persistent`, `note`, `assignment_count`, `assigned_observation_share` |
| `court` | `geometry` (line positions in metres) and `views` |
| `rallies` | ordered rallies with their shots |
| `tracks` | per-person court positions at 10 Hz and the shuttle per frame |
| `provenance` | builder, `created_at`, `analysis_key`, run ids per processing window, models |

### `court.views[]`

One per camera range with a court fit: `start_frame`, `end_frame`
(half-open), `corners` (outer court corners in normalized image coordinates,
order far left, far right, near right, near left), `homography` (row-major
3x3; `(x, y, 1)` in normalized image coordinates maps to metres after dividing
by the third component) and `source` (`automatic` or `reviewed`).

### `rallies[]`

`id`, `start_frame`/`end_frame` (inclusive: the first and last detected
contact), `start_s`/`end_s`, `server_id` (hitter of the opening serve, or
`null`), `shots`, `outcome` (`null`; later `winner_team`, `reason`
winner/error, `source`).

A new rally starts at each predicted serve, after 4 s without a contact, or at
a camera cut between two contacts. A rally that does not open with a serve
has `server_id: null`. The true rally end (landing) is unknown in version 1.

### `rallies[].shots[]`

| Field | Contents |
|---|---|
| `id`, `frame`, `time_s` | contact identity and time (`shot-<frame>`) |
| `kind` | `serve`, `shot`, or `null` |
| `hitter_id` | person id or `null` |
| `family` | shots only: clear, drive, smash, net, drop, lift, block, push, net_kill, other; `null` for serves and unknowns |
| `side` | `forehand`, `backhand` or `null` |
| `serve_type` | serves only: `short`, `long` or `null` |
| `confidence` | contact detection score |
| `family_score` | score of the predicted serve class or shot family |
| `side_score` | score of the predicted side |
| `hitter_position` | the hitter's feet in metres at contact (nearest frame within 3), or `null` |
| `players` | every player seen with a court position at the contact frame: `person_id` (or `null`) and `position` |
| `shuttle` | shuttle image position at contact (nearest frame within 2), or `null` |
| `landing` | `null` (step 3) |

### `tracks`

- `rate_hz`: 10. Sample `k` is time `k / 10` s; `sample_frames[k]` is the
  source frame nearest that time.
- `persons[]`: `person_id`, and `x`/`y` arrays aligned with `sample_frames`
  (metres, `null` when unseen or when two observations claim the person).
- `shuttle`: `x`/`y` arrays with one value per source frame (index = frame),
  `null` when not detected.

A full match stays around half a megabyte (8-minute doubles clip: 0.53 MB).

## Identity

The builder takes an optional identity input: a roster (`persons`: `id`,
`team`, optional `name`, `handedness`, `thumbnail`) and track assignments in
the `TrackAssignment` shape (`run_id`, `track_id`, `start_frame`,
`end_frame` half-open, `player_id`) that map each processing window's player
tracks to persons. Extra keys are ignored, so step 2a's per-video persons
artifact can be passed as it is. The assignments are checked like annotation
track assignments (no overlaps, known persons, inside the video).

Without an identity input the builder uses a **per-view fallback that is not
persistent identity**: in each camera view (between cuts) the far-end
player(s) become `P1` (and `P2`), the near-end player(s) `P2` (singles) or
`P3` and `P4` (doubles). Tracks are grouped by the processing's own
continuity ids; partners at one end are kept apart by a free slot and their
side of the court. After an end change or a cut the same id can name a
different human. `identity.persistent` is `false` and `identity.note` says so;
per-person statistics over a whole match need a supplied identity.
