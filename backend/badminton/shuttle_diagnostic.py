"""Frozen published-reference diagnostic, separate from application truth."""

from __future__ import annotations

import argparse
import importlib.metadata
import io
import math
import os
import platform
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path
from uuid import uuid4

import numpy as np
import psutil

from .shuttle_supervision import (
    _prior_proofs,
    _resume,
    _seal,
    _verified,
    contained,
    digest,
    encoded,
    file_hash,
    normalize_csv,
    publish_json,
    publish_stream,
    read_json,
)

PROTOCOL = (
    Path(__file__).resolve().parents[2]
    / "data/manifests/shuttle_corpus_diagnostic_v1.json"
)
PROTOCOL_SHA = "90fe79c46fa9014ff96b1b8bb372cc457eaf1bc767b1ec097dea73163f2e861d"


def load_protocol(path=PROTOCOL):
    if file_hash(path) != PROTOCOL_SHA:
        raise ValueError("Frozen diagnostic protocol changed")
    return read_json(path)


def _consumers():
    package = Path(__file__).resolve().parent
    result = {
        "badminton/" + p.relative_to(package).as_posix(): p
        for p in package.rglob("*.py")
    }
    for name in ("diagnose_shuttle_corpus.py", "prepare_shuttle_supervision.py"):
        result["scripts/" + name] = package.parents[1] / "scripts" / name
    return result


def _runtime():
    def version(name):
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        **{
            name: version(name)
            for name in (
                "av",
                "numpy",
                "Pillow",
                "psutil",
                "torch",
                "torchvision",
                "opencv-python",
                "scenedetect",
            )
        },
    }


def context(root, output, protocol_path, spec):
    """Freeze all local consumers including the native model vendor subtree."""
    output = contained(root / ".cache", output)
    if output == (root / ".cache").resolve():
        raise ValueError("Choose a dedicated diagnostic output lineage")
    destination = contained(output, output / "context.json")
    if output.exists() and (
        not output.is_dir() or (not destination.exists() and any(output.iterdir()))
    ):
        raise ValueError("Cannot adopt a foreign nonempty output lineage")
    for name in ("consumer", "attempts"):
        contained(output, output / name)
    if load_protocol(protocol_path) != spec:
        raise ValueError("Protocol changed during snapshot")
    _verified(root, spec["source_evidence"])
    _verified(root, spec["checkpoint"])
    files = _consumers()
    value = {
        "schema_version": 1,
        "purpose": "published-reference diagnostic, not annotation accuracy",
        "root": str(root),
        "protocol_sha256": file_hash(protocol_path),
        "protocol": spec,
        "runtime": _runtime(),
        "consumers": {
            name: {
                "path": contained(root, path).relative_to(root).as_posix(),
                "sha256": file_hash(path),
            }
            for name, path in sorted(files.items())
        },
    }
    if destination.exists():
        if read_json(destination) != value:
            raise ValueError(
                "Frozen consumer/input/runtime context changed; use another lineage"
            )
    else:
        publish_json(destination, value)
    for name, source in files.items():
        target = contained(output, output / "consumer" / name)
        expected = value["consumers"][name]["sha256"]
        if target.exists():
            if file_hash(target) != expected:
                raise ValueError("Frozen consumer copy changed")
        else:
            raw = source.read_bytes()
            if digest(raw) != expected:
                raise ValueError("Consumer changed while copying")
            publish_stream(target, io.BytesIO(raw), limit=len(raw))
    if any(file_hash(p) != value["consumers"][n]["sha256"] for n, p in files.items()):
        raise ValueError("Consumer changed during snapshot")
    if file_hash(protocol_path) != value["protocol_sha256"]:
        raise ValueError("Protocol changed during snapshot")
    return value, file_hash(destination)


def prior_proofs(root, output):
    for path in (output / "attempts").glob("*/admission.json"):
        document = read_json(contained(output, path))
        if document.get("host_id") != platform.node():
            raise ValueError("Recovery needs original-host process and Store proof")
    proofs = _prior_proofs(root, output)
    for proof in proofs:
        admission = contained(output, output / proof["admission"]["path"])
        if not admission.with_name("terminal.json").is_file():
            raise ValueError(
                "Prior native attempt has no terminal receipt; preserve it for authenticated recovery"
            )
    return proofs


