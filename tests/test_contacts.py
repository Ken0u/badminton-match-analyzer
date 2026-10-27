import copy
import hashlib

import numpy as np
import pytest
from badminton.contacts import propose_contacts
from badminton.shuttle import locate_shuttle


def scene(turn=True, missing=False, far=False):
    times = np.arange(25) * 0.04
    center = times[12]
    rows = []
    player_rows = []
    for i, t in enumerate(times):
        x = 300 + 200 * abs(t - center) if turn else 200 + 200 * t
        visible = not missing or not 9 <= i <= 15
        rows.append(
            {
                "frame": i,
                "time_s": float(t),
                "shuttle": {
                    "visible": visible,
                    "x": float(x) if visible else None,
                    "y": 200 if visible else None,
                    "repaired": False,
                },
            }
        )
        box = [0, 0, 20, 20] if far else [280, 180, 380, 320]
        player_rows.append(
            {
                "frame": i,
                "time_s": float(t),
                "players": [{"track_id": 7, "box": box, "keypoints": []}],
            }
        )
    return {"frames": rows}, {"frames": player_rows}, {"width": 640, "height": 360}


def native_scene():
    shuttle, players, video = scene()
    video.update(
        id="native-test",
        sha256=hashlib.sha256(b"generated source").hexdigest(),
        frame_count=25,
        duration_s=1,
    )
    for run, stage in ((shuttle, "shuttle"), (players, "players")):
        run.update(
            video_id=video["id"],
            stage=stage,
            start_frame=0,
            end_frame=25,
            video_sha256=video["sha256"],
        )
    return shuttle, players, video, [i * 0.04 for i in range(25)]


def test_native_contact_validation_preserves_candidates_and_original_inputs():
    from badminton.contacts import validate_contact_inputs

    shuttle, players, video, times = native_scene()
    before = copy.deepcopy((shuttle, players, video, times))
    assert propose_contacts(shuttle, players, video, times) == propose_contacts(
        shuttle, players, video
    )
    assert validate_contact_inputs(video, shuttle, players, times) == {
        "source_timestamps_validated": True,
        "input_source_hash_status": {"shuttle": "matched", "players": "matched"},
    }
    assert (shuttle, players, video, times) == before


@pytest.mark.parametrize("stage", [0, 1])
@pytest.mark.parametrize(
    "mutation",
    [
        "clock",
        "hash",
        "null_hash",
        "hash_syntax",
        "duplicate",
        "reverse",
        "negative",
        "outside",
        "fractional",
        "boolean",
        "missing_time",
        "nan",
        "infinite",
        "bool_time",
        "wrong_video",
        "wrong_stage",
        "range",
    ],
)
def test_native_contact_validation_rejects_original_bad_perception(stage, mutation):
    inputs = native_scene()
    run = inputs[stage]
    if mutation == "clock":
        for row in run["frames"]:
            row["time_s"] += 0.4
    elif mutation in ("hash", "null_hash", "hash_syntax"):
        run["video_sha256"] = {
            "hash": "0" * 64,
            "null_hash": None,
            "hash_syntax": "broken",
        }[mutation]
    elif mutation == "duplicate":
        run["frames"].insert(0, copy.deepcopy(run["frames"][0]))
    elif mutation == "reverse":
        run["frames"].reverse()
    elif mutation in ("negative", "outside", "fractional", "boolean"):
        run["frames"][0]["frame"] = {
            "negative": -1,
            "outside": 25,
            "fractional": 0.5,
            "boolean": False,
        }[mutation]
    elif mutation == "missing_time":
        del run["frames"][0]["time_s"]
    elif mutation in ("nan", "infinite", "bool_time"):
        run["frames"][0]["time_s"] = {
            "nan": float("nan"),
            "infinite": float("inf"),
            "bool_time": False,
        }[mutation]
    elif mutation == "wrong_video":
        run["video_id"] = "other"
    elif mutation == "wrong_stage":
        run["stage"] = "contacts"
    else:
        run["start_frame"] = 1
    # Even evidence marked non-play must be checked before any filtering.
    run["frames"][0]["scene"] = "non_play"
    with pytest.raises(ValueError):
        propose_contacts(*inputs)


