"""Frozen comparison on the Hangzhou development broadcast, not an exact-contact or test score."""

import gzip
import json
from collections import Counter
from pathlib import Path

import numpy as np
import prepare_stroke_hangzhou as transfer
import stroke_transfer_views as tv
import torch
import train_stroke_flight_video as fv
import train_stroke_lift_route as route
import train_stroke_rgb as rgb
from torch import nn
from ultralytics import YOLO

base = transfer.base
exp = base.exp
MAP = {
    "serve": "serve",
    "clear": "clear",
    "net lift": "lift",
    "net shot": "net",
    "cross-court net shot": "net",
    "drop shot": "drop",
    "kill": "smash",
    "drive": "drive",
    "push shot": "push",
    "block": "block",
    "net kill": "net kill",
}
ARMS = ("ensemble", "window", "visual", "flight", "routed")


def bindings(bounds, frames):
    candidates = [
        [j for j, f in enumerate(frames) if a <= f <= b]
        if a is not None and b is not None
        else []
        for a, b in bounds
    ]
    degree = Counter(j for choices in candidates for j in choices)
    return [(v[0] if len(v) == 1 and degree[v[0]] == 1 else None) for v in candidates]


def score(preds, labels):
    events = []
    by = Counter()
    statuses = Counter()
    npeaks = 0
    extras = 0
    assert len(preds) == len(labels)
    for p, r in zip(preds, labels):
        bounds = []
        names = []
        for hit in r["hitting"]:
            a, b = hit.get("start_frame"), hit.get("end_frame")
            ok = (
                type(a) is int
                and type(b) is int
                and r["start_frame"] <= a <= b <= r["end_frame"]
            )
            bounds.append((a, b) if ok else (None, None))
            names.append(
                MAP.get(hit.get("Foundational Actions Level", {}).get("hit type"))
            )
        fs = p["frames"]
        ids = bindings(bounds, fs)
        npeaks += len(fs)
        extras += len(fs) - sum(j is not None for j in ids)
        for (a, b), j, k in zip(bounds, ids, names):
            by[k or "unknown"] += 1
            statuses[
                "invalid_bounds"
                if a is None
                else "unbound_or_ambiguous"
                if j is None
                else "unique"
            ] += 1
            if k is not None and j is not None:
                events.append((k, {arm: exp.FAMILIES[p[arm][j]] for arm in ARMS}))
    result = {}
    for arm in ARMS:
        conf = Counter((k, v[arm]) for k, v in events)
        f1 = {}
        for k in exp.SIX:
            support = sum(n for (t, _), n in conf.items() if t == k)
            den = support + sum(n for (_, q), n in conf.items() if q == k)
            f1[k] = 2 * conf[k, k] / den if support else None
        result[arm] = {
            "correct": sum(k == v[arm] for k, v in events),
            "per_family_f1_matched": f1,
            "six_macro": float(np.mean(list(f1.values())))
            if all(v is not None for v in f1.values())
            else None,
            "confusion": {
                k: {q: n for (t, q), n in conf.items() if t == k}
                for k in sorted({t for t, _ in conf})
            },
        }
    return {
        "source_rows": sum(by.values()),
        "family_support_all_rows": by,
        "interval_status_all_rows": statuses,
        "predicted_contacts_in_rally_bounds": npeaks,
        "predictions_not_uniquely_bound": extras,
        "matched_known": len(events),
        "arms": result,
        "routed_vs": {
            arm: {
                "fixed": sum(v[arm] != k == v["routed"] for k, v in events),
                "introduced": sum(v["routed"] != k == v[arm] for k, v in events),
            }
            for arm in ARMS[:-1]
        },
    }


