from copy import deepcopy

import pytest
from badminton.identity import (
    apply_assignments,
    resolve_contact_player,
    validate_assignments,
)
from pydantic import BaseModel


def assignment(track=7, player="A", start=100, end=110, run="run-1"):
    return {
        "run_id": run,
        "track_id": track,
        "player_id": player,
        "start_frame": start,
        "end_frame": end,
    }


def player_run():
    return {
        "video_id": "sample",
        "stage": "players",
        "frames": [
            {
                "frame": frame,
                "time_s": frame * 0.04,
                "players": [
                    {
                        "track_id": track,
                        "player_id": "stale identity",
                        "box": [1, 2, 3, 4],
                        "keypoints": [[5, 6, 0.9]],
                    }
                    for track in (7, 8, None)
                ],
            }
            for frame in (99, 100, 109, 110, 119, 120)
        ],
    }


def test_only_reviewed_run_track_and_half_open_frames_resolve():
    mappings = [assignment(), assignment(track=8, player="B", run="run-2")]
    assert resolve_contact_player(100, 7, mappings, "run-1") == "A"
    assert resolve_contact_player(109, 7, mappings, "run-1") == "A"
    for frame, track, run in (
        (99, 7, "run-1"),
        (110, 7, "run-1"),
        (100, 8, "run-1"),
        (100, None, "run-1"),
        (100, 7, "run-2"),
        (100, 7, "unknown-run"),
    ):
        assert resolve_contact_player(frame, track, mappings, run) is None
    assert resolve_contact_player(100, 8, mappings, "run-2") == "B"


def test_tracker_reuse_and_end_changes_require_explicit_adjacent_ranges():
    mappings = [
        assignment(start=100, end=110),
        assignment(player="B", start=110, end=120),
        assignment(track=8, player="B", start=100, end=110),
        assignment(track=8, player="A", start=110, end=120),
    ]
    assert resolve_contact_player(109, 7, mappings, "run-1") == "A"
    assert resolve_contact_player(110, 7, mappings, "run-1") == "B"
    assert resolve_contact_player(110, 8, mappings, "run-1") == "A"
    assert resolve_contact_player(120, 7, mappings, "run-1") is None


def test_apply_returns_independent_copy_and_clears_unreviewed_identities():
    original = player_run()
    before = deepcopy(original)
    mappings = [assignment(), assignment(player="B", start=110, end=120)]
    reviewed = apply_assignments(original, mappings, "run-1")
    assert original == before
    assert [row["players"][0]["player_id"] for row in reviewed["frames"]] == [
        None,
        "A",
        "A",
        "B",
        "B",
        None,
    ]
    assert all(
        player["player_id"] is None
        for row in reviewed["frames"]
        for player in row["players"][1:]
    )
    reviewed["frames"][0]["players"][0]["box"][0] = 999
    reviewed["frames"][0]["players"][0]["keypoints"][0][0] = 999
    assert original == before
    cleared = apply_assignments(reviewed, [], "run-1")
    assert all(
        player["player_id"] is None
        for row in cleared["frames"]
        for player in row["players"]
    )


def test_doubles_allows_four_distinct_players_without_guessing_missing_tracks():
    mappings = [assignment(track=i, player=p) for i, p in enumerate("ABCD", 1)]
    assert [
        resolve_contact_player(100, i, mappings, "run-1") for i in range(1, 5)
    ] == list("ABCD")
    assert resolve_contact_player(100, 5, mappings, "run-1") is None
    assert resolve_contact_player(100, None, mappings, "run-1") is None


@pytest.mark.parametrize(
    "mappings, message",
    [
        ([assignment(), assignment(player="B", start=109)], "one tracker"),
        ([assignment(), assignment(track=8, start=109)], "overlapping tracks"),
        ([assignment(), assignment()], "one tracker"),
    ],
)
def test_ambiguous_mapping_is_rejected_instead_of_selecting_first(mappings, message):
    with pytest.raises(ValueError, match=message):
        validate_assignments(mappings)
    with pytest.raises(ValueError, match=message):
        resolve_contact_player(100, 7, mappings, "run-1")
    with pytest.raises(ValueError, match=message):
        apply_assignments(player_run(), mappings, "run-1")


def test_overlapping_source_ranges_in_independent_runs_are_valid():
    mappings = [assignment(), assignment(track=99, run="run-2")]
    assert validate_assignments(mappings) == mappings


def test_validation_can_check_roster_and_video_bounds():
    with pytest.raises(ValueError, match="Unknown player"):
        validate_assignments([assignment(player="unknown")], player_ids={"A", "B"})
    with pytest.raises(ValueError, match="exceeds the source video"):
        validate_assignments([assignment()], frame_count=109)
    assert validate_assignments([assignment()], player_ids={"A", "B"}, frame_count=110)


@pytest.mark.parametrize(
    "change",
    [
        {"start_frame": -1},
        {"start_frame": 110},
        {"end_frame": 100},
        {"start_frame": 100.0},
        {"end_frame": True},
        {"track_id": None},
        {"track_id": -1},
        {"track_id": True},
        {"run_id": ""},
        {"player_id": ""},
    ],
)
def test_invalid_assignment_fields_are_rejected(change):
    mapping = assignment() | change
    with pytest.raises(ValueError):
        validate_assignments([mapping])


def test_pydantic_records_are_supported_without_mutation():
    class AssignmentModel(BaseModel):
        run_id: str
        track_id: int
        player_id: str
        start_frame: int
        end_frame: int

    mapping = AssignmentModel(**assignment())
    assert resolve_contact_player(100, 7, [mapping], "run-1") == "A"
    assert mapping.model_dump() == assignment()
