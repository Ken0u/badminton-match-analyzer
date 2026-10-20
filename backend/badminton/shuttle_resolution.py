"""Frozen, read-only-input TrackNet resolution development experiment."""

import argparse
import importlib.metadata
import json
import math
import os
import platform
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import psutil

from . import shuttle_validation as audit
from .shuttle import validate_input_size


def publish(path, value):
    """Atomically expose a durable complete receipt without replacing anything."""
    pending = path.with_name(path.name + ".pending-" + uuid4().hex)
    with pending.open("xb") as handle:
        handle.write(audit.encoded(value))
        handle.flush()
        os.fsync(handle.fileno())
    # Hard-link creation is atomic and fails if the destination already exists
    # on Windows and POSIX. An interrupted pending file remains preserved.
    os.link(pending, path)
    pending.unlink()


def compare_rows(expected, observed, confidence_tolerance):
    """Exact native structure/geometry, with only the predeclared score tolerance."""
    differences = []

    def compare(a, b, path):
        if path[-1:] == ("confidence",):
            if (
                not audit.finite(a)
                or not audit.finite(b)
                or abs(a - b) > confidence_tolerance
            ):
                differences.append("/".join(map(str, path)))
        elif type(a) is not type(b):
            differences.append("/".join(map(str, path)))
        elif isinstance(a, dict):
            if set(a) != set(b):
                differences.append("/".join(map(str, path)) + "/keys")
            for key in sorted(set(a) & set(b)):
                compare(a[key], b[key], (*path, key))
        elif isinstance(a, list):
            if len(a) != len(b):
                differences.append("/".join(map(str, path)) + "/length")
            for index, (left, right) in enumerate(zip(a, b)):
                compare(left, right, (*path, index))
        elif a != b:
            differences.append("/".join(map(str, path)))

    if not audit.finite(confidence_tolerance) or confidence_tolerance < 0:
        raise ValueError("Control confidence tolerance must be finite and nonnegative")
    compare(expected, observed, ())
    return differences


def runtime_snapshot():
    versions = {}
    for name in ("av", "numpy", "Pillow", "opencv-python", "torch", "torchvision"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    gpu = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,uuid,driver_version",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return {
        "python": platform.python_version(),
        "libraries": versions,
        "gpu_driver_inventory": gpu.stdout.strip(),
    }


def consumer_files(root):
    package = Path(__file__).resolve().parent
    paths = {
        "badminton/" + path.relative_to(package).as_posix(): path
        for path in package.rglob("*.py")
    }
    paths["badminton/model_manifest.json"] = package / "model_manifest.json"
    paths["scripts/compare_shuttle_resolution.py"] = (
        package.parents[1] / "scripts/compare_shuttle_resolution.py"
    )
    return {name: audit.seal(root, path) for name, path in sorted(paths.items())}


def native_row(row):
    return {
        key: row[key]
        for key in ("frame", "time_s", "camera_segment_start_frame", "shuttle")
    }


def plan_views(cases, evidence, runs):
    """Each original target owns its full background/ensemble/selection view."""
    views = {}
    for case in cases:
        obs = evidence["observations"][case["id"]]
        if not obs["available"]:
            raise ValueError(
                "This fixed inference comparison requires its unchanged available baseline"
            )
        first, last = obs["background_context_frames"]
        run = runs[(case["video_id"], obs["core_index"])]
        rows = run["frames"][first - run["start_frame"] : last - run["start_frame"]]
        if (
            not run["start_frame"] <= first <= case["frame"] < last <= run["end_frame"]
            or [row["frame"] for row in rows] != list(range(first, last))
            or any(first < cut < last for cut in run["cut_frames"])
        ):
            raise ValueError(
                "Target view must retain complete same-camera native context"
            )
        expected_sha = audit.digest(audit.encoded([native_row(row) for row in rows]))
        identity = {
            "video_id": case["video_id"],
            "start_frame": first,
            "end_frame": last,
        }
        key = audit.digest(audit.encoded(identity))[:24]
        if key not in views:
            views[key] = {
                **identity,
                "id": key,
                "core_index": obs["core_index"],
                "shuttle_run_id": obs["shuttle_run_id"],
                "expected_rows_sha256": expected_sha,
                "case_ids": [],
            }
        elif views[key]["expected_rows_sha256"] != expected_sha:
            raise ValueError("Identical source views have conflicting baseline outputs")
        views[key]["case_ids"].append(case["id"])
    return list(views.values())