@pytest.mark.parametrize(
    "mutation",
    ["short", "duplicate", "reverse", "negative", "nan", "bool", "string", "none"],
)
def test_contact_generation_requires_a_complete_valid_native_clock(mutation):
    shuttle, players, video, times = native_scene()
    if mutation == "short":
        times.pop()
    elif mutation == "duplicate":
        times[1] = times[0]
    elif mutation == "reverse":
        times.reverse()
    elif mutation in ("negative", "nan", "bool"):
        times[0] = {"negative": -1, "nan": float("nan"), "bool": False}[mutation]
    elif mutation == "string":
        times = "invalid"
    else:
        # A validator call cannot mark a missing clock as verified.
        from badminton.contacts import validate_contact_inputs

        with pytest.raises(ValueError):
            validate_contact_inputs(video, shuttle, players, None)
        return
    with pytest.raises(ValueError):
        propose_contacts(shuttle, players, video, times)


def test_contact_clock_tolerance_is_absolute_and_legacy_hashes_are_unavailable():
    from badminton.contacts import validate_contact_inputs

    shuttle, players, video, times = native_scene()
    times = [t + 100000 for t in times]
    for run in (shuttle, players):
        del run["video_sha256"]
        for row in run["frames"]:
            row["time_s"] = times[row["frame"]] + 0.00001
    metadata = validate_contact_inputs(video, shuttle, players, times)
    assert metadata["input_source_hash_status"] == {
        "shuttle": "unavailable",
        "players": "unavailable",
    }
    shuttle["frames"][0]["time_s"] += 0.001
    with pytest.raises(ValueError, match="timestamp"):
        validate_contact_inputs(video, shuttle, players, times)


def test_valid_sparse_players_and_absent_optional_players_remain_supported():
    from badminton.contacts import validate_contact_inputs

    shuttle, players, video, times = native_scene()
    players["frames"] = players["frames"][3:22:3]
    players.update(start_frame=3, end_frame=22)
    assert propose_contacts(shuttle, players, video, times) == propose_contacts(
        shuttle, players, video
    )
    assert propose_contacts(shuttle, None, video, times) == propose_contacts(
        shuttle, None, video
    )
    assert (
        validate_contact_inputs(video, shuttle, None, times)[
            "input_source_hash_status"
        ]["players"]
        == "not_requested"
    )


def test_contact_proposal_is_a_timed_unreviewed_hint():
    shuttle, players, video = scene()
    candidates = propose_contacts(shuttle, players, video)
    assert len(candidates) == 1
    assert abs(candidates[0]["frame"] - 12) <= 1
    assert candidates[0]["track_id"] == 7
    assert candidates[0]["player_id"] is None and candidates[0]["reviewed"] is False
    assert candidates[0]["start_frame"] == candidates[0]["end_frame"]
    assert candidates[0]["evidence_source"] == "observed_trajectory"
    assert (
        candidates[0]["evidence"]["piecewise_rmse_px"]
        < candidates[0]["evidence"]["quadratic_rmse_px"]
    )


def test_straight_flight_gaps_and_distant_players_do_not_become_contacts():
    for kwargs in ({"turn": False}, {"missing": True}, {"far": True}):
        assert propose_contacts(*scene(**kwargs)) == []


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), None, "missing"])
def test_invalid_wrist_cannot_bypass_distant_player_gate(bad):
    shuttle, players, video = scene(far=True)
    for row in players["frames"]:
        keypoints = [[0, 0, 0] for _ in range(17)]
        keypoints[9] = [bad, 200, 0.9]
        row["players"][0]["keypoints"] = keypoints
    assert propose_contacts(shuttle, players, video) == []


