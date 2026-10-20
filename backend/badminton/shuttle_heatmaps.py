"""Frozen raw-response diagnostic; never produces replacement predictions."""

from __future__ import annotations

import argparse
import io
import math
import os
import platform
import time
from collections import Counter, defaultdict
from pathlib import Path
from uuid import uuid4

import numpy as np
import psutil

from . import shuttle_resolution as comparison
from . import shuttle_validation as audit
from .shuttle_diagnostic import (
    _require_store,
    prior_proofs,
    resume_plan,
    terminal_binding,
)

PROTOCOL = (
    Path(__file__).resolve().parents[2]
    / "data/manifests/shuttle_heatmap_protocol_v1.json"
)
PROTOCOL_SHA = "d33208aa15a34bf2c5ac7a0d72cd2796b358655658279c1d8091c6bef8aa5f6a"


def read(path):
    return audit.read_json(Path(path).read_bytes())


def sealed(root, entry):
    return audit.sealed_path(root, entry)


def publish_bytes(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".pending-" + uuid4().hex)
    with pending.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(pending, path)
    pending.unlink()


def publish(path, value):
    publish_bytes(path, audit.encoded(value))


def protocol():
    if audit.file_hash(PROTOCOL) != PROTOCOL_SHA:
        raise ValueError("Fixed heatmap protocol changed")
    return read(PROTOCOL)


def consumers(root):
    result = comparison.consumer_files(root)
    script = (
        Path(__file__).resolve().parents[2] / "scripts/diagnose_shuttle_heatmaps.py"
    )
    result["scripts/diagnose_shuttle_heatmaps.py"] = audit.seal(root, script)
    return dict(sorted(result.items()))


def inputs(root, packet, labels, baseline, spec):
    result = comparison.verify_inputs(root, packet, labels, baseline, spec)
    source_packet, _, frozen, original, runs, _ = result
    views = comparison.plan_views(source_packet["cases"], original["evidence"], runs)
    actual = {
        "cases": len(source_packet["cases"]),
        "views": len(views),
        "native_view_rows": sum(v["end_frame"] - v["start_frame"] for v in views),
        "states": {
            state: sum(c["label"]["state"] == state for c in frozen["cases"])
            for state in spec["expected"]["states"]
        },
    }
    if actual != spec["expected"]:
        raise ValueError("Frozen development membership/denominators changed")
    return result, views


def freeze(root, packet, labels, baseline, output):
    root = Path(root).resolve()
    _require_store(root)
    spec = protocol()
    data, views = inputs(root, packet, labels, baseline, spec)
    codes, runtime = consumers(root), comparison.runtime_snapshot()
    output = audit.ignored_output(root, output)
    for name, entry in codes.items():
        publish_bytes(output / "consumer" / name, audit.sealed_bytes(root, entry))
    publish_bytes(output / "protocol.json", PROTOCOL.read_bytes())
    experiment = {
        "schema_version": 1,
        "protocol_sha256": PROTOCOL_SHA,
        "packet": audit.seal(root, packet / "packet.json"),
        "labels": audit.seal(root, labels / "labels.json"),
        "baseline": audit.seal(root, baseline),
        "consumer_files": codes,
        "runtime": runtime,
        "views": views,
        "source_counts": spec["expected"],
        "shared_data": "data/processed",
        "cases": data[0]["cases"],
    }
    if codes != consumers(root) or runtime != comparison.runtime_snapshot():
        raise ValueError("Consumer/runtime changed during freeze")
    publish(output / "experiment.json", experiment)
    return {
        "experiment_sha256": audit.file_hash(output / "experiment.json"),
        **spec["expected"],
    }


