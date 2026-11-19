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
| 3 | first version done (d1d86bf..77e2b77); winner accuracy not good enough yet | `outcomes` stage (`rally_outcomes.py`), schema version 3, harness `training/rally_eval.py`. Validation clips, about 16 minutes each, outcome model v1 (the rule in brackets). ShuttleSet, 5 clips, 144 rallies: 96.5% matched one to one, winner right 83% of all rallies (70%), last hitter 90%, landing median error 0.34 m. DShuttleNet, 5 clips, 138 rallies: 93.5% matched, winner right 76% (64%), last hitter 77%, landing 0.57 m. The running score is right after only 15 to 17% of rallies, because one wrong winner shifts every later score. Wrong winners: about half are line calls with the right last hitter (half of the labelled in/out landings in singles lie within 0.3 m of a line), the rest a wrong or missed last contact and missed rallies. The outcome model (`.cache/step3/rally_outcome_v1.json`) is not installed, so the app uses the rule. Test clips are processed on the VM (`/data/step3`) but not scored. Clip `ds-52` failed in processing: "One player cannot be assigned to overlapping tracks". Results in `.cache/step3/eval/`. **Second pass (21c9786..9a4a74a):** landing fixes (slide after impact, shuttle over the top of the picture, hidden mid-fall, false detections, service lines) and a sequence outcome model (`rally_outcome_model.py`: shuttle and players from 1.0 s before to 1.6 s after the last contact; candidate `.cache/step3/rally_outcome_sequence_v2.json`, not installed). Same validation clips, end to end: winner right 85.4% of all singles rallies (123 of 144) and 81.9% of doubles (113 of 138); landing median error 0.32 m and 0.37 m; running score right after 37 and 40 rallies. With the published last hit: 90.3% singles (381 of 422), 90.3% doubles (458 of 507). Choices were made on training matches; test still unscored. `rally_labels.py` read DShuttleNet's `score_team` per match instead of per set (fixed in d3fe62b): model v1 was trained on wrong doubles winners in a sixth of rallies; the end-to-end numbers above are unaffected. Largest remaining loss: wrong or missed last contact and unmatched rallies (16 of the 46 wrong winners); then line calls. Results in `.cache/step3/eval2/`. **Installed (2026-11-17):** the sequence model retrained on every training match for the fixed 12 epochs (`--all-training`) is registered as `rally_outcome` in the model manifest (`models/weights/rally_outcome_sequence_v2.json`, git-ignored). Validation after the retrain: 90.8% singles (383 of 422) and 90.3% doubles (458 of 507) with the published last hit; end to end 86.8% singles (125 of 144) and 80.4% doubles (111 of 138), the same as before within two rallies. **Third pass (232bae9):** the rule that drops a rally's last contact when the shuttle barely moves afterwards also dropped net shots and mishits (7.7% of singles and 3.0% of doubles true last contacts on the training matches); it now also needs the shuttle not to rise (10 of 4,910 dropped). Validation end to end: last hitter 135 of 141 matched singles rallies (was 129) and 109 of 130 doubles (was 106); winner right 89.6% singles (129 of 144, was 125) and 79.7% doubles (110 of 138, was 111: the one doubles loss now has the right last hitter and the outcome model calls the landing out); landing median 0.29 m and 0.37 m; running score right after 39 and 21 rallies (doubles was 26, from that one rally). A rule dropping the weaker of two same-end serves within 1.5 s was rejected: on the training matches it drops the true serve more often than a false one (29 against 15). Results in `.cache/step3/eval3/`. **Fourth pass (doubles missed rallies and last hitter), no code change:** the 8 missed doubles rallies (and 1 of 3 singles) had nothing perceived because court detection rejected their camera range (court found only partway into the range, or found everywhere but moving), so the players stage skipped it; the fix is in court detection and needs the clips re-run through the players stage (VM). Of 21 doubles rallies with the wrong last hitter, 12 miss the last hit and 7 add a false contact 0.2-0.35 s after it at the other end. Five rule changes chosen on training rallies (settle span, dropping a quick weak final contact, recovering a 0.3-0.6 final contact, shuttle reversal, contact after the shuttle landed) gave no gain there, so none was kept. The doubles event model finds the labelled last hit in 95.9% of training rallies but 91.3% of validation rallies (all hits 97.2% vs 96.9%), so last-hit recall on unseen matches is the lever: retraining the doubles event model (for example with last hits weighted, or out-of-fold scores to set thresholds honestly) is the next step, not a rule. Results in `.cache/step3/eval4/`. **Fifth pass, part 1 (court fix, 1939155):** the court detector's agreement tolerance goes from 0.012 to 0.025 (share of the frame): fits of a still camera 0.1 s apart scatter by more than 0.012 (`training/court_jitter.py`, nine DShuttleNet training matches and the two supplied videos, 699 pairs: 3.4% over 0.012, 1.7% over 0.025, 1.3% over 0.05), so still broadcast views were rejected as moving. Validation clips re-run on the VM (players stage and later; shuttle reused), installed models, end to end: doubles rallies matched 130 to 137 of 138 (missed 8 to 1; the one left is a one-hit rally), extra 9 to 9, last hitter 109 to 117, winner 110 to 115 (79.7% to 83.3%), running score right after 21 to 29 rallies, landing median 0.37 to 0.34 m; singles unchanged (winner 129 of 144, 89.6%; score 39). User videos re-run locally: `doubles.mp4` still 26 rallies (the extra is the between-rally tap at 5:34.9; 3:53 to 4:14 still two rallies), `singles.mp4` still 21. **Part 2 (doubles event model retrained for the last hit, finished 2026-11-17):** five out-of-fold models and a final model each for the v4 recipe (A) and v4 with last-hit and after-last-hit loss weight 3 (B) (`training/gcp/last_hit_folds.sh`); cut-off chosen out of fold (most rallies with the last hit found and no contact after it): 0.7 for both. Out of fold, 2,751 doubles training rallies: last hit found 86.3% (A) and 87.4% (B), found with nothing after it 80.8% and 82.0%, all contacts precision 0.93 and recall 0.93 for both. Validation end to end (singles unchanged for all: winner 129 of 144, score 39): installed v4 winner 115 of 138 (83.3%), last hitter 117, extra 9, score 29; A winner 118 (85.5%), last hitter 121, missed 2, extra 10, score 24; B winner 118 (85.5%), last hitter 119, missed 2, extra 12, score 16. A retrained with the same recipe as v4 differs from it by 3 rallies, so seed noise is about as large as the gain; B leads A out of fold, A leads B on the five validation clips. **Installed (2026-11-17, 3156dad):** B as `models/weights/events_doubles.pt` (method "learned doubles event model v5"); the previous model is kept as `events_doubles_v4.pt`. **Sixth pass (3D flight, 06d038b..072eac7):** `shuttle_flight.py` recovers a pinhole camera (focal length and pose; principal point at the centre, square pixels) from each court view's floor homography and fits a 3D shuttle flight (gravity plus quadratic drag, terminal velocity 6.7 m/s, robust numpy least squares, start near the hitter's feet at a racket height, flight starting at the image track's turn near the contact) between contacts, with the landing on the floor or the net, initial speed, apex, landing speed and angle and the landing's uncertainty from the fit covariance (`sigma_m`). Camera: every court view of the 10 validation clips gave one; vertical field of view per clip 10.6-18.8 degrees, steady within a clip (10-90% spread of the camera position 0.1 m across, 0.7-1.8 m along the court, 0.2-0.5 m in height); the four-corner homography is reproduced to under 0.001 image heights; players measured through it stand 1.62-1.80 m to the box top and 1.43-1.54 m to the nose (clip medians), as expected for players in play. Landing, training matches (labelled in/out landings; choices on the fit fold, confirmed on the check fold): the image landing projected through the floor homography lies a median 0.17-0.19 m too far from the camera, because the tracked point is the shuttle's centre, still above the floor when it lands. Putting it on the camera ray 5 cm up and dropping it (kept; 3 to 12 cm tried, 5 cm has no bias) cuts the median error from 0.31 to 0.23 m in singles and 0.29 to 0.18 m in doubles, and lifts the landing rule's in/out call for landings within 0.3 m of a line from 72% to 77% (singles) and 72% to 78% (doubles). The fitted 3D landing alone is worse (median 0.45-0.46 m, 0.2-0.3 m towards the camera; terminal velocity 5.5 and 8 m/s were worse still), so it is kept only for tracks that end in the air with `sigma_m` at most 0.35 m (2.7% of landings; no measurable change) and as outcome-model features. Outcome model, check fold with the published last hit (winner right; rule in brackets): v2 design 385/420 singles and 586/643 doubles (83%, 80%); placed landing 379 and 590 (84%, 82%); placed landing plus 13 flight features 383 and 593, the lowest check loss (0.211 against 0.224). That design retrained on every training match is `rally_outcome_sequence_v3.json`, **installed 2026-11-17 (fb4d226)** as `rally_outcome` in the model manifest; v2 stays in the weights folder. Validation, published last hit: v3 90.5% singles (382 of 422) and 91.5% doubles (464 of 507); v2 90.8% and 90.3%. Validation end to end (installed event models; court-fixed clips in `.cache/step3/val5`, reproduced locally): before, winner 129 of 144 singles (89.6%) and 118 of 138 doubles (85.5%), score 39 and 16; installed v2 with the placed landing 130 (90.3%) and 118, score 40 and 16; candidate v3 129 (89.6%) and 120 (87.0%), score 40 and 30; the rule alone went from 111 to 122 (singles) and 104 to 108 (doubles). Landing median 0.29 to 0.25 m (singles), 0.34 to 0.25 m (doubles). In/out of matched rallies whose labelled landing is within 0.3 m of a line: installed v2 42 of 50 and 19 of 25, v3 43 of 50 and 20 of 25, rule 32 to 38 of 50 and 18 to 20 of 25. 90% is not reached in doubles: of the 18 wrong doubles winners with v3, 2 are missed rallies, 4 have the wrong last hitter, 12 have the right last hitter (in called out 6, out called in 4, in/net 2); in singles 3 missed, 1 wrong hitter, 11 with the right hitter (in called out 5, in called net 3). Shot speed: `analyse(speeds=True)` stores every shot's flight as `shot_flights` in the outcomes record (off in the stage, `SHOT_FLIGHTS`: about 0.35 s per shot, several minutes per full match); not in `MatchAnalysis` yet (schema unchanged), ready for step 4. Training rallies, published stroke types (2,459 strokes of 240 rallies, 96% fitted): median initial speed smash 211 km/h (p75 355), wrist smash 202, clear 149, lift 105, drive 100, drop 100, push 88, net shots 38-51, serves 33; smashes are the fastest family, but 19% of smash fits stop at the 450 km/h bound: at 30 frames per second the first frames after a smash do not fix its speed at the racket, so `speed_settled_kmh` (0.1 s after the contact) is also stored. Validation, the app's families: medians smash 180 km/h (14% at the bound), clear 172, drop and net kill 102, lift 93, drive 86, push 78, block 52, serve 40, net 36 (2,980 shots, 94% fitted), so the order holds but smash and clear overlap; the speed 0.1 s after the contact is capped near 120 km/h by the drag itself and does not separate the fastest shots either. Better speeds need the contact time to a fraction of a frame or a faster camera. Results in `.cache/step3/eval6/`. **Loose ends (2026-11-18):** clip `ds-52` fixed (63413f7): actor linking joined two tracker ids of one window into one player with overlapping ranges; the shorter track now keeps its range and the longer one gives up the shared frames. User videos re-run with the installed models (players stage on, names kept, 100% of person labels unchanged): `doubles.mp4` 27 rallies (user counted 25; extras are the 5:34.9 tap and a one-contact rally at 8:04.4, 1.6 s before the end), outcomes for all 27, 10 winners and 17 errors, 13-13; `singles.mp4` 21 rallies, 14 winners and 7 errors, 13-8. Test clips (12 plus `ds-52`) re-run and scored on the VM with the installed models; results in `.cache/step3/eval7/results/` (about 3 spot hours). **Test (never used for any choice), end to end:** singles 5 clips 159 rallies: matched 157, missed 2, extra 5, last hitter 143 of 157, winner right 140 (88.1%), landing median 0.28 m, running score right after 38; doubles 7 clips 232 rallies: matched 216, missed 16 (6 in `ds-62`), extra 12, last hitter 187 of 216, winner right 190 (81.9% of all, 88% of matched), landing median 0.35 m, running score right after 35. With the published last hit: 87.9% singles (371 of 422), 93.2% doubles (452 of 485). Validation re-scored on the VM now including `ds-52` (11 clips): singles unchanged (129 of 144, 89.6%), doubles 139 of 159 (87.4%; `ds-52` 19 of 21). Singles holds up on unseen matches; doubles loses about 5 points to missed rallies, so court detection and rally finding on new broadcasts are the next doubles lever, not the outcome model. |
| 4 | done (0a89fe1, 064086e, 0274ab6) | Shot flights in `MatchAnalysis` (schema version 4: `shot.flight` with initial speed, speed 0.1 s after contact, apex and `quality` good, speed_bound or poor_fit) and on in the outcomes stage (about 0.2-0.26 s per shot, +64 s doubles, +68 s singles). `clip_stats.py` (stats version 1, `docs/CLIP_STATS.md`), `GET /api/matches/{id}/stats`, `GET /api/videos/{id}/match-stats`, `clip-stats` CLI: shot type, side and serve breakdowns, contact, return and rally-ending landing maps turned to the player's end, position heatmaps, rally length, distance covered (glitches dropped, gaps to 0.5 s bridged, 0.3 s smoothing; about 15% uncertain), serve and receive, rallies won, winners, errors and consistency per shot label, shot pairs, triples and replies, doubles formation by attacking and defending phase, speeds from good fits only. Every number has its sample size; no running-score statistics (highlight reels). `doubles.mp4`: median 9 shots and 6.6 s per rally, 253-295 m per player, front-back 60-66% attacking, side by side 79-83% defending; `singles.mp4`: median 12 shots and 10.9 s, 371 and 390 m. Not measured: landings of shots that did not end the rally, contact height. Full suite: 8 shuttle broadcast and diagnostic tests fail on Windows path length (over 260 characters), unrelated to these changes. |
| 5 | first version (eba74d4, bb324f6, 406c1dc) | Three design prototypes in `design/prototypes/` (Floodlit, Featherweight, Chalk talk) on the real `doubles.mp4` data; the user chose Floodlit and refined it on their phone. Built into `backend/frontend/src/floodlit/` as the main path at `/`, wired to the matches API: landing with a 3D floodlit hall replaying a rally of the newest ready match (a bundled 38 KB sample rally when there is none), your matches, upload with names, processing with stage lamps, name confirmation, match page Watch and Analysis, per-rally swap. Old library and editor stay at `/library` and `/editor`. Perception cache keys no longer follow frontend builds: `static/` is out of the code hash, with `static/build-manifest.json` pinned to the value existing plans recorded so cached perception stays valid. Upload, name confirmation and processing states tested with mocked requests only; no new job run yet. Not decided: hosting beyond the laptop (reachable over Tailscale). |
| Strokes and speed (2026-11-19) | done (e12a4e5, 181a68d) | From another agent's research: sub-frame launch timing and a net-clearance check for shot flights adopted (its strict launch-display gate not adopted). Two stroke candidates scored once on the held-out test splits under a rule frozen beforehand, then installed: singles family ensemble (`events_singles_ensemble_v1.ts`; ShuttleSet test 1,687 vs 1,666 of 1,998 known strokes right, AI CUP test 318 vs 290 of 551, better on 6 of 7 units) and the doubles four-player stroke window blended 0.65/0.35 into the doubles event model (`events_doubles_window_v1.pt`; DShuttleNet test 3,173 vs 3,090 of 4,057, six-family macro F1 .774 to .803, better on all 7 matches and S2 match 3). Report `.cache/stroke-test-check/test-report-complete.json`. User videos re-run: rallies and winners unchanged (doubles 27, singles 21). |
| 6 to 8 | not started | |

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
