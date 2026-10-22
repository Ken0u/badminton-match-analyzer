"""Prospective, unchanged-tracker broadcast development agreement diagnostic.

The source-only labels remain immutable and private. Counts from this module
are conditional development agreement, never expert or full-match accuracy.
Preparing and interpreting do not import Torch or open a native decoder.
"""

from __future__ import annotations

import importlib.metadata
import math
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter, defaultdict
from contextlib import ExitStack, contextmanager
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psutil

from .shuttle_source_assessments import ELIGIBILITY, _ignored_output, verify_freeze
from .shuttle_supervision import (
    _seal,
    _verified,
    contained,
    digest,
    encoded,
    file_hash,
    publish_json,
    read_json,
)

PROTOCOL = (
    Path(__file__).resolve().parents[2]
    / "data/manifests/shuttle_broadcast_baseline_protocol_v1.json"
)
PROTOCOL_SHA = "3df7ae9ddd7e94b57b48ad82420ab3b008d3fbb90614bb94e69c1e7700914ebe"
CHECKPOINT = "df867641a02712b021f04548ff4b1208ddfdb47f629ab2094ceb978667e83b1a"
ASSESSMENT = {
    "manifest_sha256": "f0193b4c0ae3bf98c0592c82c9e252ead94b4cf3286e642e4bfadd3791a3db62",
    "aggregate_sha256": "e361f43a8f3122b449cc357a78bcc8890ed5d67a42133f28cba80f3ccfa722de",
    "protocol_sha256": "79653290b0dd8c1d09c244fce14019447cc6c1bf5402e27aa08bd498133a3a42",
}
CREDENTIALS = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "AGENT_PROJECT_TOKEN",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def load_protocol(path=PROTOCOL):
    _require(file_hash(path) == PROTOCOL_SHA, "Frozen protocol byte seal changed")
    spec = read_json(path)
    _require(
        spec.get("schema_version") == 1 and spec.get("task") == 179,
        "Unexpected broadcast protocol",
    )
    _require(spec["source_assessment"] == ASSESSMENT, "Assessment seals changed")
    recipe = spec["recipe"]
    _require(
        all(
            recipe.get(k) == v
            for k, v in {
                "input_size": [512, 288],
                "sequence_length": 8,
                "precision": "float16",
                "device": "cuda",
                "threshold": 0.5,
                "radius_diagonal": 0.005,
            }.items()
        ),
        "Frozen native recipe changed",
    )
    _require(spec["checkpoint_sha256"] == CHECKPOINT, "Checkpoint changed")
    _require(
        spec["windows"]["before"] == 32 and spec["windows"]["after_inclusive"] == 32,
        "Window recipe changed",
    )
    _require(
        spec["eligibility"] == ELIGIBILITY
        and all(v is False for v in spec["eligibility"].values()),
        "Eligibility changed",
    )
    _require(
        spec["expected"]["cases"] == 128
        and spec["expected"]["requested_rows"] == 8192
        and spec["expected"]["visibility"]
        == {
            "visible_localizable": 37,
            "visible_unlocalizable": 1,
            "not_visible": 5,
            "unknown": 85,
        },
        "Cohort denominator changed",
    )
    _require(
        spec["limits"]
        == {
            "native_worker_seconds": 1800,
            "max_output_bytes": 268435456,
            "max_requested_output_frames": 8192,
            "max_cases": 128,
        },
        "Bounds changed",
    )
    return spec


def window_memberships(case, clock):
    """Retain the original half-open source window and complete clock identities."""
    rows = clock["frames"]
    count, center = clock["frame_count"], case["center_frame"]
    _require(
        type(count) is int and count == len(rows) and count > 0,
        "Incomplete native clock",
    )
    _require(type(center) is int and 0 <= center < count, "Invalid center")
    start, end = max(0, center - 32), min(count, center + 33)
    selected = rows[start:end]
    _require(
        all(
            type(row["frame"]) is int and row["frame"] == i
            for i, row in enumerate(selected, start)
        ),
        "Native ordinal changed",
    )
    return {k: case[k] for k in ("key", "source_id", "case_id", "center_frame")} | {
        "start_frame": start,
        "end_frame": end,
        "frames": selected,
    }


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def window_unavailable(window):
    previous = None
    geometry = None
    for row in window["frames"]:
        if row.get("corrupt") or row.get("orientation_error"):
            return "corrupt_or_unsupported_orientation"
        current_geometry = (
            row.get("display_size"),
            row.get("source_size"),
            row.get("rotation"),
        )
        if geometry is not None and current_geometry != geometry:
            return "changing_native_geometry"
        geometry = current_geometry
        if not _finite(row.get("time_s")) or type(row.get("pts")) is not int:
            return "unavailable_native_clock"
        try:
            exact = float(row["pts"] * Fraction(row["time_base"]))
        except (KeyError, ValueError, TypeError, ZeroDivisionError):
            return "unavailable_native_time_base"
        if abs(exact - row["time_s"]) > 1e-9:
            return "inconsistent_native_pts"
        if previous is not None and row["time_s"] <= previous:
            return "nonincreasing_native_pts"
        previous = row["time_s"]
    return None


