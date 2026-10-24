"""Source-only rally packets and conservative reference validation.

Nothing here reads predictions, loads weights, or installs labels in the app.
An assessment receipt proves execution/coverage, never sporting correctness.
"""

from __future__ import annotations

import bisect
import hashlib
import importlib.metadata
import io
import itertools
import json
import math
import os
import platform
import sqlite3
import subprocess
import time
from fractions import Fraction
from pathlib import Path

import psutil

from .shuttle_sources import ELIGIBILITY, Budget, _frame_identity, _threaded
from .shuttle_supervision import contained, encoded, file_hash, read_json

SOURCE_IDS = ("go2uajSiBnE", "H1setLK1tig")
STREAMS = ("independent_a", "independent_b", "adjudication")
FAMILIES = {"clear", "lift", "net", "drop", "smash", "drive", "other", "unknown"}
SIDES = {"forehand", "backhand", "unknown"}
SCENES = {"live", "replay", "non_play", "unknown"}
STATES = {
    "service_preparation",
    "exchange",
    "stopped_play",
    "replay",
    "non_play",
    "unknown",
}
MAX_IMAGES = 20
MAX_SESSION_BYTES = 6 * 1024**2
MAX_PAYLOAD_BYTES = 2 * 1024**3
MAX_OUTPUT_BYTES = 4 * 1024**3
TASK_SECONDS = 4 * 3600
CREDENTIALS = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "AGENT_PROJECT_TOKEN",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
)


def _integer(value, low=0):
    if type(value) is not int or value < low:
        raise ValueError("Expected a bounded native integer")
    return value


def _eligibility(value):
    if value != ELIGIBILITY or any(v is not False for v in value.values()):
        raise ValueError("All research eligibility flags must remain false")


def load_protocol(path):
    protocol = read_json(path)
    _eligibility(protocol.get("eligibility", {}))
    if protocol.get("schema_version") == 4:
        _validate_transport_protocol(protocol)
        return protocol
    if protocol.get("schema_version") == 3:
        _validate_dense_protocol(protocol)
        return protocol
    extended = protocol.get("schema_version") == 2
    if (
        protocol.get("schema_version") not in (1, 2)
        or protocol.get("task") != (208 if extended else 62)
        or [s.get("source_id") for s in protocol.get("sources", [])] != list(SOURCE_IDS)
        or protocol["selection"]["overview_seconds"] != (900 if extended else 300)
        or protocol["selection"]["overview_step_seconds"] != 5
        or protocol["selection"]["max_rally_seconds"] != 40
        or protocol["selection"]["context_seconds_each_side"] != 4
        or protocol["assessment"]["chunk_overlap_frames"] != 2
        or protocol["payload"]["max_images_per_session"] != MAX_IMAGES
        or protocol["payload"]["max_image_bytes_per_session"] != MAX_SESSION_BYTES
        or protocol["payload"]["max_total_image_bytes"]
        != (2 * MAX_PAYLOAD_BYTES if extended else MAX_PAYLOAD_BYTES)
        or protocol["limits"]["max_output_bytes"]
        != (2 * MAX_OUTPUT_BYTES if extended else MAX_OUTPUT_BYTES)
        or protocol["limits"]["task_seconds_from_grant"] != TASK_SECONDS
    ):
        raise ValueError("Unsupported source-only protocol")
    if extended and (
        protocol.get("predecessor", {}).get("image_bytes") != 340760009
        or protocol["predecessor"].get("screening_sha256")
        != "77696108428995481ad6163a4ef1c3901938a04a4e0c9fc51db9b6b62ea00239"
        or protocol["predecessor"].get("head_sha")
        != "39bbb9db15b96d258de4da4d17573a35c658f530"
        or protocol["assessment"].get("adjudication") != "targeted_source_only"
    ):
        raise ValueError("Original failed pilot and targeted adjudication required")
    return protocol


def _validate_dense_protocol(protocol):
    """Bind the separately authorized reuse scope; legacy limits stay unchanged."""
    original = read_json(
        Path(__file__).resolve().parents[2]
        / "data/manifests/rally_reference_protocol_v2.json"
    )
    expected_packets = {
        SOURCE_IDS[
            0
        ]: "26ce8a86d01ecff8882f917370fb2b7c1cb2cfbebdebb9f9062d7cddd1b3cae6",
        SOURCE_IDS[
            1
        ]: "8f485d0c661f298c56268785d05dd681345bdfc7817bbf28552ca740f4e8f86a",
    }
    if (
        protocol.get("task") != 210
        or protocol.get("sources") != original["sources"]
        or protocol.get("selection") != original["selection"]
        or protocol.get("assessment") != original["assessment"]
        or protocol.get("payload")
        != {
            **original["payload"],
            "max_image_bytes_per_session": 32 * 1024**2,
            "max_total_image_bytes": 8 * 1024**3,
        }
        or protocol.get("limits")
        != {
            **original["limits"],
            "task_seconds_from_grant": 8 * 3600,
            "max_parallel_assessors": 2,
            "pacing_seconds": 5,
            "max_replacement_launches": 3,
        }
        or protocol.get("predecessor")
        != {
            "task": 208,
            "pr": 209,
            "head_sha": "890995493ddcc98076bc8d771ceb400c8234d409",
            "merged_sha": "3d2d39e76b334584d725177f3dfb950d8fa84da6",
            "screening_sha256": "7c9fb68bd600f648e32c3dbdbc1b3d20b54fe6fc54b2dfa226a152d7cc960f3e",
            "selection_sha256": "761d1da7f4b8628ebdb864ed0117d561b0db83f15258619506d7d0b7c993bebb",
            "context_sha256": "aecd99016134cec0299406c0f82f46b433ea5faee73ac3eacd11d92a36957cde",
            "terminal_sha256": "59c28c1bfc4233927cca38cf925067b7f04d80c743863b2ebfe471e186686f8e",
            "dense_packets": expected_packets,
            "image_bytes": 1347060833,
            "native_frames": {SOURCE_IDS[0]: 991, SOURCE_IDS[1]: 541},
            "complete_references": 0,
            "retained_slots": 2,
        }
    ):
        raise ValueError("Unsupported dense reuse protocol or predecessor bindings")


def _validate_transport_protocol(protocol):
    """Keep the failed v3 experiment immutable and bind its authorized successor."""
    expected = read_json(
        Path(__file__).resolve().parents[2]
        / "data/manifests/rally_reference_protocol_v3.json"
    )
    _validate_dense_protocol(expected)
    expected.update(
        schema_version=4,
        task=212,
        purpose="Transport-bounded assessment of unchanged native packets; development only",
    )
    expected["payload"].update(
        max_image_bytes_per_session=9 * 1024**2,
        max_locally_controlled_encoded_request_bytes=14 * 1024**2,
        encoded_envelope_reserve_bytes=2 * 1024**2,
    )
    expected["predecessor"].update(
        image_bytes=1400881755,
        image_bytes_before_failed_successor=1347060833,
        failed_successor={
            "task": 210,
            "pr": 211,
            "head_sha": "4d686a72fb5bb5390b1ea2250680a3df6a2a962c",
            "merged_sha": "2b005aecef275909bcf1d2745f98d9b7e491e2a0",
            "aggregate_sha256": "4e839ba32c3171937e5ebb8824c05b8daf1cacb69a055caf28fa2685d4b2f865",
            "failed_sessions": 2,
            "image_bytes": 53820922,
        },
    )
    if encoded(protocol) != encoded(expected):
        raise ValueError(
            "Unsupported transport protocol or failed predecessor bindings"
        )


