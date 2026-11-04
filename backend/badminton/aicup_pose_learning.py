"""Private, fixed two-fit weak pose study; never a deployable accuracy claim.

The source clock, provisional actor correspondence and unknown cases remain
separate from verified semantic truth. Freeze is integrity-only; run extracts
features inside real shared Store admission. Verify never fits a model.
"""

import argparse
import copy
import importlib.metadata
import math
import platform
import random
import shutil
import subprocess
import time
from collections import Counter
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path

import numpy as np

from . import aicup_actor_correspondence as actor

producer = actor.producer
read_json, digest, publish = actor.read_json, actor.digest, actor.publish
FAMILIES = ("clear", "lift", "net", "drop", "smash", "drive", "other", "serve")
SIDES = ("forehand", "backhand")
PROTOCOL = {
    "schema_version": 1,
    "name": "aicup-pose-learning-v1",
    "preparation_sha256": actor.PROTOCOL["preparation_sha256"],
    "native_completion_sha256": actor.PROTOCOL["completion_sha256"],
    "actor_prospective_sha256": "ed36c13f0c87fc867ccf0736311c4d8a39c87361a9a2bfd3e0c515d43fd5e030",
    "actor_completion_sha256": "b89e2d5c7e2ca711ccdc36f83dfb9eae673ac8317bf3fe9f06ee60256a48d7fb",
    "actor_diagnostics_sha256": "6d01625e726d113ba17a82df59ae976dd628727386ebe2bf094a5fc5bb745856",
    "expected": {
        "clips": 45,
        "native_frames": 24273,
        "references": 784,
        "train_rows": 431,
        "validation_rows": 353,
        "weak_pairs": 652,
        "unresolved": 132,
    },
    "features": {
        "dimensions": 108,
        "roles": ["hitter", "defender"],
        "joints": [5, 6, 7, 8, 9, 10],
        "minimum_confidence": 0.25,
        "native_offsets": list(range(-5, 5)),
        "center_offsets": [-1, 0],
        "maximum_adjacent_seconds": 0.1,
        "normalization": "(x-box_center_x)/box_height,(y-box_bottom)/box_height",
        "pooling": "Unweighted observed geometry mean; confidence sum/nominal slots",
        "velocity": "Mean adjacent observed differences/exact PTS dt; confidence sum of endpoint minima/9",
        "static": ["center", "center", "zero_velocity"],
        "temporal": ["center", "mean", "velocity"],
        "missing": "Zero coordinates/confidence with explicit observation and velocity masks; no interpolation",
    },
    "labels": {"family": list(FAMILIES), "side": list(SIDES)},
    "training": {
        "seed": 20261104,
        "cpu_threads": 2,
        "epochs": 300,
        "batch_size": 64,
        "hidden": [64, 32],
        "dropout": 0.1,
        "optimizer": "AdamW",
        "learning_rate": 0.001,
        "weight_decay": 0.01,
        "loss_weights": [1.0, 0.5],
        "std_floor": 0.05,
        "normalized_clip": 10.0,
        "class_weights": "Inverse sqrt of known training counts; mean one over supported classes",
        "selection_every": 5,
        "selection": "Mean supported 8-group family macro F1/side balanced recall, strict joint, earlier epoch",
        "arm_tie": "static",
        "prediction": "Argmax supported training classes; unavailable rows unanswered; no threshold search",
    },
    "limits": {"runtime_seconds": 14400, "output_bytes": 1073741824, "real_fits": 2},
    "native_passes": 0,
    "image_bytes": 0,
    "training_ready": False,
    "independent_accuracy_established": False,
    "model_installed_in_app": False,
    "complete_rally_references": {"accepted": 0, "required": 2},
}


def runtime():
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        **{
            name: importlib.metadata.version(name)
            for name in ("numpy", "torch", "psutil")
        },
    }


def code_seals():
    folder = Path(__file__).parent
    root = folder.parents[1]
    paths = [
        *sorted(folder.glob("*.py")),
        root / "scripts/compare_aicup_pose_learning.py",
        root / "data/manifests/aicup_pose_learning_protocol_v1.json",
    ]
    return {p.relative_to(root).as_posix(): digest(p) for p in paths}


def tested_commit():
    root = Path(__file__).resolve().parents[2]
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    for name, expected in code_seals().items():
        raw = subprocess.check_output(["git", "show", head + ":" + name], cwd=root)
        import hashlib

        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("Consumer must match its committed tested source: " + name)
    return head


def check_deadline(granted_at, deadline):
    if (
        not actor.finite([granted_at, deadline])
        or not granted_at <= time.time() < deadline
        or deadline - granted_at > PROTOCOL["limits"]["runtime_seconds"]
    ):
        raise ValueError("Expired or unbounded original pose-learning window")


