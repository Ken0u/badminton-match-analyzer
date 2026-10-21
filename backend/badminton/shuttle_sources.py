"""Bounded source-only inputs for independent review, never application truth."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import io
import math
import os
import platform
import sys
import time
from pathlib import Path
from uuid import uuid4

import psutil

from .shuttle_supervision import contained, encoded, file_hash, read_json

ELIGIBILITY = dict.fromkeys(
    (
        "training_allowed",
        "independent_test_allowed",
        "model_deployment_allowed",
        "dataset_redistribution_allowed",
    ),
    False,
)
LIMITS = {
    "source_bytes": 2 * 1024**3,
    "download_bytes": 3 * 1024**3,
    "output_bytes": 6 * 1024**3,
    "worker_seconds": 7200,
    "max_frames_per_source": 300000,
}
SOURCES = {"go2uajSiBnE": "singles", "H1setLK1tig": "doubles"}
CHANNEL = "UChh-akEbUM8_6ghGVnJd6cQ"


class Budget:
    """Exclusive bounded writes retain partial evidence on every failure."""

    def __init__(self, output, limits, *, reserve_bytes=0):
        self.output = Path(output).resolve()
        self.limits = limits
        self.started = time.monotonic()
        self.downloaded_bytes = 0
        self.reserve_bytes = reserve_bytes
        self.used = self._disk_bytes()
        self.check()

    def _disk_bytes(self):
        total = 0
        for path in self.output.rglob("*"):
            if path.is_symlink():
                raise ValueError("Output lineage contains a symbolic link")
            if path.is_file():
                contained(self.output, path)
                total += path.stat().st_size
        return total

    def elapsed_s(self):
        return time.monotonic() - self.started

    def check(self, additional=0):
        if self.elapsed_s() >= self.limits["worker_seconds"]:
            raise ValueError("Data worker wall budget exhausted")
        if self.used + additional + self.reserve_bytes > self.limits["output_bytes"]:
            raise ValueError("Output byte budget exhausted")

    def stream(self, path, stream, *, limit, expected_bytes=None, download=False):
        path = contained(self.output, path)
        if path.exists() or path.is_symlink():
            raise FileExistsError("Output already exists")
        self.used = self._disk_bytes()
        self.check()
        path.parent.mkdir(parents=True, exist_ok=True)
        pending = path.with_name(path.name + ".pending-" + uuid4().hex)
        count = 0
        with pending.open("xb") as target:
            while True:
                self.check()
                chunk = stream.read(min(1024 * 1024, limit - count + 1))
                if not chunk:
                    break
                if count + len(chunk) > limit:
                    raise ValueError("Source or record byte bound exceeded")
                if download and (
                    self.downloaded_bytes + len(chunk) > self.limits["download_bytes"]
                ):
                    raise ValueError("Combined download budget exhausted")
                self.check(len(chunk))
                target.write(chunk)
                count += len(chunk)
                self.used += len(chunk)
                if download:
                    self.downloaded_bytes += len(chunk)
            target.flush()
            os.fsync(target.fileno())
        if expected_bytes is not None and count != expected_bytes:
            raise ValueError("Complete source byte count does not match declaration")
        os.link(pending, path)  # Exclusive publish, including a racing destination.
        pending.unlink()
        return {"bytes": count, "sha256": file_hash(path)}

    def publish(self, path, raw):
        return self.stream(path, io.BytesIO(raw), limit=len(raw))

    def json(self, path, value):
        return self.publish(path, encoded(value))


def load_inputs(sources_path, protocol_path):
    manifest, protocol = read_json(sources_path), read_json(protocol_path)
    if (
        manifest.get("schema_version") != 1
        or protocol.get("schema_version") != 1
        or protocol.get("centers_per_source") != 64
        or protocol.get("context_offsets") != [-2, -1, 0, 1, 2]
        or protocol.get("limits") != LIMITS
        or protocol.get("eligibility") != ELIGIBILITY
        or any(type(value) is not int for value in protocol.get("limits", {}).values())
        or type(protocol.get("centers_per_source")) is not int
        or any(type(value) is not int for value in protocol.get("context_offsets", []))
        or any(value is not False for value in protocol.get("eligibility", {}).values())
    ):
        raise ValueError("Unsupported frozen source packet protocol")
    sources = manifest.get("sources", [])
    if len(sources) != 2 or {row.get("id") for row in sources} != set(SOURCES):
        raise ValueError("Exactly the two declared canonical sources are required")
    for row in sources:
        if (
            row.get("category") != SOURCES[row["id"]]
            or row.get("url") != "https://www.youtube.com/watch?v=" + row["id"]
            or row.get("channel_id") != CHANNEL
            or row.get("format_id") != "137"
            or row.get("eligibility") != ELIGIBILITY
            or any(value is not False for value in row.get("eligibility", {}).values())
        ):
            raise ValueError("Source identity, format or eligibility changed")
    return manifest, protocol


def _frame_identity(frame, ordinal):
    from .orientation import OrientationError, display_dimensions, frame_rotation

    try:
        rotation = frame_rotation(frame)
        display_size = list(display_dimensions(frame.width, frame.height, rotation))
        orientation_error = None
    except OrientationError as exc:
        rotation, display_size, orientation_error = None, None, type(exc).__name__
    pts, base = frame.pts, frame.time_base
    return {
        "frame": ordinal,
        "pts": pts,
        "time_base": str(base) if base is not None else None,
        "time_s": float(pts * base) if pts is not None and base is not None else None,
        "rotation": rotation,
        "source_size": [frame.width, frame.height],
        "display_size": display_size,
        "orientation_error": orientation_error,
        "corrupt": bool(frame.is_corrupt),
    }


def _threaded():
    available = importlib.util.find_spec("torchvision") is not None
    if available:
        import torchvision  # noqa: F401  # Before any threaded PyAV opening.

    return available


def native_clock(path, budget, *, max_frames=300000):
    """Decode the whole stream; preserve each returned native timing/geometry row."""
    from .av_runtime import open_media

    threaded = _threaded()
    before = file_hash(path)
    frames, issues = [], set()
    complete = False
    try:
        with open_media(str(path)) as container:
            if len(container.streams.video) != 1 or container.streams.audio:
                raise ValueError("Expected exactly one source video stream")
            stream = container.streams.video[0]
            stream.thread_type = "AUTO" if threaded else "NONE"
            if not threaded:
                stream.codec_context.thread_count = 1
            for ordinal, frame in enumerate(container.decode(stream)):
                budget.check()
                if ordinal >= max_frames:
                    raise ValueError("Native source frame bound exceeded")
                row = _frame_identity(frame, ordinal)
                if row["corrupt"]:
                    issues.add("corrupt_native_frame")
                if row["orientation_error"]:
                    issues.add("unsupported_native_orientation")
                if frames and any(
                    row[key] != frames[-1][key] for key in ("rotation", "source_size")
                ):
                    issues.add("changing_native_geometry")
                value = row["time_s"]
                if value is None or not math.isfinite(value):
                    issues.add("unavailable_native_time")
                elif frames and frames[-1]["time_s"] is not None:
                    if value <= frames[-1]["time_s"]:
                        issues.add("nonincreasing_native_time")
                frames.append(row)
            complete = True
    except ValueError:
        raise
    except Exception as exc:
        # Exception text can contain source locations; retain only its type.
        issues.add("decode_unavailable:" + type(exc).__name__)
    if before != file_hash(path):
        raise ValueError("Source bytes changed during clock census")
    if not frames:
        issues.add("no_native_frames")
        complete = False
    return {
        "schema_version": 1,
        "source_sha256": before,
        "frame_count": len(frames),
        "origin_s": frames[0]["time_s"] if frames else None,
        "frames": frames,
        "complete": complete,
        "issues": sorted(issues),
    }


def sample_memberships(clock, count=64, offsets=(-2, -1, 0, 1, 2)):
    frames = clock["frames"]
    if clock.get("frame_count") != len(frames) or any(
        row["frame"] != index for index, row in enumerate(frames)
    ):
        raise ValueError("Clock native ordinal census is inconsistent")
    if count != 64 or tuple(offsets) != (-2, -1, 0, 1, 2):
        raise ValueError("Sampling protocol is frozen")
    if not clock["complete"] or len(frames) < count:
        raise ValueError("Source unavailable or too short for complete packet")
    result = []
    for j in range(count):
        center = j * (len(frames) - 1) // (count - 1)
        result.append(
            {
                "case_id": j,
                "center_frame": center,
                "context": [
                    {
                        "offset": offset,
                        "frame": max(0, min(len(frames) - 1, center + offset)),
                        "clamped": not 0 <= center + offset < len(frames),
                    }
                    for offset in offsets
                ],
            }
        )
    return result


def extract_packet(
    source_path,
    clock_path,
    clock_sha256,
    source_sha256,
    output,
    budget,
    source_id,
    *,
    count=64,
):
    from .av_runtime import open_media
    from .orientation import orient_frame

    if not source_id or not all(c.isalnum() or c in "_-" for c in source_id):
        raise ValueError("Invalid canonical source identifier")
    if file_hash(source_path) != source_sha256 or file_hash(clock_path) != clock_sha256:
        raise ValueError("Frozen source or clock hash changed")
    clock = read_json(clock_path)
    if clock["source_sha256"] != source_sha256:
        raise ValueError("Clock belongs to another source")
    cases = sample_memberships(clock, count)
    selected = {m["frame"] for case in cases for m in case["context"]}
    images = {}
    threaded = _threaded()
    # A complete second decode cross-checks every native identity, not just centers.
    with open_media(str(source_path)) as container:
        if len(container.streams.video) != 1 or container.streams.audio:
            raise ValueError("Source stream selection changed")
        stream = container.streams.video[0]
        stream.thread_type = "AUTO" if threaded else "NONE"
        if not threaded:
            stream.codec_context.thread_count = 1
        decoded = 0
        for ordinal, frame in enumerate(container.decode(stream)):
            budget.check()
            if (
                ordinal >= len(clock["frames"])
                or _frame_identity(frame, ordinal) != (clock["frames"][ordinal])
            ):
                raise ValueError("Native frame identity changed since clock freeze")
            decoded += 1
            if ordinal not in selected:
                continue
            row = clock["frames"][ordinal]
            available = not row["corrupt"] and row["orientation_error"] is None
            identity = {**row, "available": available, "image": None}
            if available:
                png = io.BytesIO()
                orient_frame(frame, expected_rotation=row["rotation"]).to_image().save(
                    png, format="PNG"
                )
                path = Path(output) / "images" / source_id / f"{ordinal:09d}.png"
                seal = budget.publish(path, png.getvalue())
                identity["image"] = {
                    "path": path.relative_to(budget.output).as_posix(),
                    **seal,
                }
            images[str(ordinal)] = identity
    if decoded != len(clock["frames"]) or len(images) != len(selected):
        raise ValueError("Incomplete second native source decode")
    if file_hash(source_path) != source_sha256 or file_hash(clock_path) != clock_sha256:
        raise ValueError("Frozen source or clock changed during extraction")
    return {
        "schema_version": 1,
        "source_id": source_id,
        "source_sha256": source_sha256,
        "clock_sha256": clock_sha256,
        "case_count": len(cases),
        "requested_context_memberships": sum(len(c["context"]) for c in cases),
        "cases": cases,
        "images": images,
        "eligibility": dict(ELIGIBILITY),
    }


class _QuietLogger:
    def debug(self, _message):
        pass

    info = warning = error = debug


class _RangeStream:
    """Read contiguous HTTPS byte ranges once, without retries or substitution."""

    def __init__(self, downloader, request_type, url, headers, size):
        self.downloader, self.request_type = downloader, request_type
        self.url, self.headers, self.size = url, headers, size
        self.position, self.remaining = 0, 0
        self.response = None

    def close(self):
        if self.response is not None:
            self.response.close()
            self.response = None

    def read(self, amount):
        if self.position == self.size:
            return b""
        if not self.remaining:
            self.close()
            end = min(self.size - 1, self.position + 10 * 1024**2 - 1)
            headers = {**self.headers, "Range": f"bytes={self.position}-{end}"}
            self.response = self.downloader.urlopen(
                self.request_type(self.url, headers=headers)
            )
            status = self.response.status
            if status == 200 and self.position == 0:
                end = self.size - 1  # A server may legitimately ignore Range.
            elif status != 206 or self.response.headers.get("Content-Range") != (
                f"bytes {self.position}-{end}/{self.size}"
            ):
                raise ValueError("Selected stream range identity mismatch")
            self.remaining = end - self.position + 1
            if int(self.response.headers.get("Content-Length", -1)) != self.remaining:
                raise ValueError("Selected stream range length mismatch")
        chunk = self.response.read(min(amount, self.remaining))
        if not chunk or len(chunk) > self.remaining:
            raise ValueError("Selected stream range truncated or oversized")
        self.position += len(chunk)
        self.remaining -= len(chunk)
        if not self.remaining and self.response.read(1):
            raise ValueError("Selected stream range has excess bytes")
        return chunk


def acquire_source(declaration, output, budget):
    """Normal anonymous public extraction, no accounts, cookies or substitutions."""
    from yt_dlp import YoutubeDL
    from yt_dlp.networking import Request

    options = {
        "format": "137",
        "skip_download": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "logger": _QuietLogger(),
        "retries": 0,
        "extractor_retries": 0,
        "socket_timeout": 30,
        "cachedir": False,
    }
    with YoutubeDL(options) as downloader:
        budget.check()
        try:
            info = downloader.extract_info(declaration["url"], download=False)
        except Exception:
            raise ValueError(
                "Anonymous public metadata extraction unavailable"
            ) from None
        keys = (
            "id",
            "title",
            "channel_id",
            "channel",
            "upload_date",
            "duration",
            "availability",
            "live_status",
            "format_id",
            "width",
            "height",
            "fps",
            "vcodec",
            "acodec",
            "ext",
            "filesize",
            "filesize_approx",
            "protocol",
        )
        metadata = {key: info.get(key) for key in keys}
        folder = Path(output) / "sources" / declaration["id"]
        budget.json(folder / "returned-metadata.json", metadata)
        size = info.get("filesize")
        if (
            info.get("id") != declaration["id"]
            or info.get("channel_id") != CHANNEL
            or info.get("format_id") != "137"
            or (info.get("width"), info.get("height"), info.get("fps"))
            != (1920, 1080, 30)
            or info.get("acodec") != "none"
            or not str(info.get("vcodec", "")).startswith("avc1")
            or info.get("availability") != "public"
            or info.get("live_status") != "not_live"
            or info.get("protocol") != "https"
            or info.get("fragments")
            or type(size) is not int
            or not 0 < size <= budget.limits["source_bytes"]
            or budget.downloaded_bytes + size > budget.limits["download_bytes"]
        ):
            raise ValueError(
                "Selected public video-only stream is unavailable or changed"
            )
        budget.check(size)
        response = _RangeStream(
            downloader, Request, info["url"], info.get("http_headers", {}), size
        )
        try:
            try:
                seal = budget.stream(
                    folder / "source.mp4",
                    response,
                    limit=budget.limits["source_bytes"],
                    expected_bytes=size,
                    download=True,
                )
            except Exception as exc:
                # Do not persist signed delivery URLs in Store messages or tracebacks.
                raise ValueError(
                    "Selected stream transfer failed: " + type(exc).__name__
                ) from None
        finally:
            response.close()
        budget.json(folder / "source-seal.json", {**seal, "metadata": metadata})
        return folder / "source.mp4", seal


def _freeze(output, budget, sources_path, protocol_path):
    package = Path(__file__).resolve().parent
    files = {"backend/badminton/" + p.name: p for p in package.glob("*.py")}
    files.update(
        {
            "scripts/prepare_shuttle_sources.py": package.parents[1]
            / "scripts/prepare_shuttle_sources.py",
            "data/manifests/shuttle_review_sources_v1.json": Path(sources_path),
            "data/manifests/shuttle_review_packet_protocol_v1.json": Path(
                protocol_path
            ),
        }
    )
    hashes = {name: file_hash(path) for name, path in files.items()}
    for name, path in files.items():
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != hashes[name]:
            raise ValueError("Consumer changed during snapshot")
        budget.publish(output / "consumer" / name, raw)
    context = {
        "schema_version": 1,
        "consumers": hashes,
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            **{
                name: importlib.metadata.version(name)
                for name in (
                    "av",
                    "numpy",
                    "Pillow",
                    "psutil",
                    "torch",
                    "torchvision",
                    "yt-dlp",
                )
            },
        },
    }
    budget.json(output / "context.json", context)
    _verify_context(output, files, hashes)
    return files, hashes, file_hash(output / "context.json")


def _verify_context(output, files, hashes):
    for name, path in files.items():
        if (
            file_hash(path) != hashes[name]
            or file_hash(output / "consumer" / name) != hashes[name]
        ):
            raise ValueError("Frozen executed consumer or declaration changed")


def review_template(packet):
    return {
        "schema_version": 1,
        "source_id": packet["source_id"],
        "source_sha256": packet["source_sha256"],
        "clock_sha256": packet["clock_sha256"],
        "eligibility": dict(ELIGIBILITY),
        "cases": [
            {
                "case_id": case["case_id"],
                "center_frame": case["center_frame"],
                "visibility": "unknown",
                "difficulty": "unknown",
                "scene": "unknown",
                "x": None,
                "y": None,
                "reviewed": False,
            }
            for case in packet["cases"]
        ],
    }


def run_preparation(root, output, *, sources_path, protocol_path):
    from . import config
    from .jobs import run_local_job
    from .storage import Store

    root = Path(root).resolve()
    output = contained(root / ".cache", output)
    shared = root / "data/processed"
    if (
        config.ROOT != root
        or config.DATA.resolve() != shared
        or config.WEIGHTS.resolve() != root / "models/weights"
        or not (shared / "catalog.sqlite3").is_file()
    ):
        raise ValueError(
            "Pin original roots and the existing real shared Store before imports"
        )
    if output == (root / ".cache").resolve() or output.exists():
        raise ValueError(
            "Choose a new exclusive output lineage; never implicitly restart"
        )
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "AGENT_PROJECT_TOKEN", "OPENAI_API_KEY"):
        if os.environ.get(name):
            raise ValueError("Clear external credentials before source preparation")
    manifest, protocol = load_inputs(sources_path, protocol_path)
    budget = Budget(output, protocol["limits"], reserve_bytes=65536)
    files, hashes, context_sha = _freeze(output, budget, sources_path, protocol_path)
    process = psutil.Process()
    store = Store(shared)
    job_id = None
    completed = []

    def task(identifier, progress):
        nonlocal job_id
        job_id = identifier
        budget.json(
            output / "admission.json",
            {
                "job_id": identifier,
                "context_sha256": context_sha,
                "process": {
                    "pid": process.pid,
                    "creation_time": process.create_time(),
                    "cwd": process.cwd(),
                    "command": sys.argv,
                },
            },
        )
        acquired = []
        for declaration in manifest["sources"]:
            _verify_context(output, files, hashes)
            path, seal = acquire_source(declaration, output, budget)
            acquired.append((declaration, path, seal))
        scanned = []
        for declaration, path, seal in acquired:
            _verify_context(output, files, hashes)
            clock = native_clock(
                path, budget, max_frames=protocol["limits"]["max_frames_per_source"]
            )
            folder = path.parent
            budget.json(folder / "clock.json", clock)
            clock_sha = file_hash(folder / "clock.json")
            scanned.append((declaration, path, seal, clock, clock_sha))
        for index, (declaration, path, seal, clock, clock_sha) in enumerate(scanned):
            folder = path.parent
            _verify_context(output, files, hashes)
            packet = extract_packet(
                path,
                folder / "clock.json",
                clock_sha,
                seal["sha256"],
                output,
                budget,
                declaration["id"],
            )
            packet["context_sha256"] = context_sha
            packet_seal = budget.json(folder / "packet.json", packet)
            template = review_template(packet)
            template["packet_sha256"] = packet_seal["sha256"]
            budget.json(folder / "review-template.json", template)
            # Verify every published image, not only the immutable packet index.
            for image in packet["images"].values():
                if image["image"] is not None:
                    item = image["image"]
                    if (
                        file_hash(contained(output, output / item["path"]))
                        != item["sha256"]
                    ):
                        raise ValueError("Published native image changed")
            completed.append(
                {
                    "source_id": declaration["id"],
                    "source": seal,
                    "clock_sha256": clock_sha,
                    "frame_count": clock["frame_count"],
                    "clock_issues": clock["issues"],
                    "packet": packet_seal,
                    "case_count": packet["case_count"],
                    "context_memberships": packet["requested_context_memberships"],
                    "unique_images": len(packet["images"]),
                }
            )
            progress((index + 1) / 2)
        _verify_context(output, files, hashes)
        if file_hash(output / "context.json") != context_sha:
            raise ValueError("Frozen context changed")
        budget.used = budget._disk_bytes()
        budget.check()
        result = {
            "sources": completed,
            "eligibility": dict(ELIGIBILITY),
            "case_count": sum(x["case_count"] for x in completed),
            "requested_context_memberships": sum(
                x["context_memberships"] for x in completed
            ),
            "downloaded_bytes": budget.downloaded_bytes,
            "elapsed_s": budget.elapsed_s(),
            "context_sha256": context_sha,
        }
        budget.json(output / "result.json", result)
        return result

    try:
        result = run_local_job(store, "research-shuttle-source-packet", None, task)
    except BaseException as exc:
        if job_id is not None:
            # Even an exhausted scientific budget must leave small terminal evidence.
            from .shuttle_supervision import publish_json

            publish_json(
                output / "terminal.json",
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "job_id": job_id,
                    "context_sha256": context_sha,
                    "elapsed_s": budget.elapsed_s(),
                    "completed_sources": completed,
                },
            )
        raise
    # Scientific output leaves reserved space for the post-Store terminal proof;
    # crossing a wall deadline here cannot relabel an already completed Store job.
    from .shuttle_supervision import publish_json

    publish_json(
        output / "terminal.json",
        {
            "status": "completed",
            "job_id": job_id,
            "context_sha256": context_sha,
            "elapsed_s": budget.elapsed_s(),
            "result_sha256": file_hash(output / "result.json"),
        },
    )
    return result
