"""Source-frame camera boundaries; these do not classify play or replays."""

import math
import time
from itertools import pairwise

from scenedetect import FrameTimecode
from scenedetect.detectors import AdaptiveDetector

from .video import SourceChangedError, iter_frames, timestamps_for, write_json

METHOD = "PySceneDetect 0.7.2 AdaptiveDetector at 320px v1"
RECIPE = {
    "width": 320,
    "adaptive_threshold": 3.0,
    "min_content_val": 15.0,
    "min_scene_len": 15,
    "window_width": 2,
}


def camera_ranges(start, end, cuts):
    """Half-open ranges; a cut is the first source frame of the new camera view."""
    if not 0 <= start < end:
        raise ValueError("Camera ranges need a nonempty source-frame interval")
    points = [start, *sorted({cut for cut in cuts if start < cut < end}), end]
    return [
        {"start_frame": left, "end_frame": right, "scene": "unknown"}
        for left, right in pairwise(points)
    ]


def scan_boundaries(video, root, data, start, end, progress):
    """Decode every source frame; nominal FPS is not used for source timing.

    The detector's typed timecode carries only its source frame index. All
    exported times come from the imported PTS map, including VFR footage.
    Two future frames support the detector's look-ahead at a requested edge.
    Timestamp discontinuities form separate contexts even without a visual cut.
    """
    times = timestamps_for(data, video["id"])
    if not 0 <= start < end <= len(times):
        raise ValueError("Camera scan range must lie inside the source video")
    rate = float(video["fps"])
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("Camera scan requires a finite positive nominal rate")
    gap_threshold = max(0.1, 2.5 / rate)
    began = time.perf_counter()
    # The rolling window also needs preceding frame scores. Keep its first-cut
    # suppression outside the requested range whenever preceding media exists.
    scan_start = max(0, start - RECIPE["min_scene_len"] - 3)
    scan_end = min(len(times), end + RECIPE["window_width"])
    detector = AdaptiveDetector(
        adaptive_threshold=RECIPE["adaptive_threshold"],
        min_content_val=RECIPE["min_content_val"],
        min_scene_len=RECIPE["min_scene_len"],
        window_width=RECIPE["window_width"],
    )
    cuts = {}
    previous_time = None
    width = min(RECIPE["width"], video["width"])
    height = max(2, round(video["height"] * width / video["width"]))
    processed = 0
    for index, timestamp, frame in iter_frames(
        video, root, times, scan_start, scan_end
    ):
        if (
            previous_time is not None
            and timestamp - previous_time > gap_threshold + 1e-8
        ):
            if start <= index < end:
                cuts[index] = "timestamp_discontinuity"
            detector = AdaptiveDetector(
                adaptive_threshold=RECIPE["adaptive_threshold"],
                min_content_val=RECIPE["min_content_val"],
                min_scene_len=RECIPE["min_scene_len"],
                window_width=RECIPE["window_width"],
            )
        previous_time = timestamp
        image = frame.reformat(width=width, height=height, format="bgr24").to_ndarray()
        for cut in detector.process_frame(FrameTimecode(index, fps=rate), image):
            if start <= cut.frame_num < end:
                cuts.setdefault(cut.frame_num, "visual_cut")
        processed += 1
        if processed % 25 == 0:
            progress(processed / (scan_end - scan_start))
    if processed != scan_end - scan_start:
        raise SourceChangedError(
            "Camera scan did not decode every requested source frame"
        )
    boundaries = [
        {"frame": index, "time_s": times[index], "reason": reason, "reviewed": False}
        for index, reason in sorted(cuts.items())
    ]
    progress(1)
    return {
        "method": METHOD,
        "recipe": RECIPE.copy(),
        "timestamp_gap_threshold_s": gap_threshold,
        "cut_frames": sorted(cuts),
        "boundaries": boundaries,
        "camera_ranges": camera_ranges(start, end, cuts),
        "elapsed_s": round(time.perf_counter() - began, 3),
        "decoded_frames": processed,
        "scope": "Camera/timestamp boundaries only; live, replay and rally status unknown",
    }


def scan_video(video, root, data, progress, output):
    result = {
        "schema_version": 1,
        "stage": "segments",
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "start_frame": 0,
        "end_frame": video["frame_count"],
    } | scan_boundaries(video, root, data, 0, video["frame_count"], progress)
    write_json(output, result)
    return {
        key: value
        for key, value in result.items()
        if key not in ("boundaries", "camera_ranges")
    }
