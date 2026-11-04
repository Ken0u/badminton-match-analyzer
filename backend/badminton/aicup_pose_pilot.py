"""Fixed development-only native pose inputs; no fitting or application truth.

Original CSV rows supply weak references. Test CSV/media are never opened.
Preparation and observation are separate, prospectively frozen operations.
"""

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import sqlite3
import sys
import time
import zipfile
from collections import Counter
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

from .aicup_data import normalize_clip
from .datasets import read_rows

FAMILIES = ("clear", "lift", "net", "drop", "smash", "drive")
SIDES = ("forehand", "backhand")
FOLDS = ("train", "validation")
PROTOCOL = {
    "schema_version": 1,
    "name": "aicup-pose-pilot-v1",
    "families": list(FAMILIES),
    "sides": list(SIDES),
    "folds": list(FOLDS),
    "contacts_per_cell": 2,
    "selection_key": "SHA256 UTF-8 aicup-pose-pilot-v1|fold|record-id, ascending",
    "sources": {
        "archive": "1f14bb969a2a23fef58de76b22bd418d5848dc4f9f8ae6a364d365c1b4c9a07b",
        "clips": "ab1b906c6d5032d666ae02a66dd2049fc8ee1b297a979bf16bbca8cf7904e703",
        "records": "1362ae1cd88e3b975fff0b3bfa1144c19c7e64b8ace1d188081802893ef95d44",
        "groups": "7e97f6101cb7339a339bc0f8b0ab4e6142c0e0157101217fbac93a0bf933afc5",
        "model": "1060bda4a27012060eca246f9b2adeea22eabb045a1e58f8d229be29b7ebc2ba",
    },
    "limits": {
        "runtime_seconds": 28800,
        "output_bytes": 4294967296,
        "media_bytes": 1073741824,
        "native_frames": 32000,
        "selected_rows": 48,
        "selected_clips": 48,
        "native_passes_per_clip": 1,
        "fits": 0,
        "external_image_bytes": 0,
    },
    "pose": {"variant": "small", "stride": 1, "auto_calibrate": True},
    "support_confidence": 0.25,
    "contact_interval": "Published H>0 is ambiguous inclusive [H-1,H]; H0 is censored",
    "processing_mode": "singles placeholder; expected_players and roster are configuration, not truth",
    "scene_truth": "unknown; cuts and dataset membership do not certify live play",
    "source_mode_truth": "unknown",
    "actor_truth": "unresolved; published A/B court end is not persistent identity",
    "complete_rally_references": {"accepted": 0, "required": 2},
    "model_installed_in_app": False,
    "training_ready": False,
}


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("Nonfinite JSON value")

    return json.loads(
        Path(path).read_bytes(), object_pairs_hook=unique, parse_constant=invalid
    )


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def publish(path, value):
    path = Path(path)
    with path.open("xb") as stream:
        stream.write(encoded(value))


def inside(root, name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("Expected a relative POSIX artifact path")
    parts = name.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError("Artifact path escapes its root")
    path = (Path(root) / name).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("Artifact path escapes its root")
    return path


def check_deadline(granted_at, deadline):
    now = time.time()
    if (
        not all(
            type(v) in (int, float) and math.isfinite(v) for v in (granted_at, deadline)
        )
        or not granted_at <= now < deadline
        or deadline - granted_at > PROTOCOL["limits"]["runtime_seconds"]
    ):
        raise ValueError("Expired or unbounded original scientific deadline")


def check_budget(directory, *, frames=0, media_bytes=0, reserve=0):
    total = sum(p.stat().st_size for p in Path(directory).rglob("*") if p.is_file())
    limits = PROTOCOL["limits"]
    if (
        any(type(v) is not int or v < 0 for v in (frames, media_bytes, reserve))
        or frames > limits["native_frames"]
        or media_bytes > limits["media_bytes"]
        or total + reserve > limits["output_bytes"]
    ):
        raise ValueError("Fixed pilot exceeds its budget; preserve partial outputs")
    return total


def code_seals():
    folder = Path(__file__).parent
    # Includes transitive camera, orientation, court, tracking and Store sources.
    result = {p.name: digest(p) for p in sorted(folder.glob("*.py"))} | {
        p.name: digest(p)
        for p in (folder / "model_manifest.json", folder / "aicup2023_manifest.json")
    }
    for name in (
        "scripts/prepare_aicup_pose_pilot.py",
        "data/manifests/aicup_pose_pilot_protocol_v1.json",
    ):
        result[name] = digest(folder.parents[1] / name)
    return result


def runtime():
    import torch

    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "executable": sys.executable,
        "cuda_version": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device": torch.cuda.get_device_name(0)
        if torch.cuda.is_available()
        else None,
        "packages": {
            name: importlib.metadata.version(name)
            for name in (
                "av",
                "numpy",
                "torch",
                "torchvision",
                "ultralytics",
                "opencv-python",
                "scenedetect",
                "psutil",
            )
        },
    }


