import copy

import cv2
import numpy as np
import pytest
from badminton.court_detection import (
    court_consensus,
    detect_court,
    partial_courts,
    recheck_frames,
)


def render_court(width=960, height=540, color=(35, 115, 80), angle=0):
    """Independent physical-coordinate drawing, not the detector's template."""
    image = np.full((height, width, 3), color, np.uint8)
    corners = np.array([[0.35, 0.12], [0.65, 0.12], [0.87, 0.9], [0.13, 0.9]]) * [
        width,
        height,
    ]
    if angle:
        rotation = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 0.8)
        corners = cv2.transform(corners[None].astype(np.float32), rotation)[0]
    transform = cv2.getPerspectiveTransform(
        np.array([[0, 0], [6.1, 0], [6.1, 13.4], [0, 13.4]], np.float32),
        corners.astype(np.float32),
    )
    markings = [
        ((0, 0), (6.1, 0)),
        ((6.1, 0), (6.1, 13.4)),
        ((6.1, 13.4), (0, 13.4)),
        ((0, 13.4), (0, 0)),
        ((0.46, 0), (0.46, 13.4)),
        ((5.64, 0), (5.64, 13.4)),
        ((0, 0.76), (6.1, 0.76)),
        ((0, 12.64), (6.1, 12.64)),
        ((0, 4.72), (6.1, 4.72)),
        ((0, 8.68), (6.1, 8.68)),
        ((3.05, 0), (3.05, 4.72)),
        ((3.05, 8.68), (3.05, 13.4)),
    ]
    for endpoints in markings:
        points = cv2.perspectiveTransform(np.array([endpoints], np.float32), transform)[
            0
        ]
        cv2.line(
            image,
            tuple(np.rint(points[0]).astype(int)),
            tuple(np.rint(points[1]).astype(int)),
            (245, 245, 245),
            3,
            cv2.LINE_AA,
        )
    return image, corners / [width, height]


@pytest.mark.parametrize("color", [(35, 115, 80), (165, 30, 45), (30, 70, 160)])
@pytest.mark.parametrize(
    "size,angle", [((960, 540), 0), ((480, 720), 0), ((960, 720), 12)]
)
def test_visible_markings_fit_without_surface_color_prior(color, size, angle):
    image, expected = render_court(*size, color, angle)
    before = image.copy()
    result = detect_court(image)
    assert result["status"] == "detected"
    np.testing.assert_allclose(result["corners"], expected, atol=0.015)
    np.testing.assert_array_equal(image, before)


@pytest.mark.parametrize("kind", ["blank", "white", "rectangle", "cropped"])
def test_missing_markings_are_not_a_court(kind):
    if kind == "cropped":
        image, _ = render_court()
        image[350:] = (35, 115, 80)
    else:
        image = np.full((540, 960, 3), 255 if kind == "white" else 35, np.uint8)
        if kind == "rectangle":
            cv2.rectangle(image, (150, 80), (800, 460), (240, 240, 240), 3)
            cv2.line(image, (475, 80), (475, 460), (240, 240, 240), 3)
            cv2.line(image, (150, 270), (800, 270), (240, 240, 240), 3)
    result = detect_court(image)
    assert result["status"] == "not_detected"
    assert result["corners"] is None


@pytest.mark.parametrize(
    "image",
    [
        None,
        np.zeros((10, 10, 3), np.uint8),
        np.zeros((128, 128)),
        np.zeros((128, 128, 4), np.uint8),
    ],
)
def test_invalid_input_rejected(image):
    with pytest.raises(ValueError, match="RGB uint8"):
        detect_court(image)


def samples():
    return [
        {
            "frame": i,
            "status": "detected",
            "corners": [[0.35, 0.12], [0.65, 0.12], [0.87, 0.9], [0.13, 0.9]],
        }
        for i in (0, 25, 50, 74, 99)
    ]


def test_temporal_consensus_uses_actual_observed_fit():
    observations = samples()
    observations[0]["status"] = "not_detected"
    observations[2]["corners"][0][0] += 0.003
    result = court_consensus(observations, 0, 100)
    assert result["status"] == "detected"
    assert result["corners"] in [s["corners"] for s in observations]
    assert result["source_frame"] in (25, 74, 99)