def baseline_runs(root, baseline):
    runs, plans = {}, {}
    data = audit.inside(root, baseline["locations"]["data"])
    for vid, selection in baseline["evidence"]["manifest_selection"].items():
        if len(selection) != 1:
            raise ValueError("Unique frozen native manifest required")
        plan = audit.read_json(audit.inside(root, selection[0]).read_bytes())
        plans[vid] = plan
        for part in plan["parts"]:
            cp = part["stages"]["shuttle"]
            path = audit.inside(data, f"{vid}/runs/{cp['run_id']}.json")
            raw = path.read_bytes()
            if audit.digest(raw) != cp["sha256"]:
                raise ValueError("Changed original native view")
            runs[(vid, part["window"]["index"])] = audit.read_json(raw)
    return runs, plans


def verify_inputs(root, packet_root, label_root, baseline_path, protocol):
    root, packet_root, label_root, baseline_path = (
        path.resolve() for path in (root, packet_root, label_root, baseline_path)
    )
    packet, sources, labels = audit.audit_inputs(
        root,
        packet_root,
        protocol["packet_sha256"],
        label_root,
        protocol["labels_sha256"],
    )
    raw = baseline_path.read_bytes()
    if audit.digest(raw) != protocol["baseline_sha256"]:
        raise ValueError("Changed original baseline index")
    baseline = audit.read_json(raw)
    if (
        baseline["packet_sha256"] != protocol["packet_sha256"]
        or baseline["labels_sha256"] != protocol["labels_sha256"]
        or protocol["inventory_sha256"] != audit.PROTOCOL["inventory_sha256"]
        or len(packet["cases"]) != protocol["metrics"]["case_count"]
    ):
        raise ValueError("Comparison protocol has incompatible input lineage")
    evidence = audit.native_observations(
        root, sources, packet["cases"], labels["cases"], baseline["locations"]
    )
    if audit.encoded(evidence) != audit.encoded(baseline["evidence"]):
        raise ValueError("Original baseline graph or context changed")
    runs, plans = baseline_runs(root, baseline)
    return packet, sources, labels, baseline, runs, plans


def validate_protocol(protocol):
    if (
        protocol.get("schema_version") != 1
        or protocol.get("variants") != {"control": [512, 288], "candidate": [768, 432]}
        or protocol.get("heatmap_threshold") != 0.5
        or protocol.get("sequence_length") != 8
        or protocol.get("device") != "cuda:0"
        or protocol.get("precision") != "float16"
        or protocol.get("metrics", {}).get("diagonal_tolerance") != 0.005
        or protocol.get("control_gate", {}).get("confidence_absolute_tolerance")
        != 0.00001
        or protocol.get("control_gate", {}).get("confidence_relative_tolerance") != 0.0
    ):
        raise ValueError("Only the fixed two-variant comparison protocol is supported")
    for size in protocol["variants"].values():
        validate_input_size(size)


def freeze_experiment(
    root, packet_root, label_root, baseline_path, protocol_path, protocol_sha256, output
):
    root = root.resolve()
    protocol_raw = protocol_path.read_bytes()
    if audit.digest(protocol_raw) != protocol_sha256:
        raise ValueError("Changed public comparison protocol")
    protocol = audit.read_json(protocol_raw)
    validate_protocol(protocol)
    code = consumer_files(root)
    data = verify_inputs(root, packet_root, label_root, baseline_path, protocol)
    packet, _, _, baseline, runs, _ = data
    views = plan_views(packet["cases"], baseline["evidence"], runs)
    models = [
        entry["models"]["shuttle"]["sha256"]
        for entry in baseline["evidence"]["provenance"]
    ]
    if not models or any(sha != protocol["checkpoint_sha256"] for sha in models):
        raise ValueError("Original TrackNet checkpoint does not match protocol")
    output = audit.ignored_output(root, output)
    for name, entry in code.items():
        raw = audit.sealed_bytes(root, entry)
        destination = output / "consumer" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(raw)
    with (output / "protocol.json").open("xb") as handle:
        handle.write(protocol_raw)
    experiment = {
        "schema_version": 1,
        "protocol_sha256": protocol_sha256,
        "packet": audit.seal(root, packet_root / "packet.json"),
        "labels": audit.seal(root, label_root / "labels.json"),
        "baseline": audit.seal(root, baseline_path),
        "consumer_files": code,
        "runtime": runtime_snapshot(),
        "views": views,
        "shared_data": "data/processed",
    }
    if consumer_files(root) != code or protocol_path.read_bytes() != protocol_raw:
        raise ValueError("Consumer/protocol changed during experiment freeze")
    publish(output / "experiment.json", experiment)
    return {
        "experiment_sha256": audit.file_hash(output / "experiment.json"),
        "views": len(views),
        "native_view_frames": sum(v["end_frame"] - v["start_frame"] for v in views),
        "cases": len(packet["cases"]),
    }


