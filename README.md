# Badminton match analyzer

Upload a badminton video (or paste a YouTube link), enter the player names,
and get a match page: the video with a live overlay, and statistics for the
whole clip. Works for singles and doubles.

> **Status:** research project, in active development. Results are automatic
> and not guaranteed to be right. They are measured on broadcast matches and
> untested on amateur footage.

## What it does

- **Tracks** the players (with one identity per person across the match), the
  shuttle and the court.
- **Finds** rallies, every shot, who hit it, and the shot type: clear, lift,
  net, drop, smash or drive, forehand or backhand.
- **Calls** each rally's landing spot, winner, and whether it ended in a
  winner or an error, then keeps a running score.
- **Estimates** shot speed from a 3D fit of the shuttle's flight.
- **Shows** it all in a web app: **Watch** (video with hitter highlight, last
  shot, a mini court) and **Analysis** (heatmaps, shot breakdowns, landing
  maps, rally lengths, distance covered, winners and errors).

On held-out broadcast test matches, the rally winner is right about 88% of
the time in singles and 82% in doubles. See
[docs/REVAMP_PLAN.md](docs/REVAMP_PLAN.md) for the measurements and known
gaps.

## Run it

Requires Python 3.10+, Node.js 22+ (for the frontend and YouTube imports) and
FFmpeg. An NVIDIA GPU is strongly recommended; CPU works but is slow.

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev,tracking,download,youtube,recognition]'
.\.venv\Scripts\python.exe scripts/download_models.py --kind all
.\.venv\Scripts\python.exe -m badminton.cli serve
```

On macOS/Linux use `.venv/bin/python`. For a CUDA build of PyTorch, follow the
[PyTorch install guide](https://pytorch.org/get-started/locally/) first.

Open **http://127.0.0.1:8000**. Containers, authentication and remote access
are covered in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Models

`scripts/download_models.py` fetches the public pretrained models (YOLO pose,
TrackNetV3, BST) and checks their hashes. The models trained by this project
are listed in [backend/badminton/model_manifest.json](backend/badminton/model_manifest.json)
with their training data and terms. Weights are never committed to Git.

Some project models are trained on datasets licensed for **non-commercial use
only** (for example DShuttleNet, CC BY-NC-SA 4.0), so those weights carry the
same restriction.

## Repository layout

| Path | Contents |
|---|---|
| `backend/badminton/` | FastAPI app, processing pipeline, models |
| `backend/frontend/` | React/TypeScript web app (Vite) |
| `training/` | Training and evaluation scripts |
| `scripts/` | Setup, model download and maintenance tools |
| `tests/` | Python and browser tests |
| `docs/` | Design notes and evaluation reports |

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests scripts
.\.venv\Scripts\python.exe -m ruff format --check backend tests scripts
```

Guidance for contributors (and coding agents) is in [AGENTS.md](AGENTS.md).
