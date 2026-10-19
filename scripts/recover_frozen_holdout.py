"""Inventory and resume sealed native inputs without overwriting prior evidence.

Inventory is read-only and imports no application modules. Native recovery runs
only in a separate process with a sealed frozen runtime and real shared Store
admission. Prediction evaluation is deliberately a separate, gated phase.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import itertools
import json
import math
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import psutil


def read_json(path):
    def invalid(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid)


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inside(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Experiment paths must remain inside the workspace")
    return path


def component(value):
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise ValueError("Invalid catalog identifier")
    if any(c in value for c in "/\\:"):
        raise ValueError("Invalid catalog identifier")
    return value


def catalog_path(root, folder, video_id, *suffix):
    return inside(root, str(folder / component(video_id) / Path(*suffix)))


def sealed(root, entry):
    path = inside(root, entry["path"])
    if checksum(path) != entry["sha256"]:
        raise ValueError(f"Frozen bytes changed: {entry['path']}")
    return path


def database_snapshot(folder):
    path = folder / "catalog.sqlite3"
    if not path.is_file():
        raise FileNotFoundError("Existing experiment catalog is required")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("BEGIN")
        videos = {
            document["id"]: document
            for (raw,) in db.execute("SELECT document FROM videos")
            for document in [json.loads(raw)]
        }
        jobs = {
            document["id"]: document
            for (raw,) in db.execute("SELECT document FROM jobs ORDER BY rowid")
            for document in [json.loads(raw)]
        }
        annotations = {
            video_id: db.execute(
                "SELECT document FROM annotations WHERE video_id=? ORDER BY revision DESC LIMIT 1",
                (video_id,),
            ).fetchone()[0]
            for video_id in videos
        }
    return videos, jobs, annotations


def stable_frozen(root, manifest):
    """Match the original producers' per-case frozen-input revalidation."""
    if "execution" in manifest and manifest["execution"][
        "recovery_code_sha256"
    ] != checksum(Path(__file__)):
        raise ValueError("Recovery execution code changed after freezing")
    for entry in (manifest["protocol"], manifest["view_support"], *manifest["inputs"]):
        sealed(root, entry)
    for runtime in manifest["runtimes"]:
        directory = inside(root, runtime["directory"])
        for name, expected in runtime["files"].items():
            if checksum(inside(root, str(directory / name))) != expected:
                raise ValueError("Frozen runtime changed during recovery")


def stable_source(root, manifest, video, support, request, expected_document_sha256):
    if (
        hashlib.sha256(encoded(video)).hexdigest() != expected_document_sha256
        or checksum(inside(root, video["path"])) != support["source_sha256"]
    ):
        raise ValueError("Source bytes or registered metadata changed during recovery")
    times = read_json(
        catalog_path(
            root,
            inside(root, manifest["research_data"]),
            video["id"],
            "timestamps.json",
        )
    )
    source_clock(root, manifest, request, video, times)


def process_state(worker):
    """A reused PID does not identify the original worker; never stop it."""
    pid, created = worker["pid"], worker["created"]
    if type(pid) is not int or pid <= 0 or not math.isfinite(created) or created <= 0:
        raise ValueError("Invalid producer process identity")
    try:
        process = psutil.Process(pid)
        if abs(process.create_time() - created) >= 0.01:
            return "original_exited_pid_reused"
        # Even a contradictory command remains live/ambiguous, never restartable.
        expected_cwd = Path(worker["cwd"]).resolve()
        expected_script = Path(worker["script"]).resolve()
        matches = Path(process.cwd()).resolve() == expected_cwd and any(
            Path(arg).resolve() == expected_script for arg in process.cmdline()[1:]
        )
        return "live" if matches else "ambiguous_live_identity"
    except psutil.NoSuchProcess:
        return "original_exited"
    except psutil.AccessDenied:
        return "unverifiable"


def matching_producers(producers):
    """Also detect a producer restarted under a different PID or directory."""
    names = {Path(producer["script"]["path"]).name for producer in producers}
    matches = []
    for process in psutil.process_iter(["pid", "create_time", "cwd", "cmdline"]):
        try:
            info = process.info
            if any(Path(arg).name in names for arg in (info.get("cmdline") or [])[1:]):
                matches.append(
                    {
                        "pid": info["pid"],
                        "created": info["create_time"],
                        "cwd": info.get("cwd"),
                    }
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return matches


def inventory(root, manifest):
    root = root.resolve()
    if manifest["schema_version"] != 1:
        raise ValueError("Unsupported recovery manifest")
    plan = read_json(sealed(root, manifest["protocol"]))
    view = read_json(sealed(root, manifest["view_support"]))
    if view["frozen_protocol_sha256"] != manifest["protocol"]["sha256"]:
        raise ValueError("Source-view support belongs to another protocol")
    verified = {}
    for entry in manifest["inputs"]:
        sealed(root, entry)
        verified[entry["path"]] = entry["sha256"]
    for runtime in manifest["runtimes"]:
        directory = inside(root, runtime["directory"])
        for name, expected in runtime["files"].items():
            path = inside(root, str(directory.relative_to(root) / name))
            if checksum(path) != expected:
                raise ValueError(f"Frozen runtime changed: {name}")
    workers = []
    for producer in manifest["producers"]:
        worker = read_json(sealed(root, producer["worker"]))
        sealed(root, producer["script"])
        if inside(root, worker["script"]) != sealed(root, producer["script"]):
            raise ValueError("Producer script identity changed")
        workers.append(
            {
                "role": producer["role"],
                "pid": worker["pid"],
                "created": worker["created"],
                "state": process_state(worker),
            }
        )
    research = inside(root, manifest["research_data"])
    videos, jobs, annotations = database_snapshot(research)
    _main_videos, main_jobs, main_annotations = database_snapshot(
        inside(root, manifest["main_data"])
    )
    requests, supports = plan["requests"], view["cases"]
    expected = manifest["expected"]
    if len(requests) != expected["clips"] or len(supports) != len(requests):
        raise ValueError("Frozen experiment scope changed")
    totals = dict.fromkeys(
        ("clips", "frames", "rows", "family_eligible", "side_eligible"), 0
    )
    native = inside(root, manifest["native_receipts"])
    features = inside(root, manifest["feature_receipts"])
    audit = inside(root, manifest["input_audit_receipts"])
    cases = []
    for ordinal, (request, support) in enumerate(zip(requests, supports, strict=True)):
        video = videos[support["video_id"]]
        source = inside(root, video["path"])
        if (
            checksum(source) != video["sha256"]
            or video["sha256"] != support["source_sha256"]
        ):
            raise ValueError("Source bytes differ from the frozen experiment")
        times = read_json(catalog_path(root, research, video["id"], "timestamps.json"))
        if (
            len(times) != support["native_frames"]
            or len(times) != video["frame_count"]
            or not all(type(t) in (int, float) and math.isfinite(t) for t in times)
            or not all(b > a for a, b in itertools.pairwise(times))
        ):
            raise ValueError("Native source clock changed")
        if "execution" in manifest:
            source_clock(root, manifest, request, video, times)
        doc = json.loads(annotations[video["id"]])
        if doc.get("events") or doc.get("track_assignments"):
            raise ValueError("Research input acquired event or identity annotations")
        stages = {}
        receipt_path = native / f"request-{ordinal:02d}.json"
        receipt = read_json(receipt_path) if receipt_path.exists() else None
        if receipt and (
            receipt["request"] != request or receipt["source_sha256"] != video["sha256"]
        ):
            raise ValueError("Native receipt belongs to another source or request")
        for stage in ("players", "shuttle"):
            candidates = [
                job
                for job in jobs.values()
                if job.get("video_id") == video["id"] and job["kind"] == stage
            ]
            if receipt:
                candidates = [jobs[receipt["runs"][stage]]]
            evidence = []
            for job in candidates:
                path = catalog_path(
                    root, research, video["id"], "runs", component(job["id"]) + ".json"
                )
                valid = False
                if path.exists():
                    run = read_json(path)
                    valid = (
                        job["status"] == "completed"
                        and run["video_id"] == video["id"]
                        and run["stage"] == stage
                        and run["video_sha256"] == video["sha256"]
                        and run["cut_frames"] == support["cut_frames"]
                        and [f["frame"] for f in run["frames"]]
                        == list(range(len(times)))
                        and all(
                            abs(f["time_s"] - t) < 0.00002
                            for f, t in zip(run["frames"], times, strict=True)
                        )
                    )
                    if not valid or (
                        receipt and checksum(path) != receipt["run_sha256"][stage]
                    ):
                        raise ValueError(
                            "Existing native artifact is inconsistent; preserve and investigate"
                        )
                if receipt and not valid:
                    raise ValueError("Receipted native work is not complete")
                evidence.append(
                    {
                        "job_id": job["id"],
                        "status": job["status"],
                        "reusable": valid,
                        "artifact_sha256": checksum(path) if path.exists() else None,
                    }
                )
            stages[stage] = evidence
        feature_path, audit_path = (
            features / receipt_path.name,
            audit / receipt_path.name,
        )
        if feature_path.exists():
            feature = read_json(feature_path)
            if (
                not receipt
                or feature["request"] != request
                or feature["evidence_sha256"] != checksum(receipt_path)
            ):
                raise ValueError("Feature/native receipt chain changed")
            if checksum(feature_path.with_suffix(".npz")) != feature["features_sha256"]:
                raise ValueError("Feature archive bytes changed")
        if audit_path.exists():
            proof = read_json(audit_path)
            if (
                not receipt
                or not feature_path.exists()
                or proof["native_receipt_sha256"] != checksum(receipt_path)
                or proof["feature_receipt_sha256"] != checksum(feature_path)
            ):
                raise ValueError("Input-audit receipt chain changed")
        cases.append(
            {
                "ordinal": ordinal,
                "video_id": video["id"],
                "video_document_sha256": hashlib.sha256(encoded(video)).hexdigest(),
                "stages": stages,
                "native_receipt": bool(receipt),
                "features_receipt": feature_path.exists(),
                "input_audit_receipt": audit_path.exists(),
            }
        )
        for key, value in {
            "clips": 1,
            "frames": len(times),
            "rows": len(request["source_ids"]),
            "family_eligible": request["family_eligible_rows"],
            "side_eligible": request["side_eligible_rows"],
        }.items():
            totals[key] += value
    if totals != expected:
        raise ValueError("Frozen denominators changed")
    matching = matching_producers(manifest["producers"])
    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "totals": totals,
        "workers": workers,
        "matching_producer_processes": matching,
        "original_workers_proven_stopped": not matching
        and all(w["state"].startswith("original_exited") for w in workers),
        "cases": cases,
        "verified_inputs": verified,
        "main_annotation_document_sha256": {
            key: hashlib.sha256(raw.encode()).hexdigest()
            for key, raw in main_annotations.items()
        },
        "active_main_jobs": [
            {k: job.get(k) for k in ("id", "status", "owner_pid", "owner_started")}
            for job in main_jobs.values()
            if job["status"] in {"queued", "running"}
        ],
        "inference_or_prediction_opening": False,
        "Store_or_annotation_mutations": False,
        "execution_authorized_by_inventory": False,
    }


