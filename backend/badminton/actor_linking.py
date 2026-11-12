"""Provisional actor continuity from repeated observations of identical frames.

These anonymous hypotheses do not identify a roster member or bridge camera
edits. They inherit the limits of each input tracker; reviewed IDs stay separate.
"""

import hashlib
import itertools
import math
from collections import defaultdict
from statistics import median

METHOD = "unique same-source overlap tracks v1"
RECIPE = {
    "method": METHOD,
    "minimum_iou": 0.7,
    "minimum_alternative_margin": 0.15,
    "minimum_support_frames": 5,
    "minimum_support_span_s": 0.16,
    "minimum_agreement_fraction": 0.85,
    "minimum_detection_confidence": 0.25,
    "context": "calibrated live observations in the same detected camera segment",
    "identity": "anonymous and unverified; no cross-cut or appearance-only links",
    "output_scope": "Only eligible observed frame ranges; gaps stay unknown",
}


def _iou(left, right):
    width = max(0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0, min(left[3], right[3]) - max(left[1], right[1]))
    area = width * height
    union = (left[2] - left[0]) * (left[3] - left[1])
    union += (right[2] - right[0]) * (right[3] - right[1]) - area
    return area / union if union > 0 else 0


# A separate, weaker inference than the overlap links above: when the track of
# one player breaks, the players at that court end are counted and the only one
# unaccounted for is taken to be the same person. No appearance is compared.
CONTINUITY_RECIPE = {
    "method": "missing player at a court end v1",
    "maximum_gap_s": 2.0,
    "maximum_move": 0.35,
    "minimum_track_frames": 5,
    "players_per_end": {"singles": 1, "doubles": 2},
    "court_end": "far when most co-present players stand lower in the image",
    "scope": "one calibrated camera view; never across a cut",
    "ambiguous": "two tracks ending before two begin are reported, not joined",
}


def _join_breaks(video, actors):
    """Join an actor that ends to the one that replaces it at the same court end.

    actors: dicts with actor_id, camera, frames (set), feet {frame: (x, y)} and
    below (shares of co-present players standing lower in the image). A join
    needs exactly one recently ended candidate while every other player
    expected at that end is still being tracked.
    """
    per_end = CONTINUITY_RECIPE["players_per_end"].get(video.get("mode"))
    rate = video.get("fps")
    if per_end is None or not rate:
        return None
    reach = CONTINUITY_RECIPE["maximum_gap_s"] * float(rate)
    least = CONTINUITY_RECIPE["minimum_track_frames"]
    for actor in actors:
        actor["first"], actor["last"] = min(actor["frames"]), max(actor["frames"])
        actor["court_end"] = (
            None
            if not actor["below"]
            else "far"
            if median(actor["below"]) > 0.5
            else "near"
        )
    joins, ambiguous, successor = [], [], {}
    views = defaultdict(list)
    for actor in actors:
        if actor["court_end"]:
            views[actor["camera"], actor["court_end"]].append(actor)
    for (_, court_end), group in sorted(views.items()):
        group.sort(key=lambda a: (a["first"], a["actor_id"]))
        for born in group:
            if len(born["frames"]) < least:
                continue
            ended = [
                a
                for a in group
                if a["last"] < born["first"]
                and born["first"] - a["last"] <= reach
                and len(a["frames"]) >= least
                and a["actor_id"] not in successor
            ]
            if not ended:
                continue
            others = sum(
                a is not born
                and a["first"] < born["first"] <= a["last"]
                and len(a["frames"]) >= least
                for a in group
            )
            record = {
                "to": born["actor_id"],
                "court_end": court_end,
                "frame": born["first"],
            }
            if len(ended) != 1 or others != per_end - 1:
                ambiguous.append(
                    record
                    | {
                        "candidates": [a["actor_id"] for a in ended],
                        "other_players_tracked": others,
                    }
                )
                continue
            before = ended[0]["feet"][ended[0]["last"]]
            after = born["feet"][born["first"]]
            move = math.hypot(
                (after[0] - before[0]) / video["width"],
                (after[1] - before[1]) / video["height"],
            )
            if move > CONTINUITY_RECIPE["maximum_move"]:
                ambiguous.append(
                    record | {"candidates": [ended[0]["actor_id"]], "move": move}
                )
                continue
            successor[ended[0]["actor_id"]] = born["actor_id"]
            joins.append(
                record
                | {
                    "from": ended[0]["actor_id"],
                    "gap_frames": born["first"] - ended[0]["last"] - 1,
                    "move": move,
                }
            )
    head = {}
    for actor in sorted(actors, key=lambda a: (a["first"], a["actor_id"])):
        origin = actor["actor_id"]
        head.setdefault(origin, origin)
        if origin in successor:
            head[successor[origin]] = head[origin]
    order, players = [], {}
    for actor in sorted(actors, key=lambda a: (a["first"], a["actor_id"])):
        first = head[actor["actor_id"]]
        if first not in order:
            order.append(first)
        players[actor["actor_id"]] = {
            "continuity_id": first,
            "continuity_label": f"Player track {order.index(first) + 1}",
            "court_end": actor["court_end"],
        }
    return {
        "recipe": CONTINUITY_RECIPE,
        "joins": joins,
        "ambiguous": ambiguous,
        "player_track_count": len(order),
        "players": players,
    }


