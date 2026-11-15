"""Pictures of each labelled doubles player, for fine-tuning OSNet.

For every rally of the given DShuttleNet matches, the player tracks are given
their published letter (A to D) the way identity_probe.py does it, and a crop
of each lettered player is saved at evenly spaced frames, skipping players
another body overlaps. One person is one (match, letter).

    python training/reid_crops.py --features F --videos V --matches 3 4 \
        --out /data/reid_crops

Output: OUT/<match>/<rally>_<frame>_<letter>_<end>.jpg, end 0 far, 1 near.
A match whose folder has a `done` file is skipped, so a rerun resumes.
"""

import argparse
import gzip
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import identity_probe as probe
import osnet
from badminton.event_doubles import assign_slots


def crops_of(path, capture, samples):
    """(name, picture) of every lettered, unobstructed player in one rally."""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        document = json.load(handle)
    height = document["video"]["height"]
    rows = document["players"]
    slots = assign_slots(
        rows, document["video"]["width"], height, float(document["video"]["fps"])
    )
    letters = probe.truth_letters(document, slots, height)
    marks = [e["frame"] for e in document["events"] if 0 <= e["frame"] < len(rows)]
    if not marks or not letters:
        return []
    played = [
        i for i in range(min(marks), max(marks) + 1) if rows[i].get("calibration_valid")
    ]
    if len(played) < samples:
        return []
    found = []
    for index in sorted(
        {played[round(i)] for i in np.linspace(0, len(played) - 1, samples)}
    ):
        frame = document["start_frame"] + index
        image = capture.frame(frame)
        if image is None:
            continue
        row = rows[index]
        for person in row["players"]:
            slot = slots.get((probe.camera(row), person.get("track_id")))
            letter = letters.get(slot)
            if letter is None:
                continue
            if any(
                probe.overlap(person["box"], other["box"]) > 0.15
                for other in row["players"]
                if other is not person
            ):
                continue
            left, top, right, bottom = (int(v) for v in person["box"])
            crop = image[max(0, top) : bottom, max(0, left) : right]
            if crop.shape[0] < 32 or crop.shape[1] < 12:
                continue
            name = f"{document['clip_id']}_{frame}_{letter}_{slot // 2}.jpg"
            found.append((name, cv2.resize(crop, osnet.SIZE)))
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--videos", type=Path, required=True)
    parser.add_argument("--matches", type=int, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=12)
    args = parser.parse_args()
    for match in args.matches:
        folder = args.out / str(match)
        if (folder / "done").exists():
            continue
        video = next(
            (
                p
                for p in sorted(args.videos.glob(f"{match}.*"))
                if p.suffix in (".mp4", ".webm", ".mkv")
            ),
            None,
        )
        files = sorted(args.features.glob(f"ds-{match}-*.json.gz"))
        if video is None or not files:
            print(f"match {match}: no video or features, skipped", flush=True)
            continue
        folder.mkdir(parents=True, exist_ok=True)
        capture = probe.Video(video)
        count = 0
        for path in files:
            for name, picture in crops_of(path, capture, args.samples):
                cv2.imwrite(str(folder / name), picture, [cv2.IMWRITE_JPEG_QUALITY, 90])
                count += 1
        capture.release()
        (folder / "done").write_text(str(count))
        print(f"match {match}: {len(files)} rallies, {count} crops", flush=True)


if __name__ == "__main__":
    main()
