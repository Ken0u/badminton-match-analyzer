"""Four player slots for a doubles event model (see event_model.py).

The singles model gives each court end one player. Doubles has two at each
end, and partners swap places freely, so a slot cannot mean "left" or "right".
Instead each tracked player keeps one slot for a whole camera view: slots 0 and
1 are the far pair, 2 and 3 the near pair, and which partner gets which slot
carries no meaning. A track that breaks is rejoined first with the rule the
identities stage uses (actor_linking). The model's hitter output names a slot.

Trained on three matches, the network finds the court end that hit but not
which partner (about chance on the match it did not train on), so the partner
is chosen by choose_partner from arm motion and distance to the shuttle.
"""

import math
from collections import defaultdict

import numpy as np

from .actor_linking import _join_breaks
from .event_model import COURT_ENDS, PLAYER, _player_vector

SLOTS = 4
DOUBLES_FEATURES = SLOTS * PLAYER + 6
# choose_partner: steps looked at either side of the contact, and the weights
# of wrist speed, elbow speed and closeness to the shuttle (all in body
# heights). Fitted on S2 Doubles match 1 only; 94% right on match 2's labelled
# contacts where both partners are tracked. One tournament and camera.
PARTNER_WINDOW = 3
PARTNER_WEIGHTS = (4.31, 2.66, 3.13)


