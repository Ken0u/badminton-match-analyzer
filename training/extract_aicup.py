"""Run the app's own player and shuttle trackers over every AI CUP rally clip.

Each clip becomes one gzip JSON holding per-frame players, shuttle and the
published labels. Using the application's trackers keeps training inputs
identical to what the app sees at inference time. Finished clips are skipped,
so an interrupted (spot) VM can simply rerun the same command.

    python training/extract_aicup.py --archive /data/part1.zip --work /data/work
"""

import argparse
import csv
import gzip
import io
import json
import os
import re
import sys
import time
import traceback
import zipfile
from pathlib import Path

CLIP = re.compile(r"part1/(train|val)/(\d{5})/(\d{5})(\.mp4|_S2\.csv)$")


def unpack(archive, clips):
    """Extract labelled training clips; return [(clip_id, video, label rows)]."""
    found = {}
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            match = CLIP.search(name)
            if not match or match[1] != "train" or match[2] != match[3]:
                continue
            entry = found.setdefault(match[2], {})
            if match[4] == ".mp4":
                target = clips / f"{match[2]}.mp4"
                if not target.exists():
                    partial = target.with_suffix(".part")
                    partial.write_bytes(source.read(name))
                    partial.replace(target)
                entry["video"] = target
            else:
                text = source.read(name).decode("utf-8-sig")
                entry["labels"] = list(csv.DictReader(io.StringIO(text)))
    return [
        (clip_id, entry["video"], entry["labels"])
        for clip_id, entry in sorted(found.items())
        if "video" in entry and "labels" in entry
    ]


def compact_players(run):
    frames = []
    for row in run["frames"]:
        people = [
            {
                "track_id": p.get("track_id"),
                "confidence": round(p["confidence"], 3),
                "box": [round(v, 1) for v in p["box"]],
                "keypoints": [[round(v, 2) for v in k] for k in p.get("keypoints", [])],
            }
            for p in row["players"]
        ]
        frames.append(
            {
                "frame": row["frame"],
                "time_s": row["time_s"],
                "calibration_valid": row.get("calibration_valid", False),
                "players": people,
            }
        )
    return frames


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
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--player-model", default="small")
    args = parser.parse_args()

    work = args.work.resolve()
    clips, features = work / "clips", work / "features"
    for folder in (clips, features, work / "processed"):
        folder.mkdir(parents=True, exist_ok=True)
    # Pin configuration before the application package is imported.
    os.environ["BADMINTON_ROOT"] = str(work)
    os.environ["BADMINTON_DATA_DIR"] = str(work / "processed")
    os.environ.setdefault("BADMINTON_WEIGHTS_DIR", str(work / "weights"))

    from badminton.config import DATA, ROOT
    from badminton.ingest import inspect_video
    from badminton.jobs import run_local_job
    from badminton.shuttle import track_shuttle
    from badminton.storage import Store
    from badminton.tracking import track_players

    store = Store(DATA)
    todo = unpack(args.archive, clips)[: args.limit]
    print(f"{len(todo)} labelled clips", flush=True)
    failures, began = [], time.time()
    for number, (clip_id, video_path, labels) in enumerate(todo, 1):
        output = features / f"{clip_id}.json.gz"
        if output.exists():
            continue
        try:
            started = time.time()
            video = run_local_job(
                store,
                "import",
                None,
                lambda job, progress: inspect_video(
                    video_path, "singles", store, ROOT, progress
                ),
            )
            end = video["frame_count"]
            runs = DATA / video["id"] / "runs"
            runs.mkdir(parents=True, exist_ok=True)
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
                    0,
                    end,
                    1,
                    progress,
                    player_file,
                    player_model=args.player_model,
                ),
            )
            run_local_job(
                store,
                "shuttle",
                video["id"],
                lambda job, progress: track_shuttle(
                    video, ROOT, DATA, 0, end, progress, shuttle_file
                ),
            )
            players = json.loads(player_file.read_text(encoding="utf-8"))
            shuttle = json.loads(shuttle_file.read_text(encoding="utf-8"))
            document = {
                "clip_id": clip_id,
                "video": {
                    key: video[key]
                    for key in ("id", "sha256", "width", "height", "fps", "frame_count")
                },
                "cut_frames": sorted(
                    set(players.get("cut_frames", []))
                    | set(shuttle.get("cut_frames", []))
                ),
                "players": compact_players(players),
                "shuttle": compact_shuttle(shuttle),
                "labels": labels,
            }
            partial = output.with_suffix(".part")
            with gzip.open(partial, "wt", encoding="utf-8") as sink:
                json.dump(document, sink, separators=(",", ":"))
            partial.replace(output)
            player_file.unlink()
            shuttle_file.unlink()
            elapsed = time.time() - started
            print(
                f"[{number}/{len(todo)}] {clip_id}: {end} frames in {elapsed:.0f}s "
                f"({end / max(elapsed, 1e-3):.1f} fps), total {(time.time() - began) / 60:.0f} min",
                flush=True,
            )
        except Exception:
            failures.append(clip_id)
            print(f"[{number}/{len(todo)}] {clip_id} FAILED", flush=True)
            traceback.print_exc()
    done = len(list(features.glob("*.json.gz")))
    print(f"finished: {done} feature files, {len(failures)} failures {failures}")
    return 1 if failures and not done else 0


if __name__ == "__main__":
    sys.exit(main())
