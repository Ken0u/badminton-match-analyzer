"""Verified plain H.264 rally clips from immutable, source-audited plans."""

import copy
import hashlib
import itertools
import json
import math
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

import av
import cv2
import numpy as np

from .av_runtime import open_media
from .orientation import frame_rotation, orient_frame
from .rally_export import _canonical, _digest, plan_rally_exports
from .video import resolve_source

TIMING_TOLERANCE_S = 0.00002
DURATION_TOLERANCE_S = 0.0011
AUDIO_PROBE_SAMPLES = 4096


def _fresh_plan(store, plan, root):
    try:
        fresh = plan_rally_exports(
            store, plan["source"]["id"], plan["annotation_revision"], root
        )
        if _canonical(plan) != _canonical(fresh):
            raise ValueError(
                "Export plan is edited or stale; create a new audited plan"
            )
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError("Invalid reviewed rally export plan") from error
    return fresh


def _output_directory(output, data):
    path = Path(output).absolute()
    if ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Export output cannot traverse directories or symlinks")
    if path.resolve().is_relative_to(Path(data).resolve()):
        raise ValueError("Write rally videos outside application data storage")
    if not path.parent.is_dir():
        raise ValueError("Export output parent must already exist")
    path.mkdir(exist_ok=False)
    return path


def _audio_array(frame):
    pixels = frame.to_ndarray()
    channels = len(frame.layout.channels)
    if not frame.format.is_planar:
        pixels = pixels.reshape(-1, channels).T
    if np.issubdtype(pixels.dtype, np.integer):
        info = np.iinfo(pixels.dtype)
        if info.min == 0:
            return (pixels.astype(np.float32) - 128) / 128
        return pixels.astype(np.float32) / (float(info.max) + 1)
    return pixels.astype(np.float32)


def _audio_context(source, start_s, end_s):
    """Inspect actual samples, retaining bounded first/last waveform probes."""
    probes, tail = [], []
    first_count = tail_count = 0
    first = last = None
    rate = channels = None
    clock_tolerance = 0.0
    with open_media(str(source)) as container:
        if not container.streams.audio:
            return {
                "source_available": False,
                "available": False,
                "reason": "no_source_audio",
            }, []
        stream = container.streams.audio[0]
        for frame in container.decode(stream):
            if frame.pts is None or not frame.sample_rate:
                raise ValueError("Source audio has unavailable sample timing")
            if rate is None:
                rate, channels = frame.sample_rate, len(frame.layout.channels)
            if rate != frame.sample_rate or channels != len(frame.layout.channels):
                raise ValueError("Source audio format changes within the source")
            clock_tolerance = max(clock_tolerance, float(frame.time_base), 1 / rate)
            timestamp = float(frame.pts * frame.time_base)
            left = max(0, math.ceil((start_s - timestamp) * rate - 0.00001))
            right = min(frame.samples, math.ceil((end_s - timestamp) * rate - 0.00001))
            if right <= left:
                continue
            offset = timestamp + left / rate - start_s
            finish = timestamp + right / rate - start_s
            if (
                last is not None
                and offset < last - clock_tolerance - TIMING_TOLERANCE_S
            ):
                raise ValueError("Source audio samples overlap or run backwards")
            first = offset if first is None else first
            last = finish
            samples = _audio_array(frame)[:, left:right]
            if first_count < AUDIO_PROBE_SAMPLES:
                head = samples[:, : AUDIO_PROBE_SAMPLES - first_count].copy()
                probes.append((offset, head))
                first_count += head.shape[1]
            tail.append((offset, samples.copy()))
            tail_count += samples.shape[1]
            while tail_count > AUDIO_PROBE_SAMPLES:
                time, data = tail[0]
                remove = min(data.shape[1], tail_count - AUDIO_PROBE_SAMPLES)
                tail_count -= remove
                if remove == data.shape[1]:
                    tail.pop(0)
                else:
                    tail[0] = (time + remove / rate, data[:, remove:])
    if first is None:
        return {
            "source_available": True,
            "available": False,
            "reason": "no_audio_overlap",
        }, []
    return {
        "source_available": True,
        "available": True,
        "reason": None,
        "codec": "aac",
        "sample_rate": rate,
        "channels": channels,
        "expected_start_s": first,
        "expected_end_s_exclusive": last,
        "source_clock_tolerance_s": clock_tolerance,
        "priming": "AAC may decode leading/trailing padding; sample timing and waveform are verified against source samples.",
    }, probes + tail


