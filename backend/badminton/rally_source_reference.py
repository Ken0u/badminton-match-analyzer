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
    if (
        protocol.get("schema_version") != 1
        or protocol.get("task") != 62
        or [s.get("source_id") for s in protocol.get("sources", [])] != list(SOURCE_IDS)
        or protocol["selection"]["overview_seconds"] != 300
        or protocol["selection"]["overview_step_seconds"] != 5
        or protocol["selection"]["max_rally_seconds"] != 40
        or protocol["selection"]["context_seconds_each_side"] != 4
        or protocol["assessment"]["chunk_overlap_frames"] != 2
        or protocol["payload"]["max_images_per_session"] != MAX_IMAGES
        or protocol["payload"]["max_image_bytes_per_session"] != MAX_SESSION_BYTES
        or protocol["payload"]["max_total_image_bytes"] != MAX_PAYLOAD_BYTES
        or protocol["limits"]["max_output_bytes"] != MAX_OUTPUT_BYTES
        or protocol["limits"]["task_seconds_from_grant"] != TASK_SECONDS
    ):
        raise ValueError("Unsupported source-only protocol")
    return protocol


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


def overview_memberships(clock):
    times = validate_clock(clock)
    result = []
    for second in range(0, 301, 5):
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


def earliest_candidate(clock, assessment):
    """Sparse evidence proposes a slot, never a complete reference."""
    members = overview_memberships(clock)
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
    if (
        Path(protocol_path).resolve()
        != (checkout / "data/manifests/rally_reference_protocol_v1.json").resolve()
    ):
        raise ValueError("Use committed protocol")
    protocol = load_protocol(protocol_path)
    return {
        "schema_version": 1,
        "task": 62,
        "commit": commit,
        "granted_at": _integer(granted_at),
        "deadline": granted_at + TASK_SECONDS,
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
        Path(checkout) / "data/manifests/rally_reference_protocol_v1.json",
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


def persisted_bytes(root):
    total = 0
    for path in Path(root).rglob("*"):
        contained(root, path)
        if path.is_symlink():
            raise ValueError("Output lineage contains symbolic links")
        if path.is_file():
            total += path.stat().st_size
    if total > MAX_OUTPUT_BYTES:
        raise ValueError("Cumulative persisted output ceiling exceeded")
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


def plan_chunks(packet, *, dense, overlap=2):
    """Keep contiguous native membership and charge overlap/repeats explicitly."""
    frames = packet["frames"]
    if not frames or any(not r.get("image") for r in frames):
        raise ValueError("Unavailable native frames cannot become exhaustive coverage")
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
            and size + frames[end]["image"]["bytes"] <= MAX_SESSION_BYTES
        ):
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
        if end == len(frames):
            break
        if end - start <= overlap:
            raise ValueError(
                "Insufficient bounded chunk capacity for continuity overlap"
            )
        start = end - overlap
    return chunks


