"""Physical checks must not turn missing evidence into a fault or erase the fit."""

import pytest
from badminton import match_analysis as ma
from badminton import rally_outcomes as ro
from badminton import shuttle_flight as sf


@pytest.mark.parametrize("side", [-1, 1])
@pytest.mark.parametrize(
    ("height", "status"), [(1.20, "below_net"), (1.53, "near_tape"), (1.95, "clear")]
)
def test_interpolated_crossing(side, height, status):
    state = [3, sf.NET_Y - side * 0.18, height, 0, side * 12, 0]
    got = sf.continuing_net_check(state, 0.08)
    assert got["net_check"] == status
    assert abs(got["net_clearance_m"] - (height - sf.NET_HEIGHT)) < 0.005
    assert (
        sf.continuing_net_check(state, 0.001) is None
    )  # integration step overshoots horizon
    assert sf.continuing_net_check([6.2, *state[1:]], 0.08) is None


@pytest.mark.parametrize(
    ("segment", "receiver", "assessed"),
    [(1, "far", True), (2, "far", False), (1, None, False), (1, "near", False)],
)
def test_quality_only_for_continuing_exchange(monkeypatch, segment, receiver, assessed):
    fit = {
        "start": [3, 6.88, 1.2],
        "velocity": [0, -12, 0],
        "initial_speed_kmh": 80.0,
        "apex_m": 1.2,
        "rms": 0.001,
        "points": 10,
        "inliers": 10,
        "observed_s": 0.08,
        "start_index": 0,
    }
    monkeypatch.setattr(ro, "shot_flight", lambda *args, **kw: fit)
    line = {
        "times": [0, 0.04, 0.08],
        "contacts": [
            {"frame": 0, "court_end": "near"},
            {"frame": 2, "court_end": receiver},
        ],
        "segments": [1, 1, segment],
        "aspect": 1,
        "shuttle": [None] * 3,
    }
    first, last = ro.shot_flights(line, {"shots": [0, 1]}, 3, last=fit)
    shot = ma.flight_from_summary(first)
    terminal = ma.flight_from_summary(last)
    assert shot.quality == ("poor_fit" if assessed else "good")
    assert shot.net_check == ("below_net" if assessed else None)
    assert terminal.net_check is None and terminal.quality == "good"
    assert shot.apex_m == terminal.apex_m == 1.2
    for verdict in ["clear", "near_tape"]:
        assert ma.flight_from_summary(dict(first, net_check=verdict)).quality == "good"


def test_receiver_prior_cannot_turn_a_bound_launch_into_a_measurement():
    shot = ma.flight_from_summary(
        {
            "initial_speed_kmh": 408,
            "launch_bound": True,
            "settled_supported": True,
            "speed_settled_kmh": 118,
            "points": 9,
            "rms": 0.002,
            "inliers": 9,
        }
    )
    assert shot.quality == "speed_bound" and shot.settled_supported
    assert shot.initial_speed_kmh == 408 and shot.speed_settled_kmh == 118
