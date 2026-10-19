"""Read-only, source-audited plans for future reviewed-rally media exports."""

import hashlib
import itertools
import json
import math
import sqlite3
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path

from .av_runtime import open_media
from .orientation import display_dimensions, frame_rotation
from .storage import Store
from .video import resolve_source

TOLERANCE_S = 0.00002


class ExportPlanStore(Store):
    """Read existing catalog/revisions without Store initialization or DDL."""

    def __init__(self, data):
        self.data = Path(data)
        self.db_path = self.data / "catalog.sqlite3"
        if not self.db_path.is_file():
            raise FileNotFoundError("Existing application catalog is unavailable")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            yield db
        finally:
            db.close()


def _canonical(document):
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audit_source(video, source, times):
    """Compare the entire imported clock with actual native source frames."""
    pts = []
    final_duration = None
    with open_media(str(source)) as container:
        stream = container.streams.video[0]
        if Fraction(video["time_base"]) != stream.time_base:
            raise ValueError("Source time base changed; reimport the video")
        origin = float((stream.start_time or 0) * stream.time_base)
        if abs(origin - video["source_start_s"]) > TOLERANCE_S:
            raise ValueError("Source time origin changed; reimport the video")
        for index, frame in enumerate(container.decode(stream)):
            if frame.pts is None or index >= len(times):
                raise ValueError("Source frame count or PTS differs from import")
            timestamp = float(frame.pts * frame.time_base) - origin
            if abs(timestamp - times[index]) > TOLERANCE_S:
                raise ValueError("Source timestamps differ from imported timeline")
            rotation = frame_rotation(frame)
            if rotation != video.get("rotation", 0) or display_dimensions(
                frame.width, frame.height, rotation
            ) != (video["width"], video["height"]):
                raise ValueError("Source orientation or dimensions differ from import")
            pts.append(frame.pts)
            final_duration = (
                float(frame.duration * frame.time_base) if frame.duration else None
            )
    if len(pts) != len(times):
        raise ValueError("Source frame count differs from imported timeline")
    endpoint = None
    if final_duration is not None and final_duration > 0:
        endpoint = times[-1] + final_duration
        if abs(endpoint - video["duration_s"]) > TOLERANCE_S:
            raise ValueError("Imported video endpoint differs from source; reimport it")
    return pts, endpoint


def _validate_snapshot(snapshot, video, times):
    if snapshot["mode"] != video["mode"]:
        raise ValueError("Annotation mode differs from video")
    for event in snapshot["events"]:
        frame = event["frame"]
        if frame >= len(times) or abs(event["time_s"] - times[frame]) > TOLERANCE_S:
            raise ValueError("Annotation event differs from the source clock")
        for field in ("contact_end_frame", "terminal_end_frame"):
            if event[field] is not None and event[field] >= len(times):
                raise ValueError("Annotation interval exceeds source frames")
    for field in (
        "calibrations",
        "review_windows",
        "track_assignments",
        "scene_ranges",
    ):
        if any(item["end_frame"] > len(times) for item in snapshot[field]):
            raise ValueError("Annotation context exceeds source frames")
    for field in ("shuttle_points", "camera_corrections"):
        if any(item["frame"] >= len(times) for item in snapshot[field]):
            raise ValueError("Annotation context exceeds source frames")


