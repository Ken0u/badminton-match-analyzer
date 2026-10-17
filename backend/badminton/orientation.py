"""Normalize cardinal display rotation without changing source timestamps.

PyAV exposes display-matrix rotation in counterclockwise degrees. Browsers apply
that transform while playing the original container; CV and exact-frame review
must apply the same transform to decoded pixels.
"""

import math
import struct

import av
import numpy as np


class OrientationError(ValueError):
    pass


def frame_rotation(frame):
    """Return cardinal counterclockwise rotation, rejecting unsupported transforms."""
    rotation = float(frame.rotation)
    if not math.isfinite(rotation) or rotation % 90:
        raise OrientationError(
            "Video display rotation must be 0, 90, 180, or 270 degrees"
        )
    matrix = frame.side_data.get("DISPLAYMATRIX")
    if matrix is not None:
        values = struct.unpack("=9i", bytes(matrix))
        a, b, u, c, d, v, _x, _y, w = values
        # Phones normally use a pure rotation, with optional translation.
        # Reflection/shear/perspective must not silently produce different
        # browser and CV images merely because their rotation component is 0.
        if (
            a * d - b * c <= 0
            or a * a + b * b != 65536**2
            or c * c + d * d != 65536**2
            or a * c + b * d != 0
            or u != 0
            or v != 0
            or w != 1 << 30
        ):
            raise OrientationError(
                "Video has an unsupported mirrored, scaled, or skewed display transform"
            )
    return int(rotation) % 360


def display_dimensions(width, height, rotation):
    return (height, width) if rotation in (90, 270) else (width, height)


def orient_frame(frame, *, expected_rotation=None):
    """Return display-oriented pixels and preserve the source PTS/time base.

    Zero rotation returns the original frame. Nonzero rotation uses cardinal
    array transposition without interpolation, then carries timing into the new
    RGB VideoFrame. ``expected_rotation`` guards changing transforms within a
    source or stale imported orientation metadata.
    """
    rotation = frame_rotation(frame)
    if expected_rotation is not None and rotation != expected_rotation:
        raise OrientationError(
            "Video display rotation changed or differs from its import. Reimport the source."
        )
    if not rotation:
        return frame
    pixels = np.rot90(frame.to_ndarray(format="rgb24"), rotation // 90)
    result = av.VideoFrame.from_ndarray(np.ascontiguousarray(pixels), format="rgb24")
    result.pts = frame.pts
    result.time_base = frame.time_base
    return result
