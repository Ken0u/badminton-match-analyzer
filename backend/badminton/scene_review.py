"""Apply explicit scene review to copies; raw model outputs remain immutable."""

from copy import deepcopy


def plain(item):
    return item.model_dump() if hasattr(item, "model_dump") else item


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
    for correction in corrections:
        frame = correction["frame"]
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
        preceding_reviewed_cut_frame=max(
            (c["frame"] for c in corrections if c["is_cut"] and c["frame"] < start),
            default=None,
        ),
    )
    return result


def reviewed_run(run, annotations):
    """Current scene view of a perception run, with stale cut handling explicit."""
    doc = plain(annotations)
    start, end = run["start_frame"], run["end_frame"]
    result = corrected_boundaries(run, doc, start, end)
    result["requires_tracking_rerun"] = (
        run.get("requires_tracking_rerun", False)
        or result["cut_frames"] != sorted(run.get("cut_frames", []))
        or result["preceding_reviewed_cut_frame"]
        != run.get("preceding_reviewed_cut_frame")
    )
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
    result["scene_annotation_revision"] = doc.get("revision", 0)
    return result


def reviewed_contacts(run, annotations):
    result = deepcopy(run)
    for candidate in result.get("candidates", []):
        blocked = excluded_scene(
            annotations,
            candidate.get("start_frame", candidate["frame"]),
            candidate.get("end_frame", candidate["frame"]) + 1,
        )
        candidate["scene_excluded"] = blocked is not None
        candidate["scene_exclusion_reason"] = (
            f"Reviewed {blocked['scene']} range {blocked['id']}" if blocked else None
        )
    result["scene_annotation_revision"] = plain(annotations).get("revision", 0)
    return result


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
