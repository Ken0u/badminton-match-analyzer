"""Measure what separates the stroke classes a checkpoint confuses.

For every validation contact the checkpoint finds, this writes the labelled
and predicted stroke with simple measurements taken from the same inputs the
model reads: how high on the hitter the shuttle was struck, how far it rose
and how fast it left, how long until the next contact and where both players
stood. It then prints the medians for each labelled/predicted pair and how
well each measurement alone separates pairs of classes (AUC, 0.5 = not at
all). The model's own lift and push probabilities are written too. Everything is in image units (share of the frame), so far-end and
near-end hitters are reported apart. Validation folds only.

    python training/diagnose_strokes.py --features /data/features \
        --shuttleset /data/shuttleset/features --teacher /data/model_v2/events.pt \
        --checkpoint /data/model_v5c/events.pt --output /data/diagnose_v5c
"""

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch
from badminton.event_model import COURT_ENDS, FAMILIES, PLAYER
from badminton.event_network import from_checkpoint
from train_events import GROUPS, aicup_clip, peaks, predict, shuttleset_clip, snap

BALL = 2 * PLAYER
MEASURES = (
    "contact_height",
    "rise",
    "apex_delay",
    "speed_out",
    "up_out",
    "across_out",
    "speed_in",
    "gap",
    "hitter_feet",
    "receiver_feet",
    "next_height",
    "seen_out",
)
PAIRS = (
    ("shuttleset", "lift", "push"),
    ("shuttleset", "drive", "block"),
    ("shuttleset", "drive", "push"),
    ("shuttleset", "net kill", "net"),
    ("shuttleset", "net kill", "push"),
    ("aicup", "lift", "other"),
    ("aicup", "drive", "lift"),
)


def box(inputs, end, frame, reach=3):
    """Top, bottom and height of a player's box at the nearest observed frame."""
    block = inputs[:, end * PLAYER : (end + 1) * PLAYER]
    for offset in sorted(range(-reach, reach + 1), key=abs):
        index = frame + offset
        if 0 <= index < len(block) and block[index, 55] > 0:
            top, bottom = block[index, 52], block[index, 54]
            return top, bottom, max(bottom - top, 1e-6)
    return None


def ball_at(inputs, frame, reach=3):
    for offset in sorted(range(-reach, reach + 1), key=abs):
        index = frame + offset
        if 0 <= index < len(inputs) and inputs[index, BALL + 2] > 0:
            return inputs[index, BALL], inputs[index, BALL + 1]
    return None


def velocity(inputs, start, stop):
    rows = inputs[max(0, start) : max(0, stop)]
    rows = rows[rows[:, BALL + 5] > 0]
    if not len(rows):
        return None
    return rows[:, BALL + 3], rows[:, BALL + 4]


def measure(inputs, frame, end, following):
    """Measurements around one contact; None where the trackers saw nothing."""
    out = dict.fromkeys(MEASURES)
    last = min(len(inputs) - 1, frame + 45, following - 1 if following else 10**9)
    hitter, struck = box(inputs, end, frame), ball_at(inputs, frame)
    if hitter:
        out["hitter_feet"] = hitter[1]
    if hitter and struck:
        out["contact_height"] = (hitter[1] - struck[1]) / hitter[2]
    after = inputs[frame + 1 : last + 1]
    seen = after[:, BALL + 2] > 0
    out["seen_out"] = float(np.mean(inputs[frame + 1 : frame + 11, BALL + 2] > 0))
    if struck and seen.any():
        heights = np.where(seen, after[:, BALL + 1], np.inf)
        out["rise"] = struck[1] - heights.min()
        out["apex_delay"] = int(heights.argmin()) + 1
    leaving = velocity(inputs, frame + 1, min(frame + 7, last + 1))
    if leaving:
        out["speed_out"] = float(np.mean(np.hypot(*leaving)))
        out["up_out"] = float(-np.mean(leaving[1]))
        out["across_out"] = float(np.mean(np.abs(leaving[0])))
    arriving = velocity(inputs, frame - 6, frame)
    if arriving:
        out["speed_in"] = float(np.mean(np.hypot(*arriving)))
    if following:
        out["gap"] = following - frame
        receiver, taken = box(inputs, 1 - end, following), ball_at(inputs, following)
        if receiver:
            out["receiver_feet"] = receiver[1]
        if receiver and taken:
            out["next_height"] = (receiver[1] - taken[1]) / receiver[2]
    return out


def auc(first, second):
    """Chance that a value from first exceeds one from second."""
    first, second = np.asarray(first, float), np.asarray(second, float)
    if len(first) < 8 or len(second) < 8:
        return None
    wins = (first[:, None] > second[None]).mean()
    ties = (first[:, None] == second[None]).mean()
    return float(wins + ties / 2)


