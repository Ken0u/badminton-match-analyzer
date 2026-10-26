"""Fixed two-capacity synthetic-only research. This module never installs model weights."""

import argparse
import hashlib
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import psutil
from PIL import Image

from . import shuttle_resolution as existing
from . import shuttle_validation as audit
from .shuttle_capacity_synthetic import (
    FRAMES,
    PARENT_SHA256,
    PROTOCOL,
    SPLITS,
    generate_group,
    group_seed,
    heatmaps,
)

publish = existing.publish


def validate_protocol(value):
    if audit.encoded(value) != audit.encoded(PROTOCOL):
        raise ValueError(
            "Synthetic adaptation protocol differs from the sole frozen recipe"
        )


def consumers(root):
    result = existing.consumer_files(root)
    package = Path(__file__).resolve().parent
    runner = package.parents[1] / "scripts/compare_shuttle_capacity.py"
    result["scripts/compare_shuttle_capacity.py"] = audit.seal(root, runner)
    return result


def freeze(root, protocol_path, protocol_sha256, output, deadline):
    root, output = root.resolve(), output.resolve()
    raw = protocol_path.read_bytes()
    if audit.digest(raw) != protocol_sha256:
        raise ValueError("Changed public protocol bytes")
    protocol = audit.read_json(raw)
    validate_protocol(protocol)
    from .shuttle_synthetic import group_seed as historical_seed

    fresh = {group_seed(s, i) for s, count in SPLITS.items() for i in range(count)}
    historical = {
        historical_seed(s, i) for s, count in SPLITS.items() for i in range(count)
    }
    if len(fresh) != 160 or fresh & historical:
        raise ValueError("Fresh complete source-group separation failed")
    if (
        not audit.finite(deadline)
        or not time.time() < deadline <= time.time() + 4 * 3600
    ):
        raise ValueError("Original grant's bounded deadline required")
    inputs = existing.verify_inputs(
        root,
        root / ".cache/shuttle139-packet-v1",
        root / ".cache/shuttle139-labels-v1",
        root / ".cache/shuttle139-baseline-v2/baseline.json",
        protocol,
    )
    packet, _, _, baseline, runs, _ = inputs
    views = existing.plan_views(packet["cases"], baseline["evidence"], runs)
    if (
        len(views) != 50
        or sum(v["end_frame"] - v["start_frame"] for v in views) != 13499
    ):
        raise ValueError("Changed familiar development view membership")
    if audit.file_hash(root / "models/weights/TrackNet_best.pt") != PARENT_SHA256:
        raise ValueError("Changed original checkpoint")
    output = audit.ignored_output(root, output)
    code = consumers(root)
    for name, seal in code.items():
        path = output / "consumer" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(audit.sealed_bytes(root, seal))
    with (output / "protocol.json").open("xb") as stream:
        stream.write(raw)
    experiment = {
        "protocol_sha256": protocol_sha256,
        "consumer_files": code,
        "runtime": existing.runtime_snapshot(),
        "views": views,
        "shared_data": "data/processed",
        "deadline": deadline,
        "split_seeds": {
            split: [group_seed(split, index) for index in range(count)]
            for split, count in SPLITS.items()
        },
    }
    publish(output / "experiment.json", experiment)
    return {"experiment_sha256": audit.file_hash(output / "experiment.json")}


def load(root, output, expected):
    root, output = root.resolve(), output.resolve()
    if not output.is_relative_to(root / ".cache"):
        raise ValueError("Research output must stay inside original ignored cache")
    if audit.file_hash(output / "experiment.json") != expected:
        raise ValueError("Changed frozen experiment")
    value = audit.read_json((output / "experiment.json").read_bytes())
    if not audit.finite(value.get("deadline")) or time.time() >= value["deadline"]:
        raise ValueError("Original research runtime allowance expired")
    raw = (output / "protocol.json").read_bytes()
    if audit.digest(raw) != value["protocol_sha256"]:
        raise ValueError("Changed frozen protocol")
    validate_protocol(audit.read_json(raw))
    if (
        consumers(root) != value["consumer_files"]
        or existing.runtime_snapshot() != value["runtime"]
    ):
        raise ValueError("Research executable bytes or runtime changed")
    for name, seal in value["consumer_files"].items():
        if audit.file_hash(output / "consumer" / name) != seal["sha256"]:
            raise ValueError("Changed frozen consumer copy")
    if audit.file_hash(root / "models/weights/TrackNet_best.pt") != PARENT_SHA256:
        raise ValueError("Original checkpoint changed")
    return value


