"""Source-only shuttle development packets and immutable, uncertainty-aware audits.

This research tool never changes application annotations or runs a model. Raw
media, assessments and cached predictions belong in ignored local lineages.
"""

import argparse
import bisect
import hashlib
import io
import itertools
import json
import math
import os
import platform
import sqlite3
from collections import Counter
from fractions import Fraction
from pathlib import Path, PurePosixPath

PROTOCOL = {
    "schema_version": 1,
    "name": "source-only-shuttle-visibility-development-v1",
    "inventory_sha256": "273e0749d148e952ad1fb0534363b3971e2584702f834ad2084c59e632990822",
    "sources": [
        {
            "id": "970dbd8adfe548d8",
            "sha256": "970dbd8adfe548d8b43259e283ba30d6900f16a4c429f108df435cec82bbf14f",
            "frame_count": 12023,
        },
        {
            "id": "c406a1187130b845",
            "sha256": "c406a1187130b845ca03ba807199bbebb72924566c58cc294217c56dae0af4dd",
            "frame_count": 12148,
        },
    ],
    "grid_points_per_source": 25,
    "grid_formula": "floor((i+0.5)*frame_count/25), i=0..24",
    "extra_frames": {
        "970dbd8adfe548d8": [2039, 2040, 2041, 2042, 2043, 2047, 2048, 2077, 2078, 2079]
    },
    "context_each_side": 2,
    "context_policy": "Inspect the center at original display size. Adjacent frames may clarify a streak, but never infer a hidden coordinate or motion across a camera cut. Record mixed-view context explicitly.",
    "clock_tolerance_s": 0.00002,
    "coordinate_convention": "Display-oriented source pixels; center of observed shuttle/streak, with explicit radial uncertainty in pixels. No model overlays or inferred coordinates.",
    "states": ["visible", "visible_unlocalizable", "not_visible", "unknown"],
    "state_definitions": {
        "visible": "An observed shuttle/streak center can be localized, with finite coordinates and radial uncertainty.",
        "visible_unlocalizable": "Source evidence confirms visibility, but a defensible center/uncertainty cannot be supplied. Visibility positive; localization truth unavailable.",
        "not_visible": "Source/context supports no visible shuttle, such as confirmed occlusion or outside the image. Failure to find a tiny shuttle alone is insufficient; use unknown.",
        "unknown": "Visibility or shuttle identity cannot be resolved. Preserve the reason; never treat this as absence.",
    },
    "difficulty_tags": [
        "ordinary",
        "fast_flight",
        "occlusion",
        "distractor",
        "blur",
        "small_far",
        "camera_transition",
        "non_play",
        "unresolved",
    ],
    "localization_tolerance_diagonal": 0.005,
    "wrong_localization": "One false detection and one miss; visibility scored separately.",
    "uncertainty_policy": "Also report error bounds max(0,distance-radius)..distance+radius. Nominal point metrics and uncertainty-straddling outcomes remain separate; no threshold tuning.",
    "missing_output_policy": "Unavailable outputs remain cases and are misses for known visible truth; missing invisible outputs never become true negatives.",
    "assessment_policy": "Two genuinely separate source-only agent assessments, explicit source-based disagreement adjudication, and frozen labels before additional cached prediction access.",
    "limitations": [
        "Small known development sources, including ten known failure-neighborhood frames; not blinded held-out or human-certified truth.",
        "No complete-match or unseen accuracy claim, model inference, threshold tuning, app truth changes or model promotion.",
    ],
}


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def inside(root, name):
    if not isinstance(name, str) or "\\" in name or ":" in name:
        raise ValueError("Expected a relative POSIX path")
    part = PurePosixPath(name)
    path = (root / name).resolve()
    if (
        part.is_absolute()
        or not part.parts
        or ".." in part.parts
        or not path.is_relative_to(root)
    ):
        raise ValueError("Path escapes its root")
    return path


