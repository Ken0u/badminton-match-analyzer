"""Disposable controls for research-only observed-component selection."""

import copy
import json
import math

import numpy as np
import pytest
from badminton import shuttle_selection as selection


def candidate(identity=1, x=100.0, y=100.0, area=4, confidence=0.9):
    return {
        "id": identity,
        "x": x,
        "y": y,
        "confidence": confidence,
        "area_heatmap_pixels": area,
        "box_heatmap": [90, 90, 4, 4],
    }


def row(frame, candidates=None, timestamp=None):
    candidates = [candidate()] if candidates is None else candidates
    first = candidates[0] if candidates else None
    return {
        "frame": frame,
        "time_s": frame / 30 if timestamp is None else timestamp,
        "shuttle": {
            "visible": bool(first),
            "x": first["x"] if first else None,
            "y": first["y"] if first else None,
            "confidence": first["confidence"] if first else 0.1,
            "component_candidates": candidates,
            "selected_component_id": first["id"] if first else None,
            "repaired": False,
        },
    }


def scorer(weights=None, intercept=0):
    return {
        "schema_version": 1,
        "method": selection.METHOD,
        "feature_names": list(selection.FEATURE_NAMES),
        "available": True,
        "reason": None,
        "mean": [0.0] * 14,
        "scale": [1.0] * 14,
        "weights": [0.0] * 14 if weights is None else weights,
        "intercept": intercept,
    }


def group(split="train", *, index=0):
    rows = [
        row(
            0,
            [candidate(1, x=100, confidence=0.95), candidate(2, x=200, confidence=0.1)],
        ),
        row(
            1,
            [candidate(1, x=102, confidence=0.9), candidate(2, x=202, confidence=0.2)],
        ),
        row(2, [candidate(1, x=104, confidence=0.15)]),
    ]
    labels = [
        {"frame": 0, "visible": True, "x": 100, "y": 100},
        {"frame": 1, "visible": True, "x": 102, "y": 100},
        {"frame": 2, "visible": False, "x": None, "y": None},
    ]
    return {"split": split, "index": index, "rows": rows, "labels": labels}


def test_exact_features_include_two_native_neighbors_and_preserve_inputs():
    rows = [
        row(0, [candidate(x=100, area=4)], 0),
        row(1, [candidate(x=102, area=8)], 0.05),
        row(2, [candidate(x=105, area=12)], 0.10),
    ]
    before = copy.deepcopy(rows)
    result = selection.feature_rows(rows)
    diagonal = math.hypot(512, 288)
    expected = [
        0.9,
        math.log1p(8),
        4 / 512,
        4 / 288,
        0,
        0.5,
        math.log(2),
        2 / (diagonal * 0.05),
        3 / (diagonal * 0.05),
        1 / (diagonal * 0.05),
        1,
        1,
        math.log(9 / 5),
        math.log(9 / 13),
    ]
    np.testing.assert_allclose(result["features"][1], expected)
    assert result["support_frames"] == [[0, 1], [0, 1, 2], [1, 2]]
    assert result["row_indices"] == [0, 1, 2]
    assert rows == before


def test_nearest_neighbor_tie_uses_identity_not_list_order():
    rows = [
        row(0, [candidate(9, x=98, area=4), candidate(2, x=102, area=12)]),
        row(1, [candidate(x=100, area=8)]),
    ]
    result = selection.feature_rows(rows)
    current = result["features"][-1]
    assert current[12] == pytest.approx(math.log(9 / 13))
    rows[0]["shuttle"]["component_candidates"].reverse()
    np.testing.assert_array_equal(selection.feature_rows(rows)["features"][-1], current)


