"""Score saved boundary proposals only against explicitly reviewed coverage.

Frames and uncertainty bounds retain native source identity. Representative-time
scores and possible interval compatibility are deliberately separate: neither
an interval overlap nor a proposal's navigation frame proves a physical ending.
This module performs no inference and never changes its inputs.
"""

import itertools
import math
from collections import deque

from .evaluation import _contact_score, _frame_bounds
from .rallies import MAX_FRAME_STEP_S, reviewed_rallies

KINDS = {"serve": "serves_complete", "rally_end": "rally_ends_complete"}
TIME_EPSILON_S = 0.00002


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative source time")
    return value


def _records(value, name):
    if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
        raise ValueError(f"{name} must contain objects")
    return value


def _identifiers(records, name):
    ids = [v.get("id") for v in records]
    if any(not isinstance(v, str) or not v for v in ids) or len(set(ids)) != len(ids):
        raise ValueError(f"{name} IDs must be nonempty and unique")


def _range(item, count, name):
    left = _integer(item.get("start_frame"), f"{name} start")
    right = _integer(item.get("end_frame"), f"{name} end", 1)
    if not left < right <= count:
        raise ValueError(f"{name} must be a half-open native source range")
    return left, right


def _source_clock(video, times):
    count = _integer(video.get("frame_count"), "Source frame count", 1)
    if not isinstance(times, (list, tuple)) or len(times) != count:
        raise ValueError("Native source timestamps must cover every source frame")
    for value in times:
        _number(value, "Native source timestamp")
    if any(a >= b for a, b in itertools.pairwise(times)):
        raise ValueError("Native source timestamps must be strictly increasing")
    return count


def _time_matches(value, expected, name):
    if abs(_number(value, name) - expected) > TIME_EPSILON_S:
        raise ValueError(f"{name} does not match its native source frame")


def _boundary(item, count, times, *, reference=False):
    kind = item.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("Boundary kind must be serve or rally_end")
    prefix = ("contact_" if kind == "serve" else "terminal_") if reference else ""
    if reference:
        other = "terminal_" if kind == "serve" else "contact_"
        if any(
            item.get(other + key) is not None for key in ("start_frame", "end_frame")
        ):
            raise ValueError("Boundary reference carries the wrong uncertainty kind")
    try:
        left, right = _frame_bounds(item, count, prefix)
    except (KeyError, TypeError) as exc:
        raise ValueError("Boundary needs valid inclusive native frame bounds") from exc
    frame = item["frame"]
    if not reference or "time_s" in item:
        _time_matches(item.get("time_s"), times[frame], "Boundary representative time")
    if not reference:
        has_start = item.get("start_time_s") is not None
        has_end = item.get("end_time_s") is not None
        if has_start != has_end:
            raise ValueError("Boundary interval times must be paired")
        if has_start:
            _time_matches(item["start_time_s"], times[left], "Boundary start time")
            _time_matches(item["end_time_s"], times[right], "Boundary end time")
    return item | {"start_frame": left, "end_frame": right, "time_s": times[frame]}


def _validate_context(video, annotations, run, count):
    if run.get("stage") != "rallies" or run.get("video_id") != video.get("id"):
        raise ValueError("Expected a rallies run for this video")
    if not video.get("sha256") or run.get("video_sha256") != video["sha256"]:
        raise ValueError("Boundary run source hash must match this video")
    start, end = _range(run, count, "Boundary run")
    context = {
        "start_frame": run.get("context_start_frame"),
        "end_frame": run.get("context_end_frame"),
    }
    left, right = _range(context, count, "Boundary input context")
    if not left <= start < end <= right:
        raise ValueError("Boundary input context must contain its run")
    if run.get("source_timestamps_validated") is not True:
        raise ValueError("Boundary run needs validated native source timestamps")
    if "court_context" in run and not isinstance(run["court_context"], dict):
        raise ValueError("Boundary court context must be an object")
    if "court_context" in run:
        court_left, court_right = _range(
            run["court_context"], count, "Boundary court context"
        )
        if not left <= court_left <= start < end <= court_right <= right:
            raise ValueError(
                "Boundary court context must contain its run within the input context"
            )
    if any(
        run.get(key) for key in ("requires_proposal_rerun", "requires_tracking_rerun")
    ):
        raise ValueError("Boundary proposal context is stale; rerun proposals")
    try:
        stale = reviewed_rallies(run, annotations)["requires_proposal_rerun"]
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(
            "Boundary run has incomplete camera/scene/court context"
        ) from exc
    if stale:
        raise ValueError(
            "Boundary camera, scene or court context changed; rerun proposals"
        )
    return start, end


