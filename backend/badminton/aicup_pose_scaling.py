"""One private weak-supervision scaling experiment; never app model promotion.

Old scientific operations are consumed. Their sealed rows and control are reused;
only the previously unprocessed training clips may be decoded and inferred.
"""

import argparse
import copy
import hashlib
import io
import json
import math
import sqlite3
import subprocess
import tarfile
import time
import zipfile
import zlib
from collections import Counter, OrderedDict
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path

import numpy as np

from . import aicup_pose_learning as learning

actor, producer = learning.actor, learning.producer
read_json, digest, publish = producer.read_json, producer.digest, producer.publish
PROTOCOL = {
    "schema_version": 1,
    "name": "aicup-pose-scaling-v1",
    "sources": producer.PROTOCOL["sources"],
    "historical": {
        "pilot": "6dbdd044849ff22e98e92df33be0d9f487536710",
        "actor": "86cad39b715ceadf380b4452707febe1aa6e9c6a",
        "learning": "4e063b49974eb6fe7d97a831edb8ea7ac399cf62",
    },
    "original": {
        "preparation": learning.PROTOCOL["preparation_sha256"],
        "native": learning.PROTOCOL["native_completion_sha256"],
        "actor_prospective": learning.PROTOCOL["actor_prospective_sha256"],
        "actor_completion": learning.PROTOCOL["actor_completion_sha256"],
        "actor_diagnostics": learning.PROTOCOL["actor_diagnostics_sha256"],
        "control_completion": "42500f898ad6a1fd4548d42dd233f25826be9f7ea8cc6248fb10ab735dc84dd3",
        "control_features": "12bc9769a57077ed33e50d5fccec69386760487ce8fce0a9f5e4269a5da7e1be",
        "control_model": "ae66352af2877a58a5d665b69a5077b0319f613e27087ff285c10b0cfc9605ae",
        "control_statistics": "ba02db68741ad8e2bbf548f1395aa1fd6c6bd6e5654c272122b4ce003c51d367",
        "clock_ledger": "de5ca6509087dfd79048e179fc500536660127b8c7927aad995ab8faf739585b",
    },
    "expected": {
        "train_clips": 424,
        "validation_clips": 23,
        "new_clips": 402,
        "reused_clips": 45,
        "train_rows": 4684,
        "validation_rows": 353,
        "new_rows": 4253,
        "reused_rows": 784,
        "new_frames": 141197,
        "total_frames": 165470,
        "new_media_bytes": 825568691,
    },
    "features": {
        "dimensions": 108,
        "center_offsets": [-1, 0],
        "joints": [5, 6, 7, 8, 9, 10],
        "roles": ["hitter", "defender"],
        "minimum_confidence": 0.25,
        "representation": "center,center,zero-velocity; unchanged original static recipe",
        "normalization": learning.PROTOCOL["features"]["normalization"],
        "missing": "Zero coordinates/confidence and explicit masks; no interpolation",
    },
    "correspondence": copy.deepcopy(actor.PROTOCOL),
    "training": copy.deepcopy(learning.PROTOCOL["training"]),
    "labels": copy.deepcopy(learning.PROTOCOL["labels"]),
    "limits": {
        "task_seconds": 57600,
        "operation_seconds": 43200,
        "output_bytes": 4294967296,
        "decoded_frame_visits": 282394,
        "model_frame_observations": 141197,
        "real_fits": 1,
        "original_operations": 1,
        "image_bytes": 0,
    },
    "native": {
        "variant": "small",
        "stride": 1,
        "auto_calibrate": True,
        "frame_cache": {
            "codec": "zlib level 1 of exact native ndarray/planes; RGB/BGR byte parity required",
            "max_compressed_bytes": 1073741824,
            "initial_free_fraction": 0.5,
            "minimum_free_bytes": 536870912,
            "initial_extra_bytes": 67108864,
            "reconstruction_lru_frames": 16,
            "disk_image_outputs": 0,
        },
    },
    "training_ready": False,
    "independent_accuracy_established": False,
    "model_installed_in_app": False,
    "complete_rally_references": {"accepted": 0, "required": 2},
    "limitations": [
        "Weak published references, not verified source truth",
        "Actual actors/scenes, original-match independence and upstream pretraining unresolved",
        "Author declaration CC BY 4.0 does not resolve original media or deployment rights",
        "Familiar validation development; no held-out test access or model promotion",
    ],
}


def check_deadline(granted_at, committed_at, deadline):
    if (
        not actor.finite([granted_at, committed_at, deadline])
        or not granted_at <= committed_at <= time.time() < deadline
        or deadline > granted_at + PROTOCOL["limits"]["task_seconds"]
        or deadline > committed_at + PROTOCOL["limits"]["operation_seconds"]
    ):
        raise ValueError("Expired or unbounded original scaling deadline")


def code_seals():
    root = Path(__file__).resolve().parents[2]
    paths = [
        *sorted((root / "backend/badminton").glob("*.py")),
        root / "backend/badminton/model_manifest.json",
        root / "backend/badminton/aicup_capture_groups_v1.json",
        root / "scripts/scale_aicup_pose_learning.py",
        root / "data/manifests/aicup_pose_scaling_protocol_v1.json",
    ]
    return {p.relative_to(root).as_posix(): digest(p) for p in paths}


def tested_commit():
    root = Path(__file__).resolve().parents[2]
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    git_seals(revision, code_seals())
    return revision


def git_seals(revision, seals):
    """Verify historical inventories at their actual revision, not a later glob."""
    root = Path(__file__).resolve().parents[2]
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("Expected an exact historical source revision")
    paths = {
        name if "/" in name else "backend/badminton/" + name: expected
        for name, expected in seals.items()
    }
    for name in paths:
        producer.inside(root, name)
    raw = subprocess.check_output(
        ["git", "archive", "--format=tar", revision, "--", *paths], cwd=root
    )
    actual = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            if member.isfile():
                with archive.extractfile(member) as stream:
                    actual[member.name] = hashlib.sha256(stream.read()).hexdigest()
    if actual != paths:
        raise ValueError("Changed historical producer dependency inventory")