@pytest.mark.parametrize(
    "kind", ["frame_gap", "clock_gap", "camera", "segments", "exclusion", "empty"]
)
def test_temporal_features_do_not_cross_unsupported_neighbors(kind):
    rows = [
        row(0, [candidate(x=100)]),
        row(1, [candidate(x=110)]),
        row(2, [candidate(x=120)]),
    ]
    segments = None
    if kind == "frame_gap":
        rows[1]["frame"], rows[2]["frame"] = 2, 3
    elif kind == "clock_gap":
        rows[1]["time_s"], rows[2]["time_s"] = 0.2, 0.23
    elif kind == "camera":
        rows[0]["camera_segment_start_frame"] = 0
        rows[1]["camera_segment_start_frame"] = 1
        rows[2]["camera_segment_start_frame"] = 1
    elif kind == "segments":
        segments = [
            {"start_frame": 0, "end_frame": 1, "eligible": True},
            {"start_frame": 1, "end_frame": 3, "eligible": True},
        ]
    elif kind == "exclusion":
        rows[0]["shuttle"]["selection_context_excluded"] = True
    else:
        rows[0] = row(0, [])
    result = selection.feature_rows(rows, segments=segments)
    index = result["row_indices"].index(1)
    assert result["features"][index, 7] == 0
    assert result["features"][index, 10] == 0
    assert result["features"][index, 12] == 0
    assert result["features"][index, 11] == 1
    assert rows[0]["frame"] not in result["support_frames"][index]


def test_feature_speed_clipping_is_applied_to_raw_representation():
    result = selection.feature_rows(
        [row(0, [candidate(x=0)], 0), row(1, [candidate(x=500)], 0.00001)]
    )
    assert result["features"][0, 8] == 20
    assert np.all(result["features"] <= 20)
    assert np.all(result["features"] >= -20)


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), 0])
def test_reject_invalid_or_duplicate_native_clock(value):
    rows = [row(0), row(1)]
    rows[1]["time_s"] = value
    with pytest.raises(ValueError, match="native clocks"):
        selection.feature_rows(rows)


@pytest.mark.parametrize("value", [True, 0, -1, 0.5])
def test_reject_invalid_native_frame_identity(value):
    rows = [row(0), row(1)]
    rows[1]["frame"] = value
    with pytest.raises(ValueError, match="frames"):
        selection.feature_rows(rows)


@pytest.mark.parametrize(
    "key,value",
    [
        ("id", True),
        ("id", 0),
        ("x", float("nan")),
        ("y", float("inf")),
        ("confidence", 1.1),
        ("area_heatmap_pixels", 0),
        ("area_heatmap_pixels", 4.0),
        ("box_heatmap", [0, 0, 0, 4]),
        ("box_heatmap", [511, 0, 4, 4]),
        ("box_heatmap", [0, 0, 2, 1]),
    ],
)
def test_reject_malformed_candidate_evidence(key, value):
    rows = [row(0)]
    rows[0]["shuttle"]["component_candidates"][0][key] = value
    with pytest.raises(ValueError):
        selection.feature_rows(rows)


def test_reject_duplicate_component_identity():
    with pytest.raises(ValueError, match="component identities"):
        selection.feature_rows([row(0, [candidate(), candidate(x=200)])])


@pytest.mark.parametrize(
    "segments",
    [
        [
            {"start_frame": 0, "end_frame": 3, "eligible": True},
            {"start_frame": 2, "end_frame": 4, "eligible": True},
        ],
        [{"start_frame": 0, "end_frame": 3}],
        [{"start_frame": True, "end_frame": 3, "eligible": True}],
    ],
)
def test_reject_ambiguous_segment_evidence(segments):
    with pytest.raises(ValueError, match="segments"):
        selection.feature_rows([row(0)], segments=segments)


def test_uncovered_and_excluded_rows_are_unavailable_not_negative_predictions():
    original = [row(0), row(1), row(2)]
    segments = [
        {"start_frame": 1, "end_frame": 2, "eligible": True},
        {"start_frame": 2, "end_frame": 3, "eligible": False},
    ]
    result = selection.select(original, scorer(), 0.1, segments=segments)
    assert [r["selection_available"] for r in result] == [False, True, False]
    assert (
        result[0]["selection_unavailable_reason"]
        == "unverified_or_excluded_source_context"
    )
    assert not result[0]["shuttle"]["visible"]
    assert result[1]["shuttle"]["selection_context_frames"] == [1]