def component_metrics(cases, labels, observations):
    result = {
        "known_localizable_visible": 0,
        "unavailable": 0,
        "component_present": 0,
        "component_absent": 0,
    }
    for case, entry in zip(cases, labels):
        truth = entry["label"]
        if truth["state"] != "visible":
            continue
        result["known_localizable_visible"] += 1
        observation = observations[case["id"]]
        if not observation["available"]:
            result["unavailable"] += 1
            continue
        tolerance = 0.005 * math.hypot(case["width"], case["height"])
        present = any(
            math.hypot(point["x"] - truth["x"], point["y"] - truth["y"])
            <= tolerance + 1e-9
            for point in observation["point"].get("component_candidates", [])
        )
        result["component_present" if present else "component_absent"] += 1
    count = result["known_localizable_visible"]
    result["strict_component_recall"] = (
        result["component_present"] / count if count else None
    )
    return result


def load_experiment(root, output, expected_sha256):
    root, output = root.resolve(), output.resolve()
    if not output.is_relative_to(root / ".cache"):
        raise ValueError("Experiment must remain in its original ignored root")
    raw = (output / "experiment.json").read_bytes()
    if audit.digest(raw) != expected_sha256:
        raise ValueError("Changed experiment receipt")
    experiment = audit.read_json(raw)
    protocol_raw = (output / "protocol.json").read_bytes()
    if audit.digest(protocol_raw) != experiment["protocol_sha256"]:
        raise ValueError("Changed frozen protocol")
    protocol = audit.read_json(protocol_raw)
    validate_protocol(protocol)
    if (
        consumer_files(root) != experiment["consumer_files"]
        or runtime_snapshot() != experiment["runtime"]
    ):
        raise ValueError("Experiment code or runtime changed; preserve the old lineage")
    for name, entry in experiment["consumer_files"].items():
        if audit.file_hash(audit.inside(output / "consumer", name)) != entry["sha256"]:
            raise ValueError("Changed frozen consumer snapshot")
    packet_path = audit.sealed_path(root, experiment["packet"])
    label_path = audit.sealed_path(root, experiment["labels"])
    baseline_path = audit.sealed_path(root, experiment["baseline"])
    inputs = verify_inputs(
        root, packet_path.parent, label_path.parent, baseline_path, protocol
    )
    packet, _, _, baseline, runs, _ = inputs
    if plan_views(packet["cases"], baseline["evidence"], runs) != experiment["views"]:
        raise ValueError("Original complete view membership changed")
    return experiment, protocol, inputs


def completed_view(output, variant, view, experiment_sha256):
    path = output / variant / (view["id"] + ".json")
    if not path.exists():
        return None
    entry = audit.read_json(path.read_bytes())
    if entry.get("experiment_sha256") != experiment_sha256 or entry.get("view") != view:
        raise ValueError("Incompatible completed research view")
    raw = audit.sealed_bytes(output, entry["run"])
    run = audit.read_json(raw)
    if (
        run.get("input_size") != ([512, 288] if variant == "control" else [768, 432])
        or run.get("video_id") != view["video_id"]
        or run.get("start_frame") != view["start_frame"]
        or run.get("end_frame") != view["end_frame"]
        or [row["frame"] for row in run["frames"]]
        != list(range(view["start_frame"], view["end_frame"]))
    ):
        raise ValueError("Changed completed source-view geometry/membership")
    return entry, run


