"""Generated native clocks and explicit review; no scientific source inputs."""

import copy
import math

import pytest
from badminton.camera_evaluation import evaluate_camera


def generated(*, predicted=(5, 12), reviewed=(5, 12), gaps=(), count=20):
    video = {"id": "generated-only", "sha256": "a" * 64, "frame_count": count}
    times = [
        7 + frame * 0.04 + sum(frame >= gap for gap in gaps) for frame in range(count)
    ]
    cuts = sorted(set(predicted) | set(gaps))
    run = {
        "schema_version": 1,
        "stage": "segments",
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "start_frame": 0,
        "end_frame": count,
        "timestamp_gap_threshold_s": 0.1,
        "cut_frames": cuts,
        "boundaries": [
            {
                "frame": frame,
                "time_s": times[frame],
                "reason": "timestamp_discontinuity" if frame in gaps else "visual_cut",
                "reviewed": False,
            }
            for frame in cuts
        ],
    }
    reference = {
        "schema_version": 1,
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "windows": [
            {
                "id": "window",
                "start_frame": 0,
                "end_frame": count,
                "cuts_complete": True,
                "cuts": [
                    {"id": f"reference:{frame}", "frame": frame, "time_s": times[frame]}
                    for frame in reviewed
                ],
            }
        ],
    }
    return video, times, run, reference


def score(inputs, **kwargs):
    original = copy.deepcopy(inputs)
    result = evaluate_camera(*inputs, **kwargs)
    assert original == inputs
    counts = result["summary"]["transition_counts"]
    assert sum(counts.values()) == result["summary"]["run_transitions"]
    for label, key in (
        ("reference", "reference_cuts"),
        ("prediction", "raw_visual_cuts"),
    ):
        eligible = (
            "eligible_reference_cuts"
            if label == "reference"
            else "eligible_visual_cuts"
        )
        assert result["summary"][key] == result["summary"][eligible] + len(
            result["excluded"][label]
        )
    return result


def test_exact_cuts_preserve_inputs_and_native_denominators():
    result = score(generated(), tolerance_s=0)
    assert result["summary"]["metrics"] == {
        "tp": 2,
        "fp": 0,
        "fn": 0,
        "precision": 1,
        "recall": 1,
        "f1": 1,
    }
    assert result["summary"]["transition_counts"]["eligible"] == 19
    assert result["eligible_transition_ranges"] == [[1, 20]]
    assert result["score"]["mean_absolute_error_s"] == 0
    assert result["limitations"]


@pytest.mark.parametrize(
    "predicted,reviewed,expected",
    [
        ((5,), (5, 12), (1, 0, 1)),
        ((5, 12), (5,), (1, 1, 0)),
        ((5,), (12,), (0, 1, 1)),
        ((), (5,), (0, 0, 1)),
        ((5,), (), (0, 1, 0)),
    ],
)
def test_missed_extra_displaced_and_missing_outputs(predicted, reviewed, expected):
    result = score(generated(predicted=predicted, reviewed=reviewed), tolerance_s=0)
    assert (
        tuple(result["summary"]["metrics"][k] for k in ("tp", "fp", "fn")) == expected
    )


def test_negative_only_review_does_not_invent_an_accuracy_ratio():
    result = score(generated(predicted=(), reviewed=()))
    assert result["summary"]["status"] == "ok"
    assert result["summary"]["metrics"]["f1"] is None
    assert result["summary"]["transition_counts"]["eligible"] == 19


def test_maximum_cardinality_precedes_nearest_greedy_choice():
    result = score(generated(predicted=(3, 4), reviewed=(4, 5)), tolerance_s=0.041)
    assert result["summary"]["metrics"]["tp"] == 2
    assert [m["candidate_frame"] for m in result["score"]["matches"]] == [3, 4]


def test_matching_minimizes_total_source_time_error():
    result = score(generated(predicted=(3, 4, 6), reviewed=(4, 5)), tolerance_s=0.1)
    assert result["summary"]["metrics"]["tp"] == 2
    assert result["score"]["mean_absolute_error_s"] == pytest.approx(0.02)