def test_selection_uses_observed_candidate_identity_probability_ties_and_confidence():
    rows = [
        row(
            0,
            [candidate(8, x=200, confidence=0.3), candidate(2, x=150, confidence=0.8)],
        )
    ]
    before = copy.deepcopy(rows)
    result = selection.select(rows, scorer(), 0.5)
    point = result[0]["shuttle"]
    assert (point["x"], point["y"], point["selected_component_id"]) == (150, 100, 2)
    assert point["confidence"] == 0.8
    assert point["selection_probability"] == 0.5
    assert point["repaired"] is False
    assert point["component_candidates"] == rows[0]["shuttle"]["component_candidates"]
    result[0]["shuttle"]["component_candidates"][0]["x"] = 0
    assert rows == before


def test_available_abstention_and_missing_components_never_invent_coordinates():
    rows = [row(0), row(1, [])]
    result = selection.select(rows, scorer(), 0.6)
    assert all(r["selection_available"] for r in result)
    assert all(
        r["shuttle"]["x"] is None
        and r["shuttle"]["y"] is None
        and not r["shuttle"]["visible"]
        for r in result
    )
    assert result[0]["shuttle"]["confidence"] == rows[0]["shuttle"]["confidence"]
    assert result[0]["shuttle"]["selection_probability"] == 0.5
    assert result[1]["shuttle"]["selection_probability"] is None


def test_selection_support_covers_future_neighbor_used_for_decision():
    rows = [row(i, [candidate(x=100 + i)]) for i in range(3)]
    point = selection.select(rows, scorer(), 0.5)[1]["shuttle"]
    assert point["selection_context_frames"] == [0, 1, 2]
    assert point["selection_context_start_frame"] == 0
    assert point["selection_context_end_frame"] == 3


def test_fit_is_deterministic_class_balanced_and_training_normalized():
    training = [group()]
    original = copy.deepcopy(training)
    fitted = selection.fit(training)
    expected = selection.feature_rows(training[0]["rows"])["features"]
    assert fitted["available"]
    assert fitted["positive_candidates"] == 2
    assert fitted["negative_candidates"] == 3
    assert fitted["steps"] == 500
    assert fitted["normalization_input"] == fitted["fit_input"] == "train"
    np.testing.assert_allclose(fitted["mean"], expected.mean(axis=0))
    np.testing.assert_allclose(fitted["scale"], np.maximum(expected.std(axis=0), 1e-6))
    assert fitted == selection.fit(training)
    assert training == original
    json.dumps(fitted, allow_nan=False)
    predicted = selection.select(training[0]["rows"], fitted, 0.5)
    assert predicted[0]["shuttle"]["selected_component_id"] == 1
    assert not predicted[2]["shuttle"]["visible"]


def test_fit_matches_independent_fixed_gradient_recipe():
    training = [group()]
    fitted = selection.fit(training)
    x = selection.feature_rows(training[0]["rows"])["features"]
    x = (x - np.mean(x, axis=0)) / np.maximum(np.std(x, axis=0), 1e-6)
    y = np.array([1, 0, 1, 0, 0], dtype=float)
    beta, bias = np.zeros(14), 0.0
    factors = np.array([0.25, 1 / 6, 0.25, 1 / 6, 1 / 6])
    for _ in range(500):
        p = 1 / (1 + np.exp(-np.clip(np.dot(x, beta) + bias, -30, 30)))
        difference = (p - y) * factors
        gradient = np.sum(x * difference[:, None], axis=0) + 0.01 * beta
        bias -= 0.1 * sum(difference)
        beta -= 0.1 * gradient
    np.testing.assert_allclose(fitted["weights"], beta, atol=1e-12)
    assert fitted["intercept"] == pytest.approx(bias, abs=1e-12)


