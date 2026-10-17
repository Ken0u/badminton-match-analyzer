import copy

import numpy as np
import pytest
from badminton.recognition import recognition_targets
from badminton.schemas import Annotations, empty_annotations
from badminton.stroke_features import (
    BONES,
    build_stroke_clip,
    normalize_joints,
    pack_sequence,
    source_classes,
    summarize_probabilities,
)


def test_hitter_hint_uses_selected_family_mass_instead_of_unrelated_top_class():
    scores = np.zeros(35)
    scores[2] = 0.4  # Strongest individual class: far smash.
    scores[24], scores[25], scores[30] = 0.3, 0.2, 0.1  # Near drives total 0.6.
    result = summarize_probabilities(scores)
    assert result["family"] == "drive" and result["hitter_court_end"] == "near"
    assert result["top_classes"][0]["court_end"] == "far"
    scores[:] = 0
    scores[7], scores[24] = 0.5, 0.5
    assert summarize_probabilities(scores)["hitter_court_end"] is None
    scores[:] = 0
    scores[34] = 1
    assert summarize_probabilities(scores)["hitter_court_end"] is None


def clip_inputs():
    video = {
        "id": "sample",
        "mode": "singles",
        "width": 640,
        "height": 360,
        "duration_s": 2.4,
    }
    times = [i / 25 for i in range(60)]
    people = []
    for track, box in ((8, [200, 180, 280, 330]), (3, [250, 20, 300, 160])):
        x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        points = [[x, y, 0.95] for _ in range(17)]
        points[15:] = [[x - 5, box[3] - 2, 0.95], [x + 5, box[3] - 2, 0.95]]
        people.append({"track_id": track, "box": box, "keypoints": points})
    players = {
        "stage": "players",
        "video_id": "sample",
        "start_frame": 0,
        "end_frame": 60,
        "stride": 1,
        "frames": [
            {"frame": i, "time_s": t, "players": copy.deepcopy(people)}
            for i, t in enumerate(times)
        ],
    }
    shuttle = {
        "stage": "shuttle",
        "video_id": "sample",
        "start_frame": 0,
        "end_frame": 60,
        "frames": [
            {"frame": i, "time_s": t, "shuttle": {"visible": True, "x": 320, "y": 100}}
            for i, t in enumerate(times)
        ],
    }
    calibrations = [
        {
            "start_frame": 0,
            "end_frame": 60,
            "corners": [
                {"x": 0, "y": 0},
                {"x": 1, "y": 0},
                {"x": 1, "y": 1},
                {"x": 0, "y": 1},
            ],
        }
    ]
    return video, times, players, shuttle, calibrations


def test_excluded_component_history_cannot_be_used_as_shuttle_features():
    video, times, players, shuttle, calibrations = clip_inputs()
    for row in shuttle["frames"]:
        row["shuttle"]["selection_context_excluded"] = True
    before = copy.deepcopy(shuttle)
    result = build_stroke_clip(video, times, players, shuttle, calibrations, 30)
    assert result["coverage"]["visible_shuttle_frames"] == 0
    assert result["status"] == "abstained"
    assert shuttle == before


def test_source_label_contract_has_explicit_non_target_mapping_and_no_stroke_side():
    labels = source_classes()
    assert len(labels) == 35 and labels[0]["source_type"] == "net shot"
    assert labels[17]["court_end"] == "near" and labels[-1]["source_type"] == "unknown"
    assert labels[3]["source_type"] == "wrist smash" and labels[3]["family"] == "other"
    assert labels[15]["kind"] == "serve" and labels[15]["family"] is None
    scores = np.zeros(35)
    scores[4], scores[5], scores[21] = 0.4, 0.3, 0.3
    result = summarize_probabilities(scores)
    assert result["family"] == "lift" and result["family_score"] == pytest.approx(1)
    assert result["side"] == "unknown"
    assert set(result["family_scores"]) == {
        "clear",
        "lift",
        "net",
        "drop",
        "smash",
        "drive",
        "other",
        "unknown",
        "serve",
    }
    for bad in (np.zeros(35), np.full(35, np.nan), np.zeros(34)):
        with pytest.raises(ValueError):
            summarize_probabilities(bad)