def _node(key):
    return {"run_id": key[0], "track_id": key[1]}


def link_player_runs(video, runs, progress=None):
    """Consume ordered (run ID, raw run) pairs, retaining only overlapping rows.

    Each run must retain stride-one source PTS and global camera segment starts.
    A link needs mutual unique geometry over time, not just one close position.
    Co-present tracks cannot merge, including through transitive links.
    """
    nodes, edges, conflicts = {}, {}, set()
    active, source_runs, seen_runs = [], [], set()
    previous_start = -1
    for identifier, run in runs:
        if not isinstance(identifier, str) or not identifier or identifier in seen_runs:
            raise ValueError("Actor linking needs unique registered player run IDs")
        seen_runs.add(identifier)
        first, last = run.get("start_frame"), run.get("end_frame")
        if (
            run.get("stage") != "players"
            or run.get("video_id") != video["id"]
            or run.get("video_sha256") != video["sha256"]
            or run.get("stride", 1) != 1
            or type(first) is not int
            or type(last) is not int
            or not 0 <= first < last <= video["frame_count"]
            or first < previous_start
            or run.get("requires_tracking_rerun")
            or len(run.get("frames", [])) != last - first
        ):
            raise ValueError(
                "Actor linking requires ordered, current same-source player runs"
            )
        previous_start = first
        source_runs.append(
            {"run_id": identifier, "start_frame": first, "end_frame": last}
        )
        rows = {}
        previous_time = -1
        for index, row in enumerate(run["frames"], first):
            time_s = row.get("time_s")
            if (
                type(row.get("frame")) is not int
                or row["frame"] != index
                or type(time_s) not in (int, float)
                or not math.isfinite(time_s)
                or not 0 <= time_s < video["duration_s"]
                or time_s <= previous_time
            ):
                raise ValueError(
                    "Actor linking needs complete finite source-frame timestamps"
                )
            previous_time = time_s
            camera = row.get("camera_segment_start_frame")
            people = []
            if (
                row.get("calibration_valid") is True
                and row.get("scene", "live") == "live"
            ):
                if type(camera) is not int or not 0 <= camera <= index:
                    raise ValueError(
                        "Actor linking needs actual global camera segment context"
                    )
                frame_tracks = set()
                for person in row["players"]:
                    track = person.get("track_id")
                    if track is None:
                        continue
                    if type(track) is not int or track < 0 or track in frame_tracks:
                        raise ValueError(
                            "Tracker IDs must be unique nonnegative integers per frame"
                        )
                    frame_tracks.add(track)
                    box, confidence = person.get("box"), person.get("confidence")
                    if (
                        not isinstance(box, list | tuple)
                        or len(box) != 4
                        or any(
                            type(v) not in (int, float) or not math.isfinite(v)
                            for v in box
                        )
                        or not 0 <= box[0] < box[2] <= video["width"]
                        or not 0 <= box[1] < box[3] <= video["height"]
                        or type(confidence) not in (int, float)
                        or not math.isfinite(confidence)
                        or not RECIPE["minimum_detection_confidence"] <= confidence <= 1
                    ):
                        continue
                    key = (identifier, track)
                    if key in nodes and nodes[key]["camera"] != camera:
                        raise ValueError(
                            "A tracker ID crosses camera segments; rerun player tracking"
                        )
                    node = nodes.setdefault(
                        key,
                        {"camera": camera, "frames": set(), "feet": {}, "below": []},
                    )
                    node["frames"].add(index)
                    node["feet"][index] = ((box[0] + box[2]) / 2, box[3])
                    people.append((key, box))
                for key, box in people:
                    if len(people) > 1:
                        nodes[key]["below"].append(
                            sum(other[3] > box[3] for _, other in people)
                            / (len(people) - 1)
                        )
                conflicts.update(
                    frozenset((a[0], b[0]))
                    for a, b in itertools.combinations(people, 2)
                )
            rows[index] = (time_s, camera, people)
        active = [prior for prior in active if prior["end"] > first]
        for prior in active:
            for frame in range(first, min(last, prior["end"])):
                current, other = rows[frame], prior["rows"][frame]
                if abs(current[0] - other[0]) > 0.00002 or current[1] != other[1]:
                    raise ValueError(
                        "Overlapping player runs disagree on source PTS or camera context"
                    )
                left, right = other[2], current[2]
                if not left or not right:
                    continue
                matrix = [[_iou(a[1], b[1]) for b in right] for a in left]
                for i, (a, _) in enumerate(left):
                    j = max(range(len(right)), key=lambda j: matrix[i][j])
                    score = matrix[i][j]
                    if score < RECIPE["minimum_iou"]:
                        continue
                    row_alt = max(
                        (s for k, s in enumerate(matrix[i]) if k != j), default=0
                    )
                    col_alt = max(
                        (matrix[k][j] for k in range(len(left)) if k != i), default=0
                    )
                    if (
                        score - max(row_alt, col_alt)
                        < RECIPE["minimum_alternative_margin"]
                    ):
                        continue
                    b = right[j][0]
                    key = (a, b)
                    edge = edges.setdefault(key, {"frames": [], "times": [], "iou": []})
                    edge["frames"].append(frame)
                    edge["times"].append(current[0])
                    edge["iou"].append(score)
        active.append({"end": last, "rows": rows})
        if progress:
            progress(0)

    if not source_runs:
        raise ValueError("Actor linking needs at least one player run")
    strong, neighbors = [], defaultdict(set)
    for (left, right), edge in edges.items():
        common = len(nodes[left]["frames"] & nodes[right]["frames"])
        fraction = len(edge["frames"]) / common
        if (
            len(edge["frames"]) < RECIPE["minimum_support_frames"]
            or edge["times"][-1] - edge["times"][0] + 1e-9
            < RECIPE["minimum_support_span_s"]
            or fraction < RECIPE["minimum_agreement_fraction"]
        ):
            continue
        strong.append((left, right, edge, fraction))
        neighbors[left].add(right)
        neighbors[right].add(left)
    ambiguous = {
        key
        for key, partners in neighbors.items()
        if any(
            frozenset(pair) in conflicts for pair in itertools.combinations(partners, 2)
        )
    }
    parent = {key: key for key in nodes}
    members = {key: {key} for key in nodes}

    def root(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    accepted, rejected = [], []
    for left, right, edge, fraction in sorted(
        strong, key=lambda item: (-len(item[2]["frames"]), item[0], item[1])
    ):
        a, b = root(left), root(right)
        if left in ambiguous or right in ambiguous:
            reason = "conflicting_overlap_partners"
        elif any(
            frozenset((x, y)) in conflicts
            for x in members[a]
            for y in members[b]
            if x != y
        ):
            reason = "would_merge_copresent_tracks"
        else:
            reason = None
        if reason:
            rejected.append(
                {"left": _node(left), "right": _node(right), "reason": reason}
            )
            continue
        if a != b:
            a, b = sorted((a, b))
            parent[b] = a
            members[a].update(members.pop(b))
        accepted.append(
            {
                "left": _node(left),
                "right": _node(right),
                "support_frames": edge["frames"],
                "median_iou": median(edge["iou"]),
                "agreement_fraction": fraction,
                "camera_segment_start_frame": nodes[left]["camera"],
            }
        )
        if progress:
            progress(0)

    groups = sorted(
        members.values(),
        key=lambda group: (min(min(nodes[k]["frames"]) for k in group), min(group)),
    )
    actors, tracks, observed_actors = [], [], []
    for number, group in enumerate(groups, 1):
        camera = nodes[min(group)]["camera"]
        if len({nodes[k]["camera"] for k in group}) != 1:
            raise ValueError("An actor hypothesis cannot cross a camera cut")
        anchor = min(group, key=lambda key: (min(nodes[key]["frames"]), key))
        identity = hashlib.sha256(
            f"{video['sha256']}:{camera}:{anchor[0]}:{anchor[1]}".encode()
        ).hexdigest()[:20]
        linked = len({key[0] for key in group}) > 1
        observed_actors.append(
            {
                "actor_id": identity,
                "camera": camera,
                "frames": set().union(*(nodes[k]["frames"] for k in group)),
                "feet": {
                    f: v for k in sorted(group) for f, v in nodes[k]["feet"].items()
                },
                "below": [v for k in sorted(group) for v in nodes[k]["below"]],
            }
        )
        actors.append(
            {
                "actor_id": identity,
                "label": f"Actor {number}",
                "camera_segment_start_frame": camera,
                "member_count": len(group),
                "linked_across_windows": linked,
            }
        )
        for key in sorted(group):
            observed = nodes[key]["frames"]
            ranges = []
            for frame in sorted(observed):
                if ranges and ranges[-1][1] == frame:
                    ranges[-1][1] = frame + 1
                else:
                    ranges.append([frame, frame + 1])
            tracks.append(
                _node(key)
                | {
                    "actor_id": identity,
                    "label": f"Actor {number}",
                    "camera_segment_start_frame": camera,
                    "start_frame": min(observed),
                    "end_frame": max(observed) + 1,
                    "observation_ranges": ranges,
                    "eligible_observation_count": len(observed),
                    "linked_across_windows": linked,
                    "conflicting_overlap": key in ambiguous,
                }
            )
    continuity = _join_breaks(video, observed_actors)
    if continuity:
        players = continuity.pop("players")
        for item in actors + tracks:
            item.update(players[item["actor_id"]])
    if progress:
        progress(1)
    return {
        "schema_version": 1,
        "stage": "identities",
        "continuity": continuity,
        "method": METHOD,
        "recipe": RECIPE,
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "start_frame": 0,
        "end_frame": video["frame_count"],
        "source_runs": source_runs,
        "actors": actors,
        "tracks": tracks,
        "links": accepted,
        "rejected_links": rejected,
        "actor_count": len(actors),
        "linked_actor_count": sum(a["linked_across_windows"] for a in actors),
        "accepted_link_count": len(accepted),
        "ambiguous_track_count": len(ambiguous),
        "reviewed": False,
        "cross_camera_identity": False,
        "meaning": "Provisional anonymous track continuity in overlapping calibrated camera views; not verified player identity or a complete roster.",
    }
