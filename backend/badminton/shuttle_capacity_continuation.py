"""Remaining-only diagnostics with immutable, expired predecessor provenance."""

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from uuid import uuid4

import psutil

from . import shuttle_capacity as predecessor
from . import shuttle_resolution as existing
from . import shuttle_validation as audit

publish = existing.publish
VARIANTS = ("control", "decoder", "convolution")
PREPARATION = ".cache/capacity-remaining-preflight-v1.json"
PREVIOUS = ".cache/capacity311-experiment-v1"
PROTOCOL = {
    "schema_version": 1,
    "name": "shuttle-capacity-continuation-v1",
    "preparation_sha256": "d8bd6326129d0bf175c98c07c777d24d08aa8da2c15a49fb18541263ff869e37",
    "predecessor_experiment_sha256": "780374cc379534d853680bafa0159bcad7d6ee5783f942a616a9dd00a40d40f3",
    "predecessor_deadline": 1792981031,
    "parent_sha256": predecessor.PARENT_SHA256,
    "selected_sha256": {
        "decoder": "1506668b947a90f2d3cff79ef23a480aa97c9aed1a802fcffec9df6e8bb42598",
        "convolution": "2c65087f1849bc0a22740aa48c252b5cfd92a175693f08f18350c639082d4833",
    },
    "imported_control_views": 18,
    "imported_control_rows": 5436,
    "views": 50,
    "rows": 13499,
    "cases": 60,
    "truth_states": {"visible": 25, "not_visible": 7, "unknown": 28},
    "input_size": [512, 288],
    "sequence_length": 8,
    "device": "cuda:0",
    "precision": "float16",
    "threshold": 0.5,
    "control_projection": existing.PHYSICAL_PROJECTION,
    "confidence_absolute_tolerance": 0.00001,
    "confidence_relative_tolerance": 0,
    "localization_tolerance_diagonal": 0.005,
    "tensor_count": 104,
    "runtime_hours": 4,
    "retained_bytes": 4294967296,
    "limitations": [
        "The predecessor remains interrupted with its original expired clock and missing worker terminal.",
        "Inherited complete views are retained observations, not completed or fresh predecessor jobs.",
        "No training, synthetic test, selection, image assessment or model promotion occurs here.",
        "All familiar development cases and unknowns remain; complete scientific references are0/2.",
        "Agreement with agent labels does not establish independent or full-match annotation accuracy.",
    ],
}


def validate_protocol(value):
    if audit.encoded(value) != audit.encoded(PROTOCOL):
        raise ValueError("Continuation protocol differs from the fixed remaining phase")


def consumers(root):
    result = predecessor.consumers(root)
    runner = (
        Path(__file__).resolve().parents[2] / "scripts/continue_shuttle_capacity.py"
    )
    result["scripts/continue_shuttle_capacity.py"] = audit.seal(root, runner)
    return result


def budget(root):
    """One cumulative ledger; predecessor outputs and failures never disappear."""
    files = set()
    cache = root / ".cache"
    for prefix in ("capacity311", "capacity313", "capacity-next", "capacity-remaining"):
        for path in cache.glob(prefix + "*"):
            files.update(
                p.resolve()
                for p in (path.rglob("*") if path.is_dir() else [path])
                if p.is_file()
            )
    for name in ("capacity311-e1", "capacity313-e1"):
        files.update(
            p.resolve() for p in (cache / "worktrees" / name).rglob("*") if p.is_file()
        )
    size = sum(path.stat().st_size for path in files)
    if size > PROTOCOL["retained_bytes"]:
        raise ValueError("Cumulative retained-output budget exceeded")
    return {
        "bytes": size,
        "files": len(files),
        "limit_bytes": PROTOCOL["retained_bytes"],
    }


