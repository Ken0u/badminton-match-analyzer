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


def track_shuttle(video, root, data, start_frame, end_frame, progress, output):
    import torch

    from .vendor.tracknet_model import TrackNet

    times = timestamps_for(data, video["id"])
    validate_range(video, times, start_frame, end_frame)
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
    began = time.perf_counter()
    rows = []
    try:
        # Match upstream preprocessing: median at source resolution, then PIL resize.
        sample_budget = max(
            1, (128 * 1024 * 1024) // (video["width"] * video["height"] * 3)
        )
        sample_ids = set(
            np.linspace(
                start_frame,
                end_frame - 1,
                min(48, sample_budget, end_frame - start_frame),
                dtype=int,
            ).tolist()
        )
        samples = []
        for index, t, frame in iter_frames(video, root, times, start_frame, end_frame):
            if index in sample_ids:
                samples.append(frame.to_ndarray(format="rgb24"))
            progress(0.15 * (index - start_frame + 1) / (end_frame - start_frame))
        median = np.median(np.stack(samples), axis=0).astype(np.uint8)
        background = np.asarray(Image.fromarray(median).resize((WIDTH, HEIGHT)))
        del samples, median
        buffer = deque()
        sums, denominators = {}, {}
        temporal_weights = np.minimum(
            np.arange(1, length + 1), np.arange(length, 0, -1)
        ).astype(np.float32)

        def finish(index):
            heat = sums.pop(index) / denominators.pop(index)
            rows.append(
                {
                    "frame": index,
                    "time_s": times[index],
                    "shuttle": locate_shuttle(heat, video["width"], video["height"]),
                }
            )

        def predict_window(items):
            real = len(items)
            padded = items + [items[-1]] * (length - real)
            images = [background] + [item[1] for item in padded]
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
                heatmaps = model(tensor)[0].float().cpu().numpy()
            for offset, (index, img) in enumerate(items):
                weighted = heatmaps[offset] * temporal_weights[offset]
                if index not in sums:
                    sums[index] = weighted
                    denominators[index] = temporal_weights[offset]
                else:
                    sums[index] += weighted
                    denominators[index] += temporal_weights[offset]

        for index, t, frame in iter_frames(video, root, times, start_frame, end_frame):
            buffer.append((index, _rgb(frame)))
            if len(buffer) == length:
                predict_window(list(buffer))
                finish(buffer[0][0])
                buffer.popleft()
            progress(
                0.15 + 0.85 * (index - start_frame + 1) / (end_frame - start_frame)
            )
        if not rows and buffer:
            predict_window(list(buffer))
        for index in sorted(sums):
            finish(index)
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
