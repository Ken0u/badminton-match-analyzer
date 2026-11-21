"""Learn from hitter, court, shuttle-centered imagery and observed flight on train sources only."""

import json
import pickle
from pathlib import Path

import numpy as np
import prepare_stroke_flight_video as prep
import torch
from replay_stroke_family_validation import counts
from torch import nn
from train_stroke_rgb import weak_f1

old = prep.old
exp = prep.exp
OUT = prep.OUT
BLEND = 0.35


class Branch(nn.Sequential):
    def __init__(self, n):
        super().__init__(
            nn.Conv2d(n, 24, 5, 2, 2),
            nn.GroupNorm(4, 24),
            nn.SiLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(24, 48, 3, 2, 1),
            nn.GroupNorm(6, 48),
            nn.SiLU(),
            nn.Conv2d(48, 64, 3, 2, 1),
            nn.GroupNorm(8, 64),
            nn.SiLU(),
            nn.AdaptiveAvgPool2d((2, 2)),
            nn.Flatten(),
        )


class FlightVideo(nn.Module):
    def __init__(self):
        super().__init__()
        self.actor = Branch(9)
        self.court = Branch(17)
        self.flight = Branch(17)
        self.head = nn.Sequential(
            nn.Linear(3 * 256 + 9 * 4 + 19, 192),
            nn.LayerNorm(192),
            nn.SiLU(),
            nn.Dropout(0.35),
            nn.Linear(192, exp.K),
        )

    def forward(self, x, c, v):
        branches = []
        for enc, start, stop, mask in [
            (self.court, 0, 9, v[:, :9]),
            (self.flight, 9, 18, v[:, 9:18]),
            (self.actor, 18, 23, v[:, 18:19].expand(-1, 5)),
        ]:
            a = x[:, start:stop].float() / 255
            diff = (a[:, 1:] - a[:, :-1]) * (mask[:, 1:] * mask[:, :-1])[
                :, :, None, None
            ]
            branches.append(enc(torch.cat([a, diff], 1)))
        return self.head(torch.cat([*branches, c.flatten(1), v.float()], 1))


def records(m, protocol):
    p = old.OUT / f"train-{m}.pkl"
    assert old.digest(p) == protocol["train_input_sha"][str(m)]
    base = pickle.loads(p.read_bytes())
    flight = pickle.loads((OUT / f"{m}.pkl").read_bytes())
    assert base["sha"] == flight["source"]
    assert len(base["clips"]) == len(flight["clips"])
    for r, (clip, j, n) in zip(base["clips"], flight["clips"]):
        assert r["name"] == clip and len(r["frames"]) == n
        valid = flight["valid"][j : j + n]
        c = flight["coords"][j : j + n].copy()
        c[:, :, :3] *= valid[:, 9:, None]
        v = np.c_[valid, r["ok"]]
        x = np.zeros((n, 23, 72, 72), np.uint8)
        x[:, :18] = flight["pixels"][j : j + n]
        x[r["ok"], 18:] = r["rgb"]
        yield r, x, c, v, valid[:, :9].sum(1) >= 4