def test_timestamp_gaps_are_separate_and_cannot_bridge_matching():
    result = score(
        generated(predicted=(6,), reviewed=(7, 8), gaps=(7,)), tolerance_s=10
    )
    assert result["summary"]["timestamp_gap_boundaries"] == 1
    assert result["summary"]["metrics"]["tp"] == 0
    assert result["excluded"]["reference"] == [
        {"id": "reference:7", "frame": 7, "reason": "timestamp_gap"}
    ]
    assert result["eligible_transition_ranges"] == [[1, 7], [8, 20]]
    assert result["summary"]["transition_counts"]["timestamp_gap"] == 1


def test_variable_native_clock_with_nonzero_origin():
    inputs = generated(predicted=(5,), reviewed=(5,))
    inputs[1][:] = [11 + frame * frame / 1000 for frame in range(20)]
    inputs[2]["boundaries"][0]["time_s"] = inputs[1][5]
    inputs[3]["windows"][0]["cuts"][0]["time_s"] = inputs[1][5]
    assert score(inputs, tolerance_s=0)["summary"]["metrics"]["tp"] == 1


@pytest.mark.parametrize("complete", [False, None])
def test_missing_or_incomplete_review_does_not_count_as_negative(complete):
    inputs = generated()
    if complete is None:
        inputs[3]["windows"] = []
    else:
        inputs[3]["windows"][0]["cuts_complete"] = complete
    result = score(inputs)
    assert result["summary"]["status"] == "needs_complete_camera_review"
    assert result["summary"]["metrics"] is None
    assert result["score"] is None
    assert result["summary"]["raw_visual_cuts"] == 2
    assert result["summary"]["excluded_visual_cuts"] == 2


def test_adjacent_windows_do_not_supply_their_shared_transition_or_cross_matches():
    inputs = generated(predicted=(9,), reviewed=(10, 11))
    first = inputs[3]["windows"][0]
    first.update(end_frame=10, cuts=[])
    second = copy.deepcopy(first)
    second.update(
        id="second",
        start_frame=10,
        end_frame=20,
        cuts=[
            {"id": "edge", "frame": 10, "time_s": inputs[1][10]},
            {"id": "next", "frame": 11, "time_s": inputs[1][11]},
        ],
    )
    inputs[3]["windows"].append(second)
    result = score(inputs, tolerance_s=10)
    assert result["summary"]["metrics"]["tp"] == 0
    assert result["summary"]["transition_counts"]["review_window_edge"] == 1
    assert result["excluded"]["reference"][0]["reason"] == "review_window_edge"


def test_partial_run_excludes_edges_and_retains_outside_references():
    inputs = generated(predicted=(5, 12), reviewed=(3, 5, 12, 18))
    inputs[2].update(start_frame=5, end_frame=15)
    result = score(inputs, tolerance_s=0)
    assert result["summary"]["run_transitions"] == 9
    assert result["summary"]["metrics"]["tp"] == 1
    assert result["summary"]["excluded_reference_cuts"] == 3
    assert result["summary"]["excluded_visual_cuts"] == 1


def test_one_frame_source_has_no_transition_coverage():
    result = score(generated(predicted=(), reviewed=(), count=1))
    assert result["summary"]["run_transitions"] == 0
    assert result["summary"]["status"] == "needs_complete_camera_review"


@pytest.mark.parametrize("owner", [0, 2, 3])
@pytest.mark.parametrize("key,value", [("id", "other"), ("sha256", "b" * 64)])
def test_conflicting_source_metadata_rejected(owner, key, value):
    inputs = generated()
    if owner:
        key = "video_id" if key == "id" else "video_sha256"
    inputs[owner][key] = value
    with pytest.raises(ValueError, match="identity"):
        evaluate_camera(*inputs)


@pytest.mark.parametrize(
    "value",
    [None, [], [0], [True] * 20, [-1] * 20, [math.nan] * 20, [math.inf] * 20, [1] * 20],
)
def test_invalid_native_clocks_rejected_before_coverage(value):
    inputs = list(generated())
    inputs[1] = value
    inputs[3]["windows"] = []
    with pytest.raises(ValueError):
        evaluate_camera(*inputs)


