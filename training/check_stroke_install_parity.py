"""Check that the app's event models reproduce the stroke test check's arms.

On held-out test rally feature files (.cache/stroke-test-check/features),
compare the candidate arms of training/score_stroke_test_check.py with the
backend's installed upgrades (badminton.event_model):

* module: the same whole-clip input through event_model.infer_view with the
  installed files; family must agree at every contact peak.
* app: the full event_model.predict_events path on the clip's player and
  shuttle rows (split into camera views, non-play views skipped, implausible
  contacts dropped); family compared at contacts both put on the same frame.

Read-only: writes one JSON report to .cache/stroke-install/parity.json.

    .venv/Scripts/python training/check_stroke_install_parity.py --clips 12
"""

# ruff: noqa: E402 -- pin the real shared store before importing configuration.
import argparse
import gzip
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["BADMINTON_ROOT"] = str(ROOT)
os.environ["BADMINTON_DATA_DIR"] = str(ROOT / "data/processed")
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "training"))

import numpy as np
import score_stroke_test_check as sst
import torch
import train_doubles as td
import train_events as te
from badminton import event_model

FEATURES = ROOT / ".cache/stroke-test-check/features"
OUT = ROOT / ".cache/stroke-install/parity.json"


def doc(p):
    return json.loads(gzip.decompress(p.read_bytes()))


def app_events(d, mode):
    video = {"mode": mode, **d["video"]}
    players = {"frames": d["players"], "cut_frames": d.get("cut_frames") or []}
    shuttle = {
        "frames": [{"frame": b["frame"], "shuttle": b} for b in d["shuttle"]],
        "cut_frames": d.get("cut_frames") or [],
    }
    return {
        e["frame"] - d["players"][0]["frame"]: e["family"]
        for e in event_model.predict_events(video, players, shuttle)
    }


def singles(paths, dev):
    _, ts = sst.singles_models(dev)
    model, threshold, families, _, window = event_model.load_models("singles", dev)
    assert window is None and threshold == 0.7
    tally = Counter()
    for p in paths:
        d = doc(p)
        x, h = te.shuttleset_clip(d)
        if not h:
            continue
        ref = te.predict(ts, [(d["clip_id"], x, h)], dev)[0]
        refs = te.peaks(ref["hit"], 0.7)
        values = x[:, :-3]
        valid = np.array([bool(r.get("calibration_valid")) for r in d["players"]])
        _, scores, steps, _ = event_model.infer_view(
            model, None, values, valid, threshold, False, 0, 0, dev
        )
        tally["clips"] += 1
        tally["module_same_peaks"] += int(steps == refs)
        for f in refs:
            tally["module_contacts"] += 1
            tally["module_agree"] += int(
                scores["family"][f].argmax() == ref["family"][f]
            )
        app = app_events(d, "singles")
        one_view = not d.get("cut_frames") and bool(valid.all())
        for f in refs:
            if f in app:
                same = app[f] == families[ref["family"][f]]
                tally["app_contacts"] += 1
                tally["app_agree"] += int(same)
                tally["app_single_view_contacts"] += int(one_view)
                tally["app_single_view_agree"] += int(one_view and same)
        tally["reference_contacts"] += len(refs)
    return dict(tally)


def doubles(paths, dev):
    model, threshold, families, _, window = event_model.load_models("doubles", dev)
    assert window is not None and threshold == 0.7
    tally = Counter()
    for p in paths:
        timer = Counter()
        rows, _ = sst.doubles_rows([p], dev, timer)
        if not rows:
            continue
        _, _, pred, _, new = rows[0]
        refs = te.peaks(pred["hit"], 0.7)
        d = doc(p)
        x, _ = td.doubles_clip(d)
        segment = np.searchsorted(
            sorted(d.get("cut_frames") or []),
            [r["frame"] for r in d["players"]],
            side="right",
        )
        valid = np.array([bool(r.get("calibration_valid")) for r in d["players"]])
        w, ht = d["video"]["width"], d["video"]["height"]
        _, scores, steps, slots = event_model.infer_view(
            model, window, x[:, :-3], valid, threshold, True, w, ht, dev, segment
        )
        tally["clips"] += 1
        tally["module_same_peaks"] += int(steps == refs)
        for f, slot in zip(refs, slots):
            tally["module_contacts"] += 1
            tally["module_agree"] += int(
                scores["family"][f].argmax() == new["family"][f]
            )
            tally["module_same_hitter"] += int(slot == pred["hitter"][f])
            tally["blended"] += int(valid[f])
            tally["blend_changed_family"] += int(new["family"][f] != pred["family"][f])
        app = app_events(d, "doubles")
        # A clip with a cut or an uncalibrated stretch is split into views
        # by the app, so its event model sees a shorter context.
        one_view = not d.get("cut_frames") and bool(valid.all())
        for f in refs:
            if f in app:
                same = app[f] == families[new["family"][f]]
                tally["app_contacts"] += 1
                tally["app_agree"] += int(same)
                tally["app_single_view_contacts"] += int(one_view)
                tally["app_single_view_agree"] += int(one_view and same)
        tally["reference_contacts"] += len(refs)
    return dict(tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", type=int, default=12)
    args = ap.parse_args()
    dev = "cuda:0" if torch.cuda.is_available() else "cpu"
    ss = sorted((FEATURES / "shuttleset").rglob("ss-*.json.gz"))
    ds = sorted((FEATURES / "dshuttlenet").rglob("ds-*.json.gz"))
    # Spread over the matches: every n-th file.
    pick = lambda files: files[:: max(1, len(files) // args.clips)][: args.clips]  # noqa: E731
    report = {
        "files": {
            "singles": event_model.model_files("singles"),
            "doubles": event_model.model_files("doubles"),
        },
        "methods": dict(event_model.METHODS),
        "singles": singles(pick(ss), dev),
        "doubles": doubles(pick(ds), dev),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
