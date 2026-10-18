"""Run-local automatic courts with current manual geometry taking precedence."""

from copy import deepcopy

from .schemas import Calibration


def _plain(item):
    return item.model_dump() if hasattr(item, "model_dump") else item


def court_signature(annotations, start, end):
    return sorted(
        [c["start_frame"], c["end_frame"], [[p["x"], p["y"]] for p in c["corners"]]]
        for item in _plain(annotations).get("calibrations", [])
        if (c := _plain(item))["start_frame"] < end and start < c["end_frame"]
    )


def uncovered_ranges(start, end, blocked):
    """Subtract half-open intervals, preserving every remaining source frame."""
    cursor = start
    result = []
    for left, right in sorted(blocked):
        if right <= cursor or left >= end:
            continue
        if left > cursor:
            result.append((cursor, min(left, end)))
        cursor = max(cursor, right)
    if cursor < end:
        result.append((cursor, end))
    return result


def effective_annotations(annotations, run):
    """Return a copy; automatic geometry never becomes a reviewed annotation.

    Validate persisted derived intervals against their original camera context.
    Current edits are handled by stale-run checks, rather than extending an old
    automatic fit into a newly merged or split view.
    """
    doc = deepcopy(_plain(annotations))
    manual = [_plain(c) for c in doc.get("calibrations", [])]
    if run.get("court_context_version") == 1:
        cuts = set(run.get("cut_frames", []))
        preceding = run.get("preceding_reviewed_cut_frame")
        if preceding is not None:
            cuts.add(preceding)
        manual = [
            {
                **c,
                "end_frame": min(
                    [
                        c["end_frame"],
                        *[
                            cut
                            for cut in cuts
                            if c["start_frame"] < cut < c["end_frame"]
                        ],
                    ]
                ),
            }
            for c in manual
        ]
    automatic = [
        Calibration.model_validate(c).model_dump()
        for c in run.get("automatic_calibrations", [])
    ]
    automatic.sort(key=lambda c: c["start_frame"])
    previous_end = run["start_frame"]
    for calibration in automatic:
        start, end = calibration["start_frame"], calibration["end_frame"]
        if (
            start < previous_end
            or end > run["end_frame"]
            or any(start < cut < end for cut in run.get("cut_frames", []))
            or start < (run.get("preceding_reviewed_cut_frame") or 0)
        ):
            raise ValueError(
                "Automatic calibration exceeds its original camera context"
            )
        previous_end = end
    blocked = [(c["start_frame"], c["end_frame"]) for c in manual]
    derived = [
        {**calibration, "start_frame": start, "end_frame": end}
        for calibration in automatic
        for start, end in uncovered_ranges(
            calibration["start_frame"], calibration["end_frame"], blocked
        )
    ]
    doc["calibrations"] = sorted(manual + derived, key=lambda c: c["start_frame"])
    return doc


def court_run_context(run):
    return deepcopy(
        {
            key: run[key]
            for key in (
                "start_frame",
                "end_frame",
                "cut_frames",
                "raw_cut_frames",
                "applied_camera_corrections",
                "preceding_reviewed_cut_frame",
                "known_preceding_cut_frames",
                "known_preceding_timestamp_gaps",
                "automatic_calibrations",
                "court_context_version",
            )
            if key in run
        }
    )


def court_context_changed(annotations, artifact):
    context = artifact.get("court_context")
    return context is not None and artifact.get(
        "calibration_signature"
    ) != court_signature(
        effective_annotations(annotations, context),
        context["start_frame"],
        context["end_frame"],
    )
