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
| 3 | first version done (d1d86bf..77e2b77); winner accuracy not good enough yet | `outcomes` stage (`rally_outcomes.py`), schema version 3, harness `training/rally_eval.py`. Validation clips, about 16 minutes each, outcome model v1 (the rule in brackets). ShuttleSet, 5 clips, 144 rallies: 96.5% matched one to one, winner right 83% of all rallies (70%), last hitter 90%, landing median error 0.34 m. DShuttleNet, 5 clips, 138 rallies: 93.5% matched, winner right 76% (64%), last hitter 77%, landing 0.57 m. The running score is right after only 15 to 17% of rallies, because one wrong winner shifts every later score. Wrong winners: about half are line calls with the right last hitter (half of the labelled in/out landings in singles lie within 0.3 m of a line), the rest a wrong or missed last contact and missed rallies. The outcome model (`.cache/step3/rally_outcome_v1.json`) is not installed, so the app uses the rule. Test clips are processed on the VM (`/data/step3`) but not scored. Clip `ds-52` failed in processing: "One player cannot be assigned to overlapping tracks". Results in `.cache/step3/eval/`. **Second pass (21c9786..9a4a74a):** landing fixes (slide after impact, shuttle over the top of the picture, hidden mid-fall, false detections, service lines) and a sequence outcome model (`rally_outcome_model.py`: shuttle and players from 1.0 s before to 1.6 s after the last contact; candidate `.cache/step3/rally_outcome_sequence_v2.json`, not installed). Same validation clips, end to end: winner right 85.4% of all singles rallies (123 of 144) and 81.9% of doubles (113 of 138); landing median error 0.32 m and 0.37 m; running score right after 37 and 40 rallies. With the published last hit: 90.3% singles (381 of 422), 90.3% doubles (458 of 507). Choices were made on training matches; test still unscored. `rally_labels.py` read DShuttleNet's `score_team` per match instead of per set (fixed in d3fe62b): model v1 was trained on wrong doubles winners in a sixth of rallies; the end-to-end numbers above are unaffected. Largest remaining loss: wrong or missed last contact and unmatched rallies (16 of the 46 wrong winners); then line calls. Results in `.cache/step3/eval2/`. **Installed (2026-11-17):** the sequence model retrained on every training match for the fixed 12 epochs (`--all-training`) is registered as `rally_outcome` in the model manifest (`models/weights/rally_outcome_sequence_v2.json`, git-ignored). Validation after the retrain: 90.8% singles (383 of 422) and 90.3% doubles (458 of 507) with the published last hit; end to end 86.8% singles (125 of 144) and 80.4% doubles (111 of 138), the same as before within two rallies. **Third pass (232bae9):** the rule that drops a rally's last contact when the shuttle barely moves afterwards also dropped net shots and mishits (7.7% of singles and 3.0% of doubles true last contacts on the training matches); it now also needs the shuttle not to rise (10 of 4,910 dropped). Validation end to end: last hitter 135 of 141 matched singles rallies (was 129) and 109 of 130 doubles (was 106); winner right 89.6% singles (129 of 144, was 125) and 79.7% doubles (110 of 138, was 111: the one doubles loss now has the right last hitter and the outcome model calls the landing out); landing median 0.29 m and 0.37 m; running score right after 39 and 21 rallies (doubles was 26, from that one rally). A rule dropping the weaker of two same-end serves within 1.5 s was rejected: on the training matches it drops the true serve more often than a false one (29 against 15). Results in `.cache/step3/eval3/`. **Fourth pass (doubles missed rallies and last hitter), no code change:** the 8 missed doubles rallies (and 1 of 3 singles) had nothing perceived because court detection rejected their camera range (court found only partway into the range, or found everywhere but moving), so the players stage skipped it; the fix is in court detection and needs the clips re-run through the players stage (VM). Of 21 doubles rallies with the wrong last hitter, 12 miss the last hit and 7 add a false contact 0.2-0.35 s after it at the other end. Five rule changes chosen on training rallies (settle span, dropping a quick weak final contact, recovering a 0.3-0.6 final contact, shuttle reversal, contact after the shuttle landed) gave no gain there, so none was kept. The doubles event model finds the labelled last hit in 95.9% of training rallies but 91.3% of validation rallies (all hits 97.2% vs 96.9%), so last-hit recall on unseen matches is the lever: retraining the doubles event model (for example with last hits weighted, or out-of-fold scores to set thresholds honestly) is the next step, not a rule. Results in `.cache/step3/eval4/`. **Fifth pass, part 1 (court fix, 1939155):** the court detector's agreement tolerance goes from 0.012 to 0.025 (share of the frame): fits of a still camera 0.1 s apart scatter by more than 0.012 (`training/court_jitter.py`, nine DShuttleNet training matches and the two supplied videos, 699 pairs: 3.4% over 0.012, 1.7% over 0.025, 1.3% over 0.05), so still broadcast views were rejected as moving. Validation clips re-run on the VM (players stage and later; shuttle reused), installed models, end to end: doubles rallies matched 130 to 137 of 138 (missed 8 to 1; the one left is a one-hit rally), extra 9 to 9, last hitter 109 to 117, winner 110 to 115 (79.7% to 83.3%), running score right after 21 to 29 rallies, landing median 0.37 to 0.34 m; singles unchanged (winner 129 of 144, 89.6%; score 39). User videos re-run locally: `doubles.mp4` still 26 rallies (the extra is the between-rally tap at 5:34.9; 3:53 to 4:14 still two rallies), `singles.mp4` still 21. **Part 2 (doubles event model retrained for the last hit, finished 2026-11-17):** five out-of-fold models and a final model each for the v4 recipe (A) and v4 with last-hit and after-last-hit loss weight 3 (B) (`training/gcp/last_hit_folds.sh`); cut-off chosen out of fold (most rallies with the last hit found and no contact after it): 0.7 for both. Out of fold, 2,751 doubles training rallies: last hit found 86.3% (A) and 87.4% (B), found with nothing after it 80.8% and 82.0%, all contacts precision 0.93 and recall 0.93 for both. Validation end to end (singles unchanged for all: winner 129 of 144, score 39): installed v4 winner 115 of 138 (83.3%), last hitter 117, extra 9, score 29; A winner 118 (85.5%), last hitter 121, missed 2, extra 10, score 24; B winner 118 (85.5%), last hitter 119, missed 2, extra 12, score 16. A retrained with the same recipe as v4 differs from it by 3 rallies, so seed noise is about as large as the gain; B leads A out of fold, A leads B on the five validation clips. Not installed yet (needs the user's yes in the session); candidates on the laptop in `.cache/step3/eval5/results/folds/{A,B}/cand/`. |
| 4 to 8 | not started | User chose step 3 before 4 and 5. |

