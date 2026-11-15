"""Per-rally outcome examples from the extracted rally feature files.

The ShuttleSet and DShuttleNet extractions (training/extract_shuttleset.py,
training/extract_dshuttlenet.py) ran the application's own player and shuttle
trackers over every labelled rally, from 1.6 s before its first stroke to
1.6 s after its last stroke (ShuttleSet) or its labelled end (DShuttleNet).
This turns each file into the timeline backend/badminton/rally_outcomes.py
reads, using the dataset's published court corners for the floor homography
(the app finds its own at inference), and joins the rally labels of
training/rally_labels.py.

    python training/rally_outcome_features.py --features DIR [DIR ...] \
        --output .cache/step3/examples.jsonl
"""

import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import rally_labels

SS_SPLITS = {
    **dict.fromkeys((35, 36, 37, 38, 41), "validation"),
    **dict.fromkeys((39, 40, 42, 43, 44), "test"),
}


def ds_splits():
    data = json.loads(
        Path(__file__).with_name("dshuttlenet_splits.json").read_text(encoding="utf-8")
    )
    out = dict.fromkeys(data["validation"], "validation")
    out.update(dict.fromkeys(data["test"], "test"))
    out.update(dict.fromkeys(data["left_out"], "left_out"))
    return out


def split_of(dataset, match):
    table = SS_SPLITS if dataset == "shuttleset" else ds_splits()
    return table.get(match, "train")


def normalized_homography(dataset, match, width, height):
    """Normalized image point -> court metres, from the dataset's corners."""
    if dataset == "shuttleset":
        rows = rally_labels._read(
            rally_labels.SHUTTLESET / "ShuttleSet/set/homography.csv"
        )
        row = next(r for r in rows if int(r["id"]) == match)
        offset, size = (25.0, 150.0), (300.0, 660.0)
    else:
        rows = rally_labels._read(rally_labels.DSHUTTLENET / "match.csv")
        row = next(r for r in rows if int(r["match_id"]) == match)
        offset, size = (27.0, 100.0), (312.0, 684.0)
    pixels = np.asarray(json.loads(row["homography_matrix"]), float)
    to_metres = np.array(
        [
            [
                rally_labels.COURT_W / size[0],
                0,
                -offset[0] * rally_labels.COURT_W / size[0],
            ],
            [
                0,
                rally_labels.COURT_L / size[1],
                -offset[1] * rally_labels.COURT_L / size[1],
            ],
            [0, 0, 1],
        ]
    )
    # Published coordinates are on a 1280x720 frame.
    to_pixels = np.diag([1280.0, 720.0, 1.0])
    matrix = to_metres @ pixels @ to_pixels
    return (matrix / matrix[2, 2]).tolist()


class _Labels:
    def __init__(self):
        self.cache = {}

    def __call__(self, dataset, match):
        if (dataset, match) not in self.cache:
            self.cache[(dataset, match)] = {
                (r["set"], r["rally"]): r for r in rally_labels.rallies(dataset, match)
            }
        return self.cache[(dataset, match)]


def timeline(document, matrix):
    """The rally file as rally_outcomes inputs: times, shuttle, players."""
    video = document["video"]
    fps, width, height = float(video["fps"]), video["width"], video["height"]
    start = document["start_frame"]
    rows = document["shuttle"]
    frames = [start + i for i in range(len(rows))]
    times = [f / fps for f in frames]
    shuttle = [
        (r["x"] / width, r["y"] / height)
        if r.get("visible") and r.get("x") is not None
        else None
        for r in rows
    ]
    from badminton.match_analysis import project

    players = []
    for row in document["players"]:
        found = []
        for person in row["players"]:
            x1, _, x2, y2 = person["box"]
            point = project(matrix, (x1 + x2) / 2 / width, y2 / height)
            if point is not None:
                found.append(point)
        players.append(found)
    return {
        "fps": fps,
        "start_frame": start,
        "frames": frames,
        "times": times,
        "shuttle": shuttle,
        "players": players,
        "aspect": width / height,
        "cuts": list(document.get("cut_frames", [])),
    }


def examples(folders):
    labels = _Labels()
    matrices = {}
    for folder in folders:
        for path in sorted(Path(folder).glob("*.json.gz")):
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                document = json.load(handle)
            dataset, match = document["dataset"], int(document["match_id"])
            set_id, rally_id = int(document["set_id"]), int(document["rally_id"])
            if dataset == "dshuttlenet":
                # The extractor numbered rallies by rally.csv's rally_num in its set.
                key = (set_id, rally_id)
            else:
                key = (set_id, rally_id)
            label = labels(dataset, match).get(key)
            if label is None:
                continue
            if (dataset, match) not in matrices:
                matrices[(dataset, match)] = normalized_homography(
                    dataset,
                    match,
                    document["video"]["width"],
                    document["video"]["height"],
                )
            yield {
                "name": path.name.split(".")[0],
                "dataset": dataset,
                "match_id": match,
                "split": split_of(dataset, match),
                "label": label,
                "last_type": (document["events"][-1].get("source_type") or None)
                if document.get("events")
                else None,
                "homography": matrices[(dataset, match)],
                "timeline": timeline(document, matrices[(dataset, match)]),
            }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, nargs="+", required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    for n, example in enumerate(examples(args.features)):
        print(example["name"], example["split"], example["label"]["winner_end"])
        if args.limit and n + 1 >= args.limit:
            break


if __name__ == "__main__":
    main()