def payload_cost(chunks, streams=3, prior_bytes=0):
    _integer(streams, 1)
    _integer(prior_bytes)
    total = prior_bytes + sum(c["image_bytes"] for c in chunks) * streams
    if total > MAX_PAYLOAD_BYTES:
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
    document, packet, chunk, receipt, *, stage, stream, previous=None
):
    """Bind actual independent execution, exact inspected images and own joins."""
    if stage not in {"overview", "dense"} or stream not in STREAMS:
        raise ValueError("Unknown source assessment lane")
    _eligibility(document.get("eligibility", {}))
    frames = {r["frame"]: r for r in packet["frames"]}
    selected = chunk["frames"]
    expected_rows = packet["frames"][chunk["start_index"] : chunk["end_index"]]
    if (
        selected != [row["frame"] for row in expected_rows]
        or not 1 <= len(selected) <= MAX_IMAGES
        or len(set(selected)) != len(selected)
        or chunk["image_bytes"] != sum(row["image"]["bytes"] for row in expected_rows)
        or chunk["image_bytes"] > MAX_SESSION_BYTES
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
        or document.get("inspected_frames") != expected_images
    ):
        raise ValueError("Assessment must inspect every exact assigned source image")
    if (
        not receipt.get("thread_id")
        or receipt.get("exit_code") != 0
        or receipt.get("exited") is not True
        or receipt.get("segment_sha256")
        != hashlib.sha256(encoded(document)).hexdigest()
        or receipt.get("images") != expected_images
        or receipt.get("image_bytes") != chunk["image_bytes"]
        or document.get("session_id") != receipt.get("session_id")
    ):
        raise ValueError("Actual exited fresh session/image/output receipt required")
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
        or (stage == "dense" and previous.get("last_frames") != selected[:2])
    ):
        raise ValueError("Missing own-stream continuity at chunk join")
    if stage == "overview":
        rows = document.get("frames", [])
        if [r.get("frame") for r in rows] != selected or any(
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
        if [r.get("frame") for r in coverage] != selected or any(
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
        for event in events:
            interval = _interval(event.get("interval"), selected)
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
    for lane, documents in streams.items():
        coverage = set()
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
            for event in doc.get("events", []):
                if event["kind"] == "unresolved_contact" or (
                    event["kind"] in {"serve", "shot"}
                    and event.get("actor_id") not in actors
                ):
                    reasons.append("unresolved_contact_or_actor")
                key = (event["kind"], tuple(event["interval"]))
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
    return {
        "complete_reference": not reasons,
        "reasons": sorted(set(reasons)),
        "all_requested_labels_supported": not reasons
        and all(
            e.get("side") != "unknown" and e.get("family") != "unknown"
            for e in contacts
        ),
        "eligibility": dict(ELIGIBILITY),
    }


def verify_selection(selection, selection_path, timestamp, root):
    """Bind the exact prospectively timestamped screening decision and originals."""
    base = Path(root) / ".cache/rally62-source-only-v1"
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
    if any(
        row.get("status") != "provisional"
        or not row.get("bounds")
        or row.get("complete_reference") is not False
        for row in selection["sources"].values()
    ):
        raise ValueError("Unresolved slots cannot become dense provisional rallies")
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
        members = overview_memberships(clock)
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
                clock, {"frames": [states[m["frame"]] for m in members]}
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
    timestamp = read_json(timestamp_path)
    if (
        timestamp.get("context_sha256") != context_sha256
        or not str(timestamp.get("url", "")).startswith(
            "https://github.com/Ken0u/badminton-match-analyzer/issues/62#issuecomment-"
        )
        or timestamp.get("published_at", time.time() + 1) > time.time()
    ):
        raise ValueError("Public prospective timestamp receipt required")
    protocol = load_protocol(
        checkout / "data/manifests/rally_reference_protocol_v1.json"
    )
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
        verify_selection(selection, selection_path, timestamp, root)
    lineage = contained(root / ".cache", root / ".cache/rally62-source-only-v1")
    if output.parent != lineage:
        raise ValueError("All stages must share the fixed bounded task output lineage")
    prior_bytes = persisted_bytes(lineage)
    output.mkdir(parents=True, exist_ok=False)
    budget = Budget(
        output,
        {
            "output_bytes": MAX_OUTPUT_BYTES,
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
        for index, source_id in enumerate(SOURCE_IDS):
            verify_context(checkout, context)
            clock = clocks[source_id]
            members = (
                overview_memberships(clock)
                if stage == "overview"
                else dense_memberships(clock, selection["sources"][source_id]["bounds"])
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
            progress((index + 1) / len(SOURCE_IDS))
        verify_originals(context["input_root"], protocol)
        verify_context(checkout, context)
        summary = {
            "sources": len(SOURCE_IDS),
            "stage": stage,
            "context_sha256": context_sha256,
            "annotation_accuracy_established": False,
        }
        return summary

    try:
        run_local_job(
            Store(config.DATA), "rally_source_reference", "source-only-rally62", task
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
