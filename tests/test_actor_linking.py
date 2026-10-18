import copy

import pytest
from badminton.actor_linking import link_player_runs

VIDEO = {
    "id": "video",
    "sha256": "a" * 64,
    "frame_count": 100,
    "duration_s": 4,
    "width": 640,
    "height": 360,
}


def run(first, last, tracks=(1, 2), *, camera=0, boxes=None):
    boxes = boxes or [[100, 80, 140, 160], [300, 180, 350, 280]]
    return {
        "stage": "players",
        "video_id": VIDEO["id"],
        "video_sha256": VIDEO["sha256"],
        "start_frame": first,
        "end_frame": last,
        "stride": 1,
        "frames": [
            {
                "frame": frame,
                "time_s": frame / 25,
                "camera_segment_start_frame": camera,
                "calibration_valid": True,
                "players": [
                    {"track_id": track, "confidence": 0.9, "box": box[:]}
                    for track, box in zip(tracks, boxes)
                ],
            }
            for frame in range(first, last)
        ],
    }


def track(result, identifier, number):
    return next(
        r
        for r in result["tracks"]
        if r["run_id"] == identifier and r["track_id"] == number
    )


def test_links_observed_people_when_tracker_numbers_and_order_change():
    left, right = run(0, 60), run(40, 100, (8, 7))
    # List order carries no identity evidence.
    for row in right["frames"]:
        row["players"].reverse()
    original = copy.deepcopy((left, right))
    result = link_player_runs(VIDEO, [("a", left), ("b", right)])
    assert result["actor_count"] == result["linked_actor_count"] == 2
    assert result["accepted_link_count"] == 2
    assert track(result, "a", 1)["actor_id"] == track(result, "b", 8)["actor_id"]
    assert track(result, "a", 2)["actor_id"] == track(result, "b", 7)["actor_id"]
    assert track(result, "a", 1)["actor_id"] != track(result, "a", 2)["actor_id"]
    assert result["links"][0]["support_frames"] == list(range(40, 60))
    assert (left, right) == original and result["reviewed"] is False


def test_transitive_links_keep_three_windows_consistent_and_deterministic():
    inputs = [
        ("a", run(0, 45)),
        ("b", run(30, 75, (8, 7))),
        ("c", run(60, 100, (5, 6))),
    ]
    result = link_player_runs(VIDEO, inputs)
    assert result == link_player_runs(VIDEO, inputs)
    assert result["linked_actor_count"] == 2
    assert (
        len(
            {track(result, r, n)["actor_id"] for r, n in (("a", 1), ("b", 8), ("c", 5))}
        )
        == 1
    )


def test_actor_ranges_do_not_fill_unobserved_or_excluded_frames():
    left, right = run(0, 60), run(40, 100, (8, 7))
    for source in (left, right):
        for row in source["frames"]:
            if 45 <= row["frame"] < 50:
                row["calibration_valid"] = False
    result = link_player_runs(VIDEO, [("a", left), ("b", right)])
    assert result["accepted_link_count"] == 2
    assert track(result, "a", 1)["observation_ranges"] == [[0, 45], [50, 60]]
    assert track(result, "b", 8)["observation_ranges"] == [[40, 45], [50, 100]]


def test_cuts_do_not_reuse_identical_screen_positions_as_person_identity():
    result = link_player_runs(
        VIDEO, [("a", run(0, 40)), ("b", run(50, 100, (8, 7), camera=50))]
    )
    assert result["accepted_link_count"] == result["linked_actor_count"] == 0
    assert result["actor_count"] == 4 and not result["cross_camera_identity"]
    # Both runs also observe the actual edit inside their shared frames.
    # Identical box geometry on either side must produce separate identities.
    left, right = run(0, 70), run(30, 100, (8, 7))
    for source in (left, right):
        for row in source["frames"]:
            if row["frame"] >= 50:
                row["camera_segment_start_frame"] = 50
                for person in row["players"]:
                    person["track_id"] += 100
    result = link_player_runs(VIDEO, [("a", left), ("b", right)])
    assert result["actor_count"] == result["accepted_link_count"] == 4
    assert track(result, "a", 1)["actor_id"] == track(result, "b", 8)["actor_id"]
    assert track(result, "a", 101)["actor_id"] == track(result, "b", 108)["actor_id"]
    assert track(result, "a", 1)["actor_id"] != track(result, "a", 101)["actor_id"]


