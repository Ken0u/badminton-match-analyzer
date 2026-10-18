"""Player/pose baseline. Identity labels remain unassigned until reviewed."""

import hashlib
import json
import os
import time

import cv2
import numpy as np

from .calibration_context import (
    court_signature,
    effective_annotations,
    uncovered_ranges,
)
from .config import MODEL_MANIFEST, WEIGHTS
from .court_detection import calibrate_ranges
from .scene_review import corrected_boundaries, reviewed_run
from .schemas import Calibration
from .segments import scan_boundaries
from .video import iter_frames, timestamps_for, validate_range, write_json


def player_checkpoint(variant):
    keys = {"small": "player_pose_small", "nano": "player_pose"}
    if variant not in keys:
        raise ValueError("Choose small or nano for the player model")
    entry = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))[keys[variant]]
    folder = WEIGHTS.resolve()
    path = (folder / entry["name"]).resolve()
    if not path.is_relative_to(folder) or path.parent != folder:
        raise ValueError("Player checkpoint must be inside the weights directory")
    if not path.is_file():
        raise RuntimeError(
            f"Player model missing. Run scripts/download_models.py --kind player --player-model {variant}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != entry["sha256"]:
        raise RuntimeError("Player checkpoint does not match its pinned model manifest")
    return path, entry


def track_players(
    video,
    root,
    data,
    annotations,
    start_frame,
    end_frame,
    stride,
    progress,
    output,
    player_model="small",
    auto_calibrate=True,
):
    runtime = data / "runtime"
    runtime.mkdir(exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(runtime / "ultralytics"))
    os.environ.setdefault("MPLCONFIGDIR", str(runtime / "matplotlib"))
    try:
        import torch

        # Importing torchvision.io installs a Python FFmpeg logging callback.
        # Finish that initialization before opening any threaded decoder.
        import torchvision  # noqa: F401
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "Install the tracking dependencies first; see README.md"
        ) from exc
    weights, checkpoint = player_checkpoint(player_model)
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    if device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats()
    timestamps = timestamps_for(data, video["id"])
    validate_range(video, timestamps, start_frame, end_frame)
    began = time.perf_counter()
    boundaries = scan_boundaries(
        video, root, data, start_frame, end_frame, lambda value: progress(value * 0.1)
    )
    boundaries = corrected_boundaries(boundaries, annotations, start_frame, end_frame)
    cut_frames = set(boundaries["cut_frames"])
    court_context = {
        **boundaries,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "court_context_version": 1,
    }
    automatic, court_detection = [], None
    if auto_calibrate:
        valid_manual = effective_annotations(annotations, court_context)["calibrations"]
        blocked = [(c["start_frame"], c["end_frame"]) for c in valid_manual]
        blocked += [
            (r.start_frame, r.end_frame)
            for r in annotations.scene_ranges
            if r.scene != "live"
        ]
        ranges = [
            gap
            for view in boundaries["camera_ranges"]
            for gap in uncovered_ranges(view["start_frame"], view["end_frame"], blocked)
        ]
        automatic, court_detection = calibrate_ranges(
            video, root, timestamps, ranges, lambda value: progress(0.1 + value * 0.1)
        )
    court_context["automatic_calibrations"] = automatic
    effective = effective_annotations(annotations, court_context)
    calibrations = [Calibration.model_validate(c) for c in effective["calibrations"]]
    rows, counts = [], []
    calibrated_frames = 0
    segment_start = start_frame
    last_cut = (
        start_frame
        if start_frame in cut_frames
        else boundaries["preceding_reviewed_cut_frame"]
    )
    track_offset, largest_track = 0, 0
    pending_reset = False
    model = YOLO(str(weights))
    try:
        for index, timestamp, frame in iter_frames(
            video, root, timestamps, start_frame, end_frame
        ):
            if index in cut_frames and index > start_frame:
                segment_start = index
                last_cut = index
                pending_reset = True
            if (index - start_frame) % stride:
                continue
            if pending_reset:
                # Ultralytics' tracker reset also resets its numeric ID counter.
                # Allocate a disjoint namespace so reviewed identities cannot
                # silently attach to a different person after the edit.
                for tracker in getattr(model.predictor, "trackers", []):
                    tracker.reset()
                track_offset = largest_track
                pending_reset = False
            calibration = next(
                (
                    c
                    for c in calibrations
                    if c.start_frame <= index < c.end_frame
                    and (last_cut is None or c.start_frame >= last_cut)
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
                        "track_id": int(box.id.item()) + track_offset
                        if box.id is not None
                        else None,
                        "player_id": None,
                        "box": [x1, y1, x2, y2],
                        "confidence": float(box.conf.item()),
                        "keypoints": points,
                    }
                )
                if players[-1]["track_id"] is not None:
                    largest_track = max(largest_track, players[-1]["track_id"])
            rows.append(
                {
                    "frame": index,
                    "time_s": timestamps[index],
                    "players": players,
                    "camera_segment_start_frame": segment_start,
                    "calibration_valid": calibration is not None,
                }
            )
            counts.append(len(players))
            progress(
                0.2 + 0.8 * (index - start_frame + 1) / max(1, end_frame - start_frame)
            )
        elapsed = time.perf_counter() - began
        result = {
            "schema_version": 1,
            "video_id": video["id"],
            "stage": "players",
            "video_sha256": video["sha256"],
            "calibration_signature": court_signature(effective, start_frame, end_frame),
            "automatic_calibrations": automatic,
            "court_detection": court_detection,
            "auto_calibrate": auto_calibrate,
            "court_context_version": 1,
            "model": checkpoint["name"].removesuffix(".pt"),
            "model_variant": player_model,
            "checkpoint_sha256": checkpoint["sha256"],
            "model_source": checkpoint["source"],
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
            "cut_frames": boundaries["cut_frames"],
            "camera_boundary_method": boundaries["method"],
            "camera_ranges": boundaries["camera_ranges"],
            "tracker_reset_at_cuts": True,
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
        del model
        if device.startswith("cuda"):
            torch.cuda.empty_cache()
