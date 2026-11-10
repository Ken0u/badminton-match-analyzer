"""Train one temporal model for contacts, hitter, stroke family and side.

Input is the per-clip feature files written by extract_aicup.py. The model
reads the whole rally (players' poses plus shuttle track) and predicts, for
every frame, whether a racket contact happens there and, if so, who hit it,
which stroke family it was and forehand/backhand.

Clips are split by capture venue (aicup_capture_groups_v1.json): the test
venues are never used for training or model selection and are only scored
when --final is passed.

    python training/train_events.py --features /data/work/features --output /data/work/model
    python training/train_events.py --features ... --output ... --final
"""

import argparse
import gzip
import json
import math
import random
from pathlib import Path

import numpy as np
import torch
from badminton.event_model import FAMILIES, FEATURES, PLAYER, SIDES, clip_inputs
from badminton.event_network import EventModel
from torch import nn

BALL_TYPE = {1: 0, 2: 0, 3: 1, 4: 2, 5: 3, 6: 4, 7: 5, 8: 6, 9: 7}
REQUESTED = ("clear", "drive", "smash", "net", "drop", "lift")
# COCO keypoint left/right pairs, swapped when a clip is mirrored.
MIRROR = [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15]
GROUPS = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "badminton"
    / "aicup_capture_groups_v1.json"
)


def clip_arrays(document):
    """Per-frame inputs and targets for one rally clip."""
    width, height = document["video"]["width"], document["video"]["height"]
    inputs = clip_inputs(document["players"], document["shuttle"], width, height)
    count = len(inputs)
    hits = []
    for label in document["labels"]:
        try:
            frame = int(label["HitFrame"])
            family = BALL_TYPE[int(label["BallType"])]
            side = {1: 1, 2: 0}[int(label["Backhand"])]
            hitter = {"A": 0, "B": 1}[label["Hitter"]]
        except (KeyError, ValueError):
            continue
        if 0 <= frame < count:
            hits.append((frame, hitter, family, side))
    return inputs, hits


def load(features, folds):
    data = {"train": [], "validation": [], "test": []}
    for path in sorted(Path(features).glob("*.json.gz")):
        clip_id = path.name.split(".")[0]
        fold = folds.get(clip_id)
        if fold is None:
            continue
        with gzip.open(path, "rt", encoding="utf-8") as source:
            inputs, hits = clip_arrays(json.load(source))
        if hits:
            data[fold].append((clip_id, inputs, hits))
    return data


def mirror(inputs):
    out = inputs.copy()
    for start in (0, PLAYER):
        block = out[:, start : start + PLAYER]
        present = block[:, 55:56]
        points = block[:, :51].reshape(-1, 17, 3)[:, MIRROR].copy()
        points[:, :, 0] = (1 - points[:, :, 0]) * (points[:, :, 2] > 0)
        block[:, :51] = points.reshape(-1, 51)
        x1, x2 = block[:, 51].copy(), block[:, 53].copy()
        block[:, 51], block[:, 53] = (1 - x2) * present[:, 0], (1 - x1) * present[:, 0]
    tail = out[:, 2 * PLAYER :]
    tail[:, 0] = (1 - tail[:, 0]) * tail[:, 2]
    tail[:, 3] = -tail[:, 3]
    return out


def batch(items, device, augment=False):
    length = max(len(inputs) for _, inputs, _ in items)
    x = np.zeros((len(items), length, FEATURES), np.float32)
    hit = np.zeros((len(items), length), np.float32)
    valid = np.zeros((len(items), length), np.float32)
    classes = np.full((len(items), length, 3), -1, np.int64)
    for row, (_, inputs, hits) in enumerate(items):
        if augment and random.random() < 0.5:
            inputs = mirror(inputs)
        x[row, : len(inputs)] = inputs
        valid[row, : len(inputs)] = 1
        for frame, hitter, family, side in hits:
            for offset, weight in ((-2, 0.3), (-1, 0.8), (0, 1), (1, 0.8), (2, 0.3)):
                if 0 <= frame + offset < len(inputs):
                    hit[row, frame + offset] = max(hit[row, frame + offset], weight)
            for offset in (-1, 0, 1):
                if 0 <= frame + offset < len(inputs):
                    classes[row, frame + offset] = (hitter, family, side)
    return (torch.from_numpy(a).to(device) for a in (x, hit, valid, classes))


def loss_fn(outputs, hit, valid, classes, weights):
    contact = nn.functional.binary_cross_entropy_with_logits(
        outputs["hit"].squeeze(-1),
        hit,
        pos_weight=torch.tensor(8.0, device=hit.device),
        reduction="none",
    )
    total = (contact * valid).sum() / valid.sum()
    for index, name in enumerate(("hitter", "family", "side")):
        target = classes[..., index]
        mask = target >= 0
        if mask.any():
            total = total + 0.5 * nn.functional.cross_entropy(
                outputs[name][mask], target[mask], weight=weights.get(name)
            )
    return total


def peaks(probability, threshold, radius=4):
    found = []
    for index in np.argsort(-probability):
        if probability[index] < threshold:
            break
        if all(abs(index - other) > radius for other in found):
            found.append(int(index))
    return sorted(found)


@torch.no_grad()
def predict(model, items, device):
    model.eval()
    results = []
    for item in items:
        x, *_ = batch([item], device)
        out = model(x)
        results.append(
            {
                "hit": torch.sigmoid(out["hit"][0, :, 0]).cpu().numpy(),
                **{
                    k: out[k][0].argmax(-1).cpu().numpy()
                    for k in ("hitter", "family", "side")
                },
            }
        )
    return results