def transport_cost(image_sizes, *, context_bytes=0, protocol):
    """Conservative encoded request estimate, not proof of server acceptance.

    Each image is base64 encoded separately. The fixed envelope reserve covers
    locally controlled JSON/text/schema plus remaining CLI framing; callers must
    measure their actual escaped context rather than assume it fits.
    """
    _eligibility(protocol.get("eligibility", {}))
    _validate_transport_protocol(protocol)
    sizes = list(image_sizes)
    _integer(context_bytes)
    if not sizes or len(sizes) > MAX_IMAGES:
        raise ValueError("Transport requires one bounded assigned image set")
    for size in sizes:
        _integer(size, 1)
    if sum(sizes) > protocol["payload"]["max_image_bytes_per_session"]:
        raise ValueError("Original image payload exceeds authorized session limit")
    base64_bytes = sum(4 * ((size + 2) // 3) for size in sizes)
    header_bytes = len("data:image/png;base64,") * len(sizes)
    reserve = protocol["payload"]["encoded_envelope_reserve_bytes"]
    if context_bytes + header_bytes > reserve:
        raise ValueError("Escaped context exceeds reserved encoded envelope")
    estimated = base64_bytes + reserve
    if estimated > protocol["payload"]["max_locally_controlled_encoded_request_bytes"]:
        raise ValueError("Locally controlled encoded request exceeds transport guard")
    return {
        "base64_image_bytes": base64_bytes,
        "context_bytes": context_bytes,
        "reserved_envelope_bytes": reserve,
        "estimated_encoded_bytes": estimated,
    }


def _session_limit(protocol):
    if protocol is None:
        return MAX_SESSION_BYTES
    _eligibility(protocol.get("eligibility", {}))
    if protocol.get("schema_version") == 4:
        _validate_transport_protocol(protocol)
    elif protocol.get("schema_version") == 3:
        _validate_dense_protocol(protocol)
    elif protocol.get("schema_version") not in (1, 2):
        raise ValueError("Unsupported source-only protocol")
    elif (
        protocol.get("payload", {}).get("max_image_bytes_per_session")
        != MAX_SESSION_BYTES
        or protocol["payload"].get("max_images_per_session") != MAX_IMAGES
        or protocol["payload"].get("max_total_image_bytes")
        != MAX_PAYLOAD_BYTES * protocol["schema_version"]
    ):
        raise ValueError("Legacy source protocol limits changed")
    return protocol["payload"]["max_image_bytes_per_session"]


def validate_clock(clock):
    """Validate original ordinals and rational clocks, including variable rate."""
    frames = clock.get("frames", [])
    if (
        not frames
        or clock.get("complete") is not True
        or clock.get("frame_count") != len(frames)
    ):
        raise ValueError("Complete native census required")
    previous = None
    times = []
    for ordinal, row in enumerate(frames):
        if _integer(row.get("frame")) != ordinal or type(row.get("pts")) is not int:
            raise ValueError("Missing or reordered native ordinal/PTS")
        try:
            base = Fraction(row["time_base"])
            value = row["pts"] * base
        except (ValueError, TypeError, ZeroDivisionError) as exc:
            raise ValueError("Invalid native time base") from exc
        if base <= 0 or (previous is not None and value <= previous):
            raise ValueError("Native times must increase strictly")
        if (
            type(row.get("time_s")) not in (int, float)
            or not math.isfinite(row["time_s"])
            or abs(float(value) - row["time_s"]) > 1e-9
        ):
            raise ValueError("Native PTS and seconds disagree")
        size = row.get("source_size")
        if (
            not isinstance(size, list)
            or len(size) != 2
            or any(type(v) is not int or v <= 0 for v in size)
        ):
            raise ValueError("Invalid native geometry")
        rotation = row.get("rotation")
        expected = size[::-1] if rotation in (90, 270) else size
        if row.get("orientation_error") is None and (
            rotation not in (0, 90, 180, 270) or row.get("display_size") != expected
        ):
            raise ValueError("Native orientation/geometry disagree")
        if type(row.get("corrupt")) is not bool:
            raise ValueError("Missing native availability")
        previous = value
        times.append(value)
    if clock.get("origin_s") != frames[0]["time_s"]:
        raise ValueError("Native source origin changed")
    return times


def overview_memberships(clock, protocol=None):
    times = validate_clock(clock)
    result = []
    horizon = protocol["selection"]["overview_seconds"] if protocol else 300
    for second in range(0, horizon + 1, 5):
        index = bisect.bisect_left(times, times[0] + second)
        result.append(
            {
                "grid_second": second,
                "frame": min(index, len(times) - 1),
                "clamped": index == len(times),
            }
        )
    return result


def dense_memberships(clock, bounds):
    times = validate_clock(clock)
    start, end = (_integer(bounds[k]) for k in ("start_frame", "end_frame"))
    if not 0 <= start < end < len(times) or times[end] - times[start] > 40:
        raise ValueError("Provisional rally bounds exceed source/40-second limit")
    first = bisect.bisect_left(times, max(times[0], times[start] - 4))
    last = bisect.bisect_right(times, min(times[-1], times[end] + 4)) - 1
    return [
        {"frame": n, "in_provisional_rally": start <= n <= end}
        for n in range(first, last + 1)
    ]


def earliest_candidate(clock, assessment, protocol=None):
    """Sparse evidence proposes a slot, never a complete reference."""
    members = overview_memberships(clock, protocol)
    rows = assessment.get("frames", [])
    if [r.get("frame") for r in rows] != [m["frame"] for m in members]:
        raise ValueError("Screening must retain all ordered grid memberships")
    for row in rows:
        if (
            row.get("state") not in STATES
            or not isinstance(row.get("reason"), str)
            or not row["reason"].strip()
        ):
            raise ValueError("Explicit source screening state/reason required")
    times = validate_clock(clock)
    for i, row in enumerate(rows):
        if row["state"] != "service_preparation":
            continue
        exchange = False
        for later in rows[i + 1 :]:
            if times[later["frame"]] - times[row["frame"]] > 40 or later["state"] in {
                "replay",
                "non_play",
                "unknown",
            }:
                break
            exchange |= later["state"] == "exchange"
            if later["state"] == "stopped_play" and exchange:
                return {
                    "start_frame": row["frame"],
                    "end_frame": later["frame"],
                    "complete_reference": False,
                    "selection": "earliest_warranted_sparse_candidate",
                }
    return None


def consumer_context(checkout, protocol_path, input_root, granted_at):
    """Seal before source inspection; paths are private, input hashes public."""
    checkout = Path(checkout).resolve()
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=checkout,
        text=True,
    )
    if dirty:
        raise ValueError("Commit prospective consumers/protocol before freezing")
    files = sorted((checkout / "backend/badminton").rglob("*.py"))
    files += [
        checkout / p
        for p in (
            "scripts/prepare_rally_references.py",
            "data/manifests/rally_reference_protocol_v1.json",
            "data/manifests/shuttle_review_sources_v1.json",
            "pyproject.toml",
            "uv.lock",
            "requirements.lock",
        )
    ]
    protocol_path = Path(protocol_path).resolve()
    if protocol_path not in {
        (checkout / f"data/manifests/rally_reference_protocol_v{n}.json").resolve()
        for n in (1, 2, 3, 4)
    }:
        raise ValueError("Use committed protocol")
    protocol = load_protocol(protocol_path)
    if protocol["schema_version"] >= 2:
        files.append(protocol_path)
    if protocol["schema_version"] >= 3:
        files.append(checkout / "data/manifests/rally_reference_protocol_v2.json")
    if protocol["schema_version"] == 4:
        files.append(checkout / "data/manifests/rally_reference_protocol_v3.json")
    return {
        "schema_version": 1,
        "task": protocol["task"],
        **(
            {"protocol_path": protocol_path.relative_to(checkout).as_posix()}
            if protocol["schema_version"] >= 2
            else {}
        ),
        "commit": commit,
        "granted_at": _integer(granted_at),
        "deadline": granted_at + protocol["limits"]["task_seconds_from_grant"],
        "input_root": str(Path(input_root).resolve()),
        "inputs": protocol["sources"],
        "consumers": {p.relative_to(checkout).as_posix(): file_hash(p) for p in files},
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            **{
                name: importlib.metadata.version(name)
                for name in ("av", "numpy", "Pillow", "psutil", "torch", "torchvision")
            },
        },
        "eligibility": dict(ELIGIBILITY),
    }


def verify_context(checkout, context):
    actual = consumer_context(
        checkout,
        Path(checkout)
        / context.get(
            "protocol_path", "data/manifests/rally_reference_protocol_v1.json"
        ),
        context["input_root"],
        context["granted_at"],
    )
    if actual != context or time.time() >= context["deadline"]:
        raise ValueError(
            "Frozen consumers/runtime changed or immutable deadline reached"
        )


def verify_originals(input_root, protocol):
    """Hash both whole sources before any new decode; never open predictions."""
    result = {}
    for source in protocol["sources"]:
        folder = contained(input_root, Path(input_root) / source["source_id"])
        for name, key in (
            ("source.mp4", "source_sha256"),
            ("clock.json", "clock_sha256"),
            ("packet.json", "packet_sha256"),
        ):
            if file_hash(contained(folder, folder / name)) != source[key]:
                raise ValueError("Original source/census/packet hash changed")
        clock, packet = (
            read_json(folder / "clock.json"),
            read_json(folder / "packet.json"),
        )
        validate_clock(clock)
        if (
            clock["source_sha256"] != source["source_sha256"]
            or clock["frame_count"] != source["native_frame_count"]
            or packet["source_id"] != source["source_id"]
            or packet["source_sha256"] != source["source_sha256"]
            or packet["clock_sha256"] != source["clock_sha256"]
        ):
            raise ValueError("Original packet/census source binding changed")
        _eligibility(packet["eligibility"])
        result[source["source_id"]] = clock
    return result


