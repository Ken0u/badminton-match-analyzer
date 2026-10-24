"""Sparse derived temporal context; never exact contact or rally ground truth."""

from __future__ import annotations

import bisect
import hashlib
import io
import itertools
import math
import re
from collections import Counter
from fractions import Fraction
from pathlib import Path, PurePosixPath

from .shuttle_supervision import encoded, file_hash

LANES = ("independent_a", "independent_b", "adjudication")
SCENES = ("live", "replay", "non_play", "unknown")
PLAY = (
    "service_preparation",
    "exchange",
    "stopped_play",
    "non_play",
    "replay",
    "unknown",
)
ELIGIBILITY = dict.fromkeys(
    (
        "training_allowed",
        "independent_test_allowed",
        "model_deployment_allowed",
        "dataset_redistribution_allowed",
    ),
    False,
)
TILE = (640, 360)
CAPTION = 24
SHEET = (2560, 1536)
PRIOR_PAYLOAD = 8177560145


def validate_continuation(protocol, original):
    """A continuation changes ownership/runtime, never the sampling or rubric."""
    require(
        type(protocol.get("schema_version")) is int
        and protocol["schema_version"] == 2
        and type(protocol.get("task")) is int
        and protocol["task"] == 242
        and original.get("schema_version") == 1
        and original.get("task") == 240,
        "Exact original and continuation protocol identities required",
    )
    sha(protocol["spec_hash"])
    allowed = {"schema_version", "task", "spec_hash", "purpose", "limits"}
    require(
        set(protocol) == set(original) | {"continuation"}
        and fingerprint({k: protocol[k] for k in original if k not in allowed})
        == fingerprint({k: original[k] for k in original if k not in allowed}),
        "Continuation cannot change original sources, sampling, rubric or eligibility",
    )
    limits = protocol["limits"]
    expected = dict(original["limits"], new_image_bytes=34040436)
    require(fingerprint(limits) == fingerprint(expected), "Frozen limits changed")
    for key, value in limits.items():
        if key == "paid_services":
            require(value is False, "No paid service allowed")
        else:
            integer(value)
    continuation = protocol["continuation"]
    require(
        continuation["prepared_root"] == ".cache/rally240-source-only-v1"
        and continuation["producer_checkout"] == ".cache/worktrees/rally240-producer-v1"
        and continuation["native_receipts"] == ".cache/rally240-native-prepare-v1",
        "Reuse the original prefix in place",
    )
    require(
        type(continuation["original_task"]) is int
        and continuation["original_task"] == 240
        and type(continuation["original_attempted_sessions"]) is int
        and continuation["original_attempted_sessions"] == 0
        and type(continuation["original_transmitted_image_bytes"]) is int
        and continuation["original_transmitted_image_bytes"] == 0
        and continuation["rerendering_allowed"] is False
        and continuation["old_runtime_renewed"] is False,
        "Original blocked attempt and immutable runtime required",
    )
    for key in ("original_protocol_sha256", "context_sha256", "plan_sha256"):
        sha(continuation[key])
    require(
        set(continuation["manifests"]) == {s["source_id"] for s in protocol["sources"]},
        "Both unchanged source galleries required",
    )
    for checksum in continuation["manifests"].values():
        sha(checksum)
    expected_seals = {
        ".cache/rally240-source-only-v1/" + n
        for n in (
            "context.json",
            "pilot-plan.json",
            "metadata-gate.json",
            "preparation/admission.json",
            "preparation/terminal.json",
        )
    } | {
        ".cache/rally240-native-prepare-v1/" + n
        for n in (
            "owner.json",
            "finish.json",
            "audit.json",
            "stdout.log",
            "stderr.log",
        )
    }
    require(
        set(continuation["original_seals"]) == expected_seals,
        "Original process/artifact seals required",
    )
    for checksum in continuation["original_seals"].values():
        sha(checksum)
    return protocol


