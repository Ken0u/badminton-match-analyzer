"""One frozen offline development hypothesis; no application defaults change."""

from __future__ import annotations

import argparse
import importlib.metadata
import io
import itertools
import math
import os
import platform
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path
from uuid import uuid4

import numpy as np
import psutil

from . import shuttle_heatmaps as heatmaps
from . import shuttle_resolution as comparison
from . import shuttle_validation as audit
from .jobs import run_local_job
from .shuttle import locate_shuttle
from .shuttle_diagnostic import _require_store
from .storage import Store

CODE_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = CODE_ROOT / "data/manifests/shuttle_threshold_protocol_v1.json"
PROTOCOL_SHA = "b9b749920189f49cc584f3111dfb6e38038e454d6785b69db2d408fccdd32b61"
STATES = ("visible", "not_visible", "unknown", "visible_unlocalizable")


def protocol():
    if audit.file_hash(PROTOCOL) != PROTOCOL_SHA:
        raise ValueError("Fixed threshold protocol changed")
    return heatmaps.read(PROTOCOL)


def unique(items, key="id"):
    result = {item[key]: item for item in items}
    if len(result) != len(items):
        raise ValueError("Duplicate frozen membership")
    return result


def runtime():
    return {
        "python": platform.python_version(),
        "libraries": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "opencv-python", "psutil", "av", "Pillow")
        },
    }


def consumers(root):
    paths = [
        *sorted((CODE_ROOT / "backend/badminton").rglob("*.py")),
        CODE_ROOT / "backend/badminton/model_manifest.json",
        CODE_ROOT / "scripts/compare_shuttle_threshold.py",
        PROTOCOL,
    ]
    return {p.relative_to(CODE_ROOT).as_posix(): audit.seal(root, p) for p in paths}