def persisted_bytes(root, *, limit=MAX_OUTPUT_BYTES):
    total = 0
    for path in Path(root).rglob("*"):
        contained(root, path)
        if path.is_symlink():
            raise ValueError("Output lineage contains symbolic links")
        if path.is_file():
            total += path.stat().st_size
    if total > limit:
        raise ValueError("Cumulative persisted output ceiling exceeded")
    return total


def predecessor_output_bytes(root):
    """Count retained task62 artifacts without following generated test links."""
    cache = Path(root) / ".cache"
    paths = [p for p in cache.iterdir() if p.name.lower().startswith("rally62")]
    paths.append(cache / "worktrees/rally62-e1")
    total = 0
    for parent in paths:
        for path in [parent] if parent.is_file() else parent.rglob("*"):
            if path.is_symlink():
                total += path.lstat().st_size
            elif path.is_file():
                total += path.stat().st_size
    return total


def extract_frames(source_path, clock, memberships, output, source_id, budget):
    """Decode native prefix with full ordinal checks; save original display PNGs."""
    from .av_runtime import open_media
    from .orientation import orient_frame

    validate_clock(clock)
    if not source_id or any(not (c.isalnum() or c in "_-") for c in source_id):
        raise ValueError("Invalid source identifier")
    selected = sorted({m["frame"] for m in memberships})
    if not selected or selected[-1] >= len(clock["frames"]):
        raise ValueError("Invalid selected native membership")
    source_sha = file_hash(source_path)
    if source_sha != clock["source_sha256"]:
        raise ValueError("Source bytes changed")
    images = []
    threaded = _threaded()
    with open_media(str(source_path)) as container:
        if len(container.streams.video) != 1 or container.streams.audio:
            raise ValueError("Expected original video-only stream")
        stream = container.streams.video[0]
        stream.thread_type = "AUTO" if threaded else "NONE"
        if not threaded:
            stream.codec_context.thread_count = 1
        for ordinal, frame in enumerate(container.decode(stream)):
            budget.check()
            if (
                ordinal >= len(clock["frames"])
                or _frame_identity(frame, ordinal) != clock["frames"][ordinal]
            ):
                raise ValueError("Decoded native identity differs from sealed census")
            if ordinal in selected:
                row = {
                    **clock["frames"][ordinal],
                    "scene": "unknown",
                    "camera_view": "unreviewed",
                    "image": None,
                }
                if not row["corrupt"] and row["orientation_error"] is None:
                    raw = io.BytesIO()
                    orient_frame(
                        frame, expected_rotation=row["rotation"]
                    ).to_image().save(raw, format="PNG")
                    path = Path(output) / source_id / f"{ordinal:09d}.png"
                    row["image"] = {
                        "path": path.relative_to(budget.output).as_posix(),
                        **budget.publish(path, raw.getvalue()),
                    }
                images.append(row)
            if ordinal == selected[-1]:
                break
    if [r["frame"] for r in images] != selected or file_hash(source_path) != source_sha:
        raise ValueError("Truncated native prefix or changed source")
    return {
        "schema_version": 1,
        "source_id": source_id,
        "source_sha256": source_sha,
        "clock_sha256": hashlib.sha256(encoded(clock)).hexdigest(),
        "memberships": memberships,
        "frames": images,
        "eligibility": dict(ELIGIBILITY),
    }


def verify_packet(packet, output, clock, memberships):
    from PIL import Image

    validate_clock(clock)
    _eligibility(packet["eligibility"])
    if (
        packet["memberships"] != memberships
        or packet["source_sha256"] != clock["source_sha256"]
        or packet.get("clock_sha256") != hashlib.sha256(encoded(clock)).hexdigest()
        or [r["frame"] for r in packet["frames"]]
        != sorted({m["frame"] for m in memberships})
    ):
        raise ValueError("Packet membership/source changed")
    for row in packet["frames"]:
        if (
            {k: row.get(k) for k in clock["frames"][row["frame"]]}
            != clock["frames"][row["frame"]]
            or row.get("scene") != "unknown"
            or row.get("camera_view") != "unreviewed"
        ):
            raise ValueError("Native frame/camera identity changed")
        image = row.get("image")
        available = not row["corrupt"] and row["orientation_error"] is None
        if bool(image) != available:
            raise ValueError("Missing/hidden native image")
        if image:
            if image["path"] != f"images/{packet['source_id']}/{row['frame']:09d}.png":
                raise ValueError("Native ordinal image path changed")
            path = contained(output, Path(output) / image["path"])
            if (
                file_hash(path) != image["sha256"]
                or path.stat().st_size != image["bytes"]
            ):
                raise ValueError("Native image bytes changed")
            with Image.open(path) as png:
                if png.format != "PNG" or list(png.size) != row["display_size"]:
                    raise ValueError("Original display PNG geometry changed")
                png.verify()
    return packet


def plan_chunks(packet, *, dense, overlap=2, protocol=None):
    """Keep contiguous native membership and charge overlap/repeats explicitly."""
    frames = packet["frames"]
    session_limit = _session_limit(protocol)
    if (
        protocol is not None
        and overlap != protocol["assessment"]["chunk_overlap_frames"]
    ):
        raise ValueError("Protocol overlap changed")
    if not frames or any(not r.get("image") for r in frames):
        raise ValueError("Unavailable native frames cannot become exhaustive coverage")
    for row in frames:
        _integer(row["image"]["bytes"], 1)
    if dense and any(
        b["frame"] != a["frame"] + 1 for a, b in itertools.pairwise(frames)
    ):
        raise ValueError("Dense packet has a native frame gap")
    chunks, start = [], 0
    while start < len(frames):
        end, size = start, 0
        while (
            end < len(frames)
            and end - start < MAX_IMAGES
            and size + frames[end]["image"]["bytes"] <= session_limit
        ):
            if protocol and protocol["schema_version"] == 4:
                try:
                    transport_cost(
                        [row["image"]["bytes"] for row in frames[start : end + 1]],
                        protocol=protocol,
                    )
                except ValueError:
                    break
            size += frames[end]["image"]["bytes"]
            end += 1
        if end == start or (chunks and end <= chunks[-1]["end_index"]):
            raise ValueError(
                "Original PNGs plus required overlap exceed session budget"
            )
        chunks.append(
            {
                "index": len(chunks),
                "start_index": start,
                "end_index": end,
                "frames": [r["frame"] for r in frames[start:end]],
                "image_bytes": size,
            }
        )
        if protocol and protocol["schema_version"] == 4:
            cost = transport_cost(
                [row["image"]["bytes"] for row in frames[start:end]], protocol=protocol
            )
            chunks[-1]["base64_bytes"] = cost["base64_image_bytes"]
        if end == len(frames):
            break
        if end - start <= overlap:
            raise ValueError(
                "Insufficient bounded chunk capacity for continuity overlap"
            )
        start = end - overlap
    return chunks


def payload_cost(chunks, streams=3, prior_bytes=0, *, protocol=None):
    chunks = list(chunks)
    _integer(streams, 1)
    _integer(prior_bytes)
    for chunk in chunks:
        _integer(chunk["image_bytes"], 1)
    _session_limit(protocol)
    maximum = (
        protocol["payload"]["max_total_image_bytes"] if protocol else MAX_PAYLOAD_BYTES
    )
    if (
        protocol
        and protocol["schema_version"] >= 3
        and prior_bytes < protocol["predecessor"]["image_bytes"]
    ):
        raise ValueError("All predecessor attempted image bytes must remain charged")
    total = prior_bytes + sum(c["image_bytes"] for c in chunks) * streams
    if total > maximum:
        raise ValueError("Cumulative image payload budget would be exceeded")
    return total


