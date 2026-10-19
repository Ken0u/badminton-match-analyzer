"""Decode source presentation timestamps and create a sparse visual audit."""

import hashlib
import itertools
from pathlib import Path

from PIL import Image, ImageDraw

from .av_runtime import open_media
from .orientation import (
    OrientationError,
    display_dimensions,
    frame_rotation,
    orient_frame,
)
from .video import write_json


def inspect_video(path: Path, mode: str, store, root: Path, progress=None):
    path = path.resolve()
    relative = path.relative_to(root.resolve())
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum = digest.hexdigest()
    video_id = checksum[:16]
    try:
        existing = store.video(video_id)
    except KeyError:
        existing = None
    if existing and existing["mode"] != mode:
        raise ValueError(
            "This video is already registered with a different match format"
        )
    folder = store.data / video_id
    folder.mkdir(parents=True, exist_ok=True)
    with open_media(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        origin = float((stream.start_time or 0) * stream.time_base)
        nominal_duration = (
            float(stream.duration * stream.time_base)
            if stream.duration
            else (container.duration or 0) / 1e6
        )
        sample_times = [nominal_duration * i / 18 for i in range(18)]
        timestamps, samples = [], []
        rotation = None
        last_frame_duration = 0
        for index, frame in enumerate(container.decode(stream)):
            decoded_rotation = frame_rotation(frame)
            if rotation is None:
                rotation = decoded_rotation
            elif rotation != decoded_rotation:
                raise OrientationError(
                    "Video display rotation changes within the source"
                )
            if frame.pts is None:
                raise ValueError("Video has frames without presentation timestamps")
            timestamp = max(0.0, float(frame.pts * stream.time_base) - origin)
            if timestamps and timestamp <= timestamps[-1]:
                raise ValueError(
                    "Video presentation timestamps are not strictly increasing"
                )
            timestamps.append(round(timestamp, 8))
            last_frame_duration = float((frame.duration or 0) * stream.time_base)
            if (
                len(samples) < len(sample_times)
                and timestamp >= sample_times[len(samples)]
            ):
                img = orient_frame(frame, expected_rotation=rotation).to_image()
                img.thumbnail((384, 216))
                samples.append((index, timestamp, img))
            if progress and index % 250 == 0:
                progress(min(timestamp / max(nominal_duration, 0.001), 0.99))
        if not timestamps:
            raise ValueError("No video frames were decoded")
        width, height = display_dimensions(stream.width, stream.height, rotation)
        step = (
            timestamps[-1] - timestamps[-2]
            if len(timestamps) > 1
            else 1 / float(stream.average_rate or 25)
        )
        # Prefer the decoded final sample duration: its preceding VFR gap can
        # be unrelated. When absent, retain the last gap (or nominal single-frame
        # interval) as an estimate; no additional source frame is invented.
        document = {
            "id": video_id,
            "name": path.name,
            "path": relative.as_posix(),
            "mode": mode,
            "width": width,
            "height": height,
            "source_width": stream.width,
            "source_height": stream.height,
            "rotation": rotation,
            "fps": float(stream.average_rate or 1 / step),
            "frame_count": len(timestamps),
            "duration_s": round(
                timestamps[-1]
                + (last_frame_duration if last_frame_duration > 0 else step),
                8,
            ),
            "codec": stream.codec_context.name,
            "source_start_s": origin,
            "time_base": str(stream.time_base),
            "sha256": checksum,
            "variable_frame_rate": any(
                abs((b - a) - step) > 0.0001 for a, b in itertools.pairwise(timestamps)
            ),
            "audio": bool(container.streams.audio),
            "samples": [{"frame": i, "time_s": t} for i, t, _ in samples],
        }
    sheet = Image.new("RGB", (384 * 3, 242 * 6), "#101b21")
    draw = ImageDraw.Draw(sheet)
    for n, (index, timestamp, img) in enumerate(samples):
        x, y = (n % 3) * 384, (n // 3) * 242
        sheet.paste(img, (x, y))
        draw.text((x + 8, y + 220), f"{timestamp:.2f}s | frame {index}", fill="white")
        if n == 0:
            img.save(folder / "poster.jpg", quality=88)
    sheet.save(folder / "contact-sheet.jpg", quality=90)
    if existing:
        for field in ("review_start_frame", "source", "source_type"):
            if field in existing:
                document[field] = existing[field]
        if existing.get("source_type") and existing.get("name"):
            document["name"] = existing["name"]
    write_json(folder / "timestamps.json", timestamps)
    write_json(folder / "metadata.json", document)
    store.register(document)
    return document


def read_frame(path: Path, time_s: float, origin: float = 0):
    with open_media(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        target = time_s + origin
        container.seek(int(target / stream.time_base), stream=stream, backward=True)
        for frame in container.decode(stream):
            if (
                frame.pts is not None
                and float(frame.pts * stream.time_base) >= target - 0.00001
            ):
                return orient_frame(frame).to_image()
    raise ValueError("Could not decode requested frame")