def resume_plan(output, receipt_path, receipt_sha256, context_sha):
    terminals = sorted((output / "attempts").glob("*/terminal.json"))
    if terminals and (receipt_path is None or receipt_sha256 is None):
        raise ValueError(
            "Existing attempts require an externally sealed resume receipt"
        )
    reusable = _resume(output, receipt_path, receipt_sha256, context_sha)
    seals = [_seal(output, path) for path in terminals]
    if receipt_path is not None:
        supplied = {
            "path": contained(output, receipt_path).relative_to(output).as_posix(),
            "sha256": receipt_sha256,
        }
        receipt = read_json(_verified(output, supplied))
        chain = receipt["prior_terminal_seals"] + [supplied]
        if sorted(chain, key=lambda v: v["path"]) != seals:
            raise ValueError("Resume terminal history is incomplete or changed")
    durations = [read_json(path)["elapsed_s"] for path in terminals]
    if any(
        type(value) not in (int, float) or not math.isfinite(value) or value < 0
        for value in durations
    ):
        raise ValueError("Invalid prior runtime evidence")
    return reusable, seals, sum(durations)


def source_catalog(root, spec):
    """Validate all producer seals before any new model work."""
    evidence = read_json(_verified(root, spec["source_evidence"]))
    index_entry = evidence["evidence_index"]
    if index_entry["sha256"] != spec["source_index_sha256"]:
        raise ValueError("Source evidence index binding changed")
    index = read_json(_verified(root, index_entry))
    if len(index["files"]) != index_entry["files"]:
        raise ValueError("Source graph membership changed")
    for name, entry in index["files"].items():
        if name != entry["path"]:
            raise ValueError("Source graph path alias")
        _verified(root, entry)
    with sqlite3.connect(
        (root / "data/processed/catalog.sqlite3").as_uri() + "?mode=ro", uri=True
    ) as cx:
        for job in index["jobs"]:
            raw = cx.execute(
                "SELECT document FROM jobs WHERE id=?", (job["job_id"],)
            ).fetchone()
            if raw is None or digest(raw[0].encode()) != job["store_document_sha256"]:
                raise ValueError("Producer shared Store proof changed")
    for origin in {
        contained(root, root / j["admission"]["path"]).parents[2] for j in index["jobs"]
    }:
        _prior_proofs(root, origin)
    report = read_json(_verified(root, spec["source_report"]))
    if (
        report["archive_sha256"] != spec["archive_sha256"]
        or report["eligibility"]["training_allowed"]
    ):
        raise ValueError("Source archive or eligibility changed")
    refs = report["clips"]
    if len({entry["clip"] for entry in refs}) != len(refs):
        raise ValueError("Duplicate source clip identity")
    corpus = contained(root, root / spec["corpus"])
    counts = Counter(clips=len(refs))
    groups = set()
    for entry in refs:
        clip = read_json(_verified(corpus, entry))
        if (
            clip["clip"] != entry["clip"]
            or clip["training_eligible"]
            or clip["independent_test_eligible"]
        ):
            raise ValueError("Source clip identity/eligibility changed")
        groups.add(clip["group"])
        clock = clip["clock"]
        counts["native_frames"] += clock["frame_count"] if clock else 0
        complete = (
            len(clip["labels"]) == 1 and clip["labels"][0]["ordinal_coverage_complete"]
        )
        counts["complete_clips" if complete else "quarantined_clips"] += 1
        for labels in clip["labels"]:
            counts["published_rows"] += len(labels["records"])
            if not complete:
                counts["quarantined_rows"] += len(labels["records"])
            counts["unlabelled_native_frames"] += len(
                labels["missing_native_labels"] or []
            )
    counts["groups"] = len(groups)
    if dict(counts) != spec["expected"]:
        raise ValueError("Source corpus denominators changed")
    return corpus, refs


