import json
import sys
from types import SimpleNamespace

import av
import numpy as np
import pytest
from badminton.schemas import Annotations
from badminton.shuttle import HEIGHT, WIDTH, infer_camera_segment
from badminton.video import write_json


@pytest.mark.parametrize("sizes", [(1, 1), (5, 3), (8, 8), (11, 13)])
def test_temporal_windows_and_short_clip_padding_never_cross_camera_cuts(sizes):
    calls = []
    rows = []
    index = 0
    for value, size in zip((30, 210), sizes):
        background = np.full((HEIGHT, WIDTH, 3), value, np.uint8)
        frames = [
            (
                i,
                i * 0.04,
                av.VideoFrame.from_ndarray(
                    np.full((32, 48, 3), value, np.uint8), "rgb24"
                ),
            )
            for i in range(index, index + size)
        ]

        def predict(images):
            calls.append(images)
            assert len(images) == 9
            assert all(np.all(image == value) for image in images)
            return np.zeros((8, 4, 4), np.float32)

        rows.extend(infer_camera_segment(frames, background, 8, predict, 48, 32))
        index += size
    assert [row["frame"] for row in rows] == list(range(sum(sizes)))
    assert [row["time_s"] for row in rows] == [i * 0.04 for i in range(sum(sizes))]
    assert all(row["shuttle"]["visible"] is False for row in rows)
    assert calls


def test_tracker_reset_allocates_disjoint_ids_and_expires_old_camera_calibration(
    tmp_path, monkeypatch
):
    from badminton import tracking

    class Scalar:
        def __init__(self, value):
            self.value = value

        def item(self):
            return self.value

    class Array:
        def __init__(self, value):
            self.value = value

        def cpu(self):
            return self

        def tolist(self):
            return self.value

    resets = []

    class Model:
        def __init__(self, _path):
            self.predictor = SimpleNamespace(
                trackers=[SimpleNamespace(reset=lambda: resets.append(True))]
            )

        def track(self, *_args, **_kwargs):
            box = SimpleNamespace(
                id=Scalar(1), xyxy=[Array([30, 20, 50, 50])], conf=Scalar(0.9)
            )
            return [SimpleNamespace(boxes=[box], keypoints=None)]

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)),
    )
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=Model))
    monkeypatch.setitem(sys.modules, "torchvision", SimpleNamespace())
    monkeypatch.setattr(tracking, "WEIGHTS", tmp_path)
    (tmp_path / "yolo11n-pose.pt").write_bytes(b"stub")
    monkeypatch.setattr(
        tracking,
        "player_checkpoint",
        lambda variant: (
            tmp_path / "yolo11n-pose.pt",
            {"name": "yolo11n-pose.pt", "sha256": "fixture", "source": "fixture"},
        ),
    )
    data = tmp_path / "data"
    data.mkdir()
    write_json(data / "test" / "timestamps.json", [i * 0.04 for i in range(12)])
    monkeypatch.setattr(
        tracking,
        "scan_boundaries",
        lambda *_: {
            "cut_frames": [5],
            "method": "fixture",
            "camera_ranges": [
                {"start_frame": 0, "end_frame": 5},
                {"start_frame": 5, "end_frame": 12},
            ],
        },
    )
    monkeypatch.setattr(
        tracking,
        "iter_frames",
        lambda *_: iter(
            (
                i,
                i * 0.04,
                av.VideoFrame.from_ndarray(np.zeros((64, 96, 3), np.uint8), "bgr24"),
            )
            for i in range(12)
        ),
    )
    annotations = Annotations.model_validate(
        {
            "mode": "singles",
            "players": [
                {"id": "A", "name": "A", "team": "T1"},
                {"id": "B", "name": "B", "team": "T2"},
            ],
            "calibrations": [
                {
                    "start_frame": 0,
                    "end_frame": 12,
                    "corners": [
                        {"x": 0, "y": 0},
                        {"x": 1, "y": 0},
                        {"x": 1, "y": 1},
                        {"x": 0, "y": 1},
                    ],
                }
            ],
        }
    )
    video = {
        "id": "test",
        "sha256": "fixture",
        "width": 96,
        "height": 64,
        "mode": "singles",
        "duration_s": 0.48,
    }
    output = data / "players.json"
    tracking.track_players(
        video,
        tmp_path,
        data,
        annotations,
        0,
        12,
        2,
        lambda _: None,
        output,
        auto_calibrate=False,
    )
    result = json.loads(output.read_text())
    assert len(resets) == 1
    assert [row["players"][0]["track_id"] for row in result["frames"]] == [
        1,
        1,
        1,
        2,
        2,
        2,
    ]
    assert [row["calibration_valid"] for row in result["frames"]] == [
        True,
        True,
        True,
        False,
        False,
        False,
    ]
    assert result["frames"][3]["camera_segment_start_frame"] == 5
    assert result["calibrated_frames"] == 3
    assert result["tracker_reset_at_cuts"] is True

    # A cut exactly at the requested start also expires a calibration that
    # began in a preceding view, even though there is no in-run tracker reset.
    monkeypatch.setattr(
        tracking,
        "scan_boundaries",
        lambda *_: {"cut_frames": [4], "method": "fixture", "camera_ranges": []},
    )
    monkeypatch.setattr(
        tracking,
        "iter_frames",
        lambda *_: iter(
            (
                i,
                i * 0.04,
                av.VideoFrame.from_ndarray(np.zeros((64, 96, 3), np.uint8), "bgr24"),
            )
            for i in range(4, 12)
        ),
    )
    tracking.track_players(
        video,
        tmp_path,
        data,
        annotations,
        4,
        12,
        1,
        lambda _: None,
        output,
        auto_calibrate=False,
    )
    at_start = json.loads(output.read_text())
    assert at_start["calibrated_frames"] == 0
    # A newly confirmed calibration for that camera is eligible again.
    annotations.calibrations[0].start_frame = 4
    tracking.track_players(
        video,
        tmp_path,
        data,
        annotations,
        4,
        12,
        1,
        lambda _: None,
        output,
        auto_calibrate=False,
    )
    assert json.loads(output.read_text())["calibrated_frames"] == 8