def verify_worker(output, root):
    """An independent observer must establish original lifetime and Store exit."""
    admission, terminal = (
        read_json(Path(output) / "admission.json"),
        read_json(Path(output) / "terminal.json"),
    )
    process = admission["process"]
    if file_hash(Path(output) / "context.json") != admission.get("context_sha256"):
        raise ValueError("Saved prospective context seal changed")
    expected_slots = {
        "sources": [
            {"source_id": sid, "status": "unavailable", "complete_reference": False}
            for sid in SOURCE_IDS
        ],
        "eligibility": dict(ELIGIBILITY),
    }
    if read_json(Path(output) / "slots.json") != expected_slots:
        raise ValueError("Original planned source slots changed")
    if (
        terminal["job_id"] != admission["job_id"]
        or terminal["status"] != "completed"
        or terminal["admission_sha256"] != file_hash(Path(output) / "admission.json")
    ):
        raise ValueError("Matching completed worker/terminal evidence required")
    try:
        if (
            abs(psutil.Process(process["pid"]).create_time() - process["creation_time"])
            < 0.01
        ):
            raise ValueError("Original worker lifetime is still alive")
    except psutil.NoSuchProcess:
        pass
    catalog = Path(root) / "data/processed/catalog.sqlite3"
    with sqlite3.connect(catalog.as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute(
            "select document from jobs where id=?", (admission["job_id"],)
        ).fetchone()
    job = json.loads(row[0]) if row else {}
    if (
        job.get("status") != "completed"
        or job.get("owner_pid") != process["pid"]
        or job.get("owner_started") != process["creation_time"]
        or job.get("summary") != terminal["summary"]
    ):
        raise ValueError("Matching real Store completed lifetime required")
    for relative, sha in terminal["artifacts"].items():
        if file_hash(contained(output, Path(output) / relative)) != sha:
            raise ValueError("Worker artifact seal changed")
    return {
        "original_lifetime_absent": True,
        "store_completed": True,
        "terminal_sha256": file_hash(Path(output) / "terminal.json"),
        "observed_at": time.time(),
    }


def _failed_successor_bytes(root, predecessor):
    """Recheck sealed failed dispatches and actual original process lifetimes."""
    base = Path(root) / ".cache/rally210-source-only-v1"
    frozen = predecessor["failed_successor"]
    aggregate_path = base / "final-incomplete-v1.json"
    if file_hash(aggregate_path) != frozen["aggregate_sha256"]:
        raise ValueError("Failed successor aggregate changed")
    aggregate = read_json(aggregate_path)
    _eligibility(aggregate.get("eligibility", {}))
    if (
        aggregate.get("task") != 210
        or aggregate.get("completed_original_streams") != 0
        or aggregate.get("complete_references") != 0
        or aggregate.get("successful_assessment_sessions") != 0
        or len(aggregate.get("failures", [])) != frozen["failed_sessions"]
        or {f.get("stream") for f in aggregate["failures"]} != set(STREAMS[:2])
    ):
        raise ValueError("Failed successor outcome changed")
    charged = 0
    reservations = set()
    threads = set()
    lifetimes = set()
    for failure in aggregate["failures"]:
        if failure.get("source_id") != SOURCE_IDS[0] or failure.get("chunk") != 0:
            raise ValueError("Failed successor membership changed")
        folder = (
            base / "dense-assessment-v1" / failure["stream"] / f"{SOURCE_IDS[0]}-000"
        )
        for name, key in (
            ("payload-reservation.json", "reservation_sha256"),
            ("finish.json", "receipt_sha256"),
            ("events.jsonl", "events_sha256"),
        ):
            if file_hash(folder / name) != failure[key]:
                raise ValueError("Original failed successor execution evidence changed")
        receipt = read_json(folder / "finish.json")
        reservation = read_json(folder / "payload-reservation.json")
        start = read_json(folder / "start.json")
        if (
            receipt.get("exited") is not True
            or receipt.get("exit_code") != 1
            or receipt.get("images") != reservation.get("images")
            or receipt.get("image_bytes") != reservation.get("image_bytes")
            or any(receipt.get(key) != value for key, value in start.items())
            or not receipt.get("thread_id")
            or (folder / "original-final.json").exists()
        ):
            raise ValueError("Original failed successor exit or membership changed")
        reservations.add(folder / "payload-reservation.json")
        threads.add(receipt["thread_id"])
        lifetimes.add((receipt["pid"], receipt["creation_time"]))
        try:
            process = psutil.Process(_integer(receipt["pid"], 1))
            if process.create_time() == receipt["creation_time"]:
                raise ValueError("Original failed successor lifetime remains present")
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied as error:
            raise ValueError(
                "Original successor lifetime cannot be verified"
            ) from error
        charged += _integer(reservation["image_bytes"], 1)
    if (
        charged != frozen["image_bytes"]
        or set(base.rglob("payload-reservation.json")) != reservations
        or len(threads) != frozen["failed_sessions"]
        or len(lifetimes) != frozen["failed_sessions"]
        or aggregate.get("new_attempted_image_bytes") != charged
        or aggregate.get("cumulative_image_bytes") != predecessor["image_bytes"]
        or aggregate.get("prior_charged_image_bytes")
        != predecessor["image_bytes_before_failed_successor"]
    ):
        raise ValueError("Failed successor charged byte accounting changed")
    return charged


def reuse_dense_packets(checkout, root, context, predecessor_output):
    """Verify existing native packets in place, without decoding or copying them.

    The archived producer deadline is evidence, not permission for new work.
    Only the current consumer context supplies the successor deadline.
    """
    root, checkout = Path(root).resolve(), Path(checkout).resolve()
    verify_context(checkout, context)
    protocol = load_protocol(checkout / context["protocol_path"])
    if protocol["schema_version"] not in (3, 4) or context["task"] != protocol["task"]:
        raise ValueError("Separately authorized dense reuse protocol required")
    output = contained(root / ".cache", predecessor_output)
    if output != root / ".cache/rally208-source-only-v1/dense-v1":
        raise ValueError("Reuse only the unchanged original dense lineage")
    predecessor = protocol["predecessor"]
    if file_hash(output / "context.json") != predecessor["context_sha256"]:
        raise ValueError("Original dense consumer context changed")
    archived = read_json(output / "context.json")
    if archived["inputs"] != protocol["sources"] or archived["task"] != 208:
        raise ValueError("Original source context changed")
    worker = verify_worker(output, root)
    if worker["terminal_sha256"] != predecessor["terminal_sha256"]:
        raise ValueError("Original Store terminal seal changed")
    base = output.parent
    selection_path = base / "dense-selection-v1.json"
    screening_path = base / "screening-sealed-v1.json"
    if (
        file_hash(selection_path) != predecessor["selection_sha256"]
        or file_hash(screening_path) != predecessor["screening_sha256"]
    ):
        raise ValueError("Original candidate or screening seal changed")
    selection = read_json(selection_path)
    screening = read_json(screening_path)
    if selection["sources"] != screening["sources"]:
        raise ValueError("Original screened bounds changed")
    for name, sha in selection["assessment_seals"].items():
        if file_hash(contained(base, base / name)) != sha:
            raise ValueError("Original source screening evidence changed")
    clocks = verify_originals(context["input_root"], protocol)
    plans = []
    for source in protocol["sources"]:
        sid = source["source_id"]
        path = output / f"{sid}.packet.json"
        if file_hash(path) != predecessor["dense_packets"][sid]:
            raise ValueError("Original dense packet changed")
        packet = read_json(path)
        bounds = screened_bounds(selection["sources"][sid])
        if bounds is None:
            raise ValueError("Both unchanged candidate slots must remain available")
        members = dense_memberships(clocks[sid], bounds)
        verify_packet(packet, output, clocks[sid], members)
        if (
            len(packet["frames"]) != predecessor["native_frames"][sid]
            or packet.get("context_sha256") != predecessor["context_sha256"]
            or packet.get("stage") != "dense"
        ):
            raise ValueError("Original dense membership or producer changed")
        plans.append(
            {
                "source_id": sid,
                "packet_sha256": file_hash(path),
                "bounds": bounds,
                "frames": len(packet["frames"]),
                "chunks": plan_chunks(packet, dense=True, protocol=protocol),
            }
        )
    charged = 340760009 + sum(
        read_json(path)["image_bytes"]
        for path in base.rglob("payload-reservation.json")
    )
    if protocol["schema_version"] == 4:
        if charged != predecessor["image_bytes_before_failed_successor"]:
            raise ValueError("Original predecessor attempted bytes changed")
        charged += _failed_successor_bytes(root, predecessor)
    if charged != predecessor["image_bytes"]:
        raise ValueError("Prior attempted payload accounting changed")
    chunks = [chunk for plan in plans for chunk in plan["chunks"]]
    total = payload_cost(chunks, streams=2, prior_bytes=charged, protocol=protocol)
    verify_context(checkout, context)
    return {
        "task": protocol["task"],
        "sources": plans,
        "source_slots": 2,
        "native_frames": sum(plan["frames"] for plan in plans),
        "prior_charged_image_bytes": charged,
        "cumulative_after_originals": total,
        "worker": worker,
        "eligibility": dict(ELIGIBILITY),
    }


def run_reuse(root, checkout, output, context_path, context_sha256, timestamp_path):
    """Publish exclusive verified reuse plans; never admit a new decode job."""
    root, checkout = Path(root).resolve(), Path(checkout).resolve()
    output = contained(root / ".cache", output)
    if (
        output.parent
        not in {
            root / ".cache/rally210-source-only-v1",
            root / ".cache/rally212-source-only-v1",
        }
        or output.exists()
    ):
        raise ValueError("Use a new exclusive successor reuse directory")
    if any(os.environ.get(name) for name in CREDENTIALS):
        raise ValueError("Clear account credentials before reuse")
    if file_hash(context_path) != context_sha256:
        raise ValueError("Successor context seal changed")
    context, stamp = read_json(context_path), read_json(timestamp_path)
    task = context.get("task")
    if (
        task not in (210, 212)
        or output.parent != root / f".cache/rally{task}-source-only-v1"
    ):
        raise ValueError("Successor output must belong to its frozen task")
    if (
        stamp.get("context_sha256") != context_sha256
        or stamp.get("commit") != context.get("commit")
        or not str(stamp.get("url", "")).startswith(
            f"https://github.com/Ken0u/badminton-match-analyzer/issues/{task}#issuecomment-"
        )
        or type(stamp.get("published_at")) not in (int, float)
        or not math.isfinite(stamp["published_at"])
        or not context["granted_at"] <= stamp["published_at"] <= time.time()
    ):
        raise ValueError("Public prospective successor timestamp required")
    plans = reuse_dense_packets(
        checkout, root, context, root / ".cache/rally208-source-only-v1/dense-v1"
    )
    output.mkdir(parents=True, exist_ok=False)
    for name, doc in (("context.json", context), ("plans.json", plans)):
        with (output / name).open("xb") as stream:
            stream.write(encoded(doc))
    return plans


def _same_frames(values, expected):
    return (
        isinstance(values, list)
        and all(type(n) is int for n in values)
        and values == expected
    )


def _same_frame_rows(rows, expected):
    return (
        isinstance(rows, list)
        and all(isinstance(row, dict) for row in rows)
        and _same_frames([row.get("frame") for row in rows], expected)
    )


def _interval(value, allowed):
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(n) is not int for n in value)
        or not allowed[0] <= value[0] <= value[1] <= allowed[-1]
    ):
        raise ValueError(
            "Inclusive native interval outside inspected source membership"
        )
    return value


