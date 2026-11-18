"""Rally outcome from what the shuttle and the players do around the last shot.

``rally_outcomes.OutcomeModel`` (v1) sees one fixed description of the
landing. This model also reads a short sequence: the shuttle track and every
player's court position and posture from BEFORE_S before the last contact to
AFTER_S after it, sampled every STEP_S. Players give the outcome away: who
stops, who turns to fetch the shuttle, who lets it fall.

The sequence is described relative to the last hitter: court coordinates are
turned so the hitter's end is always the same end. The network (a small
bidirectional GRU, trained with torch in training/train_rally_sequence.py) is
stored as JSON and evaluated here with numpy, so the application needs no
new dependency. Several networks trained from different seeds are averaged.
"""

import base64
import bisect

import numpy as np

from .match_analysis import COURT_LENGTH_M, COURT_WIDTH_M, NET_Y_M, on_court, project
from .rally_outcomes import (
    CLASSES,
    ENDS,
    FEATURE_SETS,
    flight,
    other,
    outcome_features,
)

FORMAT = "rally outcome sequence v2"
STEP_S = 0.04
BEFORE_S = 1.0
AFTER_S = 1.6
SLOTS = 2  # players described per court end
POSE = 6
PLAYER = 5 + POSE  # present, x, y, vx, vy, posture
SHUTTLE = 10
STEP_FEATURES = 3 + SHUTTLE + 2 * SLOTS * PLAYER
# COCO keypoints.
NOSE, SHOULDERS, WRISTS, HIPS, ANKLES = 0, (5, 6), (9, 10), (11, 12), (15, 16)
KEYPOINT_SCORE = 0.3


def steps(after_s=AFTER_S):
    return round(BEFORE_S / STEP_S) + round(after_s / STEP_S) + 1


def person(entry, width, height, matrix):
    """One stored player detection as (track id, court point, box, keypoints).

    ``entry`` is a row of the players stage ({"track_id", "box",
    "keypoints"}, pixels). The court point is the bottom centre of the box on
    the floor (None off the court or without a court view); box and
    keypoints are normalized to the picture.
    """
    box = entry.get("box")
    if not box or len(box) != 4 or not all(np.isfinite(v) for v in box):
        return None
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return None
    court = None
    if matrix is not None:
        court = project(matrix, (x1 + x2) / 2 / width, y2 / height)
        if not on_court(court):
            court = None
    points = entry.get("keypoints") or []
    keypoints = None
    if len(points) == 17:
        keypoints = np.asarray(points, float).reshape(17, -1)[:, :3].copy()
        keypoints[:, 0] /= width
        keypoints[:, 1] /= height
    return (
        entry.get("track_id"),
        court,
        (x1 / width, y1 / height, x2 / width, y2 / height),
        keypoints,
    )


def posture(box, keypoints):
    """Six numbers about how a player stands, relative to the box height."""
    x1, y1, x2, y2 = box
    h = max(y2 - y1, 1e-6)
    values = [min(2.0, (x2 - x1) / h), 0.0, 0.0, 0.0, 0.0, 0.0]
    if keypoints is None:
        return values

    def mean_y(indices):
        seen = [keypoints[i, 1] for i in indices if keypoints[i, 2] >= KEYPOINT_SCORE]
        return None if not seen else float(np.mean(seen))

    shoulders, hips, ankles = mean_y(SHOULDERS), mean_y(HIPS), mean_y(ANKLES)
    wrists = [keypoints[i, 1] for i in WRISTS if keypoints[i, 2] >= KEYPOINT_SCORE]
    if shoulders is not None and hips is not None:
        values[1] = float(np.clip((hips - shoulders) / h, -1, 1))  # torso
    if hips is not None and ankles is not None:
        values[2] = float(np.clip((ankles - hips) / h, -1, 1))  # legs
    if wrists and shoulders is not None:
        values[3] = float(np.clip((shoulders - min(wrists)) / h, -1, 1))  # raised
    if wrists and hips is not None:
        values[4] = float(np.clip((max(wrists) - hips) / h, -1, 1))  # reaching down
    values[5] = float(np.mean(keypoints[:, 2] >= KEYPOINT_SCORE))
    return values


def _turn(point, hitter_end):
    """Court point with the hitter's end at the near end, scaled to about +-1."""
    x, y = point
    if hitter_end == "far":
        x, y = COURT_WIDTH_M - x, COURT_LENGTH_M - y
    return (
        (x - COURT_WIDTH_M / 2) / (COURT_WIDTH_M / 2),
        (y - NET_Y_M) / NET_Y_M,
    )


