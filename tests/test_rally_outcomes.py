import json
import math

import numpy as np
import pytest
from badminton import rally_outcomes as R
from badminton.match_analysis import COURT_LENGTH_M, COURT_WIDTH_M, court_homography

FPS = 30.0
# Image points are court metres scaled into the picture: x / 6.1, y / 13.4,
# so this homography maps them back exactly.
CORNERS = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
MATRIX = court_homography(CORNERS)


def image(x, y):
    return (x / COURT_WIDTH_M, y / COURT_LENGTH_M)


def times(n):
    return [i / FPS for i in range(n)]


def flight(start, top, end, frames, rest=15, total=None):
    """Points from start up to an apex at image y `top`, down to end, then still."""
    points = []
    rise = max(1, frames // 3)
    for i in range(frames):
        x = start[0] + (end[0] - start[0]) * i / (frames - 1)
        if i <= rise:
            y = start[1] + (top - start[1]) * i / rise
        else:
            y = top + (end[1] - top) * (i - rise) / (frames - 1 - rise)
        points.append((x, y))
    points += [end] * rest
    if total is not None:
        points += [None] * (total - len(points))
    return points


def test_lines_and_ends():
    assert R.court_end((3, 2)) == "far" and R.court_end((3, 9)) == "near"
    assert R.in_court((0.2, 5), "doubles") and not R.in_court((0.2, 5), "singles")
    assert not R.in_court((3, 13.6), "doubles")
    assert R.line_distance((3.05, 6.7), "doubles") == pytest.approx(3.05)
    assert R.line_distance((-0.3, 5), "doubles") == pytest.approx(-0.3)
    assert R.line_distance((6.4, 14.0), "singles") == pytest.approx(
        -math.hypot(6.4 - 5.64, 0.6)
    )
    assert R.other("far") == "near" and R.other(None) is None


def test_landing_is_the_end_of_the_descent():
    # Near player hits towards the far court: the shuttle rises in the
    # picture, then comes down onto (2.0, 2.5) and lies there.
    start, end = image(3.0, 11.0), image(2.0, 2.5)
    points = [None, *flight(start, 0.05, end, 25)]
    landing = R.find_landing(
        times(len(points)), points, 0, len(points), 16 / 9, lambda i: MATRIX
    )
    assert landing["kind"] == "rest"
    assert landing["court"] == pytest.approx((2.0, 2.5), abs=0.05)
    assert 20 <= landing["index"] <= 26


def test_a_jump_ends_the_flight_and_a_rise_never_lands():
    start, end = image(3.0, 11.0), image(2.0, 9.5)
    points = [None, *flight(start, end[1] - 0.05, end, 12, rest=0)]
    # A false detection far away after the landing is not followed.
    points += [image(5.9, 0.2)] * 15
    landing = R.find_landing(
        times(len(points)), points, 0, len(points), 16 / 9, lambda i: MATRIX
    )
    assert landing["kind"] == "descent"
    assert landing["court"] == pytest.approx((2.0, 9.5), abs=0.1)
    rising = [None, *(image(3.0, 11.0 - i * 0.3) for i in range(12))]
    track_end = R.find_landing(
        times(len(rising)), rising, 0, len(rising), 16 / 9, lambda i: MATRIX
    )
    assert track_end["kind"] == "track_end"
    assert R.find_landing(times(5), [None] * 5, 0, 5, 16 / 9, lambda i: MATRIX) is None
    no_view = R.find_landing(
        times(len(points)), points, 0, len(points), 16 / 9, lambda i: None
    )
    assert no_view["court"] is None


def landing_of(points, after=0):
    return R.find_landing(
        times(len(points)), points, after, len(points), 16 / 9, lambda i: MATRIX
    )


def test_a_hidden_shuttle_is_found_again_where_it_lies():
    # The track ends in the air above (2.0, 9.5); the shuttle shows again
    # half a second later, lying a little lower.
    start, end = image(3.0, 4.0), image(2.0, 9.0)
    seen = flight(start, start[1] - 0.05, end, 12, rest=0)
    points = [None, *seen, *[None] * 15, *[image(2.0, 9.5)] * 15]
    landing = landing_of(points)
    assert landing["kind"] == "rest"
    assert landing["court"] == pytest.approx((2.0, 9.5), abs=0.05)
    # Something lying higher in the picture is not where this shuttle fell.
    points = [None, *seen, *[None] * 15, *[image(2.0, 5.0)] * 15]
    assert landing_of(points)["court"] == pytest.approx((2.0, 9.0), abs=0.05)


def test_a_lift_that_leaves_the_top_of_the_picture_comes_back():
    up = [(0.5, 0.5 - 0.06 * i) for i in range(9)]  # leaves at y = 0.02
    down = [(0.52, 0.02 + 0.05 * i) for i in range(8)]  # back to y = 0.37
    points = [None, *up, *[None] * 20, *down, *[(0.52, 0.37)] * 12]
    landing = landing_of(points)
    assert landing["kind"] == "rest"
    assert landing["image"] == pytest.approx((0.52, 0.37))
    # Without the return the track ended in the air.
    assert landing_of([None, *up, *[None] * 40])["kind"] == "track_end"


def test_false_detections_are_not_followed():
    start, end = image(3.0, 4.0), image(2.0, 9.5)
    seen = flight(start, start[1] - 0.05, end, 12, rest=12)
    # Two detections on a player's hand in the middle of the flight.
    jumped = list(seen)
    jumped[5] = jumped[6] = image(5.5, 1.0)
    assert landing_of([None, *jumped])["court"] == pytest.approx((2.0, 9.5), abs=0.05)
    # A mark that was "detected" during the rally, and again after the track
    # ended in the air: not the landing.
    mark = image(2.2, 9.8)
    before = [mark] * 20 + [None] * 5
    points = [*before, None, *seen[:9], *[None] * 12, *[mark] * 15]
    landing = landing_of(points, after=len(before))
    assert landing["court"] != pytest.approx(image(2.2, 9.8), abs=0.05)
    assert landing["index"] <= len(before) + 9
    # The same detections without the earlier ones are the shuttle at rest.
    points = [*[None] * 25, None, *seen[:9], *[None] * 12, *[mark] * 15]
    assert landing_of(points, after=25)["court"] == pytest.approx((2.2, 9.8), abs=0.05)


def test_a_shuttle_that_slides_on_lands_at_the_impact():
    # A smash reaches the floor at (2.0, 10.0) and slides 1.2 m further.
    fall = [image(3.0 - 0.1 * i, 7.0 + 0.3 * i) for i in range(11)]
    slide = [image(2.0 - 0.02 * i, 10.0 + 0.08 * i) for i in range(1, 16)]
    points = [None, *fall, *slide, *[slide[-1]] * 12]
    landing = landing_of(points)
    assert landing["slid"] is True and landing["kind"] == "rest"
    assert landing["court"] == pytest.approx((2.0, 10.0), abs=0.1)
    # Close behind the net a slow shuttle is one dropping down the net.
    fall = [image(3.0, 3.0 + 0.3 * i) for i in range(8)]
    drop = [image(3.0, 5.1 + 0.08 * i) for i in range(1, 16)]
    points = [None, *fall, *drop, *[drop[-1]] * 12]
    landing = landing_of(points)
    assert "slid" not in landing
    assert landing["court"] == pytest.approx((3.0, 6.3), abs=0.05)


def test_a_serve_is_judged_by_the_service_lines():
    short = {"court": (2.0, 5.0), "kind": "rest"}  # 1.7 m behind the net
    assert R.rule_outcome("near", short, "doubles")["detail"] == "in"
    assert R.rule_outcome("near", short, "doubles", serve=True) == {
        "winner_end": "far",
        "reason": "error",
        "detail": "out",
    }
    long = {"court": (2.0, 0.4), "kind": "rest"}  # behind the doubles long line
    assert R.rule_outcome("near", long, "doubles", serve=True)["detail"] == "out"
    assert R.rule_outcome("near", long, "singles", serve=True)["detail"] == "in"
    assert (
        R.rule_outcome("far", {"court": (2.0, 12.9)}, "doubles", True)["detail"]
        == "out"
    )
    assert R.in_court((2.0, 4.0), "doubles", "near")
    assert R.line_distance((2.0, 5.0), "singles", "near") == pytest.approx(-0.28)
    assert R.line_distance((2.0, 9.0), "doubles", "far") == pytest.approx(0.32)


def test_rule_outcome():
    landing = {"court": (2.0, 2.0), "kind": "rest"}
    assert R.rule_outcome("near", landing, "singles") == {
        "winner_end": "near",
        "reason": "winner",
        "detail": "in",
    }
    # On the hitter's own side, or at the net: it did not get over.
    assert R.rule_outcome("far", landing, "singles")["detail"] == "net"
    assert R.rule_outcome("near", {"court": (2, 6.5)}, "doubles")["winner_end"] == "far"
    out = R.rule_outcome("near", {"court": (0.2, 3.0)}, "singles")
    assert out == {"winner_end": "far", "reason": "error", "detail": "out"}
    assert R.rule_outcome("near", {"court": (0.2, 3.0)}, "doubles")["detail"] == "in"
    assert R.rule_outcome(None, landing, "singles") is None
    assert R.rule_outcome("near", None, "singles") is None
    assert R.rule_outcome("near", {"court": (30.0, 3.0)}, "singles") is None


def test_outcome_features_are_fixed_length_and_hitter_relative():
    start, end = image(3.0, 11.0), image(2.0, 2.5)
    points = [None, *flight(start, 0.05, end, 25)]
    t = times(len(points))
    landing = R.find_landing(t, points, 0, len(points), 16 / 9, lambda i: MATRIX)
    players = [[(3.0, 11.0), (3.0, 3.5)] for _ in points]
    near = R.outcome_features(
        t, points, players, 0, landing, "near", "singles", 16 / 9, "smash"
    )
    far = R.outcome_features(t, points, players, 0, landing, "far", "singles", 16 / 9)
    names = dict(zip(R.FEATURES, near, strict=True))
    assert len(near) == len(far) == len(R.FEATURES)
    assert names["depth_m"] == pytest.approx(4.2, abs=0.1) and names["own_side"] == 0
    assert dict(zip(R.FEATURES, far))["own_side"] == 1
    assert names["family_attack"] == 1 and names["kind_rest"] == 1
    assert names["nearest_player_m"] == pytest.approx(math.hypot(1.0, 1.0), abs=0.1)
    blank = R.outcome_features(t, points, players, 0, None, None, "doubles", 16 / 9)
    assert dict(zip(R.FEATURES, blank))["landing_found"] == 0


def model_document(bias):
    n = len(R.FEATURES)
    return {
        "name": "test model",
        "features": list(R.FEATURES),
        "classes": list(R.CLASSES),
        "mean": [0.0] * n,
        "scale": [1.0] * n,
        "layers": [[np.zeros((n, 3)).tolist(), bias]],
    }


def test_json_model_calls_the_outcome_from_the_last_hitter():
    model = R.OutcomeModel(model_document([0.0, 0.0, 2.0]))
    p = model.probabilities([0.0] * len(R.FEATURES))
    assert p.sum() == pytest.approx(1) and int(np.argmax(p)) == 2
    line = {
        "times": times(10),
        "shuttle": [None] * 10,
        "players": [[] for _ in range(10)],
        "contacts": [
            {"frame": 2, "court_end": "far", "kind": "shot", "family": "drop"}
        ],
        "mode": "doubles",
        "aspect": 16 / 9,
    }
    called = model(line, {"shots": [0]}, None)
    assert called["winner_end"] == "near" and called["detail"] == "net"
    assert called["reason"] == "error" and 0 < called["confidence"] <= 1
    line["contacts"][0]["court_end"] = None
    assert model(line, {"shots": [0]}, None) is None
    wrong = model_document([0.0, 0.0, 0.0]) | {"features": ["x"]}
    with pytest.raises(ValueError):
        R.OutcomeModel(wrong)


def synthetic_line():
    """Two rallies 10 s apart; each last shot lands on the far court."""
    n = 600
    shuttle = [None] * n
    for frame in (60, 390):
        start, end = image(3.0, 11.0), image(2.0, 2.5)
        for i, p in enumerate(flight(start, 0.05, end, 25)):
            shuttle[frame + 1 + i] = p
    contacts = [
        {"frame": f, "kind": k, "family": None, "court_end": e, "score": 0.9}
        for f, k, e in (
            (10, "serve", "near"),
            (35, "shot", "far"),
            (60, "shot", "near"),
            (340, "serve", "far"),
            (365, "shot", "near"),
            (390, "shot", "near"),
        )
    ]
    return {
        "mode": "singles",
        "fps": FPS,
        "aspect": 16 / 9,
        "times": times(n),
        "shuttle": shuttle,
        "segments": [0] * n,
        "view_at": [0] * n,
        "homographies": [MATRIX],
        "players": [[(3.0, 11.0), (3.0, 3.0)] for _ in range(n)],
        "contacts": contacts,
        "serves": [],
        "ends": [],
    }


def test_analyse_splits_rallies_and_ends_them_at_the_landing():
    rallies = R.analyse(synthetic_line())
    assert [r["shot_frames"] for r in rallies] == [[10, 35, 60], [340, 365, 390]]
    first = rallies[0]
    assert first["start_source"] == "first_contact"
    assert first["end_source"] == "landing" and 80 <= first["end_frame"] <= 90
    assert first["landing"]["court"] == pytest.approx([2.0, 2.5], abs=0.05)
    assert first["landing"]["in_court"] is True
    assert first["outcome"] == {
        "winner_end": "near",
        "reason": "winner",
        "detail": "in",
        "source": "rule",
    }
    assert rallies[1]["start_source"] == "predicted_serve"
    model = R.OutcomeModel(model_document([0.0, 5.0, 0.0]))
    called = R.analyse(synthetic_line(), model)[0]["outcome"]
    assert called["source"] == "model" and called["detail"] == "out"
    assert called["winner_end"] == "far"


def test_installed_model_must_match_the_manifest(tmp_path, monkeypatch):
    import badminton.config as config

    document = model_document([1.0, 0.0, 0.0])
    path = tmp_path / "rally_outcome_test.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    import hashlib

    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(config, "WEIGHTS", tmp_path)
    monkeypatch.setattr(R, "manifest_entry", lambda: {"name": path.name, "sha256": sha})
    model, problem = R.load_model()
    assert problem is None and model.name == "test model"
    monkeypatch.setattr(
        R, "manifest_entry", lambda: {"name": path.name, "sha256": "0" * 64}
    )
    assert R.load_model()[0] is None
    monkeypatch.setattr(
        R, "manifest_entry", lambda: {"name": "missing.json", "sha256": sha}
    )
    assert "not installed" in R.load_model()[1]
    monkeypatch.setattr(R, "manifest_entry", lambda: None)
    assert "registered" in R.load_model()[1]
