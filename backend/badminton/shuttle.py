"""TrackNetV3 inference with bounded buffers and raw, unrepaired observations."""

import hashlib
import itertools
import json
import math
import time
from collections import deque
from contextlib import nullcontext

import cv2
import numpy as np
from PIL import Image

from .config import MODEL_MANIFEST, WEIGHTS
from .scene_review import corrected_boundaries, plain, reviewed_run
from .segments import scan_boundaries
from .video import iter_frames, timestamps_for, validate_range, write_json

WIDTH, HEIGHT = 512, 288
LOCALIZATION_METHOD = "observed components with bounded source-motion selection v1"
SELECTION_HISTORY = 3
MAX_SELECTION_STEP_S = 0.10
MAX_SELECTION_SPEED_DIAGONALS_S = 6


def localization_recipe():
    return {
        "method": LOCALIZATION_METHOD,
        "heatmap_threshold": 0.5,
        "coordinate_method": "thresholded component bounding-box center",
        "history_observations": SELECTION_HISTORY,
        "maximum_source_step_s": MAX_SELECTION_STEP_S,
        "maximum_speed_diagonals_per_s": MAX_SELECTION_SPEED_DIAGONALS_S,
        "scene_context": "History resets at camera boundaries and reviewed scene starts/ends",
        "switch_rule": "Largest component unreachable and exactly one observed alternative reachable",
        "missing_points": "Never interpolated; history resets on missing observations or discontinuity",
    }


def locate_shuttle(heatmap, width, height, threshold=0.5):
    """Retain every observed component, with the largest as the initial choice."""
    if heatmap.ndim != 2 or not heatmap.size or not np.isfinite(heatmap).all():
        raise ValueError("Shuttle heatmaps must be nonempty finite 2D arrays")
    score = float(heatmap.max())
    mask = np.asarray(heatmap > threshold, dtype=np.uint8)
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    if count <= 1:
        return {
            "visible": False,
            "x": None,
            "y": None,
            "confidence": score,
            "components": 0,
            "component_candidates": [],
            "selected_component_id": None,
            "largest_component_id": None,
            "selection_reason": "no_observed_component",
            "repaired": False,
        }
    candidates = []
    for component in range(1, count):
        x, y, w, h, area = stats[component]
        candidates.append(
            {
                "id": component,
                "x": float((x + w / 2) * width / heatmap.shape[1]),
                "y": float((y + h / 2) * height / heatmap.shape[0]),
                "confidence": float(heatmap[labels == component].max()),
                "area_heatmap_pixels": int(area),
                "box_heatmap": [int(v) for v in (x, y, w, h)],
            }
        )
    primary = max(candidates, key=lambda c: c["area_heatmap_pixels"])
    return {
        "visible": True,
        "x": primary["x"],
        "y": primary["y"],
        "confidence": primary["confidence"],
        "components": count - 1,
        "component_candidates": candidates,
        "selected_component_id": primary["id"],
        "largest_component_id": primary["id"],
        "selection_reason": "largest_heatmap_component",
        "repaired": False,
    }


class _ComponentSelector:
    """Select an observed alternative only after an implausible source-frame jump.

    This is not trajectory repair or constant-velocity extrapolation. Abrupt
    direction changes remain valid, and multiple reachable alternatives do not
    justify changing the primary observation. State belongs to one camera view.
    """

    def __init__(self, width, height):
        self.diagonal = math.hypot(width, height)
        self.history = deque(maxlen=SELECTION_HISTORY)

    def _continuous(self, before, after):
        return (
            after[0] == before[0] + 1
            and 0 < after[1] - before[1] <= MAX_SELECTION_STEP_S + 1e-9
        )

    def _reachable(self, before, after):
        return math.hypot(after[2] - before[2], after[3] - before[3]) <= (
            self.diagonal * MAX_SELECTION_SPEED_DIAGONALS_S * (after[1] - before[1])
            + 1e-9
        )

    def reset(self):
        self.history.clear()

    def select(self, point, frame, timestamp):
        result = dict(point)
        current = (frame, timestamp, point["x"], point["y"])
        if not math.isfinite(timestamp) or not point["visible"]:
            self.reset()
            return result
        if self.history and not self._continuous(self.history[-1], current):
            self.reset()
        result.update(
            selection_context_start_frame=frame, selection_context_end_frame=frame + 1
        )
        history = list(self.history)
        stable = len(history) == SELECTION_HISTORY and all(
            self._continuous(a, b) and self._reachable(a, b)
            for a, b in itertools.pairwise(history)
        )
        if stable and not self._reachable(history[-1], current):
            reachable = [
                c
                for c in point["component_candidates"]
                if self._reachable(history[-1], (frame, timestamp, c["x"], c["y"]))
            ]
            if len(reachable) == 1:
                chosen = reachable[0]
                result.update(
                    x=chosen["x"],
                    y=chosen["y"],
                    confidence=chosen["confidence"],
                    selected_component_id=chosen["id"],
                    selection_reason="unique_reachable_component",
                    selection_context_frames=[r[0] for r in history],
                    selection_context_start_frame=min(r[4] for r in history),
                )
        self.history.append(
            (
                frame,
                timestamp,
                result["x"],
                result["y"],
                result["selection_context_start_frame"],
            )
        )
        return result


