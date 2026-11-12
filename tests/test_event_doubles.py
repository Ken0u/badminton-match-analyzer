import numpy as np
import pytest
from badminton.event_doubles import (
    DOUBLES_FEATURES,
    SLOTS,
    assign_slots,
    doubles_observations,
    slot_end,
)
from badminton.event_model import FAMILIES, PLAYER, with_motion

WIDTH, HEIGHT, FPS = 1280, 720, 30.0
# Feet of the far pair and the near pair.
SPOTS = {1: (500, 300), 2: (760, 320), 3: (450, 620), 4: (820, 650)}


def person(track, x, y):
    return {
        "track_id": track,
        "confidence": 0.9,
        "box": [x - 30, y - 150, x + 30, y],
        "keypoints": [[x, y - 75, 0.9]] * 17,
    }


def rows(count, tracks=lambda index: SPOTS):
    return [
        {
            "frame": 100 + index,
            "camera_segment_start_frame": 0,
            "calibration_valid": True,
            "players": [person(t, *spot) for t, spot in tracks(index).items()],
        }
        for index in range(count)
    ]


def test_each_pair_shares_the_two_slots_of_its_end():
    slots = assign_slots(rows(40), WIDTH, HEIGHT, FPS)
    assert sorted(slots.values()) == [0, 1, 2, 3]
    assert {slots[0, 1], slots[0, 2]} == {0, 1}
    assert {slots[0, 3], slots[0, 4]} == {2, 3}
    assert [slot_end(s) for s in range(SLOTS)] == ["far", "far", "near", "near"]


def test_a_broken_track_keeps_its_slot_and_an_extra_person_gets_none():
    def tracks(index):
        people = dict(SPOTS)
        if index >= 20:
            # Track 2 is lost and the same player returns as track 9.
            people.pop(2)
            if index >= 24:
                people[9] = (770, 325)
        if 5 <= index < 12:
            people[7] = (640, 310)  # an official walks behind the far pair
        return people

    slots = assign_slots(rows(60, tracks), WIDTH, HEIGHT, FPS)
    assert slots[0, 9] == slots[0, 2]
    assert (0, 7) not in slots
    assert len({slots[0, t] for t in (1, 2, 3, 4)}) == 4


def test_observations_fill_slots_and_motion_follows_the_shuttle():
    shuttle = [{"visible": True, "x": 600 + 4 * i, "y": 400 - 2 * i} for i in range(30)]
    values, tracks = doubles_observations(rows(30), shuttle, WIDTH, HEIGHT, FPS)
    assert values.shape == (30, SLOTS * PLAYER + 3)
    assert sorted(tracks[0]) == [1, 2, 3, 4]
    assert all(values[:, slot * PLAYER + 55].all() for slot in range(SLOTS))
    inputs = with_motion(values)
    assert inputs.shape == (30, DOUBLES_FEATURES)
    assert inputs[5, -3:] == pytest.approx([4 / WIDTH, -2 / HEIGHT, 1], abs=1e-6)


def test_network_takes_four_players_and_names_a_slot():
    torch = pytest.importorskip("torch")
    from badminton.event_network import EventModel, from_checkpoint

    model = EventModel(hidden=16, layers=1, norm="step", players=SLOTS).eval()
    out = model(torch.zeros(1, 12, DOUBLES_FEATURES))
    assert out["hitter"].shape == (1, 12, SLOTS)
    again = from_checkpoint(
        {
            "families": FAMILIES,
            "network": {"hidden": 16, "layers": 1, "norm": "step", "players": SLOTS},
        }
    )
    again.load_state_dict(model.state_dict())
    assert EventModel(hidden=16, layers=1)(torch.zeros(1, 12, 118))["hitter"].shape == (
        1,
        12,
        2,
    )
    assert np.isfinite(out["hit"].detach().numpy()).all()


def test_resample_covers_every_slot():
    from badminton.event_model import resample

    values = np.zeros((3, SLOTS * PLAYER + 3), np.float32)
    values[:, 3 * PLAYER + 55] = 1
    values[:, 3 * PLAYER + 51] = (0.0, 0.4, 0.8)
    out, _ = resample(values, [0.0, 0.04, 0.08])
    assert out[1, 3 * PLAYER + 51] == pytest.approx(1 / 3, abs=1e-5)


def test_doubles_video_is_predicted_with_the_doubles_checkpoint(monkeypatch, tmp_path):
    torch = pytest.importorskip("torch")
    from badminton import event_model
    from badminton.event_network import EventModel

    torch.manual_seed(0)
    network = {"hidden": 16, "layers": 1, "norm": "step", "players": SLOTS}
    saved = {
        "state": EventModel(**network).state_dict(),
        "threshold": 0.0,
        "families": FAMILIES,
        "network": network,
    }
    paths = {"doubles": tmp_path / "events_doubles.pt"}
    torch.save(saved, paths["doubles"])
    monkeypatch.setattr(
        event_model,
        "checkpoint_path",
        lambda mode="singles": paths.get(mode, tmp_path / "absent.pt"),
    )
    video = {"mode": "doubles", "width": WIDTH, "height": HEIGHT, "fps": FPS}
    assert event_model.available(video)
    assert not event_model.available(video | {"mode": "singles"})
    frames = [row | {"time_s": row["frame"] / FPS} for row in rows(40)]
    shuttle = [
        {
            "frame": row["frame"],
            "shuttle": {"visible": True, "x": 600 + 4 * i, "y": 400 - 2 * i},
        }
        for i, row in enumerate(frames)
    ]
    events = event_model.predict_events(video, {"frames": frames}, {"frames": shuttle})
    assert events
    for event in events:
        assert event["track_id"] in SPOTS
        far = event["track_id"] in (1, 2)
        assert event["court_end"] == ("far" if far else "near")
        assert 0 <= event["court_end_score"] <= 1 + 1e-6


def test_partner_is_the_one_whose_arm_moves_at_the_shuttle():
    from badminton.event_doubles import choose_partner

    frames = rows(20)
    for index, row in enumerate(frames):
        # Track 2 swings: its wrist (a keypoint) travels fast around frame 10.
        swing = row["players"][1]
        swing["keypoints"] = [list(k) for k in swing["keypoints"]]
        swing["keypoints"][10][0] += 12 * max(0, 4 - abs(index - 10))
    shuttle = [{"visible": True, "x": 790, "y": 240} for _ in frames]
    values, tracks = doubles_observations(frames, shuttle, WIDTH, HEIGHT, FPS)
    slot = choose_partner(values, 10, "far", WIDTH, HEIGHT)
    assert tracks[10][slot] == 2
    # A lone tracked partner is taken; an empty end gives no answer.
    values[:, slot * PLAYER : (slot + 1) * PLAYER] = 0
    assert tracks[10][choose_partner(values, 10, "far", WIDTH, HEIGHT)] == 1
    values[:, : 2 * PLAYER] = 0
    assert choose_partner(values, 10, "far", WIDTH, HEIGHT) is None
