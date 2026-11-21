"""Shadow the installed singles head on two existing development perception caches."""

import gzip
import json
from collections import Counter
from datetime import datetime, timezone

import train_stroke_sequence as exp  # isort: skip
import numpy as np
import torch
import train_events as te
from evaluate_stroke_transfer_dev import MAP, bindings

MATCHES = ("0043", "0058")  # development only; no acceptance inputs


def save(path, value):
    with path.open("x", encoding="utf8") as fp:
        json.dump(value, fp, indent=2)


def run(_, progress):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(2)
    out = (
        exp.ROOT
        / ".cache/singles-shadow"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    out.mkdir(parents=True, exist_ok=False)
    ens = exp.OUT / "singles_family_ensemble.ts"
    manifest = json.loads((exp.OUT / "ensemble-manifest.json").read_bytes())
    hashes = [exp.sha(exp.MODELS[0]), exp.sha(ens)]
    assert hashes == [manifest["source_hashes"][0], manifest["sha256"]]
    ck = torch.load(exp.MODELS[0], weights_only=True, map_location=device)
    assert ck["threshold"] == 0.7
    old = exp.from_checkpoint(ck).to(device).eval()
    old.load_state_dict(ck["state"])
    new = torch.jit.load(str(ens), map_location=device).eval()
    save(
        out / "protocol.json",
        {
            "matches": MATCHES,
            "weights": hashes,
            "device": device,
            "threshold": 0.7,
            "matching": "unique inclusive publisher interval, no shifts",
            "script_sha": exp.sha(exp.ROOT / "training/shadow_singles_ensemble.py"),
        },
    )
    report = {}
    for n, match in enumerate(MATCHES):
        cache = exp.ROOT / f".cache/stroke-transfer-dev-{match}"
        cfg = json.loads((cache / "protocol.json").read_bytes())
        predictions = [[], []]
        with torch.inference_mode():
            for i, bounds in enumerate(cfg["rallies_in_source_order"]):
                path = cache / "features" / f"fb-{match}-{i:03}.json.gz"
                data = json.loads(gzip.decompress(path.read_bytes()))
                video, rows = data["video"], data["players"]
                assert (
                    data["source_match"] == match and data["source_interval"] == bounds
                )
                assert (
                    video["sha256"] == cfg["source"]["media_sha256"]
                    and video["fps"] == 30
                )
                native = np.array([r["frame"] for r in rows])
                times = np.array([r["time_s"] for r in rows])
                assert (
                    np.all(np.diff(native) == 1)
                    and np.max(abs(times - native / 30)) < 0.001
                )
                z, _ = te.observations(
                    rows, data["shuttle"], video["width"], video["height"]
                )
                x = torch.from_numpy(te.with_motion(z))[None].to(device)
                for pred, logits in zip(
                    predictions,
                    (old(x), dict(zip(manifest["outputs"], new(x), strict=True))),
                ):
                    peaks = te.peaks(
                        logits["hit"][0, :, 0].sigmoid().cpu().numpy(), ck["threshold"]
                    )
                    events = [
                        {
                            "frame": int(native[f]),
                            "time_s": float(times[f]),
                            "family": exp.FAMILIES[
                                int(logits["family"][0, f].argmax())
                            ],
                            "court_end_index": int(logits["hitter"][0, f].argmax()),
                        }
                        for f in peaks
                        if bounds[0] <= native[f] <= bounds[1]
                    ]
                    pred.append(
                        {
                            "bounds": bounds,
                            "feature_sha": exp.sha(path),
                            "events": events,
                        }
                    )
        for arm, pred in zip(("installed", "ensemble"), predictions):
            save(out / f"{match}-{arm}.json", pred)
        ref = exp.ROOT / f".cache/stroke-source-audit/{match}_updated.json"
        assert exp.sha(ref) == cfg["source"]["sha256"]
        stats = Counter()
        transitions = Counter()
        for r, a, b in zip(json.loads(ref.read_bytes()), *predictions, strict=True):
            assert a["bounds"] == [r["start_frame"], r["end_frame"]]
            aa, bb = a["events"], b["events"]
            frames = [e["frame"] for e in aa]
            assert [(e["frame"], e["court_end_index"]) for e in aa] == [
                (e["frame"], e["court_end_index"]) for e in bb
            ]
            stats.update(
                rallies=1, predicted=len(frames), source_actions=len(r["hitting"])
            )
            intervals = [
                (h.get("start_frame"), h.get("end_frame")) for h in r["hitting"]
            ]
            intervals = [
                (s, t)
                if type(s) is int
                and type(t) is int
                and a["bounds"][0] <= s <= t <= a["bounds"][1]
                else (None, None)
                for s, t in intervals
            ]
            for h, j in zip(r["hitting"], bindings(intervals, frames)):
                truth = MAP.get(h.get("Foundational Actions Level", {}).get("hit type"))
                if j is None or truth is None:
                    continue
                u, v = aa[j]["family"], bb[j]["family"]
                stats.update(
                    matched_known=1,
                    installed_correct=int(u == truth),
                    ensemble_correct=int(v == truth),
                    fixed=int(u != truth == v),
                    introduced=int(u == truth != v),
                )
                if u != v:
                    transitions[f"{truth}: {u} -> {v}"] += 1
        report[match] = {"stats": stats, "transitions": transitions}
        progress((n + 1) / len(MATCHES))
    save(out / "report.json", report)
    print(out, json.dumps(report), flush=True)
    return {"output": str(out)}


if __name__ == "__main__":
    print(
        exp.run_local_job(
            exp.Store(exp.DATA), "singles_shadow", "installed-vs-ensemble-dev", run
        )
    )
