"""Train a fixed temporal RGB specialist; evaluate every historical prediction."""

import json
import pickle
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import prepare_stroke_rgb as prep
import torch
import train_events as te
import train_stroke_sequence as exp
import train_stroke_window as win
from replay_stroke_family_validation import counts
from torch import nn
from ultralytics import YOLO

OUT = prep.OUT
POSE_SHA = "1060bda4a27012060eca246f9b2adeea22eabb045a1e58f8d229be29b7ebc2ba"
WEAK = ("drive", "lift", "push", "block", "drop")


class VisualExpert(nn.Module):
    def __init__(self, backbone):
        super().__init__()
        self.backbone = backbone
        with torch.no_grad():
            d = backbone.eval()(torch.zeros(1, 3, 72, 72)).shape[1]
        self.pool = nn.AdaptiveAvgPool2d((2, 2))
        self.project = nn.Sequential(nn.Linear(d * 4, 96), nn.LayerNorm(96), nn.SiLU())
        self.head = nn.Sequential(
            nn.Linear(96 * 5, 192),
            nn.LayerNorm(192),
            nn.SiLU(),
            nn.Dropout(0.35),
            nn.Linear(192, exp.K),
        )

    def forward(self, x):
        # Three ordered short motions: each input channel is a different exposure.
        n = len(x)
        v = torch.stack((x[:, 0:3], x[:, 1:4], x[:, 2:5]), 1)
        y = self.pool(self.backbone(v.flatten(0, 1))).reshape(n, 3, -1)
        a, b, c = self.project(y).unbind(1)
        return self.head(torch.cat([a, b, c, b - a, c - b], 1))


def weak_f1(score):
    tab = score["family_confusion"]
    s = []
    for k in WEAK:
        tp = tab.get(k, {}).get(k, 0)
        den = sum(tab.get(k, {}).values()) + sum(r.get(k, 0) for r in tab.values())
        s.append(2 * tp / den if den else 0)
    return float(np.mean(s))


