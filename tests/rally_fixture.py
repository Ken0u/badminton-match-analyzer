"""Generated camera/pose cues for software QA, never match ground truth."""

from copy import deepcopy
from fractions import Fraction

import av
import numpy as np
from badminton.ingest import inspect_video
from badminton.rallies import context_signature
from badminton.schemas import Annotations
from badminton.storage import Store
from badminton.video import write_json


def scene(mode="singles", times=None):
    times = times or [i / 25 for i in range(100)]
    count = len(times)
    video = {
        "id": "test",
        "sha256": "a" * 64,
        "mode": mode,
        "width": 1000,
        "height": 600,
        "frame_count": count,
    }
    doc = {
        "revision": 1,
        "calibrations": [
            {
                "start_frame": 0,
                "end_frame": count,
                "corners": [
                    {"x": x, "y": y} for x, y in [(0, 0), (1, 0), (1, 1), (0, 1)]
                ],
            }
        ],
    }
    people = []
    for tid, (x, y) in enumerate(
        [(350, 480), (650, 180), (750, 480), (250, 180)][
            : 2 if mode == "singles" else 4
        ]
    ):
        points = [[0, 0, 0] for _ in range(17)]
        points[9] = [x, y - 40, 0.9]
        points[10] = [x + 10, y - 40, 0.9]
        points[11] = points[12] = [x, y - 30, 0.9]
        people.append(
            {
                "track_id": tid,
                "confidence": 0.9,
                "box": [x - 50, y - 100, x + 50, y],
                "keypoints": points,
            }
        )
    players = {
        "stage": "players",
        "video_id": "test",
        "start_frame": 0,
        "end_frame": count,
        "stride": 1,
        "cut_frames": [],
        "frames": [
            {
                "frame": i,
                "time_s": t,
                "calibration_valid": True,
                "players": deepcopy(people),
            }
            for i, t in enumerate(times)
        ],
    }
    shuttle = {
        "stage": "shuttle",
        "video_id": "test",
        "start_frame": 0,
        "end_frame": count,
        "stride": 1,
        "cut_frames": [],
        "frames": [
            {
                "frame": i,
                "time_s": t,
                "shuttle": {
                    "visible": True,
                    "x": 350 + min(max(t - 1, 0), 0.6) * 375,
                    "y": 440,
                },
            }
            for i, t in enumerate(times)
        ],
    }
    return video, players, shuttle, doc


def catalog(root, data):
    """Create real source media plus deliberately generated perception artifacts."""
    source = root / "rally-qa.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(source), "w") as container:
        stream = container.add_stream("libx264", rate=25)
        stream.width, stream.height = 1000, 600
        stream.pix_fmt = "yuv420p"
        for i in range(100):
            frame = av.VideoFrame.from_ndarray(
                np.full((600, 1000, 3), 45 + i, np.uint8), "rgb24"
            )
            frame.pts, frame.time_base = i, Fraction(1, 25)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    store = Store(data)
    video = inspect_video(source, "singles", store, root)
    _, players, shuttle, doc = scene()
    saved = store.annotations(video["id"]).model_dump()
    saved["calibrations"] = doc["calibrations"]
    saved = store.save_annotations(video["id"], Annotations.model_validate(saved))
    for run, job_id in ((players, "qa-players"), (shuttle, "qa-shuttle")):
        run.update(
            video_id=video["id"],
            video_sha256=video["sha256"],
            processed_frames=100,
            inference_fps=25,
            device="qa_fixture",
            model="synthetic_qa",
        )
        if run["stage"] == "players":
            run.update(
                calibrated=True,
                calibration_signature=context_signature(saved, 0, 100)["court"],
            )
        else:
            run["visible_frames"] = 100
        write_json(data / video["id"] / "runs" / f"{job_id}.json", run)
        store.put_job(
            {
                "id": job_id,
                "video_id": video["id"],
                "kind": run["stage"],
                "status": "completed",
                "progress": 1,
                "summary": {k: v for k, v in run.items() if k != "frames"},
            }
        )
    return store, video