def clip_key(clip):
    return f"{clip['source_partition']}:{clip['source_clip_id']}"


def capture_folds(clips, groups):
    folds, contexts = {}, {}
    identifiers = set()
    for group in groups["source_groups"]:
        if group["id"] in identifiers or group["fold"] not in (*FOLDS, "test"):
            raise ValueError("Invalid capture-group identity or fold")
        identifiers.add(group["id"])
        for key in group["members"]:
            if key in folds:
                raise ValueError("Source appears in multiple capture groups")
            folds[key], contexts[key] = group["fold"], group["id"]
    keys = [clip_key(c) for c in clips]
    if len(set(keys)) != len(keys) or set(keys) != set(folds):
        raise ValueError("Capture groups must cover each source clip exactly once")
    seen = {}
    for clip in clips:
        fold = folds[clip_key(clip)]
        if seen.setdefault(clip["media_sha256"], fold) != fold:
            raise ValueError("Identical media crosses source folds")
    return folds, contexts


def canonical_rows(archive, clips, folds):
    """Fence held-out members before opening CSV; derive targets from source."""
    rows = []
    with zipfile.ZipFile(archive) as source:
        names = source.namelist()
        if len(set(names)) != len(names):
            raise ValueError("Duplicate original archive members")
        for clip in clips:
            key = clip_key(clip)
            if folds[key] not in FOLDS:
                continue
            partition, identity = clip["source_partition"], clip["source_clip_id"]
            if partition not in ("train", "val") or not re.fullmatch(
                r"\d{5}", identity
            ):
                raise ValueError("Invalid published development identity")
            prefix = f"part1/{partition}/{identity}/{identity}"
            if clip["media_path"] != prefix + ".mp4":
                raise ValueError("Noncanonical source media member")
            if "label_path" not in clip:
                continue
            if clip["label_path"] != prefix + "_S2.csv":
                raise ValueError("Noncanonical source label member")
            info = source.getinfo(clip["label_path"])
            if info.file_size > 1024 * 1024:
                raise ValueError("Original CSV exceeds canonical bound")
            raw = source.read(info)
            if hashlib.sha256(raw).hexdigest() != clip["label_sha256"]:
                raise ValueError("Original CSV binding changed")
            for row in normalize_clip(read_rows(raw), identity, partition):
                row.update(fold=folds[key], clip_key=key)
                rows.append(row)
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate canonical record identity")
    return rows


def select_cohort(rows):
    """Fixed rule: input eligibility only, no pose or model-result selection."""
    if any(r["fold"] not in FOLDS for r in rows):
        raise ValueError("Held-out rows cannot enter development selection")
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate source record identity")
    cells, selected = [], []
    for fold in FOLDS:
        for family in FAMILIES:
            for side in SIDES:
                pool = [
                    r
                    for r in rows
                    if r["fold"] == fold
                    and r["contact_label_eligible"]
                    and r["family"] == family
                    and r["side"] == side
                ]
                ordered = sorted(
                    pool,
                    key=lambda r: hashlib.sha256(
                        f"aicup-pose-pilot-v1|{fold}|{r['id']}".encode("utf-8")
                    ).hexdigest(),
                )
                chosen = ordered[:2]
                selected.extend(chosen)
                cells.append(
                    {
                        "fold": fold,
                        "family": family,
                        "side": side,
                        "pool": len(pool),
                        "selected": len(chosen),
                        "shortfall": 2 - len(chosen),
                    }
                )
    keys = list(dict.fromkeys(r["clip_key"] for r in selected))
    return {
        "cells": cells,
        "pool_rows": len(rows),
        "selected_row_ids": [r["id"] for r in selected],
        "clip_keys": keys,
        "reference_rows": [r for key in keys for r in rows if r["clip_key"] == key],
    }


