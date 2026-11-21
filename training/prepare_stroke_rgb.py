"""Paired RGB singles research: prepare clips locally, no held-out test access."""

import bisect
import gzip
import hashlib
import json
import os
import pickle
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torchvision  # noqa: F401 -- initialize before FFmpeg
import train_events as te
import train_stroke_sequence as exp
import train_stroke_window as win
from badminton.av_runtime import open_media
from PIL import Image

OUT = exp.ROOT / ".cache/stroke-rgb-v1"
SIZE = 72
OFF = (-6, -3, 0, 3, 6)
WINDOW_SHA = "565c3659d614d213b792c8d9abfcbaf66c06ecf2b74dcfdd8e2b71c013eb82cf"
SEED = 317
EPOCHS = 28
ALPHA = 0.30


def digest(p):
    ha = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(4 << 20), b""):
            ha.update(b)
    return ha.hexdigest()


def decode(media, req, pixels):
    """Native PTS must agree to 0.55 ms. Missing requests stay missing."""
    targets = sorted(req)
    done = 0
    if not targets:
        return 0
    with open_media(str(media)) as c:
        stream = c.streams.video[0]
        stream.thread_type = "AUTO"
        origin = next(c.decode(stream)).time
        tb = float(stream.time_base)
        i = 0
        while i < len(targets):
            start = targets[i]
            c.seek(max(0, int((origin + start - 0.05) / tb)), stream=stream)
            last = i
            for frame in c.decode(stream):
                if frame.pts is None:
                    continue
                clock = frame.time - origin
                i = bisect.bisect_left(targets, clock - 0.00055, i)
                if i == len(targets):
                    break
                if abs(clock - targets[i]) <= 0.00055:
                    if getattr(frame, "rotation", 0) == 0:
                        img = None
                        for ref, k, box, width, height in req[targets[i]]:
                            if (width, height) != (frame.width, frame.height):
                                continue
                            if img is None:
                                img = frame.to_ndarray(format="gray")
                            x0, y0, x1, y1 = box
                            crop = img[y0:y1, x0:x1]
                            if crop.size:
                                pixels[ref][k] = np.asarray(
                                    Image.fromarray(crop).resize(
                                        (SIZE, SIZE), Image.Resampling.BILINEAR
                                    )
                                )
                                done += 1
                    i += 1
                if i >= len(targets) or (i > last and targets[i] - clock > 7):
                    break
            if i == last:
                i += 1  # no frame at or beyond the first remaining request
    return done


