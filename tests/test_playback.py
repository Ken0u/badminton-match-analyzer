"""Actual transcoding must retain every source frame and its presentation time."""

import io
import shutil
import time
from fractions import Fraction
from unittest.mock import patch

import av
import numpy as np
import pytest
from badminton.api import create_app
from badminton.ingest import inspect_video
from badminton.playback import cached_playback, prepare_playback
from badminton.storage import Store
from badminton.video import SourceChangedError, iter_frames, timestamps_for
from fastapi.testclient import TestClient
from test_orientation import write_rotated_video

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is required")


def context(tmp_path, rotation=0):
    path = write_rotated_video(tmp_path / "source.mp4", rotation)
    store = Store(tmp_path / "processed")
    video = inspect_video(path, "doubles", store, tmp_path)
    return store, video, path


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_real_proxy_keeps_vfr_native_frames_orientation_and_original_bytes(
    tmp_path, rotation
):
    store, video, source = context(tmp_path, rotation)
    before = source.read_bytes()
    annotations = store.annotations(video["id"])
    times = timestamps_for(store.data, video["id"])
    receipt = prepare_playback(video, tmp_path, store.data)
    path, cached = cached_playback(video, tmp_path, store.data)
    assert cached == receipt
    assert receipt["frame_mapping"] == "identity"
    assert receipt["max_timestamp_error_s"] < 0.00002
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        assert stream.codec_context.name == "h264"
        assert stream.codec_context.format.name == "yuv420p"
        proxy = list(container.decode(stream))
    originals = list(iter_frames(video, tmp_path, times, 0, len(times)))
    assert len(proxy) == len(originals) == 4
    assert [float(f.pts * f.time_base) for f in proxy] == pytest.approx(times)
    assert [(f.width, f.height) for f in proxy] == [
        (video["width"], video["height"])
    ] * 4
    for frame, (_, _, original) in zip(proxy, originals, strict=True):
        assert frame.rotation == 0
        expected = original.to_ndarray(format="rgb24").astype(float)
        assert np.mean(np.abs(frame.to_ndarray(format="rgb24") - expected)) < 8
    assert source.read_bytes() == before
    assert store.annotations(video["id"]) == annotations
    with patch("badminton.playback.subprocess.Popen") as encode:
        assert prepare_playback(video, tmp_path, store.data) == receipt
        encode.assert_not_called()


def test_changed_proxy_or_timeline_cannot_be_served_as_valid_cache(tmp_path):
    store, video, source = context(tmp_path)
    prepare_playback(video, tmp_path, store.data)
    path, _ = cached_playback(video, tmp_path, store.data)
    path.write_bytes(b"damaged")
    assert cached_playback(video, tmp_path, store.data) is None
    prepare_playback(video, tmp_path, store.data)
    timeline = store.data / video["id"] / "timestamps.json"
    original = timeline.read_bytes()
    timeline.write_bytes(b"[0, 0.05, 0.12, 0.16]")
    assert cached_playback(video, tmp_path, store.data) is None
    with pytest.raises(ValueError, match="timestamps"):
        prepare_playback(video, tmp_path, store.data)
    timeline.write_bytes(original)
    assert cached_playback(video, tmp_path, store.data) is not None
    source.write_bytes(b"changed source")
    with pytest.raises(SourceChangedError):
        cached_playback(video, tmp_path, store.data)


def test_failed_transcode_never_publishes_partial_proxy(tmp_path):
    store, video, _ = context(tmp_path)
    with patch(
        "badminton.playback._validate", side_effect=ValueError("invalid timing")
    ):
        with pytest.raises(ValueError, match="invalid timing"):
            prepare_playback(video, tmp_path, store.data)
    folder = store.data / video["id"] / "playback"
    assert list(folder.iterdir()) == []


