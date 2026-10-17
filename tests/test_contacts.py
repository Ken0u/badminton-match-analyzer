import copy

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