def balanced_loss(prediction, target):
    """Equal support/background spatial terms, including fully negative frames."""
    import torch

    if prediction.shape != target.shape or prediction.ndim != 4:
        raise ValueError("Matching B,L,H,W targets required")
    if not torch.isfinite(prediction).all() or not torch.isfinite(target).all():
        raise ValueError("Finite predictions and targets required")
    support = target > 0
    errors = (prediction.float() - target.float()).square()
    positive = (errors * support).sum((-2, -1)) / support.sum((-2, -1)).clamp(min=1)
    negative = (errors * ~support).sum((-2, -1)) / (~support).sum((-2, -1)).clamp(min=1)
    return (0.5 * positive + 0.5 * negative).mean()


VARIANTS = ("decoder", "convolution")
STUDY = "procedural-shuttle-capacity-v1"


def trainable_names(variant):
    if variant not in VARIANTS:
        raise ValueError("Unknown frozen capacity variant")
    blocks = {
        "down_block_1": 2,
        "down_block_2": 2,
        "down_block_3": 3,
        "bottleneck": 3,
        "up_block_1": 3,
        "up_block_2": 2,
        "up_block_3": 2,
    }
    return [
        f"{block}.conv_{index}.conv.weight"
        for block, count in blocks.items()
        if variant == "convolution" or block == "up_block_3"
        for index in range(1, count + 1)
    ] + ["predictor.weight", "predictor.bias"]


def configure_training(model, variant):
    selected = trainable_names(variant)
    model.eval()
    found = []
    for name, parameter in model.named_parameters():
        parameter.requires_grad_(name in selected)
        if parameter.requires_grad:
            found.append(name)
    if found != selected:
        raise ValueError("Model differs from frozen capacity tensors")
    return found


def tensor_hashes(model, names=None):
    return {
        name: hashlib.sha256(
            tensor.detach().cpu().contiguous().numpy().tobytes()
        ).hexdigest()
        for name, tensor in model.state_dict().items()
        if names is None or name in names
    }


def choose_epoch(rows):
    if not rows or any(
        type(row.get("epoch")) is not int
        or row["epoch"] != index + 1
        or not audit.finite(row.get("validation_loss"))
        for index, row in enumerate(rows)
    ):
        raise ValueError("Ordered finite validation records required")
    return min(rows, key=lambda row: (row["validation_loss"], row["epoch"]))


def tensor(images, device):
    import torch

    array = np.concatenate(
        [np.moveaxis(image, -1, 0) for image in images], axis=0
    ).copy()
    return (
        torch.from_numpy(array).unsqueeze(0).to(device=device, dtype=torch.float32)
        / 255
    )


def model_from(path, device):
    import torch

    from .vendor.tracknet_model import TrackNet

    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    params = checkpoint["param_dict"]
    if params["seq_len"] != 8 or params["bg_mode"] != "concat":
        raise ValueError("Expected length8 background-concat parent")
    model = TrackNet(27, 8)
    model.load_state_dict(checkpoint["model"], strict=True)
    return model.to(device).eval()


