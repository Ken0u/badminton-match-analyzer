"""Train the rally outcome model and compare it with the rule.

Examples come from the extracted rally feature files (see
training/rally_outcome_features.py): the labelled last stroke, the last
hitter's labelled court end, the app's shuttle and player tracks, and the
dataset's court corners. Each example is described by
rally_outcomes.outcome_features after rally_outcomes.find_landing, exactly as
the pipeline's outcomes stage does it; the target is one of winner_in (the
last hitter won), error_out or error_net (net, failed return and faults).

Train on four fifths of the training matches, choose the epoch on the other
fifth, and report rule and model on the validation matches. Test matches are
not read.

    python training/train_rally_outcome.py --features F1 F2 ... \
        --cache .cache/step3/outcome_examples.jsonl \
        --output .cache/step3/rally_outcome_v1.json
"""

import argparse
import itertools
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import rally_outcome_features
from badminton import rally_outcomes as R


def target(label):
    if label["reason"] == "winner":
        return 0
    if label["reason"] == "error":
        return 1 if label["detail"] == "out" else 2
    return None


def build(folders, cache):
    if cache and cache.is_file():
        return [
            json.loads(line) for line in cache.read_text(encoding="utf-8").splitlines()
        ]
    rows = []
    for example in rally_outcome_features.examples(folders):
        if example["split"] not in ("train", "validation"):
            continue
        label, line = example["label"], example["timeline"]
        if label["last_hitter_end"] is None or target(label) is None:
            continue
        mode = "singles" if example["dataset"] == "shuttleset" else "doubles"
        matrix = example["homography"]
        # Training rallies also at +-2 frames: the app's contacts are not
        # exactly on the labelled frame.
        offsets = (0, -2, 2) if example["split"] == "train" else (0,)
        for offset in offsets:
            after = label["last_hit_frame"] - line["start_frame"] + offset
            if not 0 <= after < len(line["times"]):
                continue
            landing = R.find_landing(
                line["times"],
                line["shuttle"],
                after,
                len(line["times"]),
                line["aspect"],
                lambda i: matrix,
            )
            features = R.outcome_features(
                line["times"],
                line["shuttle"],
                line["players"],
                after,
                landing,
                label["last_hitter_end"],
                mode,
                line["aspect"],
                example["last_type"],
            )
            rule = R.rule_outcome(label["last_hitter_end"], landing, mode)
            rows.append(
                {
                    "name": example["name"],
                    "offset": offset,
                    "dataset": example["dataset"],
                    "match_id": example["match_id"],
                    "split": example["split"],
                    "features": features,
                    "target": target(label),
                    "rule": None if rule is None else rule["detail"],
                    "landing": None
                    if landing is None or landing["court"] is None
                    else list(landing["court"]),
                    "landing_kind": None if landing is None else landing["kind"],
                    "landing_label": label["landing"],
                }
            )
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return rows


RULE_CLASS = {"in": 0, "out": 1, "net": 2, None: 2}


def scores(rows, predicted):
    truth = np.array([r["target"] for r in rows])
    predicted = np.asarray(predicted)
    return {
        "n": len(rows),
        "winner": round(float(np.mean((truth == 0) == (predicted == 0))), 3),
        "class": round(float(np.mean(truth == predicted)), 3),
        "confusion": dict(
            Counter(f"{R.CLASSES[t]}->{R.CLASSES[p]}" for t, p in zip(truth, predicted))
        ),
    }


def train(rows, valid, hidden, epochs, seed, lr=3e-3, decay=1e-3):
    import torch

    torch.manual_seed(seed)
    x = np.array([r["features"] for r in rows], float)
    mean, scale = x.mean(0), x.std(0) + 1e-6

    def to(rs):
        values = (np.array([r["features"] for r in rs]) - mean) / scale
        return torch.tensor(values, dtype=torch.float32)

    xt, yt = to(rows), torch.tensor([r["target"] for r in rows])
    xv, yv = to(valid), torch.tensor([r["target"] for r in valid])
    sizes = [x.shape[1], *hidden, len(R.CLASSES)]
    layers = []
    for a, b in itertools.pairwise(sizes):
        layers += [torch.nn.Linear(a, b), torch.nn.ReLU()]
    net = torch.nn.Sequential(*layers[:-1])
    optimizer = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=decay)
    loss = torch.nn.CrossEntropyLoss()
    best = (1e9, None, 0)
    for epoch in range(epochs):
        net.train()
        order = torch.randperm(len(xt))
        for start in range(0, len(xt), 128):
            batch = order[start : start + 128]
            optimizer.zero_grad()
            value = loss(net(xt[batch]), yt[batch])
            value.backward()
            optimizer.step()
        net.eval()
        with torch.no_grad():
            v = float(loss(net(xv), yv))
        if v < best[0]:
            best = (v, {k: t.clone() for k, t in net.state_dict().items()}, epoch)
    net.load_state_dict(best[1])
    linear = [m for m in net if isinstance(m, torch.nn.Linear)]
    document = {
        "name": "rally outcome mlp v1",
        "features": list(R.FEATURES),
        "classes": list(R.CLASSES),
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "layers": [
            [m.weight.detach().numpy().T.tolist(), m.bias.detach().numpy().tolist()]
            for m in linear
        ],
        "hidden": list(hidden),
        "best_epoch": best[2],
        # Loss on the epoch-choice fold (training matches), not validation.
        "validation_loss": round(best[0], 4),
        "seed": seed,
    }
    return document


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, nargs="+", required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hidden", type=int, nargs="*", default=[32, 32])
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--sweep", action="store_true", help="try sizes and seeds, keep the best"
    )
    args = parser.parse_args()
    rows = build(args.features, args.cache)
    # The epoch is chosen on a fifth of the training matches; validation
    # matches only compare the finished model with the rule.
    picking = [
        r
        for r in rows
        if r["split"] == "train" and r["match_id"] % 5 == 0 and r["offset"] == 0
    ]
    trainset = [r for r in rows if r["split"] == "train" and r["match_id"] % 5 != 0]
    valid = [r for r in rows if r["split"] == "validation"]
    print(
        f"{len(trainset)} training, {len(picking)} epoch-choice, {len(valid)} validation rallies"
    )
    # Several sizes and seeds; the one with the lowest epoch-choice loss is
    # kept. Validation is not used to choose.
    candidates = [
        train(trainset, picking, hidden, args.epochs, seed)
        for hidden in ([args.hidden] if not args.sweep else ([16], [32, 32], [64, 64]))
        for seed in ([args.seed] if not args.sweep else (0, 1, 2))
    ]
    for c in candidates:
        print("candidate", c["hidden"], c["seed"], c["best_epoch"], c["validation_loss"])
    document = min(candidates, key=lambda c: c["validation_loss"])
    model = R.OutcomeModel(document)
    report = {
        "model": {
            k: document[k] for k in ("hidden", "best_epoch", "validation_loss", "seed")
        }
    }
    for dataset in ("shuttleset", "dshuttlenet"):
        part = [r for r in valid if r["dataset"] == dataset]
        if not part:
            continue
        report[dataset] = {
            "rule": scores(part, [RULE_CLASS[r["rule"]] for r in part]),
            "model": scores(
                part, [int(np.argmax(model.probabilities(r["features"]))) for r in part]
            ),
            "prior_hitter_loses": scores(part, [2] * len(part)),
        }
    document["validation"] = report
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
