"""Frozen research-only observed-component selection experiment.

This consumer never installs weights, edits reviewed annotations, acquires media,
or reruns an expired predecessor. Existing observations are immutable inputs.
"""

import argparse
import itertools
import json
import sys
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psutil
from PIL import Image

from . import shuttle_resolution as existing
from . import shuttle_validation as audit

VARIANTS = ("control", "decoder", "convolution")
publish = existing.publish


def protocol_value():
    from .shuttle_selection_synthetic import PROTOCOL

    return PROTOCOL


def validate_protocol(value):
    if audit.encoded(value) != audit.encoded(protocol_value()):
        raise ValueError("Protocol differs from the frozen component-selection study")


def consumers(root):
    package = Path(__file__).resolve().parent
    code_root = (
        package.parents[1] if package.parent.name == "backend" else package.parent
    )
    files = {
        "badminton/" + p.relative_to(package).as_posix(): p
        for p in package.rglob("*.py")
    }
    files["badminton/model_manifest.json"] = package / "model_manifest.json"
    for name in (
        "study_shuttle_selection.py",
        "compare_shuttle_capacity.py",
        "compare_shuttle_resolution.py",
    ):
        files["scripts/" + name] = code_root / "scripts" / name
    return {name: audit.seal(root, path) for name, path in sorted(files.items())}


def new_output_bytes(root):
    """Count this study's outputs without deleting or resetting historical ledgers."""
    paths = set()
    for name in (
        "selector330*",
        "selector-planning*",
        "selector-plan*",
        "selector-preflight*",
    ):
        for path in (root / ".cache").glob(name):
            paths.update(
                p.resolve()
                for p in (path.rglob("*") if path.is_dir() else [path])
                if p.is_file()
            )
    for worktree in (root / ".cache/worktrees").glob("selector330*"):
        paths.update(p.resolve() for p in worktree.rglob("*") if p.is_file())
    return sum(p.stat().st_size for p in paths)


def retained_budget(root, output, limit, refresh_seconds=60):
    """Count live stage outputs immediately; periodically refresh preserved bytes.

    Completed test fixtures and other preserved task outputs remain charged.
    Scanning their full inventory on every group would dominate model inference.
    """
    root, output = root.resolve(), output.resolve()
    if (
        type(limit) is not int
        or limit <= 0
        or not audit.finite(refresh_seconds)
        or refresh_seconds <= 0
    ):
        raise ValueError("Positive retained byte limit and refresh interval required")

    def dynamic_bytes():
        return sum(p.stat().st_size for p in output.rglob("*") if p.is_file())

    roots = [
        p.resolve()
        for pattern in (
            "selector330*",
            "selector-planning*",
            "selector-plan*",
            "selector-preflight*",
        )
        for p in (root / ".cache").glob(pattern)
    ]
    roots.extend(p.resolve() for p in (root / ".cache/worktrees").glob("selector330*"))
    counted = any(output.is_relative_to(p) for p in roots)
    total, dynamic = new_output_bytes(root), dynamic_bytes()
    static = max(0, total - dynamic) if counted else total
    refreshed = time.monotonic()

    def check():
        nonlocal static, refreshed
        if time.monotonic() - refreshed >= refresh_seconds:
            total, dynamic = new_output_bytes(root), dynamic_bytes()
            static = max(0, total - dynamic) if counted else total
            refreshed = time.monotonic()
        used = static + dynamic_bytes()
        if used >= limit:
            raise ValueError("New retained output budget reached")
        return used

    check()
    return check


def verify_inputs(root, protocol):
    """Hash inputs only; do not deserialize predictions, labels or tensors."""
    borrowed = {}
    for name, entry in protocol["input_artifacts"].items():
        path = audit.sealed_path(root, entry)
        borrowed[name] = {**entry, "bytes": path.stat().st_size}
    return borrowed


def seed_inventory():
    from . import shuttle_capacity_synthetic as previous
    from . import shuttle_selection_synthetic as fresh
    from . import shuttle_synthetic as historical

    result = {
        split: [fresh.group_seed(split, i) for i in range(count)]
        for split, count in fresh.SPLITS.items()
    }
    all_seeds = [v for values in result.values() for v in values]
    old = {
        module.group_seed(split, i)
        for module in (previous, historical)
        for split, count in module.SPLITS.items()
        for i in range(count)
    }
    if len(set(all_seeds)) != sum(fresh.SPLITS.values()) or set(all_seeds) & old:
        raise ValueError("Generated source groups overlap current or consumed splits")
    return result


