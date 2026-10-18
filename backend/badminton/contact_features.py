"""Observed temporal arm descriptors for experimental contact learning."""

import bisect
import math

import numpy as np

CONTEXT_GUARD_VERSION = 2
OFFSETS = (-0.20, -2 / 15, -1 / 15, 0.0, 1 / 15, 2 / 15, 0.20)
ARM_FEATURES = 18
MAX_ARMS = 12
RECIPE = {
    "name": "weak-contact-arm-windows-v2",
    "context_guard_version": CONTEXT_GUARD_VERSION,
    "offsets_s": OFFSETS,
    "maximum_sample_error_s": 0.025,
    "maximum_source_step_s": 0.1,
    "minimum_arm_samples": 3,
    "minimum_central_arm_samples": 1,
    "maximum_arms": MAX_ARMS,
    "arm_feature_count": ARM_FEATURES,
    "weak_shot_bounds_relative_to_start_minus_one": [-3, 3],
    "weak_serve_bounds_relative_to_start_minus_one": [-2, 12],
    "negative_exclusion_pad_frames": 7,
    "nms_s": 0.18,
    "training_match": 1,
    "validation_match": 2,
    "test_match": 3,
    "not_exact_truth": True,
}


def visible(row):
    s = row["shuttle"]
    return (
        s.get("visible", False)
        and not s.get("repaired", False)
        and not s.get("selection_context_excluded", False)
        and all(
            isinstance(s.get(k), (int, float)) and math.isfinite(s[k])
            for k in ("x", "y")
        )
    )


def _arm(player, side, row, speed, video):
    k = player.get("keypoints", [])
    if len(k) != 17:
        return None
    shoulder, elbow, wrist = (5, 7, 9) if side == 0 else (6, 8, 10)
    points = np.asarray([k[wrist], k[elbow], k[shoulder]], dtype=np.float64)
    box = np.asarray(player["box"], dtype=np.float64)
    if (
        points.shape != (3, 3)
        or not np.isfinite(points).all()
        or not np.isfinite(box).all()
    ):
        return None
    if np.any(points[:, 2] < 0.3) or box[3] <= box[1] or box[2] <= box[0]:
        return None
    h = max(16.0, box[3] - box[1])
    center = (box[:2] + box[2:]) / 2
    xy = (points[:, :2] - center) / h
    # Make anatomical left/right arm geometry comparable, not an assumption
    # about racket handedness. No source side/hitter label enters the descriptor.
    sign = -1 if side == 0 else 1
    xy[:, 0] *= sign
    a, b = points[0, :2] - points[1, :2], points[2, :2] - points[1, :2]
    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    cosine = float(np.dot(a, b) / denominator) if denominator > 1e-6 else 0.0
    s = row["shuttle"]
    seen = visible(row)
    rel = (np.array([s["x"], s["y"]]) - points[0, :2]) / h if seen else np.zeros(2)
    rel[0] *= sign
    values = [
        1.0,
        *points[:, 2],
        *xy.ravel(),
        cosine,
        float(seen),
        *np.clip(rel, -4, 4),
        h / video["height"],
        box[3] / video["height"],
        speed[0] * sign,
        speed[1],
    ]
    assert len(values) == ARM_FEATURES
    return np.clip(values, -4, 4).astype(np.float32)


