import copy
import math

import numpy as np
import pytest
from badminton.rallies import context_signature
from badminton.stroke_context import (
    BODY_DIM,
    EXTENDED_FLIGHT_OFFSETS,
    FEATURE_DIM,
    StrokeContext,
)
from test_contact_features import fixture


def inputs(times=None):
    video, players, shuttle = fixture(times)
    video["frame_count"] = len(shuttle["frames"])
    doc = {
        "calibrations": [
            {
                "start_frame": 0,
                "end_frame": video["frame_count"],
                "corners": [
                    {"x": 0.1, "y": 0.1},
                    {"x": 0.9, "y": 0.1},
                    {"x": 0.9, "y": 0.9},
                    {"x": 0.1, "y": 0.9},
                ],
            }
        ],
    }
    for run in (players, shuttle):
        run.update(start_frame=0, end_frame=video["frame_count"])
    players["calibration_signature"] = context_signature(doc, 0, video["frame_count"])[
        "court"
    ]
    for row in players["frames"]:
        for k in (15, 16):
            row["players"][0]["keypoints"][k][2] = 0
    return video, players, shuttle, doc


def test_global_observed_flight_and_source_velocity_are_preserved():
    data = inputs()
    before = copy.deepcopy(data)
    ctx = StrokeContext(*data)
    packed = ctx.pack(40, 1)
    assert packed["features"].shape == (FEATURE_DIM,) == (371,)
    flight = packed["features"][BODY_DIM:362].reshape(9, 12)
    np.testing.assert_allclose(flight[4, :4], [1, 0, 400 / 1280, 260 / 720])
    np.testing.assert_allclose(flight[4, 6:9], [1, 30 / math.hypot(1280, 720), 0])
    assert packed["anchor_observation_frame"] == 40
    assert packed["context_start_frame"] == 33
    assert packed["context_end_frame"] == 47
    assert data == before


def test_body_features_match_existing_observed_arm_windows():
    ctx = StrokeContext(*inputs())
    packed = ctx.pack(40, 1)["features"]
    for side in (0, 1):
        slot = np.flatnonzero(
            (ctx.body["arm_ids"][40, :, 0] == 1)
            & (ctx.body["arm_ids"][40, :, 1] == side)
        )[0]
        np.testing.assert_array_equal(
            packed[126 * side : 126 * (side + 1)], ctx.body["x"][40, slot]
        )
    np.testing.assert_array_equal(packed[252:254], [1, 1])


def test_extended_flight_requires_full_source_context_and_exports_its_recipe():
    data = inputs()
    ctx = StrokeContext(*data, flight_offsets=EXTENDED_FLIGHT_OFFSETS)
    packed = ctx.pack(40, 1)
    assert packed["features"].shape == (443,)
    assert (packed["context_start_frame"], packed["context_end_frame"]) == (24, 56)
    assert ctx.recipe["feature_dim"] == 443
    assert ctx.recipe["flight_offsets_s"] == EXTENDED_FLIGHT_OFFSETS
    assert ctx.pack(10, 1) is None  # No padding with clip-edge or invented positions.
    np.testing.assert_array_equal(
        packed["features"][:254], StrokeContext(*data).pack(40, 1)["features"][:254]
    )


@pytest.mark.parametrize(
    "offsets", [(-0.6, 0, 0.2), (-0.2, 0, 0), (0, 0.1, 0.2), (-0.2, float("nan"), 0.2)]
)
def test_invalid_flight_recipe_is_rejected(offsets):
    with pytest.raises(ValueError, match="Flight offsets"):
        StrokeContext(*inputs(), flight_offsets=offsets)


def test_missing_points_stay_masked_and_anchor_is_an_actual_observation():
    v, p, s, doc = inputs()
    for row in s["frames"][38:43]:
        row["shuttle"].update(visible=False, x=None, y=None)
    packed = StrokeContext(v, p, s, doc).pack(40, 1)
    flight = packed["features"][254:362].reshape(9, 12)
    np.testing.assert_array_equal(flight[4], np.zeros(12))
    np.testing.assert_array_equal(flight[:, 4:6], 0)
    np.testing.assert_array_equal(packed["features"][-3:], 0)
    assert packed["anchor_observation_frame"] is None
    assert s["frames"][40]["shuttle"]["x"] is None


def test_repaired_coordinates_do_not_enter_global_flight():
    v, p, s, doc = inputs()
    s["frames"][40]["shuttle"]["repaired"] = True
    packed = StrokeContext(v, p, s, doc).pack(40, 1)
    np.testing.assert_array_equal(packed["features"][254:362].reshape(9, 12)[4], 0)
    assert packed["anchor_observation_frame"] in (39, 41)


