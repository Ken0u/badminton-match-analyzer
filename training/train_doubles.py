"""Train the four-player event model for doubles.

Input is the per-rally feature files written by extract_s2doubles.py and,
optionally, the singles features train_events.py uses. The network is the
singles one with four player slots (two far, two near; see
badminton/event_doubles.py) and a hitter output that names a slot.

S2 Doubles is three matches from one tournament and one camera: match 1 is
trained on, match 2 chooses the model and match 3 is only scored with --final.
That is too little to learn strokes from, so the model can first be trained
on singles laid out in the four slots (one partner slot per end left empty)
and then continued on doubles:

    python training/train_doubles.py --singles-only --features /data/features \
        --shuttleset /data/shuttleset/features --teacher /data/model_v2/events.pt \
        --doubles /data/s2doubles/features --output /data/doubles_pre
    python training/train_doubles.py --doubles /data/s2doubles/features \
        --init /data/doubles_pre/events.pt --lr 5e-4 --output /data/doubles_v1

Each published stroke names its hitter by letter and gives all four players'
foot positions; the letter is attached to the tracked player standing there.
Published stroke types are coarser than the singles classes in two places:
push and net kill are one type, and in matches 2 and 3 a soft block is not
separated from a net shot. Such a label accepts either class.
"""

import argparse
import copy
import gzip
import json
import math
import random
from pathlib import Path

import numpy as np
import torch
from badminton.event_doubles import (
    DOUBLES_FEATURES,
    SLOTS,
    choose_partner,
    doubles_observations,
    slot_end,
)
from badminton.event_model import (
    FAMILIES,
    PLAYER,
    SERVES,
    SIDES,
    TRAINED_FPS,
    with_motion,
)
from badminton.event_network import EventModel, from_checkpoint
from torch import nn
from train_events import (
    AVERAGE_DECAY,
    FAMILY,
    GROUPS,
    accepted,
    batch,
    batches,
    class_weights,
    load,
    loss_fn,
    peaks,
    predict,
    score,
    snap,
)

# Published type: class, classes also accepted, serve type.
S2_TYPES = {
    "發短球": ("serve", (), "short"),
    "發長球": ("serve", (), "long"),
    "網前小球": ("net", ("block",), None),
    "放小球": ("net", (), None),
    "擋小球": ("block", (), None),
    "平球": ("drive", (), None),
    "小平球": ("drive", (), None),
    "後場抽平球": ("drive", (), None),
    "防守回抽": ("drive", (), None),
    "挑球": ("lift", (), None),
    "防守回挑": ("lift", (), None),
    "殺球": ("smash", (), None),
    "切球": ("drop", (), None),
    "長球": ("clear", (), None),
    "推撲球": ("other", ("push", "net kill"), None),
    # DShuttleNet's nine types.
    "short serve": ("serve", (), "short"),
    "long serve": ("serve", (), "long"),
    "net shot": ("net", ("block",), None),
    "drive": ("drive", (), None),
    "lift": ("lift", (), None),
    "smash": ("smash", (), None),
    "drop": ("drop", (), None),
    "clear": ("clear", (), None),
    "push": ("other", ("push", "net kill"), None),
}
# A published foot position names a tracked player within this share of the
# frame height, and only if no other player is nearly as close.
# DShuttleNet marks a stroke about two frames after the contact that S2
# Doubles and the singles sets mark (measured on its match 2).
LABEL_SHIFT = {"dshuttlenet": -2}
DSHUTTLENET_SPLITS = Path(__file__).with_name("dshuttlenet_splits.json")
REACH = 0.07
MARGIN = 0.02
DOUBLES = ("s2doubles", "dshuttlenet", "probe")
# Frame size of each doubles rally, for the partner rule.
SIZES = {}


def hitter_slot(values, frame, feet, width, height):
    """The slot whose tracked feet stand on the published hitter position."""
    if feet is None or None in feet:
        return -1
    for offset in (0, -1, 1, -2, 2):
        index = frame + offset
        if not 0 <= index < len(values):
            continue
        distances = []
        for slot in range(SLOTS):
            block = values[index, slot * PLAYER : (slot + 1) * PLAYER]
            if block[55]:
                x = (block[51] + block[53]) / 2 * width
                y = block[54] * height
                distances.append((math.hypot(x - feet[0], y - feet[1]), slot))
        if not distances:
            continue
        distances.sort()
        if distances[0][0] > REACH * height:
            continue
        if len(distances) > 1 and distances[1][0] - distances[0][0] < MARGIN * height:
            return -1
        return distances[0][1]
    return -1


