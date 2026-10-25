"""Offline raw camera-cut scoring; source identity is a supplied metadata claim.

No images, detectors, reviewed overlays or application Store are accessed. Exact
reference cuts must be supplied explicitly; validation does not establish truth.
"""

import re
from bisect import bisect_right
from collections import Counter
from itertools import pairwise

from .evaluation import (
    TIME_EPSILON_S,
    _contact_score,
    _source_time,
    _validate_native_clock,
)

MAX_CUTS = 10000
MAX_WINDOWS = 1000
MAX_MATCH_CELLS = 1000000
LIMITATIONS = [
    "Supplied hashes and timestamps bind metadata; media bytes are not inspected.",
    "Reference accuracy, independence and exhaustive review are not established.",
    "Camera cuts do not establish live/replay, contacts, rallies or identity.",
    "Timestamp discontinuities remain separate from visual camera edits.",
]


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _object(value, name):
    _require(type(value) is dict, f"{name} must be an object")
    return value


def _integer(value, name, low, high):
    _require(type(value) is int and low <= value <= high, f"Invalid {name}")
    return value


def _id(value):
    _require(type(value) is str and bool(value.strip()), "IDs must be nonempty strings")
    return value


def _list(value, name, limit):
    _require(
        type(value) is list and len(value) <= limit, f"Invalid or oversized {name}"
    )
    return value


def _range(item, count):
    left = _integer(item.get("start_frame"), "range start", 0, count - 1)
    right = _integer(item.get("end_frame"), "range end", left + 1, count)
    return left, right


def _point(row, count, times):
    _object(row, "Cut")
    frame = _integer(row.get("frame"), "cut frame", 1, count - 1)
    time = _source_time(row.get("time_s"), "Cut time_s")
    _require(
        abs(time - times[frame]) <= TIME_EPSILON_S,
        "Cut time_s must match its native source frame",
    )
    return frame