def validate_research_run(run, view, variant, protocol, original, meta, times):
    if (
        run.get("stage") != "shuttle"
        or run.get("video_id") != view["video_id"]
        or run.get("video_sha256") != meta["sha256"]
        or type(run.get("start_frame")) is not int
        or type(run.get("end_frame")) is not int
        or run["start_frame"] != view["start_frame"]
        or run["end_frame"] != view["end_frame"]
        or run.get("checkpoint_sha256") != protocol["checkpoint_sha256"]
        or run.get("seq_len") != protocol["sequence_length"]
        or run.get("input_size") != protocol["variants"][variant]
        or run.get("device") != protocol["device"]
        or run.get("precision") != protocol["precision"]
        or type(run.get("repaired_frames")) is not int
        or run["repaired_frames"] != 0
        or run.get("temporal_context_crosses_detected_cuts") is not False
        or any(
            view["start_frame"] < cut < view["end_frame"]
            for cut in run.get("cut_frames", [])
        )
    ):
        raise ValueError("Research native model/source/camera recipe changed")
    rows = audit.native_rows(run, meta, times, view)
    for row in rows:
        previous = original["frames"][row["frame"] - original["start_frame"]]
        if (
            row.get("camera_segment_start_frame")
            != previous["camera_segment_start_frame"]
        ):
            raise ValueError("Research camera identity changed")
        point = row["shuttle"]
        if point.get("repaired") is not False:
            raise ValueError("Research output must remain observed, never repaired")
        if point["visible"] and (
            type(point.get("selection_context_start_frame")) is not int
            or type(point.get("selection_context_end_frame")) is not int
            or not view["start_frame"]
            <= point["selection_context_start_frame"]
            <= row["frame"]
            or point["selection_context_end_frame"] != row["frame"] + 1
            or point.get("selection_context_excluded") is not False
        ):
            raise ValueError(
                "Research selector history escaped its complete source view"
            )
        if point["visible"]:
            history = point.get("selection_context_frames", [])
            if (
                not isinstance(history, list)
                or any(type(frame) is not int for frame in history)
                or history != sorted(set(history))
                or any(
                    not view["start_frame"] <= frame < row["frame"] for frame in history
                )
            ):
                raise ValueError("Invalid research transitive selection history")
            starts = [row["frame"]]
            for frame in history:
                previous = rows[frame - view["start_frame"]]["shuttle"]
                if (
                    previous.get("visible") is not True
                    or previous.get("repaired") is not False
                    or previous.get("selection_context_excluded") is not False
                    or type(previous.get("selection_context_start_frame")) is not int
                    or not view["start_frame"]
                    <= previous["selection_context_start_frame"]
                    <= frame
                    or type(previous.get("selection_context_end_frame")) is not int
                    or previous["selection_context_end_frame"] != frame + 1
                ):
                    raise ValueError("Invalid research predecessor provenance")
                starts.append(previous["selection_context_start_frame"])
            if point["selection_context_start_frame"] != min(starts):
                raise ValueError("Incomplete research predecessor ancestry")
    return rows


def research_views(output, variant, experiment, experiment_sha256, protocol, inputs):
    _, sources, _, _, runs, _ = inputs
    result = {}
    for view in experiment["views"]:
        completed = completed_view(output, variant, view, experiment_sha256)
        if completed is None:
            continue
        _, meta, times, _ = next(
            source for source in sources if source[1]["id"] == view["video_id"]
        )
        validate_research_run(
            completed[1],
            view,
            variant,
            protocol,
            runs[(view["video_id"], view["core_index"])],
            meta,
            times,
        )
        result[view["id"]] = completed
    return result


def control_gate(output, experiment, expected_sha256, runs, tolerance):
    differences, seals = [], []
    for view in experiment["views"]:
        completed = completed_view(output, "control", view, expected_sha256)
        if completed is None:
            raise ValueError(
                "All original control views must finish before candidate inference"
            )
        entry, run = completed
        original = runs[(view["video_id"], view["core_index"])]
        expected = original["frames"][
            view["start_frame"] - original["start_frame"] : view["end_frame"]
            - original["start_frame"]
        ]
        if (
            audit.digest(audit.encoded([native_row(row) for row in expected]))
            != view["expected_rows_sha256"]
        ):
            raise ValueError("Original view outputs changed")
        changed = compare_rows(
            [native_row(row) for row in expected],
            [native_row(row) for row in run["frames"]],
            tolerance,
        )
        differences.extend({"view": view["id"], "field": field} for field in changed)
        seals.append(entry["run"])
    return {
        "experiment_sha256": expected_sha256,
        "compatible": not differences,
        "differences": differences,
        "control_runs": seals,
    }


