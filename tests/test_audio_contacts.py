import copy

import pytest
from badminton.audio_contacts import add_audio_support
from badminton.contacts import propose_contacts


def scenario():
    rows, players = [], []
    for index in range(30):
        t = index * 0.04
        visible = index != 12
        rows.append(
            {
                "frame": index,
                "time_s": t,
                "shuttle": {
                    "visible": visible,
                    "x": 300 if visible else None,
                    "y": 200 if visible else None,
                },
            }
        )
        keypoints = [[0, 0, 0] for _ in range(17)]
        keypoints[9] = [300 + (index - 12) * 4, 200, 0.9]
        players.append(
            {
                "frame": index,
                "time_s": t,
                "players": [
                    {"track_id": 7, "box": [270, 190, 350, 350], "keypoints": keypoints}
                ],
            }
        )
    return (
        {"frames": rows},
        {"frames": players},
        {"width": 640, "height": 360},
        {
            "status": "available",
            "peaks": [
                {"time_s": 0.49, "strength_ratio": 4, "flux": 12, "threshold": 3}
            ],
        },
    )


def test_audio_vision_support_produces_an_unreviewed_interval_without_mutation():
    inputs = scenario()
    original = copy.deepcopy(inputs)
    candidates = add_audio_support([], *inputs)
    assert inputs == original
    assert len(candidates) == 1
    c = candidates[0]
    assert c["frame"] == 12 and c["track_id"] == 7
    assert c["start_time_s"] <= 0.49 - 0.12
    assert c["end_time_s"] >= 0.49 + 0.12
    assert c["start_frame"] < c["frame"] < c["end_frame"]
    assert c["timing"] == "uncertain_interval"
    assert c["reviewed"] is False and c["player_id"] is None
    assert c["evidence"]["av_offset_calibrated"] is False
    assert c["evidence"]["observed_shuttle_frame"] != 12


@pytest.mark.parametrize(
    "failure",
    [
        "missing_audio",
        "unavailable_audio",
        "no_players",
        "all_shuttle_missing",
        "no_gap",
        "static_wrist",
        "distant_wrist",
        "unconfident_wrist",
        "cut",
        "player_cut",
        "replay",
        "player_replay",
        "timestamp_gap",
        "frame_gap",
        "edge",
        "nan_time",
    ],
)
def test_audio_alone_or_invalid_visual_context_never_creates_a_contact(failure):
    shuttle, players, video, cues = scenario()
    if failure in ("missing_audio", "unavailable_audio"):
        cues["status"] = failure.split("_")[0]
    elif failure == "no_players":
        players = None
    elif failure == "all_shuttle_missing":
        for row in shuttle["frames"]:
            row["shuttle"].update(visible=False, x=None, y=None)
    elif failure == "no_gap":
        shuttle["frames"][12]["shuttle"].update(visible=True, x=300, y=200)
    elif failure in ("static_wrist", "distant_wrist", "unconfident_wrist"):
        for row in players["frames"]:
            row["players"][0]["keypoints"][9] = (
                [300, 200, 0.9]
                if failure == "static_wrist"
                else [600 + row["frame"] * 4, 0, 0.9]
                if failure == "distant_wrist"
                else [300 + row["frame"] * 4, 200, 0.1]
            )
    elif failure in ("cut", "player_cut"):
        (players if failure == "player_cut" else shuttle)["cut_frames"] = [12]
    elif failure in ("replay", "player_replay"):
        (players if failure == "player_replay" else shuttle)["frames"][12]["scene"] = (
            "replay"
        )
    elif failure == "timestamp_gap":
        shuttle["frames"][12]["time_s"] += 1
    elif failure == "frame_gap":
        shuttle["frames"].pop(11)
    elif failure == "edge":
        cues["peaks"][0]["time_s"] = 0
    elif failure == "nan_time":
        cues["peaks"][0]["time_s"] = float("nan")
    assert add_audio_support([], shuttle, players, video, cues) == []


def test_audio_corroboration_preserves_original_visual_timing_and_score():
    inputs = scenario()
    visual = [
        {
            "id": "contact-gap-10-14",
            "frame": 12,
            "time_s": 0.48,
            "start_frame": 10,
            "end_frame": 14,
            "track_id": 7,
            "timing": "uncertain_interval",
            "score": 0.6,
            "evidence": {},
        }
    ]
    original = copy.deepcopy(visual)
    result = add_audio_support(visual, *inputs)
    assert visual == original and len(result) == 1
    assert result[0] == original[0] | {"evidence": result[0]["evidence"]}
    assert len(result[0]["evidence"]["audio_support"]) == 1
    assert propose_contacts(inputs[0], inputs[1], inputs[2]) == []


def test_multiple_sounds_at_one_gap_do_not_duplicate_a_contact_or_replace_hitter():
    shuttle, players, video, cues = scenario()
    shuttle["frames"][13]["shuttle"].update(visible=False, x=None, y=None)
    cues["peaks"].append(cues["peaks"][0] | {"time_s": 0.63})
    visual = [
        {
            "id": "visual-gap",
            "frame": 12,
            "time_s": 0.48,
            "track_id": 99,
            "score": 0.8,
            "evidence": {"missing_frames": [12, 13]},
        }
    ]
    result = add_audio_support(visual, shuttle, players, video, cues)
    assert len(result) == 1 and result[0]["track_id"] == 99
    assert len(result[0]["evidence"]["audio_support"]) == 2
    assert all(
        not item["hitter_agrees"] for item in result[0]["evidence"]["audio_support"]
    )


