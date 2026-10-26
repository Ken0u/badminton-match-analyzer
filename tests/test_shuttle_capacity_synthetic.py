"""Own generated inputs; no scientific source, checkpoint or GPU access."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from badminton.shuttle_capacity_synthetic import (
    FRAMES,
    PROTOCOL,
    SPLITS,
    generate_group,
    group_seed,
    heatmaps,
)


def test_public_protocol_is_exact_executable_recipe():
    path = (
        Path(__file__).resolve().parents[1]
        / "data/manifests/shuttle_capacity_protocol_v1.json"
    )
    assert json.loads(path.read_bytes()) == PROTOCOL


def test_complete_generated_source_groups_have_disjoint_reproducible_split_seeds():
    groups = [
        group_seed(split, index)
        for split, count in SPLITS.items()
        for index in range(count)
    ]
    assert len(groups) == len(set(groups)) == 160
    expected = int.from_bytes(
        hashlib.sha256(b"synthetic-shuttle-capacity-v1/train/0").digest()[:8], "big"
    )
    assert groups[0] == expected
    assert group_seed("validation", 0) != expected != group_seed("test", 0)


@pytest.mark.parametrize(
    "split,index",
    [("other", 0), ("train", -1), ("test", 16), ("train", True), ("train", 1.0)],
)
def test_unknown_source_group_cannot_alias_another_split(split, index):
    with pytest.raises(ValueError, match="source group"):
        generate_group(split, index)


def test_generated_pixels_background_motion_and_labels_are_bit_repeatable():
    frames, background, labels = generate_group("train", 0)
    other, other_background, other_labels = generate_group("train", 0)
    np.testing.assert_array_equal(frames, other)
    np.testing.assert_array_equal(background, other_background)
    assert labels == other_labels
    assert frames.shape == (FRAMES, 288, 512, 3) and frames.dtype == np.uint8
    assert [entry["frame"] for entry in labels] == list(range(FRAMES))
    np.testing.assert_array_equal(
        background, np.median(frames, axis=0).astype(np.uint8)
    )
    assert np.any(frames[0] != frames[-1])
    other_split = generate_group("validation", 0)[0]
    assert (
        hashlib.sha256(frames.tobytes()).digest()
        != hashlib.sha256(other_split.tobytes()).digest()
    )


def test_targets_follow_exact_subpixel_coordinates_and_explicit_occlusion_absence():
    labels = [
        {"visible": True, "x": 20.25, "y": 30.75},
        {"visible": False, "x": None, "y": None},
    ]
    targets = heatmaps(labels)
    assert targets.shape == (2, 288, 512) and targets.dtype == np.float32
    assert np.unravel_index(targets[0].argmax(), targets[0].shape) == (31, 20)
    assert targets[0, 31, 20] == pytest.approx(np.exp(-0.125 / 4.5))
    assert targets[0, 31, 25] == 0
    assert np.count_nonzero(targets[1]) == 0


def test_generator_has_positive_negative_occluded_and_varied_motion_groups():
    absent, occluded, positive, radii = 0, 0, 0, set()
    for index in range(16):
        _frames, _background, labels = generate_group("train", index)
        absent += any(entry["absent_group"] for entry in labels)
        occluded += any(entry["occluded"] for entry in labels)
        positive += any(entry["visible"] for entry in labels)
        points = [entry for entry in labels if entry["visible"]]
        if len(points) > 1:
            radii.add(round(points[1]["x"] - points[0]["x"], 2))
        assert all(
            (entry["x"] is None and entry["y"] is None)
            if not entry["visible"]
            else (0 < entry["x"] < 512 and 0 < entry["y"] < 288)
            for entry in labels
        )
    assert absent and occluded and positive and len(radii) > 5


def test_new_seeds_are_disjoint_from_every_historical_source_group():
    from badminton.shuttle_synthetic import group_seed as historical_seed

    old = {historical_seed(split, i) for split, n in SPLITS.items() for i in range(n)}
    fresh = {group_seed(split, i) for split, n in SPLITS.items() for i in range(n)}
    assert len(fresh) == 160 and not fresh & old