def freeze(root, protocol_path, protocol_sha256, output, granted_at, deadline):
    root, output = root.resolve(), output.resolve()
    raw = protocol_path.read_bytes()
    if audit.digest(raw) != protocol_sha256:
        raise ValueError("Changed public protocol bytes")
    protocol = audit.read_json(raw)
    validate_protocol(protocol)
    if (
        not audit.finite(granted_at)
        or not audit.finite(deadline)
        or deadline != granted_at + protocol["limits"]["runtime_hours"] * 3600
        or not granted_at <= time.time() < deadline
    ):
        raise ValueError("Original committed grant and immutable deadline required")
    seeds = seed_inventory()  # Metadata only: no held-out pixels or labels.
    inputs = verify_inputs(root, protocol)
    code, runtime = consumers(root), existing.runtime_snapshot()
    if new_output_bytes(root) >= protocol["limits"]["new_retained_bytes"]:
        raise ValueError("New study output budget exhausted")
    output = audit.ignored_output(root, output)
    for name, entry in code.items():
        destination = audit.inside(output / "consumer", name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(audit.sealed_bytes(root, entry))
    with (output / "protocol.json").open("xb") as stream:
        stream.write(raw)
    record = {
        "schema_version": 1,
        "protocol_sha256": protocol_sha256,
        "consumer_files": code,
        "runtime": runtime,
        "inputs": inputs,
        "split_seeds": seeds,
        "granted_at": granted_at,
        "deadline": deadline,
        "shared_data": "data/processed",
        "borrowed_input_bytes": sum(v["bytes"] for v in inputs.values()),
        "new_output_bytes": new_output_bytes(root),
    }
    if consumers(root) != code or protocol_path.read_bytes() != raw:
        raise ValueError("Executable/protocol bytes changed during freeze")
    publish(output / "experiment.json", record)
    return {"experiment_sha256": audit.file_hash(output / "experiment.json")}


def load(root, output, expected):
    root, output = root.resolve(), output.resolve()
    if not output.is_relative_to(root / ".cache"):
        raise ValueError("Study output must stay in the original ignored cache")
    if audit.file_hash(output / "experiment.json") != expected:
        raise ValueError("Changed experiment receipt")
    experiment = audit.read_json((output / "experiment.json").read_bytes())
    raw = (output / "protocol.json").read_bytes()
    if audit.digest(raw) != experiment["protocol_sha256"]:
        raise ValueError("Changed frozen protocol bytes")
    protocol = audit.read_json(raw)
    validate_protocol(protocol)
    if (
        not audit.finite(experiment["granted_at"])
        or not audit.finite(experiment["deadline"])
        or experiment["deadline"]
        != experiment["granted_at"] + protocol["limits"]["runtime_hours"] * 3600
        or not experiment["granted_at"] <= time.time() < experiment["deadline"]
    ):
        raise ValueError("Original study deadline expired or changed")
    current_code = consumers(root)
    if {k: v["sha256"] for k, v in current_code.items()} != {
        k: v["sha256"] for k, v in experiment["consumer_files"].items()
    }:
        raise ValueError("Study executable source bytes changed")
    for name, entry in experiment["consumer_files"].items():
        audit.sealed_path(root, entry)
        if audit.file_hash(audit.inside(output / "consumer", name)) != entry["sha256"]:
            raise ValueError("Frozen consumer copy changed")
    if existing.runtime_snapshot() != experiment["runtime"]:
        raise ValueError("Study runtime changed")
    if verify_inputs(root, protocol) != experiment["inputs"]:
        raise ValueError("Borrowed immutable inputs changed")
    if seed_inventory() != experiment["split_seeds"]:
        raise ValueError("Generated source-group mapping changed")
    if new_output_bytes(root) >= protocol["limits"]["new_retained_bytes"]:
        raise ValueError("New study output budget exhausted")
    return experiment, protocol


def admission(root, output, expected, stage, function, *, gpu=False):
    from . import config
    from .jobs import run_local_job
    from .storage import Store

    root, output = root.resolve(), output.resolve()
    experiment, protocol = load(root, output, expected)
    shared = root / "data/processed"
    if (
        config.ROOT != root
        or config.DATA.resolve() != shared
        or config.WEIGHTS.resolve() != root / "models/weights"
        or not (shared / "catalog.sqlite3").is_file()
    ):
        raise ValueError("Pin original root, shared Store and weights before imports")
    prior = existing.prior_attempt_proof(output, shared)
    if any(p["store_status"] in ("running", "queued") for p in prior):
        raise ValueError("Prior Store job is not terminal; use normal recovery first")
    attempt = output / "attempts" / uuid4().hex
    attempt.mkdir(parents=True)
    publish(attempt / "prior-terminal-proof.json", prior)
    started = time.perf_counter()
    check_budget = retained_budget(
        root, output, protocol["limits"]["new_retained_bytes"]
    )

    def task(job_id, progress):
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
        if gpu:
            import torch
            import torchvision  # noqa: F401

            if not torch.cuda.is_available():
                raise ValueError("Frozen inference requires the actual CUDA host")
            torch.cuda.reset_peak_memory_stats()

        def bounded_progress(value):
            if time.time() >= experiment["deadline"]:
                raise ValueError("Original study deadline reached")
            check_budget()
            progress(value)

        result = function(experiment, protocol, attempt, bounded_progress)
        load(root, output, expected)
        cost = {"elapsed_s": time.perf_counter() - started}
        if gpu:
            cost["peak_tensor_bytes"] = torch.cuda.max_memory_allocated()
        publish(attempt / "cost.json", cost)
        return result

    try:
        result = run_local_job(Store(shared), "feature-preparation", None, task)
    except BaseException as exc:
        publish(
            attempt / "terminal.json",
            {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)},
        )
        raise
    publish(attempt / "terminal.json", {"status": "completed", "result": result})
    return {"result": result, "attempt": attempt.relative_to(output).as_posix()}


