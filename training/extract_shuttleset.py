"""Run the app's player and shuttle trackers over every ShuttleSet rally.

ShuttleSet publishes stroke labels (hit frame, hitter, stroke type, backhand)
for 44 broadcast singles matches and the YouTube address of each match. This
downloads a match, runs the application's own trackers over each labelled
rally and writes one gzip JSON per rally, in the same shape extract_aicup.py
writes, with the published strokes attached. Finished rallies are skipped, so
an interrupted run can simply be repeated.

    python scripts/fetch_shuttleset.py
    python training/extract_shuttleset.py --work /data/shuttleset --matches 4

The published hit frames are used as published; training/train_events.py
decides how to use them.
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
FORMAT = "bv*[height=720][fps<=30][vcodec^=vp9]/bv*[height=720][fps<=30]"


def read_matches(source):
    path = Path(source) / "ShuttleSet" / "set" / "match.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {int(row["id"]): row for row in csv.DictReader(handle)}


def download(match, videos):
    """Fetch the 720p stream the published frame numbers were counted on."""
    found = sorted(videos.glob(f"{match['id']}.*"))
    found = [p for p in found if p.suffix in (".webm", ".mp4", ".mkv")]
    if found:
        return found[0]
    from yt_dlp import YoutubeDL

    options = {
        "format": FORMAT,
        "outtmpl": str(videos / f"{match['id']}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    with YoutubeDL(options) as client:
        client.download([match["url"]])
    return download(match, videos)


def court_end(raw):
    """Which end the hitter stood at, from the published image positions."""
    try:
        own, other = (
            float(raw["player_location_y"]),
            float(raw["opponent_location_y"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if abs(own - other) < 40:
        return None
    return "near" if own > other else "far"


def rally_events(records, start):
    events = []
    for record in records:
        usable = not record["issues"]
        serve = record["kind"] == "serve"
        events.append(
            {
                "frame": record["source_frame"] - start,
                "court_end": court_end(record["raw"]),
                "kind": record["kind"],
                "source_type": record["source_type"],
                "serve_type": record["source_type"].split()[0] if serve else None,
                "side": record["side"] if usable else "unknown",
                "source_player": record["source_player"],
                "usable": usable,
            }
        )
    return events


def compact_players(run):
    return [
        {
            "frame": row["frame"],
            "time_s": row["time_s"],
            "calibration_valid": row.get("calibration_valid", False),
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
        "--source", type=Path, default=Path("data/datasets/shuttleset/source")
    )
    parser.add_argument("--matches", type=int, nargs="*")
    parser.add_argument("--limit", type=int, help="rallies per match")
    parser.add_argument("--player-model", default="small")
    parser.add_argument("--shard", default="0/1", help="i/n: every n-th match")
    parser.add_argument("--keep-videos", action="store_true")
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="only process matches whose video is already in <work>/videos",
    )
    parser.add_argument(
        "--claim",
        action="store_true",
        help="each match is taken by one of the workers sharing --shared",
    )
    parser.add_argument(
        "--shared",
        type=Path,
        help="folder holding videos, features and claims for several workers, "
        "each with its own --work (default: --work)",
    )
    args = parser.parse_args()

    work = args.work.resolve()
    shared = (args.shared or args.work).resolve()
    videos, features = shared / "videos", shared / "features"
    for folder in (videos, features, work / "videos", work / "processed"):
        folder.mkdir(parents=True, exist_ok=True)
    (shared / "index").mkdir(exist_ok=True)
    # Pin configuration before the application package is imported.
    os.environ["BADMINTON_ROOT"] = str(work)
    os.environ["BADMINTON_DATA_DIR"] = str(work / "processed")
    os.environ.setdefault("BADMINTON_WEIGHTS_DIR", str(work / "weights"))

    from badminton.config import DATA, ROOT
    from badminton.datasets import import_shuttleset
    from badminton.ingest import inspect_video
    from badminton.jobs import run_local_job
    from badminton.segments import scan_video
    from badminton.shuttle import track_shuttle
    from badminton.storage import Store
    from badminton.tracking import track_players

    index = shared / "index" / "strokes.jsonl"
    if not index.exists():
        import_shuttleset(args.source, shared / "index")
    rallies = defaultdict(list)
    with index.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            rallies[(record["match_id"], record["set_id"], record["rally_id"])].append(
                record
            )
    matches = read_matches(args.source)
    shard, total = (int(v) for v in args.shard.split("/"))
    chosen = sorted(args.matches or matches)[shard::total]
    store = Store(DATA)
    failures, began = [], time.time()
    for match_id in chosen:
        match = matches[match_id]
        own = sorted(key for key in rallies if key[0] == match_id)
        own = [
            key
            for key in own
            if all(r["source_frame"] is not None for r in rallies[key])
            and rallies[key][0]["split"] != "quarantine"
        ][: args.limit]
        todo = [
            key
            for key in own
            if not (features / "ss-{}-{}-{}.json.gz".format(*key)).exists()
        ]
        if not todo:
            continue
        present = any(
            p.suffix in (".webm", ".mp4", ".mkv") for p in videos.glob(f"{match_id}.*")
        )
        if args.no_download and not present:
            continue
        if args.claim:
            try:
                (shared / "locks").mkdir(exist_ok=True)
                (shared / "locks" / str(match_id)).mkdir()
            except FileExistsError:
                continue
        try:
            original = download(match, videos)
            # The application reads media from inside its own root folder.
            path = work / "videos" / original.name
            if path != original and not path.exists():
                os.link(original, path)
            video = run_local_job(
                store,
                "import",
                None,
                lambda job, progress, path=path: inspect_video(
                    path, "singles", store, ROOT, progress
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
            failures.append(f"match {match_id}")
            print(f"match {match_id} FAILED before extraction", flush=True)
            traceback.print_exc()
            continue
        margin = round(MARGIN_S * float(video["fps"]))
        print(
            f"match {match_id}: {video['frame_count']} frames at {video['fps']} fps, "
            f"{len(todo)} rallies to do",
            flush=True,
        )
        for number, key in enumerate(todo, 1):
            name = "ss-{}-{}-{}".format(*key)
            records = sorted(rallies[key], key=lambda r: r["stroke_order"])
            frames = [r["source_frame"] for r in records]
            start = max(0, min(frames) - margin)
            end = min(video["frame_count"], max(frames) + margin + 1)
            if end - start < 8 or min(frames) >= video["frame_count"]:
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
                    "dataset": "shuttleset",
                    "clip_id": name,
                    "match_id": key[0],
                    "set_id": key[1],
                    "rally_id": key[2],
                    "split": records[0]["split"],
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
                    "events": rally_events(records, start),
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
                    f"[{number}/{len(todo)}] {name}: {end - start} frames in "
                    f"{elapsed:.0f}s ({(end - start) / max(elapsed, 1e-3):.1f} fps), "
                    f"total {(time.time() - began) / 60:.0f} min",
                    flush=True,
                )
            except Exception:
                failures.append(name)
                print(f"[{number}/{len(todo)}] {name} FAILED", flush=True)
                traceback.print_exc()
        if not args.keep_videos:
            path.unlink(missing_ok=True)
            original.unlink(missing_ok=True)
    done = len(list(features.glob("*.json.gz")))
    print(f"finished: {done} feature files, {len(failures)} failures {failures}")
    return 1 if failures and not done else 0


if __name__ == "__main__":
    sys.exit(main())
