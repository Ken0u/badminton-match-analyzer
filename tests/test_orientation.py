"""Real MP4 display matrices must agree across playback, review and inference."""

import io
import json
import math
import struct
import time
from fractions import Fraction

import av
import numpy as np
import pytest
from badminton.api import create_app
from badminton.ingest import inspect_video, read_frame
from badminton.orientation import OrientationError, frame_rotation, orient_frame
from badminton.storage import Store
from badminton.video import iter_frames, timestamps_for
from fastapi.testclient import TestClient
from PIL import Image


def write_rotated_video(path, rotation):
    """Encode asymmetric pixels and patch a genuine MP4 track display matrix.

    PyAV cannot currently set a stream display matrix through its public API.
    Patching the standard tkhd matrix preserves encoded pixels and source PTS.
    The angle below follows PyAV's counterclockwise ``frame.rotation`` contract.
    """
    buffer = io.BytesIO()
    with av.open(buffer, "w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=25)
        stream.width, stream.height = 128, 64
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 1000)
        stream.codec_context.time_base = Fraction(1, 1000)
        for index, pts in enumerate((0, 40, 120, 160)):
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


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_cardinal_rotation_aligns_metadata_audit_exact_frames_and_inference(
    tmp_path, rotation
):
    path = write_rotated_video(tmp_path / f"rotation-{rotation}.mp4", rotation)
    with av.open(str(path)) as container:
        source = list(container.decode(container.streams.video[0]))
    assert all(frame_rotation(frame) == rotation for frame in source)
    store = Store(tmp_path / "processed")
    video = inspect_video(path, "singles", store, tmp_path)
    expected_dimensions = (64, 128) if rotation in (90, 270) else (128, 64)
    assert (video["width"], video["height"]) == expected_dimensions
    assert (video["source_width"], video["source_height"]) == (128, 64)
    assert video["rotation"] == rotation
    times = timestamps_for(store.data, video["id"])
    assert times == pytest.approx([0, 0.04, 0.12, 0.16])
    assert video["variable_frame_rate"] is True
    frames = list(iter_frames(video, tmp_path, times, 0, 4))
    assert [index for index, _, _ in frames] == list(range(4))
    assert [time for _, time, _ in frames] == pytest.approx(times)
    for original, (index, _, oriented) in zip(source, frames, strict=True):
        expected = np.rot90(original.to_ndarray(format="rgb24"), rotation // 90)
        assert (oriented.width, oriented.height) == expected_dimensions
        assert oriented.pts == original.pts
        assert oriented.time_base == original.time_base
        assert np.array_equal(oriented.to_ndarray(format="rgb24"), expected)
        exact = read_frame(path, times[index], video["source_start_s"])
        assert exact.size == expected_dimensions
        assert np.array_equal(np.asarray(exact), expected)
    poster = Image.open(store.data / video["id"] / "poster.jpg")
    assert poster.size == expected_dimensions
    expected = np.rot90(source[0].to_ndarray(format="rgb24"), rotation // 90)
    # The audit is JPEG, so compare stable interior colors with lossy tolerance.
    assert np.mean(np.abs(np.asarray(poster).astype(float) - expected)) < 5
    assert json.loads((store.data / video["id"] / "metadata.json").read_text()) == video


def test_nonrotated_legacy_metadata_preserves_source_pixels_and_timing(tmp_path):
    path = write_rotated_video(tmp_path / "legacy.mp4", 0)
    store = Store(tmp_path / "processed")
    video = inspect_video(path, "singles", store, tmp_path)
    for key in ("rotation", "source_width", "source_height"):
        video.pop(key)
    times = timestamps_for(store.data, video["id"])
    index, time, frame = next(iter_frames(video, tmp_path, times, 2, 3))
    assert index == 2 and time == pytest.approx(0.12)
    assert frame_rotation(frame) == 0
    assert np.array_equal(
        frame.to_ndarray(format="rgb24"), np.asarray(read_frame(path, times[2]))
    )


def test_noncardinal_rotation_and_stale_orientation_fail_clearly(tmp_path):
    path = write_rotated_video(tmp_path / "noncardinal.mp4", 45)
    store = Store(tmp_path / "processed")
    with pytest.raises(OrientationError, match="0, 90, 180, or 270"):
        inspect_video(path, "singles", store, tmp_path)
    assert store.videos() == []
    path = write_rotated_video(tmp_path / "cardinal.mp4", 90)
    video = inspect_video(path, "singles", store, tmp_path)
    times = timestamps_for(store.data, video["id"])
    with pytest.raises(OrientationError, match="Reimport"):
        next(iter_frames(video | {"rotation": 0}, tmp_path, times, 0, 1))
    with av.open(str(path)) as container:
        original = next(container.decode(container.streams.video[0]))
    with pytest.raises(OrientationError, match="Reimport"):
        orient_frame(original, expected_rotation=180)


def test_uploaded_phone_video_keeps_source_media_and_serves_display_oriented_frames(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("BADMINTON_USERNAME", raising=False)
    monkeypatch.delenv("BADMINTON_PASSWORD", raising=False)
    original = write_rotated_video(tmp_path / "phone.mp4", 90)
    content = original.read_bytes()
    data = tmp_path / "processed"
    with TestClient(create_app(tmp_path, data)) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("phone.mp4", content, "video/mp4")},
            data={"mode": "singles"},
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        for _ in range(200):
            job = next(
                job for job in client.get("/api/jobs").json() if job["id"] == job_id
            )
            if job["status"] not in ("queued", "running"):
                break
            time.sleep(0.01)
        assert job["status"] == "completed", job
        video = client.get("/api/videos").json()[0]
        assert (video["width"], video["height"], video["rotation"]) == (64, 128, 90)
        assert video["source_type"] == "upload" and video["name"] == "phone.mp4"
        assert client.get(f"/api/videos/{video['id']}/media").content == content
        timestamps = client.get(f"/api/videos/{video['id']}/timestamps").json()
        assert timestamps == pytest.approx([0, 0.04, 0.12, 0.16])
        response = client.get(f"/api/videos/{video['id']}/frame?index=2")
        exact = Image.open(io.BytesIO(response.content))
        assert exact.size == (64, 128)
        expected = np.asarray(read_frame(original, timestamps[2]))
        assert np.mean(np.abs(np.asarray(exact).astype(float) - expected)) < 5