def test_invalid_first_wrist_does_not_hide_a_valid_nearby_other_arm():
    shuttle, players, video = scene(far=True)
    for row in players["frames"]:
        keypoints = [[0, 0, 0] for _ in range(17)]
        keypoints[9] = [float("nan"), 200, 0.9]
        keypoints[10] = [300, 200, 0.9]
        row["players"][0]["keypoints"] = keypoints
    candidate = propose_contacts(shuttle, players, video)[0]
    assert candidate["frame"] == 12 and candidate["score"] == 0.8


def test_infinite_confidence_cannot_supply_near_wrist_evidence():
    shuttle, players, video = scene(far=True)
    for row in players["frames"]:
        keypoints = [[0, 0, 0] for _ in range(17)]
        keypoints[9] = [300, 200, float("inf")]
        row["players"][0]["keypoints"] = keypoints
    assert propose_contacts(shuttle, players, video) == []


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), None, "missing"])
def test_invalid_gap_pose_stays_missing_evidence(bad):
    shuttle, players, video = gap_scene()
    for row in players["frames"]:
        row["players"][0]["keypoints"][9][2] = bad
    assert propose_contacts(shuttle, players, video) == []


def distant_wrists_scene():
    shuttle, players, video = scene()
    for row in players["frames"]:
        keypoints = [[0, 0, 0] for _ in range(17)]
        keypoints[9] = [290, 50, 0.9]
        keypoints[10] = [320, 45, 0.9]
        row["players"][0]["keypoints"] = keypoints
    return shuttle, players, video


def test_box_proximity_does_not_override_repeated_distant_wrists():
    inputs = distant_wrists_scene()
    original = copy.deepcopy(inputs)
    assert propose_contacts(*inputs) == []
    assert inputs == original


@pytest.mark.parametrize(
    "failure",
    ["one_arm", "low_confidence", "nonfinite", "no_track", "one_sided", "ambiguous"],
)
def test_incomplete_wrist_evidence_preserves_observed_contact_fallback(failure):
    shuttle, players, video = distant_wrists_scene()
    for row in players["frames"]:
        player = row["players"][0]
        if failure == "one_arm":
            player["keypoints"][10][2] = 0
        elif failure == "low_confidence":
            player["keypoints"][9][2] = 0.29
        elif failure == "nonfinite":
            player["keypoints"][9][0] = float("nan")
        elif failure == "no_track":
            player["track_id"] = None
        elif failure == "one_sided" and row["frame"] > 12:
            player["keypoints"][9][2] = 0
        elif failure == "ambiguous":
            row["players"].append(copy.deepcopy(player))
    candidates = propose_contacts(shuttle, players, video)
    assert [c["frame"] for c in candidates] == [12]


def test_nearby_wrist_keeps_contact_even_without_wrist_motion():
    shuttle, players, video = distant_wrists_scene()
    players["frames"][11]["players"][0]["keypoints"][9] = [300, 200, 0.9]
    assert [c["frame"] for c in propose_contacts(shuttle, players, video)] == [12]


def test_sparse_pose_does_not_prove_wrist_distance_through_a_gap():
    shuttle, players, video = distant_wrists_scene()
    for row in players["frames"]:
        if row["frame"] not in (9, 12, 15):
            for wrist in (9, 10):
                row["players"][0]["keypoints"][wrist][2] = 0
    assert [c["frame"] for c in propose_contacts(shuttle, players, video)] == [12]


def test_wrist_guard_does_not_read_pose_outside_trajectory_context():
    shuttle, players, video = distant_wrists_scene()
    for row in players["frames"][9:16]:
        row["players"][0]["keypoints"][9][2] = 0
    candidate = propose_contacts(shuttle, players, video)[0]
    assert candidate["frame"] == 12
    assert candidate["context_start_frame"] == 9
    assert candidate["context_end_frame"] == 16  # Evidence context ends exclusively.


