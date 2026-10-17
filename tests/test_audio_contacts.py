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
