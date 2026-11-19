"""Controlled acquisition-clock comparison; no source footage or fitted labels."""

import numpy as np
import pytest
from badminton import rally_outcomes as R
from badminton import shuttle_flight as F
from test_shuttle_flight import ASPECT, broadcast_camera, homography_of


def case(fps, phase, vx, vy, noise=0, *, vt=None, variable=False, seed=431):
    cam = broadcast_camera()
    h = homography_of(cam)
    t = np.arange(23) / fps
    if variable:
        t += np.sin(np.arange(len(t))) * 0.09 / fps
    impact = t[6] + phase * (t[7] - t[6])
    state = np.array([2.2, 10.5, 2.9, vx, vy, -8.0])
    post = t >= impact
    image = np.empty((len(t), 2))
    image[post] = cam.project(
        F.positions_at(state, t[post] - impact, vt=vt, step=1 / 2400)[0]
    )[0]
    image[~post] = cam.project(state[:3] + (t[~post] - impact)[:, None] * [-5, 8, -2])[
        0
    ]
    image += np.random.default_rng(seed).normal(0, noise, image.shape)
    track = list(map(tuple, image))
    return (
        (t, track, 6, len(t), ASPECT, lambda _: h, "near", [[(2.2, 10.5)]] * len(t)),
        impact,
        np.linalg.norm(state[3:]) * 3.6,
    )


@pytest.mark.parametrize("fps,phase", [(30, 0.55), (50, 0.25)])
def test_launch_uses_between_frame_contact(fps, phase, monkeypatch):
    args, impact, truth = case(fps, phase, 24, -74, 0.0003)
    fit = R.shot_flight(*args)
    assert abs(fit["time_origin_s"] - impact) < 0.003
    with monkeypatch.context() as m:
        m.setattr(R, "_impact_clock", lambda *args: None)
        rounded = R.shot_flight(*args)
    assert abs(fit["initial_speed_kmh"] - truth) < 0.08 * truth
    assert abs(fit["initial_speed_kmh"] - truth) < abs(
        rounded["initial_speed_kmh"] - truth
    )


def test_reported_speed_uses_the_resolved_clock():
    args, _, truth = case(30, 0.85, 40, -48, 0.0003)
    fit = R.shot_flight(*args)
    assert fit["launch_supported"]
    assert abs(fit["early_speed_kmh"] - truth) < 0.08 * truth
    assert fit["speed_settled_kmh"] < fit["early_speed_kmh"]


def test_missing_incoming_track_does_not_claim_racket_speed():
    args, _, _ = case(30, 0.55, 24, -74)
    args[1][:6] = [None] * 6
    fit = R.shot_flight(*args)
    assert fit is not None and fit["launch_supported"] is False
    assert fit["early_speed_kmh"] is None


def test_clock_respects_view_and_native_time_gaps():
    args, _, _ = case(30, 0.55, 24, -74)
    assert not R.shot_flight(*args, segments=[0] * 6 + [1] * 17)["launch_supported"]
    t = args[0].copy()
    t[7:] += 0.2
    assert R._impact_clock(t, args[1], 6, ASPECT, 0, len(t)) is None


def comparison():
    """Standalone paired stress check: report all cases, including abstentions."""
    from unittest.mock import patch

    from badminton.match_analysis import flight_from_summary

    errors = [[], []]
    shown = [[], []]
    matched = [[], []]
    for fps in (25, 60):
        for phase in (0.15, 0.45, 0.75):
            for n, (vx, vy) in enumerate(((18, -35), (33, -66), (18, -90))):
                args, _, truth = case(
                    fps,
                    phase,
                    vx,
                    vy,
                    0.0007,
                    vt=(6.5, 6.9, 6.7)[n],
                    variable=True,
                    seed=100 + n + fps,
                )
                old_early = {}
                original = F.fit_flight

                def capture(*a, **kw):
                    result = original(*a, **kw)
                    old_early.update(result or {})
                    return result

                with (
                    patch.object(R, "_impact_clock", return_value=None),
                    patch.object(F, "fit_flight", capture),
                ):
                    old = R.shot_flight(*args)
                if old:
                    old.update(
                        {
                            k: old_early[k]
                            for k in ("early_speed_kmh", "launch_supported")
                        }
                    )
                available = []
                for idx, result in enumerate((old, R.shot_flight(*args))):
                    shot = flight_from_summary(R.flight_summary(result))
                    if shot:
                        errors[idx].append(shot.initial_speed_kmh - truth)
                    measurement = (
                        shot.early_speed_kmh - truth
                        if shot and shot.quality == "good" and shot.launch_supported
                        else None
                    )
                    available.append(measurement)
                    if measurement is not None:
                        shown[idx].append(measurement)
                if None not in available:
                    for idx, value in enumerate(available):
                        matched[idx].append(value)
    for label, pair in [
        ("raw fit", errors),
        ("reportable launch", shown),
        ("both reportable", matched),
    ]:
        for mode, row in zip(("old", "new"), pair, strict=True):
            print(
                label,
                mode,
                len(row),
                "/18",
                "MAE",
                round(np.mean(np.abs(row)), 2) if row else None,
                "bias",
                round(np.mean(row), 2) if row else None,
            )


if __name__ == "__main__":
    comparison()
