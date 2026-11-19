"""Train a contact-centered singles motion expert and compare to the frozen ensemble.

Local research only. No model installation and no test-split inference.
"""

import gzip
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import torch
import train_events as te
import train_stroke_sequence as exp
from replay_stroke_family_validation import counts
from torch import nn

OUT = exp.ROOT / ".cache/stroke-window-v1"
PIN = "654d3abe534d40f0bf3985d6941426be5635719aad5d23b14d84bc19c7bf4b17"
EPOCHS = 32
SEED = 2483
ALPHA = 0.35


def source_files():
    groups = json.loads(te.GROUPS.read_text())["source_groups"]
    ids = {
        m.split(":")[1]: g["fold"]
        for g in groups
        for m in g["members"]
        if m.startswith("train:") and g["fold"] in ("train", "validation")
    }
    ss = {}
    with (exp.ROOT / "data/datasets/shuttleset/index/strokes.jsonl").open(
        encoding="utf8"
    ) as f:
        for r in map(json.loads, f):
            ss.setdefault(r["match_id"], set()).add(r["split"])
    files = [
        (fold, "aicup", exp.ROOT / ".cache/training-run1/features" / f"{m}.json.gz")
        for m, fold in sorted(ids.items())
    ]
    files.extend(
        (next(iter(ss[k])), "shuttleset", p)
        for p in sorted(exp.FEATURE.glob("ss-*.json.gz"))
        if (k := int(p.name.split("-")[1])) in ss
        and ss[k] in ({"train"}, {"validation"})
    )
    return files


def windows(x, frames, ends, segment, valid):
    # 16 incoming + 24 outgoing bins normalized to adjacent *predicted* contacts.
    f = np.asarray(frames)
    left = np.maximum.reduce([np.zeros_like(f), f - 36, np.r_[0, f[:-1] + 1]])
    right = np.minimum.reduce(
        [np.full_like(f, len(x) - 1), f + 54, np.r_[f[1:] - 1, len(x) - 1]]
    )
    ix = np.rint(
        np.concatenate(
            (np.linspace(left, f, 16).T, np.linspace(f, right, 25).T[:, 1:]), 1
        )
    ).astype(int)
    v = x[ix]
    ok = (segment[ix] == segment[f, None]) & valid[ix] & valid[f, None]
    e = ends[f]
    bl = v[:, :, : 2 * exp.PLAYER].reshape(len(f), 40, 2, exp.PLAYER)
    n = np.arange(len(f))[:, None]
    j = np.arange(40)[None, :]
    me = bl[n, j, e[:, None]]
    other = bl[n, j, 1 - e[:, None]]
    feet = np.stack(((me[:, :, 51] + me[:, :, 53]) / 2, me[:, :, 54]), 2)
    h = np.maximum(0.05, me[:, :, 54] - me[:, :, 52])
    present = me[:, :, 55:56]
    sk = me[:, :, :51].reshape(len(f), 40, 17, 3)
    norm = (sk[:, :, :, :2] - feet[:, :, None, :]) / h[:, :, None, None]
    pose = np.concatenate((norm * (sk[:, :, :, 2:] > 0), sk[:, :, :, 2:]), 3).reshape(
        len(f), 40, 51
    )
    ball = v[:, :, -6:]
    seen = ball[:, :, 2:3]
    center = feet[:, 15:16]
    height = h[:, 15:16, None]
    rel = (ball[:, :, :2] - center) / height * seen * present[:, 15:16]
    vel = ball[:, :, 3:5] * 30 / height * ball[:, :, 5:6]
    direction = np.broadcast_to((2 * e - 1)[:, None, None], seen.shape)
    dt = np.stack((f - left, right - f), 1) / 30
    dt = np.broadcast_to(dt[:, None], (len(f), 40, 2))
    z = np.concatenate(
        (pose, feet, present, other[:, :, 51:56], rel, vel, ball, dt, direction), 2
    )
    return (np.clip(z, -10, 10) * ok[:, :, None]).astype(np.float32)


