"""Observed-component association must not invent coordinates or bridge views."""

import json
from copy import deepcopy

import av
import numpy as np
import pytest
from badminton.shuttle import (
    HEIGHT,
    WIDTH,
    _ComponentSelector,
    infer_camera_segment,
    localization_recipe,
    locate_shuttle,
)


def heatmap(*blobs):
    heat = np.zeros((100, 100), np.float32)
    for x, y, size, confidence in blobs:
        heat[y : y + size, x : x + size] = confidence
    return heat


def assert_primary_unchanged(chosen, raw):
    assert {k: chosen[k] for k in raw} == raw


def seeded_selector():
    selector = _ComponentSelector(100, 100)
    for i in range(3):
        selector.select(
            locate_shuttle(heatmap((10 + i, 10, 1, 0.9)), 100, 100), i, i * 0.04
        )
    return selector


def ambiguous_heat():
    return heatmap((90, 80, 3, 0.95), (14, 10, 1, 0.7))


def test_only_reachable_observed_alternative_beats_impossible_largest_blob():
    heat = ambiguous_heat()
    before_heat = heat.copy()
    raw = locate_shuttle(heat, 100, 100)
    before = deepcopy(raw)
    chosen = seeded_selector().select(raw, 3, 0.12)
    assert raw == before
    np.testing.assert_array_equal(heat, before_heat)
    assert (raw["x"], raw["y"]) == (91.5, 81.5)
    assert (chosen["x"], chosen["y"]) == (14.5, 10.5)
    assert chosen["confidence"] == pytest.approx(0.7)
    assert chosen["selection_reason"] == "unique_reachable_component"
    assert chosen["selected_component_id"] != chosen["largest_component_id"]
    assert chosen["selection_context_frames"] == [0, 1, 2]
    assert chosen["components"] == 2 and chosen["visible"] and not chosen["repaired"]
    assert any(
        c["id"] == chosen["selected_component_id"]
        and (c["x"], c["y"]) == (chosen["x"], chosen["y"])
        for c in chosen["component_candidates"]
    )
    json.dumps(chosen, allow_nan=False)


@pytest.mark.parametrize(
    "failure", ["frame_gap", "time_gap", "reversed_time", "missing"]
)
def test_history_cannot_cross_missing_observations_or_source_discontinuities(failure):
    selector = seeded_selector()
    frame, timestamp = 3, 0.12
    if failure == "frame_gap":
        frame = 4
    elif failure == "time_gap":
        timestamp = 0.20
    elif failure == "reversed_time":
        timestamp = 0.04
    else:
        selector.select(locate_shuttle(heatmap(), 100, 100), 3, 0.12)
        frame, timestamp = 4, 0.16
    raw = locate_shuttle(ambiguous_heat(), 100, 100)
    assert_primary_unchanged(selector.select(raw, frame, timestamp), raw)


def test_ambiguous_alternatives_or_plausible_primary_do_not_justify_switching():
    # Two small reachable components cannot establish which one is the shuttle.
    raw = locate_shuttle(
        heatmap((90, 80, 3, 0.95), (14, 10, 1, 0.7), (20, 15, 1, 0.8)), 100, 100
    )
    assert_primary_unchanged(seeded_selector().select(raw, 3, 0.12), raw)
    # A nearer alternative does not override an already reachable primary.
    raw = locate_shuttle(heatmap((22, 10, 3, 0.95), (14, 10, 1, 0.7)), 100, 100)
    assert_primary_unchanged(seeded_selector().select(raw, 3, 0.12), raw)


@pytest.mark.parametrize("count", [0, 1, 2])
def test_short_history_cannot_reassign_a_component(count):
    selector = _ComponentSelector(100, 100)
    for i in range(count):
        selector.select(
            locate_shuttle(heatmap((10 + i, 10, 1, 0.9)), 100, 100), i, i * 0.04
        )
    raw = locate_shuttle(ambiguous_heat(), 100, 100)
    assert_primary_unchanged(selector.select(raw, count, count * 0.04), raw)