def load(root, output, expected_sha):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not output.is_relative_to(root / ".cache"):
        raise ValueError("Output escapes its original ignored root")
    experiment = read(
        sealed(output, {"path": "experiment.json", "sha256": expected_sha})
    )
    spec = protocol()
    if (
        experiment["protocol_sha256"] != PROTOCOL_SHA
        or audit.file_hash(output / "protocol.json") != PROTOCOL_SHA
    ):
        raise ValueError("Frozen protocol binding changed")
    if (
        consumers(root) != experiment["consumer_files"]
        or comparison.runtime_snapshot() != experiment["runtime"]
    ):
        raise ValueError(
            "Frozen consumer/runtime changed; preserve the original lineage"
        )
    for name, entry in experiment["consumer_files"].items():
        if audit.file_hash(audit.inside(output / "consumer", name)) != entry["sha256"]:
            raise ValueError("Frozen consumer copy changed")
    data, views = inputs(
        root,
        sealed(root, experiment["packet"]).parent,
        sealed(root, experiment["labels"]).parent,
        sealed(root, experiment["baseline"]),
        spec,
    )
    if (
        views != experiment["views"]
        or data[0]["cases"] != experiment["cases"]
        or experiment["source_counts"] != spec["expected"]
    ):
        raise ValueError("Frozen source/view membership changed")
    return experiment, spec, data


def validate_heatmap(heat, shape=(288, 512)):
    if (
        not isinstance(heat, np.ndarray)
        or heat.dtype != np.dtype("float32")
        or heat.shape != shape
        or not np.isfinite(heat).all()
        or np.any(heat < 0)
        or np.any(heat > 1)
    ):
        raise ValueError(
            "Heatmap must have finite float32 responses and exact geometry"
        )
    return heat


def read_heatmap(output, entry):
    raw = audit.sealed_bytes(output, entry)
    stream = io.BytesIO(raw)
    heat = np.load(stream, allow_pickle=False)
    if stream.tell() != len(raw):
        raise ValueError("Unexpected trailing heatmap bytes")
    return validate_heatmap(heat)


def target_cases(cases, view):
    return [
        c
        for c in cases
        if c["video_id"] == view["video_id"]
        and view["start_frame"] <= c["frame"] < view["end_frame"]
        and c["id"] in view["case_ids"]
    ]


def completed_view(output, entry, view, cases, context_sha):
    from .shuttle import locate_shuttle

    record = read(sealed(output, entry))
    if (
        record["context_sha256"] != context_sha
        or record["clip"] != view["id"]
        or record["view"] != view
    ):
        raise ValueError("Completed view binding changed")
    run = read(sealed(output, record["run"]))
    expected = {c["id"]: c for c in target_cases(cases, view)}
    if set(record["heatmaps"]) != set(expected):
        raise ValueError("Heatmap case membership changed")
    for key, item in record["heatmaps"].items():
        case = expected[key]
        if item["case"] != case or item["view_id"] != view["id"]:
            raise ValueError("Heatmap source/view pairing changed")
        row = run["frames"][case["frame"] - view["start_frame"]]
        if item["time_s"] != row["time_s"] or row["frame"] != case["frame"]:
            raise ValueError("Heatmap native timestamp/frame changed")
        heat = read_heatmap(output, item["array"])
        observed = locate_shuttle(heat, case["width"], case["height"])
        for name in ("component_candidates", "components", "largest_component_id"):
            if comparison.compare_rows(observed[name], row["shuttle"][name], 0.00001):
                raise ValueError("Heatmap and emitted components disagree")
    return record, run


