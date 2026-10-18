import copy

import pytest
from badminton.track_consensus import corroborate_tracks
from test_actor_linking import VIDEO, run


def evidence():
    rows = run(0, 80)["frames"]
    for row in rows:
        row["motion_players"] = copy.deepcopy(row["players"])
        for p in row["motion_players"]:
            p["track_id"] += 10
        if 20 <= row["frame"] < 25:
            row["players"].pop(0)
        elif row["frame"] >= 25:
            row["players"][0]["track_id"] = 3
    return rows


def test_corroboration_retains_all_baseline_inputs_and_does_not_invent_gap_boxes():
    rows = evidence()
    original = copy.deepcopy(rows)
    mapping, proof = corroborate_tracks(VIDEO, rows)
    assert mapping == {1: 1, 2: 2, 3: 1}
    assert rows == original and proof["reviewed"] is False
    assert len(proof["links"]) == 1
    assert proof["links"][0]["left_support_frames"] == list(range(20))
    assert proof["links"][0]["right_support_frames"] == list(range(25, 80))
    assert proof["links"][0]["motion_track"] == 11
    assert not proof["cross_camera_identity"]
    assert corroborate_tracks(VIDEO, rows) == (mapping, proof)


@pytest.mark.parametrize(
    "problem",
    [
        "weak_support",
        "short_support",
        "same_boxes",
        "long_gap",
        "timestamp_gap",
        "replay_gap",
        "uncalibrated_gap",
        "overlapping_duplicates",
        "excluded_copresence",
        "brief_fork",
        "baseline_conflicting_partners",
    ],
)
def test_missing_or_conflicting_motion_evidence_never_replaces_baseline_ids(problem):
    rows = evidence()
    for row in rows:
        f = row["frame"]
        if problem == "weak_support":
            row["motion_players"][0]["confidence"] = 0.1
        elif problem == "short_support" and f < 17:
            row["motion_players"].pop(0)
        elif problem == "same_boxes":
            row["motion_players"][1]["box"] = row["motion_players"][0]["box"][:]
        elif problem == "long_gap" and 25 <= f < 40:
            row["players"] = [p for p in row["players"] if p["track_id"] != 3]
        elif problem == "timestamp_gap" and f >= 20:
            row["time_s"] += 0.3
        elif problem == "replay_gap" and f == 22:
            row["scene"] = "replay"
        elif problem == "uncalibrated_gap" and f == 22:
            row["calibration_valid"] = False
        elif problem == "overlapping_duplicates" and f == 25:
            row["players"].append(
                {"track_id": 1, "box": [100, 80, 140, 160], "confidence": 0.9}
            )
        elif problem == "excluded_copresence" and f == 75:
            row["scene"] = "replay"
            row["players"].append(
                {"track_id": 1, "box": [100, 80, 140, 160], "confidence": 0.9}
            )
        elif problem == "brief_fork" and f == 22:
            # One bad branch is evidence of a switch, even though 99% of
            # the corroborating track otherwise agrees with the desired link.
            row["motion_players"][0]["box"] = row["players"][0]["box"][:]
            row["motion_players"].pop(1)
        elif problem == "baseline_conflicting_partners" and 10 <= f < 15:
            row["motion_players"][0]["track_id"] = 13
    mapping, proof = corroborate_tracks(VIDEO, rows)
    assert mapping[1] != mapping[3]
    assert not proof["links"]


@pytest.mark.parametrize(
    "problem",
    ["nan_time", "missing_frame", "duplicate_id", "camera_reuse", "source_frame_range"],
)
def test_damaged_source_or_identity_inputs_fail_before_linking(problem):
    rows = evidence()
    if problem == "nan_time":
        rows[1]["time_s"] = float("nan")
    elif problem == "missing_frame":
        rows.pop(3)
    elif problem == "duplicate_id":
        rows[0]["players"][1]["track_id"] = 1
    elif problem == "camera_reuse":
        rows[-1]["camera_segment_start_frame"] = 79
    elif problem == "source_frame_range":
        rows[-1]["frame"] = 100
    with pytest.raises(ValueError):
        corroborate_tracks(VIDEO, rows)


def test_camera_cut_stays_separate_even_if_two_trackers_agree_on_screen_geometry():
    rows = evidence()
    for row in rows:
        if row["frame"] >= 25:
            row["camera_segment_start_frame"] = 25
            for p in row["players"]:
                p["track_id"] += 100
            for p in row["motion_players"]:
                p["track_id"] += 100
    mapping, proof = corroborate_tracks(VIDEO, rows)
    assert mapping[1] != mapping[103] and not proof["links"]


def test_stride_and_cancellation_do_not_silently_create_partially_checked_links():
    mapping, proof = corroborate_tracks(VIDEO, evidence(), stride=2)
    assert not mapping and proof["status"] == "requires_stride_one"

    def cancel(_):
        raise RuntimeError("Stop requested")

    with pytest.raises(RuntimeError, match="Stop requested"):
        corroborate_tracks(VIDEO, evidence(), progress=cancel)


def test_disjoint_tracklet_chain_is_transitive_but_keeps_copresent_partner_separate():
    rows = evidence()
    for row in rows:
        if 45 <= row["frame"] < 50:
            row["players"] = [p for p in row["players"] if p["track_id"] != 3]
        elif row["frame"] >= 50:
            row["players"][0]["track_id"] = 4
    mapping, proof = corroborate_tracks(VIDEO, rows)
    assert mapping[1] == mapping[3] == mapping[4] != mapping[2]
    assert len(proof["links"]) == 2