def verify_clip(corpus, entry, root):
    clip = read_json(_verified(corpus, entry))
    from .shuttle_supervision import load_manifest

    source_spec = load_manifest()
    for key in ("video", "labels"):
        for item in clip["inputs"][key]:
            path = _verified(corpus, item["extracted"])
            if key == "labels":
                normalized = normalize_csv(
                    path.read_bytes(), source_spec, clip["clock"]
                )
                recorded = next(
                    label for label in clip["labels"] if label["source"] == item["path"]
                )
                if normalized != {k: v for k, v in recorded.items() if k != "source"}:
                    raise ValueError("Published row/native-clock normalization changed")
    if clip["clock"]:
        frames = clip["clock"]["frames"]
        if [f["frame"] for f in frames] != list(range(clip["clock"]["frame_count"])):
            raise ValueError("Native source ordinal membership changed")
    return clip


def validate_predictions(prediction, clock, spec):
    """Missing outputs stay unavailable; corrupt/reordered identities fail closed."""
    frames = clock["frames"]
    origin = frames[0]["time_s"]
    available = {}
    last = -1
    for row in prediction["frames"]:
        ordinal = row["frame"]
        if type(ordinal) is not int or not last < ordinal < len(frames):
            raise ValueError("Duplicate, reordered or foreign prediction ordinal")
        if (
            not math.isfinite(row["time_s"])
            or abs(row["time_s"] - (frames[ordinal]["time_s"] - origin))
            > spec["clock_tolerance_s"]
        ):
            raise ValueError("Prediction source timestamp changed")
        point = row["shuttle"]
        if type(point["visible"]) is not bool or point.get("repaired") is not False:
            raise ValueError("Invalid or repaired shuttle prediction")
        if not math.isfinite(point["confidence"]):
            raise ValueError("Nonfinite confidence")
        if point["visible"]:
            if any(
                type(point[k]) not in (float, int) or not math.isfinite(point[k])
                for k in ("x", "y")
            ):
                raise ValueError("Invalid visible coordinate")
        elif point["x"] is not None or point["y"] is not None:
            raise ValueError("Invisible prediction invents a coordinate")
        candidates = point["component_candidates"]
        if len({c["id"] for c in candidates}) != len(candidates):
            raise ValueError("Duplicate observed component")
        if any(
            not all(math.isfinite(c[k]) for k in ("x", "y", "confidence"))
            for c in candidates
        ):
            raise ValueError("Nonfinite observed component")
        available[ordinal] = row
        last = ordinal
    return available