def prior_attempt_proof(output, shared_data):
    """No timeout/lock inference: inspect original process lifetimes and Store rows."""
    proofs = []
    database = shared_data / "catalog.sqlite3"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as cx:
        cx.execute("PRAGMA query_only=ON")
        for path in sorted((output / "attempts").glob("*/admission.json")):
            admission = audit.read_json(path.read_bytes())
            process = admission["process"]
            try:
                owner = psutil.Process(process["pid"])
                alive = abs(owner.create_time() - process["creation_time"]) < 0.01
            except psutil.NoSuchProcess:
                alive = False
            except psutil.AccessDenied as exc:
                raise ValueError(
                    "Original research process lifetime is unavailable"
                ) from exc
            if alive:
                raise ValueError(
                    "Original research process is still alive; never resume concurrently"
                )
            row = cx.execute(
                "SELECT document FROM jobs WHERE id=?", (admission["job_id"],)
            ).fetchone()
            if row is None:
                raise ValueError("Original shared admission job is missing")
            job = audit.read_json(row[0].encode("utf-8"))
            if (
                job.get("owner_pid") != process["pid"]
                or job.get("owner_started") != process["creation_time"]
            ):
                raise ValueError("Original shared admission ownership changed")
            proofs.append(
                {
                    "admission": audit.seal(output, path),
                    "process": process,
                    "original_lifetime_exited": True,
                    "store_status": job["status"],
                    "store_job_sha256": audit.digest(audit.encoded(job)),
                }
            )
    return proofs


def run_variant(root, output, experiment_sha256, variant):
    from . import config, shuttle
    from .jobs import run_local_job
    from .storage import Store

    if variant not in {"control", "candidate"}:
        raise ValueError("Only the two frozen variants may run")
    root, output = root.resolve(), output.resolve()
    experiment, protocol, inputs = load_experiment(root, output, experiment_sha256)
    _packet, sources, _labels, baseline, runs, plans = inputs
    shared_data = audit.inside(root, experiment["shared_data"])
    if (
        shared_data != root / "data/processed"
        or not (shared_data / "catalog.sqlite3").is_file()
        or config.ROOT != root
        or config.DATA.resolve() != shared_data
        or config.WEIGHTS.resolve() != root / "models/weights"
    ):
        raise ValueError(
            "Pin the real original roots and shared Store before importing configuration"
        )
    if variant == "candidate":
        research_views(
            output, "control", experiment, experiment_sha256, protocol, inputs
        )
        gate = control_gate(
            output,
            experiment,
            experiment_sha256,
            runs,
            protocol["control_gate"]["confidence_absolute_tolerance"],
        )
        if not gate["compatible"]:
            raise ValueError("Original 512 control mismatch blocks candidate inference")
    prior = prior_attempt_proof(output, shared_data)
    existing = research_views(
        output, variant, experiment, experiment_sha256, protocol, inputs
    )
    attempt = output / "attempts" / uuid4().hex
    attempt.mkdir(parents=True)
    publish(attempt / "prior-terminal-proof.json", prior)

    def task(job_id, progress):
        process = psutil.Process()
        publish(
            attempt / "admission.json",
            {
                "job_id": job_id,
                "experiment_sha256": experiment_sha256,
                "variant": variant,
                "shared_data": shared_data.as_posix(),
                "process": {
                    "pid": os.getpid(),
                    "creation_time": process.create_time(),
                    "cwd": str(Path.cwd()),
                    "command": list(sys.argv),
                },
            },
        )
        # Preserve torchvision initialization before any threaded native decoder.
        import torch
        import torchvision  # noqa: F401

        if not torch.cuda.is_available():
            raise ValueError("This frozen research task requires its actual CUDA host")
        gpu = {
            "name": torch.cuda.get_device_name(0),
            "memory_bytes": torch.cuda.get_device_properties(0).total_memory,
            "torch_cuda": torch.version.cuda,
        }
        publish(attempt / "device.json", gpu)
        (output / variant).mkdir(exist_ok=True)
        for index, view in enumerate(experiment["views"]):
            if view["id"] in existing:
                progress((index + 1) / len(experiment["views"]))
                continue
            vid = view["video_id"]
            _, source, times, _ = next(
                source for source in sources if source[1]["id"] == vid
            )
            plan = plans[vid]
            data = audit.inside(root, baseline["locations"]["data"])
            scan_cp = plan["segments"]
            scan_raw = audit.inside(
                data, f"{vid}/runs/{scan_cp['run_id']}.json"
            ).read_bytes()
            if audit.digest(scan_raw) != scan_cp["sha256"]:
                raise ValueError("Original full-source camera scan changed")
            scan = audit.read_json(scan_raw)
            annotations = baseline["evidence"]["catalogs"][vid]["snapshot"][
                "annotations"
            ]
            run_path = attempt / (view["id"] + ".json")
            shuttle.track_shuttle(
                source,
                root,
                data,
                view["start_frame"],
                view["end_frame"],
                lambda value: progress((index + value) / len(experiment["views"])),
                run_path,
                annotations=annotations,
                camera_scan=scan,
                input_size=protocol["variants"][variant],
            )
            run = audit.read_json(run_path.read_bytes())
            validate_research_run(
                run,
                view,
                variant,
                protocol,
                runs[(vid, view["core_index"])],
                source,
                times,
            )
            completed = {
                "experiment_sha256": experiment_sha256,
                "view": view,
                "run": audit.seal(output, run_path),
                "job_id": job_id,
                "device": gpu,
            }
            publish(output / variant / (view["id"] + ".json"), completed)
        # Revalidate originals, consumer and labels before publishing completion.
        load_experiment(root, output, experiment_sha256)
        research_views(output, variant, experiment, experiment_sha256, protocol, inputs)
        if variant == "control":
            result = control_gate(
                output,
                experiment,
                experiment_sha256,
                runs,
                protocol["control_gate"]["confidence_absolute_tolerance"],
            )
            publish(attempt / "control-gate.json", result)
            return {
                "variant": variant,
                "compatible": result["compatible"],
                "gate": audit.seal(output, attempt / "control-gate.json"),
            }
        return {"variant": variant, "views": len(experiment["views"])}

    began = time.perf_counter()
    try:
        result = run_local_job(Store(shared_data), "feature-preparation", None, task)
    except BaseException as exc:
        publish(
            attempt / "terminal.json",
            {
                "status": "failed",
                "error": str(exc),
                "elapsed_s": time.perf_counter() - began,
            },
        )
        raise
    publish(
        attempt / "terminal.json",
        {
            "status": "completed",
            "result": result,
            "elapsed_s": time.perf_counter() - began,
        },
    )
    return {**result, "attempt": attempt.relative_to(output).as_posix()}