def prepare(match, paths, split, models, device, expected, media_dir):
    model, wmodel = models
    packed = []
    req = defaultdict(list)
    pixels = []
    ref_sha = set()
    audit = {
        "all_features": len(paths),
        "reference_events": 0,
        "historic_excluded_events": 0,
        "known_family_events": 0,
    }
    for p in paths:
        by = p.read_bytes()
        assert hashlib.sha256(by).hexdigest() == expected[p.name]
        d = json.loads(gzip.decompress(by))
        assert d["split"] == split and d["match_id"] == match
        ref_sha.add(d["video"]["sha256"])
        audit["reference_events"] += len(d["events"])
        audit["known_family_events"] += sum(
            bool(e["usable"]) and e["source_type"] in te.SHUTTLESET_FAMILY
            for e in d["events"]
        )
        loaded = win.load_doc(p, "shuttleset")
        if loaded is None:
            audit["historic_excluded_events"] += len(d["events"])
            continue
        item, seg, valid = loaded
        raw = item[1]
        shift = 0
        if split == "validation":
            # Original scorer's teacher snap. Same transformations for all methods.
            oldhits = item[2]
            oo = TEACHER(torch.from_numpy(raw)[None].to(device))
            tf = te.peaks(oo["hit"][0, :, 0].sigmoid().cpu().numpy(), TEACHER_TH)
            used = set()
            hits = []
            for f, *tail in oldhits:
                opts = [
                    j
                    for j in tf
                    if j not in used and abs(f - j) <= round(te.SNAP_S * 30)
                ]
                new = min(opts, key=lambda j: abs(f - j)) if opts else f
                if opts:
                    used.add(new)
                hits.append((new, *tail))
            item = te.steady_ends((item[0], raw, hits))
            shift = item[2][0][0] - hits[0][0]
        name, xx, h = item
        ix = np.arange(len(xx)) - shift
        sg = seg[ix.clip(0, len(seg) - 1)]
        va = valid[ix.clip(0, len(valid) - 1)] & (ix >= 0) & (ix < len(raw))
        o = model(torch.from_numpy(xx)[None].to(device))
        hit = o[0][0, :, 0].sigmoid().cpu().numpy()
        fs = te.peaks(hit, 0.7)
        he = o[1][0].argmax(1).cpu().numpy()
        pred = {
            "hit": hit,
            **{
                k: v[0].argmax(1).cpu().numpy()
                for k, v in zip(("hitter", "family", "side", "serve"), o[1:])
            },
        }
        logits = o[2][0, fs].cpu().numpy()
        mixed = logits.copy()
        rows = d["players"]
        times = np.array([r["time_s"] for r in rows])
        native = np.array([r["frame"] for r in rows])
        cuts = np.array(sorted(d.get("cut_frames") or []))
        width = d["video"]["width"]
        height = d["video"]["height"]
        start = len(pixels)
        if fs:
            zz = win.windows(xx, fs, he, sg, va)
            rgbbase = wmodel(torch.from_numpy(zz).to(device)).cpu().numpy()
            mixed[va[fs]] = 0.65 * logits[va[fs]] + 0.35 * rgbbase[va[fs]]
        for f in fs:
            ref = len(pixels)
            pixels.append([None] * len(OFF))
            q = f - shift
            if not va[f]:
                continue
            center = int(np.abs(times - (times[0] + q / 30)).argmin())
            end = he[f]
            slot = end * exp.PLAYER
            box = xx[f, slot + 51 : slot + 55]
            if xx[f, slot + 55] <= 0:
                continue
            cx = (box[0] + box[2]) * width / 2
            cy = (box[1] + 0.36 * (box[3] - box[1])) * height
            hpx = (box[3] - box[1]) * height
            wpx = max((box[2] - box[0]) * width, 1.4 * hpx)
            side = max(wpx, 1.4 * hpx)
            bounds = (
                max(0, int(cx - side / 2)),
                max(0, int(cy - side / 2)),
                min(width, int(cx + side / 2)),
                min(height, int(cy + side / 2)),
            )
            if min(bounds[2] - bounds[0], bounds[3] - bounds[1]) < 16:
                continue
            for k, off in enumerate(OFF):
                t = times[0] + (q + off) / 30
                j = int(np.abs(times - t).argmin())
                if (
                    abs(times[j] - t) > 0.026
                    or not rows[j].get("calibration_valid")
                    or np.searchsorted(cuts, native[center], side="right")
                    != np.searchsorted(cuts, native[j], side="right")
                ):
                    continue
                req[float(times[j])].append((ref, k, bounds, width, height))
        packed.append(
            dict(
                name=name,
                hits=h,
                pred=pred,
                frames=fs,
                logits=logits,
                window=mixed,
                start=start,
            )
        )
    assert len(ref_sha) == 1
    files = list(media_dir.glob(f"{match}.*"))
    media = next((p for p in files if digest(p) in ref_sha), None)
    audit["verified_video"] = media is not None
    if media is not None:
        try:
            audit["frames_cropped"] = decode(media, req, pixels)
        except (ValueError, OSError, EOFError) as e:
            audit["decode_error"] = str(e)
            pixels = [
                [None] * len(OFF) for _ in pixels
            ]  # fail closed, retain predictions
    audit["predicted_contacts"] = len(pixels)
    audit["complete_crops"] = sum(all(a is not None for a in v) for v in pixels)
    for r in packed:
        vs = pixels[r.pop("start") :][: len(r["frames"])]
        r["ok"] = np.array([all(a is not None for a in v) for v in vs], bool)
        r["rgb"] = (
            np.stack([np.stack(v) for v, ok in zip(vs, r["ok"]) if ok])
            if r["ok"].any()
            else np.zeros((0, len(OFF), SIZE, SIZE), np.uint8)
        )
    return {"clips": packed, "audit": audit, "sha": next(iter(ref_sha))}


