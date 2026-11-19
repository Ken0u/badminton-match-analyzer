# Clip statistics (stats version 1)

Whole-clip statistics for the match page's Analysis tab, computed from one
`MatchAnalysis` document (`docs/MATCH_ANALYSIS_FORMAT.md`) and nothing else:
no processing plans, stage runs or annotations. Code and models are in
`backend/badminton/clip_stats.py` (`clip_stats(document)` returns a
`ClipStats`); TypeScript types come from the generated contract in
`backend/frontend/src/api/generated/`.

## Where to get them

- `GET /api/matches/{id}/stats` or `GET /api/videos/{id}/match-stats`:
  computed on request from the stored document and kept in memory while the
  file is unchanged (a doubles match takes about 0.4 s). 404 when the video
  is unknown or the document is not built (or is of an older schema version).
- `python -m badminton.cli clip-stats <video id> [--output stats.json]`, or
  `--analysis match_analysis.json` for a document file; `--schema` prints the
  JSON Schema.

## Rules

- **Unknown is `null`** or left out of a count, never a guess.
- **Every number carries its sample size**: a `Share` is `count` of `n`
  (`share` null when `n` is 0); a `Summary` has `n` and is all null when `n`
  is 0; maps are point lists or grids with `n`. Hide numbers whose `n` is
  thin.
- **No running-score statistics.** Uploads can be whole games or highlight
  reels, so nothing assumes that rallies are consecutive (no streaks, no
  points at game point). Rallies won are counted per rally.
- **Person ids are the document's**, with its swap overrides already applied,
  so every number follows the user's corrections. Rebuilding the document
  after a swap or name change gives new statistics.
- With a per-view fallback identity (`identity_persistent: false`) per-player
  and per-team numbers mix people after an end change; `warnings` says so.
- Model scores (`confidence`, `family_score`) are not probabilities and are
  never averaged here.
- **Shot labels**: a shot family (clear, drive, smash, net, drop, lift, block,
  push, net_kill, other), `serve_short`, `serve_long`, `serve` (type
  unknown) or `unknown`.
- **Court maps** are in the document's court metres turned so the player is
  at the near end (y from 6.7 to 13.4): a point at the far end is rotated by
  half a turn about the court centre (x to 6.1 - x, y to 13.4 - y), which
  keeps the player's own left and right. Landings and `returned_at` points
  are turned by the hitter of the shot, so they show at the far end.

## Top level

| Field | Contents |
|---|---|
| `stats_version` | `1` |
| `video_id`, `mode` | as in the document |
| `analysis_schema_version`, `analysis_created_at`, `analysis_key` | the document these were computed from |
| `identity_persistent` | `false` for the per-view fallback identity |
| `shot_flights` | `false` when the document has no shot flights: every `speeds` is null |
| `clip` | whole-clip numbers (below) |
| `players` | one `PlayerStats` per person (`person_id`, `team`, `name`) |
| `teams` | one `TeamStats` per team (`person_ids`, `names`); in singles the same numbers as its player, plus rallies won |
| `warnings` | the document's warnings and the statistics' own (no court view, no flights, per-view identity) |

## Whole clip (`clip`)

- `rallies`, `contacts`, `unattributed_contacts` (no hitter: left out of
  every per-player number).
- `rally_shots`: contacts per rally, a `Distribution` (summary plus histogram
  with one bin per count from 1 to 30; `above` counts longer rallies).
- `rally_seconds`: `end_s - start_s`, 2 s bins to 40 s. A rally ends at the
  landing when one was found, else at a proposed rally end or its last
  contact; `rallies_ended_at_landing` says how many ended at the landing
  (the others are a little short).
- `outcomes_known`: rallies with an outcome.
- `shots`: the shot breakdown below, for every contact.
- `landings`: every rally-ending shot with a landing position (see Landings).
- `pairs`, `triples`: the 15 most common sequences of two and three
  consecutive shot labels within a rally, each with `count` of `n` eligible
  sequences. A sequence is eligible when every label is known and no two
  consecutive shots are by the same team (that is a contact or identity
  mistake).
- `speeds`: speed by shot label (see Shot speed).
- `outcome_conflicts`: rallies whose outcome gives the rally to the last
  hitter's opponents while calling it the last hitter's winner (or the
  reverse); they are left out of the finish numbers.

## Per player and per team

`PlayerStats` and `TeamStats` share these fields (a team adds its partners
together):

- `shots` (`ShotBreakdown`): `contacts`, `serves`, `shots` (contacts
  recognised as shots), `unknown_kind`; `families` and `sides` (forehand,
  backhand, unknown) as shares of `shots`; `forehand_by_family`: the forehand
  share of each family's shots with a known side; `serve_types` as shares of
  `serves`.