Open issues found on the way:

- Rally segmentation is not measured. The rallies stage proposes only 14
  serves and 2 ends for the 26 rallies of `doubles.mp4` (7 and 4 of 21 on
  singles); the rest come from the contact-gap fallback. Step 3 should
  measure and improve boundaries before rally-level statistics depend on them.
- `doubles.mp4` 3:53 to 4:14 is two rallies (confirmed by the user), and the
  pipeline splits it correctly (frames 5846-5896 and 6110-6273). The far-side
  P1/P2 swap covers both, so the swap fix is applied once per rally.
- `doubles.mp4` has 25 rallies (counted by the user, 2026-11-17); the pipeline
  finds 26. The extra one is frames 8373-8422 (5:34.9 to 5:36.9): two contacts
  opened by the contact-gap fallback during the shot-clock countdown between
  rallies, a player tapping the shuttle back. No rule for it was kept: short
  rallies without a serve are common in the training labels and between-rally
  play cannot be measured on the training data held locally.
- In doubles views where only one partner is found at an end, that player
  gets no person (61 of 27,832 player-track frames on `doubles.mp4`).

Known risk for step 5: perception cache keys hash every non-`.py` file in `backend/badminton`, including `static/build-manifest.json`, so a frontend rebuild into the package would force full re-tracking of every video.