def median(rows, name):
    values = [row[name] for row in rows if row[name] is not None]
    return f"{np.median(values):7.3f}" if values else "    n/a"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--shuttleset", type=Path, required=True)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    groups = json.loads(GROUPS.read_text(encoding="utf-8"))["source_groups"]
    validation = {
        member.split(":")[1]
        for group in groups
        if group["fold"] == "validation"
        for member in group["members"]
        if member.startswith("train:")
    }
    sets = {"aicup": [], "shuttleset": []}
    for path in sorted(args.features.glob("*.json.gz")):
        clip_id = path.name.split(".")[0]
        if clip_id in validation:
            with gzip.open(path, "rt", encoding="utf-8") as source:
                inputs, hits = aicup_clip(json.load(source))
            if hits:
                sets["aicup"].append((clip_id, inputs, hits))
    for path in sorted(args.shuttleset.glob("ss-*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as source:
            document = json.load(source)
        if document["split"] != "validation":
            continue
        inputs, hits = shuttleset_clip(document)
        if hits:
            sets["shuttleset"].append((document["clip_id"], inputs, hits))
    sets["shuttleset"] = snap(sets["shuttleset"], args.teacher, device)
    print({name: len(items) for name, items in sets.items()}, "validation clips")

    saved = torch.load(args.checkpoint, map_location=device, weights_only=True)
    model = from_checkpoint(saved).to(device)
    model.load_state_dict(saved["state"])

    rows = []
    for name, items in sets.items():
        for (clip_id, inputs, hits), predicted in zip(
            items, predict(model, items, device)
        ):
            with torch.no_grad():
                out = model(torch.from_numpy(inputs)[None].to(device))
            shares = torch.softmax(out["family"][0].float(), -1).cpu().numpy()
            frames = peaks(predicted["hit"], saved["threshold"])
            used = set()
            ordered = sorted(hits, key=lambda hit: hit[0])
            for position, (frame, hitter, family, _, _, mask) in enumerate(ordered):
                options = [f for f in frames if f not in used and abs(f - frame) <= 2]
                if family < 0 or not options:
                    continue
                best = min(options, key=lambda f: abs(f - frame))
                used.add(best)
                guess = int(predicted["family"][best])
                end = hitter if hitter >= 0 else int(predicted["hitter"][best])
                later = ordered[position + 1][0] if position + 1 < len(ordered) else 0
                before = ordered[position - 1][2] if position else -1
                rows.append(
                    {
                        "dataset": name,
                        "clip": clip_id,
                        "frame": frame,
                        "end": COURT_ENDS[end],
                        "labelled": FAMILIES[family],
                        "predicted": FAMILIES[guess],
                        "accepted": bool(mask[guess]),
                        "previous": FAMILIES[before] if before >= 0 else "",
                        "lift_share": float(shares[best, FAMILIES.index("lift")]),
                        "push_share": float(shares[best, FAMILIES.index("push")]),
                        **measure(inputs, frame, end, later),
                    }
                )

    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "contacts.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    header = " ".join(f"{name[:7]:>7}" for name in MEASURES)
    cells = defaultdict(list)
    for row in rows:
        cells[row["dataset"], row["end"], row["labelled"], row["predicted"]].append(row)
    for dataset in sets:
        for end in COURT_ENDS:
            print(f"\n== {dataset}, {end}-end hitter: medians")
            print(f"{'labelled -> predicted':26s}    n {header}  usual previous")
            for key in sorted(k for k in cells if k[:2] == (dataset, end)):
                group = cells[key]
                if len(group) < 8:
                    continue
                usual = Counter(row["previous"] for row in group).most_common(2)
                print(
                    f"{key[2] + ' -> ' + key[3]:26s} {len(group):4d} "
                    + " ".join(median(group, name) for name in MEASURES)
                    + "  "
                    + ", ".join(f"{k or 'none'} {v}" for k, v in usual)
                )

    def values(chosen, name):
        return [row[name] for row in chosen if row[name] is not None]

    print("\n== AUC of each measurement alone, by label (0.5 = no separation)")
    print(f"{'pair':44s} {header}")
    for dataset, first, second in PAIRS:
        for end in COURT_ENDS:
            a = [
                r for k, g in cells.items() if k[:3] == (dataset, end, first) for r in g
            ]
            b = [
                r
                for k, g in cells.items()
                if k[:3] == (dataset, end, second)
                for r in g
            ]
            scores = [auc(values(a, name), values(b, name)) for name in MEASURES]
            label = f"{dataset} {end}: {first} ({len(a)}) vs {second} ({len(b)})"
            print(
                f"{label:44s} "
                + " ".join("    n/a" if s is None else f"{s:7.2f}" for s in scores)
            )

    print("\n== AUC within one label: called right vs called the other class")
    for dataset, label, other in (
        ("aicup", "lift", "push"),
        ("shuttleset", "lift", "push"),
        ("shuttleset", "push", "lift"),
        ("aicup", "drive", "net kill"),
        ("shuttleset", "drive", "block"),
        ("shuttleset", "block", "drive"),
    ):
        for end in COURT_ENDS:
            a, b = cells[dataset, end, label, label], cells[dataset, end, label, other]
            scores = [auc(values(a, name), values(b, name)) for name in MEASURES]
            title = f"{dataset} {end}: {label} ok ({len(a)}) vs as {other} ({len(b)})"
            print(
                f"{title:44s} "
                + " ".join("    n/a" if s is None else f"{s:7.2f}" for s in scores)
            )


if __name__ == "__main__":
    main()
