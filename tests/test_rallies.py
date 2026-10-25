"""Behavioral boundary checks; synthetic cues are not badminton accuracy truth."""

import json
from copy import deepcopy

import pytest
from badminton.rallies import (
    context_signature,
    generate_rallies,
    propose_rallies,
    reviewed_rallies,
)
from rally_fixture import scene, surround_scene


def kinds(args):
    return {c["kind"] for c in propose_rallies(*args)["candidates"]}


@pytest.mark.parametrize("mode", ["singles", "doubles"])
def test_observed_launch_and_stop_propose_intervals_without_reading_labels(mode):
    args = scene(mode)
    before = deepcopy(args)
    run = propose_rallies(*args)
    assert {c["kind"] for c in run["candidates"]} == {"serve", "rally_end"}
    assert len(run["candidates"]) == 2
    for c in run["candidates"]:
        assert c["start_frame"] <= c["frame"] <= c["end_frame"]
        assert c["needs_review"] and c["player_id"] is None
        assert c["timing"] == "uncertain_interval"
        assert (
            run["start_frame"]
            <= c["context_start_frame"]
            <= c["start_frame"]
            <= c["end_frame"]
            < c["context_end_frame"]
            <= run["end_frame"]
        )
    serve = next(c for c in run["candidates"] if c["kind"] == "serve")
    end = next(c for c in run["candidates"] if c["kind"] == "rally_end")
    assert serve["start_frame"] <= 25 <= serve["end_frame"]
    assert end["start_frame"] <= 40 <= end["end_frame"]
    assert args == before
    args[-1]["events"] = [
        {"kind": "rally_end", "frame": 1},
        {"kind": "serve", "frame": 99},
    ]
    assert propose_rallies(*args) == run


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize(
    "terminal", [(170, 440), (830, 440), (575, 40), (575, 560), (170, 40)]
)
def test_observed_settling_beside_each_court_edge_is_an_uncertain_ending(
    mode, terminal
):
    args = surround_scene(mode, terminal)
    before = deepcopy(args)
    run = propose_rallies(*args)
    endings = [c for c in run["candidates"] if c["kind"] == "rally_end"]
    assert len(endings) == 1
    c = endings[0]
    assert c["start_frame"] <= 40 <= c["end_frame"]
    assert c["timing"] == "uncertain_interval" and c["player_id"] is None
    assert c["evidence"]["settled_region"] == "near_court_surround"
    assert c["evidence"]["line_call_verified"] is False
    assert run["recipe"]["terminal_court_margin_fraction"] == 0.12
    assert args == before


@pytest.mark.parametrize("terminal", [(10, 440), (990, 440), (575, 0), (575, 600)])
def test_beyond_the_bounded_surround_cannot_create_an_ending(terminal):
    assert "rally_end" not in kinds(surround_scene(terminal=terminal))


def test_surround_ending_preserves_variable_source_pts_and_unknown_line_call():
    times, t = [], 0
    for i in range(110):
        times.append(t)
        t += 0.02 if i % 2 else 0.06
    run = propose_rallies(*surround_scene(times=times))
    c = next(c for c in run["candidates"] if c["kind"] == "rally_end")
    assert c["time_s"] == times[c["frame"]]
    assert c["start_time_s"] <= 1.6 <= c["end_time_s"]
    assert not c["evidence"]["line_call_verified"]


@pytest.mark.parametrize(
    "failure", ["ghost", "apex", "missing", "no_people", "cut", "nonlive"]
)
def test_near_court_point_still_needs_motion_settling_and_complete_context(failure):
    args = surround_scene()
    _, players, shuttle, doc = args
    if failure == "cut":
        shuttle["cut_frames"] = [40]
    elif failure == "nonlive":
        doc["scene_ranges"] = [
            {"id": "masked", "start_frame": 35, "end_frame": 80, "scene": "replay"}
        ]
    for pose, row in zip(players["frames"], shuttle["frames"]):
        if failure == "ghost":
            row["shuttle"]["x"] = 170
        elif failure == "apex":
            row["shuttle"]["x"] = 170 + 80 * (row["time_s"] - 2) ** 2
        elif failure == "missing" and row["frame"] >= 39:
            row["shuttle"]["visible"] = False
        elif failure == "no_people":
            pose["players"] = []
    assert "rally_end" not in kinds(args)


@pytest.mark.parametrize(
    "failure",
    [
        "invisible",
        "repaired",
        "ghost",
        "no_people",
        "no_wrists",
        "invalid_court",
        "replay",
        "unknown",
        "missing_court",
    ],
)
def test_missing_or_static_evidence_does_not_invent_boundaries(failure):
    args = scene()
    _, players, shuttle, doc = args
    for p, s in zip(players["frames"], shuttle["frames"]):
        if failure == "invisible":
            s["shuttle"]["visible"] = False
        elif failure == "repaired":
            s["shuttle"]["repaired"] = True
        elif failure == "ghost":
            s["shuttle"]["x"] = 350
        elif failure == "no_people":
            p["players"] = []
        elif failure == "no_wrists":
            for person in p["players"]:
                person["keypoints"] = []
        elif failure == "invalid_court":
            p["calibration_valid"] = False
        elif failure in ("replay", "unknown"):
            p["scene"] = failure
        elif failure == "missing_court":
            doc["calibrations"] = []
    assert kinds(args) == set()


