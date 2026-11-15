"""Rally boundaries, last-shot landing and rally outcome.

The pipeline's ``outcomes`` stage runs this after the per-window stages and
writes one record per rally: where it starts and ends, the court end of the
last hitter, where the last shot came down (court metres through the camera
view's floor homography), who won the rally (by court end) and whether it
ended on a winner or an error. ``match_analysis.py`` reads that record; it
never runs this inference itself.

Everything here works on a small per-video *timeline* (shuttle image points,
court views, player court positions, contacts and the rallies stage's
proposals), so the same code scores published labels in training/.

Court frame as in MatchAnalysis: x 0..6.1 across from the far-left outer
sideline, y 0..13.4 from the far baseline, net at y = 6.7.

Limits, stated in the document too: the shuttle is tracked only in the image,
so a landing is the image point where the shuttle comes to rest (or, failing
that, where its track ends), projected onto the floor. A shuttle caught high
in the net or one whose track ends in the air projects to the wrong place.
"""

import bisect
import math

import numpy as np

from .match_analysis import (
    COURT_LENGTH_M,
    COURT_WIDTH_M,
    NET_Y_M,
    RALLY_BREAK_S,
    SINGLES_SIDELINES_M,
    project,
    rally_breaks,
)

METHOD = "rally boundaries and last-shot landing v1"
# Search for the landing up to this long after the last contact.
LANDING_SEARCH_S = 3.0
# A track ends at a gap this long or a jump faster than this (image heights
# per second; a smash crosses the picture in about a third of a second).
FLIGHT_GAP_S = 0.3
MAX_SPEED_PER_S = 4.0
# The descent ends once the shuttle has risen this much (image heights) above
# its lowest point so far.
DESCENT_TOLERANCE = 0.009
# A shuttle at rest: this long within STILL_RADIUS (image heights) of the
# landing point, seen in this share of the frames.
STILL_S = 0.3
STILL_RADIUS = 0.012
# Lower than this (image heights) is jitter of a shuttle lying still, not
# further descent.
STILL_STEP = 0.002
STILL_VISIBLE = 0.6
# Landings this close to the net (metres) are called net.
NET_BAND_M = 0.4
ENDS = ("far", "near")


def other(end):
    return {"far": "near", "near": "far"}.get(end)


def court_end(point):
    if point is None:
        return None
    return "far" if point[1] < NET_Y_M else "near"


def in_court(point, mode):
    """Inside the rally lines: singles or doubles sidelines, full length."""
    left, right = (0.0, COURT_WIDTH_M) if mode == "doubles" else SINGLES_SIDELINES_M
    return left <= point[0] <= right and 0.0 <= point[1] <= COURT_LENGTH_M


def line_distance(point, mode):
    """Distance (m) from the nearest rally line; positive inside."""
    left, right = (0.0, COURT_WIDTH_M) if mode == "doubles" else SINGLES_SIDELINES_M
    inside = min(point[0] - left, right - point[0], point[1], COURT_LENGTH_M - point[1])
    if inside >= 0:
        return inside
    dx = max(left - point[0], 0, point[0] - right)
    dy = max(-point[1], 0, point[1] - COURT_LENGTH_M)
    return -math.hypot(dx, dy)


# Landing --------------------------------------------------------------------


def flight(times, shuttle, after, until, aspect):
    """The shuttle's continuous track after a contact.

    Starts just after index ``after`` and stops at a jump no shuttle could
    make (a false detection elsewhere in the picture), a gap longer than
    FLIGHT_GAP_S or ``until``. Returns indices into ``times``/``shuttle``.
    """
    points = []
    for i in range(after + 1, min(until, len(times))):
        p = shuttle[i]
        if p is None:
            if points and times[i] - times[points[-1]] > FLIGHT_GAP_S:
                break
            continue
        if points:
            q = shuttle[points[-1]]
            dt = max(times[i] - times[points[-1]], 1e-6)
            step = math.hypot((p[0] - q[0]) * aspect, p[1] - q[1])
            if step / dt > MAX_SPEED_PER_S:
                break
        points.append(i)
    return points


