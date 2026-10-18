"""Resumable whole-source processing with bounded, overlapping inference windows.

Completed stage artifacts are immutable and hash-checked. Processing boundaries
are not camera cuts; tracker identities remain scoped to their source run.
"""

import bisect
import hashlib
import importlib.metadata
import itertools
import json
import math
import os
import time
from pathlib import Path

from .calibration_context import court_run_context
from .config import WEIGHTS
from .contacts import METHOD as CONTACT_METHOD
from .contacts import proposal_recipe, propose_contacts
from .jobs import JobCancelled
from .rallies import context_signature, generate_rallies
from .recognition import recognition_targets, recognize_strokes
from .scene_review import camera_review_signature
from .segments import scan_video
from .shuttle import track_shuttle
from .storage import owner_alive
from .tracking import track_players
from .video import resolve_source, timestamps_for, validate_range, write_json

METHOD = "overlapping source windows with immutable stage checkpoints v1"
CORE_SECONDS = 60
HALO_SECONDS = 4
STAGES = ("players", "shuttle", "contacts", "rallies", "recognition")


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def file_sha(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def plan_windows(video, times, core_seconds=CORE_SECONDS, halo_seconds=HALO_SECONDS):
    if (
        not times
        or len(times) != video["frame_count"]
        or any(
            not isinstance(t, int | float) or not math.isfinite(t) or t < 0
            for t in times
        )
        or any(a >= b for a, b in itertools.pairwise(times))
        or not math.isfinite(video["duration_s"])
        or video["duration_s"] <= times[-1]
        or not math.isfinite(core_seconds)
        or not 1 <= core_seconds <= 112
        or not math.isfinite(halo_seconds)
        or not 2 <= halo_seconds <= 4
    ):
        raise ValueError(
            "Window planning needs ordered source times and bounded positive durations"
        )
    windows, start = [], 0
    while start < len(times):
        end = max(start + 1, bisect.bisect_left(times, times[start] + core_seconds))
        first = bisect.bisect_left(times, max(0, times[start] - halo_seconds))
        last = bisect.bisect_left(
            times,
            (times[end] if end < len(times) else video["duration_s"]) + halo_seconds,
        )
        validate_range(video, times, first, last)
        windows.append(
            {
                "index": len(windows),
                "core_start_frame": start,
                "core_end_frame": end,
                "start_frame": first,
                "end_frame": last,
            }
        )
        start = end
    return windows


def processing_recipe(video, times, annotations, settings):
    package = Path(__file__).parent
    code = {
        p.relative_to(package).as_posix(): file_sha(p)
        for p in sorted(package.rglob("*"))
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix in (".py", ".json", ".pt")
    }
    # An optional locally installed side head overrides the packaged head.
    local_side = {
        p.name: file_sha(p)
        for p in sorted(WEIGHTS.glob("stroke_side_v1*"))
        if p.is_file()
    }
    versions = {}
    for name in (
        "av",
        "opencv-python",
        "numpy",
        "scenedetect",
        "torch",
        "torchvision",
        "ultralytics",
    ):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {
        "method": METHOD,
        "video": {
            k: video.get(k)
            for k in (
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
            )
        },
        "timestamps_sha256": digest(times),
        "settings": settings,
        "core_seconds": CORE_SECONDS,
        "halo_seconds": HALO_SECONDS,
        "context_signature": context_signature(annotations, 0, len(times)),
        "source_files": code,
        "local_side_files": local_side,
        "library_versions": versions,
    }


def plan_path(store, video_id, key):
    if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
        raise ValueError("Invalid processing checkpoint key")
    return store.data / video_id / "analysis" / key / "manifest.json"


def stage_recipe(recipe, name, window, dependencies):
    """Recognition choices must not invalidate expensive unchanged perception."""
    result = {
        k: v
        for k, v in recipe.items()
        if k not in ("settings", "context_signature", "local_side_files")
    }
    result.update(stage=name, window=window, dependencies=dependencies)
    if name != "segments":
        result["context_signature"] = recipe["context_signature"]
    result["settings"] = (
        {k: recipe["settings"][k] for k in ("player_model", "auto_calibrate")}
        if name == "players"
        else {"recognize": recipe["settings"]["recognize"]}
        if name == "recognition"
        else {}
    )
    if name == "recognition":
        result["local_side_files"] = recipe["local_side_files"]
    return result


def read_plan(store, video_id, key):
    return json.loads(plan_path(store, video_id, key).read_text(encoding="utf-8"))


def owned_candidates(run):
    return [
        c
        for c in run.get("candidates", [])
        if run.get("analysis_core_start_frame", run["start_frame"])
        <= c["frame"]
        < run.get("analysis_core_end_frame", run["end_frame"])
    ]


def process_match(
    video, root, store, annotations, job_id, progress, settings, *, expected_key=None
):
    """Use the caller's admitted job; never claim nested jobs or edit annotations."""
    owner = store.job(job_id)
    if (
        owner["kind"] != "analysis"
        or owner["video_id"] != video["id"]
        or owner["status"] not in ("queued", "running")
        or owner.get("owner_pid") != os.getpid()
        or not owner_alive(owner)
    ):
        raise ValueError("Full-match processing requires its own admitted analysis job")
    resolve_source(video, root)
    times = timestamps_for(store.data, video["id"])
    windows = plan_windows(video, times)
    recipe = processing_recipe(video, times, annotations, settings)
    key = digest(recipe)
    if expected_key is not None and key != expected_key:
        raise ValueError("Processing inputs changed after queuing; request a new run")
    owner["details"] = {"analysis_key": key, "settings": settings}
    store.put_job(owner)
    path = plan_path(store, video["id"], key)
    if path.exists():
        plan = read_plan(store, video["id"], key)
        if (
            plan.get("recipe") != recipe
            or [p["window"] for p in plan.get("parts", [])] != windows
        ):
            raise ValueError("Saved processing recipe or coverage changed")
    else:
        plan = {
            "schema_version": 1,
            "stage": "analysis",
            "video_id": video["id"],
            "video_sha256": video["sha256"],
            "analysis_key": key,
            "recipe": recipe,
            "parts": [{"window": w, "stages": {}} for w in windows],
        }
    plan.update(
        state="running",
        job_id=job_id,
        error=None,
        fully_annotated=False,
        processing_complete=False,
        completed_stages=0,
    )
    # Existing event labels, source shuttle labels and reviewed identities never
    # supply values or targets to this automatic processing pass.
    inference_doc = annotations.model_copy(
        deep=True,
        update={
            "events": [],
            "track_assignments": [],
            "shuttle_points": [],
            "review_windows": [],
        },
    )
    completed, reused = 0, 0
    total = 1 + len(windows) * len(STAGES)
    last_tick = -1
    last_context_check = 0

    def report(value):
        nonlocal last_tick, last_context_check
        if store.job(job_id).get("cancel_requested"):
            raise JobCancelled(
                "Processing paused; completed stages are available to resume"
            )
        now = time.monotonic()
        if now - last_context_check >= 1:
            last_context_check = now
            if (
                context_signature(store.annotations(video["id"]), 0, len(times))
                != recipe["context_signature"]
            ):
                raise JobCancelled(
                    "Camera, scene or court context changed; resume processing with the current annotations"
                )
        tick = int(1000 * min(1, max(0, (completed + value) / total)))
        if tick != last_tick:
            last_tick = tick
            progress(tick / 1000)

    def stage(name, part, action):
        nonlocal completed, reused
        report(0)
        index = part["window"]["index"] if part else -1
        dependencies = {}
        if part:
            dependencies["segments"] = plan["segments"]["sha256"]
            dependencies.update(
                {s: part["stages"][s]["sha256"] for s in STAGES[: STAGES.index(name)]}
            )
        stage_key = digest(
            stage_recipe(recipe, name, part["window"] if part else None, dependencies)
        )
        identifier = stage_key[:32]
        output = store.data / video["id"] / "runs" / f"{identifier}.json"
        checkpoint = (part["stages"] if part else plan).get(name)
        if checkpoint is None:
            try:
                saved = store.job(identifier)
            except KeyError:
                saved = None
            if saved and saved["status"] == "completed":
                checkpoint = saved["summary"]["checkpoint"]
        if checkpoint:
            if (
                checkpoint["run_id"] != identifier
                or not output.is_file()
                or file_sha(output) != checkpoint["sha256"]
            ):
                raise ValueError(
                    f"Cached {name} artifact changed; preserve it and investigate before resuming"
                )
            run = json.loads(output.read_text(encoding="utf-8"))
            if (
                run.get("analysis_stage_key") != stage_key
                or run.get("video_sha256") != video["sha256"]
                or run.get("stage") != name
            ):
                raise ValueError(
                    "Cached processing artifact does not match its recipe/source/stage"
                )
            reused += 1
            try:
                registered = store.job(identifier)
            except KeyError:
                registered = None
            if registered is not None and (
                registered.get("kind") != name
                or registered.get("video_id") != video["id"]
                or registered.get("status") != "completed"
                or registered.get("summary", {}).get("checkpoint") != checkpoint
            ):
                raise ValueError("Cached artifact registration changed")
            if registered is None:
                store.put_job(
                    {
                        "id": identifier,
                        "kind": name,
                        "video_id": video["id"],
                        "status": "completed",
                        "progress": 1,
                        "analysis_key": key,
                        "analysis_part_index": index,
                        "summary": {
                            "checkpoint": checkpoint,
                            **{
                                k: v
                                for k, v in run.items()
                                if k
                                not in (
                                    "frames",
                                    "candidates",
                                    "boundaries",
                                    "camera_ranges",
                                    "court_detection",
                                )
                            },
                        },
                    }
                )
        else:
            plan["active"] = {"part_index": index, "stage": name}
            write_json(path, plan)
            action(output, report)
            run = json.loads(output.read_text(encoding="utf-8"))
            if (
                run.get("stage") != name
                or run.get("video_id") != video["id"]
                or run.get("video_sha256") != video["sha256"]
            ):
                raise ValueError("Processing stage returned a mismatched artifact")
            expected_start, expected_end = (
                (part["window"]["start_frame"], part["window"]["end_frame"])
                if part
                else (0, len(times))
            )
            if (
                run.get("start_frame") != expected_start
                or run.get("end_frame") != expected_end
            ):
                raise ValueError("Processing stage did not cover its requested range")
            if name in ("players", "shuttle") and (
                len(run.get("frames", [])) != expected_end - expected_start
                or any(
                    r.get("frame") != expected_start + i
                    or not isinstance(r.get("time_s"), int | float)
                    or not math.isfinite(r["time_s"])
                    or abs(r["time_s"] - times[expected_start + i]) > 0.00002
                    for i, r in enumerate(run.get("frames", []))
                )
            ):
                raise ValueError(
                    "Processing output must retain every requested source frame and timestamp"
                )
            if any(
                type(c.get("frame")) is not int
                or not expected_start <= c["frame"] < expected_end
                or not isinstance(c.get("time_s"), int | float)
                or not math.isfinite(c["time_s"])
                or not 0 <= c["time_s"] <= video["duration_s"]
                for c in run.get("candidates", [])
            ):
                raise ValueError("Proposal frames/times must lie in their source range")
            run.update(
                analysis_key=key,
                analysis_stage_key=stage_key,
                analysis_part_index=index,
            )
            if part:
                run.update(
                    analysis_core_start_frame=part["window"]["core_start_frame"],
                    analysis_core_end_frame=part["window"]["core_end_frame"],
                )
            write_json(output, run)
            checkpoint = {
                "run_id": identifier,
                "sha256": file_sha(output),
                "owned_candidate_count": len(owned_candidates(run))
                if "candidates" in run
                else 0,
            }
            summary = {
                k: v
                for k, v in run.items()
                if k
                not in (
                    "frames",
                    "candidates",
                    "boundaries",
                    "camera_ranges",
                    "court_detection",
                )
            }
            summary["checkpoint"] = checkpoint
            store.put_job(
                {
                    "id": identifier,
                    "kind": name,
                    "video_id": video["id"],
                    "status": "completed",
                    "progress": 1,
                    "analysis_key": key,
                    "analysis_part_index": index,
                    "summary": summary,
                }
            )
        (part["stages"] if part else plan)[name] = checkpoint
        completed += 1
        plan["completed_stages"] = completed
        write_json(path, plan)
        report(0)
        return run, identifier

    try:
        report(0)
        scan, _scan_id = stage(
            "segments",
            None,
            lambda output, callback: scan_video(
                video, root, store.data, callback, output
            ),
        )
        for part in plan["parts"]:
            w = part["window"]
            first, last = w["start_frame"], w["end_frame"]
            players, player_id = stage(
                "players",
                part,
                lambda output, callback: track_players(
                    video,
                    root,
                    store.data,
                    inference_doc,
                    first,
                    last,
                    1,
                    callback,
                    output,
                    player_model=settings["player_model"],
                    auto_calibrate=settings["auto_calibrate"],
                    camera_scan=scan,
                ),
            )
            shuttle, shuttle_id = stage(
                "shuttle",
                part,
                lambda output, callback: track_shuttle(
                    video,
                    root,
                    store.data,
                    first,
                    last,
                    callback,
                    output,
                    inference_doc,
                    camera_scan=scan,
                ),
            )

            def contacts(output, callback):
                candidates = propose_contacts(shuttle, players, video)
                result = {
                    "schema_version": 1,
                    "stage": "contacts",
                    "video_id": video["id"],
                    "video_sha256": video["sha256"],
                    "start_frame": first,
                    "end_frame": last,
                    "method": CONTACT_METHOD,
                    "recipe": proposal_recipe(),
                    "interval_bounds": "inclusive",
                    "player_run_id": player_id,
                    "shuttle_run_id": shuttle_id,
                    "candidate_count": len(candidates),
                    "candidates": candidates,
                    "annotation_revision": annotations.revision,
                    "camera_review_signature": camera_review_signature(
                        inference_doc, first, last
                    ),
                    "court_context": court_run_context(players),
                    "calibration_signature": players["calibration_signature"],
                }
                write_json(output, result)
                callback(1)

            contact_run, contact_id = stage("contacts", part, contacts)
            stage(
                "rallies",
                part,
                lambda output, callback: generate_rallies(
                    video,
                    players,
                    shuttle,
                    inference_doc,
                    player_id,
                    shuttle_id,
                    output,
                    times,
                ),
            )

            def recognize(output, callback):
                targets = recognition_targets(
                    inference_doc, contact_run, include_reviewed=False
                )
                if settings["recognize"] and video["mode"] == "singles" and targets:
                    recognize_strokes(
                        video,
                        times,
                        inference_doc,
                        players,
                        shuttle | {"run_id": shuttle_id},
                        targets,
                        player_id,
                        callback,
                        output,
                        contacts_run_id=contact_id,
                    )
                else:
                    write_json(
                        output,
                        {
                            "stage": "recognition",
                            "video_id": video["id"],
                            "video_sha256": video["sha256"],
                            "start_frame": first,
                            "end_frame": last,
                            "player_run_id": player_id,
                            "shuttle_run_id": shuttle_id,
                            "contacts_run_id": contact_id,
                            "candidates": [],
                            "candidate_count": 0,
                            "status": "unsupported"
                            if video["mode"] != "singles"
                            else "disabled"
                            if not settings["recognize"]
                            else "no_contacts",
                            "reason": "Doubles family/side recognition requires a validated model"
                            if video["mode"] != "singles"
                            else "Recognition disabled or no proposed contacts",
                        },
                    )
                    callback(1)

            stage("recognition", part, recognize)
        plan.update(
            state="completed",
            active=None,
            completed_stages=completed,
            reused_stages=reused,
            processing_complete=True,
            fully_annotated=False,
            meaning="Processing finished; all proposals and identities remain unverified. This is not full-match correctness.",
        )
        write_json(path, plan)
        progress(1)
        return {
            "analysis_key": key,
            "parts": len(windows),
            "completed_stages": completed,
            "reused_stages": reused,
            "processing_complete": True,
            "fully_annotated": False,
        }
    except BaseException as error:
        plan.update(
            state="interrupted"
            if isinstance(error, KeyboardInterrupt | JobCancelled)
            else "failed",
            error=str(error),
        )
        write_json(path, plan)
        raise