def native(root, output, experiment_sha, receipt=None, receipt_sha=None):
    import torch
    import torchvision  # noqa: F401

    from . import shuttle
    from .jobs import JobCancelled, run_local_job
    from .storage import Store

    root, output = Path(root).resolve(), Path(output).resolve()
    shared = _require_store(root)
    experiment, spec, data = load(root, output, experiment_sha)
    if not torch.cuda.is_available():
        raise ValueError("Frozen heatmap capture requires actual CUDA")
    proofs = prior_proofs(root, output)
    reusable, history, previous_elapsed = resume_plan(
        output, receipt, receipt_sha, experiment_sha
    )
    views = {v["id"]: v for v in experiment["views"]}
    if set(reusable) - set(views):
        raise ValueError("Foreign completed research view")
    complete = {key: value[1] for key, value in reusable.items()}
    attempt = output / "attempts" / uuid4().hex
    began = time.perf_counter()
    process = psutil.Process()
    job_id, index_entry, status = None, None, "failed"

    def task(identifier, progress):
        nonlocal job_id, index_entry
        job_id = identifier
        publish(
            attempt / "admission.json",
            {
                "job_id": identifier,
                "host_id": platform.node(),
                "context_sha256": experiment_sha,
                "process": {
                    "pid": process.pid,
                    "creation_time": process.create_time(),
                    "cwd": process.cwd(),
                    "command": process.cmdline(),
                },
                "prior_terminal_proofs": proofs,
            },
        )
        packet, sources, _, baseline, runs, plans = data

        def bounded_progress(value):
            if (
                previous_elapsed + time.perf_counter() - began
                > spec["max_native_seconds"]
            ):
                raise JobCancelled(
                    "Frozen cumulative native budget reached; preserve completed work"
                )
            progress(value)

        for ordinal, view in enumerate(experiment["views"]):
            if consumers(root) != experiment["consumer_files"]:
                raise ValueError("Consumer changed during native capture")
            if view["id"] in complete:
                completed_view(
                    output, complete[view["id"]], view, packet["cases"], experiment_sha
                )
            else:
                _, source, times, _ = next(
                    s for s in sources if s[1]["id"] == view["video_id"]
                )
                plan = plans[view["video_id"]]
                source_data = audit.inside(root, baseline["locations"]["data"])
                scan = read(
                    sealed(
                        source_data,
                        {
                            "path": f"{view['video_id']}/runs/{plan['segments']['run_id']}.json",
                            "sha256": plan["segments"]["sha256"],
                        },
                    )
                )
                annotations = baseline["evidence"]["catalogs"][view["video_id"]][
                    "snapshot"
                ]["annotations"]
                folder = attempt / "views" / view["id"]
                wanted = {c["frame"]: c for c in target_cases(packet["cases"], view)}
                captured = {}

                def observe(frame, timestamp, heat):
                    if frame not in wanted:
                        return
                    case = wanted[frame]
                    if case["id"] in captured or timestamp != times[frame]:
                        raise ValueError("Duplicate/changed heatmap native identity")
                    validate_heatmap(heat)
                    stream = io.BytesIO()
                    np.save(stream, heat, allow_pickle=False)
                    path = folder / (str(frame) + ".npy")
                    publish_bytes(path, stream.getvalue())
                    captured[case["id"]] = {
                        "case": case,
                        "view_id": view["id"],
                        "time_s": timestamp,
                        "array": audit.seal(output, path),
                    }

                run_path = folder / "native.json"
                run_path.parent.mkdir(parents=True, exist_ok=True)
                shuttle.track_shuttle(
                    source,
                    root,
                    source_data,
                    view["start_frame"],
                    view["end_frame"],
                    lambda value: bounded_progress((ordinal + value) / len(views)),
                    run_path,
                    annotations=annotations,
                    camera_scan=scan,
                    input_size=(512, 288),
                    heatmap_observer=observe,
                )
                run = read(run_path)
                comparison.validate_research_run(
                    run,
                    view,
                    "control",
                    {**spec, "variants": {"control": [512, 288]}},
                    runs[(view["video_id"], view["core_index"])],
                    source,
                    times,
                )
                if set(captured) != set(view["case_ids"]):
                    raise ValueError("Native capture did not retain all frozen cases")
                record = {
                    "clip": view["id"],
                    "view": view,
                    "context_sha256": experiment_sha,
                    "run": audit.seal(output, run_path),
                    "heatmaps": captured,
                }
                path = folder / "complete.json"
                publish(path, record)
                complete[view["id"]] = audit.seal(output, path)
                completed_view(
                    output, complete[view["id"]], view, packet["cases"], experiment_sha
                )
            bounded_progress((ordinal + 1) / len(views))
            print(
                audit.encoded(
                    {
                        "phase": "capture",
                        "completed_views": ordinal + 1,
                        "total_views": len(views),
                    }
                ).decode(),
                flush=True,
            )
        load(root, output, experiment_sha)
        index = {
            "schema_version": 1,
            "kind": "uninterpreted_heatmap_capture",
            "context_sha256": experiment_sha,
            "protocol_sha256": PROTOCOL_SHA,
            "completed_clips": list(complete.values()),
            "expected": spec["expected"],
        }
        path = attempt / "output-index.json"
        publish(path, index)
        index_entry = audit.seal(output, path)
        return {
            "output_index": index_entry,
            "views": len(complete),
            "interpreted": False,
        }

    try:
        result = run_local_job(Store(shared), "research-shuttle-heatmaps", None, task)
        status = "completed"
        return result
    except (KeyboardInterrupt, JobCancelled):
        status = "interrupted"
        raise
    finally:
        path = attempt / "terminal.json"
        publish(
            path,
            {
                "schema_version": 1,
                "context_sha256": experiment_sha,
                "status": status,
                "job_id": job_id,
                "elapsed_s": round(time.perf_counter() - began, 3),
                "completed_clips": list(complete.values()),
                "prior_terminal_seals": history,
                "output_index": index_entry,
            },
        )
        print(
            audit.encoded(
                {"terminal": audit.seal(output, path), "status": status}
            ).decode(),
            flush=True,
        )