def _rgb(frame):
    return np.asarray(frame.to_image().resize((WIDTH, HEIGHT)), dtype=np.uint8)


def infer_camera_segment(
    frames, background, length, predict, width, height, *, selection_reset_frames=()
):
    """Bounded temporal ensemble for exactly one camera view.

    The caller supplies a fresh background and source-frame iterator for each
    half-open segment. No real frame or heatmap can leak across its boundary.
    Only a short segment's final frame is repeated for model shape padding.
    """
    buffer = deque()
    sums, denominators = {}, {}
    weights = np.minimum(np.arange(1, length + 1), np.arange(length, 0, -1)).astype(
        np.float32
    )
    emitted = False
    selector = _ComponentSelector(width, height)
    reset_frames = set(selection_reset_frames)

    def predict_window(items):
        padded = items + [items[-1]] * (length - len(items))
        heatmaps = predict([background] + [item[2] for item in padded])
        for offset, (index, timestamp, _image) in enumerate(items):
            weighted = heatmaps[offset] * weights[offset]
            if index not in sums:
                sums[index] = (timestamp, weighted)
                denominators[index] = weights[offset]
            else:
                sums[index] = (timestamp, sums[index][1] + weighted)
                denominators[index] += weights[offset]

    def finish(index):
        timestamp, heat = sums.pop(index)
        if index in reset_frames:
            selector.reset()
        return {
            "frame": index,
            "time_s": timestamp,
            "shuttle": selector.select(
                locate_shuttle(heat / denominators.pop(index), width, height),
                index,
                timestamp,
            ),
        }

    for index, timestamp, frame in frames:
        buffer.append((index, timestamp, _rgb(frame)))
        if len(buffer) == length:
            predict_window(list(buffer))
            yield finish(buffer[0][0])
            emitted = True
            buffer.popleft()
    if not emitted and buffer:
        predict_window(list(buffer))
    for index in sorted(sums):
        yield finish(index)


