import hashlib
import wave
from fractions import Fraction
from types import SimpleNamespace

import av
import numpy as np
import pytest
from badminton.audio import RATE, extract_audio_cues, transient_peaks
from badminton.video import SourceChangedError


def source(path, start_s=0):
    return {
        "path": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_start_s": start_s,
    }


def test_transients_are_navigation_cues_with_scale_invariant_times():
    samples = np.zeros(RATE * 2)
    t = np.arange(240) / RATE
    samples[RATE : RATE + len(t)] = np.sin(2 * np.pi * 5000 * t) * np.hanning(len(t))
    peaks = transient_peaks(samples, 7)
    assert len(peaks) == 1
    assert peaks[0]["time_s"] == pytest.approx(8, abs=0.025)
    assert peaks[0]["strength_ratio"] > 1
    assert [p["time_s"] for p in transient_peaks(samples * 0.2, 7)] == [
        p["time_s"] for p in peaks
    ]
    assert transient_peaks(np.zeros(RATE), 0) == []
    assert transient_peaks(np.zeros(10), 0) == []
    with pytest.raises(ValueError, match="finite mono"):
        transient_peaks([float("nan")] * RATE, 0)


def test_real_pcm_decode_uses_audio_pts_and_video_origin_not_window_origin(tmp_path):
    rate = 44100
    samples = np.zeros(rate * 3, dtype=np.int16)
    t = np.arange(441) / rate
    samples[rate : rate + len(t)] = (
        16000 * np.sin(2 * np.pi * 5000 * t) * np.hanning(len(t))
    ).astype(np.int16)
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(samples.tobytes())
    # Imported video's first frame occurs 300 ms after the audio stream origin.
    result = extract_audio_cues(source(path, 0.3), tmp_path, 0.4, 1.5)
    assert result["status"] == "available"
    assert result["continuous_spans"] == 1
    assert result["timed_samples"] == pytest.approx(RATE * 1.1, abs=2)
    assert len(result["peaks"]) == 1
    assert result["peaks"][0]["time_s"] == pytest.approx(0.7, abs=0.025)
    assert extract_audio_cues(source(path), tmp_path, 0, 0.5)["peaks"] == []
    path.write_bytes(b"changed source")
    with pytest.raises(SourceChangedError):
        extract_audio_cues(source(path) | {"sha256": "old"}, tmp_path, 0, 1)


def test_silent_video_has_explicit_missing_audio_and_changed_source_still_fails(
    tmp_path,
):
    path = tmp_path / "silent.mp4"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("mpeg4", rate=25)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        for index in range(5):
            frame = av.VideoFrame.from_ndarray(np.zeros((48, 64, 3), np.uint8), "rgb24")
            frame.pts = index
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    result = extract_audio_cues(source(path), tmp_path, 0, 0.2)
    assert result["status"] == "missing" and result["peaks"] == []
    for start, end in [(0, 121), (-1, 1), (1, 0), (0, float("nan"))]:
        with pytest.raises(ValueError, match="120 seconds"):
            extract_audio_cues(source(path), tmp_path, start, end)


@pytest.mark.parametrize(
    "discontinuity", ["gap", "missing_pts", "backward", "nonfinite"]
)
def test_audio_spans_are_not_concatenated_across_bad_timestamps(
    tmp_path, monkeypatch, discontinuity
):
    path = tmp_path / "timestamp-fixture"
    path.write_bytes(b"synthetic decoded-frame fixture")
    frames = []
    for index in range(12):
        pcm = np.zeros((1, 1024), dtype=np.float32)
        if discontinuity == "nonfinite" and index == 6:
            pcm[0, 0] = float("nan")
        frame = av.AudioFrame.from_ndarray(pcm, format="fltp", layout="mono")
        frame.sample_rate = RATE
        frame.time_base = Fraction(1, RATE)
        frame.pts = index * 1024
        if index >= 6:
            if discontinuity == "gap":
                frame.pts += RATE // 4
            elif discontinuity == "backward":
                frame.pts -= 6 * 1024
            elif discontinuity == "missing_pts" and index == 6:
                frame.pts = None
        frames.append(frame)

    class Container:
        streams = SimpleNamespace(
            audio=[SimpleNamespace(index=0, time_base=Fraction(1, RATE))]
        )

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def seek(self, *_args, **_kwargs):
            pass

        def decode(self, _stream):
            return iter(frames)

    monkeypatch.setattr(av, "open", lambda *_: Container())
    result = extract_audio_cues(source(path), tmp_path, 0, 1)
    if discontinuity == "nonfinite":
        assert result["status"] == "unavailable" and result["peaks"] == []
        return
    assert result["status"] == "available"
    assert result["continuous_spans"] == 2
    assert result["peaks"] == []
    if discontinuity == "missing_pts":
        assert result["untimed_frames"] == 1
