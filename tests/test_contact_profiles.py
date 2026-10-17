"""Known synthetic motions test geometry/timing, not badminton accuracy."""

from copy import deepcopy

import pytest
from badminton.contacts import propose_contacts
from contact_profile_fixture import motion_scene


@pytest.mark.parametrize("variable_rate", [False, True])
def test_between_frame_motion_has_review_bounds_and_source_pts(variable_rate):
    shuttle, players, video, knot = motion_scene(variable_rate=variable_rate)
    before = deepcopy((shuttle, players))
    candidates = propose_contacts(shuttle, players, video)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["evidence_source"] == "subframe_trajectory_and_pose"
    assert candidate["timing"] == "uncertain_interval"
    assert candidate["start_time_s"] <= knot <= candidate["end_time_s"]
    assert (
        candidate["context_start_frame"]
        <= candidate["start_frame"]
        <= candidate["frame"]
        <= candidate["end_frame"]
        < candidate["context_end_frame"]
    )
    assert candidate["time_s"] == shuttle["frames"][candidate["frame"]]["time_s"]
    assert candidate["evidence"]["penalized_fit_gain"] >= 6
    assert candidate["evidence"]["fit_parameter_counts_including_noise"] == {
        "broken_line": 8,
        "quadratic": 7,
    }
    assert candidate["player_id"] is None and not candidate["reviewed"]
    assert (shuttle, players) == before


def test_adjacent_short_gaps_use_only_observed_samples_without_filling_points():
    shuttle, players, video, knot = motion_scene(missing=(20, 21, 25, 26))
    before = deepcopy(shuttle)
    candidates = propose_contacts(shuttle, players, video)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["evidence_source"] == "bounded_gap_trajectory_and_pose"
    assert candidate["start_time_s"] <= knot <= candidate["end_time_s"]
    assert set(candidate["evidence"]["missing_frames"]) == {20, 21, 25, 26}
    assert not set(candidate["evidence"]["observed_context_frames"]) & {20, 21, 25, 26}
    assert shuttle == before


@pytest.mark.parametrize("kind", ["apex", "straight", "stationary"])
@pytest.mark.parametrize("seed", range(6))
def test_quantized_noisy_noncontacts_with_nearby_moving_wrist_abstain(kind, seed):
    shuttle, players, video, _ = motion_scene(kind, seed)
    assert propose_contacts(shuttle, players, video) == []


@pytest.mark.parametrize(
    "failure",
    [
        "no_wrists",
        "still_wrist",
        "no_track",
        "two_samples",
        "cut",
        "player_cut",
        "player_row_cut",
        "gap",
        "scene",
        "player_scene",
        "jump",
    ],
)
def test_missing_pose_or_broken_context_cannot_make_an_extra_contact(failure):
    shuttle, players, video, _ = motion_scene(missing=(20, 21, 25, 26))
    if failure == "cut":
        shuttle["cut_frames"] = [20]
    elif failure == "player_cut":
        players["cut_frames"] = [20]
    elif failure == "player_row_cut":
        players["frames"][20]["scene_cut"] = True
    for i, row in enumerate(players["frames"]):
        person = row["players"][0]
        if failure == "no_wrists":
            person["keypoints"] = []
        elif failure == "still_wrist":
            person["keypoints"][9][:2] = [320, 160]
        elif failure == "no_track":
            person["track_id"] = None
        elif failure == "two_samples" and i not in (19, 22):
            person["keypoints"] = []
        elif failure == "gap" and i >= 20:
            row["time_s"] += 0.2
            shuttle["frames"][i]["time_s"] += 0.2
        elif failure == "scene":
            shuttle["frames"][i]["scene"] = "replay"
        elif failure == "player_scene":
            row["scene"] = "unknown"
        elif (
            failure == "jump" and i >= 22 and shuttle["frames"][i]["shuttle"]["visible"]
        ):
            shuttle["frames"][i]["shuttle"]["x"] += 2000
    assert propose_contacts(shuttle, players, video) == []


def test_overlapping_players_leave_hitter_unconfirmed_and_keep_possible_tracks():
    shuttle, players, video, _ = motion_scene()
    for row in players["frames"]:
        row["players"].append(deepcopy(row["players"][0]) | {"track_id": 2})
    candidate = propose_contacts(shuttle, players, video)[0]
    assert candidate["track_id"] is None and candidate["player_id"] is None
    assert candidate["evidence"]["possible_track_ids"] == [1, 2]
    assert candidate["evidence"]["hitter_hint_status"] == "ambiguous_proximity"