def native_clock(path):
    """Exact native PTS ledger; standard app floats remain separately explicit."""
    import torchvision  # noqa: F401  # before threaded media

    from .av_runtime import open_media
    from .orientation import display_dimensions, frame_rotation

    before = digest(path)
    rows, rotation = [], None
    with open_media(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        time_base = Fraction(stream.time_base)
        origin_pts = stream.start_time or 0
        rate = float(stream.average_rate or 0)
        for index, frame in enumerate(container.decode(stream)):
            current = frame_rotation(frame)
            if rotation is None:
                rotation = current
            if current != rotation or frame.pts is None:
                raise ValueError("Missing native PTS or changed source orientation")
            frame_base = Fraction(frame.time_base)
            exact = frame.pts * frame_base - origin_pts * time_base
            if exact < 0:
                raise ValueError("Negative source time cannot preserve app clock")
            if rows and exact <= Fraction(*rows[-1]["relative_time"]):
                raise ValueError("Nonincreasing native PTS")
            rows.append(
                {
                    "frame": index,
                    "pts": frame.pts,
                    "time_base": [frame_base.numerator, frame_base.denominator],
                    "relative_time": [exact.numerator, exact.denominator],
                    "duration": frame.duration or 0,
                }
            )
        if not rows or not math.isfinite(rate) or rate <= 0:
            raise ValueError("Empty source or unavailable nominal rate")
        width, height = display_dimensions(stream.width, stream.height, rotation)
        source_width, source_height = stream.width, stream.height
        codec = stream.codec_context.name
    if digest(path) != before:
        raise ValueError("Source changed across native decoder teardown")
    times = [round(float(Fraction(*r["relative_time"])), 8) for r in rows]
    if any(b <= a for a, b in pairwise(times)):
        raise ValueError("Rounded app clock cannot distinguish source frames")
    tail = float(rows[-1]["duration"] * Fraction(*rows[-1]["time_base"]))
    tail = tail if tail > 0 else (times[-1] - times[-2] if len(times) > 1 else 1 / rate)
    video = {
        "id": before[:16],
        "sha256": before,
        "name": Path(path).name,
        "mode": "singles",
        "frame_count": len(rows),
        "width": width,
        "height": height,
        "source_width": source_width,
        "source_height": source_height,
        "rotation": rotation,
        "fps": rate,
        "source_start_s": float(origin_pts * time_base),
        "duration_s": round(times[-1] + tail, 8),
        "codec": codec,
        "time_base": str(time_base),
    }
    return (
        {
            "schema_version": 1,
            "source_sha256": before,
            "origin_pts": origin_pts,
            "stream_time_base": [time_base.numerator, time_base.denominator],
            "rotation": rotation,
            "display_dimensions": [width, height],
            "rows": rows,
        },
        times,
        video,
    )


def source_paths(archive, index, model, groups):
    return {
        "archive": Path(archive).resolve(),
        "clips": Path(index).resolve() / "clips.json",
        "records": Path(index).resolve() / "records.json",
        "model": Path(model).resolve(),
        "groups": Path(groups).resolve(),
    }


def verify_sources(paths):
    if set(paths) != set(PROTOCOL["sources"]):
        raise ValueError("Incomplete pinned pilot sources")
    for name, path in paths.items():
        if digest(path) != PROTOCOL["sources"][name]:
            raise ValueError(f"Changed pinned pilot source: {name}")


def inventory(directory):
    return {
        p.relative_to(directory).as_posix(): digest(p)
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def prepare(archive, index, model, groups, protocol, granted_at, deadline, output):
    from .segments import scan_video

    check_deadline(granted_at, deadline)
    if read_json(protocol) != PROTOCOL:
        raise ValueError("Changed fixed pilot protocol")
    paths = source_paths(archive, index, model, groups)
    if not Path(output).resolve().is_relative_to(paths["model"].parents[2] / ".cache"):
        raise ValueError(
            "Preparation output must remain in the private workspace cache"
        )
    verify_sources(paths)
    code, environment = code_seals(), runtime()
    clips, grouping = read_json(paths["clips"]), read_json(paths["groups"])
    folds, contexts = capture_folds(clips, grouping)
    for key, name in (
        ("source_archive_sha256", "archive"),
        ("source_clip_index_sha256", "clips"),
        ("source_records_sha256", "records"),
    ):
        if grouping[key] != PROTOCOL["sources"][name]:
            raise ValueError("Capture mapping source binding changed")
    rows = canonical_rows(paths["archive"], clips, folds)
    cohort = select_cohort(rows)
    limits = PROTOCOL["limits"]
    if (
        not cohort["clip_keys"]
        or len(cohort["selected_row_ids"]) > limits["selected_rows"]
        or len(cohort["clip_keys"]) > limits["selected_clips"]
    ):
        raise ValueError("Empty or over-limit fixed cohort")
    selected = {clip_key(c): c for c in clips if clip_key(c) in cohort["clip_keys"]}
    media_bytes = sum(selected[key]["media_bytes"] for key in cohort["clip_keys"])
    if media_bytes > limits["media_bytes"]:
        raise ValueError("Fixed selected media exceeds budget")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    publish(output / "cohort.json", cohort)
    prepared, frames = [], 0
    try:
        with zipfile.ZipFile(paths["archive"]) as source:
            for number, key in enumerate(cohort["clip_keys"]):
                check_deadline(granted_at, deadline)
                clip = selected[key]
                folder = output / f"clip-{number:02d}"
                folder.mkdir()
                media = folder / "source.mp4"
                info = source.getinfo(clip["media_path"])
                if info.file_size != clip["media_bytes"]:
                    raise ValueError("Original media size binding changed")
                with source.open(info) as src, media.open("xb") as dest:
                    for chunk in iter(lambda: src.read(1024 * 1024), b""):
                        check_budget(
                            output,
                            frames=frames,
                            media_bytes=media_bytes,
                            reserve=len(chunk),
                        )
                        dest.write(chunk)
                if digest(media) != clip["media_sha256"]:
                    raise ValueError("Original media hash binding changed")
                ledger, times, video = native_clock(media)
                frames += len(times)
                check_budget(output, frames=frames, media_bytes=media_bytes)
                if video["duration_s"] > 120:
                    raise ValueError(
                        "Whole selected clip exceeds standard tracker range"
                    )
                video["path"] = media.relative_to(output).as_posix()
                publish(folder / "native-clock.json", ledger)
                data = folder / "data"
                (data / video["id"]).mkdir(parents=True)
                publish(data / video["id"] / "timestamps.json", times)
                scan = folder / "camera.json"
                scan_video(
                    video,
                    output,
                    data,
                    lambda _: check_deadline(granted_at, deadline),
                    scan,
                )
                publish(folder / "video.json", video)
                prepared.append(
                    {
                        "key": key,
                        "fold": folds[key],
                        "context": contexts[key],
                        "folder": folder.relative_to(output).as_posix(),
                        "source_sha256": clip["media_sha256"],
                        "source_label_sha256": clip["label_sha256"],
                        "frames": len(times),
                    }
                )
        verify_sources(paths)
        check_deadline(granted_at, deadline)
        check_budget(
            output, frames=frames, media_bytes=media_bytes, reserve=1024 * 1024
        )
        if code_seals() != code or runtime() != environment:
            raise ValueError("Consumer or runtime changed during preparation")
        freeze = {
            "schema_version": 1,
            "protocol": PROTOCOL,
            "granted_at": granted_at,
            "deadline": deadline,
            "sources": {
                k: {"path": str(v), "sha256": digest(v)} for k, v in paths.items()
            },
            "code": code,
            "runtime": environment,
            "clips": prepared,
            "native_frames": frames,
            "media_bytes": media_bytes,
            "artifacts": inventory(output),
            "training": False,
            "test_opened": False,
            "scene_truth": "unknown",
        }
        publish(output / "freeze.json", freeze)
        return {
            "freeze_sha256": digest(output / "freeze.json"),
            "native_frames": frames,
            "selected_clips": len(prepared),
            "selected_rows": len(cohort["selected_row_ids"]),
        }
    except BaseException as error:
        publish(
            output / "preparation-failure.json",
            {
                "type": type(error).__name__,
                "message": str(error),
                "completed_clips": len(prepared),
                "native_frames": frames,
            },
        )
        raise


def validate_prepared(prepared, expected_hash, *, clock=True):
    prepared = Path(prepared).resolve()
    if digest(prepared / "freeze.json") != expected_hash:
        raise ValueError("Changed prospective freeze")
    freeze = read_json(prepared / "freeze.json")
    if (
        freeze["protocol"] != PROTOCOL
        or freeze["code"] != code_seals()
        or freeze["runtime"] != runtime()
    ):
        raise ValueError("Changed consumer, protocol or runtime")
    if clock:
        check_deadline(freeze["granted_at"], freeze["deadline"])
    verify_sources({k: Path(v["path"]) for k, v in freeze["sources"].items()})
    for name, expected in freeze["artifacts"].items():
        if digest(inside(prepared, name)) != expected:
            raise ValueError(f"Changed prepared source/clock/camera/cohort: {name}")
    if (
        inventory(prepared).keys()
        != (freeze["artifacts"] | {"freeze.json": expected_hash}).keys()
    ):
        raise ValueError("Unexpected prepared artifact; preserve original freeze")
    if any(c["fold"] not in FOLDS for c in freeze["clips"]):
        raise ValueError("Held-out source in prepared cohort")
    check_budget(
        prepared, frames=freeze["native_frames"], media_bytes=freeze["media_bytes"]
    )
    return freeze


def validate_pose(result, video, times, scan, ledger):
    """Check observation provenance and availability, without assigning hitters."""
    from .calibration_context import effective_annotations
    from .schemas import empty_annotations
    from .tracking import TRACKING_RECIPE

    count = video["frame_count"]
    if (
        result["stage"] != "players"
        or result["video_id"] != video["id"]
        or result["video_sha256"] != video["sha256"]
        or result["checkpoint_sha256"] != PROTOCOL["sources"]["model"]
        or result["model_variant"] != "small"
        or result["image_size"] != 1280
        or result["tracking_recipe"] != TRACKING_RECIPE
        or result["stride"] != 1
        or result["auto_calibrate"] is not True
        or result["start_frame"] != 0
        or result["end_frame"] != count
        or result["processed_frames"] != count
        or len(result["frames"]) != count
        or result["cut_frames"] != scan["cut_frames"]
        or result["camera_ranges"] != scan["camera_ranges"]
        or ledger["source_sha256"] != video["sha256"]
        or ledger["rotation"] != video["rotation"]
        or ledger["display_dimensions"] != [video["width"], video["height"]]
        or len(ledger["rows"]) != count
    ):
        raise ValueError("Incomplete or conflicting native pose provenance")
    calibrations = effective_annotations(empty_annotations("singles"), result)[
        "calibrations"
    ]
    segment, seen_ids = 0, {}
    summary = Counter()
    for index, (row, native) in enumerate(
        zip(result["frames"], ledger["rows"], strict=True)
    ):
        if index in scan["cut_frames"]:
            segment = index
        valid_calibration = any(
            c["start_frame"] <= index < c["end_frame"] and c["start_frame"] >= segment
            for c in calibrations
        )
        exact = native["pts"] * Fraction(*native["time_base"]) - ledger[
            "origin_pts"
        ] * Fraction(*ledger["stream_time_base"])
        if (
            row["frame"] != index
            or native["frame"] != index
            or Fraction(*native["relative_time"]) != exact
            or row["time_s"] != times[index]
            or times[index] != round(float(exact), 8)
            or row["camera_segment_start_frame"] != segment
            or row["calibration_valid"] != valid_calibration
        ):
            raise ValueError("Native frame/PTS, cut or calibration mismatch")
        summary["processed_frames"] += 1
        summary["frames_without_pose_players"] += not row["players"]
        for person in row["players"] + row.get("motion_players", []):
            box, confidence, points = (
                person["box"],
                person["confidence"],
                person["keypoints"],
            )
            if (
                len(box) != 4
                or not all(math.isfinite(v) for v in [*box, confidence])
                or not 0 <= box[0] <= box[2] <= video["width"]
                or not 0 <= box[1] <= box[3] <= video["height"]
                or not 0 <= confidence <= 1
                or len(points) not in (0, 17)
                or any(
                    len(p) != 3
                    or not all(math.isfinite(v) for v in p)
                    or not 0 <= p[2] <= 1
                    for p in points
                )
            ):
                raise ValueError("Invalid native box, pose or confidence")
            for name in ("track_id", "baseline_track_id"):
                identity = person.get(name)
                if identity is not None:
                    if type(identity) is not int or identity < 1:
                        raise ValueError("Invalid provisional track identity")
                    qualified = (name, identity)
                    if seen_ids.setdefault(qualified, segment) != segment:
                        raise ValueError("Track identity crosses a camera cut")
        summary["player_observations"] += len(row["players"])
    return dict(summary)


def reference_support(rows, result):
    """All weak rows remain, including unknown targets and missing actor support."""
    output = []
    for reference in rows:
        h = reference["source_contact_frame"]
        interval = [h - 1, h] if type(h) is int and h > 0 else None
        available = interval is not None and interval[-1] < len(result["frames"])
        frames = result["frames"][interval[0] : interval[1] + 1] if available else []
        cameras = {f["camera_segment_start_frame"] for f in frames}
        observations = []
        for row in frames:
            for player in row["players"]:
                points = player["keypoints"]
                observations.append(
                    {
                        "frame": row["frame"],
                        "track_id": player["track_id"],
                        "shoulders": sum(points[i][2] >= 0.25 for i in (5, 6))
                        if len(points) == 17
                        else 0,
                        "elbows": sum(points[i][2] >= 0.25 for i in (7, 8))
                        if len(points) == 17
                        else 0,
                        "wrists": sum(points[i][2] >= 0.25 for i in (9, 10))
                        if len(points) == 17
                        else 0,
                    }
                )
        output.append(
            {
                "reference": reference,
                "published_interval": interval,
                "interval_available": available,
                "censored_H0": h == 0,
                "crosses_camera_boundary": len(cameras) > 1,
                "pose_observations": observations,
                "candidate_actor_ambiguous": True,
                "correct_hitter": None,
                "source_scene_truth": "unknown",
                "training_ready": False,
            }
        )
    return output


def clip_receipt(clip, coverage, support, directory):
    return {
        "key": clip["key"],
        "fold": clip["fold"],
        "context": clip["context"],
        "frames": clip["frames"],
        "reference_rows": len(support),
        "coverage": coverage,
        "censored_H0": sum(r["censored_H0"] for r in support),
        "available_intervals": sum(r["interval_available"] for r in support),
        **{
            name + "_observations": sum(
                o[key] for r in support for o in r["pose_observations"]
            )
            for name, key in (
                ("shoulder", "shoulders"),
                ("elbow", "elbows"),
                ("wrist", "wrists"),
            )
        },
        "player_sha256": digest(directory / "players.json"),
        "support_sha256": digest(directory / "support.json"),
    }


def annotation_snapshot(data):
    database = Path(data).resolve() / "catalog.sqlite3"
    if not database.is_file():
        raise ValueError("Existing real shared Store is required")
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        value = {
            name: db.execute(f"SELECT * FROM {name} ORDER BY 1,2").fetchall()
            for name in ("videos", "annotations")
        }
    return hashlib.sha256(encoded(value)).hexdigest()


def configure_workspace(workspace):
    workspace = Path(workspace).resolve()
    data, weights = workspace / "data/processed", workspace / "models/weights"
    os.environ["BADMINTON_ROOT"] = str(workspace)
    os.environ["BADMINTON_DATA_DIR"] = str(data)
    os.environ["BADMINTON_WEIGHTS_DIR"] = str(weights)
    from . import config

    if (config.ROOT.resolve(), config.DATA.resolve(), config.WEIGHTS.resolve()) != (
        workspace,
        data,
        weights,
    ):
        raise ValueError(
            "Application config imported before pinning the real workspace"
        )
    annotation_snapshot(data)
    return workspace, data, weights


def run(workspace, prepared, freeze_sha256, output):
    workspace, data, weights = configure_workspace(workspace)
    import psutil

    from .jobs import run_local_job
    from .schemas import empty_annotations
    from .storage import Store
    from .tracking import track_players

    prepared, output = Path(prepared).resolve(), Path(output).resolve()
    if (
        not output.is_relative_to(workspace / ".cache")
        or output.is_relative_to(prepared)
        or prepared.is_relative_to(output)
    ):
        raise ValueError("New run must be separate private workspace cache output")
    freeze = validate_prepared(prepared, freeze_sha256)
    if Path(freeze["sources"]["model"]["path"]) != weights / "yolo11s-pose.pt":
        raise ValueError("Frozen model is not the pinned real-workspace checkpoint")
    before = annotation_snapshot(data)
    output.mkdir(parents=True, exist_ok=False)
    store = Store(data)
    receipts = []
    execution_claim = prepared.with_name(prepared.name + "-native-start.json")

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
                "freeze_sha256": freeze_sha256,
            },
        )
        for number, clip in enumerate(freeze["clips"]):
            check_deadline(freeze["granted_at"], freeze["deadline"])
            folder = inside(prepared, clip["folder"])
            video, ledger = (
                read_json(folder / "video.json"),
                read_json(folder / "native-clock.json"),
            )
            times = read_json(folder / "data" / video["id"] / "timestamps.json")
            scan = read_json(folder / "camera.json")
            # Tracker runtime/timestamps are private and mutable in this run,
            # leaving all prospectively sealed preparation bytes unchanged.
            native_data = output / f"clip-{number:02d}"
            (native_data / video["id"]).mkdir(parents=True)
            publish(native_data / video["id"] / "timestamps.json", times)
            target = native_data / "players.json"

            def report(value):
                check_deadline(freeze["granted_at"], freeze["deadline"])
                check_budget(prepared, reserve=check_budget(output))
                progress((number + value) / len(freeze["clips"]))

            track_players(
                video,
                prepared,
                native_data,
                empty_annotations("singles"),
                0,
                video["frame_count"],
                1,
                report,
                target,
                player_model="small",
                auto_calibrate=True,
                camera_scan=scan,
            )
            result = read_json(target)
            coverage = validate_pose(result, video, times, scan, ledger)
            refs = [
                r
                for r in read_json(prepared / "cohort.json")["reference_rows"]
                if r["clip_key"] == clip["key"]
            ]
            support = reference_support(refs, result)
            publish(native_data / "support.json", support)
            receipt = clip_receipt(clip, coverage, support, native_data)
            publish(native_data / "receipt.json", receipt)
            receipts.append(receipt)
        validate_prepared(prepared, freeze_sha256)
        check_budget(prepared, reserve=check_budget(output) + 1024 * 1024)
        if annotation_snapshot(data) != before:
            raise ValueError("Shared video/annotation truth changed during pilot")
        return {
            "clips": len(receipts),
            "native_frames": sum(r["frames"] for r in receipts),
            "freeze_sha256": freeze_sha256,
        }

    try:
        # An alternate output directory cannot repeat an already dispatched
        # freeze. Even failed admission is preserved, never silently restarted.
        publish(
            execution_claim, {"freeze_sha256": freeze_sha256, "output": str(output)}
        )
        summary = run_local_job(store, "feature-preparation", None, task)
        process = read_json(output / "process.json")
        job = store.job(process["job_id"])
        if job["status"] != "completed":
            raise ValueError("Completion requires durable real Store release")
        completion = {
            "schema_version": 1,
            "summary": summary,
            "job_id": job["id"],
            "shared_data": str(data),
            "execution_claim": str(execution_claim),
            "original_annotations_sha256": before,
            "receipts": receipts,
            "artifacts": inventory(output),
            "freeze_sha256": freeze_sha256,
            "model_installed_in_app": False,
            "training_ready": False,
            "test_opened": False,
            "complete_rally_references": {"accepted": 0, "required": 2},
        }
        publish(output / "completion.json", completion)
        return completion
    except BaseException as error:
        publish(
            output / "failure.json",
            {
                "type": type(error).__name__,
                "message": str(error),
                "completed_clips": len(receipts),
            },
        )
        raise