def _coverage_records(annotations, count):
    windows = _records(annotations.get("review_windows", []), "Reviewed windows")
    _identifiers(windows, "Reviewed window")
    for window in windows:
        _range(window, count, "Reviewed window")
    previous = 0
    for window in sorted(windows, key=lambda row: row["start_frame"]):
        left, right = _range(window, count, "Reviewed window")
        if left < previous:
            raise ValueError("Reviewed windows must not overlap")
        previous = right
        if window.get("scene", "unknown") not in ("live", "replay", "unknown"):
            raise ValueError("Invalid reviewed-window scene")
        for flag in KINDS.values():
            if type(window.get(flag, False)) is not bool:
                raise ValueError("Boundary review completeness must be boolean")
    scenes = _records(annotations.get("scene_ranges", []), "Reviewed scenes")
    for scene in scenes:
        _range(scene, count, "Reviewed scene")
        if scene.get("scene") not in ("live", "replay", "non_play", "unknown"):
            raise ValueError("Invalid reviewed scene")
    return windows, scenes


def _discontinuities(run, annotations, times, count):
    court = run.get("court_context", {})
    if not isinstance(court, dict):
        raise ValueError("Boundary court context must be an object")
    cuts = set()
    for owner in (run, court):
        values = owner.get("cut_frames", [])
        if not isinstance(values, list):
            raise ValueError("Boundary camera cuts must be native frame ordinals")
        for value in values:
            _integer(value, "Camera cut", 1)
            if value >= count:
                raise ValueError("Camera cut exceeds source video")
            cuts.add(value)
    for correction in _records(
        annotations.get("camera_corrections", []), "Camera corrections"
    ):
        frame = _integer(correction.get("frame"), "Camera correction", 1)
        if frame >= count or type(correction.get("is_cut")) is not bool:
            raise ValueError("Invalid source camera correction")
        if correction["is_cut"]:
            cuts.add(frame)
    gaps = {
        i for i in range(1, count) if times[i] - times[i - 1] > MAX_FRAME_STEP_S + 1e-9
    }
    return sorted(cuts | gaps), sorted(gaps)


def _split(left, right, discontinuities):
    bounds = [left, *[c for c in discontinuities if left < c < right], right]
    return [[a, b] for a, b in itertools.pairwise(bounds)]


def _contained(item, ranges):
    return any(a <= item["start_frame"] <= item["end_frame"] < b for a, b in ranges)


def _interval_pairs(events, candidates):
    """Deterministic augmenting paths give general maximum-cardinality matching.

    Interval lengths can vary independently, so a greedy local choice may steal
    another reference's only compatible proposal. No timing truth is inferred.
    """
    events = sorted(events, key=lambda item: (item["frame"], item["id"]))
    candidates = sorted(
        candidates,
        key=lambda item: (item["end_frame"], item["start_frame"], item["id"]),
    )
    edges = [
        [
            j
            for j, candidate in enumerate(candidates)
            if max(event["start_frame"], candidate["start_frame"])
            <= min(event["end_frame"], candidate["end_frame"])
        ]
        for event in events
    ]
    event_match, candidate_match = {}, {}
    for root in range(len(events)):
        queue, seen, parents = deque([root]), {root}, {}
        free = None
        while queue and free is None:
            event = queue.popleft()
            for candidate in edges[event]:
                if candidate in parents:
                    continue
                parents[candidate] = event
                if candidate not in candidate_match:
                    free = candidate
                    break
                other = candidate_match[candidate]
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
        while free is not None:
            event = parents[free]
            previous = event_match.get(event)
            event_match[event] = free
            candidate_match[free] = event
            free = previous
    return [(events[i], candidates[j]) for i, j in sorted(event_match.items())]