def grouped_scores(cases, labels, observations):
    groups = {"all": list(range(len(cases)))}
    for index, (case, entry) in enumerate(zip(cases, labels)):
        names = [
            "source/" + case["video_id"],
            "state/" + entry["label"]["state"],
            "disagreement/" + ("yes" if any(entry["disagreement"].values()) else "no"),
            "availability/"
            + ("yes" if observations[case["id"]]["available"] else "no"),
            "selection/"
            + (
                "known_gap"
                if case["frame"]
                in audit.PROTOCOL["extra_frames"].get(case["video_id"], [])
                else "uniform"
            ),
        ]
        names.extend("difficulty/" + tag for tag in entry["label"]["difficulty"])
        for name in names:
            groups.setdefault(name, []).append(index)
    for name in [
        *("source/" + source["id"] for source in audit.PROTOCOL["sources"]),
        *("state/" + state for state in audit.PROTOCOL["states"]),
        *("difficulty/" + tag for tag in audit.PROTOCOL["difficulty_tags"]),
        "disagreement/yes",
        "disagreement/no",
        "availability/yes",
        "availability/no",
        "selection/known_gap",
        "selection/uniform",
    ]:
        groups.setdefault(name, [])
    results = {}
    for name, indices in groups.items():
        subset_cases = [cases[i] for i in indices]
        subset_labels = [labels[i] for i in indices]
        subset_obs = {case["id"]: observations[case["id"]] for case in subset_cases}
        results[name] = {
            "metrics": audit.score_cases(subset_cases, subset_labels, subset_obs),
            "components": component_metrics(subset_cases, subset_labels, subset_obs),
        }
    return results