def checkpoint_paths(root, protocol):
    """Use only the three fixed bytes; old experiment deadlines are not renewed."""
    from . import shuttle_capacity as capacity

    paths = {
        "control": audit.sealed_path(
            root, protocol["input_artifacts"]["parent-checkpoint"]
        )
    }
    for variant in VARIANTS[1:]:
        selection = protocol["input_artifacts"][variant + "-selection"]
        directory = audit.sealed_path(root, selection).parent.parent
        path, checksum, _ = capacity.checkpoint_override(
            {
                "study": capacity.STUDY,
                "variant": variant,
                "output": str(directory),
                "selection_sha256": selection["sha256"],
            }
        )
        expected = protocol["input_artifacts"][variant + "-checkpoint"]
        if path != audit.sealed_path(root, expected) or checksum != expected["sha256"]:
            raise ValueError("Changed original validation-selected checkpoint")
        paths[variant] = path
    return paths


def generated_group(split, index):
    from . import shuttle_selection_synthetic as synthetic

    frames, background, labels = synthetic.generate_group(split, index)
    return (
        frames,
        background,
        {
            "split": split,
            "index": index,
            "seed": synthetic.group_seed(split, index),
            "pixels_sha256": audit.digest(frames.tobytes()),
            "background_sha256": audit.digest(background.tobytes()),
            "labels": labels,
        },
    )


def validate_group(group, identity, checkpoint_sha256, expected):
    from .shuttle_selection import feature_rows
    from .shuttle_selection_synthetic import FRAMES

    if (
        group.get("identity") != identity
        or group.get("checkpoint_sha256") != checkpoint_sha256
        or group.get("experiment_sha256") != expected
        or len(group.get("rows", [])) != FRAMES
        or len(identity["labels"]) != FRAMES
    ):
        raise ValueError("Changed or incomplete generated group cache")
    rows = group["rows"]
    if [row["frame"] for row in rows] != list(range(FRAMES)) or any(
        not audit.finite(row.get("time_s"))
        or abs(row["time_s"] - row["frame"] / 30) > 1e-12
        for row in rows
    ):
        raise ValueError("Generated native frame/clock correspondence changed")
    feature_rows(rows)
    return {**identity, "rows": rows}


def infer_group(frames, background, predict):
    from .shuttle import infer_camera_segment

    source = [
        (
            frame,
            frame / 30,
            SimpleNamespace(to_image=lambda pixels=pixels: Image.fromarray(pixels)),
        )
        for frame, pixels in enumerate(frames)
    ]
    return list(infer_camera_segment(source, background, 8, predict, 512, 288))


def generated_inference(root, output, expected, paths, splits, progress, *, resume):
    import torch

    from . import shuttle_capacity as capacity
    from .shuttle_selection_synthetic import SPLITS

    results, identities = {}, {}
    total = len(VARIANTS) * sum(SPLITS[s] for s in splits)
    completed = 0
    for variant in VARIANTS:
        checksum = audit.file_hash(paths[variant])
        model = capacity.model_from(paths[variant], "cuda:0")
        predict, calls = capacity.predict_function(model)
        variant_results = {}
        try:
            for split in splits:
                groups = []
                for index in range(SPLITS[split]):
                    progress(completed / total)
                    frames, background, identity = generated_group(split, index)
                    key = (split, index)
                    if key in identities and identities[key] != identity:
                        raise ValueError(
                            "Generated inputs changed between fixed methods"
                        )
                    identities[key] = identity
                    path = output / "groups" / variant / split / f"{index:03d}.json"
                    seal_path = path.with_suffix(".seal.json")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if path.exists():
                        if not resume:
                            raise ValueError("One-shot test output already exists")
                        if not seal_path.is_file():
                            raise ValueError("Generated cache lacks a completion seal")
                        seal = audit.read_json(seal_path.read_bytes())
                        if (
                            seal.get("experiment_sha256") != expected
                            or audit.sealed_path(output, seal["group"]) != path
                        ):
                            raise ValueError("Changed generated cache completion seal")
                        group = audit.read_json(path.read_bytes())
                    else:
                        if seal_path.exists():
                            raise ValueError("Generated completion seal has no group")
                        group = {
                            "identity": identity,
                            "rows": infer_group(frames, background, predict),
                            "checkpoint_sha256": checksum,
                            "experiment_sha256": expected,
                        }
                        validate_group(group, identity, checksum, expected)
                        publish(path, group)
                        publish(
                            seal_path,
                            {
                                "experiment_sha256": expected,
                                "group": audit.seal(output, path),
                            },
                        )
                    groups.append(validate_group(group, identity, checksum, expected))
                    completed += 1
                    progress(completed / total)
                variant_results[split] = groups
        finally:
            predict = None
            model = None
            torch.cuda.empty_cache()
        if audit.file_hash(paths[variant]) != checksum:
            raise ValueError("Neural checkpoint changed during inference")
        results[variant] = {"groups": variant_results, "new_model_calls": calls[0]}
    return results