- `contacts`: the hitter's feet at each contact (`Spot`: `x`, `y`, `label`,
  `side`, `person_id`, `rally_id`, `shot_id`).
- `returned_at`: for each of this side's shots that the other side played,
  the other side's hitter's feet at that next contact. It shows where the
  shot took the opponent; it is not where the shuttle would have landed.
- `landings`: this side's rally-ending shots (Landings).
- `positions`: a heatmap `Grid` of the 10 Hz track samples during rallies
  (from each rally's start to its end), feet, turned to the near end.
  Half-metre cells, 12 across and 26 along the court, plus two cells beyond
  every line; `counts[row][column]` with rows along y. `n` samples are on the
  grid, `outside` beyond it, `seconds` is `n / 10`.
- `distance`: distance covered (Distance).
- `serve`: `serves` (rallies this side opened with a serve), `serve_types`,
  `positions` (server's feet), `won` (of those rallies with a known winner,
  won by the serving side), `faults` (the serve ended the rally and the
  server lost it) and `unreturned` (the serve ended the rally and the server
  won it: often a missed return contact rather than an ace), both of the
  serves whose result is known.
- `receive`: the shot after the other side's serve when this side played
  it: `returns`, `families` (labels as shares of returns), `positions`, `won`
  (of those rallies with a known winner, won by this side).
- `finish`: rally-ending shots with a known outcome: `ended`, `winners`,
  `errors` (shares of `ended`), and `by_label`, per shot label:
  `played` (every shot of the label, except rally-ending shots whose outcome
  is unknown), `winners`, `errors`, `errors_out`, `errors_net`,
  `consistency` (shots that were not errors, of `played`) and `winner_rate`
  (winners of `played`). A winner is the last hitter's: the shot ended the
  rally and the hitter's side won it.
- `speeds`: speed by shot label (Shot speed), null without flights.
- `replies`: the 10 most common (other side's shot, this side's reply) label
  pairs, `count` of `n` eligible pairs whose reply is this side's.

`TeamStats` adds `rallies_won` (of rallies with a known winning team),
`won_by_winner` (this team's last hitter hit a winner), `won_by_opponent_error`
and, in doubles, `formation`.

### Landings

Only a rally's last shot has a landing in the document, so landing maps are
rally-ending shots: `LandingSpot` adds `in_court`, `kind` (`rest` or
`descent`) and `result` (the last hitter's `winner` or `error`, null when
unknown). Landings whose track ended in the air (`track_end`) or that lie
more than 2 m outside the court are left off: their position is unreliable.
A landing is turned by the last hitter's end (the hitter at the near end),
so landed-in winners show in the far half and net errors in the near half.
`result` is the outcome's call, which can disagree with the landing against
the lines (the outcome model also reads the shuttle and players); show
`result` when the two differ. Where the other shots of a rally would have
landed is not measured: the fitted flights of intercepted shots are
extrapolated and even real landings from the fit alone are off by a median
0.45 m, so they are not used.

### Distance

From the 10 Hz feet tracks, per person and rally, over the rally's samples:

1. A sample more than 7 m/s from both neighbours is a tracking glitch (a box
   jump or an identity flip) and is dropped.
2. Gaps up to 0.5 s are bridged by a straight line; a longer gap, or a step
   faster than 7 m/s, ends a tracked span. Untracked time is not counted.
3. Each span is smoothed with a centred 3-sample (0.3 s) moving average, then
   its path length is added.

`distance` gives `total_m` (every tracked span of every rally: a lower bound
when coverage is below 1), `tracked_s`, `rally_s`, `coverage`,
`per_minute_m` (total per tracked minute, the steadiest number),
`per_rally` (every rally's metres and coverage) and `rally_m`, a summary of
the rallies tracked at least 80% of their time. A team's distance adds both
partners; its rally coverage is the lower of the two.

Feet jitter is the main error. Waiting for the serve, a player's feet move
a median 5 to 7 cm between samples on the supplied videos, which unsmoothed
would add about 0.5 m/s. The 3-sample average cuts that
jitter's path length about threefold while keeping about 87% of 1 Hz
footwork. On the two supplied videos the per-player total moves with the
smoothing: doubles 330 m unsmoothed, 272 m (used), 237 m with 5 samples;
singles 444, 380 and 337 m. Use distance to compare players and rallies
within a clip; absolute values carry an uncertainty of roughly 15%.

### Doubles formation

`formation` (doubles teams only) classifies every track sample during
rallies with both partners tracked: `front_back` when they are farther apart
along the court than across it, `side_by_side` otherwise, and `close` (not
classified) when they stand within 1 m. `all`, `attacking` and `defending`
each give the two as shares of the classified samples. The phase follows the
last shot played before the sample: after this team's smash, net kill or
drop it is attacking; after its lift, clear or long serve it is defending;
after the other team's such shots it is the reverse; after other shots
(drive, push, block, net, short serve, unknown) there is no phase.
`seconds` is the time with both partners tracked.

### Shot speed

From each shot's fitted 3D flight (`shot.flight` in the document; see "Shot
flight" there). `speeds[label]` gives `shots`, `fitted` (with a flight),
`good`, `speed_bound` and `poor_fit` counts, `initial_kmh` (distribution
over good fits only, 20 km/h bins), `settled_kmh` (0.1 s after the contact,
over good and speed-bound fits, which fix it well) and `apex_m` (good fits).
Speed summaries leave `min` and `max` null: single fits are too rough to name
a fastest or slowest shot. The flight's launch diagnostics
(`launch_supported`, `early_speed_kmh`, `settled_supported`) are not used:
they never drop or replace a speed. A continuing shot whose fit passes below
the net is `poor_fit` and so counts only in `poor_fit`.

What speeds are good for: comparing shot types and players within one clip
(the same camera), by median. On the validation clips the medians come in
the expected order (net 36, serve 40, block 52, push 78, drive 86, lift 93,
drop 102, clear 172, smash 180 km/h) but smash and clear overlap, and at 30
frames per second 14 to 19% of smash fits stop at the fit's 450 km/h bound; those are counted in `speed_bound` and left out of
`initial_kmh`, so a smash median is computed from the fits that were not at
the bound and is biased low. A few fits of slow shots come out far too fast
(a short serve at 220 km/h), so the 90th percentile is rough too.
`settled_kmh` is well measured but drag caps it near 120 km/h, so it does
not separate the fastest shots either. The fit now takes the contact time
to a fraction of a frame where the tracks allow it
(`docs/SHUTTLE_LAUNCH_TIMING.md`); the medians above are from before that
change (see "On the supplied videos" for after).

## Not included

- Running-score statistics (game points, streaks, comebacks): footage may
  not be continuous.
- Landing points of shots that did not end the rally (see Landings).
- Fastest or slowest single shot (see Shot speed).
- Contact height and 3D shuttle paths: the flight's start height is held
  near racket height by the fit's prior, so it is not reported.
- Per-player rallies won in doubles: rallies are won by teams.

## On the supplied videos

Stats version 1 on the two supplied videos as re-processed on 2026-11-17
(doubles event model v5, singles event model v3, outcome model v3), with the
outcomes stage re-run with shot flights:

- `doubles.mp4` (8 min, 27 rallies, 318 contacts): rallies median 9 shots
  and 6.6 s; distance per player 253 to 295 m over 212 s of rallies (73 to
  85 m per minute), a median 7 to 9 m per rally; teams front-back 60 to 66%
  of the time when attacking and side by side 79 to 83% when defending;
  most common pair lift then smash (35 of 291); speed medians block 46,
  drive 96, lift 118, smash 165 km/h (5 of 53 smash fits at the bound).
- `singles.mp4` (8 min, 21 rallies, 258 contacts): rallies median 12 shots
  and 10.9 s; distance per player 371 and 390 m over 230 s (97 and 102 m per
  minute), a median 18 to 19 m per rally; net shots the most common family
  (81 of 241 shots); speed medians net 33, lift 93, smash 204 km/h (5 of 35
  at the bound).

Fitting the flights took 70 s (singles) and 64 to 110 s (doubles, the
higher figure with other jobs running) per match.

Re-run of the outcomes stage on 2026-11-19 with the sub-frame contact clock
and the net check (`docs/SHUTTLE_LAUNCH_TIMING.md`,
`docs/CONTINUING_FLIGHT_NET_QUALITY.md`); names, swaps, rally counts and
winners unchanged. Shares are of fitted shots, medians of good fits, before
and after:

| | doubles before | doubles after | singles before | singles after |
|---|---:|---:|---:|---:|
| fitted shots | 296 | 296 | 251 | 250 |
| good | 93.6% | 91.6% | 95.2% | 91.2% |
| speed_bound | 2.0% | 1.7% | 2.0% | 0.8% |
| poor_fit (below the net) | 4.4% | 6.8% (9) | 2.8% | 8.0% (13) |
| smash median, km/h | 165 | 199 | 204 | 252 |
| drive | 96 | 116 | 96 | 96 |
| lift | 118 | 110 | 93 | 92 |
| drop | 101 | 101 | 71 | 127 |
| block | 46 | 47 | 49 | 51 |
| net | 38 | 39 | 33 | 33 |

Hard shots come out faster, as the synthetic check predicts for removing
the late clock; there are no reference speeds for these videos, so whether
each median is closer to the truth is not measured.