def doubles_clip(document):
    """Four-slot inputs and hits for one S2 Doubles rally."""
    width, height = document["video"]["width"], document["video"]["height"]
    fps = float(document["video"]["fps"])
    rows = document["players"]
    if abs(fps - TRAINED_FPS) > 0.5:
        raise ValueError("S2 Doubles features must be at the trained frame rate")
    # Judge the court by the labelled stretch: the margin before and after a
    # short rally is mostly other camera views.
    frames = [e["frame"] for e in document["events"]] or [0]
    played = rows[max(0, min(frames)) : max(frames) + 1] or rows
    if np.mean([bool(r.get("calibration_valid")) for r in played]) < 0.5:
        return None, []
    values, _ = doubles_observations(rows, document["shuttle"], width, height, fps)
    hits = []
    shift = LABEL_SHIFT.get(document.get("dataset"), 0)
    for event in document["events"]:
        frame = event["frame"]
        if not (0 <= frame < len(values) and 0 <= frame + shift < len(values)):
            continue
        family, either, serve = S2_TYPES.get(event["source_type"], (None, (), None))
        feet = event["feet"].get(event["player"]) if event["player"] else None
        hits.append(
            (
                frame + shift,
                hitter_slot(values, frame, feet, width, height),
                FAMILY[family] if family else -1,
                -1 if event["backhand"] is None else int(event["backhand"]),
                SERVES.index(serve) if serve else -1,
                accepted(family, either),
            )
        )
    return with_motion(values), hits


def dshuttlenet_split(match):
    listed = json.loads(DSHUTTLENET_SPLITS.read_text(encoding="utf-8"))
    return next(
        (fold for fold in ("validation", "test") if match in listed[fold]), "train"
    )


def load_doubles(folders, fold=None):
    """Rallies by split; `fold` puts every rally in that one instead.

    DShuttleNet rallies take their split from dshuttlenet_splits.json.
    """
    data = {"train": [], "validation": [], "test": [], "probe": []}
    paths = sorted(p for folder in folders for p in Path(folder).glob("*.json.gz"))
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as source:
            document = json.load(source)
        if document.get("dataset") == "dshuttlenet":
            document["split"] = dshuttlenet_split(document["match_id"])
        if abs(float(document["video"]["fps"]) - TRAINED_FPS) > 0.5:
            continue
        inputs, hits = doubles_clip(document)
        video = document["video"]
        SIZES[document["clip_id"]] = (video["width"], video["height"])
        split = fold or document["split"]
        if hits and split in data:
            data[split].append((document["clip_id"], inputs, hits))
    return data


def widen(item):
    """A singles clip in the four slots: far player in 0, near player in 2."""
    clip_id, inputs, hits = item
    wide = np.zeros((len(inputs), DOUBLES_FEATURES), np.float32)
    wide[:, :PLAYER] = inputs[:, :PLAYER]
    wide[:, 2 * PLAYER : 3 * PLAYER] = inputs[:, PLAYER : 2 * PLAYER]
    wide[:, SLOTS * PLAYER :] = inputs[:, 2 * PLAYER :]
    hits = [
        (frame, hitter * 2 if hitter >= 0 else -1, *rest)
        for frame, hitter, *rest in hits
    ]
    return clip_id, wide, hits


def swap_partners(item):
    """Exchange the two slots of an end at random: which is which means nothing."""
    clip_id, inputs, hits = item
    order = list(range(SLOTS))
    for base in (0, 2):
        if random.random() < 0.5:
            order[base], order[base + 1] = order[base + 1], order[base]
    if order == list(range(SLOTS)):
        return item
    out = inputs.copy()
    for target, source in enumerate(order):
        out[:, target * PLAYER : (target + 1) * PLAYER] = inputs[
            :, source * PLAYER : (source + 1) * PLAYER
        ]
    hits = [
        (frame, order.index(hitter) if hitter >= 0 else -1, *rest)
        for frame, hitter, *rest in hits
    ]
    return clip_id, out, hits


