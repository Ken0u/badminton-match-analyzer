import json

import numpy as np
import pytest
from badminton import rally_outcome_model as M
from badminton import rally_outcomes as R
from badminton.match_analysis import COURT_LENGTH_M, COURT_WIDTH_M, court_homography

FPS = 25.0
MATRIX = court_homography([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
PLAYER = 3 + M.SHUTTLE


def image(x, y):
    return (x / COURT_WIDTH_M, y / COURT_LENGTH_M)


def entry(track_id, x, y, raised=False):
    """A stored player detection standing at court (x, y), 100 px tall."""
    px, py = x / COURT_WIDTH_M * 1000, y / COURT_LENGTH_M * 1000
    keypoints = [[px, py - 50, 0.9] for _ in range(17)]
    for i in M.SHOULDERS:
        keypoints[i] = [px, py - 80, 0.9]
    for i in M.WRISTS:
        keypoints[i] = [px, py - (95 if raised else 45), 0.9]
    for i in M.ANKLES:
        keypoints[i] = [px, py - 2, 0.9]
    return {
        "track_id": track_id,
        "box": [px - 20, py - 100, px + 20, py],
        "keypoints": keypoints,
    }


def scene(n=120, contact=40):
    times = [i / FPS for i in range(n)]
    shuttle = [None] * n
    for i in range(contact + 1, contact + 16):
        shuttle[i] = image(3.0 + 0.1 * (i - contact), 9.0 - 0.4 * (i - contact))
    for i in range(contact + 16, contact + 40):
        shuttle[i] = shuttle[contact + 15]
    people = []
    for i in range(n):
        near = entry(1, 2.0 + 0.01 * i, 11.0)
        far = entry(2, 4.0, 2.5, raised=i > contact + 20)
        people.append(
            [p for p in (M.person(e, 1000, 1000, MATRIX) for e in (near, far)) if p]
        )
    return times, shuttle, people, contact


def test_person_and_posture():
    found = M.person(entry(7, 2.0, 11.0), 1000, 1000, MATRIX)
    assert found[0] == 7 and found[1] == pytest.approx((2.0, 11.0))
    assert M.person(entry(7, 2.0, 30.0), 1000, 1000, MATRIX)[1] is None  # off court
    assert M.person(entry(7, 2.0, 11.0), 1000, 1000, None)[1] is None
    assert M.person({"box": [5, 5, 5, 9]}, 1000, 1000, MATRIX) is None
    low = M.posture(found[2], found[3])
    high_person = M.person(entry(7, 2.0, 11.0, raised=True), 1000, 1000, MATRIX)
    high = M.posture(high_person[2], high_person[3])
    assert len(low) == M.POSE and low[0] == pytest.approx(0.4)
    assert high[3] == pytest.approx(0.15) and low[3] == pytest.approx(-0.35)
    assert M.posture(found[2], None)[1:] == [0.0] * 5


def test_sequence_is_described_from_the_last_hitters_end():
    times, shuttle, people, contact = scene()
    landing = R.find_landing(
        times, shuttle, contact, len(times), 16 / 9, lambda i: MATRIX
    )
    near = M.sequence_features(
        times, shuttle, people, contact, landing, "near", 16 / 9, lambda i: MATRIX
    )
    assert near.shape == (M.steps(), M.STEP_FEATURES)
    before = round(M.BEFORE_S / M.STEP_S)
    row = near[before + 10]
    assert row[1] == 1 and row[2] == 0 and row[3] == 1
    # Shuttle 10 frames on: court (4.0, 5.0), on the opponent's side (y < 0).
    assert row[3 + 4] == pytest.approx((4.0 - 3.05) / 3.05, abs=0.01)
    assert row[3 + 5] == pytest.approx((5.0 - 6.7) / 6.7, abs=0.01)
    # The hitter's own player comes first, then the opponent.
    assert row[PLAYER] == 1 and row[PLAYER + 2] == pytest.approx(4.3 / 6.7, abs=0.01)
    other = PLAYER + M.SLOTS * M.PLAYER
    assert row[other] == 1 and row[other + 2] == pytest.approx(-4.2 / 6.7, abs=0.01)
    assert row[PLAYER + 3] > 0  # the near player drifts to the right
    # The opponent raises the arms after the rally.
    assert near[-1][other + 5 + 3] > 0 > near[before][other + 5 + 3]
    # After the landing the flag is on.
    assert near[before + 5][3 + 9] == 0 and near[-1][3 + 9] == 1
    far = M.sequence_features(
        times, shuttle, people, contact, landing, "far", 16 / 9, lambda i: MATRIX
    )
    row = far[before + 10]
    assert row[2] == 1 and row[3 + 5] == pytest.approx((6.7 - 5.0) / 6.7, abs=0.01)
    assert row[PLAYER + 2] == pytest.approx(4.2 / 6.7, abs=0.01)  # the far player
    # Frames of another camera view, and steps outside the data, are not read.
    cut = M.sequence_features(
        times,
        shuttle,
        people,
        contact,
        landing,
        "near",
        16 / 9,
        lambda i: MATRIX,
        lambda i: i < contact + 12,
    )
    assert cut[before + 11][1] == 1 and not cut[before + 12 :, 1:].any()
    early = M.sequence_features(
        times, shuttle, people, 5, None, "near", 16 / 9, lambda i: MATRIX
    )
    assert not early[: before - 5, 1].any() and early[before][1] == 1


def test_mirrored_swaps_left_and_right():
    times, shuttle, people, contact = scene()
    one = M.sequence_features(
        times, shuttle, people, contact, None, "near", 16 / 9, lambda i: MATRIX
    )
    flipped_shuttle = [None if p is None else (1 - p[0], p[1]) for p in shuttle]
    flipped_people = [
        [
            M.person(e, 1000, 1000, MATRIX)
            for e in (
                entry(1, COURT_WIDTH_M - (2.0 + 0.01 * i), 11.0),
                entry(2, COURT_WIDTH_M - 4.0, 2.5, raised=i > contact + 20),
            )
        ]
        for i in range(len(times))
    ]
    two = M.sequence_features(
        times,
        flipped_shuttle,
        flipped_people,
        contact,
        None,
        "near",
        16 / 9,
        lambda i: MATRIX,
    )
    assert M.mirrored(one) == pytest.approx(two, abs=1e-5)
    assert M.mirrored(M.mirrored(one)) == pytest.approx(one, abs=1e-6)


def document(seed=0, members=1):
    rng = np.random.default_rng(seed)
    h = 8

    def member():
        shapes = {
            "input.weight": (h, M.STEP_FEATURES),
            "input.bias": (h,),
            "summary.weight": (32, len(R.FEATURES)),
            "summary.bias": (32,),
            "hidden.weight": (64, 6 * h + 32),
            "hidden.bias": (64,),
            "classes.weight": (3, 64),
            "classes.bias": (3,),
            "won.weight": (1, 64),
            "won.bias": (1,),
        }
        for suffix in ("", "_reverse"):
            shapes[f"gru.weight_ih_l0{suffix}"] = (3 * h, h)
            shapes[f"gru.weight_hh_l0{suffix}"] = (3 * h, h)
            shapes[f"gru.bias_ih_l0{suffix}"] = (3 * h,)
            shapes[f"gru.bias_hh_l0{suffix}"] = (3 * h,)
        return {k: M.encode_array(rng.normal(0, 0.3, s)) for k, s in shapes.items()}

    return {
        "format": M.FORMAT,
        "name": "test sequence model",
        "features": list(R.FEATURES),
        "classes": list(R.CLASSES),
        "step_features": M.STEP_FEATURES,
        "after_s": M.AFTER_S,
        "mean": [0.0] * len(R.FEATURES),
        "scale": [1.0] * len(R.FEATURES),
        "members": [member() for _ in range(members)],
    }


def test_numpy_network_matches_torch():
    torch = pytest.importorskip("torch")
    doc = document()
    weights = {k: M.decode_array(v) for k, v in doc["members"][0].items()}
    rng = np.random.default_rng(1)
    sequence = rng.normal(size=(M.steps(), M.STEP_FEATURES))
    summary = rng.normal(size=len(R.FEATURES))
    classes, won = M.forward(weights, sequence, summary)
    h = 8
    gru = torch.nn.GRU(h, h, batch_first=True, bidirectional=True)
    gru.load_state_dict(
        {
            k[4:]: torch.tensor(v, dtype=torch.float32)
            for k, v in weights.items()
            if k.startswith("gru.")
        }
    )
    t = lambda name: torch.tensor(weights[name], dtype=torch.float32)  # noqa: E731
    x = torch.relu(
        torch.tensor(sequence, dtype=torch.float32) @ t("input.weight").T
        + t("input.bias")
    )
    states = gru(x[None])[0][0]
    pooled = torch.cat(
        [states.mean(0), states.max(0).values, states[-1, :h], states[0, h:]]
    )
    g = torch.relu(
        torch.tensor(summary, dtype=torch.float32) @ t("summary.weight").T
        + t("summary.bias")
    )
    hid = torch.relu(torch.cat([pooled, g]) @ t("hidden.weight").T + t("hidden.bias"))
    expected = hid @ t("won.weight").T + t("won.bias")
    assert won == pytest.approx(float(expected.detach()[0]), abs=1e-4)
    expected = hid @ t("classes.weight").T + t("classes.bias")
    assert classes == pytest.approx(expected.detach().numpy(), abs=1e-4)


def test_model_document_round_trip_and_call():
    doc = json.loads(json.dumps(document(members=2)))
    model = R.model_from_document(doc)
    assert isinstance(model, M.SequenceOutcomeModel) and len(model.members) == 2
    times, shuttle, people, contact = scene()
    n = len(times)
    line = {
        "mode": "singles",
        "fps": FPS,
        "aspect": 16 / 9,
        "times": times,
        "shuttle": shuttle,
        "segments": [0] * n,
        "view_at": [0] * n,
        "homographies": [MATRIX],
        "players": [[p[1] for p in row] for row in people],
        "people": people,
        "contacts": [
            {"frame": 10, "kind": "serve", "family": None, "court_end": "far"},
            {"frame": contact, "kind": "shot", "family": "smash", "court_end": "near"},
        ],
        "serves": [],
        "ends": [],
    }
    rally = R.analyse(line, model)[0]
    outcome = rally["outcome"]
    assert outcome["source"] == "model" and 0.5 <= outcome["confidence"] <= 1
    assert outcome["winner_end"] == ("near" if outcome["reason"] == "winner" else "far")
    assert (outcome["detail"] == "in") == (outcome["reason"] == "winner")
    # Without the people (older callers) the players' positions are enough.
    del line["people"]
    assert R.analyse(line, model)[0]["outcome"]["source"] == "model"
    # An unknown last hitter leaves the rule's answer.
    line["contacts"][-1]["court_end"] = None
    assert R.analyse(line, model)[0]["outcome"] is None
    wrong = document()
    wrong["step_features"] += 1
    with pytest.raises(ValueError):
        M.SequenceOutcomeModel(wrong)
    assert isinstance(R.model_from_document(v1_document()), R.OutcomeModel)


def v1_document():
    n = len(R.FEATURES)
    return {
        "features": list(R.FEATURES),
        "classes": list(R.CLASSES),
        "mean": [0.0] * n,
        "scale": [1.0] * n,
        "layers": [[np.zeros((n, 3)).tolist(), [0.0, 0.0, 0.0]]],
    }
