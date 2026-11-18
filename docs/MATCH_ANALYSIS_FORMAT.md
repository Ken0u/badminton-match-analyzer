# MatchAnalysis format (schema version 4)

One JSON document per match. The match page and every statistic read only
this document; they never read processing plans, stage runs or annotations.
Models and the builder are in `backend/badminton/match_analysis.py`;
TypeScript types come from the OpenAPI contract in
`backend/frontend/src/api/generated/`.

## Where it lives and how it is made

- File: `<data dir>/<video id>/match_analysis.json`, next to `metadata.json`
  and `timestamps.json`. Local data; not committed.
- Build: the match job (`POST /api/matches`, see `docs/MATCHES_API.md`)
  builds it at the end of processing, and again whenever names are confirmed
  or a rally swap changes. By hand: `python -m badminton.cli match-analysis
  <video id> [--analysis-key KEY] [--identity persons.json]`. Every build
  reads one completed full-match processing plan (the newest, or the one
  given; name and swap edits keep the plan the stored document came from),
  checks the hash of every stage output it reads, applies the match's
  confirmed names and swaps, and writes the file atomically. It runs no
  inference. `--schema` prints the JSON Schema.
- Read: `GET /api/matches/{id}/analysis` or
  `GET /api/videos/{video_id}/match-analysis` return the stored file. They
  never build on request: 404 means the video is unknown or the document has
  not been built yet. A file of an older schema version reads as not built.

## Rules

