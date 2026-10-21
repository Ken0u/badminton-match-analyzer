"""Pure, bounded scoring of a frozen sparse player development audit.

Source-only automated assessments remain separate from unchanged predictions.
These measurements neither interpolate between samples nor establish full-run
identity accuracy, human gold labels, model ranking or deployment fitness.
Raw-file hashes must be checked by the caller before supplying parsed documents.
"""

import itertools
import math
import re
from pathlib import PurePosixPath

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_EXCLUDED = {"replay", "non_play", "unknown"}
_MAX_PERSONS = 128
_MAX_LOCALIZABLE = 8
_MAX_FRAMES = 251


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _document(value, name):
    _require(isinstance(value, dict), f"{name} must be an object")
    return value


def _list(value, name):
    _require(isinstance(value, list), f"{name} must be an array")
    return value


def _integer(value, name, minimum=0):
    _require(type(value) is int and value >= minimum, f"Invalid {name}")
    return value


def _finite(value, name):
    _require(type(value) in (int, float) and math.isfinite(value), f"Nonfinite {name}")
    return value


def _hash(value, name):
    _require(isinstance(value, str) and bool(_HASH.fullmatch(value)), f"Invalid {name}")
    return value


def _label(value, name, nullable=False):
    if value is None and nullable:
        return value
    _require(
        isinstance(value, str) and bool(value.strip()) and len(value) <= 256,
        f"Invalid {name}",
    )
    return value


def _box(box, width, height):
    _require(isinstance(box, list) and len(box) == 4, "Box must contain four values")
    for value in box:
        _finite(value, "box coordinate")
    _require(
        0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height,
        "Box must be strictly ordered and within native image bounds",
    )


def validate_manifest(manifest):
    """Validate the frozen protocol; generated fixtures may use fewer samples."""
    m = _document(manifest, "Manifest")
    _require(
        type(m.get("schema_version")) is int and m["schema_version"] == 1,
        "Manifest schema",
    )
    for key in ("source_sha256", "clock_sha256", "annotation_sha256", "run_sha256"):
        _hash(m.get(key), key)
    _label(m.get("video_id"), "video_id")
    _integer(m.get("annotation_revision"), "annotation revision")
    start = _integer(m.get("start_frame"), "start frame")
    end = _integer(m.get("end_frame"), "end frame")
    _require(
        0 < end - start <= _MAX_FRAMES, "Audit range must contain at most 251 frames"
    )
    samples = _list(m.get("sample_frames"), "sample_frames")
    _require(1 <= len(samples) <= 11, "Audit needs between one and eleven samples")
    for frame in samples:
        _integer(frame, "sample frame")
        _require(start <= frame < end, "Sample outside frozen range")
    _require(
        samples == sorted(set(samples)), "Sample frames must be unique and ordered"
    )
    _require(
        type(m.get("iou_threshold")) in (int, float) and m["iou_threshold"] == 0.5,
        "Frozen IoU threshold must be 0.5",
    )
    return {"sample_count": len(samples), "source_frames": end - start}


def validate_packet(manifest, packet, *, manifest_sha256):
    """Validate source-only packet lineage; supplied hash is of the raw manifest."""
    validate_manifest(manifest)
    _hash(manifest_sha256, "raw manifest hash")
    p = _document(packet, "Packet")
    _require(
        type(p.get("schema_version")) is int and p["schema_version"] == 1,
        "Packet schema",
    )
    _require(
        p.get("manifest_sha256") == manifest_sha256, "Packet manifest hash mismatch"
    )
    for key in ("source_sha256", "clock_sha256", "video_id"):
        _require(p.get(key) == manifest[key], f"Packet {key} mismatch")
    width = _integer(p.get("width"), "native width", 1)
    height = _integer(p.get("height"), "native height", 1)
    rows = _list(p.get("samples"), "packet samples")
    _require(
        len(rows) == len(manifest["sample_frames"]), "Missing or extra packet samples"
    )
    previous_time, images = -1, set()
    for frame, row in zip(manifest["sample_frames"], rows, strict=True):
        _document(row, "Packet sample")
        _require(
            type(row.get("frame")) is int and row["frame"] == frame,
            "Packet samples must match frozen ordered frames",
        )
        time_s = _finite(row.get("time_s"), "source PTS")
        _require(time_s >= 0 and time_s > previous_time, "Packet PTS must increase")
        previous_time = time_s
        image = _label(row.get("image"), "native image path")
        path = PurePosixPath(image)
        _require(
            not path.is_absolute()
            and ".." not in path.parts
            and "\\" not in image
            and image not in images,
            "Native image paths must be distinct relative POSIX paths",
        )
        images.add(image)
        _hash(row.get("image_sha256"), "native image hash")
    return {"sample_count": len(rows), "width": width, "height": height}


