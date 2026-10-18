"""Review proposals from raw trajectories; never fill missing shuttle points.

Candidate start/end frames and times are inclusive possible-contact bounds. For
occlusions, ``frame``/``time_s`` identify a navigation frame, not a measured hit.
Scores rank heuristic evidence and are not calibrated probabilities.
"""

import bisect
import itertools
import math

import numpy as np

METHOD = "subframe and short-gap motion/pose proposals v4"
MAX_FRAME_STEP_S = 0.1
MAX_GAP_S = 0.24
PROFILE_STEPS = 25
MIN_PROFILE_GAIN = 6
MAX_PROFILE_ERROR_DIAGONALS = 0.005
MAX_FLANK_S = 0.20
MIN_WRIST_SAMPLES = 3
WRIST_REACH_DIAGONALS = 0.10
WRIST_REACH_BODY_DIAGONALS = 0.6


def proposal_recipe():
    return {
        "observed_window_frames": 7,
        "maximum_source_step_s": MAX_FRAME_STEP_S,
        "maximum_gap_s": MAX_GAP_S,
        "profile_grid_steps": PROFILE_STEPS,
        "minimum_penalized_fit_gain": MIN_PROFILE_GAIN,
        "maximum_profile_rmse_diagonals": MAX_PROFILE_ERROR_DIAGONALS,
        "maximum_rmse_ratio_to_quadratic": 0.65,
        "minimum_rmse_gain_px": 0.75,
        "minimum_rmse_gain_diagonals": 0.0005,
        "maximum_flank_context_s": MAX_FLANK_S,
        "minimum_moving_wrist_samples": MIN_WRIST_SAMPLES,
        "observed_contact_wrist_guard": {
            "minimum_samples_per_wrist": MIN_WRIST_SAMPLES,
            "minimum_confidence": 0.3,
            "reach_image_diagonals": WRIST_REACH_DIAGONALS,
            "reach_body_diagonals": WRIST_REACH_BODY_DIAGONALS,
            "missing_or_ambiguous_pose": "retain proximity fallback",
        },
        "uncertainty": "Profile support plus source-frame quantization; not a calibrated confidence interval",
    }


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


def _wrist_reach_contradicted(point, player, rows, origin, source_step, diagonal):
    """Reject box-only proximity contradicted by repeated observations of both arms.

    This conservative image-space heuristic is not a measured racket reach.
    Missing, ambiguous or one-sided pose evidence leaves the fallback available.
    All observations must belong to the already validated trajectory window.
    """
    track_id = player.get("track_id")
    if track_id is None:
        return False
    x1, y1, x2, y2 = player["box"]
    reach = max(
        diagonal * WRIST_REACH_DIAGONALS,
        math.hypot(x2 - x1, y2 - y1) * WRIST_REACH_BODY_DIAGONALS,
    )
    wrists = {9: [], 10: []}
    for row in rows:
        matches = [p for p in row["players"] if p.get("track_id") == track_id]
        if len(matches) != 1 or row.get("scene", "live") != "live":
            continue
        keypoints = matches[0].get("keypoints", [])
        for wrist, observations in wrists.items():
            if wrist >= len(keypoints) or len(keypoints[wrist]) < 3:
                continue
            x, y, confidence = keypoints[wrist][:3]
            if confidence < 0.3 or not all(
                math.isfinite(value) for value in (x, y, confidence)
            ):
                continue
            observations.append((row["time_s"], math.hypot(x - point[0], y - point[1])))
    for observations in wrists.values():
        if len(observations) < MIN_WRIST_SAMPLES:
            return False
        if not observations[0][0] < origin < observations[-1][0]:
            return False
        if min(abs(t - origin) for t, _ in observations) > source_step + 1e-9:
            return False
        if any(
            not 0 < after[0] - before[0] <= MAX_FRAME_STEP_S + 1e-9
            for before, after in itertools.pairwise(observations)
        ):
            return False
        if min(distance for _, distance in observations) <= reach:
            return False
    return True


def _raw_visible(row):
    shuttle = row["shuttle"]
    return (
        shuttle["visible"]
        and not shuttle.get("repaired", False)
        and not shuttle.get("selection_context_excluded", False)
        and all(
            shuttle.get(axis) is not None and math.isfinite(shuttle[axis])
            for axis in ("x", "y")
        )
    )


def _valid_window(window, cuts, diagonal, excluded_frames=()):
    """Reject discontinuous timestamps, explicit cuts and impossible jumps."""
    times = np.asarray([row["time_s"] for row in window])
    frames = np.asarray([row["frame"] for row in window])
    context_start = min(
        row["shuttle"].get("selection_context_start_frame", row["frame"])
        for row in window
    )
    if (
        not np.isfinite(times).all()
        or np.any(np.diff(times) <= 0)
        or np.max(np.diff(times)) > MAX_FRAME_STEP_S + 1e-9
        or np.any(np.diff(frames) != 1)
        or any(context_start < cut <= window[-1]["frame"] for cut in cuts)
        or any(row.get("cut") or row.get("scene_cut") for row in window[1:])
        or any(row.get("scene", "live") != "live" for row in window)
        or any(
            context_start <= frame <= window[-1]["frame"] for frame in excluded_frames
        )
        or any(
            row["shuttle"].get("selection_context_excluded", False) for row in window
        )
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
        players[index]["players"]
        if abs(player_times[index] - time_s) <= 0.08
        and players[index].get("scene", "live") == "live"
        else []
    )


