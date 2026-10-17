"""Evaluate saved predictions against explicit human review coverage.

The pure functions take plain dictionaries (use ``annotations.model_dump()``).
Contact event ``time_s`` must already be normalized from source timestamps by the
Store; candidate times come from source-aligned inference. No FPS conversion is
used. Review windows and run ranges use half-open source frame intervals.
"""

import math


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


def evaluate_contacts(video, annotations, contact_run, tolerance_s=0.12):
    """Score contacts only inside fully covered, exhaustive live review windows.

    Marking a few proposed hits as reviewed is insufficient: a review window must
    explicitly declare ``contacts_complete`` after missed hits are also added.
    Replay/unknown windows and partially covered windows never contribute scores.
    Predicted annotation events and rally endings are never ground truth.
    """
    if not math.isfinite(tolerance_s) or tolerance_s < 0:
        raise ValueError("Contact tolerance must be finite and nonnegative")
    result = _base(video, annotations, contact_run, "contacts")
    start, end = contact_run["start_frame"], contact_run["end_frame"]
    usable, skipped = [], []
    for window in annotations.get("review_windows", []):
        if window["scene"] != "live":
            reason = "scene_is_not_live"
        elif not window["contacts_complete"]:
            reason = "contacts_not_exhaustively_reviewed"
        elif window["start_frame"] < start or window["end_frame"] > end:
            reason = "run_does_not_cover_entire_window"
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

    def included(frame):
        return any(left <= frame < right for left, right in ranges)

    all_events = [
        event
        for event in annotations.get("events", [])
        if event["kind"] in ("serve", "shot")
        and event["status"] in ("reviewed", "corrected")
    ]
    events = [event for event in all_events if included(event["frame"])]
    candidates = [item for item in contact_run["candidates"] if included(item["frame"])]
    for item in events + candidates:
        if not math.isfinite(item["time_s"]) or item["time_s"] < 0:
            raise ValueError("Contact timestamps must be finite source times")
    result.update(
        stage="contacts",
        status="scored" if usable else "needs_complete_live_review",
        ground_truth="reviewed/corrected serve and shot events",
        matching="maximum cardinality, then minimum total absolute source-time error",
        coverage={
            "usable_window_ids": [window["id"] for window in usable],
            "skipped_windows": skipped,
            "frame_ranges": ranges,
            "reviewed_frames": sum(right - left for left, right in ranges),
            "reviewed_contacts": len(events),
            "evaluated_candidates": len(candidates),
            "excluded_reviewed_contacts": len(all_events) - len(events),
            "excluded_candidates": len(contact_run["candidates"]) - len(candidates),
        },
        tolerance_s=tolerance_s,
        metrics=None,
        tighter_tolerance=None,
    )
    if usable:
        result.update(_contact_score(events, candidates, ranges, tolerance_s))
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
