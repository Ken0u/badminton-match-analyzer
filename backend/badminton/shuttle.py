"""TrackNetV3 inference with bounded buffers and raw, unrepaired observations."""

import hashlib
import json
import time
from collections import deque
from contextlib import nullcontext

import cv2
import numpy as np
from PIL import Image

from .config import MODEL_MANIFEST, WEIGHTS
from .segments import scan_boundaries
from .video import iter_frames, timestamps_for, validate_range, write_json

WIDTH, HEIGHT = 512, 288


def locate_shuttle(heatmap, width, height, threshold=0.5):
    """Missing points use null coordinates; a real point on an edge remains valid."""
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
            "repaired": False,
        }
    component = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h, _area = stats[component]
    return {
        "visible": True,
        "x": float((x + w / 2) * width / heatmap.shape[1]),
        "y": float((y + h / 2) * height / heatmap.shape[0]),
        "confidence": float(heatmap[labels == component].max()),
        "components": count - 1,
        "repaired": False,
    }


def _rgb(frame):
    return np.asarray(frame.to_image().resize((WIDTH, HEIGHT)), dtype=np.uint8)


def infer_camera_segment(frames, background, length, predict, width, height):
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
        return {
            "frame": index,
            "time_s": timestamp,
            "shuttle": locate_shuttle(heat / denominators.pop(index), width, height),
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


def track_shuttle(video, root, data, start_frame, end_frame, progress, output):
    import torch

    from .vendor.tracknet_model import TrackNet

    times = timestamps_for(data, video["id"])
    validate_range(video, times, start_frame, end_frame)
    began = time.perf_counter()
    boundaries = scan_boundaries(
        video, root, data, start_frame, end_frame, lambda value: progress(value * 0.1)
    )
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
                frames, background, length, predict, video["width"], video["height"]
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
            "model": "TrackNetV3",
            "checkpoint_sha256": checksum,
            "device": device,
            "input_size": [WIDTH, HEIGHT],
            "seq_len": length,
            "precision": "float16" if device.startswith("cuda") else "float32",
            "ensemble": "weighted overlapping windows",
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
        write_json(output, result)
        return {k: v for k, v in result.items() if k != "frames"}
    finally:
        model = None
        if device.startswith("cuda"):
            torch.cuda.empty_cache()
