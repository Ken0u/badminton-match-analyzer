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
    assert strokes[0]["serve_type"] is None

    serve = event | {
        "frame": 35,
        "kind": "serve",
        "family": "serve",
        "family_scores": {"serve": 0.8},
        "serve_type": "short",
        "serve_type_score": 0.7,
    }
    contacts = event_model.contact_candidates([serve])
    target = {"id": "stroke-c", "frame": 35, "contact_candidate_id": "contact-35"}
    stroke = event_model.stroke_candidates([target], {"candidates": contacts})[0]
    assert (stroke["kind"], stroke["family"], stroke["serve_type"]) == (
        "serve",
        None,
        "short",
    )
    assert stroke["reason"].startswith("learned short serve")


def test_views_without_a_court_are_suggested_as_non_play():
    frames = rows(30, [person(1, 600)])
    for index, row in enumerate(frames):
        # Second camera view starts at frame 10 and never shows the court.
        row["camera_segment_start_frame"] = 0 if index < 10 else 10
        row["calibration_valid"] = index < 9 or index >= 20
    scenes = event_model.view_scenes({"frames": frames}, cuts={20})
    assert [(s["start_frame"], s["end_frame"], s["scene"]) for s in scenes] == [
        (0, 10, "live"),
        (10, 20, "non_play"),
        (20, 30, "live"),
    ]
    # With no court information at all, nothing is judged or skipped.
    for row in frames:
        row["calibration_valid"] = False
    unknown = event_model.view_scenes({"frames": frames})
    assert {s["scene"] for s in unknown} == {"unknown"}


def _suggestion(frame, court_end, score=0.9):
    return {
        "frame": frame,
        "time_s": frame / 25,
        "court_end": court_end,
        "score": score,
    }


def _track(points):
    return [
        {"frame": frame, "shuttle": {"visible": True, "x": x, "y": y}}
        for frame, (x, y) in points.items()
    ]


def test_last_suggestion_is_dropped_when_the_shuttle_has_landed():
    flying = {f: (100 + 12 * f, 300) for f in range(0, 31)}
    resting = {f: (600 + (f - 100) * 0.5, 400) for f in range(98, 121)}
    events = [_suggestion(10, "far"), _suggestion(100, "near")]
    kept = event_model.drop_implausible(events, _track(flying | resting), 25, 720)
    assert [e["frame"] for e in kept] == [10]


def test_last_suggestion_is_kept_when_the_shuttle_leaves_or_is_unseen():
    leaving = {f: (600 + (f - 100) * 9, 400) for f in range(98, 121)}
    events = [_suggestion(100, "near")]
    assert event_model.drop_implausible(events, _track(leaving), 25, 720) == events
    assert (
        event_model.drop_implausible(events, _track({100: (600, 400)}), 25, 720)
        == events
    )


def test_mid_rally_suggestion_is_not_judged_by_shuttle_travel():
    resting = dict.fromkeys(range(98, 121), (600, 400))
    events = [_suggestion(100, "near"), _suggestion(130, "far")]
    kept = event_model.drop_implausible(events, _track(resting), 25, 720)
    assert [e["frame"] for e in kept] == [100, 130]


def test_one_court_end_cannot_hit_twice_in_quick_succession():
    events = [
        _suggestion(100, "near", 0.8),
        _suggestion(108, "near", 0.95),
        _suggestion(125, "far"),
        _suggestion(150, "near"),
    ]
    kept = event_model.drop_implausible(events, [], 25, 720)
    assert [e["frame"] for e in kept] == [108, 125, 150]
