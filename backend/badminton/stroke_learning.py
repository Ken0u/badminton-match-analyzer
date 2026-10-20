"""Portable reproduction of a fixed, weakly supervised development experiment.

This module never installs a model or reads test predictions. Input manifests
are data, not executable recipes. The CLI pins the real main workspace before
importing application configuration or admitting CPU training.
"""

import argparse
import hashlib
import io
import json
import os
import platform
import sys
from pathlib import Path, PurePosixPath

import numpy as np

from .datasets import integer, read_rows

FAMILIES = ("clear", "lift", "net", "drop", "smash", "drive", "other", "serve")
SIDES = ("forehand", "backhand")
PROTOCOL = {
    "schema_version": 1,
    "name": "observed-stroke-r3-development-reproduction-v1",
    "input_dim": 371,
    "source_commit": "c9168210e13f4869cbc8ebf47f9bc671b056cbab",
    "source_catalog_git_blob": "df71918b487c297aa1aa53edb57e369b283187d5",
    "source_labels": [
        {
            "match_id": 1,
            "set_id": 1,
            "path": "Match 001/label/set1.csv",
            "git_blob": "2f6b736f24a20ba8b3b8fe74500b061ac6ccbfed",
        },
        {
            "match_id": 1,
            "set_id": 2,
            "path": "Match 001/label/set2.csv",
            "git_blob": "197e6d145d464bf80a0590cc5f8a2fc10ba2c603",
        },
        {
            "match_id": 2,
            "set_id": 1,
            "path": "Match 002/label/set1.csv",
            "git_blob": "cc6c44f72719f7d3faeb3398617389591926a605",
        },
        {
            "match_id": 2,
            "set_id": 2,
            "path": "Match 002/label/set2.csv",
            "git_blob": "c990e694e1b26bc0461528b165ce20d0d1db44b9",
        },
    ],
    "source_plan_sha256": "6212563928e49b08e93ecf26e3699b606c2fbbb44155aa76451413a7d0cdef89",
    "feature_recipe_sha256": "76cba8529f2bc55ba8a17a6c34b5fc448292e7159006873ae99fefe3c1492506",
    "groups": {
        "train": {
            "match_id": 1,
            "source_id": "EpLD0HrwDJU",
            "clips": 67,
            "rows": 624,
            "available": 608,
        },
        "validation": {
            "match_id": 2,
            "source_id": "kbHgum5unYc",
            "clips": 67,
            "rows": 672,
            "available": 662,
        },
    },
    "training": {
        "seed": 20261018,
        "device": "cpu",
        "cpu_threads": 2,
        "hidden": [128, 64],
        "dropout": 0.1,
        "epochs": 300,
        "evaluate_every": 5,
        "batch_size": 64,
        "optimizer": "AdamW",
        "learning_rate": 0.001,
        "weight_decay": 0.01,
        "family_loss_weight": 1.0,
        "side_loss_weight": 0.5,
        "std_floor": 0.05,
        "normalized_clip": 10,
        "class_weights": "inverse sqrt training count, normalized over supported labels",
        "selection": "mean validation family macro F1 and side balanced recall; then joint accuracy; then earlier epoch",
        "threshold_grid": [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95],
        "minimum_threshold_support": 10,
        "family_threshold_precision": 0.8,
        "side_threshold_precision": 0.9,
        "disabled_threshold": 1.01,
    },
    "family_labels": list(FAMILIES),
    "side_labels": list(SIDES),
    "conditional_on": "Published weak source clock and hitter-foot association; not automatic contact or identity detection",
    "exact_truth": False,
    "model_installed_in_app": False,
    "test_policy": "No test inputs or predictions. The original holdout is consumed; test-informed changes require another complete-source holdout.",
    "terms": "S2Doubles has no license file at the pinned commit; do not redistribute source labels, features or derived weights as product assets.",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode("utf-8")


def read_json(data):
    def duplicate(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")

    return json.loads(data, object_pairs_hook=duplicate, parse_constant=invalid)


def inside(root, name):
    if not isinstance(name, str) or "\\" in name or ":" in name:
        raise ValueError("Input paths must be relative POSIX paths")
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("Input path escapes its root")
    result = (root / name).resolve()
    if not result.is_relative_to(root):
        raise ValueError("Input path escapes its root")
    return result


def seal(root, path):
    path = path.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Sealed input must be a file inside the input root")
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": digest(path.read_bytes()),
    }


def sealed_bytes(root, entry):
    if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
        raise ValueError("Invalid input seal")
    data = inside(root, entry["path"]).read_bytes()
    if digest(data) != entry["sha256"]:
        raise ValueError(f"Changed sealed input: {entry['path']}")
    return data


def publish(path, value):
    with path.open("xb") as handle:
        handle.write(encoded(value))


def expected_requests(plan):
    if plan["source_dataset_commit"] != PROTOCOL["source_commit"]:
        raise ValueError("Changed dataset source")
    groups = PROTOCOL["groups"]
    if (
        len({g["match_id"] for g in groups.values()}) != 2
        or len({g["source_id"] for g in groups.values()}) != 2
    ):
        raise ValueError("Original source groups overlap")
    result = []
    for split, group in groups.items():
        source = plan["sources"][str(group["match_id"])]
        if source["id"] != group["source_id"]:
            raise ValueError("Changed original source group")
        rows = [r for r in plan["clips"] if r["match_id"] == group["match_id"]]
        if len(rows) != group["clips"] or any(r["split"] != split for r in rows):
            raise ValueError("Incomplete or substituted split")
        result.extend((split, row) for row in rows)
    return result


def prepare(root, plan, features, source_catalog, protocol, target):
    """Seal existing development inputs; no downloads, helpers or model loads."""
    root, features = root.resolve(), features.resolve()
    manifest = {
        "schema_version": 1,
        "protocol": seal(root, protocol),
        "plan": seal(root, plan),
        "source_catalog": seal(root, source_catalog),
        "source_labels": {
            entry["path"]: seal(
                root, inside(source_catalog.parent.resolve(), entry["path"])
            )
            for entry in PROTOCOL["source_labels"]
        },
        "feature_recipe": seal(root, features / "recipe.json"),
        "clips": [],
    }
    requests = expected_requests(read_json(sealed_bytes(root, manifest["plan"])))
    for split, request in requests:
        stem = f"match{request['match_id']}-{request['score_key']}"
        path = inside(features, stem + ".json")
        manifest["clips"].append(
            {
                "split": split,
                "request": request,
                "metadata": seal(root, path),
                "features": seal(root, path.with_suffix(".npz")),
            }
        )
    raw = encoded(manifest)
    audit(root, raw, digest(raw))
    target.parent.mkdir(parents=True, exist_ok=True)
    publish(target, manifest)
    return {"manifest_sha256": digest(raw), "clips": len(manifest["clips"])}


def canonical_source_rows(root, entries):
    """Derive exact ordered IDs from original pinned development CSV bytes."""
    expected = {entry["path"]: entry for entry in PROTOCOL["source_labels"]}
    if not isinstance(entries, dict) or set(entries) != set(expected):
        raise ValueError("Incomplete original source label files")
    result = {}
    for name, description in expected.items():
        raw = sealed_bytes(root, entries[name])
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if blob != description["git_blob"]:
            raise ValueError("Changed original source labels")
        rows = read_rows(raw)
        if rows and not {"rally", "ball_round"}.issubset(rows[0]):
            raise ValueError("Original source labels lack identity columns")
        match, set_id = description["match_id"], description["set_id"]
        # Match normalize_set exactly, including its source data-row numbering.
        # Unselected flawed/unknown rows remain in the source; no evaluation
        # reference is removed or renumbered when constructing an included rally.
        for number, row in enumerate(rows, 2):
            rally, order = integer(row["rally"], 1), integer(row["ball_round"], 1)
            result.setdefault((match, set_id, rally), []).append(
                f"s2doubles:{match}:{set_id}:{rally}:{order}:{number}"
            )
    return result


def audit(root, raw, manifest_sha256):
    """Parse the exact hashed bytes, retaining every original reference row."""
    root = root.resolve()
    if digest(raw) != manifest_sha256:
        raise ValueError("Changed input manifest")
    manifest = read_json(raw)
    if manifest.get("schema_version") != 1 or set(manifest) != {
        "schema_version",
        "protocol",
        "plan",
        "source_catalog",
        "source_labels",
        "feature_recipe",
        "clips",
    }:
        raise ValueError("Unsupported input manifest")
    protocol_bytes = sealed_bytes(root, manifest["protocol"])
    if encoded(read_json(protocol_bytes)) != encoded(PROTOCOL):
        raise ValueError("Changed fixed protocol")
    plan_bytes = sealed_bytes(root, manifest["plan"])
    recipe_bytes = sealed_bytes(root, manifest["feature_recipe"])
    if (
        digest(plan_bytes) != PROTOCOL["source_plan_sha256"]
        or digest(recipe_bytes) != PROTOCOL["feature_recipe_sha256"]
    ):
        raise ValueError("Changed source or feature recipe")
    catalog = sealed_bytes(root, manifest["source_catalog"])
    if (
        hashlib.sha1(
            b"blob " + str(len(catalog)).encode() + b"\0" + catalog
        ).hexdigest()
        != PROTOCOL["source_catalog_git_blob"]
    ):
        raise ValueError("Changed original match catalog")
    requests = expected_requests(read_json(plan_bytes))
    canonical = canonical_source_rows(root, manifest["source_labels"])
    clips = manifest["clips"]
    if len(clips) != len(requests):
        raise ValueError("Incomplete clip list")
    chunks = {
        split: {key: [] for key in ("features", "available", "family", "side")}
        for split in PROTOCOL["groups"]
    }
    all_ids, all_paths, all_sources = set(), set(), {split: set() for split in chunks}
    seals = [
        manifest[key]
        for key in ("protocol", "plan", "source_catalog", "feature_recipe")
    ]
    seals.extend(manifest["source_labels"].values())
    for entry, (split, request) in zip(clips, requests):
        if (
            set(entry) != {"split", "request", "metadata", "features"}
            or entry["split"] != split
            or encoded(entry["request"]) != encoded(request)
        ):
            raise ValueError("Changed clip membership or ordering")
        for key in ("metadata", "features"):
            path = inside(root, entry[key]["path"])
            if path in all_paths:
                raise ValueError("Duplicate input file")
            all_paths.add(path)
            seals.append(entry[key])
        meta = read_json(sealed_bytes(root, entry["metadata"]))
        if (
            encoded(meta["request"]) != encoded(request)
            or meta.get("exact_truth") is not False
            or meta["features_sha256"] != entry["features"]["sha256"]
        ):
            raise ValueError("Changed clip provenance")
        source_hash = meta["source_sha256"]
        if (
            not isinstance(source_hash, str)
            or len(source_hash) != 64
            or any(c not in "0123456789abcdef" for c in source_hash)
        ):
            raise ValueError("Invalid source hash")
        all_sources[split].add(source_hash)
        with np.load(
            io.BytesIO(sealed_bytes(root, entry["features"])), allow_pickle=False
        ) as archive:
            if set(archive.files) != set(chunks[split]):
                raise ValueError("Unexpected feature arrays")
            values = {key: archive[key] for key in archive.files}
        x, available, family, side = [
            values[key] for key in ("features", "available", "family", "side")
        ]
        records = meta["records"]
        size = len(records)
        if size != request["published_strokes"]:
            raise ValueError("Incomplete source records for clip")
        expected_ids = canonical.get(
            (request["match_id"], request["set_id"], request["rally_id"]), []
        )
        if [record["id"] for record in records] != expected_ids:
            raise ValueError("Canonical source row identity or order mismatch")
        if (
            x.dtype != np.float32
            or x.shape != (size, PROTOCOL["input_dim"])
            or not np.isfinite(x).all()
            or available.dtype != np.bool_
            or any(v.shape != (size,) for v in (available, family, side))
        ):
            raise ValueError("Invalid feature shape, type or finite values")
        for target, labels, key in (
            (family, FAMILIES, "family_target"),
            (side, SIDES, "side_target"),
        ):
            if (
                target.dtype.kind not in "iu"
                or ((target < -1) | (target >= len(labels))).any()
            ):
                raise ValueError("Invalid target labels")
            expected = [
                labels.index(r[key]) if r[key] in labels else -1 for r in records
            ]
            if not np.array_equal(target, expected):
                raise ValueError("Targets disagree with source records")
        for index, record in enumerate(records):
            row_id = record["id"]
            if (
                not isinstance(row_id, str)
                or not row_id.startswith(
                    f"s2doubles:{request['match_id']}:{request['set_id']}:{request['rally_id']}:"
                )
                or row_id in all_ids
            ):
                raise ValueError("Duplicate or substituted row identity")
            all_ids.add(row_id)
            if (
                type(record["features_available"]) is not bool
                or record["features_available"] != bool(available[index])
                or record.get("exact_truth") is not False
            ):
                raise ValueError("Changed row availability or supervision")
        for key in values:
            chunks[split][key].append(values[key])
    if all_sources["train"] & all_sources["validation"]:
        raise ValueError("Source bytes overlap splits")
    result, counts = {}, {}
    for split, parts in chunks.items():
        data = {key: np.concatenate(value) for key, value in parts.items()}
        expected = PROTOCOL["groups"][split]
        if (
            len(data["features"]) != expected["rows"]
            or int(data["available"].sum()) != expected["available"]
        ):
            raise ValueError("Incomplete source rows or available inputs")
        counts[split] = {
            "clips": expected["clips"],
            "rows": len(data["available"]),
            "available": int(data["available"].sum()),
            "unknown_family": int((data["family"] < 0).sum()),
            "unknown_side": int((data["side"] < 0).sum()),
        }
        result[split] = data
    return result, {
        "manifest_sha256": manifest_sha256,
        "protocol_sha256": digest(protocol_bytes),
        "counts": counts,
        "seals": seals,
        "conditional_on": PROTOCOL["conditional_on"],
        "exact_truth": False,
        "model_installed_in_app": False,
    }


def class_metrics(truth, prediction, labels):
    from .recognition_evaluation import _confusion_metrics

    matrix = {name: dict.fromkeys((*labels, "unanswered"), 0) for name in labels}
    known = truth >= 0
    for target, predicted in zip(truth[known], prediction[known]):
        matrix[labels[target]][
            labels[predicted] if predicted >= 0 else "unanswered"
        ] += 1
    metrics = _confusion_metrics(matrix, labels)
    answered = known & (prediction >= 0)
    metrics.update(
        matrix=matrix,
        source_rows=int(known.sum()),
        answered=int(answered.sum()),
        precision_given_answered=float(np.mean(truth[answered] == prediction[answered]))
        if answered.any()
        else None,
        strict_accuracy=float(np.mean(truth[known] == prediction[known]))
        if known.any()
        else None,
    )
    metrics["balanced_recall"] = (
        float(
            np.mean(
                [
                    metrics["per_class"][name]["recall"]
                    for name in metrics["supported_classes"]
                ]
            )
        )
        if metrics["supported_classes"]
        else 0.0
    )
    return metrics


def evaluate(data, probabilities, thresholds=None):
    predictions = []
    for head, values in enumerate(probabilities):
        predicted = values.argmax(1)
        accepted = data["available"].copy()
        if thresholds is not None:
            accepted &= values.max(1) >= np.asarray(thresholds[head])[predicted]
        predicted[~accepted] = -1
        predictions.append(predicted)
    family, side = predictions
    eligible = (data["family"] >= 0) & (data["side"] >= 0)
    correct = eligible & (family == data["family"]) & (side == data["side"])
    return {
        "family": class_metrics(data["family"], family, FAMILIES),
        "side": class_metrics(data["side"], side, SIDES),
        "family_side_tuple_given_weak_source_hitter_clock": float(
            correct.sum() / max(1, eligible.sum())
        ),
        "available_rows": int(data["available"].sum()),
        "source_rows": len(family),
        "exact_truth": False,
    }


def select_thresholds(data, probabilities, config):
    thresholds, evidence = [], []
    for head, values in enumerate(probabilities):
        labels = FAMILIES if head == 0 else SIDES
        truth = data["family" if head == 0 else "side"]
        required = config[
            "family_threshold_precision" if head == 0 else "side_threshold_precision"
        ]
        predicted = values.argmax(1)
        limits, rows = [], []
        for label, name in enumerate(labels):
            candidates = []
            for threshold in config["threshold_grid"]:
                accepted = (
                    data["available"]
                    & (truth >= 0)
                    & (predicted == label)
                    & (values[:, label] >= threshold)
                )
                count = int(accepted.sum())
                precision = float(np.mean(truth[accepted] == label)) if count else 0.0
                if (
                    count >= config["minimum_threshold_support"]
                    and precision >= required
                ):
                    candidates.append((count, precision, threshold))
            chosen = max(candidates) if candidates else None
            limits.append(float(chosen[2]) if chosen else config["disabled_threshold"])
            rows.append(
                {
                    "label": name,
                    "threshold": limits[-1],
                    "validation_accepted": chosen[0] if chosen else 0,
                    "validation_precision": chosen[1] if chosen else None,
                    "enabled": chosen is not None,
                }
            )
        thresholds.append(limits)
        evidence.append(rows)
    return thresholds, evidence


def fit(train, validation, progress):
    """CPU only; each head learns from its own known training labels."""
    import torch
    from torch import nn

    config = PROTOCOL["training"]

    class Head(nn.Module):
        def __init__(self):
            super().__init__()
            self.shared = nn.Sequential(
                nn.Linear(PROTOCOL["input_dim"], 128),
                nn.ReLU(),
                nn.Dropout(config["dropout"]),
                nn.Linear(128, 64),
                nn.ReLU(),
            )
            self.family, self.side = nn.Linear(64, 8), nn.Linear(64, 2)

        def forward(self, values):
            hidden = self.shared(values)
            return self.family(hidden), self.side(hidden)

    available = train["available"]
    if not available.any():
        raise ValueError("No available training inputs")
    mean = train["features"][available].mean(0).astype(np.float32)
    std = np.maximum(train["features"][available].std(0), config["std_floor"]).astype(
        np.float32
    )
    value = torch.from_numpy(
        np.clip((train["features"][available] - mean) / std, -10, 10)
    )
    targets = [
        torch.from_numpy(train[key][available].astype(np.int64))
        for key in ("family", "side")
    ]
    weights, support = [], []
    for target, size in zip(targets, (8, 2)):
        known = target.numpy() >= 0
        counts = np.bincount(target.numpy()[known], minlength=size)
        present = counts > 0
        if not present.any():
            raise ValueError("No known training labels for one output")
        weight = np.zeros(size, np.float32)
        weight[present] = 1 / np.sqrt(counts[present])
        weight[present] /= weight[present].mean()
        weights.append(torch.from_numpy(weight))
        support.append(present)

    def probabilities(model, data):
        value = torch.from_numpy(np.clip((data["features"] - mean) / std, -10, 10))
        with torch.inference_mode():
            outputs = model(value)
            for head, logits in enumerate(outputs):
                logits[:, ~torch.from_numpy(support[head])] = -1e9
            return [logits.softmax(1).numpy() for logits in outputs]

    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(config["cpu_threads"])
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(config["seed"])
            rng = np.random.default_rng(config["seed"])
            model = Head()
            optimizer = torch.optim.AdamW(
                model.parameters(),
                lr=config["learning_rate"],
                weight_decay=config["weight_decay"],
            )
            history, best = [], None
            for epoch in range(1, config["epochs"] + 1):
                model.train()
                order, losses = rng.permutation(len(value)), []
                for start in range(0, len(order), config["batch_size"]):
                    index = order[start : start + config["batch_size"]]
                    outputs = model(value[index])
                    terms = []
                    for head, logits in enumerate(outputs):
                        target = targets[head][index]
                        known = target >= 0
                        if known.any():
                            coefficient = config[
                                "family_loss_weight"
                                if head == 0
                                else "side_loss_weight"
                            ]
                            terms.append(
                                coefficient
                                * nn.functional.cross_entropy(
                                    logits[known], target[known], weight=weights[head]
                                )
                            )
                    if not terms:
                        continue
                    loss = sum(terms)
                    optimizer.zero_grad()
                    loss.backward()
                    optimizer.step()
                    losses.append(float(loss.detach()))
                if epoch % config["evaluate_every"]:
                    continue
                model.eval()
                metrics = evaluate(validation, probabilities(model, validation))
                family_score = metrics["family"]["macro_f1_supported"]
                if family_score is None or not metrics["side"]["supported_classes"]:
                    raise ValueError(
                        "Validation selection needs known labels for both outputs"
                    )
                score = (family_score + metrics["side"]["balanced_recall"]) / 2
                key = (
                    score,
                    metrics["family_side_tuple_given_weak_source_hitter_clock"],
                )
                history.append(
                    {
                        "epoch": epoch,
                        "loss": float(np.mean(losses)),
                        "selection_score": score,
                        "validation": metrics,
                    }
                )
                if best is None or key > best["key"]:
                    best = {
                        "key": key,
                        "epoch": epoch,
                        "state": {
                            k: v.detach().clone() for k, v in model.state_dict().items()
                        },
                    }
                progress(epoch, best["epoch"])
            if best is None:
                raise ValueError("Training produced no selection checkpoint")
            model.load_state_dict(best["state"])
            model.eval()
            probabilities_ = probabilities(model, validation)
            thresholds, evidence = select_thresholds(validation, probabilities_, config)
            checkpoint = {
                "state_dict": best["state"],
                "mean": torch.from_numpy(mean),
                "std": torch.from_numpy(std),
                "supported_family": torch.from_numpy(support[0]),
                "supported_side": torch.from_numpy(support[1]),
                "thresholds": thresholds,
                "epoch": best["epoch"],
                "spec": PROTOCOL,
            }
            result = {
                "epoch": best["epoch"],
                "history": history,
                "thresholds": thresholds,
                "threshold_evidence": evidence,
                "closed_set": evaluate(validation, probabilities_),
                "with_abstention": evaluate(validation, probabilities_, thresholds),
                "training_available": int(available.sum()),
                "training_known": {
                    key: int((train[key][available] >= 0).sum())
                    for key in ("family", "side")
                },
                "test_opened": False,
                "model_installed_in_app": False,
            }
            return checkpoint, result
    finally:
        torch.set_num_threads(previous_threads)


def train(workspace, root, manifest_path, manifest_sha256, output):
    """Admit work in the real existing main Store, never a research catalog."""
    workspace, root, output = workspace.resolve(), root.resolve(), output.resolve()
    main_data = workspace / "data/processed"
    if (
        not (workspace / "AGENTS.md").is_file()
        or not (main_data / "catalog.sqlite3").is_file()
    ):
        raise ValueError("Explicit real workspace with existing main catalog required")
    if (
        not output.is_relative_to(workspace / ".cache")
        or output == workspace / ".cache"
    ):
        raise ValueError(
            "Training output must be a new ignored workspace cache lineage"
        )
    os.environ["BADMINTON_ROOT"] = str(workspace)
    os.environ["BADMINTON_DATA_DIR"] = str(main_data)
    # Reject an already-imported different configuration instead of pretending
    # environment changes can redirect existing Store users.
    from . import config

    if config.ROOT != workspace or config.DATA.resolve() != main_data:
        raise ValueError("Configuration was imported before real workspace pins")
    from .jobs import run_local_job
    from .storage import Store

    raw = manifest_path.read_bytes()
    data, inventory = audit(root, raw, manifest_sha256)
    paths = [
        manifest_path.resolve(),
        *(inside(root, e["path"]) for e in inventory["seals"]),
    ]
    if any(p.is_relative_to(output) for p in paths):
        raise ValueError("Output overlaps immutable input files")
    source_paths = [
        Path(__file__),
        Path(__file__).with_name("recognition_evaluation.py"),
        Path(__file__).with_name("evaluation.py"),
        Path(__file__).with_name("datasets.py"),
    ]
    code = {p.name: digest(p.read_bytes()) for p in source_paths}

    def stable():
        if digest(manifest_path.read_bytes()) != manifest_sha256:
            raise ValueError("Input manifest changed during execution")
        for entry in inventory["seals"]:
            sealed_bytes(root, entry)
        if any(digest(p.read_bytes()) != code[p.name] for p in source_paths):
            raise ValueError("Execution code changed during training")

    output.mkdir(parents=True, exist_ok=False)
    publish(
        output / "attempt.json",
        {
            "pid": os.getpid(),
            "workspace": str(workspace),
            "main_data": str(main_data),
            "manifest_sha256": manifest_sha256,
            "code_sha256": code,
        },
    )
    job_id = None

    def task(identifier, report_progress):
        nonlocal job_id
        import torch

        job_id = identifier
        stable()
        publish(output / "inventory.json", inventory)
        publish(output / "protocol.json", PROTOCOL)

        def progress(epoch, selected):
            stable()
            temporary = output / "progress.partial.json"
            publish(
                temporary,
                {"epoch": epoch, "selected_epoch": selected, "job_id": identifier},
            )
            temporary.replace(output / "progress.json")
            report_progress(epoch / PROTOCOL["training"]["epochs"])

        checkpoint, result = fit(data["train"], data["validation"], progress)
        stable()
        with (output / "selected.pt").open("xb") as handle:
            torch.save(checkpoint, handle)
        torch.load(output / "selected.pt", map_location="cpu", weights_only=True)
        result.update(
            model_sha256=digest((output / "selected.pt").read_bytes()),
            manifest_sha256=manifest_sha256,
            code_sha256=code,
            runtime={
                "python": platform.python_version(),
                "platform": platform.platform(),
                "numpy": np.__version__,
                "torch": torch.__version__,
                "device": "cpu",
            },
            job_id=identifier,
        )
        publish(output / "validation.json", result)
        return {
            "output": str(output),
            "selected_epoch": result["epoch"],
            "model_sha256": result["model_sha256"],
            "manifest_sha256": manifest_sha256,
            "test_opened": False,
        }

    result = run_local_job(Store(main_data), "side-training", None, task)
    # Publish completion only after the Store persisted completion and released
    # its actual shared admission, never from inside the training callback.
    publish(
        output / "completed.json",
        {**result, "job_id": job_id, "main_data": str(main_data)},
    )
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser(
        "prepare", help="Seal original development-only inputs"
    )
    for name in ("root", "plan", "features", "source-catalog", "protocol", "output"):
        prepare_parser.add_argument("--" + name, type=Path, required=True)
    audit_parser = commands.add_parser("audit", help="Validate a frozen input manifest")
    train_parser = commands.add_parser(
        "train", help="Reproduce the frozen CPU development run"
    )
    for command in (audit_parser, train_parser):
        command.add_argument("--root", type=Path, required=True)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--manifest-sha256", required=True)
    train_parser.add_argument("--workspace", type=Path, required=True)
    train_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        result = prepare(
            args.root,
            args.plan,
            args.features,
            args.source_catalog,
            args.protocol,
            args.output,
        )
    elif args.command == "audit":
        _, result = audit(args.root, args.manifest.read_bytes(), args.manifest_sha256)
        result.pop("seals")
    else:
        result = train(
            args.workspace, args.root, args.manifest, args.manifest_sha256, args.output
        )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main(sys.argv[1:])
