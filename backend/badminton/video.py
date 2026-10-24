"""Source validation and presentation-time aligned frame access."""

import bisect
import json
import math
import operator
import os
import tempfile
import time
from contextlib import suppress
from pathlib import Path

from .av_runtime import open_media
from .file_cache import FileChangedError, file_digest, timestamp_tuple
from .orientation import orient_frame

_WINDOWS = os.name == "nt"


class SourceChangedError(ValueError):
    pass


def resolve_source(video, root):
    root = root.resolve()
    path = (root / video["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise FileNotFoundError("Video source is unavailable")
    try:
        checksum = file_digest(path)
    except FileChangedError as error:
        raise SourceChangedError(str(error)) from error
    if checksum != video["sha256"]:
        raise SourceChangedError(
            "Video source changed since import. Import the changed file before reviewing or processing it."
        )
    return path


def timestamps_for(data, video_id):
    path = data / video_id / "timestamps.json"
    return timestamp_tuple(path)


def validate_range(video, times, start, end, max_seconds=120):
    if not 0 <= start < end <= len(times):
        raise ValueError("Choose a non-empty frame range within the video")
    end_time = times[end] if end < len(times) else video["duration_s"]
    if end_time - times[start] > max_seconds + 0.00001:
        raise ValueError(f"Baseline runs are limited to {max_seconds} seconds")


def seconds_to_frames(video, times, start, duration):
    if (
        not math.isfinite(start)
        or not math.isfinite(duration)
        or start < 0
        or duration <= 0
        or duration > 120
    ):
        raise ValueError(
            "Choose a finite, positive clip up to 120 seconds within the video"
        )
    first = bisect.bisect_left(times, start)
    last = bisect.bisect_left(times, start + duration)
    validate_range(video, times, first, last)
    return first, last


def iter_frames(video, root, times, start, end):
    """Yield an exact native range, rejecting incomplete decoder output.

    Completeness is checked on normal iteration, never in a finalizer: a caller
    can intentionally close a partial read without turning cancellation into an
    input failure. The existing media context still owns decoder teardown.
    """
    try:
        start, end = operator.index(start), operator.index(end)
    except TypeError as error:
        raise ValueError("Choose integer bounds for the native frame range") from error
    if not 0 <= start < end <= len(times):
        raise ValueError("Choose a non-empty frame range within the video")
    expected = start
    with open_media(str(resolve_source(video, root))) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        target = times[start] + video["source_start_s"]
        container.seek(int(target / stream.time_base), stream=stream, backward=True)
        for frame in container.decode(stream):
            if frame.pts is None:
                raise SourceChangedError(
                    "Decoded source frame has no presentation timestamp"
                )
            t = float(frame.pts * stream.time_base) - video["source_start_s"]
            index = bisect.bisect_left(times, t - 0.00001)
            if index < start and expected == start:
                continue
            if index >= end:
                break
            if index != expected:
                raise SourceChangedError(
                    f"Decoded native frame sequence is incomplete or out of order: "
                    f"expected frame {expected}, received {index}. Retry processing or reimport the source."
                )
            if not math.isfinite(times[index]) or abs(times[index] - t) > 0.00002:
                raise SourceChangedError(
                    "Decoded timestamps do not match the imported source"
                )
            display_frame = orient_frame(
                frame, expected_rotation=video.get("rotation", 0)
            )
            if (display_frame.width, display_frame.height) != (
                video["width"],
                video["height"],
            ):
                raise SourceChangedError(
                    "Decoded display dimensions do not match the imported source. Reimport the video."
                )
            expected += 1
            yield index, times[index], display_frame
            if expected == end:
                break
        if expected != end:
            raise SourceChangedError(
                f"Could not decode the complete native frame range: expected frame "
                f"{expected} before {end}. Retry processing or reimport the source."
            )


def _replace_json(temporary, path):
    # Windows readers may briefly hold the destination without delete sharing.
    # Access denied (5) is also used for persistent ACL failures: never hide it.
    delays = (0.01, 0.02, 0.04, 0.08, 0.1)
    for attempt in range(len(delays) + 1):
        try:
            temporary.replace(path)
            return
        except OSError as error:
            if (
                not _WINDOWS
                or getattr(error, "winerror", None) not in (5, 32, 33)
                or attempt == len(delays)
            ):
                raise
            time.sleep(delays[attempt])


def write_json(path, document):
    serialized = json.dumps(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(name)
    try:
        try:
            output = os.fdopen(descriptor, "w", encoding="utf-8")
        except BaseException:
            with suppress(OSError):
                os.close(descriptor)
            raise
        with output:
            output.write(serialized)
        _replace_json(temporary, path)
    except BaseException:
        # Preserve the publication error even if an external handle prevents
        # removal of our file. A successful replace already consumed it.
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise
