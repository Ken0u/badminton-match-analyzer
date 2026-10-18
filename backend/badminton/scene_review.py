"""Apply explicit scene review to copies; raw model outputs remain immutable."""

from copy import deepcopy

from .calibration_context import (
    court_context_changed,
    court_signature,
    effective_annotations,
)


def plain(item):
    return item.model_dump() if hasattr(item, "model_dump") else item


def scene_review_signature(annotations, start, end):
    return sorted(
        [r["start_frame"], r["end_frame"], r["scene"]]
        for item in plain(annotations).get("scene_ranges", [])
        if (r := plain(item))["start_frame"] < end and start < r["end_frame"]
    )


def excluded_scene(annotations, start, end):
    """Return a blocking reviewed range overlapping the half-open context.

    Unlabeled footage can still generate review proposals. An explicitly unknown
    scene is held for review, like a replay/non-play range; it is not live truth.
    """
    doc = plain(annotations)
    return next(
        (
            r
            for item in doc.get("scene_ranges", [])
            if (r := plain(item))["scene"] != "live"
            and r["start_frame"] < end
            and start < r["end_frame"]
        ),
        None,
    )


def corrected_boundaries(raw, annotations, start, end):
    from .segments import camera_ranges

    doc = plain(annotations)
    result = deepcopy(raw)
    original = set(raw.get("raw_cut_frames", raw.get("cut_frames", [])))
    cuts = original.copy()
    physical_gaps = {
        b["frame"]
        for b in raw.get("boundaries", [])
        if b.get("reason") == "timestamp_discontinuity"
    }
    corrections = [plain(item) for item in doc.get("camera_corrections", [])]
    preceding = set(raw.get("known_preceding_cut_frames", []))
    previous_gaps = set(raw.get("known_preceding_timestamp_gaps", []))
    for correction in corrections:
        frame = correction["frame"]
        if frame < start:
            if correction["is_cut"]:
                preceding.add(frame)
            elif frame not in previous_gaps:
                preceding.discard(frame)
        if not start <= frame < end:
            continue
        if correction["is_cut"]:
            cuts.add(frame)
        elif frame not in physical_gaps:
            cuts.discard(frame)
    result.update(
        raw_cut_frames=sorted(original),
        cut_frames=sorted(cuts),
        camera_ranges=camera_ranges(start, end, cuts),
        camera_annotation_revision=doc.get("revision", 0),
        applied_camera_corrections=[
            c for c in corrections if start <= c["frame"] < end
        ],
        preceding_reviewed_cut_frame=max(preceding, default=None),
    )
    return result


def reviewed_run(run, annotations):
    """Current scene view of a perception run, with stale cut handling explicit."""
    doc = plain(annotations)
    start, end = run["start_frame"], run["end_frame"]
    result = corrected_boundaries(run, doc, start, end)
    result["requires_court_tracking_rerun"] = (
        run.get("stage") == "players"
        and "calibration_signature" in run
        and run["calibration_signature"]
        != court_signature(effective_annotations(doc, run), start, end)
    )
    result["requires_tracking_rerun"] = (
        run.get("requires_tracking_rerun", False)
        or result["requires_court_tracking_rerun"]
        or result["cut_frames"] != sorted(run.get("cut_frames", []))
        or result["preceding_reviewed_cut_frame"]
        != run.get("preceding_reviewed_cut_frame")
    )
    continuity = result.get("track_continuity", {})
    result["requires_continuity_rerun"] = bool(continuity.get("links")) and (
        result["requires_tracking_rerun"]
        or continuity.get("scene_signature") != scene_review_signature(doc, start, end)
    )
    if result["requires_continuity_rerun"]:
        result["requires_tracking_rerun"] = True
        continuity.update(status="stale_context", requires_rerun=True)
        for row in result.get("frames", []):
            for person in row.get("players", []):
                person["track_id"] = person.get("baseline_track_id", person["track_id"])
                person["player_id"] = None
    ranges = sorted(
        (plain(r) for r in doc.get("scene_ranges", [])), key=lambda r: r["start_frame"]
    )
    position = 0
    for row in result.get("frames", []):
        if "reviewed_scene_range_id" in row:
            row.pop("scene", None)
            row.pop("reviewed_scene_range_id", None)
            original_scene = row.pop("scene_before_review", None)
            if original_scene is not None:
                row["scene"] = original_scene
        while position < len(ranges) and ranges[position]["end_frame"] <= row["frame"]:
            position += 1
        if (
            position < len(ranges)
            and ranges[position]["start_frame"]
            <= row["frame"]
            < ranges[position]["end_frame"]
        ):
            row["scene_before_review"] = row.get("scene")
            row["scene"] = ranges[position]["scene"]
            row["reviewed_scene_range_id"] = ranges[position]["id"]
        point = row.get("shuttle", {})
        if "selection_context_start_frame" in point:
            left, right = (
                point["selection_context_start_frame"],
                point.get("selection_context_end_frame"),
            )
            valid = (
                type(left) is int
                and type(right) is int
                and start <= left <= row["frame"] < right <= end
            )
            point["selection_context_excluded"] = (
                not valid
                or excluded_scene(doc, left, right) is not None
                or any(left < cut < right for cut in result["cut_frames"])
            )
    result["scene_annotation_revision"] = doc.get("revision", 0)
    return result


def reviewed_contacts(run, annotations):
    result = deepcopy(run)
    result["requires_context_rerun"] = court_context_changed(
        annotations, run
    ) or camera_context_changed(annotations, run.get("court_context"))
    for candidate in result.get("candidates", []):
        if "context_start_frame" not in candidate and candidate.get(
            "evidence_source"
        ) in ("observed_trajectory", "short_gap_trajectory_and_pose"):
            pad = 3 if candidate["evidence_source"] == "observed_trajectory" else 2
            candidate["context_start_frame"] = max(
                result.get("start_frame", 0),
                candidate.get("start_frame", candidate["frame"]) - pad,
            )
            candidate["context_end_frame"] = min(
                result.get("end_frame", candidate["frame"] + pad + 1),
                candidate.get("end_frame", candidate["frame"]) + pad + 1,
            )
            candidate["context_provenance"] = "conservative_legacy_window"
        blocked = excluded_scene(
            annotations,
            candidate.get(
                "context_start_frame", candidate.get("start_frame", candidate["frame"])
            ),
            candidate.get(
                "context_end_frame", candidate.get("end_frame", candidate["frame"]) + 1
            ),
        )
        candidate["scene_excluded"] = blocked is not None
        candidate["scene_exclusion_reason"] = (
            f"Reviewed {blocked['scene']} range {blocked['id']}" if blocked else None
        )
    result["scene_annotation_revision"] = plain(annotations).get("revision", 0)
    return result


def camera_context_changed(annotations, context):
    if context is None:
        return False
    current = corrected_boundaries(
        context, annotations, context["start_frame"], context["end_frame"]
    )
    return current["cut_frames"] != sorted(context.get("cut_frames", [])) or current[
        "preceding_reviewed_cut_frame"
    ] != context.get("preceding_reviewed_cut_frame")


def camera_review_signature(annotations, start, end):
    return sorted(
        [
            [c["frame"], c["is_cut"]]
            for item in plain(annotations).get("camera_corrections", [])
            if (
                (c := plain(item))["frame"] < end
                and (c["frame"] >= start or c["is_cut"])
            )
        ]
    )
