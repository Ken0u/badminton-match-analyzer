"""Offline singles family recognizer. Frozen frame models; learn at stroke cadence.

Run from this checkout: .venv/Scripts/python training/train_stroke_sequence.py
Uses existing local feature archives; never installs weights or reads test clips.
"""

# ruff: noqa: E402 -- pin the real shared store before importing configuration.
import gzip
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["BADMINTON_ROOT"] = str(ROOT)
os.environ["BADMINTON_DATA_DIR"] = str(ROOT / "data/processed")
sys.path.insert(0, str(ROOT / "backend"))
import numpy as np
import torch
from badminton.config import DATA
from badminton.event_model import FAMILIES, PLAYER
from badminton.event_network import from_checkpoint
from badminton.jobs import run_local_job
from badminton.storage import Store
from torch import nn
from train_events import peaks, shuttleset_clip

OUT = ROOT / ".cache/stroke-sequence-v1"
K = len(FAMILIES)
SEED = 173
MODELS = [
    ROOT / "models/weights/events.pt",
    ROOT / ".cache/model_v6b/events.pt",
    ROOT / ".cache/model_v5a/events.pt",
]
FEATURE = ROOT / ".cache/step3/features/shuttleset/features"
FOCUS = ["drive", "lift", "push", "block", "drop"]
SIX = ["clear", "lift", "net", "drop", "smash", "drive"]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def features(x, frames, hitter, outputs):
    out = []
    for j, f in enumerate(frames):
        slot = hitter[f] * PLAYER
        person = x[f, slot : slot + PLAYER]
        feet = person[51:55]
        scale = max(0.04, float(feet[3] - feet[1]))
        ball = x[:, -6:]
        row = [hitter[f], *feet, person[55]]
        for a, b in [(-12, -5), (-5, 1), (1, 5), (5, 12), (12, 24)]:
            lo = max(0, f + a, frames[j - 1] + 1 if j else 0)
            hi = min(len(x), f + b, frames[j + 1] if j + 1 < len(frames) else len(x))
            segment = ball[lo:hi]
            bb = segment[segment[:, 2] > 0]
            if len(bb):
                center = bb[:, :2].mean(0)
                row.extend(
                    [
                        1,
                        (center[0] - (feet[0] + feet[2]) / 2) / scale,
                        (center[1] - feet[3]) / scale,
                        (bb[-1, 0] - bb[0, 0]) / scale,
                        (bb[-1, 1] - bb[0, 1]) / scale,
                    ]
                )
            else:
                row.extend([0] * 5)
        for idx in [5, 6, 7, 8, 9, 10]:
            px, py, p = person[3 * idx : 3 * idx + 3]
            row.extend(
                [(px - (feet[0] + feet[2]) / 2) / scale, (py - feet[3]) / scale, p]
                if p > 0.2
                else [0] * 3
            )
        row.extend(
            [
                min(2, (f - frames[j - 1]) / 30) if j else 0,
                min(2, (frames[j + 1] - f) / 30) if j + 1 < len(frames) else 0,
            ]
        )
        out.append(np.r_[np.concatenate([o[f] for o in outputs]), np.clip(row, -8, 8)])
    return np.array(out, np.float32)


