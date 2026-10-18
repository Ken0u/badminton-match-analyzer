"""Experimental rally-boundary review proposals from observed motion.

This module does not read event labels. Quiet poses plus a near-wrist shuttle
departure support a possible serve. A moving-to-stationary shuttle transition
and quiet poses support a possible ending, never a certified ground contact.
Missing detections, camera edits and clip edges alone cannot create boundaries.
All times are source PTS; proposed inclusive bounds are uncertain review ranges.
"""

import bisect
import itertools
import math
from copy import deepcopy

import cv2
import numpy as np

from .calibration_context import (
    court_run_context,
    court_signature,
    effective_annotations,
)
from .scene_review import camera_review_signature, reviewed_run
from .video import write_json

METHOD = "observed shuttle transition and bounded court surround v2"
POSE_LAG_S = 0.16
QUIET_S = 0.60
SETTLED_S = 0.48
MIN_CONTEXT_COVERAGE = 0.75
MOVING_DIAGONALS_PER_S = 0.08
STILL_RADIUS_DIAGONALS = 0.005
MAX_FRAME_STEP_S = 0.10
TERMINAL_COURT_MARGIN = 0.12


def context_signature(annotations, start, end):
    """Only inference context, never event labels or track/player assignments."""
    doc = (
        annotations.model_dump() if hasattr(annotations, "model_dump") else annotations
    )
    return {
        "camera": camera_review_signature(doc, start, end),
        "scenes": sorted(
            [r["start_frame"], r["end_frame"], r["scene"]]
            for r in doc.get("scene_ranges", [])
            if r["start_frame"] < end and start < r["end_frame"]
        ),
        "court": court_signature(doc, start, end),
    }


def reviewed_rallies(run, annotations):
    result = deepcopy(run)
    if "court_context" in run:
        annotations = effective_annotations(annotations, run["court_context"])
    result["requires_proposal_rerun"] = result.get(
        "context_signature"
    ) != context_signature(
        annotations, result["context_start_frame"], result["context_end_frame"]
    )
    return result


def _index(run, video, stage):
    if run.get("video_id") != video["id"] or run.get("stage") != stage:
        raise ValueError(f"Expected a {stage} run for this video")
    if run.get("video_sha256", video["sha256"]) != video["sha256"]:
        raise ValueError("Perception source hash does not match this video")
    if run.get("requires_tracking_rerun"):
        if run.get("requires_court_tracking_rerun"):
            raise ValueError(
                "Court calibration changed these inputs; rerun player tracking"
            )
        raise ValueError("Camera corrections changed inputs; rerun tracking")
    start, end = run["start_frame"], run["end_frame"]
    if not 0 <= start < end <= video["frame_count"]:
        raise ValueError("Perception range exceeds source video")
    frames = run["frames"]
    if any(
        type(row["frame"]) is not int
        or not start <= row["frame"] < end
        or not isinstance(row.get("time_s"), int | float)
        or not math.isfinite(row["time_s"])
        or row["time_s"] < 0
        for row in frames
    ) or any(
        a["frame"] >= b["frame"] or a["time_s"] >= b["time_s"]
        for a, b in itertools.pairwise(frames)
    ):
        raise ValueError("Perception frames/times must be finite, ordered and unique")
    if run.get("stride", 1) != 1:
        raise ValueError(
            "Rally proposals require every source frame; rerun at stride 1"
        )
    return {row["frame"]: row for row in frames}


def _person(person):
    box, points = person.get("box", []), person.get("keypoints", [])
    if (
        person.get("track_id") is None
        or len(box) != 4
        or not all(isinstance(x, int | float) and math.isfinite(x) for x in box)
        or box[2] <= box[0]
        or box[3] - box[1] < 5
    ):
        return None
    valid = {
        k: np.asarray(p[:2], dtype=float)
        for k, p in enumerate(points)
        if len(p) >= 3
        and all(isinstance(x, int | float) and math.isfinite(x) for x in p[:3])
        and p[2] >= 0.3
    }
    hips = (
        np.mean([valid[11], valid[12]], axis=0)
        if 11 in valid and 12 in valid
        else np.asarray([(box[0] + box[2]) / 2, box[1] + 0.6 * (box[3] - box[1])])
    )
    wrists = {k: valid[k] for k in (9, 10) if k in valid}
    return {
        "id": person["track_id"],
        "height": box[3] - box[1],
        "top": box[1],
        "feet": np.asarray([(box[0] + box[2]) / 2, box[3]]),
        "wrists": wrists,
        "relative_wrists": {k: p - hips for k, p in wrists.items()},
    }


