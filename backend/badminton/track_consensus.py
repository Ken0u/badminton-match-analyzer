"""Conservative continuity supported by two independent motion associations.

Keep baseline observations. A second tracker may corroborate short tracklet
joins, but cannot replace boxes, introduce observations or identify a person.
"""

import itertools
import math
from collections import defaultdict

from .actor_linking import _iou

RECIPE = {
    "method": "baseline-anchored motion corroboration v1",
    "minimum_iou": 0.7,
    "minimum_alternative_margin": 0.15,
    "minimum_support_frames": 5,
    "minimum_support_span_s": 0.16,
    "minimum_full_baseline_coverage": 0.85,
    "maximum_gap_s": 0.4,
    "minimum_confidence": 0.25,
    "scope": "same calibrated live camera; no appearance-only or cross-cut links",
    "conflicts": "all observations and correspondence branches, not just strong links",
    "output": "baseline boxes and poses retained; no interpolated observations",
}


def corroborate_tracks(video, rows, stride=1, progress=None):
    """Return a provisional canonical map and its evidence, without input edits.

    Rows retain both `players` and `motion_players`, including raw tracker IDs.
    IDs must be disjoint across camera cuts. A branch to a co-present counterpart
    quarantines every proposed link of that node, however brief the branch.
    """
    if stride != 1:
        return {}, {"recipe": RECIPE, "status": "requires_stride_one", "links": []}
    bnodes, anodes, edges = {}, {}, defaultdict(list)
    bconf, aconf, eligible = set(), set(), set()
    by_frame, previous_frame, previous_time = {}, None, -1
    for row in rows:
        frame, time_s = row.get("frame"), row.get("time_s")
        camera = row.get("camera_segment_start_frame")
        if (
            type(frame) is not int
            or not 0 <= frame < video["frame_count"]
            or (previous_frame is not None and frame != previous_frame + 1)
            or type(time_s) not in (int, float)
            or not math.isfinite(time_s)
            or not previous_time < time_s < video["duration_s"]
            or type(camera) is not int
            or not 0 <= camera <= frame
        ):
            raise ValueError(
                "Track consensus needs consecutive finite source PTS and camera context"
            )
        previous_frame, previous_time = frame, time_s
        by_frame[frame] = row
        valid = (
            row.get("calibration_valid") is True and row.get("scene", "live") == "live"
        )
        if valid:
            eligible.add(frame)
        people = []
        for name, nodes, conflicts in (
            ("players", bnodes, bconf),
            ("motion_players", anodes, aconf),
        ):
            current, seen = [], set()
            for person in row[name]:
                identity = person.get("track_id")
                if identity is None:
                    continue
                if type(identity) is not int or identity < 0 or identity in seen:
                    raise ValueError(
                        "Track consensus needs unique nonnegative tracker IDs"
                    )
                seen.add(identity)
                box, confidence = person.get("box"), person.get("confidence")
                if (
                    not isinstance(box, list | tuple)
                    or len(box) != 4
                    or any(
                        type(v) not in (int, float) or not math.isfinite(v) for v in box
                    )
                    or not 0 <= box[0] < box[2] <= video["width"]
                    or not 0 <= box[1] < box[3] <= video["height"]
                    or type(confidence) not in (int, float)
                    or not math.isfinite(confidence)
                    or not RECIPE["minimum_confidence"] <= confidence <= 1
                ):
                    continue
                node = nodes.setdefault(identity, {"camera": camera, "frames": set()})
                if node["camera"] != camera:
                    raise ValueError("Tracker ID reused across camera segments")
                if valid:
                    node["frames"].add(frame)
                    current.append(person)
            # Even excluded/uncalibrated co-presence forbids merging. Do not
            # erase that negative evidence by selecting only calibrated rows.
            conflicts.update(
                frozenset(pair) for pair in itertools.combinations(seen, 2)
            )
            people.append(current)
        baseline, motion = people
        if baseline and motion:
            matrix = [[_iou(a["box"], b["box"]) for b in motion] for a in baseline]
            for i, person in enumerate(baseline):
                j = max(range(len(motion)), key=lambda j: matrix[i][j])
                score = matrix[i][j]
                alternate = max(
                    [s for k, s in enumerate(matrix[i]) if k != j]
                    + [matrix[k][j] for k in range(len(baseline)) if k != i]
                    + [0]
                )
                if (
                    score >= RECIPE["minimum_iou"]
                    and score - alternate >= RECIPE["minimum_alternative_margin"]
                ):
                    edges[person["track_id"], motion[j]["track_id"]].append(
                        (frame, time_s, score)
                    )
        if progress:
            progress(0)
    bn, an = defaultdict(set), defaultdict(set)
    for b, a in edges:
        bn[b].add(a)
        an[a].add(b)
    badb = {
        b
        for b, partners in bn.items()
        if any(frozenset(p) in aconf for p in itertools.combinations(partners, 2))
    }
    bada = {
        a
        for a, partners in an.items()
        if any(frozenset(p) in bconf for p in itertools.combinations(partners, 2))
    }
    supported = defaultdict(list)
    for (b, a), samples in edges.items():
        if b in badb or a in bada:
            continue
        coverage = len(samples) / len(bnodes[b]["frames"])
        if (
            len(samples) >= RECIPE["minimum_support_frames"]
            and samples[-1][1] - samples[0][1] + 1e-9
            >= RECIPE["minimum_support_span_s"]
            and coverage >= RECIPE["minimum_full_baseline_coverage"]
        ):
            supported[a].append((b, coverage, samples))
    parent = {b: b for b in bnodes}
    members = {b: {b} for b in bnodes}

    def root(b):
        while parent[b] != b:
            parent[b] = parent[parent[b]]
            b = parent[b]
        return b

    accepted = []
    for a, tracks in sorted(supported.items()):
        tracks.sort(key=lambda item: min(bnodes[item[0]]["frames"]))
        for first, last in itertools.pairwise(tracks):
            left, right = first[0], last[0]
            end, start = max(bnodes[left]["frames"]), min(bnodes[right]["frames"])
            camera = bnodes[left]["camera"]
            if start <= end or camera != bnodes[right]["camera"]:
                continue
            gap = by_frame[start]["time_s"] - by_frame[end]["time_s"]
            if gap > RECIPE["maximum_gap_s"] + 1e-9 or not all(
                f in eligible and by_frame[f]["camera_segment_start_frame"] == camera
                for f in range(end, start + 1)
            ):
                continue
            x, y = root(left), root(right)
            if x == y or any(
                frozenset((u, v)) in bconf for u in members[x] for v in members[y]
            ):
                continue
            anchor = min((x, y), key=lambda b: (min(bnodes[b]["frames"]), b))
            other = y if anchor == x else x
            parent[other] = anchor
            members[anchor].update(members.pop(other))
            accepted.append(
                {
                    "left": left,
                    "right": right,
                    "motion_track": a,
                    "gap_s": gap,
                    "camera_segment_start_frame": camera,
                    "left_coverage": first[1],
                    "right_coverage": last[1],
                    "left_support_frames": [s[0] for s in first[2]],
                    "right_support_frames": [s[0] for s in last[2]],
                    "evidence_start_frame": first[2][0][0],
                    "evidence_end_frame": last[2][-1][0] + 1,
                }
            )
        if progress:
            progress(0)
    mapping = {b: root(b) for b in bnodes}
    if progress:
        progress(1)
    return mapping, {
        "recipe": RECIPE,
        "status": "completed",
        "links": accepted,
        "ambiguous_baseline_tracks": sorted(badb),
        "ambiguous_motion_tracks": sorted(bada),
        "baseline_track_count": len(mapping),
        "canonical_track_count": len(set(mapping.values())),
        "reviewed": False,
        "cross_camera_identity": False,
        "meaning": "Unverified track continuity; baseline errors can remain. Not roster identity.",
    }