class StrokeSequence(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.embed = nn.Sequential(
            nn.Linear(d, 64), nn.LayerNorm(64), nn.GELU(), nn.Dropout(0.18)
        )
        self.context = nn.GRU(64, 48, batch_first=True, bidirectional=True)
        self.head = nn.Linear(96, K)
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def forward(self, x, lengths):
        enc = self.embed(x)
        h = nn.utils.rnn.pack_padded_sequence(
            enc, lengths.cpu(), batch_first=True, enforce_sorted=False
        )
        h, _ = self.context(h)
        h, _ = nn.utils.rnn.pad_packed_sequence(
            h, batch_first=True, total_length=x.shape[1]
        )
        return x[:, :, : 3 * K].reshape(*x.shape[:2], 3, K).mean(2) + self.head(h)


def collect(device, progress):
    models = []
    for p in MODELS:
        s = torch.load(p, map_location=device, weights_only=True)
        assert tuple(s["families"]) == tuple(FAMILIES)
        m = from_checkpoint(s).to(device).eval()
        m.load_state_dict(s["state"])
        models.append(m)
    cut = torch.load(MODELS[0], map_location="cpu", weights_only=True)["threshold"]
    idx = ROOT / "data/datasets/shuttleset/index/strokes.jsonl"
    split = {}
    with idx.open(encoding="utf8") as fin:
        for line in fin:
            rec = json.loads(line)
            split.setdefault(rec["match_id"], set()).add(rec["split"])
    paths = [
        p
        for p in sorted(FEATURE.glob("*.json.gz"))
        if split.get(int(p.name.split("-")[1]), set()) in ({"train"}, {"validation"})
    ]
    data = []
    inventory = Counter()
    with torch.inference_mode():
        for i, p in enumerate(paths):
            if i % 300 == 0:
                print("extract", i, len(paths), flush=True)
                progress(0.85 * i / max(1, len(paths)))
            doc = json.loads(gzip.decompress(p.read_bytes()))
            fold = doc["split"]
            assert {fold} == split[doc["match_id"]]
            inventory[fold + "_clips"] += 1
            inventory[fold + "_refs"] += len(doc["events"])
            inventory[fold + "_known_refs"] += sum(
                bool(e["usable"]) and e["source_type"] in SH_TYPES
                for e in doc["events"]
            )
            x, hits = shuttleset_clip(doc)
            if x is None or not len(x):
                continue
            xx = torch.from_numpy(x)[None].to(device)
            oo = [m(xx) for m in models]
            frames = peaks(oo[0]["hit"][0, :, 0].sigmoid().cpu().numpy(), cut)
            inventory[fold + "_peaks"] += len(frames)
            if not frames:
                continue
            fac = [o["family"][0].cpu().numpy() for o in oo]
            he = oo[0]["hitter"][0].argmax(1).cpu().numpy()
            z = features(x, frames, he, fac)
            y = np.full(len(z), -1, np.int64)
            who = np.full(len(z), -1, np.int64)
            used = set()
            taken = set()
            for _, i0, j in sorted(
                (abs(f - h[0]), i0, j)
                for i0, h in enumerate(hits)
                for j, f in enumerate(frames)
                if abs(f - h[0]) <= 4
            ):
                if i0 in used or j in taken:
                    continue
                used.add(i0)
                taken.add(j)
                y[j] = hits[i0][2]
                who[j] = hits[i0][1]
            data.append((fold, doc["match_id"], z, y, who))
    return data, dict(inventory)


from train_events import SHUTTLESET_FAMILY as SH_TYPES


def batch(items, dev):
    def pad(items, val):
        return nn.utils.rnn.pad_sequence(
            [torch.from_numpy(a) for a in items], batch_first=True, padding_value=val
        ).to(dev)

    return (
        pad([r[2] for r in items], 0),
        pad([r[3] for r in items], -1),
        torch.tensor([len(r[2]) for r in items]),
    )


def metrics(rows):
    y = np.concatenate([r[1] for r in rows])
    out = {}
    for j, key in enumerate(("installed", "ensemble", "sequence"), 2):
        p = np.concatenate([r[j] for r in rows])
        mask = y >= 0
        tab = np.zeros((K, K), int)
        np.add.at(tab, (y[mask], p[mask]), 1)
        f = 2 * tab.diagonal() / np.maximum(1, tab.sum(1) + tab.sum(0))
        per = {s: round(float(f[i]), 4) for i, s in enumerate(FAMILIES)}
        matches = {
            str(m): sum(
                int(((r[1] == r[j]) & (r[1] >= 0)).sum()) for r in rows if r[0] == m
            )
            for m in sorted({r[0] for r in rows})
        }
        out[key] = {
            "correct": int(tab.trace()),
            "known": int(tab.sum()),
            "focus_macro": float(np.mean([f[FAMILIES.index(t)] for t in FOCUS])),
            "six_macro": float(np.mean([f[FAMILIES.index(t)] for t in SIX])),
            "per_family_f1": per,
            "match_correct": matches,
            "confusion": tab.tolist(),
        }
    return out


def task(job, progress):
    OUT.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(2)
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    protocol = {
        "seed": SEED,
        "epochs": 16,
        "match_tolerance_30fps": 4,
        "focus": FOCUS,
        "six": SIX,
        "model_hashes": [sha(p) for p in MODELS],
        "script_sha": sha(Path(__file__)),
        "device": device,
    }
    (OUT / "protocol.json").write_text(json.dumps(protocol, indent=2))
    print("job", job, device, flush=True)
    data, inventory = collect(device, progress)
    train = [r for r in data if r[0] == "train"]
    val = [r for r in data if r[0] == "validation"]
    assert not ({r[1] for r in train} & {r[1] for r in val})
    print("train/val", len(train), len(val), flush=True)
    model = StrokeSequence(train[0][2].shape[1]).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=0.0015, weight_decay=0.015)
    rng = np.random.default_rng(SEED)
    freq = np.bincount(np.concatenate([r[3][r[3] >= 0] for r in train]), minlength=K)
    weights = torch.tensor(
        np.clip((np.median(freq[freq > 0]) / freq.clip(1)) ** 0.25, 0.65, 2),
        device=device,
        dtype=torch.float32,
    )
    model.train()
    for e in range(16):
        for ids in np.array_split(
            rng.permutation(len(train)), max(1, len(train) // 48)
        ):
            x, y, lengths = batch([train[i] for i in ids], device)
            mask = y >= 0
            if not mask.any():
                continue
            pred = model(x, lengths)
            loss = nn.functional.cross_entropy(pred[mask], y[mask], weight=weights)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 2)
            opt.step()
        progress(0.85 + 0.14 * (e + 1) / 16)
    torch.save(
        {
            "state": model.cpu().state_dict(),
            "features": train[0][2].shape[1],
            "families": FAMILIES,
            "protocol": protocol,
        },
        OUT / "candidate.pt",
    )
    model.eval()
    rows = []
    with torch.no_grad():
        for r in val:
            x, _, lengths = batch([r], "cpu")
            pred = model(x, lengths)[0].argmax(-1).numpy()
            z = r[2]
            rows.append(
                (
                    r[1],
                    r[3],
                    z[:, :K].argmax(1),
                    z[:, : 3 * K].reshape(len(z), 3, K).mean(1).argmax(1),
                    pred,
                )
            )
    report = {
        "inventory": inventory,
        "train_matches": sorted({r[1] for r in train}),
        "validation_matches": sorted({r[1] for r in val}),
        "train_matched_known": int(freq.sum()),
        "metrics": metrics(rows),
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    return {
        "matched": report["metrics"]["sequence"]["known"],
        "report": str(OUT / "report.json"),
    }


if __name__ == "__main__":
    print(
        run_local_job(
            Store(DATA), "stroke_sequence_research", "stroke-sequence-v1", task
        ),
        flush=True,
    )