def _compatibility(events, candidates, ranges):
    pairs = []
    for a, b in ranges:
        pairs.extend(
            _interval_pairs(
                [e for e in events if a <= e["frame"] < b],
                [c for c in candidates if a <= c["frame"] < b],
            )
        )
    matches = [
        {
            "event_id": e["id"],
            "candidate_id": c["id"],
            "event_start_frame": e["start_frame"],
            "event_end_frame": e["end_frame"],
            "candidate_start_frame": c["start_frame"],
            "candidate_end_frame": c["end_frame"],
            "event_interval_frames": e["end_frame"] - e["start_frame"] + 1,
            "candidate_interval_frames": c["end_frame"] - c["start_frame"] + 1,
            "overlap_start_frame": max(e["start_frame"], c["start_frame"]),
            "overlap_end_frame": min(e["end_frame"], c["end_frame"]),
        }
        for e, c in pairs
    ]
    matched_events = {e["id"] for e, _ in pairs}
    matched_candidates = {c["id"] for _, c in pairs}
    return {
        "meaning": "Possible inclusive-interval temporal compatibility only; not exact boundary timing or accuracy",
        "matching": "maximum-cardinality one-to-one inclusive interval overlap within uninterrupted reviewed coverage",
        "reviewed_event_count": len(events),
        "candidate_count": len(candidates),
        "matched_count": len(matches),
        "matches": matches,
        "unmatched_event_ids": [
            e["id"] for e in events if e["id"] not in matched_events
        ],
        "unmatched_candidate_ids": [
            c["id"] for c in candidates if c["id"] not in matched_candidates
        ],
    }


def _kind_report(kind, flag, events, candidates, windows, scenes, run_range, cuts):
    relevant = [e for e in events if e["kind"] == kind]
    references = [e for e in relevant if e.get("status") in ("reviewed", "corrected")]
    predictions = [c for c in candidates if c["kind"] == kind]
    usable, skipped, ranges, exact_ranges, exact_skipped = [], [], [], [], []
    start, end = run_range
    for window in windows:
        left, right = window["start_frame"], window["end_frame"]
        pieces = _split(left, right, cuts)
        overlapping = [
            e for e in references if e["start_frame"] < right and left <= e["end_frame"]
        ]
        reason = None
        if window.get("scene", "unknown") != "live":
            reason = "scene_is_not_live"
        elif not window.get(flag, False):
            reason = f"{kind}_not_exhaustively_reviewed"
        elif left < start or right > end:
            reason = "run_does_not_cover_entire_window"
        elif any(
            r["scene"] != "live" and r["start_frame"] < right and left < r["end_frame"]
            for r in scenes
        ):
            reason = "reviewed_scene_excludes_window"
        elif any(not _contained(e, pieces) for e in overlapping):
            reason = "reference_interval_crosses_coverage_or_context"
        if reason:
            skipped.append({"id": window["id"], "reason": reason})
            continue
        usable.append(window["id"])
        ranges.extend(pieces)
        if any(e["start_frame"] < e["end_frame"] for e in overlapping):
            exact_skipped.append(
                {"id": window["id"], "reason": "boundary_timing_needs_adjudication"}
            )
        else:
            exact_ranges.extend(pieces)
    included_events = [e for e in references if _contained(e, ranges)]
    included_candidates = [c for c in predictions if _contained(c, ranges)]
    exact_events = [e for e in included_events if _contained(e, exact_ranges)]
    exact_candidates = [c for c in included_candidates if _contained(c, exact_ranges)]
    event_ids, candidate_ids = (
        {e["id"] for e in included_events},
        {c["id"] for c in included_candidates},
    )
    return {
        "status": "scored"
        if exact_ranges
        else "needs_exact_boundary_timing"
        if ranges
        else "needs_complete_live_review",
        "coverage": {
            "usable_window_ids": usable,
            "skipped_windows": skipped,
            "frame_ranges": ranges,
            "reviewed_frames": sum(b - a for a, b in ranges),
            "reviewed_events": len(included_events),
            "evaluated_candidates": len(included_candidates),
            "excluded_event_ids": [
                e["id"] for e in relevant if e["id"] not in event_ids
            ],
            "excluded_candidate_ids": [
                c["id"] for c in predictions if c["id"] not in candidate_ids
            ],
            "uncertain_reference_event_ids": [
                e["id"] for e in included_events if e["start_frame"] < e["end_frame"]
            ],
            "uncertain_candidate_ids": [
                c["id"]
                for c in included_candidates
                if c["start_frame"] < c["end_frame"]
                or c.get("timing") == "uncertain_interval"
            ],
            "point_timing_skipped_windows": exact_skipped,
            "point_timing_frame_ranges": exact_ranges,
            "point_timing_event_count": len(exact_events),
            "point_timing_candidate_count": len(exact_candidates),
        },
        "representative_timing": None,
        "interval_compatibility": _compatibility(
            included_events, included_candidates, ranges
        )
        if ranges
        else None,
        "_exact_inputs": (exact_events, exact_candidates, exact_ranges),
    }


