"""Optional real association-engine regression; no model, download or GPU."""

from types import SimpleNamespace

import numpy as np
import pytest
from badminton.tracking import BYTE_TRACK_CONFIG, TRACKER_CONFIG, TRACKING_RECIPE


@pytest.mark.parametrize("backend", ["bytetrack", "botsort"])
def test_low_score_second_stage_keeps_moving_identity_without_starting_weak_tracks(
    tmp_path, monkeypatch, backend
):
    # Review-only CI does not install the tracking extra. Check optional modules
    # before Ultralytics can try to install an absent association dependency.
    pytest.importorskip("torch")
    pytest.importorskip("lap")
    monkeypatch.setenv("YOLO_CONFIG_DIR", str(tmp_path / "ultralytics"))
    pytest.importorskip("ultralytics")
    from ultralytics.engine.results import Boxes
    from ultralytics.trackers.bot_sort import BOTSORT
    from ultralytics.trackers.byte_tracker import BYTETracker

    def replay(detector_gate):
        tracker = (
            BYTETracker(SimpleNamespace(**BYTE_TRACK_CONFIG))
            if backend == "bytetrack"
            else BOTSORT(SimpleNamespace(**TRACKER_CONFIG))
        )
        records = []
        for frame in range(15):
            # Acceleration and ten weak frames defeat extrapolation from only
            # the first three strong observations. The weak boxes are observed
            # input, not an interpolated or fabricated detection.
            x = 20 + 2 * frame + 0.6 * frame**2
            confidence = 0.9 if frame < 3 or frame >= 13 else 0.2
            detections = [
                [x, 20, x + 60, 140, confidence, 0],
                [400, 20, 460, 140, 0.9, 0],
                [530, 20, 590, 140, 0.2, 0],
            ]
            detections = [p for p in detections if p[4] >= detector_gate]
            result = tracker.update(
                Boxes(np.asarray(detections, dtype=np.float32), (200, 640)),
                np.zeros((200, 640, 3), dtype=np.uint8),
            )
            records.append(result)
        return records

    previous = replay(0.25)
    recovered = replay(TRACKING_RECIPE["detector_confidence"])

    def moving_ids(record):
        return [int(row[4]) for row in record if row[0] < 350]

    assert moving_ids(previous[0]) == [1]
    assert moving_ids(previous[-1]) != [1]
    assert all(moving_ids(row) == [1] for row in recovered)
    assert all([int(p[4]) for p in row if 350 < p[0] < 500] == [2] for row in recovered)
    assert all(not any(p[0] > 500 for p in row) for row in recovered)
    # The app's separate publication gate omits the weak association frames.
    assert all(
        not any(
            p[0] < 350 and p[5] >= TRACKING_RECIPE["observation_confidence"]
            for p in row
        )
        for row in recovered[3:13]
    )


def test_dual_association_preserves_pose_indices_and_separates_ids_after_reset(
    tmp_path, monkeypatch
):
    torch = pytest.importorskip("torch")
    pytest.importorskip("lap")
    monkeypatch.setenv("YOLO_CONFIG_DIR", str(tmp_path / "ultralytics"))
    pytest.importorskip("ultralytics")
    from badminton.tracking import associate_observations, association_trackers
    from ultralytics.engine.results import Boxes

    trackers = association_trackers()
    image = np.zeros((200, 640, 3), dtype=np.uint8)
    rows = torch.tensor(
        [
            [530, 20, 590, 140, 0.2, 0],
            [20, 20, 80, 140, 0.9, 0],
            [400, 20, 460, 140, 0.9, 0],
        ]
    )
    result = SimpleNamespace(
        boxes=Boxes(rows, image.shape[:2]),
        keypoints=SimpleNamespace(
            data=torch.tensor([[[5, 5, 0.1]], [[40, 30, 0.9]], [[430, 30, 0.9]]])
        ),
    )
    all_ids, last_ids = set(), None
    for _ in range(4):
        baseline = associate_observations(result, trackers[0], image, 0.25, 0)
        auxiliary = associate_observations(result, trackers[1], image, 0.1, 0, False)
        assert [p["keypoints"][0][:2] for p in baseline] == [[40, 30], [430, 30]]
        assert all(p["keypoints"] == [] for p in auxiliary)
        assert len(baseline) == len(auxiliary) == 2
        current = [p["track_id"] for p in baseline + auxiliary]
        # These are separate association namespaces. Numeric overlap between
        # the baseline and corroborating engine is valid; within either one it is not.
        assert len({p["track_id"] for p in baseline}) == 2
        assert len({p["track_id"] for p in auxiliary}) == 2
        assert last_ids is None or current == last_ids
        all_ids.update(current)
        last_ids = current
    offset = max(all_ids)
    for tracker in trackers:
        tracker.reset()
    for tracker, gate in zip(trackers, (0.25, 0.1)):
        later = associate_observations(result, tracker, image, gate, offset)
        assert all(p["track_id"] not in all_ids for p in later)
