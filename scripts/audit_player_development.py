"""Prepare source-only development packets and score sealed player assessments.

Raw images and assessment documents remain local. This never runs a model or
writes reviewed annotations; automated source assessments are not human gold.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write(path, document):
    Path(path).write_text(
        json.dumps(document, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def inside(base, relative):
    path = (base / relative).resolve()
    if not path.is_relative_to(base) or path == base:
        raise ValueError("Artifact path escapes its frozen directory")
    return path


def snapshot(root, data, manifest):
    """Hash the named source and original runs without opening predictions."""
    from badminton.video import resolve_source, validate_range

    if data != root / "data" / "processed" or not (data / "catalog.sqlite3").is_file():
        raise ValueError("Use the existing real shared Store")
    with sqlite3.connect(
        (data / "catalog.sqlite3").as_uri() + "?mode=ro", uri=True
    ) as db:
        row = db.execute(
            "SELECT document FROM videos WHERE id=?", (manifest["video_id"],)
        ).fetchone()
        history = db.execute(
            "SELECT revision,document FROM annotations WHERE video_id=? ORDER BY revision",
            (manifest["video_id"],),
        ).fetchall()
    if row is None or not history:
        raise ValueError("Frozen source or annotations unavailable")
    video = json.loads(row[0])
    source = resolve_source(video, root)
    clock = inside(data, manifest["video_id"] + "/timestamps.json")
    run = inside(data, manifest["run_path"])
    expected = (
        video["sha256"],
        digest(source),
        digest(clock),
        history[-1][0],
        hashlib.sha256(history[-1][1].encode()).hexdigest(),
        digest(run),
    )
    if expected != (
        manifest["source_sha256"],
        manifest["source_sha256"],
        manifest["clock_sha256"],
        manifest["annotation_revision"],
        manifest["annotation_sha256"],
        manifest["run_sha256"],
    ):
        raise ValueError("Frozen source/clock/revision/run bytes conflict")
    times = json.loads(clock.read_text(encoding="utf-8"))
    if len(times) != video["frame_count"]:
        raise ValueError("Incomplete source clock")
    validate_range(video, times, manifest["start_frame"], manifest["end_frame"])
    original_runs = {
        p.relative_to(data).as_posix(): digest(p)
        for p in sorted(run.parent.rglob("*"))
        if p.is_file()
    }
    frozen = {
        "source_sha256": expected[1],
        "clock_sha256": expected[2],
        "video_document_sha256": hashlib.sha256(row[0].encode()).hexdigest(),
        "annotation_history_sha256": hashlib.sha256(
            json.dumps(history, sort_keys=True).encode()
        ).hexdigest(),
        "annotation_revision": expected[3],
        "annotation_sha256": expected[4],
        "original_runs": original_runs,
    }
    return video, times, frozen


def verify_packet(directory, manifest, manifest_sha256):
    from badminton.player_audit import validate_packet

    packet_path = directory / "packet.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    validate_packet(manifest, packet, manifest_sha256=manifest_sha256)
    for sample in packet["samples"]:
        if digest(inside(directory, sample["image"])) != sample["image_sha256"]:
            raise ValueError("Source packet image changed")
    return packet, digest(packet_path)


def initialize_vision():
    """Initialize installed vision hooks before decoding; decoding needs no model extra."""
    from importlib import import_module
    from importlib.util import find_spec

    if find_spec("torchvision") is not None:
        import_module("torchvision")


def prepare(root, data, manifest, manifest_sha256, output):
    import psutil

    initialize_vision()
    from badminton.jobs import run_local_job
    from badminton.storage import Store
    from badminton.video import iter_frames

    if not output.is_relative_to(root / ".cache") or output.exists():
        raise ValueError("Preparation requires a new ignored output directory")
    video, times, before = snapshot(root, data, manifest)
    output.mkdir(parents=True)
    write(output / "inputs-before.json", before)
    process = psutil.Process()
    receipt = {
        "schema_version": 1,
        "status": "running",
        "manifest_sha256": manifest_sha256,
        "process": {
            "pid": process.pid,
            "created_at": process.create_time(),
            "cwd": str(Path.cwd()),
            "command": sys.argv,
        },
        "code_sha": subprocess.check_output(
            [
                "git",
                "-C",
                str(Path(__file__).resolve().parents[1]),
                "rev-parse",
                "HEAD",
            ],
            text=True,
        ).strip(),
        "launcher_sha256": digest(__file__),
        "shared_store": str(data / "catalog.sqlite3"),
        "core_sha256": digest(
            Path(__file__).resolve().parents[1] / "backend/badminton/player_audit.py"
        ),
        "inference_calls": 0,
    }
    write(output / "prepare-receipt.json", receipt)
    began = time.monotonic()

    def task(job_id, progress):
        receipt["job_id"] = job_id
        write(output / "prepare-receipt.json", receipt)
        if snapshot(root, data, manifest)[2] != before:
            raise ValueError("Input changed before source decoding admission")
        packet = {
            "schema_version": 1,
            "manifest_sha256": manifest_sha256,
            "video_id": video["id"],
            "source_sha256": before["source_sha256"],
            "clock_sha256": before["clock_sha256"],
            "width": video["width"],
            "height": video["height"],
            "samples": [],
        }
        for number, index in enumerate(manifest["sample_frames"]):
            frames = list(iter_frames(video, root, times, index, index + 1))
            if len(frames) != 1 or frames[0][:2] != (index, times[index]):
                raise ValueError("Source frame/PTS identity changed")
            filename = f"source-{index}.png"
            frames[0][2].to_image().save(output / filename)
            packet["samples"].append(
                {
                    "frame": index,
                    "time_s": times[index],
                    "image": filename,
                    "image_sha256": digest(output / filename),
                }
            )
            if (
                time.monotonic() - began > manifest["max_runtime_seconds"]
                or sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
                > manifest["max_output_bytes"]
            ):
                raise ValueError("Source preparation exceeded its frozen budget")
            progress((number + 1) / len(manifest["sample_frames"]))
        write(output / "packet.json", packet)
        verify_packet(output, manifest, manifest_sha256)
        after = snapshot(root, data, manifest)[2]
        write(output / "inputs-after.json", after)
        if after != before:
            raise ValueError("Frozen inputs changed inside source preparation")
        if (
            sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
            > manifest["max_output_bytes"]
        ):
            raise ValueError("Source packet exceeded its frozen output budget")
        receipt["inputs_preserved"] = True
        return {"source_frames": len(packet["samples"]), "inference_calls": 0}

    try:
        run_local_job(Store(data), "player-source-audit", video["id"], task)
        receipt.update(status="completed", packet_sha256=digest(output / "packet.json"))
    except BaseException as exc:
        receipt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        write(output / "prepare-receipt.json", receipt)
    return receipt


def exclusive_json(path, document):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, indent=2, allow_nan=False) + "\n")


def finish(command, root, data, manifest, manifest_sha256, output, assessments):
    from badminton.player_audit import score_audit, validate_assessment

    if command not in {"seal", "score"}:
        raise ValueError("Choose seal or score for an existing packet")
    if not output.is_relative_to(root / ".cache") or not output.is_dir():
        raise ValueError("Use the existing ignored source packet directory")
    packet, packet_sha256 = verify_packet(output, manifest, manifest_sha256)
    before = snapshot(root, data, manifest)[2]
    if before != json.loads(
        (output / "inputs-before.json").read_text(encoding="utf-8")
    ):
        raise ValueError("Original inputs changed since source preparation")
    prepared = json.loads((output / "prepare-receipt.json").read_text(encoding="utf-8"))
    if (
        prepared["status"] != "completed"
        or not prepared["inputs_preserved"]
        or prepared["packet_sha256"] != packet_sha256
    ):
        raise ValueError("Source preparation was not verified complete")
    documents = []
    for path in assessments:
        path = path.resolve()
        if not path.is_relative_to(output):
            raise ValueError("Private assessment must remain within the task packet")
        raw = path.read_bytes()
        document = json.loads(raw)
        validate_assessment(packet, document, packet_sha256=packet_sha256)
        documents.append((path, document, hashlib.sha256(raw).hexdigest()))
    seal_path = output / "streams-seal.json"
    if command == "seal":
        if len(documents) != 2 or len({d["session_id"] for _, d, _ in documents}) != 2:
            raise ValueError("Seal exactly two distinct genuine assessment sessions")
        seal = {
            "schema_version": 1,
            "packet_sha256": packet_sha256,
            "manifest_sha256": manifest_sha256,
            "streams": [
                {
                    "path": p.relative_to(output).as_posix(),
                    "sha256": sha,
                    "session_id": d["session_id"],
                }
                for p, d, sha in documents
            ],
        }
        if any(digest(p) != sha for p, _, sha in documents):
            raise ValueError("Assessment changed during sealing")
        exclusive_json(seal_path, seal)
        return seal
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if (
        seal["packet_sha256"] != packet_sha256
        or seal["manifest_sha256"] != manifest_sha256
        or len(seal["streams"]) != 2
    ):
        raise ValueError("Independent stream seal conflicts")
    for stream in seal["streams"]:
        if digest(inside(output, stream["path"])) != stream["sha256"]:
            raise ValueError("Original independent assessment changed")
    if len(documents) != 1:
        raise ValueError("Score exactly one source-only adjudication")
    path, adjudication, adjudication_sha = documents[0]
    decision = adjudication.get("adjudication", {})
    if (
        decision.get("source_only") is not True
        or decision.get("stream_sha256") != [s["sha256"] for s in seal["streams"]]
        or not isinstance(decision.get("disagreements"), list)
        or not isinstance(decision.get("evidence"), list)
        or not decision["evidence"]
    ):
        raise ValueError(
            "Source-only adjudication must preserve stream evidence/disagreements"
        )
    if adjudication["session_id"] in {s["session_id"] for s in seal["streams"]}:
        raise ValueError("Adjudication requires a separate source-only session/pass")
    adjudication_seal = {
        "packet_sha256": packet_sha256,
        "streams_seal_sha256": digest(seal_path),
        "path": path.relative_to(output).as_posix(),
        "sha256": adjudication_sha,
        "session_id": adjudication["session_id"],
        "sealed_before_prediction_read": True,
    }
    if digest(path) != adjudication_sha:
        raise ValueError("Adjudication changed during sealing")
    adjudication_seal_path = output / "adjudication-seal.json"
    if adjudication_seal_path.exists():
        if (
            json.loads(adjudication_seal_path.read_text(encoding="utf-8"))
            != adjudication_seal
        ):
            raise ValueError("Existing adjudication seal conflicts")
    else:
        exclusive_json(adjudication_seal_path, adjudication_seal)
    if (output / "score.json").exists():
        raise ValueError("Preserve existing score output")
    frozen_names = [
        "packet.json",
        "inputs-before.json",
        "inputs-after.json",
        "prepare-receipt.json",
        "streams-seal.json",
        "adjudication-seal.json",
        *[sample["image"] for sample in packet["samples"]],
        *[stream["path"] for stream in seal["streams"]],
        path.relative_to(output).as_posix(),
    ]
    frozen_files = {name: digest(inside(output, name)) for name in frozen_names}

    def verify_frozen_files():
        if any(
            digest(inside(output, name)) != expected
            for name, expected in frozen_files.items()
        ):
            raise ValueError(
                "Sealed source packet or assessment changed during scoring"
            )

    from badminton.jobs import run_local_job
    from badminton.scene_review import reviewed_run
    from badminton.storage import Store

    def task(job_id, progress):
        verify_frozen_files()
        if snapshot(root, data, manifest)[2] != before:
            raise ValueError("Frozen inputs changed before scoring admission")
        # This is the first prediction-content read: both streams and source-only
        # adjudication already have immutable byte receipts above.
        run = json.loads(inside(data, manifest["run_path"]).read_text(encoding="utf-8"))
        annotations = Store(data).annotations(manifest["video_id"])
        reviewed = reviewed_run(run, annotations)
        for key in ("cut_frames", "camera_ranges", "preceding_reviewed_cut_frame"):
            if run.get(key) != reviewed.get(key):
                raise ValueError(
                    "Cached run conflicts with current reviewed camera context"
                )
        for original, expected in zip(run["frames"], reviewed["frames"], strict=True):
            if any(
                original.get(k) != expected.get(k)
                for k in ("scene", "reviewed_scene_range_id")
            ):
                raise ValueError(
                    "Cached run conflicts with current reviewed scene context"
                )
        result = score_audit(
            manifest,
            packet,
            adjudication,
            run,
            manifest_sha256=manifest_sha256,
            packet_sha256=packet_sha256,
        )
        verify_frozen_files()
        if snapshot(root, data, manifest)[2] != before:
            raise ValueError("Frozen inputs changed inside scoring admission")
        for stream in seal["streams"]:
            if digest(inside(output, stream["path"])) != stream["sha256"]:
                raise ValueError("Independent stream changed during scoring")
        if digest(path) != adjudication_sha:
            raise ValueError("Adjudication changed during scoring")
        result.update(
            job_id=job_id,
            manifest_sha256=manifest_sha256,
            packet_sha256=packet_sha256,
            run_sha256=manifest["run_sha256"],
            streams_seal_sha256=digest(seal_path),
            adjudication_seal_sha256=digest(output / "adjudication-seal.json"),
            inputs_preserved=True,
            inference_calls=0,
            frozen_file_sha256=frozen_files,
        )
        exclusive_json(output / "score.json", result)
        progress(1)
        return result

    import psutil

    process = psutil.Process()
    receipt = {
        "schema_version": 1,
        "status": "running",
        "inference_calls": 0,
        "manifest_sha256": manifest_sha256,
        "packet_sha256": packet_sha256,
        "process": {
            "pid": process.pid,
            "created_at": process.create_time(),
            "cwd": str(Path.cwd()),
            "command": sys.argv,
        },
        "shared_store": str(data / "catalog.sqlite3"),
        "launcher_sha256": digest(__file__),
        "frozen_file_sha256": frozen_files,
    }
    # Preserve every scoring attempt, including a failed provenance check.
    attempt = 1
    while (output / f"score-receipt-{attempt}.json").exists():
        attempt += 1
    receipt_path = output / f"score-receipt-{attempt}.json"
    exclusive_json(receipt_path, receipt)

    def admitted(job_id, progress):
        receipt["job_id"] = job_id
        write(receipt_path, receipt)
        return task(job_id, progress)

    try:
        result = run_local_job(
            Store(data), "player-source-score", manifest["video_id"], admitted
        )
        receipt.update(status="completed", score_sha256=digest(output / "score.json"))
        return result
    except BaseException as exc:
        receipt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        write(receipt_path, receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "seal", "score"))
    for name in ("root", "data", "manifest", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--assessment", action="append", type=Path, default=[])
    args = parser.parse_args()
    root, data, output = (p.resolve() for p in (args.root, args.data, args.output))
    os.environ["BADMINTON_ROOT"] = str(root)
    os.environ["BADMINTON_DATA_DIR"] = str(data)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from badminton.player_audit import validate_manifest

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    manifest_sha256 = digest(args.manifest)
    if args.command == "prepare":
        result = prepare(root, data, manifest, manifest_sha256, output)
    else:
        result = finish(
            args.command, root, data, manifest, manifest_sha256, output, args.assessment
        )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
