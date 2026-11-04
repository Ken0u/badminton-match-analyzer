"""One frozen development-only stroke capacity comparison; never app training."""

import argparse
import copy
import math
import os
import platform
import time
from pathlib import Path

import numpy as np
import psutil

from . import stroke_learning as learning

PROTOCOL = {
    "schema_version": 1,
    "name": "observed-stroke-capacity-development-v1",
    "input_manifest_sha256": "0bea5f55f6ba402ca7665bb0d2d4bb8eaa903d0593ebc76870cf8901035bd059",
    "baseline_source_sha256": "745de9212ef0ecf41d47b9ad96426c46741b330e462783baecdcc5c46c700932",
    "input_dim": 371,
    "training": copy.deepcopy(learning.PROTOCOL["training"]),
    "variants": {
        "baseline_mlp": {"hidden": [128, 64], "parameters": 56522},
        "linear": {"hidden": [], "parameters": 3720},
    },
    "order": ["baseline_mlp", "linear"],
    "selection": "Within each variant: mean validation supported eight-group family macro F1 and side balanced recall, then strict family/side accuracy, then earlier epoch. Report both variants; retain baseline on a cross-variant tie.",
    "maximum_real_fits": 2,
    "maximum_runtime_seconds": 14400,
    "maximum_output_bytes": 1073741824,
    "source_groups": copy.deepcopy(learning.PROTOCOL["groups"]),
    "conditional_on": learning.PROTOCOL["conditional_on"],
    "limitations": [
        "One weakly supervised training match and one validation match; one seed.",
        "All consumed test sources remain unopened; a fresh original-source holdout is required for test-informed changes.",
        "Class sparsity and unavailable inputs remain in original denominators.",
        "Capacity ablation cannot establish overfitting, unseen accuracy, complete events or persistent identities.",
        "Upstream perception pretraining overlap is unresolved.",
        "S2Doubles has no license file at the pinned commit; labels, features and derived weights remain private research assets.",
    ],
    "model_installed_in_app": False,
    "exact_truth": False,
}

CODE_FILES = (
    "stroke_capacity.py",
    "stroke_learning.py",
    "recognition_evaluation.py",
    "evaluation.py",
    "datasets.py",
    "jobs.py",
    "storage.py",
    "config.py",
)


def code_seals():
    return {
        name: learning.digest(Path(__file__).with_name(name).read_bytes())
        for name in CODE_FILES
    }


def runtime():
    import torch

    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "torch": str(torch.__version__),
        "device": "cpu",
    }


def check_deadline(deadline):
    if not math.isfinite(deadline) or time.time() >= deadline:
        raise ValueError("Scientific runtime deadline expired or invalid")