def hitter_report(items, predictions, threshold, tolerance=2):
    """On found contacts with a known hitter: right end, then right partner.

    The partner is scored twice: as the network names it, and as the rule the
    app uses (event_doubles.choose_partner) names it at the found frame.
    """
    ends = partners = ruled = total = 0
    for (clip_id, inputs, hits), predicted in zip(items, predictions):
        frames = peaks(predicted["hit"], threshold)
        used = set()
        for frame, hitter, *_ in hits:
            options = [
                f for f in frames if f not in used and abs(f - frame) <= tolerance
            ]
            if not options:
                continue
            best = min(options, key=lambda f: abs(f - frame))
            used.add(best)
            if hitter < 0:
                continue
            guess = int(predicted["hitter"][best])
            total += 1
            if guess // 2 != hitter // 2:
                continue
            ends += 1
            partners += guess == hitter
            ruled += (
                choose_partner(inputs, best, slot_end(guess), *SIZES[clip_id]) == hitter
            )
    return {
        "contacts_with_hitter": total,
        "court_end_accuracy": ends / max(1, total),
        "partner_accuracy_within_end": partners / max(1, ends),
        "partner_accuracy_within_end_by_rule": ruled / max(1, ends),
    }


def timing(items, predictions, threshold, reach=8):
    """How many frames found contacts sit after the labelled ones."""
    offsets = []
    for (_, _, hits), predicted in zip(items, predictions):
        frames = peaks(predicted["hit"], threshold)
        for frame, *_ in hits:
            near = [f - frame for f in frames if abs(f - frame) <= reach]
            if near:
                offsets.append(min(near, key=abs))
    if not offsets:
        return {}
    values = np.array(offsets)
    return {
        "labels_with_a_contact_nearby": len(offsets),
        "median_offset_frames": float(np.median(values)),
        "mean_offset_frames": float(values.mean()),
        "share_within_frames": {
            str(t): float((abs(values) <= t).mean()) for t in (1, 2, 3, 4, 6)
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--doubles", type=Path, help="S2 Doubles feature folder")
    parser.add_argument(
        "--dshuttlenet", type=Path, nargs="*", help="DShuttleNet feature folders"
    )
    parser.add_argument("--features", type=Path, help="AI CUP singles features")
    parser.add_argument("--shuttleset", type=Path, help="ShuttleSet feature folder")
    parser.add_argument(
        "--teacher", type=Path, help="checkpoint that places ShuttleSet hit frames"
    )
    parser.add_argument(
        "--singles-only",
        action="store_true",
        help="train and choose the model on singles; doubles is only reported",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="times each doubles rally is seen per epoch when singles is mixed in",
    )
    parser.add_argument("--init", type=Path, help="checkpoint to continue from")
    parser.add_argument(
        "--probe",
        type=Path,
        help="only score the saved model on this folder of other doubles features",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--hidden", type=int, default=192)
    parser.add_argument("--layers", type=int, default=2)
    parser.add_argument(
        "--jitter", action="store_true", help="vary framing and hide the shuttle"
    )
    parser.add_argument(
        "--final", action="store_true", help="score the held-out match and venues"
    )
    args = parser.parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    if not (args.doubles or args.dshuttlenet or args.singles_only or args.probe):
        raise SystemExit("Give --doubles, or --singles-only to train without it")
    sets = {"s2doubles": load_doubles([args.doubles] if args.doubles else [])}
    if args.dshuttlenet:
        sets["dshuttlenet"] = load_doubles(args.dshuttlenet)
    if args.probe:
        sets["probe"] = load_doubles([args.probe], "probe")
    if args.features or args.shuttleset:
        groups = json.loads(GROUPS.read_text(encoding="utf-8"))["source_groups"]
        folds = {
            member.split(":")[1]: group["fold"]
            for group in groups
            for member in group["members"]
            if member.startswith("train:")
        }
        aicup, shuttleset = load(args.features or Path("-"), folds, args.shuttleset)
        if args.teacher:
            shuttleset = {
                fold: snap(items, args.teacher, device)
                for fold, items in shuttleset.items()
            }
        for name, data in (("aicup", aicup), ("shuttleset", shuttleset)):
            sets[name] = {
                fold: [widen(i) for i in items] for fold, items in data.items()
            }
    known = [
        h[1] >= 0
        for name in DOUBLES
        for fold in sets.get(name, {}).values()
        for i in fold
        for h in i[2]
    ]
    print(
        {name: {k: len(v) for k, v in data.items()} for name, data in sets.items()},
        f"rallies on {device}; doubles hitter attached to a track for "
        f"{sum(known)} of {len(known)} strokes",
        flush=True,
    )
    singles = [
        i
        for name in ("aicup", "shuttleset")
        for i in sets.get(name, {}).get("train", [])
    ]
    if args.singles_only:
        train, chosen_on = singles, [n for n in sets if n not in DOUBLES]
    else:
        doubles = [
            item
            for name in ("s2doubles", "dshuttlenet")
            for item in sets.get(name, {}).get("train", [])
        ]
        train = singles + doubles * (args.repeat if singles else 1)
        chosen_on = [
            name
            for name in ("s2doubles", "dshuttlenet")
            if sets.get(name, {}).get("validation")
        ]
    args.output.mkdir(parents=True, exist_ok=True)
    checkpoint = args.output / "events.pt"

    def evaluate(model, fold, threshold, tolerance):
        result = {}
        for name, data in sets.items():
            items = data.get(fold, [])
            if not items:
                continue
            predictions = predict(model, items, device)
            result[name] = score(items, predictions, threshold, tolerance)
            if name == "probe":
                result[name]["timing"] = timing(items, predictions, threshold)
            if name in DOUBLES:
                result[name]["hitter"] = hitter_report(
                    items, predictions, threshold, tolerance
                )
        return result

    if not (args.final or args.probe):
        if not train:
            raise SystemExit("No training rallies found")
        network = {
            "hidden": args.hidden,
            "layers": args.layers,
            "norm": "step",
            "players": SLOTS,
        }
        model = EventModel(**network).to(device)
        if args.init:
            start = torch.load(args.init, map_location=device, weights_only=True)
            model.load_state_dict(start["state"])
        average = copy.deepcopy(model)
        updates = 0
        weights = class_weights(train, device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-2)
        steps = args.epochs * math.ceil(len(train) / args.batch_size)
        schedule = torch.optim.lr_scheduler.OneCycleLR(
            optimizer, args.lr, total_steps=steps
        )
        best, history = -1, []
        for epoch in range(1, args.epochs + 1):
            model.train()
            losses = []
            for group in batches(train, args.batch_size, True):
                x, hit, valid, classes, accept = batch(
                    [swap_partners(item) for item in group],
                    device,
                    augment=True,
                    strong=args.jitter,
                )
                x = x + 0.003 * torch.randn_like(x) * (x != 0)
                loss = loss_fn(model(x), hit, valid, classes, accept, weights)
                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1)
                optimizer.step()
                schedule.step()
                losses.append(loss.item())
                updates += 1
                keep = min(AVERAGE_DECAY, updates / (updates + 10))
                with torch.no_grad():
                    for kept, value in zip(average.parameters(), model.parameters()):
                        kept.lerp_(value, 1 - keep)
            if epoch % 5 == 0 or epoch == args.epochs:
                options = []
                for threshold in (0.3, 0.4, 0.5, 0.6, 0.7):
                    result = evaluate(average, "validation", threshold, 2)
                    mean = float(
                        np.mean(
                            [
                                result[name]["complete_event_f1"]
                                for name in chosen_on
                                if name in result
                            ]
                        )
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
                                        "hitter_accuracy_on_matched",
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
                            "state": average.state_dict(),
                            "threshold": threshold,
                            "epoch": epoch,
                            "families": FAMILIES,
                            "network": network,
                            "serves": SERVES,
                            "sides": SIDES,
                            "features": DOUBLES_FEATURES,
                            "mode": "doubles",
                            "chosen_on": chosen_on,
                        },
                        checkpoint,
                    )
        (args.output / "history.json").write_text(json.dumps(history, indent=1))

    saved = torch.load(checkpoint, map_location=device, weights_only=True)
    model = from_checkpoint(saved).to(device)
    model.load_state_dict(saved["state"])
    report = {"epoch": saved["epoch"], "threshold": saved["threshold"]}
    folds = ("validation", "test") if args.final else ("validation",)
    for fold in ("probe",) if args.probe else folds:
        report[fold] = [
            evaluate(model, fold, saved["threshold"], tolerance) for tolerance in (2, 4)
        ]
    name = "final_report.json" if args.final else "validation_report.json"
    if args.probe:
        name = "probe_report.json"
    (args.output / name).write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
