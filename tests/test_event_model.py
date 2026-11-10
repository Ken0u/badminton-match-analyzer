import numpy as np
from badminton import event_model
from badminton.event_model import FEATURES, PLAYER


def person(track, foot_y, confidence=0.9):
    return {
        "track_id": track,
        "confidence": confidence,
        "box": [100.0, foot_y - 200, 200.0, foot_y],
        "keypoints": [[150.0, foot_y - 100, 0.8]] * 17,
    }


def rows(count, players):
    return [
        {
            "frame": i,
            "time_s": i / 25,
            "players": players,
            "camera_segment_start_frame": 0,
        }
        for i in range(count)
    ]


def test_court_slots_order_by_feet_and_place_a_lone_person_by_half():
    far, near = event_model.court_slots([person(1, 600), person(2, 250)], 720)
    assert (far["track_id"], near["track_id"]) == (2, 1)
    assert event_model.court_slots([person(3, 650)], 720) == (None, person(3, 650))
    assert event_model.court_slots([person(4, 200)], 720)[1] is None
    assert event_model.court_slots([], 720) == (None, None)


def test_clip_inputs_mark_missing_observations_and_bounded_shuttle_motion():
    balls = [
        {"visible": True, "x": 128.0, "y": 72.0},
        {"visible": False, "x": None, "y": None},
        {"visible": True, "x": 384.0, "y": 216.0},
        {"visible": False, "x": None, "y": None},
        {"visible": False, "x": None, "y": None},
        {"visible": False, "x": None, "y": None},
        {"visible": False, "x": None, "y": None},
        {"visible": True, "x": 640.0, "y": 360.0},
    ]
    inputs = event_model.clip_inputs(rows(8, [person(1, 600)]), balls, 1280, 720)
    assert inputs.shape == (8, FEATURES)
    assert inputs[0, 55] == 0 and inputs[0, PLAYER + 55] == 1
    tail = inputs[:, 2 * PLAYER :]
    assert tail[1].tolist() == [0] * 6
    # Two steps apart: velocity is the per-step change; five apart: none.
    np.testing.assert_allclose(tail[2], [0.3, 0.3, 1, 0.1, 0.1, 1], atol=1e-6)
    np.testing.assert_allclose(tail[7], [0.5, 0.5, 1, 0, 0, 0], atol=1e-6)


def test_resample_interpolates_only_between_two_observations():
    values = np.zeros((3, 2 * PLAYER + 3), np.float32)
    values[0, 2 * PLAYER :] = (0.0, 0.0, 1)
    values[1, 2 * PLAYER :] = (0.5, 0.5, 1)
    out, nearest = event_model.resample(values, [0.0, 0.04, 0.08])
    assert len(out) == 3 and nearest.tolist() == [0, 1, 2]
    np.testing.assert_allclose(out[1, 2 * PLAYER :], [5 / 12, 5 / 12, 1], atol=1e-5)
    # The last source frame has no shuttle, so nothing is blended into it.
    assert out[2, 2 * PLAYER :].tolist() == [0, 0, 0]


def test_candidates_carry_the_learned_stroke_to_recognition_targets():
    event = {
        "frame": 40,
        "time_s": 1.6,
        "score": 0.91,
        "court_end": "near",
        "court_end_score": 0.99,
        "track_id": 7,
        "kind": "shot",
        "family": "smash",
        "family_score": 0.8,
        "family_scores": {"smash": 0.8, "drop": 0.15, "clear": 0.05},
        "side": "forehand",
        "side_score": 0.9,
        "view_start_frame": 30,
        "view_end_frame": 50,
    }
    contacts = event_model.contact_candidates([event])
    assert contacts[0]["id"] == "contact-40" and contacts[0]["track_id"] == 7
    assert (contacts[0]["context_start_frame"], contacts[0]["context_end_frame"]) == (
        30,
        50,
    )
    targets = [
        {"id": "stroke-a", "frame": 40, "contact_candidate_id": "contact-40"},
        {"id": "stroke-b", "frame": 90, "contact_candidate_id": None},
    ]
    strokes = event_model.stroke_candidates(targets, {"candidates": contacts})
    assert [s["id"] for s in strokes] == ["stroke-a"]
    assert strokes[0]["status"] == "predicted" and strokes[0]["family"] == "smash"
    assert strokes[0]["side"] == "forehand"
    assert strokes[0]["time_s"] == 1.6
    assert strokes[0]["hitter_hint"] == {
        "court_end": "near",
        "track_id": 7,
        "player_id": None,
    }
    assert strokes[0]["top_classes"][0] == {
        "kind": "shot",
        "family": "smash",
        "score": 0.8,
    }
