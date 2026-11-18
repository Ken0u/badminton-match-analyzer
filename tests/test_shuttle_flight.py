import math

import numpy as np
from badminton import rally_outcomes as R
from badminton import shuttle_flight as F
from badminton.match_analysis import COURT_LENGTH_M, COURT_WIDTH_M, court_homography

ASPECT = 16 / 9
CORNERS = [(0, 0, 0), (COURT_WIDTH_M, 0, 0), (COURT_WIDTH_M, COURT_LENGTH_M, 0)]
CORNERS.append((0, COURT_LENGTH_M, 0))


def broadcast_camera(centre=(3.05, 22.4, 7.5), target=(3.05, 6.0, 0.0), focal=1.6):
    """A camera behind the near baseline looking down the court."""
    centre, target = np.asarray(centre, float), np.asarray(target, float)
    forward = (target - centre) / np.linalg.norm(target - centre)
    right = np.array([1.0, 0, 0]) - forward * forward[0]
    right /= np.linalg.norm(right)
    # The court frame (x right, y towards the camera, z up) is left-handed.
    down = np.cross(right, forward)
    rotation = np.stack([right, down, forward])
    return F.Camera(focal, rotation, -rotation @ centre, ASPECT)


def homography_of(camera):
    image, _ = camera.project(np.array(CORNERS, float))
    return court_homography([tuple(p) for p in image])


def observe(camera, state, times, noise=0.0, seed=0):
    positions = F.positions_at(np.array([state], float), times)[0]
    keep = positions[:, 2] > 0
    image, _ = camera.project(positions[keep])
    rng = np.random.default_rng(seed)
    return np.asarray(times)[keep], image + rng.normal(0, noise, image.shape)


def test_camera_is_recovered_from_the_floor_homography():
    for centre, target in (
        ((3.05, 22.4, 7.5), (3.05, 6.0, 0.0)),
        ((4.5, 30.0, 9.0), (2.5, 6.5, 0.0)),  # off centre, panned
    ):
        truth = broadcast_camera(centre, target, focal=2.4)
        camera = F.camera_from_homography(homography_of(truth), ASPECT)
        assert camera is not None
        assert abs(camera.focal - 2.4) < 1e-3
        assert np.allclose(camera.centre, centre, atol=0.02)
        assert camera.reprojection < 1e-5
        # Any 3D point projects where the true camera puts it.
        point = np.array([[1.0, 4.0, 2.5]])
        assert np.allclose(camera.project(point)[0], truth.project(point)[0], atol=1e-5)
        assert np.allclose(camera.at_height(*truth.project(point)[0][0], 2.5), point[0])


def test_degenerate_homographies_give_no_camera():
    assert F.camera_from_homography([[1, 0, 0], [0, 1, 0], [0, 0, 0]], ASPECT) is None
    assert F.camera_from_homography(np.full((3, 3), np.nan), ASPECT) is None
    # A plain scaling (a camera looking straight down at infinity) has no
    # finite focal length.
    assert F.camera_from_homography(np.diag([6.1, 13.4, 1.0]), ASPECT) is None


def test_drag_model_reaches_terminal_velocity():
    times, _, velocity = F.integrate([[0, 0, 50, 0, 0, 0]], 3.0, step=1 / 240)
    vt, g = F.TERMINAL_VELOCITY, F.GRAVITY
    expected = -vt * np.tanh(g * times / vt)
    assert np.allclose(velocity[:, 0, 2], expected, atol=1e-4)
    assert abs(velocity[-1, 0, 2] + vt) < 0.01
    # A fast shot slows quickly: half its speed within a tenth of a second.
    _, _, velocity = F.integrate([[0, 0, 2, 0, -80, 0]], 0.1)
    assert np.linalg.norm(velocity[-1, 0]) < 40
    # The coarse step agrees with a fine one to millimetres.
    state = [[3, 11.5, 2.8, 0, -90, -20]]
    at = np.arange(1, 30) / 30
    assert (
        np.abs(F.positions_at(state, at) - F.positions_at(state, at, step=1e-3)).max()
        < 3e-3
    )


def test_flight_fit_round_trip_gives_landing_and_speed():
    truth = broadcast_camera()
    camera = F.camera_from_homography(homography_of(truth), ASPECT)
    state = [3.0, 11.5, 2.6, 1.0, -22.0, 14.0]  # a clear from the near end
    down = F.touchdown(np.array([state]))[0]
    at, image = observe(truth, state, np.arange(0, 60) / 30, noise=0.002)
    fit = F.fit_flight(camera, at, image, hitter=(3.2, 11.8), towards=-1)
    assert fit is not None and not fit["touchdown"]["net"]
    assert math.dist(fit["touchdown"]["point"][:2], down["point"][:2]) < 0.2
    assert abs(fit["initial_speed_m_s"] - math.hypot(1, 22, 14)) < 2.5
    assert fit["sigma_m"] is not None and fit["sigma_m"] < 0.5
    assert fit["rms"] < 0.006 and fit["inliers"] >= len(at) - 2
    assert 75 < fit["landing_angle_deg"] < 85
    assert abs(fit["landing_speed_m_s"] - down_speed(down)) < 0.5