def source_bundle(root, capture, report_path, spec):
    """Verify immutable capture envelopes and file seals, without new predictions."""
    graph = {}

    def read(base, entry):
        raw = audit.sealed_bytes(base, entry)
        path = audit.inside(base, entry["path"])
        graph[path.relative_to(root).as_posix()] = entry["sha256"]
        return audit.read_json(raw)

    def fixed(base, name, digest):
        return read(base, {"path": name, "sha256": digest})

    experiment = fixed(capture, "experiment.json", spec["capture_experiment_sha256"])
    report = fixed(
        capture,
        report_path.relative_to(capture).as_posix(),
        spec["capture_report_sha256"],
    )
    if report["control_gate"] != {
        "compatible": True,
        "differences": [],
        "native_rows": spec["expected"]["native_rows"],
        "views": spec["expected"]["views"],
    }:
        raise ValueError("Original complete control gate is unavailable")
    if (
        report["experiment_sha256"] != spec["capture_experiment_sha256"]
        or report["protocol_sha256"] != experiment["protocol_sha256"]
        or report["output_index"]["sha256"] != spec["capture_index_sha256"]
        or report["native_terminal"]["sha256"] != spec["capture_terminal_sha256"]
        or experiment["labels"]["sha256"] != spec["labels_sha256"]
        or experiment["baseline"]["sha256"] != spec["baseline_sha256"]
    ):
        raise ValueError("Original capture identity changed")
    original_protocol = fixed(capture, "protocol.json", experiment["protocol_sha256"])
    index = read(capture, report["output_index"])
    terminal = read(capture, report["native_terminal"])
    labels = read(root, experiment["labels"])
    baseline = read(root, experiment["baseline"])
    packet = read(root, experiment["packet"])
    if (
        terminal["status"] != "completed"
        or terminal["context_sha256"] != spec["capture_experiment_sha256"]
        or terminal["output_index"] != report["output_index"]
        or terminal["completed_clips"] != index["completed_clips"]
        or index["context_sha256"] != spec["capture_experiment_sha256"]
        or index["protocol_sha256"] != experiment["protocol_sha256"]
        or index["expected"] != original_protocol["expected"]
        or packet["cases"] != experiment["cases"]
        or labels["packet_sha256"] != experiment["packet"]["sha256"]
    ):
        raise ValueError("Original terminal, index or source membership changed")
    cases = unique(experiment["cases"])
    truth = unique(labels["cases"])
    views = unique(experiment["views"])
    old_cases = unique(report["cases"])
    if set(cases) != set(truth) or set(cases) != set(old_cases):
        raise ValueError("Original case/label membership changed")
    captures, rows_by_case, rows_count = {}, {}, 0
    for entry in index["completed_clips"]:
        record = read(capture, entry)
        view = views[record["clip"]]
        if (
            record["view"] != view
            or record["context_sha256"] != spec["capture_experiment_sha256"]
            or set(record["heatmaps"]) != set(view["case_ids"])
        ):
            raise ValueError("Original view ownership changed")
        run = read(capture, record["run"])
        first, last = view["start_frame"], view["end_frame"]
        rows = run["frames"]
        if (
            run["start_frame"] != first
            or run["end_frame"] != last
            or [r["frame"] for r in rows] != list(range(first, last))
            or any(not audit.finite(r["time_s"]) for r in rows)
            or any(a["time_s"] >= b["time_s"] for a, b in itertools.pairwise(rows))
            or len({r["camera_segment_start_frame"] for r in rows}) != 1
            or rows[0]["camera_segment_start_frame"] > first
        ):
            raise ValueError("Native frame/time/camera coverage changed")
        rows_count += len(rows)
        for key, item in record["heatmaps"].items():
            case = cases[key]
            row = rows[case["frame"] - first]
            if (
                key in captures
                or item["case"] != case
                or item["view_id"] != view["id"]
                or case["video_id"] != view["video_id"]
                or item["time_s"] != row["time_s"]
                or row["frame"] != case["frame"]
            ):
                raise ValueError("Native center identity changed")
            array = item["array"]
            path = audit.sealed_path(capture, array)
            graph[path.relative_to(root).as_posix()] = array["sha256"]
            captures[key], rows_by_case[key] = item, row
    if (
        len(cases) != spec["expected"]["cases"]
        or len(views) != spec["expected"]["views"]
        or len(index["completed_clips"]) != len(views)
        or rows_count != spec["expected"]["native_rows"]
        or set(captures) != set(cases)
    ):
        raise ValueError("Incomplete original capture membership")
    frozen_cases = []
    for key, case in cases.items():
        assessment = truth[key]
        label = assessment["label"]
        if label["state"] not in STATES:
            raise ValueError("Unsupported source visibility state")
        for dimension in ("width", "height"):
            if type(case[dimension]) is not int or case[dimension] <= 0:
                raise ValueError("Invalid source display geometry")
        if label["state"] == "visible" and not (
            all(audit.finite(label[k]) for k in ("x", "y", "uncertainty_px"))
            and 0 <= label["x"] < case["width"]
            and 0 <= label["y"] < case["height"]
            and label["uncertainty_px"] >= 0
        ):
            raise ValueError("Invalid source coordinate reference")
        frame_count = baseline["evidence"]["catalogs"][case["video_id"]]["snapshot"][
            "video"
        ]["frame_count"]
        uniform = {math.floor((i + 0.5) * frame_count / 25) for i in range(25)}
        groups = [
            "all",
            "source:" + case["video_id"],
            "state:" + label["state"],
            "selection:" + ("uniform" if case["frame"] in uniform else "known_gap"),
            "disagreement:" + str(any(assessment["disagreement"].values())).lower(),
            *["difficulty:" + tag for tag in label["difficulty"]],
        ]
        frozen_cases.append({"case": case, "label": label, "groups": groups})
    counts = Counter(c["label"]["state"] for c in frozen_cases)
    if {state: counts[state] for state in STATES} != spec["expected"]["states"]:
        raise ValueError("Original state denominators changed")
    return graph, frozen_cases, captures, rows_by_case


def freeze(root, capture, report, output):
    _require_store(root)
    spec = protocol()
    graph, cases, _, _ = source_bundle(root, capture, report, spec)
    output = audit.ignored_output(root, output)
    value = {
        "schema_version": 1,
        "protocol_sha256": PROTOCOL_SHA,
        "code_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=CODE_ROOT, text=True
        ).strip(),
        "consumers": consumers(root),
        "runtime": runtime(),
        "capture": capture.relative_to(root).as_posix(),
        "original_report": report.relative_to(root).as_posix(),
        "input_files": graph,
        "cases": cases,
    }
    heatmaps.publish(output / "experiment.json", value)
    load(root, output, audit.file_hash(output / "experiment.json"))
    return {"experiment_sha256": audit.file_hash(output / "experiment.json")}


def load(root, output, expected):
    value = heatmaps.read(
        audit.sealed_path(output, {"path": "experiment.json", "sha256": expected})
    )
    if (
        value["schema_version"] != 1
        or value["protocol_sha256"] != PROTOCOL_SHA
        or value["consumers"] != consumers(root)
        or value["runtime"] != runtime()
    ):
        raise ValueError("Frozen comparison code/protocol/runtime changed")
    return value


