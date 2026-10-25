"""Experimental review intervals supported jointly by audio and raw vision."""

import copy
import math

from .contacts import _gap_pose, _raw_visible, _valid_window

METHOD = "optional acoustic onset, shuttle gap and moving wrist v1"


def _aligned_players(window, players):
    """Require unambiguous pairwise source correspondence, without retiming.

    Sparse poses are allowed. A row is relevant by either frame or time so a
    conflicting clock cannot hide it outside the window. This is not an
    independent check against native media or acoustic synchronization.
    """
    source_times = {row["frame"]: row["time_s"] for row in window}
    aligned, seen = [], set()
    for row in players:
        frame, time_s = row.get("frame"), row.get("time_s")
        # An unknown clock cannot establish that the row is outside context.
        if (
            isinstance(time_s, bool)
            or not isinstance(time_s, int | float)
            or not math.isfinite(time_s)
        ):
            return None
        valid_frame = type(frame) is int and frame >= 0
        if not (
            window[0]["time_s"] <= time_s <= window[-1]["time_s"]
            or (valid_frame and frame in source_times)
        ):
            continue
        if (
            not valid_frame
            or frame not in source_times
            or frame in seen
            or not math.isclose(time_s, source_times[frame], rel_tol=0, abs_tol=1e-9)
        ):
            return None
        seen.add(frame)
        aligned.append(row)
    return sorted(aligned, key=lambda row: row["time_s"])


def _interval_context(rows, index, onset, cuts, diagonal):
    """Bracket source times and retain every consumed selection-history row."""
    before = [i for i in range(index + 1) if rows[i]["time_s"] <= onset - 0.12]
    after = [i for i in range(index, len(rows)) if rows[i]["time_s"] >= onset + 0.12]
    if not before or not after:
        return None
    left, right = before[-1], after[0]
    start, end = min(left, index - 4), max(right, index + 4)
    positions = {row["frame"]: i for i, row in enumerate(rows)}
    while True:
        context = rows[start : end + 1]
        required_start, required_end = start, end
        for row in context:
            point = row["shuttle"]
            first = point.get("selection_context_start_frame", row["frame"])
            last = point.get("selection_context_end_frame", row["frame"] + 1)
            if (
                type(first) is not int
                or type(last) is not int
                or not first <= row["frame"] < last
                or first not in positions
                or last - 1 not in positions
            ):
                return None
            required_start = min(required_start, positions[first])
            required_end = max(required_end, positions[last - 1])
        if (required_start, required_end) == (start, end):
            break
        start, end = required_start, required_end
    if not _valid_window(context, cuts, diagonal):
        return None
    return rows[left], rows[right], context


def add_audio_support(candidates, shuttle_run, player_run, video, cues):
    """Keep visual proposals; add only uncertain, visually supported intervals.

    This is deliberately opt-in. An acoustic onset may be a shoe, a crowd sound,
    or another court. Its source time is not certified AV synchronization.
    """
    selected = copy.deepcopy(candidates)
    if cues.get("status") != "available" or not player_run:
        return selected
    rows = shuttle_run["frames"]
    players = player_run["frames"]
    if not rows or not players:
        return selected
    cuts = set(shuttle_run.get("cut_frames", [])) | set(
        player_run.get("cut_frames", [])
    )
    diagonal = math.hypot(video["width"], video["height"])
    supported = False
    for peak in cues["peaks"]:
        t = peak["time_s"]
        if not math.isfinite(t):
            continue
        index = min(range(len(rows)), key=lambda i: abs(rows[i]["time_s"] - t))
        window = rows[max(0, index - 4) : index + 5]
        if (
            len(window) != 9
            or abs(rows[index]["time_s"] - t) > 0.05
            or not _valid_window(window, cuts, diagonal)
        ):
            continue
        # Sparse wrists within the existing +/-120 ms interval can lie beyond
        # the nine-row gap window at high frame rates. Validate their source
        # context too, while keeping the original proposal bounds unchanged.
        left = min(window[0]["time_s"], t - 0.12)
        right = max(window[-1]["time_s"], t + 0.12)
        pose_context = [row for row in rows if left <= row["time_s"] <= right]
        if not _valid_window(pose_context, cuts, diagonal):
            continue
        aligned = _aligned_players(pose_context, players)
        if aligned is None or any(
            row.get("scene", "live") != "live" or row.get("cut") or row.get("scene_cut")
            for row in aligned
        ):
            continue
        # Audio cannot create a proposal in otherwise smooth visible flight.
        # There must be missing raw shuttle evidence near the acoustic onset.
        missing_frames = [
            row["frame"]
            for row in window
            if not _raw_visible(row) and abs(row["time_s"] - t) <= 0.12
        ]
        if not missing_frames:
            continue
        observations = sorted(
            (
                row
                for row in window
                if _raw_visible(row) and abs(row["time_s"] - t) <= 0.08
            ),
            key=lambda row: abs(row["time_s"] - t),
        )
        support = None
        for row in observations:
            point = [row["shuttle"]["x"], row["shuttle"]["y"]]
            pose = _gap_pose(point, aligned, t - 0.12, t + 0.12, diagonal)
            if pose and pose["pose_samples"] >= 3:
                support = row, pose
                break
        if support is None:
            continue
        observed, pose = support
        evidence = {
            "audio": copy.deepcopy(peak),
            "pose": pose,
            "observed_shuttle_frame": observed["frame"],
            "missing_frames": missing_frames,
            "av_offset_calibrated": False,
        }
        existing = [
            candidate
            for candidate in selected
            if (
                abs(candidate["time_s"] - t) <= 0.12
                and candidate.get("track_id") in (None, pose["track_id"])
            )
            or set(missing_frames).intersection(
                candidate.get("evidence", {}).get("missing_frames", [])
            )
        ]
        if existing:
            nearest = min(existing, key=lambda candidate: abs(candidate["time_s"] - t))
            evidence["hitter_agrees"] = nearest.get("track_id") in (
                None,
                pose["track_id"],
            )
            nearest.setdefault("evidence", {}).setdefault("audio_support", []).append(
                evidence
            )
            supported = True
            continue
        # Bracket +/-120 ms with actual source frames, not inferred FPS. These
        # are review bounds, not a calibrated contact confidence interval.
        interval = _interval_context(rows, index, t, cuts, diagonal)
        if interval is None:
            continue
        left, right, context = interval
        context_players = _aligned_players(context, players)
        if context_players is None or any(
            row.get("scene", "live") != "live" or row.get("cut") or row.get("scene_cut")
            for row in context_players
        ):
            continue
        middle = rows[index]
        selected.append(
            {
                "id": f"contact-audio-{middle['frame']}",
                "frame": middle["frame"],
                "time_s": middle["time_s"],
                "start_frame": left["frame"],
                "end_frame": right["frame"],
                "start_time_s": left["time_s"],
                "end_time_s": right["time_s"],
                "context_start_frame": context[0]["frame"],
                "context_end_frame": context[-1]["frame"] + 1,
                "interval_bounds": "inclusive",
                "timing": "uncertain_interval",
                "track_id": pose["track_id"],
                "player_id": None,
                "score": round(min(1, peak["strength_ratio"] / 10), 3),
                "evidence_source": "audio_shuttle_gap_and_pose",
                "evidence": evidence,
                "reason": "audio onset near moving wrist and shuttle gap; verify sound source and entire interval",
                "reviewed": False,
            }
        )
        supported = True
    return (
        sorted(selected, key=lambda candidate: candidate["frame"])
        if supported
        else selected
    )