def load_inputs(prepared, native, actor_prospective, audit):
    """Validate immutable historical seals individually, without extracting features."""
    prepared, native, actor_prospective, audit = map(
        Path, (prepared, native, actor_prospective, audit)
    )
    for path, key in (
        (prepared / "freeze.json", "preparation_sha256"),
        (native / "completion.json", "native_completion_sha256"),
        (actor_prospective, "actor_prospective_sha256"),
        (audit / "completion.json", "actor_completion_sha256"),
        (audit / "diagnostics.json", "actor_diagnostics_sha256"),
    ):
        if digest(path) != PROTOCOL[key]:
            raise ValueError("Changed original input: " + key)
    original, completion = (
        read_json(actor_prospective),
        read_json(audit / "completion.json"),
    )
    if (
        original["protocol"] != actor.PROTOCOL
        or original["prepared"] != str(prepared.resolve())
        or original["native"] != str(native.resolve())
        or completion["prospective_sha256"] != PROTOCOL["actor_prospective_sha256"]
    ):
        raise ValueError("Conflicting historical correspondence binding")
    actor.verify_producer_code(original["code"])
    actor.verify_inventory(
        audit,
        completion["artifacts"]
        | {"completion.json": PROTOCOL["actor_completion_sha256"]},
    )
    claim = actor.audit_claim(original)
    if (
        completion["claim"] != str(claim)
        or read_json(claim)
        != {
            "prospective_sha256": PROTOCOL["actor_prospective_sha256"],
            "output": str(audit.resolve()),
        }
        or not original["granted_at"]
        <= completion["finished_at"]
        < original["deadline"]
    ):
        raise ValueError("Changed original correspondence execution claim/window")
    observations = actor.load_inputs(prepared, native)
    diagnostics = read_json(audit / "diagnostics.json")
    refs = [r for _, _, _, rows in observations for r in rows]
    if [r["id"] for r in refs] != [r["reference_id"] for r in diagnostics] or any(
        r["clip_key"] != d["clip_key"] for r, d in zip(refs, diagnostics, strict=True)
    ):
        raise ValueError("Missing, extra, reordered or conflicting correspondence rows")
    counts = Counter(c["fold"] for c, _, _, rows in observations for _ in rows)
    expected = PROTOCOL["expected"]
    if (
        len(refs) != expected["references"]
        or counts
        != Counter(
            {"train": expected["train_rows"], "validation": expected["validation_rows"]}
        )
        or sum(d["weak_pair"] is not None for d in diagnostics)
        != expected["weak_pairs"]
        or len(refs) - expected["weak_pairs"] != expected["unresolved"]
    ):
        raise ValueError("Changed original cohort/fold/weak-pair denominator")
    if read_json(audit / "aggregate.json") != completion["summary"] or any(
        d["training_ready"]
        or d["correct_hitter"] is not None
        or d["source_scene_truth"] != "unknown"
        for d in diagnostics
    ):
        raise ValueError("Historical unknown truth or aggregate changed")
    return observations, diagnostics


def observed_joints(frame, identity, camera, video):
    values, mask = np.zeros((6, 3), np.float64), np.zeros(6, bool)
    if (
        frame is None
        or frame.get("camera_segment_start_frame") != camera
        or frame.get("calibration_valid") is not True
    ):
        return values, mask
    people = [p for p in frame["players"] if p.get("track_id") == identity]
    if len(people) != 1:
        return values, mask
    person = people[0]
    box, points = person.get("box"), person.get("keypoints")
    if (
        not isinstance(box, list)
        or len(box) != 4
        or not actor.finite(box)
        or not 0 <= box[0] < box[2] <= video["width"]
        or not 0 <= box[1] < box[3] <= video["height"]
        or not isinstance(points, list)
        or len(points) != 17
    ):
        return values, mask
    height, center = box[3] - box[1], (box[0] + box[2]) / 2
    for number, index in enumerate(PROTOCOL["features"]["joints"]):
        p = points[index]
        if (
            not isinstance(p, list)
            or len(p) != 3
            or not actor.finite(p)
            or not 0 <= p[0] < video["width"]
            or not 0 <= p[1] < video["height"]
            or not PROTOCOL["features"]["minimum_confidence"] <= p[2] <= 1
        ):
            continue
        values[number] = [(p[0] - center) / height, (p[1] - box[3]) / height, p[2]]
        mask[number] = True
    return values, mask


def pool(values, mask, nominal):
    count = mask.sum(axis=0)
    result = np.zeros(values.shape[1:], np.float64)
    result[..., :2] = np.divide(
        (values[..., :2] * mask[..., None]).sum(axis=0),
        count[..., None],
        out=result[..., :2],
        where=count[..., None] > 0,
    )
    result[..., 2] = (values[..., 2] * mask).sum(axis=0) / nominal
    return result


