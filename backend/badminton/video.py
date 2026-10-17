"""Source validation and presentation-time aligned frame access."""

import bisect
import hashlib
import json
import math
from functools import lru_cache

import av


class SourceChangedError(ValueError):
    pass


@lru_cache(maxsize=16)
def _checksum(path, size, mtime_ns):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_source(video, root):
    root = root.resolve()
    path = (root / video["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise FileNotFoundError("Video source is unavailable")
    stat = path.stat()
    if _checksum(path, stat.st_size, stat.st_mtime_ns) != video["sha256"]:
        raise SourceChangedError(
            "Video source changed since import. Import the changed file before reviewing or processing it."
        )
    return path


@lru_cache(maxsize=16)
def _times(path, size, mtime_ns):
    return tuple(json.loads(path.read_text(encoding="utf-8")))


def timestamps_for(data, video_id):
    path = data / video_id / "timestamps.json"
    stat = path.stat()
    return _times(path, stat.st_size, stat.st_mtime_ns)


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
    with av.open(str(resolve_source(video, root))) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        target = times[start] + video["source_start_s"]
        container.seek(int(target / stream.time_base), stream=stream, backward=True)
        for frame in container.decode(stream):
            if frame.pts is None:
                continue
            t = float(frame.pts * stream.time_base) - video["source_start_s"]
            index = bisect.bisect_left(times, t - 0.00001)
            if index < start:
                continue
            if index >= end:
                break
            if abs(times[index] - t) > 0.00002:
                raise SourceChangedError(
                    "Decoded timestamps do not match the imported source"
                )
            yield index, times[index], frame


def write_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document), encoding="utf-8")
    temporary.replace(path)