def validate_assessment(packet, assessment, *, packet_sha256):
    """Check complete source-person accounting, preserving explicit unknowns."""
    _hash(packet_sha256, "raw packet hash")
    a = _document(assessment, "Assessment")
    _require(
        type(a.get("schema_version")) is int and a["schema_version"] == 1,
        "Assessment schema",
    )
    _require(a.get("packet_sha256") == packet_sha256, "Assessment packet hash mismatch")
    _require(
        a.get("prediction_blind") is True,
        "Assessment must declare prediction blindness",
    )
    _label(a.get("session_id"), "assessment session")
    width = _integer(packet.get("width"), "native width", 1)
    height = _integer(packet.get("height"), "native height", 1)
    rows = _list(a.get("frames"), "assessment frames")
    samples = _list(packet.get("samples"), "packet samples")
    _require(len(rows) == len(samples), "Missing or extra assessment frames")
    for sample, row in zip(samples, rows, strict=True):
        _document(row, "Assessment frame")
        _require(
            type(row.get("frame")) is int and row["frame"] == sample["frame"],
            "Assessment frames must match packet in order",
        )
        _require(
            isinstance(row.get("scene"), str)
            and row["scene"] in {"court_view", "replay", "non_play", "unknown"},
            "Invalid assessed scene",
        )
        _label(row.get("view_id"), "source view", nullable=True)
        _require(
            type(row.get("complete")) is bool,
            "Assessment completeness must be explicit",
        )
        _require(isinstance(row.get("note"), str), "Source frame evidence is required")
        people = _list(row.get("persons"), "source persons")
        _require(len(people) <= _MAX_PERSONS, "Too many source persons")
        actors, localizable = set(), 0
        for person in people:
            _document(person, "Source person")
            actor = _label(person.get("actor"), "source actor", nullable=True)
            _require(
                actor is None or actor not in actors,
                "Duplicate source actor within frame",
            )
            if actor is not None:
                actors.add(actor)
            for key in ("localization_eligible", "identity_eligible"):
                _require(type(person.get(key)) is bool, f"Explicit {key} is required")
            _require(
                isinstance(person.get("note"), str),
                "Source person evidence is required",
            )
            if person.get("box") is not None:
                _box(person["box"], width, height)
            if person["localization_eligible"]:
                _require(
                    person.get("box") is not None,
                    "Eligible localization needs a native box",
                )
                localizable += 1
            if person["identity_eligible"]:
                _require(
                    person["localization_eligible"]
                    and actor is not None
                    and row["view_id"] is not None,
                    "Eligible identity needs localization, actor and source view",
                )
        _require(
            localizable <= _MAX_LOCALIZABLE,
            "At most eight localizable persons are supported",
        )
    return {
        "sample_count": len(rows),
        "source_person_observations": sum(len(r["persons"]) for r in rows),
    }


def box_iou(left, right):
    """Intersection over union for validated native pixel boxes."""
    area = max(0, min(left[2], right[2]) - max(left[0], right[0])) * max(
        0, min(left[3], right[3]) - max(left[1], right[1])
    )
    union = (
        (left[2] - left[0]) * (left[3] - left[1])
        + (right[2] - right[0]) * (right[3] - right[1])
        - area
    )
    return area / union if union else 0.0