def checkpoint_override(value):
    """Bind method, experiment, training and selected bytes before media access."""
    keys = {"study", "variant", "output", "selection_sha256"}
    if not isinstance(value, dict) or set(value) != keys or value["study"] != STUDY:
        raise ValueError("Research capacity checkpoint requires exact study seal")
    variant = value["variant"]
    names = trainable_names(variant)
    output = Path(value["output"]).resolve()
    method = output / variant
    path = method / "selection.json"
    if audit.file_hash(path) != value["selection_sha256"]:
        raise ValueError("Research selection checksum changed")
    selection = audit.read_json(path.read_bytes())
    training = audit.read_json(audit.sealed_bytes(method, selection["training"]))
    raw = (output / "protocol.json").read_bytes()
    validate_protocol(audit.read_json(raw))
    experiment_sha = audit.file_hash(output / "experiment.json")
    experiment = audit.read_json((output / "experiment.json").read_bytes())
    if experiment.get("protocol_sha256") != audit.digest(raw):
        raise ValueError("Changed experiment protocol binding")
    for receipt in (selection, training):
        if (
            receipt.get("study") != STUDY
            or receipt.get("variant") != variant
            or receipt.get("parent_sha256") != PARENT_SHA256
            or receipt.get("protocol_sha256") != audit.digest(raw)
            or receipt.get("experiment_sha256") != experiment_sha
        ):
            raise ValueError("Research capacity method/parent/protocol binding changed")
    epochs = training.get("epochs", [])
    if (
        len(epochs) != 4
        or training.get("frozen_unchanged") is not True
        or training.get("trainable_names") != names
        or training.get("selection_input") != "synthetic validation only"
        or set(training.get("train_groups", {})) != {str(i) for i in range(128)}
        or any(
            set(row.get("validation_groups", {})) != {str(i) for i in range(16)}
            for row in epochs
        )
    ):
        raise ValueError("Research capacity training provenance changed")
    best = choose_epoch(epochs)
    if best["epoch"] != selection.get("epoch") or best["checkpoint"] != selection.get(
        "checkpoint"
    ):
        raise ValueError("Research checkpoint is not the frozen validation selection")
    checkpoint = audit.sealed_path(method, selection["checkpoint"])
    return (
        checkpoint,
        selection["checkpoint"]["sha256"],
        {
            "study": STUDY,
            "variant": variant,
            "selection_sha256": value["selection_sha256"],
            "training_sha256": selection["training"]["sha256"],
            "protocol_sha256": audit.digest(raw),
            "parent_sha256": PARENT_SHA256,
            "experiment_sha256": experiment_sha,
            "epoch": best["epoch"],
        },
    )


def selected(output, variant):
    value = {
        "study": STUDY,
        "variant": variant,
        "output": str(output),
        "selection_sha256": audit.file_hash(output / variant / "selection.json"),
    }
    checkpoint_override(value)
    return value


def both_selected(output):
    return {variant: selected(output, variant) for variant in VARIANTS}


def admission(root, output, experiment_sha256, stage, function):
    """One genuine shared-Store job, with independent prior lifetime evidence."""
    import sys

    from . import config
    from .jobs import run_local_job
    from .storage import Store

    experiment = load(root, output, experiment_sha256)
    shared = root.resolve() / "data/processed"
    if (
        config.ROOT != root.resolve()
        or config.DATA.resolve() != shared
        or config.WEIGHTS.resolve() != root.resolve() / "models/weights"
    ):
        raise ValueError(
            "Pin real original root, shared Store and weights before imports"
        )
    if not (shared / "catalog.sqlite3").is_file():
        raise ValueError("Original shared Store is missing")
    prior = existing.prior_attempt_proof(output, shared)
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
                "experiment_sha256": experiment_sha256,
                "process": {
                    "pid": process.pid,
                    "creation_time": process.create_time(),
                    "cwd": process.cwd(),
                    "command": list(sys.argv),
                },
            },
        )
        if not torch.cuda.is_available():
            raise ValueError("Frozen research requires actual CUDA host")
        torch.cuda.reset_peak_memory_stats()
        device = {
            "name": torch.cuda.get_device_name(0),
            "memory_bytes": torch.cuda.get_device_properties(0).total_memory,
            "torch_cuda": torch.version.cuda,
        }
        publish(attempt / "device.json", device)

        def bounded_progress(value):
            if time.time() >= experiment["deadline"]:
                raise ValueError(
                    "Original research deadline reached; preserve artifacts"
                )
            progress(value)

        result = function(experiment, attempt, bounded_progress)
        load(root, output, experiment_sha256)
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


