"""Generated 130-second media and synthetic perception for processing UI QA.

No match footage, downloaded checkpoints or accuracy claims are used here.
"""

import time
from fractions import Fraction
from pathlib import Path
from tempfile import mkdtemp

import av
import cv2
import numpy as np
import uvicorn
from badminton import pipeline
from badminton.api import create_app
from badminton.config import ROOT
from badminton.ingest import inspect_video
from badminton.rallies import context_signature
from badminton.scene_review import corrected_boundaries
from badminton.segments import slice_camera_scan
from badminton.storage import Store
from badminton.video import timestamps_for, write_json


def prepare(root, data):
    source = root / "pipeline-qa.mp4"
    with av.open(str(source), "w") as container:
        stream = container.add_stream("libx264", rate=10)
        stream.width, stream.height, stream.pix_fmt = 640, 360, "yuv420p"
        for i in range(1300):
            picture = np.full((360, 640, 3), (30, 65, 45), np.uint8)
            cv2.putText(
                picture,
                "SOFTWARE QA",
                (100, 120),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (240, 240, 240),
                2,
            )
            cv2.putText(
                picture,
                f"Source frame {i}",
                (100, 220),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (240, 240, 240),
                2,
            )
            frame = av.VideoFrame.from_ndarray(picture, "bgr24")
            frame.pts, frame.time_base = i, Fraction(1, 10)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    store = Store(data)
    video = inspect_video(source, "singles", store, root)
    times = timestamps_for(data, video["id"])

    def players(v, _root, _data, doc, first, last, stride, callback, output, **kwargs):
        for i in range(30):
            callback(i / 30)
            time.sleep(0.1)
        boundaries = corrected_boundaries(
            slice_camera_scan(v, kwargs["camera_scan"], first, last), doc, first, last
        )
        result = {
            "stage": "players",
            "video_id": v["id"],
            "video_sha256": v["sha256"],
            "start_frame": first,
            "end_frame": last,
            "stride": stride,
            "model": "synthetic_qa",
            "device": "qa_fixture",
            "processed_frames": last - first,
            "inference_fps": 100,
            "calibrated_frames": 0,
            "calibrated": False,
            "calibration_signature": context_signature(doc, first, last)["court"],
            "frames": [
                {
                    "frame": i,
                    "time_s": times[i],
                    "players": [],
                    "calibration_valid": False,
                }
                for i in range(first, last)
            ],
        }
        result.update(
            {
                k: boundaries[k]
                for k in (
                    "cut_frames",
                    "raw_cut_frames",
                    "applied_camera_corrections",
                    "preceding_reviewed_cut_frame",
                    "known_preceding_cut_frames",
                    "known_preceding_timestamp_gaps",
                )
            }
        )
        write_json(output, result)

    def shuttle(v, _root, _data, first, last, callback, output, doc, **kwargs):
        boundaries = corrected_boundaries(
            slice_camera_scan(v, kwargs["camera_scan"], first, last), doc, first, last
        )
        result = {
            "stage": "shuttle",
            "video_id": v["id"],
            "video_sha256": v["sha256"],
            "start_frame": first,
            "end_frame": last,
            "stride": 1,
            "visible_frames": 0,
            "processed_frames": last - first,
            "inference_fps": 100,
            "frames": [
                {
                    "frame": i,
                    "time_s": times[i],
                    "shuttle": {
                        "visible": False,
                        "x": None,
                        "y": None,
                        "repaired": False,
                    },
                }
                for i in range(first, last)
            ],
        }
        result.update(
            {
                k: boundaries[k]
                for k in (
                    "cut_frames",
                    "raw_cut_frames",
                    "applied_camera_corrections",
                    "preceding_reviewed_cut_frame",
                    "known_preceding_cut_frames",
                    "known_preceding_timestamp_gaps",
                )
            }
        )
        write_json(output, result)
        callback(1)

    def contacts(flight, _players, _video):
        return [
            {
                "id": f"qa-contact-{f}",
                "frame": f,
                "time_s": times[f],
                "timing": "uncertain_interval",
                "start_frame": f - 1,
                "end_frame": f + 1,
                "context_start_frame": f - 3,
                "context_end_frame": f + 4,
                "track_id": None,
                "score": 0.6,
                "reason": "Generated QA cue",
                "evidence_source": "observed_trajectory",
            }
            for f in (600, 1000)
            if flight["start_frame"] <= f < flight["end_frame"]
        ]

    def recognition(
        v, _times, doc, poses, flight, targets, player_id, callback, output, **kwargs
    ):
        write_json(
            output,
            {
                "stage": "recognition",
                "video_id": v["id"],
                "video_sha256": v["sha256"],
                "start_frame": poses["start_frame"],
                "end_frame": poses["end_frame"],
                "player_run_id": player_id,
                "shuttle_run_id": flight["run_id"],
                "contacts_run_id": kwargs["contacts_run_id"],
                "annotation_revision": doc.revision,
                "candidate_count": len(targets),
                "predicted_count": 0,
                "candidates": [
                    {
                        **t,
                        "kind": "shot",
                        "time_s": times[t["frame"]],
                        "status": "abstained",
                        "family": "unknown",
                        "side": "unknown",
                        "reason": "Synthetic QA; no trained head used",
                    }
                    for t in targets
                ],
            },
        )
        callback(1)

    pipeline.track_players, pipeline.track_shuttle = players, shuttle
    pipeline.propose_contacts, pipeline.recognize_strokes = contacts, recognition
    return store, video


if __name__ == "__main__":
    parent = ROOT / ".cache/pipeline-ui-test-data"
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(mkdtemp(prefix="run-", dir=parent))
    data = root / "processed"
    prepare(root, data)
    print(f"Isolated full-source QA: {root}", flush=True)
    uvicorn.run(create_app(root, data), host="127.0.0.1", port=8005)