def reference_features(reference, diagnostic, result, video, ledger):
    """Label-blind 2-endpoint/10-native-slot geometry with exact PTS velocities."""
    h, pair = reference["source_contact_frame"], diagnostic["weak_pair"]
    values, mask = np.zeros((10, 2, 6, 3), np.float64), np.zeros((10, 2, 6), bool)
    clocks, frames = [], result["frames"]
    available = pair is not None
    if available and (type(h) is not int or not 0 < h < len(frames)):
        raise ValueError("Weak pair has no original contact interval")
    camera = frames[h]["camera_segment_start_frame"] if available else None
    times = []
    for slot, offset in enumerate(PROTOCOL["features"]["native_offsets"]):
        index = h + offset if type(h) is int else -1
        valid = 0 <= index < len(frames)
        clock = ledger["rows"][index] if valid else None
        clocks.append(copy.deepcopy(clock))
        times.append(Fraction(*clock["relative_time"]) if clock else None)
        if available and valid:
            for role, name in enumerate(PROTOCOL["features"]["roles"]):
                values[slot, role], mask[slot, role] = observed_joints(
                    frames[index], pair[name], camera, video
                )
    center = pool(values[4:6], mask[4:6], 2)
    mean = pool(values, mask, 10)
    speeds, adjacent = np.zeros((9, 2, 6, 3), np.float64), np.zeros((9, 2, 6), bool)
    for slot in range(9):
        if times[slot] is None or times[slot + 1] is None:
            continue
        dt = times[slot + 1] - times[slot]
        if (
            not 0
            < dt
            <= Fraction(str(PROTOCOL["features"]["maximum_adjacent_seconds"]))
        ):
            continue
        adjacent[slot] = mask[slot] & mask[slot + 1]
        speeds[slot, ..., :2] = (
            values[slot + 1, ..., :2] - values[slot, ..., :2]
        ) / float(dt)
        speeds[slot, ..., 2] = np.minimum(
            values[slot, ..., 2], values[slot + 1, ..., 2]
        )
    velocity = pool(speeds, adjacent, 9)
    temporal = np.concatenate((center.ravel(), mean.ravel(), velocity.ravel()))
    static = np.concatenate((center.ravel(), center.ravel(), np.zeros(36)))
    if not np.isfinite(temporal).all() or not np.isfinite(static).all():
        raise ValueError("Nonfinite observed pose feature")
    return {
        "static": static.tolist(),
        "temporal": temporal.tolist(),
        "observed_mask": mask.tolist(),
        "adjacent_mask": adjacent.tolist(),
        "native_clocks": clocks,
        "camera": camera,
        "available": available,
        "observed_joint_slots": int(mask.sum()),
        "adjacent_joint_pairs": int(adjacent.sum()),
    }


def extract(observations, diagnostics, prepared):
    output, offset = [], 0
    for clip, video, result, refs in observations:
        ledger = read_json(
            producer.inside(Path(prepared), clip["folder"]) / "native-clock.json"
        )
        for ref in refs:
            d = diagnostics[offset]
            if d["reference_id"] != ref["id"]:
                raise ValueError("Feature/target order changed")
            family = "serve" if ref["kind"] == "serve" else ref["family"]
            output.append(
                {
                    "id": ref["id"],
                    "clip_key": clip["key"],
                    "fold": clip["fold"],
                    "context": clip["context"],
                    "family": FAMILIES.index(family) if family in FAMILIES else -1,
                    "side": SIDES.index(ref["side"]) if ref["side"] in SIDES else -1,
                    "training_ready": False,
                    "scene_truth": "unknown",
                    "actor_truth": "unknown",
                    **reference_features(ref, d, result, video, ledger),
                }
            )
            offset += 1
    if offset != len(diagnostics):
        raise ValueError("Incomplete feature denominator")
    return output


def arrays(rows, arm):
    if arm not in ("static", "temporal") or any(
        r["fold"] not in producer.FOLDS for r in rows
    ):
        raise ValueError("Invalid study arm or held-out source")
    values = np.asarray([r[arm] for r in rows], np.float32)
    if values.shape != (len(rows), 108) or not np.isfinite(values).all():
        raise ValueError("Invalid pose feature dimensions/values")
    return {
        "features": values,
        "available": np.asarray([r["available"] for r in rows], bool),
        "family": np.asarray([r["family"] for r in rows], np.int64),
        "side": np.asarray([r["side"] for r in rows], np.int64),
        "train": np.asarray([r["fold"] == "train" for r in rows], bool),
        "validation": np.asarray([r["fold"] == "validation" for r in rows], bool),
    }


def training_statistics(data):
    eligible = data["train"] & data["available"]
    if not eligible.any():
        raise ValueError("No weakly paired training rows")
    x = data["features"][eligible].astype(np.float64)
    mean, std = (
        x.mean(axis=0),
        np.maximum(x.std(axis=0), PROTOCOL["training"]["std_floor"]),
    )
    weights, supports, counts = [], [], []
    for head, labels in (("family", FAMILIES), ("side", SIDES)):
        truth = data[head][eligible]
        if np.any((truth < -1) | (truth >= len(labels))):
            raise ValueError("Invalid training target")
        count = np.asarray([(truth == i).sum() for i in range(len(labels))], np.int64)
        supported = count > 0
        if not supported.any():
            raise ValueError("No known training labels for " + head)
        weight = np.zeros(len(labels), np.float64)
        weight[supported] = 1 / np.sqrt(count[supported])
        weight[supported] /= weight[supported].mean()
        counts.append(count.tolist())
        supports.append(supported.tolist())
        weights.append(weight.tolist())
    return {
        "mean": mean.tolist(),
        "std": std.tolist(),
        "weights": weights,
        "support": supports,
        "counts": counts,
        "normalization_rows": int(eligible.sum()),
    }


def normalized(data, statistics):
    return np.clip(
        (data["features"] - np.asarray(statistics["mean"], np.float32))
        / np.asarray(statistics["std"], np.float32),
        -PROTOCOL["training"]["normalized_clip"],
        PROTOCOL["training"]["normalized_clip"],
    ).astype(np.float32)


