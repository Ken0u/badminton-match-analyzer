"""Generated shuttle artifacts must retain their native frame/time identity."""

from copy import deepcopy

import pytest
from badminton.evaluation import evaluate_shuttle


def generated():
    times = [0.11, 0.13, 0.18, 0.21, 0.29, 0.31, 0.36, 0.42, 0.9, 0.95]
    video = {
        "id": "generated",
        "sha256": "a" * 64,
        "frame_count": len(times),
        "width": 100,
        "height": 100,
    }
    labels = {
        "revision": 1,
        "shuttle_points": [
            {"frame": f, "visible": f not in (4, 5, 7), "x": 0.5, "y": 0.5}
            for f in range(8)
        ],
    }
    observations = [
        (1, True, 50, 50),
        (2, True, 90, 90),
        (3, False, None, None),
        (4, True, 50, 50),
        (5, False, None, None),
        (8, True, 50, 50),  # Valid, unlabelled output beyond a native clock gap.
    ]
    run = {
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "stage": "shuttle",
        "start_frame": 1,
        "end_frame": 9,
        "frames": [
            {
                "frame": frame,
                "time_s": times[frame],
                "shuttle": {"visible": visible, "x": x, "y": y},
            }
            for frame, visible, x, y in observations
        ],
    }
    return video, labels, run, times


def test_native_clock_keeps_localization_visibility_and_missing_denominators():
    video, labels, run, times = generated()
    before = deepcopy((video, labels, run, times))
    legacy = evaluate_shuttle(video, labels, run, 0.005)
    checked = evaluate_shuttle(
        video, labels, run, 0.005, native_timestamps=tuple(times)
    )
    assert legacy.pop("prediction_clock_status") == "unavailable"
    assert checked.pop("prediction_clock_status") == "validated"
    assert checked == legacy
    assert checked["metrics"] == {
        "tp": 1,
        "fp": 2,
        "fn": 3,
        "precision": 1 / 3,
        "recall": 1 / 4,
        "f1": 2 / 7,
        "true_negatives": 1,
        "wrong_localizations": 1,
        "correct_frame_fraction": 2 / 7,
    }
    assert checked["coverage"]["labeled_frames"] == 7
    assert checked["coverage"]["excluded_labeled_frames"] == 1
    assert checked["coverage"]["missing_visible_output_frames"] == 1
    assert checked["coverage"]["missing_invisible_output_frames"] == 1
    assert (video, labels, run, times) == before


@pytest.mark.parametrize(
    "clock", [None, [], [0] * 10, list(range(9)), "0123456789", {}, 5, iter(range(10))]
)
def test_invalid_native_clock_is_not_hidden_by_empty_inputs(clock):
    video, labels, run, _ = generated()
    labels["shuttle_points"] = []
    run["frames"] = []
    # None deliberately retains the documented legacy API.
    if clock is None:
        assert (
            evaluate_shuttle(video, labels, run)["prediction_clock_status"]
            == "unavailable"
        )
    else:
        with pytest.raises(ValueError, match="Native source timestamps"):
            evaluate_shuttle(video, labels, run, native_timestamps=clock)


@pytest.mark.parametrize(
    "bad", [True, False, None, "0.18", float("nan"), float("inf"), -1, 1j]
)
def test_invalid_native_time_is_rejected(bad):
    video, labels, run, times = generated()
    times[2] = bad
    with pytest.raises(ValueError, match="Native source timestamp"):
        evaluate_shuttle(video, labels, run, native_timestamps=times)


@pytest.mark.parametrize("count", [None, True, 0, -1, 10.0])
def test_native_clock_requires_a_strict_positive_frame_count(count):
    video, labels, run, times = generated()
    video["frame_count"] = count
    with pytest.raises(ValueError, match="Source frame count"):
        evaluate_shuttle(video, labels, run, native_timestamps=times)


@pytest.mark.parametrize("bad", [None, True, False, "1", 1.0, -1, 0, 9, 10])
def test_all_rows_need_strict_in_run_native_frames(bad):
    video, labels, run, times = generated()
    run["frames"][0]["frame"] = bad
    before = deepcopy(run)
    with pytest.raises(ValueError, match=r"Shuttle.*frame"):
        evaluate_shuttle(video, labels, run, native_timestamps=times)
    assert run == before


@pytest.mark.parametrize(
    "bad", [None, True, "0.13", float("nan"), float("inf"), -1, 1j, 0.8]
)
@pytest.mark.parametrize("labelled", [True, False])
def test_every_row_time_is_validated_before_label_filtering(bad, labelled):
    video, labels, run, times = generated()
    row = run["frames"][0 if labelled else -1]
    row["time_s"] = bad
    with pytest.raises(ValueError, match=r"Shuttle.*time_s"):
        evaluate_shuttle(video, labels, run, native_timestamps=times)


@pytest.mark.parametrize("missing", ["frame", "time_s"])
def test_missing_row_identity_is_an_actionable_error(missing):
    video, labels, run, times = generated()
    del run["frames"][0][missing]
    with pytest.raises(ValueError, match="Shuttle"):
        evaluate_shuttle(video, labels, run, native_timestamps=times)


@pytest.mark.parametrize("rows", [None, {}, "invalid", [None], [1], [[]]])
def test_malformed_row_containers_are_not_scored(rows):
    video, labels, run, times = generated()
    run["frames"] = rows
    with pytest.raises(ValueError, match="Shuttle"):
        evaluate_shuttle(video, labels, run, native_timestamps=times)


@pytest.mark.parametrize("error,accepted", [(0.000019, True), (0.000021, False)])
def test_fixed_clock_tolerance_never_rewrites_row_times(error, accepted):
    video, labels, run, times = generated()
    run["frames"][0]["time_s"] += error
    before = deepcopy((labels, run, times))
    if accepted:
        result = evaluate_shuttle(video, labels, run, native_timestamps=times)
        assert result["metrics"]["tp"] == 1
    else:
        with pytest.raises(ValueError, match="does not match native source frame"):
            evaluate_shuttle(video, labels, run, native_timestamps=times)
    assert (labels, run, times) == before


def test_no_labels_and_missing_predictions_keep_their_distinct_statuses():
    video, labels, run, times = generated()
    labels["shuttle_points"] = []
    result = evaluate_shuttle(video, labels, run, native_timestamps=times)
    assert result["status"] == "needs_shuttle_labels"
    assert result["metrics"] is None
    video, labels, run, times = generated()
    run["frames"] = []
    result = evaluate_shuttle(video, labels, run, native_timestamps=times)
    assert result["status"] == "scored"
    assert result["coverage"]["missing_output_frames"] == 7
    assert result["metrics"]["true_negatives"] == 0


def test_validated_clock_preserves_hash_and_duplicate_guards():
    video, labels, run, times = generated()
    run["frames"].append(deepcopy(run["frames"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_shuttle(video, labels, run, native_timestamps=times)
    run["video_sha256"] = "b" * 64
    del run["frames"]
    with pytest.raises(ValueError, match="source hash"):
        evaluate_shuttle(video, labels, run, native_timestamps=times)
