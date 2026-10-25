"""Plan prospective source-only review using metadata, without reading images.

Raw input provenance is the caller's responsibility. A plan supplies no image
execution authority, source judgment or scientific acceptance decision.
"""

from __future__ import annotations

import copy
from fractions import Fraction
from pathlib import PurePosixPath

from . import rally_evidence_join as join
from . import rally_temporal_context as temporal

MAX_BYTES = 9 * 1024**2
MAX_IMAGES = 20
LANES = ("independent_a", "independent_b", "source_adjudication")
BINDING_KEYS = (
    "packet_sha256",
    "gallery_sha256",
    "prior_audit_sha256",
    "protocol_sha256",
    "consumer_sha256",
)
FRAME_KEYS = tuple(k for k in join.FRAME_KEYS if k != "image")
OUTPUT_CONTRACT = {
    "schema_version": 1,
    "purpose": "prospective source-review specification; not accepted truth",
    "identity": "Bind source, clock, native frame/image identities, lane and batch index.",
    "continuity": (
        "A future reading cites only its own preceding document hash and the shared "
        "native overlap. Distinguish repeated mentions from distinct physical "
        "contacts; preserve unresolved correspondence."
    ),
    "scene_context": (
        "Inspect every supplied native frame in whole-window temporal context; "
        "retain camera changes, replay/non-play, missing evidence and unknown spans. "
        "Nearest sparse gallery context is navigation, never interpolated truth."
    ),
    "actors": (
        "Use document-local actor definitions and visual evidence ranges. Equal "
        "strings, court position or clothing cannot link people across documents "
        "or views without explicit source correspondence; hidden actors stay unknown."
    ),
    "events": (
        "Contact, serve/opening and observable terminal event retain inclusive "
        "native-frame uncertainty intervals and source evidence. Missing or hidden "
        "evidence and censoring stay explicit; last stroke, shuttle absence and "
        "stopped play alone do not prove an exact ending."
    ),
    "labels": "Unsupported family, forehand/backhand, actor and timing remain unknown.",
    "independence": (
        "Independent lanes receive source identities/images and fixed rubric only, "
        "never historical labels, other-stream outputs or predictions. The separately "
        "named source-adjudication lane uses the same exhaustive source schedule. "
        "No majority vote, forced event merge or timestamp averaging."
    ),
    "acceptance": (
        "A future assessment requires a separately frozen specifically authorized "
        "task. This contract neither validates assessment output nor changes "
        "historical acceptance, annotations, predictions or source eligibility."
    ),
}

# These expose the existing strict metadata codec; no file/media IO is used.
strict_json = join.strict_json
fingerprint = join.fingerprint
require = join.require


def _same(left, right):
    return fingerprint(left) == fingerprint(right)


def _path(value):
    require(type(value) is str and bool(value), "Relative image identity required")
    path = PurePosixPath(value)
    require(
        "\\" not in value
        and bool(path.parts)
        and not path.is_absolute()
        and str(path) == value
        and all(part not in (".", "..") and ":" not in part for part in path.parts),
        "Unsafe or ambiguous image identity",
    )
    return value


def _image(value, *, gallery=False):
    require(isinstance(value, dict), "Image metadata required")
    result = {
        "path": _path(value["path"]),
        "sha256": temporal.sha(value["sha256"]),
        "bytes": temporal.integer(value["bytes"], 1),
    }
    if gallery:
        require(_same(value["size"], list(temporal.SHEET)), "Gallery geometry changed")
        result["size"] = list(temporal.SHEET)
    return result