def trainval(root, output, expected):
    if (output / "trainval.json").exists():
        raise ValueError("Complete train/validation inference must not be repeated")

    def task(_experiment, protocol, _attempt, progress):
        paths = checkpoint_paths(root, protocol)
        results = generated_inference(
            root,
            output,
            expected,
            paths,
            ("train", "validation"),
            progress,
            resume=True,
        )
        groups = {
            variant: {
                split: [
                    audit.seal(
                        output,
                        output / "groups" / variant / split / f"{g['index']:03d}.json",
                    )
                    for g in results[variant]["groups"][split]
                ]
                for split in ("train", "validation")
            }
            for variant in VARIANTS
        }
        record = {"experiment_sha256": expected, "groups": groups}
        publish(output / "trainval.json", record)
        return {
            "trainval_sha256": audit.file_hash(output / "trainval.json"),
            "new_model_calls": {v: results[v]["new_model_calls"] for v in VARIANTS},
        }

    return admission(root, output, expected, "trainval", task, gpu=True)


def load_trainval(output, expected, protocol):
    from .shuttle_selection_synthetic import SPLITS, group_seed

    record = audit.read_json((output / "trainval.json").read_bytes())
    if record.get("experiment_sha256") != expected or set(
        record.get("groups", {})
    ) != set(VARIANTS):
        raise ValueError("Changed train/validation stage binding")
    result = {}
    for variant in VARIANTS:
        if set(record["groups"][variant]) != {"train", "validation"}:
            raise ValueError("Test or incomplete split present in training stage")
        result[variant] = {}
        key = "parent-checkpoint" if variant == "control" else variant + "-checkpoint"
        checksum = protocol["input_artifacts"][key]["sha256"]
        for split in ("train", "validation"):
            refs = record["groups"][variant][split]
            if len(refs) != SPLITS[split]:
                raise ValueError("Training stage omitted complete source groups")
            groups = []
            for index, entry in enumerate(refs):
                group = audit.read_json(audit.sealed_bytes(output, entry))
                identity = group["identity"]
                if (identity["split"], identity["index"], identity["seed"]) != (
                    split,
                    index,
                    group_seed(split, index),
                ):
                    raise ValueError("Changed generated split membership")
                groups.append(validate_group(group, identity, checksum, expected))
            result[variant][split] = groups
    for split in ("train", "validation"):
        identities = [
            {k: v for k, v in g.items() if k != "rows"}
            for g in result["control"][split]
        ]
        if any(
            [
                {k: v for k, v in g.items() if k != "rows"}
                for g in result[variant][split]
            ]
            != identities
            for variant in VARIANTS[1:]
        ):
            raise ValueError("Training inputs differ between fixed neural methods")
    return result


def fit_all(root, output, expected):
    if (output / "fit-opened.json").exists() or (output / "fits.json").exists():
        raise ValueError("Fitted scorers cannot be silently retrained")

    def task(_experiment, protocol, _attempt, progress):
        from .shuttle_selection import choose_threshold, fit

        groups = load_trainval(output, expected, protocol)
        publish(output / "fit-opened.json", {"experiment_sha256": expected})
        fits = {}
        for index, variant in enumerate(VARIANTS):
            scorer = fit(groups[variant]["train"])
            chosen = choose_threshold(groups[variant]["validation"], scorer)
            fits[variant] = {"scorer": scorer, "validation": chosen}
            progress((index + 1) / len(VARIANTS))
        record = {
            "experiment_sha256": expected,
            "trainval_sha256": audit.file_hash(output / "trainval.json"),
            "variants": fits,
            "test_generated": False,
        }
        publish(output / "fits.json", record)
        return {
            "fits_sha256": audit.file_hash(output / "fits.json"),
            "variants": {v: fits[v]["validation"]["available"] for v in VARIANTS},
        }

    return admission(root, output, expected, "fit", task)


