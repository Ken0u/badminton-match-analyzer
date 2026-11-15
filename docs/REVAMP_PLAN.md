# Revamp plan: upload, name, analyse

Agreed 2026-11-15. Branch `revamp/auto-analysis`, cut from `training/cloud-l4`.

## Goal

The app becomes: upload a video, enter player names, wait, then get a match
page. No review or editing tools on the main path. The match page has two
parts:

- **Watch**: the video with a live overlay (hitter highlight, last stroke
  type and side, rally shot count and time, a mini top-down court with every
  player and the last landing spot; live score once rally outcomes exist).
- **Analysis**: whole-clip statistics (heatmaps, shot breakdowns, landing
  maps, winners and errors, shot quality, skill hexagon).

One safety valve stays: a one-tap "these two players are swapped in this
rally" fix, because identity mistakes move a whole rally's shots to the wrong
person.

## Principles

- **One results file per match.** The pipeline writes a single
  `MatchAnalysis` document. The UI and every statistic read only from it. No
  UI code reads pipeline internals, runs or annotations.
- **Unknown stays unknown.** A value the pipeline did not measure is `null`,
  never a guess. No shuttle speed, height or 3D position until a 3D trajectory
  fit exists (step 7). No winners until the rally-outcome model exists
  (step 3).
- **Court coordinates are metres on the court floor**, from the existing
  automatic court detection. Player positions are the feet, so 2D is accurate.
  The shuttle stays in image coordinates until step 7.
- Existing guidance in `AGENTS.md` (video processing, learning and
  evaluation, verification commands) still applies.

## Name labelling

Names are entered at upload: two for singles, two per team for doubles (so
the app knows partners). After processing, one screen shows a picture of each
person the app found, with the name it guessed; one tap swaps two names. Then
the match page opens. The pipeline cannot know which body carries which name
before it has seen them, so this one confirmation is the minimum.

## Steps

1. **Results format (`MatchAnalysis`).** A versioned pydantic model, its JSON
   Schema and TypeScript types, and a builder that assembles it from what the
   pipeline stores today. Done when the builder produces a valid document for
   the already-processed `singles.mp4` and `doubles.mp4`, with tests on a
   small synthetic fixture.
2. **Automatic pipeline.**
   - 2a. *Persistent identity in the app.* Move the doubles identity method
     (`training/identity_probe.py`, 94% on the DShuttleNet test matches, with
     `models/weights/reid/osnet_doubles_ft1.pth`) into the backend as a
     pipeline stage that gives every person one id through the whole video,
     across camera views. Singles needs the same across end changes.
   - 2b. *One job, no manual steps.* Upload plus names starts one job that
     runs every stage, the identity stage and the `MatchAnalysis` builder,
     and reports one progress value with a stage label. Endpoints for
     creating a match, reading its status and result, and confirming names.
3. **Rally outcomes.** Landing point, who won the rally, and winner versus
   error, trained and checked on ShuttleSet (`getpoint_player`, `win_reason`,
   `lose_reason`, `landing_x/y` per stroke). Fills `rally.outcome` and the live
   score.
4. **Clip statistics.** Plain tested functions over `MatchAnalysis`: position
   heatmaps, contact positions (2D, hitter's feet), landing maps by shot type,
   shot type breakdown per player, rally length distribution, distance
   covered, serve and return stats, shot sequences, doubles formation (front
   and back versus side by side). Once step 3 lands: winners and errors by
   shot type, consistency per shot type.
5. **New UI.** Upload, progress, name confirmation, match page (Watch and
   Analysis). Can start alongside steps 3 and 4 from a real `MatchAnalysis`
   file of `doubles.mp4`. Old editor and library screens leave the main path.
6. **Shot quality.** A model trained on ShuttleSet predicting the hitter's
   chance of winning the rally from the state after a shot (type, landing,
   both players' positions). A shot's quality is how much it changes that
   chance. Gives best and worst shots, strongest and weakest shot, and the
   skill hexagon (attack, net play, defence, consistency, movement,
   placement), scored relative to the other players in the clip.
7. **3D shuttle path.** Fit a physical trajectory between consecutive
   contacts. Gives shuttle speed, contact height and a 3D view.
8. **Far-side partner swaps.** Add a head-crop appearance feature to
   identity. Regression case: `doubles.mp4` 3:53 to 4:14 (two rallies), P1
   and P2 swapped on the far side throughout (distinguishable by hair).

Processing time matters once users wait on one job; the deferred speed-up
work in `docs/INFERENCE_SPEED_NOTES.md` comes back around step 5.

## Not planned

- Live player speed (noisy; distance covered per rally replaces it).
- Model confidence numbers in the main view.
- 3D contact maps before step 7.

## Orchestration

This plan is run by an orchestrating session that briefs subagents, reviews
their commits and records progress below. Subagents working at the same time
own separate files and commit only their own paths.

## Progress

| Step | State | Notes |
|---|---|---|
| 1 | done (b1a0bdf) | `match_analysis.py`, `GET /api/videos/{id}/match-analysis`, `badminton match-analysis` CLI; format in `docs/MATCH_ANALYSIS_FORMAT.md`. Rally boundaries still from a contact-gap rule; `schema.ts` not regenerated yet. |
| 2a | done (4e1a627, a6d21d2) | `persons` pipeline stage (`person_identity.py`); 100% agreement with the research grouping on `doubles.mp4`; regression rally frames 5838-6344. Not re-scored on the DShuttleNet test matches (needs the VM). |
| 2b | done (ae83a29..4e3113f) | `matches` API (`docs/MATCHES_API.md`): upload with names, one job to `needs_names`, name confirmation, per-rally swap overrides, persistent-identity fallback when the re-identification weights are missing. Rally boundaries now prefer the rallies stage's serve and end proposals (schema version 2). End-to-end on both videos with cached perception: 26 s doubles, 19 s singles. |
| 3 | in progress | Rally boundaries, landing point, winner and reason, running score; evaluated on held-out ShuttleSet and doubles matches. VM use approved by the user (2026-11-15). |
| 4 to 8 | not started | User chose step 3 before 4 and 5. |

Open issues found on the way:

- Rally segmentation is not measured. The rallies stage proposes only 14
  serves and 2 ends for the 26 rallies of `doubles.mp4` (7 and 4 of 21 on
  singles); the rest come from the contact-gap fallback. Step 3 should
  measure and improve boundaries before rally-level statistics depend on them.
- `doubles.mp4` 3:53 to 4:14 is two rallies (confirmed by the user), and the
  pipeline splits it correctly (frames 5846-5896 and 6110-6273). The far-side
  P1/P2 swap covers both, so the swap fix is applied once per rally.
- In doubles views where only one partner is found at an end, that player
  gets no person (61 of 27,832 player-track frames on `doubles.mp4`).

Known risk for step 5: perception cache keys hash every non-`.py` file in `backend/badminton`, including `static/build-manifest.json`, so a frontend rebuild into the package would force full re-tracking of every video.
