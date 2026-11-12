"""Run the app's player and shuttle trackers over every S2 Doubles rally.

S2 Doubles publishes stroke labels for three broadcast doubles matches: the
frame each stroke starts at (the contact), which of the four players hit it,
all four players' foot positions, the stroke type and a backhand flag. This
runs the application's own trackers over each labelled rally and writes one
gzip JSON per rally with the published strokes attached. Tracker numbers are
kept as the tracker gave them; training/train_events.py joins broken tracks
and matches the published player letters to them. Finished rallies are
skipped, so an interrupted run can simply be repeated.

    python scripts/fetch_s2doubles.py
    python training/extract_s2doubles.py --work .cache/s2doubles

The videos are not part of the dataset: put each match's BWF broadcast (720p,
30 fps) in --videos as <match number>.mp4 or .webm.
"""

import argparse
import csv
import gzip
import json
import os
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

MARGIN_S = 1.6
# Whole matches: train on the first, choose the model on the second.
SPLITS = {1: "train", 2: "validation", 3: "test"}
LETTERS = "ABCD"


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_rallies(source):
    """Published strokes grouped by (match, set, rally), in stroke order."""
    rallies = defaultdict(list)
    for folder in sorted(Path(source).glob("Match *")):
        match = int(folder.name.split()[-1])
        for path in sorted((folder / "label").glob("set*.csv")):
            game = int(path.stem.removeprefix("set"))
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    rallies[(match, game, int(row["rally"]))].append(row)
    for rows in rallies.values():
        rows.sort(key=lambda row: int(row["ball_round"]))
    return dict(rallies)


def rally_events(rows, start):
    events = []
    for row in rows:
        feet = {
            letter: [
                number(row[f"player_{letter}_x"]),
                number(row[f"player_{letter}_y"]),
            ]
            for letter in LETTERS
        }
        events.append(
            {
                "frame": int(row["start_frame"]) - start,
                "end_frame": int(row["end_frame"]) - start,
                "order": int(row["ball_round"]),
                "player": row["player"] if row["player"] in LETTERS else None,
                "source_type": row["ball_type"],
                "backhand": {"0": False, "1": True}.get(row["backhand"]),
                "serve": row["server"] == "1",
                "feet": feet,
            }
        )
    return events


def compact_players(run):
    return [
        {
            "frame": row["frame"],
            "time_s": row["time_s"],
            "calibration_valid": row.get("calibration_valid", False),
            "camera_segment_start_frame": row.get("camera_segment_start_frame"),
            "players": [
                {
                    "track_id": p.get("track_id"),
                    "confidence": round(p["confidence"], 3),
                    "box": [round(v, 1) for v in p["box"]],
                    "keypoints": [
                        [round(v, 2) for v in k] for k in p.get("keypoints", [])
                    ],
                }
                for p in row["players"]
            ],
        }
        for row in run["frames"]
    ]