def freeze(root, manifest, manifest_sha256, protocol, deadline, output):
    """Audit original development inputs before committing a prospective freeze."""
    root, manifest, protocol = root.resolve(), manifest.resolve(), protocol.resolve()
    check_deadline(deadline)
    if deadline - time.time() > PROTOCOL["maximum_runtime_seconds"]:
        raise ValueError("Deadline exceeds the bounded runtime")
    raw = manifest.read_bytes()
    if manifest_sha256 != PROTOCOL["input_manifest_sha256"]:
        raise ValueError("Changed fixed development manifest")
    _, inventory = learning.audit(root, raw, manifest_sha256)
    protocol_raw = protocol.read_bytes()
    if learning.encoded(learning.read_json(protocol_raw)) != learning.encoded(PROTOCOL):
        raise ValueError("Changed fixed capacity protocol")
    code = code_seals()
    if code["stroke_learning.py"] != PROTOCOL["baseline_source_sha256"]:
        raise ValueError("Changed fixed baseline source")
    if PROTOCOL["training"] != learning.PROTOCOL["training"]:
        raise ValueError("Changed fixed baseline training parameters")
    # Freeze files are new immutable artifacts, never executable launchers.
    value = {
        "schema_version": 1,
        "manifest": learning.seal(root, manifest),
        "protocol": learning.seal(root, protocol),
        "inventory": inventory,
        "code_sha256": code,
        "runtime": runtime(),
        "deadline": deadline,
        "test_opened": False,
        "model_installed_in_app": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    protected = [
        manifest,
        protocol,
        *(learning.inside(root, e["path"]) for e in inventory["seals"]),
    ]
    if output.resolve() in protected:
        raise ValueError("Freeze would overwrite immutable inputs")
    learning.publish(output, value)
    return {"freeze_sha256": learning.digest(output.read_bytes())}


def fit_linear(train, validation, progress):
    """CPU only; each head learns from its own known training labels."""
    import torch
    from torch import nn

    config = PROTOCOL["training"]

    class Head(nn.Module):
        def __init__(self):
            super().__init__()
            self.family = nn.Linear(PROTOCOL["input_dim"], 8)
            self.side = nn.Linear(PROTOCOL["input_dim"], 2)

        def forward(self, values):
            return self.family(values), self.side(values)

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
                metrics = learning.evaluate(
                    validation, probabilities(model, validation)
                )
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
            thresholds, evidence = learning.select_thresholds(
                validation, probabilities_, config
            )
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
                "closed_set": learning.evaluate(validation, probabilities_),
                "with_abstention": learning.evaluate(
                    validation, probabilities_, thresholds
                ),
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


def summary(result, parameter_count):
    """Report strict source denominators alongside conditional classifier scores."""
    metrics = result["closed_set"]
    family = metrics["family"]
    requested = {name: family["per_class"][name] for name in learning.FAMILIES[:6]}
    supported = [row["f1"] for row in requested.values() if row["support"]]
    eligible = result["validation_known_joint"]
    return {
        "parameters": parameter_count,
        "selected_epoch": result["epoch"],
        "selection_score": (
            family["macro_f1_supported"] + metrics["side"]["balanced_recall"]
        )
        / 2,
        "family_macro_f1_eight_groups": family["macro_f1_supported"],
        "requested_family_macro_f1_supported": float(np.mean(supported))
        if supported
        else None,
        "requested_family_support_and_metrics": requested,
        "side_balanced_recall": metrics["side"]["balanced_recall"],
        "strict_family_side_accuracy": metrics[
            "family_side_tuple_given_weak_source_hitter_clock"
        ],
        "validation_source_rows": metrics["source_rows"],
        "validation_available_rows": metrics["available_rows"],
        "validation_known_joint": eligible,
        "unknown_family": result["validation_unknown_family"],
        "unknown_side": result["validation_unknown_side"],
        "family_answered_with_abstention": result["with_abstention"]["family"][
            "answered"
        ],
        "side_answered_with_abstention": result["with_abstention"]["side"]["answered"],
        "strict_family_side_accuracy_with_abstention": result["with_abstention"][
            "family_side_tuple_given_weak_source_hitter_clock"
        ],
    }


def compare(results):
    values = {
        name: summary(results[name], PROTOCOL["variants"][name]["parameters"])
        for name in PROTOCOL["order"]
    }

    def key(name):
        return (
            values[name]["selection_score"],
            values[name]["strict_family_side_accuracy"],
        )

    preferred = max(PROTOCOL["order"], key=key)
    return {
        "variants": values,
        "validation_preferred_variant": preferred,
        "preference_is_development_only": True,
        "test_opened": False,
        "model_installed_in_app": False,
        "exact_truth": False,
        "limitations": PROTOCOL["limitations"],
    }


def run(workspace, root, frozen_path, frozen_sha256, output):
    """Admit both fits together in the existing main Store, preserving old work."""
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
        raise ValueError("Output must be a new ignored workspace cache lineage")
    raw = frozen_path.read_bytes()
    if learning.digest(raw) != frozen_sha256:
        raise ValueError("Changed prospective freeze")
    frozen = learning.read_json(raw)
    check_deadline(frozen["deadline"])
    if frozen["runtime"] != runtime() or frozen["code_sha256"] != code_seals():
        raise ValueError("Changed frozen consumer or runtime")
    protocol = learning.sealed_bytes(root, frozen["protocol"])
    if learning.encoded(learning.read_json(protocol)) != learning.encoded(PROTOCOL):
        raise ValueError("Changed fixed capacity protocol")
    manifest = frozen["manifest"]
    if manifest["sha256"] != PROTOCOL["input_manifest_sha256"]:
        raise ValueError("Changed fixed development manifest")
    data, inventory = learning.audit(
        root, learning.sealed_bytes(root, manifest), manifest["sha256"]
    )
    if inventory != frozen["inventory"]:
        raise ValueError("Changed frozen input inventory")
    protected = [
        frozen_path.resolve(),
        learning.inside(root, manifest["path"]),
        learning.inside(root, frozen["protocol"]["path"]),
    ]
    protected += [learning.inside(root, e["path"]) for e in inventory["seals"]]
    if any(path.is_relative_to(output) for path in protected):
        raise ValueError("Output overlaps immutable inputs")
    os.environ["BADMINTON_ROOT"] = str(workspace)
    os.environ["BADMINTON_DATA_DIR"] = str(main_data)
    from . import config

    if config.ROOT != workspace or config.DATA.resolve() != main_data:
        raise ValueError("Configuration was imported before real workspace pins")
    from .jobs import run_local_job
    from .storage import Store

    def stable():
        check_deadline(frozen["deadline"])
        if learning.digest(frozen_path.read_bytes()) != frozen_sha256:
            raise ValueError("Prospective freeze changed during execution")
        learning.sealed_bytes(root, frozen["protocol"])
        learning.sealed_bytes(root, manifest)
        for entry in inventory["seals"]:
            learning.sealed_bytes(root, entry)
        if code_seals() != frozen["code_sha256"]:
            raise ValueError("Execution code changed during training")
        if (
            sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
            > PROTOCOL["maximum_output_bytes"]
        ):
            raise ValueError("Output allowance exceeded")

    output.mkdir(parents=True, exist_ok=False)
    process = psutil.Process()
    learning.publish(
        output / "attempt.json",
        {
            "pid": process.pid,
            "creation_time": process.create_time(),
            "cwd": process.cwd(),
            "command": process.cmdline(),
            "workspace": str(workspace),
            "main_data": str(main_data),
            "freeze_sha256": frozen_sha256,
        },
    )
    job_id = None

    def task(identifier, report_progress):
        nonlocal job_id
        import torch

        job_id = identifier
        stable()
        learning.publish(output / "inventory.json", inventory)
        learning.publish(output / "protocol.json", PROTOCOL)
        results = {}
        for index, name in enumerate(PROTOCOL["order"]):
            stable()
            target = output / name
            target.mkdir(exist_ok=False)

            def progress(epoch, selected):
                stable()
                temporary = target / "progress.partial.json"
                learning.publish(
                    temporary,
                    {"epoch": epoch, "selected_epoch": selected, "job_id": identifier},
                )
                temporary.replace(target / "progress.json")
                report_progress((index + epoch / PROTOCOL["training"]["epochs"]) / 2)

            fit = learning.fit if name == "baseline_mlp" else fit_linear
            checkpoint, result = fit(data["train"], data["validation"], progress)
            stable()
            count = sum(value.numel() for value in checkpoint["state_dict"].values())
            if count != PROTOCOL["variants"][name]["parameters"]:
                raise ValueError("Unexpected classifier parameter count")
            with (target / "selected.pt").open("xb") as handle:
                torch.save(checkpoint, handle)
            torch.load(target / "selected.pt", map_location="cpu", weights_only=True)
            validation = data["validation"]
            result.update(
                validation_known_joint=int(
                    ((validation["family"] >= 0) & (validation["side"] >= 0)).sum()
                ),
                validation_unknown_family=int((validation["family"] < 0).sum()),
                validation_unknown_side=int((validation["side"] < 0).sum()),
                parameters=count,
                runtime=frozen["runtime"],
                model_sha256=learning.digest((target / "selected.pt").read_bytes()),
                freeze_sha256=frozen_sha256,
                job_id=identifier,
            )
            learning.publish(target / "validation.json", result)
            results[name] = result
        comparison = compare(results)
        stable()
        learning.publish(output / "comparison.json", comparison)
        return {
            "job_id": identifier,
            "freeze_sha256": frozen_sha256,
            "validation_preferred_variant": comparison["validation_preferred_variant"],
            "test_opened": False,
            "model_installed_in_app": False,
        }

    result = run_local_job(Store(main_data), "side-training", None, task)
    stable()
    learning.publish(
        output / "completed.json",
        {**result, "job_id": job_id, "main_data": str(main_data)},
    )
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("freeze")
    for name in ("root", "manifest", "protocol", "output"):
        prepare.add_argument("--" + name, type=Path, required=True)
    prepare.add_argument("--manifest-sha256", required=True)
    prepare.add_argument("--deadline", type=float, required=True)
    train = commands.add_parser("run")
    for name in ("workspace", "root", "freeze", "output"):
        train.add_argument("--" + name, type=Path, required=True)
    train.add_argument("--freeze-sha256", required=True)
    args = parser.parse_args(argv)
    if args.command == "freeze":
        result = freeze(
            args.root,
            args.manifest,
            args.manifest_sha256,
            args.protocol,
            args.deadline,
            args.output,
        )
    else:
        result = run(
            args.workspace, args.root, args.freeze, args.freeze_sha256, args.output
        )
    print(learning.encoded(result).decode("utf-8"), end="")


if __name__ == "__main__":
    main()
