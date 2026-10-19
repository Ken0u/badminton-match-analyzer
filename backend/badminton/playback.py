"""Disposable browser media; source frames and annotations remain authoritative."""

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from fractions import Fraction
from functools import lru_cache
from uuid import uuid4

from .av_runtime import open_media
from .orientation import frame_rotation
from .video import resolve_source, timestamps_for, write_json

VERSION = 2
TIMING_TOLERANCE_S = 0.00002
DURATION_TOLERANCE_S = 0.0011  # MP4 movie duration is rounded to milliseconds.


@lru_cache(maxsize=16)
def _digest(path, size, mtime_ns):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def digest(path):
    stat = path.stat()
    return _digest(path, stat.st_size, stat.st_mtime_ns)


def _context(video, data):
    return {
        "version": VERSION,
        "source_sha256": video["sha256"],
        "timestamps_sha256": digest(data / video["id"] / "timestamps.json"),
        "source_start_s": video["source_start_s"],
        "time_base": video["time_base"],
        "width": video["width"],
        "height": video["height"],
        "rotation": video.get("rotation", 0),
        "frame_count": video["frame_count"],
        "duration_s": video["duration_s"],
        "audio": video["audio"],
    }


def cached_playback(video, root, data):
    """Return only a complete, source-matching, byte-verified proxy."""
    resolve_source(video, root)
    folder = data / video["id"] / "playback"
    try:
        receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
        path = folder / "browser.mp4"
        if (
            receipt["context"] == _context(video, data)
            and receipt["frame_mapping"] == "identity"
            and digest(path) == receipt["proxy_sha256"]
        ):
            return path, receipt
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _validate(path, video, times):
    maximum_error = 0.0
    count = 0
    with open_media(str(path)) as container:
        stream = container.streams.video[0]
        if stream.codec_context.name != "h264":
            raise ValueError("Playback video must use H.264")
        if bool(container.streams.audio) != video["audio"]:
            raise ValueError("Playback did not preserve source audio availability")
        expected_duration = video["duration_s"]
        if (
            stream.duration is None
            or stream.start_time is None
            or container.duration is None
            or abs(
                float((stream.start_time + stream.duration) * stream.time_base)
                - expected_duration
            )
            > DURATION_TOLERANCE_S
            or abs(container.duration / 1e6 - expected_duration) > DURATION_TOLERANCE_S
        ):
            raise ValueError("Playback duration does not match the source timeline")
        width = video["width"] + video["width"] % 2
        height = video["height"] + video["height"] % 2
        for frame in container.decode(stream):
            if count >= len(times) or frame.pts is None:
                raise ValueError("Playback changed the source frame count")
            timestamp = float(frame.pts * frame.time_base)
            error = abs(timestamp - times[count])
            if not math.isfinite(timestamp) or error > TIMING_TOLERANCE_S:
                raise ValueError("Playback timestamps do not match the source timeline")
            if frame_rotation(frame) != 0 or (frame.width, frame.height) != (
                width,
                height,
            ):
                raise ValueError("Playback display orientation or dimensions changed")
            maximum_error = max(maximum_error, error)
            count += 1
    if count != len(times) or count != video["frame_count"]:
        raise ValueError("Playback is missing source frames")
    return maximum_error


def _set_packet_durations(source, destination, video, times):
    """Retain encoded samples and their PTS while fixing MP4 sample durations.

    Nominal encoder frame rates do not describe variable-rate presentation gaps.
    No B frames are encoded, so each packet's decode and presentation order agree.
    """
    count = 0
    with (
        open_media(str(source)) as original,
        open_media(str(destination), "w", options={"movflags": "+faststart"}) as output,
    ):
        streams = {
            stream.index: output.add_stream_from_template(stream, opaque=True)
            for stream in original.streams
        }
        for stream in original.streams:
            streams[stream.index].time_base = stream.time_base
        for packet in original.demux():
            if packet.pts is None or packet.dts is None:
                continue
            if packet.stream.type == "video":
                if (
                    count >= len(times)
                    or packet.dts != packet.pts
                    or abs(float(packet.pts * packet.time_base) - times[count])
                    > TIMING_TOLERANCE_S
                ):
                    raise ValueError(
                        "Encoded playback timestamps or source frame order changed"
                    )
                end = (
                    times[count + 1] if count + 1 < len(times) else video["duration_s"]
                )
                packet.duration = round(end / packet.time_base) - packet.pts
                if packet.duration <= 0:
                    raise ValueError("Playback frame duration must be positive")
                count += 1
            packet.stream = streams[packet.stream.index]
            output.mux(packet)
    if count != len(times):
        raise ValueError("Encoded playback is missing source frames")


def prepare_playback(video, root, data, progress=lambda value: None):
    existing = cached_playback(video, root, data)
    if existing:
        return existing[1]
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise ValueError("Install FFmpeg to prepare browser playback")
    source = resolve_source(video, root)
    context = _context(video, data)
    times = timestamps_for(data, video["id"])
    folder = data / video["id"] / "playback"
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f"{uuid4().hex}.mp4"
    remuxed = folder / f"{uuid4().hex}.mp4"
    time_base = Fraction(video["time_base"])
    origin = format(video["source_start_s"], ".12f")
    # Explicit timestamp passthrough and encoder time base avoid CFR frame
    # duplication. Validate the decoded result before publishing its receipt.
    # https://ffmpeg.org/ffmpeg.html#Advanced-Video-options
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
        "-map",
        "0:a:0?",
        "-vf",
        f"setpts=PTS-{origin}/TB,setsar=1,scale=ceil(iw/2)*2:ceil(ih/2)*2",
        "-af",
        f"asetpts=PTS-{origin}/TB,atrim=start=0",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-bf",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-fps_mode",
        "passthrough",
        "-enc_time_base",
        f"{time_base.numerator}:{time_base.denominator}",
        "-video_track_timescale",
        str(time_base.denominator),
        "-g",
        "50",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-map_metadata",
        "-1",
        "-metadata:s:v:0",
        "rotate=0",
        "-avoid_negative_ts",
        "disabled",
        "-t",
        str(video["duration_s"]),
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(temporary),
    ]
    try:
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
                        progress(min(0.9, max(0, seconds / video["duration_s"] * 0.9)))
                if process.wait() != 0:
                    raise ValueError(
                        "Could not prepare playback. Check FFmpeg codec support and available storage."
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
        progress(0.92)
        _set_packet_durations(temporary, remuxed, video, times)
        error = _validate(remuxed, video, times)
        # Source/timing changes during encoding invalidate this result too.
        resolve_source(video, root)
        if context != _context(video, data):
            raise ValueError(
                "Video metadata or timestamps changed during playback preparation"
            )
        receipt = {
            "context": context,
            "frame_mapping": "identity",
            "max_timestamp_error_s": error,
            "proxy_sha256": digest(remuxed),
            "duration_s": video["duration_s"],
            "audio_codec": "aac" if video["audio"] else None,
            "video_codec": "h264",
        }
        remuxed.replace(folder / "browser.mp4")
        write_json(folder / "receipt.json", receipt)
        progress(1)
        return receipt
    finally:
        temporary.unlink(missing_ok=True)
        remuxed.unlink(missing_ok=True)