def _rate(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def score_clip(clip, prediction, spec):
    """Agreement with publication states; never install labels or infer absences."""
    clock = clip["clock"]
    available = (
        validate_predictions(prediction, clock, spec)
        if prediction is not None and clock
        else {}
    )
    labels = [row for label in clip["labels"] for row in label["records"]]
    complete = (
        bool(clock)
        and not clip["issues"]
        and len(clip["labels"]) == 1
        and clip["labels"][0]["ordinal_coverage_complete"]
    )
    counts = Counter(
        clips=1,
        native_frames=clock["frame_count"] if clock else 0,
        published_rows=len(labels),
        predictions_available=len(available),
    )
    counts["native_frames_unavailable"] = counts["native_frames"] - len(available)
    counts["quarantined_rows"] = len(labels) if not complete else 0
    counts["unlabelled_native_frames"] = sum(
        len(label["missing_native_labels"] or []) for label in clip["labels"]
    )
    errors = []
    diagonal = math.hypot(*clock["display_size"]) if clock else None
    tolerance = diagonal * spec["localization_tolerance_diagonal"] if diagonal else None
    for row in labels:
        if (
            not complete
            or row["issues"]
            or row["published_state"]
            not in ("published_visible", "published_not_visible")
        ):
            counts["ineligible_published_rows"] += 1
            continue
        visible = row["published_state"] == "published_visible"
        if visible and not row["coordinate_reference_eligible"]:
            counts["ineligible_published_rows"] += 1
            continue
        counts["eligible_published_rows"] += 1
        counts["published_visible" if visible else "published_not_visible"] += 1
        native = row["native_frame"]
        if (
            not isinstance(native, dict)
            or native["frame"] != row["published_frame"]
            or native != clock["frames"][row["published_frame"]]
        ):
            raise ValueError("Published/native frame reference changed")
        observed = available.get(native["frame"])
        if observed is None:
            counts["eligible_output_unavailable"] += 1
            if visible:
                counts["visibility_fn"] += 1
                counts["localization_fn"] += 1
                counts["component_unavailable"] += 1
            else:
                counts["unavailable_published_negative"] += 1
            continue
        point = observed["shuttle"]
        if not visible:
            counts["visibility_fp" if point["visible"] else "visibility_tn"] += 1
            counts["localization_fp" if point["visible"] else "localization_tn"] += 1
            continue
        px, py = row["published_point"]
        candidates = point["component_candidates"]
        nearby = any(
            math.hypot(c["x"] - px, c["y"] - py) <= tolerance for c in candidates
        )
        counts["component_present" if nearby else "component_absent"] += 1
        if not point["visible"]:
            counts["visibility_fn"] += 1
            counts["localization_fn"] += 1
            continue
        counts["visibility_tp"] += 1
        error = math.hypot(point["x"] - px, point["y"] - py)
        errors.append(error)
        if error <= tolerance:
            counts["localization_tp"] += 1
        else:
            counts["localization_fp"] += 1
            counts["localization_fn"] += 1
            counts["wrong_component_selection"] += bool(nearby)
    return {"counts": dict(counts), "conditional_errors_px": errors}


def summarize(parts):
    counts = Counter()
    errors = []
    for part in parts:
        counts.update(part["counts"])
        errors.extend(part["conditional_errors_px"])
    result = {"counts": dict(sorted(counts.items()))}
    for name in ("visibility", "localization"):
        result[name] = {
            **_rate(*(counts[name + "_" + key] for key in ("tp", "fp", "fn"))),
            "tn": counts[name + "_tn"],
        }
    result["conditional_error_px"] = {
        "support": len(errors),
        "mean": float(np.mean(errors)) if errors else None,
        "median": float(np.median(errors)) if errors else None,
        "p90": float(np.percentile(errors, 90)) if errors else None,
    }
    return result


def _native_video(root, corpus, clip, clock_data):
    from .av_runtime import open_media

    clock = clip["clock"]
    if not clock or clock["issues"] or len(clip["inputs"]["video"]) != 1:
        return None
    entry = clip["inputs"]["video"][0]["extracted"]
    source = _verified(corpus, entry)
    origin = clock["frames"][0]["time_s"]
    times = [f["time_s"] - origin for f in clock["frames"]]
    with open_media(str(source)) as container:
        stream = container.streams.video[0]
        rate = float(stream.average_rate) if stream.average_rate else None
        duration = (
            float(stream.duration * stream.time_base)
            if stream.duration is not None
            else None
        )
        stream_start = float((stream.start_time or 0) * stream.time_base)
    if rate is None or not math.isfinite(rate) or rate <= 0:
        return None
    video_id = digest(clip["clip"].encode())[:16]
    publish_json(
        contained(clock_data, clock_data / video_id / "timestamps.json"), times
    )
    return {
        "id": video_id,
        "sha256": entry["sha256"],
        "path": contained(root, source).relative_to(root).as_posix(),
        "width": clock["display_size"][0],
        "height": clock["display_size"][1],
        "rotation": clock["rotation"],
        "fps": rate,
        "source_start_s": origin,
        "frame_count": len(times),
        "duration_s": max(times[-1], duration or 0),
        "source_duration_metadata_s": duration,
        "source_stream_start_s": stream_start,
        "duration_basis": "Container duration or observed last timestamp; exact terminal sample endpoint is not certified",
    }


def _require_store(root):
    from . import config

    shared = root / "data/processed"
    if (
        config.ROOT != root
        or config.DATA.resolve() != shared
        or config.WEIGHTS.resolve() != root / "models/weights"
        or not (shared / "catalog.sqlite3").is_file()
    ):
        raise ValueError(
            "Pin original roots and the existing real shared Store before imports"
        )
    return shared


def run(root, output, protocol_path=PROTOCOL, resume_receipt=None, resume_sha256=None):
    import torch
    import torchvision  # noqa: F401  # Before any threaded native decode.

    from .jobs import JobCancelled, run_local_job
    from .shuttle import track_shuttle
    from .storage import Store

    root = Path(root).resolve()
    shared = _require_store(root)
    output = contained(root / ".cache", output)
    spec = load_protocol(protocol_path)
    if not torch.cuda.is_available():
        raise ValueError(
            "This frozen native diagnostic requires CUDA; no implicit CPU fallback"
        )
    frozen, context_sha = context(root, output, protocol_path, spec)
    proofs = prior_proofs(root, output)
    reusable, prior_terminal_seals, previous_elapsed = resume_plan(
        output, resume_receipt, resume_sha256, context_sha
    )
    attempt = contained(output, output / "attempts" / uuid4().hex)
    process = psutil.Process()
    completed = []
    began = time.perf_counter()
    status, job_id, index_entry = "failed", None, None

    def unchanged():
        if context(root, output, protocol_path, spec)[0] != frozen:
            raise ValueError("Frozen native context changed during work")

    def task(identifier, report_progress):
        nonlocal job_id, index_entry
        job_id = identifier
        publish_json(
            attempt / "admission.json",
            {
                "job_id": identifier,
                "host_id": platform.node(),
                "context_sha256": context_sha,
                "process": {
                    "pid": process.pid,
                    "creation_time": process.create_time(),
                    "cwd": process.cwd(),
                    "command": process.cmdline(),
                },
                "prior_terminal_proofs": proofs,
            },
        )
        corpus, refs = source_catalog(root, spec)
        if set(reusable) - {ref["clip"] for ref in refs}:
            raise ValueError("Resume has a foreign source clip")
        last_progress = -1.0

        def progress(value):
            nonlocal last_progress
            if (
                previous_elapsed + time.perf_counter() - began
                > spec["max_native_seconds"]
            ):
                raise JobCancelled(
                    "Frozen native runtime bound reached; preserve evidence and obtain a new bounded authorization"
                )
            if value - last_progress >= 0.005:
                report_progress(value)
                last_progress = value

        for number, entry in enumerate(refs):
            clip = verify_clip(corpus, entry, root)
            if clip["clip"] in reusable:
                record, seal = reusable[clip["clip"]]
                if record["input_reference"] != entry:
                    raise ValueError("Resume source membership changed")
                if record["raw_prediction"]:
                    raw = read_json(_verified(output, record["raw_prediction"]))
                    validate_predictions(raw, clip["clock"], spec)
            else:
                folder = contained(
                    attempt, attempt / "clips" / digest(clip["clip"].encode())
                )
                clock_data = contained(folder, folder / "clock-data")
                video = _native_video(root, corpus, clip, clock_data)
                record = {
                    "clip": clip["clip"],
                    "context_sha256": context_sha,
                    "input_reference": entry,
                    "raw_prediction": None,
                    "video_projection": video,
                    "unavailable_reason": None,
                }
                if video is None:
                    record["unavailable_reason"] = (
                        "Native clock, unique media or rate metadata unavailable"
                    )
                else:
                    raw_path = contained(folder, folder / "raw-prediction.json")
                    if raw_path.exists() or raw_path.with_suffix(".tmp").exists():
                        raise FileExistsError("Native output is not fresh")
                    track_shuttle(
                        video,
                        root,
                        clock_data,
                        0,
                        clip["clock"]["frame_count"],
                        lambda value: progress((number + value) / len(refs)),
                        raw_path,
                        annotations={},
                        input_size=tuple(spec["input_size"]),
                    )
                    raw = read_json(raw_path)
                    if (
                        raw["checkpoint_sha256"] != spec["checkpoint"]["sha256"]
                        or raw["input_size"] != spec["input_size"]
                        or not raw["device"].startswith("cuda")
                        or raw["precision"] != "float16"
                        or raw["repaired_frames"] != 0
                        or raw["video_sha256"] != video["sha256"]
                        or raw["localization"]["heatmap_threshold"]
                        != spec["heatmap_threshold"]
                        or raw["start_frame"] != 0
                        or raw["end_frame"] != clip["clock"]["frame_count"]
                        or raw["temporal_context_crosses_detected_cuts"] is not False
                    ):
                        raise ValueError(
                            "Native model/device/precision/repair recipe changed"
                        )
                    validate_predictions(raw, clip["clock"], spec)
                    record["raw_prediction"] = _seal(output, raw_path)
                verify_clip(corpus, entry, root)
                unchanged()
                checkpoint = folder / "complete.json"
                publish_json(checkpoint, record)
                seal = _seal(output, checkpoint)
            completed.append(seal)
            progress((number + 1) / len(refs))
            print(
                encoded(
                    {
                        "phase": "native",
                        "completed_clips": number + 1,
                        "total_clips": len(refs),
                        "elapsed_s": round(time.perf_counter() - began, 2),
                    }
                ).decode(),
                flush=True,
            )
        unchanged()
        _verified(root, spec["source_report"])
        result = {
            "schema_version": 1,
            "kind": "unscored_frozen_native_outputs",
            "context_sha256": context_sha,
            "protocol_sha256": PROTOCOL_SHA,
            "checkpoint_sha256": spec["checkpoint"]["sha256"],
            "source_evidence_sha256": spec["source_evidence"]["sha256"],
            "completed_clips": completed,
            "expected_source_counts": spec["expected"],
            "limitations": spec["limitations"],
        }
        path = attempt / "output-index.json"
        publish_json(path, result)
        index_entry = _seal(output, path)
        return {
            "output_index": index_entry,
            "prior_terminal_seals": prior_terminal_seals,
            "completed_clips": len(completed),
            "scored": False,
        }

    try:
        result = run_local_job(
            Store(shared), "research-shuttle-corpus-native", None, task
        )
        status = "completed"
        return result
    except (KeyboardInterrupt, JobCancelled):
        status = "interrupted"
        raise
    finally:
        terminal = {
            "schema_version": 1,
            "context_sha256": context_sha,
            "status": status,
            "job_id": job_id,
            "elapsed_s": round(time.perf_counter() - began, 3),
            "completed_clips": completed,
            "output_index": index_entry,
        }
        path = attempt / "terminal.json"
        publish_json(path, terminal)
        print(
            encoded(
                {"terminal": _seal(output, path), "status": status, "job_id": job_id}
            ).decode(),
            flush=True,
        )


def terminal_binding(
    output, terminal_path, terminal_sha256, entry, index, context_sha, proofs
):
    receipt = read_json(
        _verified(
            output,
            {
                "path": contained(output, terminal_path).relative_to(output).as_posix(),
                "sha256": terminal_sha256,
            },
        )
    )
    admission_path = Path(terminal_path).parent / "admission.json"
    admission_entry = _seal(output, admission_path)
    proof = next((p for p in proofs if p["admission"] == admission_entry), None)
    admission = read_json(admission_path)
    if (
        proof is None
        or proof["store_status"] != "completed"
        or receipt["status"] != "completed"
        or receipt["context_sha256"] != context_sha
        or receipt["output_index"] != entry
        or receipt["completed_clips"] != index["completed_clips"]
        or receipt["job_id"] != admission["job_id"]
    ):
        raise ValueError(
            "Prediction index lacks its matching completed native/Store terminal proof"
        )
    return {
        "path": contained(output, terminal_path).relative_to(output).as_posix(),
        "sha256": terminal_sha256,
    }


def score(
    root,
    output,
    index_path,
    index_sha256,
    terminal_path,
    terminal_sha256,
    protocol_path=PROTOCOL,
):
    from .jobs import run_local_job
    from .storage import Store

    root, output = Path(root).resolve(), Path(output).resolve()
    shared = _require_store(root)
    spec = load_protocol(protocol_path)
    frozen, context_sha = context(root, output, protocol_path, spec)
    proofs = prior_proofs(root, output)
    entry = {
        "path": contained(output, index_path).relative_to(output).as_posix(),
        "sha256": index_sha256,
    }
    index = read_json(_verified(output, entry))
    if (
        index["context_sha256"] != context_sha
        or index["protocol_sha256"] != PROTOCOL_SHA
        or index["checkpoint_sha256"] != spec["checkpoint"]["sha256"]
    ):
        raise ValueError("Prediction index belongs to another frozen context")
    if not proofs:
        raise ValueError("Scoring requires original-host native terminal proof")
    native_terminal = terminal_binding(
        output, terminal_path, terminal_sha256, entry, index, context_sha, proofs
    )
    destination = contained(output, output / "scores" / uuid4().hex / "report.json")

    def task(_identifier, progress):
        corpus, refs = source_catalog(root, spec)
        raw_records = [
            read_json(_verified(output, seal)) for seal in index["completed_clips"]
        ]
        records = {record["clip"]: record for record in raw_records}
        if len(records) != len(raw_records) or set(records) != {
            ref["clip"] for ref in refs
        }:
            raise ValueError("Native output clip membership incomplete or duplicated")
        groups, partitions = defaultdict(list), defaultdict(list)
        all_parts, per_clip = [], []
        for ordinal, ref in enumerate(refs):
            clip = verify_clip(corpus, ref, root)
            record = records[clip["clip"]]
            if (
                record["context_sha256"] != context_sha
                or record["input_reference"] != ref
            ):
                raise ValueError("Prediction/source clip pairing changed")
            prediction = (
                read_json(_verified(output, record["raw_prediction"]))
                if record["raw_prediction"]
                else None
            )
            part = score_clip(clip, prediction, spec)
            all_parts.append(part)
            groups[clip["group"]].append(part)
            partitions[clip["published_partition"]].append(part)
            per_clip.append(
                {
                    "clip": clip["clip"],
                    "unavailable_reason": record["unavailable_reason"],
                    **summarize([part]),
                }
            )
            progress((ordinal + 1) / len(refs))
        if context(root, output, protocol_path, spec)[0] != frozen:
            raise ValueError("Context changed while scoring")
        _verified(output, entry)
        report = {
            "schema_version": 1,
            "scope": "Conditional agreement with published/pretrained-source coordinates; not expert or independent accuracy",
            "context_sha256": context_sha,
            "protocol_sha256": PROTOCOL_SHA,
            "output_index": entry,
            "summary": summarize(all_parts),
            "groups": {k: summarize(v) for k, v in sorted(groups.items())},
            "partitions": {k: summarize(v) for k, v in sorted(partitions.items())},
            "clips": per_clip,
            "eligibility": spec["eligibility"],
            "limitations": spec["limitations"],
            "prior_terminal_proofs": proofs,
            "native_terminal": native_terminal,
        }
        publish_json(destination, report)
        return {"report": _seal(output, destination), "summary": report["summary"]}

    return run_local_job(Store(shared), "research-shuttle-corpus-score", None, task)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "score"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--resume-receipt", type=Path)
    parser.add_argument("--resume-sha256")
    parser.add_argument("--index", type=Path)
    parser.add_argument("--index-sha256")
    parser.add_argument("--native-terminal", type=Path)
    parser.add_argument("--native-terminal-sha256")
    args = parser.parse_args(argv)
    if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        parser.error("Clear GitHub credentials before executing research code")
    if args.mode == "run":
        if (
            args.index
            or args.index_sha256
            or args.native_terminal
            or args.native_terminal_sha256
        ):
            parser.error("Native run does not accept a scored index")
        result = run(
            args.root,
            args.output,
            args.protocol,
            args.resume_receipt,
            args.resume_sha256,
        )
    else:
        if (
            not all(
                (
                    args.index,
                    args.index_sha256,
                    args.native_terminal,
                    args.native_terminal_sha256,
                )
            )
            or args.resume_receipt
            or args.resume_sha256
        ):
            parser.error(
                "Score requires a sealed index AND matching native terminal with both SHAs, without resume arguments"
            )
        result = score(
            args.root,
            args.output,
            args.index,
            args.index_sha256,
            args.native_terminal,
            args.native_terminal_sha256,
            args.protocol,
        )
    print(encoded(result).decode(), flush=True)