def select_cohort(clips, folds, contexts, old_freeze):
    """All labelled training; exactly the already frozen validation membership."""
    by_key = {producer.clip_key(c): c for c in clips}
    if len(by_key) != len(clips):
        raise ValueError("Duplicate source clip")
    old = {c["key"]: c for c in old_freeze["clips"]}
    if len(old) != len(old_freeze["clips"]):
        raise ValueError("Duplicate original cohort clip")
    for key, clip in old.items():
        if (
            key not in by_key
            or clip["fold"] not in producer.FOLDS
            or folds[key] != clip["fold"]
            or contexts[key] != clip["context"]
            or "label_path" not in by_key[key]
            or by_key[key]["media_sha256"] != clip["source_sha256"]
            or by_key[key]["label_sha256"] != clip["source_label_sha256"]
        ):
            raise ValueError("Changed original membership/fold/context/source")
    train = [
        producer.clip_key(c)
        for c in clips
        if folds[producer.clip_key(c)] == "train" and "label_path" in c
    ]
    validation = [c["key"] for c in old_freeze["clips"] if c["fold"] == "validation"]
    keys = train + validation
    reused, new = [k for k in keys if k in old], [k for k in keys if k not in old]
    expected = PROTOCOL["expected"]
    if (
        len(train) != expected["train_clips"]
        or len(validation) != expected["validation_clips"]
        or len(new) != expected["new_clips"]
        or len(reused) != expected["reused_clips"]
        or set(reused) != set(old)
        or any(folds[k] != "train" for k in new)
        or sum(by_key[k]["media_bytes"] for k in new) != expected["new_media_bytes"]
    ):
        raise ValueError("Changed fixed scaling cohort or media denominator")
    return {
        "clip_keys": keys,
        "new_keys": new,
        "reused_keys": reused,
        "clips": [
            {**by_key[k], "key": k, "fold": folds[k], "context": contexts[k]}
            for k in keys
        ],
    }


def canonical_reference_rows(archive, clips, folds, cohort):
    by_key = {producer.clip_key(c): c for c in clips}
    keys = cohort["clip_keys"]
    if (
        len(keys) != len(set(keys))
        or set(keys) != set(cohort["new_keys"]) | set(cohort["reused_keys"])
        or set(cohort["new_keys"]) & set(cohort["reused_keys"])
        or any(folds[k] not in producer.FOLDS for k in keys)
        or any(folds[k] != "train" for k in cohort["new_keys"])
    ):
        raise ValueError("Held-out or conflicting source selection")
    rows = producer.canonical_rows(archive, [by_key[k] for k in keys], folds)
    expected = PROTOCOL["expected"]
    counts = Counter(r["fold"] for r in rows)
    if (
        counts
        != {"train": expected["train_rows"], "validation": expected["validation_rows"]}
        or sum(r["clip_key"] in cohort["new_keys"] for r in rows)
        != expected["new_rows"]
        or sum(r["clip_key"] in cohort["reused_keys"] for r in rows)
        != expected["reused_rows"]
    ):
        raise ValueError("Changed canonical source-row denominator")
    return rows


def static_features(reference, diagnostic, result, video, ledger):
    """The original static recipe, without constructing unused temporal inputs."""
    h, pair = reference["source_contact_frame"], diagnostic["weak_pair"]
    frames = result["frames"]
    if pair is not None and (type(h) is not int or not 0 < h < len(frames)):
        raise ValueError("Weak pair lacks a valid original contact interval")
    camera = frames[h]["camera_segment_start_frame"] if pair is not None else None
    values = np.zeros((2, 2, 6, 3), np.float64)
    masks = np.zeros((2, 2, 6), bool)
    clocks = []
    for slot, offset in enumerate((-1, 0)):
        index = h + offset if type(h) is int else -1
        valid = 0 <= index < len(frames)
        clocks.append(copy.deepcopy(ledger["rows"][index]) if valid else None)
        if pair is not None and valid:
            for role, name in enumerate(("hitter", "defender")):
                values[slot, role], masks[slot, role] = learning.observed_joints(
                    frames[index], pair[name], camera, video
                )
    center = learning.pool(values, masks, 2).ravel()
    feature = np.concatenate((center, center, np.zeros(36))).tolist()
    return {
        "static": feature,
        "center_mask": masks.tolist(),
        "native_clocks": clocks,
        "camera": camera,
        "available": pair is not None,
        "observed_joint_slots": int(masks.sum()),
    }


def target_fields(clip, ref):
    family = "serve" if ref["kind"] == "serve" else ref["family"]
    return {
        "id": ref["id"],
        "clip_key": clip["key"],
        "fold": clip["fold"],
        "context": clip["context"],
        "family": learning.FAMILIES.index(family)
        if family in learning.FAMILIES
        else -1,
        "side": learning.SIDES.index(ref["side"])
        if ref["side"] in learning.SIDES
        else -1,
        "training_ready": False,
        "scene_truth": "unknown",
        "actor_truth": "unknown",
    }


def feature_row(clip, ref, diagnostic, result, video, ledger):
    if diagnostic["reference_id"] != ref["id"] or ref["clip_key"] != clip["key"]:
        raise ValueError("Conflicting feature/reference identity")
    return target_fields(clip, ref) | static_features(
        ref, diagnostic, result, video, ledger
    )


def combined_features(cohort, original_rows, new_rows):
    originals, fresh = (
        {r["id"]: r for r in rows} for rows in (original_rows, new_rows)
    )
    if (
        len(originals) != len(original_rows)
        or len(fresh) != len(new_rows)
        or set(originals) & set(fresh)
        or any(r["clip_key"] not in cohort["reused_keys"] for r in original_rows)
        or any(r["clip_key"] not in cohort["new_keys"] for r in new_rows)
    ):
        raise ValueError("Duplicate or conflicting old/new feature membership")
    clips = {c["key"]: c for c in cohort["clips"]}
    refs = cohort["reference_rows"]
    if {r["id"] for r in refs} != set(originals) | set(fresh) or len(refs) != len(
        originals
    ) + len(fresh):
        raise ValueError("Incomplete or extra source/feature denominator")
    result = []
    for ref in refs:
        row = originals.get(ref["id"], fresh.get(ref["id"]))
        expected = target_fields(clips[ref["clip_key"]], ref)
        if any(row.get(k) != v for k, v in expected.items()):
            raise ValueError("Feature targets contradict canonical original CSV")
        result.append(row)
    old_validation = [r for r in original_rows if r["fold"] == "validation"]
    if [r for r in result if r["fold"] == "validation"] != old_validation:
        raise ValueError("Original validation order or inputs changed")
    learning.arrays(result, "static")
    return result


