"""Fine-tune OSNet to tell apart the four players of a doubles match.

The published OSNet weights learned pedestrians in street cameras. Here it
learns badminton players from crops written by reid_crops.py, one person per
(match, letter). Each batch holds a few matches with all four of their
players, so the hardest comparisons are the real ones: partners in one kit,
seen from both ends. Loss: a classifier over the training people (label
smoothing) plus a triplet loss whose negatives are the other three players of
the same match.

A few training matches are kept aside as a check (--check): after each epoch,
every check crop is matched to its nearest crop of the same match from
another rally, and the share with the right letter is printed. The checkpoint
with the best check share is kept. Validation and test matches are never read.

    python training/finetune_reid.py --crops /data/reid_crops \
        --init /data/reid/osnet_x1_0_msmt17.pth --out /data/reid_ft \
        --check 3 4 8
"""

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

sys.path.insert(0, str(Path(__file__).resolve().parent))

import osnet


def index(crops, matches):
    """Crop paths per (match, letter), with rally and court end."""
    found = []
    for match in matches:
        for path in sorted((crops / str(match)).glob("*.jpg")):
            clip, frame, letter, end = path.stem.rsplit("_", 3)
            found.append(
                {"path": path, "match": match, "letter": letter,
                 "clip": clip, "end": int(end)}
            )
    return found


def prepare(image, train):
    image = image.astype(np.float32) / 255.0
    if train:
        # Light changes from end to end and venue to venue; the kit colour
        # itself must stay, so only brightness and contrast move.
        image = np.clip((image - 0.5) * random.uniform(0.85, 1.15) + 0.5
                        + random.uniform(-0.08, 0.08), 0, 1)
        h, w = image.shape[:2]
        scale = random.uniform(0.85, 1.0)
        ch, cw = int(h * scale), int(w * random.uniform(0.85, 1.0))
        top, left = random.randint(0, h - ch), random.randint(0, w - cw)
        image = cv2.resize(image[top : top + ch, left : left + cw], (w, h))
        if random.random() < 0.4:
            eh, ew = int(h * random.uniform(0.1, 0.35)), int(w * random.uniform(0.2, 0.5))
            y, x = random.randint(0, h - eh), random.randint(0, w - ew)
            image[y : y + eh, x : x + ew] = np.random.rand(eh, ew, 3)
    image = (image[:, :, ::-1] - osnet.MEAN) / osnet.SPREAD
    return torch.from_numpy(np.ascontiguousarray(image.transpose(2, 0, 1)))


class Crops(Dataset):
    def __init__(self, items, train):
        self.items, self.train = items, train

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        item = self.items[i]
        image = cv2.imread(str(item["path"]))
        return prepare(image, self.train), item["person"], item["match_index"]


class Batches(torch.utils.data.Sampler):
    """Batches of `matches` matches x 4 players x `each` crops."""

    def __init__(self, items, matches, each, steps):
        self.by = defaultdict(lambda: defaultdict(list))
        for i, item in enumerate(items):
            self.by[item["match"]][item["letter"]].append(i)
        self.usable = [m for m, people in self.by.items() if len(people) == 4]
        self.matches, self.each, self.steps = matches, each, steps

    def __len__(self):
        return self.steps

    def __iter__(self):
        for _ in range(self.steps):
            batch = []
            for match in random.sample(self.usable, self.matches):
                for pool in self.by[match].values():
                    batch += random.choices(pool, k=self.each)
            yield batch


class Head(nn.Module):
    def __init__(self, people):
        super().__init__()
        self.neck = nn.BatchNorm1d(512)
        self.classify = nn.Linear(512, people, bias=False)

    def forward(self, features):
        return self.classify(self.neck(features))


def triplet(features, people, matches, margin):
    """Batch-hard triplet loss; negatives only from the same match."""
    unit = nn.functional.normalize(features, dim=1)
    distance = torch.cdist(unit, unit)
    same = people[:, None] == people[None, :]
    match = matches[:, None] == matches[None, :]
    hardest_positive = (distance * same).max(dim=1).values
    negative = torch.where(match & ~same, distance, torch.full_like(distance, 9.0))
    hardest_negative = negative.min(dim=1).values
    return torch.relu(hardest_positive - hardest_negative + margin).mean()