def maximum_iou_matching(source_boxes, prediction_boxes, threshold=0.5):
    """Return globally maximum total IoU, then lexicographically stable pairs.

    A prediction can match one source person. Bitmask states cover at most eight
    people and are iterated over at most 128 predictions; no dependencies needed.
    The inputs must already be validated boxes. Unmatched assignments sort last.
    """
    _require(
        len(source_boxes) <= _MAX_LOCALIZABLE and len(prediction_boxes) <= _MAX_PERSONS,
        "Matching inputs exceed bounded capacity",
    )
    _require(threshold == 0.5, "Frozen IoU threshold must be 0.5")
    empty = (_MAX_PERSONS,) * len(source_boxes)
    states = {0: (0.0, empty)}
    for prediction, box in enumerate(prediction_boxes):
        updated = dict(states)
        for mask, (total, assignments) in states.items():
            for person, source in enumerate(source_boxes):
                overlap = box_iou(source, box)
                if mask & (1 << person) or overlap < threshold:
                    continue
                indices = list(assignments)
                indices[person] = prediction
                candidate = (total + overlap, tuple(indices))
                new_mask = mask | (1 << person)
                previous = updated.get(new_mask)
                if (
                    previous is None
                    or candidate[0] > previous[0]
                    or (candidate[0] == previous[0] and candidate[1] < previous[1])
                ):
                    updated[new_mask] = candidate
        states = updated
    _, assignments = min(states.values(), key=lambda item: (-item[0], item[1]))
    return [
        {
            "person_index": person,
            "prediction_index": prediction,
            "iou": box_iou(source_boxes[person], prediction_boxes[prediction]),
        }
        for person, prediction in enumerate(assignments)
        if prediction != _MAX_PERSONS
    ]


def _validate_run(manifest, packet, run):
    r = _document(run, "Player run")
    expected = {
        "schema_version": 1,
        "video_id": manifest["video_id"],
        "video_sha256": manifest["source_sha256"],
        "stage": "players",
        "start_frame": manifest["start_frame"],
        "end_frame": manifest["end_frame"],
        "stride": 1,
        "processed_frames": manifest["end_frame"] - manifest["start_frame"],
        "annotation_revision": manifest["annotation_revision"],
    }
    for key, value in expected.items():
        _require(
            r.get(key) == value and type(r.get(key)) is type(value),
            f"Player run {key} mismatch",
        )
    _hash(r.get("checkpoint_sha256"), "checkpoint hash")
    _require(not r.get("requires_tracking_rerun"), "Stale player run cannot be scored")
    start, end = manifest["start_frame"], manifest["end_frame"]
    cuts = _list(r.get("cut_frames"), "cut frames")
    for cut in cuts:
        _integer(cut, "camera cut")
        _require(start <= cut < end, "Cut outside run")
    _require(cuts == sorted(set(cuts)), "Cuts must be unique and ordered")
    ranges = _list(r.get("camera_ranges"), "camera ranges")
    points = [start, *(cut for cut in cuts if cut > start), end]
    _require(len(ranges) == len(points) - 1, "Missing camera ranges")
    for left, right, camera in zip(points[:-1], points[1:], ranges, strict=True):
        _document(camera, "Camera range")
        _require(
            type(camera.get("start_frame")) is int
            and type(camera.get("end_frame")) is int
            and camera["start_frame"] == left
            and camera["end_frame"] == right,
            "Camera ranges do not preserve cuts",
        )
    rows = _list(r.get("frames"), "run frames")
    _require(len(rows) == end - start, "Missing native prediction frames")
    times = {sample["frame"]: sample["time_s"] for sample in packet["samples"]}
    previous_time, segment = -1, None
    for index, row in enumerate(rows, start):
        _document(row, "Prediction frame")
        _require(
            type(row.get("frame")) is int and row["frame"] == index,
            "Run must contain every native frame in order",
        )
        time_s = _finite(row.get("time_s"), "prediction PTS")
        _require(
            time_s >= 0 and time_s > previous_time, "Run PTS must strictly increase"
        )
        previous_time = time_s
        _require(
            index not in times or time_s == times[index],
            "Prediction source PTS mismatch",
        )
        if index in cuts:
            segment = index
        camera = row.get("camera_segment_start_frame")
        if camera is not None:
            _integer(camera, "camera segment")
            if segment is None:
                _require(
                    camera <= start, "Initial camera segment begins after run start"
                )
                segment = camera
            _require(
                camera == segment, "Prediction camera segment does not preserve cuts"
            )
        _require(
            (row.get("scene") is None or isinstance(row.get("scene"), str))
            and row.get("scene") in {None, "live", "replay", "non_play", "unknown"},
            "Invalid prediction scene",
        )
        people = _list(row.get("players"), "predicted players")
        _require(len(people) <= _MAX_PERSONS, "Too many predicted players")
        tracks = set()
        for person in people:
            _document(person, "Predicted person")
            _require(
                "track_id" in person,
                "Prediction must retain unknown track ID explicitly",
            )
            track = person["track_id"]
            if track is not None:
                _integer(track, "track ID")
                _require(track not in tracks, "Duplicate track ID within frame")
                tracks.add(track)
            _box(person.get("box"), packet["width"], packet["height"])
            confidence = _finite(person.get("confidence"), "prediction confidence")
            _require(0 <= confidence <= 1, "Prediction confidence outside [0,1]")
    for gap in _list(r.get("known_preceding_timestamp_gaps", []), "timestamp gaps"):
        _integer(gap, "timestamp gap")
    for boundary in _list(r.get("boundaries", []), "boundaries"):
        _document(boundary, "Boundary")
        _integer(boundary.get("frame"), "boundary frame")
        _label(boundary.get("reason"), "boundary reason")
    return rows


