"""Labelled evaluation clips for rally boundaries and outcomes.

Each clip is the first set of a held-out ShuttleSet or DShuttleNet match
(10 s before its first serve to 10 s after its last rally, at most
--limit seconds), cut so clip frame k is source frame start + k, then run
through the application's own full-match processing (`badminton process`) so
training/rally_eval.py can score what the app produces against the labels.

    # 1. which clips (validation and test matches of both datasets)
    python training/rally_clips.py spec --output clips.json
    # 2. cut those whose source video is in --videos
    python training/rally_clips.py cut clips.json --dataset shuttleset \
        --videos data/datasets/shuttleset/videos --output clips/
    # 3. one worker: ingest and process unclaimed clips, in spec order
    python training/rally_clips.py process clips.json --clips clips/ \
        --work /data/step3/w1 --claims /data/step3/claims

Test-split clips are processed with the others (perception does not depend on
any setting chosen here) but training/rally_eval.py scores them only when
asked to with --split test.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rally_labels

SHUTTLESET_SPLITS = {
    "validation": [35, 36, 37, 38, 41],
    "test": [39, 40, 42, 43, 44],
}


def dshuttlenet_splits():
    path = Path(__file__).with_name("dshuttlenet_splits.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"validation": data["validation"], "test": data["test"]}


def spec(limit_s, fps=30.0):
    clips = []
    for split in ("validation", "test"):
        for dataset, ids in (
            ("shuttleset", SHUTTLESET_SPLITS[split]),
            ("dshuttlenet", dshuttlenet_splits()[split]),
        ):
            for match in ids:
                labels = rally_labels.rallies(dataset, match)
                start, end = rally_labels.first_set_span(labels, fps, limit_s=limit_s)
                prefix = "ss" if dataset == "shuttleset" else "ds"
                clips.append(
                    {
                        "name": f"{prefix}-{match}",
                        "dataset": dataset,
                        "match_id": match,
                        "split": split,
                        "mode": "singles" if dataset == "shuttleset" else "doubles",
                        "start_frame": start,
                        "end_frame": end,
                    }
                )
    return clips


def video_id(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def process(clips, folder, work, claims, log):
    work, claims = Path(work).resolve(), Path(claims).resolve()
    (work / "videos").mkdir(parents=True, exist_ok=True)
    claims.mkdir(parents=True, exist_ok=True)
    env = dict(
        os.environ,
        BADMINTON_ROOT=str(work),
        BADMINTON_DATA_DIR=str(work / "processed"),
    )
    for clip in clips:
        source = Path(folder) / f"{clip['name']}.mp4"
        if not source.is_file():
            continue
        try:
            (claims / clip["name"]).mkdir()
        except FileExistsError:
            continue
        began = time.time()
        local = work / "videos" / source.name
        if not local.exists():
            os.link(source, local)
        command = [sys.executable, "-m", "badminton.cli"]
        with open(log, "a", encoding="utf-8") as sink:
            sink.write(f"== {clip['name']} start {time.ctime()}\n")
            sink.flush()
            ok = (
                subprocess.run(
                    [*command, "ingest", str(local), "--mode", clip["mode"]],
                    env=env,
                    stdout=sink,
                    stderr=subprocess.STDOUT,
                ).returncode
                == 0
            )
            identifier = video_id(local)
            ok = ok and (
                subprocess.run(
                    [*command, "process", identifier],
                    env=env,
                    stdout=sink,
                    stderr=subprocess.STDOUT,
                ).returncode
                == 0
            )
            minutes = (time.time() - began) / 60
            sink.write(
                f"== {clip['name']} video {identifier} "
                f"{'done' if ok else 'FAILED'} in {minutes:.1f} min\n"
            )
        record = {**clip, "video_id": identifier, "ok": ok, "minutes": minutes}
        (claims / clip["name"] / "result.json").write_text(
            json.dumps(record) + "\n", encoding="utf-8"
        )


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("spec")
    make.add_argument("--output", type=Path, required=True)
    make.add_argument("--limit", type=float, default=960.0, help="seconds per clip")
    cutting = commands.add_parser("cut")
    cutting.add_argument("spec", type=Path)
    cutting.add_argument("--dataset", required=True)
    cutting.add_argument("--videos", type=Path, required=True)
    cutting.add_argument("--output", type=Path, required=True)
    work = commands.add_parser("process")
    work.add_argument("spec", type=Path)
    work.add_argument("--clips", type=Path, required=True)
    work.add_argument("--work", type=Path, required=True)
    work.add_argument("--claims", type=Path, required=True)
    work.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "spec":
        clips = spec(args.limit)
        args.output.write_text(json.dumps(clips, indent=1) + "\n", encoding="utf-8")
        print(
            f"{len(clips)} clips, {sum(c['end_frame'] - c['start_frame'] for c in clips) / 30 / 3600:.1f} h"
        )
    elif args.command == "cut":
        from cut_clip import cut

        for clip in json.loads(args.spec.read_text(encoding="utf-8")):
            if clip["dataset"] != args.dataset:
                continue
            target = args.output / f"{clip['name']}.mp4"
            found = sorted(args.videos.glob(f"{clip['match_id']}.*"))
            found = [p for p in found if p.suffix in (".mp4", ".webm", ".mkv")]
            if target.exists() or not found:
                continue
            info = cut(found[0], target, clip["start_frame"], clip["end_frame"])
            print(clip["name"], info, flush=True)
    else:
        clips = json.loads(args.spec.read_text(encoding="utf-8"))
        process(clips, args.clips, args.work, args.claims, args.log)


if __name__ == "__main__":
    main()