def _inputs(packet, gallery, expected_source, bindings):
    # Recursive strictness rejects nonfinite fields even when they are not copied.
    fingerprint((packet, gallery, expected_source, bindings))
    require(
        set(bindings) == set(BINDING_KEYS), "Exact provenance binding keys required"
    )
    for value in bindings.values():
        temporal.sha(value)
    for key in join.SOURCE_KEYS:
        (temporal.text if key == "source_id" else temporal.sha)(expected_source[key])
        require(packet[key] == expected_source[key], "Source or native clock changed")
    temporal.sha(expected_source["packet_sha256"])
    require(
        expected_source["packet_sha256"] == bindings["packet_sha256"],
        "Raw packet provenance changed",
    )
    count = temporal.integer(expected_source["native_frame_count"], 1)
    require(len(packet["frames"]) == count, "Full native denominator changed")
    plan = temporal.sample_plan(packet)
    require(
        type(gallery["schema_version"]) is int
        and gallery["schema_version"] == 1
        and _same(gallery["plan"], plan),
        "Exact original gallery/native memberships required",
    )
    selected = [row["frame"] for row in plan["samples"]]
    sheets = sorted(gallery["sheets"], key=lambda row: row["path"])
    require(len(sheets) == (len(selected) + 15) // 16, "Missing or extra gallery sheet")
    clean_sheets = []
    for index, sheet in enumerate(sheets):
        require(
            sheet["path"] == f"sheet-{index:03d}.png"
            and _same(sheet["frames"], selected[index * 16 : (index + 1) * 16]),
            "Gallery sheet membership changed",
        )
        clean_sheets.append(
            {
                "index": index,
                **_image(sheet, gallery=True),
                "frames": sheet["frames"][:],
            }
        )
    frames = []
    paths = set()
    for row in packet["frames"]:
        clean = {key: copy.deepcopy(row[key]) for key in FRAME_KEYS}
        require(
            row["orientation_error"] is None or type(row["orientation_error"]) is str,
            "Invalid native orientation error metadata",
        )
        image = _image(row["image"]) if row["image"] is not None else None
        if image is not None:
            require(image["path"] not in paths, "Duplicate native image identity")
            paths.add(image["path"])
        clean.update(
            image=image,
            available=image is not None
            and row["corrupt"] is False
            and row["orientation_error"] is None,
        )
        frames.append(clean)
    return frames, plan["samples"], clean_sheets


def _time(row):
    return row["pts"] * Fraction(row["time_base"])


def _batch(rows, contexts, sheets, index, previous):
    gallery_indices = sorted({contexts[row["frame"]]["sheet"] for row in rows})
    native_bytes = sum(row["image"]["bytes"] for row in rows)
    gallery_bytes = sum(sheets[number]["bytes"] for number in gallery_indices)
    return {
        "index": index,
        "frames": [row["frame"] for row in rows],
        "overlap_frame": previous,
        "new_frames": [row["frame"] for row in rows if row["frame"] != previous],
        "gallery_sheets": gallery_indices,
        "native_image_bytes": native_bytes,
        "gallery_image_bytes": gallery_bytes,
        "total_image_bytes": native_bytes + gallery_bytes,
        "distinct_images": len(rows) + len(gallery_indices),
    }


def plan_source(
    packet,
    gallery,
    *,
    expected_source,
    bindings,
    max_bytes=MAX_BYTES,
    max_images=MAX_IMAGES,
):
    """Return aggregate counts and private source-only prospective manifests.

    Raw file hashes in bindings are independently verified by the caller. The
    additional canonical hashes bind parsed objects without equating whitespace
    or dictionary order with raw file identity. Failed feasibility returns no
    partial substitute schedule and retains the original complete denominator.
    """
    temporal.integer(max_bytes, 1)
    temporal.integer(max_images, 1)
    require(
        max_bytes <= MAX_BYTES and max_images <= MAX_IMAGES,
        "Frozen input caps exceeded",
    )
    frames, samples, sheets = _inputs(packet, gallery, expected_source, bindings)
    contexts = {}
    for row in frames:
        closest = min(
            samples,
            key=lambda sample: (abs(_time(row) - _time(sample)), sample["frame"]),
        )
        contexts[row["frame"]] = {
            "nearest_sample": closest["frame"],
            "sheet": closest["sheet"],
        }
    batches, cursor = [], 0
    unavailable = any(not row["available"] for row in frames)
    reason = "unavailable_native_input" if unavailable else None
    blocked = None
    while cursor < len(frames) and not unavailable:
        start = cursor - 1 if cursor else 0
        previous = frames[cursor - 1]["frame"] if cursor else None
        end, chosen = cursor + 1, None
        while end <= len(frames):
            candidate = _batch(
                frames[start:end], contexts, sheets, len(batches), previous
            )
            if (
                candidate["total_image_bytes"] > max_bytes
                or candidate["distinct_images"] > max_images
            ):
                break
            chosen = candidate
            end += 1
        if chosen is None:
            unavailable, reason, blocked = (
                True,
                "oversized_minimum_batch",
                frames[cursor]["frame"],
            )
            batches.clear()
        else:
            batches.append(chosen)
            cursor = start + len(chosen["frames"])
    if unavailable:
        batches.clear()
    per_lane_sessions = len(batches)
    native_bytes = sum(
        row["image"]["bytes"] for row in frames if row["image"] is not None
    )
    overlap_bytes = sum(
        frames[batch["frames"][0] - frames[0]["frame"]]["image"]["bytes"]
        for batch in batches[1:]
    )
    gallery_bytes = sum(batch["gallery_image_bytes"] for batch in batches)
    per_lane_bytes = sum(batch["total_image_bytes"] for batch in batches)
    summary = {
        "source_id": packet["source_id"],
        "status": "unavailable" if unavailable else "planned",
        "reason": reason,
        "native_frames": len(frames),
        "available_native_frames": sum(row["available"] for row in frames),
        "sampled_frames": len(samples),
        "unsampled_native_frames": len(frames) - len(samples),
        "per_lane_sessions": per_lane_sessions,
        "per_lane_image_bytes": per_lane_bytes,
        "native_image_bytes": native_bytes,
        "overlap_image_bytes": overlap_bytes,
        "gallery_image_bytes": gallery_bytes,
        "proposed_sessions": len(LANES) * per_lane_sessions,
        "proposed_image_bytes": len(LANES) * per_lane_bytes,
        "actual_new_scientific_sessions": 0,
        "actual_new_image_bytes": 0,
        "complete_references": 0,
        "scientific_acceptance_changed": False,
        "eligibility": dict(temporal.ELIGIBILITY),
    }
    source = {key: copy.deepcopy(packet[key]) for key in join.SOURCE_KEYS}
    private = {
        "schema_version": 1,
        "kind": "prospective_review_plan",
        "source": source,
        "bindings": copy.deepcopy(bindings),
        "canonical_packet_sha256": fingerprint(packet),
        # Canonical gallery is sorted by sheet identity, while raw binding is retained.
        "canonical_gallery_sha256": fingerprint(
            {
                **gallery,
                "sheets": sorted(gallery["sheets"], key=lambda row: row["path"]),
            }
        ),
        "limits": {"max_image_bytes": max_bytes, "max_distinct_images": max_images},
        "summary": copy.deepcopy(summary),
        "blocked_native_frame": blocked,
        "frames": frames,
        "gallery_sheets": sheets,
        "navigation_context": [
            dict(frame=number, **value) for number, value in contexts.items()
        ],
        "batches": batches,
        "output_contract": copy.deepcopy(OUTPUT_CONTRACT),
        "lane_manifests": [
            {
                "lane": lane,
                "source": copy.deepcopy(source),
                "bindings": copy.deepcopy(bindings),
                "status": summary["status"],
                "batch_indices": [batch["index"] for batch in batches],
                "continuity": "previous own-stream document only; native overlap retained; no historical or other-stream labels",
                "execution_authorized": False,
            }
            for lane in LANES
        ],
    }
    return summary, private


def summarize_sources(summaries):
    """Aggregate deterministic prospective costs without partial-source success."""
    rows = sorted(copy.deepcopy(summaries), key=lambda row: row["source_id"])
    require(bool(rows), "Source denominator required")
    require(
        len({row["source_id"] for row in rows}) == len(rows), "Duplicate source plan"
    )
    for row in rows:
        fingerprint(row)
        require(row["status"] in ("planned", "unavailable"), "Unknown planning status")
        require(
            all(
                type(row[key]) is int and row[key] == 0
                for key in (
                    "actual_new_scientific_sessions",
                    "actual_new_image_bytes",
                    "complete_references",
                )
            )
            and row["scientific_acceptance_changed"] is False
            and _same(row["eligibility"], temporal.ELIGIBILITY),
            "Planner cannot execute or promote scientific evidence",
        )
        require(
            temporal.integer(row["native_frames"], 1)
            == temporal.integer(row["sampled_frames"], 1)
            + temporal.integer(row["unsampled_native_frames"])
            and temporal.integer(row["available_native_frames"]) <= row["native_frames"]
            and temporal.integer(row["proposed_sessions"])
            == len(LANES) * temporal.integer(row["per_lane_sessions"])
            and temporal.integer(row["proposed_image_bytes"])
            == len(LANES) * temporal.integer(row["per_lane_image_bytes"]),
            "Prospective denominator or lane costs changed",
        )
        require(
            (
                row["status"] == "planned"
                and row["available_native_frames"] == row["native_frames"]
                and row["reason"] is None
                and row["per_lane_sessions"] > 0
                and row["per_lane_image_bytes"]
                == temporal.integer(row["native_image_bytes"])
                + temporal.integer(row["overlap_image_bytes"])
                + temporal.integer(row["gallery_image_bytes"])
            )
            or (
                row["status"] == "unavailable"
                and row["reason"]
                in ("unavailable_native_input", "oversized_minimum_batch")
                and row["proposed_sessions"] == row["proposed_image_bytes"] == 0
            ),
            "Partial schedule or inconsistent repeated-image costs",
        )
    additive = (
        "native_frames",
        "available_native_frames",
        "sampled_frames",
        "unsampled_native_frames",
        "per_lane_sessions",
        "per_lane_image_bytes",
        "native_image_bytes",
        "overlap_image_bytes",
        "gallery_image_bytes",
        "proposed_sessions",
        "proposed_image_bytes",
    )
    return {
        "schema_version": 1,
        "status": "planned"
        if all(row["status"] == "planned" for row in rows)
        else "unavailable",
        "source_count": len(rows),
        "sources": rows,
        **{key: sum(temporal.integer(row[key]) for row in rows) for key in additive},
        "actual_new_scientific_sessions": 0,
        "actual_new_image_bytes": 0,
        "complete_references": 0,
        "scientific_acceptance_changed": False,
        "full_match_accuracy_established": False,
        "eligibility": dict(temporal.ELIGIBILITY),
    }