def down_speed(down):
    return float(np.linalg.norm(down["velocity"]))


def test_flight_fit_bridges_a_gap_and_ignores_false_detections():
    truth = broadcast_camera()
    camera = F.camera_from_homography(homography_of(truth), ASPECT)
    state = [2.0, 2.0, 2.4, 0.5, 18.0, 9.0]  # from the far end
    down = F.touchdown(np.array([state]))[0]
    at, image = observe(truth, state, np.arange(0, 60) / 30, noise=0.001)
    keep = (at < 0.3) | (at > 0.9)  # hidden for 0.6 s mid-flight
    at, image = at[keep], image[keep].copy()
    image[5] = (0.9, 0.9)  # a player's hand
    image[6] = (0.1, 0.8)
    fit = F.fit_flight(camera, at, image, hitter=(2.0, 2.0), towards=1)
    assert math.dist(fit["touchdown"]["point"][:2], down["point"][:2]) < 0.25
    assert fit["inliers"] == len(at) - 2


def test_a_low_flight_stops_at_the_net_and_short_tracks_give_nothing():
    truth = broadcast_camera()
    camera = F.camera_from_homography(homography_of(truth), ASPECT)
    state = [3.0, 9.0, 1.2, 0.0, -9.0, 1.0]  # a net shot that falls short
    at, image = observe(truth, state, np.arange(0, 9) / 30, noise=0.0005)
    fit = F.fit_flight(camera, at, image, hitter=(3.0, 9.3), towards=-1)
    assert fit["touchdown"]["net"]
    assert abs(fit["touchdown"]["point"][1] - F.NET_Y) < 1e-6
    assert F.fit_flight(camera, at[:4], image[:4]) is None


def test_shot_flight_uses_the_turn_at_the_racket_and_falls_back():
    truth = broadcast_camera()
    matrix = homography_of(truth)
    state = [3.0, 11.5, 2.6, 1.0, -22.0, 14.0]
    fps = 30
    times = [i / fps for i in range(80)]
    contact = 10
    # Incoming shuttle before the contact (moving down the picture), the
    # shot after it; the detector puts the contact two frames early.
    after = F.positions_at(np.array([state]), np.arange(0, 70) / fps)[0]
    before = np.array([[3.0, 11.5 - 0.6 * k, 2.6 + 0.3 * k] for k in range(10, 0, -1)])
    image = np.vstack([truth.project(before)[0], truth.project(after)[0]])
    shuttle = [tuple(p) if p is not None else None for p in image]
    for i, p in enumerate(F.positions_at(np.array([state]), np.arange(0, 70) / fps)[0]):
        if p[2] <= 0:
            shuttle[contact + i] = None
    assert R.contact_turn(times, shuttle, contact - 2, ASPECT) == contact
    people = [[] for _ in times]
    people[contact - 2] = [(1, (3.2, 11.8), (0.45, 0.5, 0.55, 0.9), None)]
    fit = R.shot_flight(
        times,
        shuttle,
        contact - 2,
        len(times),
        ASPECT,
        lambda i: matrix,
        "near",
        people,
    )
    down = F.touchdown(np.array([state]))[0]
    assert fit["start_index"] == contact
    assert fit["hitter"] == [3.2, 11.8]
    assert math.dist(fit["landing"], down["point"][:2]) < 0.2
    # No camera view, or nothing to fit: no flight.
    assert (
        R.shot_flight(times, shuttle, contact, len(times), ASPECT, lambda i: None)
        is None
    )
    empty = [None] * len(times)
    assert (
        R.shot_flight(times, empty, contact, len(times), ASPECT, lambda i: matrix)
        is None
    )


def test_the_image_landing_is_lifted_to_the_shuttle_centre():
    truth = broadcast_camera()
    matrix = homography_of(truth)
    # The shuttle's centre lies LIFT_M above the floor at (2.0, 3.0).
    image, _ = truth.project(np.array([[2.0, 3.0, R.LIFT_M]]))
    plain = R.project(matrix, *image[0])
    landing = {"index": 5, "image": tuple(image[0]), "kind": "rest", "court": plain}
    placed = R.placed_landing(landing, None, lambda i: matrix, ASPECT)
    assert placed["placement"] == "lifted" and placed["flight"] is None
    assert placed["court_image"] == plain
    assert math.dist(placed["court"], (2.0, 3.0)) < 1e-3
    assert plain[1] < 3.0 - 0.1  # the plain projection lies beyond it
    # A track that ended in the air is not lifted; a sure flight places it.
    ended = dict(landing, kind="track_end")
    fit = {"landing": [1.0, 1.5], "sigma_m": 0.1, "initial_speed_kmh": 90.0}
    fit |= {"start": [3, 11, 2], "rms": 0.003, "points": 20, "inliers": 20}
    fit |= {"observed_s": 0.8}
    placed = R.placed_landing(ended, fit, lambda i: matrix, ASPECT)
    assert placed["placement"] == "flight" and placed["court"] == (1.0, 1.5)
    unsure = R.placed_landing(ended, fit | {"sigma_m": 2.0}, lambda i: matrix, ASPECT)
    assert unsure["placement"] == "image" and unsure["court"] == plain
    assert unsure["flight"]["initial_speed_kmh"] == 90.0