def read_heatmap(capture, entry, spec):
    raw = audit.sealed_bytes(capture, entry)
    stream = io.BytesIO(raw)
    heat = np.load(stream, allow_pickle=False)
    if stream.tell() != len(raw):
        raise ValueError("Unexpected trailing heatmap bytes")
    return heatmaps.validate_heatmap(heat, shape=tuple(spec["heatmap_shape"]))


def compute(root, context, spec, progress):
    """Finish every control reconstruction before making any alternate prediction."""
    frozen_cases = context["cases"]
    raw = [
        {
            "id": c["case"]["id"],
            "control": None,
            "candidate": None,
            "original_motion": None,
        }
        for c in frozen_cases
    ]
    try:
        capture = audit.inside(root, context["capture"])
        graph, cases, captures, rows = source_bundle(
            root, capture, audit.inside(root, context["original_report"]), spec
        )
        if graph != context["input_files"] or cases != frozen_cases:
            raise ValueError("Frozen source context changed")
        for offset, item in enumerate(frozen_cases):
            case = item["case"]
            key = case["id"]
            heat = read_heatmap(capture, captures[key]["array"], spec)
            control = locate_shuttle(
                heat, case["width"], case["height"], spec["control_threshold"]
            )
            for field in ("component_candidates", "components", "largest_component_id"):
                if comparison.compare_rows(
                    rows[key]["shuttle"][field],
                    control[field],
                    spec["confidence_absolute_tolerance"],
                ):
                    raise ValueError("Original center components changed")
            raw[offset].update(control=control, original_motion=rows[key]["shuttle"])
            progress(0.5 * (offset + 1) / len(raw))
    except (ValueError, OSError, KeyError, IndexError):
        return {
            "compatible": False,
            "reason": "source_or_control_incompatible",
            "cases": [{**r, "control": None, "original_motion": None} for r in raw],
        }
    for offset, item in enumerate(frozen_cases):
        case = item["case"]
        heat = read_heatmap(capture, captures[case["id"]]["array"], spec)
        raw[offset]["candidate"] = locate_shuttle(
            heat, case["width"], case["height"], spec["candidate_threshold"]
        )
        progress(0.5 + 0.5 * (offset + 1) / len(raw))
    # Recheck all inputs after computing; a mixed-source result cannot be scored.
    graph, cases, _, _ = source_bundle(
        root, capture, audit.inside(root, context["original_report"]), spec
    )
    if graph != context["input_files"] or cases != frozen_cases:
        raise ValueError("Source context changed during comparison")
    return {"compatible": True, "reason": None, "cases": raw}


def run(root, output, expected):
    shared = _require_store(root)
    context, spec = load(root, output, expected), protocol()
    # Exclusive attempt reservation prevents a second process or a timeout from
    # silently rerunning this scientific context. Preserve failures for recovery.
    (output / "attempts").mkdir(exist_ok=False)
    attempt = output / "attempts" / uuid4().hex
    process = psutil.Process()
    identity = {
        "pid": process.pid,
        "creation_time": process.create_time(),
        "cwd": process.cwd(),
        "command": process.cmdline(),
    }
    started = time.monotonic()
    job_id, result_entry, status = None, None, "failed"

    def task(identifier, progress):
        nonlocal job_id, result_entry
        job_id = identifier
        heatmaps.publish(
            attempt / "admission.json",
            {"process": identity, "job_id": identifier, "context_sha256": expected},
        )
        value = compute(root, context, spec, progress)
        if time.monotonic() - started > spec["maximum_comparison_seconds"]:
            raise ValueError("Fixed comparison runtime budget exceeded")
        load(root, output, expected)
        value["context_sha256"] = expected
        heatmaps.publish(attempt / "raw.json", value)
        result_entry = audit.seal(output, attempt / "raw.json")
        return {"result": result_entry, "compatible": value["compatible"]}

    try:
        result = run_local_job(
            Store(shared), "research-shuttle-fixed-threshold", None, task
        )
        status = "completed"
        return result
    finally:
        heatmaps.publish(
            attempt / "terminal.json",
            {
                "schema_version": 1,
                "status": status,
                "process": identity,
                "job_id": job_id,
                "context_sha256": expected,
                "raw": result_entry,
                "elapsed_s": time.monotonic() - started,
            },
        )