def _run(command, progress):
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=errors, text=True
        )
        try:
            for line in process.stdout:
                if line.startswith("out_time_us="):
                    try:
                        seconds = int(line.split("=", 1)[1]) / 1e6
                    except ValueError:
                        continue
                    progress(seconds)
            if process.wait() != 0:
                raise ValueError(
                    "Could not encode rally video; check FFmpeg codecs and storage"
                )
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            process.stdout.close()


def _remux(source, destination, times, duration, movie_timescale):
    count = 0
    with (
        open_media(str(source)) as original,
        open_media(
            str(destination),
            "w",
            options={"movflags": "+faststart", "movie_timescale": str(movie_timescale)},
        ) as output,
    ):
        streams = {
            s.index: output.add_stream_from_template(s, opaque=True)
            for s in original.streams
        }
        for stream in original.streams:
            streams[stream.index].time_base = stream.time_base
        for packet in original.demux():
            if packet.pts is None or packet.dts is None:
                continue
            if packet.stream.type == "video":
                if (
                    count >= len(times)
                    or packet.pts != packet.dts
                    or abs(float(packet.pts * packet.time_base) - times[count])
                    > TIMING_TOLERANCE_S
                ):
                    raise ValueError("Encoder changed native frame order or PTS")
                endpoint = times[count + 1] if count + 1 < len(times) else duration
                packet.duration = round(endpoint / packet.time_base) - packet.pts
                if packet.duration <= 0:
                    raise ValueError("Export video sample duration must be positive")
                count += 1
            packet.stream = streams[packet.stream.index]
            output.mux(packet)
    if count != len(times):
        raise ValueError("Encoder omitted native source frames")


def _verify_audio(path, context, probes):
    with open_media(str(path)) as container:
        if bool(container.streams.audio) != context["available"]:
            raise ValueError("Export changed source audio availability in this range")
        if not context["available"]:
            return context
        stream = container.streams.audio[0]
        rate = context["sample_rate"]
        tolerance = max(DURATION_TOLERANCE_S, context["source_clock_tolerance_s"])
        if (
            stream.codec_context.name != "aac"
            or stream.codec_context.sample_rate != rate
            or len(stream.codec_context.layout.channels) != context["channels"]
        ):
            raise ValueError("Export audio codec, sample rate or channels changed")
        if stream.start_time is None or stream.duration is None:
            raise ValueError("Export audio timing is unavailable")
        start = float(stream.start_time * stream.time_base)
        end = float((stream.start_time + stream.duration) * stream.time_base)
        if (
            start > context["expected_start_s"] + tolerance
            or start < context["expected_start_s"] - 1024 / rate - tolerance
            or abs(end - context["expected_end_s_exclusive"]) > tolerance
        ):
            raise ValueError("Export audio offset or final sample duration changed")
        measured = [np.zeros_like(data) for _, data in probes]
        covered = [np.zeros(data.shape[1], dtype=bool) for _, data in probes]
        for frame in container.decode(stream):
            if frame.pts is None:
                raise ValueError("Export audio has unavailable sample PTS")
            timestamp = float(frame.pts * frame.time_base)
            data = _audio_array(frame)
            for index, (offset, expected) in enumerate(probes):
                # All indices refer to the same source-relative audio sample clock.
                shift = round((timestamp - offset) * rate)
                left, right = (
                    max(0, shift),
                    min(expected.shape[1], shift + data.shape[1]),
                )
                if right > left:
                    measured[index][:, left:right] = data[
                        :, left - shift : right - shift
                    ]
                    covered[index][left:right] = True
        errors = []
        for (_, expected), actual, coverage in zip(probes, measured, covered):
            if not coverage.all():
                raise ValueError("Export is missing source audio samples")
            error = float(np.sqrt(np.mean((expected - actual) ** 2)))
            rms = float(np.sqrt(np.mean(expected**2)))
            if error > max(0.05, rms * 0.7):
                raise ValueError(
                    "Export audio waveform or source-relative timing changed"
                )
            errors.append(error)
    return context | {
        "stream_start_s": start,
        "stream_end_s_exclusive": end,
        "max_probe_rmse": max(errors, default=0.0),
    }


