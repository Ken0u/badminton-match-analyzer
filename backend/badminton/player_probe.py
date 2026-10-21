"""Bounded development inference with immutable inputs and shared admission.

This records model observations, not labelled accuracy or persistent identity.
"""

import hashlib
import importlib.metadata
import json
import math
import os
import sqlite3
import sys
import time
from pathlib import Path

import psutil
from PIL import Image, ImageDraw

from .calibration_context import effective_annotations
from .jobs import JobCancelled, run_local_job
from .scene_review import reviewed_run
from .storage import Store
from .video import iter_frames, resolve_source, validate_range, write_json


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _document_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def _snapshot(root, data, weights, manifest):
    """Read only the named development source, never enumerate other corpora."""
    database = data / "catalog.sqlite3"
    if not database.is_file():
        raise ValueError("The existing shared processing Store is required")
    with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as db:
        row = db.execute(
            "SELECT document FROM videos WHERE id=?", (manifest["video_id"],)
        ).fetchone()
        history = db.execute(
            "SELECT revision,document FROM annotations WHERE video_id=? ORDER BY revision",
            (manifest["video_id"],),
        ).fetchall()
    if row is None or not history:
        raise ValueError("Development source or annotations are unavailable")
    video = json.loads(row[0])
    if video["sha256"] != manifest["source_sha256"]:
        raise ValueError("Source does not match the frozen manifest")
    source = resolve_source(video, root)
    clock = data / video["id"] / "timestamps.json"
    if not clock.resolve().is_relative_to(data):
        raise ValueError("Source clock escapes the shared data directory")
    latest = history[-1]
    annotations_hash = hashlib.sha256(latest[1].encode()).hexdigest()
    if (
        latest[0] != manifest["annotation_revision"]
        or annotations_hash != manifest["annotation_sha256"]
    ):
        raise ValueError("Annotations do not match the frozen revision/hash")
    if digest(clock) != manifest["clock_sha256"]:
        raise ValueError("Source clock does not match the frozen hash")
    times = json.loads(clock.read_text(encoding="utf-8"))
    start, end = manifest["start_frame"], manifest["end_frame"]
    validate_range(video, times, start, end)
    if len(times) != video["frame_count"]:
        raise ValueError("Incomplete imported source clock")
    checkpoints = {}
    for model in manifest["variants"]:
        path = (weights / model["name"]).resolve()
        if not path.is_relative_to(weights) or digest(path) != model["sha256"]:
            raise ValueError("Checkpoint does not match the frozen model hash")
        checkpoints[model["variant"]] = digest(path)
    runs = data / video["id"] / "runs"
    original_predictions = {
        path.relative_to(data).as_posix(): digest(path)
        for path in sorted(runs.rglob("*"))
        if path.is_file()
    }
    snapshot = {
        "source_sha256": digest(source),
        "clock_sha256": digest(clock),
        "video_document_sha256": hashlib.sha256(row[0].encode()).hexdigest(),
        "annotation_history_sha256": _document_hash(history),
        "annotation_revision": latest[0],
        "annotation_sha256": annotations_hash,
        "model_sha256": checkpoints,
        "original_predictions": original_predictions,
    }
    if snapshot["source_sha256"] != manifest["source_sha256"]:
        raise ValueError("Source bytes do not match the frozen hash")
    return video, times, snapshot


def _validate_manifest(manifest):
    start, end = manifest["start_frame"], manifest["end_frame"]
    if (
        manifest["schema_version"] != 1
        or type(start) is not int
        or type(end) is not int
        or not 0 <= start < end
        or (end - start) * len(manifest["variants"]) > 100
        or [m["variant"] for m in manifest["variants"]] != ["nano", "small"]
        or not 0 < manifest["max_runtime_seconds"] <= 900
        or not 0 < manifest["max_output_bytes"] <= 64 * 1024**2
        or not manifest["sample_frames"]
        or len(manifest["sample_frames"]) > 5
        or len(set(manifest["sample_frames"])) != len(manifest["sample_frames"])
        or any(
            type(f) is not int or not start <= f < end
            for f in manifest["sample_frames"]
        )
    ):
        raise ValueError("Invalid or unbounded development probe manifest")


def _cpu_only():
    import torch
    import torchvision  # noqa: F401

    if torch.cuda.is_available():
        raise ValueError("This grant permits CPU inference only")