def evaluate_rallies(video, annotations, run, source_times, tolerance_s=0.12):
    """Evaluate saved serve/end proposals without assuming complete references.

    Completeness is declared independently for each boundary kind. Uncertain
    references retain interval support while their complete window is excluded
    from point-timing scores. Reported source labels are supplied references,
    not independently certified expert truth.
    """
    if any(not isinstance(item, dict) for item in (video, annotations, run)):
        raise ValueError("Video, annotations and boundary run must be objects")
    tolerance_s = _number(tolerance_s, "Boundary tolerance")
    count = _source_clock(video, source_times)
    revision = _integer(annotations.get("revision"), "Annotation revision")
    windows, scenes = _coverage_records(annotations, count)
    cuts, gaps = _discontinuities(run, annotations, source_times, count)
    run_range = _validate_context(video, annotations, run, count)
    raw_events = _records(annotations.get("events", []), "Annotation events")
    _identifiers(raw_events, "Annotation event")
    events = []
    for item in raw_events:
        kind = item.get("kind")
        if not isinstance(kind, str):
            raise ValueError("Annotation event kind must be a string")
        if kind not in KINDS:
            continue
        if item.get("status") not in ("predicted", "reviewed", "corrected"):
            raise ValueError("Boundary reference status is invalid")
        events.append(_boundary(item, count, source_times, reference=True))
    raw_candidates = _records(run.get("candidates"), "Boundary candidates")
    _identifiers(raw_candidates, "Boundary candidate")
    candidates = [_boundary(item, count, source_times) for item in raw_candidates]
    if any(
        not run_range[0] <= c["start_frame"] <= c["end_frame"] < run_range[1]
        for c in candidates
    ):
        raise ValueError("Boundary candidate interval must lie inside its run")
    for candidate in candidates:
        if "context_start_frame" in candidate or "context_end_frame" in candidate:
            left, right = _range(
                {
                    "start_frame": candidate.get("context_start_frame"),
                    "end_frame": candidate.get("context_end_frame"),
                },
                count,
                "Boundary candidate evidence context",
            )
            if not (
                run_range[0]
                <= left
                <= candidate["start_frame"]
                <= candidate["end_frame"]
                < right
                <= run_range[1]
            ):
                raise ValueError(
                    "Boundary candidate evidence context must contain its interval within its run"
                )
    kinds = {}
    for kind, flag in KINDS.items():
        report = _kind_report(
            kind, flag, events, candidates, windows, scenes, run_range, cuts
        )
        exact_events, exact_candidates, exact_ranges = report.pop("_exact_inputs")
        if exact_ranges:
            report["representative_timing"] = _contact_score(
                exact_events, exact_candidates, exact_ranges, tolerance_s
            ) | {
                "meaning": "Representative proposal navigation times against exact reviewed source frames; uncertain proposal times are not measured physical boundaries",
            }
        kinds[kind] = report
    return {
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "annotation_revision": revision,
        "run_id": run.get("run_id"),
        "stage": "rallies",
        "run_start_frame": run_range[0],
        "run_end_frame": run_range[1],
        "source_timestamps_validated": True,
        "tolerance_s": tolerance_s,
        "interval_bounds": "inclusive",
        "source_context_discontinuities": cuts,
        "source_timestamp_gap_frames": gaps,
        "max_source_frame_step_s": MAX_FRAME_STEP_S,
        "ground_truth": "Supplied reviewed/corrected boundary references with separately explicit complete live coverage; reference quality is not independently certified",
        "kinds": kinds,
    }