def _verify(
    path, source, video, interval, times, duration, audio, probes, overlay=None
):
    count = 0
    maximum_error = maximum_pixel_error = maximum_unmasked_error = 0.0
    unmasked_pixels = 0
    with open_media(str(path)) as encoded, open_media(str(source)) as original:
        stream = encoded.streams.video[0]
        if (
            stream.codec_context.name != "h264"
            or stream.start_time != 0
            or stream.duration is None
            or encoded.duration is None
        ):
            raise ValueError("Export must be timed H.264 MP4 starting at zero")
        if (
            abs(float(stream.duration * stream.time_base) - duration)
            > TIMING_TOLERANCE_S
            or abs(encoded.duration / 1e6 - duration) > DURATION_TOLERANCE_S
        ):
            raise ValueError("Export packet or container endpoint changed")
        native = itertools.islice(
            original.decode(video=0),
            interval["start_frame"],
            interval["end_frame_exclusive"],
        )
        for frame, expected in itertools.zip_longest(encoded.decode(stream), native):
            if (
                frame is None
                or expected is None
                or count >= len(times)
                or frame.pts is None
            ):
                raise ValueError("Export changed native source frame count")
            error = abs(float(frame.pts * frame.time_base) - times[count])
            if (
                error > TIMING_TOLERANCE_S
                or frame_rotation(frame) != 0
                or (frame.width, frame.height)
                != (
                    video["width"] + video["width"] % 2,
                    video["height"] + video["height"] % 2,
                )
            ):
                raise ValueError("Export frame PTS, orientation or dimensions changed")
            expected = orient_frame(
                expected, expected_rotation=video.get("rotation", 0)
            ).to_ndarray(format="rgb24")
            original_pixels = expected
            mask = np.zeros(expected.shape[:2], dtype=bool)
            if overlay is not None:
                expected, mask, _ = overlay.draw(
                    expected, interval["start_frame"] + count
                )
            actual = frame.to_ndarray(format="rgb24")[
                : video["height"], : video["width"]
            ]
            # Compare displayed source pixels after the same unavoidable 4:2:0
            # chroma reduction used by browser-compatible H.264.
            padded = np.pad(
                expected, ((0, video["height"] % 2), (0, video["width"] % 2), (0, 0))
            )
            reference = (
                av.VideoFrame.from_ndarray(padded, format="rgb24")
                .reformat(format="yuv420p")
                .to_ndarray(format="rgb24")[: video["height"], : video["width"]]
            )
            pixel_error = float(
                np.abs(reference.astype(float) - actual.astype(float)).mean()
            )
            if pixel_error > 8:
                raise ValueError(
                    "Export pixels differ from the display-oriented source frame"
                )
            if overlay is not None:
                # Account for chroma subsampling and H.264 blocks next to a
                # documented overlay region while checking source-only pixels.
                guard = cv2.dilate(
                    mask.astype(np.uint8), np.ones((33, 33), np.uint8)
                ).astype(bool)
                if (~guard).any():
                    source_reference = (
                        av.VideoFrame.from_ndarray(
                            np.pad(
                                original_pixels,
                                (
                                    (0, video["height"] % 2),
                                    (0, video["width"] % 2),
                                    (0, 0),
                                ),
                            ),
                            format="rgb24",
                        )
                        .reformat(format="yuv420p")
                        .to_ndarray(format="rgb24")[: video["height"], : video["width"]]
                    )
                    unmasked_error = float(
                        np.abs(source_reference.astype(float) - actual.astype(float))[
                            ~guard
                        ].mean()
                    )
                    if unmasked_error > 8:
                        raise ValueError(
                            "Unmasked export pixels changed from original source"
                        )
                    maximum_unmasked_error = max(maximum_unmasked_error, unmasked_error)
                    unmasked_pixels += int((~guard).sum())
            maximum_pixel_error = max(maximum_pixel_error, pixel_error)
            maximum_error = max(maximum_error, error)
            count += 1
    with open_media(str(path)) as container:
        packets = [p for p in container.demux(video=0) if p.pts is not None]
        if len(packets) != len(times):
            raise ValueError("Export video packet count differs from source frames")
        for index, packet in enumerate(packets):
            end = times[index + 1] if index + 1 < len(times) else duration
            if (
                packet.duration <= 0
                or packet.dts != packet.pts
                or abs(float(packet.pts * packet.time_base) - times[index])
                > TIMING_TOLERANCE_S
                or abs(float((packet.pts + packet.duration) * packet.time_base) - end)
                > TIMING_TOLERANCE_S
            ):
                raise ValueError("Export video packet/sample durations changed")
    return {
        "max_timestamp_error_s": maximum_error,
        "max_pixel_mean_absolute_error": maximum_pixel_error,
        "audio": _verify_audio(path, audio, probes),
        **(
            {
                "max_unmasked_pixel_mean_absolute_error": maximum_unmasked_error,
                "unmasked_verified_pixels": unmasked_pixels,
            }
            if overlay is not None
            else {}
        ),
    }