def class_metrics(truth, predicted, labels):
    truth, predicted = np.asarray(truth), np.asarray(predicted)
    if (
        truth.shape != predicted.shape
        or np.any((truth < -1) | (truth >= len(labels)))
        or np.any((predicted < -1) | (predicted >= len(labels)))
    ):
        raise ValueError("Invalid class metric targets/predictions")
    known = truth >= 0
    matrix = np.zeros((len(labels), len(labels) + 1), np.int64)
    for t, p in zip(truth[known], predicted[known], strict=True):
        matrix[t, p if p >= 0 else len(labels)] += 1
    classes = {}
    for i, name in enumerate(labels):
        support, predictions, tp = (
            int(matrix[i].sum()),
            int(matrix[:, i].sum()),
            int(matrix[i, i]),
        )
        classes[name] = {
            "support": support,
            "predictions_on_known_truth": predictions,
            "tp": tp,
            "precision": tp / predictions if predictions else 0.0,
            "recall": tp / support if support else None,
            "f1": 2 * tp / (support + predictions) if support + predictions else None,
        }
    supported = [name for name in labels if classes[name]["support"]]
    return {
        "source_rows": len(truth),
        "known_targets": int(known.sum()),
        "unknown_targets": int((~known).sum()),
        "predictions_on_unknown_truth": int(((predicted >= 0) & ~known).sum()),
        "unanswered_known_targets": int(((predicted < 0) & known).sum()),
        "confusion_columns": [*labels, "unanswered"],
        "confusion": matrix.tolist(),
        "per_class": classes,
        "supported_classes": supported,
        "macro_f1": float(np.mean([classes[n]["f1"] for n in supported]))
        if supported
        else None,
        "balanced_recall": float(np.mean([classes[n]["recall"] for n in supported]))
        if supported
        else None,
        "strict_known_accuracy": float(np.mean(truth[known] == predicted[known]))
        if known.any()
        else None,
    }


def evaluate(data, predictions, selection):
    family, side = (np.asarray(p)[selection] for p in predictions)
    target_f, target_s = data["family"][selection], data["side"][selection]
    available = data["available"][selection]
    known = (target_f >= 0) & (target_s >= 0)
    correct = known & (target_f == family) & (target_s == side)
    pairs = {}
    for f, name in enumerate(FAMILIES):
        for s, stroke_side in enumerate(SIDES):
            target = (target_f == f) & (target_s == s)
            prediction = (family == f) & (side == s) & known
            tp, support, predicted = (
                int((target & prediction).sum()),
                int(target.sum()),
                int(prediction.sum()),
            )
            pairs[name + "/" + stroke_side] = {
                "support": support,
                "predictions_on_known_truth": predicted,
                "tp": tp,
                "precision": tp / predicted if predicted else 0.0,
                "recall": tp / support if support else None,
                "f1": 2 * tp / (support + predicted) if support + predicted else None,
            }
    family_metrics = class_metrics(target_f, family, FAMILIES)
    requested = [
        family_metrics["per_class"][n]["f1"]
        for n in FAMILIES[:6]
        if family_metrics["per_class"][n]["support"]
    ]
    return {
        "source_rows": len(family),
        "weak_pairs": int(available.sum()),
        "unavailable_rows": int((~available).sum()),
        "unknown_joint_targets": int((~known).sum()),
        "family": family_metrics,
        "side": class_metrics(target_s, side, SIDES),
        "requested_six_macro_f1": float(np.mean(requested)) if requested else None,
        "family_side": pairs,
        "correct_joint": int(correct.sum()),
        "strict_joint_all_source_rows": float(correct.sum() / len(family))
        if len(family)
        else None,
        "strict_joint_known_targets": float(correct[known].mean())
        if known.any()
        else None,
        "conditional_joint_given_weak_pair_and_known_targets": float(
            correct[available & known].mean()
        )
        if (available & known).any()
        else None,
        "conditional_denominator": int((available & known).sum()),
        "independent_accuracy": False,
    }


def selection_key(metrics, epoch):
    f, s, joint = (
        metrics["family"]["macro_f1"],
        metrics["side"]["balanced_recall"],
        metrics["strict_joint_all_source_rows"],
    )
    if f is None or s is None or joint is None:
        raise ValueError("Validation selection needs known support for both outputs")
    return ((f + s) / 2, joint, -epoch)


@contextmanager
def cpu_state():
    import torch

    state = (
        random.getstate(),
        np.random.get_state(),
        torch.get_num_threads(),
        torch.are_deterministic_algorithms_enabled(),
        torch.is_deterministic_algorithms_warn_only_enabled(),
        torch.get_default_dtype(),
    )
    try:
        with torch.random.fork_rng(devices=[]):
            torch.set_num_threads(PROTOCOL["training"]["cpu_threads"])
            torch.use_deterministic_algorithms(True)
            torch.set_default_dtype(torch.float32)
            random.seed(PROTOCOL["training"]["seed"])
            np.random.seed(PROTOCOL["training"]["seed"])
            torch.random.default_generator.manual_seed(PROTOCOL["training"]["seed"])
            yield
    finally:
        random.setstate(state[0])
        np.random.set_state(state[1])
        torch.set_num_threads(state[2])
        torch.use_deterministic_algorithms(state[3], warn_only=state[4])
        torch.set_default_dtype(state[5])


