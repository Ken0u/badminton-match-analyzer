"""Evaluate saved predictions against explicit human review coverage.

The pure functions take plain dictionaries (use ``annotations.model_dump()``).
Contact event ``time_s`` must already be normalized from source timestamps by the
Store; candidate times come from source-aligned inference. No FPS conversion is
used. Review windows and run ranges use half-open source frame intervals.
Contact uncertainty bounds are inclusive. Strict timing metrics compare proposal
representative times, which are navigation locations for occlusion proposals.
"""

import math
from itertools import pairwise

from .scene_review import camera_review_signature, reviewed_contacts


def _base(video, annotations, run, stage):
    if run.get("video_id") != video["id"] or run.get("stage") != stage:
        raise ValueError(f"Expected a {stage} run for this video")
    start, end = run["start_frame"], run["end_frame"]
    if not 0 <= start < end <= video["frame_count"]:
        raise ValueError("Run range must lie within the source video")
    return {
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "annotation_revision": annotations["revision"],
        "run_id": run.get("run_id"),
        "run_start_frame": start,
        "run_end_frame": end,
    }


def _metrics(tp, fp, fn):
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
    }


def _match_contacts(events, candidates, tolerance):
    """Maximum-cardinality, minimum-total-error ordered bipartite matching.

    For absolute time differences an optimal matching has no crossing pairs.
    Dynamic programming therefore avoids a greedy match stealing a later event's
    only candidate. The score orders match count before total timing error.
    """
    events = sorted(events, key=lambda event: (event["time_s"], event["frame"]))
    candidates = sorted(candidates, key=lambda item: (item["time_s"], item["frame"]))
    n, m = len(events), len(candidates)
    scores = [[(0, 0.0)] * (m + 1) for _ in range(n + 1)]
    moves = [bytearray(m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            # Minimize (-match count, absolute timing error).
            options = [(scores[i - 1][j], 1), (scores[i][j - 1], 2)]
            error = abs(events[i - 1]["time_s"] - candidates[j - 1]["time_s"])
            if error <= tolerance + 1e-9:
                count, cost = scores[i - 1][j - 1]
                options.append(((count - 1, cost + error), 3))
            scores[i][j], moves[i][j] = min(options, key=lambda option: option[0])
    matches = []
    i, j = n, m
    while i and j:
        move = moves[i][j]
        if move == 3:
            event, candidate = events[i - 1], candidates[j - 1]
            delta = candidate["time_s"] - event["time_s"]
            matches.append(
                {
                    "event_id": event["id"],
                    "candidate_id": candidate["id"],
                    "event_frame": event["frame"],
                    "candidate_frame": candidate["frame"],
                    "event_time_s": event["time_s"],
                    "candidate_time_s": candidate["time_s"],
                    "signed_error_s": delta,
                    "absolute_error_s": abs(delta),
                }
            )
            i, j = i - 1, j - 1
        elif move == 1:
            i -= 1
        else:
            j -= 1
    return list(reversed(matches))


def _contact_score(events, candidates, ranges, tolerance):
    matches = []
    for start, end in ranges:
        matches.extend(
            _match_contacts(
                [event for event in events if start <= event["frame"] < end],
                [item for item in candidates if start <= item["frame"] < end],
                tolerance,
            )
        )
    matched_events = {item["event_id"] for item in matches}
    matched_candidates = {item["candidate_id"] for item in matches}
    errors = [item["absolute_error_s"] for item in matches]
    return {
        "tolerance_s": tolerance,
        "metrics": _metrics(
            len(matches), len(candidates) - len(matches), len(events) - len(matches)
        ),
        "matches": matches,
        "unmatched_event_ids": [
            e["id"] for e in events if e["id"] not in matched_events
        ],
        "unmatched_candidate_ids": [
            item["id"] for item in candidates if item["id"] not in matched_candidates
        ],
        "mean_absolute_error_s": sum(errors) / len(errors) if errors else None,
        "max_absolute_error_s": max(errors) if errors else None,
    }


def _frame_bounds(item, frame_count, prefix=""):
    start_key, end_key = f"{prefix}start_frame", f"{prefix}end_frame"
    start, end = item.get(start_key), item.get(end_key)
    if start is None and end is None:
        start = end = item["frame"]
    if (
        type(start) is not int
        or type(end) is not int
        or type(item["frame"]) is not int
        or not 0 <= start <= item["frame"] <= end < frame_count
    ):
        raise ValueError(
            "Contact interval must have paired inclusive source frame bounds containing its frame"
        )
    return start, end


def _validate_candidate(candidate, video, run):
    start, end = _frame_bounds(candidate, video["frame_count"])
    if not run["start_frame"] <= start <= end < run["end_frame"]:
        raise ValueError("Contact candidate interval must lie within its run")
    if "context_start_frame" in candidate or "context_end_frame" in candidate:
        left, right = (
            candidate.get("context_start_frame"),
            candidate.get("context_end_frame"),
        )
        if (
            type(left) is not int
            or type(right) is not int
            or not run["start_frame"]
            <= left
            <= start
            <= end
            < right
            <= run["end_frame"]
        ):
            raise ValueError(
                "Contact evidence context must contain its interval and lie within its run"
            )
    time = candidate["time_s"]
    if not isinstance(time, int | float) or not math.isfinite(time) or time < 0:
        raise ValueError("Contact timestamps must be finite source times")
    left, right = candidate.get("start_time_s"), candidate.get("end_time_s")
    if left is not None or right is not None:
        if (
            not isinstance(left, int | float)
            or not isinstance(right, int | float)
            or not math.isfinite(left)
            or not math.isfinite(right)
            or not 0 <= left <= time <= right
        ):
            raise ValueError(
                "Contact interval times must be paired finite source times containing time_s"
            )
    return candidate | {"start_frame": start, "end_frame": end}


def _uncertain_candidate(candidate):
    return (
        candidate.get("start_frame", candidate["frame"])
        < candidate.get("end_frame", candidate["frame"])
        or candidate.get("timing") == "uncertain_interval"
    )


def _interval_coverage(events, candidates, ranges):
    """Maximum-cardinality one-to-one containment, separate from timing metrics.

    For ordered point events and interval predictions, assigning the available
    containing interval with the earliest end preserves all future choices.
    Matching is confined to one uninterrupted reviewed range at a time.
    """
    matches = []
    for start, end in ranges:
        available = {
            item["id"]: item for item in candidates if start <= item["frame"] < end
        }
        for event in sorted(
            (event for event in events if start <= event["frame"] < end),
            key=lambda event: event["frame"],
        ):
            containing = [
                item
                for item in available.values()
                if item.get("start_frame", item["frame"])
                <= event["frame"]
                <= item.get("end_frame", item["frame"])
            ]
            if not containing:
                continue
            chosen = min(
                containing,
                key=lambda item: (item.get("end_frame", item["frame"]), item["id"]),
            )
            matches.append(
                {
                    "event_id": event["id"],
                    "event_frame": event["frame"],
                    "candidate_id": chosen["id"],
                    "start_frame": chosen.get("start_frame", chosen["frame"]),
                    "end_frame": chosen.get("end_frame", chosen["frame"]),
                    "uncertain_candidate": _uncertain_candidate(chosen),
                }
            )
            del available[chosen["id"]]
    event_ids = {item["event_id"] for item in matches}
    candidate_ids = {item["candidate_id"] for item in matches}
    return {
        "meaning": "A proposal interval contains a reviewed point contact; this does not measure exact hit timing accuracy",
        "matching": "one-to-one maximum-cardinality inclusive-frame containment within reviewed ranges",
        "reviewed_contact_count": len(events),
        "candidate_count": len(candidates),
        "matched_count": len(matches),
        "matches": matches,
        "unmatched_event_ids": [
            event["id"] for event in events if event["id"] not in event_ids
        ],
        "unmatched_candidate_ids": [
            item["id"] for item in candidates if item["id"] not in candidate_ids
        ],
    }


def _contact_camera_context(video, annotations, run):
    """Validate known camera lineage without claiming missing legacy metadata.

    Cut ordinals name the first frame of a new view. A legacy artifact without
    a frozen context may still use explicit reviewed additions as conservative
    comparison barriers; it cannot certify that no other edit exists.
    """
    count = video["frame_count"]

    def cut(value):
        if type(value) is not int or not 0 < value < count:
            raise ValueError(
                "Camera cuts must be integer source frames inside the video"
            )
        return value

    context = run.get("court_context")
    if "court_context" in run:
        if not isinstance(context, dict):
            raise ValueError("Contact court context must be an object")
        left, right = context.get("start_frame"), context.get("end_frame")
        if (
            type(left) is not int
            or type(right) is not int
            or not 0 <= left <= run["start_frame"] < run["end_frame"] <= right <= count
        ):
            raise ValueError(
                "Contact court context must contain its run within the source"
            )
    cuts = set()
    known = False
    for owner in (run, context):
        if owner is None:
            continue
        for key in (
            "cut_frames",
            "raw_cut_frames",
            "known_preceding_cut_frames",
            "known_preceding_timestamp_gaps",
        ):
            if key not in owner:
                continue
            values = owner[key]
            if not isinstance(values, list):
                raise ValueError("Camera cut metadata must be a list of source frames")
            validated = [cut(value) for value in values]
            if key == "cut_frames":
                known = True
                cuts.update(validated)
        preceding = owner.get("preceding_reviewed_cut_frame")
        if preceding is not None:
            cut(preceding)
    corrections = annotations.get("camera_corrections", [])
    if not isinstance(corrections, list):
        raise ValueError("Reviewed camera corrections must be a list")
    for correction in corrections:
        if (
            not isinstance(correction, dict)
            or type(correction.get("is_cut")) is not bool
        ):
            raise ValueError(
                "Reviewed camera corrections need a source frame and boolean decision"
            )
        frame = cut(correction.get("frame"))
        if correction["is_cut"]:
            cuts.add(frame)
            known = True
        elif frame in cuts:
            raise ValueError("Camera review changed known cuts; rerun proposals")
    signature = run.get("camera_review_signature")
    if "camera_review_signature" in run:
        if not isinstance(signature, list):
            raise ValueError("Contact camera review signature must be a list")
        for item in signature:
            if (
                not isinstance(item, list)
                or len(item) != 2
                or type(item[1]) is not bool
            ):
                raise ValueError("Contact camera review signature is malformed")
            cut(item[0])
        if signature != camera_review_signature(
            annotations, run["start_frame"], run["end_frame"]
        ):
            raise ValueError("Camera review changed contact inputs; rerun proposals")
    if any(
        run.get(key) for key in ("requires_context_rerun", "requires_tracking_rerun")
    ):
        raise ValueError("Contact input context is stale; rerun proposals")
    try:
        reviewed = reviewed_contacts(run, annotations)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Contact camera/court context is malformed") from exc
    if reviewed["requires_context_rerun"]:
        raise ValueError(
            "Camera or court context changed contact inputs; rerun proposals"
        )
    return sorted(cuts), "available" if known else "unavailable", reviewed


def _contact_context_exclusion(item, ranges, cuts):
    """Require all possible contact/evidence frames in one reviewed camera view."""
    left, right = item["start_frame"], item["end_frame"] + 1
    if any(left < cut < right for cut in cuts):
        return "contact_interval_crosses_camera_cut"
    if not any(start <= left < right <= end for start, end in ranges):
        return "contact_interval_outside_reviewed_coverage"
    if "context_start_frame" in item:
        left, right = item["context_start_frame"], item["context_end_frame"]
        if any(left < cut < right for cut in cuts):
            return "evidence_context_crosses_camera_cut"
        if not any(start <= left < right <= end for start, end in ranges):
            return "evidence_context_outside_reviewed_coverage"
    return None


def evaluate_contacts(video, annotations, contact_run, tolerance_s=0.12):
    """Score contacts only inside fully covered, exhaustive live review windows.

    Marking a few proposed hits as reviewed is insufficient: a review window must
    explicitly declare ``contacts_complete`` after missed hits are also added.
    Replay/unknown windows and partially covered windows never contribute scores.
    Predicted annotation events and rally endings are never ground truth. A
    reviewed contact whose timing remains an interval invalidates its complete
    window until a reviewer adjudicates the contact frame.
    """
    if not math.isfinite(tolerance_s) or tolerance_s < 0:
        raise ValueError("Contact tolerance must be finite and nonnegative")
    result = _base(video, annotations, contact_run, "contacts")
    start, end = contact_run["start_frame"], contact_run["end_frame"]
    cuts, camera_metadata, reviewed = _contact_camera_context(
        video, annotations, contact_run
    )
    all_events = [
        event
        for event in annotations.get("events", [])
        if event["kind"] in ("serve", "shot")
        and event["status"] in ("reviewed", "corrected")
    ]
    uncertain_events = []
    for event in all_events:
        left, right = _frame_bounds(event, video["frame_count"], "contact_")
        if left < right:
            uncertain_events.append(event)
    all_candidates = [
        _validate_candidate(candidate, video, contact_run)
        for candidate in contact_run["candidates"]
    ]
    if len({item["id"] for item in all_candidates}) != len(all_candidates):
        raise ValueError("Contact candidate IDs must be unique")
    # The reviewed copy can add conservative evidence context for old artifacts.
    # Validate and consume that same view instead of losing its context metadata.
    all_candidates = [
        _validate_candidate(candidate, video, contact_run)
        for candidate in reviewed["candidates"]
    ]
    excluded_context_ids = [c["id"] for c in all_candidates if c["scene_excluded"]]
    usable, skipped = [], []
    for window in annotations.get("review_windows", []):
        if window["scene"] != "live":
            reason = "scene_is_not_live"
        elif any(
            r["scene"] != "live"
            and r["start_frame"] < window["end_frame"]
            and window["start_frame"] < r["end_frame"]
            for r in annotations.get("scene_ranges", [])
        ):
            reason = "reviewed_scene_excludes_window"
        elif not window["contacts_complete"]:
            reason = "contacts_not_exhaustively_reviewed"
        elif window["start_frame"] < start or window["end_frame"] > end:
            reason = "run_does_not_cover_entire_window"
        elif any(
            window["start_frame"] <= event["frame"] < window["end_frame"]
            for event in uncertain_events
        ):
            reason = "contact_timing_needs_adjudication"
        else:
            usable.append(window)
            continue
        skipped.append({"id": window["id"], "reason": reason})
    # Merge touching/overlapping coverage; do not match across unreviewed gaps.
    ranges = []
    for window in sorted(usable, key=lambda item: item["start_frame"]):
        left, right = window["start_frame"], window["end_frame"]
        if ranges and left <= ranges[-1][1]:
            ranges[-1][1] = max(ranges[-1][1], right)
        else:
            ranges.append([left, right])
    uninterrupted = []
    for start, end in ranges:
        bounds = [start, *[cut for cut in cuts if start < cut < end], end]
        uninterrupted.extend([left, right] for left, right in pairwise(bounds))
    ranges = uninterrupted

    def included(frame):
        return any(left <= frame < right for left, right in ranges)

    events = [event for event in all_events if included(event["frame"])]
    candidates, exclusions = [], []
    for item in all_candidates:
        reason = (
            "reviewed_scene_excludes_evidence"
            if item["scene_excluded"]
            else _contact_context_exclusion(item, ranges, cuts)
        )
        if reason:
            exclusions.append({"id": item["id"], "reason": reason})
        else:
            candidates.append(item)
    for item in events + candidates:
        if not math.isfinite(item["time_s"]) or item["time_s"] < 0:
            raise ValueError("Contact timestamps must be finite source times")
    result.update(
        stage="contacts",
        status="scored" if usable else "needs_complete_live_review",
        ground_truth="reviewed/corrected serve and shot events",
        prediction_timing={
            "strict_metrics": "Representative source times within tolerance; uncertain proposal times are navigation locations, not measured hit times",
            "uncertain_candidate_time_s": "Navigation frame only; review the entire possible-contact interval",
            "interval_bounds": "inclusive",
        },
        matching="maximum cardinality, then minimum total absolute source-time error",
        coverage={
            "usable_window_ids": [window["id"] for window in usable],
            "skipped_windows": skipped,
            "frame_ranges": ranges,
            "reviewed_frames": sum(right - left for left, right in ranges),
            "reviewed_contacts": len(events),
            "evaluated_candidates": len(candidates),
            "reviewed_event_ids": [item["id"] for item in events],
            "evaluated_candidate_ids": [item["id"] for item in candidates],
            "excluded_candidate_ids": [item["id"] for item in exclusions],
            "candidate_exclusions": exclusions,
            "camera_cut_frames": cuts,
            "camera_context_metadata": camera_metadata,
            "uncertain_candidate_count": sum(
                _uncertain_candidate(item) for item in candidates
            ),
            "excluded_reviewed_contacts": len(all_events) - len(events),
            "excluded_candidates": len(contact_run["candidates"]) - len(candidates),
            "scene_context_excluded_candidate_ids": excluded_context_ids,
        },
        tolerance_s=tolerance_s,
        metrics=None,
        tighter_tolerance=None,
        interval_coverage=None,
    )
    if usable:
        result.update(_contact_score(events, candidates, ranges, tolerance_s))
        result["interval_coverage"] = _interval_coverage(events, candidates, ranges)
        if tolerance_s > 0.04:
            result["tighter_tolerance"] = _contact_score(
                events, candidates, ranges, 0.04
            )
    return result


def evaluate_shuttle(video, annotations, shuttle_run, tolerance_diagonal=0.005):
    """Score explicitly labeled shuttle frames, not unlabeled tracking coverage.

    Human coordinates are normalized, model coordinates are source pixels. A
    visible prediction outside the localization tolerance counts as both a miss
    and a false detection. Missing output rows never count as true negatives.
    """
    if not math.isfinite(tolerance_diagonal) or not 0 < tolerance_diagonal <= 1:
        raise ValueError("Shuttle tolerance must be a finite fraction in (0, 1]")
    result = _base(video, annotations, shuttle_run, "shuttle")
    start, end = shuttle_run["start_frame"], shuttle_run["end_frame"]
    width, height = video["width"], video["height"]
    diagonal = math.hypot(width, height)
    points = [
        point
        for point in annotations.get("shuttle_points", [])
        if start <= point["frame"] < end
    ]
    rows = {}
    for row in shuttle_run["frames"]:
        if row["frame"] in rows:
            raise ValueError("Shuttle run contains duplicate source frames")
        rows[row["frame"]] = row["shuttle"]
    tp = fp = fn = tn = wrong = missing_visible = missing_invisible = 0
    visibility_tp = visibility_fp = visibility_fn = 0
    outcomes, errors = [], []
    for point in sorted(points, key=lambda point: point["frame"]):
        prediction = rows.get(point["frame"])
        predicted_visible = prediction is not None and prediction["visible"]
        outcome = {"frame": point["frame"], "visible": point["visible"]}
        if prediction is None:
            if point["visible"]:
                missing_visible += 1
            else:
                missing_invisible += 1
        if predicted_visible:
            coordinates = prediction["x"], prediction["y"]
            if any(value is None or not math.isfinite(value) for value in coordinates):
                raise ValueError(
                    "A visible shuttle prediction needs finite coordinates"
                )
        if point["visible"] and predicted_visible:
            visibility_tp += 1
            error = math.hypot(
                prediction["x"] - point["x"] * width,
                prediction["y"] - point["y"] * height,
            )
            errors.append(error)
            outcome.update(error_px=error, error_diagonal=error / diagonal)
            if error <= tolerance_diagonal * diagonal + 1e-9:
                tp += 1
                outcome["outcome"] = "correct_localization"
            else:
                fp += 1
                fn += 1
                wrong += 1
                outcome["outcome"] = "localization_error"
        elif point["visible"]:
            fn += 1
            visibility_fn += 1
            outcome["outcome"] = "missing_output" if prediction is None else "miss"
        elif predicted_visible:
            fp += 1
            visibility_fp += 1
            outcome["outcome"] = "false_detection"
        elif prediction is None:
            outcome["outcome"] = "missing_output"
        else:
            tn += 1
            outcome["outcome"] = "correct_absence"
        outcomes.append(outcome)
    result.update(
        stage="shuttle",
        status="scored" if points else "needs_shuttle_labels",
        tolerance_diagonal=tolerance_diagonal,
        tolerance_px=tolerance_diagonal * diagonal,
        coordinate_convention="human normalized x*width,y*height; predictions source pixels",
        wrong_localization_policy="one false detection plus one miss",
        coverage={
            "labeled_frames": len(points),
            "visible_labels": sum(point["visible"] for point in points),
            "invisible_labels": sum(not point["visible"] for point in points),
            "excluded_labeled_frames": len(annotations.get("shuttle_points", []))
            - len(points),
            "missing_output_frames": missing_visible + missing_invisible,
            "missing_visible_output_frames": missing_visible,
            "missing_invisible_output_frames": missing_invisible,
        },
        metrics=None,
        visibility_metrics=None,
        frames=outcomes,
    )
    if points:
        result.update(
            metrics=_metrics(tp, fp, fn)
            | {
                "true_negatives": tn,
                "wrong_localizations": wrong,
                "correct_frame_fraction": (tp + tn) / len(points),
            },
            visibility_metrics=_metrics(visibility_tp, visibility_fp, visibility_fn)
            | {"true_negatives": tn},
            mean_visible_pair_error_px=sum(errors) / len(errors) if errors else None,
        )
    return result