def validate_assessment(
    document, packet, chunk, receipt, *, stage, stream, previous=None, protocol=None
):
    """Bind actual independent execution, exact inspected images and own joins."""
    if stage not in {"overview", "dense"} or stream not in STREAMS:
        raise ValueError("Unknown source assessment lane")
    _eligibility(document.get("eligibility", {}))
    frames = {r["frame"]: r for r in packet["frames"]}
    selected = chunk["frames"]
    expected_rows = packet["frames"][chunk["start_index"] : chunk["end_index"]]
    _integer(chunk["image_bytes"], 1)
    for row in expected_rows:
        _integer(row["image"]["bytes"], 1)
    if (
        not _same_frames(selected, [row["frame"] for row in expected_rows])
        or not 1 <= len(selected) <= MAX_IMAGES
        or len(set(selected)) != len(selected)
        or chunk["image_bytes"] != sum(row["image"]["bytes"] for row in expected_rows)
        or chunk["image_bytes"] > _session_limit(protocol)
        or (
            stage == "dense"
            and any(b != a + 1 for a, b in itertools.pairwise(selected))
        )
    ):
        raise ValueError("Assigned chunk membership or payload budget changed")
    expected_images = [
        {"frame": n, "sha256": frames[n]["image"]["sha256"]} for n in selected
    ]
    if (
        document.get("stage") != stage
        or document.get("stream") != stream
        or document.get("source_id") != packet["source_id"]
        or not _same_frame_rows(document.get("inspected_frames"), selected)
        or document.get("inspected_frames") != expected_images
    ):
        raise ValueError("Assessment must inspect every exact assigned source image")
    if (
        not isinstance(receipt.get("thread_id"), str)
        or not receipt["thread_id"].strip()
        or not isinstance(receipt.get("session_id"), str)
        or not receipt["session_id"].strip()
        or type(receipt.get("exit_code")) is not int
        or receipt.get("exit_code") != 0
        or receipt.get("exited") is not True
        or receipt.get("segment_sha256")
        != hashlib.sha256(encoded(document)).hexdigest()
        or not _same_frame_rows(receipt.get("images"), selected)
        or receipt.get("images") != expected_images
        or receipt.get("image_bytes") != chunk["image_bytes"]
        or document.get("session_id") != receipt.get("session_id")
    ):
        raise ValueError("Actual exited fresh session/image/output receipt required")
    if protocol and protocol["schema_version"] == 4:
        cost = receipt.get("transport_cost")
        if not isinstance(cost, dict):
            raise ValueError("Encoded transport cost receipt required")
        expected_cost = transport_cost(
            [row["image"]["bytes"] for row in expected_rows],
            context_bytes=cost.get("context_bytes"),
            protocol=protocol,
        )
        if (
            encoded(cost) != encoded(expected_cost)
            or chunk.get("base64_bytes") != expected_cost["base64_image_bytes"]
        ):
            raise ValueError(
                "Encoded transport cost or assigned image rounding changed"
            )
    if (
        receipt.get("original_resolution_viewing") is not True
        or document.get("independent_source_only") is not True
    ):
        raise ValueError("Source-only original image inspection required")
    if previous is None:
        if document.get("previous_segment_sha256") is not None:
            raise ValueError("First chunk cannot claim inherited continuity")
    elif (
        document.get("previous_segment_sha256") != previous["sha256"]
        or not document.get("continuity_notes")
        or previous.get("stream") != stream
        or previous.get("source_id") != packet["source_id"]
        or previous.get("stage") != stage
        or (
            stage == "dense"
            and not _same_frames(previous.get("last_frames"), selected[:2])
        )
    ):
        raise ValueError("Missing own-stream continuity at chunk join")
    if stage == "overview":
        rows = document.get("frames", [])
        if not _same_frame_rows(rows, selected) or any(
            r.get("state") not in STATES or not r.get("reason") for r in rows
        ):
            raise ValueError("Missing/duplicate/unreviewed screening row")
    else:
        if (
            document.get("coverage_complete") is not True
            or document.get("scene") not in SCENES
            or type(document.get("unresolved_gaps")) is not list
        ):
            raise ValueError("Explicit exhaustive coverage/context and gaps required")
        for gap in document["unresolved_gaps"]:
            _interval(gap["interval"], selected)
            if not gap.get("reason"):
                raise ValueError("Unknown gaps require reasons")
        actors = document.get("actors", [])
        ids = [a.get("actor_id") for a in actors]
        if len(set(ids)) != len(ids) or any(
            not a.get("actor_id")
            or not a.get("description")
            or type(a.get("identity_supported")) is not bool
            for a in actors
        ):
            raise ValueError("Distinct source actor definitions required")
        events = document.get("events", [])
        coverage = document.get("frame_states", [])
        if not _same_frame_rows(coverage, selected) or any(
            r.get("scene") not in SCENES
            or not r.get("camera_view")
            or r.get("contact_state")
            not in {"none_observed", "observed", "possible", "unknown"}
            for r in coverage
        ):
            raise ValueError(
                "Every native frame needs explicit source/camera/contact coverage"
            )
        last = -1
        seen_events = set()
        for event in events:
            interval = _interval(event.get("interval"), selected)
            key = (event.get("kind"), tuple(interval))
            if key in seen_events:
                raise ValueError("Duplicate within-chunk event enumeration")
            seen_events.add(key)
            if (
                interval[0] < last
                or event.get("kind")
                not in {"serve", "shot", "rally_end", "unresolved_contact"}
                or not event.get("reason")
            ):
                raise ValueError("Ordered supported source events required")
            last = interval[0]
            if event["kind"] in {"serve", "shot"}:
                if (
                    event.get("actor_id") not in [*ids, None]
                    or event.get("side") not in SIDES
                ):
                    raise ValueError("Source hitter/side unknown must remain explicit")
                if (event["kind"] == "serve" and event.get("family") is not None) or (
                    event["kind"] == "shot" and event.get("family") not in FAMILIES
                ):
                    raise ValueError("Serve/family taxonomy changed")
            elif event["kind"] == "rally_end" and event.get("evidence") not in {
                "ground_contact",
                "net_fault",
                "fault",
                "stopped_play",
                "unknown",
            }:
                raise ValueError("Separate terminal evidence required")
        for row in coverage:
            if row["contact_state"] in {"observed", "possible"} and not any(
                e["kind"] in {"serve", "shot", "unresolved_contact"}
                and e["interval"][0] <= row["frame"] <= e["interval"][1]
                for e in events
            ):
                raise ValueError("Observed/possible contact missing from event list")
        if (
            type(document.get("start_censored")) is not bool
            or type(document.get("end_censored")) is not bool
        ):
            raise ValueError("Source censoring must remain explicit")
    return document