def _validate_result(result, video, times, manifest, model, annotations):
    start, end = manifest["start_frame"], manifest["end_frame"]
    if (
        result["video_id"] != video["id"]
        or result["video_sha256"] != video["sha256"]
        or result["checkpoint_sha256"] != model["sha256"]
        or result["model_variant"] != model["variant"]
        or result["device"] != "cpu"
        or result["stage"] != "players"
        or result["auto_calibrate"] is not False
        or result["start_frame"] != start
        or result["end_frame"] != end
        or result["stride"] != 1
        or result["annotation_revision"] != manifest["annotation_revision"]
        or result["processed_frames"] != end - start
        or [row["frame"] for row in result["frames"]] != list(range(start, end))
    ):
        raise ValueError("Incomplete or conflicting player prediction provenance")
    expected = reviewed_run(result, annotations)
    for key in ("cut_frames", "camera_ranges", "preceding_reviewed_cut_frame"):
        if result.get(key) != expected.get(key):
            raise ValueError("Prediction lost reviewed camera context")
    calibrations = effective_annotations(annotations, expected)["calibrations"]
    segment, last_cut = start, expected.get("preceding_reviewed_cut_frame")
    counts, ids, unassigned, points, excluded = [], set(), 0, 0, 0
    for row, expected_row in zip(result["frames"], expected["frames"], strict=True):
        index = row["frame"]
        if index in expected["cut_frames"]:
            last_cut = index
            if index > start:
                segment = index
        valid_court = any(
            c["start_frame"] <= index < c["end_frame"]
            and (last_cut is None or c["start_frame"] >= last_cut)
            for c in calibrations
        )
        if (
            row["camera_segment_start_frame"] != segment
            or row["calibration_valid"] != valid_court
            or any(
                row.get(key) != expected_row.get(key)
                for key in ("scene", "reviewed_scene_range_id")
            )
        ):
            raise ValueError("Prediction lost scene, camera or calibration context")
        if not math.isfinite(row["time_s"]) or row["time_s"] != times[row["frame"]]:
            raise ValueError("Prediction does not preserve native source time")
        excluded += row.get("scene") in {"replay", "non_play", "unknown"}
        counts.append(len(row["players"]))
        for player in row["players"] + row.get("motion_players", []):
            box, confidence = player["box"], player["confidence"]
            if (
                len(box) != 4
                or not all(math.isfinite(v) for v in [*box, confidence])
                or not 0 <= box[0] <= box[2] <= video["width"]
                or not 0 <= box[1] <= box[3] <= video["height"]
                or not 0 <= confidence <= 1
            ):
                raise ValueError("Invalid player coordinates or confidence")
            for point in player["keypoints"]:
                if (
                    len(point) != 3
                    or not all(math.isfinite(v) for v in point)
                    or not 0 <= point[2] <= 1
                ):
                    raise ValueError("Invalid player keypoint")
        for player in row["players"]:
            unassigned += player["track_id"] is None
            if player["track_id"] is not None:
                ids.add(player["track_id"])
            points += sum(p[2] >= 0.25 for p in player["keypoints"])
    return {
        "processed_frames": len(counts),
        "player_observations": sum(counts),
        "frames_without_detections": counts.count(0),
        "frames_with_expected_detection_count": counts.count(
            2 if video["mode"] == "singles" else 4
        ),
        "detection_count_range": [min(counts), max(counts)],
        "provisional_track_ids": sorted(ids),
        "observations_without_track_id": unassigned,
        "keypoints_confidence_at_least_025": points,
        "scene_excluded_frames": excluded,
        "cut_frames": result["cut_frames"],
        "camera_ranges": result["camera_ranges"],
        "elapsed_s": result["elapsed_s"],
        "inference_fps": result["inference_fps"],
    }


def _overlays(video, root, times, result, samples, directory, progress):
    rows = {r["frame"]: r for r in result["frames"]}
    panels = []
    for index in samples:
        progress(1)
        frames = iter_frames(video, root, times, index, index + 1)
        try:
            image = next(frames)[2].to_image().convert("RGB")
        finally:
            frames.close()
        draw = ImageDraw.Draw(image)
        row = rows[index]
        for player in row["players"]:
            color = "yellow" if player["track_id"] is None else "lime"
            draw.rectangle(player["box"], outline=color, width=3)
            draw.text(
                tuple(player["box"][:2]),
                f"track {player['track_id']} (unverified)",
                fill=color,
            )
            for x, y, confidence in player["keypoints"]:
                if confidence >= 0.25:
                    draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill="cyan")
        draw.rectangle((0, 0, image.width, 30), fill="black")
        draw.text(
            (8, 8),
            f"{result['model_variant']} frame {index} PTS {times[index]:.3f}s scene {row.get('scene', 'unreviewed')} - model observations",
            fill="white",
        )
        image.save(directory / f"frame-{index}.jpg", quality=90)
        image.thumbnail((640, 360))
        panels.append(image)
    sheet = Image.new("RGB", (640, 360 * len(panels)))
    for i, panel in enumerate(panels):
        sheet.paste(panel, (0, i * 360))
    sheet.save(directory / "contact-sheet.jpg", quality=90)