- **Unknown is `null`**, never a guess. There is no shuttle 3D position
  track. `shot.landing` (last shot of a rally only), `shot.flight` (each
  shot's fitted 3D flight and speed) and `rally.outcome` come from the
  pipeline's outcomes stage and are `null` where it could not tell (see
  "Landing and outcome" and "Shot flight").
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
| `schema_version` | `4` |
| `video` | `id`, `name`, `mode` (singles/doubles), `fps`, `frame_count`, `duration_s`, `width`, `height` |
| `players` | persons: `id` (`P1`..`P4`), `name` (empty until confirmed), `team` (`T1`/`T2`), `handedness` (`null` = unknown), `thumbnail` (path relative to the video's data folder, or `null`; the API serves it at `/api/matches/{id}/players/{person}/thumbnail`) |
| `names_confirmed` | `true` once every player has a confirmed name (see Names) |
| `identity` | how person ids were given: `source` (`persons_stage`, `supplied` or `per_view_fallback`), `method`, `persistent`, `note`, `assignment_count`, `assigned_observation_share` |
| `court` | `geometry` (line positions in metres) and `views` |
| `rallies` | ordered rallies with their shots |
| `tracks` | per-person court positions at 10 Hz and the shuttle per frame |
| `overrides` | user swaps applied to person ids (see Overrides) |
| `warnings` | plain sentences about limits of this document, such as a per-view identity fallback; empty when there are none |
| `provenance` | builder, `created_at`, `analysis_key`, run ids (segments, identities, persons, and per processing window players, shuttle, contacts, rallies, recognition), models |

### `court.views[]`

One per camera range with a court fit: `start_frame`, `end_frame`
(half-open), `corners` (outer court corners in normalized image coordinates,
order far left, far right, near right, near left), `homography` (row-major
3x3; `(x, y, 1)` in normalized image coordinates maps to metres after dividing
by the third component) and `source` (`automatic` or `reviewed`).

### `rallies[]`

`id`, `start_frame`/`end_frame` (inclusive), `start_s`/`end_s`,
`start_source`, `end_source`, `server_id` (hitter of the opening serve, or
`null`), `shots`, `outcome` (see "Landing and outcome"; `null` when
unknown). Rally ids number the rallies in order (`rally-1`,
...) and can change when a rebuild changes the boundaries.

Boundaries come first from the pipeline's rallies stage, which proposes
serves (a quiet player context, then a low launch) and rally ends (the
shuttle settling after flight):

- A serve proposal opens the rally at the earliest contact within 0.5 s of
  it (the serve contact; the proposal marks the launch a few frames later):
  `start_source: proposed_serve`, and that contact's hitter is the server.
  Without such a contact it opens the rally at the proposal frame itself
  when a contact follows within 4 s; the serve contact was missed, so
  `server_id` is `null`. A serve proposal with no contact within 4 s after it
  opens nothing.
- A rally-end proposal after a contact (within 4 s, same camera view, before
  the next rally's start) ends the rally at the proposal frame:
  `end_source: proposed_rally_end`. The next rally then starts at its first
  contact with `start_source: after_proposed_end`, unless a serve proposal
  opens it.
- Where no proposal decides, the fallback applies between two contacts: a
  predicted serve (`predicted_serve`), more than 4 s without a contact
  (`contact_gap`) or a camera cut (`camera_cut`). The video's first rally
  without a proposal has `first_contact`.
- A rally without a proposed end ends at its last contact
  (`end_source: last_contact`); the landing time is then unknown.

The rallies stage abstains often (on `doubles.mp4` it proposes 14 serves and
2 rally ends for 26 rallies; on `singles.mp4` 7 serves and 4 ends for 21), so
many boundaries still come from the fallback. Statistics that care can filter
on the sources.

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
| `landing` | last shot of a rally: where it came down (see "Landing and outcome"); otherwise `null` |
| `flight` | the shot's fitted 3D flight and speed (see "Shot flight"), or `null` |

### Landing and outcome

The outcomes stage (`rally_outcomes.py`) follows the shuttle's image track
after the last contact of each rally and projects the point where it comes
down onto the floor. `landing` has `frame`, `time_s`, `image`, `position`
(metres; `null` more than 2 m outside the court), `in_court` (rally lines:
singles or doubles sidelines, full length), `kind` and `source`. Kinds:
`rest` (the shuttle then lay still), `descent` (it stopped going down),
`track_end` (the track ended in the air; the position is unreliable). The
track is followed through short disappearances and over the top of the
picture, false detections are skipped, and a shuttle that slid or bounced on
is placed where it first met the floor. A camera (focal length and pose) is
recovered from each court view's floor homography: the landing point is taken
on the camera ray a few centimetres above the floor (the shuttle's centre
when it lands) and dropped to the floor. When the track ended in the air, a
3D flight fitted to the track (gravity and air drag, from the hitter) places
the landing if the fit is sure of it. A shuttle caught in the net still
projects to the wrong place. The outcomes stage's stored records also keep
the fitted flight (`landing.flight`: initial speed, apex height, landing
speed and angle, uncertainty); the document gives every shot's speed in
`shot.flight` instead.

`outcome` has `winner_team` (`null` when no identified player stood at the
winning end), `winner_end`, `last_hitter_end`, `reason` (`winner`: the last
hitter won; `error`: the last hitter lost it), `detail` (`in`, `out`, `net`
or `null`), `confidence` (uncalibrated) and `source`: `rule` (the landing
against the lines; a serve against the service lines) or `model` when a
rally outcome model is installed (`provenance.models`). It is `null` when
the last hitter's end or the landing is unknown. Measured accuracy is in
`docs/REVAMP_PLAN.md`; it is not high enough to trust single rallies.

### Shot flight

The outcomes stage fits a 3D flight (gravity and air drag, through the
camera recovered from the court view) to the shuttle's image track from each
contact to the next one (the last shot: to its landing), never across a
camera cut. `shot.flight` has `initial_speed_kmh` (leaving the racket),
`speed_settled_kmh` (0.1 s after the contact), `apex_m` (highest point above
the floor), the fit's `rms` (image heights), `points`, `inliers` and
`observed_s`, and `quality`:

- `good`: the speed is a measurement;
- `speed_bound`: the fit reached its speed limit (440 km/h or more of the
  450 km/h bound). At 30 frames per second the first frames after a hard hit
  do not fix the speed at the racket, so the initial speed is not known
  (about one smash in six on the validation clips). `speed_settled_kmh` is
  still well fixed;
- `poor_fit`: residual above 0.01 image heights or fewer than 5 agreeing
  points; neither speed is a measurement.

`flight` is `null` when no flight could be fitted (no court view, too short
a track). `provenance.shot_flights` says whether the stage fitted flights at
all; when it is `false`, every `flight` is `null` because none was tried.
Speeds order the shot families as expected (net shots and serves slowest,
then block, push, drive, lift, drop, clear and smash), but smash and clear
overlap and single values are rough; the drag caps `speed_settled_kmh` near
120 km/h, so it does not separate the fastest shots either. See
`docs/CLIP_STATS.md` for what the statistics use.

### `tracks`

- `rate_hz`: 10. Sample `k` is time `k / 10` s; `sample_frames[k]` is the
  source frame nearest that time.
- `persons[]`: `person_id`, and `x`/`y` arrays aligned with `sample_frames`
  (metres, `null` when unseen or when two observations claim the person).
- `shuttle`: `x`/`y` arrays with one value per source frame (index = frame),
  `null` when not detected.

A full match stays around half a megabyte (8-minute doubles clip: 0.59 MB
with shot flights, which add about 0.15 kB per shot).

## Identity

By default the identity is the pipeline's persons stage
(`identity.source: persons_stage`, `persistent: true`; see
`backend/badminton/person_identity.py`): every person keeps one id through
the whole video, across camera views and end changes. Its ids are unreviewed;
the name confirmation and the rally swap exist for its mistakes. When the
re-identification weights are missing or do not match the model manifest,
processing still finishes without the persons stage, and the builder uses the
per-view fallback below, with the reason in `identity.note` and in
`warnings`.

An explicit identity input wins over the persons stage
(`source: supplied`): a roster (`persons`: `id`,
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

## Names

Names are entered at upload, by team (partners together), and kept in the
match record (`<data dir>/<video id>/match.json`), never in the persons
document. Until they are confirmed every `players[].name` is empty and
`names_confirmed` is `false`; the API's players endpoint shows the entered
names as a guess (team 1's names on `T1` in id order, team 2's on `T2`).
Confirmation gives each entered name to exactly one person, with doubles
partners on one team; the document is then rebuilt with the names and
`names_confirmed: true`. Names given with a supplied identity input count as
confirmed.

## Overrides

`overrides[]` are the user's corrections, kept in
`<data dir>/<video id>/match_overrides.json` and applied by the builder on
every build, in list order: `kind` (`swap`), `persons` (the two ids),
`start_frame`/`end_frame` (inclusive: the rally's frames when the swap was
made) and `rally_id` (that rally, for reference). Inside the range every
person id the document gives (hitters, servers, `shots[].players`, tracks)
is swapped between the two persons. Overrides are frame ranges, so they
survive rebuilds even when rally ids change; two identical swaps cancel.
