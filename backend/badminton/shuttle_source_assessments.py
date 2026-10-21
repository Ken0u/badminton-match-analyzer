"""Validate and freeze source-only agent assessments without importing inference.

Image headers and hashes establish identity, never evidence of actual inspection.
Raw media stay in their immutable packet lineage; the bounded freeze copies JSON
originals and consumers and records every external media identity in its inputs.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import subprocess
import zlib
from collections import Counter
from pathlib import Path, PurePosixPath

ELIGIBILITY = dict.fromkeys(
    (
        "training_allowed",
        "independent_test_allowed",
        "model_deployment_allowed",
        "dataset_redistribution_allowed",
    ),
    False,
)
VISIBILITY = ["visible_localizable", "visible_unlocalizable", "not_visible", "unknown"]
SCENES = ["unknown", "play_view", "non_play", "replay"]
DIFFICULTY = [
    "ordinary",
    "fast_flight",
    "blur",
    "small_far",
    "occlusion",
    "distractor",
    "camera_transition",
    "non_play",
    "unresolved",
]
CASE_FIELDS = {
    "key",
    "source_id",
    "case_id",
    "center_frame",
    "visibility",
    "x",
    "y",
    "uncertainty_radius",
    "scene",
    "difficulty",
    "reason",
    "negative_evidence",
    "inspected_frames",
}
LABEL_FIELDS = ("visibility", "x", "y", "uncertainty_radius", "scene", "difficulty")
MAX_OUTPUT = 256 * 1024**2
MAX_DOCUMENT = 4 * 1024**2
MAX_SESSION_IMAGES = 6 * 1024**2
ORIGINAL_NAMES = ("assessor-a.json", "assessor-b.json", "adjudication.json")
LIMITATIONS = [
    "Source-only agent assessments are not expert-certified truth or annotation accuracy.",
    "Hashes and validation cannot prove actual visual inspection or session independence.",
    "Unknown and unavailable cases remain in every case denominator; unknown is not absent.",
    "Rights, original-match overlap, upstream membership and full-match completeness remain unresolved.",
    "Media remain in the original immutable packet lineage and must be reverified there.",
    "No training, independent test, model deployment or dataset redistribution is authorized.",
]


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            result.update(chunk)
    return result.hexdigest()


def read_json(path, limit=None):
    path = Path(path)
    if limit is not None and path.stat().st_size > limit:
        raise ValueError("JSON byte limit exceeded")
    return _decode_json(_read_bytes(path, limit))


def _read_bytes(path, limit=None):
    with Path(path).open("rb") as stream:
        raw = stream.read() if limit is None else stream.read(limit + 1)
    _require(limit is None or len(raw) <= limit, "Input byte limit exceeded")
    return raw


def _decode_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("Nonfinite JSON number")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _eligibility(value):
    _require(
        isinstance(value, dict)
        and value.keys() == ELIGIBILITY.keys()
        and all(item is False for item in value.values()),
        "Usage eligibility changed",
    )


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _relative(root, name):
    _require(isinstance(name, str) and "\\" not in name, "Invalid relative path")
    parts = PurePosixPath(name)
    _require(
        not parts.is_absolute()
        and bool(parts.parts)
        and all(p not in ("..", ".") and ":" not in p for p in parts.parts),
        "Invalid relative path",
    )
    root = Path(root).resolve()
    path = root.joinpath(*parts.parts)
    _require(path.resolve().is_relative_to(root), "Path escapes input root")
    # Refuse links even when their current target remains inside the tree.
    _require(
        not any(
            p.is_symlink() or p.resolve() != p.absolute()
            for p in [path, *path.parents]
            if p.is_relative_to(root)
        ),
        "Linked input path",
    )
    return path


def _sealed(path, sha, size=None):
    _require(
        isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha), "Invalid SHA256"
    )
    _require(Path(path).is_file(), "Missing sealed input")
    if size is not None:
        _require(
            _integer(size) and Path(path).stat().st_size == size, "Input size changed"
        )
    _require(file_hash(path) == sha, "Input SHA256 changed")


def _protocol(path, sha):
    _sealed(path, sha)
    raw = _read_bytes(path, MAX_DOCUMENT)
    _require(digest(raw) == sha, "Protocol changed while reading")
    protocol = _decode_json(raw)
    _eligibility(protocol["eligibility"])
    _require(
        type(protocol["schema_version"]) is int and protocol["schema_version"] == 1,
        "Schema changed",
    )
    _require(protocol["visibility_states"] == VISIBILITY, "Visibility protocol changed")
    _require(
        protocol["scenes"] == SCENES and protocol["difficulty_tags"] == DIFFICULTY,
        "Label protocol changed",
    )
    selection = protocol["selection"]
    _require(
        selection["case_count"] == 128
        and selection["centers_per_source"] == 64
        and selection["context_offsets"] == [-2, -1, 0, 1, 2]
        and selection["requested_context_memberships"] == 640
        and selection["unique_images"] == 632,
        "Fixed case denominators changed",
    )
    _require(len(protocol["sources"]) == 2, "Source membership changed")
    _require(
        len({s["source_id"] for s in protocol["sources"]}) == 2, "Duplicate source"
    )
    for source in protocol["sources"]:
        _require(
            re.fullmatch(r"[A-Za-z0-9_-]+", source["source_id"]),
            "Invalid source identifier",
        )
        _require(
            source["case_count"] == 64
            and source["requested_context_memberships"] == 320
            and source["unique_images"] == 316
            and _integer(source["native_frame_count"], 64),
            "Fixed source denominator changed",
        )
        _require(
            len(source["display_size"]) == 2
            and all(_integer(v, 1) for v in source["display_size"]),
            "Invalid native geometry",
        )
    _require(
        0 < protocol["limits"]["output_bytes"] <= MAX_OUTPUT
        and 0 < protocol["limits"]["assessment_document_bytes"] <= MAX_DOCUMENT,
        "Protocol exceeds byte budget",
    )
    version = protocol.get("procedure_version", 1)
    _require(type(version) is int and version in (1, 2), "Unknown procedure version")
    if version == 2:
        streams = protocol["assessment_streams"]
        _require(
            streams["max_cases_per_session"] == 4
            and streams["max_inspected_image_bytes_per_session"] == MAX_SESSION_IMAGES,
            "Session budgets changed",
        )
    return protocol


def _png_header(path, dimensions):
    with path.open("rb") as stream:
        header = stream.read(33)
    _require(
        len(header) == 33
        and header[:16] == b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        and list(struct.unpack(">II", header[16:24])) == dimensions
        and struct.unpack(">I", header[29:33])[0] == zlib.crc32(header[12:29]),
        "PNG native geometry/header changed",
    )


def load_inputs(packet_root, protocol_path, protocol_sha256):
    """Reverify original bytes; return the exact deterministic blind-input index."""
    root = Path(packet_root).resolve()
    protocol = _protocol(protocol_path, protocol_sha256)
    _sealed(_relative(root, "context.json"), protocol["packet_context_sha256"])
    context = read_json(root / "context.json", MAX_DOCUMENT)
    consumers = context["consumers"]
    for name, sha in consumers.items():
        _sealed(_relative(root / "consumer", name), sha)
    declaration_name = "data/manifests/shuttle_review_sources_v1.json"
    packet_protocol_name = "data/manifests/shuttle_review_packet_protocol_v1.json"
    _require(
        consumers[declaration_name] == protocol["source_declaration_sha256"],
        "Declaration seal changed",
    )
    _require(
        consumers[packet_protocol_name] == protocol["source_packet_protocol_sha256"],
        "Packet protocol seal changed",
    )
    declaration = read_json(root / "consumer" / declaration_name)
    _require(
        [s["id"] for s in declaration["sources"]]
        == [s["source_id"] for s in protocol["sources"]],
        "Source declaration membership changed",
    )
    cases = []
    for source, declared in zip(protocol["sources"], declaration["sources"]):
        sid = source["source_id"]
        folder = _relative(root, "sources/" + sid)
        _eligibility(declared["eligibility"])
        _require(
            declared["category"] == source["category_metadata_assertion"],
            "Category assertion changed",
        )
        _sealed(_relative(folder, "packet.json"), source["packet_sha256"])
        _sealed(_relative(folder, "clock.json"), source["clock_sha256"])
        _sealed(
            _relative(folder, "review-template.json"), source["unknown_template_sha256"]
        )
        seal = read_json(_relative(folder, "source-seal.json"), MAX_DOCUMENT)
        _require(
            seal["sha256"] == source["source_sha256"]
            and seal["bytes"] == declared["metadata_selected_bytes"],
            "Raw source seal changed",
        )
        _sealed(_relative(folder, "source.mp4"), source["source_sha256"], seal["bytes"])
        metadata = read_json(_relative(folder, "returned-metadata.json"), MAX_DOCUMENT)
        _require(
            metadata == seal["metadata"] and metadata["id"] == sid,
            "Source metadata changed",
        )
        clock = read_json(folder / "clock.json")
        packet = read_json(folder / "packet.json", MAX_DOCUMENT)
        template = read_json(folder / "review-template.json", MAX_DOCUMENT)
        _eligibility(packet["eligibility"])
        _eligibility(template["eligibility"])
        for doc in (packet, template):
            _require(
                doc["source_id"] == sid
                and doc["source_sha256"] == source["source_sha256"]
                and doc["clock_sha256"] == source["clock_sha256"],
                "Packet source identity changed",
            )
        _require(
            packet["context_sha256"] == protocol["packet_context_sha256"]
            and template["packet_sha256"] == source["packet_sha256"],
            "Packet/template parent seal changed",
        )
        count = source["native_frame_count"]
        _require(
            clock["complete"] is True
            and clock["source_sha256"] == source["source_sha256"]
            and clock["frame_count"] == count
            and len(clock["frames"]) == count
            and all(
                type(row["frame"]) is int and row["frame"] == i
                for i, row in enumerate(clock["frames"])
            ),
            "Incomplete native clock",
        )
        expected_cases = []
        selected = set()
        for i in range(64):
            center = i * (count - 1) // 63
            memberships = []
            for offset in [-2, -1, 0, 1, 2]:
                frame = max(0, min(count - 1, center + offset))
                selected.add(frame)
                memberships.append(
                    {
                        "offset": offset,
                        "frame": frame,
                        "clamped": frame != center + offset,
                    }
                )
            expected_cases.append(
                {"case_id": i, "center_frame": center, "context": memberships}
            )
        _require(
            packet["cases"] == expected_cases
            and packet["case_count"] == 64
            and packet["requested_context_memberships"] == 320,
            "Packet case membership changed",
        )
        _require(
            set(packet["images"]) == {str(i) for i in selected}
            and len(selected) == 316,
            "Packet image membership changed",
        )
        for frame in sorted(selected):
            identity = packet["images"][str(frame)]
            native = clock["frames"][frame]
            _require(
                {k: v for k, v in identity.items() if k not in {"available", "image"}}
                == native,
                "Native image identity changed",
            )
            available = (
                native["corrupt"] is False and native["orientation_error"] is None
            )
            _require(identity["available"] is available, "Image availability changed")
            if available:
                image = identity["image"]
                _require(
                    image["path"] == f"images/{sid}/{frame:09d}.png"
                    and identity["display_size"] == source["display_size"],
                    "Image path/geometry changed",
                )
                path = _relative(root, image["path"])
                _sealed(path, image["sha256"], image["bytes"])
                _png_header(path, identity["display_size"])
            else:
                _require(
                    identity["image"] is None, "Unavailable image has fabricated bytes"
                )
        _require(len(template["cases"]) == 64, "Unknown template membership changed")
        for expected, row in zip(expected_cases, template["cases"]):
            _require(
                row
                == {
                    "case_id": expected["case_id"],
                    "center_frame": expected["center_frame"],
                    "difficulty": "unknown",
                    "reviewed": False,
                    "scene": "unknown",
                    "visibility": "unknown",
                    "x": None,
                    "y": None,
                },
                "Unknown source template was relabeled",
            )
        for case in packet["cases"]:
            cases.append(
                {
                    "key": f"{sid}:{case['case_id']:02d}",
                    "source_id": sid,
                    "case_id": case["case_id"],
                    "center_frame": case["center_frame"],
                    "context": [
                        {**m, "identity": packet["images"][str(m["frame"])]}
                        for m in case["context"]
                    ],
                }
            )
    # Unique image identity count includes unavailable entries; availability is not a denominator filter.
    _require(
        sum(s["unique_images"] for s in protocol["sources"]) == 632,
        "Unique image denominator changed",
    )
    return {
        "schema_version": 1,
        "protocol_sha256": protocol_sha256,
        "packet_context_sha256": protocol["packet_context_sha256"],
        "source_declaration_sha256": protocol["source_declaration_sha256"],
        "source_packet_protocol_sha256": protocol["source_packet_protocol_sha256"],
        "sources": protocol["sources"],
        "case_count": 128,
        "requested_context_memberships": 640,
        "unique_images": 632,
        "eligibility": protocol["eligibility"],
        "cases": cases,
    }


def validate_assessment(
    document, inputs, protocol, inputs_sha256, *, adjudication=False, partial=False
):
    """Validate claimed inspection identities, without certifying inspection occurred."""
    id_field = "adjudicator_id" if adjudication else "assessor_id"
    required = {
        "schema_version",
        "role",
        id_field,
        "session_id",
        "protocol_sha256",
        "inputs_sha256",
        "eligibility",
        "cases",
    }
    if adjudication:
        required.add("assessment_sha256")
    _require(
        isinstance(document, dict) and document.keys() == required,
        "Assessment document fields changed",
    )
    _require(
        type(document["schema_version"]) is int and document["schema_version"] == 1,
        "Assessment schema changed",
    )
    role = "source_only_adjudication" if adjudication else "source_only_assessment"
    _require(
        document["role"] == role
        and _text(document[id_field])
        and _text(document["session_id"]),
        "Invalid assessment role/session",
    )
    _require(
        document["protocol_sha256"] == inputs["protocol_sha256"]
        and document["inputs_sha256"] == inputs_sha256,
        "Assessment input provenance changed",
    )
    _eligibility(document["eligibility"])
    index = {c["key"]: c for c in inputs["cases"]}
    rows = {}
    _require(isinstance(document["cases"], list), "Cases must be a list")
    for row in document["cases"]:
        _require(
            isinstance(row, dict) and row.keys() == CASE_FIELDS,
            "Assessment case fields changed",
        )
        key = row["key"]
        _require(
            isinstance(key, str) and key in index and key not in rows,
            "Missing, duplicate or foreign case",
        )
        case = index[key]
        _require(
            row["source_id"] == case["source_id"]
            and type(row["case_id"]) is int
            and row["case_id"] == case["case_id"]
            and type(row["center_frame"]) is int
            and row["center_frame"] == case["center_frame"],
            "Assessment native case identity changed",
        )
        _require(
            row["visibility"] in VISIBILITY
            and row["scene"] in SCENES
            and _text(row["reason"]),
            "Invalid source observation",
        )
        tags = row["difficulty"]
        _require(
            isinstance(tags, list)
            and bool(tags)
            and all(isinstance(t, str) and t in DIFFICULTY for t in tags),
            "Invalid difficulty tags",
        )
        _require(
            len(set(tags)) == len(tags) and ("ordinary" not in tags or len(tags) == 1),
            "Duplicate/incompatible difficulty tags",
        )
        context = {m["frame"]: m["identity"] for m in case["context"]}
        center = context[case["center_frame"]]
        inspected = row["inspected_frames"]
        _require(isinstance(inspected, list), "Invalid inspection records")
        seen = set()
        for entry in inspected:
            _require(
                isinstance(entry, dict) and entry.keys() == {"frame", "image_sha256"},
                "Invalid inspection record fields",
            )
            frame = entry["frame"]
            _require(
                _integer(frame) and frame in context and frame not in seen,
                "Inspection outside declared context or duplicated",
            )
            identity = context[frame]
            _require(
                identity["available"] is True
                and entry["image_sha256"] == identity["image"]["sha256"],
                "Inspection identity changed",
            )
            seen.add(frame)
        if center["available"]:
            _require(
                case["center_frame"] in seen,
                "Available center inspection record required",
            )
        else:
            _require(
                row["visibility"] == "unknown", "Unavailable center must remain unknown"
            )
        values = [row[k] for k in ("x", "y", "uncertainty_radius")]
        if row["visibility"] == "visible_localizable":
            width, height = center["display_size"]
            _require(
                all(_number(v) for v in values), "Nonfinite/non-numeric coordinate"
            )
            x, y, radius = values
            _require(
                0 <= x <= width - 1
                and 0 <= y <= height - 1
                and 1 <= radius <= math.hypot(width, height),
                "Coordinate/uncertainty outside native bounds",
            )
        else:
            _require(
                all(v is None for v in values),
                "Nonlocalizable observation carries coordinates",
            )
        if row["visibility"] == "not_visible":
            _require(
                _text(row["negative_evidence"])
                and len(row["negative_evidence"].strip()) >= 10,
                "Affirmative negative evidence required",
            )
        else:
            _require(
                row["negative_evidence"] is None,
                "Unknown/nonnegative case carries negative evidence",
            )
        rows[key] = row
    if not adjudication and not partial:
        _require(rows.keys() == index.keys(), "Incomplete assessor case membership")
    return rows


def _differences(a, b):
    return [
        field
        for field in LABEL_FIELDS
        if (
            set(a[field]) != set(b[field])
            if field == "difficulty"
            else a[field] != b[field]
        )
    ]


def _stream(
    path, document, inputs, protocol, inputs_sha, stream_id, sessions, originals
):
    """Validate bounded originals; never attribute a whole stream to one session."""
    adjudication = stream_id == "adjudication"
    fields = {
        "schema_version",
        "role",
        "stream_id",
        "protocol_sha256",
        "inputs_sha256",
        "eligibility",
        "segments",
    }
    if adjudication:
        fields.add("assessment_sha256")
    _require(
        isinstance(document, dict) and document.keys() == fields,
        "Stream index fields changed",
    )
    _require(
        type(document["schema_version"]) is int
        and document["schema_version"] == 2
        and document["role"]
        == (
            "source_only_adjudication_stream"
            if adjudication
            else "source_only_assessment_stream"
        )
        and document["stream_id"] == stream_id,
        "Invalid stream role/identity",
    )
    _require(
        document["protocol_sha256"] == inputs["protocol_sha256"]
        and document["inputs_sha256"] == inputs_sha,
        "Stream input provenance changed",
    )
    _eligibility(document["eligibility"])
    entries = document["segments"]
    _require(
        isinstance(entries, list) and len(entries) <= len(inputs["cases"]),
        "Invalid segment inventory",
    )
    rows, provenance, paths = {}, {}, set()
    case_index = {c["key"]: c for c in inputs["cases"]}
    prefix = f"segments/{stream_id}/"
    for entry in entries:
        _require(
            isinstance(entry, dict)
            and entry.keys()
            == {
                "path",
                "sha256",
                "bytes",
                "session_id",
                "case_keys",
            },
            "Segment inventory fields changed",
        )
        name = entry["path"]
        target = _relative(path.parent, name)
        _require(
            name == PurePosixPath(name).as_posix()
            and name.startswith(prefix)
            and name not in paths,
            "Invalid or duplicate segment path",
        )
        paths.add(name)
        _require(
            _integer(entry["bytes"], 1)
            and entry["bytes"] <= protocol["limits"]["assessment_document_bytes"],
            "Segment document byte limit exceeded",
        )
        _require(
            sum(len(raw) for raw in originals.values()) + entry["bytes"]
            <= min(MAX_OUTPUT, protocol["limits"]["output_bytes"]),
            "Assessment originals exceed byte budget",
        )
        _sealed(target, entry["sha256"], entry["bytes"])
        raw = _read_bytes(target, entry["bytes"])
        _require(
            len(raw) == entry["bytes"] and digest(raw) == entry["sha256"],
            "Segment changed while reading",
        )
        segment = _decode_json(raw)
        segment_rows = validate_assessment(
            segment,
            inputs,
            protocol,
            inputs_sha,
            adjudication=adjudication,
            partial=True,
        )
        _require(1 <= len(segment_rows) <= 4, "Segment session case budget exceeded")
        _require(
            entry["case_keys"] == list(segment_rows),
            "Segment ordered case inventory changed",
        )
        id_field = "adjudicator_id" if adjudication else "assessor_id"
        _require(segment[id_field] == stream_id, "Segment assessor identity changed")
        session = segment["session_id"]
        _require(
            entry["session_id"] == session and session.strip() not in sessions,
            "Segment sessions must be globally distinct",
        )
        sessions.add(session.strip())
        if adjudication:
            _require(
                segment["assessment_sha256"] == document["assessment_sha256"],
                "Adjudication segment assessment provenance changed",
            )
        inspected = {}
        for key, row in segment_rows.items():
            _require(key not in rows, "Duplicate stream case membership")
            context = {m["frame"]: m["identity"] for m in case_index[key]["context"]}
            for record in row["inspected_frames"]:
                image = context[record["frame"]]["image"]
                inspected[image["path"]] = image["bytes"]
            rows[key] = row
            provenance[key] = session
        _require(
            sum(inspected.values()) <= MAX_SESSION_IMAGES,
            "Session inspected PNG byte budget exceeded",
        )
        originals[name] = raw
    directory = _relative(path.parent, prefix.rstrip("/"))
    actual = set()
    if directory.exists():
        _require(directory.is_dir(), "Invalid segment inventory directory")
        for candidate in directory.rglob("*"):
            relative = candidate.relative_to(path.parent).as_posix()
            _relative(path.parent, relative)
            if candidate.is_file():
                actual.add(relative)
            else:
                _require(candidate.is_dir(), "Unexpected segment filesystem entry")
    _require(actual == paths, "Unindexed or missing segment original")
    if not adjudication:
        _require(rows.keys() == case_index.keys(), "Incomplete stream case membership")
    return rows, provenance


def _validated_documents(
    inputs, protocol, inputs_path, a_path, b_path, adjudication_path
):
    expected = encoded(inputs)
    _require(
        _read_bytes(inputs_path, len(expected)) == expected,
        "Blind input receipt bytes changed",
    )
    inputs_sha = digest(expected)
    paths = [Path(p).resolve() for p in (a_path, b_path, adjudication_path)]
    _require(
        len({p.resolve() for p in paths}) == 3,
        "Assessment originals must be distinct files",
    )
    originals = {
        name: _read_bytes(p, protocol["limits"]["assessment_document_bytes"])
        for name, p in zip(ORIGINAL_NAMES, paths)
    }
    documents = [_decode_json(raw) for raw in originals.values()]
    a, b, adjudication = documents
    shas = [digest(raw) for raw in originals.values()]
    streams = protocol.get("procedure_version", 1) == 2
    provenance = []
    if streams:
        sessions = set()
        validated = [
            _stream(path, doc, inputs, protocol, inputs_sha, sid, sessions, originals)
            for path, doc, sid in zip(paths, documents, ("a", "b", "adjudication"))
        ]
        rows_a, rows_b, rows_j = [item[0] for item in validated]
        provenance = [item[1] for item in validated]
    else:
        rows_a = validate_assessment(a, inputs, protocol, inputs_sha)
        rows_b = validate_assessment(b, inputs, protocol, inputs_sha)
        rows_j = validate_assessment(
            adjudication, inputs, protocol, inputs_sha, adjudication=True
        )
        _require(
            a["assessor_id"].strip() != b["assessor_id"].strip(),
            "Assessors must be distinct",
        )
        _require(
            len({d["session_id"].strip() for d in documents}) == 3,
            "Assessment/adjudication sessions must be distinct",
        )
    _require(
        shas[0] != shas[1] and adjudication["assessment_sha256"] == shas[:2],
        "Adjudication original assessment provenance changed",
    )
    differences = []
    resolved = []
    required = set()
    for case in inputs["cases"]:
        key = case["key"]
        first, second = rows_a[key], rows_b[key]
        fields = _differences(first, second)
        if fields:
            differences.append(
                {
                    "key": key,
                    "fields": fields,
                    "assessor_a": first,
                    "assessor_b": second,
                }
            )
        if fields or first["visibility"] == second["visibility"] == "not_visible":
            required.add(key)
        chosen = rows_j[key] if key in rows_j else first
        resolved.append(
            {
                "key": key,
                "basis": "source_based_adjudication"
                if key in rows_j
                else "two_assessor_agreement",
                "assessment": chosen,
            }
        )
        if streams:
            inspection_sessions = {
                "assessor_a": provenance[0][key],
                "assessor_b": provenance[1][key],
            }
            if key in rows_j:
                inspection_sessions["adjudication"] = provenance[2][key]
            resolved[-1]["inspection_sessions"] = inspection_sessions
            if fields:
                differences[-1]["inspection_sessions"] = dict(inspection_sessions)
    _require(
        required <= rows_j.keys(),
        "Explicit adjudication required for every disagreement and agreed negative",
    )
    counts = Counter(r["assessment"]["visibility"] for r in resolved)
    scenes = Counter(r["assessment"]["scene"] for r in resolved)
    difficulty = Counter(tag for r in resolved for tag in r["assessment"]["difficulty"])
    aggregate = {
        "schema_version": 1,
        "case_count": 128,
        "requested_context_memberships": 640,
        "unique_images": 632,
        "raw_label_agreements": 128 - len(differences),
        "raw_label_disagreements": len(differences),
        "required_adjudications": len(required),
        "explicit_adjudications": len(rows_j),
        "two_assessor_agreement_only": 128 - len(rows_j),
        "resolved_visibility_support": {state: counts[state] for state in VISIBILITY},
        "resolved_scene_support": {scene: scenes[scene] for scene in SCENES},
        "resolved_difficulty_support": {tag: difficulty[tag] for tag in DIFFICULTY},
        "unavailable_centers": sum(
            not next(
                m["identity"]["available"] for m in c["context"] if m["offset"] == 0
            )
            for c in inputs["cases"]
        ),
        "eligibility": ELIGIBILITY,
        "limitations": LIMITATIONS,
    }
    if streams:
        aggregate["limitations"] = [
            *LIMITATIONS,
            "Each stream comprises bounded sessions with preserved case-level provenance; no single session inspected the whole stream.",
        ]
    return originals, shas, differences, resolved, aggregate


def _copy_plan(packet_root, protocol_path, inputs_path, originals):
    root = Path(packet_root)
    plan = {"protocol.json": Path(protocol_path), "inputs.json": Path(inputs_path)}
    plan["packet/context.json"] = root / "context.json"
    inputs = read_json(inputs_path, MAX_DOCUMENT)
    for source in inputs["sources"]:
        for name in (
            "packet.json",
            "review-template.json",
            "source-seal.json",
            "returned-metadata.json",
        ):
            rel = "sources/" + source["source_id"] + "/" + name
            plan["packet/" + rel] = _relative(root, rel)
    project = Path(__file__).resolve().parents[2]
    for name in (
        "backend/badminton/shuttle_source_assessments.py",
        "scripts/freeze_shuttle_source_assessments.py",
    ):
        plan["consumer/" + name] = project / name
    plan.update(originals)
    return plan


def _ignored_output(path):
    path = Path(path).absolute()
    _require(
        not path.exists() and not path.is_symlink(), "Exclusive output already exists"
    )
    existing = next(p for p in path.parents if p.exists())
    _require(existing.resolve() == existing, "Linked output parent")
    result = subprocess.run(
        ["git", "-C", str(existing), "check-ignore", "--quiet", "--", str(path)],
        capture_output=True,
        check=False,
    )
    _require(result.returncode == 0, "Output must be Git ignored")
    return path


def freeze(
    packet_root,
    protocol_path,
    protocol_sha256,
    inputs_path,
    a_path,
    b_path,
    adjudication_path,
    output,
):
    """Publish an exclusive bounded lineage; preserve partial output on failure."""
    output = _ignored_output(output)
    supplied = [
        Path(p).resolve()
        for p in (
            packet_root,
            protocol_path,
            inputs_path,
            a_path,
            b_path,
            adjudication_path,
        )
    ]
    _require(
        all(
            not p.is_relative_to(output) and not output.is_relative_to(p)
            for p in supplied
        ),
        "Output overlaps an input",
    )
    inputs = load_inputs(packet_root, protocol_path, protocol_sha256)
    protocol = _protocol(protocol_path, protocol_sha256)
    originals, shas, differences, resolved, aggregate = _validated_documents(
        inputs, protocol, inputs_path, a_path, b_path, adjudication_path
    )
    plan = _copy_plan(packet_root, protocol_path, inputs_path, originals)
    plan.update(
        {
            "raw-differences.json": encoded(differences),
            "resolved.json": encoded(resolved),
            "aggregate.json": encoded(aggregate),
        }
    )
    # Snapshot all hashes before creating the output, then enforce them while copying.
    seals = {
        name: {
            "bytes": len(value) if isinstance(value, bytes) else value.stat().st_size,
            "sha256": digest(value) if isinstance(value, bytes) else file_hash(value),
        }
        for name, value in plan.items()
    }
    manifest = {
        "schema_version": 1,
        "protocol_sha256": protocol_sha256,
        "inputs_sha256": digest(encoded(inputs)),
        "assessment_sha256": shas[:2],
        "adjudication_sha256": shas[2],
        "eligibility": ELIGIBILITY,
        "external_media": "Original videos and PNGs are sealed in inputs.json and reverified at the original packet root; they are not copied under the 256MiB cap.",
        "files": seals,
    }
    manifest_raw = encoded(manifest)
    limit = min(MAX_OUTPUT, protocol["limits"]["output_bytes"])
    _require(
        sum(s["bytes"] for s in seals.values()) + len(manifest_raw) <= limit,
        "Freeze exceeds output byte budget",
    )
    # Recheck identity after planning to reject input changes before publication.
    _require(
        load_inputs(packet_root, protocol_path, protocol_sha256) == inputs,
        "Inputs changed during freeze",
    )
    _require(
        _validated_documents(
            inputs, protocol, inputs_path, a_path, b_path, adjudication_path
        )[:2]
        == (originals, shas),
        "Assessments changed during freeze",
    )
    output.mkdir(parents=True, exist_ok=False)
    written = 0
    for name, value in plan.items():
        target = _relative(output, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        checksum = hashlib.sha256()
        size = 0
        with target.open("xb") as destination:
            if isinstance(value, bytes):
                chunks = (value,)
                source = None
            else:
                source = value.open("rb")
                chunks = iter(lambda: source.read(1024**2), b"")
            try:
                for chunk in chunks:
                    written += len(chunk)
                    size += len(chunk)
                    _require(
                        written + len(manifest_raw) <= limit,
                        "Freeze byte budget exceeded while copying",
                    )
                    destination.write(chunk)
                    checksum.update(chunk)
            finally:
                if source is not None:
                    source.close()
            destination.flush()
            os.fsync(destination.fileno())
        _require(
            {"bytes": size, "sha256": checksum.hexdigest()} == seals[name],
            "Input changed while copying; partial output preserved",
        )
    # A manifest appears only after every planned copy passes its original seal.
    with (output / "manifest.json").open("xb") as stream:
        stream.write(manifest_raw)
        stream.flush()
        os.fsync(stream.fileno())
    return aggregate


def verify_freeze(output, packet_root, protocol_sha256):
    """Reverify a frozen lineage and original external media without publishing."""
    output = Path(output).resolve()
    manifest = read_json(output / "manifest.json", MAX_DOCUMENT)
    _require(
        manifest["protocol_sha256"] == protocol_sha256, "Frozen protocol seal changed"
    )
    _eligibility(manifest["eligibility"])
    actual_files = set()
    total = 0
    for path in output.rglob("*"):
        relative = path.relative_to(output).as_posix()
        _relative(output, relative)
        if path.is_file():
            actual_files.add(relative)
            total += path.stat().st_size
            _require(total <= MAX_OUTPUT, "Frozen output exceeds byte budget")
        else:
            _require(path.is_dir(), "Unexpected output filesystem entry")
    _require(
        actual_files == {"manifest.json", *manifest["files"]},
        "Unmanifested or missing frozen output file",
    )
    for name, seal in manifest["files"].items():
        path = _relative(output, name)
        _sealed(path, seal["sha256"], seal["bytes"])
    _require(total <= MAX_OUTPUT, "Frozen output exceeds byte budget")
    inputs = load_inputs(packet_root, output / "protocol.json", protocol_sha256)
    protocol = _protocol(output / "protocol.json", protocol_sha256)
    _require(
        total <= protocol["limits"]["output_bytes"],
        "Frozen output exceeds protocol byte budget",
    )
    originals, shas, differences, resolved, aggregate = _validated_documents(
        inputs,
        protocol,
        output / "inputs.json",
        output / "assessor-a.json",
        output / "assessor-b.json",
        output / "adjudication.json",
    )
    expected_plan = _copy_plan(
        packet_root, output / "protocol.json", output / "inputs.json", originals
    )
    expected_plan.update(
        {
            "raw-differences.json": encoded(differences),
            "resolved.json": encoded(resolved),
            "aggregate.json": encoded(aggregate),
        }
    )
    _require(
        manifest["files"].keys() == expected_plan.keys(),
        "Frozen file membership changed",
    )
    for name, value in expected_plan.items():
        if name.startswith("packet/"):
            _require(
                file_hash(value) == manifest["files"][name]["sha256"],
                "Frozen packet original changed",
            )
    _require(
        manifest["inputs_sha256"] == digest(encoded(inputs))
        and manifest["assessment_sha256"] == shas[:2]
        and manifest["adjudication_sha256"] == shas[2],
        "Frozen provenance changed",
    )
    for name, value in (
        ("raw-differences.json", differences),
        ("resolved.json", resolved),
        ("aggregate.json", aggregate),
    ):
        _require(
            (output / name).read_bytes() == encoded(value),
            "Frozen derived document changed",
        )
    return aggregate
