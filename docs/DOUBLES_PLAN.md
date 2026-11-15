# Doubles plan

Goal: per-player statistics for a doubles match. For every shot, who hit it
and what stroke it was, with totals per person across the whole game.

Scores below are on S2 Doubles match 2, which also chose the model, so they
describe one tournament and one camera. Accuracy elsewhere is not yet known.

## 1. Find each hit and its type (first version done)

A four-player event model (`backend/badminton/event_doubles.py`,
`training/train_doubles.py`) finds contacts, the court end, the stroke type
and forehand or backhand. Contact F1 is 0.93 at 2 frames, the court end is
right for 99% of found contacts, and stroke type macro F1 is 0.80.

## 2. Pick which partner hit (done by rule)

Trained on one match, the network names the right partner only at chance.
`choose_partner` picks by arm movement and distance to the shuttle instead
and is right about 95% of the time.

With more data (part 3), train the network to name the partner as it names
the player in singles. Score it against the rule on held-out matches and keep
the better one; the rule stays as the fallback.

## 3. More labelled data (in progress)

DShuttleNet has 58 BWF doubles matches and 58,359 labelled strokes
(CC BY-NC-SA 4.0, so a model trained on it is non-commercial). It ships no
videos; each match's BWF TV upload has to be found. Match 2's labels line up
with its upload with no frame offset (`training/extract_dshuttlenet.py`).

- Score the current model on DShuttleNet match 2: a first test on another
  tournament.
- Find and download the other 57 videos (about 40 GB; owner decision).
- Split whole matches into train, validation and an unopened test set,
  keeping each tournament on one side where possible. Retrain.
- S2 Doubles match 3 stays unopened until a final score is wanted.

## 4. Recognise each player across the match (first version, not in the app)

A player is followed only within one camera view in the app. Per-person
statistics need the same four people recognised from rally to rally and
after the change of ends, from looks alone (edited highlights keep only some
rallies, so rally order and the score are not used).

`training/identity_probe.py` describes each tracked player by clothing and
shoe colour, body length and a whole-person description (OSNet, fine-tuned
on DShuttleNet's player letters by `training/finetune_reid.py`), then splits
each match into two teams and each team into two partners.

Each player is pictured in at least four frames of a rally: frames where a
player stands clear are added from the tracks, and a player never seen clear
is pictured where least covered, skipping colour inside the box of whoever
stands in front. Before this, nearly every partner mix-up was a rally where
one partner had no usable picture.

All four players right per rally, on DShuttleNet matches never trained on:

| Set | Original description | Fine-tuned | + every player pictured |
|---|---|---|---|
| Test (7 matches from 2025, 452 rallies) | 80% | 86% | 94.5% |
| Validation (6 matches, 471 rallies) | 77% * | 91% | 94.3% |

\* with the earlier grouping. Validation chose some earlier settings; the
picture change was chosen on training matches only, and the test matches
were scored once before and once after it. Teams are 99 to 100% right on
every match. Weakest: validation match 34 (79%) and test match 54 (86%).

## 5. Statistics in the app (not started)

Per-player shot counts, stroke mix, forehand and backhand split and serves,
shown during review and after the game.

## Practical check

The owner's doubles video (`c406a1187130b845`) is re-rendered after each step
so wrong hitters and strokes can be pointed out by timestamp.