def _pose_evidence(point, player_rows, left, right, diagonal):
    """Require a nearby confident wrist and measurable wrist movement.

    Box-only proximity is insufficient evidence for an unobserved contact. The
    wrist may be up to racket reach from the modeled trajectory junction.
    """
    samples = {}
    for row in player_rows:
        if not left <= row["time_s"] <= right or row.get("scene", "live") != "live":
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
    return sorted(evidence, key=lambda item: item["wrist_distance_px"])


def _gap_pose(point, player_rows, left, right, diagonal):
    evidence = _pose_evidence(point, player_rows, left, right, diagonal)
    return evidence[0] if evidence else None


def _subframe_fit(times, points, left, right, diagonal):
    """Profile a shared 2D knot, penalizing its extra fitted parameter.

    The small-sample residual criterion counts the common noise scale as well:
    eight parameters for the broken line, seven for the smooth quadratic.
    Its gain is heuristic evidence, not a probability or an accuracy estimate.
    """
    smooth = np.column_stack([np.ones(len(times)), times, times**2])
    residual = smooth @ np.linalg.lstsq(smooth, points, rcond=None)[0] - points
    smooth_sse = float(np.sum(residual**2))
    n = points.size

    def penalty(k):
        return 2 * k + 2 * k * (k + 1) / (n - k - 1)

    if n <= 9:
        return None
    accepted = []
    for knot in np.linspace(left, right, PROFILE_STEPS):
        centered = times - knot
        design = np.column_stack(
            [np.ones(len(times)), centered, np.maximum(centered, 0)]
        )
        weights = np.linalg.lstsq(design, points, rcond=None)[0]
        sse = float(np.sum((design @ weights - points) ** 2))
        error, smooth_error = (
            math.sqrt(sse / len(times)),
            math.sqrt(smooth_sse / len(times)),
        )
        gain = (
            n * math.log(max(smooth_sse, 1e-12) / max(sse, 1e-12))
            + penalty(7)
            - penalty(8)
        )
        motion = _motion(weights[1], weights[1] + weights[2], diagonal)
        if (
            motion is None
            or error > diagonal * MAX_PROFILE_ERROR_DIAGONALS
            or error > smooth_error * 0.65
            or smooth_error - error < max(0.75, diagonal * 0.0005)
            or gain < MIN_PROFILE_GAIN
        ):
            continue
        accepted.append((sse, float(knot), weights, motion, gain))
    if not accepted:
        return None
    _, knot, weights, motion, gain = min(accepted, key=lambda sample: sample[0])
    return {
        "knot": knot,
        "point": weights[0],
        "motion": motion,
        "knot_bounds": (min(a[1] for a in accepted), max(a[1] for a in accepted)),
        "evidence": {
            "piecewise_rmse_px": round(
                math.sqrt(min(a[0] for a in accepted) / len(times)), 3
            ),
            "quadratic_rmse_px": round(math.sqrt(smooth_sse / len(times)), 3),
            "penalized_fit_gain": round(gain, 3),
            "fit_parameter_counts_including_noise": {"broken_line": 8, "quadratic": 7},
            "timing_model": "profiled subframe junction; interval is not a confidence interval",
        },
    }


def _profile_candidate(
    window, observed, origin, left, right, players, diagonal, source, segment
):
    times, points = _observations(observed, origin)
    fitted = _subframe_fit(times, points, left - origin, right - origin, diagonal)
    if fitted is None:
        return None
    # Additional uncertain proposals need observed wrist motion, not box-only
    # proximity. Multiple credible tracks leave the hitter unconfirmed.
    poses = _pose_evidence(
        fitted["point"],
        players,
        max(window[0]["time_s"], left - 0.08),
        min(window[-1]["time_s"], right + 0.08),
        diagonal,
    )
    poses = [pose for pose in poses if pose["pose_samples"] >= MIN_WRIST_SAMPLES]
    if not poses:
        return None
    possible = sorted({pose["track_id"] for pose in poses})
    hint = {
        "track_id": possible[0] if len(possible) == 1 else None,
        "distance_px": poses[0]["wrist_distance_px"],
        "pose": poses[0],
    }
    ts = [r["time_s"] for r in window]
    quantization = max(b - a for a, b in itertools.pairwise(ts)) / 2
    lo, hi = (origin + t for t in fitted["knot_bounds"])
    first = window[max(0, bisect.bisect_right(ts, lo - quantization) - 1)]
    last = window[min(len(window) - 1, bisect.bisect_left(ts, hi + quantization))]
    navigation = min(window, key=lambda r: abs(r["time_s"] - origin - fitted["knot"]))
    evidence = fitted["evidence"] | {
        "possible_track_ids": possible,
        "hitter_hint_status": "ambiguous_proximity"
        if len(possible) > 1
        else "unconfirmed_track",
        "observed_context_frames": [r["frame"] for r in observed],
        "missing_frames": [r["frame"] for r in window if not _raw_visible(r)],
    }
    candidate = _candidate(
        navigation,
        first,
        last,
        fitted["motion"],
        evidence,
        hint,
        diagonal,
        source,
        segment,
        window,
    )
    candidate.update(
        id=f"contact-profile-{first['frame']}-{last['frame']}",
        timing="uncertain_interval",
        reason="possible contact between source observations; review timing and hitter",
    )
    return candidate