def run(job, progress):
    out = transfer.OUT
    spec = json.loads((out / "evaluation-freeze.json").read_bytes())
    assert spec == freeze()
    assert not (out / "transfer-score.json").exists()
    d = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(2)
    ens = torch.jit.load(
        str(exp.OUT / "singles_family_ensemble.ts"), map_location=d
    ).eval()
    w = torch.load(base.win.OUT / "expert.pt", map_location="cpu", weights_only=True)
    window = base.win.Expert(w["dim"], exp.K).to(d).eval()
    window.load_state_dict(w["state"])
    pose = exp.ROOT / "models/weights/yolo11s-pose.pt"
    assert base.digest(pose) == rgb.POSE_SHA
    vis = (
        rgb.VisualExpert(
            nn.Sequential(*list(YOLO(str(pose)).model.model.children())[:5])
        )
        .to(d)
        .eval()
    )
    vis.load_state_dict(
        torch.load(base.OUT / "expert.pt", map_location="cpu", weights_only=True)[
            "state"
        ]
    )
    flight = fv.FlightVideo().to(d).eval()
    weights = fv.OUT / "candidate.pt"
    ck = torch.load(weights, map_location="cpu", weights_only=True)
    assert ck["fit_spec_sha"] == base.digest(fv.OUT / "fit-spec.json")
    flight.load_state_dict(ck["state"])
    media = transfer.SRC / "0043.mp4"
    cfg = transfer.protocol()
    model = dict(np.load(route.OUT / "model.npz"))
    assert (
        base.digest(route.OUT / "model.npz")
        == json.loads((route.OUT / "report.json").read_bytes())["model_sha"]
    )
    preds = []
    # Predict using only perception artifacts. Load reference stroke labels after predictions are saved.
    with torch.inference_mode():
        for i, (a, b) in enumerate(cfg["rallies_in_source_order"]):
            data = json.loads(
                gzip.decompress(
                    (out / "features" / f"fb-0043-{i:03}.json.gz").read_bytes()
                )
            )
            assert (
                data["source_match"] == "0043"
                and data["source_interval"] == [a, b]
                and data["video"]["sha256"] == cfg["source"]["media_sha256"]
            )
            rows = data["players"]
            native = np.array([r["frame"] for r in rows])
            assert (
                np.all(np.diff(native) == 1)
                and np.max(abs(np.array([r["time_s"] for r in rows]) - native / 30))
                < 0.001
            )
            z, _ = base.te.observations(
                rows, data["shuttle"], data["video"]["width"], data["video"]["height"]
            )
            xx = base.te.with_motion(z)
            o = ens(torch.from_numpy(xx)[None].to(d))
            fs = base.te.peaks(o[0][0, :, 0].sigmoid().cpu().numpy(), 0.7)
            ends = o[1][0].argmax(1).cpu().numpy()
            log = o[2][0, fs].cpu().numpy()
            wl = log.copy()
            vl = log.copy()
            fl = log.copy()
            if fs:
                seg = np.searchsorted(sorted(data["cut_frames"]), native, side="right")
                valid = np.array([r["calibration_valid"] for r in rows])
                times = np.array([row["time_s"] for row in rows])
                ix = np.searchsorted(times, times[0] + np.arange(len(xx)) / 30).clip(
                    0, len(times) - 1
                )
                seg, valid = seg[ix], valid[ix]
                ww = (
                    window(
                        torch.from_numpy(base.win.windows(xx, fs, ends, seg, valid)).to(
                            d
                        )
                    )
                    .cpu()
                    .numpy()
                )
                ok = valid[fs]
                wl[ok] = 0.65 * log[ok] + 0.35 * ww[ok]
                vl = wl.copy()
                fl = wl.copy()
                x, c, v = tv.views(data, xx, fs, ends, media, valid)
                ok = v[:, 18]
                if ok.any():
                    vl[ok] = (
                        0.7 * wl[ok]
                        + 0.3
                        * vis(torch.from_numpy(x[ok, 18:]).to(d).float() / 255)
                        .cpu()
                        .numpy()
                    )
                ok = v[:, :9].sum(1) >= 4
                if ok.any():
                    fl[ok] = (1 - fv.BLEND) * wl[ok] + fv.BLEND * flight(
                        *(torch.from_numpy(y[ok]).to(d) for y in (x, c, v))
                    ).cpu().numpy()
            fr = native[np.asarray(fs, dtype=int)]
            routed = wl.copy()
            t = np.array([r["time_s"] for r in rows])
            sg = np.searchsorted(sorted(data["cut_frames"]), native, side="right")
            va = np.array([r["calibration_valid"] for r in rows])
            for j, f in enumerate(fs):
                if int(wl[j].argmax()) == route.LIFT and route.predict(
                    model, route.describe(t, z, sg, va, f)
                ):
                    routed[j, route.PUSH] = wl[j].max() + 1
            keep = (fr >= a) & (fr <= b)
            preds.append(
                {
                    "frames": fr[keep].tolist(),
                    **{
                        k: v.argmax(1)[keep].tolist()
                        for k, v in zip(ARMS, (log, wl, vl, fl, routed))
                    },
                }
            )
            progress((i + 1) / len(cfg["rallies_in_source_order"]))
    (out / "predictions.json").open("x").write(json.dumps(preds))
    labels = json.loads((transfer.SRC / "0043_updated.json").read_bytes())
    report = score(preds, labels)
    report["flight_sha"] = base.digest(weights)
    (out / "transfer-score.json").open("x").write(json.dumps(report, indent=2))
    return {"matched_known": report["matched_known"]}


def freeze():
    return {
        "scope": "Development transfer, single Hangzhou World Tour Finals match. No model selection on this source. Source-interval-conditioned evaluation only; not precision/recall of actual contact times.",
        "matching": "Within each published rally, accept a source action only if exactly one predicted peak falls inside the inclusive action interval and no other valid interval contains that peak. Unknown classes may block a binding. No midpoint, time shifts, label-dependent ties or retuning. Report every source row.",
        "arms": list(ARMS),
        "map": MAP,
        "evaluator_sha": base.digest(Path(__file__)),
        "route_model_sha": base.digest(route.OUT / "model.npz"),
        "route_trainer_sha": base.digest(Path(route.__file__)),
        "views_sha": base.digest(Path(tv.__file__)),
        "prep_protocol_sha": base.digest(transfer.OUT / "protocol.json"),
        "flight_training_queue": json.loads(
            (fv.OUT / "queued-trainer.json").read_bytes()
        ),
        "input_models": {
            str(p.name): base.digest(p)
            for p in [
                exp.OUT / "singles_family_ensemble.ts",
                base.win.OUT / "expert.pt",
            ]
        },
        "visual_expert_sha": base.digest(base.OUT / "expert.pt"),
    }


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--freeze", action="store_true")
    args = p.parse_args()
    if args.freeze:
        (transfer.OUT / "evaluation-freeze.json").open("x").write(
            json.dumps(freeze(), indent=2)
        )
    else:
        print(
            exp.run_local_job(
                exp.Store(exp.DATA),
                "stroke_transfer_comparison",
                "fb-0043-compare",
                run,
            )
        )