def sequence_features(
    times,
    shuttle,
    people,
    after,
    landing,
    hitter_end,
    aspect,
    homography,
    usable=None,
    after_s=AFTER_S,
):
    """The [steps, STEP_FEATURES] description around the contact at ``after``.

    ``people[i]`` are the ``person`` tuples of frame i; ``homography(i)`` the
    court view's matrix or None; ``usable(i)`` is false for frames that must
    not be read (another camera view). Steps outside the data are left zero
    with their "seen" flag off.
    """
    count = steps(after_s)
    before = round(BEFORE_S / STEP_S)
    out = np.zeros((count, STEP_FEATURES), np.float32)
    t0 = times[after]
    index = []
    for n in range(count):
        t = t0 + (n - before) * STEP_S
        i = bisect.bisect_left(times, t)
        if i > 0 and (i == len(times) or t - times[i - 1] <= times[i] - t):
            i -= 1
        near = 0 <= i < len(times) and abs(times[i] - t) <= 0.75 * STEP_S
        index.append(i if near and (usable is None or usable(i)) else None)
    track = set(flight(times, shuttle, after, len(times), aspect))
    landed = None if landing is None else landing["index"]
    # Players: the track ids seen most at each end, ordered across the court.
    seen = {}
    for i in index:
        if i is None:
            continue
        for track_id, court, _box, _keypoints in people[i]:
            if court is not None and track_id is not None:
                seen.setdefault(track_id, []).append(_turn(court, hitter_end))
    slots = {}
    for own in (True, False):
        ids = [k for k, v in seen.items() if (np.median([p[1] for p in v]) > 0) == own]
        ids = sorted(ids, key=lambda k: -len(seen[k]))[:SLOTS]
        ids.sort(key=lambda k: float(np.mean([p[0] for p in seen[k]])))
        for number, track_id in enumerate(ids):
            slots[track_id] = (0 if own else SLOTS) + number
    previous = {}
    last_shuttle = None
    for n, i in enumerate(index):
        row = out[n]
        row[0] = (n - before) * STEP_S / AFTER_S
        row[2] = float(hitter_end == "far")
        if i is None:
            continue
        row[1] = 1.0
        p = shuttle[i]
        if p is not None:
            s = row[3 : 3 + SHUTTLE]
            s[0] = 1.0
            s[1], s[2] = p[0] - 0.5, p[1] - 0.5
            matrix = homography(i)
            point = None if matrix is None else project(matrix, *p)
            if point is not None:
                s[3] = 1.0
                s[4], s[5] = np.clip(_turn(point, hitter_end), -3, 3)
            if last_shuttle is not None and n - last_shuttle[0] <= 3:
                gap = n - last_shuttle[0]
                s[6] = np.clip((p[0] - last_shuttle[1][0]) * 10 / gap, -2, 2)
                s[7] = np.clip((p[1] - last_shuttle[1][1]) * 10 / gap, -2, 2)
            s[8] = float(i in track)
            last_shuttle = (n, p)
        if landed is not None:
            row[3 + 9] = float(i >= landed)
        for track_id, court, box, keypoints in people[i]:
            slot = slots.get(track_id)
            if slot is None or court is None:
                continue
            start = 3 + SHUTTLE + slot * PLAYER
            if row[start]:
                continue
            x, y = _turn(court, hitter_end)
            row[start : start + 3] = (1.0, x, y)
            if slot in previous and n - previous[slot][0] <= 3:
                gap = n - previous[slot][0]
                row[start + 3] = np.clip((x - previous[slot][1]) * 10 / gap, -2, 2)
                row[start + 4] = np.clip((y - previous[slot][2]) * 10 / gap, -2, 2)
            previous[slot] = (n, x, y)
            row[start + 5 : start + PLAYER] = posture(box, keypoints)
    return out


def mirrored(sequence):
    """The same rally seen in a mirror (left and right swapped)."""
    out = sequence.copy()
    s = 3
    out[:, s + 1] = -sequence[:, s + 1]
    out[:, s + 4] = -sequence[:, s + 4]
    out[:, s + 6] = -sequence[:, s + 6]
    for end in range(2):
        base = 3 + SHUTTLE + end * SLOTS * PLAYER
        blocks = [
            sequence[:, base + k * PLAYER : base + (k + 1) * PLAYER].copy()
            for k in range(SLOTS)
        ]
        # Slots are ordered across the court: mirror the order too, keeping a
        # lone player in the first slot.
        both = bool(blocks[1][:, 0].any())
        order = [1, 0] if both else [0, 1]
        for k, source in enumerate(order):
            block = blocks[source]
            block[:, 1] = -block[:, 1]
            block[:, 3] = -block[:, 3]
            out[:, base + k * PLAYER : base + (k + 1) * PLAYER] = block
    return out


# Network ----------------------------------------------------------------------


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _gru(x, w_ih, w_hh, b_ih, b_hh):
    """torch.nn.GRU, one direction: x [T, D] -> hidden states [T, H]."""
    hidden = w_hh.shape[1]
    h = np.zeros(hidden)
    out = np.zeros((len(x), hidden))
    gi_all = x @ w_ih.T + b_ih
    for t in range(len(x)):
        gi, gh = gi_all[t], w_hh @ h + b_hh
        r = _sigmoid(gi[:hidden] + gh[:hidden])
        z = _sigmoid(gi[hidden : 2 * hidden] + gh[hidden : 2 * hidden])
        n = np.tanh(gi[2 * hidden :] + r * gh[2 * hidden :])
        h = (1 - z) * n + z * h
        out[t] = h
    return out


