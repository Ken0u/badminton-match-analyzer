"""Generated-media contact review QA, independent of samples and checkpoints."""

import sys
from fractions import Fraction
from pathlib import Path
from tempfile import mkdtemp

import av
import cv2
import numpy as np
import uvicorn
from badminton.api import create_app
from badminton.config import ROOT
from badminton.ingest import inspect_video
from badminton.schemas import Calibration
from badminton.shuttle import _ComponentSelector, localization_recipe, locate_shuttle
from badminton.storage import Store
from badminton.video import write_json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from contact_profile_fixture import motion_scene


def prepare(root, data):
    shuttle, players, _, _ = motion_scene()
    selector = _ComponentSelector(640, 360)
    for row in shuttle["frames"]:
        point = row["shuttle"]
        heat = np.zeros((360, 640), np.float32)
        heat[round(point["y"]), round(point["x"])] = 0.9
        if 17 <= row["frame"] <= 23:
            heat[20:23, 20:23] = 0.95  # Deliberate detector ghost, not video truth.
        row["shuttle"] = selector.select(
            locate_shuttle(heat, 640, 360), row["frame"], row["time_s"]
        )
    path = root / "contact-profile-qa.mp4"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = 640, 360, "yuv420p"
        for row in shuttle["frames"]:
            picture = np.full((360, 640, 3), 30, np.uint8)
            point = row["shuttle"]
            cv2.circle(
                picture, (round(point["x"]), round(point["y"])), 4, (240, 240, 240), -1
            )
            frame = av.VideoFrame.from_ndarray(picture, "bgr24")
            frame.pts, frame.time_base = row["frame"], Fraction(1, 30)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    store = Store(data)
    video = inspect_video(path, "singles", store, root)
    doc = store.annotations(video["id"])
    doc.calibrations = [
        Calibration(
            start_frame=0,
            end_frame=45,
            corners=[{"x": x, "y": y} for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))],
        )
    ]
    store.save_annotations(video["id"], doc)
    for run in (players, shuttle):
        stage = "players" if run is players else "shuttle"
        job_id = f"qa-{stage}"
        run.update(
            stage=stage,
            video_id=video["id"],
            video_sha256=video["sha256"],
            start_frame=0,
            end_frame=45,
            stride=1,
            processed_frames=45,
            inference_fps=30,
            device="qa_fixture",
            model="synthetic_qa",
        )
        if stage == "players":
            run.update(calibrated=True, calibrated_frames=45)
            for row in run["frames"]:
                row["players"][0]["confidence"] = 0.95
        else:
            run["visible_frames"] = 45
            run["localization"] = localization_recipe()
        write_json(data / video["id"] / "runs" / f"{job_id}.json", run)
        store.put_job(
            {
                "id": job_id,
                "video_id": video["id"],
                "kind": stage,
                "status": "completed",
                "progress": 1,
                "summary": {k: v for k, v in run.items() if k != "frames"},
            }
        )


if __name__ == "__main__":
    parent = ROOT / ".cache/contact-ui-test-data"
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(mkdtemp(prefix="run-", dir=parent))
    data = root / "processed"
    prepare(root, data)
    print(f"Isolated contact QA: {root}", flush=True)
    uvicorn.run(create_app(root, data), host="127.0.0.1", port=8004)
