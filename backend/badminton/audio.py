"""Optional acoustic navigation cues, aligned by source PTS, never hit labels."""

import math

import av
import numpy as np

from .video import resolve_source

RATE = 24000
FFT_SIZE = 512
HOP = 240
METHOD = "high-frequency positive spectral flux v1"


def transient_peaks(samples, start_s, rate=RATE):
    """Rank isolated onsets in one continuous PCM span; no impact semantics.

    The robust threshold is fixed at median + six median absolute deviations.
    Time is the analysis-window center, not an estimate of sound propagation
    delay or of the exact racket contact. Never concatenate timestamp gaps.
    """
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim != 1 or not np.isfinite(samples).all():
        raise ValueError("Audio samples must be a finite mono array")
    if rate != RATE or not math.isfinite(start_s):
        raise ValueError("Audio cues require timestamped 24 kHz PCM")
    if len(samples) < FFT_SIZE + HOP * 2:
        return []
    windows = np.lib.stride_tricks.sliding_window_view(samples, FFT_SIZE)[::HOP]
    spectrum = np.abs(np.fft.rfft(windows * np.hanning(FFT_SIZE), axis=1))
    band = np.fft.rfftfreq(FFT_SIZE, 1 / rate) >= 2000
    flux = np.maximum(np.diff(spectrum[:, band], axis=0), 0).sum(axis=1)
    median = float(np.median(flux))
    mad = float(np.median(np.abs(flux - median)))
    threshold = max(median + 6 * mad, 1e-8)
    selected = []
    # Stable tie handling makes repeated analysis reproducible.
    for index in np.argsort(-flux, kind="stable"):
        value = float(flux[index])
        if value <= threshold:
            break
        time_s = start_s + ((int(index) + 1) * HOP + FFT_SIZE / 2) / rate
        if any(abs(time_s - peak["time_s"]) < 0.12 for peak in selected):
            continue
        selected.append(
            {
                "time_s": time_s,
                "flux": value,
                "threshold": threshold,
                "strength_ratio": value / threshold,
            }
        )
    return sorted(selected, key=lambda peak: peak["time_s"])


def extract_audio_cues(video, root, start_s, end_s):
    """Decode at most a baseline window; missing/unusable audio is explicit.

    Audio PTS is rebased by the imported *video* origin. Resampling preserves
    PTS; absent timestamps are never replaced by sample counts or frame rate.
    Source validation errors still fail the job, even though audio is optional.
    """
    if not (
        math.isfinite(start_s)
        and math.isfinite(end_s)
        and 0 <= start_s < end_s
        and end_s - start_s <= 120 + 1e-5
    ):
        raise ValueError("Choose an audio window of at most 120 seconds")
    path = resolve_source(video, root)
    result = {
        "method": METHOD,
        "status": "missing",
        "sample_rate": RATE,
        "start_time_s": start_s,
        "end_time_s": end_s,
        "peaks": [],
        "continuous_spans": 0,
    }
    segments = []
    chunks = []
    segment_start = None
    expected = None
    timed_samples = 0
    untimed_frames = 0

    def finish():
        nonlocal chunks, segment_start, expected
        if chunks:
            segments.append((segment_start, np.concatenate(chunks)))
        chunks, segment_start, expected = [], None, None

    def consume(frame):
        nonlocal segment_start, expected, timed_samples, untimed_frames
        if frame.pts is None:
            untimed_frames += 1
            finish()
            return
        t = float(frame.pts * frame.time_base) - video["source_start_s"]
        samples = frame.to_ndarray().reshape(-1)
        first = max(0, math.ceil((start_s - t) * RATE - 1e-6))
        last = min(len(samples), math.ceil((end_s - t) * RATE - 1e-6))
        if first >= last:
            return
        t += first / RATE
        samples = samples[first:last]
        if not np.isfinite(samples).all():
            raise ValueError("Nonfinite audio samples")
        if expected is not None and abs(t - expected) > 1.5 / RATE:
            finish()
        if segment_start is None:
            segment_start = t
        chunks.append(samples)
        timed_samples += len(samples)
        expected = t + len(samples) / RATE

    try:
        with av.open(str(path)) as container:
            if not container.streams.audio:
                return result
            stream = container.streams.audio[0]
            result["stream_index"] = stream.index
            target = start_s + video["source_start_s"] - 0.1
            container.seek(int(target / stream.time_base), stream=stream, backward=True)
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=RATE)
            decoded_duration = 0
            for frame in container.decode(stream):
                decoded_duration += frame.samples / frame.sample_rate
                if decoded_duration > end_s - start_s + 4:
                    break
                if frame.pts is None:
                    untimed_frames += 1
                    finish()
                    # Do not let the resampler infer missing timestamps.
                    resampler = av.AudioResampler(
                        format="fltp", layout="mono", rate=RATE
                    )
                    continue
                if float(frame.pts * frame.time_base) > (
                    end_s + video["source_start_s"] + 0.1
                ):
                    break
                for converted in resampler.resample(frame):
                    consume(converted)
            for converted in resampler.resample(None):
                consume(converted)
        finish()
    except (av.error.FFmpegError, ValueError) as exc:
        # Unsupported/corrupt audio must not invalidate visual-only suggestions.
        # Do not emit cues from a partially failed decoder.
        result.update(status="unavailable", reason=type(exc).__name__)
        return result
    result["continuous_spans"] = len(segments)
    result["timed_samples"] = timed_samples
    result["untimed_frames"] = untimed_frames
    result["status"] = "available" if timed_samples else "unavailable"
    for t, samples in segments:
        result["peaks"].extend(transient_peaks(samples, t))
    result["peaks"].sort(key=lambda peak: peak["time_s"])
    return result
