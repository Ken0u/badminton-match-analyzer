"""Apply reviewed identities to tracker IDs within explicit source-frame ranges.

Tracker IDs belong to one run, not to a person. An assignment is valid only for
its reviewed half-open range; identity is never inferred outside that range.
"""

from collections import defaultdict
from copy import deepcopy
from itertools import pairwise


def validate_assignments(assignments, *, player_ids=None, frame_count=None):
    """Return plain assignment records, rejecting ambiguous identity mappings.

    Accept dictionaries or Pydantic models. The optional roster and frame count
    let callers validate references at the annotation boundary. Overlap is
    checked separately within each run, since different runs may track the same
    source frames with different tracker IDs.
    """
    records = []
    for assignment in assignments:
        item = (
            assignment.model_dump()
            if hasattr(assignment, "model_dump")
            else dict(assignment)
        )
        try:
            run_id, track_id, start, end, player_id = (
                item[key]
                for key in (
                    "run_id",
                    "track_id",
                    "start_frame",
                    "end_frame",
                    "player_id",
                )
            )
        except KeyError as exc:
            raise ValueError(f"Track assignment missing {exc.args[0]}") from exc
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("Track assignments require a run ID")
        if not isinstance(player_id, str) or not player_id:
            raise ValueError("Track assignments require a player ID")
        if type(track_id) is not int or track_id < 0:
            raise ValueError("Track assignments require a nonnegative tracker ID")
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ValueError("Track assignment end must follow its nonnegative start")
        if player_ids is not None and player_id not in player_ids:
            raise ValueError("Unknown player ID in track assignment")
        if frame_count is not None and end > frame_count:
            raise ValueError("Track assignment exceeds the source video")
        records.append(
            {
                "run_id": run_id,
                "track_id": track_id,
                "start_frame": start,
                "end_frame": end,
                "player_id": player_id,
            }
        )

    for field, message in (
        ("track_id", "Track assignment ranges must not overlap for one tracker"),
        ("player_id", "One player cannot be assigned to overlapping tracks"),
    ):
        groups = defaultdict(list)
        for item in records:
            groups[(item["run_id"], item[field])].append(item)
        for items in groups.values():
            ordered = sorted(items, key=lambda item: item["start_frame"])
            if any(
                left["end_frame"] > right["start_frame"]
                for left, right in pairwise(ordered)
            ):
                raise ValueError(message)
    return records


def _resolve(frame, track_id, assignments, run_id):
    if track_id is None:
        return None
    return next(
        (
            assignment["player_id"]
            for assignment in assignments
            if assignment["run_id"] == run_id
            and assignment["track_id"] == track_id
            and assignment["start_frame"] <= frame < assignment["end_frame"]
        ),
        None,
    )


def resolve_contact_player(frame, track_id, assignments, run_id):
    """Resolve a contact's hinted tracker only from a reviewed exact-range map."""
    records = validate_assignments(assignments)
    return _resolve(frame, track_id, records, run_id)


def apply_assignments(player_run, assignments, run_id):
    """Copy a raw player run and fill only identities covered by reviewed maps.

    Unmatched identities are explicitly cleared, so an old applied view cannot
    leak labels after an assignment has been removed or its range shortened.
    Boxes, keypoints, and the original on-disk run remain unchanged.
    """
    records = validate_assignments(assignments)
    result = deepcopy(player_run)
    for row in result["frames"]:
        for player in row["players"]:
            player["player_id"] = _resolve(
                row["frame"], player.get("track_id"), records, run_id
            )
    return result
