"""Train-only cross-source label diagnostic: can observed play distinguish disagreements?"""

import gzip
import json
from collections import Counter
from functools import lru_cache

import numpy as np
import torch
import train_stroke_sequence as exp
from badminton.event_model import observations

ROOT = exp.ROOT
OUT = ROOT / ".cache/stroke-source-audit"


@lru_cache(maxsize=16)
def arrays(m, s, r):
    d = json.loads(
        gzip.decompress((exp.FEATURE / f"ss-{m}-{s}-{r}.json.gz").read_bytes())
    )
    assert d["split"] == "train" and d["match_id"] == m
    rows = d["players"]
    f = np.array([x["frame"] for x in rows])
    t = np.array([x["time_s"] for x in rows])
    v, _ = observations(rows, d["shuttle"], d["video"]["width"], d["video"]["height"])
    return (
        f,
        t,
        v,
        np.searchsorted(sorted(d.get("cut_frames") or []), f, side="right"),
        np.array([x.get("calibration_valid", False) for x in rows]),
    )


def descriptor(r):
    f, t, v, seg, ok = arrays(r["ss"], r["set"], r["rally"])
    j = np.where(f == r["native_frame"])[0]
    out = []
    if len(j) != 1:
        return None
    j = int(j[0])
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


def run(job, progress):
    torch.set_num_threads(1)
    rows = json.loads((OUT / "train-taxonomy.json").read_bytes())["examples"]
    res = {}
    for src, alt in [("lift", "push"), ("net", "block")]:
        pool = [
            r for r in rows if r["ss_family"] == src and r["fine_family"] in (src, alt)
        ]
        data = [(r, descriptor(r)) for r in pool]
        per = {}
        for m in sorted({r["ss"] for r in pool}):
            fit = [
                (x, int(r["fine_family"] == alt))
                for r, x in data
                if r["ss"] != m and x is not None
            ]
            test = [(x, int(r["fine_family"] == alt)) for r, x in data if r["ss"] == m]
            X, y = map(np.array, zip(*fit))
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
            prior = int(float(y.mean()) >= 0.5)
            ct = Counter()
            for x, label in test:
                pred = (
                    prior
                    if x is None
                    else int(
                        float(
                            np.clip((x - mean) / std, -5, 5) @ w.detach().numpy()
                            + b.item()
                        )
                        >= 0
                    )
                )
                ct["total"] += 1
                ct["correct"] += int(pred == label)
                ct["prior_correct"] += int(prior == label)
                ct["fixed"] += int(pred == label != prior)
                ct["introduced"] += int(prior == label != pred)
                ct["missing"] += int(x is None)
            per[m] = dict(ct)
        res[src] = {
            "per_training_match": per,
            "totals": dict(sum((Counter(v) for v in per.values()), Counter())),
            "excluded_third_labels": sum(
                r["ss_family"] == src and r["fine_family"] not in (src, alt)
                for r in rows
            ),
        }
    d = {
        "scope": "Leave-one-training-match-out across four duplicate broadcasts: source-family and rough timing supplied, predict second publisher label only. Not product performance. Unknown descriptors fallback to training prior. No test data or Korea access.",
        "results": res,
    }
    dest = OUT / "source-contrast-probe.json"
    dest.open("x").write(json.dumps(d, indent=2))
    return res


if __name__ == "__main__":
    print(
        exp.run_local_job(
            exp.Store(exp.DATA),
            "stroke_taxonomy_diagnostic",
            "training-label-contrast",
            run,
        )
    )
