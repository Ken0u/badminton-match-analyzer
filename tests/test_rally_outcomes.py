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
    """Points from start up to an apex then down to end, then still."""
    points = []
    for i in range(frames):
        t = i / (frames - 1)
        x = start[0] + (end[0] - start[0]) * t
        # Rise towards `top` (smaller image y) then fall to `end`.
        y = (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * top + t**2 * end[1]
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