def sealed_fits(output, expected, public_seal_sha256):
    path = output / "fit-public-seal.json"
    if audit.file_hash(path) != public_seal_sha256:
        raise ValueError("Changed externally timestamped fit seal")
    public = audit.read_json(path.read_bytes())
    if (
        not public.get("comment", "").startswith(
            "https://github.com/Ken0u/badminton-match-analyzer/issues/330#issuecomment-"
        )
        or public.get("experiment_sha256") != expected
        or public.get("fits_sha256") != audit.file_hash(output / "fits.json")
    ):
        raise ValueError(
            "All fitted scorers and thresholds require a bound public seal"
        )
    fits = audit.read_json((output / "fits.json").read_bytes())
    if (
        fits.get("experiment_sha256") != expected
        or fits.get("test_generated") is not False
        or set(fits.get("variants", {})) != set(VARIANTS)
        or fits.get("trainval_sha256") != audit.file_hash(output / "trainval.json")
    ):
        raise ValueError("Missing or changed fitted method/threshold lineage")
    for value in fits["variants"].values():
        chosen = value["validation"]
        if type(chosen.get("available")) is not bool or (
            chosen["available"]
            and chosen.get("threshold") not in [i / 10 for i in range(1, 10)]
        ):
            raise ValueError("Invalid validation-selected threshold")
    return fits, public


def select_fitted(rows, fitted, width=512, height=288, segments=None):
    """An unavailable fit or validation choice remains an unavailable method."""
    from .shuttle_selection import select

    scorer = fitted["scorer"]
    chosen = fitted["validation"]
    if not chosen["available"]:
        scorer = {**scorer, "available": False, "reason": chosen["reason"]}
    return select(
        rows,
        scorer,
        chosen["threshold"] if chosen["available"] else 0.5,
        width,
        height,
        segments,
    )


def selected_groups(groups, fitted):
    return [
        {
            **group,
            "rows": select_fitted(
                group["rows"], fitted, segments=group.get("segments")
            ),
        }
        for group in groups
    ]


def paired_generated(baseline, selected):
    """Pair complete generated frame membership, including unavailable outputs."""
    left, right = baseline["outcomes"], selected["outcomes"]
    if [(r["group"], r["frame"], r["state"]) for r in left] != [
        (r["group"], r["frame"], r["state"]) for r in right
    ]:
        raise ValueError("Paired generated test membership changed")
    return {
        kind: dict(
            sorted(
                Counter(a[kind] + "->" + b[kind] for a, b in zip(left, right)).items()
            )
        )
        for kind in ("visibility", "localization")
    }


def completed_stage(output, expected, stage, path, result_key):
    """Only a terminal admitted stage can authorize a dependent scientific stage."""
    checksum = audit.file_hash(path)
    for folder in (output / "attempts").glob("*"):
        admission_path, terminal_path = (
            folder / "admission.json",
            folder / "terminal.json",
        )
        if not admission_path.is_file() or not terminal_path.is_file():
            continue
        admitted = audit.read_json(admission_path.read_bytes())
        terminal = audit.read_json(terminal_path.read_bytes())
        if (
            admitted.get("experiment_sha256") == expected
            and admitted.get("stage") == stage
            and terminal.get("status") == "completed"
            and terminal.get("result", {}).get(result_key) == checksum
        ):
            return checksum
    raise ValueError("Required admitted stage is incomplete or its result changed")


def test(root, output, expected, public_seal_sha256):
    if (output / "test-opened.json").exists() or (output / "test.json").exists():
        raise ValueError(
            "Generated test already opened; preserve any incomplete result"
        )
    fits, public = sealed_fits(output, expected, public_seal_sha256)

    def task(_experiment, protocol, _attempt, progress):
        from .shuttle_selection import metrics

        current, _ = sealed_fits(output, expected, public_seal_sha256)
        if current != fits:
            raise ValueError("Fitted methods changed before test opening")
        paths = checkpoint_paths(root, protocol)
        publish(
            output / "test-opened.json",
            {
                "experiment_sha256": expected,
                "public_seal_sha256": public_seal_sha256,
                "fits_sha256": public["fits_sha256"],
            },
        )
        raw = generated_inference(
            root, output, expected, paths, ("test",), progress, resume=False
        )
        results = {}
        for variant in VARIANTS:
            groups = raw[variant]["groups"]["test"]
            selected = selected_groups(groups, fits["variants"][variant])
            results[variant] = {
                "baseline": metrics(groups),
                "selected": metrics(selected),
                "new_model_calls": raw[variant]["new_model_calls"],
                "groups": [
                    audit.seal(
                        output,
                        output / "groups" / variant / "test" / f"{g['index']:03d}.json",
                    )
                    for g in groups
                ],
            }
            results[variant]["paired_transitions"] = paired_generated(
                results[variant]["baseline"], results[variant]["selected"]
            )
            for name in ("baseline", "selected"):
                value = results[variant][name]
                value["component_oracle_recall"] = (
                    value["component_agrees"] / value["visible"]
                    if value["visible"]
                    else None
                )
            publish(
                output / f"test-selected-{variant}.json",
                {"experiment_sha256": expected, "groups": selected},
            )
        if sealed_fits(output, expected, public_seal_sha256)[0] != fits:
            raise ValueError("Fitted methods changed during test")
        publish(
            output / "test.json",
            {
                "experiment_sha256": expected,
                "public_seal_sha256": public_seal_sha256,
                "fits_sha256": public["fits_sha256"],
                "variants": results,
            },
        )
        return {
            "test_sha256": audit.file_hash(output / "test.json"),
            "variants": {
                v: {k: results[v][k] for k in ("baseline", "selected")}
                for v in VARIANTS
            },
        }

    return admission(root, output, expected, "test", task, gpu=True)


