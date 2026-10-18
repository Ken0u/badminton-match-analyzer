"""Player/pose baseline. Identity labels remain unassigned until reviewed."""

import hashlib
import json
import math
import os
import time
from types import SimpleNamespace

import cv2
import numpy as np

from .calibration_context import (
    court_signature,
    effective_annotations,
    uncovered_ranges,
)
from .config import MODEL_MANIFEST, WEIGHTS
from .court_detection import calibrate_ranges
from .scene_review import corrected_boundaries, reviewed_run, scene_review_signature
from .schemas import Calibration
from .segments import scan_boundaries, slice_camera_scan
from .track_consensus import RECIPE as CONSENSUS_RECIPE
from .track_consensus import corroborate_tracks
from .video import iter_frames, timestamps_for, validate_range, write_json

BYTE_TRACK_CONFIG = {
    "tracker_type": "bytetrack",
    "track_high_thresh": 0.25,
    "track_low_thresh": 0.1,
    "new_track_thresh": 0.25,
    "track_buffer": 30,
    "match_thresh": 0.8,
    "fuse_score": True,
}
TRACKER_CONFIG = {
    **BYTE_TRACK_CONFIG,
    "tracker_type": "botsort",
    "gmc_method": "sparseOptFlow",
    "proximity_thresh": 0.5,
    "appearance_thresh": 0.8,
    "with_reid": False,
    "model": "auto",
}
TRACKING_RECIPE = {
    "method": "baseline observations with motion-corroborated continuity v4",
    "detector_confidence": 0.1,
    "observation_confidence": 0.25,
    "tracker_config": TRACKER_CONFIG,
    "baseline_config": BYTE_TRACK_CONFIG,
    "baseline_detector_confidence": 0.25,
    "weak_observations": "Tracker association only; absent from published player rows",
    "appearance_reidentification": False,
    "continuity_recipe": CONSENSUS_RECIPE,
}


def association_trackers():
    from ultralytics.trackers.bot_sort import BOTSORT
    from ultralytics.trackers.byte_tracker import BYTETracker

    # Initialize both engines before any frame. Their IDs are separate evidence
    # namespaces (numeric overlap is valid); reset both only at a camera cut.
    return (
        BYTETracker(SimpleNamespace(**BYTE_TRACK_CONFIG)),
        BOTSORT(SimpleNamespace(**TRACKER_CONFIG)),
    )


def associate_observations(result, tracker, image, threshold, offset, pose=True):
    """Preserve detector/pose indices through score filtering and association."""
    detections = result.boxes.cpu().numpy()
    indices = np.flatnonzero(detections.conf >= threshold)
    selected = detections[indices]
    tracks = tracker.update(selected, image)
    # Match Ultralytics' handling of newly unconfirmed tracks. When there is no
    # association at all, retain a raw strong detection with an unknown ID.
    if not len(tracks) and any(not t.is_activated for t in tracker.tracked_stracks):
        return []
    observations = (
        [(int(t[-1]), t[:4].tolist(), int(t[4]) + offset, float(t[5])) for t in tracks]
        if len(tracks)
        else [
            (i, box.tolist(), None, float(selected.conf[i]))
            for i, box in enumerate(selected.xyxy)
        ]
    )
    players = []
    for index, box, identity, confidence in observations:
        points = (
            result.keypoints.data[int(indices[index])].cpu().tolist()
            if pose and result.keypoints is not None
            else []
        )
        players.append(
            {
                "track_id": identity,
                "player_id": None,
                "box": box,
                "confidence": confidence,
                "keypoints": points,
            }
        )
    return players


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
    camera_scan=None,
):
    runtime = data / "runtime"
    runtime.mkdir(exist_ok=True)
    # Keep the baseline high-score associations; only the corroborating tracker
    # receives the weak band. Persist settings rather than mutable library defaults.
    write_json(runtime / "badminton-dual-trackers-v1.json", TRACKING_RECIPE)
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
    boundaries = (
        slice_camera_scan(video, camera_scan, start_frame, end_frame)
        if camera_scan is not None
        else scan_boundaries(
            video,
            root,
            data,
            start_frame,
            end_frame,
            lambda value: progress(value * 0.1),
        )
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
    weak_observations = 0
    segment_start = start_frame
    last_cut = (
        start_frame
        if start_frame in cut_frames
        else boundaries["preceding_reviewed_cut_frame"]
    )
    if camera_scan is not None:
        segment_start = last_cut if last_cut is not None else 0
    track_offset, largest_track = 0, 0
    pending_reset = False
    model = YOLO(str(weights))
    trackers = association_trackers()
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
                for tracker in trackers:
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
            image = frame.to_ndarray(format="bgr24")
            result = model.predict(
                image,
                conf=TRACKING_RECIPE["detector_confidence"],
                imgsz=1280,
                device=device,
                verbose=False,
            )[0]
            groups = []
            for tracker, threshold, pose in (
                (trackers[0], TRACKING_RECIPE["baseline_detector_confidence"], True),
                (trackers[1], TRACKING_RECIPE["detector_confidence"], False),
            ):
                observed = associate_observations(
                    result, tracker, image, threshold, track_offset, pose
                )
                players = []
                for person in observed:
                    if person["track_id"] is not None:
                        largest_track = max(largest_track, person["track_id"])
                    x1, _y1, x2, y2 = person["box"]
                    if (
                        polygon is not None
                        and cv2.pointPolygonTest(polygon, ((x1 + x2) / 2, y2), True)
                        < -video["height"] * 0.08
                    ):
                        continue
                    confidence = person["confidence"]
                    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                        continue
                    if confidence < TRACKING_RECIPE["observation_confidence"]:
                        weak_observations += 1
                        continue
                    players.append(person)
                groups.append(players)
            rows.append(
                {
                    "frame": index,
                    "time_s": timestamps[index],
                    "players": groups[0],
                    "motion_players": groups[1],
                    "camera_segment_start_frame": segment_start,
                    "calibration_valid": calibration is not None,
                }
            )
            counts.append(len(groups[0]))
            progress(
                0.2 + 0.75 * (index - start_frame + 1) / max(1, end_frame - start_frame)
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
            "tracking_recipe": TRACKING_RECIPE,
            "weak_court_observations_hidden": weak_observations,
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
                    "known_preceding_cut_frames",
                    "known_preceding_timestamp_gaps",
                )
                if key in boundaries
            }
        )
        result = reviewed_run(result, annotations)
        mapping, evidence = corroborate_tracks(
            video, result["frames"], stride, lambda value: progress(0.95 + value * 0.05)
        )
        for row in result["frames"]:
            for person in row["players"]:
                person["baseline_track_id"] = person["track_id"]
                person["track_id"] = mapping.get(person["track_id"], person["track_id"])
        result["track_continuity"] = evidence
        evidence["scene_signature"] = scene_review_signature(
            annotations, start_frame, end_frame
        )
        result["continuity_scene_signature"] = evidence["scene_signature"]
        result["uses_motion_continuity"] = bool(evidence["links"])
        elapsed = time.perf_counter() - began
        result["elapsed_s"] = round(elapsed, 3)
        result["inference_fps"] = round(len(rows) / max(elapsed, 0.001), 2)
        write_json(output, result)
        return {k: v for k, v in result.items() if k != "frames"}
    finally:
        del model
        if device.startswith("cuda"):
            torch.cuda.empty_cache()