def terminal_proof(output, shared, *, completed=False):
    proofs = existing.prior_attempt_proof(output, shared)
    stages = set()
    for proof in proofs:
        if proof["store_status"] not in {
            "completed",
            "failed",
            "cancelled",
            "interrupted",
        }:
            raise ValueError("Prior Store job is not terminal")
        admission_path = audit.sealed_path(output, proof["admission"])
        admission = audit.read_json(admission_path.read_bytes())
        terminal_path = admission_path.parent / "terminal.json"
        if proof["store_status"] == "completed":
            if not terminal_path.is_file():
                raise ValueError("Completed Store job lacks its worker terminal")
            terminal = audit.read_json(terminal_path.read_bytes())
            if terminal.get("status") != "completed":
                raise ValueError("Store and worker terminal disagree")
            proof["worker_terminal"] = audit.seal(output, terminal_path)
            stages.add(admission["stage"])
        else:
            proof["worker_terminal"] = (
                audit.seal(output, terminal_path) if terminal_path.is_file() else None
            )
    if completed and not {"tensor-audit", *VARIANTS} <= stages:
        raise ValueError(
            "All remaining stages need completed Store and worker terminals"
        )
    return proofs


def validate_predecessor(root):
    """Read fixed predecessor seals without calling or weakening its expired loader."""
    preparation = root / PREPARATION
    if audit.file_hash(preparation) != PROTOCOL["preparation_sha256"]:
        raise ValueError("Changed remaining-phase preparation")
    ready = audit.read_json(preparation.read_bytes())
    for name, seal in ready["seals"].items():
        if audit.file_hash(audit.inside(root, name)) != seal["sha256"]:
            raise ValueError("Changed sealed predecessor/input")
    old = root / PREVIOUS
    if (
        audit.file_hash(old / "experiment.json")
        != PROTOCOL["predecessor_experiment_sha256"]
    ):
        raise ValueError("Changed predecessor experiment")
    experiment = audit.read_json((old / "experiment.json").read_bytes())
    if (
        experiment.get("deadline") != PROTOCOL["predecessor_deadline"]
        or time.time() < experiment["deadline"]
    ):
        raise ValueError("Original expired predecessor deadline must remain unchanged")
    predecessor.validate_protocol(audit.read_json((old / "protocol.json").read_bytes()))
    current = consumers(root)
    if len(experiment["consumer_files"]) != 84:
        raise ValueError("Changed predecessor consumer membership")
    for name, seal in experiment["consumer_files"].items():
        audit.sealed_path(root, seal)
        if (
            current.get(name, {}).get("sha256") != seal["sha256"]
            or audit.file_hash(audit.inside(old / "consumer", name)) != seal["sha256"]
        ):
            raise ValueError("Changed predecessor executable or frozen copy")
    if existing.runtime_snapshot() != experiment["runtime"]:
        raise ValueError("Changed predecessor runtime")
    for method in predecessor.VARIANTS:
        override = predecessor.selected(old, method)
        if (
            predecessor.checkpoint_override(override)[1]
            != PROTOCOL["selected_sha256"][method]
        ):
            raise ValueError("Changed validation-selected checkpoint")
    recovery = audit.read_json(
        (root / ".cache/capacity311-interruption-recovered-v1.json").read_bytes()
    )
    if (
        recovery.get("store_after", {}).get("status") != "interrupted"
        or recovery.get("original_worker_terminal_absent") is not True
        or recovery.get("restart_performed") is not False
    ):
        raise ValueError("Original interruption provenance changed")
    prior = terminal_proof(old, root / "data/processed")
    if not any(p["store_status"] == "interrupted" for p in prior):
        raise ValueError("Original interrupted Store job must remain explicit")
    actual = {
        p.relative_to(root).as_posix(): audit.file_hash(p)
        for p in (old / "control").glob("*.json")
    }
    if actual != ready["predecessor_view_seals"]:
        raise ValueError("Changed inherited control membership or bytes")
    if any(
        (old / name).exists()
        for name in (
            "report.json",
            "report-opened.json",
            "raw-index.json",
            "tensor-audit.json",
        )
    ):
        raise ValueError("Predecessor unfinished stages must remain untouched")
    if (
        len(experiment["views"]) != PROTOCOL["views"]
        or sum(v["end_frame"] - v["start_frame"] for v in experiment["views"])
        != PROTOCOL["rows"]
    ):
        raise ValueError("Changed complete original view plan")
    return experiment, ready, prior


