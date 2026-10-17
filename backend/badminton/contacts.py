"""Review proposals from raw trajectories; never fill missing shuttle points.

Candidate start/end frames and times are inclusive possible-contact bounds. For
occlusions, ``frame``/``time_s`` identify a navigation frame, not a measured hit.
Scores rank heuristic evidence and are not calibrated probabilities.
"""

import bisect
import itertools
import math

import numpy as np

METHOD = "gap-aware motion and pose proposals v2"
MAX_FRAME_STEP_S = 0.1
MAX_GAP_S = 0.24


def _hitter_hint(point, players, diagonal):
    best = None
    for player in players:
        keypoints = player.get("keypoints", [])
        wrists = [
            keypoints[i]
            for i in (9, 10)
            if i < len(keypoints) and len(keypoints[i]) > 2 and keypoints[i][2] >= 0.3
        ]
        x1, y1, x2, y2 = player["box"]
        box_distance = math.hypot(
            max(x1 - point[0], 0, point[0] - x2), max(y1 - point[1], 0, point[1] - y2)
        )
        wrist_distance = min(
            (math.hypot(p[0] - point[0], p[1] - point[1]) for p in wrists),
            default=float("inf"),
        )
        distance = min(wrist_distance, box_distance + diagonal * 0.02)
        if best is None or distance < best[0]:
            best = (distance, player)
    if best is None or best[0] > diagonal * 0.075:
        return None
    return best


def _raw_visible(row):
    shuttle = row["shuttle"]
    return (
        shuttle["visible"]
        and not shuttle.get("repaired", False)
        and all(
            shuttle.get(axis) is not None and math.isfinite(shuttle[axis])
            for axis in ("x", "y")
        )
    )


def _valid_window(window, cuts, diagonal):
    """Reject discontinuous timestamps, explicit cuts and impossible jumps."""
    times = np.asarray([row["time_s"] for row in window])
    frames = np.asarray([row["frame"] for row in window])
    if (
        not np.isfinite(times).all()
        or np.any(np.diff(times) <= 0)
        or np.max(np.diff(times)) > MAX_FRAME_STEP_S + 1e-9
        or np.any(np.diff(frames) != 1)
        or any(window[0]["frame"] < cut <= window[-1]["frame"] for cut in cuts)
        or any(row.get("cut") or row.get("scene_cut") for row in window[1:])
        or any(row.get("scene", "live") != "live" for row in window)
    ):
        return False
    visible = [row for row in window if _raw_visible(row)]
    for before, after in itertools.pairwise(visible):
        dt = after["time_s"] - before["time_s"]
        jump = math.hypot(
            after["shuttle"]["x"] - before["shuttle"]["x"],
            after["shuttle"]["y"] - before["shuttle"]["y"],
        )
        if jump / dt > diagonal * 6:
            return False
    return True


def _observations(rows, origin):
    times = np.asarray([row["time_s"] - origin for row in rows])
    points = np.asarray([[row["shuttle"]["x"], row["shuttle"]["y"]] for row in rows])
    return times, points


def _motion(before, after, diagonal):
    speed_before, speed_after = (
        float(np.linalg.norm(before)),
        float(np.linalg.norm(after)),
    )
    if (
        min(speed_before, speed_after) < diagonal * 0.025
        or max(speed_before, speed_after) > diagonal * 6
    ):
        return None
    cosine = float(np.clip(np.dot(before, after) / (speed_before * speed_after), -1, 1))
    angle = math.degrees(math.acos(cosine))
    ratio = max(speed_before, speed_after) / min(speed_before, speed_after)
    return (angle, ratio) if angle >= 35 or ratio >= 2.5 else None


def _contact_fit(times, points, knot, diagonal):
    """Compare equally complex abrupt and smooth models, not angle alone.

    Both fits have three coefficients per coordinate. A smooth flight apex fits
    a quadratic well; an abrupt change should fit a continuous broken line
    substantially better. A source-pixel floor limits quantization-only claims.
    """
    centered = times - knot
    broken = np.column_stack([np.ones(len(times)), centered, np.maximum(centered, 0)])
    smooth = np.column_stack([np.ones(len(times)), centered, centered**2])

    def residual(design):
        fitted = design @ np.linalg.lstsq(design, points, rcond=None)[0]
        return float(np.sqrt(np.mean(np.sum((points - fitted) ** 2, axis=1))))

    abrupt_error, smooth_error = residual(broken), residual(smooth)
    if abrupt_error > smooth_error * 0.65 or smooth_error - abrupt_error < max(
        0.75, diagonal * 0.0005
    ):
        return None
    return {
        "piecewise_rmse_px": round(abrupt_error, 3),
        "quadratic_rmse_px": round(smooth_error, 3),
    }