def test_unstable_history_cannot_seed_selection_and_direction_changes_are_allowed():
    selector = seeded_selector()
    # No observed alternative: keep the raw component, do not synthesize a point.
    jump = locate_shuttle(heatmap((90, 80, 3, 0.95)), 100, 100)
    assert_primary_unchanged(selector.select(jump, 3, 0.12), jump)
    raw = locate_shuttle(ambiguous_heat(), 100, 100)
    assert_primary_unchanged(selector.select(raw, 4, 0.16), raw)
    # Reversing direction at a racket hit does not violate a speed-only gate.
    reversal = locate_shuttle(heatmap((5, 10, 3, 0.95), (14, 10, 1, 0.7)), 100, 100)
    assert_primary_unchanged(seeded_selector().select(reversal, 3, 0.12), reversal)


def test_reachability_uses_source_pts_instead_of_assumed_frame_rate():
    raw = locate_shuttle(heatmap((40, 10, 3, 0.95), (14, 10, 1, 0.7)), 100, 100)
    # The primary is reachable after 40 ms, but not after 20 ms. Both are
    # consecutive source frames with identical previous observations.
    assert_primary_unchanged(seeded_selector().select(raw, 3, 0.12), raw)
    chosen = seeded_selector().select(raw, 3, 0.10)
    assert chosen["selection_reason"] == "unique_reachable_component"
    assert chosen["x"] == 14.5


def test_chained_selection_preserves_the_earliest_evidence_dependency():
    selector = seeded_selector()
    for frame in range(3, 8):
        chosen = selector.select(
            locate_shuttle(ambiguous_heat(), 100, 100), frame, frame * 0.04
        )
        assert chosen["selection_reason"] == "unique_reachable_component"
        assert chosen["selection_context_start_frame"] == 0
        assert chosen["selection_context_end_frame"] == frame + 1


def test_component_history_resets_at_each_camera_segment():
    heats = [heatmap((10 + i, 10, 1, 0.9)) for i in range(3)] + [ambiguous_heat()]

    def frames(first, last):
        return [
            (
                i,
                i * 0.04,
                av.VideoFrame.from_ndarray(np.full((16, 16, 3), i, np.uint8), "rgb24"),
            )
            for i in range(first, last)
        ]

    def predict(images):
        return np.asarray([heats[int(image[0, 0, 0])] for image in images[1:]])

    background = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    continuous = list(
        infer_camera_segment(frames(0, 4), background, 4, predict, 100, 100)
    )
    assert continuous[-1]["shuttle"]["selection_reason"] == "unique_reachable_component"
    scene_boundary = list(
        infer_camera_segment(
            frames(0, 4), background, 4, predict, 100, 100, selection_reset_frames={3}
        )
    )
    assert (
        scene_boundary[-1]["shuttle"]["selection_reason"] == "largest_heatmap_component"
    )
    split = list(infer_camera_segment(frames(0, 3), background, 4, predict, 100, 100))
    split += list(infer_camera_segment(frames(3, 4), background, 4, predict, 100, 100))
    assert split[-1]["shuttle"]["selection_reason"] == "largest_heatmap_component"
    assert [r["frame"] for r in split] == [0, 1, 2, 3]
    assert [r["time_s"] for r in split] == [0, 0.04, 0.08, 0.12]


@pytest.mark.parametrize(
    "heat",
    [np.zeros((0, 2)), np.zeros((1, 2, 3)), np.array([[np.nan]]), np.array([[np.inf]])],
)
def test_invalid_heatmaps_do_not_emit_nonfinite_artifacts(heat):
    with pytest.raises(ValueError, match="finite 2D"):
        locate_shuttle(heat, 100, 100)


def test_recipe_explains_observed_selection_and_threshold():
    recipe = localization_recipe()
    assert recipe["heatmap_threshold"] == 0.5
    assert "Never interpolated" in recipe["missing_points"]
