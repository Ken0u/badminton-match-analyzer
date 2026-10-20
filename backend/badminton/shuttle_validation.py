"""Source-only shuttle development packets and immutable, uncertainty-aware audits.

This research tool never changes application annotations or runs a model. Raw
media, assessments and cached predictions belong in ignored local lineages.
"""

import argparse
import hashlib
import itertools
import json
import math
import os
import platform
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
        meta = read_json(inputs["metadata"].read_bytes())
        times = read_json(inputs["timestamps"].read_bytes())
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
    if encoded(
        read_json(sealed_path(root, packet["protocol"]).read_bytes())
    ) != encoded(PROTOCOL):
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
    inventory = read_json(sealed_path(root, packet["inventory"]).read_bytes())
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
            path = sealed_path(root, files[key])
            if files[key]["sha256"] != entry["inputs"][key]["sha256"]:
                raise ValueError("Substituted original source inputs")
            documents[key] = read_json(path.read_bytes())
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
            path = sealed_path(root, item["image"])
            with Image.open(path) as image:
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
        or label["reason"].strip().lower() in {"todo", "unassessed"}
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    packet = commands.add_parser(
        "packet", help="Freeze and render original-size source-only cases"
    )
    for name in ("root", "inventory", "protocol", "output"):
        packet.add_argument("--" + name, type=Path, required=True)
    packet.add_argument("--inventory-sha256", required=True)
    args = parser.parse_args(argv)
    result = make_packet(
        args.root, args.inventory, args.inventory_sha256, args.protocol, args.output
    )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