@pytest.mark.parametrize("owner", ["prediction", "reference"])
@pytest.mark.parametrize(
    "key,value",
    [
        ("frame", True),
        ("frame", 5.0),
        ("frame", -1),
        ("frame", 20),
        ("time_s", None),
        ("time_s", True),
        ("time_s", math.nan),
        ("time_s", -1),
        ("time_s", 7.01),
    ],
)
def test_malformed_rows_fail_even_when_review_incomplete(owner, key, value):
    inputs = generated()
    inputs[3]["windows"][0]["cuts_complete"] = False
    rows = (
        inputs[2]["boundaries"]
        if owner == "prediction"
        else inputs[3]["windows"][0]["cuts"]
    )
    rows[0][key] = value
    with pytest.raises(ValueError):
        evaluate_camera(*inputs)


@pytest.mark.parametrize(
    "field",
    [
        "raw_cut_frames",
        "applied_camera_corrections",
        "camera_annotation_revision",
        "scene_annotation_revision",
        "preceding_reviewed_cut_frame",
    ],
)
def test_corrected_camera_overlay_cannot_be_scored_as_raw(field):
    inputs = generated()
    inputs[2][field] = []
    with pytest.raises(ValueError, match="overlays"):
        evaluate_camera(*inputs)


@pytest.mark.parametrize("value", [True, None, 0, "false"])
def test_boundaries_need_explicit_unreviewed_boolean(value):
    inputs = generated()
    inputs[2]["boundaries"][0]["reviewed"] = value
    with pytest.raises(ValueError, match="unreviewed"):
        evaluate_camera(*inputs)


@pytest.mark.parametrize(
    "mode", ["missing", "extra", "wrong_reason", "duplicate", "order"]
)
def test_boundary_inventory_must_match_raw_clock_and_cut_list(mode):
    inputs = generated(gaps=(7,))
    run = inputs[2]
    if mode == "missing":
        run["boundaries"].pop(1)
    elif mode == "extra":
        run["cut_frames"].append(18)
    elif mode == "wrong_reason":
        run["boundaries"][1]["reason"] = "visual_cut"
    elif mode == "duplicate":
        run["cut_frames"].insert(1, 5)
    else:
        run["boundaries"].reverse()
    with pytest.raises(ValueError):
        evaluate_camera(*inputs)


@pytest.mark.parametrize("value", [True, False, -1, math.inf, math.nan, None])
def test_bad_gap_thresholds_fail(value):
    inputs = generated()
    inputs[2]["timestamp_gap_threshold_s"] = value
    with pytest.raises(ValueError):
        evaluate_camera(*inputs)


@pytest.mark.parametrize("value", [True, -1, math.inf, math.nan, None])
def test_bad_matching_tolerances_fail(value):
    with pytest.raises(ValueError):
        evaluate_camera(*generated(), tolerance_s=value)


@pytest.mark.parametrize(
    "change",
    [
        "overlap",
        "duplicate_id",
        "duplicate_cut",
        "unknown_field",
        "complete_type",
        "range_type",
        "uncertainty",
    ],
)
def test_review_schema_rejects_ambiguity_even_without_eligible_coverage(change):
    inputs = generated()
    window = inputs[3]["windows"][0]
    if change == "overlap":
        second = copy.deepcopy(window)
        second["id"] = "second"
        inputs[3]["windows"].append(second)
    elif change == "duplicate_id":
        window["cuts"][0]["id"] = window["id"]
    elif change == "duplicate_cut":
        window["cuts"][1]["frame"] = 5
        window["cuts"][1]["time_s"] = inputs[1][5]
    elif change == "unknown_field":
        window["cut_complete"] = True
    elif change == "complete_type":
        window["cuts_complete"] = 1
    elif change == "range_type":
        window["start_frame"] = False
    else:
        window["cuts"][0]["start_frame"] = 4
    with pytest.raises(ValueError):
        evaluate_camera(*inputs)


def test_quadratic_matching_is_bounded(monkeypatch):
    monkeypatch.setattr("badminton.camera_evaluation.MAX_MATCH_CELLS", 3)
    with pytest.raises(ValueError, match="cell limit"):
        evaluate_camera(*generated())
