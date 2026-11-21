"""One-way lift/push specialist using predicted contact timing, no reference context at inference."""

import json
import pickle
from collections import Counter

import numpy as np
import prepare_stroke_rgb as base
import probe_stroke_source_contrast as probe
import torch
from evaluate_stroke_transfer_dev import bindings

exp = base.exp
OUT = exp.ROOT / ".cache/lift-push-route-v1"
LIFT = exp.FAMILIES.index("lift")
PUSH = exp.FAMILIES.index("push")
THRESH = 0.75


def describe(t, v, seg, ok, j):
    out = []
    if not ok[j]:
        return None
    for a, b in [
        (-0.40, -0.12),
        (-0.12, 0.05),
        (0.05, 0.22),
        (0.22, 0.45),
        (0.45, 0.72),
    ]:
        ix = (t - t[j] >= a) & (t - t[j] < b) & (seg == seg[j]) & ok
        z = v[ix]
        tt = t[ix] - t[j]
        seen = z[:, -1] > 0
        out.append(seen.sum() / max(1, len(z)))
        vals = z[seen, -3:-1]
        out.extend(np.median(vals, axis=0) if len(vals) else [0, 0])
        out.extend(
            np.clip(np.polyfit(tt[seen], vals, 1)[0], -5, 5)
            if len(vals) >= 3 and np.ptp(tt[seen]) > 0.035
            else [0, 0]
        )
        for slot in range(2):
            h = z[:, slot * exp.PLAYER : (slot + 1) * exp.PLAYER]
            det = h[:, 55] > 0
            out.extend(np.median(h[det, 51:55], axis=0) if det.any() else [0] * 4)
    return out


def predict(model, x):
    return x is not None and float(
        np.clip((x - model["mean"]) / model["std"], -5, 5) @ model["w"] + model["b"]
    ) >= np.log(THRESH / (1 - THRESH))


def fit(data):
    X, y = map(
        np.array, zip(*[(x, int(k == "push")) for x, k, m in data if x is not None])
    )
    mean, std = X.mean(0), X.std(0).clip(0.05)
    X = torch.tensor(np.clip((X - mean) / std, -5, 5), dtype=torch.float64)
    y = torch.tensor(y, dtype=torch.float64)
    w = torch.zeros(X.shape[1], dtype=torch.float64, requires_grad=True)
    b = torch.zeros((), dtype=torch.float64, requires_grad=True)
    opt = torch.optim.LBFGS([w, b], max_iter=60, line_search_fn="strong_wolfe")

    def closure():
        opt.zero_grad()
        loss = (
            torch.nn.functional.binary_cross_entropy_with_logits(X @ w + b, y)
            + 0.15 * w.square().sum()
        )
        loss.backward()
        return loss

    opt.step(closure)
    return {"mean": mean, "std": std, "w": w.detach().numpy(), "b": b.item()}


def run(job, progress):
    torch.set_num_threads(1)
    OUT.mkdir(exist_ok=True)
    assert not (OUT / "model.npz").exists()
    dataset = probe.OUT / "train-taxonomy.json"
    rows = json.loads(dataset.read_bytes())["examples"]
    raw = {}
    data = []
    packs = json.loads((base.OUT / "frozen-training.json").read_bytes())["packs"]
    audit = Counter()
    for fid, m in [("0033", 29), ("0034", 30), ("0035", 6), ("0036", 4)]:
        p = base.OUT / f"train-{m}.pkl"
        assert base.digest(p) == packs[p.name]
        clips = {r["name"]: r for r in pickle.loads(p.read_bytes())["clips"]}
        fr = json.loads((probe.OUT / (fid + "_updated.json")).read_bytes())
        for row in rows:
            if row["ss"] != m:
                continue
            clip = f"ss-{m}-{row['set']}-{row['rally']}"
            rec = clips.get(clip)
            audit["all_paired_labels"] += 1
            if rec is None:
                continue
            if clip not in raw:
                f, t, v, seg, ok = probe.arrays(m, row["set"], row["rally"])
                fs = rec["frames"]
                ix = [int(abs(t - (t[0] + j / 30)).argmin()) for j in fs]
                on = f[ix].tolist()
                rallies = [
                    r
                    for r in fr
                    if r["start_frame"] <= row["interval"][0] <= r["end_frame"]
                ]
                assert len(rallies) == 1
                h = rallies[0]["hitting"]
                bounds = [(z["start_frame"], z["end_frame"]) for z in h]
                bound = bindings(bounds, on)
                raw[clip] = dict(zip(bounds, bound))
            j = raw[clip].get(tuple(row["interval"]))
            if j is None:
                continue
            audit["bound"] += 1
            if int(rec["window"][j].argmax()) != LIFT:
                continue
            f, t, v, seg, ok = probe.arrays(m, row["set"], row["rally"])
            idx = int(abs(t - (t[0] + rec["frames"][j] / 30)).argmin())
            data.append((describe(t, v, seg, ok, idx), row["fine_family"], m))
    cv = {}
    for m in (4, 6, 29, 30):
        model = fit([r for r in data if r[2] != m])
        ct = Counter()
        for x, k, group in data:
            if group != m:
                continue
            fire = predict(model, x)
            ct["routed_lifts"] += 1
            ct["changed"] += int(fire)
            ct["fixed"] += int(fire and k == "push")
            ct["introduced"] += int(fire and k == "lift")
        cv[m] = ct
    model = fit(data)
    np.savez(OUT / "model.npz", **model)
    (OUT / "report.json").write_text(
        json.dumps(
            {
                "cv": cv,
                "audit": audit,
                "fit_rows": len(data),
                "target_counts": Counter(k for _, k, _ in data),
                "taxonomy_sha": base.digest(dataset),
                "model_sha": base.digest(OUT / "model.npz"),
            },
            indent=2,
        )
    )
    return cv


if __name__ == "__main__":
    print(
        exp.run_local_job(
            exp.Store(exp.DATA), "stroke_route_fit", "lift-push-route-v1", run
        )
    )