def _event_signature(event):
    return {
        k: event.get(k)
        for k in ("kind", "interval", "actor_id", "family", "side", "evidence")
    }


def _dense_lane(documents):
    """Normalize a validated lane while retaining every contradictory region."""
    frames, events, actors, disputed = {}, {}, {}, set()
    for doc, _ in documents:
        selected = {row["frame"] for row in doc["inspected_frames"]}
        if (
            doc.get("scene") != "live"
            or doc.get("coverage_complete") is not True
            or doc.get("start_censored")
            or doc.get("end_censored")
        ):
            disputed.update(selected)
        for gap in doc.get("unresolved_gaps", []):
            disputed.update(range(gap["interval"][0], gap["interval"][1] + 1))
        rows = doc.get("frame_states", [])
        if [row["frame"] for row in rows] != [
            row["frame"] for row in doc["inspected_frames"]
        ]:
            disputed.update(selected)
        for row in rows:
            n = row["frame"]
            if (n in frames and frames[n] != row) or (
                row.get("scene") != "live"
                or row.get("camera_view") in (None, "", "unknown", "unreviewed")
                or row.get("contact_state") in ("unknown", "possible")
            ):
                disputed.add(n)
            frames[n] = row
        local_actors = {a["actor_id"]: a for a in doc.get("actors", [])}
        for identity, actor in local_actors.items():
            if identity in actors and actors[identity] != actor:
                disputed.update(selected)
            actors[identity] = actor
        local_keys = set()
        for event in doc.get("events", []):
            key = (event["kind"], tuple(event["interval"]))
            signature = _event_signature(event)
            interval = set(range(event["interval"][0], event["interval"][1] + 1))
            if (
                key in local_keys
                or (key in events and events[key] != signature)
                or event["kind"] == "unresolved_contact"
                or (
                    event["kind"] in {"serve", "shot"}
                    and not local_actors.get(event.get("actor_id"), {}).get(
                        "identity_supported"
                    )
                )
                or (
                    event["kind"] == "rally_end"
                    and event.get("evidence") in {"unknown", "stopped_play"}
                )
            ):
                disputed.update(interval)
            local_keys.add(key)
            events[key] = signature
    for event in events.values():
        if event["kind"] in {"serve", "shot"} and not any(
            event["interval"][0] <= n <= event["interval"][1]
            and row.get("contact_state") in {"observed", "possible"}
            for n, row in frames.items()
        ):
            disputed.update(range(event["interval"][0], event["interval"][1] + 1))
    return frames, events, actors, disputed


def _matching_dense_sources(streams):
    sources, images = set(), {}
    for lane, documents in streams.items():
        for doc, _ in documents:
            if doc.get("stage") != "dense" or doc.get("stream") != lane:
                return False
            sources.add(doc.get("source_id"))
            for row in doc["inspected_frames"]:
                n, sha = row["frame"], row["sha256"]
                if n in images and images[n] != sha:
                    return False
                images[n] = sha
    return len(sources) == 1 and bool(next(iter(sources)))


def adjudication_targets(streams, *, native_frames):
    """Derive source regions needing a fresh verdict, never a third full stream."""
    if not all(lane in streams for lane in STREAMS[:2]):
        raise ValueError("Two exhaustive original streams required")
    if not _matching_dense_sources(streams):
        raise ValueError(
            "All lanes must bind the same dense source and original images"
        )
    allowed = set(native_frames)
    lanes = [_dense_lane(streams[lane]) for lane in STREAMS[:2]]
    if any(set(lane[0]) != allowed for lane in lanes):
        raise ValueError("Both originals must inspect every native frame")
    a, b = lanes
    targets = a[3] | b[3] | {n for n in allowed if a[0][n] != b[0][n]}
    for key in set(a[1]) | set(b[1]):
        if a[1].get(key) != b[1].get(key):
            targets.update(range(key[1][0], key[1][1] + 1))
        elif key[0] in {"serve", "shot"}:
            actor = a[1][key].get("actor_id")
            if a[2].get(actor) != b[2].get(actor):
                targets.update(range(key[1][0], key[1][1] + 1))
    # An uncertain contact interval cannot be resolved using only a fragment.
    intervals = [key[1] for lane in lanes for key in lane[1]]
    while True:
        before = set(targets)
        for first, last in intervals:
            region = set(range(first, last + 1))
            if targets & region:
                targets.update(region)
        if targets == before:
            break
    if not targets <= allowed:
        raise ValueError("Adjudication interval escapes original native membership")
    return sorted(targets)


def targeted_reference_status(streams, *, native_frames, bounds):
    """Combine agreed original regions with separately inspected resolutions.

    Inputs are original documents already bound by validate_assessment. The
    composite below is a calculation, not a new scientific session or verdict.
    """
    allowed = set(native_frames)
    targets = set(adjudication_targets(streams, native_frames=allowed))
    documents = [item for lane in STREAMS for item in streams.get(lane, [])]
    threads = [receipt.get("thread_id") for _, receipt in documents]
    sessions = [doc.get("session_id") for doc, _ in documents]
    if (
        not all(threads)
        or not all(sessions)
        or len(set(threads)) != len(threads)
        or len(set(sessions)) != len(sessions)
    ):
        raise ValueError("Actual distinct original and adjudication sessions required")
    a = _dense_lane(streams[STREAMS[0]])
    resolved = _dense_lane(streams.get("adjudication", []))
    covered = set(resolved[0])
    reasons = []
    if not targets <= covered or not covered <= allowed:
        reasons.append("missing_targeted_source_adjudication")
    if resolved[3]:
        reasons.append("unresolved_targeted_source_evidence")
    # Additional context may be inspected, but all intersecting events must be
    # completely covered; do not truncate events at an adjudication edge.
    for lane in STREAMS[:2]:
        for key in _dense_lane(streams[lane])[1]:
            region = set(range(key[1][0], key[1][1] + 1))
            if region & covered and not region <= covered:
                reasons.append("partial_targeted_event_interval")
    final_frames = {n: row for n, row in a[0].items() if n not in covered}
    final_frames.update(resolved[0])
    final_events = {
        key: event
        for key, event in a[1].items()
        if not set(range(key[1][0], key[1][1] + 1)) & covered
    }
    if any(event["kind"] in {"serve", "shot"} for event in final_events.values()):
        # A composite with retained original contacts needs a supported identity
        # link into the independent resolution. Reused names, changed people or
        # independently invented IDs cannot silently become one source roster.
        # If all contacts are replaced, their identities come from the single
        # resolution lane instead and no cross-lane link is inferred.
        original_actors, ambiguous_actors = {}, set()
        for doc, _ in streams[STREAMS[0]]:
            if not any(
                event["kind"] in {"serve", "shot"}
                and (event["kind"], tuple(event["interval"])) in final_events
                for event in doc["events"]
            ):
                continue
            # Use the definitions supporting retained contacts, not a later
            # conflicting chunk's last-write-wins actor registry.
            for actor in doc["actors"]:
                identity = actor["actor_id"]
                if identity in original_actors and original_actors[identity] != actor:
                    ambiguous_actors.add(identity)
                original_actors[identity] = actor
        for event in resolved[1].values():
            actor = event.get("actor_id")
            if event["kind"] in {"serve", "shot"} and (
                actor in ambiguous_actors
                or original_actors.get(actor) != resolved[2].get(actor)
            ):
                reasons.append("unlinked_targeted_source_actor")
    final_events.update(resolved[1])
    events = sorted(final_events.values(), key=lambda e: (e["interval"], e["kind"]))
    for frame, row in final_frames.items():
        if row["contact_state"] == "observed" and not any(
            e["kind"] in {"serve", "shot"}
            and e["interval"][0] <= frame <= e["interval"][1]
            for e in events
        ):
            reasons.append("observed_contact_missing_from_resolution")
    contacts = [e for e in events if e["kind"] in {"serve", "shot"}]
    serves = [e for e in contacts if e["kind"] == "serve"]
    endings = [e for e in events if e["kind"] == "rally_end"]
    if (
        len(serves) != 1
        or len(endings) != 1
        or not contacts
        or contacts[0]["kind"] != "serve"
        or not bounds["start_frame"]
        <= serves[0]["interval"][0]
        <= serves[0]["interval"][1]
        < endings[0]["interval"][0]
        <= endings[0]["interval"][1]
        <= bounds["end_frame"]
        or contacts[-1]["interval"][1] >= endings[0]["interval"][0]
    ):
        reasons.append("unsupported_opening_or_terminal_boundary")
    if any(
        left["interval"][1] >= right["interval"][0]
        for left, right in itertools.pairwise(contacts)
    ):
        reasons.append("overlapping_contact_intervals")
    return {
        "complete_reference": not reasons,
        "reasons": sorted(set(reasons)),
        "required_adjudication_frames": len(targets),
        "inspected_adjudication_frames": len(covered),
        "all_requested_labels_supported": not reasons
        and all(
            e.get("side") != "unknown" and e.get("family") not in {"unknown", "other"}
            for e in contacts
        ),
        "eligibility": dict(ELIGIBILITY),
    }