def network():
    import torch
    from torch import nn

    class Head(nn.Module):
        def __init__(self):
            super().__init__()
            self.body = nn.Sequential(
                nn.Linear(108, 64),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(64, 32),
                nn.ReLU(),
                nn.Dropout(0.1),
            )
            self.family, self.side = nn.Linear(32, 8), nn.Linear(32, 2)

        def forward(self, x):
            hidden = self.body(x)
            return self.family(hidden), self.side(hidden)

    return Head().to(device="cpu", dtype=torch.float32)


def predict(model, data, statistics):
    import torch

    model.eval()
    with torch.inference_mode():
        logits = model(torch.from_numpy(normalized(data, statistics)))
        predictions = []
        for values, support in zip(logits, statistics["support"], strict=True):
            values[:, ~torch.tensor(support, dtype=torch.bool)] = -torch.inf
            p = values.argmax(dim=1).numpy().copy()
            p[~data["available"]] = -1
            predictions.append(p)
    return predictions


def save_state(path, model):
    import torch

    with Path(path).open("xb") as stream:
        torch.save(
            {
                name: value.detach().cpu().clone()
                for name, value in model.state_dict().items()
            },
            stream,
        )


def rng_state(rng):
    import torch

    numpy_state = np.random.get_state()
    return {
        "seed": PROTOCOL["training"]["seed"],
        "python": random.getstate(),
        "numpy_global": [numpy_state[0], numpy_state[1].tolist(), *numpy_state[2:]],
        "numpy_batches": copy.deepcopy(rng.bit_generator.state),
        "torch_cpu": torch.get_rng_state().tolist(),
        "threads": torch.get_num_threads(),
        "dtype": str(torch.get_default_dtype()),
        "deterministic": torch.are_deterministic_algorithms_enabled(),
    }


def restore_state(path, model):
    import torch

    state = torch.load(path, map_location="cpu", weights_only=True)
    if set(state) != set(model.state_dict()) or any(
        not torch.isfinite(v).all() for v in state.values()
    ):
        raise ValueError("Invalid saved pose model")
    model.load_state_dict(state, strict=True)


def fit(data, output, progress):
    """One original CPU fit, fixed schedule; every selection checkpoint retained."""
    import torch
    from torch import nn

    output = Path(output)
    output.mkdir(exist_ok=False)
    statistics = training_statistics(data)
    publish(output / "statistics.json", statistics)
    config = PROTOCOL["training"]
    with cpu_state():
        rng = np.random.default_rng(config["seed"])
        initial_rng = rng_state(rng)
        model = network()
        parameter_count = sum(p.numel() for p in model.parameters())
        optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=config["learning_rate"],
            weight_decay=config["weight_decay"],
        )
        x = torch.from_numpy(normalized(data, statistics))
        targets = [torch.from_numpy(data[name]) for name in ("family", "side")]
        weights = [torch.tensor(w, dtype=torch.float32) for w in statistics["weights"]]
        support = [torch.tensor(s, dtype=torch.bool) for s in statistics["support"]]
        eligible = np.flatnonzero(data["train"] & data["available"])
        history, best = [], None
        for epoch in range(1, config["epochs"] + 1):
            progress(epoch, False)
            model.train()
            losses = []
            order = rng.permutation(eligible)
            for start in range(0, len(order), config["batch_size"]):
                indices = torch.from_numpy(order[start : start + config["batch_size"]])
                optimizer.zero_grad(set_to_none=True)
                logits = model(x[indices])
                terms = []
                for head in range(2):
                    known = targets[head][indices] >= 0
                    if known.any():
                        values = logits[head][known].masked_fill(~support[head], -1e9)
                        terms.append(
                            config["loss_weights"][head]
                            * nn.functional.cross_entropy(
                                values,
                                targets[head][indices][known],
                                weight=weights[head],
                            )
                        )
                if not terms:
                    continue
                loss = sum(terms)
                if not torch.isfinite(loss):
                    raise ValueError("Nonfinite fixed CPU training loss")
                loss.backward()
                optimizer.step()
                losses.append(float(loss.detach()))
            record = {
                "epoch": epoch,
                "loss": math.fsum(losses) / len(losses) if losses else None,
            }
            if epoch % config["selection_every"] == 0:
                predictions = predict(model, data, statistics)
                metrics = evaluate(data, predictions, data["validation"])
                key = selection_key(metrics, epoch)
                checkpoint = f"epoch-{epoch:03d}.pt"
                save_state(output / checkpoint, model)
                record.update(
                    validation=metrics,
                    selection_key=list(key),
                    checkpoint=checkpoint,
                    checkpoint_sha256=digest(output / checkpoint),
                )
                publish(output / f"epoch-{epoch:03d}.json", record)
                if best is None or key > tuple(best["key"]):
                    best = {"key": list(key), "epoch": epoch, "checkpoint": checkpoint}
                progress(epoch, True)
            history.append(record)
        if best is None:
            raise ValueError("Fixed schedule produced no selectable checkpoint")
        publish(output / "rng.json", {"initial": initial_rng, "final": rng_state(rng)})
        shutil.copyfile(output / best["checkpoint"], output / "model.pt")
        restore_state(output / "model.pt", model)
        predictions = predict(model, data, statistics)
        publish(output / "history.json", history)
        publish(output / "predictions.json", [p.tolist() for p in predictions])
        result = {
            "parameter_count": parameter_count,
            "selection": best,
            "train": evaluate(data, predictions, data["train"]),
            "validation": evaluate(data, predictions, data["validation"]),
        }
        publish(output / "result.json", result)
        return result