def _candidate(
    row, left, right, motion, fit, hint, diagonal, evidence_source, segment, context
):
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
        "context_start_frame": min(
            row["shuttle"].get("selection_context_start_frame", row["frame"])
            for row in context
        ),
        "context_end_frame": context[-1]["frame"] + 1,
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
    cuts.update(
        row["frame"] for row in players if row.get("cut") or row.get("scene_cut")
    )
    excluded_frames = {
        row["frame"] for row in players if row.get("scene", "live") != "live"
    }
    excluded_frames.update(
        row["frame"] for row in rows if row.get("scene", "live") != "live"
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
            window, cuts, diagonal, excluded_frames
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
            left = bisect.bisect_left(player_times, window[0]["time_s"])
            right = bisect.bisect_right(player_times, window[-1]["time_s"])
            pose_window = players[left:right]
            source_step = float(np.max(np.diff(times)))
            possible_hitters = [
                player
                for player in _nearest_players(players, player_times, row["time_s"])
                if not _wrist_reach_contradicted(
                    points[3], player, pose_window, row["time_s"], source_step, diagonal
                )
            ]
            nearby = _hitter_hint(
                points[3],
                possible_hitters,
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
                window,
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
        ) or not _valid_window(window, cuts, diagonal, excluded_frames):
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
                window,
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
    # Additional uncertain proposals keep the strong existing observations.
    # Profile within one source-frame interval; the extra knot parameter must
    # earn its fit gain and have observed moving-wrist support.
    extra = []
    if players:
        for index in range(3, len(rows) - 3):
            window = rows[index - 3 : index + 4]
            if not all(_raw_visible(r) for r in window) or not _valid_window(
                window, cuts, diagonal, excluded_frames
            ):
                continue
            candidate = _profile_candidate(
                window,
                window,
                rows[index]["time_s"],
                rows[index - 1]["time_s"],
                rows[index + 1]["time_s"],
                players,
                diagonal,
                "subframe_trajectory_and_pose",
                segment_ids[index],
            )
            if candidate:
                extra.append(candidate)

        # Nearby short gaps need not leave exactly three consecutive detections
        # immediately on each side. Gather bounded *observed* samples and keep
        # the entire original window for continuity/scene/cut checks.
        index = 0
        while index < len(rows):
            if _raw_visible(rows[index]):
                index += 1
                continue
            start = index
            while index < len(rows) and not _raw_visible(rows[index]):
                index += 1
            left, right = start - 1, index
            if (
                left < 0
                or right >= len(rows)
                or rows[right]["time_s"] - rows[left]["time_s"] > MAX_GAP_S + 1e-9
            ):
                continue
            before, after = [], []
            for j in range(left, -1, -1):
                if (
                    rows[left]["time_s"] - rows[j]["time_s"] > MAX_FLANK_S + 1e-9
                    or len(before) == 4
                ):
                    break
                if _raw_visible(rows[j]):
                    before.append(j)
            for j in range(right, len(rows)):
                if (
                    rows[j]["time_s"] - rows[right]["time_s"] > MAX_FLANK_S + 1e-9
                    or len(after) == 4
                ):
                    break
                if _raw_visible(rows[j]):
                    after.append(j)
            if min(len(before), len(after)) < 3:
                continue
            before.reverse()
            window = rows[before[0] : after[-1] + 1]
            if not _valid_window(window, cuts, diagonal, excluded_frames):
                continue
            candidate = _profile_candidate(
                window,
                [rows[j] for j in before + after],
                rows[left]["time_s"],
                rows[left]["time_s"],
                rows[right]["time_s"],
                players,
                diagonal,
                "bounded_gap_trajectory_and_pose",
                ("profile", left, right),
            )
            if candidate:
                extra.append(candidate)
    for candidate in sorted(extra, key=lambda c: c["score"], reverse=True):
        # Overlapping review intervals describe one unresolved transition, not
        # several events. This also avoids duplicating a strong v2 proposal.
        overlapping = [
            c
            for c in selected
            if candidate["start_frame"] <= c["end_frame"]
            and c["start_frame"] <= candidate["end_frame"]
        ]
        if (
            len(overlapping) == 1
            and overlapping[0]["evidence_source"] == "observed_trajectory"
        ):
            # Moving-wrist support and the penalized subframe fit justify an
            # uncertain interval rather than retaining a sampled exact point.
            selected.remove(overlapping[0])
        elif overlapping:
            continue
        candidate.pop("_segment")
        selected.append(candidate)
    return sorted(selected, key=lambda item: item["frame"])
