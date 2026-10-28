"""Metadata-only diagnosis of frozen shuttle context; no models, media or Store."""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import stat
from collections import Counter
from pathlib import Path

MAX_JSON_BYTES = 32 * 1024 * 1024
METHODS = ("control", "decoder", "convolution")
SCENES = ("live", "replay", "non_play", "unknown")
CONSUMER_FILES = (
    "backend/badminton/shuttle_selection_study.py",
    "backend/badminton/scene_review.py",
    "backend/badminton/shuttle_validation.py",
    "backend/badminton/shuttle_capacity_continuation.py",
    "backend/badminton/segments.py",
)
ELIGIBILITY = {
    "training_allowed": False,
    "independent_test_allowed": False,
    "model_deployment_allowed": False,
    "dataset_redistribution_allowed": False,
}


def checksum(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate metadata JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Non-finite metadata JSON constant")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def scalar(value):
    if value is None or type(value) in (str, int, float, bool):
        return value
    return {"invalid_type": type(value).__name__}


def fields(value, names):
    if not isinstance(value, dict):
        return None
    return {key: scalar(value[key]) for key in names if key in value}


def ranges(value, *, scenes=False):
    if not isinstance(value, list):
        return scalar(value)
    keys = (
        ("start_frame", "end_frame", "scene")
        if scenes
        else ("start_frame", "end_frame")
    )
    return [fields(item, keys) for item in value]


def project_run(raw):
    result = fields(
        raw, ("id", "video_id", "video_sha256", "stage", "start_frame", "end_frame")
    )
    if result is None:
        return None
    if "camera_ranges" in raw:
        result["camera_ranges"] = ranges(raw["camera_ranges"])
    if "cut_frames" in raw:
        cuts = raw["cut_frames"]
        result["cut_frames"] = (
            [scalar(v) for v in cuts] if isinstance(cuts, list) else scalar(cuts)
        )
    return result


def project_view(raw):
    result = fields(raw, ("id", "video_id", "start_frame", "end_frame"))
    if result is not None and "case_ids" in raw:
        values = raw["case_ids"]
        result["case_ids"] = (
            [scalar(v) for v in values] if isinstance(values, list) else scalar(values)
        )
    return result


def project_snapshot(raw):
    if not isinstance(raw, dict):
        return None
    annotations = raw.get("annotations")
    projected = fields(annotations, ("video_id", "revision"))
    if projected is not None and "scene_ranges" in annotations:
        projected["scene_ranges"] = ranges(annotations["scene_ranges"], scenes=True)
    return {
        "video": fields(raw.get("video"), ("id", "sha256")),
        "revision": scalar(raw.get("revision")),
        "annotations": projected,
    }


def frame_range(value):
    return (
        isinstance(value, dict)
        and type(value.get("start_frame")) is int
        and type(value.get("end_frame")) is int
        and value["start_frame"] < value["end_frame"]
    )


def partition_context(run, annotations):
    """Match archived eligible_segments while exposing unavailable prerequisites."""
    flags = set()
    if run is None:
        return [], ["missing_run_metadata"]
    if not frame_range(run):
        return [], ["malformed_run_metadata"]
    first, last = run["start_frame"], run["end_frame"]
    cameras = run.get("camera_ranges")
    scenes = annotations.get("scene_ranges") if isinstance(annotations, dict) else None
    for label, values in (("camera", cameras), ("scene", scenes)):
        if values is None:
            flags.add("missing_" + label + "_metadata")
        elif not isinstance(values, list) or any(not frame_range(v) for v in values):
            flags.add("malformed_" + label + "_metadata")
    cuts = run.get("cut_frames", [])
    if not isinstance(cuts, list) or any(
        type(c) is not int or not first <= c < last for c in cuts
    ):
        flags.add("malformed_run_metadata")
    if isinstance(scenes, list) and any(
        not isinstance(v, dict) or v.get("scene") not in SCENES for v in scenes
    ):
        flags.add("malformed_scene_metadata")
    if flags:
        return [], sorted(flags)
    bounds = {first, last, *cuts}
    for value in [*cameras, *scenes]:
        bounds.update(
            max(first, min(last, value[key])) for key in ("start_frame", "end_frame")
        )
    result = []
    for start, end in itertools.pairwise(sorted(bounds)):
        camera_count = sum(
            v["start_frame"] <= start and end <= v["end_frame"] for v in cameras
        )
        live_count = sum(
            v["start_frame"] <= start and end <= v["end_frame"] and v["scene"] == "live"
            for v in scenes
        )
        excluded = {
            v["scene"]
            for v in scenes
            if v["scene"] != "live"
            and v["start_frame"] < end
            and start < v["end_frame"]
        }
        interval_flags = set()
        if camera_count == 0:
            interval_flags.add("uncovered_camera_context")
        elif camera_count > 1:
            interval_flags.add("ambiguous_camera_coverage")
        if live_count == 0:
            interval_flags.add("uncovered_live_context")
        elif live_count > 1:
            interval_flags.add("ambiguous_live_coverage")
        interval_flags.update("explicit_" + scene + "_exclusion" for scene in excluded)
        eligible = camera_count == 1 and live_count == 1 and not excluded
        if eligible:
            interval_flags.add("eligible_metadata")
        result.append(
            {
                "start_frame": start,
                "end_frame": end,
                "eligible": eligible,
                "flags": sorted(interval_flags),
            }
        )
    return result, []


def inspect_view(view, run, snapshot):
    annotations = snapshot.get("annotations") if isinstance(snapshot, dict) else None
    segments, global_flags = partition_context(run, annotations)
    flags = set(global_flags)
    if not frame_range(view):
        flags.add("missing_view_membership")
    elif isinstance(run, dict) and (
        run.get("start_frame") != view["start_frame"]
        or run.get("end_frame") != view["end_frame"]
    ):
        flags.add("malformed_run_metadata")
    video = snapshot.get("video") if isinstance(snapshot, dict) else None
    if not (
        isinstance(view, dict)
        and isinstance(view.get("video_id"), str)
        and isinstance(run, dict)
        and isinstance(video, dict)
        and run.get("video_id") == video.get("id") == view["video_id"]
        and isinstance(video.get("sha256"), str)
        and re.fullmatch("[0-9a-f]{64}", video["sha256"])
        and run.get("video_sha256") == video["sha256"]
        and run.get("stage") == "shuttle"
        and isinstance(annotations, dict)
        # Annotations is keyed by the catalog's video_id; its document schema
        # has no video_id member. If a container supplies one, it must agree.
        and (
            "video_id" not in annotations or annotations["video_id"] == view["video_id"]
        )
        and type(snapshot.get("revision")) is int
        and type(annotations.get("revision")) is int
        and annotations.get("revision") == snapshot["revision"]
    ):
        flags.add("source_mismatch")
    if flags:
        segments = [{**v, "eligible": False} for v in segments]
    combined = flags | {f for value in segments for f in value["flags"]}
    if frame_range(run):
        for kind, values in (
            ("camera", run.get("camera_ranges")),
            (
                "scene",
                annotations.get("scene_ranges")
                if isinstance(annotations, dict)
                else None,
            ),
        ):
            if not isinstance(values, list) or not all(frame_range(v) for v in values):
                continue
            if kind == "scene" and not all(v.get("scene") in SCENES for v in values):
                continue
            bounds = {run["start_frame"], run["end_frame"]}
            for value in values:
                bounds.update(
                    max(run["start_frame"], min(run["end_frame"], value[k]))
                    for k in ("start_frame", "end_frame")
                )
            for start, end in itertools.pairwise(sorted(bounds)):
                covered = [
                    v
                    for v in values
                    if v["start_frame"] <= start and end <= v["end_frame"]
                ]
                count = (
                    len(covered)
                    if kind == "camera"
                    else sum(v["scene"] == "live" for v in covered)
                )
                if count == 0:
                    combined.add(
                        "uncovered_camera_context"
                        if kind == "camera"
                        else "uncovered_live_context"
                    )
                elif count > 1:
                    combined.add(
                        "ambiguous_camera_coverage"
                        if kind == "camera"
                        else "ambiguous_live_coverage"
                    )
                if kind == "scene":
                    combined.update(
                        "explicit_" + v["scene"] + "_exclusion"
                        for v in covered
                        if v["scene"] != "live"
                    )
    if flags:
        combined.discard("eligible_metadata")
    return {
        "view": view,
        "run_identity": fields(run, ("id", "video_id", "video_sha256")),
        "global_flags": sorted(flags),
        "flags": sorted(combined),
        "segments": segments,
        "camera_metadata": run.get("camera_ranges") if isinstance(run, dict) else None,
        "scene_metadata": annotations.get("scene_ranges")
        if isinstance(annotations, dict)
        else None,
        "eligible_metadata": not flags and any(v["eligible"] for v in segments),
    }


def inspect_case(case, views):
    identifier = case.get("id") if isinstance(case, dict) else None
    members = [
        v
        for v in views
        if isinstance(v["view"], dict)
        and isinstance(v["view"].get("case_ids"), list)
        and identifier in v["view"]["case_ids"]
    ]
    flags, eligible = set(), False
    if not members:
        flags.add("missing_view_membership")
    elif len(members) != 1 or members[0]["view"]["case_ids"].count(identifier) != 1:
        flags.add("ambiguous_view_membership")
    else:
        member = members[0]
        view = member["view"]
        flags.update(member["global_flags"])
        if case.get("video_id") != view.get("video_id"):
            flags.add("source_mismatch")
        frame = case.get("frame")
        matches = [
            s
            for s in member["segments"]
            if type(frame) is int and s["start_frame"] <= frame < s["end_frame"]
        ]
        if len(matches) != 1:
            if not (
                frame_range(view)
                and type(frame) is int
                and view["start_frame"] <= frame < view["end_frame"]
            ):
                flags.add("missing_view_membership")
            # Independently present metadata can diagnose another prerequisite
            # even when the archived guard returned no intervals. It supplies no
            # eligibility credit and does not replace unavailable metadata.
            elif member["global_flags"]:
                cameras = member["camera_metadata"]
                if isinstance(cameras, list) and all(frame_range(c) for c in cameras):
                    camera_count = sum(
                        c["start_frame"] <= frame < c["end_frame"] for c in cameras
                    )
                    if camera_count == 0:
                        flags.add("uncovered_camera_context")
                    elif camera_count > 1:
                        flags.add("ambiguous_camera_coverage")
                scenes = member["scene_metadata"]
                if isinstance(scenes, list) and all(
                    frame_range(s) and s.get("scene") in SCENES for s in scenes
                ):
                    live_count = sum(
                        s["scene"] == "live"
                        and s["start_frame"] <= frame < s["end_frame"]
                        for s in scenes
                    )
                    if live_count == 0:
                        flags.add("uncovered_live_context")
                    elif live_count > 1:
                        flags.add("ambiguous_live_coverage")
                    flags.update(
                        "explicit_" + s["scene"] + "_exclusion"
                        for s in scenes
                        if s["scene"] != "live"
                        and s["start_frame"] <= frame < s["end_frame"]
                    )
        else:
            flags.update(matches[0]["flags"])
            eligible = matches[0]["eligible"] and not member["global_flags"]
        if flags - {"eligible_metadata"}:
            eligible = False
    if not eligible:
        flags.discard("eligible_metadata")
    return {"case": case, "flags": sorted(flags), "eligible_metadata": eligible}


class BoundMetadata:
    """Hash-bound JSON reads; no coordinates, model or media consumer is called."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.reads = {}
        self.missing = set()

    def bound_path(self, descriptor):
        if not isinstance(descriptor, dict) or not isinstance(
            descriptor.get("path"), str
        ):
            raise ValueError("Missing bound metadata descriptor")
        expected = descriptor.get("sha256")
        if not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected):
            raise ValueError("Invalid bound metadata checksum")
        path = self.root / descriptor["path"]
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("Bound metadata path escapes root")
        if path.suffix.lower() != ".json":
            raise ValueError("Only bound JSON metadata is supported")
        self.verify_path(path)
        return path, expected

    def verify_path(self, path):
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("Bound metadata path escapes root")
        for parent in (path, *path.parents):
            if parent == self.root:
                break
            try:
                info = parent.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(
                info, "st_file_attributes", 0
            ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError("Symlink or reparse metadata is not supported")

    def read(self, descriptor, *, decode_json=True):
        path, expected = self.bound_path(descriptor)
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_JSON_BYTES + 1)
        except FileNotFoundError:
            self.missing.add(path)
            raise
        if len(raw) > MAX_JSON_BYTES or checksum(raw) != expected:
            raise ValueError("Bound metadata bytes changed or exceed the limit")
        if path in self.reads and self.reads[path] != expected:
            raise ValueError("Conflicting bound metadata identity")
        self.reads[path] = expected
        return decode(raw) if decode_json else None

    def verify_unchanged(self):
        if any(path.exists() for path in self.missing):
            raise ValueError("Previously unavailable metadata appeared during audit")
        for path, expected in self.reads.items():
            self.verify_path(path)
            with path.open("rb") as stream:
                raw = stream.read(MAX_JSON_BYTES + 1)
            if len(raw) > MAX_JSON_BYTES or checksum(raw) != expected:
                raise ValueError("Metadata source changed during audit")


def audit_metadata(protocol, bindings, root):
    """Project frozen metadata only; retain every declared method/view/case."""
    if (
        protocol.get("schema_version") != 1
        or protocol.get("eligibility") != ELIGIBILITY
    ):
        raise ValueError("Metadata-only protocol or eligibility flags changed")
    if (
        protocol.get("limits", {}).get("metadata_only") is not True
        or protocol["limits"].get("max_new_scientific_attempts") != 0
    ):
        raise ValueError("Only metadata diagnosis is supported")
    denominator = protocol["denominators"]
    if denominator["methods"] != list(METHODS):
        raise ValueError("Method denominator changed")
    if any(
        type(denominator.get(k)) is not int or not 0 < denominator[k] <= 4096
        for k in ("views_per_method", "cases_per_method")
    ):
        raise ValueError("Invalid audit denominator")
    expected = protocol["input_sha256"]
    names = {
        "original-experiment",
        "sealed-familiar-result",
        "original-public-protocol",
        "familiar-packet",
        "baseline-context-container",
        "raw-index",
    }
    if set(bindings) != set(expected) or set(expected) != names:
        raise ValueError("Frozen input membership changed")
    reader = BoundMetadata(root)

    def original(name):
        return reader.read({"path": bindings[name], "sha256": expected[name]})

    # These three bind the public premise and old experiment. Their contents
    # are never decoded: model/checkpoint/scientific result fields are not inputs.
    for name in (
        "original-experiment",
        "sealed-familiar-result",
        "original-public-protocol",
    ):
        reader.read(
            {"path": bindings[name], "sha256": expected[name]}, decode_json=False
        )
    packet = original("familiar-packet")
    cases = [fields(c, ("id", "video_id", "frame")) for c in packet["cases"]]
    del packet
    if len(cases) != denominator["cases_per_method"] or any(
        not isinstance(c, dict) or not isinstance(c.get("id"), str) for c in cases
    ):
        raise ValueError("Case denominator or identity is unavailable")
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate original case identity")
    baseline = original("baseline-context-container")
    catalogs = baseline.get("evidence", {}).get("catalogs", {})
    snapshots = {
        key: project_snapshot(
            value.get("snapshot") if isinstance(value, dict) else None
        )
        for key, value in catalogs.items()
    }
    del catalogs, baseline
    raw_index = original("raw-index")
    references = raw_index.get("references", {})
    del raw_index
    if set(references) != set(METHODS):
        raise ValueError("Raw-index method membership changed")
    methods = {}
    for method in METHODS:
        refs = references[method]
        if not isinstance(refs, list) or len(refs) != denominator["views_per_method"]:
            raise ValueError("View denominator changed")
        views = []
        for ref in refs:
            if not isinstance(ref, dict):
                raise ValueError("Malformed bound view reference")
            try:
                receipt = reader.read(ref["receipt"])
            except FileNotFoundError:
                views.append(inspect_view(None, None, None))
                continue
            view = project_view(receipt.get("view"))
            run_descriptor = receipt.get("run")
            if not isinstance(run_descriptor, dict) or run_descriptor.get(
                "sha256"
            ) != ref["run"].get("sha256"):
                raise ValueError("Receipt and raw-index run bindings differ")
            del receipt, run_descriptor
            try:
                run = project_run(reader.read(ref["run"]))
            except FileNotFoundError:
                run = None
            source = view.get("video_id") if isinstance(view, dict) else None
            snapshot = snapshots.get(source) if isinstance(source, str) else None
            views.append(inspect_view(view, run, snapshot))
        methods[method] = {
            "views": views,
            "cases": [inspect_case(c, views) for c in cases],
        }
    reader.verify_unchanged()
    aggregates = {}
    for method, result in methods.items():
        by_source = {}
        sources = {
            c["case"].get("video_id")
            if isinstance(c["case"].get("video_id"), str)
            else None
            for c in result["cases"]
        }
        sources.update(
            v["view"].get("video_id")
            if isinstance(v["view"], dict)
            and isinstance(v["view"].get("video_id"), str)
            else None
            for v in result["views"]
        )
        for source in sorted(sources, key=str):
            source_cases = [
                c
                for c in result["cases"]
                if (
                    c["case"].get("video_id")
                    if isinstance(c["case"].get("video_id"), str)
                    else None
                )
                == source
            ]
            source_views = [
                v
                for v in result["views"]
                if (
                    v["view"].get("video_id")
                    if isinstance(v["view"], dict)
                    and isinstance(v["view"].get("video_id"), str)
                    else None
                )
                == source
            ]
            source_key = checksum(encode(source))
            by_source[source_key] = {
                "cases": len(source_cases),
                "views": len(source_views),
                "eligible_cases": sum(c["eligible_metadata"] for c in source_cases),
                "eligible_views": sum(v["eligible_metadata"] for v in source_views),
                "case_flags_non_additive": dict(
                    sorted(Counter(f for c in source_cases for f in c["flags"]).items())
                ),
                "view_flags_non_additive": dict(
                    sorted(Counter(f for v in source_views for f in v["flags"]).items())
                ),
            }
        aggregates[method] = {
            "cases": len(result["cases"]),
            "views": len(result["views"]),
            "eligible_cases": sum(c["eligible_metadata"] for c in result["cases"]),
            "eligible_views": sum(v["eligible_metadata"] for v in result["views"]),
            "unassigned_views": sum(
                not isinstance(v["view"], dict)
                or not isinstance(v["view"].get("video_id"), str)
                for v in result["views"]
            ),
            "case_flags_non_additive": dict(
                sorted(Counter(f for c in result["cases"] for f in c["flags"]).items())
            ),
            "view_flags_non_additive": dict(
                sorted(Counter(f for v in result["views"] for f in v["flags"]).items())
            ),
            "sources": by_source,
        }
    return {
        "schema_version": 1,
        "protocol_sha256": checksum(encode(protocol)),
        "input_sha256": expected,
        "eligibility": dict(ELIGIBILITY),
        "fixed_diagnostic_premise": protocol["fixed_diagnostic_premise"],
        "methods": methods,
        "aggregate": aggregates,
        "metadata_files_read": len(reader.reads),
        "limitations": list(protocol["limitations"]),
    }, reader