def run(job, progress):
    global TEACHER, TEACHER_TH
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = win.OUT / "feature-inputs.json"
    assert (
        digest(manifest)
        == "a5a2d1130e9ff751c6dfd1c7bef9556512c169b13c3aa476732d7451393bfda7"
    )
    expected = {
        n: h for _, ds, n, h in json.loads(manifest.read_text()) if ds == "shuttleset"
    }
    bp = exp.OUT / "singles_family_ensemble.ts"
    wp = win.OUT / "expert.pt"
    assert digest(bp) == win.PIN and digest(wp) == WINDOW_SHA
    files = defaultdict(list)
    for split, ds, p in win.source_files():
        if ds == "shuttleset":
            files[split, int(p.name.split("-")[1])].append(p)
    protocol = {
        "prep_sha": digest(Path(__file__)),
        "input_manifest_sha": digest(manifest),
        "baseline_sha": win.PIN,
        "previous_window_sha": WINDOW_SHA,
        "corpus": "ShuttleSet singles RGB; AICup fallback unchanged when raw video absent",
        "split_matches": {
            s: sorted(m for fold, m in files if fold == s)
            for s in ("train", "validation")
        },
        "frames30fps": OFF,
        "size": SIZE,
        "alpha": ALPHA,
        "epochs": EPOCHS,
        "seed": SEED,
        "decision": "Predeclared meaningful development gate: +0.02 family macro F1 and +0.03 weak macro F1 against each frozen baseline at 2 frames, nonnegative full-event F1, better in >=4/5 matches; no release claim without untouched adjudicated source groups. +/-4 frames secondary. No tuning on validation or test.",
    }
    proto = json.dumps(protocol, indent=2)
    f = OUT / "protocol.json"
    if f.exists():
        assert f.read_text() == proto
    else:
        f.write_text(proto)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(2)
    model = torch.jit.load(str(bp), map_location=device).eval()
    s = torch.load(wp, map_location="cpu", weights_only=True)
    wmodel = win.Expert(s["dim"], exp.K).to(device).eval()
    wmodel.load_state_dict(s["state"])
    ts = torch.load(
        exp.ROOT / "models/weights/events_v2.pt", map_location="cpu", weights_only=True
    )
    TEACHER = exp.from_checkpoint(ts).to(device).eval()
    TEACHER.load_state_dict(ts["state"])
    TEACHER_TH = ts["threshold"]
    print("job", job, device, flush=True)
    with torch.inference_mode():
        for i, ((split, m), paths) in enumerate(sorted(files.items())):
            dest = OUT / f"{split}-{m}.pkl"
            if not dest.exists():
                pack = prepare(
                    m,
                    paths,
                    split,
                    (model, wmodel),
                    device,
                    expected,
                    exp.ROOT / "data/datasets/shuttleset/videos",
                )
                tmp = dest.with_suffix(".tmp")
                tmp.write_bytes(pickle.dumps(pack, protocol=5))
                os.replace(tmp, dest)
                print(split, m, pack["audit"], flush=True)
            progress((i + 1) / len(files))
    return {"complete": len(files)}


if __name__ == "__main__":
    print(exp.run_local_job(exp.Store(exp.DATA), "rgb_crops", "singles-rgb-v1", run))