@pytest.mark.parametrize("change", ["pan", "middle_only", "ambiguous"])
def test_moving_or_insufficiently_covered_view_abstains(change):
    observations = samples()
    if change == "pan":
        for corner in observations[-1]["corners"]:
            corner[0] += 0.03
    elif change == "middle_only":
        observations[0]["status"] = observations[-1]["status"] = "not_detected"
    else:
        for s in observations[:3]:
            s["status"] = "ambiguous"
    before = copy.deepcopy(observations)
    result = court_consensus(observations, 0, 100)
    assert result["corners"] is None
    assert observations == before


def test_one_misfit_beside_an_agreeing_fit_does_not_discard_the_view():
    observations = samples()
    for corner in observations[0]["corners"]:
        corner[1] *= 0.7
    assert court_consensus(observations, 0, 100)["corners"] is None
    assert recheck_frames(observations, 0, 100) == [6]
    observations.insert(1, {**copy.deepcopy(observations[1]), "frame": 6})
    result = court_consensus(observations, 0, 100)
    assert result["status"] == "detected"
    assert result["disagreeing_frames"] == [0]
    assert result["source_frame"] != 0


def test_disagreement_that_persists_beside_the_fit_still_abstains():
    observations = samples()
    for corner in observations[-1]["corners"]:
        corner[0] += 0.03
    assert recheck_frames(observations, 0, 100) == [93]
    observations.insert(4, {**copy.deepcopy(observations[-1]), "frame": 93})
    assert court_consensus(observations, 0, 100)["corners"] is None


def test_duplicate_or_outside_source_frames_rejected():
    observations = samples()
    observations[1]["frame"] = 0
    with pytest.raises(ValueError, match="ordered and unique"):
        court_consensus(observations, 0, 100)


def test_two_equally_supported_courts_are_ambiguous():
    image, _ = render_court(640, 720)
    result = detect_court(np.concatenate([image, image], axis=1))
    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) >= 2
    assert result["corners"] is None


COURT = [[0.35, 0.12], [0.65, 0.12], [0.87, 0.9], [0.13, 0.9]]


def fading_view(court_from, court_to, moved_from=None):
    """A view whose court is visible only in [court_from, court_to)."""
    asked = []

    def sample_at(frame):
        asked.append(frame)
        if not court_from <= frame < court_to:
            return {"frame": frame, "status": "not_detected", "corners": None}
        corners = copy.deepcopy(COURT)
        if moved_from is not None and frame >= moved_from:
            for corner in corners:
                corner[0] += 0.03
        return {"frame": frame, "status": "detected", "corners": corners}

    return sample_at, asked


def test_court_seen_for_part_of_a_view_is_kept_for_that_part():
    # A replay fades into the rally at frame 260 of a 500-frame view.
    sample_at, asked = fading_view(260, 500)
    first = [sample_at(frame) for frame in (0, 125, 250, 374, 499)]
    assert court_consensus(first, 0, 500)["corners"] is None
    parts, taken = partial_courts(first, 0, 500, sample_at)
    assert len(parts) == 1
    start, end, found = parts[0]
    assert 260 <= start <= 268 and end == 500
    assert found["status"] == "detected" and found["corners"] == COURT
    assert [s["frame"] for s in taken] == sorted(set(asked))


def test_two_rallies_around_a_replay_give_two_stretches():
    def sample_at(frame):
        seen = frame < 90 or frame >= 300
        return {
            "frame": frame,
            "status": "detected" if seen else "not_detected",
            "corners": copy.deepcopy(COURT) if seen else None,
        }

    first = [sample_at(frame) for frame in (0, 125, 250, 374, 499)]
    parts, _ = partial_courts(first, 0, 500, sample_at)
    assert [(a <= 0, 82 <= b <= 90) for a, b, _ in parts[:1]] == [(True, True)]
    assert 300 <= parts[1][0] <= 308 and parts[1][1] == 500


def test_brief_or_moving_court_inside_a_view_stays_uncalibrated():
    # Seen for under MIN_PARTIAL_FRAMES.
    sample_at, _ = fading_view(240, 262)
    first = [sample_at(frame) for frame in (0, 125, 250, 374, 499)]
    assert partial_courts(first, 0, 500, sample_at)[0] == []
    # The camera moves inside the visible stretch: each geometry is separate.
    sample_at, _ = fading_view(200, 500, moved_from=400)
    first = [sample_at(frame) for frame in (0, 125, 250, 374, 499)]
    parts, _ = partial_courts(first, 0, 500, sample_at)
    assert all(b <= 400 or a >= 400 for a, b, _ in parts)
    assert all(a < b for a, b, _ in parts)
    assert all(parts[i][1] <= parts[i + 1][0] for i in range(len(parts) - 1))