def run(job, progress):
    proto = json.loads((OUT / "protocol.json").read_bytes())
    assert old.digest(Path(prep.__file__)) == proto["preparer"]
    assert not (OUT / "diagnostic.json").exists()
    assert not (OUT / "candidate.pt").exists()
    assert set(proto["fit_matches"]).isdisjoint(proto["diagnostic_matches"])
    d = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(2)
    torch.manual_seed(904)
    rng = np.random.default_rng(904)
    spec = {
        "trainer_sha": old.digest(Path(__file__)),
        "protocol_sha": old.digest(OUT / "protocol.json"),
        "pack_sha": {
            m: old.digest(OUT / f"{m}.pkl")
            for m in proto["fit_matches"] + proto["diagnostic_matches"]
        },
        "blend": BLEND,
        "epochs": 24,
        "selection": "fixed final four epochs averaged, 2-frame primary; none selected by diagnostic outcomes",
    }
    (OUT / "fit-spec.json").write_text(json.dumps(spec, indent=2))
    arrays = [[] for _ in range(4)]
    for m in proto["fit_matches"]:
        for r, x, c, v, ok in records(m, proto):
            pairs = [
                (i, y) for i, y in old.win.matched(r["frames"], r["hits"], 4) if ok[i]
            ]
            if not pairs:
                continue
            ix, y = zip(*pairs)
            idx = list(ix)
            for bucket, a in zip(arrays, (x[idx], c[idx], v[idx], np.stack(y))):
                bucket.append(a)
    X, C, V, Y = [torch.from_numpy(np.concatenate(b)) for b in arrays]
    del arrays
    model = FlightVideo().to(d)
    avg = torch.optim.swa_utils.AveragedModel(model)
    opt = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.02)
    steps = (len(X) + 95) // 96
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=0.001, total_steps=steps * 24
    )
    for ep in range(24):
        model.train()
        for ids in np.array_split(rng.permutation(len(X)), steps):
            x = X[ids].to(d)
            c = C[ids].to(d)
            v = V[ids].to(d)
            if rng.random() < 0.5:
                x = x.flip((-1,))
                c[:, :, 0] = torch.where(c[:, :, 2] > 0, 1 - c[:, :, 0], 0)
            o = model(x, c, v)
            loss = (
                -o.log_softmax(1)
                .masked_fill(~Y[ids].to(d).bool(), -torch.inf)
                .logsumexp(1)
                .mean()
            )
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 3)
            opt.step()
            sched.step()
        if ep >= 20:
            avg.update_parameters(model)
        progress(0.85 * (ep + 1) / 24)
        if ep % 4 == 3:
            print("epoch", ep + 1, flush=True)
    net = avg.module.eval()
    torch.save(
        {"state": net.state_dict(), "fit_spec_sha": old.digest(OUT / "fit-spec.json")},
        OUT / "candidate.pt",
    )
    items = []
    arms = {k: [] for k in ("ensemble", "window", "flight")}
    with torch.inference_mode():
        for m in proto["diagnostic_matches"]:
            for r, x, c, v, ok in records(m, proto):
                items.append((r["name"], None, r["hits"]))
                base = r["pred"]
                fs = np.asarray(r["frames"], dtype=int)
                wp = dict(base, family=base["family"].copy())
                wp["family"][fs] = r["window"].argmax(1)
                fp = dict(wp, family=wp["family"].copy())
                if ok.any():
                    z = (
                        net(*(torch.from_numpy(a[ok]).to(d) for a in (x, c, v)))
                        .cpu()
                        .numpy()
                    )
                    fp["family"][fs[ok]] = (
                        (1 - BLEND) * r["window"][ok] + BLEND * z
                    ).argmax(1)
                for k, a in zip(arms, (base, wp, fp)):
                    arms[k].append(a)
    report = {
        "fit_contacts": len(X),
        "scope": "training tournament diagnostic only; frozen incumbents saw these matches",
        "tolerances": {},
    }
    for t in (2, 4):
        scores = {k: old.te.score(items, a, 0.7, t) for k, a in arms.items()}
        report["tolerances"][t] = {
            "scores": scores,
            "weak": {k: weak_f1(s) for k, s in scores.items()},
            "paired": {
                k: counts(items, arms[k], arms["flight"], 0.7, t)
                for k in ("ensemble", "window")
            },
        }
    (OUT / "diagnostic.json").write_text(json.dumps(report, indent=2))
    return {"fit_contacts": len(X), "diagnostic_matches": proto["diagnostic_matches"]}


if __name__ == "__main__":
    print(
        exp.run_local_job(
            exp.Store(exp.DATA), "stroke_flight_video_fit", "flight-video-v2-fit", run
        )
    )