def outcome(point, case, label, tolerance):
    if point is None:
        return {
            "outcome": "unavailable",
            "components": None,
            "any_component_agrees": None,
            "uncertainty_agrees": None,
        }
    if (
        type(point["visible"]) is not bool
        or type(point["components"]) is not int
        or point["components"] != len(point["component_candidates"])
        or point["components"] < 0
        or point["visible"] != bool(point["components"])
    ):
        raise ValueError("Invalid comparison observation")
    for observed in [
        *point["component_candidates"],
        *([point] if point["visible"] else []),
    ]:
        if not (
            all(audit.finite(observed[k]) for k in ("x", "y", "confidence"))
            and 0 <= observed["x"] < case["width"]
            and 0 <= observed["y"] < case["height"]
            and 0 <= observed["confidence"] <= 1
        ):
            raise ValueError("Invalid observed component coordinates")
    base = {"components": point["components"]}
    state = label["state"]
    if state == "not_visible":
        return {
            **base,
            "outcome": "false_observation" if point["visible"] else "absence",
            "any_component_agrees": None,
            "uncertainty_agrees": None,
        }
    if state != "visible":
        return {
            **base,
            "outcome": "observed_unscored" if point["visible"] else "absent_unscored",
            "any_component_agrees": None,
            "uncertainty_agrees": None,
        }
    radius = tolerance * math.hypot(case["width"], case["height"])

    def distance(p):
        return math.hypot(p["x"] - label["x"], p["y"] - label["y"])

    visible = point["visible"]
    return {
        **base,
        "outcome": "localized"
        if visible and distance(point) <= radius
        else "displaced"
        if visible
        else "missing",
        "any_component_agrees": any(
            distance(p) <= radius for p in point["component_candidates"]
        ),
        "uncertainty_agrees": visible and distance(point) <= label["uncertainty_px"],
    }


def summarize(cases):
    result = {
        "cases": len(cases),
        "states": {s: sum(c["state"] == s for c in cases) for s in STATES},
        "variants": {},
    }
    for variant in ("control", "candidate", "original_motion"):
        values = [c[variant] for c in cases]
        result["variants"][variant] = {
            "outcomes": dict(sorted(Counter(v["outcome"] for v in values).items())),
            "available": sum(v["outcome"] != "unavailable" for v in values),
            "unavailable": sum(v["outcome"] == "unavailable" for v in values),
            "observed_components": sum(
                v["components"] for v in values if v["components"] is not None
            ),
            "visible_reference_support": result["states"]["visible"],
            "available_visible_support": sum(
                c["state"] == "visible" and c[variant]["outcome"] != "unavailable"
                for c in cases
            ),
            "any_component_agrees": sum(
                v["any_component_agrees"] is True for v in values
            ),
            "uncertainty_agrees": sum(v["uncertainty_agrees"] is True for v in values),
        }
    result["paired_visible_transitions"] = dict(
        sorted(
            Counter(
                c["control"]["outcome"] + "->" + c["candidate"]["outcome"]
                for c in cases
                if c["state"] == "visible"
            ).items()
        )
    )
    return result