def response_statistics(heat, case, label, diagonal_tolerance=0.005):
    validate_heatmap(heat)
    width, height = case["width"], case["height"]
    if type(width) is not int or type(height) is not int or min(width, height) <= 0:
        raise ValueError("Source geometry must be positive integers")
    if label["state"] not in {
        "visible",
        "visible_unlocalizable",
        "not_visible",
        "unknown",
    }:
        raise ValueError("Unknown visibility state")
    maximum = float(heat.max())
    y, x = np.unravel_index(int(heat.argmax()), heat.shape)
    global_point = [
        (int(x) + 0.5) * width / heat.shape[1],
        (int(y) + 0.5) * height / heat.shape[0],
    ]
    result = {
        "global_max": maximum,
        "global_first_argmax_source_xy": global_point,
        "global_zero_response": maximum == 0,
        "local": None,
    }
    if label["state"] != "visible":
        return result
    lx, ly, uncertainty = label["x"], label["y"], label["uncertainty_px"]
    if not all(
        audit.finite(v) for v in (lx, ly, uncertainty, diagonal_tolerance)
    ) or not (
        0 <= lx < width
        and 0 <= ly < height
        and uncertainty >= 0
        and diagonal_tolerance > 0
    ):
        raise ValueError("Invalid fixed source coordinate/uncertainty")
    tolerance = diagonal_tolerance * math.hypot(width, height)
    xs = (np.arange(heat.shape[1], dtype=np.float64) + 0.5) * width / heat.shape[1]
    ys = (np.arange(heat.shape[0], dtype=np.float64) + 0.5) * height / heat.shape[0]
    squared = (xs[None, :] - lx) ** 2 + (ys[:, None] - ly) ** 2

    def disk(radius):
        values = heat[squared <= radius * radius]
        peak = float(values.max()) if values.size else None
        return {
            "radius_px": radius,
            "cell_support": int(values.size),
            "max_response": peak,
            "local_global_ratio": peak / maximum
            if peak is not None and maximum > 0
            else None,
            "above_original_threshold_cells": int(np.count_nonzero(values > 0.5)),
        }

    result["global_argmax_label_distance_px"] = math.dist(global_point, (lx, ly))
    result["local"] = {
        "nominal": disk(tolerance),
        "uncertainty_inner": disk(max(0, tolerance - uncertainty)),
        "uncertainty_outer": disk(tolerance + uncertainty),
    }
    return result


def aggregate_responses(cases):
    counts = Counter(
        {
            "cases": len(cases),
            "available_heatmaps": 0,
            "unavailable_heatmaps": 0,
            "uninterpreted_heatmaps": 0,
            "visible_coordinate_support": 0,
            "zero_global_responses": 0,
            **{
                "state:" + state: 0
                for state in (
                    "visible",
                    "visible_unlocalizable",
                    "not_visible",
                    "unknown",
                )
            },
        }
    )
    values = defaultdict(list)
    for case in cases:
        counts["state:" + case["state"]] += 1
        available = case.get("heatmap_available", case["response"] is not None)
        counts["available_heatmaps" if available else "unavailable_heatmaps"] += 1
        if case["response"] is None:
            counts["uninterpreted_heatmaps"] += int(available)
            continue
        response = case["response"]
        counts["zero_global_responses"] += int(response["global_zero_response"])
        values["global_max"].append(response["global_max"])
        if response["local"] is not None:
            counts["visible_coordinate_support"] += 1
            for region, disk in response["local"].items():
                counts[region + ":empty_disks"] += int(disk["cell_support"] == 0)
                counts[region + ":response_above_original_threshold"] += int(
                    disk["above_original_threshold_cells"] > 0
                )
                for name in ("max_response", "local_global_ratio"):
                    if disk[name] is not None:
                        values[region + ":" + name].append(disk[name])
    return {
        "counts": dict(counts),
        "descriptive": {
            name: {
                "support": len(items),
                "minimum": min(items),
                "median": float(np.median(items)),
                "maximum": max(items),
            }
            for name, items in sorted(values.items())
        },
    }