def reference_status(streams, *, native_frames, bounds):
    """Fail closed on disagreements, gaps or unobserved start/end/identity."""
    if set(streams) != set(STREAMS):
        return {
            "complete_reference": False,
            "reason": "missing_independent_stream_or_adjudication",
        }
    threads = [r["thread_id"] for documents in streams.values() for _, r in documents]
    sessions = [d["session_id"] for documents in streams.values() for d, _ in documents]
    if len(set(threads)) != len(threads) or len(set(sessions)) != len(sessions):
        raise ValueError(
            "Assessors/adjudicators must be genuinely distinct fresh sessions"
        )
    records = {}
    reasons = []
    if not _matching_dense_sources(streams):
        reasons.append("source_or_image_membership_mismatch")
    for lane, documents in streams.items():
        coverage = set()
        native_states = {}
        actor_definitions = {}
        events = {}
        for doc, _receipt in documents:
            coverage.update(row["frame"] for row in doc["inspected_frames"])
            if (
                doc.get("scene") != "live"
                or doc.get("unresolved_gaps")
                or doc.get("start_censored")
                or doc.get("end_censored")
                or doc.get("coverage_complete") is not True
            ):
                reasons.append("unknown_context_gap_or_censoring")
            if any(
                r.get("scene") != "live"
                or r.get("camera_view") in {None, "", "unknown", "unreviewed"}
                or r.get("contact_state") in {"unknown", "possible"}
                for r in doc.get("frame_states", [])
            ):
                reasons.append("unresolved_native_frame_context_or_contact")
            if [r.get("frame") for r in doc.get("frame_states", [])] != [
                r["frame"] for r in doc["inspected_frames"]
            ]:
                reasons.append("missing_explicit_native_frame_review")
            actors = {
                a["actor_id"] for a in doc.get("actors", []) if a["identity_supported"]
            }
            for actor in doc.get("actors", []):
                identity = actor["actor_id"]
                if (
                    identity in actor_definitions
                    and actor_definitions[identity] != actor
                ):
                    reasons.append("conflicting_source_actor_definition")
                actor_definitions[identity] = actor
            for row in doc.get("frame_states", []):
                frame = row["frame"]
                if frame in native_states and native_states[frame] != row:
                    reasons.append("conflicting_native_frame_chunk_join")
                native_states[frame] = row
            local_events = set()
            for event in doc.get("events", []):
                if event["kind"] == "unresolved_contact" or (
                    event["kind"] in {"serve", "shot"}
                    and event.get("actor_id") not in actors
                ):
                    reasons.append("unresolved_contact_or_actor")
                key = (event["kind"], tuple(event["interval"]))
                if key in local_events:
                    reasons.append("duplicate_within_chunk_event")
                local_events.add(key)
                signature = {
                    k: event.get(k)
                    for k in (
                        "kind",
                        "interval",
                        "actor_id",
                        "family",
                        "side",
                        "evidence",
                    )
                }
                if key in events and events[key] != signature:
                    reasons.append("conflicting_chunk_join")
                events[key] = signature
        if coverage != set(native_frames):
            reasons.append("incomplete_native_frame_coverage")
        records[lane] = sorted(
            events.values(), key=lambda e: (e["interval"], e["kind"])
        )
    normalized = [_dense_lane(streams[lane]) for lane in STREAMS]
    if any(lane[3] for lane in normalized):
        reasons.append("unresolved_native_source_evidence")
    if any(lane[0] != normalized[0][0] for lane in normalized[1:]):
        reasons.append("source_native_frame_disagreement")
    if any(lane[2] != normalized[0][2] for lane in normalized[1:]):
        reasons.append("source_actor_definition_disagreement")
    # Agreement never erases an unresolved case. Explicit source adjudication is
    # preserved separately; disagreements stay incomplete in this conservative v1.
    if (
        records[STREAMS[0]] != records[STREAMS[1]]
        or records[STREAMS[0]] != records[STREAMS[2]]
    ):
        reasons.append("source_disagreement_requires_resolution")
    events = records["adjudication"]
    serves = [e for e in events if e["kind"] == "serve"]
    endings = [e for e in events if e["kind"] == "rally_end"]
    if (
        len(serves) != 1
        or len(endings) != 1
        or not bounds["start_frame"]
        <= serves[0]["interval"][0]
        <= serves[0]["interval"][1]
        < endings[0]["interval"][0]
        <= endings[0]["interval"][1]
        <= bounds["end_frame"]
    ):
        reasons.append("unsupported_opening_or_terminal_boundary")
    elif endings[0]["evidence"] in {"unknown", "stopped_play"}:
        reasons.append("terminal_moment_unresolved")
    contacts = [e for e in events if e["kind"] in {"serve", "shot"}]
    if (
        endings
        and contacts
        and contacts[-1]["interval"][1] >= endings[0]["interval"][0]
    ):
        reasons.append("contact_is_not_terminal_evidence")
    if contacts and contacts[0]["kind"] != "serve":
        reasons.append("contact_precedes_opening_serve")
    if any(
        left["interval"][1] >= right["interval"][0]
        for left, right in itertools.pairwise(contacts)
    ):
        reasons.append("overlapping_contact_intervals")
    return {
        "complete_reference": not reasons,
        "reasons": sorted(set(reasons)),
        "all_requested_labels_supported": not reasons
        and all(
            e.get("side") != "unknown" and e.get("family") not in {"unknown", "other"}
            for e in contacts
        ),
        "eligibility": dict(ELIGIBILITY),
    }


def screened_bounds(row):
    """Keep unsupported slots explicit while preparing a warranted other slot."""
    if row.get("complete_reference") is not False:
        raise ValueError("Screening never certifies a complete reference")
    if row.get("status") == "unresolved" and row.get("bounds") is None:
        return None
    if row.get("status") != "provisional" or not isinstance(row.get("bounds"), dict):
        raise ValueError("Retain an explicit unresolved or provisional source slot")
    return row["bounds"]