def test_flight_features_extend_the_outcome_features():
    times = [i / 30 for i in range(40)]
    shuttle = [(0.5, 0.3 + 0.01 * i) for i in range(40)]
    landing = {"index": 30, "image": (0.5, 0.6), "kind": "rest", "court": (3.0, 2.0)}
    flight = {"landing": [3.0, 2.1], "sigma_m": 0.2, "rms": 0.004, "net": False}
    flight |= {"initial_speed_kmh": 150.0, "landing_speed_m_s": 6.5}
    flight |= {"landing_angle_deg": 80.0, "apex_m": 4.0, "extrapolated_s": 0.05}
    players = [[] for _ in times]
    args = (times, shuttle, players, 0, landing, "near", "singles", ASPECT, "clear")
    plain = R.outcome_features(*args)
    assert len(plain) == len(R.FEATURES)
    without = R.outcome_features(*args, names=R.FEATURES_FLIGHT)
    assert without[: len(R.FEATURES)] == plain and not any(without[len(R.FEATURES) :])
    args = (times, shuttle, players, 0, dict(landing, flight=flight), "near")
    values = dict(
        zip(
            R.FEATURES_FLIGHT,
            R.outcome_features(*args, "singles", ASPECT, "clear", R.FEATURES_FLIGHT),
            strict=True,
        )
    )
    assert values["flight_found"] == 1 and values["flight_in_court"] == 1
    assert abs(values["flight_depth_m"] - 4.6) < 1e-9
    assert values["flight_initial_speed"] == 1.5 and values["flight_sigma_m"] == 0.2
    n = len(R.FEATURES_FLIGHT)
    document = {
        "features": list(R.FEATURES_FLIGHT),
        "classes": list(R.CLASSES),
        "mean": [0.0] * n,
        "scale": [1.0] * n,
        "layers": [[np.zeros((n, 3)).tolist(), [1.0, 0.0, 0.0]]],
    }
    assert R.OutcomeModel(document).features == R.FEATURES_FLIGHT


def test_analyse_places_the_landing_and_can_fit_every_shot():
    truth = broadcast_camera()
    matrix = homography_of(truth)
    fps, n = 30, 200
    times = [i / fps for i in range(n)]
    shuttle = [None] * n
    first = [3.0, 11.5, 2.6, 1.0, -22.0, 14.0]
    # The far player meets the clear 1.33 s later and hits it back.
    met = F.positions_at(np.array([first]), [40 / fps])[0, 0]
    shots = ((20, first), (60, [*met, 0.0, 20.0, 12.0]))
    for (frame, state), stop in zip(shots, (60, n), strict=True):
        positions = F.positions_at(np.array([state]), np.arange(0, stop - frame) / fps)[
            0
        ]
        for k, p in enumerate(positions):
            if p[2] > 0:
                shuttle[frame + k] = tuple(truth.project(p[None])[0][0])
            else:
                # The shuttle then lies where it landed.
                shuttle[frame + k] = shuttle[frame + k - 1]
    line = {
        "mode": "singles",
        "fps": fps,
        "aspect": ASPECT,
        "times": times,
        "shuttle": shuttle,
        "segments": [0] * n,
        "view_at": [0] * n,
        "homographies": [matrix],
        "players": [[(3.0, 11.5), (3.0, 2.0)] for _ in range(n)],
        "contacts": [
            {"frame": 20, "kind": "serve", "family": None, "court_end": "near"},
            {"frame": 60, "kind": "shot", "family": "clear", "court_end": "far"},
        ],
        "serves": [],
        "ends": [],
    }
    done = []
    (rally,) = R.analyse(line, speeds=True, progress=done.append)
    assert done == [1.0]
    landing = rally["landing"]
    down = F.touchdown(np.array([shots[1][1]]))[0]["point"]
    assert landing["placement"] in ("lifted", "image")
    assert math.dist(landing["court"], down[:2]) < 0.3
    assert landing["flight"]["initial_speed_kmh"] > 80
    truths = [np.linalg.norm(state[3:]) * 3.6 for _, state in shots]
    speeds = [f["initial_speed_kmh"] for f in rally["shot_flights"]]
    assert len(speeds) == 2
    assert all(abs(v - t) < 0.15 * t for v, t in zip(speeds, truths, strict=True))
    (plain,) = R.analyse(line, flight=False)
    assert "placement" not in plain["landing"] and "shot_flights" not in plain