def run_probe(
    root,
    data,
    weights,
    manifest,
    output,
    *,
    tracker=None,
    cpu_check=None,
    code_sha=None,
):
    root, data, weights, output = (
        Path(p).resolve() for p in (root, data, weights, output)
    )
    _validate_manifest(manifest)
    if data != root / "data" / "processed" or weights != root / "models" / "weights":
        raise ValueError("Use the real root's shared Store and installed weights")
    if not output.is_relative_to(root / ".cache") or output.exists():
        raise ValueError("Output must be a new directory under the root .cache")
    video, times, before = _snapshot(root, data, weights, manifest)
    (cpu_check or _cpu_only)()
    if tracker is None:
        from . import config
        from .tracking import track_players

        if (config.ROOT, config.DATA.resolve(), config.WEIGHTS.resolve()) != (
            root,
            data,
            weights,
        ):
            raise ValueError("Pin root/data/weights before importing the application")
        tracker = track_players
    store = Store(data)
    output.mkdir(parents=True)
    write_json(output / "inputs-before.json", before)
    receipt = {
        "schema_version": 1,
        "status": "running",
        "code_sha": code_sha,
        "manifest_sha256": _document_hash(manifest),
        "process": {
            "pid": os.getpid(),
            "created_at": psutil.Process().create_time(),
            "cwd": str(Path.cwd()),
            "command": sys.argv,
        },
        "shared_store": str(store.db_path),
        "output": str(output),
        "application_source_hashes": {
            p.relative_to(Path(__file__).parent).as_posix(): digest(p)
            for p in sorted(Path(__file__).parent.rglob("*.py"))
        },
        "runtime": {
            name: importlib.metadata.version(name)
            for name in ("torch", "torchvision", "ultralytics", "av")
            if importlib.util.find_spec(name) is not None
        },
        "limitations": [
            "Reused singles development excerpt, not an independent labelled evaluation",
            "Tracker IDs and observed keypoints are model hypotheses, not verified players or accuracy",
            "No doubles, shuttle, contact, shot-family, serve or rally-end inference exercised",
        ],
        "variants": {},
    }
    write_json(output / "receipt.json", receipt)
    began = time.monotonic()
    after = None

    def task(job_id, update):
        nonlocal after
        receipt["job_id"] = job_id
        write_json(output / "receipt.json", receipt)

        def progress(value):
            if time.monotonic() - began > manifest["max_runtime_seconds"]:
                raise JobCancelled(
                    "Frozen probe runtime exhausted; preserve partial artifacts"
                )
            if store.job(job_id).get("cancel_requested"):
                raise JobCancelled("Probe cancellation requested")
            size = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
            if size > manifest["max_output_bytes"]:
                raise JobCancelled("Frozen probe output budget exhausted")
            update(value)

        annotations = store.annotations(video["id"], manifest["annotation_revision"])
        for position, model in enumerate(manifest["variants"]):
            # Recheck every frozen input between models, before more inference.
            if _snapshot(root, data, weights, manifest)[2] != before:
                raise ValueError("Inputs changed between model variants")
            directory = output / model["variant"]
            directory.mkdir()
            predictions = directory / "predictions.json"
            summary = tracker(
                video,
                root,
                data,
                annotations,
                manifest["start_frame"],
                manifest["end_frame"],
                1,
                lambda v: progress((position + v) / 2),
                predictions,
                player_model=model["variant"],
                auto_calibrate=False,
            )
            result = json.loads(predictions.read_text(encoding="utf-8"))
            if any(summary[k] != v for k, v in result.items() if k != "frames"):
                raise ValueError("Prediction summary conflicts with saved observations")
            receipt["variants"][model["variant"]] = _validate_result(
                result, video, times, manifest, model, annotations
            )
            _overlays(
                video,
                root,
                times,
                result,
                manifest["sample_frames"],
                directory,
                lambda _value: progress((position + 1) / 2),
            )
            write_json(output / "receipt.json", receipt)
        # Verify the final variant before releasing shared admission. A late
        # change must fail the Store job as well as this probe's receipt.
        after = _snapshot(root, data, weights, manifest)[2]
        if after != before:
            raise ValueError(
                "Source, annotations, weights or original predictions changed"
            )
        progress(1)
        return {"output": str(output), "variants": receipt["variants"]}

    try:
        run_local_job(store, "player_runtime_probe", video["id"], task)
        receipt.update(status="completed", inputs_preserved=True)
    except BaseException as exc:
        receipt.update(
            status="interrupted"
            if isinstance(exc, JobCancelled | KeyboardInterrupt)
            else "failed",
            error=str(exc),
        )
        raise
    finally:
        try:
            # Successful after-evidence belongs to the admitted interval. Do
            # not race a subsequent job after our Store job has completed.
            if after is None:
                after = _snapshot(root, data, weights, manifest)[2]
            receipt["inputs_preserved"] = after == before
            write_json(output / "inputs-after.json", after)
        except Exception as exc:
            receipt.update(inputs_preserved=False, input_verification_error=str(exc))
        if "job_id" in receipt:
            receipt["shared_job"] = store.job(receipt["job_id"])
        receipt["wall_seconds"] = round(time.monotonic() - began, 3)
        receipt["artifacts"] = {
            p.relative_to(output).as_posix(): digest(p)
            for p in sorted(output.rglob("*"))
            if p.is_file() and p.name != "receipt.json"
        }
        write_json(output / "receipt.json", receipt)
    if not receipt["inputs_preserved"]:
        raise ValueError("Final input preservation check failed")
    return receipt