def evaluate_camera(video, native_timestamps, run, reference, *, tolerance_s=0.12):
    """Score only transitions whose adjacent frames share complete review.

    Windows are half-open; a cut names the first frame of a new view. Matching
    cannot cross a window edge or timestamp discontinuity. All original records
    are validated before any eligibility filtering. Inputs are never modified.
    """
    _object(video, "Video")
    _object(run, "Raw camera run")
    _object(reference, "Camera reference")
    count = _validate_native_clock(video, native_timestamps)
    times = native_timestamps
    _id(video.get("id"))
    _require(
        type(video.get("sha256")) is str
        and re.fullmatch(r"[0-9a-f]{64}", video["sha256"]),
        "Source needs a SHA256 digest",
    )
    tolerance_s = _source_time(tolerance_s, "Matching tolerance")
    for item in (run, reference):
        _require(
            item.get("video_id") == video["id"]
            and item.get("video_sha256") == video["sha256"],
            "Source identity must match video, run and reference",
        )
        _require(
            type(item.get("schema_version")) is int and item["schema_version"] == 1,
            "Expected schema_version 1",
        )
    _require(run.get("stage") == "segments", "Expected a raw segments run")
    _require(
        not any(
            key in run
            for key in (
                "raw_cut_frames",
                "applied_camera_corrections",
                "camera_annotation_revision",
                "scene_annotation_revision",
                "preceding_reviewed_cut_frame",
            )
        ),
        "Reviewed/corrected camera overlays are not automatic predictions",
    )
    start, end = _range(run, count)
    threshold = _source_time(run.get("timestamp_gap_threshold_s"), "Gap threshold")
    _require(threshold > 0, "Gap threshold must be positive")
    cut_frames = _list(run.get("cut_frames"), "cut_frames", MAX_CUTS)
    for frame in cut_frames:
        _integer(frame, "raw cut frame", max(start, 1), end - 1)
    _require(
        cut_frames == sorted(set(cut_frames)), "Raw cuts must be unique and sorted"
    )
    boundaries = _list(run.get("boundaries"), "boundaries", MAX_CUTS)
    gaps, predictions = set(), []
    for row in boundaries:
        frame = _point(row, count, times)
        _require(start <= frame < end, "Boundary lies outside the raw run")
        _require(row.get("reviewed") is False, "Only unreviewed raw boundaries qualify")
        reason = row.get("reason")
        _require(
            reason in ("visual_cut", "timestamp_discontinuity"),
            "Boundary reason must distinguish visual cuts and timestamp gaps",
        )
        if reason == "timestamp_discontinuity":
            gaps.add(frame)
        else:
            predictions.append(
                {"id": f"cut:{frame}", "frame": frame, "time_s": times[frame]}
            )
    _require(
        [row["frame"] for row in boundaries] == cut_frames,
        "Raw boundaries must exactly match sorted cut_frames",
    )
    actual_gaps = {
        frame
        for frame in range(max(1, start), end)
        if times[frame] - times[frame - 1] > threshold + 1e-8
    }
    _require(
        gaps == actual_gaps, "Gap reasons must match native timestamp discontinuities"
    )
    _require(
        set(reference) == {"schema_version", "video_id", "video_sha256", "windows"},
        "Unexpected reference fields",
    )
    windows = _list(reference.get("windows"), "review windows", MAX_WINDOWS)
    previous_end, ids, references = 0, set(), []
    for window in windows:
        _object(window, "Review window")
        _require(
            set(window) == {"id", "start_frame", "end_frame", "cuts_complete", "cuts"},
            "Unexpected review window fields",
        )
        identifier = _id(window["id"])
        _require(identifier not in ids, "Review and cut IDs must be unique")
        ids.add(identifier)
        left, right = _range(window, count)
        _require(
            left >= previous_end, "Review windows must be sorted and nonoverlapping"
        )
        previous_end = right
        _require(type(window["cuts_complete"]) is bool, "cuts_complete must be boolean")
        last_frame = -1
        for row in _list(window["cuts"], "reference cuts", MAX_CUTS):
            frame = _point(row, count, times)
            _require(
                set(row) == {"id", "frame", "time_s"}, "Expected exact cut reference"
            )
            identifier = _id(row["id"])
            _require(identifier not in ids, "Review and cut IDs must be unique")
            ids.add(identifier)
            _require(
                left <= frame < right and frame > last_frame,
                "Invalid reference order/range",
            )
            last_frame = frame
            references.append(
                {"id": identifier, "frame": frame, "time_s": times[frame]}
            )
            _require(len(references) <= MAX_CUTS, "Too many reference cuts")

    starts = [window["start_frame"] for window in windows]

    def window_at(frame):
        index = bisect_right(starts, frame) - 1
        if index >= 0 and frame < windows[index]["end_frame"]:
            return index
        return None

    def reason(frame):
        if not start < frame < end:
            return "outside_run_or_run_edge"
        if frame in gaps:
            return "timestamp_gap"
        before, after = window_at(frame - 1), window_at(frame)
        if before != after:
            return "review_window_edge"
        if after is None:
            return "unreviewed"
        if not windows[after]["cuts_complete"]:
            return "incomplete_review"
        return None

    coverage = Counter(reason(frame) or "eligible" for frame in range(start + 1, end))
    transition_counts = {
        key: coverage[key]
        for key in (
            "eligible",
            "timestamp_gap",
            "review_window_edge",
            "unreviewed",
            "incomplete_review",
        )
    }
    eligible, excluded = {}, {}
    for name, records in (("reference", references), ("prediction", predictions)):
        eligible[name], excluded[name] = [], []
        for row in records:
            why = reason(row["frame"])
            if why is None:
                eligible[name].append(row)
            else:
                excluded[name].append(
                    {"id": row["id"], "frame": row["frame"], "reason": why}
                )
    ranges, skipped = [], []
    for window in windows:
        left, right = max(start, window["start_frame"]), min(end, window["end_frame"])
        if left >= right or not window["cuts_complete"]:
            skipped.append(
                {
                    "id": window["id"],
                    "reason": "outside_run" if left >= right else "incomplete_review",
                }
            )
            continue
        edges = [left, *sorted(g for g in gaps if left < g < right), right]
        ranges.extend((a + 1, b) for a, b in pairwise(edges) if a + 1 < b)
    _require(
        sum(b - a for a, b in ranges) == transition_counts["eligible"],
        "Internal transition coverage mismatch",
    )
    cells = sum(
        sum(a <= r["frame"] < b for r in eligible["reference"])
        * sum(a <= p["frame"] < b for p in eligible["prediction"])
        for a, b in ranges
    )
    _require(
        cells <= MAX_MATCH_CELLS,
        "Matching cell limit exceeded; use smaller review windows",
    )
    score = _contact_score(
        eligible["reference"], eligible["prediction"], ranges, tolerance_s
    )
    status = "ok" if transition_counts["eligible"] else "needs_complete_camera_review"
    summary = {
        "status": status,
        "source_transitions": count - 1,
        "run_transitions": end - start - 1,
        "transition_counts": transition_counts,
        "review_windows": len(windows),
        "complete_review_windows": sum(w["cuts_complete"] for w in windows),
        "reference_cuts": len(references),
        "raw_visual_cuts": len(predictions),
        "timestamp_gap_boundaries": len(gaps),
        "eligible_reference_cuts": len(eligible["reference"]),
        "eligible_visual_cuts": len(eligible["prediction"]),
        "excluded_reference_cuts": len(excluded["reference"]),
        "excluded_visual_cuts": len(excluded["prediction"]),
        "tolerance_s": tolerance_s,
        "metrics": score["metrics"] if status == "ok" else None,
        "mean_absolute_error_s": score["mean_absolute_error_s"],
        "max_absolute_error_s": score["max_absolute_error_s"],
    }
    return {
        "schema_version": 1,
        "stage": "camera_evaluation",
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "run_start_frame": start,
        "run_end_frame": end,
        "clock_status": "validated",
        "timestamp_gap_threshold_s": threshold,
        "matching": "maximum cardinality, then minimum absolute native-time error within each continuous reviewed window",
        "summary": summary,
        "score": score if status == "ok" else None,
        "eligible_transition_ranges": [list(r) for r in ranges],
        "excluded": excluded,
        "skipped_windows": skipped,
        "limitations": list(LIMITATIONS),
    }