def _nearest_players(players, player_times, time_s):
    if not players:
        return []
    position = bisect.bisect_left(player_times, time_s)
    index = min(
        (index for index in (position - 1, position) if 0 <= index < len(players)),
        key=lambda index: abs(player_times[index] - time_s),
    )
    return (
        players[index]["players"] if abs(player_times[index] - time_s) <= 0.08 else []
    )


def _gap_pose(point, player_rows, left, right, diagonal):
    """Require a nearby confident wrist and measurable wrist movement.

    Box-only proximity is insufficient evidence for an unobserved contact. The
    wrist may be up to racket reach from the modeled trajectory junction.
    """
    samples = {}
    for row in player_rows:
        if not left <= row["time_s"] <= right:
            continue
        for player in row["players"]:
            if player.get("track_id") is None:
                continue
            for wrist in (9, 10):
                keypoints = player.get("keypoints", [])
                if wrist >= len(keypoints) or len(keypoints[wrist]) < 3:
                    continue
                x, y, confidence = keypoints[wrist][:3]
                if confidence < 0.5 or not all(
                    math.isfinite(v) for v in (x, y, confidence)
                ):
                    continue
                samples.setdefault((player["track_id"], wrist), []).append(
                    (row["time_s"], np.asarray([x, y]), confidence)
                )
    evidence = []
    for (track_id, wrist), observations in samples.items():
        observations.sort(key=lambda observation: observation[0])
        near = min(
            observations, key=lambda observation: np.linalg.norm(observation[1] - point)
        )
        distance = float(np.linalg.norm(near[1] - point))
        speeds = [
            float(np.linalg.norm(b[1] - a[1]) / (b[0] - a[0]))
            for a, b in itertools.pairwise(observations)
            if 0 < b[0] - a[0] <= MAX_FRAME_STEP_S + 1e-9
        ]
        speed = float(np.median(speeds)) if speeds else 0
        if distance <= diagonal * 0.075 and diagonal * 0.025 <= speed <= diagonal * 4:
            evidence.append(
                {
                    "track_id": track_id,
                    "wrist_index": wrist,
                    "wrist_distance_px": round(distance, 2),
                    "wrist_confidence": round(float(near[2]), 3),
                    "median_wrist_speed_px_s": round(speed, 2),
                    "pose_samples": len(observations),
                }
            )
    return (
        min(evidence, key=lambda item: item["wrist_distance_px"]) if evidence else None
    )


def _candidate(row, left, right, motion, fit, hint, diagonal, evidence_source, segment):
    angle, ratio = motion
    distance = hint["distance_px"] if hint else diagonal * 0.075
    proximity = 1 - min(1, distance / (diagonal * 0.075))
    score = min(
        1, 0.55 * min(1, angle / 120) + 0.2 * min(1, (ratio - 1) / 2) + 0.25 * proximity
    )
    gap = evidence_source == "short_gap_trajectory_and_pose"
    return {
        "id": f"contact-gap-{left['frame']}-{right['frame']}"
        if gap
        else f"contact-{row['frame']}",
        "frame": row["frame"],
        "time_s": row["time_s"],
        "start_frame": left["frame"],
        "end_frame": right["frame"],
        "start_time_s": left["time_s"],
        "end_time_s": right["time_s"],
        "interval_bounds": "inclusive",
        "timing": "uncertain_interval" if gap else "observed_motion_change",
        "score": round(score, 3),
        "angle_deg": round(angle, 1),
        "speed_ratio": round(ratio, 2),
        "track_id": hint["track_id"] if hint else None,
        "player_id": None,
        "evidence_source": evidence_source,
        "evidence": fit | ({"pose": hint["pose"]} if hint and "pose" in hint else {}),
        "reason": "possible contact during shuttle occlusion; review entire interval"
        if gap
        else "abrupt motion change near player"
        if hint
        else "abrupt motion change; hitter unconfirmed",
        "reviewed": False,
        "_segment": segment,
    }


