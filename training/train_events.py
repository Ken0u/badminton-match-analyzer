"""Train one temporal model for contacts, hitter, stroke, side and serve type.

Input is the per-clip feature files written by extract_aicup.py and, when
given, extract_shuttleset.py. The model reads the whole rally (players' poses
plus shuttle track) and predicts, for every frame, whether a racket contact
happens there and, if so, who hit it, which stroke family it was,
forehand/backhand and, for a serve, short or long.

AI CUP clips are split by capture venue (aicup_capture_groups_v1.json) and
ShuttleSet rallies by whole match (the published split). Test venues and
matches are never used for training or model selection and are only scored
when --final is passed.

ShuttleSet adds stroke types AI CUP does not label separately: the block (a
soft return of a smash or drive to the net), push, net kill, cross-court net
shot and wrist smash. An AI CUP label therefore accepts any of the finer
classes it may contain (see AICUP_ACCEPTS). ShuttleSet hit frames are hand-entered and sit a
couple of frames before the contact, so with --teacher each one is moved to
the nearest contact an earlier checkpoint finds.

    python training/train_events.py --features /data/features \
        --shuttleset /data/shuttleset/features --teacher /data/model_v2/events.pt \
        --output /data/model_v3
    python training/train_events.py --features ... --shuttleset ... --output ... --final
"""

import argparse
import gzip
import json
import math
import random
from pathlib import Path

import numpy as np
import torch
from badminton.event_model import (
    COURT_ENDS,
    FAMILIES,
    FEATURES,
    PLAYER,
    SERVES,
    SIDES,
    TRAINED_FPS,
    clip_inputs,
    observations,
    resample,
    with_motion,
)
from badminton.event_network import EventModel
from torch import nn

FAMILY = {name: index for index, name in enumerate(FAMILIES)}
# AI CUP ball types: 1/2 short and long serve, 9 the combined push/net kill.
AICUP_FAMILY = {
    1: "serve",
    2: "serve",
    3: "clear",
    4: "drive",
    5: "smash",
    6: "net",
    7: "drop",
    8: "lift",
    9: "other",
}
SERVE_TYPE = {1: 0, 2: 1}
# ShuttleSet stroke types, by the importer's English names.
SHUTTLESET_FAMILY = {
    "short service": "serve",
    "long service": "serve",
    "net shot": "net",
    "cross-court net shot": "cross-court net",
    "return net": "block",
    "smash": "smash",
    "lob": "lift",
    "defensive return lob": "lift",
    "clear": "clear",
    "drive": "drive",
    "driven flight": "drive",
    "back-court drive": "drive",
    "defensive return drive": "drive",
    "drop": "drop",
    "passive drop": "drop",
    "push": "push",
    "rush": "net kill",
    "wrist smash": "wrist smash",
}
# Finer classes an AI CUP label may contain; its "other" is push or net kill.
AICUP_ACCEPTS = {
    "net": ("block", "cross-court net"),
    "smash": ("wrist smash",),
    "other": ("push", "net kill"),
}
# The earlier, coarser classes, for comparison with earlier checkpoints.
COARSE = {
    "push": "other",
    "net kill": "other",
    "wrist smash": "other",
    "cross-court net": "net",
}
HEADS = ("hitter", "family", "side", "serve")
REQUESTED = ("clear", "drive", "smash", "net", "drop", "lift", "block")
FINE = tuple(name for name in FAMILIES if name not in ("serve", "other"))
# Published ShuttleSet hit frames precede the detected contact by about this.
SHUTTLESET_LEAD_S = 0.08
SNAP_S = 0.2
# COCO keypoint left/right pairs, swapped when a clip is mirrored.
MIRROR = [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15]
GROUPS = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "badminton"
    / "aicup_capture_groups_v1.json"
)


def accepted(family, either=()):
    """Family target as the set of classes that count as correct."""
    mask = np.zeros(len(FAMILIES), np.float32)
    if family is not None:
        mask[[FAMILY[name] for name in (family, *either)]] = 1
    return mask