def test_extra_flight_samples_expand_transitive_lineage_at_60fps():
    v, p, s, doc = inputs(np.arange(90) / 60)
    # Frame54 is used by the denser flight window, not by the body samples.
    s["frames"][54]["shuttle"].update(
        selection_context_start_frame=20, selection_context_end_frame=55
    )
    ctx = StrokeContext(v, p, s, doc)
    assert ctx.body["context"][60].tolist() == [47, 73]
    assert ctx.pack(60, 1)["context_start_frame"] == 20
    doc["scene_ranges"] = [
        {"id": "earlier", "start_frame": 25, "end_frame": 26, "scene": "unknown"}
    ]
    assert StrokeContext(v, p, s, doc).pack(60, 1) is None


@pytest.mark.parametrize(
    "failure", ["source_hash", "camera_edit", "court_edit", "missing_court_provenance"]
)
def test_stale_or_wrong_sources_are_rejected(failure):
    v, p, s, doc = inputs()
    if failure == "source_hash":
        p["video_sha256"] = "another video"
    elif failure == "camera_edit":
        doc["camera_corrections"] = [{"frame": 40, "is_cut": True}]
    elif failure == "court_edit":
        doc["calibrations"][0]["corners"][0]["x"] += 0.01
    else:
        p.pop("calibration_signature")
    with pytest.raises(ValueError):
        StrokeContext(v, p, s, doc)


def test_current_scene_and_camera_context_blocks_inference():
    v, p, s, doc = inputs()
    doc["scene_ranges"] = [
        {"id": "replay", "start_frame": 45, "end_frame": 46, "scene": "replay"}
    ]
    assert StrokeContext(v, p, s, doc).pack(40, 1) is None
    doc.pop("scene_ranges")
    for run in (p, s):
        run["cut_frames"] = [45]
    assert StrokeContext(v, p, s, doc).pack(40, 1) is None


def test_court_hint_uses_observed_feet_and_masks_ankle_fallback():
    v, p, s, doc = inputs()
    baseline = StrokeContext(v, p, s, doc).pack(40, 1)["features"][362:368]
    np.testing.assert_allclose(
        baseline[:4],
        [1, (350 / 1280 - 0.1) / 0.8, (400 / 720 - 0.1) / 0.8, 0],
        atol=1e-6,
    )
    for k in (15, 16):
        p["frames"][40]["players"][0]["keypoints"][k] = [360, 390, 0.9]
    observed = StrokeContext(v, p, s, doc).pack(40, 1)["features"][362:368]
    assert observed[3] == 1 and observed[1] > baseline[1] and observed[2] < baseline[2]


def test_no_calibration_boundary_may_split_complete_context():
    v, p, s, doc = inputs()
    first = copy.deepcopy(doc["calibrations"][0])
    first["end_frame"] = 40
    doc["calibrations"][0]["start_frame"] = 40
    doc["calibrations"].insert(0, first)
    p["calibration_signature"] = context_signature(doc, 0, 90)["court"]
    assert StrokeContext(v, p, s, doc).pack(40, 1) is None


def test_event_labels_and_track_numbers_do_not_enter_values():
    v, p, s, doc = inputs()
    expected = StrokeContext(v, p, s, doc).pack(40, 1)["features"]
    doc["events"] = [{"family": "smash", "side": "backhand", "player_id": "A"}]
    doc["track_assignments"] = [{"track_id": 9, "player_id": "B"}]
    for row in p["frames"]:
        row["players"][0]["track_id"] = 9
    actual = StrokeContext(v, p, s, doc).pack(40, 9)["features"]
    np.testing.assert_array_equal(actual, expected)


def test_input_edits_after_construction_do_not_mix_inference_snapshots():
    v, p, s, doc = inputs()
    ctx = StrokeContext(v, p, s, doc)
    expected = ctx.pack(40, 1)["features"].copy()
    v["width"] = 1920
    doc["calibrations"][0]["corners"][0]["x"] += 0.01
    p["frames"][40]["players"][0]["keypoints"][9][0] += 300
    s["frames"][40]["shuttle"]["x"] += 100
    np.testing.assert_array_equal(ctx.pack(40, 1)["features"], expected)


def test_edges_missing_actor_and_long_source_gap_abstain():
    ctx = StrokeContext(*inputs())
    assert ctx.pack(0, 1) is None and ctx.pack(40, 99) is None
    times = np.arange(90) / 30
    times[45:] += 0.3
    assert StrokeContext(*inputs(times)).pack(44, 1) is None