def interpret(
    root, output, experiment_sha, index_path, index_sha, terminal_path, terminal_sha
):
    from .jobs import run_local_job
    from .storage import Store

    root, output = Path(root).resolve(), Path(output).resolve()
    shared = _require_store(root)
    experiment, spec, data = load(root, output, experiment_sha)
    proofs = prior_proofs(root, output)
    entry = {
        "path": Path(index_path).resolve().relative_to(output).as_posix(),
        "sha256": index_sha,
    }
    index = read(sealed(output, entry))
    terminal_entry = terminal_binding(
        output, terminal_path, terminal_sha, entry, index, experiment_sha, proofs
    )
    if (
        index["kind"] != "uninterpreted_heatmap_capture"
        or index["protocol_sha256"] != PROTOCOL_SHA
        or index["expected"] != spec["expected"]
        or index["context_sha256"] != experiment_sha
    ):
        raise ValueError("Uninterpreted output index binding changed")
    packet, sources, labels, baseline, runs, _ = data
    source_meta = {s[1]["id"]: (s[1], s[2]) for s in sources}
    views = {v["id"]: v for v in experiment["views"]}
    entries = {}
    for seal in index["completed_clips"]:
        document = read(sealed(output, seal))
        key = document["clip"]
        if key not in views or key in entries:
            raise ValueError("Duplicate or foreign output view")
        entries[key] = seal
    if set(entries) != set(views):
        raise ValueError("Complete original-view index required")
    destination = output / "interpretations" / uuid4().hex / "report.json"

    def task(_identifier, progress):
        captures, gate_rows, differences = {}, 0, []
        for ordinal, view in enumerate(experiment["views"]):
            record, run = completed_view(
                output, entries[view["id"]], view, packet["cases"], experiment_sha
            )
            original = runs[(view["video_id"], view["core_index"])]
            meta, times = source_meta[view["video_id"]]
            comparison.validate_research_run(
                run,
                view,
                "control",
                {**spec, "variants": {"control": [512, 288]}},
                original,
                meta,
                times,
            )
            expected = [
                comparison.native_row(row)
                for row in original["frames"][
                    view["start_frame"] - original["start_frame"] : view["end_frame"]
                    - original["start_frame"]
                ]
            ]
            current = [comparison.native_row(row) for row in run["frames"]]
            if audit.digest(audit.encoded(expected)) != view["expected_rows_sha256"]:
                raise ValueError("Original view control hash changed")
            diff = comparison.compare_rows(
                expected, current, spec["control_gate"]["confidence_absolute_tolerance"]
            )
            if diff:
                differences.append({"view_id": view["id"], "differences": diff})
            gate_rows += len(current)
            if set(captures) & set(record["heatmaps"]):
                raise ValueError("A case has multiple heatmap owners")
            captures.update(record["heatmaps"])
            progress((ordinal + 1) / len(views) * 0.5)
        if (
            set(captures) != {c["id"] for c in packet["cases"]}
            or gate_rows != spec["expected"]["native_view_rows"]
        ):
            raise ValueError("Full case/native-row membership changed")
        # No source-coordinate response interpretation before the complete gate.
        report = {
            "schema_version": 1,
            "scope": "Descriptive familiar-development raw heatmap responses, not alternate predictions or accuracy",
            "experiment_sha256": experiment_sha,
            "protocol_sha256": PROTOCOL_SHA,
            "native_terminal": terminal_entry,
            "output_index": entry,
            "control_gate": {
                "compatible": not differences,
                "views": len(views),
                "native_rows": gate_rows,
                "differences": differences,
            },
            "eligibility": spec["eligibility"],
            "limitations": spec["limitations"],
            "cases": [],
            "groups": {},
        }
        truth = {label["id"]: label for label in labels["cases"]}
        groups = defaultdict(list)
        for key in [
            "all",
            *["state:" + state for state in spec["expected"]["states"]],
            *["difficulty:" + tag for tag in audit.PROTOCOL["difficulty_tags"]],
            "selection:uniform",
            "selection:known_gap",
            "disagreement:true",
            "disagreement:false",
        ]:
            groups[key] = []
        for case in packet["cases"]:
            assessment = truth[case["id"]]
            label = assessment["label"]
            capture = captures[case["id"]]
            response = (
                None
                if differences
                else response_statistics(
                    read_heatmap(output, capture["array"]),
                    case,
                    label,
                    spec["metrics"]["diagonal_tolerance"],
                )
            )
            value = {
                "id": case["id"],
                "video_id": case["video_id"],
                "frame": case["frame"],
                "state": label["state"],
                "response": response,
                "heatmap_available": True,
                "interpretation_unavailable_reason": "control_mismatch"
                if differences
                else None,
                "original_observation": baseline["evidence"]["observations"][
                    case["id"]
                ],
            }
            report["cases"].append(value)
            keys = [
                "all",
                "source:" + case["video_id"],
                "state:" + label["state"],
                "selection:"
                + (
                    "uniform"
                    if case["frame"]
                    in {
                        math.floor(
                            (i + 0.5)
                            * source_meta[case["video_id"]][0]["frame_count"]
                            / 25
                        )
                        for i in range(25)
                    }
                    else "known_gap"
                ),
                "disagreement:" + str(any(assessment["disagreement"].values())).lower(),
            ]
            keys += ["difficulty:" + tag for tag in label["difficulty"]]
            for key in keys:
                groups[key].append(value)
        report["groups"] = {
            name: aggregate_responses(values) for name, values in sorted(groups.items())
        }
        report["summary"] = aggregate_responses(report["cases"])
        load(root, output, experiment_sha)
        sealed(output, entry)
        publish(destination, report)
        return {
            "report": audit.seal(output, destination),
            "compatible": not differences,
            "cases": len(report["cases"]),
        }

    return run_local_job(
        Store(shared), "research-shuttle-heatmap-interpretation", None, task
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "capture", "interpret"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--experiment-sha256")
    parser.add_argument("--resume-receipt", type=Path)
    parser.add_argument("--resume-sha256")
    parser.add_argument("--index", type=Path)
    parser.add_argument("--index-sha256")
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--terminal-sha256")
    args = parser.parse_args(argv)
    if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        parser.error("Clear GitHub credentials before executing research code")
    if args.mode == "freeze":
        if not all((args.packet, args.labels, args.baseline)) or any(
            (
                args.experiment_sha256,
                args.resume_receipt,
                args.resume_sha256,
                args.index,
                args.index_sha256,
                args.terminal,
                args.terminal_sha256,
            )
        ):
            parser.error("Freeze requires packet/labels/baseline only")
        result = freeze(
            args.root,
            args.packet.resolve(),
            args.labels.resolve(),
            args.baseline.resolve(),
            args.output,
        )
    elif args.mode == "capture":
        if not args.experiment_sha256 or any(
            (
                args.packet,
                args.labels,
                args.baseline,
                args.index,
                args.index_sha256,
                args.terminal,
                args.terminal_sha256,
            )
        ):
            parser.error(
                "Capture requires experiment hash and optional sealed resume receipt only"
            )
        result = native(
            args.root,
            args.output,
            args.experiment_sha256,
            args.resume_receipt,
            args.resume_sha256,
        )
    else:
        if not all(
            (
                args.experiment_sha256,
                args.index,
                args.index_sha256,
                args.terminal,
                args.terminal_sha256,
            )
        ) or any(
            (
                args.packet,
                args.labels,
                args.baseline,
                args.resume_receipt,
                args.resume_sha256,
            )
        ):
            parser.error(
                "Interpret requires experiment, index and matching completed terminal with external hashes only"
            )
        result = interpret(
            args.root,
            args.output,
            args.experiment_sha256,
            args.index,
            args.index_sha256,
            args.terminal,
            args.terminal_sha256,
        )
    print(audit.encoded(result).decode(), flush=True)
