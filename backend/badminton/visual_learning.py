"""Experimental raw-video event learning with capture-separated evaluation.

The reference clock is a published ordinal interval, not adjudicated truth.
This module never installs weights or writes application annotations.
"""

import json
import os
import random
import time
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path

import numpy as np

from .video import write_json
from .visual_inputs import (
    GROUPS,
    MANIFEST,
    clip_key,
    context_indices,
    feature_recipe,
    load_protocol,
    read_features,
    sha256,
)


def references(records, times, spec):
    result = []
    for record in records:
        ordinal = record["source_contact_frame"]
        if type(ordinal) is not int or not 0 <= ordinal < len(times):
            raise ValueError(
                "Published contact ordinal is outside decoded source bounds"
            )
        labels = (
            "serve" if record["kind"] == "serve" else record["family"],
            record["side"],
            record["source_court_end"],
        )
        encoded = [
            spec["labels"][name].index(value)
            for name, value in zip(
                ("family", "side", "hitter_end"), labels, strict=True
            )
        ]
        left, right = max(0, ordinal - 1), ordinal
        result.append(
            {
                "id": record["id"],
                "left": left,
                "right": right,
                "start_s": float(times[left]),
                "end_s": float(times[right]),
                "labels": encoded,
                "left_censored": ordinal == 0,
            }
        )
    return result


def training_samples(refs, times, valid, config, rng):
    """Positive bags retain both plausible ordinals; negatives avoid all refs."""
    positive = []
    for ref in refs:
        centers = [i for i in range(ref["left"], ref["right"] + 1) if valid[i]]
        if centers:
            positive.append(
                {"centers": centers, "labels": ref["labels"], "positive": True}
            )
    eligible = np.flatnonzero(valid)
    for ref in refs:
        distance = np.maximum(
            ref["start_s"] - times[eligible], times[eligible] - ref["end_s"]
        )
        eligible = eligible[distance > config["negative_exclusion_s"] + 1e-8]
    # Sample without replacement. Short clips retain their true negative support.
    count = min(len(eligible), config["negative_ratio"] * len(positive))
    negatives = [
        {"centers": [int(i)], "labels": [-1, -1, -1], "positive": False}
        for i in rng.choice(eligible, count, replace=False)
    ]
    return positive + negatives


def normalize_features(features, mean, std):
    return np.clip((np.asarray(features, dtype=np.float32) - mean) / std, -10, 10)


def input_windows(features, indices, centers, mean, std):
    selected = indices[np.asarray(centers)]
    available = selected >= 0
    values = normalize_features(features[selected.clip(0)], mean, std)
    values[~available] = 0
    return values, available.astype(np.float32)


def normalization(clips, dim):
    """Only learning-train original/mirrored pixels contribute statistics."""
    count = 0
    total, squares = np.zeros(dim, np.float64), np.zeros(dim, np.float64)
    for clip in clips:
        if clip["fold"] != "train":
            continue
        for name in ("features.npy", "mirrored.npy"):
            source = clip["arrays"][name]
            for start in range(0, len(source), 512):
                block = np.asarray(source[start : start + 512], dtype=np.float64)
                count += len(block)
                total += block.sum(axis=0)
                squares += np.square(block).sum(axis=0)
    if not count:
        raise ValueError("No training observations for visual normalization")
    mean = total / count
    std = np.maximum(np.sqrt(np.maximum(0, squares / count - mean**2)), 0.05)
    return mean.astype(np.float32), std.astype(np.float32), count