def validate_prediction(raw, window, spec):
    """Refuse output from any different device, recipe, source clock or cut range."""
    from .shuttle import localization_recipe

    expected = {
        "checkpoint_sha256": spec["checkpoint_sha256"],
        "input_size": [512, 288],
        "seq_len": 8,
        "precision": "float16",
        "start_frame": window["start_frame"],
        "end_frame": window["end_frame"],
        "processed_frames": len(window["frames"]),
        "repaired_frames": 0,
    }
    _require(all(raw.get(k) == v for k, v in expected.items()), "Native recipe changed")
    _require(
        isinstance(raw.get("device"), str) and raw["device"].startswith("cuda"),
        "CUDA required",
    )
    _require(
        raw.get("temporal_context_crosses_detected_cuts") is False,
        "Native temporal context crosses cuts",
    )
    _require(
        raw["localization"] == localization_recipe()
        and raw.get("ensemble") == "weighted overlapping windows",
        "Localization recipe changed",
    )
    start, end = window["start_frame"], window["end_frame"]
    ranges = raw["camera_ranges"]
    _require(
        bool(ranges)
        and ranges[0]["start_frame"] == start
        and ranges[-1]["end_frame"] == end,
        "Incomplete camera ranges",
    )
    boundary = start
    for segment in ranges:
        _require(
            segment["start_frame"] == boundary
            and type(segment["end_frame"]) is int
            and boundary < segment["end_frame"] <= end,
            "Invalid camera range partition",
        )
        boundary = segment["end_frame"]
    cuts = raw["cut_frames"]
    _require(
        cuts == sorted(set(cuts))
        and all(type(c) is int and start <= c < end for c in cuts)
        and set(cuts) - {start} == {r["start_frame"] for r in ranges[1:]},
        "Cut partition changed",
    )
    rows = raw["frames"]
    _require(len(rows) == len(window["frames"]), "Incomplete requested output")
    origin = window.get("origin_s", 0)
    for actual, native in zip(rows, window["frames"]):
        _require(
            actual["frame"] == native["frame"]
            and _finite(actual["time_s"])
            and abs(actual["time_s"] - (native["time_s"] - origin)) <= 2e-5,
            "Output native PTS identity changed",
        )
        segment = next(
            r for r in ranges if r["start_frame"] <= actual["frame"] < r["end_frame"]
        )
        _require(
            actual.get("camera_segment_start_frame") == segment["start_frame"],
            "Camera context changed",
        )
        point = actual["shuttle"]
        _require(
            type(point["visible"]) is bool and point.get("repaired") is False,
            "Invalid or repaired observation",
        )
        candidates = point["component_candidates"]
        geometry = native.get("display_size")
        _require(
            isinstance(candidates, list)
            and all(
                _finite(c["x"])
                and _finite(c["y"])
                and (
                    geometry is None
                    or (0 <= c["x"] <= geometry[0] and 0 <= c["y"] <= geometry[1])
                )
                for c in candidates
            ),
            "Invalid observed components",
        )
        _require(point["visible"] == bool(candidates), "Component visibility changed")
        if point["visible"]:
            _require(
                _finite(point["x"])
                and _finite(point["y"])
                and any(
                    c["id"] == point["selected_component_id"]
                    and c["x"] == point["x"]
                    and c["y"] == point["y"]
                    for c in candidates
                ),
                "Selected point is not an observed component",
            )
        else:
            _require(
                point["x"] is None and point["y"] is None,
                "Fabricated missing coordinate",
            )
        _require(
            point.get("selection_context_start_frame", actual["frame"])
            >= segment["start_frame"],
            "Selection context leaked across cut",
        )
    return raw