def _point(row):
    observation = row["shuttle"]
    if (
        not observation.get("visible")
        or observation.get("repaired", False)
        or observation.get("selection_context_excluded", False)
        or any(
            not isinstance(observation.get(axis), int | float)
            or not math.isfinite(observation[axis])
            for axis in ("x", "y")
        )
    ):
        return None
    return np.asarray([observation["x"], observation["y"]], dtype=float)


def _terminal_region(point, frame, annotations, video):
    """Bound a possible settled floor location without asserting a line call.

    Out shots can end beside or behind the court. This calibrated surround is
    only a proposal search region; perspective projection alone cannot prove
    ground contact, identify a fault or decide whether a shot was in or out.
    """
    position = _court_position(point, frame, annotations, video)
    if (
        position is None
        or not np.isfinite(position).all()
        or not all(
            -TERMINAL_COURT_MARGIN <= x <= 1 + TERMINAL_COURT_MARGIN for x in position
        )
    ):
        return None
    return {
        "settled_region": "court"
        if all(0 <= x <= 1 for x in position)
        else "near_court_surround",
        "court_plane_position_hint": [round(float(x), 5) for x in position],
        "line_call_verified": False,
    }


def _court_position(point, frame, annotations, video):
    for calibration in annotations.get("calibrations", []):
        if calibration["start_frame"] <= frame < calibration["end_frame"]:
            polygon = np.asarray(
                [
                    [p["x"] * video["width"], p["y"] * video["height"]]
                    for p in calibration["corners"]
                ],
                dtype=np.float32,
            )
            transform = cv2.getPerspectiveTransform(
                polygon, np.asarray([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)
            )
            return cv2.perspectiveTransform(
                np.asarray([[point]], np.float32), transform
            )[0, 0]
    return None


def _segments(players, shuttle, cuts, start, end, expected):
    segments, current = [], []
    for frame in range(start, end):
        pose, flight = players.get(frame), shuttle.get(frame)
        if (
            pose is not None
            and flight is not None
            and abs(pose["time_s"] - flight["time_s"]) > 0.00002
        ):
            raise ValueError("Player and shuttle source times disagree")
        eligible = (
            pose is not None
            and flight is not None
            and pose.get("calibration_valid") is True
            and pose.get("scene", "live") == "live"
            and flight.get("scene", "live") == "live"
        )
        boundary = (
            frame in cuts
            or (pose and (pose.get("cut") or pose.get("scene_cut")))
            or (flight and (flight.get("cut") or flight.get("scene_cut")))
            or (
                current
                and pose
                and pose["time_s"] - current[-1]["time_s"] > MAX_FRAME_STEP_S + 1e-8
            )
        )
        if (not eligible or boundary) and current:
            segments.append(current)
            current = []
        if not eligible:
            continue
        people = [_person(p) for p in pose["players"]]
        valid_count = sum(p is not None for p in people)
        people = {p["id"]: p for p in people if p is not None}
        current.append(
            {
                "frame": frame,
                "time_s": pose["time_s"],
                "people": people
                if valid_count == len(people)
                and max(2, expected - 1) <= len(people) <= expected
                else {},
                "expected_players": expected,
                "point": _point(flight),
                "quiet": False,
                "quiet_visible": False,
            }
        )
    if current:
        segments.append(current)
    return segments


def _motion(rows, diagonal):
    times = [r["time_s"] for r in rows]
    for i, row in enumerate(rows):
        row["shuttle_speed"] = None
        if i and row["point"] is not None and rows[i - 1]["point"] is not None:
            row["shuttle_speed"] = (
                float(np.linalg.norm(row["point"] - rows[i - 1]["point"]))
                / (times[i] - times[i - 1])
                / diagonal
            )
        lag = bisect.bisect_right(times, times[i] - POSE_LAG_S + 1e-8) - 1
        if (
            lag < 0
            or lag >= i
            or not POSE_LAG_S * 0.7 <= times[i] - times[lag] <= POSE_LAG_S * 1.5
        ):
            continue
        before = rows[lag]["people"]
        if not row["people"] or row["people"].keys() != before.keys():
            continue
        dt = times[i] - times[lag]
        body, wrists = [], []
        for tid, person in row["people"].items():
            old = before[tid]
            height = (person["height"] + old["height"]) / 2
            body.append(
                float(np.linalg.norm(person["feet"] - old["feet"])) / height / dt
            )
            hands = person["relative_wrists"].keys() & old["relative_wrists"].keys()
            if hands:
                wrists.append(
                    max(
                        float(
                            np.linalg.norm(
                                person["relative_wrists"][k] - old["relative_wrists"][k]
                            )
                        )
                        / height
                        / dt
                        for k in hands
                    )
                )
        row["body_speed"] = max(body)
        row["wrist_speed"] = max(wrists) if wrists else None
        row["quiet_visible"] = (
            len(wrists) >= max(1, row["expected_players"] - 1)
            and max(body) <= 0.90
            and max(wrists) <= 1.50
        )
        row["quiet"] = (
            row["quiet_visible"] and len(row["people"]) == row["expected_players"]
        )
    return times


def _window(rows, times, start, end):
    return rows[
        bisect.bisect_left(times, start - 1e-8) : bisect.bisect_right(times, end + 1e-8)
    ]


def _fraction(window, key):
    if len(window) < 2:
        return 0.0
    duration = window[-1]["time_s"] - window[0]["time_s"]
    return (
        sum(
            (b["time_s"] - a["time_s"]) * (bool(a.get(key)) + bool(b.get(key))) / 2
            for a, b in itertools.pairwise(window)
        )
        / duration
    )


def _quiet(window, key="quiet"):
    return _fraction(window, key) >= MIN_CONTEXT_COVERAGE


def _candidate(kind, row, first, last, evidence, track_id=None):
    return {
        "id": f"{kind}-{row['frame']}",
        "kind": kind,
        "frame": row["frame"],
        "time_s": row["time_s"],
        "start_frame": first["frame"],
        "end_frame": last["frame"],
        "start_time_s": first["time_s"],
        "end_time_s": last["time_s"],
        "timing": "uncertain_interval",
        "track_id": track_id,
        "player_id": None,
        "needs_review": True,
        "evidence": evidence,
    }


def _moving(rows):
    """Sustained flight, excluding isolated heatmap/quantization jumps."""
    result, current = [], []
    for row in rows:
        speed = row["shuttle_speed"]
        if speed is not None and MOVING_DIAGONALS_PER_S <= speed <= 6:
            current.append(row)
        else:
            if len(current) >= 3:
                result.extend(current)
            current = []
    if len(current) >= 3:
        result.extend(current)
    return result


def _serve(rows, times, index, diagonal, annotations, video):
    row = rows[index]
    if (
        row["shuttle_speed"] is None
        or not MOVING_DIAGONALS_PER_S <= row["shuttle_speed"] <= 6
    ):
        return None
    start, stop = row["time_s"] - QUIET_S - 0.12, row["time_s"] - 0.12
    if start < times[0]:
        return None
    context = _window(rows, times, start, stop)
    if not _quiet(context, "quiet_visible"):
        return None
    if any((r["shuttle_speed"] or 0) >= MOVING_DIAGONALS_PER_S for r in context):
        return None
    departure = _window(rows, times, row["time_s"], row["time_s"] + 0.20)
    moving = len(_moving(departure))
    if moving < 3:
        return None
    launch = _window(rows, times, row["time_s"] - 0.20, row["time_s"] + 0.08)
    nearby = []
    for sample in launch:
        if sample["point"] is None:
            continue
        for tid, person in sample["people"].items():
            if not person["wrists"]:
                continue
            hands = list(person["wrists"].values())
            distances = [
                float(np.linalg.norm(p - sample["point"])) / person["height"]
                for p in hands
            ]
            hand = int(np.argmin(distances))
            if (
                distances[hand] > 0.75
                or hands[hand][1] < person["top"] + person["height"] * 0.35
            ):
                continue
            location = _court_position(
                person["feet"], sample["frame"], annotations, video
            )
            if location is None or not (
                0.1 <= location[0] <= 0.9
                and (0.04 <= location[1] <= 0.38 or 0.62 <= location[1] <= 0.96)
            ):
                continue
            opponents = [
                _court_position(p["feet"], sample["frame"], annotations, video)
                for key, p in sample["people"].items()
                if key != tid
            ]
            if not any(
                p is not None and (p[1] < 0.5) != (location[1] < 0.5) for p in opponents
            ):
                continue
            nearby.append((distances[hand], sample["frame"], tid, sample))
    if not nearby:
        return None
    _, _, tid, representative = min(nearby, key=lambda r: (r[0], r[1], r[2]))
    possible_tracks = sorted({item[2] for item in nearby})
    if len(possible_tracks) > 1:
        tid = None
    return _candidate(
        "serve",
        representative,
        launch[0],
        launch[-1],
        {
            "quiet_context_s": QUIET_S,
            "observed_quiet_fraction": round(_fraction(context, "quiet_visible"), 3),
            "full_player_context_fraction": round(_fraction(context, "quiet"), 3),
            "partial_player_context": _fraction(context, "quiet")
            < MIN_CONTEXT_COVERAGE,
            "observed_departure_frames": moving,
            "possible_track_ids": possible_tracks,
            "hitter_hint_status": "ambiguous_proximity"
            if tid is None
            else "unconfirmed_track",
            "service_posture_hint": "low wrist, service-area feet and an observed opponent",
            "meaning": "Observed quiet-player context and low near-wrist launch; serve mechanics and identity still need review",
        },
        tid,
    )


def _settling_fit(rows, times, row, settled, moving, diagonal):
    first = moving[-1]["time_s"] - 0.24
    samples = _window(rows, times, first, settled[-1]["time_s"])
    if len(samples) < 8 or any(r["point"] is None for r in samples):
        return None
    points = np.asarray([r["point"] for r in samples])
    ts = np.asarray([r["time_s"] - row["time_s"] for r in samples])
    smooth = np.column_stack([np.ones(len(ts)), ts, ts**2])
    fit = smooth @ np.linalg.lstsq(smooth, points, rcond=None)[0]
    smooth_error = float(np.sqrt(np.mean(np.sum((fit - points) ** 2, axis=1))))
    best = None
    for knot in _window(rows, times, moving[-1]["time_s"] - 0.16, row["time_s"]):
        t = ts - (knot["time_s"] - row["time_s"])
        if sum(t < 0) < 3 or sum(t >= 0) < 4:
            continue
        design = np.column_stack([np.ones(len(t)), t, np.maximum(t, 0)])
        weights = np.linalg.lstsq(design, points, rcond=None)[0]
        velocity = float(np.linalg.norm(weights[1] + weights[2])) / diagonal
        error = float(
            np.sqrt(np.mean(np.sum((design @ weights - points) ** 2, axis=1)))
        )
        if (
            velocity > 0.035
            or error > smooth_error * 0.80
            or smooth_error - error < 0.5
        ):
            continue
        if best is None or error < best[0]:
            best = (error, knot, velocity)
    if best is None:
        return None
    return {
        "knot": best[1],
        "piecewise_rmse_px": round(best[0], 3),
        "quadratic_rmse_px": round(smooth_error, 3),
        "tail_speed_diagonals_per_s": round(best[2], 4),
    }


def _ending(rows, times, index, diagonal, annotations, video):
    row = rows[index]
    if row["time_s"] + SETTLED_S > times[-1] + 1e-8:
        return None
    settled = _window(rows, times, row["time_s"], row["time_s"] + SETTLED_S)
    for sample in settled:
        sample["visible_point"] = sample["point"] is not None
    if _fraction(settled, "visible_point") < 0.80:
        return None
    points = [r["point"] for r in settled if r["point"] is not None]
    if len(points) < 4:
        return None
    center = np.median(points, axis=0)
    region = _terminal_region(center, row["frame"], annotations, video)
    if (
        region is None
        or max(float(np.linalg.norm(p - center)) for p in points)
        > diagonal * STILL_RADIUS_DIAGONALS
    ):
        return None
    incoming = _window(rows, times, row["time_s"] - 1.20, row["time_s"])
    moving = _moving(incoming)
    if len(moving) < 3:
        return None
    transition = _window(rows, times, moving[-1]["time_s"], row["time_s"])
    if any(r["point"] is None or (r["shuttle_speed"] or 0) > 6 for r in transition):
        return None
    fit = _settling_fit(rows, times, row, settled, moving, diagonal)
    if fit is None:
        return None
    followup = None
    for anchor in _window(
        rows, times, row["time_s"], min(row["time_s"] + 1.20, times[-1] - QUIET_S)
    ):
        context = _window(rows, times, anchor["time_s"], anchor["time_s"] + QUIET_S)
        if _quiet(context):
            followup = (anchor, context)
            break
    if followup is None:
        return None
    knot = fit.pop("knot")
    first = _window(rows, times, knot["time_s"] - 0.12, row["time_s"])[0]
    return _candidate(
        "rally_end",
        knot,
        first,
        row,
        {
            "stationary_context_s": SETTLED_S,
            "stationary_radius_px": round(diagonal * STILL_RADIUS_DIAGONALS, 2),
            "quiet_player_followup_s": QUIET_S,
            "quiet_followup_delay_s": round(followup[0]["time_s"] - row["time_s"], 3),
            "full_player_quiet_fraction": round(_fraction(followup[1], "quiet"), 3),
            "stationary_observation_fraction": round(
                _fraction(settled, "visible_point"), 3
            ),
            **region,
            **fit,
            "meaning": "Observed settling unlike a smooth flight apex, followed by quieter full-player motion; terminal contact/fault remains unverified",
        },
    )


def validate_rally_inputs(
    video, player_run, shuttle_run, annotations, source_times=None
):
    player_run = reviewed_run(player_run, annotations)
    shuttle_run = reviewed_run(shuttle_run, annotations)
    players = _index(player_run, video, "players")
    shuttle = _index(shuttle_run, video, "shuttle")
    if source_times is not None:
        if len(source_times) != video["frame_count"] or any(
            abs(row["time_s"] - source_times[row["frame"]]) > 0.00002
            for run in (player_run, shuttle_run)
            for row in run["frames"]
        ):
            raise ValueError("Perception timestamps do not match source frames")
    if (
        "calibration_signature" in player_run
        and player_run["calibration_signature"]
        != context_signature(
            effective_annotations(annotations, player_run),
            player_run["start_frame"],
            player_run["end_frame"],
        )["court"]
    ):
        raise ValueError(
            "Court calibration changed these inputs; rerun player tracking"
        )
    if max(player_run["start_frame"], shuttle_run["start_frame"]) >= min(
        player_run["end_frame"], shuttle_run["end_frame"]
    ):
        raise ValueError("Player and shuttle ranges must overlap")
    return player_run, shuttle_run, players, shuttle


def propose_rallies(video, player_run, shuttle_run, annotations, source_times=None):
    """Return uncertain boundary proposals and input-quality diagnostics.

    The annotation argument supplies only reviewed camera/scene context and court
    geometry. Existing serves/endings/shot labels are deliberately never read.
    """
    if hasattr(annotations, "model_dump"):
        annotations = annotations.model_dump()
    # Copies make it safe for diagnostics/evidence consumers to retain results.
    annotations = deepcopy(annotations)
    player_run, shuttle_run, players, shuttle = validate_rally_inputs(
        video, player_run, shuttle_run, annotations, source_times
    )
    annotations = effective_annotations(annotations, player_run)
    start = max(player_run["start_frame"], shuttle_run["start_frame"])
    end = min(player_run["end_frame"], shuttle_run["end_frame"])
    if start >= end:
        raise ValueError("Player and shuttle ranges must overlap")
    cuts = set(player_run.get("cut_frames", [])) | set(
        shuttle_run.get("cut_frames", [])
    )
    segments = _segments(
        players, shuttle, cuts, start, end, 2 if video["mode"] == "singles" else 4
    )
    diagonal = math.hypot(video["width"], video["height"])
    candidates = []
    quiet_rows = complete_rows = 0
    for rows in segments:
        segment_candidates = []
        times = _motion(rows, diagonal)
        complete_rows += sum(len(r["people"]) == r["expected_players"] for r in rows)
        quiet_rows += sum(r["quiet"] for r in rows)
        for i in range(len(rows)):
            for candidate in (
                _serve(rows, times, i, diagonal, annotations, video),
                _ending(rows, times, i, diagonal, annotations, video),
            ):
                if candidate is None:
                    continue
                if any(
                    c["kind"] == candidate["kind"]
                    and abs(c["time_s"] - candidate["time_s"]) < 1.0
                    for c in segment_candidates
                ):
                    continue
                segment_candidates.append(candidate)
        candidates.extend(segment_candidates)
    candidates.sort(key=lambda c: (c["frame"], c["kind"]))
    return {
        "schema_version": 1,
        "stage": "rallies",
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "start_frame": start,
        "end_frame": end,
        "method": METHOD,
        "recipe": {
            "pose_lag_s": POSE_LAG_S,
            "quiet_context_s": QUIET_S,
            "settled_context_s": SETTLED_S,
            "minimum_context_coverage": MIN_CONTEXT_COVERAGE,
            "moving_diagonals_per_s": MOVING_DIAGONALS_PER_S,
            "still_radius_diagonals": STILL_RADIUS_DIAGONALS,
            "max_frame_step_s": MAX_FRAME_STEP_S,
            "terminal_court_margin_fraction": TERMINAL_COURT_MARGIN,
            "terminal_region_meaning": "Bounded search region around calibrated court, not proof of floor contact or an in/out call",
        },
        "interval_bounds": "inclusive",
        "meaning": "Experimental boundary review intervals, not verified rallies or exact terminal times",
        "candidates": candidates,
        "candidate_count": len(candidates),
        "diagnostics": {
            "eligible_frames": sum(len(rows) for rows in segments),
            "complete_player_body_frames": complete_rows,
            "quiet_pose_frames": quiet_rows,
            "camera_context_count": len(segments),
            "abstention_policy": "No boundary from missing detections, invalid calibration, non-live scenes, camera/source gaps or clip edges alone",
        },
    }


def generate_rallies(
    video,
    players,
    shuttle,
    annotations,
    player_run_id,
    shuttle_run_id,
    output,
    source_times=None,
):
    result = propose_rallies(video, players, shuttle, annotations, source_times)
    doc = (
        annotations.model_dump() if hasattr(annotations, "model_dump") else annotations
    )
    doc = effective_annotations(doc, players)
    # Include full input context: an earlier camera edit can change track IDs.
    start = min(players["start_frame"], shuttle["start_frame"])
    end = max(players["end_frame"], shuttle["end_frame"])
    result.update(
        player_run_id=player_run_id,
        shuttle_run_id=shuttle_run_id,
        annotation_revision=doc.get("revision", 0),
        source_timestamps_validated=source_times is not None,
        context_start_frame=start,
        context_end_frame=end,
        context_signature=context_signature(doc, start, end),
        court_context=court_run_context(players),
        input_models={
            stage: {
                key: run[key]
                for key in (
                    "model",
                    "model_variant",
                    "checkpoint_sha256",
                    "model_source",
                )
                if key in run
            }
            for stage, run in (("players", players), ("shuttle", shuttle))
        },
        calibration_provenance="recorded_snapshot"
        if "calibration_signature" in players
        else "legacy_unverified_snapshot",
    )
    write_json(output, result)
    return {k: v for k, v in result.items() if k != "candidates"}