def propose_contacts(shuttle_run, player_run, video):
    rows = shuttle_run["frames"]
    players = (
        sorted(player_run["frames"], key=lambda row: row["time_s"])
        if player_run
        else []
    )
    player_times = [row["time_s"] for row in players]
    cuts = set(shuttle_run.get("cut_frames", [])) | set(
        player_run.get("cut_frames", []) if player_run else []
    )
    diagonal = math.hypot(video["width"], video["height"])
    candidates = []
    segment_ids = []
    segment = 0
    for index, row in enumerate(rows):
        if index and (
            not _raw_visible(row)
            or not _raw_visible(rows[index - 1])
            or row["frame"] in cuts
            or row.get("cut")
            or row.get("scene_cut")
            or row["time_s"] - rows[index - 1]["time_s"] > MAX_FRAME_STEP_S
        ):
            segment += 1
        segment_ids.append(segment)
    for index in range(3, len(rows) - 3):
        window = rows[index - 3 : index + 4]
        if not all(_raw_visible(row) for row in window) or not _valid_window(
            window, cuts, diagonal
        ):
            continue
        row = rows[index]
        times, points = _observations(window, row["time_s"])
        before = np.polyfit(times[:4], points[:4], 1)[0]
        after = np.polyfit(times[3:], points[3:], 1)[0]
        motion = _motion(before, after, diagonal)
        fit = _contact_fit(times, points, 0, diagonal) if motion else None
        if fit is None:
            continue
        hint = None
        if players:
            nearby = _hitter_hint(
                points[3],
                _nearest_players(players, player_times, row["time_s"]),
                diagonal,
            )
            if nearby is None:
                continue
            hint = {"track_id": nearby[1]["track_id"], "distance_px": nearby[0]}
        candidates.append(
            _candidate(
                row,
                row,
                row,
                motion,
                fit,
                hint,
                diagonal,
                "observed_trajectory",
                segment_ids[index],
            )
        )

    # A gap creates an interval, never a synthetic shuttle point or an exact hit.
    index = 0
    while index < len(rows):
        if _raw_visible(rows[index]):
            index += 1
            continue
        missing_start = index
        while index < len(rows) and not _raw_visible(rows[index]):
            index += 1
        left_index, right_index = missing_start - 1, index
        if left_index < 2 or right_index + 2 >= len(rows) or not players:
            continue
        left, right = rows[left_index], rows[right_index]
        if right["time_s"] - left["time_s"] > MAX_GAP_S + 1e-9:
            continue
        window = rows[left_index - 2 : right_index + 3]
        before_rows, after_rows = (
            rows[left_index - 2 : left_index + 1],
            rows[right_index : right_index + 3],
        )
        if not all(
            _raw_visible(row) for row in before_rows + after_rows
        ) or not _valid_window(window, cuts, diagonal):
            continue
        origin = left["time_s"]
        before_times, before_points = _observations(before_rows, origin)
        after_times, after_points = _observations(after_rows, origin)
        before_fit = np.polyfit(before_times, before_points, 1)
        after_fit = np.polyfit(after_times, after_points, 1)
        motion = _motion(before_fit[0], after_fit[0], diagonal)
        if motion is None:
            continue
        delta_velocity = before_fit[0] - after_fit[0]
        delta_position = before_fit[1] - after_fit[1]
        norm = float(np.dot(delta_velocity, delta_velocity))
        if norm <= 1e-9:
            continue
        knot = -float(np.dot(delta_position, delta_velocity)) / norm
        duration = right["time_s"] - origin
        # Fits to sampled trajectories cannot resolve a subframe junction. Allow
        # half one observed source-frame interval at either boundary; widen the
        # review interval if the modeled junction lies just outside the gap.
        quantization = (
            max(np.max(np.diff(before_times)), np.max(np.diff(after_times))) / 2
        )
        if not -quantization - 1e-9 <= knot <= duration + quantization + 1e-9:
            continue
        before_junction = before_fit[0] * knot + before_fit[1]
        after_junction = after_fit[0] * knot + after_fit[1]
        separation = float(np.linalg.norm(before_junction - after_junction))
        if separation > diagonal * 0.015:
            continue
        times = np.concatenate([before_times, after_times])
        points = np.concatenate([before_points, after_points])
        fit = _contact_fit(times, points, knot, diagonal)
        if fit is None:
            continue
        pose = _gap_pose(
            (before_junction + after_junction) / 2,
            players,
            left["time_s"],
            right["time_s"],
            diagonal,
        )
        if pose is None:
            continue
        fit["trajectory_junction_separation_px"] = round(separation, 3)
        fit["missing_frames"] = [
            row["frame"] for row in rows[missing_start:right_index]
        ]
        hint = {
            "track_id": pose["track_id"],
            "distance_px": pose["wrist_distance_px"],
            "pose": pose,
        }
        interval_left = before_rows[-2] if knot < 0 else left
        interval_right = after_rows[1] if knot > duration else right
        # Midpoint is only a reproducible review navigation location.
        middle = min(
            window,
            key=lambda row: abs(
                row["time_s"] - (interval_left["time_s"] + interval_right["time_s"]) / 2
            ),
        )
        candidates.append(
            _candidate(
                middle,
                interval_left,
                interval_right,
                motion,
                fit,
                hint,
                diagonal,
                "short_gap_trajectory_and_pose",
                ("gap", missing_start),
            )
        )

    # Suppress neighbors only within one uninterrupted observed segment. A gap
    # interval cannot suppress a hit on the other side of missing observations.
    selected = []
    for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True):
        if all(
            candidate["_segment"] != other["_segment"]
            or abs(candidate["time_s"] - other["time_s"]) >= 0.16
            for other in selected
        ):
            selected.append(candidate)
    for candidate in selected:
        candidate.pop("_segment")
    return sorted(selected, key=lambda item: item["frame"])