def encode_array(array):
    array = np.asarray(array, "<f4")
    return {
        "shape": list(array.shape),
        "data": base64.b64encode(array.tobytes()).decode("ascii"),
    }


def decode_array(item):
    data = np.frombuffer(base64.b64decode(item["data"]), "<f4")
    return data.reshape(item["shape"]).astype(float)


def forward(weights, sequence, summary):
    """(class logits [3], logit that the last hitter's end won)."""
    w = weights
    x = np.maximum(sequence @ w["input.weight"].T + w["input.bias"], 0)
    ahead = _gru(
        x,
        w["gru.weight_ih_l0"],
        w["gru.weight_hh_l0"],
        w["gru.bias_ih_l0"],
        w["gru.bias_hh_l0"],
    )
    back = _gru(
        x[::-1],
        w["gru.weight_ih_l0_reverse"],
        w["gru.weight_hh_l0_reverse"],
        w["gru.bias_ih_l0_reverse"],
        w["gru.bias_hh_l0_reverse"],
    )[::-1]
    states = np.concatenate([ahead, back], axis=1)
    pooled = np.concatenate([states.mean(0), states.max(0), ahead[-1], back[0]])
    g = np.maximum(summary @ w["summary.weight"].T + w["summary.bias"], 0)
    h = np.concatenate([pooled, g])
    h = np.maximum(h @ w["hidden.weight"].T + w["hidden.bias"], 0)
    classes = h @ w["classes.weight"].T + w["classes.bias"]
    won = h @ w["won.weight"].T + w["won.bias"]
    return classes, float(won[0])


class SequenceOutcomeModel:
    """The trained networks (JSON document) behind rally_outcomes.analyse."""

    def __init__(self, document):
        if (
            document.get("format") != FORMAT
            or tuple(document["features"]) not in FEATURE_SETS
            or tuple(document["classes"]) != CLASSES
            or document["step_features"] != STEP_FEATURES
        ):
            raise ValueError("Rally outcome model does not match this code's features")
        self.name = document.get("name", "rally outcome sequence model")
        self.features = tuple(document["features"])
        self.after_s = float(document.get("after_s", AFTER_S))
        self.mean = np.asarray(document["mean"], float)
        self.scale = np.asarray(document["scale"], float)
        self.members = [
            {k: decode_array(v) for k, v in member.items()}
            for member in document["members"]
        ]

    def probabilities(self, sequence, summary):
        """(P(in), P(out), P(net)) and P(the last hitter's end won)."""
        summary = (np.asarray(summary, float) - self.mean) / self.scale
        classes, won = [], []
        for weights in self.members:
            logits, logit = forward(weights, np.asarray(sequence, float), summary)
            e = np.exp(logits - logits.max())
            classes.append(e / e.sum())
            won.append(_sigmoid(logit))
        return np.mean(classes, axis=0), float(np.mean(won))

    def __call__(self, line, group, landing):
        """Outcome for analyse(); None when the last hitter's end is unknown."""
        last = line["contacts"][group["shots"][-1]]
        hitter = last["court_end"]
        if hitter not in ENDS:
            return None
        frame = last["frame"]
        times = line["times"]
        segment = line["segments"][frame]
        people = line.get("people")
        if people is None:
            people = [
                [(n, point, (0.0, 0.0, 0.1, 0.3), None) for n, point in enumerate(row)]
                for row in line["players"]
            ]

        def homography(i):
            view = line["view_at"][i]
            return None if view is None else line["homographies"][view]

        family = "serve" if last["kind"] == "serve" else last["family"]
        summary = outcome_features(
            times,
            line["shuttle"],
            line["players"],
            frame,
            landing,
            hitter,
            line["mode"],
            line["aspect"],
            family,
            self.features,
        )
        sequence = sequence_features(
            times,
            line["shuttle"],
            people,
            frame,
            landing,
            hitter,
            line["aspect"],
            homography,
            lambda i: line["segments"][i] == segment,
            self.after_s,
        )
        classes, won = self.probabilities(sequence, summary)
        hitter_won = won >= 0.5
        if hitter_won:
            detail = "in"
        else:
            detail = "out" if classes[1] >= classes[2] else "net"
        return {
            "winner_end": hitter if hitter_won else other(hitter),
            "reason": "winner" if hitter_won else "error",
            "detail": detail,
            "confidence": round(float(won if hitter_won else 1 - won), 3),
        }


__all__ = [
    "AFTER_S",
    "BEFORE_S",
    "FORMAT",
    "STEP_FEATURES",
    "STEP_S",
    "SequenceOutcomeModel",
    "decode_array",
    "encode_array",
    "forward",
    "mirrored",
    "person",
    "posture",
    "sequence_features",
    "steps",
]