def train(root, output, experiment_sha256, variant):
    trainable_names(variant)
    if (output / "synthetic-test-opened.json").exists():
        raise ValueError("Test is already opened; training is sealed")
    method_output = output / variant
    method_output.mkdir(exist_ok=True)
    if (method_output / "training-opened.json").exists() or any(
        method_output.glob("epoch-*.pt")
    ):
        raise ValueError(
            "Training outputs exist; preserve prior attempt, no silent rerun"
        )

    def task(experiment, attempt, progress):
        import torch

        publish(
            method_output / "training-opened.json",
            {
                "experiment_sha256": experiment_sha256,
                "attempt": attempt.relative_to(output).as_posix(),
            },
        )
        torch.manual_seed(20261025)
        torch.cuda.manual_seed_all(20261025)
        model = model_from(root / "models/weights/TrackNet_best.pt", "cuda:0")
        names = configure_training(model, variant)
        before = tensor_hashes(model)
        frozen = {name: value for name, value in before.items() if name not in names}
        optimizer = torch.optim.AdamW(
            [p for p in model.parameters() if p.requires_grad],
            lr=0.0001,
            weight_decay=0.0001,
        )
        scaler = torch.amp.GradScaler("cuda")
        rng = np.random.default_rng(20261025)
        epochs, generated = [], {}
        for epoch in range(4):
            losses = []
            for step, index in enumerate(rng.permutation(128)):
                index = int(index)
                frames, background, labels = generate_group("train", index)
                digest = audit.digest(
                    frames.tobytes() + background.tobytes() + audit.encoded(labels)
                )
                if str(index) in generated and generated[str(index)] != digest:
                    raise ValueError("Generated train group changed between epochs")
                generated[str(index)] = digest
                first = 8 * ((epoch + index) % 3)
                target = (
                    torch.from_numpy(heatmaps(labels[first : first + 8]))
                    .unsqueeze(0)
                    .to("cuda:0")
                )
                optimizer.zero_grad(set_to_none=True)
                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    prediction = model(
                        tensor([background, *frames[first : first + 8]], "cuda:0")
                    )
                loss = balanced_loss(prediction, target)
                if not torch.isfinite(loss):
                    raise ValueError("Nonfinite training loss")
                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
                if any(
                    p.grad is not None and not torch.isfinite(p.grad).all()
                    for p in model.parameters()
                ):
                    raise ValueError("Nonfinite training gradients")
                torch.nn.utils.clip_grad_norm_(
                    [p for p in model.parameters() if p.requires_grad],
                    1.0,
                    error_if_nonfinite=True,
                )
                scaler.step(optimizer)
                scaler.update()
                losses.append(float(loss.detach()))
                progress((epoch + (step + 1) / 128) / 4)
            validation, validation_groups = [], {}
            with torch.inference_mode():
                for index in range(16):
                    frames, background, labels = generate_group("validation", index)
                    validation_groups[str(index)] = audit.digest(
                        frames.tobytes() + background.tobytes() + audit.encoded(labels)
                    )
                    for first in (0, 8, 16):
                        target = (
                            torch.from_numpy(heatmaps(labels[first : first + 8]))
                            .unsqueeze(0)
                            .to("cuda:0")
                        )
                        with torch.autocast(device_type="cuda", dtype=torch.float16):
                            prediction = model(
                                tensor(
                                    [background, *frames[first : first + 8]], "cuda:0"
                                )
                            )
                        validation.append(float(balanced_loss(prediction, target)))
            current = tensor_hashes(model)
            if any(current[name] != value for name, value in frozen.items()):
                raise ValueError("Frozen model/BN tensor changed")
            if not all(torch.isfinite(t).all() for t in model.state_dict().values()):
                raise ValueError("Nonfinite checkpoint tensor")
            path = method_output / f"epoch-{epoch + 1}.pt"
            with path.open("xb") as stream:
                torch.save(
                    {
                        "param_dict": {"seq_len": 8, "bg_mode": "concat"},
                        "model": {
                            k: v.detach().cpu() for k, v in model.state_dict().items()
                        },
                        "adaptation": {
                            "study": STUDY,
                            "variant": variant,
                            "parent_sha256": PARENT_SHA256,
                            "protocol_sha256": experiment["protocol_sha256"],
                            "epoch": epoch + 1,
                        },
                    },
                    stream,
                )
            row = {
                "epoch": epoch + 1,
                "training_loss": float(np.mean(losses)),
                "validation_loss": float(np.mean(validation)),
                "checkpoint": audit.seal(method_output, path),
                "validation_groups": validation_groups,
                "trainable_changed": [
                    name for name in names if current[name] != before[name]
                ],
            }
            publish(method_output / f"epoch-{epoch + 1}.json", row)
            epochs.append(row)
        training = {
            "study": STUDY,
            "variant": variant,
            "parent_sha256": PARENT_SHA256,
            "protocol_sha256": experiment["protocol_sha256"],
            "experiment_sha256": experiment_sha256,
            "epochs": epochs,
            "train_groups": generated,
            "frozen_unchanged": True,
            "frozen_tensor_hashes": frozen,
            "trainable_names": names,
            "selection_input": "synthetic validation only",
        }
        publish(method_output / "training.json", training)
        best = choose_epoch(epochs)
        publish(
            method_output / "selection.json",
            {
                "study": STUDY,
                "variant": variant,
                "parent_sha256": PARENT_SHA256,
                "protocol_sha256": experiment["protocol_sha256"],
                "experiment_sha256": experiment_sha256,
                "training": audit.seal(method_output, method_output / "training.json"),
                "epoch": best["epoch"],
                "checkpoint": best["checkpoint"],
            },
        )
        model = optimizer = None
        torch.cuda.empty_cache()
        return {
            "selected_epoch": best["epoch"],
            "selection_sha256": audit.file_hash(method_output / "selection.json"),
        }

    return admission(root, output, experiment_sha256, "train-" + variant, task)