def eligible_segments(run, annotations):
    """Partition known source context; malformed or missing context is unavailable."""
    first, last = run["start_frame"], run["end_frame"]
    cameras = run.get("camera_ranges")
    scenes = annotations.get("scene_ranges") if isinstance(annotations, dict) else None
    if not isinstance(cameras, list) or not isinstance(scenes, list):
        return []
    cuts = run.get("cut_frames", [])
    if not isinstance(cuts, list) or any(
        type(c) is not int or not first <= c < last for c in cuts
    ):
        return []
    bounds = {first, last, *cuts}
    for entry in [*cameras, *scenes]:
        if not isinstance(entry, dict):
            return []
        a, b = entry.get("start_frame"), entry.get("end_frame")
        if type(a) is not int or type(b) is not int or not a < b:
            return []
        bounds.update((max(first, min(last, a)), max(first, min(last, b))))
    if any(
        entry.get("scene") not in {"live", "replay", "non_play", "unknown"}
        for entry in scenes
    ):
        return []

    from .scene_review import excluded_scene

    result = []
    ordered = sorted(bounds)
    for start, end in itertools.pairwise(ordered):
        covered = (
            sum(c["start_frame"] <= start and end <= c["end_frame"] for c in cameras)
            == 1
        )
        live = (
            sum(
                s["start_frame"] <= start
                and end <= s["end_frame"]
                and s["scene"] == "live"
                for s in scenes
            )
            == 1
        )
        result.append(
            {
                "start_frame": start,
                "end_frame": end,
                "eligible": covered
                and live
                and not bool(excluded_scene(annotations, start, end)),
            }
        )
    return result


def validate_baseline(original, protocol, variant):
    """Require the complete unchanged-denominator predecessor reproduction."""
    metrics = original["all"]["metrics"]
    expected_states = {
        **dict.fromkeys(audit.PROTOCOL["states"], 0),
        **protocol["familiar"]["truth_states"],
    }
    if (
        metrics["cases"] != protocol["familiar"]["cases"]
        or metrics["truth_states"] != expected_states
    ):
        raise ValueError("Original familiar baseline denominator did not reproduce")
    for name in ("visibility", "localization"):
        counts = {key: metrics[name][key] for key in ("tp", "fp", "fn", "tn")}
        if counts != protocol["familiar"]["baseline_" + name + "_counts"][variant]:
            raise ValueError("Original familiar baseline did not reproduce")
    if (
        original["all"]["components"]["component_present"]
        != protocol["familiar"]["baseline_agreeing_components"][variant]
    ):
        raise ValueError("Original familiar component oracle did not reproduce")


def validate_source_views(root, packet, views):
    """Recheck original display geometry and PTS without opening source video."""
    source_ids = {s["id"]: s for s in audit.PROTOCOL["sources"]}
    if set(packet["source_inputs"]) != set(source_ids):
        raise ValueError("Original familiar source membership changed")
    for video_id, entries in packet["source_inputs"].items():
        meta = audit.read_json(audit.sealed_bytes(root, entries["metadata"]))
        times = audit.read_json(audit.sealed_bytes(root, entries["timestamps"]))
        if (
            meta.get("id") != video_id
            or meta.get("sha256") != source_ids[video_id]["sha256"]
            or len(times) != source_ids[video_id]["frame_count"]
        ):
            raise ValueError("Original familiar source/clock identity changed")
        for case in packet["cases"]:
            if case["video_id"] == video_id and (
                case["width"],
                case["height"],
                case["rotation"],
            ) != (meta["width"], meta["height"], meta.get("rotation", 0)):
                raise ValueError("Original familiar display geometry changed")
        for method in VARIANTS:
            for view, run in views[method].values():
                if view["video_id"] != video_id:
                    continue
                if (
                    run.get("video_sha256") != meta["sha256"]
                    or run.get("stage") != "shuttle"
                ):
                    raise ValueError("Cached familiar source identity changed")
                audit.native_rows(run, meta, times, view)