def find_landing(times, shuttle, after, until, aspect, homography):
    """Where the shuttle comes down after a contact.

    ``times`` are source seconds and ``shuttle`` normalized image points (or
    None) for consecutive frames; ``after`` and ``until`` are indices into
    them (the last contact and the end of the search). ``aspect`` is
    width/height, ``homography(index)`` the view's matrix or None.

    A falling shuttle moves down the picture until it reaches the floor, so
    the landing is the lowest image point of the track's descent: the track
    first rises (or not at all), then descends; the descent ends where the
    shuttle stops going down by more than DESCENT_TOLERANCE. Kind "rest" when
    it then lies still for STILL_S, "descent" when the descent ended without
    a rest, "track_end" when the track never descended (it ended in the air,
    so its projection is unreliable). Returns None without a track.
    """
    points = flight(times, shuttle, after, until, aspect)
    if len(points) < 3:
        return None
    tolerance = DESCENT_TOLERANCE
    low = shuttle[points[0]][1]
    descending, best = False, None
    for i in points:
        y = shuttle[i][1]
        if not descending:
            low = min(low, y)
            if y > low + tolerance:
                descending, best = True, i
            continue
        if y > shuttle[best][1] + STILL_STEP:
            best = i
        elif y < shuttle[best][1] - tolerance:
            break
    if not descending:
        landing = {
            "index": points[-1],
            "image": shuttle[points[-1]],
            "kind": "track_end",
        }
    else:
        landing = {"index": best, "image": shuttle[best], "kind": "descent"}
        stop = bisect.bisect_right(times, times[best] + STILL_S, best, len(times))
        near = [
            p
            for p in shuttle[best:stop]
            if p is not None
            and math.hypot((p[0] - shuttle[best][0]) * aspect, p[1] - shuttle[best][1])
            <= STILL_RADIUS
        ]
        if stop - best >= 3 and len(near) >= STILL_VISIBLE * (stop - best):
            landing["kind"] = "rest"
    matrix = homography(landing["index"])
    point = None if matrix is None else project(matrix, *landing["image"])
    landing["court"] = point
    return landing


# Outcome rule ---------------------------------------------------------------


def rule_outcome(hitter_end, landing, mode):
    """Transparent call from the last hitter's end and the landing.

    - no landing: unknown;
    - on the hitter's own side or within NET_BAND_M of the net: the shot did
      not get over: error, net;
    - on the opponent's side inside the rally lines: winner (landed in);
    - outside them: error, out.
    The reason is the last hitter's: a winner means the last hitter won.
    """
    if hitter_end is None or landing is None or landing.get("court") is None:
        return None
    point = landing["court"]
    if not (
        -3 <= point[0] <= COURT_WIDTH_M + 3 and -3 <= point[1] <= COURT_LENGTH_M + 3
    ):
        return None
    side = court_end(point)
    if side == hitter_end or abs(point[1] - NET_Y_M) <= NET_BAND_M:
        return {"winner_end": other(hitter_end), "reason": "error", "detail": "net"}
    if in_court(point, mode):
        return {"winner_end": hitter_end, "reason": "winner", "detail": "in"}
    return {"winner_end": other(hitter_end), "reason": "error", "detail": "out"}


# Boundaries -----------------------------------------------------------------


def rallies_from_contacts(shots, times, segments, serves=(), ends=()):
    """Rally spans over the contacts, as the builder has always made them.

    ``shots`` are dicts with at least "frame" and "kind". Returns a list of
    {"start_frame", "end_frame", "start_source", "end_source", "shots":
    [indices], "opens_with_serve"}.
    """
    starts, closes = rally_breaks(shots, times, segments, serves, ends)
    groups = []
    for index in range(len(shots)):
        if index in starts:
            frame, source, served = starts[index]
            groups.append(
                {
                    "start_frame": frame,
                    "start_source": source,
                    "opens_with_serve": served,
                    "shots": [],
                }
            )
        groups[-1]["shots"].append(index)
    for group in groups:
        last = group["shots"][-1]
        end, source = closes.get(last, (shots[last]["frame"], "last_contact"))
        group.update(end_frame=end, end_source=source)
    return groups


# Learned outcome ------------------------------------------------------------