def report_metrics(rows, arm_results, predictions):
    report = {
        "source_rows": len(rows),
        "training_ready": False,
        "independent_accuracy_established": False,
        "model_installed_in_app": False,
        "complete_rally_references": {"accepted": 0, "required": 2},
        "arms": {},
    }
    for arm in ("static", "temporal"):
        data = arrays(rows, arm)
        groups = {
            "all": np.ones(len(rows), bool),
            "train": data["train"],
            "validation": data["validation"],
        }
        groups.update(
            {
                "capture:" + c: np.asarray([r["context"] == c for r in rows])
                for c in sorted({r["context"] for r in rows})
            }
        )
        report["arms"][arm] = {
            **arm_results[arm],
            "groups": {
                k: evaluate(data, predictions[arm], mask) for k, mask in groups.items()
            },
        }
    keys = {
        arm: tuple(arm_results[arm]["selection"]["key"][:2])
        for arm in ("static", "temporal")
    }
    report["selected_development_arm"] = (
        "temporal" if keys["temporal"] > keys["static"] else "static"
    )
    report["pose_availability"] = {
        fold: {
            "rows": sum(r["fold"] == fold for r in rows),
            "weak_pairs": sum(r["available"] for r in rows if r["fold"] == fold),
            "observed_joint_slots": sum(
                r["observed_joint_slots"] for r in rows if r["fold"] == fold
            ),
            "nominal_joint_slots": 120 * sum(r["fold"] == fold for r in rows),
            "adjacent_joint_pairs": sum(
                r["adjacent_joint_pairs"] for r in rows if r["fold"] == fold
            ),
            "nominal_adjacent_joint_pairs": 108 * sum(r["fold"] == fold for r in rows),
        }
        for fold in producer.FOLDS
    }
    return report


def execution_claim(plan):
    return (
        Path(plan["workspace"])
        / ".cache"
        / (PROTOCOL["name"] + "-" + PROTOCOL["actor_completion_sha256"] + "-start.json")
    )


def check_output(plan, output):
    output = actor.private_output(plan["workspace"], output)
    protected = [Path(plan[n]).resolve() for n in ("prepared", "native", "audit")]
    protected.append(Path(plan["actor_prospective"]).parent.resolve())
    protected.append(Path(plan["prospective_directory"]).resolve())
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError("New output overlaps immutable inputs/prospective freeze")
    return output


def validate_workspace(plan):
    """An isolated research catalog cannot stand in for native producer admission."""
    workspace = Path(plan["workspace"]).resolve()
    native = read_json(Path(plan["native"]) / "completion.json")
    original = read_json(plan["actor_prospective"])
    if (
        Path(native["shared_data"]).resolve() != workspace / "data/processed"
        or Path(original["workspace"]).resolve() != workspace
    ):
        raise ValueError("Study must use the original real shared Store/workspace")


def budget(plan, prospective_path, output, reserve=0):
    files = {Path(prospective_path), execution_claim(plan)}
    files.update(p for p in Path(output).rglob("*") if p.is_file())
    if (
        sum(p.stat().st_size for p in files if p.is_file()) + reserve
        > PROTOCOL["limits"]["output_bytes"]
    ):
        raise ValueError("Cumulative private pose-study output budget exceeded")


def freeze(
    workspace,
    prepared,
    native,
    actor_prospective,
    audit,
    protocol,
    granted_at,
    deadline,
    output,
):
    check_deadline(granted_at, deadline)
    if read_json(protocol) != PROTOCOL:
        raise ValueError("Changed fixed pose-learning protocol")
    paths = {
        k: str(Path(v).resolve())
        for k, v in {
            "workspace": workspace,
            "prepared": prepared,
            "native": native,
            "actor_prospective": actor_prospective,
            "audit": audit,
        }.items()
    }
    output = actor.private_output(workspace, output)
    plan = {
        **paths,
        "prospective_directory": str(output),
        "granted_at": granted_at,
        "deadline": deadline,
        "protocol": PROTOCOL,
        "runtime": runtime(),
        "code": code_seals(),
        "tested_commit": tested_commit(),
        "features_extracted": False,
        "real_fits": 0,
    }
    # Protect every input and its parent before creating any new file.
    for p in (
        Path(paths["prepared"]),
        Path(paths["native"]),
        Path(paths["audit"]),
        Path(paths["actor_prospective"]).parent,
    ):
        if output.is_relative_to(p) or p.is_relative_to(output):
            raise ValueError("Prospective output overlaps original inputs")
    observations, _ = load_inputs(
        **{k: paths[k] for k in ("prepared", "native", "actor_prospective", "audit")}
    )
    validate_workspace(plan)
    plan["denominator"] = {
        "clips": len(observations),
        "references": sum(len(o[3]) for o in observations),
    }
    if plan["code"] != code_seals() or plan["runtime"] != runtime():
        raise ValueError("Consumer/runtime changed during integrity-only freeze")
    check_deadline(granted_at, deadline)
    output.mkdir(exist_ok=False)
    publish(output / "prospective.json", plan)
    budget(plan, output / "prospective.json", output)
    return {
        "prospective_sha256": digest(output / "prospective.json"),
        "features_extracted": False,
        "real_fits": 0,
    }


