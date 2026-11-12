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

## 4. Recognise each player across the match (not started)

A player is followed only within one rally today. Per-person statistics need
the same four people recognised from rally to rally and after the change of
ends. Planned evidence: appearance (shirt, build) and the rule that partners
share an end. DShuttleNet's player ids give labels to test against.

## 5. Statistics in the app (not started)

Per-player shot counts, stroke mix, forehand and backhand split and serves,
shown during review and after the game.

## Practical check

The owner's doubles video (`c406a1187130b845`) is re-rendered after each step
so wrong hitters and strokes can be pointed out by timestamp.
