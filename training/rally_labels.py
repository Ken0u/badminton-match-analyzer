"""Published rally labels of ShuttleSet (singles) and DShuttleNet (doubles).

Both datasets label every rally of a broadcast match. This reads them into one
shape for training/rally_eval.py and training/rally_outcome_features.py:

    {
      "dataset", "match_id", "set", "rally",          # identity
      "serve_frame", "last_hit_frame", "hit_frames",   # source frames
      "end_frame",          # DShuttleNet's rally end; None for ShuttleSet
      "last_hitter_end",    # "far"/"near"/None: who played the last stroke
      "winner_end",         # "far"/"near"/None: who won the rally
      "reason",             # "winner"/"error"/None, from the winner's side
      "detail",             # in, out, net, failed_return, fault or None
      "landing",            # [x, y] court metres of the last shot, or None
      "score_after",        # {"first": n, "second": m} points in the set
      "first_end",          # end of the score's "first" side in this rally
    }

Court metres follow MatchAnalysis: x 0..6.1 from the far-left outer sideline,
y 0..13.4 from the far baseline. "Far" is the upper end of the broadcast
image. Unknown values stay None; nothing is guessed.

Label meanings (checked on the published tables, not on video):

- ShuttleSet `lose_reason` on a rally's last stroke row, with
  `getpoint_player` the rally winner: 對手落地致勝 (the shot landed in),
  落點判斷失誤 and 對手落地判斷失誤 (left to land, landed in) are winners of
  the last hitter; 出界 out, 掛網 and 未過網 net; 犯規 fault. Landing pixels
  are in the 1280x720 broadcast image; `homography.csv` maps them to a court
  drawn with outer corners at (25, 150) and (325, 810).
- DShuttleNet `rally.csv`: `score_reason` is the scoring team's view
  (Grounded within Boundaries, Opp Judgment Error: winners; Opp Net Fault,
  Opp Out of Bounds, Opp Failed Return, Opp Faults: the other team's error);
  `land_x/y` pixels map through the match homography to a court with outer
  corners at (27, 100) and (339, 784); player court positions in `shot.csv`
  are decimetres with Y measured from the near baseline.
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

COURT_W, COURT_L = 6.1, 13.4
SHUTTLESET = Path("data/datasets/shuttleset/source")
DSHUTTLENET = Path("data/datasets/dshuttlenet/source")

SS_REASONS = {
    "對手落地致勝": ("winner", "in"),
    "落點判斷失誤": ("winner", "in"),
    "對手落地判斷失誤": ("winner", "in"),
    "出界": ("error", "out"),
    "掛網": ("error", "net"),
    "未過網": ("error", "net"),
    "犯規": ("error", "fault"),
}
DS_REASONS = {
    "Grounded within Boundaries": ("winner", "in"),
    "Opp Judgment Error": ("winner", "in"),
    "Opp Net Fault": ("error", "net"),
    "Opp Out of Bounds": ("error", "out"),
    "Opp Failed Return": ("error", "failed_return"),
    "Opp Faults": ("error", "fault"),
}


def _read(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _project(matrix, x, y):
    p = matrix @ np.array([x, y, 1.0])
    return p[:2] / p[2]


def _other(end):
    return {"far": "near", "near": "far"}.get(end)


# ShuttleSet -------------------------------------------------------------------


def shuttleset_matches(source=SHUTTLESET):
    return {int(r["id"]): r for r in _read(Path(source) / "ShuttleSet/set/match.csv")}


def shuttleset_metres(source=SHUTTLESET):
    """match id -> function (pixel x, y) -> court metres [x, y]."""
    result = {}
    for row in _read(Path(source) / "ShuttleSet/set/homography.csv"):
        matrix = np.asarray(json.loads(row["homography_matrix"]), float)

        def convert(x, y, matrix=matrix):
            u, v = _project(matrix, x, y)
            return [(u - 25) / 300 * COURT_W, (v - 150) / 660 * COURT_L]

        result[int(row["id"])] = convert
    return result


def _ss_end(row, own=True):
    """End of the stroke's hitter (own) or its opponent, from image y."""
    a, b = _float(row["player_location_y"]), _float(row["opponent_location_y"])
    if a is None or b is None or abs(a - b) < 40:
        return None
    hitter = "near" if a > b else "far"
    return hitter if own else _other(hitter)