def aicup_clip(document):
    """Per-frame inputs and hits for one AI CUP rally clip."""
    width, height = document["video"]["width"], document["video"]["height"]
    inputs = clip_inputs(document["players"], document["shuttle"], width, height)
    hits = []
    for label in document["labels"]:
        try:
            frame = int(label["HitFrame"])
            code = int(label["BallType"])
            family = AICUP_FAMILY[code]
            side = {1: 1, 2: 0}[int(label["Backhand"])]
            hitter = {"A": 0, "B": 1}[label["Hitter"]]
        except (KeyError, ValueError):
            continue
        if 0 <= frame < len(inputs):
            mask = accepted(family, AICUP_ACCEPTS.get(family, ()))
            hits.append(
                (frame, hitter, FAMILY[family], side, SERVE_TYPE.get(code, -1), mask)
            )
    return inputs, hits


def shuttleset_clip(document):
    """Inputs on the trained frame rate and hits for one ShuttleSet rally."""
    width, height = document["video"]["width"], document["video"]["height"]
    rows = document["players"]
    if np.mean([bool(r.get("calibration_valid")) for r in rows]) < 0.5:
        return None, []
    values, _ = observations(rows, document["shuttle"], width, height)
    times = np.array([r["time_s"] for r in rows])
    if abs(float(document["video"]["fps"]) - TRAINED_FPS) > 0.5:
        values, _ = resample(values, times)
    inputs = with_motion(values)
    hits = []
    for event in document["events"]:
        if not 0 <= event["frame"] < len(times):
            continue
        moment = times[event["frame"]] - times[0] + SHUTTLESET_LEAD_S
        frame = min(len(inputs) - 1, round(moment * TRAINED_FPS))
        family = (
            SHUTTLESET_FAMILY.get(event["source_type"]) if event["usable"] else None
        )
        hits.append(
            (
                frame,
                COURT_ENDS.index(event["court_end"]) if event["court_end"] else -1,
                FAMILY[family] if family else -1,
                SIDES.index(event["side"]) if event["side"] in SIDES else -1,
                SERVES.index(event["serve_type"])
                if event["serve_type"] in SERVES
                else -1,
                accepted(family),
            )
        )
    return inputs, hits


def snap(items, teacher, device):
    """Move ShuttleSet hits onto the contacts an earlier checkpoint finds."""
    saved = torch.load(teacher, map_location=device, weights_only=True)
    model = EventModel(families=len(saved.get("families", FAMILIES[:8]))).to(device)
    model.load_state_dict(saved["state"], strict=False)
    model.eval()
    reach = round(SNAP_S * TRAINED_FPS)
    moved = total = 0
    snapped = []
    with torch.no_grad():
        for clip_id, inputs, hits in items:
            out = model(torch.from_numpy(inputs)[None].to(device))
            found = peaks(
                torch.sigmoid(out["hit"][0, :, 0]).cpu().numpy(), saved["threshold"]
            )
            used, result = set(), []
            for frame, *labels in hits:
                options = [
                    f for f in found if f not in used and abs(f - frame) <= reach
                ]
                total += 1
                if options:
                    frame = min(options, key=lambda f: abs(f - frame))
                    used.add(frame)
                    moved += 1
                result.append((frame, *labels))
            snapped.append((clip_id, inputs, result))
    print(f"teacher placed {moved} of {total} ShuttleSet hits", flush=True)
    return snapped


def load(features, folds, shuttleset=None):
    data = {"train": [], "validation": [], "test": []}
    for path in sorted(Path(features).glob("*.json.gz")):
        clip_id = path.name.split(".")[0]
        fold = folds.get(clip_id)
        if fold is None:
            continue
        with gzip.open(path, "rt", encoding="utf-8") as source:
            inputs, hits = aicup_clip(json.load(source))
        if hits:
            data[fold].append((clip_id, inputs, hits))
    extra = {"train": [], "validation": [], "test": []}
    if shuttleset:
        for path in sorted(Path(shuttleset).glob("ss-*.json.gz")):
            with gzip.open(path, "rt", encoding="utf-8") as source:
                document = json.load(source)
            inputs, hits = shuttleset_clip(document)
            if hits and document["split"] in extra:
                extra[document["split"]].append((document["clip_id"], inputs, hits))
    return data, extra


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
    classes = np.full((len(items), length, len(HEADS)), -1, np.int64)
    accept = np.zeros((len(items), length, len(FAMILIES)), np.float32)
    for row, (_, inputs, hits) in enumerate(items):
        if augment and random.random() < 0.5:
            inputs = mirror(inputs)
        x[row, : len(inputs)] = inputs
        valid[row, : len(inputs)] = 1
        for frame, *labels, mask in hits:
            for offset, weight in ((-2, 0.3), (-1, 0.8), (0, 1), (1, 0.8), (2, 0.3)):
                if 0 <= frame + offset < len(inputs):
                    hit[row, frame + offset] = max(hit[row, frame + offset], weight)
            for offset in (-1, 0, 1):
                if 0 <= frame + offset < len(inputs):
                    classes[row, frame + offset] = labels
                    accept[row, frame + offset] = mask
    return (torch.from_numpy(a).to(device) for a in (x, hit, valid, classes, accept))