def _encode_overlay(source, destination, video, interval, overlay, progress):
    """Encode actual oriented source frames with deterministic saved overlays."""
    time_base = Fraction(video["time_base"])
    with (
        open_media(str(source)) as original,
        open_media(str(destination), "w") as output,
    ):
        stream = output.add_stream("libx264", rate=25)
        stream.width = video["width"] + video["width"] % 2
        stream.height = video["height"] + video["height"] % 2
        stream.pix_fmt = "yuv420p"
        stream.time_base = stream.codec_context.time_base = time_base
        stream.options = {"crf": "12", "preset": "veryfast", "bf": "0"}
        origin = None
        count = interval["end_frame_exclusive"] - interval["start_frame"]
        for index, frame in enumerate(original.decode(video=0)):
            if index >= interval["end_frame_exclusive"]:
                break
            if index < interval["start_frame"]:
                continue
            if origin is None:
                origin = frame.pts * frame.time_base
            oriented = orient_frame(frame, expected_rotation=video.get("rotation", 0))
            pixels, _, _ = overlay.draw(oriented.to_ndarray(format="rgb24"), index)
            pixels = np.pad(
                pixels, ((0, video["height"] % 2), (0, video["width"] % 2), (0, 0))
            )
            rendered = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            rendered.pts = round((frame.pts * frame.time_base - origin) / time_base)
            rendered.time_base = time_base
            for packet in stream.encode(rendered):
                packet.duration = 1
                output.mux(packet)
            progress((index - interval["start_frame"] + 1) / count)
        for packet in stream.encode():
            packet.duration = 1
            output.mux(packet)


def render_rally_videos(store, plan, root, output, progress=lambda value: None):
    """Render plain eligible rally clips without changing source evidence."""
    return _render_videos(store, plan, root, output, progress)