FEATURES = (
    "doubles",
    "hitter_known",
    "landing_found",
    "kind_rest",
    "kind_descent",
    "kind_track_end",
    "depth_m",
    "lateral_m",
    "line_distance_m",
    "in_court",
    "own_side",
    "net_distance_m",
    "flight_s",
    "flight_points",
    "visible_after_contact",
    "image_x",
    "image_y",
    "nearest_player_m",
    "visible_after_landing",
    "final_dy",
    "family_attack",
    "family_short",
    "family_long",
    "family_flat",
    "family_serve",
)
# The last stroke's family, from the app's names or the datasets' published
# stroke types, in five groups.
FAMILY_GROUPS = {
    **dict.fromkeys(("smash", "net kill", "net_kill", "wrist smash", "rush"), "attack"),
    **dict.fromkeys(
        (
            "net",
            "drop",
            "block",
            "push",
            "net shot",
            "return net",
            "cross-court net shot",
            "passive drop",
        ),
        "short",
    ),
    **dict.fromkeys(("clear", "lift", "lob", "defensive return lob"), "long"),
    **dict.fromkeys(
        ("drive", "driven flight", "back-court drive", "defensive return drive"), "flat"
    ),
    **dict.fromkeys(
        ("serve", "short serve", "long serve", "short service", "long service"), "serve"
    ),
}
CLASSES = ("winner_in", "error_out", "error_net")


def outcome_features(
    times, shuttle, players, after, landing, hitter_end, mode, aspect, family=None
):
    """Fixed-length description of how the last shot ended.

    ``players[i]`` are the court positions seen at index i. Depth is measured
    from the net towards the opponent's baseline (negative: the shot stayed
    on the hitter's side).
    """
    values = dict.fromkeys(FEATURES, 0.0)
    values["doubles"] = float(mode == "doubles")
    values["hitter_known"] = float(hitter_end in ENDS)
    horizon = bisect.bisect_right(times, times[after] + 1.5)
    seen = sum(p is not None for p in shuttle[after + 1 : horizon])
    values["visible_after_contact"] = seen / max(1, horizon - after - 1)
    group = FAMILY_GROUPS.get(family)
    if group is not None:
        values[f"family_{group}"] = 1.0
    if landing is None:
        return [values[k] for k in FEATURES]
    index = landing["index"]
    values["landing_found"] = 1.0
    values[f"kind_{landing['kind']}"] = 1.0
    values["flight_s"] = min(3.0, times[index] - times[after])
    values["flight_points"] = (
        min(90, len(flight(times, shuttle, after, index + 1, aspect))) / 90
    )
    values["image_x"], values["image_y"] = landing["image"]
    point = landing.get("court")
    if point is not None and abs(point[0]) < 50 and abs(point[1]) < 50:
        x, y = point
        towards = 1.0 if hitter_end == "far" else -1.0 if hitter_end == "near" else 0.0
        values["depth_m"] = float(np.clip((y - NET_Y_M) * towards, -8, 8))
        values["lateral_m"] = float(np.clip(abs(x - COURT_WIDTH_M / 2), 0, 6))
        values["line_distance_m"] = float(np.clip(line_distance(point, mode), -3, 3))
        values["in_court"] = float(in_court(point, mode))
        values["own_side"] = float(values["depth_m"] < 0)
        values["net_distance_m"] = float(min(3.0, abs(y - NET_Y_M)))
        around = [
            math.dist(point, q)
            for j in range(max(0, index - 3), min(len(players), index + 4))
            for q in players[j]
        ]
        values["nearest_player_m"] = min(8.0, min(around)) if around else 8.0
    else:
        values["nearest_player_m"] = 8.0
    stop = bisect.bisect_right(times, times[index] + 1.0)
    values["visible_after_landing"] = sum(
        p is not None for p in shuttle[index:stop]
    ) / max(1, stop - index)
    track = [shuttle[j] for j in flight(times, shuttle, after, index + 1, aspect)][-4:]
    if len(track) >= 2:
        values["final_dy"] = float(np.clip((track[-1][1] - track[0][1]) * 10, -2, 2))
    return [float(values[k]) for k in FEATURES]


