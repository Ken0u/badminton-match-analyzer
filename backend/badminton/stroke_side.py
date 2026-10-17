"""Experimental stroke side from a frozen BST descriptor and hitter court end."""

import io
import json
import platform
import re
from pathlib import Path

import numpy as np

from .config import MODEL_MANIFEST, WEIGHTS
from .training_features import file_sha, training_recipe


def make_side_head():
    from torch import nn

    return nn.Sequential(
        nn.Linear(302, 128), nn.GELU(), nn.Dropout(0.1), nn.Linear(128, 2)
    )


def forward_with_descriptor(model, *inputs):
    """Capture the frozen 300-value descriptor without changing family logits."""
    captured = []
    hook = model.mlp_head.register_forward_pre_hook(
        lambda _module, values: captured.append(values[0])
    )
    try:
        logits = model(*inputs)
        if len(captured) != 1 or captured[0].shape[-1] != 300:
            raise ValueError(
                "Stroke-side model requires the BST-0 300-value descriptor"
            )
        return logits, captured[0]
    finally:
        hook.remove()


def load_side_predictor(device, *, weights=WEIGHTS, use_packaged=True):
    """A missing optional model keeps side unknown; corrupt/incompatible assets fail."""
    import torch

    root = Path(weights)
    packaged = False
    path, metadata_path = root / "stroke_side_v1.pt", root / "stroke_side_v1.json"
    if use_packaged and not path.exists() and not metadata_path.exists():
        root = Path(__file__).with_name("assets")
        packaged = True
        path, metadata_path = root / "stroke_side_v1.pt", root / "stroke_side_v1.json"
    if not path.exists() and not metadata_path.exists():
        return None
    if not metadata_path.is_file():
        raise RuntimeError(
            "Stroke-side weights/metadata are incomplete; rerun scripts/train_stroke_side.py"
        )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    name = metadata.get("weights_name", "stroke_side_v1.pt")
    if not re.fullmatch(r"stroke_side_v1(?:-[0-9a-f]{12,64})?\.pt", name):
        raise RuntimeError("Stroke-side metadata contains an invalid checkpoint name")
    path = root / name
    if not path.is_file():
        raise RuntimeError(
            "Stroke-side checkpoint is missing; retrain or restore its weights"
        )
    recipe = training_recipe()
    if (
        packaged
        and metadata["checkpoint_sha256"]
        != json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))["stroke_side"][
            "sha256"
        ]
    ):
        raise RuntimeError(
            "Packaged stroke-side model does not match the model inventory"
        )
    if (
        metadata["recipe"] != recipe
        or metadata["base_checkpoint_sha256"] != recipe["base_checkpoint_sha256"]
        or file_sha(path) != metadata["checkpoint_sha256"]
    ):
        raise RuntimeError(
            "Stroke-side checkpoint/recipe hash does not match its training metadata"
        )
    data = torch.load(path, map_location="cpu", weights_only=True)
    mean, std = data["mean"], data["std"]
    if (
        mean.shape != (302,)
        or std.shape != (302,)
        or not torch.isfinite(mean).all()
        or not torch.isfinite(std).all()
        or (std <= 0).any()
    ):
        raise RuntimeError(
            "Stroke-side normalization must contain finite positive scales"
        )
    model = make_side_head()
    model.load_state_dict(data["state_dict"], strict=True)
    return {
        "model": model.to(device).eval(),
        "mean": mean.to(device),
        "std": std.to(device),
        "metadata": metadata,
    }