def slot_end(slot):
    return COURT_ENDS[slot // 2]


def _chains(rows, width, height, fps):
    """Joined player tracks of one view, each with its court end."""
    actors = {}
    for index, row in enumerate(rows):
        people = [
            p
            for p in row["players"]
            if p.get("track_id") is not None and len(p.get("keypoints", [])) == 17
        ]
        camera = row.get("camera_segment_start_frame")
        camera = -1 if camera is None else camera
        for person in people:
            key = (camera, person["track_id"])
            actor = actors.setdefault(
                key,
                {
                    "actor_id": key,
                    "camera": camera,
                    "frames": set(),
                    "feet": {},
                    "below": [],
                },
            )
            box = person["box"]
            actor["frames"].add(index)
            actor["feet"][index] = ((box[0] + box[2]) / 2, box[3])
            if len(people) > 1:
                actor["below"].append(
                    sum(o["box"][3] > box[3] for o in people if o is not person)
                    / (len(people) - 1)
                )
    video = {"mode": "doubles", "fps": fps, "width": width, "height": height}
    joined = _join_breaks(video, list(actors.values()))["players"] if actors else {}
    chains = defaultdict(lambda: {"members": [], "feet": {}, "ends": defaultdict(int)})
    for key, actor in actors.items():
        chain = chains[joined[key]["continuity_id"]]
        chain["members"].append(key)
        chain["feet"].update(actor["feet"])
        end = joined[key]["court_end"]
        if end is None:
            # Never seen with another player: placed by where the feet are.
            lowest = float(np.median([y for _, y in actor["feet"].values()]))
            end = "far" if lowest < height * 0.55 else "near"
        chain["ends"][end] += len(actor["frames"])
    for chain in chains.values():
        chain["first"], chain["last"] = min(chain["feet"]), max(chain["feet"])
        chain["end"] = max(chain["ends"], key=chain["ends"].get)
    return list(chains.values())


def assign_slots(rows, width, height, fps):
    """Map each (camera, track) of a view to one of the four slots.

    Longer tracks are placed first. A track only takes a slot nobody holds
    during its own span; if both slots of its end are open it follows the
    earlier holder that stood nearest. A third simultaneous track at one end
    (an official, a misplaced detection) gets no slot.
    """
    held = {slot: [] for slot in range(SLOTS)}
    for chain in sorted(
        _chains(rows, width, height, fps), key=lambda c: -len(c["feet"])
    ):
        base = COURT_ENDS.index(chain["end"]) * 2
        options = []
        for slot in (base, base + 1):
            if any(
                chain["first"] <= o["last"] and o["first"] <= chain["last"]
                for o in held[slot]
            ):
                continue
            cost = math.inf
            for other in held[slot]:
                if other["last"] < chain["first"]:
                    a, b = other["feet"][other["last"]], chain["feet"][chain["first"]]
                else:
                    a, b = chain["feet"][chain["last"]], other["feet"][other["first"]]
                cost = min(cost, math.hypot(a[0] - b[0], a[1] - b[1]))
            options.append((cost, slot))
        if options:
            held[min(options)[1]].append(chain)
    return {
        key: slot
        for slot, chains in held.items()
        for c in chains
        for key in c["members"]
    }


def doubles_observations(player_rows, shuttle_points, width, height, fps):
    """Per-frame poses in four slots and the shuttle, before motion features.

    Also returns each frame's tracker number per slot (None where empty).
    """
    slots = assign_slots(player_rows, width, height, fps)
    values = np.zeros((len(player_rows), SLOTS * PLAYER + 3), np.float32)
    tracks = []
    for index, (row, ball) in enumerate(zip(player_rows, shuttle_points)):
        camera = row.get("camera_segment_start_frame")
        camera = -1 if camera is None else camera
        seen = [None] * SLOTS
        for person in row["players"]:
            slot = slots.get((camera, person.get("track_id")))
            if slot is None or len(person.get("keypoints", [])) != 17:
                continue
            values[index, slot * PLAYER : (slot + 1) * PLAYER] = _player_vector(
                person, width, height
            )
            seen[slot] = person["track_id"]
        if ball.get("visible") and ball.get("x") is not None:
            values[index, SLOTS * PLAYER :] = (ball["x"] / width, ball["y"] / height, 1)
        tracks.append(tuple(seen))
    return values, tracks


def _arm_evidence(values, step, slot, width, height):
    """Wrist speed, elbow speed and nearest arm-to-shuttle distance of a slot.

    Measured in the player's body heights around one step; None if the slot
    is empty there, and no distance if the shuttle was not seen beside them.
    """
    start, stop = max(0, step - PARTNER_WINDOW), step + PARTNER_WINDOW + 1
    block = values[start:stop, slot * PLAYER : (slot + 1) * PLAYER]
    present = block[:, 55] > 0
    if not present.any():
        return None
    scale = np.array([width, height], np.float32)
    points = block[:, :51].reshape(-1, 17, 3)
    ball = values[start:stop, SLOTS * PLAYER : SLOTS * PLAYER + 3]
    body = max(
        1.0, float(np.median((block[present, 54] - block[present, 52]))) * height
    )
    seen = points[:, :, 2] > 0
    travel = np.linalg.norm((points[1:, :, :2] - points[:-1, :, :2]) * scale, axis=-1)
    travel[~(seen[1:] & seen[:-1] & present[1:, None] & present[:-1, None])] = 0
    reach = np.linalg.norm((points[:, 7:11, :2] - ball[:, None, :2]) * scale, axis=-1)
    reach[~(seen[:, 7:11] & present[:, None] & (ball[:, 2:3] > 0))] = np.inf
    distance = float(reach.min())
    return (
        float(travel[:, 9:11].max(initial=0)) / body,
        float(travel[:, 7:9].max(initial=0)) / body,
        distance / body if math.isfinite(distance) else None,
    )


def choose_partner(values, step, end, width, height):
    """Which of an end's two slots hit at this step, or None if neither is seen.

    values are doubles_observations rows at the trained frame rate. A lone
    tracked partner is taken; between two, the faster arm nearer the shuttle.
    """
    base = COURT_ENDS.index(end) * 2
    first = _arm_evidence(values, step, base, width, height)
    second = _arm_evidence(values, step, base + 1, width, height)
    if first is None or second is None:
        return None if first is second else base + (first is None)
    score = PARTNER_WEIGHTS[0] * (second[0] - first[0]) + PARTNER_WEIGHTS[1] * (
        second[1] - first[1]
    )
    if first[2] is not None and second[2] is not None:
        score += PARTNER_WEIGHTS[2] * (first[2] - second[2])
    return base + (score > 0)