def loss_fn(outputs, hit, valid, classes, accept, weights):
    contact = nn.functional.binary_cross_entropy_with_logits(
        outputs["hit"].squeeze(-1),
        hit,
        pos_weight=torch.tensor(8.0, device=hit.device),
        reduction="none",
    )
    total = (contact * valid).sum() / valid.sum()
    for index, name in enumerate(HEADS):
        target = classes[..., index]
        mask = target >= 0
        if not mask.any():
            continue
        if name == "family":
            # Probability of any accepted class, weighted by the labelled one.
            chosen = torch.logsumexp(
                outputs[name][mask].float().log_softmax(-1)
                + torch.log(accept[mask].clamp_min(1e-12)),
                -1,
            )
            scale = weights[name][target[mask]]
            total = total + 0.5 * -(chosen * scale).sum() / scale.sum()
        else:
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
                **{k: out[k][0].argmax(-1).cpu().numpy() for k in HEADS},
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


def coarse(index):
    return FAMILY[COARSE.get(FAMILIES[index], FAMILIES[index])]


def balanced(pairs, count):
    rates = [
        np.mean([p == s for t, p in pairs if t == s])
        for s in range(count)
        if any(t == s for t, _ in pairs)
    ]
    return float(np.mean(rates)) if rates else float("nan")


def score(items, predictions, threshold, tolerance):
    tp = fp = fn = complete = 0
    hitters, families, sides, serves = [], [], [], []
    for (_, _, hits), predicted in zip(items, predictions):
        frames = peaks(predicted["hit"], threshold)
        used = set()
        for frame, hitter, family, side, serve, mask in hits:
            options = [
                f for f in frames if f not in used and abs(f - frame) <= tolerance
            ]
            if not options:
                fn += 1
                continue
            best = min(options, key=lambda f: abs(f - frame))
            used.add(best)
            tp += 1
            guess = {k: int(predicted[k][best]) for k in HEADS}
            # A prediction inside the accepted set counts as the labelled class.
            if family >= 0 and mask[guess["family"]]:
                guess["family"] = family
            if hitter >= 0:
                hitters.append((hitter, guess["hitter"]))
            if family >= 0:
                families.append((family, guess["family"]))
            if side >= 0:
                sides.append((side, guess["side"]))
            if serve >= 0:
                serves.append((serve, guess["serve"]))
            complete += all(
                true < 0 or true == guess[name]
                for name, true in (
                    ("hitter", hitter),
                    ("family", family),
                    ("side", side),
                )
            )
        fp += len(frames) - len(used)
    f1 = lambda hit: 2 * hit / max(1, 2 * tp + fp + fn)  # noqa: E731
    return {
        "tolerance_frames": tolerance,
        "contacts": tp + fn,
        "contact_precision": tp / max(1, tp + fp),
        "contact_recall": tp / max(1, tp + fn),
        "contact_f1": f1(tp),
        "hitter_accuracy_on_matched": float(np.mean([t == p for t, p in hitters]))
        if hitters
        else float("nan"),
        "family_macro_f1_on_matched": macro_f1(
            families, [FAMILY[name] for name in FINE]
        ),
        "coarse_family_macro_f1_on_matched": macro_f1(
            [(coarse(t), coarse(p)) for t, p in families],
            [FAMILY[name] for name in REQUESTED],
        ),
        "side_balanced_accuracy_on_matched": balanced(sides, len(SIDES)),
        "serves_matched": len(serves),
        "serve_type_balanced_accuracy_on_matched": balanced(serves, len(SERVES)),
        "family_recall_on_matched": {
            name: float(np.mean([p == index for t, p in families if t == index]))
            for index, name in enumerate(FAMILIES)
            if any(t == index for t, _ in families)
        },
        "family_precision_on_matched": {
            name: float(np.mean([t == index for t, p in families if p == index]))
            for index, name in enumerate(FAMILIES)
            if any(p == index for _, p in families)
        },
        # Strict end-to-end: right time, hitter, family and side together.
        "complete_event_f1": f1(complete),
    }