def build_contact_features(video, players, shuttle):
    """Sample observed arm windows in source time, never across an edit/scene."""
    rows, prows = shuttle["frames"], players["frames"]
    if players.get("stage") != "players" or shuttle.get("stage") != "shuttle":
        raise ValueError("Expected player and shuttle runs")
    if any(
        r.get("video_sha256") != video["sha256"] or r.get("video_id") != video["id"]
        for r in (players, shuttle)
    ):
        raise ValueError("Feature sources must match video identity and hash")
    if players.get("stride", 1) != 1 or len(rows) != len(prows):
        raise ValueError("Full aligned player and shuttle observations are required")
    if any(
        a["frame"] != b["frame"] or abs(a["time_s"] - b["time_s"]) > 1e-7
        for a, b in zip(rows, prows)
    ):
        raise ValueError("Feature source frames/timestamps disagree")
    frames = np.asarray([r["frame"] for r in rows], dtype=np.int64)
    times = np.asarray([r["time_s"] for r in rows], dtype=np.float64)
    if (
        len(times) < 2
        or not np.isfinite(times).all()
        or np.any(np.diff(times) <= 0)
        or np.any(np.diff(frames) != 1)
    ):
        raise ValueError("Consecutive source frames and increasing timestamps required")
    diagonal = math.hypot(video["width"], video["height"])
    blocked = np.array(
        [
            a.get("scene", "live") != "live"
            or b.get("scene", "live") != "live"
            or not b.get("calibration_valid", False)
            or a["shuttle"].get("selection_context_excluded", False)
            for a, b in zip(rows, prows)
        ]
    )
    cuts = set(players.get("cut_frames", [])) | set(shuttle.get("cut_frames", []))
    cuts.update(r["frame"] for r in rows + prows if r.get("cut") or r.get("scene_cut"))
    observed, dependencies = [], []
    for i, (row, prow) in enumerate(zip(rows, prows)):
        speed = np.zeros(2)
        used = [i]
        if (
            i
            and 0 < times[i] - times[i - 1] <= 0.1
            and visible(row)
            and visible(rows[i - 1])
            and frames[i] not in cuts
        ):
            speed = np.array(
                [row["shuttle"][k] - rows[i - 1]["shuttle"][k] for k in ("x", "y")]
            ) / ((times[i] - times[i - 1]) * diagonal)
            speed = np.clip(speed, -6, 6)
            used.append(i - 1)
        # Velocity consumes an earlier observation. A selected component can
        # itself depend on earlier reachability observations. Include the full
        # transitive lineage before applying scene/camera exclusions.
        left, right = int(frames[min(used)]), int(row["frame"] + 1)
        for index in used:
            if not visible(rows[index]):
                continue
            point = rows[index]["shuttle"]
            a = point.get("selection_context_start_frame", rows[index]["frame"])
            b = point.get("selection_context_end_frame", rows[index]["frame"] + 1)
            if (
                type(a) is not int
                or type(b) is not int
                or not frames[0] <= a <= rows[index]["frame"] < b <= frames[-1] + 1
            ):
                raise ValueError(
                    "Shuttle selection lineage must lie inside the observed run"
                )
            left, right = min(left, a), max(right, b)
        dependencies.append((left, right))
        arms = {}
        for player in prow["players"]:
            track = player.get("track_id")
            if track is None:
                continue
            for side in (0, 1):
                feature = _arm(player, side, row, speed, video)
                if feature is not None:
                    key = (track, side)
                    if key in arms:
                        raise ValueError("Duplicate same-frame track/arm")
                    arms[key] = feature
        observed.append(arms)
    x = np.zeros((len(rows), MAX_ARMS, len(OFFSETS) * ARM_FEATURES), np.float32)
    mask = np.zeros((len(rows), MAX_ARMS), bool)
    arm_ids = np.full((len(rows), MAX_ARMS, 2), -1, np.int64)
    context = np.full((len(rows), 2), -1, np.int64)
    for i, timestamp in enumerate(times):
        indices = []
        for offset in OFFSETS:
            target = timestamp + offset
            pos = bisect.bisect_left(times, target)
            options = [p for p in (pos - 1, pos) if 0 <= p < len(times)]
            selected = min(options, key=lambda p: abs(times[p] - target))
            if abs(times[selected] - target) > 0.025 + 1e-9:
                break
            indices.append(selected)
        if len(indices) != len(OFFSETS):
            continue
        left = min(dependencies[p][0] for p in indices)
        right = max(dependencies[p][1] for p in indices)
        context_lo, context_hi = int(left - frames[0]), int(right - frames[0])
        if (
            blocked[context_lo:context_hi].any()
            or any(left < c < right for c in cuts)
            or np.max(np.diff(times[context_lo:context_hi])) > 0.1 + 1e-9
        ):
            continue
        candidates = set().union(*(observed[p] for p in indices))
        candidates = sorted(
            candidates, key=lambda key: (-sum(key in observed[p] for p in indices), key)
        )
        slot = 0
        for key in candidates:
            if sum(key in observed[p] for p in indices) < 3 or not any(
                key in observed[p] for p in indices[2:5]
            ):
                continue
            if slot == MAX_ARMS:
                break
            x[i, slot] = np.concatenate(
                [
                    observed[p].get(key, np.zeros(ARM_FEATURES, np.float32))
                    for p in indices
                ]
            )
            mask[i, slot] = True
            arm_ids[i, slot] = key
            slot += 1
        if slot:
            context[i] = [left, right]
    return {
        "x": x,
        "arm_mask": mask,
        "arm_ids": arm_ids,
        "frames": frames,
        "times": times,
        "context": context,
    }


def weak_targets(source_rows, parent_hints, *, excluded_frames=(), cut_frames=()):
    """An explicit hypothesis for research; does NOT change source contact truth."""
    hints = np.asarray(parent_hints)
    excluded_frames, cut_frames = set(excluded_frames), set(cut_frames)
    bags, negative = [], np.ones(len(hints), dtype=bool)
    for row in source_rows:
        center = row["source_start_frame"] - 1
        a, b = (-2, 12) if row["kind"] == "serve" else (-3, 3)
        local = np.flatnonzero((hints >= center + a) & (hints <= center + b))
        blocked = (
            any(int(local[0]) < c <= int(local[-1]) for c in cut_frames)
            if len(local)
            else False
        )
        blocked = blocked or any(i in excluded_frames for i in local)
        bags.append(
            {
                "id": row["id"],
                "indices": [] if blocked else local.tolist(),
                "source_possible_indices": local.tolist(),
                "source_context_blocked": blocked,
                "source_kind": row["kind"],
                "parent_bounds": [center + a, center + b],
            }
        )
        negative &= ~((hints >= center + a - 7) & (hints <= center + b + 7))
    return bags, negative


def peaks(scores, times, valid, threshold):
    """Deterministic source-time suppression, no peak on an invalid window."""
    candidates = np.flatnonzero(valid & np.isfinite(scores) & (scores >= threshold))
    selected = []
    for i in sorted(candidates, key=lambda i: (-scores[i], i)):
        if all(abs(times[i] - times[j]) >= RECIPE["nms_s"] for j in selected):
            selected.append(int(i))
    return sorted(selected)


def match_bags(predictions, bags):
    """Maximum one-to-one interval matching (avoids chronological greedy misses)."""
    assigned = {}

    def visit(pred, seen):
        for j, bag in enumerate(bags):
            if j in seen or pred not in bag["indices"]:
                continue
            seen.add(j)
            if j not in assigned or visit(assigned[j], seen):
                assigned[j] = pred
                return True
        return False

    return sum(visit(pred, set()) for pred in predictions)
