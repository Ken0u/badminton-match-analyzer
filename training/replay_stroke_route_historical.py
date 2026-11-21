"""Paired no-retuning replay of frozen lift router on the historical ShuttleSet validation."""

import gzip
import json
import pickle

import numpy as np
import torch
import train_stroke_lift_route as route
from replay_stroke_family_validation import counts

base = route.base
exp = base.exp
te = base.te


def run(job, progress):
    fp = route.OUT / "historical-shuttleset.json"
    assert not fp.exists()
    freeze = json.loads(
        (
            exp.ROOT / ".cache/stroke-transfer-dev-0043/candidate-freeze.json"
        ).read_bytes()
    )
    p = route.OUT / "model.npz"
    assert base.digest(p) == freeze["router_sha256"]
    model = dict(np.load(p))
    items = []
    arms = {k: [] for k in ("ensemble", "window", "routed")}
    dv = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(2)
    ts = torch.load(
        exp.ROOT / "models/weights/events_v2.pt", map_location="cpu", weights_only=True
    )
    teacher = exp.from_checkpoint(ts).to(dv).eval()
    teacher.load_state_dict(ts["state"])
    meta = json.loads((base.OUT / "frozen-training.json").read_bytes())
    wanted = {
        n: h
        for split, corpus, n, h in json.loads(
            (base.win.OUT / "feature-inputs.json").read_bytes()
        )
        if split == "validation" and corpus == "shuttleset"
    }
    with torch.inference_mode():
        for i, m in enumerate([35, 36, 37, 38, 41]):
            p = base.OUT / f"validation-{m}.pkl"
            assert base.digest(p) == meta["packs"][p.name]
            records = pickle.loads(p.read_bytes())["clips"]
            for r in records:
                src = exp.FEATURE / (r["name"] + ".json.gz")
                assert base.digest(src) == wanted[src.name]
                d = json.loads(gzip.decompress(src.read_bytes()))
                assert d["match_id"] == m and d["split"] == "validation"
                xx, h = te.shuttleset_clip(d)
                fr = te.peaks(
                    teacher(torch.from_numpy(xx)[None].to(dv))["hit"][0, :, 0]
                    .sigmoid()
                    .cpu()
                    .numpy(),
                    ts["threshold"],
                )
                used = set()
                snapped = []
                for f, *tail in h:
                    opts = [
                        j
                        for j in fr
                        if j not in used and abs(j - f) <= round(te.SNAP_S * 30)
                    ]
                    new = min(opts, key=lambda j: abs(f - j)) if opts else f
                    if opts:
                        used.add(new)
                    snapped.append((new, *tail))
                _, cut, moved = te.steady_ends((r["name"], xx, snapped))
                shift = moved[0][0] - snapped[0][0]
                assert np.array_equal(
                    [h[0] for h in moved], [h[0] for h in r["hits"]]
                ) and len(cut) == len(r["pred"]["hit"])
                rows = d["players"]
                t = np.array([s["time_s"] for s in rows])
                v, _ = te.observations(
                    rows, d["shuttle"], d["video"]["width"], d["video"]["height"]
                )
                seg = np.searchsorted(
                    sorted(d["cut_frames"]), [s["frame"] for s in rows], side="right"
                )
                valid = np.array([s["calibration_valid"] for s in rows])
                wp = dict(r["pred"], family=r["pred"]["family"].copy())
                fs = np.array(r["frames"], int)
                wp["family"][fs] = r["window"].argmax(1)
                rp = dict(wp, family=wp["family"].copy())
                for f in fs:
                    if wp["family"][f] != route.LIFT or not 0 <= f - shift < len(xx):
                        continue
                    j = int(abs(t - (t[0] + (f - shift) / 30)).argmin())
                    x = route.describe(t, v, seg, valid, j)
                    if route.predict(model, x):
                        rp["family"][f] = route.PUSH
                items.append((r["name"], None, r["hits"]))
                for k, a in zip(arms, (r["pred"], wp, rp)):
                    arms[k].append(a)
            progress((i + 1) / 6)
    previous = json.loads((base.win.OUT / "report.json").read_bytes())["scores"][
        "shuttleset"
    ]
    results = {}
    for i, tol in enumerate((2, 4)):
        scores = {k: te.score(items, a, 0.7, tol) for k, a in arms.items()}
        assert (
            scores["window"] == previous[i]["candidate"]
            and scores["ensemble"] == previous[i]["baseline"]
        )
        results[tol] = {
            "scores": scores,
            "paired": {
                k: counts(items, arms[k], arms["routed"], 0.7, tol)
                for k in ("ensemble", "window")
            },
        }
    fp.write_text(
        json.dumps(
            {"router_sha": freeze["router_sha256"], "results": results}, indent=2
        )
    )
    return {"report": str(fp)}


if __name__ == "__main__":
    print(
        exp.run_local_job(
            exp.Store(exp.DATA),
            "stroke_router_historical_replay",
            "shuttleset-frozen-router",
            run,
        )
    )