def compact_shuttle(run):
    return [
        {
            "frame": row["frame"],
            "visible": bool(row["shuttle"].get("visible")),
            "x": row["shuttle"].get("x"),
            "y": row["shuttle"].get("y"),
            "confidence": row["shuttle"].get("confidence"),
        }
        for row in run["frames"]
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument(
        "--source", type=Path, default=Path("data/datasets/s2doubles/source")
    )
    parser.add_argument(
        "--videos", type=Path, default=Path("data/datasets/s2doubles/videos")
    )
    parser.add_argument("--matches", type=int, nargs="*")
    parser.add_argument("--limit", type=int, help="rallies per match")
    parser.add_argument("--player-model", default="small")
    args = parser.parse_args()

    work = args.work.resolve()
    features = work / "features"
    for folder in (features, work / "videos", work / "processed"):
        folder.mkdir(parents=True, exist_ok=True)
    # Pin configuration before the application package is imported.
    os.environ["BADMINTON_ROOT"] = str(work)
    os.environ["BADMINTON_DATA_DIR"] = str(work / "processed")
    os.environ.setdefault("BADMINTON_WEIGHTS_DIR", str(work / "weights"))

    from badminton.config import DATA, ROOT
    from badminton.ingest import inspect_video
    from badminton.jobs import run_local_job
    from badminton.segments import scan_video
    from badminton.shuttle import track_shuttle
    from badminton.storage import Store
    from badminton.tracking import track_players

    rallies = read_rallies(args.source)
    store = Store(DATA)
    failures, began = [], time.time()
    for match in sorted(args.matches or SPLITS):
        own = sorted(key for key in rallies if key[0] == match)[: args.limit]
        todo = [
            key
            for key in own
            if not (features / "s2-{}-{}-{}.json.gz".format(*key)).exists()
        ]
        if not todo:
            continue
        found = [
            p
            for p in sorted(args.videos.glob(f"{match}.*"))
            if p.suffix in (".webm", ".mp4", ".mkv")
        ]
        if not found:
            print(f"match {match}: no video in {args.videos}; skipped", flush=True)
            continue
        try:
            # The application reads media from inside its own root folder.
            path = work / "videos" / found[0].name
            if not path.exists():
                os.link(found[0].resolve(), path)
            video = run_local_job(
                store,
                "import",
                None,
                lambda job, progress, path=path: inspect_video(
                    path, "doubles", store, ROOT, progress
                ),
            )
            runs = DATA / video["id"] / "runs"
            runs.mkdir(parents=True, exist_ok=True)
            scan_file = runs / "segments.json"
            if not scan_file.exists():
                run_local_job(
                    store,
                    "segments",
                    video["id"],
                    lambda job, progress, video=video, scan_file=scan_file: scan_video(
                        video, ROOT, DATA, progress, scan_file
                    ),
                )
            scan = json.loads(scan_file.read_text(encoding="utf-8"))
        except Exception:
            failures.append(f"match {match}")
            print(f"match {match} FAILED before extraction", flush=True)
            traceback.print_exc()
            continue
        margin = round(MARGIN_S * float(video["fps"]))
        print(
            f"match {match}: {video['frame_count']} frames at {video['fps']} fps, "
            f"{len(todo)} rallies to do",
            flush=True,
        )
        for count, key in enumerate(todo, 1):
            name = "s2-{}-{}-{}".format(*key)
            rows = rallies[key]
            first = int(rows[0]["start_frame"])
            last = max(int(row["end_frame"]) for row in rows)
            start = max(0, first - margin)
            end = min(video["frame_count"], last + margin + 1)
            if end - start < 8 or first >= video["frame_count"]:
                print(f"{name}: labels lie outside the video; skipped", flush=True)
                continue
            try:
                started = time.time()
                player_file, shuttle_file = runs / "players.json", runs / "shuttle.json"
                run_local_job(
                    store,
                    "players",
                    video["id"],
                    lambda job, progress: track_players(
                        video,
                        ROOT,
                        DATA,
                        store.annotations(video["id"]),
                        start,
                        end,
                        1,
                        progress,
                        player_file,
                        player_model=args.player_model,
                        camera_scan=scan,
                        skip_uncalibrated=True,
                    ),
                )
                players = json.loads(player_file.read_text(encoding="utf-8"))
                run_local_job(
                    store,
                    "shuttle",
                    video["id"],
                    lambda job, progress: track_shuttle(
                        video,
                        ROOT,
                        DATA,
                        start,
                        end,
                        progress,
                        shuttle_file,
                        camera_scan=scan,
                        skip_frames=[
                            row["frame"]
                            for row in players["frames"]
                            if row.get("skipped_no_court")
                        ],
                    ),
                )
                shuttle = json.loads(shuttle_file.read_text(encoding="utf-8"))
                document = {
                    "dataset": "s2doubles",
                    "clip_id": name,
                    "match_id": key[0],
                    "set_id": key[1],
                    "rally_id": key[2],
                    "split": SPLITS.get(key[0], "test"),
                    "start_frame": start,
                    "video": {
                        k: video[k]
                        for k in (
                            "id",
                            "sha256",
                            "width",
                            "height",
                            "fps",
                            "frame_count",
                        )
                    },
                    "cut_frames": sorted(
                        set(players.get("cut_frames", []))
                        | set(shuttle.get("cut_frames", []))
                    ),
                    "players": compact_players(players),
                    "shuttle": compact_shuttle(shuttle),
                    "events": rally_events(rows, start),
                }
                output = features / f"{name}.json.gz"
                partial = output.with_suffix(".part")
                with gzip.open(partial, "wt", encoding="utf-8") as sink:
                    json.dump(document, sink, separators=(",", ":"))
                partial.replace(output)
                player_file.unlink()
                shuttle_file.unlink()
                elapsed = time.time() - started
                print(
                    f"[{count}/{len(todo)}] {name}: {end - start} frames in "
                    f"{elapsed:.0f}s ({(end - start) / max(elapsed, 1e-3):.1f} fps), "
                    f"total {(time.time() - began) / 60:.0f} min",
                    flush=True,
                )
            except Exception:
                failures.append(name)
                print(f"[{count}/{len(todo)}] {name} FAILED", flush=True)
                traceback.print_exc()
    done = len(list(features.glob("*.json.gz")))
    print(f"finished: {done} feature files, {len(failures)} failures {failures}")
    return 1 if failures and not done else 0


if __name__ == "__main__":
    sys.exit(main())