def file_hash(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def sealed_path(root, entry):
    if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
        raise ValueError("Invalid file seal")
    path = inside(root, entry["path"])
    if file_hash(path) != entry["sha256"]:
        raise ValueError(f"Changed sealed input: {entry['path']}")
    return path


def seal(root, path):
    path = path.resolve()
    return {"path": path.relative_to(root).as_posix(), "sha256": file_hash(path)}


def sealed_bytes(root, entry):
    if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
        raise ValueError("Invalid file seal")
    raw = inside(root, entry["path"]).read_bytes()
    if digest(raw) != entry["sha256"]:
        raise ValueError(f"Changed sealed input: {entry['path']}")
    return raw


def publish(path, value):
    with path.open("xb") as handle:
        handle.write(encoded(value))


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def selection(source):
    count, points = source["frame_count"], PROTOCOL["grid_points_per_source"]
    frames = {((2 * i + 1) * count) // (2 * points) for i in range(points)}
    frames.update(PROTOCOL["extra_frames"].get(source["id"], []))
    if not frames or min(frames) < 0 or max(frames) >= count:
        raise ValueError("Selected case outside source")
    return sorted(frames)


def load_inventory(root, raw, expected):
    if digest(raw) != expected or expected != PROTOCOL["inventory_sha256"]:
        raise ValueError("Changed frozen source inventory")
    inventory = read_json(raw)
    if (
        set(inventory) != {"schema_version", "sources"}
        or inventory["schema_version"] != 1
    ):
        raise ValueError("Invalid source inventory")
    if len(inventory["sources"]) != len(PROTOCOL["sources"]):
        raise ValueError("Incomplete source inventory")
    result, paths = [], set()
    for entry, source in zip(inventory["sources"], PROTOCOL["sources"]):
        if (
            set(entry) != {"video_id", "frame_count", "inputs"}
            or entry["video_id"] != source["id"]
            or entry["frame_count"] != source["frame_count"]
        ):
            raise ValueError("Substituted source inventory")
        if set(entry["inputs"]) != {"video", "metadata", "timestamps"}:
            raise ValueError("Incomplete source seals")
        inputs = {key: sealed_path(root, item) for key, item in entry["inputs"].items()}
        if paths.intersection(inputs.values()) or len(set(inputs.values())) != 3:
            raise ValueError("Aliased source inputs")
        paths.update(inputs.values())
        meta = read_json(sealed_bytes(root, entry["inputs"]["metadata"]))
        times = read_json(sealed_bytes(root, entry["inputs"]["timestamps"]))
        if (
            meta["id"] != source["id"]
            or meta["sha256"] != source["sha256"]
            or entry["inputs"]["video"]["sha256"] != source["sha256"]
            or meta["frame_count"] != source["frame_count"]
            or inside(root, meta["path"]) != inputs["video"]
        ):
            raise ValueError("Source metadata mismatch")
        if (
            any(
                type(meta[key]) is not int or meta[key] <= 0
                for key in ("frame_count", "width", "height")
            )
            or type(meta.get("rotation", 0)) is not int
            or meta.get("rotation", 0) not in (0, 90, 180, 270)
        ):
            raise ValueError("Invalid source geometry")
        if (
            not isinstance(times, list)
            or len(times) != meta["frame_count"]
            or any(not finite(t) or t < 0 for t in times)
            or any(a >= b for a, b in itertools.pairwise(times))
            or not finite(meta["duration_s"])
            or meta["duration_s"] <= times[-1]
            or not finite(meta["source_start_s"])
        ):
            raise ValueError("Invalid native source clock")
        if Fraction(meta["time_base"]) <= 0:
            raise ValueError("Invalid source time base")
        result.append((entry, meta, times, inputs["video"]))
    return result


def render_source(meta, times, video_path, wanted, output):
    """Decode in source ordinal order using one CPU thread, with no inference."""
    from .av_runtime import open_media
    from .orientation import orient_frame

    images, decoded = {}, 0
    with open_media(str(video_path)) as container:
        stream = container.streams.video[0]
        stream.codec_context.thread_count = 1
        for number, frame in enumerate(container.decode(stream)):
            decoded += 1
            if number >= len(times) or frame.pts is None:
                raise ValueError("Native source frame count/PTS mismatch")
            relative = float(frame.pts * frame.time_base) - meta["source_start_s"]
            if (
                frame.time_base != Fraction(meta["time_base"])
                or abs(relative - times[number]) > PROTOCOL["clock_tolerance_s"]
            ):
                raise ValueError("Native source frame clock mismatch")
            if number not in wanted:
                continue
            display = orient_frame(frame, expected_rotation=meta.get("rotation", 0))
            if (display.width, display.height) != (meta["width"], meta["height"]):
                raise ValueError("Display orientation/dimensions mismatch")
            path = output / f"{number:06d}.png"
            with path.open("xb") as handle:
                display.to_image().save(handle, format="PNG")
            images[number] = {
                "frame": number,
                "time_s": times[number],
                "pts": frame.pts,
                "time_base": str(frame.time_base),
                "image": path,
            }
    if decoded != meta["frame_count"] or set(images) != wanted:
        raise ValueError("Incomplete native source frames")
    return images


def make_packet(root, inventory_path, inventory_sha256, protocol_path, output):
    root, output = root.resolve(), output.resolve()
    if not output.is_relative_to(root / ".cache") or output == root / ".cache":
        raise ValueError("Packet must use a new ignored input-root cache lineage")
    raw, protocol_raw = inventory_path.read_bytes(), protocol_path.read_bytes()
    if encoded(read_json(protocol_raw)) != encoded(PROTOCOL):
        raise ValueError("Changed public protocol")
    sources = load_inventory(root, raw, inventory_sha256)
    output.mkdir(parents=True, exist_ok=False)
    import psutil

    publish(
        output / "attempt.json",
        {
            "pid": os.getpid(),
            "created_at": psutil.Process().create_time(),
            "cwd": str(Path.cwd()),
            "phase": "CPU source rendering only; no model or Store",
            "inventory_sha256": inventory_sha256,
        },
    )
    provenance = output / "provenance"
    provenance.mkdir()
    code_seals = {}
    for name in ("shuttle_validation.py", "av_runtime.py", "orientation.py"):
        code_raw = Path(__file__).with_name(name).read_bytes()
        with (provenance / name).open("xb") as handle:
            handle.write(code_raw)
        code_seals[name] = seal(output, provenance / name)
    with (output / "inventory.json").open("xb") as handle:
        handle.write(raw)
    with (output / "protocol.json").open("xb") as handle:
        handle.write(protocol_raw)
    cases, source_inputs = [], {}
    for entry, meta, times, video_path in sources:
        copies = provenance / meta["id"]
        copies.mkdir()
        source_inputs[meta["id"]] = {}
        for key in ("metadata", "timestamps"):
            original = sealed_path(root, entry["inputs"][key])
            copied = copies / f"{key}.json"
            with copied.open("xb") as handle:
                handle.write(original.read_bytes())
            source_inputs[meta["id"]][key] = seal(output, copied)
        centers = selection({"id": meta["id"], "frame_count": meta["frame_count"]})
        context = {
            f
            for center in centers
            for f in range(
                max(0, center - PROTOCOL["context_each_side"]),
                min(len(times), center + PROTOCOL["context_each_side"] + 1),
            )
        }
        image_root = output / "images" / meta["id"]
        image_root.mkdir(parents=True)
        rendered = render_source(meta, times, video_path, context, image_root)
        for center in centers:
            images = []
            for f in range(
                max(0, center - PROTOCOL["context_each_side"]),
                min(len(times), center + PROTOCOL["context_each_side"] + 1),
            ):
                item = dict(rendered[f])
                item["image"] = seal(output, item["image"])
                images.append(item)
            cases.append(
                {
                    "id": f"{meta['id']}:{center}",
                    "video_id": meta["id"],
                    "frame": center,
                    "width": meta["width"],
                    "height": meta["height"],
                    "rotation": meta.get("rotation", 0),
                    "context": images,
                }
            )
    # Recheck every original byte after decoding. A partial attempt remains an
    # immutable interrupted lineage; it never acquires a completion manifest.
    load_inventory(root, raw, inventory_sha256)
    if inventory_path.read_bytes() != raw or protocol_path.read_bytes() != protocol_raw:
        raise ValueError("Input changed during packet creation")
    for name, entry in code_seals.items():
        if file_hash(Path(__file__).with_name(name)) != entry["sha256"]:
            raise ValueError("Renderer code changed during packet creation")
    import av
    import PIL

    packet = {
        "schema_version": 1,
        "inventory": seal(output, output / "inventory.json"),
        "protocol": seal(output, output / "protocol.json"),
        "code": code_seals,
        "source_inputs": source_inputs,
        "runtime": {
            "python": platform.python_version(),
            "av": av.__version__,
            "pillow": PIL.__version__,
            "decoder_threads": 1,
        },
        "cases": cases,
        "source_only": True,
    }
    publish(output / "packet.json", packet)
    return {
        "packet_sha256": file_hash(output / "packet.json"),
        "cases": len(cases),
        "images": len(
            {image["image"]["path"] for case in cases for image in case["context"]}
        ),
        "source_only": True,
    }


def validate_packet(root, raw, expected):
    if digest(raw) != expected:
        raise ValueError("Changed review packet")
    packet = read_json(raw)
    if (
        set(packet)
        != {
            "schema_version",
            "inventory",
            "protocol",
            "code",
            "source_inputs",
            "runtime",
            "cases",
            "source_only",
        }
        or packet["schema_version"] != 1
        or packet["source_only"] is not True
    ):
        raise ValueError("Invalid review packet")
    if encoded(read_json(sealed_bytes(root, packet["protocol"]))) != encoded(PROTOCOL):
        raise ValueError("Changed frozen protocol")
    if (
        file_hash(sealed_path(root, packet["inventory"]))
        != PROTOCOL["inventory_sha256"]
    ):
        raise ValueError("Changed packet inventory")
    if set(packet["code"]) != {
        "shuttle_validation.py",
        "av_runtime.py",
        "orientation.py",
    }:
        raise ValueError("Incomplete execution code seals")
    for entry in packet["code"].values():
        sealed_path(root, entry)
    inventory = read_json(sealed_bytes(root, packet["inventory"]))
    if (
        set(packet["runtime"]) != {"python", "av", "pillow", "decoder_threads"}
        or packet["runtime"]["decoder_threads"] != 1
        or any(
            not isinstance(packet["runtime"][key], str) or not packet["runtime"][key]
            for key in ("python", "av", "pillow")
        )
    ):
        raise ValueError("Incomplete source renderer runtime")
    if set(packet["source_inputs"]) != {s["id"] for s in PROTOCOL["sources"]}:
        raise ValueError("Incomplete packet source inputs")
    originals = {}
    for source, entry in zip(PROTOCOL["sources"], inventory["sources"]):
        files = packet["source_inputs"][source["id"]]
        if set(files) != {"metadata", "timestamps"}:
            raise ValueError("Incomplete packet source clocks")
        documents = {}
        for key in files:
            raw_input = sealed_bytes(root, files[key])
            if files[key]["sha256"] != entry["inputs"][key]["sha256"]:
                raise ValueError("Substituted original source inputs")
            documents[key] = read_json(raw_input)
        originals[source["id"]] = documents
    expected_cases = [(s, f) for s in PROTOCOL["sources"] for f in selection(s)]
    if len(packet["cases"]) != len(expected_cases):
        raise ValueError("Incomplete case membership")
    from PIL import Image

    for case, (source, center) in zip(packet["cases"], expected_cases):
        if set(case) != {
            "id",
            "video_id",
            "frame",
            "width",
            "height",
            "rotation",
            "context",
        }:
            raise ValueError("Unexpected case fields")
        if (
            case["id"] != f"{source['id']}:{center}"
            or case["video_id"] != source["id"]
            or type(case["frame"]) is not int
            or case["frame"] != center
        ):
            raise ValueError("Substituted or reordered case")
        meta, times = [
            originals[source["id"]][key] for key in ("metadata", "timestamps")
        ]
        if (case["width"], case["height"], case["rotation"]) != (
            meta["width"],
            meta["height"],
            meta.get("rotation", 0),
        ):
            raise ValueError("Changed source display geometry")
        frames = list(
            range(
                max(0, center - PROTOCOL["context_each_side"]),
                min(source["frame_count"], center + PROTOCOL["context_each_side"] + 1),
            )
        )
        if [item["frame"] for item in case["context"]] != frames:
            raise ValueError("Incomplete context membership")
        for item in case["context"]:
            if (
                set(item) != {"frame", "time_s", "pts", "time_base", "image"}
                or type(item["frame"]) is not int
                or type(item["pts"]) is not int
                or not finite(item["time_s"])
                or Fraction(item["time_base"]) != Fraction(meta["time_base"])
            ):
                raise ValueError("Invalid packet source clock")
            if (
                item["time_s"] != times[item["frame"]]
                or abs(
                    float(item["pts"] * Fraction(item["time_base"]))
                    - meta["source_start_s"]
                    - item["time_s"]
                )
                > PROTOCOL["clock_tolerance_s"]
            ):
                raise ValueError("Substituted packet source PTS")
            if (
                item["image"]["path"]
                != f"images/{source['id']}/{item['frame']:06d}.png"
            ):
                raise ValueError("Substituted source image identity")
            with Image.open(io.BytesIO(sealed_bytes(root, item["image"]))) as image:
                if image.size != (case["width"], case["height"]):
                    raise ValueError("Changed original display dimensions")
                image.verify()
    return packet, inventory


def validate_label(label, case):
    if (
        set(label)
        != {
            "id",
            "state",
            "x",
            "y",
            "uncertainty_px",
            "reason",
            "difficulty",
            "context_cut",
        }
        or label["id"] != case["id"]
        or label["state"] not in PROTOCOL["states"]
    ):
        raise ValueError("Invalid source assessment label")
    if (
        not isinstance(label["reason"], str)
        or not label["reason"].strip()
        or label["reason"].strip().lower() in {"todo", "unassessed", "root_pending"}
    ):
        raise ValueError("Every source assessment needs an observation reason")
    if (
        type(label["context_cut"]) is not bool
        or not isinstance(label["difficulty"], list)
        or not label["difficulty"]
        or len(set(label["difficulty"])) != len(label["difficulty"])
        or not set(label["difficulty"]) <= set(PROTOCOL["difficulty_tags"])
    ):
        raise ValueError("Invalid difficulty or camera-context assessment")
    if label["state"] == "visible":
        if (
            any(not finite(label[k]) for k in ("x", "y", "uncertainty_px"))
            or not 0 <= label["x"] < case["width"]
            or not 0 <= label["y"] < case["height"]
            or not 0
            < label["uncertainty_px"]
            <= math.hypot(case["width"], case["height"])
        ):
            raise ValueError(
                "Visible label needs finite observed source coordinates and uncertainty"
            )
    elif any(label[k] is not None for k in ("x", "y", "uncertainty_px")):
        raise ValueError(
            "Unlocalizable/unknown/absent truth must not invent coordinates"
        )


def validate_assessment(document, packet, packet_sha256):
    if (
        set(document)
        != {"schema_version", "packet_sha256", "assessor_session", "method", "cases"}
        or document["schema_version"] != 1
        or document["packet_sha256"] != packet_sha256
        or not isinstance(document["assessor_session"], str)
        or not document["assessor_session"].strip()
        or document["method"] != "source-only original-size inspection"
    ):
        raise ValueError("Invalid assessment provenance")
    if len(document["cases"]) != len(packet["cases"]):
        raise ValueError("Incomplete source assessment")
    for label, case in zip(document["cases"], packet["cases"]):
        validate_label(label, case)
    return document


def disagreement(a, b):
    location = False
    point_estimate = False
    uncertainty = False
    if a["state"] == b["state"] == "visible":
        point_estimate = (a["x"], a["y"]) != (b["x"], b["y"])
        uncertainty = a["uncertainty_px"] != b["uncertainty_px"]
        location = (
            math.hypot(a["x"] - b["x"], a["y"] - b["y"])
            > a["uncertainty_px"] + b["uncertainty_px"]
        )
    return {
        "state": a["state"] != b["state"],
        "point_estimate": point_estimate,
        "uncertainty_radius": uncertainty,
        "location": location,
        "camera_context": a["context_cut"] != b["context_cut"],
        "difficulty": set(a["difficulty"]) != set(b["difficulty"]),
    }


def adjudicated_cases(document, assessments, assessment_hashes, packet, packet_sha256):
    if (
        set(document)
        != {
            "schema_version",
            "packet_sha256",
            "assessment_sha256",
            "adjudicator_session",
            "cases",
        }
        or document["schema_version"] != 1
        or document["packet_sha256"] != packet_sha256
        or document["assessment_sha256"] != assessment_hashes
    ):
        raise ValueError("Adjudication is not bound to both original assessments")
    sessions = [a["assessor_session"] for a in assessments]
    if (
        len(set(sessions)) != 2
        or not isinstance(document["adjudicator_session"], str)
        or not document["adjudicator_session"].strip()
        or document["adjudicator_session"] in sessions
    ):
        raise ValueError(
            "Two separate assessors and an explicit adjudicator are required"
        )
    if len(document["cases"]) != len(packet["cases"]):
        raise ValueError("Incomplete source adjudication")
    result = []
    for entry, case, a, b in zip(
        document["cases"],
        packet["cases"],
        assessments[0]["cases"],
        assessments[1]["cases"],
    ):
        if (
            set(entry)
            != {"id", "label", "reason", "evidence_frames", "observed_cut_frames"}
            or entry["id"] != case["id"]
            or not isinstance(entry["reason"], str)
            or not entry["reason"].strip()
            or entry["reason"].strip().lower() in {"todo", "unassessed", "root_pending"}
        ):
            raise ValueError("Invalid source adjudication record")
        validate_label(entry["label"], case)
        frames = [item["frame"] for item in case["context"]]
        evidence, cuts = entry["evidence_frames"], entry["observed_cut_frames"]
        if (
            not isinstance(evidence, list)
            or case["frame"] not in evidence
            or len(set(evidence)) != len(evidence)
            or any(type(f) is not int or f not in frames for f in evidence)
        ):
            raise ValueError("Adjudication needs actual center/context evidence")
        if (
            not isinstance(cuts, list)
            or cuts != sorted(set(cuts))
            or any(
                type(f) is not int
                or f not in frames[1:]
                or f not in evidence
                or f - 1 not in evidence
                for f in cuts
            )
            or bool(cuts) != entry["label"]["context_cut"]
        ):
            raise ValueError("Observed cuts must retain exact source transition frames")
        flags = disagreement(a, b)
        result.append(
            {
                "id": case["id"],
                "label": entry["label"],
                "disagreement": flags,
                "adjudication_reason": entry["reason"],
                "evidence_frames": evidence,
                "observed_cut_frames": cuts,
            }
        )
    return result


def ignored_output(root, output):
    output = output.resolve()
    if (
        not output.is_relative_to(root.resolve() / ".cache")
        or output == root.resolve() / ".cache"
    ):
        raise ValueError("Use a new ignored input-root cache lineage")
    output.mkdir(parents=True, exist_ok=False)
    return output


def freeze_labels(
    root, packet_root, packet_sha256, assessment_paths, adjudication_path, output
):
    packet_root = packet_root.resolve()
    packet_raw = (packet_root / "packet.json").read_bytes()
    packet, _ = validate_packet(packet_root, packet_raw, packet_sha256)
    load_inventory(
        root.resolve(),
        sealed_bytes(packet_root, packet["inventory"]),
        PROTOCOL["inventory_sha256"],
    )
    if len(assessment_paths) != 2:
        raise ValueError("Exactly two genuine source assessments are required")
    raw = [p.read_bytes() for p in assessment_paths]
    assessment_hashes = [digest(item) for item in raw]
    assessments = [
        validate_assessment(read_json(item), packet, packet_sha256) for item in raw
    ]
    adjudication_raw = adjudication_path.read_bytes()
    adjudication = read_json(adjudication_raw)
    cases = adjudicated_cases(
        adjudication, assessments, assessment_hashes, packet, packet_sha256
    )
    output = ignored_output(root, output)
    inputs = {}
    for name, item in zip(
        ("assessment-a.json", "assessment-b.json", "adjudication.json"),
        [*raw, adjudication_raw],
    ):
        with (output / name).open("xb") as handle:
            handle.write(item)
        inputs[name] = seal(output, output / name)
    frozen = {
        "schema_version": 1,
        "packet_sha256": packet_sha256,
        "inputs": inputs,
        "adjudicator_session": adjudication["adjudicator_session"],
        "cases": cases,
        "limitations": PROTOCOL["limitations"],
    }
    publish(output / "labels.json", frozen)
    return {
        "labels_sha256": file_hash(output / "labels.json"),
        "cases": len(cases),
        "disagreements": sum(any(c["disagreement"].values()) for c in cases),
        "states": {
            state: sum(c["label"]["state"] == state for c in cases)
            for state in PROTOCOL["states"]
        },
    }


def load_labels(label_root, raw, expected, packet, packet_sha256):
    if digest(raw) != expected:
        raise ValueError("Changed frozen labels")
    labels = read_json(raw)
    if (
        set(labels)
        != {
            "schema_version",
            "packet_sha256",
            "inputs",
            "adjudicator_session",
            "cases",
            "limitations",
        }
        or labels["schema_version"] != 1
        or labels["packet_sha256"] != packet_sha256
        or labels["limitations"] != PROTOCOL["limitations"]
    ):
        raise ValueError("Invalid frozen label lineage")
    if set(labels["inputs"]) != {
        "assessment-a.json",
        "assessment-b.json",
        "adjudication.json",
    }:
        raise ValueError("Incomplete frozen source assessments")
    raw_assessments = [
        sealed_bytes(label_root, labels["inputs"][name])
        for name in ("assessment-a.json", "assessment-b.json")
    ]
    assessments = [
        validate_assessment(read_json(item), packet, packet_sha256)
        for item in raw_assessments
    ]
    adjudication = read_json(
        sealed_bytes(label_root, labels["inputs"]["adjudication.json"])
    )
    cases = adjudicated_cases(
        adjudication,
        assessments,
        [digest(item) for item in raw_assessments],
        packet,
        packet_sha256,
    )
    if (
        encoded(cases) != encoded(labels["cases"])
        or labels["adjudicator_session"] != adjudication["adjudicator_session"]
    ):
        raise ValueError("Frozen outcomes disagree with original source adjudication")
    return labels


def metrics(tp, fp, fn, tn):
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
    }


def score_cases(cases, labels, observations):
    """Separate visibility, point truth, output availability and uncertainty."""
    if [c["id"] for c in cases] != [entry["id"] for entry in labels] or set(
        observations
    ) != {c["id"] for c in cases}:
        raise ValueError("Incomplete score case membership")
    visibility = dict.fromkeys(("tp", "fp", "fn", "tn"), 0)
    localization = visibility.copy()
    states = dict.fromkeys(PROTOCOL["states"], 0)
    unavailable, rows, errors = {}, [], []
    certain, ambiguous, unlocalizable_answers = 0, 0, 0
    for case, entry in zip(cases, labels):
        label, observation = entry["label"], observations[case["id"]]
        validate_label(label, case)
        states[label["state"]] += 1
        available, point = observation["available"], observation.get("point")
        if (
            type(available) is not bool
            or (available and not isinstance(point, dict))
            or (point is not None and type(point.get("visible")) is not bool)
        ):
            raise ValueError("Invalid observation availability/visibility")
        if not available:
            reason = observation.get("reason")
            if not isinstance(reason, str) or not reason:
                raise ValueError("Unavailable output needs a reason")
            unavailable[reason] = unavailable.get(reason, 0) + 1
        visible = available and point["visible"]
        if (
            point is not None
            and point["visible"]
            and (
                any(not finite(point.get(k)) for k in ("x", "y"))
                or not 0 <= point["x"] < case["width"]
                or not 0 <= point["y"] < case["height"]
            )
        ):
            raise ValueError("Visible output needs finite display source coordinates")
        state = label["state"]
        row = {
            "id": case["id"],
            "truth_state": state,
            "available": available,
            "unavailable_reason": observation.get("reason"),
            "predicted_visible": bool(visible) if available else None,
        }
        if state in {"visible", "visible_unlocalizable"}:
            visibility["tp" if visible else "fn"] += 1
        elif state == "not_visible" and available:
            visibility["fp" if visible else "tn"] += 1
        if state == "visible":
            if visible:
                error = math.hypot(point["x"] - label["x"], point["y"] - label["y"])
                tolerance = PROTOCOL["localization_tolerance_diagonal"] * math.hypot(
                    case["width"], case["height"]
                )
                low, high = (
                    max(0, error - label["uncertainty_px"]),
                    error + label["uncertainty_px"],
                )
                errors.append(error)
                nominal = error <= tolerance + 1e-9
                localization["tp" if nominal else "fn"] += 1
                if not nominal:
                    localization["fp"] += 1
                certain += high <= tolerance + 1e-9
                ambiguous += low <= tolerance + 1e-9 < high
                row.update(
                    error_px=error,
                    error_lower_px=low,
                    error_upper_px=high,
                    tolerance_px=tolerance,
                    outcome="correct_localization" if nominal else "localization_error",
                    uncertainty_straddles_tolerance=low <= tolerance + 1e-9 < high,
                )
            else:
                localization["fn"] += 1
                row["outcome"] = "miss" if available else "unavailable_visible_output"
        elif state == "not_visible":
            if available:
                localization["fp" if visible else "tn"] += 1
            row["outcome"] = (
                ("false_detection" if visible else "correct_absence")
                if available
                else "unavailable_invisible_output"
            )
        elif state == "visible_unlocalizable":
            unlocalizable_answers += bool(visible)
            row["outcome"] = "localization_truth_unavailable"
        else:
            row["outcome"] = "unknown_truth"
        rows.append(row)
    positive = states["visible"] + states["visible_unlocalizable"]
    eligible = states["visible"] + states["not_visible"]
    return {
        "cases": len(cases),
        "truth_states": states,
        "visibility_known": len(cases) - states["unknown"],
        "localization_eligible": eligible,
        "localization_truth_unavailable": states["visible_unlocalizable"],
        "output_unavailable": sum(unavailable.values()),
        "unavailable_reasons": unavailable,
        "visibility": metrics(**visibility),
        "localization": metrics(**localization),
        "nominal_correct_frame_fraction": (localization["tp"] + localization["tn"])
        / eligible
        if eligible
        else None,
        "mean_visible_pair_error_px": sum(errors) / len(errors) if errors else None,
        "uncertainty_straddling_cases": ambiguous,
        "strict_localization_recall_lower_bound": certain / positive
        if positive
        else None,
        "strict_localization_recall_upper_bound": (
            certain + ambiguous + unlocalizable_answers
        )
        / positive
        if positive
        else None,
        "frames": rows,
    }


def recipe_hash(value):
    """The existing pipeline producer hashes compact JSON, not report JSON."""
    return digest(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    )


def native_windows(meta, times, core, halo):
    if (
        not finite(core)
        or not 1 <= core <= 112
        or not finite(halo)
        or not 2 <= halo <= 4
    ):
        raise ValueError("Invalid native processing window recipe")
    result, start = [], 0
    while start < len(times):
        end = max(start + 1, bisect.bisect_left(times, times[start] + core))
        result.append(
            {
                "index": len(result),
                "core_start_frame": start,
                "core_end_frame": end,
                "start_frame": bisect.bisect_left(times, max(0, times[start] - halo)),
                "end_frame": bisect.bisect_left(
                    times,
                    (times[end] if end < len(times) else meta["duration_s"]) + halo,
                ),
            }
        )
        start = end
    return result


def native_stage_key(recipe, stage, window, dependencies):
    value = {
        k: v
        for k, v in recipe.items()
        if k not in ("settings", "context_signature", "local_side_files")
    }
    value.update(stage=stage, window=window, dependencies=dependencies)
    if stage != "segments":
        value["context_signature"] = recipe["context_signature"]
    value["settings"] = (
        {k: recipe["settings"][k] for k in ("player_model", "auto_calibrate")}
        if stage == "players"
        else {}
    )
    return recipe_hash(value)


def catalog_snapshot(data, video_id, job_ids):
    """Read only relevant registered documents, never construct a Store."""
    path = inside(data, "catalog.sqlite3")
    if not path.is_file():
        return None
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        # One consistent SQLite read transaction; unrelated jobs need not match.
        connection.execute("BEGIN")
        video = connection.execute(
            "SELECT document FROM videos WHERE id=?", (video_id,)
        ).fetchone()
        annotation = connection.execute(
            "SELECT revision,document FROM annotations WHERE video_id=? "
            "ORDER BY revision DESC LIMIT 1",
            (video_id,),
        ).fetchone()
        jobs = {}
        for identifier in sorted(set(job_ids)):
            row = connection.execute(
                "SELECT document FROM jobs WHERE id=?", (identifier,)
            ).fetchone()
            jobs[identifier] = read_json(row[0]) if row else None
        return {
            "video": read_json(video[0]) if video else None,
            "annotations": read_json(annotation[1]) if annotation else None,
            "revision": annotation[0] if annotation else None,
            "jobs": jobs,
        }


def native_rows(run, meta, times, window):
    """Reject extra, duplicated, reordered or substituted rows, even if unscored."""
    start, end = window["start_frame"], window["end_frame"]
    rows = run.get("frames", [])
    if (
        run.get("stride", 1) != 1
        or run.get("processed_frames") != end - start
        or len(rows) != end - start
    ):
        raise ValueError("Native output must retain every source frame")
    for frame, row in enumerate(rows, start):
        if (
            type(row.get("frame")) is not int
            or row["frame"] != frame
            or not finite(row.get("time_s"))
            or abs(row["time_s"] - times[frame]) > PROTOCOL["clock_tolerance_s"]
        ):
            raise ValueError("Native source row membership/PTS mismatch")
        if run["stage"] == "shuttle":
            point = row.get("shuttle", {})
            if type(point.get("visible")) is not bool:
                raise ValueError("Native shuttle visibility must be explicit")
            if point["visible"] and (
                any(not finite(point.get(k)) for k in ("x", "y", "confidence"))
                or not 0 <= point["x"] < meta["width"]
                or not 0 <= point["y"] < meta["height"]
                or not 0 <= point["confidence"] <= 1
            ):
                raise ValueError("Nonfinite/out-of-image native visible coordinate")
            if point["visible"]:
                candidates = point.get("component_candidates", [])
                identifiers = [c.get("id") for c in candidates]
                if (
                    not candidates
                    or len(set(identifiers)) != len(identifiers)
                    or any(type(i) is not int or i <= 0 for i in identifiers)
                ):
                    raise ValueError("Invalid native observed components")
                if any(
                    any(not finite(c.get(k)) for k in ("x", "y", "confidence"))
                    or not 0 <= c["x"] < meta["width"]
                    or not 0 <= c["y"] < meta["height"]
                    or not 0 <= c["confidence"] <= 1
                    for c in candidates
                ):
                    raise ValueError("Nonfinite/out-of-image native component")
                chosen = next(
                    (
                        c
                        for c in candidates
                        if c["id"] == point.get("selected_component_id")
                    ),
                    None,
                )
                if chosen is None or any(
                    chosen.get(k) != point[k] for k in ("x", "y", "confidence")
                ):
                    raise ValueError(
                        "Native point is not its selected observed component"
                    )
    return rows


def native_observations(root, sources, cases, labels, locations):
    """Verify the frozen v1 producer graph, then choose each unique core owner.

    No ignored helper or model is executed. Original runtime/weights are read as
    bytes. Missing dependencies stay unavailable; corrupted present bytes/rows
    are errors. A second pass over seals and registered targets detects changes.
    """
    from .calibration_context import effective_annotations
    from .rallies import context_signature
    from .scene_review import corrected_boundaries, excluded_scene, reviewed_run
    from .segments import slice_camera_scan

    roots = {name: inside(root, value) for name, value in locations.items()}
    if set(roots) != {"data", "runtime", "weights"}:
        raise ValueError(
            "Explicit native data, frozen runtime and weights roots required"
        )
    files, catalogs, observations, provenance, selections = {}, {}, {}, [], {}

    def read(path, expected=None):
        path = inside(root, path.resolve().relative_to(root).as_posix())
        name = path.relative_to(root).as_posix()
        raw = path.read_bytes() if path.is_file() else None
        actual = digest(raw) if raw is not None else None
        if raw is not None and expected is not None and actual != expected:
            raise ValueError(f"Changed native dependency bytes: {name}")
        entry = {"sha256": actual, "expected_sha256": expected}
        if name in files and files[name] != entry:
            raise ValueError("Aliased native dependency has conflicting seals")
        files[name] = entry
        return raw

    def document(path, expected=None):
        raw = read(path, expected)
        return read_json(raw) if raw is not None else None

    by_label = {entry["id"]: entry for entry in labels}
    for _, meta, times, _ in sources:
        vid = meta["id"]
        selected = [c for c in cases if c["video_id"] == vid]
        paths = sorted((roots["data"] / vid / "analysis").glob("*/manifest.json"))
        if len(paths) > 1:
            raise ValueError(
                "Ambiguous baseline: preserve all manifests, never choose by results"
            )
        selections[vid] = [p.relative_to(root).as_posix() for p in paths]
        if not paths:
            for case in selected:
                observations[case["id"]] = {
                    "available": False,
                    "point": None,
                    "reason": "missing_native_manifest",
                }
            continue
        plan = document(paths[0])
        recipe = plan["recipe"]
        key = recipe_hash(recipe)
        projection = {k: meta.get(k) for k in recipe["video"]}
        if (
            recipe["video"] != projection
            or set(projection)
            != {
                "id",
                "sha256",
                "mode",
                "width",
                "height",
                "rotation",
                "source_start_s",
                "duration_s",
                "frame_count",
                "fps",
            }
            or recipe["timestamps_sha256"] != recipe_hash(times)
            or plan.get("schema_version") != 1
            or plan.get("stage") != "analysis"
            or plan.get("video_id") != vid
            or plan.get("video_sha256") != meta["sha256"]
            or plan.get("analysis_key") != key
            or paths[0].parent.name != key
        ):
            raise ValueError("Native source/clock/analysis recipe mismatch")
        native_meta = document(inside(roots["data"], f"{vid}/metadata.json"))
        native_times = document(inside(roots["data"], f"{vid}/timestamps.json"))
        if (
            native_meta is not None
            and {k: native_meta.get(k) for k in projection} != projection
        ):
            raise ValueError("Substituted native source metadata")
        if native_times is not None and encoded(native_times) != encoded(times):
            raise ValueError("Substituted native source clock")
        missing = []
        # Store.register persists source metadata in SQLite. A sidecar is
        # optional; the registered document below and sealed original packet
        # must still agree exactly. The clock sidecar is a real model input.
        if native_times is None:
            missing.append("missing_native_source_provenance")
        if (
            recipe.get("method")
            != "overlapping source windows with immutable stage checkpoints v1"
        ):
            missing.append("unsupported_native_pipeline_recipe")
        for name, sha in recipe["source_files"].items():
            if read(inside(roots["runtime"], name), sha) is None:
                missing.append("missing_frozen_runtime")
        if not {
            "pipeline.py",
            "shuttle.py",
            "tracking.py",
            "segments.py",
            "scene_review.py",
            "calibration_context.py",
            "model_manifest.json",
        } <= set(recipe["source_files"]):
            raise ValueError("Incomplete transitive runtime provenance")
        manifest = document(
            inside(roots["runtime"], "model_manifest.json"),
            recipe["source_files"]["model_manifest.json"],
        )
        models = {}
        if manifest is not None:
            player_key = (
                "player_pose_small"
                if recipe["settings"]["player_model"] == "small"
                else "player_pose"
            )
            models = {"players": manifest[player_key], "shuttle": manifest["shuttle"]}
            for model in models.values():
                if (
                    read(inside(roots["weights"], model["name"]), model["sha256"])
                    is None
                ):
                    missing.append("missing_model_provenance")
        windows = native_windows(
            meta, times, recipe["core_seconds"], recipe["halo_seconds"]
        )
        if [p["window"] for p in plan["parts"]] != windows:
            raise ValueError("Native core/halo coverage changed")
        checkpoints = [("segments", None, plan.get("segments"))]
        checkpoints += [
            (s, p["window"], p["stages"].get(s))
            for p in plan["parts"]
            for s in ("players", "shuttle")
        ]
        identifiers = [cp["run_id"] for _, _, cp in checkpoints if cp]
        snapshot = catalog_snapshot(roots["data"], vid, [plan["job_id"], *identifiers])
        catalogs[vid] = {
            "job_ids": [plan["job_id"], *identifiers],
            "snapshot": snapshot,
        }
        ann = snapshot["annotations"] if snapshot else None
        if snapshot is None or ann is None or snapshot["video"] is None:
            missing.append("missing_native_registration")
        elif {k: snapshot["video"].get(k) for k in projection} != projection or ann.get(
            "revision"
        ) != snapshot["revision"]:
            raise ValueError("Substituted registered source/annotation revision")
        if (
            ann is not None
            and context_signature(ann, 0, len(times)) != recipe["context_signature"]
        ):
            missing.append("incompatible_frozen_inference_context")
        parent = snapshot["jobs"].get(plan["job_id"]) if snapshot else None
        if (
            plan.get("state") != "completed"
            or plan.get("processing_complete") is not True
            or not parent
            or parent.get("status") != "completed"
            or parent.get("kind") != "analysis"
            or parent.get("video_id") != vid
            or parent.get("summary", {}).get("analysis_key") != key
        ):
            missing.append("incomplete_native_analysis_registration")
        runs, stage_reasons = {}, {}
        for stage, window, cp in checkpoints:
            index = window["index"] if window else -1
            token = (index, stage)
            stage_reasons[token] = []
            if cp is None:
                stage_reasons[token].append("missing_native_checkpoint")
                continue
            deps = (
                {}
                if window is None
                else {"segments": plan["segments"]["sha256"]}
                if plan.get("segments")
                else None
            )
            if stage == "shuttle":
                players_cp = plan["parts"][index]["stages"].get("players")
                deps = (
                    {**deps, "players": players_cp["sha256"]}
                    if deps is not None and players_cp
                    else None
                )
            stage_key = (
                native_stage_key(recipe, stage, window, deps)
                if deps is not None
                else None
            )
            if stage_key is not None and cp["run_id"] != stage_key[:32]:
                raise ValueError("Native stage dependency/recipe key mismatch")
            if (
                not isinstance(cp["run_id"], str)
                or len(cp["run_id"]) != 32
                or any(c not in "0123456789abcdef" for c in cp["run_id"])
            ):
                raise ValueError("Invalid native stage identifier")
            run = document(
                inside(roots["data"], f"{vid}/runs/{cp['run_id']}.json"), cp["sha256"]
            )
            if run is None:
                stage_reasons[token].append("missing_native_stage_file")
                continue
            runs[token] = run
            first, last = (
                (window["start_frame"], window["end_frame"])
                if window
                else (0, len(times))
            )
            if (
                run.get("stage") != stage
                or run.get("video_id") != vid
                or run.get("video_sha256") != meta["sha256"]
                or run.get("analysis_key") != key
                or (
                    stage_key is not None and run.get("analysis_stage_key") != stage_key
                )
                or run.get("analysis_part_index") != index
                or run.get("start_frame") != first
                or run.get("end_frame") != last
                or (
                    window is not None
                    and (
                        run.get("analysis_core_start_frame")
                        != window["core_start_frame"]
                        or run.get("analysis_core_end_frame")
                        != window["core_end_frame"]
                    )
                )
            ):
                raise ValueError("Substituted native stage/source/range")
            job = snapshot["jobs"].get(cp["run_id"]) if snapshot else None
            if (
                not job
                or job.get("status") != "completed"
                or job.get("kind") != stage
                or job.get("video_id") != vid
                or job.get("summary", {}).get("checkpoint") != cp
            ):
                stage_reasons[token].append("incompatible_native_stage_registration")
            if window is not None:
                native_rows(run, meta, times, window)
                if (
                    not models
                    or run.get("checkpoint_sha256") != models[stage]["sha256"]
                ):
                    stage_reasons[token].append("incompatible_native_model_provenance")
            else:
                cuts = run.get("cut_frames", [])
                if cuts != sorted(set(cuts)) or any(
                    type(f) is not int or not 0 < f < len(times) for f in cuts
                ):
                    raise ValueError("Invalid native camera boundaries")
                if not finite(meta.get("fps")) or meta["fps"] <= 0:
                    raise ValueError("Invalid native nominal frame rate")
                gap_limit = max(0.1, 2.5 / meta["fps"])
                physical_gaps = [
                    i
                    for i in range(1, len(times))
                    if times[i] - times[i - 1] > gap_limit + 1e-8
                ]
                if (
                    run.get("timestamp_gap_threshold_s") != gap_limit
                    or [
                        b["frame"]
                        for b in run.get("boundaries", [])
                        if b.get("reason") == "timestamp_discontinuity"
                    ]
                    != physical_gaps
                ):
                    raise ValueError(
                        "Native source timestamp gaps lost camera separation"
                    )
                for boundary in run.get("boundaries", []):
                    frame = boundary["frame"]
                    if (
                        type(frame) is not int
                        or frame not in cuts
                        or not finite(boundary.get("time_s"))
                        or abs(boundary["time_s"] - times[frame])
                        > PROTOCOL["clock_tolerance_s"]
                    ):
                        raise ValueError("Native camera boundary PTS mismatch")
        scan = runs.get((-1, "segments"))
        if scan is not None and ann is not None:
            for part in plan["parts"]:
                window = part["window"]
                first, last, index = (
                    window["start_frame"],
                    window["end_frame"],
                    window["index"],
                )
                expected = corrected_boundaries(
                    slice_camera_scan(meta, scan, first, last), ann, first, last
                )
                for stage in ("players", "shuttle"):
                    token = (index, stage)
                    run = runs.get(token)
                    if run is None:
                        continue
                    if any(
                        run.get(k) != expected.get(k)
                        for k in (
                            "cut_frames",
                            "raw_cut_frames",
                            "known_preceding_cut_frames",
                            "known_preceding_timestamp_gaps",
                            "preceding_reviewed_cut_frame",
                            "applied_camera_corrections",
                        )
                    ):
                        stage_reasons[token].append("incompatible_camera_context")
                    try:
                        view = reviewed_run(run, ann)
                        if view.get("requires_tracking_rerun"):
                            stage_reasons[token].append(
                                "incompatible_scene_or_court_context"
                            )
                        if stage == "players":
                            # Validates automatic calibration interval/cut expiry.
                            effective_annotations(ann, run)
                    except ValueError:
                        stage_reasons[token].append("incompatible_calibration_context")
                    cuts = sorted(
                        {
                            0,
                            *run.get("cut_frames", []),
                            *run.get("known_preceding_cut_frames", []),
                        }
                    )
                    for row in run["frames"]:
                        if (
                            row.get("camera_segment_start_frame")
                            != cuts[bisect.bisect_right(cuts, row["frame"]) - 1]
                        ):
                            raise ValueError("Native row camera identity mismatch")
        for case in selected:
            frame = case["frame"]
            window = next(
                w
                for w in windows
                if w["core_start_frame"] <= frame < w["core_end_frame"]
            )
            index = window["index"]
            reasons = set(missing)
            for token in ((-1, "segments"), (index, "players"), (index, "shuttle")):
                reasons.update(stage_reasons[token])
            run = runs.get((index, "shuttle"))
            point, context = None, None
            if run is not None:
                row = run["frames"][frame - window["start_frame"]]
                point = row["shuttle"]
                cuts = run.get("cut_frames", [])
                left = max([window["start_frame"], *[c for c in cuts if c <= frame]])
                right = min([window["end_frame"], *[c for c in cuts if c > frame]])
                context = [left, right]  # Median background uses this whole view.
                if (
                    point.get("repaired") is not False
                    or run.get("repaired_frames") != 0
                ):
                    reasons.add("repaired_native_output")
                if run.get("temporal_context_crosses_detected_cuts") is not False:
                    reasons.add("incompatible_neural_camera_context")
                if point["visible"]:
                    start, end = (
                        point.get("selection_context_start_frame"),
                        point.get("selection_context_end_frame"),
                    )
                    if (
                        type(start) is not int
                        or type(end) is not int
                        or not left <= start <= frame < end <= right
                        or point.get("selection_context_excluded") is not False
                    ):
                        reasons.add("incompatible_transitive_selection_context")
                    else:
                        context = [min(left, start), max(right, end)]
                        history = point.get("selection_context_frames", [])
                        if (
                            not isinstance(history, list)
                            or history != sorted(set(history))
                            or any(
                                type(f) is not int or not left <= f < frame
                                for f in history
                            )
                        ):
                            reasons.add("incompatible_transitive_selection_history")
                        else:
                            predecessors = [
                                run["frames"][f - window["start_frame"]]["shuttle"]
                                for f in history
                            ]
                            starts = [
                                p.get("selection_context_start_frame")
                                for p in predecessors
                            ]
                            if (
                                any(
                                    not p.get("visible")
                                    or p.get("repaired") is not False
                                    or p.get("selection_context_excluded") is not False
                                    or type(p.get("selection_context_end_frame"))
                                    is not int
                                    or p.get("selection_context_end_frame")
                                    != previous + 1
                                    for previous, p in zip(history, predecessors)
                                )
                                or any(
                                    type(f) is not int or not left <= f <= previous
                                    for previous, f in zip(history, starts)
                                )
                                or start != min([frame, *starts])
                                or end != frame + 1
                            ):
                                reasons.add("incompatible_transitive_selection_history")
                if ann is not None and excluded_scene(ann, *context) is not None:
                    reasons.add("excluded_scene_in_neural_or_background_context")
                if any(
                    context[0] < cut < context[1]
                    for cut in by_label[case["id"]]["observed_cut_frames"]
                ):
                    reasons.add("source_observed_cut_in_cached_context")
            observations[case["id"]] = {
                "available": not reasons,
                "point": point,
                "reason": ";".join(sorted(reasons)) if reasons else None,
                "core_index": index,
                "background_context_frames": context,
                "shuttle_run_id": plan["parts"][index]["stages"]
                .get("shuttle", {})
                .get("run_id"),
            }
        provenance.append(
            {
                "video_id": vid,
                "analysis_key": key,
                "manifest_path": selections[vid][0],
                "runtime_source_files": recipe["source_files"],
                "models": models,
                "settings": recipe["settings"],
                "producer_versions": recipe["library_versions"],
                "localization_recipes": [
                    runs[(w["index"], "shuttle")].get("localization")
                    for w in windows
                    if (w["index"], "shuttle") in runs
                ],
                "windows": len(windows),
                "context_signature": recipe["context_signature"],
            }
        )
    for name, entry in files.items():
        path = inside(root, name)
        current = file_hash(path) if path.is_file() else None
        if current != entry["sha256"]:
            raise ValueError("Native inputs changed during audit")
    for vid, entry in catalogs.items():
        if encoded(catalog_snapshot(roots["data"], vid, entry["job_ids"])) != encoded(
            entry["snapshot"]
        ):
            raise ValueError("Native registration changed during audit")
    return {
        "files": files,
        "catalogs": catalogs,
        "manifest_selection": selections,
        "provenance": provenance,
        "observations": observations,
    }


def audit_inputs(root, packet_root, packet_sha256, label_root, labels_sha256):
    packet, _ = validate_packet(
        packet_root, (packet_root / "packet.json").read_bytes(), packet_sha256
    )
    sources = load_inventory(
        root,
        sealed_bytes(packet_root, packet["inventory"]),
        PROTOCOL["inventory_sha256"],
    )
    labels = load_labels(
        label_root,
        (label_root / "labels.json").read_bytes(),
        labels_sha256,
        packet,
        packet_sha256,
    )
    return packet, sources, labels


def freeze_baseline(
    root, packet_root, packet_sha256, label_root, labels_sha256, locations, output
):
    root, packet_root, label_root = (
        root.resolve(),
        packet_root.resolve(),
        label_root.resolve(),
    )
    packet, sources, labels = audit_inputs(
        root, packet_root, packet_sha256, label_root, labels_sha256
    )
    locations = {
        name: path.resolve().relative_to(root).as_posix()
        for name, path in locations.items()
    }
    evidence = native_observations(
        root, sources, packet["cases"], labels["cases"], locations
    )
    audit_inputs(root, packet_root, packet_sha256, label_root, labels_sha256)
    output = ignored_output(root, output)
    publish(
        output / "baseline.json",
        {
            "schema_version": 1,
            "packet_sha256": packet_sha256,
            "labels_sha256": labels_sha256,
            "locations": locations,
            "evidence": evidence,
            "selection": "Unique original native manifest per fixed source; unique core owner; no best halo or recipe selection",
        },
    )
    return {
        "baseline_sha256": file_hash(output / "baseline.json"),
        "cases": len(packet["cases"]),
        "available": sum(o["available"] for o in evidence["observations"].values()),
        "sealed_files": len(evidence["files"]),
    }


def evaluate_baseline(
    root,
    packet_root,
    packet_sha256,
    label_root,
    labels_sha256,
    baseline_path,
    baseline_sha256,
    output,
):
    root, packet_root, label_root = (
        root.resolve(),
        packet_root.resolve(),
        label_root.resolve(),
    )
    package = Path(__file__).parent
    consumer = {
        name: (package / name).read_bytes()
        for name in (
            "shuttle_validation.py",
            "rallies.py",
            "scene_review.py",
            "calibration_context.py",
            "schemas.py",
            "segments.py",
            "video.py",
            "orientation.py",
            "av_runtime.py",
            "config.py",
        )
    }
    packet, sources, labels = audit_inputs(
        root, packet_root, packet_sha256, label_root, labels_sha256
    )
    raw = baseline_path.read_bytes()
    if digest(raw) != baseline_sha256:
        raise ValueError("Changed frozen baseline index")
    baseline = read_json(raw)
    if (
        baseline.get("schema_version") != 1
        or baseline.get("packet_sha256") != packet_sha256
        or baseline.get("labels_sha256") != labels_sha256
    ):
        raise ValueError("Baseline is not bound to frozen source labels")
    evidence = native_observations(
        root, sources, packet["cases"], labels["cases"], baseline["locations"]
    )
    if encoded(evidence) != encoded(baseline["evidence"]):
        raise ValueError(
            "Frozen native baseline inputs/results changed; preserve and investigate"
        )
    cases, truth, obs = packet["cases"], labels["cases"], evidence["observations"]

    def group(indices):
        return score_cases(
            [cases[i] for i in indices],
            [truth[i] for i in indices],
            {cases[i]["id"]: obs[cases[i]["id"]] for i in indices},
        )

    groups = {"all": group(range(len(cases)))}
    for name, predicate in (
        *[
            ("source/" + s["id"], lambda c, e, vid=s["id"]: c["video_id"] == vid)
            for s in PROTOCOL["sources"]
        ],
        *[
            ("state/" + state, lambda c, e, state=state: e["label"]["state"] == state)
            for state in PROTOCOL["states"]
        ],
        *[
            ("difficulty/" + tag, lambda c, e, tag=tag: tag in e["label"]["difficulty"])
            for tag in PROTOCOL["difficulty_tags"]
        ],
        ("disagreement/yes", lambda c, e: any(e["disagreement"].values())),
        ("disagreement/no", lambda c, e: not any(e["disagreement"].values())),
        (
            "selection/known_gap",
            lambda c, e: c["frame"] in PROTOCOL["extra_frames"].get(c["video_id"], []),
        ),
        (
            "selection/uniform",
            lambda c, e: (
                c["frame"] not in PROTOCOL["extra_frames"].get(c["video_id"], [])
            ),
        ),
        ("availability/yes", lambda c, e: obs[c["id"]]["available"]),
        ("availability/no", lambda c, e: not obs[c["id"]]["available"]),
    ):
        groups[name] = group(
            [i for i, (c, e) in enumerate(zip(cases, truth)) if predicate(c, e)]
        )
    report = {
        "schema_version": 1,
        "packet_sha256": packet_sha256,
        "labels_sha256": labels_sha256,
        "baseline_sha256": baseline_sha256,
        "protocol_sha256": digest(encoded(PROTOCOL)),
        "consumer_source_sha256": digest(consumer["shuttle_validation.py"]),
        "consumer_files": {name: digest(raw) for name, raw in consumer.items()},
        "groups": groups,
        "disagreements": {
            k: sum(e["disagreement"][k] for e in truth)
            for k in truth[0]["disagreement"]
        },
        "failure_categories": dict(
            Counter(r["outcome"] for r in groups["all"]["frames"])
        ),
        "provenance": evidence["provenance"],
        "limitations": PROTOCOL["limitations"],
    }
    audit_inputs(root, packet_root, packet_sha256, label_root, labels_sha256)
    if any((package / name).read_bytes() != raw for name, raw in consumer.items()):
        raise ValueError("Audit consumer code changed during evaluation")
    output = ignored_output(root, output)
    (output / "consumer").mkdir()
    for name, raw in consumer.items():
        with (output / "consumer" / name).open("xb") as handle:
            handle.write(raw)
    publish(output / "report.json", report)
    return {
        "report_sha256": file_hash(output / "report.json"),
        "cases": len(cases),
        "failures": report["failure_categories"],
        "all": {k: v for k, v in groups["all"].items() if k != "frames"},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    packet = commands.add_parser(
        "packet", help="Freeze and render original-size source-only cases"
    )
    for name in ("root", "inventory", "protocol", "output"):
        packet.add_argument("--" + name, type=Path, required=True)
    packet.add_argument("--inventory-sha256", required=True)
    freeze = commands.add_parser(
        "freeze-labels",
        help="Seal two real assessments and explicit source adjudication before baseline access",
    )
    for name in ("root", "packet", "adjudication", "output"):
        freeze.add_argument("--" + name, type=Path, required=True)
    freeze.add_argument("--packet-sha256", required=True)
    freeze.add_argument("--assessments", nargs=2, type=Path, required=True)
    for command, help_text in (
        ("baseline", "Seal the unchanged native cache after source-label freeze"),
        ("audit", "Revalidate frozen inputs and score every case"),
    ):
        native = commands.add_parser(command, help=help_text)
        for name in ("root", "packet", "labels", "output"):
            native.add_argument("--" + name, type=Path, required=True)
        for name in ("packet-sha256", "labels-sha256"):
            native.add_argument("--" + name, required=True)
        if command == "baseline":
            for name in ("data", "runtime", "weights"):
                native.add_argument("--" + name, type=Path, required=True)
        else:
            native.add_argument("--baseline", type=Path, required=True)
            native.add_argument("--baseline-sha256", required=True)
    args = parser.parse_args(argv)
    if args.command == "packet":
        result = make_packet(
            args.root, args.inventory, args.inventory_sha256, args.protocol, args.output
        )
    elif args.command == "freeze-labels":
        result = freeze_labels(
            args.root,
            args.packet,
            args.packet_sha256,
            args.assessments,
            args.adjudication,
            args.output,
        )
    elif args.command == "baseline":
        result = freeze_baseline(
            args.root,
            args.packet,
            args.packet_sha256,
            args.labels,
            args.labels_sha256,
            {k: getattr(args, k) for k in ("data", "runtime", "weights")},
            args.output,
        )
    else:
        result = evaluate_baseline(
            args.root,
            args.packet,
            args.packet_sha256,
            args.labels,
            args.labels_sha256,
            args.baseline,
            args.baseline_sha256,
            args.output,
        )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