def score_case(case, prediction, display_size, radius_diagonal=0.005):
    """Score only supported reference states; unknown never becomes absence."""
    _require(radius_diagonal == 0.005, "Fixed scoring radius changed")
    _require(
        len(display_size) == 2 and all(_finite(v) and v > 0 for v in display_size),
        "Invalid display geometry",
    )
    visibility = case["visibility"]
    _require(
        visibility
        in {"visible_localizable", "visible_unlocalizable", "not_visible", "unknown"},
        "Unknown reference state",
    )
    available = prediction is not None
    point = prediction["shuttle"] if available else None
    if available:
        _require(
            prediction["frame"] == case["center_frame"], "Foreign center observation"
        )
        _require(
            type(point["visible"]) is bool and point.get("repaired") is False,
            "Invalid observation",
        )
        _require(
            all(
                _finite(c["x"]) and _finite(c["y"])
                for c in point["component_candidates"]
            ),
            "Invalid component coordinates",
        )
        if point["visible"]:
            _require(
                _finite(point["x"]) and _finite(point["y"]), "Nonfinite selected point"
            )
    if case["visibility"] == "visible_localizable":
        _require(
            _finite(case["x"])
            and _finite(case["y"])
            and 0 <= case["x"] < display_size[0]
            and 0 <= case["y"] < display_size[1]
            and _finite(case["uncertainty_radius"])
            and case["uncertainty_radius"] >= 1,
            "Invalid reference coordinate",
        )
    selected = bool(point and point["visible"])
    result = {
        k: case[k] for k in ("key", "source_id", "scene", "visibility", "difficulty")
    }
    result.update(
        available=available,
        selected_observation=selected,
        component_count=len(point["component_candidates"]) if point else None,
        outcome="unavailable" if not available else "unscored",
        selected_within_fixed=None,
        any_component_within_fixed=None,
        within_uncertainty=None,
        distance_pixels=None,
    )
    if visibility == "visible_localizable" and available:
        radius = math.hypot(*display_size) * radius_diagonal

        def distance(candidate):
            return math.hypot(candidate["x"] - case["x"], candidate["y"] - case["y"])

        result["any_component_within_fixed"] = any(
            distance(c) <= radius + 1e-9 for c in point["component_candidates"]
        )
        result["selected_within_fixed"] = selected and distance(point) <= radius + 1e-9
        result["within_uncertainty"] = (
            selected and distance(point) <= case["uncertainty_radius"] + 1e-9
        )
        result["distance_pixels"] = distance(point) if selected else None
        result["outcome"] = (
            "missing"
            if not selected
            else "within"
            if result["selected_within_fixed"]
            else "displaced"
        )
    elif visibility == "not_visible" and available:
        result["outcome"] = "false_observation" if selected else "absence"
    return result


def summarize(parts):
    support = Counter(p["visibility"] for p in parts)
    outcomes = Counter(p["outcome"] for p in parts)
    localizable = [p for p in parts if p["visibility"] == "visible_localizable"]
    negatives = [p for p in parts if p["visibility"] == "not_visible"]
    within = sum(p["selected_within_fixed"] is True for p in localizable)
    return {
        "cases": len(parts),
        "visibility_support": dict(support),
        "available": sum(p["available"] for p in parts),
        "outcomes": dict(outcomes),
        "localizable_denominator": len(localizable),
        "localizable_outcomes": dict(Counter(p["outcome"] for p in localizable)),
        "within_fixed": within,
        "strict_fixed_agreement": within / len(localizable) if localizable else None,
        "within_original_uncertainty": sum(
            p["within_uncertainty"] is True for p in localizable
        ),
        "any_observed_component_within_fixed": sum(
            p["any_component_within_fixed"] is True for p in localizable
        ),
        "alternate_component_only_within_fixed": sum(
            p["any_component_within_fixed"] is True
            and p["selected_within_fixed"] is False
            for p in localizable
        ),
        "negative_denominator": len(negatives),
        "negative_outcomes": dict(Counter(p["outcome"] for p in negatives)),
        "selected_observations": sum(p["selected_observation"] for p in parts),
        "observed_components": sum(p["component_count"] or 0 for p in parts),
    }