def test_wrist_guard_reconsiders_other_possible_hitters():
    shuttle, players, video = distant_wrists_scene()
    for row in players["frames"]:
        other = copy.deepcopy(row["players"][0])
        other["track_id"] = 8
        other["keypoints"][9] = [300, 200, 0.9]
        row["players"].append(other)
    candidate = propose_contacts(shuttle, players, video)[0]
    assert candidate["frame"] == 12 and candidate["track_id"] == 8


@pytest.mark.parametrize("scale", [0.5, 2])
def test_wrist_guard_uses_actual_image_dimensions(scale):
    shuttle, players, video = distant_wrists_scene()
    for row in shuttle["frames"]:
        row["shuttle"]["x"] *= scale
        row["shuttle"]["y"] *= scale
    for row in players["frames"]:
        player = row["players"][0]
        player["box"] = [v * scale for v in player["box"]]
        for keypoint in player["keypoints"]:
            keypoint[0] *= scale
            keypoint[1] *= scale
    video = {k: v * scale for k, v in video.items()}
    assert propose_contacts(shuttle, players, video) == []


def test_close_player_body_scale_prevents_overly_short_reach_limit():
    shuttle, players, video = distant_wrists_scene()
    for row in players["frames"]:
        row["players"][0]["box"] = [150, 0, 450, 350]
    assert [c["frame"] for c in propose_contacts(shuttle, players, video)] == [12]


def test_missing_shuttle_and_edge_coordinates_are_distinct():
    empty = locate_shuttle(np.zeros((10, 10), np.float32), 100, 100)
    assert empty["visible"] is False and empty["x"] is None and empty["y"] is None
    heat = np.zeros((10, 10), np.float32)
    heat[0, 0] = 0.9
    edge = locate_shuttle(heat, 100, 100)
    assert edge["visible"] is True and edge["x"] == 5 and edge["y"] == 5
    assert edge["repaired"] is False


def gap_scene(missing=(11, 12, 13), wrist_motion=True):
    shuttle, players, video = scene()
    for index, row in enumerate(shuttle["frames"]):
        row["shuttle"]["x"] = 300 + 400 * abs(row["time_s"] - 0.48)
        if index in missing:
            row["shuttle"].update(visible=False, x=None, y=None)
    for index, row in enumerate(players["frames"]):
        keypoints = [[0, 0, 0] for _ in range(17)]
        wrist_x = 300 + (index - 12) * 3 if wrist_motion else 300
        keypoints[9] = [wrist_x, 205, 0.9]
        row["players"][0]["keypoints"] = keypoints
    return shuttle, players, video


def test_short_gap_reversal_with_wrist_evidence_proposes_uncertain_interval():
    shuttle, players, video = gap_scene()
    original = copy.deepcopy(shuttle)
    candidates = propose_contacts(shuttle, players, video)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["evidence_source"] == "short_gap_trajectory_and_pose"
    assert candidate["timing"] == "uncertain_interval"
    assert candidate["start_frame"] == 10 and candidate["end_frame"] == 14
    assert candidate["start_time_s"] == pytest.approx(0.4)
    assert candidate["end_time_s"] == pytest.approx(0.56)
    assert candidate["interval_bounds"] == "inclusive"
    assert candidate["frame"] == 12  # Navigation midpoint is not a measured hit.
    assert candidate["evidence"]["missing_frames"] == [11, 12, 13]
    assert candidate["evidence"]["pose"]["pose_samples"] == 5
    assert candidate["evidence"]["pose"]["median_wrist_speed_px_s"] == 75
    assert candidate["track_id"] == 7
    assert candidate["player_id"] is None and candidate["reviewed"] is False
    assert shuttle == original  # Missing coordinates stay null; no repaired trajectory.