def predict_side(predictor, descriptor, court_end):
    import torch

    if predictor is None:
        return {"side": "unknown", "side_status": "not_available"}
    if court_end not in ("far", "near"):
        return {
            "side": "unknown",
            "side_status": "abstained",
            "side_reason": "Hitter court end is unresolved",
        }
    if descriptor.shape != (1, 300) or not torch.isfinite(descriptor).all():
        raise ValueError("Stroke-side inference requires one finite BST-0 descriptor")
    end = torch.tensor(
        [[1.0, 0.0]] if court_end == "far" else [[0.0, 1.0]], device=descriptor.device
    )
    features = torch.cat((descriptor, end), dim=1)
    with torch.inference_mode():
        probabilities = (
            predictor["model"]((features - predictor["mean"]) / predictor["std"])
            .softmax(dim=1)[0]
            .cpu()
            .numpy()
        )
    label, score = int(probabilities.argmax()), float(probabilities.max())
    if not np.isfinite(probabilities).all():
        raise RuntimeError("Stroke-side model returned nonfinite probabilities")
    recipe = predictor["metadata"]["recipe"]
    accepted = score >= recipe["threshold"]
    return {
        "side": recipe["labels"][label] if accepted else "unknown",
        "side_status": "predicted" if accepted else "abstained",
        "side_score": score,
        "side_probabilities": dict(
            zip(recipe["labels"], probabilities.astype(float).tolist(), strict=True)
        ),
        "side_reason": "Experimental MMPose-to-YOLO transfer; verify hitter and stroke mechanics",
    }