def _context_reasons(left, right, run, rows):
    reasons = []
    if left["view_id"] is None or left["view_id"] != right["view_id"]:
        reasons.append("unknown_or_changed_source_view")
    first, last = left["frame"], right["frame"]
    interval = rows[first - run["start_frame"] : last - run["start_frame"] + 1]
    segments = {row.get("camera_segment_start_frame") for row in interval}
    if None in segments or len(segments) != 1:
        reasons.append("unknown_or_changed_cached_camera_segment")
    if any(first < cut <= last for cut in run["cut_frames"]):
        reasons.append("camera_cut")
    if any(row.get("scene") in _EXCLUDED for row in interval):
        reasons.append("reviewed_scene_exclusion")
    if any(
        first < gap <= last for gap in run.get("known_preceding_timestamp_gaps", [])
    ):
        reasons.append("timestamp_gap")
    if any(
        first < boundary.get("frame", -1) <= last
        and boundary.get("reason") == "timestamp_discontinuity"
        for boundary in run.get("boundaries", [])
    ):
        reasons.append("timestamp_gap")
    return list(dict.fromkeys(reasons))


def score_audit(manifest, packet, assessment, run, *, manifest_sha256, packet_sha256):
    """Score a sealed source assessment without changing any input document.

    The caller verifies raw run/annotation/source/clock hashes and current
    reviewed context. This function validates parsed lineage and sample PTS.
    Every source person and prediction remains in explicit denominators.
    Unmatched predictions are not automatically asserted false positives when
    source people are unlocalizable or a source frame is incomplete/excluded.
    """
    validate_packet(manifest, packet, manifest_sha256=manifest_sha256)
    validate_assessment(packet, assessment, packet_sha256=packet_sha256)
    rows = _validate_run(manifest, packet, run)
    totals = dict.fromkeys(
        (
            "sample_frames",
            "scored_frames",
            "ineligible_frames",
            "source_person_observations",
            "source_localization_eligible_persons",
            "source_identity_eligible_persons",
            "localization_eligible_persons",
            "localization_ineligible_persons",
            "unlocalizable_persons",
            "unknown_actor_persons",
            "identity_ineligible_persons",
            "raw_predictions",
            "scored_predictions",
            "unscored_predictions",
            "matched_persons",
            "unmatched_eligible_persons",
            "unmatched_predictions",
            "predictions_without_track_id",
            "transition_candidates",
            "eligible_transitions",
            "ineligible_transitions",
            "same_id_transitions",
            "changed_id_transitions",
        ),
        0,
    )
    frames, actor_tracks, track_actors, ious = [], {}, {}, []
    for source in assessment["frames"]:
        index = source["frame"]
        prediction = rows[index - manifest["start_frame"]]
        people, predictions = source["persons"], prediction["players"]
        reasons = []
        if source["scene"] != "court_view":
            reasons.append("source_scene_not_court_view")
        if not source["complete"]:
            reasons.append("incomplete_source_assessment")
        if prediction.get("scene") in _EXCLUDED:
            reasons.append("reviewed_scene_exclusion")
        eligible = not reasons
        eligible_indices = (
            [i for i, person in enumerate(people) if person["localization_eligible"]]
            if eligible
            else []
        )
        matched = (
            maximum_iou_matching(
                [people[i]["box"] for i in eligible_indices],
                [p["box"] for p in predictions],
            )
            if eligible
            else []
        )
        matches = [
            {**match, "person_index": eligible_indices[match["person_index"]]}
            for match in matched
        ]
        by_person = {match["person_index"]: match for match in matches}
        matched_predictions = {match["prediction_index"] for match in matches}
        person_results = []
        for person_index, person in enumerate(people):
            match = by_person.get(person_index)
            track = (
                predictions[match["prediction_index"]]["track_id"] if match else None
            )
            identity_eligible = bool(
                eligible
                and person["identity_eligible"]
                and match
                and track is not None
                and prediction.get("camera_segment_start_frame") is not None
            )
            person_results.append(
                {
                    "person_index": person_index,
                    "actor": person["actor"],
                    "source_box": list(person["box"])
                    if person["box"] is not None
                    else None,
                    "source_localization_eligible": person["localization_eligible"],
                    "source_identity_eligible": person["identity_eligible"],
                    "localization_eligible": bool(
                        eligible and person["localization_eligible"]
                    ),
                    "identity_eligible": identity_eligible,
                    "prediction_index": match["prediction_index"] if match else None,
                    "track_id": track,
                    "iou": match["iou"] if match else None,
                }
            )
            if identity_eligible:
                actor_key = (
                    source["view_id"],
                    prediction.get("camera_segment_start_frame"),
                    person["actor"],
                )
                actor_tracks.setdefault(actor_key, set()).add(track)
                track_key = (
                    source["view_id"],
                    prediction.get("camera_segment_start_frame"),
                    track,
                )
                track_actors.setdefault(track_key, set()).add(person["actor"])
        frame_result = {
            "frame": index,
            "time_s": prediction["time_s"],
            "scored": eligible,
            "ineligible_reasons": reasons,
            "source_scene": source["scene"],
            "view_id": source["view_id"],
            "camera_segment_start_frame": prediction.get("camera_segment_start_frame"),
            "source_person_count": len(people),
            "raw_prediction_count": len(predictions),
            "persons": person_results,
            "matches": matches,
            "unmatched_eligible_person_indices": [
                i for i in eligible_indices if i not in by_person
            ],
            "unmatched_prediction_indices": [
                i for i in range(len(predictions)) if i not in matched_predictions
            ]
            if eligible
            else [],
            "unscored_prediction_indices": []
            if eligible
            else list(range(len(predictions))),
        }
        frames.append(frame_result)
        counts = {
            "sample_frames": 1,
            "scored_frames": int(eligible),
            "ineligible_frames": int(not eligible),
            "source_person_observations": len(people),
            "source_localization_eligible_persons": sum(
                p["localization_eligible"] for p in people
            ),
            "source_identity_eligible_persons": sum(
                p["identity_eligible"] for p in people
            ),
            "localization_eligible_persons": len(eligible_indices),
            "localization_ineligible_persons": len(people) - len(eligible_indices),
            "unlocalizable_persons": sum(p["box"] is None for p in people),
            "unknown_actor_persons": sum(p["actor"] is None for p in people),
            "identity_ineligible_persons": sum(
                not p["identity_eligible"] for p in person_results
            ),
            "raw_predictions": len(predictions),
            "scored_predictions": len(predictions) if eligible else 0,
            "unscored_predictions": 0 if eligible else len(predictions),
            "matched_persons": len(matches),
            "unmatched_eligible_persons": len(eligible_indices) - len(matches),
            "unmatched_predictions": len(predictions) - len(matches) if eligible else 0,
            "predictions_without_track_id": sum(
                p["track_id"] is None for p in predictions
            ),
        }
        for key, count in counts.items():
            totals[key] += count
        ious.extend(match["iou"] for match in matches)
    transitions = []
    for position, (left, right) in enumerate(itertools.pairwise(frames)):
        source_left, source_right = assessment["frames"][position : position + 2]
        context = _context_reasons(source_left, source_right, run, rows)
        left_actors = {p["actor"]: p for p in left["persons"] if p["actor"] is not None}
        right_actors = {
            p["actor"]: p for p in right["persons"] if p["actor"] is not None
        }
        for actor in sorted(left_actors.keys() | right_actors.keys()):
            before, after = left_actors.get(actor), right_actors.get(actor)
            reasons = list(context)
            if before is None or after is None:
                reasons.append("source_actor_missing_at_endpoint")
            if not left["scored"] or not right["scored"]:
                reasons.append("ineligible_endpoint_frame")
            if (
                not before
                or not after
                or not before["identity_eligible"]
                or not after["identity_eligible"]
            ):
                reasons.append("unavailable_eligible_identity_match")
            eligible = not reasons
            status = (
                "same_id"
                if eligible and before["track_id"] == after["track_id"]
                else "changed_id"
                if eligible
                else "ineligible"
            )
            transitions.append(
                {
                    "from_frame": left["frame"],
                    "to_frame": right["frame"],
                    "actor": actor,
                    "eligible": eligible,
                    "ineligible_reasons": reasons,
                    "from_track_id": before["track_id"] if before else None,
                    "to_track_id": after["track_id"] if after else None,
                    "status": status,
                }
            )
            totals["transition_candidates"] += 1
            totals[
                "eligible_transitions" if eligible else "ineligible_transitions"
            ] += 1
            if eligible:
                totals[f"{status}_transitions"] += 1
    fragments = [
        {
            "view_id": view,
            "camera_segment_start_frame": segment,
            "actor": actor,
            "track_ids": sorted(tracks),
            "distinct_track_ids": len(tracks),
        }
        for (view, segment, actor), tracks in actor_tracks.items()
    ]
    reuse = [
        {
            "view_id": view,
            "camera_segment_start_frame": segment,
            "track_id": track,
            "actors": sorted(actors),
        }
        for (view, segment, track), actors in track_actors.items()
        if len(actors) > 1
    ]
    return {
        "schema_version": 1,
        "manifest_sha256": manifest_sha256,
        "packet_sha256": packet_sha256,
        "assessment_session_id": assessment["session_id"],
        "sample_frames": list(manifest["sample_frames"]),
        "iou_threshold": 0.5,
        "totals": totals,
        "frames": frames,
        "transitions": transitions,
        "matched_ious": ious,
        "iou_summary": {
            "count": len(ious),
            "minimum": min(ious) if ious else None,
            "maximum": max(ious) if ious else None,
            "mean": sum(ious) / len(ious) if ious else None,
        },
        "source_actor_fragments": fragments,
        "track_id_reuse": reuse,
        "limitations": [
            "Sparse development samples assessed by automated source-only sessions; not human gold labels or an independent held-out test.",
            "Unmatched predictions remain unmatched observations, not automatic false-positive claims where source localization is unavailable.",
            "Sampled ID changes do not establish full-run switches; no interpolation, cross-camera identity or full-match accuracy claim.",
        ],
    }