def test_smooth_flight_apex_is_rejected_even_near_a_player_and_through_a_gap():
    for missing in ((), (11, 12, 13)):
        shuttle, players, video = gap_scene(missing=missing)
        for row in shuttle["frames"]:
            time = row["time_s"] - 0.48
            if row["shuttle"]["visible"]:
                row["shuttle"].update(x=300 + 100 * time, y=200 + 1200 * time**2)
        assert propose_contacts(shuttle, players, video) == []


def test_subframe_junction_uncertainty_widens_the_gap_review_bounds():
    shuttle, players, video = gap_scene()
    # The turn happens between two visible samples just before the missing span.
    # A line fit cannot place that change exactly at a source timestamp.
    for row in shuttle["frames"]:
        if row["shuttle"]["visible"]:
            row["shuttle"]["x"] = 300 + 1000 * abs(row["time_s"] - 0.385)
    candidate = propose_contacts(shuttle, players, video)[0]
    assert candidate["start_frame"] == 9 and candidate["end_frame"] == 14
    assert candidate["timing"] == "uncertain_interval"


def test_gap_needs_nearby_confident_moving_wrist_not_just_player_box():
    for failure in (
        "no_pose",
        "low_confidence",
        "distant",
        "static",
        "no_players",
        "no_track",
    ):
        shuttle, players, video = gap_scene(wrist_motion=failure != "static")
        for row in players["frames"]:
            if failure == "no_pose":
                row["players"][0]["keypoints"] = []
            elif failure == "low_confidence":
                row["players"][0]["keypoints"][9][2] = 0.2
            elif failure == "distant":
                row["players"][0]["keypoints"][9][0] += 200
            elif failure == "no_track":
                row["players"][0]["track_id"] = None
        assert (
            propose_contacts(
                shuttle, None if failure == "no_players" else players, video
            )
            == []
        )


def test_gap_rejects_long_missing_span_timing_discontinuity_cut_and_spatial_jump():
    for failure in (
        "long_gap",
        "timestamp_gap",
        "cut",
        "row_cut",
        "replay",
        "jump",
        "missing_row",
    ):
        shuttle, players, video = gap_scene(
            missing=tuple(range(9, 16)) if failure == "long_gap" else (11, 12, 13)
        )
        if failure == "timestamp_gap":
            for row in shuttle["frames"][12:]:
                row["time_s"] += 0.2
        elif failure == "cut":
            shuttle["cut_frames"] = [12]
        elif failure == "row_cut":
            shuttle["frames"][12]["scene_cut"] = True
        elif failure == "replay":
            shuttle["frames"][12]["scene"] = "replay"
        elif failure == "jump":
            for row in shuttle["frames"][14:]:
                row["shuttle"]["x"] += 2000
        elif failure == "missing_row":
            shuttle["frames"].pop(12)
        assert propose_contacts(shuttle, players, video) == []


def test_visible_contacts_are_rejected_across_a_marked_camera_cut():
    shuttle, players, video = scene()
    shuttle["cut_frames"] = [12]
    assert propose_contacts(shuttle, players, video) == []


def test_contacts_honor_cuts_detected_only_in_the_player_run():
    shuttle, players, video = scene()
    players["cut_frames"] = [12]
    assert propose_contacts(shuttle, players, video) == []


def test_suppression_does_not_cross_missing_observations():
    shuttle, players, video = scene()
    for index, row in enumerate(shuttle["frames"]):
        time = index / 120
        row["time_s"] = time
        players["frames"][index]["time_s"] = time
        x = 300 + 1000 * (abs(time - 8 / 120) - abs(time - 17 / 120) + time)
        row["shuttle"].update(x=x, y=200)
        players["frames"][index]["players"][0]["box"] = [150, 180, 600, 320]
    shuttle["frames"][12]["shuttle"].update(visible=False, x=None, y=None)
    candidates = propose_contacts(shuttle, players, video)
    assert [candidate["frame"] for candidate in candidates] == [8, 17]