def cached_views(root, protocol):
    """Validate sealed predecessor references without invoking expired study code."""
    inputs = protocol["input_artifacts"]
    raw = audit.read_json(audit.sealed_bytes(root, inputs["capacity-raw-index"]))
    old = audit.read_json(
        audit.sealed_bytes(root, inputs["capacity-continuation-experiment"])
    )
    if raw.get("experiment_sha256") != inputs["capacity-continuation-experiment"][
        "sha256"
    ] or set(raw.get("references", {})) != set(VARIANTS):
        raise ValueError("Cached raw index differs from the completed predecessor")
    raw_root = audit.inside(root, protocol["familiar"]["raw_output_root"])
    for entry in raw["files"].values():
        audit.sealed_path(raw_root, entry)
    views = old["views"]
    expected_views = {v["id"]: v for v in views}
    if len(expected_views) != protocol["familiar"]["views_per_method"]:
        raise ValueError("Incomplete original familiar view inventory")
    results = {}
    for variant in VARIANTS:
        results[variant] = {}
        for ref in raw["references"][variant]:
            receipt_path = audit.sealed_path(root, ref["receipt"])
            receipt = audit.read_json(receipt_path.read_bytes())
            view = receipt["view"]
            if view["id"] in results[variant] or expected_views.get(view["id"]) != view:
                raise ValueError("Changed or duplicate familiar view")
            origin = ref["origin"]
            if origin not in ("predecessor", "continuation") or (
                origin == "predecessor" and variant != "control"
            ):
                raise ValueError("Invalid inherited observation origin")
            source_key = (
                "capacity-experiment"
                if origin == "predecessor"
                else "capacity-continuation-experiment"
            )
            if receipt.get("experiment_sha256") != inputs[source_key]["sha256"]:
                raise ValueError("Changed inherited original experiment binding")
            source_root = audit.inside(root, inputs[source_key]["path"]).parent
            run_path = audit.sealed_path(root, ref["run"])
            if run_path != audit.sealed_path(source_root, receipt["run"]):
                raise ValueError("Raw-index run differs from original receipt")
            run = audit.read_json(run_path.read_bytes())
            key = (
                "parent-checkpoint" if variant == "control" else variant + "-checkpoint"
            )
            if (
                run.get("checkpoint_sha256") != inputs[key]["sha256"]
                or run.get("video_id") != view["video_id"]
                or run.get("input_size") != [512, 288]
                or run.get("seq_len") != 8
                or run.get("temporal_context_crosses_detected_cuts") is not False
                or run.get("start_frame") != view["start_frame"]
                or run.get("end_frame") != view["end_frame"]
                or run.get("processed_frames")
                != view["end_frame"] - view["start_frame"]
                or [v["frame"] for v in run["frames"]]
                != list(range(view["start_frame"], view["end_frame"]))
            ):
                raise ValueError("Cached source/clock/model view identity changed")
            if any(not audit.finite(row.get("time_s")) for row in run["frames"]) or any(
                b["time_s"] <= a["time_s"]
                for a, b in zip(run["frames"], run["frames"][1:])
            ):
                raise ValueError("Invalid cached native clock")
            results[variant][view["id"]] = (view, run)
        if (
            set(results[variant]) != set(expected_views)
            or sum(run["processed_frames"] for _, run in results[variant].values())
            != protocol["familiar"]["rows_per_method"]
        ):
            raise ValueError("Incomplete familiar rows or original view denominator")
    return results