def verify(prepared, freeze_sha256, output):
    """Read-only verification remains possible after the scientific deadline."""
    prepared, output = Path(prepared).resolve(), Path(output).resolve()
    freeze = validate_prepared(prepared, freeze_sha256, clock=False)
    completion = read_json(output / "completion.json")
    if completion["freeze_sha256"] != freeze_sha256:
        raise ValueError("Completion freeze mismatch")
    expected_claim = prepared.with_name(prepared.name + "-native-start.json")
    if Path(completion["execution_claim"]) != expected_claim or read_json(
        expected_claim
    ) != {"freeze_sha256": freeze_sha256, "output": str(output)}:
        raise ValueError("Native execution claim is absent or changed")
    for name, expected in completion["artifacts"].items():
        if digest(inside(output, name)) != expected:
            raise ValueError("Changed native output artifact")
    if len(completion["receipts"]) != len(freeze["clips"]):
        raise ValueError("Incomplete fixed cohort")
    if (
        inventory(output).keys()
        != (completion["artifacts"] | {"completion.json": ""}).keys()
    ):
        raise ValueError("Unexpected native output artifact")
    cohort = read_json(prepared / "cohort.json")
    total_frames = 0
    for number, clip in enumerate(freeze["clips"]):
        folder = inside(prepared, clip["folder"])
        video = read_json(folder / "video.json")
        directory = output / f"clip-{number:02d}"
        result = read_json(directory / "players.json")
        coverage = validate_pose(
            result,
            video,
            read_json(folder / "data" / video["id"] / "timestamps.json"),
            read_json(folder / "camera.json"),
            read_json(folder / "native-clock.json"),
        )
        refs = [r for r in cohort["reference_rows"] if r["clip_key"] == clip["key"]]
        support = reference_support(refs, result)
        receipt = clip_receipt(clip, coverage, support, directory)
        if (
            support != read_json(directory / "support.json")
            or receipt != read_json(directory / "receipt.json")
            or receipt != completion["receipts"][number]
        ):
            raise ValueError(
                "Native support/receipt does not reproduce from original rows"
            )
        total_frames += coverage["processed_frames"]
    expected = {
        "clips": len(freeze["clips"]),
        "native_frames": total_frames,
        "freeze_sha256": freeze_sha256,
    }
    if completion["summary"] != expected or total_frames != freeze["native_frames"]:
        raise ValueError("Completion does not retain the full native denominator")
    data = Path(completion["shared_data"])
    if annotation_snapshot(data) != completion["original_annotations_sha256"]:
        raise ValueError("Shared annotation history changed since pilot")
    with sqlite3.connect(
        (data / "catalog.sqlite3").resolve().as_uri() + "?mode=ro", uri=True
    ) as db:
        row = db.execute(
            "SELECT document FROM jobs WHERE id=?", (completion["job_id"],)
        ).fetchone()
    job = json.loads(row[0]) if row else {}
    if job.get("status") != "completed" or job.get("summary") != expected:
        raise ValueError("Real shared Store completion is absent or changed")
    check_budget(prepared, reserve=check_budget(output))
    return {
        "verified_clips": len(freeze["clips"]),
        "native_frames": freeze["native_frames"],
        "accuracy_established": False,
        "model_installed_in_app": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    for name in ("archive", "index", "model", "groups", "protocol", "output"):
        prep.add_argument("--" + name, required=True, type=Path)
    prep.add_argument("--granted-at", required=True, type=float)
    prep.add_argument("--deadline", required=True, type=float)
    for name in ("run", "verify"):
        command = sub.add_parser(name)
        command.add_argument("--prepared", required=True, type=Path)
        command.add_argument("--freeze-sha256", required=True)
        command.add_argument("--output", required=True, type=Path)
        if name == "run":
            command.add_argument("--workspace", required=True, type=Path)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    print(
        json.dumps(
            {"prepare": prepare, "run": run, "verify": verify}[command](**args),
            indent=2,
        )
    )