def evaluate_experiment(root, output, experiment_sha256, report_output):
    root, output = root.resolve(), output.resolve()
    experiment, protocol, inputs = load_experiment(root, output, experiment_sha256)
    packet, _, labels, baseline, runs, _ = inputs
    control = research_views(
        output, "control", experiment, experiment_sha256, protocol, inputs
    )
    gate = None
    if len(control) == len(experiment["views"]):
        gate = control_gate(
            output,
            experiment,
            experiment_sha256,
            runs,
            protocol["control_gate"]["confidence_absolute_tolerance"],
        )
    compatible = gate is not None and gate["compatible"]
    cases, truth = packet["cases"], labels["cases"]
    result = {
        "schema_version": 1,
        "experiment_sha256": experiment_sha256,
        "protocol_sha256": experiment["protocol_sha256"],
        "case_count": len(cases),
        "control_gate": gate,
        "comparison_status": "compatible"
        if compatible
        else "blocked_control_mismatch_or_unavailable",
        "original": grouped_scores(cases, truth, baseline["evidence"]["observations"]),
        "variants": {},
        "limitations": protocol["limitations"],
    }
    seals = []
    # Do not open candidate predictions unless the unchanged control reproduces.
    for variant in ("control", "candidate"):
        values = (
            control
            if variant == "control"
            else (
                research_views(
                    output, variant, experiment, experiment_sha256, protocol, inputs
                )
                if compatible
                else {}
            )
        )
        observations = {}
        for view in experiment["views"]:
            completed = values.get(view["id"])
            for case_id in view["case_ids"]:
                if completed is None:
                    observations[case_id] = {
                        "available": False,
                        "point": None,
                        "reason": "control_gate_blocked"
                        if not compatible
                        else "missing_research_view",
                    }
                else:
                    run = completed[1]
                    frame = next(
                        case["frame"] for case in cases if case["id"] == case_id
                    )
                    observations[case_id] = {
                        "available": True,
                        "point": run["frames"][frame - view["start_frame"]]["shuttle"],
                        "reason": None,
                    }
            if completed is not None:
                seals.append(completed[0]["run"])
        result["variants"][variant] = {
            "input_size": protocol["variants"][variant],
            "complete_views": len(values),
            "total_views": len(experiment["views"]),
            "all_cases_retained": len(observations),
            "groups": grouped_scores(cases, truth, observations)
            if compatible
            else None,
            "performance": {
                "native_view_frames": sum(
                    value[1]["processed_frames"] for value in values.values()
                ),
                "inference_elapsed_s": sum(
                    value[1]["elapsed_s"] for value in values.values()
                ),
                "peak_gpu_tensor_allocation_mb": max(
                    (value[1]["peak_gpu_memory_mb"] for value in values.values()),
                    default=None,
                ),
            },
        }
    load_experiment(root, output, experiment_sha256)
    for seal in seals:
        audit.sealed_path(output, seal)
    report_output = audit.ignored_output(root, report_output)
    publish(report_output / "report.json", result)
    return {
        "report_sha256": audit.file_hash(report_output / "report.json"),
        "comparison_status": result["comparison_status"],
        "cases": len(cases),
        "views": {
            name: value["complete_views"] for name, value in result["variants"].items()
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser(
        "freeze",
        help="Seal inputs, complete views and executed consumer before predictions",
    )
    for name in ("root", "packet", "labels", "baseline", "protocol", "output"):
        freeze.add_argument("--" + name, type=Path, required=True)
    freeze.add_argument("--protocol-sha256", required=True)
    run = commands.add_parser(
        "run", help="Run one fixed variant through real shared admission"
    )
    for name in ("root", "experiment"):
        run.add_argument("--" + name, type=Path, required=True)
    run.add_argument("--experiment-sha256", required=True)
    run.add_argument("--variant", choices=("control", "candidate"), required=True)
    report = commands.add_parser(
        "report", help="Score both fixed variants only after the original control gate"
    )
    for name in ("root", "experiment", "output"):
        report.add_argument("--" + name, type=Path, required=True)
    report.add_argument("--experiment-sha256", required=True)
    args = parser.parse_args(argv)
    if args.command == "freeze":
        result = freeze_experiment(
            args.root,
            args.packet,
            args.labels,
            args.baseline,
            args.protocol,
            args.protocol_sha256,
            args.output,
        )
    elif args.command == "run":
        result = run_variant(
            args.root, args.experiment, args.experiment_sha256, args.variant
        )
    else:
        result = evaluate_experiment(
            args.root, args.experiment, args.experiment_sha256, args.output
        )
    print(json.dumps(result, indent=2, allow_nan=False))