@pytest.mark.parametrize(
    "failure",
    [
        "shifted_frames",
        "shifted_times",
        "duplicate",
        "conflicting_duplicate",
        "time_collision",
        "missing_frame",
        "missing_time",
        "boolean_frame",
        "fractional_frame",
        "nan_time",
        "infinite_time",
        "boolean_time",
        "wrong_time_outside_window",
    ],
)
def test_audio_requires_unambiguous_corresponding_pose_frames(failure):
    shuttle, players, video, cues = scenario()
    rows = players["frames"]
    if failure == "shifted_frames":
        for row in rows:
            row["frame"] += 100
    elif failure == "shifted_times":
        for row in rows:
            row["time_s"] += 0.005
    elif failure in ("duplicate", "conflicting_duplicate"):
        duplicate = copy.deepcopy(rows[12])
        if failure == "conflicting_duplicate":
            duplicate["time_s"] += 0.001
        rows.append(duplicate)
    elif failure == "time_collision":
        rows[12]["time_s"] = rows[11]["time_s"]
    elif failure in ("missing_frame", "missing_time"):
        rows[12].pop("frame" if failure == "missing_frame" else "time_s")
    elif failure == "boolean_frame":
        rows[12]["frame"] = True
    elif failure == "fractional_frame":
        rows[12]["frame"] = 12.5
    elif failure == "nan_time":
        rows[12]["time_s"] = float("nan")
    elif failure == "infinite_time":
        rows[12]["time_s"] = float("inf")
    elif failure == "boolean_time":
        rows[12]["time_s"] = True
    elif failure == "wrong_time_outside_window":
        rows[12]["time_s"] = 10
    original = copy.deepcopy((shuttle, players, video, cues))
    # Deliberately unsorted: ineligible optional evidence must preserve the
    # entire visual result, including order, timing, scores and nested evidence.
    visual = [
        {"id": "later", "frame": 20, "time_s": 0.8, "evidence": {"kept": [1]}},
        {
            "id": "near",
            "frame": 12,
            "time_s": 0.48,
            "track_id": 7,
            "score": 0.6,
            "evidence": {"missing_frames": [12]},
        },
    ]
    before = copy.deepcopy(visual)
    assert add_audio_support([], shuttle, players, video, cues) == []
    assert add_audio_support(visual, shuttle, players, video, cues) == before
    assert visual == before
    # The NaN object itself is preserved rather than normalized or replaced.
    assert (shuttle, players, video, cues) == original


@pytest.mark.parametrize("sampling", ["sparse", "partial", "vfr_nonzero", "roundoff"])
def test_aligned_pose_support_preserves_native_sparse_and_variable_times(sampling):
    shuttle, players, video, cues = scenario()
    if sampling == "sparse":
        players["frames"] = players["frames"][::2]
    elif sampling == "partial":
        players["frames"].pop(12)
    elif sampling == "vfr_nonzero":
        for run in (shuttle, players):
            for row in run["frames"]:
                row["time_s"] += 7.5 + row["frame"] % 3 * 0.001
        cues["peaks"][0]["time_s"] += 7.5
    elif sampling == "roundoff":
        for row in players["frames"]:
            row["time_s"] += 1e-12
    result = add_audio_support([], shuttle, players, video, cues)
    assert len(result) == 1
    candidate = result[0]
    assert candidate["frame"] == 12 and candidate["track_id"] == 7
    assert candidate["start_time_s"] <= cues["peaks"][0]["time_s"] - 0.12
    assert candidate["end_time_s"] >= cues["peaks"][0]["time_s"] + 0.12
    assert candidate["interval_bounds"] == "inclusive"
    assert candidate["evidence"]["pose"]["pose_samples"] >= 3


def test_alignment_does_not_require_pose_outside_the_audio_context():
    shuttle, players, video, cues = scenario()
    players["frames"][0]["frame"] = 100
    players["frames"][0]["time_s"] = -10
    assert len(add_audio_support([], shuttle, players, video, cues)) == 1


def test_insufficient_aligned_sparse_pose_remains_unavailable():
    shuttle, players, video, cues = scenario()
    players["frames"] = players["frames"][::4]
    assert add_audio_support([], shuttle, players, video, cues) == []


@pytest.mark.parametrize(
    "context", ["aligned", "wrong_frame", "cut", "player_replay", "selection_excluded"]
)
def test_sparse_high_rate_pose_corroboration_checks_the_entire_wrist_context(context):
    shuttle, players, video, cues = scenario()
    for run in (shuttle, players):
        for row in run["frames"]:
            row["time_s"] = row["frame"] / 60
    players["frames"] = [
        row for row in players["frames"] if row["frame"] in (6, 12, 18)
    ]
    cues["peaks"][0]["time_s"] = 0.205
    if context == "wrong_frame":
        players["frames"][-1]["frame"] = 100
    elif context == "cut":
        shuttle["cut_frames"] = [7]
    elif context == "player_replay":
        players["frames"][0]["scene"] = "replay"
    elif context == "selection_excluded":
        shuttle["frames"][6]["shuttle"]["selection_context_excluded"] = True
    visual = [
        {
            "id": "visual",
            "frame": 12,
            "time_s": 0.2,
            "track_id": 7,
            "score": 0.6,
            "evidence": {"original": True},
        }
    ]
    original = copy.deepcopy(visual)
    result = add_audio_support(visual, shuttle, players, video, cues)
    assert visual == original
    if context == "aligned":
        assert result[0] == original[0] | {"evidence": result[0]["evidence"]}
        assert result[0]["evidence"]["audio_support"][0]["pose"]["pose_samples"] == 3
    else:
        assert result == original
