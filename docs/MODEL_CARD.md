# Badminton match analyzer models

The trained models behind
[badminton-match-analyzer](https://github.com/Ken0u/badminton-match-analyzer),
which turns a badminton match video into shots, rally outcomes and
statistics. Install them with the app:

```bash
python scripts/download_models.py --kind all
```

The script downloads each file listed in `scripts/project_models.json` and
checks its SHA-256. Public pretrained models (YOLO11 pose, TrackNetV3, BST)
are fetched from their original publishers, not from here.

## Models

| File | What it does | Trained on | License |
|---|---|---|---|
| `events.pt` | Singles: finds each contact and predicts hitter, shot family, forehand/backhand and serve from player poses and the shuttle track | AI CUP 2023, ShuttleSet | CC BY 4.0 |
| `events_singles_ensemble_v1.ts` | Singles shot-family ensemble (TorchScript) used on top of `events.pt` | AI CUP 2023, ShuttleSet | CC BY 4.0 |
| `events_doubles.pt` | Doubles version of the event model, four players | DShuttleNet, S2 Doubles; pretrained on AI CUP 2023 and ShuttleSet | CC BY-NC-SA 4.0 |
| `events_doubles_window_v1.pt` | Doubles four-player stroke window, blended 0.65/0.35 into the doubles event model | DShuttleNet, S2 Doubles | CC BY-NC-SA 4.0 |
| `rally_outcome_sequence_v3.json` | Rally winner and in/out/net from the shuttle, players, landing spot and 3D flight around the last contact | ShuttleSet, DShuttleNet | CC BY-NC-SA 4.0 |
| `reid/osnet_doubles_ft1.pth` | Player appearance embedding (OSNet x1.0) for one identity per person through the match | OSNet MSMT17 weights fine-tuned on DShuttleNet | CC BY-NC-SA 4.0 |

Shot families are clear, lift, net, drop, smash and drive (plus serve), each
with forehand or backhand.

## Results

Measured on held-out broadcast matches that were never used for training or
any design choice:

| Task | Singles | Doubles |
|---|---|---|
| Rally winner, end to end from raw video | 88.1% (140 of 159 rallies) | 81.9% (190 of 232) |
| Rally winner, given the published last hit | 87.9% | 93.2% |
| Landing spot, median error | 0.28 m | 0.35 m |
| Shot family, known strokes | 84.4% on ShuttleSet (1,687 of 1,998) | 78.2% on DShuttleNet (3,173 of 4,057), six-family macro F1 0.803 |
| All four doubles players identified correctly | | 94.5% of rallies |

## Limitations

- Trained and tested on professional broadcast footage. Amateur or phone
  video, other camera angles and poor lighting are untested.
- Shuttle speed at the racket is unreliable for the fastest smashes at
  30 frames per second.
- Line calls are the main source of wrong rally winners.

## Licenses and data

Each model takes the most restrictive license of its training data:

- **AI CUP 2023** badminton dataset: CC BY 4.0.
- **ShuttleSet** (Wang et al., KDD 2023, `wywyWang/CoachAI-Projects`): MIT.
- **DShuttleNet**: CC BY-NC-SA 4.0, so models trained on it are for
  non-commercial use only and shared under the same license.
- **S2 Doubles**: published without a license file.
- **OSNet** (Zhou et al., Omni-Scale Feature Learning for Person
  Re-Identification): MIT.

The match videos themselves belong to their broadcasters and are not
distributed here.

Please cite the original dataset papers when you use these models.