def continuation_deadline(grant, protocol, now, host):
    """Bind the fresh interval to its genuine committed task/owner approval."""
    task = grant["task"]
    claim = task["claim"]
    epoch = integer(claim["epoch"], 1)
    started = integer(claim["granted_at"], 1)
    expires = integer(claim["expires_at"], 1)
    receipt = grant["receipt"]
    require(
        receipt["status"] == "granted"
        and receipt["actor"] == "Ken0u"
        and receipt["task_id"] == "242"
        and type(receipt["epoch"]) is int
        and receipt["epoch"] == epoch
        and fingerprint({k: receipt["claim"][k] for k in claim if k != "expires_at"})
        == fingerprint({k: claim[k] for k in claim if k != "expires_at"}),
        "Committed original grant receipt required",
    )
    require(
        type(now) in (int, float)
        and math.isfinite(now)
        and host == claim["host_id"] == "MSI"
        and claim["actor"] == "Ken0u"
        and task["status"] == "running"
        and type(task["epoch"]) is int
        and task["epoch"] == epoch
        and task["spec_hash"] == claim["spec_hash"] == protocol["spec_hash"]
        and task["human_approval"]["spec_hash"] == protocol["spec_hash"]
        and task["human_approval"]["actor"] == "Ken0u"
        and started <= now < expires,
        "Fresh committed original-host and explicitly authorized grant required",
    )
    deadline = started + integer(protocol["limits"]["runtime_seconds"], 1)
    require(now < deadline, "Continuation runtime expired")
    return deadline


def verify_original_images(packet, original_root):
    """Hash every retained original PNG without decoding or changing any image."""
    available = 0
    for row in packet["frames"]:
        image = row["image"]
        if image is None:
            continue
        path = safe_file(original_root, image["path"])
        require(
            path.stat().st_size == integer(image["bytes"], 1)
            and file_hash(path) == sha(image["sha256"]),
            "Original PNG changed",
        )
        available += 1
    return {"native_frames": len(packet["frames"]), "original_pngs_verified": available}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, minimum=0):
    require(type(value) is int and value >= minimum, "Exact bounded integer required")
    return value


def sha(value):
    require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
        "SHA256 required",
    )
    return value


def text(value):
    require(
        isinstance(value, str) and bool(value.strip()) and len(value) <= 8192,
        "Bounded nonempty text required",
    )
    return value