class Expert(nn.Module):
    def __init__(self, d, k):
        super().__init__()
        self.input = nn.Sequential(nn.Conv1d(d, 80, 1), nn.BatchNorm1d(80), nn.SiLU())
        self.blocks = nn.ModuleList(
            [
                nn.Sequential(
                    nn.Conv1d(80, 80, 3, padding=i, dilation=i),
                    nn.BatchNorm1d(80),
                    nn.SiLU(),
                    nn.Dropout(0.12),
                    nn.Conv1d(80, 80, 1),
                )
                for i in (1, 2, 4)
            ]
        )
        self.head = nn.Sequential(
            nn.Linear(80 * 5, 128),
            nn.LayerNorm(128),
            nn.SiLU(),
            nn.Dropout(0.25),
            nn.Linear(128, k),
        )

    def forward(self, x):
        h = self.input(x.transpose(1, 2))
        for b in self.blocks:
            h = h + b(h)
        return self.head(
            torch.cat(
                [
                    h[:, :, a:b].mean(2)
                    for a, b in [(0, 9), (9, 15), (14, 18), (18, 29), (29, 40)]
                ],
                1,
            )
        )


def load_doc(p, ds):
    d = json.loads(gzip.decompress(p.read_bytes()))
    x, h = te.aicup_clip(d) if ds == "aicup" else te.shuttleset_clip(d)
    if not h:
        return None
    rows = d["players"]
    times = np.array([r["time_s"] for r in rows])
    n = len(x)
    grid = times[0] + np.arange(n) / 30
    idx = np.searchsorted(times, grid).clip(0, len(rows) - 1)
    native = np.array([r["frame"] for r in rows])
    cuts = d.get("cut_frames") or []
    seg = np.searchsorted(sorted(cuts), native[idx], side="right")
    valid = np.array([r.get("calibration_valid", True) for r in rows], bool)[idx]
    return (d["clip_id"], x, h), seg, valid


def matched(frames, hits, tol):
    f = np.array(frames)
    used = set()
    for target in hits:
        opts = [j for j in np.flatnonzero(abs(f - target[0]) <= tol) if j not in used]
        if opts:
            j = min(opts, key=lambda i: abs(f[i] - target[0]))
            used.add(j)
            if target[2] >= 0:
                yield j, target[-1]