def load_clips(index, features, *, folds_to_open):
    spec, _groups, members, folds = load_protocol(index)
    completed = json.loads((features / "completed.json").read_text(encoding="utf-8"))
    recipe = feature_recipe(spec)
    if (
        completed["recipe"] != recipe
        or completed["capture_manifest_sha256"] != sha256(GROUPS)
        or completed["learning_manifest_sha256"] != sha256(MANIFEST)
    ):
        raise ValueError(
            "Feature preparation does not match the frozen learning protocol"
        )
    expected = {clip_key(c) for c in members if c["source_partition"] == "train"}
    completed_members = {row["clip"]: row for row in completed["members"]}
    if (
        len(completed_members) != len(completed["members"])
        or set(completed_members) != expected
    ):
        raise ValueError(
            "Feature completion registry must cover each labelled source exactly once"
        )
    by_key = defaultdict(list)
    for record in json.loads((index / "records.json").read_text(encoding="utf-8")):
        by_key[clip_key(record)].append(record)
    clips, runtime = [], None
    for member in members:
        key = clip_key(member)
        fold = folds[key]
        if member["source_partition"] != "train" or fold not in folds_to_open:
            continue
        directory = features / key.replace(":", "-")
        if completed_members[key]["fold"] != fold or completed_members[key][
            "receipt_sha256"
        ] != sha256(directory / "receipt.json"):
            raise ValueError("Feature receipt changed after preparation completed")
        cached = read_features(directory, member, recipe, fold == "train")
        if cached is None:
            raise ValueError(f"Feature preparation is incomplete: {key}")
        receipt, arrays = cached
        if runtime is None:
            runtime = receipt["runtime"]
        if receipt["runtime"] != runtime:
            raise ValueError(
                "Visual learning requires one consistent encoder runtime across sources"
            )
        cuts = [c["frame"] for c in receipt["cuts"]]
        indices, valid = context_indices(arrays["times.npy"], cuts, spec["context"])
        refs = references(by_key[key], arrays["times.npy"], spec)
        clips.append(
            {
                "key": key,
                "fold": fold,
                "arrays": arrays,
                "indices": indices,
                "valid": valid,
                "refs": refs,
                "cuts": cuts,
                "receipt_sha256": sha256(directory / "receipt.json"),
                "encoder_runtime": receipt["runtime"],
            }
        )
    return spec, clips


def create_model(spec):
    """Lazy Torch dependency; a frame projection plus a 31-bin temporal field."""
    import torch
    from torch import nn

    config = spec["training"]

    class TemporalEvents(nn.Module):
        def __init__(self):
            super().__init__()
            width = config["hidden_dim"]
            self.project = nn.Linear(spec["encoder"]["feature_dim"] + 1, width)
            self.layers = nn.ModuleList(
                [
                    nn.Conv1d(
                        width,
                        width,
                        config["kernel_size"],
                        padding=dilation,
                        dilation=dilation,
                    )
                    for dilation in config["temporal_dilations"]
                ]
            )
            self.dropout = nn.Dropout(config["dropout"])
            self.head = nn.Conv1d(
                width, 1 + sum(len(v) for v in spec["labels"].values()), 1
            )

        def forward(self, values, mask):
            # Every intermediate observation remains masked. This prevents a
            # bias or convolution from inventing context beyond cuts/clip edges.
            x = torch.cat([values, mask.unsqueeze(-1)], dim=-1)
            x = torch.nn.functional.gelu(self.project(x)).transpose(1, 2)
            support = mask.unsqueeze(1)
            x = x * support
            for layer in self.layers:
                x = (x + self.dropout(torch.nn.functional.gelu(layer(x)))) * support
            return self.head(x).transpose(1, 2)

    return TemporalEvents()


def split_heads(logits, spec):
    result, offset = {"contact": logits[..., 0]}, 1
    for name in ("family", "side", "hitter_end"):
        count = len(spec["labels"][name])
        result[name] = logits[..., offset : offset + count]
        offset += count
    return result