def fingerprint(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def safe_file(root, name):
    require(
        isinstance(name, str) and bool(name) and "\\" not in name,
        "Relative artifact path required",
    )
    relative = PurePosixPath(name)
    require(
        not relative.is_absolute()
        and all(p not in (".", "..") and ":" not in p for p in relative.parts),
        "Unsafe artifact path",
    )
    root = Path(root)
    require(
        not root.is_symlink()
        and not getattr(root.lstat(), "st_file_attributes", 0) & 1024,
        "Linked artifact root",
    )
    path = root
    for part in relative.parts:
        path = path / part
        require(
            not path.is_symlink()
            and not getattr(path.lstat(), "st_file_attributes", 0) & 1024,
            "Linked artifact",
        )
    require(
        path.resolve().is_relative_to(root.resolve()) and path.is_file(),
        "Artifact outside root",
    )
    return path


def sample_plan(packet):
    """Retain every grid membership, including endpoint aliases/unavailability."""
    rows = packet["frames"]
    text(packet["source_id"])
    sha(packet["source_sha256"])
    sha(packet["clock_sha256"])
    require(
        packet["eligibility"] == ELIGIBILITY
        and all(type(v) is bool for v in packet["eligibility"].values()),
        "Ineligible source context required",
    )
    require(bool(rows), "Native source denominator required")
    times = []
    for row in rows:
        integer(row["frame"])
        require(type(row["pts"]) is int, "Exact native PTS required")
        require(isinstance(row["time_base"], str), "Native time base required")
        base = Fraction(row["time_base"])
        require(base > 0, "Positive native time base required")
        instant = row["pts"] * base
        require(
            type(row["time_s"]) in (int, float)
            and math.isfinite(row["time_s"])
            and abs(float(instant) - row["time_s"]) < 1e-6,
            "Native PTS/time disagreement",
        )
        times.append(instant)
        require(
            type(row["corrupt"]) is bool
            and type(row["rotation"]) is int
            and row["rotation"] in (0, 90, 180, 270),
            "Native orientation state required",
        )
        for name in ("source_size", "display_size"):
            require(
                isinstance(row[name], list) and len(row[name]) == 2,
                "Native geometry required",
            )
            for dimension in row[name]:
                integer(dimension, 1)
        expected = (
            row["source_size"][::-1]
            if row["rotation"] in (90, 270)
            else row["source_size"]
        )
        require(
            row["display_size"] == expected, "Oriented native geometry disagreement"
        )
    require(
        all(b["frame"] == a["frame"] + 1 for a, b in itertools.pairwise(rows)),
        "Whole unchanged dense native window required",
    )
    require(all(b >= a for a, b in itertools.pairwise(times)), "Source PTS reversal")
    require(times[-1] - times[0] <= 60, "Bounded original window required")
    memberships = [{"reason": "first", "frame": rows[0]["frame"]}]
    grid = 0
    while times[0] + grid <= times[-1]:
        index = bisect.bisect_left(times, times[0] + grid)
        memberships.append(
            {"reason": "grid", "offset_seconds": grid, "frame": rows[index]["frame"]}
        )
        grid += 1
    memberships.append({"reason": "last", "frame": rows[-1]["frame"]})
    selected = sorted({m["frame"] for m in memberships})
    by_frame = {r["frame"]: r for r in rows}
    samples = []
    for index, number in enumerate(selected):
        row = by_frame[number]
        available = (
            row["image"] is not None
            and row["corrupt"] is False
            and row["orientation_error"] is None
        )
        if row["image"] is not None:
            sha(row["image"]["sha256"])
            integer(row["image"]["bytes"], 1)
        samples.append(
            {
                "frame": number,
                "pts": row["pts"],
                "time_base": row["time_base"],
                "time_s": row["time_s"],
                "sheet": index // 16,
                "tile": index % 16,
                "available": available,
                "original_sha256": row["image"]["sha256"] if row["image"] else None,
                "display_size": row["display_size"],
                "rotation": row["rotation"],
            }
        )
    return {
        "source_id": packet["source_id"],
        "source_sha256": packet["source_sha256"],
        "clock_sha256": packet["clock_sha256"],
        "packet_sha256": fingerprint(packet),
        "native_frame_denominator": len(rows),
        "memberships": memberships,
        "samples": samples,
        "unsampled_native_frames": len(rows) - len(samples),
        "eligibility": dict(ELIGIBILITY),
        "evidence_kind": "derived_sparse_temporal_context",
        "exact_contact_evidence": False,
    }


def render_gallery(packet, original_root, output):
    """Create exclusive chronological galleries; originals are never modified."""
    from PIL import Image, ImageDraw, ImageOps

    plan = sample_plan(packet)
    output = Path(output)
    require(
        not output.exists() and not output.is_symlink(),
        "Exclusive new gallery required",
    )
    output.mkdir(parents=True)
    rows = {r["frame"]: r for r in packet["frames"]}
    sheets = []
    for start in range(0, len(plan["samples"]), 16):
        members = plan["samples"][start : start + 16]
        sheet = Image.new("RGB", SHEET, "black")
        draw = ImageDraw.Draw(sheet)
        for local, member in enumerate(members):
            x, y = local % 4 * TILE[0], local // 4 * (TILE[1] + CAPTION)
            if member["available"]:
                row = rows[member["frame"]]
                original = safe_file(original_root, row["image"]["path"])
                require(
                    original.stat().st_size == row["image"]["bytes"]
                    and file_hash(original) == row["image"]["sha256"],
                    "Original PNG changed",
                )
                with Image.open(original) as image:
                    require(
                        image.format == "PNG"
                        and list(image.size) == member["display_size"],
                        "Original PNG geometry/format changed",
                    )
                    image.load()
                    tile = ImageOps.pad(
                        image.convert("RGB"),
                        TILE,
                        method=Image.Resampling.LANCZOS,
                        color="black",
                    )
                    sheet.paste(tile, (x, y))
            else:
                draw.text((x + 8, y + 8), "UNAVAILABLE SOURCE SAMPLE", fill="white")
            label = f"DERIVED f={member['frame']} PTS={member['pts']} tb={member['time_base']} t={member['time_s']:.6f}"
            draw.text((x + 4, y + TILE[1] + 4), label, fill="white")
        raw = io.BytesIO()
        sheet.save(raw, format="PNG", compress_level=6)
        name = f"sheet-{len(sheets):03d}.png"
        data = raw.getvalue()
        with (output / name).open("xb") as handle:
            handle.write(data)
        sheets.append(
            {
                "path": name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "size": list(SHEET),
                "frames": [m["frame"] for m in members],
            }
        )
    manifest = {"schema_version": 1, "plan": plan, "sheets": sheets}
    with (output / "gallery.json").open("xb") as handle:
        handle.write(encoded(manifest))
    payload_cost(manifest)
    return manifest


def verify_gallery(manifest, packet, output):
    from PIL import Image

    require(
        type(manifest.get("schema_version")) is int
        and manifest["schema_version"] == 1
        and manifest["plan"] == sample_plan(packet),
        "Gallery plan/source binding changed",
    )
    selected = [r["frame"] for r in manifest["plan"]["samples"]]
    require(
        len(manifest["sheets"]) == math.ceil(len(selected) / 16),
        "Missing gallery sheets",
    )
    for index, row in enumerate(manifest["sheets"]):
        require(
            row["path"] == f"sheet-{index:03d}.png"
            and row["frames"] == selected[index * 16 : (index + 1) * 16]
            and row["size"] == list(SHEET),
            "Gallery tile membership changed",
        )
        path = safe_file(output, row["path"])
        require(
            type(row["bytes"]) is int
            and path.stat().st_size == row["bytes"]
            and file_hash(path) == sha(row["sha256"]),
            "Derived gallery bytes changed",
        )
        with Image.open(path) as image:
            require(
                image.format == "PNG" and image.size == SHEET,
                "Derived sheet geometry changed",
            )
            image.verify()
    payload_cost(manifest)
    return manifest


def payload_cost(manifest, *, context_bytes=0):
    integer(context_bytes)
    sizes = [integer(s["bytes"], 1) for s in manifest["sheets"]]
    require(
        0 < len(sizes) <= 20 and sum(sizes) <= 9 * 1024**2,
        "Gallery session payload exhausted",
    )
    encoded_bytes = sum(4 * ((n + 2) // 3) for n in sizes)
    require(
        context_bytes + len(sizes) * 1024 <= 2 * 1024**2
        and encoded_bytes + 2 * 1024**2 <= 14 * 1024**2,
        "Encoded transport budget exhausted",
    )
    return {
        "image_bytes": sum(sizes),
        "base64_bytes": encoded_bytes,
        "images": len(sizes),
    }


def validate_assessment(document, manifest, receipt, lane):
    plan = manifest["plan"]
    require(
        set(document)
        == {
            "source_id",
            "lane",
            "session_id",
            "gallery_sha256",
            "evidence_kind",
            "exact_contact_evidence",
            "eligibility",
            "inspected_sheets",
            "frame_states",
            "actors",
            "transitions",
            "limitations",
        },
        "Only coarse sparse-context fields permitted",
    )
    require(
        lane in LANES
        and document["lane"] == lane
        and document["source_id"] == plan["source_id"],
        "Source/lane mismatch",
    )
    require(
        document["gallery_sha256"] == fingerprint(manifest), "Gallery seal mismatch"
    )
    require(
        document["eligibility"] == ELIGIBILITY
        and all(type(v) is bool for v in document["eligibility"].values()),
        "All eligibility flags must remain false",
    )
    require(
        document["evidence_kind"] == "derived_sparse_temporal_context"
        and document["exact_contact_evidence"] is False,
        "Sparse context cannot certify contacts",
    )
    require(
        document["inspected_sheets"]
        == [{"path": s["path"], "sha256": s["sha256"]} for s in manifest["sheets"]],
        "Exact inspected gallery membership required",
    )
    require(
        type(receipt["exit_code"]) is int
        and receipt["exit_code"] == 0
        and receipt["exited"] is True
        and receipt["forbidden_items"] == [],
        "Successful tool-free actual execution required",
    )
    require(
        text(document["session_id"]) == text(receipt["session_id"])
        and text(receipt["thread_id"]),
        "Genuine execution identifiers required",
    )
    integer(receipt["pid"], 1)
    require(
        type(receipt["creation_time"]) in (float, int)
        and math.isfinite(receipt["creation_time"])
        and receipt["creation_time"] > 0,
        "Actual process lifetime required",
    )
    require(
        receipt["gallery_sha256"] == fingerprint(manifest)
        and receipt["document_sha256"] == fingerprint(document),
        "Actual receipt/output mismatch",
    )
    states = document["frame_states"]
    samples = plan["samples"]
    require(len(states) == len(samples), "All selected samples required")
    actors = document["actors"]
    identities = {}
    for actor in actors:
        require(
            set(actor)
            == {"actor_id", "description", "identity_supported", "evidence_frames"},
            "Only source actor context permitted",
        )
        identity = text(actor["actor_id"])
        require(identity not in identities, "Duplicate actor definition")
        text(actor["description"])
        require(
            type(actor["identity_supported"]) is bool,
            "Explicit actor uncertainty required",
        )
        evidence = actor["evidence_frames"]
        require(
            isinstance(evidence, list) and evidence == sorted(set(evidence)),
            "Ordered actor evidence required",
        )
        for number in evidence:
            integer(number)
        require(
            set(evidence) <= {s["frame"] for s in samples if s["available"]},
            "Actor evidence outside available samples",
        )
        require(
            not actor["identity_supported"] or len(evidence) >= 2,
            "Repeated visual support required for identity link",
        )
        identities[identity] = actor
    for row, sample in zip(states, samples, strict=True):
        require(
            set(row)
            == {"frame", "scene", "play_state", "camera_view", "actor_ids", "reason"},
            "Only sampled scene/actor context permitted",
        )
        require(
            integer(row["frame"]) == sample["frame"]
            and row["scene"] in SCENES
            and row["play_state"] in PLAY,
            "Native scene membership required",
        )
        text(row["camera_view"])
        text(row["reason"])
        require(
            isinstance(row["actor_ids"], list)
            and len(row["actor_ids"]) == len(set(row["actor_ids"]))
            and set(row["actor_ids"]) <= identities.keys(),
            "Local source actor definition required",
        )
        if not sample["available"]:
            require(
                row["scene"] == row["play_state"] == row["camera_view"] == "unknown"
                and row["actor_ids"] == [],
                "Unavailable sample cannot acquire visual labels",
            )
        for identity in row["actor_ids"]:
            require(
                row["frame"] in identities[identity]["evidence_frames"],
                "Local actor occurrence lacks evidence",
            )
    for actor in actors:
        require(
            set(actor["evidence_frames"])
            == {s["frame"] for s in states if actor["actor_id"] in s["actor_ids"]},
            "Actor evidence/occurrence disagreement",
        )
    transitions = document["transitions"]
    require(len(transitions) == len(states) - 1, "All sparse transitions required")
    for row, (a, b) in zip(transitions, itertools.pairwise(states), strict=True):
        require(
            set(row)
            == {
                "from_frame",
                "to_frame",
                "camera_continuity",
                "actor_continuity",
                "reason",
            },
            "Only sparse continuity fields permitted",
        )
        require(
            integer(row["from_frame"]) == a["frame"]
            and integer(row["to_frame"]) == b["frame"],
            "Sparse transition membership mismatch",
        )
        require(
            row["camera_continuity"] in ("same", "changed", "unknown")
            and row["actor_continuity"] in ("supported", "unresolved", "not_visible"),
            "Explicit continuity uncertainty required",
        )
        text(row["reason"])
        if row["camera_continuity"] == "same":
            require(
                a["camera_view"] == b["camera_view"] != "unknown",
                "Same-camera evidence missing",
            )
        if row["actor_continuity"] == "supported":
            shared = set(a["actor_ids"]) & set(b["actor_ids"])
            require(
                row["camera_continuity"] == "same"
                and any(identities[i]["identity_supported"] for i in shared),
                "Persistent identity needs local shared visual support",
            )
    text(document["limitations"])
    return document


def summarize(manifest, documents):
    """Compare coarse states only after caller verifies global execution exits."""
    require(set(documents) == set(LANES), "All three independent lanes required")
    rows = {
        lane: {r["frame"]: r for r in documents[lane]["frame_states"]} for lane in LANES
    }
    plan = manifest["plan"]
    result = {
        k: plan[k]
        for k in (
            "source_id",
            "native_frame_denominator",
            "unsampled_native_frames",
            "evidence_kind",
        )
    }
    result.update(
        sampled_frames=len(plan["samples"]),
        unavailable_samples=sum(not s["available"] for s in plan["samples"]),
        streams={},
        agreement={},
    )
    for lane, document in documents.items():
        result["streams"][lane] = {
            "scenes": {
                s: sum(r["scene"] == s for r in document["frame_states"])
                for s in SCENES
            },
            "play_states": {
                s: sum(r["play_state"] == s for r in document["frame_states"])
                for s in PLAY
            },
            "actor_definition_groups": len(document["actors"]),
            "supported_actor_groups": sum(
                a["identity_supported"] for a in document["actors"]
            ),
            "camera_continuity": dict(
                Counter(t["camera_continuity"] for t in document["transitions"])
            ),
            "actor_continuity": dict(
                Counter(t["actor_continuity"] for t in document["transitions"])
            ),
        }
    for a, b in itertools.combinations(LANES, 2):
        result["agreement"][a + ":" + b] = {
            "scene_equal_including_unknown": sum(
                rows[a][n]["scene"] == rows[b][n]["scene"] for n in rows[a]
            ),
            "scene_known_equal": sum(
                rows[a][n]["scene"] == rows[b][n]["scene"] != "unknown" for n in rows[a]
            ),
            "scene_unknown_in_either": sum(
                "unknown" in (rows[a][n]["scene"], rows[b][n]["scene"]) for n in rows[a]
            ),
        }
    result.update(
        complete_reference=False,
        exact_contact_evidence=False,
        eligibility=dict(ELIGIBILITY),
    )
    return result