class OutcomeModel:
    """A small multilayer perceptron stored as JSON (no pickle, no torch)."""

    def __init__(self, document):
        if (
            tuple(document["features"]) != FEATURES
            or tuple(document["classes"]) != CLASSES
        ):
            raise ValueError("Rally outcome model does not match this code's features")
        self.mean = np.asarray(document["mean"], float)
        self.scale = np.asarray(document["scale"], float)
        self.layers = [
            (np.asarray(w, float), np.asarray(b, float)) for w, b in document["layers"]
        ]
        self.name = document.get("name", "rally outcome model")

    def probabilities(self, features):
        h = (np.asarray(features, float) - self.mean) / self.scale
        for n, (w, b) in enumerate(self.layers):
            h = h @ w + b
            if n + 1 < len(self.layers):
                h = np.maximum(h, 0)
        h = np.exp(h - h.max())
        return h / h.sum()

    def __call__(self, line, group, landing):
        """Outcome for analyse(); None when the last hitter's end is unknown."""
        last = line["contacts"][group["shots"][-1]]
        hitter = last["court_end"]
        if hitter not in ENDS:
            return None
        features = outcome_features(
            line["times"],
            line["shuttle"],
            line["players"],
            last["frame"],
            landing,
            hitter,
            line["mode"],
            line["aspect"],
            "serve" if last["kind"] == "serve" else last["family"],
        )
        p = self.probabilities(features)
        best = int(np.argmax(p))
        won = CLASSES[best] == "winner_in"
        return {
            "winner_end": hitter if won else other(hitter),
            "reason": "winner" if won else "error",
            "detail": {"winner_in": "in", "error_out": "out", "error_net": "net"}[
                CLASSES[best]
            ],
            "confidence": round(float(p[0] if won else 1 - p[0]), 3),
        }


# Timeline -------------------------------------------------------------------


def timeline(inputs):
    """What the outcome stage reads from a processing plan's stored runs.

    ``inputs`` is a match_analysis.MatchInputs (identity is not used):
    per frame the shuttle's image point, the camera segment, the court view
    and the players' court positions; the contacts with their court end; the
    rallies stage's serve and rally-end proposals.
    """
    from . import match_analysis as ma

    video = inputs.video
    parts = ma._parts(inputs.plan)
    views = ma._court_views(parts, inputs.runs)
    observations, segments = ma._observations(inputs, parts, views)
    shuttle = ma._shuttle_track(inputs, parts)
    count = video["frame_count"]
    view_at = [None] * count
    for number, view in enumerate(views):
        for frame in range(view.start_frame, min(view.end_frame, count)):
            view_at[frame] = number
    contacts = []
    for part in parts:
        run = inputs.runs[part["contacts"]]
        recognized = {}
        if part["recognition"]:
            for c in ma._owned(inputs.runs[part["recognition"]], part):
                if c.get("contact_candidate_id"):
                    recognized[c["contact_candidate_id"]] = c
        for c in sorted(ma._owned(run, part), key=lambda c: c["frame"]):
            learned = c.get("learned") or {}
            rec = recognized.get(c["id"], {})
            kind = rec.get("kind") or learned.get("kind")
            end = learned.get("court_end") or (c.get("evidence") or {}).get("court_end")
            contacts.append(
                {
                    "frame": c["frame"],
                    "kind": kind if kind in ("serve", "shot") else None,
                    "family": rec.get("family") or learned.get("family"),
                    "court_end": end if end in ENDS else None,
                    "score": c.get("score"),
                }
            )
    unique = []
    for c in sorted(contacts, key=lambda c: c["frame"]):
        if not unique or unique[-1]["frame"] != c["frame"]:
            unique.append(c)
    serves, ends = ma._proposals(inputs, parts)
    return {
        "mode": video["mode"],
        "fps": float(video["fps"]),
        "aspect": video["width"] / video["height"],
        "times": list(inputs.times),
        "shuttle": [
            None if x is None else (x, y) for x, y in zip(shuttle.x, shuttle.y)
        ],
        "segments": segments,
        "view_at": view_at,
        "homographies": [v.homography for v in views],
        "players": [
            [o[2] for o in items if o[2] is not None] for items in observations
        ],
        "contacts": unique,
        "serves": serves,
        "ends": ends,
    }


def _homography(line, index):
    view = line["view_at"][index]
    return None if view is None else line["homographies"][view]


