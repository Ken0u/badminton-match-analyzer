import copy

import cv2
import numpy as np
import pytest
from badminton.court_detection import court_consensus, detect_court


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
