import numpy as np
from badminton.contacts import propose_contacts
from badminton.shuttle import locate_shuttle


def scene(turn=True, missing=False, far=False):
    times = np.arange(25) * 0.04
    center = times[12]
    rows = []
    player_rows = []
    for i, t in enumerate(times):
        x = 300 + 200 * abs(t - center) if turn else 200 + 200 * t
        visible = not missing or not 9 <= i <= 15
        rows.append(
            {
                "frame": i,
                "time_s": float(t),
                "shuttle": {
                    "visible": visible,
                    "x": float(x) if visible else None,
                    "y": 200 if visible else None,
                    "repaired": False,
                },
            }
        )
        box = [0, 0, 20, 20] if far else [280, 180, 380, 320]
        player_rows.append(
            {
                "frame": i,
                "time_s": float(t),
                "players": [{"track_id": 7, "box": box, "keypoints": []}],
            }
        )
    return {"frames": rows}, {"frames": player_rows}, {"width": 640, "height": 360}


def test_contact_proposal_is_a_timed_unreviewed_hint():
    shuttle, players, video = scene()
    candidates = propose_contacts(shuttle, players, video)
    assert len(candidates) == 1
    assert abs(candidates[0]["frame"] - 12) <= 1
    assert candidates[0]["track_id"] == 7
    assert candidates[0]["player_id"] is None and candidates[0]["reviewed"] is False


def test_straight_flight_gaps_and_distant_players_do_not_become_contacts():
    for kwargs in ({"turn": False}, {"missing": True}, {"far": True}):
        assert propose_contacts(*scene(**kwargs)) == []


def test_missing_shuttle_and_edge_coordinates_are_distinct():
    empty = locate_shuttle(np.zeros((10, 10), np.float32), 100, 100)
    assert empty["visible"] is False and empty["x"] is None and empty["y"] is None
    heat = np.zeros((10, 10), np.float32)
    heat[0, 0] = 0.9
    edge = locate_shuttle(heat, 100, 100)
    assert edge["visible"] is True and edge["x"] == 5 and edge["y"] == 5
    assert edge["repaired"] is False