def analyse(line, model=None):
    """Rallies with boundaries, last-shot landing and outcome.

    Returns a list of plain dicts (the outcomes stage's ``rallies``):
    start/end frame and source, the contact frames, the last hitter's court
    end, the landing and the outcome. Winners are given by court end; the
    builder turns ends into teams.
    """
    times, contacts = line["times"], line["contacts"]
    count = len(times)
    groups = rallies_from_contacts(
        contacts, times, line["segments"], line["serves"], line["ends"]
    )
    result = []
    for number, group in enumerate(groups):
        last = contacts[group["shots"][-1]]
        frame = last["frame"]
        # Search until the next rally starts, a camera cut, or the limit.
        limit = bisect.bisect_right(times, times[frame] + LANDING_SEARCH_S)
        if number + 1 < len(groups):
            limit = min(limit, groups[number + 1]["start_frame"])
        segment = line["segments"][frame]
        cut = next(
            (
                f
                for f in range(frame + 1, min(limit, count))
                if line["segments"][f] != segment
            ),
            None,
        )
        if cut is not None:
            limit = cut
        landing = find_landing(
            times,
            line["shuttle"],
            frame,
            limit,
            line["aspect"],
            lambda i: _homography(line, i),
        )
        hitter = last["court_end"]
        outcome = rule_outcome(hitter, landing, line["mode"])
        source = "rule"
        if model is not None:
            predicted = model(line, group, landing)
            if predicted is not None:
                outcome, source = predicted, "model"
        end_frame, end_source = group["end_frame"], group["end_source"]
        if landing is not None and landing["kind"] != "track_end":
            end_frame, end_source = landing["index"], "landing"
        record = {
            "start_frame": group["start_frame"],
            "end_frame": max(end_frame, frame),
            "start_source": group["start_source"],
            "end_source": end_source,
            "opens_with_serve": group["opens_with_serve"],
            "shot_frames": [contacts[i]["frame"] for i in group["shots"]],
            "last_hitter_end": hitter,
            "landing": None,
            "outcome": None,
        }
        if landing is not None and landing.get("court") is not None:
            point = landing["court"]
            record["landing"] = {
                "frame": landing["index"],
                "kind": landing["kind"],
                "image": [round(v, 4) for v in landing["image"]],
                "court": [round(v, 3) for v in point],
                "in_court": in_court(point, line["mode"]),
                "line_distance": round(line_distance(point, line["mode"]), 3),
            }
        if outcome is not None:
            record["outcome"] = {**outcome, "source": source}
        result.append(record)
    return result


# Pipeline stage -------------------------------------------------------------

MANIFEST_KEY = "rally_outcome"


def manifest_entry():
    """The registered outcome model, or None when none is registered."""
    import json

    from .config import MODEL_MANIFEST

    return json.loads(MODEL_MANIFEST.read_text(encoding="utf-8")).get(MANIFEST_KEY)


def load_model():
    """(model, None) or (None, why the rule is used instead)."""
    import hashlib
    import json

    from .config import WEIGHTS

    entry = manifest_entry()
    if entry is None:
        return None, "No rally outcome model is registered in the model manifest"
    path = WEIGHTS / entry["name"]
    if not path.is_file():
        return None, f"The rally outcome model is not installed ({entry['name']})"
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        return (
            None,
            "The installed rally outcome model does not match the model manifest",
        )
    try:
        return OutcomeModel(json.loads(data)), None
    except (KeyError, TypeError, ValueError) as error:
        return None, f"The rally outcome model cannot be read: {error}"


def run_stage(video, store, plan, times, output, progress):
    """The pipeline's outcomes stage: write runs/<run ID>.json at ``output``."""
    from .match_analysis import MatchInputs, load_plan_runs
    from .video import write_json

    runs = load_plan_runs(store, video["id"], plan, outcomes=False)
    line = timeline(MatchInputs(video, list(times), plan, runs))
    progress(0.5)
    model, problem = load_model()
    entry = manifest_entry() if model is not None else None
    rallies = analyse(line, model)
    write_json(
        output,
        {
            "schema_version": 1,
            "stage": "outcomes",
            "video_id": video["id"],
            "video_sha256": video["sha256"],
            "start_frame": 0,
            "end_frame": len(times),
            "method": METHOD,
            "model": None
            if entry is None
            else {
                "name": entry["name"],
                "sha256": entry["sha256"],
                "title": model.name,
            },
            "model_unavailable": problem,
            "meaning": "Automatic rally boundaries, last-shot landings and outcomes; unreviewed",
            "rally_count": len(rallies),
            "rallies": rallies,
        },
    )
    progress(1)


__all__ = [
    "ENDS",
    "METHOD",
    "RALLY_BREAK_S",
    "analyse",
    "court_end",
    "find_landing",
    "in_court",
    "line_distance",
    "load_model",
    "other",
    "rallies_from_contacts",
    "rule_outcome",
    "run_stage",
    "timeline",
]