def predict_function(model):
    import torch

    calls = [0]

    def predict(images):
        with (
            torch.inference_mode(),
            torch.autocast(device_type="cuda", dtype=torch.float16),
        ):
            result = model(tensor(images, "cuda:0"))[0].float().cpu().numpy()
        calls[0] += 1
        return result

    return predict, calls


def synthetic_metrics(groups):
    counts = dict.fromkeys(
        (
            "frames",
            "visible",
            "negative",
            "visibility_tp",
            "visibility_fp",
            "visibility_fn",
            "visibility_tn",
            "localization_tp",
            "localization_fp",
            "localization_fn",
            "localization_tn",
            "displaced",
            "component_agrees",
        ),
        0,
    )
    errors = []
    for group in groups:
        if len(group["labels"]) != FRAMES or len(group["rows"]) != FRAMES:
            raise ValueError("Complete generated source group required")
        for truth, row in zip(group["labels"], group["rows"]):
            if row["frame"] != truth["frame"]:
                raise ValueError("Generated frame correspondence changed")
            point = row["shuttle"]
            visible, observed = truth["visible"], point["visible"]
            counts["frames"] += 1
            counts["visible" if visible else "negative"] += 1
            counts[
                "visibility_" + ("tp" if observed else "fn")
                if visible
                else "visibility_" + ("fp" if observed else "tn")
            ] += 1
            if visible:
                tolerance = 0.005 * math.hypot(512, 288)
                agreeing = any(
                    math.hypot(p["x"] - truth["x"], p["y"] - truth["y"]) <= tolerance
                    for p in point["component_candidates"]
                )
                counts["component_agrees"] += agreeing
                if observed:
                    error = math.hypot(point["x"] - truth["x"], point["y"] - truth["y"])
                    errors.append(error)
                    if error <= tolerance:
                        counts["localization_tp"] += 1
                    else:
                        counts["displaced"] += 1
                        counts["localization_fp"] += 1
                        counts["localization_fn"] += 1
                else:
                    counts["localization_fn"] += 1
            else:
                counts["localization_fp" if observed else "localization_tn"] += 1
    counts["mean_error_predicted_visible_px"] = (
        float(np.mean(errors)) if errors else None
    )
    return counts


def synthetic_test(root, output, experiment_sha256):
    from .shuttle import infer_camera_segment

    overrides = both_selected(output)  # Must exist before any test group is generated.
    if (output / "synthetic-test-opened.json").exists():
        raise ValueError("Synthetic test was already opened; no silent repeat")

    def task(experiment, attempt, progress):
        import torch

        paths = {
            variant: checkpoint_override(value)[0]
            for variant, value in overrides.items()
        }
        selection_seals = {
            variant: value["selection_sha256"] for variant, value in overrides.items()
        }
        publish(
            output / "synthetic-test-opened.json",
            {
                "selections": selection_seals,
                "experiment_sha256": experiment_sha256,
                "attempt": attempt.relative_to(output).as_posix(),
            },
        )
        results = {}
        for variant, path in (
            ("control", root / "models/weights/TrackNet_best.pt"),
            *paths.items(),
        ):
            model = model_from(path, "cuda:0")
            predict, calls = predict_function(model)
            groups = []
            for index in range(16):
                frames, background, labels = generate_group("test", index)
                source = [
                    (
                        frame,
                        frame / 30,
                        SimpleNamespace(
                            to_image=lambda pixels=pixels: Image.fromarray(pixels)
                        ),
                    )
                    for frame, pixels in enumerate(frames)
                ]
                rows = list(
                    infer_camera_segment(source, background, 8, predict, 512, 288)
                )
                groups.append(
                    {
                        "index": index,
                        "seed": group_seed("test", index),
                        "pixels_sha256": audit.digest(frames.tobytes()),
                        "labels": labels,
                        "rows": rows,
                    }
                )
                progress((index + 1 + 16 * ("control", *VARIANTS).index(variant)) / 48)
            results[variant] = {
                "groups": groups,
                "metrics": synthetic_metrics(groups),
                "model_calls": calls[0],
            }
            model = None
            torch.cuda.empty_cache()
        # Detect even regenerated input drift across methods before accepting results.
        expected = [
            (g["seed"], g["pixels_sha256"], g["labels"])
            for g in results["control"]["groups"]
        ]
        if any(
            [(g["seed"], g["pixels_sha256"], g["labels"]) for g in result["groups"]]
            != expected
            for result in results.values()
        ):
            raise ValueError("Test inputs differ between fixed variants")
        if both_selected(output) != overrides:
            raise ValueError("Selections changed during test")
        publish(
            output / "synthetic-test.json",
            {
                "experiment_sha256": experiment_sha256,
                "selections": selection_seals,
                "results": results,
            },
        )
        return {name: value["metrics"] for name, value in results.items()}

    return admission(root, output, experiment_sha256, "synthetic-test", task)