def predict_clip(model, clip, spec, mean, std, device):
    """No source contact or hitter target is supplied to prediction."""
    import torch

    features = clip["arrays"]["features.npy"]
    times = clip["arrays"]["times.npy"]
    dim = 1 + sum(len(v) for v in spec["labels"].values())
    outputs = np.zeros((len(features), dim), np.float32)
    # Exact fast path for regular 30Hz source clocks. Receptive field is31;
    # chunk halos retain15 actual observations and never cross camera cuts.
    regular = np.allclose(np.diff(times), 1 / 30, rtol=0, atol=1e-7)
    with torch.inference_mode():
        if regular:
            edges = sorted({0, len(features), *clip["cuts"]})
            for left, right in pairwise(edges):
                for start in range(left, right, 512):
                    end = min(start + 512, right)
                    lo, hi = max(left, start - 15), min(right, end + 15)
                    values = normalize_features(features[lo:hi], mean, std)
                    tensor = torch.from_numpy(values[None]).to(device)
                    mask = torch.ones((1, hi - lo), device=device)
                    prediction = model(tensor, mask)[0, start - lo : end - lo]
                    outputs[start:end] = prediction.cpu().numpy()
        else:
            for start in range(0, len(features), 64):
                centers = np.arange(start, min(start + 64, len(features)))
                values, mask = input_windows(
                    features, clip["indices"], centers, mean, std
                )
                tensor = torch.from_numpy(values).to(device)
                mask = torch.from_numpy(mask).to(device)
                outputs[centers] = (
                    model(tensor, mask)[:, len(spec["context"]["offsets_s"]) // 2]
                    .cpu()
                    .numpy()
                )
    return outputs


def spot_events(clip, logits, threshold, spec):
    heads = split_heads(logits, spec)
    probability = 1 / (1 + np.exp(-np.clip(heads["contact"], -50, 50)))
    times = clip["arrays"]["times.npy"]
    candidates = np.flatnonzero(clip["valid"] & (probability >= threshold))
    gaps = (
        np.flatnonzero(np.diff(times) > spec["context"]["max_source_step_s"] + 1e-8) + 1
    )
    boundaries = np.unique(np.r_[clip["cuts"], gaps])
    contexts = np.searchsorted(boundaries, np.arange(len(times)), side="right")
    chosen = []
    for frame in sorted(candidates, key=lambda i: (-probability[i], i)):
        if any(
            contexts[frame] == contexts[old]
            and abs(times[frame] - times[old]) < spec["training"]["nms_s"] - 1e-8
            for old in chosen
        ):
            continue
        chosen.append(frame)
    return [
        {
            "frame": int(frame),
            "time_s": float(times[frame]),
            "score": float(probability[frame]),
            "labels": [
                int(heads[name][frame].argmax())
                for name in ("family", "side", "hitter_end")
            ],
        }
        for frame in sorted(chosen)
    ]


def match_intervals(refs, predictions, tolerance):
    """Maximum-cardinality then minimum-error ordered source-interval matching."""
    refs = sorted(refs, key=lambda r: (r["start_s"], r["id"]))
    predictions = sorted(predictions, key=lambda p: p["time_s"])
    scores = [[(0, 0.0)] * (len(predictions) + 1) for _ in range(len(refs) + 1)]
    moves = [bytearray(len(predictions) + 1) for _ in range(len(refs) + 1)]
    for i, ref in enumerate(refs, 1):
        for j, prediction in enumerate(predictions, 1):
            error = max(
                ref["start_s"] - prediction["time_s"],
                prediction["time_s"] - ref["end_s"],
                0.0,
            )
            options = [(scores[i - 1][j], 1), (scores[i][j - 1], 2)]
            if error <= tolerance + 1e-8:
                count, total = scores[i - 1][j - 1]
                options.append(((count - 1, total + error), 3))
            scores[i][j], moves[i][j] = min(options, key=lambda option: option[0])
    matches, i, j = [], len(refs), len(predictions)
    while i and j:
        if moves[i][j] == 3:
            matches.append((refs[i - 1], predictions[j - 1]))
            i, j = i - 1, j - 1
        elif moves[i][j] == 1:
            i -= 1
        else:
            j -= 1
    return list(reversed(matches))


def event_metrics(clips, predictions, spec):
    total_refs = total_predictions = contacts = tuples = 0
    correct = Counter()
    family_refs, family_preds, family_tp = Counter(), Counter(), Counter()
    pair_refs, pair_preds, pair_tp = Counter(), Counter(), Counter()
    confusion = np.zeros((8, 8), dtype=int)
    unavailable = censored = 0
    for clip in clips:
        refs, events = clip["refs"], predictions[clip["key"]]
        total_refs += len(refs)
        total_predictions += len(events)
        censored += sum(ref["left_censored"] for ref in refs)
        unavailable += sum(
            not any(clip["valid"][ref["left"] : ref["right"] + 1]) for ref in refs
        )
        family_refs.update(ref["labels"][0] for ref in refs)
        family_preds.update(event["labels"][0] for event in events)
        pair_refs.update(tuple(ref["labels"][:2]) for ref in refs)
        pair_preds.update(tuple(event["labels"][:2]) for event in events)
        matches = match_intervals(
            refs, events, spec["training"]["primary_timing_tolerance_s"]
        )
        contacts += len(matches)
        for ref, event in matches:
            equal = [
                a == b for a, b in zip(ref["labels"], event["labels"], strict=True)
            ]
            tuples += all(equal)
            for name, value in zip(
                ("family", "side", "hitter_end"), equal, strict=True
            ):
                correct[name] += value
            if equal[0]:
                family_tp[ref["labels"][0]] += 1
            if all(equal[:2]):
                pair_tp[tuple(ref["labels"][:2])] += 1
            confusion[ref["labels"][0], event["labels"][0]] += 1

    def metric(tp, predicted=total_predictions, references=total_refs):
        return {
            "support": int(references),
            "predicted_count": int(predicted),
            "tp": int(tp),
            "fp": int(predicted - tp),
            "fn": int(references - tp),
            "precision": tp / predicted if predicted else None,
            "recall": tp / references if references else None,
            "f1": 2 * tp / (predicted + references) if predicted + references else None,
        }

    return {
        "references": total_refs,
        "predictions": total_predictions,
        "contact": metric(contacts),
        "tuple": metric(tuples),
        "spotted_family": metric(correct["family"]),
        "spotted_side": metric(correct["side"]),
        "spotted_hitter_end": metric(correct["hitter_end"]),
        "conditional_on_matched_contact": {
            name: correct[name] / contacts if contacts else 0.0
            for name in ("family", "side", "hitter_end")
        },
        "family_metrics": {
            name: metric(family_tp[i], family_preds[i], family_refs[i])
            for i, name in enumerate(spec["labels"]["family"])
        },
        "family_side_metrics": {
            f"{family}/{side}": metric(pair_tp[i, j], pair_preds[i, j], pair_refs[i, j])
            for i, family in enumerate(spec["labels"]["family"])
            for j, side in enumerate(spec["labels"]["side"])
        },
        "matched_family_confusion": confusion.tolist(),
        "reference_contacts_without_valid_context": unavailable,
        "left_censored_references": censored,
        "reference_status": "Published ordinal intervals and labels; not independent source adjudication",
    }


def validation_selection(clips, outputs, spec):
    best = None
    for threshold in spec["training"]["contact_threshold_grid"]:
        predictions = {
            clip["key"]: spot_events(clip, outputs[clip["key"]], threshold, spec)
            for clip in clips
        }
        metrics = event_metrics(clips, predictions, spec)
        score = (metrics["tuple"]["f1"], metrics["contact"]["f1"])
        if best is None or score > best[0]:
            best = (score, threshold, metrics)
    return best[1], best[2]


def _class_weights(samples, spec, device):
    import torch

    result = {}
    for index, name in enumerate(("family", "side", "hitter_end")):
        counts = Counter(s["labels"][index] for s in samples if s["positive"])
        weights = np.asarray(
            [
                1 / np.sqrt(counts[i]) if counts[i] else 0.0
                for i in range(len(spec["labels"][name]))
            ],
            np.float32,
        )
        if np.any(weights > 0):
            weights /= weights[weights > 0].mean()
        result[name] = torch.from_numpy(weights).to(device)
    return result


def train_visual(index, features, output, progress, *, device="cuda:0"):
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch

    if output.exists() and any(output.iterdir()):
        raise ValueError(
            "Training output already exists; preserve it and choose a new run directory"
        )
    spec, clips = load_clips(index, features, folds_to_open={"train", "validation"})
    training = [c for c in clips if c["fold"] == "train"]
    validation = [c for c in clips if c["fold"] == "validation"]
    if not training or not validation:
        raise ValueError(
            "Visual learning requires nonempty capture-separated train and validation folds"
        )
    config = spec["training"]
    seed = config["seed"]
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise ValueError("CUDA training requested but CUDA is unavailable")
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True)
    rng = np.random.default_rng(seed)
    mean, std, norm_count = normalization(training, spec["encoder"]["feature_dim"])
    output.mkdir(parents=True, exist_ok=True)
    np.savez(output / "normalization.npz", mean=mean, std=std)
    write_json(
        output / "protocol.json",
        {
            "spec": spec,
            "learning_manifest_sha256": sha256(MANIFEST),
            "capture_manifest_sha256": sha256(GROUPS),
            "feature_recipe": feature_recipe(spec),
            "implementation_sha256": sha256(Path(__file__)),
            "source_receipts": {c["key"]: c["receipt_sha256"] for c in clips},
            "normalization_observations": norm_count,
            "normalization_sha256": sha256(output / "normalization.npz"),
            "encoder_runtime": training[0]["encoder_runtime"],
            "torch": torch.__version__,
            "device": device,
            "test_head_predictions_opened": False,
        },
    )
    samples = []
    for ci, clip in enumerate(training):
        for sample in training_samples(
            clip["refs"], clip["arrays"]["times.npy"], clip["valid"], config, rng
        ):
            samples.append(sample | {"clip_index": ci})
    if not any(s["positive"] for s in samples) or not any(
        not s["positive"] for s in samples
    ):
        raise ValueError("Visual training requires supported positives and negatives")
    weights = _class_weights(samples, spec, device)
    model = create_model(spec).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config["learning_rate"],
        weight_decay=config["weight_decay"],
    )
    best_score, started = (-1.0, -1.0), time.perf_counter()
    for epoch in range(1, config["epochs"] + 1):
        model.train()
        losses = []
        order = rng.permutation(len(samples))
        for start in range(0, len(order), config["batch_size"]):
            batch = [samples[i] for i in order[start : start + config["batch_size"]]]
            values, masks, owners = [], [], []
            for bi, sample in enumerate(batch):
                clip = training[sample["clip_index"]]
                name = "mirrored.npy" if rng.random() < 0.5 else "features.npy"
                window, mask = input_windows(
                    clip["arrays"][name], clip["indices"], sample["centers"], mean, std
                )
                values.extend(window)
                masks.extend(mask)
                owners.extend([bi] * len(window))
            logits = model(
                torch.from_numpy(np.stack(values)).to(device),
                torch.from_numpy(np.stack(masks)).to(device),
            )[:, len(spec["context"]["offsets_s"]) // 2]
            # Multiple-instance positive bags: choose the most confident valid
            # source ordinal, then apply its semantic targets at that location.
            chosen = []
            for bi in range(len(batch)):
                rows = [i for i, owner in enumerate(owners) if owner == bi]
                best = logits[rows, 0].argmax().item()
                chosen.append(rows[best])
            heads = split_heads(logits[chosen], spec)
            positive = torch.tensor([s["positive"] for s in batch], device=device)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(
                heads["contact"], positive.float()
            )
            for li, name in enumerate(("family", "side", "hitter_end")):
                if positive.any():
                    labels = torch.tensor(
                        [s["labels"][li] for s in batch if s["positive"]], device=device
                    )
                    class_loss = torch.nn.functional.cross_entropy(
                        heads[name][positive], labels, weight=weights[name]
                    )
                    loss = loss + config[f"{name}_loss_weight"] * class_loss
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            losses.append(loss.item())
        row = {
            "epoch": epoch,
            "loss": float(np.mean(losses)),
            "elapsed_s": round(time.perf_counter() - started, 2),
        }
        if epoch % config["evaluate_every"] == 0:
            model.eval()
            outputs = {
                c["key"]: predict_clip(model, c, spec, mean, std, device)
                for c in validation
            }
            threshold, metrics = validation_selection(validation, outputs, spec)
            score = (metrics["tuple"]["f1"], metrics["contact"]["f1"])
            row.update(threshold=threshold, validation=metrics)
            if score > best_score:
                best_score = score
                temporary = output / "selected.tmp"
                torch.save(model.state_dict(), temporary)
                temporary.replace(output / "selected.pt")
                write_json(
                    output / "selected.json",
                    {
                        "epoch": epoch,
                        "threshold": threshold,
                        "validation": metrics,
                        "weights_sha256": sha256(output / "selected.pt"),
                        "protocol_sha256": sha256(output / "protocol.json"),
                        "normalization_sha256": sha256(output / "normalization.npz"),
                        "test_head_predictions_opened": False,
                        "selection_final": False,
                    },
                )
        with (output / "history.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")
        print(
            json.dumps({k: v for k, v in row.items() if k != "validation"}), flush=True
        )
        progress(epoch / config["epochs"])
    selected = json.loads((output / "selected.json").read_text())
    selected["selection_final"] = True
    write_json(output / "selected.json", selected)
    result = {
        "epochs": config["epochs"],
        "training_samples": len(samples),
        "supported_positive_bags": sum(s["positive"] for s in samples),
        "selected": selected,
        "elapsed_s": round(time.perf_counter() - started, 2),
        "app_annotations_written": False,
        "installed_in_app": False,
    }
    write_json(output / "completed.json", result)
    return result


def evaluate_visual(index, features, run, output, progress, *, device="cuda:0"):
    if output.exists():
        raise ValueError("Evaluation output already exists; preserve the frozen result")
    selected = json.loads((run / "selected.json").read_text(encoding="utf-8"))
    protocol = json.loads((run / "protocol.json").read_text(encoding="utf-8"))
    completed = (
        json.loads((run / "completed.json").read_text(encoding="utf-8"))
        if (run / "completed.json").is_file()
        else {}
    )
    if (
        not selected.get("selection_final")
        or completed.get("selected") != selected
        or selected["weights_sha256"] != sha256(run / "selected.pt")
        or selected["protocol_sha256"] != sha256(run / "protocol.json")
        or selected["normalization_sha256"] != sha256(run / "normalization.npz")
        or protocol["implementation_sha256"] != sha256(Path(__file__))
        or protocol["capture_manifest_sha256"] != sha256(GROUPS)
        or protocol["learning_manifest_sha256"] != sha256(MANIFEST)
    ):
        raise ValueError(
            "Held-out prediction requires a completed, unchanged validation selection"
        )
    spec, clips = load_clips(index, features, folds_to_open={"test"})
    if spec != protocol["spec"]:
        raise ValueError("Learning protocol changed after validation selection")
    if any(clip["encoder_runtime"] != protocol["encoder_runtime"] for clip in clips):
        raise ValueError(
            "Held-out encoder runtime differs from the frozen training inputs"
        )
    import torch

    model = create_model(spec).to(device)
    model.load_state_dict(
        torch.load(run / "selected.pt", map_location=device, weights_only=True),
        strict=True,
    )
    model.eval()
    with np.load(run / "normalization.npz", allow_pickle=False) as norm:
        mean, std = norm["mean"], norm["std"]
    predictions = {}
    for number, clip in enumerate(clips):
        logits = predict_clip(model, clip, spec, mean, std, device)
        predictions[clip["key"]] = spot_events(
            clip, logits, selected["threshold"], spec
        )
        progress((number + 1) / len(clips))
    result = {
        "metrics": event_metrics(clips, predictions, spec),
        "predictions": predictions,
        "selection_sha256": sha256(run / "selected.json"),
        "selected_weights_sha256": selected["weights_sha256"],
        "threshold": selected["threshold"],
        "installed_in_app": False,
        "scope": "AI CUP capture-context holdout, weak published contact/family/side/end references; singles only",
    }
    write_json(output, result)
    return {k: v for k, v in result.items() if k != "predictions"}