def _render_videos(
    store, plan, root, output, progress, *, overlay=None, scope="rallies"
):
    """Shared native-media validation and atomic completion for export modes."""
    plan = copy.deepcopy(plan)
    fresh = _fresh_plan(store, plan, root)
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise ValueError("Install FFmpeg to render rally videos")
    video = fresh["source"]
    source = resolve_source(video, root)
    timeline = json.loads((store.data / video["id"] / "timestamps.json").read_bytes())
    if scope == "full" and video["audited_endpoint_s"] is None:
        raise ValueError("Full-video export requires a verified final sample duration")
    progress(0)
    folder = _output_directory(output, store.data)
    identity = folder.stat()
    try:
        staging = folder / ".staging"
        staging.mkdir()
        rallies = copy.deepcopy(plan["rallies"])
        entries = rallies
        if scope == "full":
            entries = [
                {
                    "eligible": True,
                    "source_range": {
                        "start_frame": 0,
                        "end_frame_exclusive": len(timeline),
                        "start_s": timeline[0],
                        "end_s_exclusive": video["audited_endpoint_s"],
                        "source_start_s": timeline[0] + video["source_start_s"],
                        "source_end_s_exclusive": video["audited_endpoint_s"]
                        + video["source_start_s"],
                    },
                }
            ]
            for rally in rallies:
                rally["clip"] = None
        total = max(1, sum(e["eligible"] for e in entries))
        completed = 0
        for ordinal, rally in enumerate(entries, 1):
            rally["clip"] = None
            if not rally["eligible"]:
                continue
            interval = rally["source_range"]
            duration = interval["end_s_exclusive"] - interval["start_s"]
            times = [
                t - interval["start_s"]
                for t in timeline[
                    interval["start_frame"] : interval["end_frame_exclusive"]
                ]
            ]
            audio, probes = _audio_context(
                source, interval["source_start_s"], interval["source_end_s_exclusive"]
            )
            rate = audio.get("sample_rate", 48000)
            time_base = Fraction(video["time_base"])
            movie_timescale = math.lcm(time_base.denominator, rate)
            if movie_timescale > 2147483647:
                raise ValueError("Source clocks exceed supported MP4 time scale")
            filename = f"{'full' if scope == 'full' else 'rally'}-{ordinal:06d}.mp4"
            temporary, encoded = (
                staging / f"encoded-{ordinal:06d}.mp4",
                staging / filename,
            )
            start, end = interval["source_start_s"], interval["source_end_s_exclusive"]
            command = [
                executable,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-copyts",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-vf",
                f"trim=start_frame={interval['start_frame']}:end_frame={interval['end_frame_exclusive']},setpts=PTS-STARTPTS,setsar=1,pad=ceil(iw/2)*2:ceil(ih/2)*2",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "12",
                "-bf",
                "0",
                "-pix_fmt",
                "yuv420p",
                "-fps_mode",
                "passthrough",
                "-enc_time_base:v",
                f"{time_base.numerator}:{time_base.denominator}",
                # An intermediate zero-duration final MP4 sample can become
                # invisible to its demuxer. Give it one tick here; _remux sets
                # every sample to the audited native duration before validation.
                "-bsf:v",
                "setts=duration=1",
                "-video_track_timescale",
                str(time_base.denominator),
                "-movie_timescale",
                str(movie_timescale),
            ]
            if overlay is not None:
                overlay_media = staging / f"overlay-{ordinal:06d}.mp4"
                _encode_overlay(
                    source,
                    overlay_media,
                    video,
                    interval,
                    overlay,
                    lambda fraction: progress(
                        (completed + fraction * 0.5) / total * 0.9
                    ),
                )
                command = [
                    executable,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-copyts",
                    "-i",
                    str(overlay_media),
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0",
                    "-c:v",
                    "copy",
                    "-video_track_timescale",
                    str(time_base.denominator),
                    "-movie_timescale",
                    str(movie_timescale),
                ]
            if audio["available"]:
                command += [
                    "-map",
                    "1:a:0" if overlay is not None else "0:a:0",
                    "-af",
                    f"atrim=start={start:.12f}:end={end:.12f},asetpts=PTS-({start:.12f})/TB",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-ar",
                    str(rate),
                    "-enc_time_base:a",
                    f"1:{rate}",
                ]
            else:
                command += ["-an"]
            command += [
                "-map_metadata",
                "-1",
                "-metadata:s:v:0",
                "rotate=0",
                "-avoid_negative_ts",
                "disabled",
                "-movflags",
                "+faststart",
                "-progress",
                "pipe:1",
                "-nostats",
                str(temporary),
            ]
            _run(
                command,
                lambda seconds: progress(
                    min(
                        0.9,
                        (completed + max(0, min(seconds / duration, 1))) / total * 0.9,
                    )
                ),
            )
            _remux(temporary, encoded, times, duration, movie_timescale)
            validation = _verify(
                encoded,
                source,
                video,
                interval,
                times,
                duration,
                audio,
                probes,
                overlay,
            )
            temporary.unlink()
            if overlay is not None:
                overlay_media.unlink()
            rally["clip"] = {
                "file": filename,
                "sha256": _digest(encoded),
                "video_codec": "h264",
                "frame_mapping": "identity",
                "start_frame": interval["start_frame"],
                "end_frame_exclusive": interval["end_frame_exclusive"],
                "frame_count": len(times),
                "duration_s": duration,
                "relative_timestamps_s": times,
                "source_sha256": video["sha256"],
                "annotation_revision": plan["annotation_revision"],
                "annotation_sha256": plan["annotation_sha256"],
                "display_width": video["width"],
                "display_height": video["height"],
                "encoded_width": video["width"] + video["width"] % 2,
                "encoded_height": video["height"] + video["height"] % 2,
                "padding": "black right/bottom to even dimensions; no source-pixel scaling",
                **validation,
            }
            completed += 1
            progress(completed / total * 0.95)
        if folder.stat().st_ino != identity.st_ino or folder.is_symlink():
            raise ValueError("Export output directory changed during rendering")
        manifest = {
            "schema_version": 1,
            "purpose": "annotated_videos"
            if overlay is not None
            else "reviewed_rally_videos",
            "plan_sha256": hashlib.sha256(_canonical(plan)).hexdigest(),
            "source": plan["source"],
            "annotation_revision": plan["annotation_revision"],
            "annotation_sha256": plan["annotation_sha256"],
            "annotations": plan["annotations"],
            "counts": plan["counts"],
            "rallies": rallies,
            "limitations": [
                "Plain rally clips; annotation burn-in and frontend controls are separate follow-ups.",
                "Saved unknown/predicted events and scene/camera/calibration context are provenance, not verified automatic annotation accuracy.",
                "Browser-compatible H.264 uses lossy encoding and 4:2:0 chroma; AAC may include disclosed codec padding.",
            ],
        }
        if overlay is not None:
            manifest.update(
                scope=scope,
                exports=[e["clip"] for e in entries if e["clip"] is not None],
                overlay_config=overlay.config,
                overlay_config_sha256=overlay.config_sha256,
                event_counts=overlay.event_receipt(
                    [
                        (
                            e["source_range"]["start_frame"],
                            e["source_range"]["end_frame_exclusive"],
                        )
                        for e in entries
                        if e["eligible"]
                    ]
                ),
            )
            manifest["limitations"][0] = (
                "Saved reviewed annotations burned into source-timed video; no inferred boxes, shuttle positions or exact contacts."
            )
        for rally in entries:
            if rally["clip"] is not None:
                path = staging / rally["clip"]["file"]
                if _digest(path) != rally["clip"]["sha256"]:
                    raise ValueError("Encoded export bytes changed before publication")
                path.rename(folder / path.name)
        staging.rmdir()
        progress(1)
        # Callbacks can cancel or change inputs too. Audit after the final one,
        # immediately before the completion receipt becomes visible.
        _fresh_plan(store, plan, root)
        if (
            folder.is_symlink()
            or folder.stat().st_ino != identity.st_ino
            or any(p.is_symlink() for p in folder.parents)
        ):
            raise ValueError("Export output directory changed before completion")
        for entry in entries:
            if (
                entry["clip"] is not None
                and _digest(folder / entry["clip"]["file"]) != entry["clip"]["sha256"]
            ):
                raise ValueError("Encoded export bytes changed before completion")
        with (folder / "manifest.json").open(
            "x", encoding="utf-8", newline="\n"
        ) as receipt:
            receipt.write(
                json.dumps(manifest, ensure_ascii=False, allow_nan=False, indent=2)
                + "\n"
            )
        return manifest
    except BaseException:
        if (
            not folder.is_symlink()
            and folder.exists()
            and folder.stat().st_ino == identity.st_ino
        ):
            shutil.rmtree(folder)
        raise