def interpret(root, output, expected, terminal_path, terminal_sha):
    shared = _require_store(root)
    context, spec = load(root, output, expected), protocol()
    terminal = heatmaps.read(
        audit.sealed_path(
            output,
            {
                "path": terminal_path.relative_to(output).as_posix(),
                "sha256": terminal_sha,
            },
        )
    )
    identity = terminal["process"]
    try:
        if psutil.Process(identity["pid"]).create_time() == identity["creation_time"]:
            raise ValueError("Original comparison lifetime remains present")
    except psutil.NoSuchProcess:
        pass
    store = Store(shared)
    try:
        job = store.job(terminal["job_id"])
    except KeyError as exc:
        raise ValueError("Original comparison Store registration is missing") from exc
    if (
        terminal["status"] != "completed"
        or terminal["context_sha256"] != expected
        or not job
        or job["status"] != "completed"
        or job["kind"] != "research-shuttle-fixed-threshold"
        or job["summary"]["result"] != terminal["raw"]
        or job.get("owner_pid") != identity["pid"]
        or job.get("owner_started") != identity["creation_time"]
        or not audit.finite(terminal["elapsed_s"])
        or not 0 <= terminal["elapsed_s"] <= spec["maximum_comparison_seconds"]
    ):
        raise ValueError("Matching completed comparison and Store proof required")
    raw = heatmaps.read(audit.sealed_path(output, terminal["raw"]))
    records = unique(raw["cases"])
    if (
        type(raw["compatible"]) is not bool
        or raw["compatible"] != job["summary"]["compatible"]
        or raw["context_sha256"] != expected
        or set(records) != {c["case"]["id"] for c in context["cases"]}
    ):
        raise ValueError("Comparison output membership changed")
    if raw["compatible"]:
        graph, cases, _, _ = source_bundle(
            root,
            audit.inside(root, context["capture"]),
            audit.inside(root, context["original_report"]),
            spec,
        )
        if graph != context["input_files"] or cases != context["cases"]:
            raise ValueError("Source context changed before interpretation")

    def task(_identifier, progress):
        groups = defaultdict(
            list,
            {
                "all": [],
                **{"state:" + state: [] for state in STATES},
                **{
                    "difficulty:" + tag: [] for tag in audit.PROTOCOL["difficulty_tags"]
                },
            },
        )
        scored = []
        for item in context["cases"]:
            case, label = item["case"], item["label"]
            record = records[case["id"]]
            value = {
                "id": case["id"],
                "state": label["state"],
                **{
                    variant: outcome(
                        record[variant] if raw["compatible"] else None,
                        case,
                        label,
                        spec["diagonal_tolerance"],
                    )
                    for variant in ("control", "candidate", "original_motion")
                },
            }
            scored.append(value)
            for group in item["groups"]:
                groups[group].append(value)
        summary = summarize(scored)
        control = summary["variants"]["control"]["outcomes"]
        candidate = summary["variants"]["candidate"]["outcomes"]
        advance = (
            raw["compatible"]
            and candidate.get("localized", 0) > control.get("localized", 0)
            and candidate.get("false_observation", 0)
            <= control.get("false_observation", 0)
            and candidate.get("displaced", 0) <= control.get("displaced", 0)
            and candidate.get("unavailable", 0) == control.get("unavailable", 0) == 0
        )
        report = {
            "schema_version": 1,
            "context_sha256": expected,
            "terminal_sha256": terminal_sha,
            "compatible": raw["compatible"],
            "summary": summary,
            "groups": {
                key: summarize(values) for key, values in sorted(groups.items())
            },
            "cases": scored,
            "disposition": "separate_broader_experiment_only"
            if advance
            else "rejected"
            if raw["compatible"]
            else "incompatible_unscored",
            "eligibility": spec["eligibility"],
            "limitations": spec["limitations"],
        }
        load(root, output, expected)
        audit.sealed_path(output, terminal["raw"])
        destination = output / "interpretations" / uuid4().hex / "report.json"
        heatmaps.publish(destination, report)
        progress(1)
        return {
            "report": audit.seal(output, destination),
            "summary": summary,
            "disposition": report["disposition"],
        }

    return run_local_job(
        store, "research-shuttle-fixed-threshold-interpretation", None, task
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run", "interpret"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--control-report", type=Path)
    parser.add_argument("--experiment-sha256")
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--terminal-sha256")
    args = parser.parse_args(argv)
    if any(
        os.environ.get(name)
        for name in (
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "AGENT_PROJECT_TOKEN",
            "OPENAI_API_KEY",
            "CODEX_API_KEY",
        )
    ):
        parser.error("Clear account variables before research imports/execution")
    root, output = args.root.resolve(), args.output.resolve()
    if not output.is_relative_to(root / ".cache"):
        parser.error("Use a fresh ignored output under the original root")
    if args.mode == "freeze":
        if (
            not args.capture
            or not args.control_report
            or any((args.experiment_sha256, args.terminal, args.terminal_sha256))
        ):
            parser.error("Freeze requires only capture and original control report")
        result = freeze(
            root, args.capture.resolve(), args.control_report.resolve(), output
        )
    elif args.mode == "run":
        if not args.experiment_sha256 or any(
            (args.capture, args.control_report, args.terminal, args.terminal_sha256)
        ):
            parser.error("Run requires only the frozen experiment hash")
        result = run(root, output, args.experiment_sha256)
    else:
        if (
            not all((args.experiment_sha256, args.terminal, args.terminal_sha256))
            or args.capture
            or args.control_report
        ):
            parser.error(
                "Interpret requires frozen experiment and sealed exited terminal"
            )
        result = interpret(
            root,
            output,
            args.experiment_sha256,
            args.terminal.resolve(),
            args.terminal_sha256,
        )
    print(audit.encoded(result).decode(), end="")