def run(job, progress):
    assert not (OUT / "rgb-validation.json").exists()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(2)
    torch.manual_seed(prep.SEED)
    rng = np.random.default_rng(prep.SEED)
    meta = json.loads((OUT / "protocol.json").read_text())
    assert meta["prep_sha"] == prep.digest(Path(prep.__file__))
    p = exp.ROOT / "models/weights/yolo11s-pose.pt"
    assert prep.digest(p) == POSE_SHA
    manifest = {}
    seen = {}
    coverage = defaultdict(Counter)
    for fold, ids in meta["split_matches"].items():
        for m in ids:
            file = OUT / f"{fold}-{m}.pkl"
            assert file.is_file()
            manifest[file.name] = prep.digest(file)
    spec = {
        "trainer_sha": prep.digest(Path(__file__)),
        "pose_sha": POSE_SHA,
        "prep_protocol_sha": prep.digest(OUT / "protocol.json"),
        "packs": manifest,
        "epochs": prep.EPOCHS,
        "seed": prep.SEED,
        "fusion": "0.70 fixed previous window logits + 0.30 visual logits. Missing crops use previous window logits.",
    }
    (OUT / "frozen-training.json").write_text(json.dumps(spec, indent=2))
    model = VisualExpert(
        nn.Sequential(*list(YOLO(str(p)).model.model.children())[:5])
    ).to(dev)
    xs = []
    ys = []
    for m in meta["split_matches"]["train"]:
        data = pickle.loads((OUT / f"train-{m}.pkl").read_bytes())
        assert data["sha"] not in seen
        seen[data["sha"]] = m
        coverage["train"].update(data["audit"])
        for r in data["clips"]:
            indices = np.flatnonzero(r["ok"])
            lookup = {v: i for i, v in enumerate(indices)}
            pairs = [
                (lookup[j], mask)
                for j, mask in win.matched(r["frames"], r["hits"], 4)
                if j in lookup
            ]
            if not pairs:
                continue
            ids, labels = zip(*pairs)
            xs.append(r["rgb"][list(ids)])
            ys.append(np.stack(labels))
    X = torch.from_numpy(np.concatenate(xs))
    Y = torch.from_numpy(np.concatenate(ys))
    del xs, ys, data
    num = len(X)
    batch = 96
    steps = (num + batch - 1) // batch
    opt = torch.optim.AdamW(
        [
            {"params": model.backbone.parameters()},
            {
                "params": list(model.project.parameters())
                + list(model.head.parameters())
            },
        ],
        weight_decay=0.02,
    )
    lr = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=[0.00035, 0.0018], total_steps=prep.EPOCHS * steps
    )
    avg = torch.optim.swa_utils.AveragedModel(model)
    print("job", job, dev, "training contacts", num, flush=True)
    for epoch in range(prep.EPOCHS):
        model.train()
        for ids in np.array_split(rng.permutation(num), steps):
            x = X[ids].to(dev).float() / 255
            tg = Y[ids].to(dev).bool()
            if rng.random() < 0.5:
                x = x.flip((-1,))
            # Same lighting and displacement across all five moments of one contact.
            x = (
                x * (0.8 + 0.4 * torch.rand(len(x), 1, 1, 1, device=dev))
                + (torch.rand(len(x), 1, 1, 1, device=dev) - 0.5) * 0.15
            ).clamp(0, 1)
            o = model(x)
            loss = -o.log_softmax(1).masked_fill(~tg, -torch.inf).logsumexp(1).mean()
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 3)
            opt.step()
            lr.step()
        if epoch >= prep.EPOCHS - 5:
            avg.update_parameters(model)
        if (epoch + 1) % 4 == 0:
            print("epoch", epoch + 1, flush=True)
        progress(0.85 * (epoch + 1) / prep.EPOCHS)
    model = avg.module.eval()
    torch.save(
        {
            "state": model.state_dict(),
            "source_sha": POSE_SHA,
            "protocol_sha": prep.digest(OUT / "frozen-training.json"),
        },
        OUT / "expert.pt",
    )
    del X, Y
    items = []
    arms = {k: [] for k in ["ensemble", "window", "visual"]}
    validation_hashes = set()
    with torch.inference_mode():
        for m in meta["split_matches"]["validation"]:
            data = pickle.loads((OUT / f"validation-{m}.pkl").read_bytes())
            assert data["sha"] not in seen and data["sha"] not in validation_hashes
            validation_hashes.add(data["sha"])
            coverage["validation"].update(data["audit"])
            for r in data["clips"]:
                pred = r["pred"]
                fs = r["frames"]
                items.append((r["name"], None, r["hits"]))
                arms["ensemble"].append(pred)
                wp = dict(pred, family=pred["family"].copy())
                wp["family"][fs] = r["window"].argmax(1)
                arms["window"].append(wp)
                rp = dict(wp, family=wp["family"].copy())
                ok = r["ok"]
                if ok.any():
                    v = (
                        model(torch.from_numpy(r["rgb"]).to(dev).float() / 255)
                        .cpu()
                        .numpy()
                    )
                    rp["family"][np.array(fs)[ok]] = (
                        (1 - prep.ALPHA) * r["window"][ok] + prep.ALPHA * v
                    ).argmax(1)
                arms["visual"].append(rp)
    historic = json.loads((win.OUT / "report.json").read_text())["scores"]["shuttleset"]
    result = {}
    for j, t in enumerate((2, 4)):
        comp = {k: te.score(items, a, 0.7, t) for k, a in arms.items()}
        assert (
            comp["ensemble"] == historic[j]["baseline"]
            and comp["window"] == historic[j]["candidate"]
        ), "both historical baselines must reproduce"
        group = {
            k: counts(items, arms[k], arms["visual"], 0.7, t)
            for k in ("ensemble", "window")
        }
        result[t] = {
            "scores": comp,
            "weak_f1": {k: weak_f1(s) for k, s in comp.items()},
            "paired": group,
        }
    (OUT / "rgb-validation.json").write_text(
        json.dumps(
            {"coverage": dict(coverage), "training_examples": num, "results": result},
            indent=1,
        )
    )
    return {"report": str(OUT / "rgb-validation.json")}


if __name__ == "__main__":
    print(
        exp.run_local_job(
            exp.Store(exp.DATA), "rgb_stroke_training", "singles-rgb-v1", run
        )
    )