def macro_f1(pairs, labels):
    scores = []
    for label in labels:
        tp = sum(t == label and p == label for t, p in pairs)
        fp = sum(t != label and p == label for t, p in pairs)
        fn = sum(t == label and p != label for t, p in pairs)
        if tp + fn:
            scores.append(2 * tp / max(1, 2 * tp + fp + fn))
    return float(np.mean(scores)) if scores else float("nan")


def score(items, predictions, threshold, tolerance):
    tp = fp = fn = complete = 0
    hitters, families, sides = [], [], []
    for (_, _, hits), predicted in zip(items, predictions):
        frames = peaks(predicted["hit"], threshold)
        used = set()
        for frame, hitter, family, side in hits:
            options = [
                f for f in frames if f not in used and abs(f - frame) <= tolerance
            ]
            if not options:
                fn += 1
                continue
            best = min(options, key=lambda f: abs(f - frame))
            used.add(best)
            tp += 1
            guess = tuple(int(predicted[k][best]) for k in ("hitter", "family", "side"))
            hitters.append((hitter, guess[0]))
            families.append((family, guess[1]))
            sides.append((side, guess[2]))
            complete += guess == (hitter, family, side)
        fp += len(frames) - len(used)
    f1 = lambda hit: 2 * hit / max(1, 2 * tp + fp + fn)  # noqa: E731
    requested = [FAMILIES.index(name) for name in REQUESTED]
    return {
        "tolerance_frames": tolerance,
        "contacts": tp + fn,
        "contact_precision": tp / max(1, tp + fp),
        "contact_recall": tp / max(1, tp + fn),
        "contact_f1": f1(tp),
        "hitter_accuracy_on_matched": float(np.mean([t == p for t, p in hitters]))
        if hitters
        else float("nan"),
        "family_macro_f1_six_on_matched": macro_f1(families, requested),
        "side_balanced_accuracy_on_matched": float(
            np.mean(
                [
                    np.mean([p == s for t, p in sides if t == s])
                    for s in (0, 1)
                    if any(t == s for t, _ in sides)
                ]
            )
        )
        if sides
        else float("nan"),
        # Strict end-to-end: right time, hitter, family and side together.
        "complete_event_f1": f1(complete),
    }


def class_weights(items, device):
    counts = {"family": np.ones(len(FAMILIES)), "side": np.ones(len(SIDES))}
    for _, _, hits in items:
        for _, _, family, side in hits:
            counts["family"][family] += 1
            counts["side"][side] += 1
    return {
        name: torch.tensor(
            (value.sum() / value / len(value)) ** 0.5, dtype=torch.float32
        ).to(device)
        for name, value in counts.items()
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--final", action="store_true", help="score the held-out test venues"
    )
    args = parser.parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    groups = json.loads(GROUPS.read_text(encoding="utf-8"))["source_groups"]
    folds = {
        member.split(":")[1]: group["fold"]
        for group in groups
        for member in group["members"]
        if member.startswith("train:")
    }
    data = load(args.features, folds)
    print({k: len(v) for k, v in data.items()}, "clips on", device, flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    checkpoint = args.output / "events.pt"

    if not args.final:
        model = EventModel().to(device)
        weights = class_weights(data["train"], device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-2)
        steps = args.epochs * math.ceil(len(data["train"]) / args.batch_size)
        schedule = torch.optim.lr_scheduler.OneCycleLR(
            optimizer, 2e-3, total_steps=steps
        )
        best, history = -1, []
        for epoch in range(1, args.epochs + 1):
            model.train()
            order = random.sample(data["train"], len(data["train"]))
            losses = []
            for start in range(0, len(order), args.batch_size):
                x, hit, valid, classes = batch(
                    order[start : start + args.batch_size], device, augment=True
                )
                x = x + 0.003 * torch.randn_like(x) * (x != 0)
                loss = loss_fn(model(x), hit, valid, classes, weights)
                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1)
                optimizer.step()
                schedule.step()
                losses.append(loss.item())
            if epoch % 5 == 0 or epoch == args.epochs:
                predictions = predict(model, data["validation"], device)
                options = [
                    (score(data["validation"], predictions, t, 2), t)
                    for t in (0.3, 0.4, 0.5, 0.6, 0.7)
                ]
                result, threshold = max(
                    options, key=lambda o: o[0]["complete_event_f1"]
                )
                history.append(
                    {
                        "epoch": epoch,
                        "loss": float(np.mean(losses)),
                        "threshold": threshold,
                        **result,
                    }
                )
                print(json.dumps(history[-1]), flush=True)
                if result["complete_event_f1"] > best:
                    best = result["complete_event_f1"]
                    torch.save(
                        {
                            "state": model.state_dict(),
                            "threshold": threshold,
                            "epoch": epoch,
                            "families": FAMILIES,
                            "features": FEATURES,
                        },
                        checkpoint,
                    )
        (args.output / "history.json").write_text(json.dumps(history, indent=1))

    saved = torch.load(checkpoint, map_location=device, weights_only=True)
    model = EventModel().to(device)
    model.load_state_dict(saved["state"])
    report = {"epoch": saved["epoch"], "threshold": saved["threshold"]}
    for fold in ("validation", "test") if args.final else ("validation",):
        predictions = predict(model, data[fold], device)
        report[fold] = [
            score(data[fold], predictions, saved["threshold"], tolerance)
            for tolerance in (2, 4)
        ]
    name = "final_report.json" if args.final else "validation_report.json"
    (args.output / name).write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