def validate_test(output, experiment_sha256):
    """Check all fixed methods and full source denominators before diagnostics."""
    selections = {k: v["selection_sha256"] for k, v in both_selected(output).items()}
    opened = audit.read_json((output / "synthetic-test-opened.json").read_bytes())
    value = audit.read_json((output / "synthetic-test.json").read_bytes())
    if any(
        receipt.get("experiment_sha256") != experiment_sha256
        or receipt.get("selections") != selections
        for receipt in (opened, value)
    ):
        raise ValueError("Synthetic test selection/experiment binding changed")
    if set(value.get("results", {})) != {"control", *VARIANTS}:
        raise ValueError("All three fixed test variants required")
    reference = None
    for result in value["results"].values():
        groups = result["groups"]
        if len(groups) != 16 or any(
            g.get("index") != i or g.get("seed") != group_seed("test", i)
            for i, g in enumerate(groups)
        ):
            raise ValueError("Complete fresh test groups required")
        inputs = [(g["seed"], g["pixels_sha256"], g["labels"]) for g in groups]
        if reference is not None and reference != inputs:
            raise ValueError("Synthetic test inputs differ between methods")
        reference = inputs
        if result["metrics"] != synthetic_metrics(groups):
            raise ValueError("Synthetic test counts changed")
    return value


def diagnostic_inputs(root, experiment):
    inputs = existing.verify_inputs(
        root,
        root / ".cache/shuttle139-packet-v1",
        root / ".cache/shuttle139-labels-v1",
        root / ".cache/shuttle139-baseline-v2/baseline.json",
        PROTOCOL,
    )
    packet, _, _, baseline, runs, _ = inputs
    if (
        existing.plan_views(packet["cases"], baseline["evidence"], runs)
        != experiment["views"]
    ):
        raise ValueError("Changed complete original view plan")
    return inputs


def completed_views(output, variant, experiment, experiment_sha256, inputs):
    _, sources, _, baseline, originals, _ = inputs
    checksum = (
        PARENT_SHA256
        if variant == "control"
        else checkpoint_override(selected(output, variant))[1]
    )
    compatibility_protocol = {
        "checkpoint_sha256": checksum,
        "sequence_length": 8,
        "variants": {variant: [512, 288]},
        "device": "cuda:0",
        "precision": "float16",
        "spatial_layouts": {variant: "full"},
    }
    results = {}
    for view in experiment["views"]:
        path = output / variant / (view["id"] + ".json")
        if not path.exists():
            continue
        entry = audit.read_json(path.read_bytes())
        if (
            entry.get("experiment_sha256") != experiment_sha256
            or entry.get("view") != view
        ):
            raise ValueError("Changed completed view lineage")
        run = audit.read_json(audit.sealed_bytes(output, entry["run"]))
        _, meta, times, _ = next(s for s in sources if s[1]["id"] == view["video_id"])
        annotations = baseline["evidence"]["catalogs"][view["video_id"]]["snapshot"][
            "annotations"
        ]
        existing.validate_research_run(
            run,
            view,
            variant,
            compatibility_protocol,
            originals[(view["video_id"], view["core_index"])],
            meta,
            times,
            annotations=annotations,
        )
        if (
            variant in VARIANTS
            and run.get("research_adaptation")
            != checkpoint_override(selected(output, variant))[2]
        ):
            raise ValueError("Candidate checkpoint provenance changed")
        if variant == "control" and "research_adaptation" in run:
            raise ValueError("Control must retain default checkpoint enforcement")
        results[view["id"]] = (entry, run)
    return results