def test_nonbrowser_codec_nonzero_clock_odd_size_and_delayed_audio(tmp_path):
    source = tmp_path / "lossless.mkv"
    with av.open(str(source), "w") as container:
        video_stream = container.add_stream("ffv1", rate=25)
        video_stream.width, video_stream.height = 127, 65
        video_stream.pix_fmt = "bgr0"
        video_stream.time_base = Fraction(1, 1000)
        video_stream.codec_context.time_base = Fraction(1, 1000)
        audio_stream = container.add_stream("pcm_s16le", rate=48000)
        audio_stream.layout = "mono"
        for index, pts in enumerate((3000, 3040, 3120, 3160)):
            frame = av.VideoFrame.from_ndarray(
                np.full((65, 127, 3), 40 + index * 40, dtype=np.uint8), format="rgb24"
            )
            frame.pts, frame.time_base = pts, Fraction(1, 1000)
            for packet in video_stream.encode(frame):
                container.mux(packet)
        # Audio starts 80 ms after the first video frame, not at source time 0.
        samples = (12000 * np.sin(np.arange(5760) * 2 * np.pi * 440 / 48000)).astype(
            np.int16
        )
        frame = av.AudioFrame.from_ndarray(
            samples.reshape(1, -1), format="s16", layout="mono"
        )
        frame.sample_rate = 48000
        frame.pts, frame.time_base = 147840, Fraction(1, 48000)
        for packet in audio_stream.encode(frame):
            container.mux(packet)
        for stream in (video_stream, audio_stream):
            for packet in stream.encode():
                container.mux(packet)
    store = Store(tmp_path / "processed")
    video = inspect_video(source, "singles", store, tmp_path)
    assert video["source_start_s"] == 3 and video["audio"]
    receipt = prepare_playback(video, tmp_path, store.data)
    path, _ = cached_playback(video, tmp_path, store.data)
    assert receipt["audio_codec"] == "aac"
    with av.open(str(path)) as container:
        frames = list(container.decode(video=0))
        assert len(frames) == 4
        assert [(frame.width, frame.height) for frame in frames] == [(128, 66)] * 4
        assert [float(f.pts * f.time_base) for f in frames] == pytest.approx(
            [0, 0.04, 0.12, 0.16]
        )
    with av.open(str(path)) as container:
        audio = list(container.decode(audio=0))
        assert container.streams.audio[0].codec_context.name == "aac"
        assert audio
        assert float(audio[0].pts * audio[0].time_base) == pytest.approx(
            0.08, abs=0.025
        )
        audible = [
            float(frame.pts * frame.time_base) + int(sample) / frame.sample_rate
            for frame in audio
            for sample in np.flatnonzero(np.abs(frame.to_ndarray()[0]) > 0.05)
        ]
        assert audible and min(audible) == pytest.approx(0.08, abs=0.003)


def test_proxy_api_runs_under_shared_admission_and_keeps_reviewed_exports(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("BADMINTON_USERNAME", raising=False)
    monkeypatch.delenv("BADMINTON_PASSWORD", raising=False)
    store, video, source = context(tmp_path, 90)
    root = f"/api/videos/{video['id']}"
    with TestClient(create_app(tmp_path, store.data)) as client:
        doc = client.get(root + "/annotations").json()
        doc["events"] = [
            {
                "id": "reviewed",
                "rally_id": "R1",
                "kind": "shot",
                "frame": 2,
                "family": "drop",
                "side": "backhand",
                "status": "corrected",
            }
        ]
        assert client.put(root + "/annotations", json=doc).status_code == 200
        before = client.get(root + "/export?format=json").content
        csv = client.get(root + "/export?format=csv").content
        assert client.get(root + "/playback").json()["status"] == "missing"
        assert client.get(root + "/playback/media").status_code == 404
        busy = {
            "id": "other",
            "kind": "tracking",
            "status": "running",
            "video_id": video["id"],
        }
        store.claim_job(busy)
        assert client.post(root + "/playback").status_code == 409
        store.put_job(busy | {"status": "completed"})
        response = client.post(root + "/playback")
        assert response.status_code == 202
        for _ in range(300):
            job = next(j for j in store.jobs() if j["id"] == response.json()["id"])
            if job["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)
        assert job["status"] == "completed", job
        status = client.get(root + "/playback").json()
        assert status["status"] == "ready"
        response = client.get(status["url"])
        assert response.headers["content-type"] == "video/mp4"
        with av.open(io.BytesIO(response.content)) as container:
            assert len(list(container.decode(video=0))) == video["frame_count"]
        partial = client.get(status["url"], headers={"Range": "bytes=0-99"})
        assert partial.status_code == 206 and len(partial.content) == 100
        assert client.get(root + "/media").content == source.read_bytes()
        assert client.get(root + "/export?format=json").content == before
        assert client.get(root + "/export?format=csv").content == csv