def test_box_diagonal_center_normalization_and_upstream_zero_coordinate_semantics():
    points = np.full((17, 2), [130, 240], dtype=float)
    result = normalize_joints(points, [100, 200, 160, 280])
    assert result == pytest.approx(np.zeros((17, 2)))
    points[0] = [0, 0]
    result = normalize_joints(points, [100, 200, 160, 280])
    assert result[0] == pytest.approx([-0.3, -0.4])
    with pytest.raises(ValueError):
        normalize_joints(points, [1, 2, 1, 4])


def test_sequence_padding_bones_and_long_clip_decimation_match_source_contract():
    joints = np.ones((25, 2, 17, 2), np.float32)
    joints[:, :, 1] = [2, 3]
    pose, shuttle, length, selected = pack_sequence(joints, np.full((25, 2), 0.5))
    assert pose.shape == (30, 2, 72) and shuttle.shape == (30, 2)
    assert length == 25 and selected == list(range(25))
    assert pose[0, 0, 34:36] == pytest.approx([1, 2])
    assert not pose[25:].any() and not shuttle[25:].any() and len(BONES) == 19
    _, _, length, selected = pack_sequence(np.ones((55, 2, 17, 2)), np.ones((55, 2)))
    assert length == 28 and selected == list(range(0, 55, 2))


def test_source_clip_sorts_court_ends_preserves_gaps_and_never_changes_raw_tracks():
    args = clip_inputs()
    before = copy.deepcopy(args)
    args[3]["frames"][30]["shuttle"] = {"visible": False, "x": None, "y": None}
    clip = build_stroke_clip(*args, 30)
    assert clip["status"] == "ready" and clip["length"] == 25
    assert clip["contact_tracks"] == {"far": 3, "near": 8}
    assert clip["coverage"]["visible_shuttle_frames"] == 24
    index = clip["sampled_frames"].index(30)
    assert not clip["shuttle"][index].any()
    assert args[2] == before[2]
    assert args[3]["frames"][30]["shuttle"]["x"] is None


@pytest.mark.parametrize(
    "failure",
    [
        "context",
        "calibration",
        "cut",
        "pose",
        "shuttle",
        "output",
        "stale_calibration",
        "scene",
    ],
)
def test_missing_or_incompatible_context_abstains_instead_of_fabricating_features(
    failure,
):
    args = clip_inputs()
    if failure == "context":
        args[2]["start_frame"] = 25
    if failure == "calibration":
        args[4][0]["end_frame"] = 30
    if failure == "cut":
        args[3]["cut_frames"] = [30]
    if failure == "pose":
        for row in args[2]["frames"]:
            row["players"] = []
    if failure == "shuttle":
        for row in args[3]["frames"]:
            row["shuttle"] = {"visible": False, "x": None, "y": None}
    if failure == "output":
        args[3]["frames"].pop(30)
    if failure == "stale_calibration":
        args[2]["frames"][30]["calibration_valid"] = False
    if failure == "scene":
        args[3]["frames"][30]["scene"] = "replay"
    result = build_stroke_clip(*args, 30)
    assert result["status"] == "abstained" and result["reason"] and "pose" not in result


def test_wrong_run_mode_stride_and_timestamp_alignment_are_rejected():
    for change in ("mode", "video", "stride", "time"):
        args = clip_inputs()
        if change == "mode":
            args[0]["mode"] = "doubles"
        if change == "video":
            args[2]["video_id"] = "different"
        if change == "stride":
            args[2]["stride"] = 2
        if change == "time":
            args[3]["frames"][30]["time_s"] += 0.04
        with pytest.raises(ValueError):
            build_stroke_clip(*args, 30)


def test_reviewed_contacts_take_priority_over_uncertain_proposals_without_duplicating_hits():
    doc = empty_annotations("singles").model_dump()
    doc["events"] = [
        {
            "id": "known",
            "rally_id": "R1",
            "kind": "shot",
            "frame": 30,
            "family": "unknown",
            "side": "unknown",
        }
    ]
    annotations = Annotations.model_validate(doc)
    proposals = {
        "candidates": [
            {"id": "nearby", "frame": 31, "start_frame": 29, "end_frame": 32},
            {"id": "another", "frame": 40},
        ]
    }
    result = recognition_targets(annotations, proposals)
    assert [item["frame"] for item in result] == [30, 40]
    assert result[0]["event_id"] == "known"
    assert recognition_targets(annotations, proposals) == result
    assert [
        t["frame"]
        for t in recognition_targets(
            annotations, proposals, start_frame=35, end_frame=45
        )
    ] == [40]