def test_same_source_overlap_disagreement_fails_instead_of_inventing_a_link():
    bad = run(40, 100, (8, 7))
    for row in bad["frames"]:
        row["camera_segment_start_frame"] = 40
    with pytest.raises(ValueError, match="PTS or camera"):
        link_player_runs(VIDEO, [("a", run(0, 60)), ("b", bad)])
    bad = run(40, 100, (8, 7))
    bad["frames"][0]["time_s"] += 0.001
    with pytest.raises(ValueError, match="PTS or camera"):
        link_player_runs(VIDEO, [("a", run(0, 60)), ("b", bad)])


@pytest.mark.parametrize(
    "mode",
    [
        "uncalibrated",
        "replay",
        "low_confidence",
        "nonfinite_box",
        "insufficient_frames",
    ],
)
def test_missing_or_ambiguous_support_stays_unlinked(mode):
    left, right = run(0, 60), run(40, 100, (8, 7))
    for row in right["frames"]:
        if mode == "uncalibrated":
            row["calibration_valid"] = False
        elif mode == "replay":
            row["scene"] = "replay"
        elif mode == "low_confidence":
            for p in row["players"]:
                p["confidence"] = 0.1
        elif mode == "nonfinite_box":
            for p in row["players"]:
                p["box"][0] = float("nan")
        elif mode == "insufficient_frames" and row["frame"] >= 44:
            row["players"] = []
    result = link_player_runs(VIDEO, [("a", left), ("b", right)])
    assert result["accepted_link_count"] == 0


def test_overlapping_doubles_partners_with_equal_boxes_do_not_force_a_match():
    boxes = [[100, 80, 140, 160]] * 2
    result = link_player_runs(
        VIDEO,
        [("a", run(0, 60, boxes=boxes)), ("b", run(40, 100, (8, 7), boxes=boxes))],
    )
    assert result["accepted_link_count"] == 0


def test_tracker_switch_in_overlap_fails_temporal_agreement_requirement():
    left, right = run(0, 60), run(40, 100, (8, 7))
    for row in right["frames"]:
        if 50 <= row["frame"] < 60:
            row["players"][0]["box"], row["players"][1]["box"] = (
                row["players"][1]["box"],
                row["players"][0]["box"],
            )
    result = link_player_runs(VIDEO, [("a", left), ("b", right)])
    assert result["accepted_link_count"] == 0


def test_conflicting_partner_fork_quarantines_all_links_of_the_ambiguous_track():
    left, right = run(0, 60, (1,)), run(30, 100, (8, 7))
    # A single tracker alternates between two different, co-present tracks.
    # The counterpart disappears in the ambiguous overlap, but both reappear
    # together outside it: simple strongest-edge union would merge them.
    for row in right["frames"]:
        if 30 <= row["frame"] < 45:
            row["players"] = [row["players"][0]]
        elif 45 <= row["frame"] < 60:
            row["players"] = [row["players"][1]]
            row["players"][0]["box"] = [100, 80, 140, 160]
    result = link_player_runs(VIDEO, [("a", left), ("b", right)])
    assert result["ambiguous_track_count"] == 1
    assert result["accepted_link_count"] == 0
    assert len(result["rejected_links"]) == 2
    assert track(result, "a", 1)["conflicting_overlap"]


@pytest.mark.parametrize(
    "problem",
    ["hash", "stride", "missing_frame", "duplicate_track", "camera_reuse", "bad_time"],
)
def test_input_contract_rejects_incompatible_or_damaged_runs(problem):
    raw = run(0, 60)
    if problem == "hash":
        raw["video_sha256"] = "b" * 64
    elif problem == "stride":
        raw["stride"] = 2
    elif problem == "missing_frame":
        raw["frames"].pop()
    elif problem == "duplicate_track":
        raw["frames"][0]["players"][1]["track_id"] = 1
    elif problem == "camera_reuse":
        raw["frames"][-1]["camera_segment_start_frame"] = 59
    elif problem == "bad_time":
        raw["frames"][1]["time_s"] = 0
    with pytest.raises(ValueError):
        link_player_runs(VIDEO, [("a", raw)])


def test_processing_source_order_and_run_ids_must_be_unambiguous():
    with pytest.raises(ValueError):
        link_player_runs(VIDEO, [])
    with pytest.raises(ValueError):
        link_player_runs(VIDEO, [("a", run(0, 40)), ("a", run(30, 60))])
    with pytest.raises(ValueError):
        link_player_runs(VIDEO, [("b", run(30, 60)), ("a", run(0, 40))])