@torch.no_grad()
def check(model, items, device):
    """Share of check crops whose nearest crop (same match, other rally) has
    the right letter, overall and for partners only (same team end)."""
    model.eval()
    loader = DataLoader(Crops(items, False), batch_size=256, num_workers=6)
    vectors = []
    for images, _, _ in loader:
        with torch.autocast("cuda", enabled=device == "cuda"):
            out = model(images.to(device))
        vectors.append(nn.functional.normalize(out.float(), dim=1).cpu())
    vectors = torch.cat(vectors)
    right = partner_right = partner_total = 0
    for match in {item["match"] for item in items}:
        own = [i for i, item in enumerate(items) if item["match"] == match]
        v = vectors[own]
        similarity = v @ v.T
        clips = [items[i]["clip"] for i in own]
        letters = [items[i]["letter"] for i in own]
        same_clip = torch.tensor([[a == b for b in clips] for a in clips])
        similarity[same_clip] = -9
        nearest = similarity.argmax(dim=1)
        # Partners: the letter that shares an end with this one in a rally.
        partner = {}
        for i in own:
            for j in own:
                if (items[i]["clip"] == items[j]["clip"]
                        and items[i]["end"] == items[j]["end"]
                        and items[i]["letter"] != items[j]["letter"]):
                    partner[items[i]["letter"]] = items[j]["letter"]
        for k, n in enumerate(nearest.tolist()):
            right += letters[k] == letters[n]
            mine = letters[k]
            if mine in partner:
                pair = {mine, partner[mine]}
                if letters[n] in pair:
                    partner_total += 1
                    partner_right += letters[n] == mine
    model.train()
    return right / len(items), partner_right / max(1, partner_total)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--crops", type=Path, required=True)
    parser.add_argument("--init", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--check", type=int, nargs="+", required=True)
    parser.add_argument("--leave-out", type=int, nargs="*", default=[])
    parser.add_argument("--epochs", type=int, default=24)
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--matches", type=int, default=4)
    parser.add_argument("--each", type=int, default=8)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--margin", type=float, default=0.3)
    args = parser.parse_args()
    random.seed(0)
    torch.manual_seed(0)
    splits = json.loads(
        (Path(__file__).resolve().parent / "dshuttlenet_splits.json").read_text("utf-8")
    )
    closed = set(splits["validation"]) | set(splits["test"]) | set(splits["left_out"])
    closed |= set(args.leave_out)
    available = sorted(
        int(p.name) for p in args.crops.iterdir() if p.is_dir() and p.name.isdigit()
    )
    train_matches = [m for m in available if m not in closed and m not in args.check]
    check_matches = [m for m in args.check if m in available and m not in closed]
    print(f"train matches {train_matches}\ncheck matches {check_matches}", flush=True)

    train = index(args.crops, train_matches)
    people = sorted({(i["match"], i["letter"]) for i in train})
    number = {p: n for n, p in enumerate(people)}
    for item in train:
        item["person"] = number[(item["match"], item["letter"])]
        item["match_index"] = item["match"]
    held = index(args.crops, check_matches)
    for item in held:
        item["person"] = item["match_index"] = -1
    print(f"{len(train)} training crops of {len(people)} people, "
          f"{len(held)} check crops", flush=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = osnet.load(args.init, device).train()
    head = Head(len(people)).to(device)
    optimiser = torch.optim.AdamW(
        [{"params": model.parameters(), "lr": args.lr},
         {"params": head.parameters(), "lr": args.lr * 10}],
        weight_decay=5e-4,
    )
    schedule = torch.optim.lr_scheduler.OneCycleLR(
        optimiser, max_lr=[args.lr, args.lr * 10],
        total_steps=args.epochs * args.steps, pct_start=0.1,
    )
    scaler = torch.amp.GradScaler(enabled=device == "cuda")
    smooth = nn.CrossEntropyLoss(label_smoothing=0.1)
    loader = DataLoader(
        Crops(train, True),
        batch_sampler=Batches(train, args.matches, args.each, args.steps),
        num_workers=6, persistent_workers=True,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    start_all, start_partner = check(model, held, device)
    print(f"epoch 0: check nearest right {start_all:.3f}, partners {start_partner:.3f}",
          flush=True)
    torch.save(model.state_dict(), args.out / "osnet_doubles.pth")
    best, history = start_partner, [{"epoch": 0, "all": start_all, "partner": start_partner}]
    for epoch in range(1, args.epochs + 1):
        began, losses = time.time(), []
        for images, persons, matches in loader:
            images, persons, matches = (t.to(device) for t in (images, persons, matches))
            with torch.autocast("cuda", enabled=device == "cuda"):
                features = model(images)
                loss = smooth(head(features.float()), persons) + triplet(
                    features.float(), persons, matches, args.margin
                )
            optimiser.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(optimiser)
            scaler.update()
            schedule.step()
            losses.append(loss.item())
        every, partner = check(model, held, device)
        history.append({"epoch": epoch, "loss": float(np.mean(losses)),
                        "all": every, "partner": partner})
        print(f"epoch {epoch}: loss {np.mean(losses):.3f}, check nearest right "
              f"{every:.3f}, partners {partner:.3f} ({time.time() - began:.0f} s)",
              flush=True)
        if partner > best:
            best = partner
            torch.save(model.state_dict(), args.out / "osnet_doubles.pth")
        (args.out / "history.json").write_text(json.dumps(history, indent=1))
    print(f"best check partner share {best:.3f}", flush=True)


if __name__ == "__main__":
    main()