def encoded(value):
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode("utf-8")


def create_json(path, value):
    """Publish once, atomically; an existing receipt is never replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def output_lock(output):
    """OS-owned lock survives neither process exit nor a reused PID."""
    output.mkdir(parents=True, exist_ok=True)
    with (output / "recovery.lock").open("a+b") as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def raw_annotation_hashes(folder):
    return {
        key: hashlib.sha256(raw.encode()).hexdigest()
        for key, raw in database_snapshot(folder)[2].items()
    }


def prepare_attempt(root, manifest, output, phase):
    """Inspect before any Store constructor and retain an immutable lineage."""
    report = inventory(root, manifest)
    if not report["original_workers_proven_stopped"]:
        raise RuntimeError(
            "Original producer is live or unverifiable; recovery refused"
        )
    identity = {
        "manifest_sha256": hashlib.sha256(encoded(manifest)).hexdigest(),
        "main_annotation_document_sha256": report["main_annotation_document_sha256"],
        "video_document_sha256": {
            case["video_id"]: case["video_document_sha256"] for case in report["cases"]
        },
    }
    lineage = output / "lineage.json"
    if lineage.exists():
        if read_json(lineage) != identity:
            raise ValueError("Recovery lineage or main annotations changed")
    else:
        create_json(lineage, identity)
    code = checksum(Path(__file__))
    phase_path = output / (phase + "-recipe.json")
    if phase_path.exists():
        if read_json(phase_path)["code_sha256"] != code:
            raise ValueError(
                "Execution code changed; inspect before resuming this phase"
            )
    else:
        create_json(phase_path, {"code_sha256": code})
    attempt = output / "attempts" / uuid4().hex
    attempt.mkdir(parents=True)
    create_json(attempt / "inventory-before.json", report)
    for name in ("main_data", "research_data"):
        folder = inside(root, manifest[name])
        source = folder / "catalog.sqlite3"
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db:
            with sqlite3.connect(attempt / (name + "-before.sqlite3")) as backup:
                db.backup(backup)
    create_json(
        attempt / "worker.json",
        {
            "pid": os.getpid(),
            "created": psutil.Process().create_time(),
            "cwd": str(Path.cwd()),
            "script": str(Path(__file__).resolve()),
            "phase": phase,
            "code_sha256": code,
            **identity,
        },
    )
    return attempt, report


def bind_runtime(root, manifest, name):
    """Only call in a fresh CLI process; never mix current and frozen packages."""
    if any(key == "badminton" or key.startswith("badminton.") for key in sys.modules):
        raise RuntimeError("Frozen runtime requires a fresh process")
    stable_frozen(root, manifest)
    directory = inside(root, manifest["execution"][name])
    if directory not in {
        inside(root, runtime["directory"]) for runtime in manifest["runtimes"]
    }:
        raise ValueError("Execution runtime was not sealed by inventory")
    os.environ["BADMINTON_ROOT"] = str(root)
    os.environ["BADMINTON_DATA_DIR"] = str(inside(root, manifest["main_data"]))
    os.environ["BADMINTON_WEIGHTS_DIR"] = str(root / "models/weights")
    sys.path.insert(
        0, str(directory / "backend" if name == "feature_runtime" else directory)
    )
    return directory


def recovery_output(root, manifest, output):
    path = inside(root, output)
    cache = root / ".cache"
    if path == cache or not path.is_relative_to(cache):
        raise ValueError(
            "New recovery evidence must use a separate .cache subdirectory"
        )
    protected = [
        inside(root, manifest[key])
        for key in (
            "main_data",
            "research_data",
            "native_receipts",
            "feature_receipts",
            "input_audit_receipts",
        )
    ]
    protected.extend(
        inside(root, runtime["directory"]) for runtime in manifest["runtimes"]
    )
    protected.extend(
        inside(root, e["path"])
        for e in [manifest["protocol"], manifest["view_support"], *manifest["inputs"]]
    )
    if any(path.is_relative_to(p) or p.is_relative_to(path) for p in protected):
        raise ValueError("Recovery output overlaps preserved input evidence")
    return path


def receipt_for(root, manifest, output, stage, ordinal):
    name = f"request-{ordinal:02d}.json"
    prior = inside(root, manifest[stage + "_receipts"]) / name
    recovered = output / stage / name
    if prior.exists() and recovered.exists():
        raise ValueError(
            "Original and recovered receipts conflict; preserve and inspect"
        )
    return prior if prior.exists() else recovered


def verify_native(root, data, video, support, job):
    path = catalog_path(root, data, video["id"], "runs", component(job["id"]) + ".json")
    if not path.exists():
        if job["status"] == "completed":
            raise ValueError(
                "Completed native job lost its artifact; do not repeat silently"
            )
        return None
    run = read_json(path)
    times = read_json(catalog_path(root, data, video["id"], "timestamps.json"))
    valid = (
        job["status"] == "completed"
        and job["video_id"] == video["id"]
        and run["video_id"] == video["id"]
        and run["video_sha256"] == video["sha256"] == support["source_sha256"]
        and run["stage"] == job["kind"]
        and run["cut_frames"] == support["cut_frames"]
        and [f["frame"] for f in run["frames"]] == list(range(video["frame_count"]))
        and len(times) == len(run["frames"])
        and all(
            abs(f["time_s"] - t) < 1e-8
            for f, t in zip(run["frames"], times, strict=True)
        )
        and not run.get("requires_tracking_rerun", False)
    )
    if not valid:
        raise ValueError(
            "Existing native artifact is inconsistent; preserve and investigate"
        )
    return path


def select_native(root, data, video, support, jobs, stage, receipt=None):
    candidates = [j for j in jobs if j["kind"] == stage]
    if receipt:
        candidates = [j for j in candidates if j["id"] == receipt["runs"][stage]]
        if len(candidates) != 1:
            raise ValueError("Receipted native job is missing or ambiguous")
    completed = []
    for job in candidates:
        path = verify_native(root, data, video, support, job)
        if path:
            if receipt and checksum(path) != receipt["run_sha256"][stage]:
                raise ValueError("Receipted native bytes changed")
            completed.append(job)
    if len(completed) > 1:
        raise ValueError(
            "Multiple completed native stages require explicit investigation"
        )
    if receipt and not completed:
        raise ValueError("Receipted native stage is not completed")
    return completed[0] if completed else None


def native_recipe(root, manifest, video, doc, support, job, corners):
    """A matching source hash alone does not establish the frozen recipe."""
    data = inside(root, manifest["research_data"])
    path = verify_native(root, data, video, support, job)
    run = read_json(path)
    runtime = inside(root, manifest["execution"]["native_runtime"])
    models = read_json(runtime / "badminton/model_manifest.json")
    kind = job["kind"]
    model = models["player_pose_small" if kind == "players" else "shuttle"]
    expected_signature = [
        [
            support["calibration_start_frame"],
            support["calibration_end_frame"],
            [[p.x, p.y] for p in corners],
        ]
    ]
    if (
        run["start_frame"] != 0
        or run["end_frame"] != video["frame_count"]
        or run["processed_frames"] != video["frame_count"]
        or run["checkpoint_sha256"] != model["sha256"]
        or not run["device"].startswith("cuda")
        or run["scene_annotation_revision"] != doc.revision
        or run["camera_annotation_revision"] != doc.revision
        or run.get("applied_camera_corrections", []) != []
        or (
            kind == "players"
            and (
                run["stride"] != 1
                or run["model_variant"] != "small"
                or run["annotation_revision"] != doc.revision
                or run["calibration_signature"] != expected_signature
            )
        )
        or (
            kind == "shuttle"
            and (
                run["model"] != "TrackNetV3"
                or run["temporal_context_crosses_detected_cuts"]
            )
        )
    ):
        raise ValueError("Native artifact does not implement the frozen recipe")
    pinned = manifest["execution"].get("reusable_artifacts", {}).get(job["id"])
    if pinned and checksum(path) != pinned:
        raise ValueError("Preserved unreceipted native bytes changed")


def native_recovery(root, manifest, output):
    root = root.resolve()
    output = recovery_output(root, manifest, output)
    with output_lock(output):
        attempt, before = prepare_attempt(root, manifest, output, "native")
        bind_runtime(root, manifest, "native_runtime")
        # Required before any threaded PyAV decode in the frozen perception path.
        import torch
        import torchvision  # noqa: F401
        from badminton.jobs import run_local_job
        from badminton.schemas import Calibration, Point, SceneRange
        from badminton.shuttle import track_shuttle
        from badminton.storage import Store
        from badminton.tracking import track_players

        if not torch.cuda.is_available():
            raise RuntimeError(
                "Frozen Windows native recovery requires CUDA; no CPU fallback"
            )

        plan = read_json(sealed(root, manifest["protocol"]))
        view = read_json(sealed(root, manifest["view_support"]))
        court_path = inside(root, manifest["execution"]["court_path"])
        if checksum(court_path) != view["published_homography_sha256"]:
            raise ValueError("Published court geometry changed")
        with court_path.open(encoding="utf-8-sig", newline="") as stream:
            court = next(row for row in csv.DictReader(stream) if row["id"] == "2")
        corners = [
            Point(x=float(court[k + "_x"]) / 1280, y=float(court[k + "_y"]) / 720)
            for k in ("upleft", "upright", "downright", "downleft")
        ]
        main = Store(inside(root, manifest["main_data"]))
        research_data = inside(root, manifest["research_data"])
        completed = []

        def task(parent_id, parent_progress):
            # Construct the research Store only after successful real main admission.
            store = Store(research_data)
            create_json(attempt / "admission.json", {"main_job_id": parent_id})
            for ordinal, (request, support) in enumerate(
                zip(plan["requests"], view["cases"], strict=True)
            ):
                stable_frozen(root, manifest)
                video = store.video(support["video_id"])
                stable_source(
                    root,
                    manifest,
                    video,
                    support,
                    request,
                    before["cases"][ordinal]["video_document_sha256"],
                )
                if (video["width"], video["height"]) != (1280, 720):
                    raise ValueError("Frozen native source dimensions changed")
                receipt_path = receipt_for(root, manifest, output, "native", ordinal)
                receipt = read_json(receipt_path) if receipt_path.exists() else None
                doc = store.annotations(video["id"])
                if receipt:
                    if (
                        receipt["request"] != request
                        or receipt["view_support_sha256"]
                        != manifest["view_support"]["sha256"]
                        or receipt["annotation_revision"] != doc.revision
                        or receipt["annotation_sha256"]
                        != hashlib.sha256(
                            json.dumps(doc.model_dump(), sort_keys=True).encode()
                        ).hexdigest()
                    ):
                        raise ValueError("Receipted source-view annotations changed")
                elif not doc.calibrations:
                    if doc.revision or store.jobs(video["id"]) or doc.scene_ranges:
                        raise ValueError(
                            "Uninitialized case acquired work; preserve and investigate"
                        )
                    start = support["calibration_start_frame"]
                    doc = store.save_annotations(
                        video["id"],
                        doc.model_copy(
                            update={
                                "calibrations": [
                                    Calibration(
                                        start_frame=start,
                                        end_frame=support["calibration_end_frame"],
                                        corners=corners,
                                    )
                                ],
                                "scene_ranges": [
                                    SceneRange(
                                        id="unsupported-source-prefix",
                                        start_frame=0,
                                        end_frame=start,
                                        scene="unknown",
                                        notes="Source-only coding-agent view support: closeup/wipe; no usable published court geometry. Exact event/scene truth unadjudicated.",
                                    )
                                ]
                                if start
                                else [],
                            }
                        ),
                    )
                if (
                    doc.events
                    or doc.track_assignments
                    or doc.shuttle_points
                    or doc.review_windows
                ):
                    raise ValueError("Research input contains manually reviewed truth")
                expected_calibration = Calibration(
                    start_frame=support["calibration_start_frame"],
                    end_frame=support["calibration_end_frame"],
                    corners=corners,
                )
                expected_scenes = (
                    [(0, support["calibration_start_frame"], "unknown")]
                    if support["calibration_start_frame"]
                    else []
                )
                if (
                    doc.calibrations != [expected_calibration]
                    or [(r.start_frame, r.end_frame, r.scene) for r in doc.scene_ranges]
                    != expected_scenes
                    or doc.camera_corrections
                ):
                    raise ValueError("Research geometry or source-view support changed")
                runs, summaries = {}, {}
                for stage in ("players", "shuttle"):
                    prior = select_native(
                        root,
                        research_data,
                        video,
                        support,
                        store.jobs(video["id"]),
                        stage,
                        receipt,
                    )
                    if prior:
                        native_recipe(
                            root, manifest, video, doc, support, prior, corners
                        )
                        runs[stage], summaries[stage] = prior["id"], prior["summary"]
                    else:

                        def native(identifier, progress):
                            runs[stage] = identifier
                            create_json(
                                attempt / f"request-{ordinal:02d}-{stage}.json",
                                {
                                    "research_job_id": identifier,
                                    "main_job_id": parent_id,
                                    "previous_job_ids": [
                                        j["id"]
                                        for j in store.jobs(video["id"])
                                        if j["kind"] == stage and j["id"] != identifier
                                    ],
                                },
                            )
                            destination = catalog_path(
                                root,
                                research_data,
                                video["id"],
                                "runs",
                                identifier + ".json",
                            )
                            last = -1

                            def throttled(value):
                                nonlocal last
                                tick = int(value * 100)
                                if tick != last:
                                    last = tick
                                    progress(value)
                                    parent_progress(
                                        (
                                            ordinal
                                            + ((0 if stage == "players" else 1) + value)
                                            / 2
                                        )
                                        / len(plan["requests"])
                                    )

                            if stage == "players":
                                return track_players(
                                    video,
                                    root,
                                    research_data,
                                    doc,
                                    0,
                                    video["frame_count"],
                                    1,
                                    throttled,
                                    destination,
                                    "small",
                                )
                            return track_shuttle(
                                video,
                                root,
                                research_data,
                                0,
                                video["frame_count"],
                                throttled,
                                destination,
                                doc,
                            )

                        summaries[stage] = run_local_job(
                            store, stage, video["id"], native
                        )
                        native_recipe(
                            root,
                            manifest,
                            video,
                            doc,
                            support,
                            next(
                                j
                                for j in store.jobs(video["id"])
                                if j["id"] == runs[stage]
                            ),
                            corners,
                        )
                    print(
                        json.dumps(
                            {
                                "ordinal": ordinal,
                                "stage": stage,
                                "job_id": runs[stage],
                                "reused": prior is not None,
                            }
                        ),
                        flush=True,
                    )
                stable_source(
                    root,
                    manifest,
                    store.video(video["id"]),
                    support,
                    request,
                    before["cases"][ordinal]["video_document_sha256"],
                )
                if not receipt:
                    create_json(
                        receipt_path,
                        {
                            "request_ordinal": ordinal,
                            "request": request,
                            "video_id": video["id"],
                            "source_sha256": video["sha256"],
                            "source_frames": video["frame_count"],
                            "view_support_sha256": manifest["view_support"]["sha256"],
                            "annotation_revision": doc.revision,
                            "annotation_sha256": hashlib.sha256(
                                json.dumps(doc.model_dump(), sort_keys=True).encode()
                            ).hexdigest(),
                            "calibration_start_frame": support[
                                "calibration_start_frame"
                            ],
                            "cut_frames": support["cut_frames"],
                            "runs": runs,
                            "run_sha256": {
                                k: checksum(
                                    catalog_path(
                                        root,
                                        research_data,
                                        video["id"],
                                        "runs",
                                        v + ".json",
                                    )
                                )
                                for k, v in runs.items()
                            },
                            "summaries": summaries,
                            "shot_heads_opened": False,
                        },
                    )
                completed.append(
                    {
                        "ordinal": ordinal,
                        "path": receipt_path.relative_to(root).as_posix(),
                        "sha256": checksum(receipt_path),
                    }
                )
                parent_progress((ordinal + 1) / len(plan["requests"]))
            stable_frozen(root, manifest)
            if (
                raw_annotation_hashes(inside(root, manifest["main_data"]))
                != before["main_annotation_document_sha256"]
            ):
                raise ValueError("Main annotations changed during native recovery")
            create_json(
                attempt / "native-completed.json",
                {
                    "cases": completed,
                    "totals": before["totals"],
                    "main_job_id": parent_id,
                    "main_annotations_unchanged": True,
                    "shot_heads_opened": False,
                },
            )
            return {
                "clips": len(completed),
                "shot_heads_opened": False,
                "main_annotations_unchanged": True,
            }

        result = run_local_job(main, "feature-preparation", None, task)
        # This receipt is written only after run_local_job persisted parent success.
        create_json(attempt / "admission-released.json", result)
        return {"attempt": str(attempt.relative_to(root)), **result}


FAMILIES = ("clear", "lift", "net", "drop", "smash", "drive", "other", "serve")
SIDES = ("forehand", "backhand")


def source_clock(root, manifest, request, video, times):
    directory = inside(root, manifest["execution"]["source_receipt_directory"])
    for key in ("set_id", "rally_id"):
        if type(request[key]) is not int or request[key] <= 0:
            raise ValueError("Invalid published source request")
    path = inside(
        root,
        str(
            directory / f"match2-set{request['set_id']}-rally{request['rally_id']}.json"
        ),
    )
    source = read_json(path)
    frames = source["frames"]
    if (
        source["request"] != request
        or source["clip_sha256"] != video["sha256"]
        or len(frames) != len(times)
        or [f["local_frame"] for f in frames] != list(range(len(times)))
        or [f["parent_cfr_hint"] for f in frames]
        != list(
            range(request["lower_cfr_hint"], request["upper_cfr_hint_inclusive"] + 1)
        )
        or not all(
            abs(t - (f["parent_time_s"] - frames[0]["parent_time_s"])) <= 1e-8
            for t, f in zip(times, frames, strict=True)
        )
    ):
        raise ValueError("Explicit published source clock or request changed")
    return path, source


def load_helper(root, manifest, path, name):
    entry = next(e for e in manifest["inputs"] if e["path"] == path)
    spec = importlib.util.spec_from_file_location(name, sealed(root, entry))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def successful_native(root, manifest, output):
    """Require a new, genuine successful main parent; never rewrite the old job."""
    _videos, jobs, _annotations = database_snapshot(inside(root, manifest["main_data"]))
    for path in sorted((output / "attempts").glob("*/native-completed.json")):
        released = path.with_name("admission-released.json")
        if not released.exists():
            continue
        proof = read_json(path)
        if jobs[proof["main_job_id"]]["status"] != "completed":
            raise ValueError("Native parent completion disagrees with Store")
        if (
            proof["totals"] != manifest["expected"]
            or len(proof["cases"]) != manifest["expected"]["clips"]
        ):
            raise ValueError("Native completion scope changed")
        for ordinal, case in enumerate(proof["cases"]):
            if case["ordinal"] != ordinal or sealed(root, case) != receipt_for(
                root, manifest, output, "native", ordinal
            ):
                raise ValueError("Native completion receipt chain changed")
        return path
    raise ValueError("All native inputs need a successfully released real main parent")


def label_rows(root, manifest, plan):
    path = manifest["execution"]["labels"]
    entry = next(e for e in manifest["inputs"] if e["path"] == path)
    if entry["sha256"] != plan["normalized_labels_sha256"]:
        raise ValueError("Labels no longer belong to frozen protocol")
    all_ids = [i for request in plan["requests"] for i in request["source_ids"]]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("Duplicate source IDs")
    selected = set(all_ids)
    rows = {}
    with sealed(root, entry).open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["id"] in selected:
                if row["id"] in rows:
                    raise ValueError("Duplicate normalized source row")
                rows[row["id"]] = row
    if set(rows) != selected:
        raise ValueError("Frozen source row is missing")
    if len(rows) != manifest["expected"]["rows"] or any(
        sum(bool(r[task + "_eligible"]) for r in rows.values())
        != manifest["expected"][task + "_eligible"]
        for task in ("family", "side")
    ):
        raise ValueError("Frozen eligible label denominators changed")
    return rows


def cache_case(
    root,
    manifest,
    output,
    ordinal,
    request,
    rows,
    video,
    evidence_path,
    runs,
    context,
    pack_hitter,
    associate,
    weak_targets,
):
    import numpy as np

    target = output / "feature" / f"request-{ordinal:02d}.npz"
    if target.exists():
        raise ValueError("Unreceipted feature archive exists; preserve and investigate")
    evidence = read_json(evidence_path)
    times = np.asarray(context.times)
    source_path, source = source_clock(root, manifest, request, video, times)
    hints = np.asarray([f["parent_cfr_hint"] for f in source["frames"]], dtype=np.int64)
    labels = [rows[i] for i in request["source_ids"]]
    weak = [r | {"source_start_frame": r["source_frame"]} for r in labels]
    excluded = {
        p["frame"]
        for p, s in zip(
            context.players["frames"], context.shuttle["frames"], strict=True
        )
        if p.get("scene", "live") != "live"
        or not p.get("calibration_valid", False)
        or s.get("scene", "live") != "live"
    }
    bags, _ = weak_targets(
        weak, hints, excluded_frames=excluded, cut_frames=context.cuts
    )
    bags = {bag["id"]: bag for bag in bags}
    r2, r3, a2, a3, family, side, records = [], [], [], [], [], [], []
    for row in labels:
        indices = np.flatnonzero(hints == row["source_frame"] - 1)
        if len(indices) != 1:
            raise ValueError("Published weak cue is not uniquely source-aligned")
        cue = int(indices[0])
        association = associate(video, context.players, row, float(times[cue]))
        packed2 = (
            pack_hitter(
                context.body, association["track_id"], bags[row["id"]]["indices"], cue
            )
            if association["status"] == "weak_association"
            else None
        )
        packed3 = (
            context.pack(packed2["navigation_frame"], association["track_id"])
            if packed2
            else None
        )
        if packed3 is not None:
            np.testing.assert_array_equal(
                packed3["features"][:254], packed2["features"]
            )
        r2.append(packed2["features"] if packed2 else np.zeros(254, np.float32))
        r3.append(packed3["features"] if packed3 else np.zeros(371, np.float32))
        a2.append(packed2 is not None)
        a3.append(packed3 is not None)
        target_family = "serve" if row["kind"] == "serve" else row["family"]
        family.append(
            FAMILIES.index(target_family)
            if row["family_eligible"] and target_family in FAMILIES
            else -1
        )
        side.append(
            SIDES.index(row["side"])
            if row["side_eligible"] and row["side"] in SIDES
            else -1
        )
        records.append(
            {
                "id": row["id"],
                "cue_local_frame": cue,
                "source_frame": row["source_frame"],
                "association": association,
                "weak_bag": bags[row["id"]],
                "r2_available": packed2 is not None,
                "r3_available": packed3 is not None,
                "navigation_frame": packed2["navigation_frame"] if packed2 else None,
                "r3_context_start_frame": packed3["context_start_frame"]
                if packed3
                else None,
                "r3_context_end_frame": packed3["context_end_frame"]
                if packed3
                else None,
                "family_target": target_family,
                "family_eligible": row["family_eligible"],
                "side_target": row["side"],
                "side_eligible": row["side_eligible"],
                "independently_adjudicated": False,
            }
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves evidence after interruption; no silent replacement.
    with target.open("xb") as stream:
        np.savez_compressed(
            stream,
            r2_features=np.asarray(r2, np.float32),
            r3_features=np.asarray(r3, np.float32),
            r2_available=np.asarray(a2, bool),
            r3_available=np.asarray(a3, bool),
            family=np.asarray(family, np.int64),
            side=np.asarray(side, np.int64),
        )
    create_json(
        target.with_suffix(".json"),
        {
            "request_ordinal": ordinal,
            "request": request,
            "video_id": video["id"],
            "source_sha256": video["sha256"],
            "evidence_sha256": checksum(evidence_path),
            "native_run_sha256": evidence["run_sha256"],
            "source_metadata_sha256": checksum(source_path),
            "features_sha256": checksum(target),
            "records": records,
            "head_predictions_opened": False,
        },
    )
    return target.with_suffix(".json")


def audit_features(
    root,
    manifest,
    ordinal,
    request,
    support,
    video,
    evidence_path,
    meta_path,
    rows,
    context,
):
    """Recheck source truth/masks/guards without trusting cache-producer summaries."""
    import numpy as np

    evidence, meta = read_json(evidence_path), read_json(meta_path)
    if (
        meta["request"] != request
        or meta["native_run_sha256"] != evidence["run_sha256"]
        or meta["video_id"] != video["id"]
        or meta["source_sha256"] != video["sha256"]
        or meta["evidence_sha256"] != checksum(evidence_path)
        or checksum(meta_path.with_suffix(".npz")) != meta["features_sha256"]
    ):
        raise ValueError("Feature/native/source receipt chain changed")
    with np.load(meta_path.with_suffix(".npz"), allow_pickle=False) as archive:
        data = {key: archive[key] for key in archive.files}
    n = len(request["source_ids"])
    if set(data) != {
        "r2_features",
        "r3_features",
        "r2_available",
        "r3_available",
        "family",
        "side",
    } or not all(np.isfinite(v).all() for v in data.values()):
        raise ValueError("Invalid or nonfinite feature archive")
    for prefix, dim in (("r2", 254), ("r3", 371)):
        values, available = data[prefix + "_features"], data[prefix + "_available"]
        if (
            values.shape != (n, dim)
            or values.dtype != np.float32
            or available.shape != (n,)
            or available.dtype != np.bool_
            or np.any(values[~available])
        ):
            raise ValueError("Feature shapes, dtypes or unavailable rows changed")
        masks = values[available, 252:254]
        if not np.isin(masks, [0, 1]).all() or not (masks.sum(1) >= 1).all():
            raise ValueError("Body availability masks changed")
    if np.any(data["r3_available"] & ~data["r2_available"]):
        raise ValueError("R3 availability lacks R2 input")
    np.testing.assert_array_equal(
        data["r3_features"][data["r3_available"], :254],
        data["r2_features"][data["r3_available"]],
    )
    for task in ("family", "side"):
        if data[task].shape != (n,) or data[task].dtype != np.int64:
            raise ValueError("Targets must be original int64 row arrays")
    if [r["id"] for r in meta["records"]] != request["source_ids"]:
        raise ValueError("Source rows changed order or disappeared")
    times = np.asarray(context.times)
    source_path, source = source_clock(root, manifest, request, video, times)
    if checksum(source_path) != meta["source_metadata_sha256"]:
        raise ValueError("Published source metadata changed")
    start = support["calibration_start_frame"]
    if [f["calibration_valid"] for f in context.players["frames"]] != [
        i >= start for i in range(len(times))
    ]:
        raise ValueError("Source-view calibration expiry changed")
    for cut in context.players["cut_frames"]:
        left = {
            p["track_id"] for f in context.players["frames"][:cut] for p in f["players"]
        }
        right = {
            p["track_id"] for f in context.players["frames"][cut:] for p in f["players"]
        }
        if left & right:
            raise ValueError("Player identity crossed a camera cut")
    for i, record in enumerate(meta["records"]):
        row = rows[record["id"]]
        cue = record["cue_local_frame"]
        if source["frames"][cue]["parent_cfr_hint"] != row["source_frame"] - 1:
            raise ValueError("Weak label/source clock changed")
        family = "serve" if row["kind"] == "serve" else row["family"]
        if int(data["family"][i]) != (
            FAMILIES.index(family)
            if row["family_eligible"] and family in FAMILIES
            else -1
        ) or int(data["side"][i]) != (
            SIDES.index(row["side"])
            if row["side_eligible"] and row["side"] in SIDES
            else -1
        ):
            raise ValueError("Targets changed or unknown truth was relabeled")
        association = record["association"]
        if association["status"] == "weak_association":
            hit = np.asarray(
                [float(row["raw"]["player_location_" + axis]) for axis in ("x", "y")]
            )
            other = np.asarray(
                [float(row["raw"]["opponent_location_" + axis]) for axis in ("x", "y")]
            )
            distances = []
            for frame in context.players["frames"]:
                if abs(frame["time_s"] - times[cue]) > 0.1 + 1e-9:
                    continue
                if (
                    frame.get("scene", "live") != "live"
                    or not frame["calibration_valid"]
                ):
                    raise ValueError("Hitter association crossed excluded context")
                for player in frame["players"]:
                    if player.get("track_id") != association["track_id"]:
                        continue
                    box = player["box"]
                    foot = np.asarray([(box[0] + box[2]) / 2, box[3]])
                    d, margin = np.linalg.norm(foot - hit), np.linalg.norm(foot - other)
                    diagonal = math.hypot(video["width"], video["height"])
                    if d <= 0.04 * diagonal and margin - d >= 0.01 * diagonal:
                        distances.append(float(d))
            if (
                len(distances) < 3
                or len(distances) != association["support_frames"]
                or abs(
                    float(np.median(distances)) - association["median_foot_distance_px"]
                )
                >= 1e-8
            ):
                raise ValueError("Weak source hitter support changed")
        for prefix in ("r2", "r3"):
            if bool(data[prefix + "_available"][i]) != record[prefix + "_available"]:
                raise ValueError("Availability mask and record disagree")
            if not record[prefix + "_available"]:
                continue
            frame = record["navigation_frame"]
            left, right = (
                map(int, context.body["context"][frame])
                if prefix == "r2"
                else (record["r3_context_start_frame"], record["r3_context_end_frame"])
            )
            if (
                not start <= left <= frame < right <= len(times)
                or context.blocked[left:right].any()
                or any(left < c < right for c in context.cuts)
            ):
                raise ValueError(
                    "Feature context crossed a source boundary or excluded scene"
                )
    return {
        "ordinal": ordinal,
        "source_sha256": video["sha256"],
        "native_receipt_sha256": checksum(evidence_path),
        "feature_receipt_sha256": checksum(meta_path),
        "totals": {
            "clips": 1,
            "frames": len(times),
            "rows": n,
            "family_eligible": int((data["family"] >= 0).sum()),
            "side_eligible": int((data["side"] >= 0).sum()),
        },
        "available": {key: int(data[key + "_available"].sum()) for key in ("r2", "r3")},
        "head_predictions_opened": False,
    }


def feature_recovery(root, manifest, output):
    root = root.resolve()
    output = recovery_output(root, manifest, output)
    with output_lock(output):
        attempt, before = prepare_attempt(root, manifest, output, "features")
        native_completion = successful_native(root, manifest, output)
        bind_runtime(root, manifest, "feature_runtime")
        from badminton.contact_features import weak_targets
        from badminton.jobs import run_local_job
        from badminton.storage import Store
        from badminton.stroke_context import FEATURE_DIM, StrokeContext

        if FEATURE_DIM != 371:
            raise ValueError("Frozen R3 dimension changed")
        pack = load_helper(
            root, manifest, manifest["execution"]["pack_helper"], "frozen_pack"
        )
        associate = load_helper(
            root,
            manifest,
            manifest["execution"]["association_helper"],
            "frozen_association",
        )
        plan = read_json(sealed(root, manifest["protocol"]))
        view = read_json(sealed(root, manifest["view_support"]))
        rows = label_rows(root, manifest, plan)
        main = Store(inside(root, manifest["main_data"]))

        def task(job_id, progress):
            store = Store(inside(root, manifest["research_data"]))
            checks, totals = [], dict.fromkeys(manifest["expected"], 0)
            for ordinal, (request, support) in enumerate(
                zip(plan["requests"], view["cases"], strict=True)
            ):
                evidence_path = receipt_for(root, manifest, output, "native", ordinal)
                evidence = read_json(evidence_path)
                stable_frozen(root, manifest)
                video = store.video(support["video_id"])
                stable_source(
                    root,
                    manifest,
                    video,
                    support,
                    request,
                    before["cases"][ordinal]["video_document_sha256"],
                )
                if (
                    store.annotations(video["id"]).revision
                    != evidence["annotation_revision"]
                ):
                    raise ValueError("Native source-view annotation revision changed")
                runs = {}
                for stage in ("players", "shuttle"):
                    job = select_native(
                        root,
                        store.data,
                        video,
                        support,
                        store.jobs(video["id"]),
                        stage,
                        evidence,
                    )
                    runs[stage] = read_json(
                        catalog_path(
                            root, store.data, video["id"], "runs", job["id"] + ".json"
                        )
                    )
                context = StrokeContext(
                    video,
                    runs["players"],
                    runs["shuttle"],
                    store.annotations(video["id"]),
                )
                meta_path = receipt_for(root, manifest, output, "feature", ordinal)
                if not meta_path.exists():
                    meta_path = cache_case(
                        root,
                        manifest,
                        output,
                        ordinal,
                        request,
                        rows,
                        video,
                        evidence_path,
                        runs,
                        context,
                        pack.pack_hitter,
                        associate.associate_singles_hitter,
                        weak_targets,
                    )
                check = audit_features(
                    root,
                    manifest,
                    ordinal,
                    request,
                    support,
                    video,
                    evidence_path,
                    meta_path,
                    rows,
                    context,
                )
                audit_path = receipt_for(root, manifest, output, "input_audit", ordinal)
                if audit_path.exists():
                    prior = read_json(audit_path)
                    if any(
                        prior[k] != check[k]
                        for k in ("native_receipt_sha256", "feature_receipt_sha256")
                    ):
                        raise ValueError("Existing input-audit receipt chain changed")
                else:
                    create_json(audit_path, check)
                checks.append(
                    {
                        "path": audit_path.relative_to(root).as_posix(),
                        "sha256": checksum(audit_path),
                        "recomputed": check,
                    }
                )
                for key in totals:
                    totals[key] += check["totals"][key]
                progress((ordinal + 1) / len(plan["requests"]))
                print(
                    json.dumps({"audited_clips": ordinal + 1, "totals": totals}),
                    flush=True,
                )
            stable_frozen(root, manifest)
            if (
                totals != manifest["expected"]
                or raw_annotation_hashes(inside(root, manifest["main_data"]))
                != before["main_annotation_document_sha256"]
            ):
                raise ValueError("Complete-input denominator or annotation gate failed")
            proof = {
                "totals": totals,
                "checks": checks,
                "native_completion": {
                    "path": native_completion.relative_to(root).as_posix(),
                    "sha256": checksum(native_completion),
                },
                "main_job_id": job_id,
                "main_annotations_unchanged": True,
                "head_predictions_opened": False,
            }
            create_json(attempt / "features-completed.json", proof)
            return {"totals": totals, "head_predictions_opened": False}

        result = run_local_job(main, "feature-preparation", None, task)
        create_json(attempt / "admission-released.json", result)
        return {"attempt": str(attempt.relative_to(root)), **result}


def class_metrics(truth, prediction, names):
    import numpy as np

    matrix = np.zeros((len(names), len(names) + 1), np.int64)
    for t, p in zip(truth, prediction, strict=True):
        if t >= 0:
            matrix[int(t), int(p) if p >= 0 else len(names)] += 1
    per = {}
    for k, name in enumerate(names):
        tp, support, predicted = (
            int(matrix[k, k]),
            int(matrix[k].sum()),
            int(matrix[:, k].sum()),
        )
        per[name] = {
            "support": support,
            "predicted": predicted,
            "tp": tp,
            "fp": predicted - tp,
            "fn": support - tp,
            "precision": tp / predicted if predicted else None,
            "recall": tp / support if support else None,
            "f1": 2 * tp / (support + predicted) if support + predicted else None,
        }
    supported = [name for name in names if per[name]["support"]]
    total, answered, correct = (
        int(matrix.sum()),
        int(matrix[:, :-1].sum()),
        int(matrix[:, :-1].trace()),
    )
    return {
        "per_class": per,
        "source_rows": total,
        "unavailable_truth_rows": int((truth < 0).sum()),
        "answered": answered,
        "strict_accuracy": correct / total if total else None,
        "precision_given_answered": correct / answered if answered else None,
        "macro_f1_supported": float(np.mean([per[n]["f1"] or 0 for n in supported]))
        if supported
        else None,
        "balanced_recall": float(np.mean([per[n]["recall"] for n in supported]))
        if supported
        else None,
        "supported_classes": supported,
        "confusion": matrix.tolist(),
        "confusion_columns": [*names, "unanswered"],
    }


def score_probabilities(data, probabilities, available, thresholds=None):
    import numpy as np

    predictions = []
    for j, values in enumerate(probabilities):
        prediction, accepted = values.argmax(1), available.copy()
        if thresholds is not None:
            accepted &= values.max(1) >= np.asarray(thresholds[j])[prediction]
        prediction[~accepted] = -1
        predictions.append(prediction)
    family, side = predictions
    eligible = (data["family"] >= 0) & (data["side"] >= 0)
    correct = (family == data["family"]) & (side == data["side"]) & eligible
    metrics = {
        "family": class_metrics(data["family"], family, FAMILIES),
        "side": class_metrics(data["side"], side, SIDES),
        "family_side_tuple_given_weak_source_hitter_clock": float(
            correct.sum() / eligible.sum()
        )
        if eligible.any()
        else None,
        "joint_eligible_rows": int(eligible.sum()),
        "joint_correct": int(correct.sum()),
        "source_rows": len(family),
        "available_input_rows": int(available.sum()),
        "available_joint_eligible_rows": int((available & eligible).sum()),
        "exact_truth": False,
    }
    return metrics, np.stack(predictions, axis=1)


def feature_completion(root, manifest, output):
    successful_native(root, manifest, output)
    _videos, jobs, _annotations = database_snapshot(inside(root, manifest["main_data"]))
    for path in sorted((output / "attempts").glob("*/features-completed.json")):
        if not path.with_name("admission-released.json").exists():
            continue
        proof = read_json(path)
        if (
            jobs[proof["main_job_id"]]["status"] != "completed"
            or proof["totals"] != manifest["expected"]
            or len(proof["checks"]) != manifest["expected"]["clips"]
        ):
            raise ValueError("Complete input audit disagrees with actual shared Store")
        sealed(root, proof["native_completion"])
        for ordinal, case in enumerate(proof["checks"]):
            if sealed(root, case) != receipt_for(
                root, manifest, output, "input_audit", ordinal
            ):
                raise ValueError("Input-audit lineage changed")
            check = case["recomputed"]
            if (
                check["ordinal"] != ordinal
                or check["native_receipt_sha256"]
                != checksum(receipt_for(root, manifest, output, "native", ordinal))
                or check["feature_receipt_sha256"]
                != checksum(receipt_for(root, manifest, output, "feature", ordinal))
            ):
                raise ValueError("Input-audit transitive receipt chain changed")
        return path
    raise ValueError(
        "Frozen head evaluation requires all source input audits and released admission"
    )


def assembled_features(root, manifest, output):
    import numpy as np

    plan = read_json(sealed(root, manifest["protocol"]))
    chunks = {
        key: []
        for key in (
            "r2_features",
            "r3_features",
            "r2_available",
            "r3_available",
            "family",
            "side",
        )
    }
    ids = []
    for ordinal, request in enumerate(plan["requests"]):
        path = receipt_for(root, manifest, output, "feature", ordinal)
        meta = read_json(path)
        if (
            meta["request"] != request
            or [r["id"] for r in meta["records"]] != request["source_ids"]
            or checksum(path.with_suffix(".npz")) != meta["features_sha256"]
        ):
            raise ValueError("Frozen evaluation inputs changed")
        with np.load(path.with_suffix(".npz"), allow_pickle=False) as archive:
            for key in chunks:
                chunks[key].append(archive[key])
        ids.extend(request["source_ids"])
    data = {key: np.concatenate(value) for key, value in chunks.items()}
    if (
        len(ids) != len(set(ids))
        or len(ids) != manifest["expected"]["rows"]
        or any(
            int((data[task] >= 0).sum()) != manifest["expected"][task + "_eligible"]
            for task in ("family", "side")
        )
    ):
        raise ValueError(
            "All unknown and eligible source denominators must be retained"
        )
    return data, ids


def check_preflight(path, code_sha256, manifest):
    proof = read_json(path)
    if (
        proof.get("schema_version") != 1
        or proof.get("verdict") != "approve"
        or proof.get("code_sha256") != code_sha256
        or proof.get("protocol_sha256") != manifest["protocol"]["sha256"]
        or proof.get("manifest_sha256") != hashlib.sha256(encoded(manifest)).hexdigest()
        or proof.get("blockers") != []
        or not proof.get("reviewer_session")
        or not proof.get("evidence")
    ):
        raise ValueError(
            "Fresh independent exact-code recipe preflight is required before predictions"
        )
    return proof


def evaluation_recovery(root, manifest, output, preflight):
    """One fixed CPU opening of each selected head; never resume by re-predicting."""
    root = root.resolve()
    output = recovery_output(root, manifest, output)
    check_preflight(preflight, checksum(Path(__file__)), manifest)
    with output_lock(output):
        attempt, before = prepare_attempt(root, manifest, output, "evaluation")
        completion = feature_completion(root, manifest, output)
        data, ids = assembled_features(root, manifest, output)
        # All integrity and independent-review gates precede imports/model loads.
        bind_runtime(root, manifest, "feature_runtime")
        import numpy as np
        import torch
        from badminton.jobs import run_local_job
        from badminton.storage import Store
        from torch import nn

        main = Store(inside(root, manifest["main_data"]))
        plan = read_json(sealed(root, manifest["protocol"]))
        model_spec = {m["name"]: m["model_sha256"] for m in plan["models"]}
        torch.set_num_threads(2)

        class Head(nn.Module):
            def __init__(self, dim):
                super().__init__()
                self.shared = nn.Sequential(
                    nn.Linear(dim, 128),
                    nn.ReLU(),
                    nn.Dropout(0.1),
                    nn.Linear(128, 64),
                    nn.ReLU(),
                )
                self.family, self.side = nn.Linear(64, 8), nn.Linear(64, 2)

            def forward(self, x):
                y = self.shared(x)
                return self.family(y), self.side(y)

        def task(job_id, progress):
            results = {}
            directory = output / "evaluation"
            directory.mkdir(exist_ok=True)
            for index, (name, dim) in enumerate((("R2", 254), ("R3", 371))):
                stable_frozen(root, manifest)
                folder = inside(root, manifest["execution"]["models"][name])
                selection = read_json(folder / "selection.json")
                if (
                    checksum(folder / "selected.pt") != model_spec[name]
                    or selection["model_sha256"] != model_spec[name]
                ):
                    raise ValueError("Selected frozen model changed")
                artifact, metrics_path = (
                    directory / (name.lower() + "-predictions.npz"),
                    directory / (name.lower() + "-metrics.json"),
                )
                if artifact.exists() or metrics_path.exists():
                    if not artifact.exists() or not metrics_path.exists():
                        raise ValueError(
                            "Partial held-out outputs exist; preserve and inspect without re-prediction"
                        )
                    results[name] = read_json(metrics_path)
                    if (
                        results[name]["prediction_artifact_sha256"]
                        != checksum(artifact)
                        or results[name]["model_sha256"] != model_spec[name]
                        or results[name]["input_audit_sha256"] != checksum(completion)
                    ):
                        raise ValueError(
                            "Existing held-out prediction provenance changed"
                        )
                    continue
                checkpoint = torch.load(
                    folder / "selected.pt", map_location="cpu", weights_only=True
                )
                if (
                    checkpoint["spec"]["input_dim"] != dim
                    or checkpoint["spec"]["hidden"] != [128, 64]
                    or tuple(checkpoint["spec"]["family_labels"]) != FAMILIES
                    or tuple(checkpoint["spec"]["side_labels"]) != SIDES
                    or checkpoint["thresholds"] != selection["thresholds"]
                ):
                    raise ValueError(
                        "Frozen head architecture, labels or validation thresholds changed"
                    )
                model = Head(dim)
                model.load_state_dict(checkpoint["state_dict"], strict=True)
                model.eval()
                mean, std = checkpoint["mean"].numpy(), checkpoint["std"].numpy()
                if (
                    mean.shape != (dim,)
                    or std.shape != (dim,)
                    or not np.isfinite(mean).all()
                    or not np.isfinite(std).all()
                    or not (std > 0).all()
                ):
                    raise ValueError("Frozen validation normalization changed")
                x, available = (
                    data[name.lower() + "_features"],
                    data[name.lower() + "_available"],
                )
                with torch.inference_mode():
                    logits = model(torch.from_numpy(np.clip((x - mean) / std, -10, 10)))
                    probs = []
                    for head, support in zip(
                        logits,
                        (checkpoint["supported_family"], checkpoint["supported_side"]),
                        strict=True,
                    ):
                        head[:, ~support.bool()] = -1e9
                        probs.append(head.softmax(1).numpy())
                closed, closed_predictions = score_probabilities(data, probs, available)
                abstaining, abstaining_predictions = score_probabilities(
                    data, probs, available, checkpoint["thresholds"]
                )
                with artifact.open("xb") as stream:
                    np.savez_compressed(
                        stream,
                        family_probabilities=probs[0],
                        side_probabilities=probs[1],
                        closed_set_predictions=closed_predictions,
                        with_abstention_predictions=abstaining_predictions,
                    )
                result = {
                    "model_sha256": model_spec[name],
                    "selection_sha256": checksum(folder / "selection.json"),
                    "selected_epoch": checkpoint["epoch"],
                    "validation_thresholds": checkpoint["thresholds"],
                    "closed_set": closed,
                    "with_abstention": abstaining,
                    "prediction_artifact_sha256": checksum(artifact),
                    "input_audit_sha256": checksum(completion),
                }
                create_json(metrics_path, result)
                results[name] = result
                progress((index + 1) / 2)
            stable_frozen(root, manifest)
            if (
                raw_annotation_hashes(inside(root, manifest["main_data"]))
                != before["main_annotation_document_sha256"]
            ):
                raise ValueError("Main annotations changed during frozen evaluation")
            proof = {
                "models": results,
                "source_ids": ids,
                "totals": manifest["expected"],
                "input_audit": {
                    "path": completion.relative_to(root).as_posix(),
                    "sha256": checksum(completion),
                },
                "preflight_sha256": checksum(preflight),
                "code_sha256": checksum(Path(__file__)),
                "main_job_id": job_id,
                "predeclared_selected_representation": "R3",
                "conditional_on_weak_source_contact_hitter_and_court": True,
                "main_annotations_unchanged": True,
                "installed_in_app": False,
                "future_changes_using_this_test_require_another_holdout": True,
            }
            create_json(attempt / "evaluation-completed.json", proof)
            return {
                "totals": manifest["expected"],
                "main_annotations_unchanged": True,
                "installed_in_app": False,
            }

        result = run_local_job(main, "evaluate-recognition", None, task)
        create_json(attempt / "admission-released.json", result)
        return {"attempt": str(attempt.relative_to(root)), **result}


def audit_saved_metrics(root, manifest, output, proof):
    """Recompute counts independently, without calling the evaluator's metrics."""
    import numpy as np

    data, ids = assembled_features(root, manifest, output)
    if ids != proof["source_ids"] or proof["totals"] != manifest["expected"]:
        raise ValueError("Saved evaluation source denominator changed")
    summaries = {}
    for name in ("R2", "R3"):
        path = output / "evaluation" / (name.lower() + "-predictions.npz")
        result = proof["models"][name]
        if "execution" in manifest:
            selection_path = (
                inside(root, manifest["execution"]["models"][name]) / "selection.json"
            )
            selection = read_json(selection_path)
            if (
                result["selection_sha256"] != checksum(selection_path)
                or result["validation_thresholds"] != selection["thresholds"]
                or result["model_sha256"] != selection["model_sha256"]
            ):
                raise ValueError(
                    "Saved model selection or validation thresholds changed"
                )
        if checksum(path) != result["prediction_artifact_sha256"]:
            raise ValueError("Saved prediction bytes changed")
        with np.load(path, allow_pickle=False) as archive:
            saved = {key: archive[key] for key in archive.files}
        available = data[name.lower() + "_available"]
        summaries[name] = {}
        for mode, key in (
            ("closed_set", "closed_set_predictions"),
            ("with_abstention", "with_abstention_predictions"),
        ):
            predicted, metrics = saved[key], result[mode]
            if predicted.shape != (len(ids), 2) or predicted.dtype != np.int64:
                raise ValueError("Prediction row shape or dtype changed")
            for h, (task, labels) in enumerate((("family", FAMILIES), ("side", SIDES))):
                truth, probability = data[task], saved[task + "_probabilities"]
                known = truth >= 0
                if (
                    probability.shape != (len(ids), len(labels))
                    or not np.isfinite(probability).all()
                    or (probability < 0).any()
                    or (probability > 1).any()
                ):
                    raise ValueError("Invalid saved probability array")
                np.testing.assert_allclose(probability.sum(1), 1, rtol=1e-5, atol=1e-6)
                expected, accepted = probability.argmax(1), available.copy()
                if mode == "with_abstention":
                    accepted &= (
                        probability.max(1)
                        >= np.asarray(result["validation_thresholds"][h])[expected]
                    )
                expected[~accepted] = -1
                np.testing.assert_array_equal(predicted[:, h], expected)
                counts = metrics[task]
                if (
                    counts["source_rows"] != int(known.sum())
                    or counts["unavailable_truth_rows"] != int((~known).sum())
                    or counts["answered"] != int((known & (expected >= 0)).sum())
                    or counts["strict_accuracy"]
                    != float((known & (expected == truth)).sum() / known.sum())
                ):
                    raise ValueError(
                        "Saved metric denominator or accuracy differs from recomputation"
                    )
                confusion = np.zeros((len(labels), len(labels) + 1), np.int64)
                for t, p in zip(truth[known], expected[known], strict=True):
                    confusion[t, p if p >= 0 else len(labels)] += 1
                if confusion.tolist() != counts["confusion"]:
                    raise ValueError(
                        "Saved confusion matrix differs from recomputation"
                    )
                recomputed_per = {}
                for k, label in enumerate(labels):
                    record = counts["per_class"][label]
                    support, tp, predicted_count = (
                        int((truth == k).sum()),
                        int(((truth == k) & (expected == k)).sum()),
                        int((known & (expected == k)).sum()),
                    )
                    if (
                        record["support"],
                        record["tp"],
                        record["fp"],
                        record["fn"],
                    ) != (support, tp, predicted_count - tp, support - tp) or record[
                        "f1"
                    ] != (
                        2 * tp / (support + predicted_count)
                        if support + predicted_count
                        else None
                    ):
                        raise ValueError("Saved class counts differ from recomputation")
                    recomputed_per[label] = {
                        "support": support,
                        "predicted": predicted_count,
                        "tp": tp,
                        "fp": predicted_count - tp,
                        "fn": support - tp,
                        "precision": tp / predicted_count if predicted_count else None,
                        "recall": tp / support if support else None,
                        "f1": 2 * tp / (support + predicted_count)
                        if support + predicted_count
                        else None,
                    }
                supported = [
                    label for label in labels if recomputed_per[label]["support"]
                ]
                total = int(known.sum())
                answered = int((known & (expected >= 0)).sum())
                correct_count = int((known & (expected == truth)).sum())
                independently_recomputed = {
                    "per_class": recomputed_per,
                    "source_rows": total,
                    "unavailable_truth_rows": int((~known).sum()),
                    "answered": answered,
                    "strict_accuracy": correct_count / total if total else None,
                    "precision_given_answered": correct_count / answered
                    if answered
                    else None,
                    "macro_f1_supported": float(
                        np.mean(
                            [recomputed_per[label]["f1"] or 0 for label in supported]
                        )
                    )
                    if supported
                    else None,
                    "balanced_recall": float(
                        np.mean(
                            [recomputed_per[label]["recall"] for label in supported]
                        )
                    )
                    if supported
                    else None,
                    "supported_classes": supported,
                    "confusion": confusion.tolist(),
                    "confusion_columns": [*labels, "unanswered"],
                }
                if counts != independently_recomputed:
                    raise ValueError(
                        "Saved class metric differs from independent recomputation"
                    )
            eligible = (data["family"] >= 0) & (data["side"] >= 0)
            correct = (
                eligible
                & (predicted[:, 0] == data["family"])
                & (predicted[:, 1] == data["side"])
            )
            joint = float(correct.sum() / eligible.sum()) if eligible.any() else None
            if (
                metrics["joint_correct"] != int(correct.sum())
                or metrics["joint_eligible_rows"] != int(eligible.sum())
                or metrics["family_side_tuple_given_weak_source_hitter_clock"] != joint
            ):
                raise ValueError("Saved joint metric differs from recomputation")
            if metrics != {
                "family": metrics["family"],
                "side": metrics["side"],
                "family_side_tuple_given_weak_source_hitter_clock": joint,
                "joint_eligible_rows": int(eligible.sum()),
                "joint_correct": int(correct.sum()),
                "source_rows": len(ids),
                "available_input_rows": int(available.sum()),
                "available_joint_eligible_rows": int((available & eligible).sum()),
                "exact_truth": False,
            }:
                raise ValueError(
                    "Saved source or availability metric differs from recomputation"
                )
            requested = [
                metrics["family"]["per_class"][f]["f1"]
                for f in FAMILIES[:6]
                if metrics["family"]["per_class"][f]["support"]
            ]
            cells = {}
            for f, family in enumerate(FAMILIES):
                for s, side in enumerate(SIDES):
                    mask = eligible & (data["family"] == f) & (data["side"] == s)
                    support = int(mask.sum())
                    cells[family + "/" + side] = {
                        "support": support,
                        "joint_correct": int((mask & correct).sum()),
                        "strict_joint_recall": float((mask & correct).sum() / support)
                        if support
                        else None,
                    }
            summaries[name][mode] = {
                "strict_family_accuracy": metrics["family"]["strict_accuracy"],
                "strict_side_accuracy": metrics["side"]["strict_accuracy"],
                "conditional_family_side_tuple": joint,
                "requested_six_family_macro_f1_supported": float(np.mean(requested))
                if requested
                else None,
                "family_side_cells": cells,
                "available_input_rows": int(available.sum()),
                "available_joint_eligible_rows": int((available & eligible).sum()),
            }
    return {
        "totals": manifest["expected"],
        "summaries": summaries,
        "all_metrics_exact_recompute": True,
        "no_new_inference": True,
        "installed_in_app": False,
        "conditional_not_automatic_event_or_identity_accuracy": True,
    }


