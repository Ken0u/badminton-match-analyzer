"""Local four-player stroke-family expert; fixed contacts/partners, grouped comparisons."""

import argparse
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch
import train_doubles as td
import train_events as te
import train_stroke_sequence as exp
import train_stroke_window as win
from badminton.event_doubles import choose_partner
from torch import nn

OUT = exp.ROOT / ".cache/doubles-stroke-window-v1"
SEED = 761
EPOCHS = 32
ALPHA = 0.35


def fingerprint(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def freeze():
    OUT.mkdir(parents=True, exist_ok=True)
    files = defaultdict(list)
    splits = json.loads(td.DSHUTTLENET_SPLITS.read_text())
    excluded = set(splits["left_out"] + splits["test"])
    roots = [
        exp.ROOT / ".cache/step3/features/dshuttlenet",
        exp.ROOT / ".cache/s2doubles/features",
    ]
    for root in roots:
        for p in sorted(root.rglob("*.json.gz")):
            a = p.name.split("-")
            if a[0] not in ("ds", "s2"):
                continue
            m = int(a[1])
            if (a[0] == "ds" and m not in excluded) or (a[0] == "s2" and m == 2):
                files[p.name].append(p)
    take = []
    conflicts = {}
    for name, paths in sorted(files.items()):
        hs = {fingerprint(p) for p in paths}
        ds, match, *_ = name.split("-")
        match = int(match)
        if len(hs) != 1:
            # Repacked gzip may have identical contents; never pick a conflicting extraction.
            if (
                len(
                    {
                        hashlib.sha256(gzip.decompress(p.read_bytes())).hexdigest()
                        for p in paths
                    }
                )
                != 1
            ):
                conflicts[name] = sorted(hs)
                continue
        p = paths[0]
        fold = "validation" if ds == "s2" or match in splits["validation"] else "train"
        take.append([fold, ds, match, str(p.relative_to(exp.ROOT)), fingerprint(p)])
    meta = {
        "seed": SEED,
        "epochs": EPOCHS,
        "blend": ALPHA,
        "baseline": fingerprint(exp.ROOT / "models/weights/events_doubles.pt"),
        "previous": fingerprint(exp.ROOT / "models/weights/events_doubles_v4.pt"),
        "script_sha": fingerprint(Path(__file__)),
        "split_sha": fingerprint(td.DSHUTTLENET_SPLITS),
        "files": take,
        "conflicts_excluded_both_arms": conflicts,
        "gate": "DShuttleNet >=2 percentage point gain on six-family macro F1 & >=3 on supported weak families drive/lift/drop, positive paired correct change in >=4/6 matches; no regressions in complete-event F1 or S2 six-family macro F1. Matched accuracy is secondary. No separate push or block claim where labels are merged. Independent matches required before claiming acceptance.",
    }
    p = OUT / "protocol.json"
    s = json.dumps(meta, indent=1)
    if p.exists():
        assert p.read_text() == s
    else:
        p.write_text(s)
    return meta


def windows4(x, fs, slots, seg, valid):
    # Put the predicted hitter first. The partner is a separate stream; sort
    # opponents by horizontal position per frame, avoiding arbitrary track IDs.
    f = np.array(fs)
    left = np.maximum.reduce([np.zeros_like(f), f - 36, np.r_[0, f[:-1] + 1]])
    right = np.minimum.reduce(
        [np.full_like(f, len(x) - 1), f + 54, np.r_[f[1:] - 1, len(x) - 1]]
    )
    ix = np.rint(
        np.c_[np.linspace(left, f, 16).T, np.linspace(f, right, 25).T[:, 1:]]
    ).astype(int)
    v = x[ix]
    slots = np.array(slots)
    n = np.arange(len(f))[:, None]
    j = np.arange(40)[None, :]
    bs = v[:, :, : 4 * exp.PLAYER].reshape(len(f), 40, 4, exp.PLAYER)
    me = bs[n, j, slots[:, None]]
    mate = bs[n, j, (slots ^ 1)[:, None]]
    a = bs[n, j, ((1 - slots // 2) * 2)[:, None]]
    b = bs[n, j, ((1 - slots // 2) * 2 + 1)[:, None]]
    flip = a[:, :, 51:52] > b[:, :, 51:52]
    feet = np.stack(((me[:, :, 51] + me[:, :, 53]) / 2, me[:, :, 54]), 2)
    height = np.maximum(0.05, me[:, :, 54:55] - me[:, :, 52:53])
    sk = me[:, :, :51].reshape(len(f), 40, 17, 3)
    pose = np.concatenate(
        (
            (sk[:, :, :, :2] - feet[:, :, None, :])
            / height[:, :, :, None]
            * (sk[:, :, :, 2:] > 0),
            sk[:, :, :, 2:],
        ),
        3,
    ).reshape(len(f), 40, 51)
    ball = v[:, :, -6:]
    rel = (
        (ball[:, :, :2] - feet[:, 15:16])
        / height[:, 15:16]
        * ball[:, :, 2:3]
        * me[:, 15:16, 55:56]
    )
    dt = np.broadcast_to(
        np.stack((f - left, right - f), 1)[:, None] / 30, (len(f), 40, 2)
    )
    z = np.concatenate(
        (
            pose,
            me[:, :, 51:56],
            mate[:, :, 51:56],
            np.where(flip, b[:, :, 51:56], a[:, :, 51:56]),
            np.where(flip, a[:, :, 51:56], b[:, :, 51:56]),
            rel,
            ball,
            dt,
        ),
        2,
    )
    ok = (seg[ix] == seg[f, None]) & valid[ix] & valid[f, None]
    return (np.clip(z, -10, 10) * ok[:, :, None]).astype("f")


def load(p, base, prev, dev, fold):
    d = json.loads(gzip.decompress(p.read_bytes()))
    audit = Counter(refs=len(d["events"]))
    if abs(d["video"]["fps"] - 30) > 0.5:
        return None, audit
    x, h = td.doubles_clip(d)
    if not h:
        return None, audit
    w, ht = d["video"]["width"], d["video"]["height"]
    xx = torch.from_numpy(x)[None].to(dev)
    o = base(xx)
    pred = {
        "hit": o["hit"][0, :, 0].sigmoid().cpu().numpy(),
        **{k: o[k][0].argmax(1).cpu().numpy() for k in te.HEADS},
    }
    fs = te.peaks(pred["hit"], 0.7)
    old = (
        {**pred, "family": prev(xx)["family"][0].argmax(1).cpu().numpy()}
        if fold == "validation"
        else None
    )
    l = o["family"][0, fs].cpu().numpy()
    ends = o["hitter"][0].softmax(-1).reshape(-1, 2, 2).sum(-1).argmax(1).cpu().numpy()
    slots = []
    for f in fs:
        sl = choose_partner(x, f, te.COURT_ENDS[ends[f]], w, ht)
        slots.append(int(2 * ends[f] if sl is None else sl))
        pred["hitter"][f] = slots[-1]
    rows = d["players"]
    seg = np.searchsorted(
        sorted(d.get("cut_frames") or []), [r["frame"] for r in rows], side="right"
    )
    va = np.array([r.get("calibration_valid", False) for r in rows])
    z = windows4(x, fs, slots, seg, va) if fs else None
    audit["known_family"] = sum(t[2] >= 0 for t in h)
    audit["known_hitter"] = sum(t[1] >= 0 for t in h)
    audit["peaks"] = len(fs)
    return (d["clip_id"], h, pred, old, fs, z, l, va[fs]), audit


def scores(rows, method, tol):
    items = [(r[0], None, r[1]) for r in rows]
    ps = [r[method] for r in rows]
    raw = te.score(items, ps, 0.7, tol)
    tab = raw["family_confusion"]
    vals = {}
    for key in exp.FAMILIES:
        tp = tab.get(key, {}).get(key, 0)
        den = sum(tab.get(key, {}).values()) + sum(r.get(key, 0) for r in tab.values())
        vals[key] = 2 * tp / den if den else None
    known_actor = correct = joint = 0
    for (_, _, hits), p in zip(items, ps):
        fr = te.peaks(p["hit"], 0.7)
        used = set()
        for frame, hitter, fam, _, _, mask in hits:
            opts = [f for f in fr if f not in used and abs(f - frame) <= tol]
            if not opts:
                continue
            f = min(opts, key=lambda v: abs(v - frame))
            used.add(f)
            if hitter >= 0:
                known_actor += 1
                correct += int(p["hitter"][f] == hitter)
                joint += int(
                    fam >= 0 and p["hitter"][f] == hitter and mask[p["family"][f]]
                )
    return {
        "family_f1": vals,
        "six_macro": np.mean([vals[n] for n in exp.SIX if vals[n] is not None]),
        "weak_macro": np.mean(
            [vals[n] for n in ["drive", "lift", "drop"] if vals[n] is not None]
        ),
        "matched_correct": sum(v.get(k, 0) for k, v in tab.items()),
        "matched_known": sum(sum(v.values()) for v in tab.values()),
        "hitter_correct": correct,
        "hitter_denominator": known_actor,
        "joint_correct": joint,
        "historical_scorer": raw,
    }


def run(job, progress):
    meta = freeze()
    assert not (OUT / "report.json").exists()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(2)
    torch.manual_seed(SEED)
    rng = np.random.default_rng(SEED)
    models = []
    for name in ["events_doubles.pt", "events_doubles_v4.pt"]:
        s = torch.load(
            exp.ROOT / "models/weights" / name, map_location="cpu", weights_only=True
        )
        m = exp.from_checkpoint(s).to(dev).eval()
        m.load_state_dict(s["state"])
        models.append(m)
    audits = defaultdict(Counter)
    test = defaultdict(list)
    files = meta["files"]
    xs = []
    ys = []
    print("job", job, dev, flush=True)
    for fold in ("train", "validation"):
        selected = [r for r in files if r[0] == fold]
        for i, (_, ds, match, rel, sha) in enumerate(selected):
            p = exp.ROOT / rel
            assert fingerprint(p) == sha
            if i % 500 == 0:
                print(fold, i, len(selected), flush=True)
                progress(
                    (0.5 if fold == "train" else 0.15) * i / len(selected)
                    + (0 if fold == "train" else 0.83)
                )
            with torch.inference_mode():
                rec, audit = load(p, *models, dev, fold)
            audits[f"{fold}/{ds}"].update(audit)
            if rec is None:
                audits[f"{fold}/{ds}"]["excluded_refs"] += audit["refs"]
                continue
            name, h, pred, old, fs, z, logits, ok = rec
            if fold == "train":
                for j, mask in win.matched(fs, h, 4):
                    if ok[j]:
                        xs.append(z[j].astype("e"))
                        ys.append(mask)
            else:
                new = dict(pred, family=pred["family"].copy())
                if fs:
                    with torch.inference_mode():
                        adj = expert(torch.from_numpy(z).to(dev)).cpu().numpy()
                        bl = (1 - ALPHA) * logits + ALPHA * adj
                        idx = np.array(fs)[ok]
                        new["family"][idx] = bl[ok].argmax(1)
                test[ds].append((name, h, pred, old, new))
        if fold == "train":
            X = torch.from_numpy(np.stack(xs)).to(dev)
            Y = torch.from_numpy(np.stack(ys)).to(dev).bool()
            del xs, ys
            expert = win.Expert(X.shape[-1], exp.K).to(dev)
            opt = torch.optim.AdamW(expert.parameters(), lr=0.002, weight_decay=0.012)
            steps = (len(X) + 191) // 192
            lr = torch.optim.lr_scheduler.OneCycleLR(
                opt, max_lr=0.002, total_steps=EPOCHS * steps
            )
            avg = torch.optim.swa_utils.AveragedModel(expert)
            print("fit", len(X), flush=True)
            for ep in range(EPOCHS):
                for idx in np.array_split(rng.permutation(len(X)), steps):
                    out = expert(X[idx].float())
                    loss = (
                        -out.log_softmax(1)
                        .masked_fill(~Y[idx], -torch.inf)
                        .logsumexp(1)
                        .mean()
                    )
                    opt.zero_grad()
                    loss.backward()
                    nn.utils.clip_grad_norm_(expert.parameters(), 3)
                    opt.step()
                    lr.step()
                if ep >= EPOCHS - 6:
                    avg.update_parameters(expert)
            expert = avg.module.eval()
            torch.save(
                {
                    "state": expert.state_dict(),
                    "dim": X.shape[-1],
                    "protocol_sha": fingerprint(OUT / "protocol.json"),
                },
                OUT / "expert.pt",
            )
            audits["train/ds"]["fit_contacts"] = len(X)
            del X, Y
            progress(0.83)
    report = {"audit": dict(audits), "corpora": {}}
    for ds, rows in test.items():
        report["corpora"][ds] = {}
        for tol in [2, 4]:
            vals = {
                key: scores(rows, j, tol)
                for key, j in [("v5", 2), ("v4_same_contacts", 3), ("new", 4)]
            }
            vals["per_match_correct"] = {
                k: [
                    scores([r for r in rows if r[0].split("-")[1] == k], j, tol)[
                        "matched_correct"
                    ]
                    for j in (2, 4)
                ]
                for k in sorted({r[0].split("-")[1] for r in rows})
            }
            report["corpora"][ds][tol] = vals
    (OUT / "report.json").write_text(json.dumps(report, indent=1))
    return {"report": str(OUT / "report.json")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    args = ap.parse_args()
    if args.freeze:
        m = freeze()
        print(
            Counter((r[0], r[1]) for r in m["files"]),
            len(m["conflicts_excluded_both_arms"]),
        )
    else:
        print(
            exp.run_local_job(
                exp.Store(exp.DATA), "doubles_stroke_training", "doubles-stroke-v1", run
            )
        )