def _consumers():
    package = Path(__file__).resolve().parent
    checkout = package.parents[1]
    files = {
        "backend/badminton/" + p.relative_to(package).as_posix(): p
        for p in package.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    for name in ("scripts/diagnose_shuttle_broadcasts.py", "pyproject.toml", "uv.lock"):
        files[name] = checkout / name
    return files


def _runtime():
    versions = {}
    for name in (
        "av",
        "numpy",
        "Pillow",
        "psutil",
        "torch",
        "torchvision",
        "opencv-python",
        "scenedetect",
    ):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    executable = shutil.which("nvidia-smi")
    gpu = None
    if executable:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=index,name,uuid,driver_version",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        _require(result.returncode == 0, "GPU runtime identity unavailable")
        gpu = result.stdout.strip().splitlines()
    return {
        "python": platform.python_version(),
        "executable": sys.executable,
        "platform": platform.platform(),
        "packages": versions,
        "gpu_identity": gpu,
        "native_environment": {
            name: os.environ.get(name)
            for name in (
                "CUDA_VISIBLE_DEVICES",
                "CUDA_DEVICE_ORDER",
                "CUBLAS_WORKSPACE_CONFIG",
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
            )
        },
    }


def _git_state():
    checkout = Path(__file__).resolve().parents[2]

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(checkout), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    return {
        "commit": git("rev-parse", "HEAD"),
        "tracked_changes": git("status", "--porcelain", "--untracked-files=normal"),
    }


def _truth_seals(root, source_hashes):
    """Inspect only these two source identities, never unrelated research data."""
    data = root / "data/processed"
    database = data / "catalog.sqlite3"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as cx:
        videos = cx.execute(
            "SELECT id,document FROM videos WHERE json_extract(document,'$.sha256') IN (?,?) ORDER BY id",
            tuple(source_hashes),
        ).fetchall()
        ids = [row[0] for row in videos]
        annotations = []
        for video_id in ids:
            annotations.extend(
                cx.execute(
                    "SELECT video_id,revision,document,saved_at FROM annotations WHERE video_id=? ORDER BY revision",
                    (video_id,),
                ).fetchall()
            )
        truth = {"videos": videos, "annotations": annotations}
    files = {}
    for video_id in ids:
        folder = contained(data, data / video_id)
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                files[path.relative_to(data).as_posix()] = file_hash(path)
    return {"catalog_truth_sha256": digest(encoded(truth)), "processed_files": files}


def _source_inputs(packet, assessments, spec):
    for name, expected in (
        ("manifest.json", ASSESSMENT["manifest_sha256"]),
        ("aggregate.json", ASSESSMENT["aggregate_sha256"]),
    ):
        _require(
            file_hash(assessments / name) == expected,
            "Original assessment seal changed",
        )
    aggregate = verify_freeze(assessments, packet, ASSESSMENT["protocol_sha256"])
    _require(
        aggregate["resolved_visibility_support"] == spec["expected"]["visibility"],
        "Resolved support changed",
    )
    resolved = read_json(assessments / "resolved.json")
    cases = [row["assessment"] for row in resolved]
    sources, windows = {}, []
    for source in spec["sources"]:
        sid = source["source_id"]
        folder = contained(packet, packet / "sources" / sid)
        for name, key in (
            ("source.mp4", "source_sha256"),
            ("clock.json", "clock_sha256"),
            ("packet.json", "packet_sha256"),
        ):
            _require(
                file_hash(folder / name) == source[key], "Original source seal changed"
            )
        clock = read_json(folder / "clock.json")
        _require(
            clock["frame_count"] == source["native_frame_count"], "Native count changed"
        )
        metadata = read_json(folder / "returned-metadata.json")
        sources[sid] = {
            "declaration": source,
            "clock": clock,
            "metadata": metadata,
            "source_path": str(folder / "source.mp4"),
        }
        relevant = [case for case in cases if case["source_id"] == sid]
        _require(
            len(relevant) == 64 and [c["case_id"] for c in relevant] == list(range(64)),
            "Source case order changed",
        )
        for case in relevant:
            _require(
                case["center_frame"]
                == case["case_id"] * (clock["frame_count"] - 1) // 63,
                "Original case center changed",
            )
            window = window_memberships(case, clock)
            window["origin_s"] = clock["origin_s"]
            windows.append(window)
    _require(
        len(windows) == 128
        and len({w["key"] for w in windows}) == 128
        and sum(len(w["frames"]) for w in windows) == 8192,
        "Window membership changed",
    )
    return sources, windows, cases


def _require_store(root):
    from .shuttle_diagnostic import _require_store as require

    return require(root)


def prior_proofs(root, output):
    from .shuttle_diagnostic import prior_proofs as proofs

    return proofs(root, output)


def resume_plan(output, receipt_path, receipt_sha256, context_sha):
    from .shuttle_diagnostic import resume_plan as resume

    for terminal in (output / "attempts").glob("*/terminal.json"):
        value = read_json(terminal)
        for seal in value.get("artifact_inventory", []):
            _verified(output, seal)
    return resume(output, receipt_path, receipt_sha256, context_sha)


def _budget(output, spec):
    total = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    _require(
        total <= spec["limits"]["max_output_bytes"], "Output byte budget exhausted"
    )
    return total


def prepare(root, packet, assessments, output, protocol_path=PROTOCOL):
    root = Path(root).resolve()
    packet, assessments = contained(root, packet), contained(root, assessments)
    spec = load_protocol(protocol_path)
    output = _ignored_output(contained(root / ".cache", output))
    _require_store(root)
    sources, windows, _cases = _source_inputs(packet, assessments, spec)
    files = _consumers()
    checkpoint = root / "models/weights/TrackNet_best.pt"
    _require(file_hash(checkpoint) == CHECKPOINT, "Checkpoint seal changed")
    value = {
        "schema_version": 1,
        "root": str(root),
        "packet": str(packet),
        "assessments": str(assessments),
        "protocol": spec,
        "protocol_sha256": file_hash(protocol_path),
        "runtime": _runtime(),
        "git": _git_state(),
        "consumers": {n: file_hash(p) for n, p in sorted(files.items())},
        "checkpoint_sha256": CHECKPOINT,
        "windows": windows,
        "source_input_seals": {
            sid: source["declaration"] for sid, source in sources.items()
        },
        "application_before": _truth_seals(
            root, [s["source_sha256"] for s in spec["sources"]]
        ),
        "reviewed_scene_context": None,
        "reviewed_calibration_context": None,
    }
    _require(
        not value["git"]["tracked_changes"], "Commit native consumers before preparing"
    )
    # Only bounded JSON clock projections are copied; no raw image/media copying.
    publish_json(output / "context.json", value)
    for sid, source in sources.items():
        clock = source["clock"]
        publish_json(
            output / "clock-data" / sid / "timestamps.json",
            [row["time_s"] - clock["origin_s"] for row in clock["frames"]],
        )
    _budget(output, spec)
    return {
        "context": _seal(output, output / "context.json"),
        "cases": len(windows),
        "requested_rows": sum(len(w["frames"]) for w in windows),
    }


def _verify_context(root, output, context_sha, protocol_path):
    path = output / "context.json"
    _require(file_hash(path) == context_sha, "Frozen context changed")
    value = read_json(path)
    spec = load_protocol(protocol_path)
    _require(
        value["root"] == str(root)
        and value["protocol"] == spec
        and value["protocol_sha256"] == file_hash(protocol_path),
        "Frozen protocol/root changed",
    )
    _require(
        value["runtime"] == _runtime() and value["git"] == _git_state(),
        "Consumer runtime/commit changed",
    )
    _require(
        value["consumers"]
        == {n: file_hash(p) for n, p in sorted(_consumers().items())},
        "Recursive consumer seal changed",
    )
    _require(
        file_hash(root / "models/weights/TrackNet_best.pt") == CHECKPOINT,
        "Checkpoint changed",
    )
    sources, windows, cases = _source_inputs(
        Path(value["packet"]), Path(value["assessments"]), spec
    )
    _require(value["windows"] == windows, "Native window identity changed")
    _require(
        value["application_before"]
        == _truth_seals(root, [s["source_sha256"] for s in spec["sources"]]),
        "Application truth/predictions changed",
    )
    for sid, source in sources.items():
        times = read_json(output / "clock-data" / sid / "timestamps.json")
        _require(
            times
            == [
                row["time_s"] - source["clock"]["origin_s"]
                for row in source["clock"]["frames"]
            ],
            "Native timestamp projection changed",
        )
    _budget(output, spec)
    return value, sources, cases


@contextmanager
def native_accounting():
    """Observe existing calls without changing native readers, model or outputs."""
    from . import segments, shuttle, video
    from .vendor.tracknet_model import TrackNet

    counters = Counter()
    phase = ["unknown"]
    original_open = video.open_media
    original_forward = TrackNet.forward
    original_iter = shuttle.iter_frames
    original_scan_iter = segments.iter_frames
    original_infer = shuttle.infer_camera_segment

    class Container:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def decode(self, *args, **kwargs):
            for frame in self.wrapped.decode(*args, **kwargs):
                counters["decoder_frames_total"] += 1
                counters["decoder_frames_" + phase[0]] += 1
                yield frame

    class BackgroundFrame:
        def __init__(self, frame):
            self.frame = frame

        def __getattr__(self, name):
            return getattr(self.frame, name)

        def to_ndarray(self, *args, **kwargs):
            counters["median_background_samples"] += 1
            return self.frame.to_ndarray(*args, **kwargs)

    @contextmanager
    def opened(*args, **kwargs):
        counters["decoder_opens"] += 1
        with original_open(*args, **kwargs) as container:
            yield Container(container)

    def scan_iter(*args, **kwargs):
        before = phase[0]
        phase[0] = "camera_scan"
        try:
            for item in original_scan_iter(*args, **kwargs):
                counters["camera_scan_yields"] += 1
                yield item
        finally:
            phase[0] = before

    def tracker_iter(*args, **kwargs):
        before = phase[0]
        phase[0] = "inference" if before == "inference" else "background"
        try:
            for item in original_iter(*args, **kwargs):
                counters[phase[0] + "_reader_yields"] += 1
                yield (
                    (item[0], item[1], BackgroundFrame(item[2]))
                    if phase[0] == "background"
                    else item
                )
        finally:
            phase[0] = before

    def infer(*args, **kwargs):
        before = phase[0]
        phase[0] = "inference"
        try:
            yield from original_infer(*args, **kwargs)
        finally:
            phase[0] = before

    def forward(model, tensor, *args, **kwargs):
        counters["model_calls"] += 1
        counters["model_sequence_slots"] += 8
        counters["model_background_slots"] += 1
        _require(
            tuple(tensor.shape)[1:] == (27, 288, 512), "Native model shape changed"
        )
        return original_forward(model, tensor, *args, **kwargs)

    with ExitStack() as stack:
        for target, name, replacement in (
            (video, "open_media", opened),
            (segments, "iter_frames", scan_iter),
            (shuttle, "iter_frames", tracker_iter),
            (shuttle, "infer_camera_segment", infer),
            (TrackNet, "forward", forward),
        ):
            stack.enter_context(patch.object(target, name, replacement))
        yield counters


def _native_video(root, source, sid):
    clock, metadata = source["clock"], source["metadata"]
    first = clock["frames"][0]
    width, height = first["display_size"]
    return {
        "id": sid,
        "path": contained(root, source["source_path"]).relative_to(root).as_posix(),
        "sha256": source["declaration"]["source_sha256"],
        "width": width,
        "height": height,
        "rotation": first["rotation"],
        "frame_count": clock["frame_count"],
        "fps": metadata["fps"],
        "source_start_s": clock["origin_s"],
        "duration_s": max(
            clock["frames"][-1]["time_s"] - clock["origin_s"], metadata["duration"]
        ),
    }


def run(
    root,
    output,
    context_sha,
    *,
    protocol_path=PROTOCOL,
    resume_receipt=None,
    resume_sha256=None,
):
    began = time.perf_counter()
    for name in CREDENTIALS:
        os.environ.pop(name, None)
    root, output = Path(root).resolve(), Path(output).resolve()
    contained(root / ".cache", output)
    shared = _require_store(root)
    context, sources, _cases = _verify_context(root, output, context_sha, protocol_path)
    spec = context["protocol"]
    proofs = prior_proofs(root, output)
    reusable, history, previous_elapsed = resume_plan(
        output, resume_receipt, resume_sha256, context_sha
    )
    _require(
        set(reusable).issubset({w["key"] for w in context["windows"]}),
        "Foreign resume case",
    )
    _require(previous_elapsed < 1800, "Cumulative native time exhausted")
    import torch
    import torchvision  # noqa: F401  # Initialize before any threaded decoder.

    from .jobs import JobCancelled, run_local_job
    from .shuttle import track_shuttle
    from .storage import Store

    _require(torch.cuda.is_available(), "CUDA required; no CPU fallback")
    attempt = output / "attempts" / uuid4().hex
    process = psutil.Process()
    status, job_id, index_entry = "failed", None, None
    completed = []
    all_records = dict(reusable)

    def bounded():
        if previous_elapsed + time.perf_counter() - began >= 1800:
            raise JobCancelled("Cumulative native runtime bound reached")
        _budget(output, spec)

    def task(identifier, report):
        nonlocal job_id, index_entry
        job_id = identifier
        last_progress = -1.0

        def report_progress(value):
            nonlocal last_progress
            if value - last_progress >= 0.005 or value == 1:
                report(value)
                last_progress = value

        publish_json(
            attempt / "admission.json",
            {
                "job_id": identifier,
                "host_id": platform.node(),
                "context_sha256": context_sha,
                "shared_store": str(shared / "catalog.sqlite3"),
                "process": {
                    "pid": process.pid,
                    "creation_time": process.create_time(),
                    "cwd": process.cwd(),
                    "command": process.cmdline(),
                },
                "prior_terminal_proofs": proofs,
            },
        )
        for ordinal, window in enumerate(context["windows"]):
            bounded()
            key = window["key"]
            if key in reusable:
                record, seal = reusable[key]
                _require(
                    record["window"] == window and record["raw_prediction"] is not None,
                    "Only successful unchanged windows are reusable",
                )
                validate_prediction(
                    read_json(_verified(output, record["raw_prediction"])), window, spec
                )
            else:
                folder = attempt / "windows" / digest(key.encode())
                raw_path = folder / "raw-prediction.json"
                record = {
                    "clip": key,
                    "key": key,
                    "context_sha256": context_sha,
                    "window": window,
                    "raw_prediction": None,
                    "unavailable_reason": window_unavailable(window),
                    "accounting": {},
                }
                if record["unavailable_reason"] is None:
                    video = _native_video(
                        root, sources[window["source_id"]], window["source_id"]
                    )
                    accounting = Counter()
                    try:
                        with native_accounting() as accounting:

                            def progress(value):
                                bounded()
                                report_progress((ordinal + value) / 128)

                            track_shuttle(
                                video,
                                root,
                                output / "clock-data",
                                window["start_frame"],
                                window["end_frame"],
                                progress,
                                raw_path,
                                annotations={},
                                input_size=(512, 288),
                            )
                        record["accounting"] = dict(accounting)
                        raw = validate_prediction(read_json(raw_path), window, spec)
                        _require(
                            raw["video_sha256"] == video["sha256"],
                            "Output source changed",
                        )
                        record["raw_prediction"] = _seal(output, raw_path)
                    except (KeyboardInterrupt, JobCancelled):
                        record["accounting"] = dict(accounting)
                        record["unavailable_reason"] = "native_interrupted"
                        publish_json(folder / "complete.json", record)
                        all_records[key] = (
                            record,
                            _seal(output, folder / "complete.json"),
                        )
                        raise
                    except Exception as exc:
                        record["accounting"] = dict(accounting)
                        record["unavailable_reason"] = (
                            "native_refusal:" + type(exc).__name__
                        )
                publish_json(folder / "complete.json", record)
                seal = _seal(output, folder / "complete.json")
            completed.append(seal)
            all_records[key] = (record, seal)
            report_progress((ordinal + 1) / 128)
        _verify_context(root, output, context_sha, protocol_path)
        index = {
            "schema_version": 1,
            "context_sha256": context_sha,
            "planned_cases": 128,
            "requested_rows": 8192,
            "completed_clips": completed,
            "scored": False,
        }
        publish_json(attempt / "output-index.json", index)
        index_entry = _seal(output, attempt / "output-index.json")
        return {
            "output_index": index_entry,
            "completed_windows": len(completed),
            "scored": False,
        }

    try:
        result = run_local_job(
            Store(shared), "research-shuttle-broadcast-native", None, task
        )
        status = "completed"
        return result
    except (KeyboardInterrupt, JobCancelled):
        status = "interrupted"
        raise
    finally:
        # Even a refusal/timeout leaves all 128 planned cases in the raw seal.
        records = []
        for window in context["windows"]:
            if window["key"] in all_records:
                records.append(
                    {"key": window["key"], "complete": all_records[window["key"]][1]}
                )
            else:
                records.append(
                    {
                        "key": window["key"],
                        "complete": None,
                        "unavailable_reason": "not_completed_in_bounded_attempt",
                    }
                )
        preservation = {"verified": status == "completed", "failure": None}
        if job_id is not None and status != "completed":
            try:
                _verify_context(root, output, context_sha, protocol_path)
                preservation["verified"] = True
            except Exception as exc:
                preservation["failure"] = type(exc).__name__
        terminal = {
            "schema_version": 1,
            "context_sha256": context_sha,
            "status": status,
            "job_id": job_id,
            "elapsed_s": round(time.perf_counter() - began, 6),
            "completed_clips": [
                seal
                for record, seal in all_records.values()
                if record["raw_prediction"] is not None
            ],
            "case_availability": records,
            "prior_terminal_seals": history,
            "output_index": index_entry,
            "input_preservation": preservation,
            "artifact_inventory": [
                _seal(output, path)
                for path in sorted(output.rglob("*"))
                if path.is_file()
            ],
        }
        publish_json(attempt / "terminal.json", terminal)
        print(
            encoded(
                {
                    "terminal": _seal(output, attempt / "terminal.json"),
                    "status": status,
                    "job_id": job_id,
                }
            ).decode(),
            flush=True,
        )


def interpret(
    root,
    output,
    context_sha,
    terminal,
    terminal_sha,
    destination,
    *,
    protocol_path=PROTOCOL,
):
    root, output = Path(root).resolve(), Path(output).resolve()
    contained(root / ".cache", output)
    _require_store(root)
    context, sources, cases = _verify_context(root, output, context_sha, protocol_path)
    proofs = prior_proofs(root, output)
    terminal = contained(output / "attempts", terminal)
    entry = {"path": terminal.relative_to(output).as_posix(), "sha256": terminal_sha}
    receipt = read_json(_verified(output, entry))
    _require(
        isinstance(receipt.get("artifact_inventory"), list),
        "Raw output inventory missing",
    )
    for seal in receipt["artifact_inventory"]:
        _verified(output, seal)
    admission = terminal.with_name("admission.json")
    admission_seal = _seal(output, admission)
    proof = next((p for p in proofs if p["admission"] == admission_seal), None)
    _require(
        proof is not None
        and receipt["context_sha256"] == context_sha
        and receipt["job_id"] == read_json(admission)["job_id"]
        and receipt["status"] == proof["store_status"],
        "Terminal Store binding unavailable",
    )
    availability = receipt["case_availability"]
    _require(
        [a["key"] for a in availability] == [w["key"] for w in context["windows"]],
        "Incomplete raw case denominator",
    )
    parts, private_cases, accounting = [], [], Counter()
    groups = {
        name: defaultdict(list)
        for name in ("source_id", "scene", "visibility", "difficulty")
    }
    case_index = {c["key"]: c for c in cases}
    for window, availability_row in zip(context["windows"], availability):
        case = case_index[window["key"]]
        prediction = None
        reason = availability_row.get("unavailable_reason")
        if availability_row["complete"] is not None:
            record = read_json(_verified(output, availability_row["complete"]))
            _require(
                record["key"] == case["key"]
                and record["window"] == window
                and record["context_sha256"] == context_sha,
                "Raw case/source pairing changed",
            )
            reason = record["unavailable_reason"]
            if record["raw_prediction"] is not None:
                raw = validate_prediction(
                    read_json(_verified(output, record["raw_prediction"])),
                    window,
                    context["protocol"],
                )
                _require(
                    raw["video_sha256"]
                    == sources[case["source_id"]]["declaration"]["source_sha256"],
                    "Raw source changed",
                )
                prediction = next(
                    row for row in raw["frames"] if row["frame"] == case["center_frame"]
                )
        source = sources[case["source_id"]]
        dimensions = source["clock"]["frames"][case["center_frame"]]["display_size"]
        part = score_case(case, prediction, dimensions)
        parts.append(part)
        private_cases.append({**part, "unavailable_reason": reason})
        for name in groups:
            values = case[name] if name == "difficulty" else [case[name]]
            for value in values:
                groups[name][value].append(part)
    _verify_context(root, output, context_sha, protocol_path)
    # Count every actual attempt, including failed/partial windows and reused
    # outputs; successful reuse adds no second set of native calls.
    for seal in receipt["artifact_inventory"]:
        path = Path(seal["path"])
        if (
            len(path.parts) == 5
            and path.parts[0] == "attempts"
            and path.parts[2] == "windows"
            and path.name == "complete.json"
        ):
            accounting.update(read_json(_verified(output, seal))["accounting"])
    summary = summarize(parts)
    _require(
        summary["cases"] == 128
        and summary["localizable_denominator"] == 37
        and summary["negative_denominator"] == 5,
        "Interpretation denominator changed",
    )
    destination = _ignored_output(contained(output, destination))
    report = {
        "schema_version": 1,
        "scope": "Agent-labeled development agreement; not expert or independent annotation accuracy",
        "context_sha256": context_sha,
        "terminal": entry,
        "terminal_proofs": proofs,
        "summary": summary,
        "strata": {
            name: {value: summarize(rows) for value, rows in sorted(values.items())}
            for name, values in groups.items()
        },
        "actual_accounting": dict(accounting),
        "requested_output_rows": 8192,
        "unavailable_causes": dict(
            Counter(
                p["unavailable_reason"] for p in private_cases if not p["available"]
            )
        ),
        "cases": private_cases,
        "eligibility": ELIGIBILITY,
        "limitations": context["protocol"]["limitations"],
    }
    publish_json(destination, report)
    _budget(output, context["protocol"])
    return {"report": _seal(output, destination), "summary": summary}
