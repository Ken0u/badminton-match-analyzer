import hashlib

import numpy as np
import pytest
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
        row["calibration_valid"] = index < 10 or index >= 20
    scenes = event_model.view_scenes({"frames": frames}, cuts={20})
    assert [(s["start_frame"], s["end_frame"], s["scene"]) for s in scenes] == [
        (0, 10, "live"),
        (10, 20, "non_play"),
        (20, 30, "live"),
    ]
    # A fade into a replay is no cut, but the court is lost: the view splits.
    for index, row in enumerate(frames):
        row["camera_segment_start_frame"] = 0
        row["calibration_valid"] = index >= 18
    faded = event_model.view_scenes({"frames": frames})
    assert [(s["start_frame"], s["end_frame"], s["scene"]) for s in faded] == [
        (0, 18, "non_play"),
        (18, 30, "live"),
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


def test_last_suggestion_is_kept_when_the_shuttle_rises_a_little():
    # A soft shot into the net: the shuttle travels under SETTLE_TRAVEL but
    # climbs up the picture, which a shuttle lying on the floor cannot do.
    lifted = {f: (600 + (f - 100), 400 - min(f - 100, 10) * 2) for f in range(98, 121)}
    events = [_suggestion(100, "near")]
    assert event_model.drop_implausible(events, _track(lifted), 25, 720) == events


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


try:
    import torch as _torch

    class _FixedSingles(_torch.nn.Module):
        """One contact mid-view, always a drop (index 5 of FAMILIES)."""

        def forward(self, x):
            steps = x.shape[1]
            hit = _torch.full((1, steps, 1), -10.0)
            hit[0, steps // 2, 0] = 10.0
            family = _torch.zeros(1, steps, 11)
            family[:, :, 5] = 3.0
            other = _torch.zeros(1, steps, 2)
            return hit, other, family, other, other

except ImportError:  # pragma: no cover - torch is an optional extra
    _FixedSingles = None


def _scripted_singles(path):
    torch = pytest.importorskip("torch")
    torch.jit.script(_FixedSingles()).save(str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _upgrade(monkeypatch, path, sha):
    monkeypatch.setattr(event_model, "upgrade_path", lambda mode="singles": path)
    monkeypatch.setattr(
        event_model,
        "upgrade_entry",
        lambda mode: (
            {
                "sha256": sha,
                "threshold": 0.7,
                "family_order": list(event_model.FAMILIES),
            }
            if mode == "singles"
            else None
        ),
    )


def test_without_an_upgrade_the_plain_checkpoints_keep_their_names():
    for mode in ("singles", "doubles"):
        assert event_model.upgrade(mode) is None
        assert event_model.method({"mode": mode}) == event_model.BASE_METHODS[mode]
        assert event_model.model_files(mode) == {}


def test_singles_upgrade_is_loaded_with_torchscript(monkeypatch, tmp_path):
    pytest.importorskip("torch")
    path = tmp_path / "events_singles_ensemble_v1.ts"
    sha = _scripted_singles(path)
    _upgrade(monkeypatch, path, sha)
    video = {"mode": "singles", "width": 1280, "height": 720, "fps": 30.0}
    # Self-contained: usable without events.pt, which it replaces.
    assert event_model.available(video)
    assert event_model.method(video) == event_model.METHODS["singles"]
    assert event_model.checkpoint_sha256("singles") == sha
    assert event_model.model_files("singles") == {path.name: sha}
    frames = [
        {
            "frame": i,
            "time_s": i / 30,
            "calibration_valid": True,
            "camera_segment_start_frame": 0,
            "players": [person(1, 300), person(2, 650)],
        }
        for i in range(40)
    ]
    shuttle = [
        {"frame": i, "shuttle": {"visible": True, "x": 600 + 5 * i, "y": 400.0}}
        for i in range(40)
    ]
    events = event_model.predict_events(video, {"frames": frames}, {"frames": shuttle})
    assert [(e["frame"], e["family"]) for e in events] == [(20, "drop")]
    assert sum(events[0]["family_scores"].values()) == pytest.approx(1)


def test_an_upgrade_that_differs_from_the_manifest_is_refused(monkeypatch, tmp_path):
    pytest.importorskip("torch")
    path = tmp_path / "events_singles_ensemble_v1.ts"
    _scripted_singles(path)
    _upgrade(monkeypatch, path, "0" * 64)
    with pytest.raises(ValueError, match="does not match the model manifest"):
        event_model.available({"mode": "singles"})


def test_manifest_registers_the_installed_upgrades():
    for mode, name in event_model.UPGRADES.items():
        entry = event_model.upgrade_entry(mode)
        assert entry["name"] == name and len(entry["sha256"]) == 64
        path = event_model.WEIGHTS / name
        if path.is_file():
            assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
    singles = event_model.upgrade_entry("singles")
    assert tuple(singles["family_order"]) == event_model.FAMILIES
    assert singles["threshold"] == 0.7
    assert event_model.upgrade_entry("doubles")["blend"] == 0.35