@pytest.mark.parametrize("split", ["validation", "test", None])
def test_fitting_rejects_nontraining_groups(split):
    value = group(split)
    with pytest.raises(ValueError, match="train"):
        selection.fit([value])


@pytest.mark.parametrize("mode", ["only_negative", "only_positive", "no_candidates"])
def test_missing_training_class_is_explicitly_unavailable(mode):
    value = group()
    if mode == "only_negative":
        for label in value["labels"]:
            label.update(visible=False, x=None, y=None)
    elif mode == "only_positive":
        value["rows"] = [row(0)]
        value["labels"] = [{"frame": 0, "visible": True, "x": 100, "y": 100}]
    else:
        value["rows"] = [row(i, []) for i in range(3)]
    fitted = selection.fit([value])
    assert fitted["available"] is False
    assert "weights" not in fitted
    selected = selection.select(value["rows"], fitted, 0.5)
    assert len(selected) == len(value["rows"])
    assert all(not r["selection_available"] for r in selected)
    assert all(r["shuttle"]["selection_probability"] is None for r in selected)


def test_threshold_selection_is_validation_only_and_preserves_normalization():
    fitted = selection.fit([group()])
    before = copy.deepcopy(fitted)
    validation = group("validation")
    chosen = selection.choose_threshold([validation], fitted)
    assert chosen["selection_input"] == "validation"
    assert [r["threshold"] for r in chosen["grid"]] == selection.THRESHOLDS
    assert chosen["threshold"] in selection.THRESHOLDS
    assert fitted == before
    for wrong in ("train", "test", None):
        validation["split"] = wrong
        with pytest.raises(ValueError, match="validation"):
            selection.choose_threshold([validation], fitted)


def test_threshold_tie_uses_fewer_false_positives_then_higher_threshold():
    validation = group("validation")
    for label in validation["labels"]:
        label.update(visible=False, x=None, y=None)
    chosen = selection.choose_threshold([validation], scorer())
    assert chosen["threshold"] == 0.9
    assert chosen["metrics"]["localization_fp"] == 0
    assert chosen["metrics"]["negative"] == 3


def test_unavailable_training_keeps_validation_denominators_without_a_threshold():
    training = group()
    for label in training["labels"]:
        label.update(visible=False, x=None, y=None)
    fitted = selection.fit([training])
    chosen = selection.choose_threshold([group("validation")], fitted)
    assert chosen["available"] is False and chosen["threshold"] is None
    assert chosen["grid"] == []
    assert chosen["metrics"]["frames"] == 3
    assert chosen["metrics"]["unavailable"] == 3
    assert chosen["metrics"]["localization_fn"] == 2
    assert chosen["metrics"]["unavailable_negative"] == 1
    assert chosen["metrics"]["localization_tn"] == 0


@pytest.mark.parametrize("mode", ["unavailable", "unknown"])
def test_no_supported_validation_cannot_choose_a_usable_threshold(mode):
    validation = group("validation")
    if mode == "unavailable":
        validation["segments"] = []
    else:
        validation["labels"] = [
            {"frame": frame, "state": "unknown"} for frame in range(3)
        ]
    chosen = selection.choose_threshold([validation], scorer())
    assert chosen["available"] is False
    assert chosen["threshold"] is None
    assert chosen["reason"] == "validation_has_no_available_localization_truth"
    assert chosen["metrics"]["frames"] == 3
    assert len(chosen["grid"]) == 9