def freeze(root, protocol_path, protocol_sha256, output, granted_at, deadline):
    root, output = root.resolve(), output.resolve()
    raw = protocol_path.read_bytes()
    if audit.digest(raw) != protocol_sha256:
        raise ValueError("Changed public protocol bytes")
    validate_protocol(audit.read_json(raw))
    if (
        not audit.finite(granted_at)
        or not audit.finite(deadline)
        or deadline != granted_at + 4 * 3600
        or not granted_at <= time.time() < deadline
    ):
        raise ValueError(
            "Original fresh grant and immutable four-hour deadline required"
        )
    if not output.name.startswith("capacity313-") or not output.is_relative_to(
        root / ".cache"
    ):
        raise ValueError("Separate ignored continuation namespace required")
    previous, ready, proof = validate_predecessor(root)
    inputs = predecessor.diagnostic_inputs(root, previous)
    inherited = predecessor.completed_views(
        root / PREVIOUS,
        "control",
        previous,
        PROTOCOL["predecessor_experiment_sha256"],
        inputs,
    )
    if (
        len(inherited) != PROTOCOL["imported_control_views"]
        or sum(run["processed_frames"] for _, run in inherited.values())
        != PROTOCOL["imported_control_rows"]
    ):
        raise ValueError("Inherited complete-view denominator changed")
    partial = {"views": [view for view in previous["views"] if view["id"] in inherited]}
    if not compare_control(partial, inherited, inputs[4])["compatible"]:
        raise ValueError(
            "Inherited physical control differs before remaining inference"
        )
    budget(root)
    output = audit.ignored_output(root, output)
    code = consumers(root)
    for name, seal in code.items():
        path = audit.inside(output / "consumer", name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(audit.sealed_bytes(root, seal))
    with (output / "protocol.json").open("xb") as stream:
        stream.write(raw)
    value = {
        "protocol_sha256": protocol_sha256,
        "granted_at": granted_at,
        "deadline": deadline,
        "consumer_files": code,
        "runtime": existing.runtime_snapshot(),
        "views": previous["views"],
        "predecessor_views": ready["predecessor_view_seals"],
        "predecessor_terminal_proof": proof,
        "preparation_sha256": PROTOCOL["preparation_sha256"],
    }
    publish(output / "experiment.json", value)
    return {"experiment_sha256": audit.file_hash(output / "experiment.json")}


def load(root, output, expected):
    root, output = root.resolve(), output.resolve()
    if not output.name.startswith("capacity313-") or not output.is_relative_to(
        root / ".cache"
    ):
        raise ValueError("Separate ignored continuation namespace required")
    if audit.file_hash(output / "experiment.json") != expected:
        raise ValueError("Changed frozen continuation experiment")
    value = audit.read_json((output / "experiment.json").read_bytes())
    if (
        not audit.finite(value.get("granted_at"))
        or not audit.finite(value.get("deadline"))
        or value["deadline"] != value["granted_at"] + 4 * 3600
        or not value["granted_at"] <= time.time() < value["deadline"]
    ):
        raise ValueError("Original continuation deadline expired or changed")
    raw = (output / "protocol.json").read_bytes()
    if audit.digest(raw) != value["protocol_sha256"]:
        raise ValueError("Changed continuation protocol")
    validate_protocol(audit.read_json(raw))
    if (
        consumers(root) != value["consumer_files"]
        or existing.runtime_snapshot() != value["runtime"]
    ):
        raise ValueError("Changed continuation consumers/runtime")
    for name, seal in value["consumer_files"].items():
        audit.sealed_path(root, seal)
        if audit.file_hash(audit.inside(output / "consumer", name)) != seal["sha256"]:
            raise ValueError("Changed frozen continuation consumer")
    previous, ready, proof = validate_predecessor(root)
    if (
        value["views"] != previous["views"]
        or value["predecessor_views"] != ready["predecessor_view_seals"]
        or value["predecessor_terminal_proof"] != proof
        or value["preparation_sha256"] != PROTOCOL["preparation_sha256"]
    ):
        raise ValueError("Changed predecessor continuation binding")
    budget(root)
    return value


def admission(root, output, expected, stage, function):
    from . import config
    from .jobs import run_local_job
    from .storage import Store

    experiment = load(root, output, expected)
    shared = root.resolve() / "data/processed"
    if (
        config.ROOT != root.resolve()
        or config.DATA.resolve() != shared
        or config.WEIGHTS.resolve() != root.resolve() / "models/weights"
        or not (shared / "catalog.sqlite3").is_file()
    ):
        raise ValueError("Pin real original root/shared Store/weights before imports")
    prior = terminal_proof(output, shared)
    attempt = output / "attempts" / uuid4().hex
    attempt.mkdir(parents=True)
    publish(attempt / "prior-terminal-proof.json", prior)
    began = time.perf_counter()

    def task(job_id, progress):
        import torch
        import torchvision  # noqa: F401

        process = psutil.Process()
        publish(
            attempt / "admission.json",
            {
                "job_id": job_id,
                "stage": stage,
                "experiment_sha256": expected,
                "process": {
                    "pid": process.pid,
                    "creation_time": process.create_time(),
                    "cwd": process.cwd(),
                    "command": list(sys.argv),
                },
            },
        )
        if not torch.cuda.is_available():
            raise ValueError("Frozen continuation requires actual original CUDA host")
        torch.cuda.reset_peak_memory_stats()

        def bounded_progress(value):
            if time.time() >= experiment["deadline"]:
                raise ValueError("Original continuation deadline reached")
            progress(value)

        result = function(experiment, attempt, bounded_progress)
        load(root, output, expected)
        publish(
            attempt / "cost.json",
            {
                "elapsed_s": time.perf_counter() - began,
                "peak_tensor_bytes": torch.cuda.max_memory_allocated(),
            },
        )
        return result

    try:
        result = run_local_job(Store(shared), "feature-preparation", None, task)
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
    return {"result": result, "attempt": attempt.relative_to(output).as_posix()}


def audit_states(parent, selected, method, frozen):
    """CPU state bytes only; this function constructs no model or optimizer."""
    import torch

    eligible = set(predecessor.trainable_names(method))
    if (
        len(parent) != PROTOCOL["tensor_count"]
        or set(parent) != set(selected)
        or not eligible <= set(parent)
    ):
        raise ValueError("Changed selected tensor membership")
    changed, observed_frozen = [], {}
    for name, tensor in selected.items():
        original = parent[name]
        if (
            not isinstance(tensor, torch.Tensor)
            or not isinstance(original, torch.Tensor)
            or tensor.device.type != "cpu"
            or original.device.type != "cpu"
            or tensor.shape != original.shape
            or tensor.dtype != original.dtype
            or not torch.isfinite(tensor).all()
            or not torch.isfinite(original).all()
        ):
            raise ValueError("Selected CPU tensor shape/dtype/finite state changed")
        checksum = hashlib.sha256(
            tensor.detach().contiguous().numpy().tobytes()
        ).hexdigest()
        before = hashlib.sha256(
            original.detach().contiguous().numpy().tobytes()
        ).hexdigest()
        if checksum != before:
            changed.append(name)
        if name not in eligible:
            if checksum != before:
                raise ValueError("Frozen tensor bytes changed")
            observed_frozen[name] = checksum
    if set(changed) != eligible or observed_frozen != frozen:
        raise ValueError("Selected changes or recorded frozen tensor hashes differ")
    return {
        "changed_tensors": sorted(changed),
        "tensor_count": len(parent),
        "byte_equal_frozen_tensors": len(observed_frozen),
        "all_shapes_dtypes_finite": True,
        "all_tensors_read_on_cpu": True,
    }


def tensor_audit(root, output, expected):
    load(root, output, expected)
    publish(output / "tensor-audit-opened.json", {"experiment_sha256": expected})

    def task(experiment, attempt, progress):
        import torch

        parent = torch.load(
            root / "models/weights/TrackNet_best.pt",
            map_location="cpu",
            weights_only=True,
        )["model"]
        results = {}
        for index, method in enumerate(predecessor.VARIANTS):
            override = predecessor.selected(root / PREVIOUS, method)
            path, checksum, _ = predecessor.checkpoint_override(override)
            selected = torch.load(path, map_location="cpu", weights_only=True)["model"]
            training = audit.read_json(
                (root / PREVIOUS / method / "training.json").read_bytes()
            )
            results[method] = {
                **audit_states(
                    parent, selected, method, training["frozen_tensor_hashes"]
                ),
                "checkpoint_sha256": checksum,
                "selection_sha256": override["selection_sha256"],
            }
            progress((index + 1) / 2)
        load(root, output, expected)
        publish(
            output / "tensor-audit.json",
            {
                "experiment_sha256": expected,
                "methods": results,
                "model_constructed": False,
                "forward_or_optimizer_executed": False,
            },
        )
        return {"tensor_audit_sha256": audit.file_hash(output / "tensor-audit.json")}

    return admission(root, output, expected, "tensor-audit", task)


def require_tensor_audit(output, expected):
    value = audit.read_json((output / "tensor-audit.json").read_bytes())
    if (
        value.get("experiment_sha256") != expected
        or value.get("model_constructed") is not False
        or value.get("forward_or_optimizer_executed") is not False
        or set(value.get("methods", {})) != set(predecessor.VARIANTS)
    ):
        raise ValueError("Missing bound independent selected-tensor audit")
    for method, result in value["methods"].items():
        count = len(predecessor.trainable_names(method))
        if (
            result.get("checkpoint_sha256") != PROTOCOL["selected_sha256"][method]
            or result.get("tensor_count") != 104
            or result.get("changed_tensors")
            != sorted(predecessor.trainable_names(method))
            or result.get("byte_equal_frozen_tensors") != 104 - count
            or result.get("all_shapes_dtypes_finite") is not True
            or result.get("all_tensors_read_on_cpu") is not True
        ):
            raise ValueError("Selected-tensor audit result changed")
    return value


def completed_views(root, output, variant, experiment, expected, inputs):
    if variant not in VARIANTS:
        raise ValueError("Unknown fixed continuation variant")
    _, sources, _, baseline, originals, _ = inputs
    results = {}
    checksum = (
        PROTOCOL["parent_sha256"]
        if variant == "control"
        else PROTOCOL["selected_sha256"][variant]
    )
    recipe = {
        "checkpoint_sha256": checksum,
        "sequence_length": 8,
        "variants": {variant: [512, 288]},
        "device": "cuda:0",
        "precision": "float16",
        "spatial_layouts": {variant: "full"},
    }
    for view in experiment["views"]:
        old_name = PREVIOUS + "/control/" + view["id"] + ".json"
        path = output / variant / (view["id"] + ".json")
        inherited = variant == "control" and old_name in experiment["predecessor_views"]
        if inherited:
            if path.exists():
                raise ValueError(
                    "Inherited complete view must not be rerun or replaced"
                )
            path = audit.sealed_path(
                root,
                {"path": old_name, "sha256": experiment["predecessor_views"][old_name]},
            )
            base, binding, origin = (
                root / PREVIOUS,
                PROTOCOL["predecessor_experiment_sha256"],
                "predecessor",
            )
        elif path.exists():
            base, binding, origin = output, expected, "continuation"
        else:
            continue
        entry = audit.read_json(path.read_bytes())
        if entry.get("experiment_sha256") != binding or entry.get("view") != view:
            raise ValueError("Changed complete-view lineage")
        run = audit.read_json(audit.sealed_bytes(base, entry["run"]))
        _, meta, times, _ = next(s for s in sources if s[1]["id"] == view["video_id"])
        annotations = baseline["evidence"]["catalogs"][view["video_id"]]["snapshot"][
            "annotations"
        ]
        existing.validate_research_run(
            run,
            view,
            variant,
            recipe,
            originals[(view["video_id"], view["core_index"])],
            meta,
            times,
            annotations=annotations,
        )
        if variant == "control":
            if "research_adaptation" in run:
                raise ValueError("Parent control checkpoint enforcement changed")
        elif (
            run.get("research_adaptation")
            != predecessor.checkpoint_override(
                predecessor.selected(root / PREVIOUS, variant)
            )[2]
        ):
            raise ValueError("Changed fixed selected-checkpoint provenance")
        reference = {
            "origin": origin,
            "receipt": audit.seal(root, path),
            "run": audit.seal(root, audit.sealed_path(base, entry["run"])),
        }
        results[view["id"]] = (reference, run)
    return results


def compare_control(experiment, values, originals):
    differences = []
    for view in experiment["views"]:
        if view["id"] not in values:
            raise ValueError("All original control views required before candidates")
        original = originals[(view["video_id"], view["core_index"])]
        expected = original["frames"][
            view["start_frame"] - original["start_frame"] : view["end_frame"]
            - original["start_frame"]
        ]
        if (
            audit.digest(audit.encoded([existing.native_row(row) for row in expected]))
            != view["expected_rows_sha256"]
        ):
            raise ValueError("Original control rows changed")
        changed = existing.compare_rows(
            [
                existing.native_row(row, existing.PHYSICAL_PROJECTION)
                for row in expected
            ],
            [
                existing.native_row(row, existing.PHYSICAL_PROJECTION)
                for row in values[view["id"]][1]["frames"]
            ],
            1e-5,
        )
        differences.extend({"view": view["id"], "field": field} for field in changed)
    return {
        "compatible": not differences,
        "differences": differences,
        "projection": existing.PHYSICAL_PROJECTION,
        "omitted_dependency_fields": sorted(existing.DEPENDENCY_FIELDS),
        "control_runs": [reference for reference, _ in values.values()],
    }


def control_gate(root, output, experiment, expected, inputs):
    return compare_control(
        experiment,
        completed_views(root, output, "control", experiment, expected, inputs),
        inputs[4],
    )


def native_variant(root, output, expected, variant):
    from . import shuttle

    if variant not in VARIANTS:
        raise ValueError("Unknown fixed continuation variant")
    experiment = load(root, output, expected)
    require_tensor_audit(output, expected)
    inputs = predecessor.diagnostic_inputs(root, experiment)
    if (
        variant != "control"
        and not control_gate(root, output, experiment, expected, inputs)["compatible"]
    ):
        raise ValueError("Original control mismatch blocks candidates")
    prior = completed_views(root, output, variant, experiment, expected, inputs)
    if len(prior) == len(experiment["views"]):
        raise ValueError("Variant already complete; never silently repeat")

    def task(experiment, attempt, progress):
        _, sources, _, baseline, _, plans = inputs
        (output / variant).mkdir(exist_ok=True)
        for index, view in enumerate(experiment["views"]):
            if view["id"] in prior:
                continue
            load(root, output, expected)
            vid = view["video_id"]
            _, source, _, _ = next(s for s in sources if s[1]["id"] == vid)
            data = audit.inside(root, baseline["locations"]["data"])
            seal = plans[vid]["segments"]
            camera = data / vid / "runs" / (seal["run_id"] + ".json")
            if audit.file_hash(camera) != seal["sha256"]:
                raise ValueError("Original complete camera scan changed")
            run_path = attempt / (view["id"] + ".json")
            shuttle.track_shuttle(
                source,
                root,
                data,
                view["start_frame"],
                view["end_frame"],
                lambda value: progress((index + value) / len(experiment["views"])),
                run_path,
                annotations=baseline["evidence"]["catalogs"][vid]["snapshot"][
                    "annotations"
                ],
                camera_scan=audit.read_json(camera.read_bytes()),
                spatial_layout="full",
                **(
                    {
                        "research_checkpoint": predecessor.selected(
                            root / PREVIOUS, variant
                        )
                    }
                    if variant != "control"
                    else {}
                ),
            )
            load(root, output, expected)
            publish(
                output / variant / (view["id"] + ".json"),
                {
                    "experiment_sha256": expected,
                    "view": view,
                    "run": audit.seal(output, run_path),
                },
            )
        predecessor.diagnostic_inputs(root, experiment)
        values = completed_views(root, output, variant, experiment, expected, inputs)
        if len(values) != len(experiment["views"]):
            raise ValueError("Every complete original view must remain")
        if variant == "control":
            gate = control_gate(root, output, experiment, expected, inputs)
            publish(attempt / "control-gate.json", gate)
            if not gate["compatible"]:
                raise ValueError("Complete original control did not reproduce")
        return {
            "variant": variant,
            "views": len(values),
            "new_views": len(values) - len(prior),
        }

    return admission(root, output, expected, variant, task)


def raw_index(root, output, expected):
    if (output / "raw-index.json").exists():
        raise ValueError("Raw outputs already sealed")
    experiment = load(root, output, expected)
    require_tensor_audit(output, expected)
    inputs = predecessor.diagnostic_inputs(root, experiment)
    if not control_gate(root, output, experiment, expected, inputs)["compatible"]:
        raise ValueError("Control mismatch blocks raw seal")
    references = {}
    for variant in VARIANTS:
        values = completed_views(root, output, variant, experiment, expected, inputs)
        if (
            len(values) != PROTOCOL["views"]
            or sum(run["processed_frames"] for _, run in values.values())
            != PROTOCOL["rows"]
        ):
            raise ValueError("All complete raw views required before scoring")
        references[variant] = [reference for reference, _ in values.values()]
    proofs = terminal_proof(output, root / "data/processed", completed=True)
    files = {
        p.relative_to(output).as_posix(): audit.seal(output, p)
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    load(root, output, expected)
    publish(
        output / "raw-index.json",
        {
            "experiment_sha256": expected,
            "files": files,
            "references": references,
            "terminal_proofs": proofs,
            "predecessor_terminal_proofs": experiment["predecessor_terminal_proof"],
            "labels_scored": False,
            "budget": budget(root),
        },
    )
    return {"raw_index_sha256": audit.file_hash(output / "raw-index.json")}


def paired_transitions(left, right):
    if [row["id"] for row in left] != [row["id"] for row in right]:
        raise ValueError("Paired diagnostic membership changed")
    return dict(
        sorted(
            Counter(
                a["outcome"] + "->" + b["outcome"] for a, b in zip(left, right)
            ).items()
        )
    )


def report(root, output, expected, public_seal_sha256):
    if (output / "report-opened.json").exists() or (output / "report.json").exists():
        raise ValueError("Familiar diagnostics already opened; never repeat")
    public_path = output / "raw-public-seal.json"
    if audit.file_hash(public_path) != public_seal_sha256:
        raise ValueError("Exact externally timestamped raw seal required")
    public = audit.read_json(public_path.read_bytes())
    if not public.get("comment", "").startswith(
        "https://github.com/Ken0u/badminton-match-analyzer/issues/313#issuecomment-"
    ) or audit.file_hash(output / "raw-index.json") != public.get("raw_index_sha256"):
        raise ValueError("Missing exact owning-issue raw-output commitment")
    raw = audit.read_json((output / "raw-index.json").read_bytes())
    if (
        raw.get("experiment_sha256") != expected
        or raw.get("labels_scored") is not False
    ):
        raise ValueError("Raw seal experiment/scoring binding changed")
    for entry in raw["files"].values():
        audit.sealed_path(output, entry)
    experiment = load(root, output, expected)
    require_tensor_audit(output, expected)
    if (
        terminal_proof(output, root / "data/processed", completed=True)
        != raw["terminal_proofs"]
    ):
        raise ValueError("Changed raw terminal provenance")
    inputs = predecessor.diagnostic_inputs(root, experiment)
    packet, _, labels, _, _, _ = inputs
    if (
        len(packet["cases"]) != PROTOCOL["cases"]
        or dict(Counter(entry["label"]["state"] for entry in labels["cases"]))
        != PROTOCOL["truth_states"]
    ):
        raise ValueError("All original familiar labels/unknowns must remain")
    gate = control_gate(root, output, experiment, expected, inputs)
    if not gate["compatible"]:
        raise ValueError("Control mismatch prevents familiar scoring")
    publish(
        output / "report-opened.json",
        {"experiment_sha256": expected, "public_seal_sha256": public_seal_sha256},
    )
    results = {}
    for variant in VARIANTS:
        values = completed_views(root, output, variant, experiment, expected, inputs)
        if len(values) != PROTOCOL["views"]:
            raise ValueError("Raw view missing after public seal")
        observations = {}
        for view in experiment["views"]:
            run = values[view["id"]][1]
            for case_id in view["case_ids"]:
                case = next(c for c in packet["cases"] if c["id"] == case_id)
                observations[case_id] = {
                    "available": True,
                    "point": run["frames"][case["frame"] - view["start_frame"]][
                        "shuttle"
                    ],
                    "reason": None,
                }
        results[variant] = {
            "groups": existing.grouped_scores(
                packet["cases"], labels["cases"], observations
            ),
            "cases_retained": len(observations),
            "views": len(values),
            "native_rows": sum(run["processed_frames"] for _, run in values.values()),
            "model_calls": sum(run["model_calls"] for _, run in values.values()),
            "elapsed_s": sum(run["elapsed_s"] for _, run in values.values()),
            "peak_tensor_mb": max(
                run["peak_gpu_memory_mb"] for _, run in values.values()
            ),
        }
    pairs = {
        method: paired_transitions(
            results["control"]["groups"]["all"]["metrics"]["frames"],
            results[method]["groups"]["all"]["metrics"]["frames"],
        )
        for method in predecessor.VARIANTS
    }
    load(root, output, expected)
    publish(
        output / "report.json",
        {
            "experiment_sha256": expected,
            "public_raw_seal": public,
            "control_gate": gate,
            "variants": results,
            "paired_transitions": pairs,
            "limitations": PROTOCOL["limitations"],
            "promoted": False,
            "complete_references": "0/2",
        },
    )
    return {"report_sha256": audit.file_hash(output / "report.json")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=("freeze", "tensor-audit", *VARIANTS, "raw-index", "report")
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--protocol-sha256")
    parser.add_argument("--granted-at", type=float)
    parser.add_argument("--deadline", type=float)
    parser.add_argument("--experiment-sha256")
    parser.add_argument("--public-seal-sha256")
    args = parser.parse_args(argv)
    root, output = args.root.resolve(), args.output.resolve()
    if args.stage == "freeze":
        result = freeze(
            root,
            args.protocol,
            args.protocol_sha256,
            output,
            args.granted_at,
            args.deadline,
        )
    elif args.stage in VARIANTS:
        result = native_variant(root, output, args.experiment_sha256, args.stage)
    elif args.stage == "report":
        result = report(root, output, args.experiment_sha256, args.public_seal_sha256)
    else:
        result = {"tensor-audit": tensor_audit, "raw-index": raw_index}[args.stage](
            root, output, args.experiment_sha256
        )
    print(json.dumps(result, allow_nan=False))