def verify_selection(selection, selection_path, timestamp, root, protocol=None):
    """Bind the exact prospectively timestamped screening decision and originals."""
    task = protocol["task"] if protocol else 62
    base = Path(root) / f".cache/rally{task}-source-only-v1"
    contained(base, selection_path)
    if timestamp.get("selection_sha256") != file_hash(selection_path):
        raise ValueError(
            "Prospective dense timestamp must bind exact screening decision"
        )
    if (
        set(selection.get("sources", {})) != set(SOURCE_IDS)
        or selection.get("screening_sealed") is not True
    ):
        raise ValueError("Retain both independently screened original source slots")
    _eligibility(selection.get("eligibility", {}))
    seals = selection.get("assessment_seals", {})
    if not seals or not any(name.endswith("original-final.json") for name in seals):
        raise ValueError("Original scientific assessments and receipts required")
    for name, sha in seals.items():
        if file_hash(contained(base, base / name)) != sha:
            raise ValueError("Sealed original screening evidence changed")
    if "screening_original" in selection:
        original = selection["screening_original"]
        path = contained(base, base / original["path"])
        if file_hash(path) != original["sha256"]:
            raise ValueError("Original screening handoff seal changed")
        prior = read_json(path)
        if (
            prior["sources"] != selection["sources"]
            or prior["assessment_seals"] != seals
        ):
            raise ValueError(
                "A new producer context cannot change screened source decisions"
            )
    chosen = [screened_bounds(row) for row in selection["sources"].values()]
    if not any(chosen):
        raise ValueError("No warranted provisional source slot for dense preparation")
    finals = [
        (base / name, read_json(base / name))
        for name in seals
        if name.endswith("original-final.json")
    ]
    verify_worker(base / "overview-v1", root)
    original_context = read_json(base / "overview-v1/context.json")
    threads, sessions = [], []
    for source_id in SOURCE_IDS:
        source = next(
            row for row in original_context["inputs"] if row["source_id"] == source_id
        )
        clock_path = contained(
            original_context["input_root"],
            Path(original_context["input_root"]) / source_id / "clock.json",
        )
        if file_hash(clock_path) != source["clock_sha256"]:
            raise ValueError("Original screening census changed")
        clock = read_json(clock_path)
        packet = read_json(base / "overview-v1" / f"{source_id}.packet.json")
        members = overview_memberships(clock, protocol)
        verify_packet(packet, base / "overview-v1", clock, members)
        chunks = plan_chunks(packet, dense=False, overlap=0)
        for lane in STREAMS:
            documents = [
                (path, doc)
                for path, doc in finals
                if doc.get("source_id") == source_id and doc.get("stream") == lane
            ]
            documents.sort(key=lambda item: item[1]["inspected_frames"][0]["frame"])
            if len(documents) != len(chunks):
                raise ValueError("Missing independent screening chunk")
            previous = None
            states = {}
            for (path, doc), chunk in zip(documents, chunks, strict=True):
                receipt_path = path.with_name("finish.json")
                if receipt_path.relative_to(base).as_posix() not in seals:
                    raise ValueError(
                        "Actual original scientific receipt missing from seal"
                    )
                receipt = read_json(receipt_path)
                if receipt.get("original_output_sha256") != file_hash(path):
                    raise ValueError("Original scientific output changed")
                validate_assessment(
                    doc,
                    packet,
                    chunk,
                    receipt,
                    stage="overview",
                    stream=lane,
                    previous=previous,
                )
                threads.append(receipt["thread_id"])
                sessions.append(receipt["session_id"])
                states.update({row["frame"]: row for row in doc["frames"]})
                previous = {
                    "sha256": receipt["segment_sha256"],
                    "stream": lane,
                    "source_id": source_id,
                    "stage": "overview",
                    "last_frames": chunk["frames"][-2:],
                }
            candidate = earliest_candidate(
                clock, {"frames": [states[m["frame"]] for m in members]}, protocol
            )
            if selection["sources"][source_id]["original_candidates"][
                lane
            ] != candidate or (
                lane == "adjudication"
                and selection["sources"][source_id]["bounds"] != candidate
            ):
                raise ValueError("Frozen earliest warranted screening decision changed")
    if (
        len(threads) != len(finals)
        or len(set(threads)) != len(threads)
        or len(set(sessions)) != len(sessions)
    ):
        raise ValueError("Scientific screening sessions are not independent")


def run_preparation(
    root,
    checkout,
    output,
    context_path,
    context_sha256,
    timestamp_path,
    *,
    stage,
    selection_path=None,
):
    from . import config
    from .jobs import run_local_job
    from .storage import Store

    root, checkout = Path(root).resolve(), Path(checkout).resolve()
    output = contained(root / ".cache", output)
    if (
        config.ROOT != root
        or config.DATA.resolve() != root / "data/processed"
        or config.WEIGHTS.resolve() != root / "models/weights"
        or not (config.DATA / "catalog.sqlite3").is_file()
    ):
        raise ValueError("Pin original roots and real existing Store before imports")
    if any(os.environ.get(name) for name in CREDENTIALS):
        raise ValueError("Clear account credentials before preparation")
    if (
        stage not in {"overview", "dense"}
        or output.exists()
        or output == root / ".cache"
    ):
        raise ValueError("Use a new exclusive stage lineage")
    if file_hash(context_path) != context_sha256:
        raise ValueError("Prospective context seal changed")
    context = read_json(context_path)
    verify_context(checkout, context)
    task_number = context.get("task", 62)
    timestamp = read_json(timestamp_path)
    if (
        timestamp.get("context_sha256") != context_sha256
        or not str(timestamp.get("url", "")).startswith(
            f"https://github.com/Ken0u/badminton-match-analyzer/issues/{task_number}#issuecomment-"
        )
        or timestamp.get("published_at", time.time() + 1) > time.time()
    ):
        raise ValueError("Public prospective timestamp receipt required")
    protocol = load_protocol(
        checkout
        / context.get(
            "protocol_path", "data/manifests/rally_reference_protocol_v1.json"
        )
    )
    if protocol.get("schema_version") in (3, 4):
        raise ValueError("Dense reuse protocol forbids new native preparation/decode")
    if context["inputs"] != protocol["sources"]:
        raise ValueError("Frozen original source declarations changed")
    selection = read_json(selection_path) if selection_path else None
    if stage == "dense" and (
        not selection
        or selection.get("context_sha256") != context_sha256
        or selection.get("screening_sealed") is not True
    ):
        raise ValueError(
            "Freeze independently screened bounds before dense preparation"
        )
    if stage == "dense":
        verify_selection(selection, selection_path, timestamp, root, protocol)
    lineage = contained(
        root / ".cache", root / f".cache/rally{task_number}-source-only-v1"
    )
    if output.parent != lineage:
        raise ValueError("All stages must share the fixed bounded task output lineage")
    maximum = protocol.get("limits", {}).get("max_output_bytes", MAX_OUTPUT_BYTES)
    prior_bytes = persisted_bytes(lineage, limit=maximum)
    if task_number == 208:
        original = root / ".cache/rally62-source-only-v1/screening-sealed-v1.json"
        if file_hash(original) != protocol["predecessor"]["screening_sha256"]:
            raise ValueError("Original failed pilot seal changed")
        prior_bytes += predecessor_output_bytes(root)
    output.mkdir(parents=True, exist_ok=False)
    budget = Budget(
        output,
        {
            "output_bytes": maximum,
            "worker_seconds": max(0, context["deadline"] - time.time()),
        },
        reserve_bytes=65536,
        prior={"output_bytes": prior_bytes},
    )
    budget.json(output / "context.json", context)
    budget.json(
        output / "slots.json",
        {
            "sources": [
                {"source_id": sid, "status": "unavailable", "complete_reference": False}
                for sid in SOURCE_IDS
            ],
            "eligibility": dict(ELIGIBILITY),
        },
    )
    process, job_id, artifacts = psutil.Process(), None, {}
    summary = None

    def task(identifier, progress):
        nonlocal job_id, summary
        job_id = identifier
        budget.json(
            output / "admission.json",
            {
                "job_id": identifier,
                "context_sha256": context_sha256,
                "stage": stage,
                "process": {
                    "pid": process.pid,
                    "creation_time": process.create_time(),
                    "cwd": process.cwd(),
                    "command": process.cmdline(),
                },
            },
        )
        artifacts.update(
            {name: file_hash(output / name) for name in ("context.json", "slots.json")}
        )
        clocks = verify_originals(context["input_root"], protocol)
        prepared, unresolved = [], []
        for index, source_id in enumerate(SOURCE_IDS):
            verify_context(checkout, context)
            clock = clocks[source_id]
            bounds = (
                screened_bounds(selection["sources"][source_id])
                if stage == "dense"
                else None
            )
            if stage == "dense" and bounds is None:
                unresolved.append(source_id)
                progress((index + 1) / len(SOURCE_IDS))
                continue
            members = (
                overview_memberships(clock, protocol)
                if stage == "overview"
                else dense_memberships(clock, bounds)
            )
            packet = extract_frames(
                Path(context["input_root"]) / source_id / "source.mp4",
                clock,
                members,
                output / "images",
                source_id,
                budget,
            )
            packet.update(
                stage=stage,
                clock_sha256=protocol["sources"][index]["clock_sha256"],
                context_sha256=context_sha256,
            )
            path = output / f"{source_id}.packet.json"
            budget.json(path, packet)
            artifacts[path.name] = file_hash(path)
            for row in packet["frames"]:
                if row["image"]:
                    artifacts[row["image"]["path"]] = row["image"]["sha256"]
            prepared.append(source_id)
            progress((index + 1) / len(SOURCE_IDS))
        verify_originals(context["input_root"], protocol)
        verify_context(checkout, context)
        summary = {
            "sources": len(SOURCE_IDS),
            "prepared_sources": prepared,
            "unresolved_sources": unresolved,
            "stage": stage,
            "context_sha256": context_sha256,
            "annotation_accuracy_established": False,
        }
        return summary

    try:
        run_local_job(
            Store(config.DATA),
            "rally_source_reference",
            f"source-only-rally{task_number}",
            task,
        )
    except BaseException:
        if job_id:
            budget.json(
                output / "terminal.json",
                {
                    "job_id": job_id,
                    "status": "failed",
                    "artifacts": artifacts,
                    "admission_sha256": file_hash(output / "admission.json"),
                    "summary": summary,
                },
            )
        raise
    budget.json(
        output / "terminal.json",
        {
            "job_id": job_id,
            "status": "completed",
            "artifacts": artifacts,
            "admission_sha256": file_hash(output / "admission.json"),
            "summary": summary,
        },
    )
    return summary