def run(job, progress):
    OUT.mkdir(parents=True, exist_ok=True)
    assert not (OUT / "report.json").exists(), "Preserve completed research run"
    path = exp.OUT / "singles_family_ensemble.ts"
    assert exp.sha(path) == PIN
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(2)
    torch.manual_seed(SEED)
    rng = np.random.default_rng(SEED)
    files = source_files()
    base = exp.MODELS[0]
    s = torch.load(base, map_location=device, weights_only=True)
    m = exp.from_checkpoint(s).to(device).eval()
    m.load_state_dict(s["state"])
    th = s["threshold"]
    train = [(ds, p) for split, ds, p in files if split == "train"]
    inventory = Counter()
    protocol = {
        "baseline": PIN,
        "epochs": EPOCHS,
        "alpha": ALPHA,
        "seed": SEED,
        "script_sha": exp.sha(Path(__file__)),
        "scorer_sha": exp.sha(Path(te.__file__)),
        "threshold": th,
        "gate": "both historical 2-frame family macro F1 improve, no matched accuracy loss in either corpus; report 4 frames and per-match results, no post-validation tuning",
        "splits": dict(Counter(f"{split}/{ds}" for split, ds, _ in files)),
    }
    (OUT / "protocol.json").write_text(json.dumps(protocol, indent=2))
    print("job", job, device, "training clips", len(train), flush=True)
    X = []
    Y = []
    with torch.inference_mode():
        for i, (ds, p) in enumerate(train):
            if i % 500 == 0:
                print("extract", i, len(train), flush=True)
                progress(0.55 * i / len(train))
            result = load_doc(p, ds)
            if result is None:
                continue
            (_, x, h), seg, valid = result
            o = m(torch.from_numpy(x)[None].to(device))
            frames = te.peaks(o["hit"][0, :, 0].sigmoid().cpu().numpy(), th)
            pairs = list(matched(frames, h, 4))
            if not pairs:
                continue
            ix, labels = zip(*pairs)
            z = windows(x, frames, o["hitter"][0].argmax(1).cpu().numpy(), seg, valid)
            X.append(z[list(ix)].astype(np.float16))
            Y.append(np.stack(labels))
            inventory[ds + "_train_contacts"] += len(labels)
    x = torch.tensor(np.concatenate(X), device=device)
    y = torch.tensor(np.concatenate(Y), device=device)
    del X, Y
    model = Expert(x.shape[-1], exp.K).to(device)
    avg = torch.optim.swa_utils.AveragedModel(model)
    opt = torch.optim.AdamW(model.parameters(), lr=0.0015, weight_decay=0.012)
    steps = math.ceil(len(y) / 192)
    lr = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=0.002, total_steps=EPOCHS * steps
    )
    print("train", dict(inventory), flush=True)
    for epoch in range(EPOCHS):
        model.train()
        for ids in np.array_split(rng.permutation(len(y)), steps):
            xx = x[ids].float()
            mask = y[ids].bool()
            out = model(xx)
            loss = -torch.logsumexp(
                out.log_softmax(1).masked_fill(~mask, -torch.inf), 1
            ).mean()
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 3)
            opt.step()
            lr.step()
        if epoch >= EPOCHS - 6:
            avg.update_parameters(model)
        if epoch % 8 == 7:
            print("epoch", epoch + 1, flush=True)
        progress(0.55 + 0.3 * (epoch + 1) / EPOCHS)
    model = avg.module.eval()
    torch.save(
        {
            "state": model.state_dict(),
            "dim": x.shape[-1],
            "families": exp.FAMILIES,
            "protocol": protocol,
        },
        OUT / "expert.pt",
    )
    del x, y
    frozen = torch.jit.load(str(path), map_location=device).eval()
    teacher = exp.ROOT / "models/weights/events_v2.pt"
    report = {}
    archive = json.loads((exp.OUT / "historical-validation-replay.json").read_text())[
        "results"
    ]
    with torch.inference_mode():
        for ds in ["aicup", "shuttleset"]:
            raw = [
                i
                for split, src, p in files
                if split == "validation"
                and src == ds
                and (i := load_doc(p, ds)) is not None
            ]
            refs = [v[0] for v in raw]
            if ds == "shuttleset":
                refs = te.snap(refs, teacher, device)
            items = []
            ba = []
            ca = []
            for (_, seg, valid), item in zip(raw, refs):
                name, xx, h = te.steady_ends(item)
                shift = h[0][0] - item[2][0][0]
                ix = np.arange(len(xx)) - shift
                seg = seg[ix.clip(0, len(seg) - 1)]
                valid = (
                    valid[ix.clip(0, len(valid) - 1)] & (ix >= 0) & (ix < len(item[1]))
                )
                items.append((name, xx, h))
                outs = frozen(torch.from_numpy(xx)[None].to(device))
                old = {
                    k: o[0].argmax(1).cpu().numpy()
                    for k, o in zip(["hitter", "family", "side", "serve"], outs[1:])
                }
                old["hit"] = outs[0][0, :, 0].sigmoid().cpu().numpy()
                frames = te.peaks(old["hit"], th)
                new = dict(old, family=old["family"].copy())
                if frames:
                    z = windows(xx, frames, old["hitter"], seg, valid)
                    other = model(torch.from_numpy(z).to(device))
                    blend = (1 - ALPHA) * outs[2][0, frames] + ALPHA * other
                    new["family"][frames] = (
                        torch.where(
                            torch.from_numpy(valid[frames]).to(device),
                            blend.argmax(1),
                            outs[2][0, frames].argmax(1),
                        )
                        .cpu()
                        .numpy()
                    )
                ba.append(old)
                ca.append(new)
            report[ds] = []
            for j, t in enumerate((2, 4)):
                b = te.score(items, ba, th, t)
                c = te.score(items, ca, th, t)
                assert b == archive[ds]["comparisons"][j]["candidate"], (
                    f"{ds} baseline replay mismatch"
                )
                groups = counts(items, ba, ca, th, t)
                report[ds].append({"baseline": b, "candidate": c, "groups": groups})
                print(
                    ds,
                    t,
                    b["family_macro_f1_on_matched"],
                    c["family_macro_f1_on_matched"],
                    flush=True,
                )
    (OUT / "report.json").write_text(
        json.dumps({"inventory": dict(inventory), "scores": report}, indent=2)
    )
    return {"report": str(OUT / "report.json")}


if __name__ == "__main__":
    print(
        exp.run_local_job(
            exp.Store(exp.DATA), "stroke_window_training", "stroke-window-v1", run
        )
    )