def test_metrics_retain_displacement_unknown_and_missing_inputs():
    rows = [
        row(0, [candidate(x=100)]),
        row(1, [candidate(x=200)]),
        row(2, []),
        row(3),
        row(4),
        row(5),
    ]
    rows[4]["selection_available"] = False
    rows[5]["selection_available"] = False
    labels = [
        {"frame": 0, "visible": True, "x": 100, "y": 100},
        {"frame": 1, "visible": True, "x": 100, "y": 100},
        {"frame": 2, "visible": False},
        {"frame": 3, "state": "unknown"},
        {"frame": 4, "visible": False},
        {"frame": 5, "visible": True, "x": 100, "y": 100},
    ]
    result = selection.metrics([{"rows": rows, "labels": labels}])
    assert result["frames"] == 6
    assert (result["visible"], result["negative"], result["unknown"]) == (3, 2, 1)
    assert (
        result["localization_tp"],
        result["localization_fp"],
        result["localization_fn"],
        result["localization_tn"],
    ) == (1, 1, 2, 1)
    assert result["displaced"] == 1
    assert result["unavailable"] == 2
    assert result["unavailable_negative"] == 1
    assert result["localization_f1"] == pytest.approx(0.4)
    assert result["mean_error_predicted_visible_px"] == 50
    assert result["outcomes"][3]["localization"] == "unscored"
    assert result["outcomes"][4]["localization"] == "unavailable"


def test_evaluation_rejects_missing_or_reordered_labels_and_conflicting_states():
    value = group("test")
    value["labels"].pop()
    with pytest.raises(ValueError, match="denominator"):
        selection.metrics([value])
    value = group("test")
    value["labels"].reverse()
    with pytest.raises(ValueError, match="correspondence"):
        selection.metrics([value])
    value = group("test")
    value["labels"][0]["state"] = "not_visible"
    with pytest.raises(ValueError, match="Conflicting"):
        selection.metrics([value])


@pytest.mark.parametrize(
    "key,value",
    [
        ("weights", [0] * 13),
        ("mean", [float("nan")] * 14),
        ("scale", [0] * 14),
        ("intercept", float("inf")),
        ("feature_names", ["wrong"] * 14),
    ],
)
def test_prediction_rejects_corrupt_scorer(key, value):
    model = scorer()
    model[key] = value
    with pytest.raises(ValueError):
        selection.select([row(0)], model, 0.5)


def test_feature_extraction_does_not_read_labels():
    value = group()
    before = selection.feature_rows(value["rows"])["features"]
    value["labels"] = [{"frame": False, "visible": "invalid"}]
    np.testing.assert_array_equal(
        selection.feature_rows(value["rows"])["features"], before
    )


def test_unavailable_input_cannot_become_available_or_supply_neighbor_features():
    rows = [row(frame) for frame in range(3)]
    rows[1].update(
        selection_available=False,
        selection_unavailable_reason="original_native_input_unavailable",
    )
    before = copy.deepcopy(rows)
    features = selection.feature_rows(rows)
    assert features["row_indices"] == [0, 2]
    assert features["support_frames"] == [[0], [2]]
    selected = selection.select(rows, scorer(), 0.1)
    assert [entry["selection_available"] for entry in selected] == [True, False, True]
    assert (
        selected[1]["selection_unavailable_reason"]
        == "original_native_input_unavailable"
    )
    assert selected[1]["shuttle"]["selection_probability"] is None
    assert selected[1]["shuttle"]["x"] is None
    assert rows == before


@pytest.mark.parametrize("availability", [None, 0, 1, "false"])
def test_reject_ambiguous_input_availability(availability):
    rows = [row(0)]
    rows[0]["selection_available"] = availability
    with pytest.raises(ValueError, match="availability"):
        selection.feature_rows(rows)


def test_finite_parameters_cannot_silently_produce_nonfinite_probabilities():
    model = scorer(weights=[1e308, -1e308] + [0.0] * 12)
    model["mean"] = [-1e308] * 14
    model["scale"] = [1e-6] * 14
    with np.errstate(over="ignore", invalid="ignore"):
        with pytest.raises(ValueError, match="nonfinite"):
            selection.select([row(0)], model, 0.5)