def familiar(root, output, expected, public_seal_sha256):
    if (output / "familiar-opened.json").exists() or (
        output / "familiar.json"
    ).exists():
        raise ValueError("Familiar diagnostic cannot be silently repeated")
    fits, public = sealed_fits(output, expected, public_seal_sha256)
    completed_stage(output, expected, "test", output / "test.json", "test_sha256")
    generated = audit.read_json((output / "test.json").read_bytes())
    if (
        generated.get("experiment_sha256") != expected
        or generated.get("fits_sha256") != public["fits_sha256"]
        or set(generated.get("variants", {})) != set(VARIANTS)
    ):
        raise ValueError(
            "Complete fixed generated test is required before familiar reads"
        )

    def task(_experiment, protocol, _attempt, progress):
        inputs = protocol["input_artifacts"]
        views = cached_views(root, protocol)
        packet = audit.read_json(
            audit.sealed_bytes(root, inputs["familiar-source-packet"])
        )
        labels = audit.read_json(
            audit.sealed_bytes(root, inputs["familiar-source-labels"])
        )
        baseline = audit.read_json(
            audit.sealed_bytes(root, inputs["familiar-source-baseline"])
        )
        packet_root = audit.sealed_path(root, inputs["familiar-source-packet"]).parent
        validate_source_views(packet_root, packet, views)
        cases = packet["cases"]
        if (
            len(cases) != protocol["familiar"]["cases"]
            or dict(Counter(c["label"]["state"] for c in labels["cases"]))
            != protocol["familiar"]["truth_states"]
        ):
            raise ValueError("Familiar cases, unknowns or negative denominator changed")
        publish(
            output / "familiar-opened.json",
            {
                "experiment_sha256": expected,
                "fits_sha256": public["fits_sha256"],
                "test_sha256": audit.file_hash(output / "test.json"),
            },
        )
        results = {}
        for index, variant in enumerate(VARIANTS):
            observations, selected_observations = {}, {}
            selected_views = []
            for view, run in views[variant].values():
                members = [c for c in cases if c["id"] in view["case_ids"]]
                if (
                    not members
                    or len({(c["width"], c["height"]) for c in members}) != 1
                ):
                    raise ValueError("Missing or inconsistent native display geometry")
                width, height = members[0]["width"], members[0]["height"]
                annotations = baseline["evidence"]["catalogs"][view["video_id"]][
                    "snapshot"
                ]["annotations"]
                rows = select_fitted(
                    run["frames"],
                    fits["variants"][variant],
                    width,
                    height,
                    segments=eligible_segments(run, annotations),
                )
                selected_views.append({"view": view, "rows": rows})
                for case in members:
                    offset = case["frame"] - view["start_frame"]
                    if case["id"] in observations or not 0 <= offset < len(rows):
                        raise ValueError("Duplicate or out-of-view familiar case")
                    observations[case["id"]] = {
                        "available": True,
                        "point": run["frames"][offset]["shuttle"],
                        "reason": None,
                    }
                    row = rows[offset]
                    selected_observations[case["id"]] = {
                        "available": row["selection_available"],
                        "point": row["shuttle"],
                        "reason": row["selection_unavailable_reason"],
                    }
            original = existing.grouped_scores(cases, labels["cases"], observations)
            validate_baseline(original, protocol, variant)
            learned = existing.grouped_scores(
                cases, labels["cases"], selected_observations
            )
            pairs = Counter(
                (a["outcome"], b["outcome"])
                for a, b in zip(
                    original["all"]["metrics"]["frames"],
                    learned["all"]["metrics"]["frames"],
                )
            )
            results[variant] = {
                "baseline": original,
                "selected": learned,
                "paired_transitions": {
                    a + " -> " + b: n for (a, b), n in sorted(pairs.items())
                },
                "views": len(views[variant]),
                "native_rows": sum(
                    run["processed_frames"] for _, run in views[variant].values()
                ),
            }
            publish(
                output / f"familiar-selected-{variant}.json",
                {"experiment_sha256": expected, "views": selected_views},
            )
            progress((index + 1) / len(VARIANTS))
        if sealed_fits(output, expected, public_seal_sha256)[0] != fits:
            raise ValueError("Fitted methods changed during familiar diagnostics")
        publish(
            output / "familiar.json",
            {
                "experiment_sha256": expected,
                "fits_sha256": public["fits_sha256"],
                "variants": results,
                "complete_references": "0/2",
                "promoted": False,
                "new_native_inference": False,
                "eligibility_changed": False,
                "eligibility": dict.fromkeys(
                    (
                        "training_allowed",
                        "independent_test_allowed",
                        "model_deployment_allowed",
                        "dataset_redistribution_allowed",
                    ),
                    False,
                ),
                "limitations": protocol["limitations"],
            },
        )
        return {
            "familiar_sha256": audit.file_hash(output / "familiar.json"),
            "cases": len(cases),
            "unknown": protocol["familiar"]["truth_states"]["unknown"],
        }

    return admission(root, output, expected, "familiar", task)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=("freeze", "trainval", "fit", "test", "familiar")
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--protocol-sha256")
    parser.add_argument("--experiment-sha256")
    parser.add_argument("--public-seal-sha256")
    parser.add_argument("--granted-at", type=float)
    parser.add_argument("--deadline", type=float)
    args = parser.parse_args(argv)
    if args.stage == "freeze":
        result = freeze(
            args.root,
            args.protocol,
            args.protocol_sha256,
            args.output,
            args.granted_at,
            args.deadline,
        )
    else:
        function = {
            "trainval": trainval,
            "fit": fit_all,
            "test": test,
            "familiar": familiar,
        }[args.stage]
        extra = (args.public_seal_sha256,) if args.stage in ("test", "familiar") else ()
        result = function(args.root, args.output, args.experiment_sha256, *extra)
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