def prospective(path, expected, clock):
    if digest(path) != expected:
        raise ValueError("Changed prospective pose-learning freeze")
    plan = read_json(path)
    if (
        plan["code"] != code_seals()
        or plan["runtime"] != runtime()
        or plan["protocol"] != PROTOCOL
    ):
        raise ValueError("Changed committed pose consumer/runtime/protocol")
    if clock:
        check_deadline(plan["granted_at"], plan["deadline"])
    return plan


def original_inputs(plan):
    return load_inputs(
        **{k: plan[k] for k in ("prepared", "native", "actor_prospective", "audit")}
    )


def run(prospective_path, prospective_sha256, output):
    plan = prospective(prospective_path, prospective_sha256, True)
    output = check_output(plan, output)
    validate_workspace(plan)
    _, data, _ = producer.configure_workspace(plan["workspace"])
    import psutil

    from .jobs import run_local_job
    from .storage import Store

    claim = execution_claim(plan)
    if output.exists():
        raise FileExistsError("Preserve existing study output")
    publish(claim, {"prospective_sha256": prospective_sha256, "output": str(output)})
    output.mkdir(exist_ok=False)
    store, before = Store(data), producer.annotation_snapshot(data)
    completed_fits = []

    def task(job_id, progress):
        process = psutil.Process()
        publish(
            output / "process.json",
            {
                "job_id": job_id,
                "pid": process.pid,
                "created_at": process.create_time(),
                "cwd": str(Path.cwd()),
                "command": process.cmdline(),
                "prospective_sha256": prospective_sha256,
            },
        )
        observations, diagnostics = original_inputs(plan)
        rows = extract(observations, diagnostics, plan["prepared"])
        publish(output / "features.json", rows)
        results, predictions = {}, {}
        for index, arm in enumerate(("static", "temporal")):

            def report(epoch, checkpoint):
                prospective(prospective_path, prospective_sha256, True)
                budget(plan, prospective_path, output, 8 * 1024 * 1024)
                if checkpoint:
                    original_inputs(plan)
                progress((index + epoch / PROTOCOL["training"]["epochs"]) / 2)

            results[arm] = fit(arrays(rows, arm), output / arm, report)
            completed_fits.append(arm)
            predictions[arm] = read_json(output / arm / "predictions.json")
            original_inputs(plan)
        if (
            results["static"]["parameter_count"]
            != results["temporal"]["parameter_count"]
        ):
            raise ValueError("Static/temporal network capacity differs")
        publish(output / "report.json", report_metrics(rows, results, predictions))
        prospective(prospective_path, prospective_sha256, True)
        if producer.annotation_snapshot(data) != before:
            raise ValueError("Original annotation history changed")
        return {
            "references": len(rows),
            "weak_pairs": sum(r["available"] for r in rows),
            "real_fits": len(completed_fits),
            "prospective_sha256": prospective_sha256,
        }

    try:
        summary = run_local_job(store, "feature-preparation", None, task)
        job = store.job(read_json(output / "process.json")["job_id"])
        if job["status"] != "completed" or job["summary"] != summary:
            raise ValueError("Study requires durable real shared Store completion")
        original_inputs(plan)
        prospective(prospective_path, prospective_sha256, True)
        record = {
            "summary": summary,
            "prospective_sha256": prospective_sha256,
            "job_id": job["id"],
            "shared_data": str(data),
            "execution_claim": str(claim),
            "finished_at": time.time(),
            "original_annotations_sha256": before,
            "artifacts": producer.inventory(output),
            "model_installed_in_app": False,
            "training_ready": False,
            "test_opened": False,
        }
        budget(plan, prospective_path, output, len(producer.encoded(record)))
        publish(output / "completion.json", record)
        return summary
    except BaseException as error:
        publish(
            output / "failure.json",
            {
                "error_type": type(error).__name__,
                "at": time.time(),
                "completed_fits": completed_fits,
                "original_run_consumed": True,
            },
        )
        raise


