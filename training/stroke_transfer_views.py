"""Exact 30-fps transfer views from predicted contacts and unlabelled perception only."""

from collections import defaultdict

import numpy as np
import prepare_stroke_rgb as base

exp = base.exp


def views(d, xx, fs, he, media, va):
    rows = d["players"]
    times = np.array([r["time_s"] for r in rows])
    native = np.array([r["frame"] for r in rows])
    cuts = sorted(d["cut_frames"])
    width, height = d["video"]["width"], d["video"]["height"]
    req = defaultdict(list)
    pixels = []
    for f in fs:
        ref = len(pixels)
        pixels.append([None] * len(base.OFF))
        q = f
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
        for k, off in enumerate(base.OFF):
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
    base.decode(media, req, pixels)
    actors = pixels
    pixels = []
    req = defaultdict(list)
    spans = []
    t = times
    seg = np.searchsorted(cuts, native, side="right")
    w, h = width, height
    shuttle = {r["frame"]: r for r in d["shuttle"]}
    for j, f in enumerate(fs):
        lo = max(0, f - 24, fs[j - 1] + 1 if j else 0)
        hi = min(
            len(xx) - 1,
            f + 39,
            fs[j + 1] - 1 if j + 1 < len(fs) else f + 39,
        )
        idx = len(pixels)
        pixels.append([None] * 18)
        coords = np.zeros((9, 4), np.float32)
        spans.append(coords)
        center = np.abs(t - (t[0] + f / 30)).argmin()
        for k, q in enumerate(np.r_[np.linspace(lo, f, 4), np.linspace(f, hi, 6)[1:]]):
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
    base.decode(media, req, pixels)
    x = np.zeros((len(fs), 23, 72, 72), np.uint8)
    v = np.zeros((len(fs), 19), bool)
    c = np.array(spans, dtype=np.float32).reshape(-1, 9, 4)
    for i, (vs, ac) in enumerate(zip(pixels, actors)):
        for j, img in enumerate(vs):
            if img is not None:
                x[i, j] = img
                v[i, j] = True
        if all(z is not None for z in ac):
            x[i, 18:] = np.stack(ac)
            v[i, 18] = True
    c[:, :, :3] *= v[:, 9:18, None]
    return x, c, v
