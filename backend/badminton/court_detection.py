"""Unreviewed court geometry from visible markings, without a surface-color prior.

The template uses the doubles boundary and singles/service markings. A fit is
not a probability, a live/replay classifier, or evidence for an in/out decision.
Incomplete, ambiguous and moving views deliberately remain uncalibrated.
"""

import itertools
import math
import time
from contextlib import closing

import cv2
import numpy as np

from .video import iter_frames

METHOD = "local contrast badminton marking template v1"
SIDELINE = (6.10 - 5.18) / 2 / 6.10
SHORT = 0.5 - 1.98 / 13.40
LONG = 0.76 / 13.40
SEGMENTS = np.asarray(
    [
        [[0, 0], [1, 0]],
        [[1, 0], [1, 1]],
        [[1, 1], [0, 1]],
        [[0, 1], [0, 0]],
        [[SIDELINE, 0], [SIDELINE, 1]],
        [[1 - SIDELINE, 0], [1 - SIDELINE, 1]],
        [[0, LONG], [1, LONG]],
        [[0, 1 - LONG], [1, 1 - LONG]],
        [[0, SHORT], [1, SHORT]],
        [[0, 1 - SHORT], [1, 1 - SHORT]],
        [[0.5, 0], [0.5, SHORT]],
        [[0.5, 1 - SHORT], [0.5, 1]],
    ],
    np.float32,
)
_T = np.linspace(0.04, 0.96, 48, dtype=np.float32)[None, :, None]
_TEMPLATE = (SEGMENTS[:, :1] * (1 - _T) + SEGMENTS[:, 1:] * _T).reshape(1, -1, 2)
_UNIT = np.asarray([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)


def _line_mask(rgb):
    h, w = rgb.shape[:2]
    scale = min(1, 640 / max(w, h))
    image = cv2.resize(
        rgb, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA
    )
    kernel = max(3, min(31, round(15 * image.shape[0] / 360) | 1))
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    contrast = gray.astype(np.int16) - cv2.medianBlur(gray, kernel).astype(np.int16)
    return ((gray >= 80) & (contrast >= 15)).astype(np.uint8)


def _lines(mask):
    h, _ = mask.shape
    raw = cv2.HoughLinesP(
        mask,
        1,
        np.pi / 360,
        max(12, round(h * 0.07)),
        minLineLength=max(15, h * 0.12),
        maxLineGap=max(2, h * 0.015),
    )
    if raw is None:
        return []
    records = []
    for x1, y1, x2, y2 in raw[:, 0]:
        length = math.hypot(x2 - x1, y2 - y1)
        normal = np.asarray([y1 - y2, x2 - x1, x1 * y2 - x2 * y1], float) / length
        if normal[0] < 0 or (abs(normal[0]) < 1e-6 and normal[1] < 0):
            normal *= -1
        records.append((length, normal, np.asarray([(x1 + x2) / 2, (y1 + y2) / 2, 1])))
    selected = []
    for length, normal, midpoint in sorted(records, key=lambda r: -r[0]):
        if any(
            abs(np.dot(normal[:2], other[1][:2])) > math.cos(math.radians(3))
            and abs(np.dot(other[1], midpoint)) <= max(1.5, h * 0.006)
            for other in selected
        ):
            continue
        selected.append((length, normal, midpoint))
        if len(selected) == 26:
            break
    return selected


def _canonical(quad):
    # Preserve the fitted long/short court axes. Arbitrary polygon rotation
    # would incorrectly swap court length and width for downstream features.
    if quad[:2, 1].sum() > quad[2:, 1].sum():
        quad = quad[[3, 2, 1, 0]]
    if quad[0, 0] > quad[1, 0]:
        quad = quad[[1, 0, 3, 2]]
    return quad


def _score(quad, distance, soft):
    h, w = distance.shape
    transform = cv2.getPerspectiveTransform(_UNIT, quad.astype(np.float32))
    projected = cv2.perspectiveTransform(_TEMPLATE, transform)[0]
    if not np.isfinite(projected).all():
        return None
    points = np.rint(projected).astype(int)
    x, y = points[:, 0].clip(0, w - 1), points[:, 1].clip(0, h - 1)
    support = (distance[y, x].reshape(12, -1) <= max(1.2, h * 4 / 720)).mean(1)
    quality = soft[y, x].reshape(12, -1).mean(1)
    if (
        min(support[:4]) < 0.2
        or sum(support[:4] >= 0.6) < 3
        or support[:4].mean() < 0.65
        or sum(support[4:] >= 0.5) < 4
        or support[4:].mean() < 0.55
        or min(support[[4, 5, 8, 9]]) < 0.45
    ):
        return None
    return float(0.5 * quality[:4].mean() + 0.5 * quality[4:].mean()), support


def detect_court(rgb):
    """Fit a complete visible court to an RGB uint8 image; return normalized corners."""
    if (
        not isinstance(rgb, np.ndarray)
        or rgb.dtype != np.uint8
        or rgb.ndim != 3
        or rgb.shape[2] != 3
        or min(rgb.shape[:2]) < 128
    ):
        raise ValueError(
            "Court detection requires an RGB uint8 image at least 128px per side"
        )
    began = time.perf_counter()
    mask = _line_mask(rgb)
    h, w = mask.shape
    records = _lines(mask)
    candidates, considered = [], 0
    if len(records) >= 4:
        matrix = np.asarray([r[1] for r in records])
        cross = np.cross(matrix[:, None, :], matrix[None, :, :])
        finite = np.abs(cross[:, :, 2]) > 1e-5
        intersections = np.divide(
            cross[:, :, :2],
            cross[:, :, 2:],
            out=np.full(cross[:, :, :2].shape, np.nan),
            where=finite[:, :, None],
        )
        angles = np.degrees(
            np.arccos(np.clip(np.abs(matrix[:, :2] @ matrix[:, :2].T), 0, 1))
        )
        pairs = list(itertools.combinations(range(len(records)), 2))
        transverse = sorted(
            [(i, j) for i, j in pairs if angles[i, j] <= 25],
            key=lambda p: -(records[p[0]][0] + records[p[1]][0]),
        )[:100]
        distance = cv2.distanceTransform(1 - mask, cv2.DIST_L2, 3)
        soft = np.exp(-0.5 * (distance / max(0.7, h * 2 / 720)) ** 2)
        found = []
        for i, j in transverse:
            for k, last in pairs:
                if (
                    i in (k, last)
                    or j in (k, last)
                    or min(angles[i, k], angles[i, last], angles[j, k], angles[j, last])
                    < 25
                ):
                    continue
                quad = np.asarray(
                    [
                        intersections[i, k],
                        intersections[i, last],
                        intersections[j, last],
                        intersections[j, k],
                    ],
                    np.float32,
                )
                if (
                    not np.isfinite(quad).all()
                    or np.any(quad < 0)
                    or np.any(quad[:, 0] >= w)
                    or np.any(quad[:, 1] >= h)
                    or not cv2.isContourConvex(quad)
                    or not 0.07 <= abs(cv2.contourArea(quad)) / (w * h) <= 0.85
                    or np.ptp(quad[:, 0]) < 0.18 * w
                    or np.ptp(quad[:, 1]) < 0.18 * h
                ):
                    continue
                considered += 1
                result = _score(quad, distance, soft)
                if result is not None and result[0] >= 0.6:
                    found.append((result[0], quad, result[1]))
        selected = []
        for value, quad, support in sorted(found, key=lambda r: -r[0]):
            quad = _canonical(quad)
            if any(
                np.linalg.norm(quad - c[1], axis=1).mean() < 0.015 * math.hypot(w, h)
                for c in selected
            ):
                continue
            selected.append((value, quad, support))
            candidates.append(
                {
                    "score": value,
                    "corners": (quad / [w, h]).tolist(),
                    "line_support": support.tolist(),
                }
            )
            if len(selected) == 8:
                break
    ambiguous = (
        len(candidates) > 1 and candidates[0]["score"] - candidates[1]["score"] < 0.05
    )
    status = "ambiguous" if ambiguous else "detected" if candidates else "not_detected"
    return {
        "status": status,
        "corners": candidates[0]["corners"] if status == "detected" else None,
        "candidates": candidates,
        "line_count": len(records),
        "considered": considered,
        "elapsed_s": time.perf_counter() - began,
    }


def court_consensus(samples, start, end):
    """Require agreement and temporal coverage; never average conflicting fits."""
    if (
        not 0 <= start < end
        or any(
            type(s.get("frame")) is not int or not start <= s["frame"] < end
            for s in samples
        )
        or any(a["frame"] >= b["frame"] for a, b in itertools.pairwise(samples))
    ):
        raise ValueError(
            "Court sample frames must be ordered and unique within the range"
        )
    valid = [s for s in samples if s["status"] == "detected"]
    if (
        len(valid) < 3
        or (valid[-1]["frame"] - valid[0]["frame"]) / max(1, end - start - 1) < 0.6
    ):
        return {"status": "insufficient_evidence", "corners": None}
    quads = np.asarray([s["corners"] for s in valid], dtype=float)
    if (
        quads.shape != (len(valid), 4, 2)
        or not np.isfinite(quads).all()
        or np.any(quads < 0)
        or np.any(quads > 1)
    ):
        raise ValueError(
            "Detected court samples require four finite normalized corners"
        )
    if any(
        np.linalg.norm(a - b, axis=1).max() > 0.012
        for a, b in itertools.combinations(quads, 2)
    ):
        return {"status": "changing_geometry", "corners": None}
    # Use an actual observed fit, rather than inventing blended line geometry.
    center = np.median(quads, axis=0)
    chosen = int(np.argmin(np.linalg.norm(quads - center, axis=2).mean(axis=1)))
    return {
        "status": "detected",
        "corners": quads[chosen].tolist(),
        "source_frame": valid[chosen]["frame"],
    }


def calibrate_ranges(video, root, timestamps, ranges, progress):
    """Analyze uncovered ranges of a single camera view without saving annotations."""
    calibrations, reviews = [], []
    for position, (start, end) in enumerate(ranges):
        indices = sorted(
            set(
                np.rint(np.linspace(start, end - 1, min(5, end - start)))
                .astype(int)
                .tolist()
            )
        )
        samples = []
        for index in indices:
            with closing(
                iter_frames(video, root, timestamps, index, index + 1)
            ) as frames:
                actual, timestamp, frame = next(frames)
                if (
                    actual != index
                    or not math.isfinite(timestamp)
                    or abs(timestamp - timestamps[index]) > 0.00002
                ):
                    raise ValueError(
                        "Court sample does not match its source frame timestamp"
                    )
                rgb = frame.to_ndarray(format="rgb24")
                detection = (
                    detect_court(rgb)
                    if min(rgb.shape[:2]) >= 128
                    else {
                        "status": "not_detected",
                        "corners": None,
                        "reason": "resolution_below_128px",
                    }
                )
                samples.append(
                    {
                        "frame": actual,
                        "time_s": timestamp,
                        **detection,
                    }
                )
        result = court_consensus(samples, start, end)
        if result["corners"] is not None:
            calibrations.append(
                {
                    "start_frame": start,
                    "end_frame": end,
                    "corners": [{"x": x, "y": y} for x, y in result["corners"]],
                }
            )
        reviews.append(
            {"start_frame": start, "end_frame": end, **result, "samples": samples}
        )
        progress((position + 1) / max(1, len(ranges)))
    return calibrations, {
        "method": METHOD,
        "review_status": "unreviewed",
        "ranges": reviews,
    }