def class_weights(items, device):
    counts = {"family": np.ones(len(FAMILIES)), "side": np.ones(len(SIDES))}
    for _, _, hits in items:
        for _, _, family, side, _, _ in hits:
            if family >= 0:
                counts["family"][family] += 1
            if side >= 0:
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
    parser.add_argument("--shuttleset", type=Path, help="ShuttleSet feature folder")
    parser.add_argument(
        "--teacher", type=Path, help="checkpoint that places ShuttleSet hit frames"
    )
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
    data, extra = load(args.features, folds, args.shuttleset)
    if args.teacher:
        extra = {
            fold: snap(items, args.teacher, device) for fold, items in extra.items()
        }
    print(
        {k: len(v) for k, v in data.items()},
        "AI CUP clips,",
        {k: len(v) for k, v in extra.items()},
        "ShuttleSet rallies on",
        device,
        flush=True,
    )
    train = data["train"] + extra["train"]
    args.output.mkdir(parents=True, exist_ok=True)
    checkpoint = args.output / "events.pt"

    def evaluate(model, fold, threshold, tolerance):
        """AI CUP and ShuttleSet are scored apart: their labels differ in kind."""
        result = {}
        for name, items in (("aicup", data[fold]), ("shuttleset", extra[fold])):
            if items:
                result[name] = score(
                    items, predict(model, items, device), threshold, tolerance
                )
        return result

    if not args.final:
        model = EventModel().to(device)
        weights = class_weights(train, device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-2)
        steps = args.epochs * math.ceil(len(train) / args.batch_size)
        schedule = torch.optim.lr_scheduler.OneCycleLR(
            optimizer, 2e-3, total_steps=steps
        )
        best, history = -1, []
        for epoch in range(1, args.epochs + 1):
            model.train()
            order = random.sample(train, len(train))
            losses = []
            for start in range(0, len(order), args.batch_size):
                x, hit, valid, classes, accept = batch(
                    order[start : start + args.batch_size], device, augment=True
                )
                x = x + 0.003 * torch.randn_like(x) * (x != 0)
                loss = loss_fn(model(x), hit, valid, classes, accept, weights)
                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1)
                optimizer.step()
                schedule.step()
                losses.append(loss.item())
            if epoch % 5 == 0 or epoch == args.epochs:
                options = []
                for threshold in (0.3, 0.4, 0.5, 0.6, 0.7):
                    result = evaluate(model, "validation", threshold, 2)
                    mean = float(
                        np.mean([r["complete_event_f1"] for r in result.values()])
                    )
                    options.append((mean, threshold, result))
                mean, threshold, result = max(options, key=lambda o: o[0])
                history.append(
                    {
                        "epoch": epoch,
                        "loss": float(np.mean(losses)),
                        "threshold": threshold,
                        "selection_score": mean,
                        **result,
                    }
                )
                print(
                    json.dumps(
                        {
                            "epoch": epoch,
                            "loss": round(float(np.mean(losses)), 4),
                            "threshold": threshold,
                            "selection_score": round(mean, 4),
                            **{
                                name: {
                                    key: round(value[key], 3)
                                    for key in (
                                        "contact_f1",
                                        "family_macro_f1_on_matched",
                                        "coarse_family_macro_f1_on_matched",
                                        "complete_event_f1",
                                    )
                                }
                                for name, value in result.items()
                            },
                        }
                    ),
                    flush=True,
                )
                if mean > best:
                    best = mean
                    torch.save(
                        {
                            "state": model.state_dict(),
                            "threshold": threshold,
                            "epoch": epoch,
                            "families": FAMILIES,
                            "serves": SERVES,
                            "features": FEATURES,
                        },
                        checkpoint,
                    )
        (args.output / "history.json").write_text(json.dumps(history, indent=1))

    saved = torch.load(checkpoint, map_location=device, weights_only=True)
    model = EventModel(families=len(saved["families"])).to(device)
    model.load_state_dict(saved["state"])
    report = {"epoch": saved["epoch"], "threshold": saved["threshold"]}
    for fold in ("validation", "test") if args.final else ("validation",):
        report[fold] = [
            evaluate(model, fold, saved["threshold"], tolerance) for tolerance in (2, 4)
        ]
    name = "final_report.json" if args.final else "validation_report.json"
    (args.output / name).write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