def plan_rally_exports(store, video_id, revision, root):
    """Freeze a specific saved revision; retain every distinct rally and reason.

    This audits media without inference, rendering, or writes to the Store.
    Annotation context and unknown/predicted labels remain original evidence.
    """
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("Choose an explicit nonnegative annotation revision")
    video = store.video(video_id)
    source = resolve_source(video, root)
    if _digest(source) != video["sha256"]:
        raise ValueError("Source bytes differ from import")
    timeline = store.data / video_id / "timestamps.json"
    timeline_bytes = timeline.read_bytes()
    times = json.loads(timeline_bytes)
    if (
        not isinstance(times, list)
        or not times
        or len(times) != video["frame_count"]
        or any(
            isinstance(t, bool)
            or not isinstance(t, (int, float))
            or not math.isfinite(t)
            or t < 0
            for t in times
        )
        or any(b <= a for a, b in itertools.pairwise(times))
        or isinstance(video["duration_s"], bool)
        or not isinstance(video["duration_s"], (int, float))
        or not math.isfinite(video["duration_s"])
        or video["duration_s"] <= times[-1]
    ):
        raise ValueError("Imported source timeline or endpoint is invalid")
    snapshot = store.annotations(video_id, revision=revision).model_dump(mode="json")
    if snapshot["revision"] != revision:
        raise ValueError("Saved revision does not match requested revision")
    _validate_snapshot(snapshot, video, times)
    native_pts, endpoint = _audit_source(video, source, times)
    rallies = []
    for rally_id in sorted({event["rally_id"] for event in snapshot["events"]}):
        events = [e for e in snapshot["events"] if e["rally_id"] == rally_id]
        starts = [e for e in events if e["kind"] == "serve"]
        ends = [e for e in events if e["kind"] == "rally_end"]
        reasons = []
        for label, candidates, interval in (
            ("start", starts, "contact_start_frame"),
            ("end", ends, "terminal_start_frame"),
        ):
            if len(candidates) != 1:
                reasons.append(f"missing_or_ambiguous_{label}")
            elif candidates[0]["status"] not in ("reviewed", "corrected"):
                reasons.append(f"unreviewed_{label}")
            elif candidates[0][interval] is not None:
                reasons.append(f"uncertain_{label}")
        source_range = None
        if not reasons:
            start, end = starts[0]["frame"], ends[0]["frame"] + 1
            if end == len(times) and endpoint is None:
                reasons.append("unavailable_final_sample_duration")
            else:
                end_s = times[end] if end < len(times) else endpoint
                source_range = {
                    "start_frame": start,
                    "end_frame_exclusive": end,
                    "start_s": times[start],
                    "end_s_exclusive": end_s,
                    "source_start_s": times[start] + video["source_start_s"],
                    "source_end_s_exclusive": end_s + video["source_start_s"],
                    "start_pts": native_pts[start],
                    "end_pts_exclusive": native_pts[end]
                    if end < len(times)
                    else round(
                        (end_s + video["source_start_s"]) / Fraction(video["time_base"])
                    ),
                }
        rallies.append(
            {
                "rally_id": rally_id,
                "event_ids": [e["id"] for e in events],
                "boundary_event_ids": [e["id"] for e in [*starts, *ends]],
                "reasons": reasons,
                "source_range": source_range,
            }
        )
    # Even individually valid boundaries may identify competing overlapping rallies.
    candidates = [r for r in rallies if r["source_range"] is not None]
    for a, b in itertools.combinations(candidates, 2):
        left, right = a["source_range"], b["source_range"]
        if max(left["start_frame"], right["start_frame"]) < min(
            left["end_frame_exclusive"], right["end_frame_exclusive"]
        ):
            for rally in (a, b):
                if "overlapping_rallies" not in rally["reasons"]:
                    rally["reasons"].append("overlapping_rallies")
    for rally in rallies:
        rally["eligible"] = not rally["reasons"]
        if not rally["eligible"]:
            rally["source_range"] = None
    if (
        _digest(source) != video["sha256"]
        or timeline.read_bytes() != timeline_bytes
        or store.video(video_id) != video
        or store.annotations(video_id, revision=revision).model_dump(mode="json")
        != snapshot
    ):
        raise ValueError(
            "Export inputs changed during planning; retry from a saved revision"
        )
    eligible = sum(r["eligible"] for r in rallies)
    return {
        "schema_version": 1,
        "purpose": "reviewed_rally_export_plan",
        "source": video
        | {
            "metadata_sha256": hashlib.sha256(_canonical(video)).hexdigest(),
            "timestamps_sha256": hashlib.sha256(timeline_bytes).hexdigest(),
            "audited_endpoint_s": endpoint,
        },
        "annotation_revision": revision,
        "annotation_sha256": hashlib.sha256(_canonical(snapshot)).hexdigest(),
        "annotations": snapshot,
        "rallies": rallies,
        "counts": {
            "total": len(rallies),
            "eligible": eligible,
            "ineligible": len(rallies) - eligible,
        },
        "limitations": [
            "An export plan is not rendered media or an annotation accuracy evaluation.",
            "Reviewed scene, camera and calibration context is preserved without filtering or reinterpreting it.",
            "Unknown labels and original predicted events remain distinct from reviewed boundaries.",
        ],
    }


def write_export_plan(path, plan, data):
    """Create a new requested file, never overwrite a source or Store artifact."""
    path = Path(path)
    if path.resolve().is_relative_to(Path(data).resolve()):
        raise ValueError("Write export plans outside application data storage")
    content = json.dumps(plan, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(content)
