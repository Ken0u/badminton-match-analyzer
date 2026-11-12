"""Run the app's trackers over DShuttleNet doubles rallies.

DShuttleNet (Kaggle anonymousay58dki/dshuttlenet, CC BY-NC-SA 4.0) labels 58
BWF doubles broadcasts: per stroke the start frame, the hitter, the stroke
type, a backhand flag and all four players' court positions. Its tables are
turned into the rows extract_s2doubles.py works from, and the same extraction
writes one gzip JSON per rally, named ds-<match>-<set>-<rally>.

    python training/extract_dshuttlenet.py --work .cache/dshuttlenet --matches 2

The videos are not part of the dataset: put each match's BWF TV upload (720p,
30 fps) in --videos as <match_id>.mp4. Frame numbers were checked against the
upload of match 2 and need no offset there.

Court positions are in decimetres with y measured from the bottom of the
court picture; each match's own homography takes image pixels to that picture
(51 pixels per metre, court corner at (27, 100)). Every rally is written with
the split "probe": nothing here is trained on yet.
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from extract_s2doubles import LETTERS, arguments, extract

SCALE = 5.1
CORNER = (27.0, 100.0)
LENGTH = 134.0


def table(source, name):
    with (Path(source) / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def to_image(inverse, x, y):
    """Image pixel of a court position, or None where the label is unusable."""
    try:
        x, y = float(x), float(y)
    except (TypeError, ValueError):
        return None, None
    # A few rows carry positions far off the court.
    if not (-20 <= x <= 81 and -20 <= y <= LENGTH + 20):
        return None, None
    point = inverse @ np.array(
        [x * SCALE + CORNER[0], (LENGTH - y) * SCALE + CORNER[1], 1.0]
    )
    if abs(point[2]) < 1e-9:
        return None, None
    return float(point[0] / point[2]), float(point[1] / point[2])


def read_rallies(source):
    """Strokes by (match, set, rally) in the shape of S2 Doubles rows."""
    inverse = {
        row["match_id"]: np.linalg.inv(np.array(json.loads(row["homography_matrix"])))
        for row in table(source, "match.csv")
    }
    games = {row["set_id"]: row for row in table(source, "set.csv")}
    keys = {}
    for row in table(source, "rally.csv"):
        game = games.get(row["set_id"])
        if game and game["match_id"] in inverse:
            keys[row["rally_id"]] = (
                game["match_id"],
                (int(game["match_id"]), int(game["set_num"]), int(row["rally_num"])),
            )
    rallies = defaultdict(list)
    for row in table(source, "shot.csv"):
        if row["rally_id"] not in keys:
            continue
        match, key = keys[row["rally_id"]]
        try:
            hitter = int(float(row["player"]))
        except ValueError:
            hitter = None
        letter = next((name for name in LETTERS if hitter == int(float(row[name]))), "")
        out = {
            "start_frame": int(float(row["start_frame_num"])),
            "end_frame": int(float(row["end_frame_num"])),
            "ball_round": int(float(row["shot_num"])),
            "player": letter,
            "ball_type": row["ball_type"],
            "backhand": row["backhand"].split(".")[0],
            "server": "1" if row["ball_type"].endswith("serve") else "0",
        }
        for name in LETTERS:
            out[f"player_{name}_x"], out[f"player_{name}_y"] = to_image(
                inverse[match], row[f"player_{name}_x"], row[f"player_{name}_y"]
            )
        rallies[key].append(out)
    for rows in rallies.values():
        rows.sort(key=lambda row: row["ball_round"])
    return dict(rallies)


def main():
    args = arguments("dshuttlenet")
    rallies = read_rallies(args.source)
    splits = {key[0]: "probe" for key in rallies}
    return extract(args, rallies, "dshuttlenet", "ds", splits)


if __name__ == "__main__":
    sys.exit(main())