def control_gate(output, experiment, experiment_sha256, inputs):
    completed_views(output, "control", experiment, experiment_sha256, inputs)
    return existing.control_gate(
        output,
        experiment,
        experiment_sha256,
        inputs[4],
        1e-5,
        existing.PHYSICAL_PROJECTION,
    )


def native_variant(root, output, experiment_sha256, variant):
    from . import shuttle

    if variant not in ("control", *VARIANTS):
        raise ValueError("Only three prospectively fixed variants exist")
    validate_test(output, experiment_sha256)
    experiment = load(root, output, experiment_sha256)
    inputs = diagnostic_inputs(root, experiment)
    if (
        variant in VARIANTS
        and not control_gate(output, experiment, experiment_sha256, inputs)[
            "compatible"
        ]
    ):
        raise ValueError("Original control mismatch blocks candidate inference")
    prior = completed_views(output, variant, experiment, experiment_sha256, inputs)
    if len(prior) == len(experiment["views"]):
        raise ValueError("Native variant already complete; do not silently repeat")

    def task(experiment, attempt, progress):
        _, sources, _, baseline, _, plans = inputs
        (output / variant).mkdir(exist_ok=True)
        for index, view in enumerate(experiment["views"]):
            if view["id"] in prior:
                continue
            vid = view["video_id"]
            _, source, _, _ = next(s for s in sources if s[1]["id"] == vid)
            data = audit.inside(root, baseline["locations"]["data"])
            camera_seal = plans[vid]["segments"]
            camera = data / vid / "runs" / (camera_seal["run_id"] + ".json")
            if audit.file_hash(camera) != camera_seal["sha256"]:
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
                    {"research_checkpoint": selected(output, variant)}
                    if variant in VARIANTS
                    else {}
                ),
            )
            publish(
                output / variant / (view["id"] + ".json"),
                {
                    "experiment_sha256": experiment_sha256,
                    "view": view,
                    "run": audit.seal(output, run_path),
                },
            )
        diagnostic_inputs(root, experiment)
        result = completed_views(output, variant, experiment, experiment_sha256, inputs)
        if len(result) != len(experiment["views"]):
            raise ValueError("Every original view must remain")
        if variant == "control":
            gate = control_gate(output, experiment, experiment_sha256, inputs)
            publish(attempt / "control-gate.json", gate)
            if not gate["compatible"]:
                raise ValueError("Original control did not reproduce")
        return {"variant": variant, "views": len(result)}

    return admission(root, output, experiment_sha256, variant, task)