def results_audit(root, manifest, output):
    root = root.resolve()
    output = recovery_output(root, manifest, output)
    with output_lock(output):
        attempt, _before = prepare_attempt(root, manifest, output, "results_audit")
        completion = feature_completion(root, manifest, output)
        _videos, jobs, _annotations = database_snapshot(
            inside(root, manifest["main_data"])
        )
        for path in sorted((output / "attempts").glob("*/evaluation-completed.json")):
            if not path.with_name("admission-released.json").exists():
                continue
            proof = read_json(path)
            if (
                jobs[proof["main_job_id"]]["status"] != "completed"
                or sealed(root, proof["input_audit"]) != completion
            ):
                raise ValueError(
                    "Evaluation completion disagrees with actual Store/input audit"
                )
            result = audit_saved_metrics(root, manifest, output, proof)
            create_json(
                attempt / "results-audit-completed.json",
                {
                    **result,
                    "evaluation": {
                        "path": path.relative_to(root).as_posix(),
                        "sha256": checksum(path),
                    },
                },
            )
            return {"attempt": str(attempt.relative_to(root)), **result}
        raise ValueError(
            "Successful released frozen evaluation is required for result audit"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--phase",
        choices=("inventory", "native", "features", "evaluate", "audit-results"),
        default="inventory",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--preflight",
        type=Path,
        help="Genuine independent exact-code recipe review receipt",
    )
    args = parser.parse_args()
    manifest = read_json(args.manifest)
    if args.phase == "inventory":
        result = inventory(args.workspace, manifest)
    else:
        if not args.output:
            parser.error("--output is required for native recovery")
        if args.phase == "evaluate":
            if not args.preflight:
                parser.error("--preflight is required before opening held-out heads")
            result = evaluation_recovery(
                args.workspace, manifest, args.output, args.preflight
            )
        else:
            operation = {
                "native": native_recovery,
                "features": feature_recovery,
                "audit-results": results_audit,
            }[args.phase]
            result = operation(args.workspace, manifest, args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
