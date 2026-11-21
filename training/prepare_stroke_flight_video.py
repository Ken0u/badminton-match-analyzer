"""Build train-only rally-flight clips on native timestamps; no new source/test predictions."""

import csv
import gzip
import json
import os
import pickle
from collections import defaultdict
from pathlib import Path

import numpy as np
import prepare_stroke_rgb as old

exp = old.exp
OUT = exp.ROOT / ".cache/stroke-flight-video-v2"
DIAGNOSTIC = [14, 15, 16]


def run(job, progress):
    OUT.mkdir(exist_ok=True)
    sources = json.loads((old.OUT / "frozen-training.json").read_bytes())["packs"]
    ids = json.loads((old.OUT / "protocol.json").read_bytes())["split_matches"]["train"]
    feature_file = old.win.OUT / "feature-inputs.json"
    assert (
        old.digest(feature_file)
        == "a5a2d1130e9ff751c6dfd1c7bef9556512c169b13c3aa476732d7451393bfda7"
    )
    features = {
        n: sha
        for fold, ds, n, sha in json.loads(feature_file.read_bytes())
        if ds == "shuttleset" and fold == "train"
    }
    match_csv = exp.ROOT / "data/datasets/shuttleset/source/ShuttleSet/set/match.csv"
    with match_csv.open(encoding="utf-8-sig") as f:
        assert (
            sorted(
                int(r["id"])
                for r in csv.DictReader(f)
                if r["tournament"] == "Indonesia Masters 2020"
            )
            == DIAGNOSTIC
        )
    protocol = {
        "preparer": old.digest(Path(__file__)),
        "decoder": old.digest(Path(old.__file__)),
        "train_input_sha": {str(m): sources[f"train-{m}.pkl"] for m in ids},
        "fit_matches": sorted(set(ids) - set(DIAGNOSTIC)),
        "diagnostic_matches": DIAGNOSTIC,
        "decision": "Training-only experiment. No final tests, no historical validation access. Previous heads saw diagnostic training sources: incumbent comparisons are diagnostics only. No fitted normalization across diagnostic matches. Fixed training seed 904, 24 epochs, final four averaged; no epoch selection. Use ensemble/window fallbacks for missing video and preserve all contacts.",
    }
    fp = OUT / "protocol.json"
    txt = json.dumps(protocol, indent=2)
    assert not fp.exists() or fp.read_text() == txt
    fp.write_text(txt)
    for i, m in enumerate(ids):
        path = OUT / f"{m}.pkl"
        src = old.OUT / f"train-{m}.pkl"
        assert old.digest(src) == sources[src.name]
        if path.exists():
            continue
        pack = pickle.loads(src.read_bytes())
        media = next(
            p
            for p in (exp.ROOT / "data/datasets/shuttleset/videos").glob(f"{m}.*")
            if old.digest(p) == pack["sha"]
        )
        req = defaultdict(list)
        pixels = []
        spans = []
        clips = []
        for rec in pack["clips"]:
            p = exp.FEATURE / (rec["name"] + ".json.gz")
            assert old.digest(p) == features[p.name]
            d = json.loads(gzip.decompress(p.read_bytes()))
            assert (
                d["split"] == "train"
                and d["match_id"] == m
                and d["video"]["sha256"] == pack["sha"]
            )
            rows = d["players"]
            t = np.array([r["time_s"] for r in rows])
            n = np.array([r["frame"] for r in rows])
            seg = np.searchsorted(sorted(d.get("cut_frames") or []), n, side="right")
            shuttle = {r["frame"]: r for r in d["shuttle"]}
            w, h = d["video"]["width"], d["video"]["height"]
            fs = rec["frames"]
            start = len(pixels)
            for j, f in enumerate(fs):
                lo = max(0, f - 24, fs[j - 1] + 1 if j else 0)
                hi = min(
                    len(rec["pred"]["hit"]) - 1,
                    f + 39,
                    fs[j + 1] - 1 if j + 1 < len(fs) else f + 39,
                )
                idx = len(pixels)
                pixels.append([None] * 18)
                coords = np.zeros((9, 4), np.float32)
                spans.append(coords)
                center = np.abs(t - (t[0] + f / 30)).argmin()
                for k, q in enumerate(
                    np.r_[np.linspace(lo, f, 4), np.linspace(f, hi, 6)[1:]]
                ):
                    target = t[0] + q / 30
                    b = int(np.abs(t - target).argmin())
                    row = rows[b]
                    coords[k, 3] = (q - f) / 30
                    if (
                        abs(t[b] - target) > 0.026
                        or seg[b] != seg[center]
                        or not rows[center].get("calibration_valid")
                        or not row.get("calibration_valid")
                    ):
                        continue
                    req[float(t[b])].append(
                        (
                            idx,
                            k,
                            (
                                int(0.12 * w),
                                int(0.12 * h),
                                int(0.88 * w),
                                int(0.96 * h),
                            ),
                            w,
                            h,
                        )
                    )
                    ball = shuttle.get(row["frame"])
                    if (
                        not ball
                        or not ball["visible"]
                        or ball["x"] is None
                        or ball["y"] is None
                    ):
                        continue
                    x, y = ball["x"], ball["y"]
                    radius = max(12, round(0.05 * h))
                    box = (
                        max(0, int(x) - radius),
                        max(0, int(y) - radius),
                        min(w, int(x) + radius),
                        min(h, int(y) + radius),
                    )
                    if not (0 <= x < w and 0 <= y < h):
                        continue
                    coords[k, :3] = [x / w, y / h, 1]
                    req[float(t[b])].append((idx, k + 9, box, w, h))
            clips.append((rec["name"], start, len(fs)))
        old.decode(media, req, pixels)
        frames = np.zeros((len(pixels), 18, old.SIZE, old.SIZE), np.uint8)
        valid = np.zeros((len(pixels), 18), bool)
        for j, v in enumerate(pixels):
            for k, x in enumerate(v):
                if x is not None:
                    frames[j, k] = x
                    valid[j, k] = True
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(
            pickle.dumps(
                {
                    "clips": clips,
                    "pixels": frames,
                    "valid": valid,
                    "coords": np.stack(spans),
                    "source": pack["sha"],
                },
                protocol=5,
            )
        )
        os.replace(tmp, path)
        print(
            "match",
            m,
            "contacts",
            len(frames),
            "court views",
            int(valid[:, :9].sum()),
            "shuttle views",
            int(valid[:, 9:].sum()),
            flush=True,
        )
        progress((i + 1) / len(ids))
    return {"matches": len(ids)}


if __name__ == "__main__":
    print(
        exp.run_local_job(
            exp.Store(exp.DATA), "stroke_flight_video_prep", "flight-video-v2", run
        )
    )
