"""Generated media shared by Python and runtime-only browser fixtures."""

import io
import math
import struct
from fractions import Fraction

import av
import numpy as np


def write_lossless_vfr_video(path, timestamps=(0, 40, 80, 680)):
    """Matroska with explicit 40-ms final sample and independently varied gaps."""
    with av.open(str(path), "w") as container:
        stream = container.add_stream("ffv1", rate=25)
        stream.width, stream.height = 64, 32
        stream.pix_fmt = "bgr0"
        stream.time_base = Fraction(1, 1000)
        stream.codec_context.time_base = Fraction(1, 1000)
        for index, timestamp in enumerate(timestamps):
            frame = av.VideoFrame.from_ndarray(
                np.full((32, 64, 3), 30 + index * 50, np.uint8), format="rgb24"
            )
            frame.pts, frame.time_base = timestamp, Fraction(1, 1000)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path


def write_rotated_video(path, rotation, timestamps=(0, 40, 120, 160)):
    """Encode asymmetric VFR pixels and patch a genuine MP4 display matrix.

    PyAV cannot currently set a stream display matrix through its public API.
    The standard tkhd matrix preserves encoded pixels and source PTS; the angle
    follows PyAV's counterclockwise ``frame.rotation`` contract.
    """
    buffer = io.BytesIO()
    with av.open(buffer, "w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=25)
        stream.width, stream.height = 128, 64
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 1000)
        stream.codec_context.time_base = Fraction(1, 1000)
        for index, pts in enumerate(timestamps):
            pixels = np.empty((64, 128, 3), dtype=np.uint8)
            pixels[:32, :64] = [230, 20 + index * 5, 20]
            pixels[:32, 64:] = [20, 220, 20 + index * 5]
            pixels[32:, :64] = [20 + index * 5, 20, 230]
            pixels[32:, 64:] = [220, 220, 20 + index * 5]
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = pts, Fraction(1, 1000)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    content = bytearray(buffer.getvalue())
    angle = math.radians(rotation)
    cosine, sine = round(math.cos(angle) * 65536), round(math.sin(angle) * 65536)
    matrix = (cosine, -sine, 0, sine, cosine, 0, 0, 0, 1 << 30)
    patched = []

    def patch_boxes(start, end):
        position = start
        while position + 8 <= end:
            size, kind = struct.unpack_from(">I4s", content, position)
            assert size >= 8, "Fixture encoder emitted an unsupported MP4 atom"
            if kind == b"tkhd":
                assert content[position + 8] == 0, "Fixture needs tkhd version 0"
                struct.pack_into(">9i", content, position + 48, *matrix)
                patched.append(position)
            if kind in (b"moov", b"trak"):
                patch_boxes(position + 8, position + size)
            position += size

    patch_boxes(0, len(content))
    assert len(patched) == 1
    path.write_bytes(content)
    return path
