"""Player/pose baseline. Identity labels remain unassigned until reviewed."""

import os
import time

import cv2
import numpy as np

from .config import WEIGHTS
from .video import iter_frames, timestamps_for, validate_range, write_json


def track_players(
    video, root, data, annotations, start_frame, end_frame, stride, progress, output
):
    runtime = data / "runtime"
    runtime.mkdir(exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(runtime / "ultralytics"))
    os.environ.setdefault("MPLCONFIGDIR", str(runtime / "matplotlib"))
    try:
        import torch
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "Install the tracking dependencies first; see README.md"
        ) from exc
    weights = WEIGHTS / "yolo11n-pose.pt"
    if not weights.exists():
        raise RuntimeError(
            "Player model missing. Run scripts/download_models.py first."
        )
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    if device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats()
    model = YOLO(str(weights))
    timestamps = timestamps_for(data, video["id"])
    validate_range(video, timestamps, start_frame, end_frame)
    began = time.perf_counter()
    rows, counts = [], []
    calibrated_frames = 0
    try:
        for index, timestamp, frame in iter_frames(
            video, root, timestamps, start_frame, end_frame
        ):
            if (index - start_frame) % stride:
                continue
            calibration = next(
                (
                    c
                    for c in annotations.calibrations
                    if c.start_frame <= index < c.end_frame
                ),
                None,
            )
            polygon = (
                np.array(
                    [
                        [p.x * video["width"], p.y * video["height"]]
                        for p in calibration.corners
                    ],
                    np.float32,
                )
                if calibration
                else None
            )
            calibrated_frames += polygon is not None
            result = model.track(
                frame.to_ndarray(format="bgr24"),
                persist=True,
                tracker="bytetrack.yaml",
                conf=0.25,
                imgsz=1280,
                device=device,
                verbose=False,
            )[0]
            players = []
            for i, box in enumerate(result.boxes):
                x1, y1, x2, y2 = box.xyxy[0].cpu().tolist()
                if (
                    polygon is not None
                    and cv2.pointPolygonTest(polygon, ((x1 + x2) / 2, y2), True)
                    < -video["height"] * 0.08
                ):
                    continue
                points = (
                    result.keypoints.data[i].cpu().tolist()
                    if result.keypoints is not None
                    else []
                )
                players.append(
                    {
                        "track_id": int(box.id.item()) if box.id is not None else None,
                        "player_id": None,
                        "box": [x1, y1, x2, y2],
                        "confidence": float(box.conf.item()),
                        "keypoints": points,
                    }
                )
            rows.append(
                {"frame": index, "time_s": timestamps[index], "players": players}
            )
            counts.append(len(players))
            progress((index - start_frame + 1) / max(1, end_frame - start_frame))
        elapsed = time.perf_counter() - began
        result = {
            "schema_version": 1,
            "video_id": video["id"],
            "stage": "players",
            "model": "yolo11n-pose",
            "device": device,
            "image_size": 1280,
            "peak_gpu_memory_mb": round(torch.cuda.max_memory_allocated() / 1e6, 1)
            if device.startswith("cuda")
            else None,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "stride": stride,
            "annotation_revision": annotations.revision,
            "calibrated": bool(rows) and calibrated_frames == len(rows),
            "calibrated_frames": calibrated_frames,
            "elapsed_s": round(elapsed, 3),
            "processed_frames": len(rows),
            "inference_fps": round(len(rows) / max(elapsed, 0.001), 2),
            "expected_players": 2 if video["mode"] == "singles" else 4,
            "mean_detections": round(sum(counts) / max(1, len(counts)), 2),
            "frames": rows,
        }
        write_json(output, result)
        return {k: v for k, v in result.items() if k != "frames"}
    finally:
        del model
        if device.startswith("cuda"):
            torch.cuda.empty_cache()