def clock_and_scan(media, progress):
    """One source decode supplies exact clocks and the unchanged cut detector."""
    import torchvision  # noqa: F401  # initialize before threaded PyAV

    from .av_runtime import open_media
    from .orientation import display_dimensions, frame_rotation, orient_frame
    from .segments import METHOD, RECIPE, BoundaryDetector, camera_ranges

    before, rows, rotation, cuts = digest(media), [], None, {}
    began = time.perf_counter()
    with open_media(str(media)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        base, origin, rate = (
            Fraction(stream.time_base),
            stream.start_time or 0,
            float(stream.average_rate or 0),
        )
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError("Unavailable native source rate")
        detector = None
        for index, frame in enumerate(container.decode(stream)):
            progress(index)
            current = frame_rotation(frame)
            if rotation is None:
                rotation = current
                width, height = display_dimensions(
                    stream.width, stream.height, rotation
                )
                detector = BoundaryDetector(rate, width, height)
            if current != rotation or frame.pts is None:
                raise ValueError("Missing native PTS or changing orientation")
            frame_base = Fraction(frame.time_base)
            exact = frame.pts * frame_base - origin * base
            if exact < 0 or (rows and exact <= Fraction(*rows[-1]["relative_time"])):
                raise ValueError("Invalid or nonmonotonic source PTS")
            timestamp = round(float(exact), 8)
            if rows and timestamp <= round(
                float(Fraction(*rows[-1]["relative_time"])), 8
            ):
                raise ValueError("Rounded app clock loses native identity")
            rows.append(
                {
                    "frame": index,
                    "pts": frame.pts,
                    "time_base": [frame_base.numerator, frame_base.denominator],
                    "relative_time": [exact.numerator, exact.denominator],
                    "duration": frame.duration or 0,
                }
            )
            for cut, reason in detector.process(
                index, timestamp, orient_frame(frame, expected_rotation=rotation)
            ).items():
                cuts.setdefault(cut, reason)
        if not rows:
            raise ValueError("Empty source")
        source_width, source_height, codec = (
            stream.width,
            stream.height,
            stream.codec_context.name,
        )
    if digest(media) != before:
        raise ValueError("Source changed during native preparation")
    times = [round(float(Fraction(*r["relative_time"])), 8) for r in rows]
    tail = rows[-1]["duration"] * Fraction(*rows[-1]["time_base"])
    tail = (
        float(tail)
        if tail > 0
        else (times[-1] - times[-2] if len(times) > 1 else 1 / rate)
    )
    video = {
        "id": before[:16],
        "sha256": before,
        "name": Path(media).name,
        "mode": "singles",
        "frame_count": len(rows),
        "width": width,
        "height": height,
        "source_width": source_width,
        "source_height": source_height,
        "rotation": rotation,
        "fps": rate,
        "source_start_s": float(origin * base),
        "duration_s": round(times[-1] + tail, 8),
        "codec": codec,
        "time_base": str(base),
    }
    ledger = {
        "schema_version": 1,
        "source_sha256": before,
        "origin_pts": origin,
        "stream_time_base": [base.numerator, base.denominator],
        "rotation": rotation,
        "display_dimensions": [width, height],
        "rows": rows,
    }
    scan = {
        "schema_version": 1,
        "stage": "segments",
        "video_id": video["id"],
        "video_sha256": before,
        "start_frame": 0,
        "end_frame": len(rows),
        "method": METHOD,
        "recipe": RECIPE.copy(),
        "timestamp_gap_threshold_s": detector.gap_threshold,
        "cut_frames": sorted(cuts),
        "boundaries": [
            {"frame": i, "time_s": times[i], "reason": reason, "reviewed": False}
            for i, reason in sorted(cuts.items())
        ],
        "camera_ranges": camera_ranges(0, len(rows), cuts),
        "elapsed_s": round(time.perf_counter() - began, 3),
        "decoded_frames": len(rows),
        "scope": "Camera/timestamp boundaries only; live, replay and rally status unknown",
    }
    return ledger, times, video, scan


CACHE_MAX_BYTES = PROTOCOL["native"]["frame_cache"]["max_compressed_bytes"]
CACHE_MIN_FREE_BYTES = PROTOCOL["native"]["frame_cache"]["minimum_free_bytes"]
CACHE_INITIAL_EXTRA_BYTES = PROTOCOL["native"]["frame_cache"]["initial_extra_bytes"]
CACHE_LRU_FRAMES = PROTOCOL["native"]["frame_cache"]["reconstruction_lru_frames"]


def unpack_frame(record):
    import av

    raw = zlib.decompress(record["compressed_pixels"])
    if hashlib.sha256(raw).hexdigest() != record["raw_sha256"]:
        raise ValueError("Lossless native pixel cache changed")
    array = np.frombuffer(raw, dtype=np.dtype(record["dtype"])).reshape(record["shape"])
    if "planes" in record:
        frame = av.VideoFrame(*record["dimensions"], format=record["format"])
        if len(frame.planes) != len(record["planes"]):
            raise ValueError("Lossless native plane layout changed")
        offset = 0
        for plane, layout in zip(frame.planes, record["planes"], strict=True):
            if plane.height != layout["height"]:
                raise ValueError("Lossless native plane height changed")
            source = array[offset : offset + layout["size"]].reshape(
                layout["height"], layout["line_size"]
            )
            offset += layout["size"]
            restored = np.zeros((plane.height, plane.line_size), np.uint8)
            width = min(plane.line_size, layout["line_size"])
            restored[:, :width] = source[:, :width]
            plane.update(restored.tobytes())
        if offset != len(array):
            raise ValueError("Lossless native plane bytes changed")
    else:
        frame = av.VideoFrame.from_ndarray(array, format=record["format"])
    frame.colorspace = record["colorspace"]
    frame.color_range = record["color_range"]
    frame.pts = record["pts"]
    if record["time_base"] is not None:
        frame.time_base = Fraction(*record["time_base"])
    return frame


def pack_frame(frame):
    planes = None
    try:
        array = frame.to_ndarray()
    except ValueError:
        # PyAV cannot expose some packed formats (such as FFV1 bgr0) as an
        # ndarray. Retain native planes, including row strides, without a color
        # conversion. Reconstruction may use different non-pixel row padding.
        planes = [
            {"size": p.buffer_size, "line_size": p.line_size, "height": p.height}
            for p in frame.planes
        ]
        array = np.frombuffer(b"".join(bytes(p) for p in frame.planes), dtype=np.uint8)
    raw = array.tobytes()
    base = Fraction(frame.time_base) if frame.time_base is not None else None
    record = {
        "compressed_pixels": zlib.compress(raw, 1),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "dtype": str(array.dtype),
        "shape": list(array.shape),
        "format": frame.format.name,
        "colorspace": frame.colorspace,
        "color_range": frame.color_range,
        "pts": frame.pts,
        "time_base": [base.numerator, base.denominator] if base is not None else None,
    }
    if planes is not None:
        record.update(planes=planes, dimensions=[frame.width, frame.height])
    restored = unpack_frame(record)
    if not all(
        np.array_equal(frame.to_ndarray(format=name), restored.to_ndarray(format=name))
        for name in ("rgb24", "bgr24")
    ):
        raise ValueError("Lossless pixel cache does not preserve RGB and BGR")
    return record


@contextmanager
def decode_cache(video, root, times, progress):
    """Retain bounded lossless pixels, reconstructing at most sixteen LRU frames.

    Only source decoding counts as a native frame visit. Court samples and the
    tracking iterator read the exact same cached native pixels and source clock.
    No image or frame cache is written to disk. Scoped adapters always restore.
    """
    import psutil

    from . import court_detection, tracking
    from .video import iter_frames, resolve_source

    initial = psutil.virtual_memory().available
    if initial < CACHE_MIN_FREE_BYTES + CACHE_INITIAL_EXTRA_BYTES:
        raise ValueError("Insufficient RAM for one bounded native clip cache")
    limit = min(initial // 2, CACHE_MAX_BYTES)
    cached, live = [], OrderedDict()
    total = 0
    old_tracking, old_court = tracking.iter_frames, court_detection.iter_frames

    def memory_check():
        if psutil.virtual_memory().available < CACHE_MIN_FREE_BYTES:
            raise ValueError("Insufficient free RAM for bounded native clip cache")

    def frames(requested, requested_root, requested_times, start, end):
        if (
            requested != video
            or Path(requested_root).resolve() != Path(root).resolve()
            or list(requested_times) != list(times)
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(cached)
        ):
            raise ValueError("Cached decoder requested another source or range")
        for index in range(start, end):
            memory_check()
            ordinal, timestamp, record = cached[index]
            if index not in live:
                if len(live) >= CACHE_LRU_FRAMES:
                    live.popitem(last=False)
                live[index] = unpack_frame(record)
                memory_check()
            live.move_to_end(index)
            yield ordinal, timestamp, live[index]

    try:
        for ordinal, timestamp, frame in iter_frames(
            video, root, times, 0, video["frame_count"]
        ):
            memory_check()
            record = pack_frame(frame)
            total += len(record["compressed_pixels"])
            if total > limit:
                raise ValueError("Bounded compressed native clip cache exceeds RAM cap")
            memory_check()
            cached.append((ordinal, timestamp, record))
            progress(len(cached))
        tracking.iter_frames = court_detection.iter_frames = frames
        yield len(cached)
        resolve_source(video, root)
    finally:
        tracking.iter_frames, court_detection.iter_frames = old_tracking, old_court
        cached.clear()
        live.clear()


@contextmanager
def historical_sources(plan):
    """Historical validators retain their scientific checks and original seals."""
    inventories = [
        (
            PROTOCOL["historical"]["pilot"],
            read_json(Path(plan["prepared"]) / "freeze.json")["code"],
        ),
        (PROTOCOL["historical"]["actor"], read_json(plan["actor_prospective"])["code"]),
        (
            PROTOCOL["historical"]["learning"],
            read_json(plan["control_prospective"])["code"],
        ),
    ]
    for revision, seals in inventories:
        git_seals(revision, seals)
    # Every backend helper actually exercised by this consumer must still have
    # the original semantics. Unrelated application changes are not producers.
    folder = Path(__file__).parent
    original_code = inventories[-1][1]
    for name in (
        "aicup_pose_pilot",
        "aicup_actor_correspondence",
        "aicup_pose_learning",
        "aicup_data",
        "datasets",
        "tracking",
        "segments",
        "court_detection",
        "calibration_context",
        "track_consensus",
        "actor_linking",
        "video",
        "orientation",
        "av_runtime",
        "schemas",
        "jobs",
        "storage",
        "config",
        "file_cache",
        "scene_review",
    ):
        key = "backend/badminton/" + name + ".py"
        if digest(folder / (name + ".py")) != original_code[key]:
            raise ValueError("Changed reused semantic helper: " + name)
    known = {producer.encoded(seals) for _, seals in inventories}

    def verify(seals):
        if producer.encoded(seals) not in known:
            raise ValueError("Unknown historical producer inventory")

    previous = actor.verify_producer_code
    try:
        actor.verify_producer_code = verify
        yield
    finally:
        actor.verify_producer_code = previous


def store_job(data, identity):
    with sqlite3.connect(
        (Path(data) / "catalog.sqlite3").as_uri() + "?mode=ro", uri=True
    ) as db:
        row = db.execute("SELECT document FROM jobs WHERE id=?", (identity,)).fetchone()
    return json.loads(row[0]) if row else {}


def original_inputs(plan):
    """Opaque seals and canonical old rows; never refit or regenerate old inputs."""
    control = Path(plan["control"])
    bindings = {
        "preparation": Path(plan["prepared"]) / "freeze.json",
        "native": Path(plan["native"]) / "completion.json",
        "actor_prospective": Path(plan["actor_prospective"]),
        "actor_completion": Path(plan["audit"]) / "completion.json",
        "actor_diagnostics": Path(plan["audit"]) / "diagnostics.json",
        "control_completion": control / "completion.json",
        "control_features": control / "features.json",
        "control_model": control / "static/model.pt",
        "control_statistics": control / "static/statistics.json",
        "clock_ledger": Path(plan["clock_ledger"]),
    }
    for key, path in bindings.items():
        if digest(path) != PROTOCOL["original"][key]:
            raise ValueError("Changed sealed original input: " + key)
    old_plan, complete = (
        read_json(plan["control_prospective"]),
        read_json(control / "completion.json"),
    )
    if (
        digest(plan["control_prospective"]) != complete["prospective_sha256"]
        or old_plan["tested_commit"] != PROTOCOL["historical"]["learning"]
        or old_plan["protocol"] != learning.PROTOCOL
        or any(
            old_plan[k] != plan[k]
            for k in ("workspace", "prepared", "native", "actor_prospective", "audit")
        )
        or not old_plan["granted_at"] <= complete["finished_at"] < old_plan["deadline"]
        or complete["summary"]["real_fits"] != 2
        or complete["shared_data"] != str(Path(plan["workspace"]) / "data/processed")
        or complete["training_ready"]
        or complete["test_opened"]
        or complete["model_installed_in_app"]
    ):
        raise ValueError("Changed original learning binding/recipe/window")
    claim = learning.execution_claim(old_plan)
    if complete["execution_claim"] != str(claim) or read_json(claim) != {
        "prospective_sha256": complete["prospective_sha256"],
        "output": str(control),
    }:
        raise ValueError("Changed consumed original learning claim")
    actor.verify_inventory(
        control,
        complete["artifacts"]
        | {"completion.json": PROTOCOL["original"]["control_completion"]},
    )
    original_job = store_job(complete["shared_data"], complete["job_id"])
    if (
        original_job.get("status") != "completed"
        or original_job.get("summary") != complete["summary"]
    ):
        raise ValueError("Original learning Store job is not completed")
    if (
        producer.annotation_snapshot(complete["shared_data"])
        != complete["original_annotations_sha256"]
    ):
        raise ValueError("Original annotation history changed")
    with historical_sources(plan):
        observations, diagnostics = learning.load_inputs(
            **{k: plan[k] for k in ("prepared", "native", "actor_prospective", "audit")}
        )
    features = read_json(control / "features.json")
    refs = [r for _, _, _, rows in observations for r in rows]
    if [r["id"] for r in refs] != [r["id"] for r in features]:
        raise ValueError("Original feature/target order changed")
    by_id = {r["id"]: r for r in features}
    for clip, _, _, rows in observations:
        for ref in rows:
            row = by_id[ref["id"]]
            if any(row.get(k) != v for k, v in target_fields(clip, ref).items()):
                raise ValueError("Original targets contradict canonical CSV")
    learning.arrays(features, "static")
    return observations, diagnostics, features


def input_sources(plan):
    old = read_json(Path(plan["prepared"]) / "freeze.json")
    paths = {k: Path(v["path"]) for k, v in old["sources"].items()}
    producer.verify_sources(paths)
    if "sources" in plan and plan["sources"] != {
        k: {"path": str(v), "sha256": PROTOCOL["sources"][k]} for k, v in paths.items()
    }:
        raise ValueError("Changed prospective source path/hash binding")
    if paths["model"] != Path(plan["workspace"]) / "models/weights/yolo11s-pose.pt":
        raise ValueError("Model is not the original real-workspace checkpoint")
    return paths


def execution_claim(plan):
    # Fixed cohort identity survives a different freeze, output or grant epoch.
    return (
        Path(plan["workspace"])
        / ".cache"
        / (PROTOCOL["name"] + "-" + PROTOCOL["sources"]["archive"] + "-start.json")
    )


def private_output(plan, output):
    output = actor.private_output(plan["workspace"], output)
    protected = [
        Path(plan[k]).resolve() for k in ("prepared", "native", "audit", "control")
    ]
    protected += [
        Path(plan[k]).parent.resolve()
        for k in ("actor_prospective", "control_prospective")
    ]
    if "clock_ledger" in plan:
        protected.append(Path(plan["clock_ledger"]).parent.resolve())
    if "prospective_directory" in plan:
        protected.append(Path(plan["prospective_directory"]))
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError("New scaling output overlaps immutable original inputs")
    return output


def budget(plan, output, reserve=0, decoded=0, observed=0):
    roots = {Path(plan["prospective_directory"]), Path(output)}
    files = {execution_claim(plan)}
    for root in roots:
        files.update(p for p in root.rglob("*") if p.is_file())
    if (
        any(type(v) is not int or v < 0 for v in (reserve, decoded, observed))
        or sum(p.stat().st_size for p in files if p.is_file()) + reserve
        > PROTOCOL["limits"]["output_bytes"]
        or decoded > PROTOCOL["limits"]["decoded_frame_visits"]
        or observed > PROTOCOL["limits"]["model_frame_observations"]
    ):
        raise ValueError("Fixed scaling output/decode/observation budget exceeded")


def freeze(
    workspace,
    prepared,
    native,
    actor_prospective,
    audit,
    control,
    control_prospective,
    clock_ledger,
    protocol,
    granted_at,
    committed_at,
    deadline,
    output,
    run_output,
):
    check_deadline(granted_at, committed_at, deadline)
    if read_json(protocol) != PROTOCOL:
        raise ValueError("Changed fixed scaling protocol")
    producer.configure_workspace(workspace)
    plan = {
        k: str(Path(v).resolve())
        for k, v in {
            "workspace": workspace,
            "prepared": prepared,
            "native": native,
            "actor_prospective": actor_prospective,
            "audit": audit,
            "control": control,
            "control_prospective": control_prospective,
            "clock_ledger": clock_ledger,
        }.items()
    }
    output = private_output(plan, output)
    run_output = private_output(plan, run_output)
    if (
        output.is_relative_to(run_output)
        or run_output.is_relative_to(output)
        or run_output.exists()
    ):
        raise ValueError("Prospective and new run output must be separate unused paths")
    plan.update(
        prospective_directory=str(output),
        protocol=PROTOCOL,
        code=code_seals(),
        runtime=producer.runtime(),
        tested_commit=tested_commit(),
        granted_at=granted_at,
        committed_at=committed_at,
        deadline=deadline,
        new_decodes=0,
        real_fits=0,
        output=str(run_output),
    )
    observations, _, _ = original_inputs(plan)
    learning.validate_workspace(plan)
    paths = input_sources(plan)
    clips, groups = read_json(paths["clips"]), read_json(paths["groups"])
    folds, contexts = producer.capture_folds(clips, groups)
    plan["cohort"] = select_cohort(
        clips, folds, contexts, read_json(Path(prepared) / "freeze.json")
    )
    plan["old_denominator"] = {
        "clips": len(observations),
        "references": sum(len(o[3]) for o in observations),
        "native_frames": sum(o[0]["frames"] for o in observations),
    }
    if (
        plan["old_denominator"]["native_frames"] + PROTOCOL["expected"]["new_frames"]
        != PROTOCOL["expected"]["total_frames"]
    ):
        raise ValueError("Changed total source-frame denominator")
    plan["sources"] = {
        k: {"path": str(v), "sha256": digest(v)} for k, v in paths.items()
    }
    if plan["code"] != code_seals() or plan["runtime"] != producer.runtime():
        raise ValueError("Source/runtime changed during integrity-only freeze")
    check_deadline(granted_at, committed_at, deadline)
    output.mkdir(exist_ok=False)
    publish(output / "prospective.json", plan)
    publish(
        execution_claim(plan),
        {
            "prospective_sha256": digest(output / "prospective.json"),
            "output": str(run_output),
            "committed_at": committed_at,
            "deadline": deadline,
        },
    )
    budget(plan, output)
    return {
        "prospective_sha256": digest(output / "prospective.json"),
        "execution_claim_sha256": digest(execution_claim(plan)),
        "new_decodes": 0,
        "real_fits": 0,
    }


def prospective(path, expected, clock):
    if digest(path) != expected:
        raise ValueError("Changed prospective scaling freeze")
    plan = read_json(path)
    if (
        plan["protocol"] != PROTOCOL
        or plan["code"] != code_seals()
        or plan["runtime"] != producer.runtime()
    ):
        raise ValueError("Changed committed scaling protocol/consumer/runtime")
    if clock:
        check_deadline(plan["granted_at"], plan["committed_at"], plan["deadline"])
    if read_json(execution_claim(plan)) != {
        "prospective_sha256": expected,
        "output": plan["output"],
        "committed_at": plan["committed_at"],
        "deadline": plan["deadline"],
    }:
        raise ValueError("Changed original scaling execution claim")
    return plan


def clock_index(path, keys):
    selected = {}
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            key = row["partition"] + ":" + row["clip_id"]
            if key not in keys:
                continue
            if key in selected:
                raise ValueError("Duplicate original source-clock metadata")
            selected[key] = row
    if set(selected) != set(keys):
        raise ValueError("Missing original clock metadata")
    return selected


@contextmanager
def required_cuda():
    """The existing tracker may choose CUDA, but may never fall back to CPU."""
    import torch

    original = torch.cuda.is_available

    def available():
        if not original():
            raise ValueError("CUDA became unavailable; CPU fallback is forbidden")
        return True

    try:
        torch.cuda.is_available = available
        yield
    finally:
        torch.cuda.is_available = original


def new_clip(plan, clip, refs, expected_clock, directory, check, progress):
    """Exactly one preparation and one cached perception decode for a new clip."""
    from .schemas import empty_annotations
    from .tracking import track_players

    directory.mkdir(exist_ok=False)
    media = directory / "source.mp4"
    with zipfile.ZipFile(plan["sources"]["archive"]["path"]) as archive:
        info = archive.getinfo(clip["media_path"])
        if info.file_size != clip["media_bytes"]:
            raise ValueError("Changed source media size")
        with archive.open(info) as source, media.open("xb") as destination:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                check(reserve=len(block))
                destination.write(block)
    if digest(media) != clip["media_sha256"]:
        raise ValueError("Changed source media bytes")
    expected_frames = expected_clock["decoded_frames"]
    check(decoded=expected_frames)
    publish(
        directory / "preparation-start.json",
        {"frames": expected_frames, "key": clip["key"]},
    )

    def preparation(index):
        if index >= expected_frames:
            raise ValueError("Source exceeds original frame denominator")
        check(decoded=index + 1, full=index % 25 == 0)

    ledger, times, video, scan = clock_and_scan(media, preparation)
    if (
        video["frame_count"] != expected_frames
        or video["duration_s"] > 120
        or expected_clock["media_sha256"] != video["sha256"]
        or expected_clock["shape"] != [video["source_width"], video["source_height"]]
        or abs(
            float(Fraction(*ledger["rows"][0]["relative_time"]))
            - expected_clock["first_pts"]
        )
        > 0.00002
        or abs(
            float(Fraction(*ledger["rows"][-1]["relative_time"]))
            - expected_clock["last_pts"]
        )
        > 0.00002
    ):
        raise ValueError("Native source clock contradicts original metadata")
    video["path"] = media.name
    publish(directory / "native-clock.json", ledger)
    publish(directory / "video.json", video)
    publish(directory / "camera.json", scan)
    data = directory / "data"
    (data / video["id"]).mkdir(parents=True)
    publish(data / video["id"] / "timestamps.json", times)
    check(decoded=2 * expected_frames, observed=expected_frames)
    publish(
        directory / "perception-start.json",
        {"frames": expected_frames, "key": clip["key"], "passes": 1},
    )

    def cache_progress(count):
        check(decoded=expected_frames + count, full=count % 25 == 0)

    with decode_cache(video, directory, times, cache_progress) as count:
        if count != expected_frames:
            raise ValueError("Cached native frame denominator changed")

        def report(value):
            check(decoded=2 * expected_frames, observed=expected_frames, full=False)
            progress(value)

        with required_cuda():
            track_players(
                video,
                directory,
                data,
                empty_annotations("singles"),
                0,
                expected_frames,
                1,
                report,
                directory / "players.json",
                player_model="small",
                auto_calibrate=True,
                camera_scan=scan,
            )
    result = read_json(directory / "players.json")
    if not result["device"].startswith("cuda"):
        raise ValueError("CPU fallback is forbidden")
    actor.validate_clocks(video, ledger, times)
    coverage = producer.validate_pose(result, video, times, scan, ledger)
    diagnostics = [actor.diagnose(ref, result, video) for ref in refs]
    features = [
        feature_row(clip, ref, diagnostic, result, video, ledger)
        for ref, diagnostic in zip(refs, diagnostics, strict=True)
    ]
    publish(directory / "diagnostics.json", diagnostics)
    publish(directory / "features.json", features)
    receipt = {
        "key": clip["key"],
        "frames": count,
        "references": len(refs),
        "weak_pairs": sum(r["available"] for r in features),
        "coverage": coverage,
        "decoded_frame_visits": 2 * count,
        "model_frame_observations": count,
        "artifacts": producer.inventory(directory),
    }
    publish(directory / "receipt.json", receipt)
    check(decoded=2 * count, observed=count)
    return features, receipt


def comparison(rows, result, predictions, old_rows, control, control_predictions):
    data = learning.arrays(rows, "static")
    old = learning.arrays(old_rows, "static")
    control_metrics = learning.evaluate(old, control_predictions, old["validation"])
    if control_metrics != control["validation"]:
        raise ValueError("Sealed control validation does not reproduce")
    groups = {
        "all": np.ones(len(rows), bool),
        "train": data["train"],
        "validation": data["validation"],
    }
    for field, prefix in (("context", "capture:"), ("clip_key", "source:")):
        groups.update(
            {
                prefix + key: np.asarray([r[field] == key for r in rows])
                for key in sorted({r[field] for r in rows})
            }
        )
    return {
        "references": len(rows),
        "training_ready": False,
        "model_installed_in_app": False,
        "independent_accuracy_established": False,
        "complete_rally_references": {"accepted": 0, "required": 2},
        "candidate": {
            **result,
            "groups": {
                key: learning.evaluate(data, predictions, mask)
                for key, mask in groups.items()
            },
        },
        "sealed_control": {
            "selection": control["selection"],
            "validation": control_metrics,
            "refitted": False,
            "reselected": False,
        },
        "development_preference": "candidate"
        if learning.selection_key(result["validation"], 0)[:2]
        > learning.selection_key(control_metrics, 0)[:2]
        else "sealed_control",
        "availability": {
            fold: {
                "rows": sum(r["fold"] == fold for r in rows),
                "weak_pairs": sum(r["available"] for r in rows if r["fold"] == fold),
                "unavailable": sum(
                    not r["available"] for r in rows if r["fold"] == fold
                ),
            }
            for fold in producer.FOLDS
        },
    }


def run(prospective_path, prospective_sha256, output):
    plan = prospective(prospective_path, prospective_sha256, True)
    output = private_output(plan, output)
    if str(output) != plan["output"]:
        raise ValueError("Run output differs from the published prospective claim")
    learning.validate_workspace(plan)
    _, data, _ = producer.configure_workspace(plan["workspace"])
    import psutil
    import torch

    from .jobs import run_local_job
    from .storage import Store

    if not torch.cuda.is_available():
        raise ValueError("Original scaling operation requires CUDA; no CPU fallback")
    if output.exists():
        raise FileExistsError("Preserve existing scaling output")
    claim = execution_claim(plan)
    output.mkdir(exist_ok=False)
    publish(
        output / "dispatch.json",
        {"prospective_sha256": prospective_sha256, "started_at": time.time()},
    )
    store, before = Store(data), producer.annotation_snapshot(data)
    receipts, counts = [], {"decoded": 0, "observed": 0, "real_fits": 0}

    def task(job_id, progress):
        process = psutil.Process()
        publish(
            output / "process.json",
            {
                "job_id": job_id,
                "pid": process.pid,
                "created_at": process.create_time(),
                "cwd": str(Path.cwd()),
                "command": process.cmdline(),
                "prospective_sha256": prospective_sha256,
            },
        )
        _, _, old_rows = original_inputs(plan)
        paths = input_sources(plan)
        clips, groups = read_json(paths["clips"]), read_json(paths["groups"])
        folds, contexts = producer.capture_folds(clips, groups)
        cohort = select_cohort(
            clips, folds, contexts, read_json(Path(plan["prepared"]) / "freeze.json")
        )
        if cohort != plan["cohort"]:
            raise ValueError("Changed prospective source membership")
        cohort["reference_rows"] = canonical_reference_rows(
            paths["archive"], clips, folds, cohort
        )
        publish(output / "cohort.json", cohort)
        clocks = clock_index(plan["clock_ledger"], cohort["new_keys"])
        if (
            sum(c["decoded_frames"] for c in clocks.values())
            != PROTOCOL["expected"]["new_frames"]
        ):
            raise ValueError("Changed new source-frame denominator")
        new_rows = []
        by_key = {c["key"]: c for c in cohort["clips"]}
        for number, key in enumerate(cohort["new_keys"]):
            prospective(prospective_path, prospective_sha256, True)

            def check(reserve=0, decoded=0, observed=0, full=True):
                check_deadline(
                    plan["granted_at"], plan["committed_at"], plan["deadline"]
                )
                if (
                    counts["decoded"] + decoded
                    > PROTOCOL["limits"]["decoded_frame_visits"]
                    or counts["observed"] + observed
                    > PROTOCOL["limits"]["model_frame_observations"]
                ):
                    raise ValueError("Fixed native execution budget exceeded")
                if full:
                    budget(
                        plan,
                        output,
                        reserve,
                        counts["decoded"] + decoded,
                        counts["observed"] + observed,
                    )

            features, receipt = new_clip(
                plan,
                by_key[key],
                [r for r in cohort["reference_rows"] if r["clip_key"] == key],
                clocks[key],
                output / f"clip-{number:03d}",
                check,
                lambda value: progress(
                    0.9 * (number + value) / len(cohort["new_keys"])
                ),
            )
            new_rows.extend(features)
            receipts.append(receipt)
            counts["decoded"] += receipt["decoded_frame_visits"]
            counts["observed"] += receipt["model_frame_observations"]
            publish(
                output / f"progress-{number:03d}.json",
                {"completed_clips": len(receipts), **counts},
            )
        if counts["observed"] != PROTOCOL["expected"]["new_frames"]:
            raise ValueError("Incomplete native observation denominator")
        rows = combined_features(cohort, old_rows, new_rows)
        publish(output / "features.json", rows)
        # The cohort-bound claim consumes the one fit even if it fails partially.
        publish(
            output / "fit-start.json",
            {"real_fits": 1, "training": PROTOCOL["training"]},
        )
        counts["real_fits"] = 1

        def report(epoch, checkpoint):
            check_deadline(plan["granted_at"], plan["committed_at"], plan["deadline"])
            budget(plan, output, 8 * 1024 * 1024, counts["decoded"], counts["observed"])
            if checkpoint:
                prospective(prospective_path, prospective_sha256, True)
            progress(0.9 + 0.1 * epoch / PROTOCOL["training"]["epochs"])

        result = learning.fit(
            learning.arrays(rows, "static"), output / "candidate", report
        )
        predictions = read_json(output / "candidate/predictions.json")
        control = Path(plan["control"]) / "static"
        publish(
            output / "report.json",
            comparison(
                rows,
                result,
                predictions,
                old_rows,
                read_json(control / "result.json"),
                read_json(control / "predictions.json"),
            ),
        )
        original_inputs(plan)
        input_sources(plan)
        prospective(prospective_path, prospective_sha256, True)
        if producer.annotation_snapshot(data) != before:
            raise ValueError("Original application truth changed")
        return {
            "references": len(rows),
            "new_clips": len(receipts),
            **counts,
            "prospective_sha256": prospective_sha256,
        }

    try:
        summary = run_local_job(store, "feature-preparation", None, task)
        job = store.job(read_json(output / "process.json")["job_id"])
        if job["status"] != "completed" or job["summary"] != summary:
            raise ValueError(
                "Original scaling requires durable shared Store completion"
            )
        completion = {
            "summary": summary,
            "prospective_sha256": prospective_sha256,
            "job_id": job["id"],
            "shared_data": str(data),
            "execution_claim": str(claim),
            "finished_at": time.time(),
            "original_annotations_sha256": before,
            "receipts": receipts,
            "artifacts": producer.inventory(output),
            "training_ready": False,
            "model_installed_in_app": False,
            "test_opened": False,
        }
        check_deadline(plan["granted_at"], plan["committed_at"], plan["deadline"])
        budget(
            plan,
            output,
            len(producer.encoded(completion)),
            counts["decoded"],
            counts["observed"],
        )
        publish(output / "completion.json", completion)
        return summary
    except BaseException as error:
        publish(
            output / "failure.json",
            {
                "error_type": type(error).__name__,
                "message": str(error),
                "at": time.time(),
                "completed_clips": len(receipts),
                "reserved_original_run_consumed": True,
                **counts,
            },
        )
        raise


def verify(prospective_path, prospective_sha256, output):
    """Reconstruct new inputs and checkpoint predictions; no decode or fitting."""
    plan = prospective(prospective_path, prospective_sha256, False)
    output = private_output(plan, output)
    if str(output) != plan["output"]:
        raise ValueError("Verification output differs from original claim")
    producer.configure_workspace(plan["workspace"])
    learning.validate_workspace(plan)
    complete = read_json(output / "completion.json")
    if (
        complete["prospective_sha256"] != prospective_sha256
        or complete["execution_claim"] != str(execution_claim(plan))
        or complete["shared_data"] != str(Path(plan["workspace"]) / "data/processed")
        or not plan["committed_at"] <= complete["finished_at"] < plan["deadline"]
        or complete["training_ready"]
        or complete["test_opened"]
        or complete["model_installed_in_app"]
    ):
        raise ValueError("Changed original execution binding/window or truth flags")
    actor.verify_inventory(
        output,
        complete["artifacts"] | {"completion.json": digest(output / "completion.json")},
    )
    _, _, old_rows = original_inputs(plan)
    sources = input_sources(plan)
    clips, groups = read_json(sources["clips"]), read_json(sources["groups"])
    folds, contexts = producer.capture_folds(clips, groups)
    cohort = select_cohort(
        clips, folds, contexts, read_json(Path(plan["prepared"]) / "freeze.json")
    )
    if cohort != plan["cohort"]:
        raise ValueError("Changed original cohort")
    cohort["reference_rows"] = canonical_reference_rows(
        sources["archive"], clips, folds, cohort
    )
    if cohort != read_json(output / "cohort.json"):
        raise ValueError("Changed canonical ordered rows/coordinates")
    clocks = clock_index(plan["clock_ledger"], cohort["new_keys"])
    by_key, new_rows, receipts = {c["key"]: c for c in cohort["clips"]}, [], []
    for number, key in enumerate(cohort["new_keys"]):
        directory = output / f"clip-{number:03d}"
        receipt = read_json(directory / "receipt.json")
        actor.verify_inventory(
            directory,
            receipt["artifacts"] | {"receipt.json": digest(directory / "receipt.json")},
        )
        video, ledger, scan, result = (
            read_json(directory / name)
            for name in (
                "video.json",
                "native-clock.json",
                "camera.json",
                "players.json",
            )
        )
        times = read_json(directory / "data" / video["id"] / "timestamps.json")
        clip = by_key[key]
        if (
            digest(directory / "source.mp4") != clip["media_sha256"]
            or video["sha256"] != clip["media_sha256"]
            or video["frame_count"] != clocks[key]["decoded_frames"]
            or video["path"] != "source.mp4"
            or not result["device"].startswith("cuda")
            or read_json(directory / "preparation-start.json")
            != {"frames": video["frame_count"], "key": key}
            or read_json(directory / "perception-start.json")
            != {"frames": video["frame_count"], "key": key, "passes": 1}
        ):
            raise ValueError("Changed original new-clip source/pass denominator")
        actor.validate_clocks(video, ledger, times)
        coverage = producer.validate_pose(result, video, times, scan, ledger)
        refs = [r for r in cohort["reference_rows"] if r["clip_key"] == key]
        diagnostics = [actor.diagnose(ref, result, video) for ref in refs]
        features = [
            feature_row(clip, ref, diagnostic, result, video, ledger)
            for ref, diagnostic in zip(refs, diagnostics, strict=True)
        ]
        expected = {
            "key": key,
            "frames": video["frame_count"],
            "references": len(refs),
            "weak_pairs": sum(r["available"] for r in features),
            "coverage": coverage,
            "decoded_frame_visits": 2 * video["frame_count"],
            "model_frame_observations": video["frame_count"],
            "artifacts": receipt["artifacts"],
        }
        if (
            receipt != expected
            or diagnostics != read_json(directory / "diagnostics.json")
            or features != read_json(directory / "features.json")
        ):
            raise ValueError(
                "New native correspondence/features/receipt do not reproduce"
            )
        new_rows.extend(features)
        receipts.append(receipt)
    rows = combined_features(cohort, old_rows, new_rows)
    if rows != read_json(output / "features.json") or receipts != complete["receipts"]:
        raise ValueError("Full feature denominator/reuse/receipt changed")
    # Verify the candidate's entire schedule and the sealed original control.
    # Control selection is checked against its original saved result, never changed.
    result, predictions = learning.verify_arm(
        learning.arrays(rows, "static"), output / "candidate"
    )
    control, control_predictions = learning.verify_arm(
        learning.arrays(old_rows, "static"), Path(plan["control"]) / "static"
    )
    report = comparison(
        rows, result, predictions, old_rows, control, control_predictions
    )
    if report != read_json(output / "report.json"):
        raise ValueError("Full source/capture/class comparison does not reproduce")
    decoded = sum(r["decoded_frame_visits"] for r in receipts)
    observed = sum(r["model_frame_observations"] for r in receipts)
    expected = {
        "references": len(rows),
        "new_clips": len(receipts),
        "decoded": decoded,
        "observed": observed,
        "real_fits": 1,
        "prospective_sha256": prospective_sha256,
    }
    job = store_job(complete["shared_data"], complete["job_id"])
    if (
        complete["summary"] != expected
        or job.get("status") != "completed"
        or job.get("summary") != expected
        or observed != PROTOCOL["expected"]["new_frames"]
        or read_json(output / "fit-start.json")
        != {"real_fits": 1, "training": PROTOCOL["training"]}
        or producer.annotation_snapshot(complete["shared_data"])
        != complete["original_annotations_sha256"]
    ):
        raise ValueError("Durable original Store/fit/annotation denominator changed")
    budget(plan, output, decoded=decoded, observed=observed)
    return {
        "verified_references": len(rows),
        "new_native_clips": len(receipts),
        "new_native_frames": observed,
        "real_fits": 1,
        "independent_accuracy_established": False,
        "development_preference": report["development_preference"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("freeze")
    for name in (
        "workspace",
        "prepared",
        "native",
        "actor-prospective",
        "audit",
        "control",
        "control-prospective",
        "clock-ledger",
        "protocol",
        "output",
        "run-output",
    ):
        command.add_argument("--" + name, type=Path, required=True)
    for name in ("granted-at", "committed-at", "deadline"):
        command.add_argument("--" + name, type=float, required=True)
    for name in ("run", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--prospective", type=Path, required=True)
        command.add_argument("--prospective-sha256", required=True)
        command.add_argument("--output", type=Path, required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    print(json.dumps(globals()[command](**args), indent=2))