def test_quadratic_flight_apex_and_isolated_heatmap_jumps_are_not_endings():
    args = scene()
    for row in args[2]["frames"]:
        row["shuttle"]["x"] = 500 + 80 * (row["time_s"] - 2) ** 2
    assert "rally_end" not in kinds(args)
    for row in args[2]["frames"]:
        row["shuttle"]["x"] = 360 if row["frame"] in (25, 29, 33) else 350
    assert kinds(args) == set()


@pytest.mark.parametrize(
    "failure", ["cut", "gap", "missing_row", "nonlive", "expired_calibration"]
)
def test_no_boundary_evidence_crosses_context_break(failure):
    args = scene()
    _, players, shuttle, doc = args
    # Split exactly at launch and settling: neither new segment has the
    # incoming/quiet history required to infer that transition.
    for run in (players, shuttle):
        if failure == "cut":
            run["cut_frames"] = [25, 40]
        elif failure == "gap":
            for row in run["frames"]:
                row["time_s"] += (0.2 if row["frame"] >= 25 else 0) + (
                    0.2 if row["frame"] >= 40 else 0
                )
        elif failure == "missing_row":
            run["frames"] = [r for r in run["frames"] if r["frame"] not in (24, 39)]
    if failure == "nonlive":
        doc["scene_ranges"] = [
            {"id": "masked", "start_frame": 20, "end_frame": 45, "scene": "non_play"}
        ]
    elif failure == "expired_calibration":
        for row in players["frames"][20:45]:
            row["calibration_valid"] = False
    assert kinds(args) == set()


def test_source_pts_drive_boundaries_with_variable_frame_rate():
    times, t = [], 0
    for i in range(110):
        times.append(t)
        t += 0.02 if i % 2 else 0.06
    args = scene(times=times)
    run = propose_rallies(*args)
    assert kinds(args) == {"serve", "rally_end"}
    for c in run["candidates"]:
        assert c["time_s"] == times[c["frame"]]


def test_partial_pose_context_and_ambiguous_server_are_explicit():
    args = scene("doubles")
    for row in args[1]["frames"]:
        row["players"].pop()
        # Two players overlap the launch; distance is not proof of hitter.
        row["players"][2] = deepcopy(row["players"][0]) | {"track_id": 2}
    run = propose_rallies(*args)
    assert {c["kind"] for c in run["candidates"]} == {"serve"}
    c = run["candidates"][0]
    assert c["track_id"] is None
    assert c["evidence"]["partial_player_context"] is True
    assert c["evidence"]["possible_track_ids"] == [0, 2]


def test_clip_edges_and_changing_track_ids_do_not_supply_missing_context():
    args = scene()
    for run in args[1:3]:
        run["frames"] = run["frames"][25:40]
        run.update(start_frame=25, end_frame=40)
    assert kinds(args) == set()
    args = scene()
    for row in args[1]["frames"]:
        for person in row["players"]:
            person["track_id"] += row["frame"] * 10
    assert kinds(args) == set()


@pytest.mark.parametrize(
    "failure",
    [
        "hash",
        "stride",
        "time_mismatch",
        "duplicate_frame",
        "nan_time",
        "stale_camera",
        "court_changed",
    ],
)
def test_incompatible_inputs_fail_instead_of_mixing_evidence(failure):
    args = scene()
    _, players, shuttle, doc = args
    if failure == "hash":
        players["video_sha256"] = "b" * 64
    elif failure == "stride":
        players["stride"] = 2
    elif failure == "time_mismatch":
        shuttle["frames"][3]["time_s"] += 0.001
    elif failure == "duplicate_frame":
        players["frames"][2]["frame"] = 1
    elif failure == "nan_time":
        players["frames"][2]["time_s"] = float("nan")
    elif failure == "stale_camera":
        doc["camera_corrections"] = [{"frame": 20, "is_cut": True}]
    elif failure == "court_changed":
        players["calibration_signature"] = context_signature(doc, 0, 100)["court"]
        doc["calibrations"][0]["corners"][0]["x"] = 0.1
    with pytest.raises(ValueError):
        propose_rallies(*args)


def test_generated_artifact_and_review_staleness_preserve_immutable_predictions(
    tmp_path,
):
    video, players, shuttle, doc = scene()
    output = tmp_path / "run.json"
    summary = generate_rallies(video, players, shuttle, doc, "p1", "s1", output)
    raw = json.loads(output.read_text())
    assert summary["player_run_id"] == "p1" and summary["shuttle_run_id"] == "s1"
    assert "candidates" not in summary and summary["candidate_count"] == 2
    assert reviewed_rallies(raw, doc)["requires_proposal_rerun"] is False
    for edit in ("court", "scene", "camera"):
        changed = deepcopy(doc)
        if edit == "court":
            changed["calibrations"][0]["corners"][0]["x"] = 0.01
        elif edit == "scene":
            changed["scene_ranges"] = [
                {"id": "replay", "start_frame": 1, "end_frame": 15, "scene": "replay"}
            ]
        else:
            changed["camera_corrections"] = [{"frame": 5, "is_cut": True}]
        # A context edit outside the candidate interval can invalidate its cues.
        assert reviewed_rallies(raw, changed)["requires_proposal_rerun"] is True
    assert json.loads(output.read_text()) == raw