def track_shuttle(
    video, root, data, start_frame, end_frame, progress, output, annotations=None
):
    import torch

    from .vendor.tracknet_model import TrackNet

    times = timestamps_for(data, video["id"])
    validate_range(video, times, start_frame, end_frame)
    began = time.perf_counter()
    boundaries = scan_boundaries(
        video, root, data, start_frame, end_frame, lambda value: progress(value * 0.1)
    )
    if annotations is None:
        from .storage import Store

        annotations = Store(data).annotations(video["id"])
    boundaries = corrected_boundaries(boundaries, annotations, start_frame, end_frame)
    selection_reset_frames = {
        boundary
        for scene in plain(annotations).get("scene_ranges", [])
        for boundary in (plain(scene)["start_frame"], plain(scene)["end_frame"])
    }
    weights = WEIGHTS / "TrackNet_best.pt"
    if not weights.exists():
        raise RuntimeError(
            "Shuttle model missing. Run scripts/download_models.py --kind shuttle."
        )
    manifest = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))["shuttle"]
    checksum = hashlib.sha256(weights.read_bytes()).hexdigest()
    if not manifest or checksum != manifest["sha256"]:
        raise RuntimeError("Shuttle checkpoint does not match the model manifest")
    checkpoint = torch.load(weights, map_location="cpu", weights_only=True)
    params = checkpoint["param_dict"]
    length = params["seq_len"]
    if params["bg_mode"] != "concat" or not 1 <= length <= 32:
        raise RuntimeError(
            "This adapter expects a background-concatenated TrackNet checkpoint"
        )
    model = TrackNet((length + 1) * 3, length)
    model.load_state_dict(checkpoint["model"])
    del checkpoint
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    model = model.to(device).eval()
    if device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats()
    rows = []
    try:

        def predict(images):
            array = np.concatenate(
                [np.moveaxis(img, -1, 0) for img in images], axis=0
            ).copy()
            tensor = (
                torch.from_numpy(array)
                .unsqueeze(0)
                .to(device=device, dtype=torch.float32)
                / 255
            )
            context = (
                torch.autocast(device_type="cuda", dtype=torch.float16)
                if device.startswith("cuda")
                else nullcontext()
            )
            with torch.inference_mode(), context:
                return model(tensor)[0].float().cpu().numpy()

        for segment in boundaries["camera_ranges"]:
            first, last = segment["start_frame"], segment["end_frame"]
            offset = 0.1 + 0.9 * (first - start_frame) / (end_frame - start_frame)
            fraction = 0.9 * (last - first) / (end_frame - start_frame)
            # Match upstream median-at-source-resolution preprocessing, separately
            # for each view. Never mix a close-up into the court background.
            sample_budget = max(
                1, (128 * 1024 * 1024) // (video["width"] * video["height"] * 3)
            )
            sample_ids = set(
                np.linspace(
                    first, last - 1, min(48, sample_budget, last - first), dtype=int
                ).tolist()
            )
            samples = []
            for index, _t, frame in iter_frames(video, root, times, first, last):
                if index in sample_ids:
                    samples.append(frame.to_ndarray(format="rgb24"))
                progress(
                    offset + fraction * 0.15 * (index - first + 1) / (last - first)
                )
            median = np.median(np.stack(samples), axis=0).astype(np.uint8)
            background = np.asarray(Image.fromarray(median).resize((WIDTH, HEIGHT)))
            del samples, median
            frames = iter_frames(video, root, times, first, last)
            for row in infer_camera_segment(
                frames,
                background,
                length,
                predict,
                video["width"],
                video["height"],
                selection_reset_frames=selection_reset_frames,
            ):
                row["camera_segment_start_frame"] = first
                rows.append(row)
                progress(
                    offset
                    + fraction
                    * (0.15 + 0.85 * (row["frame"] - first + 1) / (last - first))
                )
        if len(rows) != end_frame - start_frame:
            raise RuntimeError(
                "Shuttle output did not cover the requested source frames"
            )
        elapsed = time.perf_counter() - began
        result = {
            "schema_version": 1,
            "video_id": video["id"],
            "stage": "shuttle",
            "video_sha256": video["sha256"],
            "model": "TrackNetV3",
            "checkpoint_sha256": checksum,
            "device": device,
            "input_size": [WIDTH, HEIGHT],
            "seq_len": length,
            "precision": "float16" if device.startswith("cuda") else "float32",
            "ensemble": "weighted overlapping windows",
            "localization": localization_recipe(),
            "component_selection_frames": sum(
                row["shuttle"]["selection_reason"] == "unique_reachable_component"
                for row in rows
            ),
            "start_frame": start_frame,
            "end_frame": end_frame,
            "processed_frames": len(rows),
            "visible_frames": sum(row["shuttle"]["visible"] for row in rows),
            "repaired_frames": 0,
            "cut_frames": boundaries["cut_frames"],
            "camera_boundary_method": boundaries["method"],
            "camera_ranges": boundaries["camera_ranges"],
            "temporal_context_crosses_detected_cuts": False,
            "elapsed_s": round(elapsed, 3),
            "inference_fps": round(len(rows) / max(elapsed, 0.001), 2),
            "peak_gpu_memory_mb": round(torch.cuda.max_memory_allocated() / 1e6, 1)
            if device.startswith("cuda")
            else None,
            "frames": rows,
        }
        result.update(
            {
                key: boundaries[key]
                for key in (
                    "raw_cut_frames",
                    "applied_camera_corrections",
                    "camera_annotation_revision",
                    "preceding_reviewed_cut_frame",
                )
            }
        )
        result = reviewed_run(result, annotations)
        write_json(output, result)
        return {k: v for k, v in result.items() if k != "frames"}
    finally:
        model = None
        if device.startswith("cuda"):
            torch.cuda.empty_cache()