def raw_index(root, output, experiment_sha256):
    if (output / "raw-index.json").exists():
        raise ValueError("Raw index already sealed")
    validate_test(output, experiment_sha256)
    experiment = load(root, output, experiment_sha256)
    inputs = diagnostic_inputs(root, experiment)
    if not control_gate(output, experiment, experiment_sha256, inputs)["compatible"]:
        raise ValueError("Control mismatch blocks raw seal")
    for variant in ("control", *VARIANTS):
        if (
            len(completed_views(output, variant, experiment, experiment_sha256, inputs))
            != 50
        ):
            raise ValueError("All raw views required before scoring")
    proof = existing.prior_attempt_proof(output, root / "data/processed")
    if not proof or any(p["store_status"] != "completed" for p in proof):
        raise ValueError("All native stages must be terminal and completed")
    files = {
        p.relative_to(output).as_posix(): audit.seal(output, p)
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    count = sum((output / name).stat().st_size for name in files)
    if count > PROTOCOL["limits"]["retained_bytes"]:
        raise ValueError("Retained output budget exceeded")
    publish(
        output / "raw-index.json",
        {
            "experiment_sha256": experiment_sha256,
            "files": files,
            "bytes": count,
            "terminal_proofs": proof,
            "labels_scored": False,
        },
    )
    return {
        "raw_index_sha256": audit.file_hash(output / "raw-index.json"),
        "files": len(files),
        "bytes": count,
    }


def report(root, output, experiment_sha256, public_seal_sha256):
    if (output / "report.json").exists() or (output / "report-opened.json").exists():
        raise ValueError("Familiar diagnostics already opened; no silent repetition")
    seal_path = output / "raw-public-seal.json"
    if audit.file_hash(seal_path) != public_seal_sha256:
        raise ValueError(
            "Externally timestamped raw seal is required before diagnostics"
        )
    public = audit.read_json(seal_path.read_bytes())
    if not public.get("comment", "").startswith(
        "https://github.com/Ken0u/badminton-match-analyzer/issues/311#issuecomment-"
    ) or audit.file_hash(output / "raw-index.json") != public.get("raw_index_sha256"):
        raise ValueError("Missing exact external raw-output commitment")
    raw = audit.read_json((output / "raw-index.json").read_bytes())
    if (
        raw.get("experiment_sha256") != experiment_sha256
        or raw.get("labels_scored") is not False
    ):
        raise ValueError("Raw seal experiment changed")
    for entry in raw["files"].values():
        audit.sealed_path(output, entry)
    validate_test(output, experiment_sha256)
    experiment = load(root, output, experiment_sha256)
    inputs = diagnostic_inputs(root, experiment)
    packet, _, labels, _, _, _ = inputs
    gate = control_gate(output, experiment, experiment_sha256, inputs)
    if not gate["compatible"]:
        raise ValueError("Control mismatch prevents comparable report")
    publish(
        output / "report-opened.json",
        {
            "experiment_sha256": experiment_sha256,
            "public_seal_sha256": public_seal_sha256,
        },
    )
    variants = {}
    for variant in ("control", *VARIANTS):
        values = completed_views(output, variant, experiment, experiment_sha256, inputs)
        observations = {}
        for view in experiment["views"]:
            completed = values.get(view["id"])
            for case_id in view["case_ids"]:
                if completed is None:
                    observations[case_id] = {
                        "available": False,
                        "point": None,
                        "reason": "missing_view",
                    }
                else:
                    case = next(c for c in packet["cases"] if c["id"] == case_id)
                    observations[case_id] = {
                        "available": True,
                        "point": completed[1]["frames"][
                            case["frame"] - view["start_frame"]
                        ]["shuttle"],
                        "reason": None,
                    }
        variants[variant] = {
            "groups": existing.grouped_scores(
                packet["cases"], labels["cases"], observations
            ),
            "views": len(values),
            "cases_retained": len(observations),
            "native_rows": sum(v[1]["processed_frames"] for v in values.values()),
            "model_calls": sum(v[1]["model_calls"] for v in values.values()),
            "elapsed_s": sum(v[1]["elapsed_s"] for v in values.values()),
            "peak_tensor_mb": max(
                (v[1]["peak_gpu_memory_mb"] for v in values.values()), default=None
            ),
        }
    publish(
        output / "report.json",
        {
            "experiment_sha256": experiment_sha256,
            "public_raw_seal": public,
            "control_gate": gate,
            "variants": variants,
            "synthetic": audit.read_json((output / "synthetic-test.json").read_bytes()),
            "limitations": PROTOCOL["limitations"],
            "promoted": False,
        },
    )
    return {"report_sha256": audit.file_hash(output / "report.json")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage",
        choices=(
            "freeze",
            "train-decoder",
            "train-convolution",
            "synthetic-test",
            "control",
            "decoder",
            "convolution",
            "raw-index",
            "report",
        ),
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--protocol-sha256")
    parser.add_argument("--experiment-sha256")
    parser.add_argument("--public-seal-sha256")
    parser.add_argument("--deadline", type=float)
    args = parser.parse_args(argv)
    root, output = args.root.resolve(), args.output.resolve()
    if args.stage == "freeze":
        result = freeze(
            root, args.protocol, args.protocol_sha256, output, args.deadline
        )
    elif args.stage in ("control", *VARIANTS):
        result = native_variant(root, output, args.experiment_sha256, args.stage)
    elif args.stage.startswith("train-"):
        result = train(
            root, output, args.experiment_sha256, args.stage.removeprefix("train-")
        )
    elif args.stage == "report":
        result = report(root, output, args.experiment_sha256, args.public_seal_sha256)
    else:
        function = {
            "synthetic-test": synthetic_test,
            "raw-index": raw_index,
        }[args.stage]
        result = function(root, output, args.experiment_sha256)
    print(json.dumps(result, allow_nan=False))