def shuttleset_rallies(match_id, source=SHUTTLESET):
    match = shuttleset_matches(source)[match_id]
    metres = shuttleset_metres(source).get(match_id)
    folder = Path(source) / "ShuttleSet/set" / match["video"]
    rallies = []
    for set_number in range(1, int(match["set"]) + 1):
        path = folder / f"set{set_number}.csv"
        if not path.is_file():
            continue
        grouped = defaultdict(list)
        for row in _read(path):
            grouped[int(row["rally"])].append(row)
        for number in sorted(grouped):
            rows = sorted(grouped[number], key=lambda r: float(r["ball_round"]))
            frames = [_float(r["frame_num"]) for r in rows]
            if any(f is None for f in frames):
                continue
            frames = [int(f) for f in frames]
            last = rows[-1]
            hitter_end = _ss_end(last)
            reason, detail = SS_REASONS.get(last["lose_reason"].strip(), (None, None))
            winner = last["getpoint_player"].strip() or None
            if winner is None or hitter_end is None:
                winner_end = None
            else:
                winner_end = (
                    hitter_end if winner == last["player"] else _other(hitter_end)
                )
            # The reason is the last hitter's: a winner if the last hitter won.
            if reason is not None and winner is not None:
                reason = "winner" if winner == last["player"] else "error"
                if reason == "winner" and detail != "in":
                    detail = None  # inconsistent row
                if reason == "error" and detail == "in":
                    detail = None
            # Player A's end: the hitter's end when A hit, else the other.
            a_end = hitter_end if last["player"] == "A" else _other(hitter_end)
            x, y = _float(last["landing_x"]), _float(last["landing_y"])
            landing = None
            if metres and x is not None and y is not None:
                landing = [round(float(v), 3) for v in metres(x, y)]
            rallies.append(
                {
                    "dataset": "shuttleset",
                    "match_id": match_id,
                    "set": set_number,
                    "rally": number,
                    "serve_frame": frames[0],
                    "last_hit_frame": frames[-1],
                    "hit_frames": frames,
                    "end_frame": None,
                    "last_hitter_end": hitter_end,
                    "winner_end": winner_end,
                    "reason": reason,
                    "detail": detail,
                    "landing": landing,
                    "score_after": {
                        "first": int(last["roundscore_A"]),
                        "second": int(last["roundscore_B"]),
                    },
                    "first_end": a_end,
                }
            )
    return rallies


# DShuttleNet ------------------------------------------------------------------


def dshuttlenet_rallies(match_id, source=DSHUTTLENET):
    source = Path(source)
    match = next(
        r for r in _read(source / "match.csv") if int(r["match_id"]) == match_id
    )
    matrix = np.asarray(json.loads(match["homography_matrix"]), float)
    sets = {
        int(r["set_id"]): int(r["set_num"])
        for r in _read(source / "set.csv")
        if int(r["match_id"]) == match_id
    }
    shots = defaultdict(list)
    rally_rows = [r for r in _read(source / "rally.csv") if int(r["set_id"]) in sets]
    wanted = {r["rally_id"] for r in rally_rows}
    for row in _read(source / "shot.csv"):
        if row["rally_id"] in wanted:
            shots[row["rally_id"]].append(row)
    rallies = []
    for row in rally_rows:
        strokes = sorted(
            shots.get(row["rally_id"], []), key=lambda r: int(r["shot_num"])
        )
        start, end = _float(row["start_frame"]), _float(row["end_frame"])
        if start is None or end is None or not strokes:
            continue
        frames = [int(float(s["start_frame_num"])) for s in strokes]

        def team_end(stroke, letters):
            ys = [_float(stroke[f"player_{k}_y"]) for k in letters]
            ys = [y for y in ys if y is not None and -20 <= y <= 154]
            if not ys:
                return None
            # Y in decimetres from the near baseline.
            return "far" if np.mean(ys) > 67 else "near"

        ends = [team_end(s, "AB") for s in strokes]
        known = [e for e in ends if e is not None]
        first_end = max(set(known), key=known.count) if known else None
        score_team = _float(row["score_team"])
        winner_end = None
        if score_team is not None and first_end is not None:
            winner_end = first_end if score_team == 0 else _other(first_end)
        reason, detail = DS_REASONS.get(row["score_reason"].strip(), (None, None))
        last = strokes[-1]
        hitter = _float(last["player"])
        letters = {_float(last[k]): k for k in "ABCD"}
        letter = letters.get(hitter)
        hitter_end = None
        if letter is not None and first_end is not None:
            hitter_end = first_end if letter in "AB" else _other(first_end)
        # The published reason is the scorer's; ours is the last hitter's.
        if reason is not None and hitter_end is not None and winner_end is not None:
            hitter_won = hitter_end == winner_end
            if hitter_won != (reason == "winner"):
                # e.g. a failed return: the loser touched it last.
                reason = "winner" if hitter_won else "error"
        x, y = _float(row["land_x"]), _float(row["land_y"])
        landing = None
        if x is not None and y is not None:
            u, v = _project(matrix, x, y)
            landing = [
                round(float((u - 27) / 312 * COURT_W), 3),
                round(float((v - 100) / 684 * COURT_L), 3),
            ]
        rallies.append(
            {
                "dataset": "dshuttlenet",
                "match_id": match_id,
                "set": sets[int(row["set_id"])],
                "rally": int(row["rally_num"]),
                "serve_frame": frames[0],
                "last_hit_frame": frames[-1],
                "hit_frames": frames,
                "end_frame": int(end),
                "last_hitter_end": hitter_end,
                "winner_end": winner_end,
                "reason": reason,
                "detail": detail,
                "landing": landing,
                "score_after": {
                    "first": int(row["current_win_score"]),
                    "second": int(row["current_lose_score"]),
                },
                "first_end": first_end,
            }
        )
    rallies.sort(key=lambda r: r["serve_frame"])
    return rallies


def rallies(dataset, match_id):
    if dataset == "shuttleset":
        return shuttleset_rallies(match_id)
    if dataset == "dshuttlenet":
        return dshuttlenet_rallies(match_id)
    raise ValueError(dataset)


def first_set_span(labels, fps, before_s=10.0, after_s=10.0, limit_s=None):
    """Source frames [start, end) covering the first set's rallies."""
    first = [r for r in labels if r["set"] == min(r["set"] for r in labels)]
    start = max(0, min(r["serve_frame"] for r in first) - round(before_s * fps))
    end = max((r["end_frame"] or r["last_hit_frame"]) for r in first) + round(
        after_s * fps
    )
    if limit_s is not None:
        end = min(end, start + round(limit_s * fps))
    return start, end