def verify_arm(data, output):
    """Recompute every saved selection checkpoint without optimizer or fitting."""
    output = Path(output)
    statistics = read_json(output / "statistics.json")
    if statistics != training_statistics(data):
        raise ValueError("Changed train-only normalization/label weights")
    history = read_json(output / "history.json")
    config = PROTOCOL["training"]
    if [h["epoch"] for h in history] != list(range(1, config["epochs"] + 1)):
        raise ValueError("Incomplete fixed training history")
    result, best = read_json(output / "result.json"), None
    with cpu_state():
        initial_rng = rng_state(np.random.default_rng(config["seed"]))
        # Tuple/list normalization uses the same strict JSON encoding as output.
        import json

        if read_json(output / "rng.json")["initial"] != json.loads(
            producer.encoded(initial_rng)
        ):
            raise ValueError("Changed original seed/CPU/RNG state")
        model = network()
        if result["parameter_count"] != sum(p.numel() for p in model.parameters()):
            raise ValueError("Changed network capacity")
        for item in history:
            epoch = item["epoch"]
            if item["loss"] is not None and (
                not actor.finite([item["loss"]]) or item["loss"] < 0
            ):
                raise ValueError("Invalid saved training loss")
            if epoch % config["selection_every"]:
                if set(item) != {"epoch", "loss"}:
                    raise ValueError("Unexpected off-schedule selection")
                continue
            expected = f"epoch-{epoch:03d}.pt"
            if item["checkpoint"] != expected:
                raise ValueError("Changed checkpoint schedule")
            if item != read_json(output / f"epoch-{epoch:03d}.json") or item[
                "checkpoint_sha256"
            ] != digest(output / expected):
                raise ValueError("Changed saved checkpoint history/weights")
            restore_state(output / expected, model)
            metrics = evaluate(
                data, predict(model, data, statistics), data["validation"]
            )
            key = list(selection_key(metrics, epoch))
            if metrics != item["validation"] or key != item["selection_key"]:
                raise ValueError("Saved validation history does not reproduce")
            if best is None or tuple(key) > tuple(best["key"]):
                best = {"key": key, "epoch": epoch, "checkpoint": expected}
        if result["selection"] != best or digest(output / "model.pt") != digest(
            output / best["checkpoint"]
        ):
            raise ValueError("Changed fixed model selection")
        restore_state(output / "model.pt", model)
        predictions = predict(model, data, statistics)
        if [p.tolist() for p in predictions] != read_json(output / "predictions.json"):
            raise ValueError("Saved predictions do not reproduce")
        for fold in producer.FOLDS:
            if result[fold] != evaluate(data, predictions, data[fold]):
                raise ValueError("Saved full-denominator metrics do not reproduce")
    return result, predictions


def verify(prospective_path, prospective_sha256, output):
    plan = prospective(prospective_path, prospective_sha256, False)
    output = check_output(plan, output)
    completion = read_json(output / "completion.json")
    claim = execution_claim(plan)
    if (
        completion["prospective_sha256"] != prospective_sha256
        or completion["execution_claim"] != str(claim)
        or read_json(claim)
        != {"prospective_sha256": prospective_sha256, "output": str(output)}
        or not plan["granted_at"] <= completion["finished_at"] < plan["deadline"]
        or completion["shared_data"] != str(Path(plan["workspace"]) / "data/processed")
    ):
        raise ValueError("Changed original execution binding/window/Store")
    actor.verify_inventory(
        output,
        completion["artifacts"]
        | {"completion.json": digest(output / "completion.json")},
    )
    observations, diagnostics = original_inputs(plan)
    rows = extract(observations, diagnostics, plan["prepared"])
    if rows != read_json(output / "features.json"):
        raise ValueError(
            "Features/masks/targets do not reproduce from original observations"
        )
    results, predictions = {}, {}
    for arm in ("static", "temporal"):
        results[arm], predictions[arm] = verify_arm(arrays(rows, arm), output / arm)
    if read_json(output / "report.json") != report_metrics(rows, results, predictions):
        raise ValueError("Full source/capture/sparse-cell report does not reproduce")
    import sqlite3

    with sqlite3.connect(
        (Path(completion["shared_data"]) / "catalog.sqlite3").as_uri() + "?mode=ro",
        uri=True,
    ) as db:
        row = db.execute(
            "SELECT document FROM jobs WHERE id=?", (completion["job_id"],)
        ).fetchone()
    import json

    job = json.loads(row[0]) if row else {}
    expected = {
        "references": len(rows),
        "weak_pairs": sum(r["available"] for r in rows),
        "real_fits": 2,
        "prospective_sha256": prospective_sha256,
    }
    if (
        completion["summary"] != expected
        or job.get("status") != "completed"
        or job.get("summary") != expected
        or completion["original_annotations_sha256"]
        != producer.annotation_snapshot(Path(completion["shared_data"]))
        or completion["training_ready"]
        or completion["model_installed_in_app"]
        or completion["test_opened"]
    ):
        raise ValueError("Changed durable Store/annotation/non-promotion evidence")
    budget(plan, prospective_path, output)
    return {
        "verified_references": len(rows),
        "real_fits": 2,
        "independent_accuracy_established": False,
        "selected_development_arm": read_json(output / "report.json")[
            "selected_development_arm"
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("freeze")
    for name in (
        "workspace",
        "prepared",
        "native",
        "actor-prospective",
        "audit",
        "protocol",
        "output",
    ):
        command.add_argument("--" + name, type=Path, required=True)
    for name in ("granted-at", "deadline"):
        command.add_argument("--" + name, type=float, required=True)
    for name in ("run", "verify"):
        command = sub.add_parser(name)
        command.add_argument(
            "--prospective", dest="prospective_path", type=Path, required=True
        )
        command.add_argument("--prospective-sha256", required=True)
        command.add_argument("--output", type=Path, required=True)
    args = vars(parser.parse_args(argv))
    name = args.pop("command")
    print(
        producer.encoded(
            {"freeze": freeze, "run": run, "verify": verify}[name](**args)
        ).decode(),
        end="",
    )