def training_arrays(directory, *, recipe=None):
    """Validate provenance, finite values, class order, and match-disjoint splits."""
    recipe = recipe or training_recipe()
    root = Path(directory)
    metadata = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if (
        metadata["recipe"] != recipe
        or file_sha(root / "descriptors.npz") != metadata["array_sha256"]
    ):
        raise ValueError("Descriptor cache does not match its training recipe/hash")
    with np.load(root / "descriptors.npz", allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    features, labels = arrays["features"], arrays["labels"]
    if (
        features.ndim != 2
        or features.shape[1] != recipe["feature_dim"]
        or features.dtype.kind not in "fi"
        or not np.isfinite(features).all()
        or labels.shape != (len(features),)
        or labels.dtype.kind not in "iu"
        or not np.isin(labels, [0, 1]).all()
    ):
        raise ValueError(
            "Side training requires finite aligned binary descriptor arrays"
        )
    if (
        metadata["label_index_sha256"] != recipe["label_index_sha256"]
        or not np.isin(features[:, -2:], [0, 1]).all()
        or not np.all(features[:, -2:].sum(axis=1) == 1)
    ):
        raise ValueError(
            "Side descriptors require pinned labels and one known hitter end"
        )
    if any(len(v) != len(features) for v in arrays.values()) or len(
        set(arrays["record_ids"].tolist())
    ) != len(features):
        raise ValueError("Every training descriptor requires one unique source label")
    from .datasets import pinned_source

    frozen = pinned_source()["splits"]
    for split in ("train", "validation", "test"):
        mask = arrays["splits"] == split
        if not mask.any() or not set(arrays["matches"][mask].tolist()).issubset(
            frozen[split]
        ):
            raise ValueError(
                "Descriptor matches must stay in their frozen source split"
            )
        if split != "test" and len(np.unique(labels[mask])) != 2:
            raise ValueError("Both stroke sides need train and validation support")
    if not np.isin(arrays["splits"], ["train", "validation", "test"]).all():
        raise ValueError("Unknown descriptor split")
    return arrays, metadata


def side_metrics(labels, probabilities, threshold=0.8):
    labels, values = np.asarray(labels), np.asarray(probabilities)
    if not np.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Side score threshold must be finite and within zero to one")
    if (
        values.shape != (len(labels), 2)
        or not np.isfinite(values).all()
        or np.any(values < 0)
        or not np.allclose(values.sum(axis=1), 1, atol=1e-5)
        or not np.isin(labels, [0, 1]).all()
    ):
        raise ValueError("Side metrics need finite normalized binary probabilities")
    predicted = values.argmax(axis=1)
    accepted = values.max(axis=1) >= threshold
    confusion = np.zeros((2, 2), dtype=np.int64)
    for truth, guess in zip(labels, predicted, strict=True):
        confusion[int(truth), int(guess)] += 1
    supports = confusion.sum(axis=1)
    recalls = [
        float(confusion[i, i] / supports[i]) if supports[i] else None for i in (0, 1)
    ]
    strict = [
        float(np.sum(accepted & (labels == i) & (predicted == i)) / supports[i])
        if supports[i]
        else None
        for i in (0, 1)
    ]
    return {
        "count": len(labels),
        "labels": ["forehand", "backhand"],
        "confusion": confusion.tolist(),
        "support": supports.tolist(),
        "recall": recalls,
        "accuracy": float((predicted == labels).mean()) if len(labels) else None,
        "balanced_accuracy": sum(recalls) / 2
        if all(r is not None for r in recalls)
        else None,
        "threshold": threshold,
        "answered_count": int(accepted.sum()),
        "coverage": float(accepted.mean()) if len(labels) else None,
        "accuracy_of_answered": float((predicted[accepted] == labels[accepted]).mean())
        if accepted.any()
        else None,
        "balanced_recall_counting_abstentions_as_misses": sum(strict) / 2
        if all(r is not None for r in strict)
        else None,
        "score_meaning": "uncalibrated two-class softmax mass, not verified correctness probability",
    }


def normalization_from_training(features, mask):
    values = np.asarray(features, dtype=np.float32)[mask]
    if not len(values) or not np.isfinite(values).all():
        raise ValueError("Training normalization requires finite train-only rows")
    mean = values.mean(axis=0, dtype=np.float64).astype(np.float32)
    std = values.std(axis=0, dtype=np.float64).astype(np.float32)
    return mean, np.where(std > 1e-6, std, 1).astype(np.float32)


def train_side_head(
    descriptors, output, progress=print, *, recipe=None, report_progress=None
):
    import torch

    from .video import write_json

    recipe = recipe or training_recipe()
    arrays, source = training_arrays(descriptors, recipe=recipe)
    torch.manual_seed(recipe["seed"])
    np.random.seed(recipe["seed"])
    torch.set_num_threads(4)
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    masks = {
        split: arrays["splits"] == split for split in ("train", "validation", "test")
    }
    mean, std = normalization_from_training(arrays["features"], masks["train"])
    x = torch.from_numpy((arrays["features"] - mean) / std).float().to(device)
    y = torch.from_numpy(arrays["labels"]).long().to(device)
    train = torch.from_numpy(np.flatnonzero(masks["train"])).to(device)
    val = torch.from_numpy(np.flatnonzero(masks["validation"])).to(device)
    model = make_side_head().to(device)
    counts = np.bincount(arrays["labels"][masks["train"]], minlength=2)
    weights = torch.tensor(
        len(train) / (2 * counts), dtype=torch.float32, device=device
    )
    loss_fn = torch.nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=recipe["learning_rate"], weight_decay=1e-3
    )
    best, best_state, best_epoch = None, None, None
    history = []
    try:
        for epoch in range(recipe["epochs"]):
            model.train()
            order = train[torch.randperm(len(train), device=device)]
            for indices in order.split(recipe["batch_size"]):
                optimizer.zero_grad(set_to_none=True)
                loss = loss_fn(model(x[indices]), y[indices])
                loss.backward()
                optimizer.step()
            model.eval()
            with torch.inference_mode():
                logits = model(x[val])
                probabilities = logits.softmax(dim=1).cpu().numpy()
                validation_loss = float(loss_fn(logits, y[val]).cpu())
            metrics = side_metrics(
                arrays["labels"][masks["validation"]],
                probabilities,
                recipe["threshold"],
            )
            criterion = (metrics["balanced_accuracy"], -validation_loss)
            history.append(
                {
                    "epoch": epoch + 1,
                    "validation_balanced_accuracy": criterion[0],
                    "validation_loss": validation_loss,
                }
            )
            if best is None or criterion > best:
                best, best_epoch = criterion, epoch + 1
                best_state = {
                    name: value.detach().cpu().clone()
                    for name, value in model.state_dict().items()
                }
            progress(
                f"Side epoch {epoch + 1}: validation balanced accuracy {criterion[0]:.4f}; best epoch {best_epoch}"
            )
            if report_progress:
                report_progress(0.95 * (epoch + 1) / recipe["epochs"])
            if epoch + 1 - best_epoch >= recipe["patience"]:
                break
        model.load_state_dict(best_state, strict=True)
        model.eval()
        evaluations = {}
        probability_arrays = {}
        # Test is used only after weights/epoch are frozen by validation selection.
        with torch.inference_mode():
            for split in ("validation", "test"):
                indices = torch.from_numpy(np.flatnonzero(masks[split])).to(device)
                probabilities = model(x[indices]).softmax(dim=1).cpu().numpy()
                probability_arrays[split] = probabilities
                evaluations[split] = side_metrics(
                    arrays["labels"][masks[split]], probabilities, recipe["threshold"]
                )
        baseline = {}
        for split in ("validation", "test"):
            labels = arrays["labels"][masks[split]]
            guesses = np.full(len(labels), int(counts.argmax()))
            baseline[split] = {
                "training_majority": side_metrics(
                    labels, np.eye(2)[guesses], recipe["threshold"]
                )
            }
            family_guesses = {}
            for family in recipe["target_families"]:
                selected = masks["train"] & (arrays["families"] == family)
                family_guesses[family] = int(
                    np.bincount(arrays["labels"][selected], minlength=2).argmax()
                )
            guesses = np.asarray(
                [family_guesses[f] for f in arrays["families"][masks[split]]]
            )
            baseline[split]["training_family_majority_with_gold_family"] = side_metrics(
                labels, np.eye(2)[guesses], recipe["threshold"]
            )
        per_match = {}
        per_family = {}
        test_matches = arrays["matches"][masks["test"]]
        test_families = arrays["families"][masks["test"]]
        test_labels = arrays["labels"][masks["test"]]
        for match in np.unique(test_matches):
            selected = test_matches == match
            per_match[str(match)] = side_metrics(
                test_labels[selected],
                probability_arrays["test"][selected],
                recipe["threshold"],
            )
        for family in recipe["target_families"]:
            selected = test_families == family
            per_family[family] = side_metrics(
                test_labels[selected],
                probability_arrays["test"][selected],
                recipe["threshold"],
            )
        destination = Path(output)
        destination.mkdir(parents=True, exist_ok=True)
        serialized = io.BytesIO()
        torch.save(
            {
                "state_dict": best_state,
                "mean": torch.from_numpy(mean),
                "std": torch.from_numpy(std),
            },
            serialized,
        )
        from hashlib import sha256

        raw = serialized.getvalue()
        checksum = sha256(raw).hexdigest()
        weights_path = destination / f"stroke_side_v1-{checksum[:16]}.pt"
        if not weights_path.exists():
            temporary = weights_path.with_suffix(".tmp")
            temporary.write_bytes(raw)
            temporary.replace(weights_path)
        report = {
            "schema_version": 1,
            "architecture": "BST-0 frozen 300-value descriptor + hitter end; MLP 302/128/2",
            "checkpoint_sha256": checksum,
            "weights_name": weights_path.name,
            "base_checkpoint_sha256": recipe["base_checkpoint_sha256"],
            "recipe": recipe,
            "descriptor_cache_sha256": source["array_sha256"],
            "label_index_sha256": source["label_index_sha256"],
            "device": device,
            "environment": {
                "torch": str(torch.__version__),
                "cuda": torch.version.cuda,
                "numpy": np.__version__,
                "python": platform.python_version(),
                "device": torch.cuda.get_device_name(device)
                if device.startswith("cuda")
                else "cpu",
            },
            "selected_epoch": best_epoch,
            "history": history,
            "test_used_for_selection": False,
            "split_counts": source["split_counts"],
            "validation": evaluations["validation"],
            "test": evaluations["test"],
            "baselines": baseline,
            "test_per_match": per_match,
            "test_per_family": per_family,
            "meaning": "Published MMPose inputs and known hitter court end; runtime YOLO transfer and full-video accuracy remain unvalidated",
        }
        write_json(destination / "stroke_side_v1.json", report)
        np.savez_compressed(
            destination / "side-evaluation-predictions.npz", **probability_arrays
        )
        if report_progress:
            report_progress(1)
        return report
    finally:
        del model, x, y
        if device.startswith("cuda"):
            torch.cuda.empty_cache()
