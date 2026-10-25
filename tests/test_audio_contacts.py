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


def interval_scenario(rate=60, case="aligned"):
    center = 4 if case == "edge" else 75 if case == "tail" else 24
    times = [
        frame / rate + (7.5 + 0.002 * (frame % 2) if case == "vfr_origin" else 0)
        for frame in range(80)
    ]
    if case == "timestamp_gap":
        times = [t + (0.11 if frame >= 18 else 0) for frame, t in enumerate(times)]
    shuttle, players, video, cues = scenario()
    template_shuttle, template_player = shuttle["frames"][0], players["frames"][0]
    shuttle["frames"], players["frames"] = [], []
    for frame, t in enumerate(times):
        row = copy.deepcopy(template_shuttle)
        row.update(frame=frame, time_s=t)
        visible = frame != center or case == "no_gap"
        row["shuttle"].update(
            visible=visible, x=300 if visible else None, y=200 if visible else None
        )
        shuttle["frames"].append(row)
        player = copy.deepcopy(template_player)
        player.update(frame=frame, time_s=t)
        player["players"][0]["keypoints"][9] = [
            300 if case == "static_wrist" else 300 + (frame - center) * 4,
            200,
            0.9,
        ]
        players["frames"].append(player)
    if case == "sparse":
        players["frames"] = players["frames"][::4]
    elif case in ("cut", "player_cut"):
        (players if case == "player_cut" else shuttle)["cut_frames"] = [18]
    elif case in ("replay_bound", "player_replay_bound", "unknown_bound"):
        (players if case == "player_replay_bound" else shuttle)["frames"][17][
            "scene"
        ] = "unknown" if case == "unknown_bound" else "replay"
    elif case == "excluded_bound":
        shuttle["frames"][17]["shuttle"]["selection_context_excluded"] = True
    elif case == "frame_gap":
        shuttle["frames"].pop(17)
    elif case == "bound_pose_mismatch":
        players["frames"][17]["frame"] = 101
    elif case == "bound_pose_duplicate":
        players["frames"].append(copy.deepcopy(players["frames"][32]))
    elif case in (
        "history_valid",
        "history_replay",
        "missing_history",
        "history_cut",
        "history_player_replay",
        "recursive_history",
    ):
        shuttle["frames"][17]["shuttle"].update(
            selection_context_start_frame=10, selection_context_end_frame=18
        )
        if case == "history_replay":
            shuttle["frames"][10]["scene"] = "replay"
        elif case == "missing_history":
            shuttle["frames"].pop(10)
        elif case == "history_cut":
            shuttle["cut_frames"] = [11]
        elif case == "history_player_replay":
            players["frames"][10]["scene"] = "replay"
        elif case == "recursive_history":
            shuttle["frames"][10]["shuttle"].update(
                selection_context_start_frame=5, selection_context_end_frame=11
            )
    cues["peaks"][0]["time_s"] = times[center] + 0.005
    if case == "missing_audio":
        cues["status"] = "missing"
    elif case == "duplicate_sound":
        cues["peaks"].append(cues["peaks"][0] | {"time_s": times[center] + 0.01})
    video.update(
        fps=rate,
        frame_count=80,
        duration_s=times[-1] + 1 / rate,
        source_start_s=7.5 if case == "vfr_origin" else 0,
    )
    return shuttle, players, video, cues, times


@pytest.mark.parametrize("rate", [24, 25, 30, 50, 60, 120])
def test_new_audio_interval_brackets_source_time_at_each_rate(rate):
    shuttle, players, video, cues, times = interval_scenario(rate)
    inputs = copy.deepcopy((shuttle, players, video, cues))
    result = add_audio_support([], shuttle, players, video, cues)
    assert (shuttle, players, video, cues) == inputs
    assert len(result) == 1
    candidate = result[0]
    onset = cues["peaks"][0]["time_s"]
    left = max(frame for frame, t in enumerate(times) if t <= onset - 0.12)
    right = min(frame for frame, t in enumerate(times) if t >= onset + 0.12)
    assert candidate["start_frame"] == left
    assert candidate["end_frame"] == right
    assert candidate["start_time_s"] == times[left]
    assert candidate["end_time_s"] == times[right]
    assert candidate["context_start_frame"] <= left
    assert candidate["context_end_frame"] > right
    navigation = min(range(len(times)), key=lambda i: abs(times[i] - onset))
    assert candidate["frame"] == navigation
    assert candidate["time_s"] == times[navigation]
    assert candidate["timing"] == "uncertain_interval"
    assert candidate["interval_bounds"] == "inclusive"
    assert candidate["reviewed"] is False


@pytest.mark.parametrize(
    "case,expected",
    [
        ("sparse", 1),
        ("vfr_origin", 1),
        ("duplicate_sound", 1),
        ("history_valid", 1),
        ("recursive_history", 1),
        ("edge", 0),
        ("tail", 0),
        ("cut", 0),
        ("player_cut", 0),
        ("replay_bound", 0),
        ("player_replay_bound", 0),
        ("unknown_bound", 0),
        ("excluded_bound", 0),
        ("frame_gap", 0),
        ("timestamp_gap", 0),
        ("missing_audio", 0),
        ("no_gap", 0),
        ("static_wrist", 0),
        ("history_replay", 0),
        ("missing_history", 0),
        ("bound_pose_mismatch", 0),
        ("bound_pose_duplicate", 0),
        ("history_cut", 0),
        ("history_player_replay", 0),
    ],
)
def test_new_audio_interval_preserves_available_and_excluded_context(case, expected):
    shuttle, players, video, cues, times = interval_scenario(case=case)
    result = add_audio_support([], shuttle, players, video, cues)
    assert len(result) == expected
    if expected:
        candidate = result[0]
        onset = cues["peaks"][0]["time_s"]
        assert candidate["start_time_s"] <= onset - 0.12
        assert candidate["end_time_s"] >= onset + 0.12
        assert candidate["time_s"] == times[24]
        assert candidate["context_start_frame"] <= candidate["start_frame"]
        assert candidate["context_end_frame"] > candidate["end_frame"]
        if case == "history_valid":
            assert candidate["context_start_frame"] == 10
        elif case == "recursive_history":
            assert candidate["context_start_frame"] == 5
    else:
        far = max(
            range(len(times)), key=lambda i: abs(times[i] - cues["peaks"][0]["time_s"])
        )
        visual = [
            {"id": "far", "frame": far, "time_s": times[far], "evidence": {"keep": [1]}}
        ]
        assert add_audio_support(visual, shuttle, players, video, cues) == visual


def test_missing_new_interval_endpoint_preserves_existing_tail_corroboration():
    shuttle, players, video, cues, times = interval_scenario(case="tail")
    assert add_audio_support([], shuttle, players, video, cues) == []
    visual = [{"id": "tail", "frame": 70, "time_s": times[70], "evidence": {}}]
    original = copy.deepcopy(visual)
    result = add_audio_support(visual, shuttle, players, video, cues)
    assert visual == original
    assert len(result) == 1 and result[0]["time_s"] == times[70]
    assert len(result[0]["evidence"]["audio_support"]) == 1
