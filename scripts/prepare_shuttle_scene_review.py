"""Freeze, prepare and independently audit private exhaustive source galleries.

No assessor, service client, image transfer or semantic label writer is provided.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import psutil

CHECKOUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CHECKOUT / "backend"))
from badminton import shuttle_scene_preparation as scene  # noqa: E402

PROTOCOL = "data/manifests/shuttle_scene_preparation_protocol_v1.json"
PRODUCERS = (
    "backend/badminton/shuttle_scene_preparation.py",
    "scripts/prepare_shuttle_scene_review.py",
    "tests/test_shuttle_scene_preparation.py",
    PROTOCOL,
)
CREDENTIALS = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "AGENT_PROJECT_TOKEN",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "BADMINTON_PASSWORD",
    "BADMINTON_USERNAME",
)
MAX_JSON = 32 * 1024**2


def read(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_JSON + 1)
    scene.require(len(raw) <= MAX_JSON, "JSON input exceeds limit")
    return scene.decode(raw)


def identity():
    process = psutil.Process()
    return {
        "pid": process.pid,
        "created": process.create_time(),
        "cwd": process.cwd(),
        "command": process.cmdline(),
    }


def require_absent(original):
    scene.require(
        type(original.get("pid")) is int
        and type(original.get("created")) in (int, float),
        "Missing original process identity",
    )
    try:
        process = psutil.Process(original["pid"])
        same = process.create_time() == original["created"]
    except psutil.NoSuchProcess:
        return
    scene.require(not same, "Original preparation process is still present")


def write(output, name, value, *, binary=False):
    raw = value if binary else scene.encode(value)
    path = scene.safe_path(output, name, must_exist=False)
    used = sum(p.stat().st_size for p in Path(output).rglob("*") if p.is_file())
    scene.require(
        used + len(raw) <= scene.MAX_OUTPUT_BYTES, "Preparation output budget exceeded"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def producer_hashes(protocol):
    expected = protocol["helper_sha256"]
    for name, digest in expected.items():
        path = scene.safe_path(CHECKOUT, name)
        scene.require(scene.file_hash(path) == digest, "Frozen helper source changed")
    return {
        name: scene.file_hash(scene.safe_path(CHECKOUT, name))
        for name in (*PRODUCERS, *expected)
    }


def validate_protocol(protocol):
    scene.require(
        protocol.get("schema_version") == 1 and protocol.get("task") == 340,
        "Invalid preparation protocol",
    )
    scene.require(
        protocol.get("eligibility") == scene.ELIGIBILITY, "Eligibility changed"
    )
    scene.require(
        protocol["render"]
        == {
            "tile": [320, 180],
            "columns": 4,
            "rows": 4,
            "caption_height": 36,
            "format": "JPEG",
            "quality": 80,
            "subsampling": 0,
            "optimize": False,
            "fit": "contain original aspect with black padding",
        },
        "Frozen rendering changed",
    )
    scene.require(
        protocol["packing"]
        == {
            "max_bytes": scene.MAX_BYTES,
            "max_images": scene.MAX_IMAGES,
            "overlap_sheets_within_view": 1,
            "independent_passes": 2,
            "adjudication_reserve_passes": 1,
        },
        "Frozen review packing changed",
    )
    scene.require(
        protocol["limits"]["max_assessor_sessions"]
        == protocol["limits"]["max_image_transfer_bytes"]
        == 0,
        "No assessment/transfer authority",
    )
    scene.require(
        protocol["limits"]["max_output_bytes"] == scene.MAX_OUTPUT_BYTES,
        "Output cap changed",
    )
    scene.require(len(protocol["sources"]) == 2, "Both original sources required")
    for source in protocol["sources"]:
        scene.integer(source["frame_count"], 1)
        scene.require(
            source["sha256"] == protocol["artifacts"][source["artifact"]],
            "Source hash binding changed",
        )


def validate_grant(grant, protocol, *, now=None):
    now = time.time() if now is None else now
    task, claim = grant["task"], grant["task"]["claim"]
    scene.require(
        task["status"] == "running"
        and task["epoch"] == claim["epoch"]
        and type(claim["epoch"]) is int,
        "Live implementation grant required",
    )
    scene.require(
        claim["host_id"] == platform.node()
        and claim["session_id"] == grant["session_id"],
        "Original-host grant required",
    )
    scene.require(
        task["spec_hash"] == claim["spec_hash"] == protocol["spec_hash"],
        "Frozen task specification changed",
    )
    scene.require(
        task["spec"]["artifacts"] == protocol["artifacts"],
        "Granted original artifacts changed",
    )
    deadline = claim["granted_at"] + protocol["limits"]["max_runtime_hours"] * 3600
    scene.require(
        grant["deadline"] == deadline and now < min(claim["expires_at"], deadline),
        "Preparation grant/deadline expired",
    )


def validate_ownership(path, grant):
    live = read(path)
    scene.require(
        type(live.get("at")) in (int, float)
        and 0 <= time.time() - live["at"] < 180
        and live.get("paused") is False
        and live["task"]["status"] == "running",
        "Fresh authoritative ownership observation required",
    )
    claim, expected = live["task"]["claim"], grant["task"]["claim"]
    for key in (
        "actor",
        "host_id",
        "session_id",
        "epoch",
        "spec_hash",
        "branch",
        "baseline_sha",
    ):
        scene.require(
            claim[key] == expected[key], "Current ownership differs from frozen grant"
        )
    scene.require(time.time() < claim["expires_at"], "Current lease expired")
    return live


def bound_inputs(root, protocol, bindings):
    scene.require(
        set(bindings) == set(protocol["artifacts"]),
        "Exact bound input membership required",
    )
    paths = {}
    for name, relative in bindings.items():
        path = scene.safe_path(root, relative)
        scene.require(
            scene.file_hash(path) == protocol["artifacts"][name],
            "Original input hash changed",
        )
        paths[name] = path
    return paths


def verified_context(args):
    context_path = scene.safe_path(args.output, "context.json")
    scene.require(
        scene.file_hash(context_path) == args.context_sha256, "Frozen context changed"
    )
    context = read(context_path)
    protocol = read(args.protocol)
    validate_protocol(protocol)
    scene.require(
        scene.file_hash(args.protocol) == context["protocol_sha256"],
        "Public protocol changed",
    )
    scene.require(
        scene.file_hash(args.bindings) == context["bindings_sha256"],
        "Input bindings changed",
    )
    grant = read(args.grant)
    scene.require(grant == context["grant"], "Frozen original grant changed")
    validate_grant(grant, protocol)
    validate_ownership(args.ownership, grant)
    scene.require(str(args.root.resolve()) == context["root"], "Shared root changed")
    scene.require(
        producer_hashes(protocol) == context["producer_sha256"],
        "Frozen producer changed",
    )
    paths = bound_inputs(args.root, protocol, read(args.bindings))
    return context, protocol, paths


def verify_stable(args, context, protocol, paths):
    scene.require(
        scene.file_hash(args.protocol) == context["protocol_sha256"],
        "Public protocol changed during stage",
    )
    scene.require(
        scene.file_hash(args.bindings) == context["bindings_sha256"],
        "Input bindings changed during stage",
    )
    scene.require(
        read(args.grant) == context["grant"], "Frozen grant changed during stage"
    )
    scene.require(
        scene.file_hash(args.output / "context.json") == args.context_sha256,
        "Frozen context changed during stage",
    )
    scene.require(
        producer_hashes(protocol) == context["producer_sha256"],
        "Frozen producer changed during stage",
    )
    for name, path in paths.items():
        checked = scene.safe_path(args.root, path.relative_to(args.root).as_posix())
        scene.require(
            scene.file_hash(checked) == protocol["artifacts"][name],
            "Original input hash changed during stage",
        )
    validate_grant(context["grant"], protocol)
    validate_ownership(args.ownership, context["grant"])


def freeze(args):
    protocol, grant = read(args.protocol), read(args.grant)
    validate_protocol(protocol)
    validate_grant(grant, protocol)
    validate_ownership(args.ownership, grant)
    output = scene.safe_path(
        args.root, args.output.relative_to(args.root).as_posix(), must_exist=False
    )
    scene.require(
        args.output.is_relative_to(args.root / ".cache") and not output.exists(),
        "Exclusive ignored output required",
    )
    inputs = bound_inputs(args.root, protocol, read(args.bindings))
    metadata, cases = scene.inventory(
        read(inputs["familiar-scene-inventory"]),
        read(inputs["context-audit-diagnostics"]),
        protocol,
    )
    context = {
        "schema_version": 1,
        "root": str(args.root),
        "grant": grant,
        "protocol_sha256": scene.file_hash(args.protocol),
        "bindings_sha256": scene.file_hash(args.bindings),
        "producer_sha256": producer_hashes(protocol),
        "views": len(metadata),
        "cases": len(cases),
        "source_media_decoded": False,
        "image_transfer_bytes": 0,
        "frozen_at": time.time(),
    }
    output.mkdir(parents=True, exist_ok=False)
    write(output, "context.json", context)
    return {
        "status": "frozen",
        "context_sha256": scene.file_hash(output / "context.json"),
        "source_media_decoded": False,
        "image_transfer_bytes": 0,
    }


def shared_store(root):
    from badminton import config
    from badminton.storage import Store

    common = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=root,
            text=True,
        ).strip()
    )
    scene.require(
        common.parent.resolve() == root.resolve(),
        "Use the original shared namespace, not an isolated worktree",
    )
    scene.require(
        config.ROOT == root
        and config.DATA.resolve() == root / "data/processed"
        and config.WEIGHTS.resolve() == root / "models/weights"
        and (config.DATA / "catalog.sqlite3").is_file(),
        "Real existing shared Store required",
    )
    return Store(config.DATA)


def check_store_terminal(root, terminal):
    database = root / "data/processed/catalog.sqlite3"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute(
            "SELECT document FROM jobs WHERE id=?", (terminal["job_id"],)
        ).fetchone()
    scene.require(row is not None, "Original Store job missing")
    job = scene.decode(row[0])
    scene.require(
        job["status"] == "completed" and job["summary"] == terminal["summary"],
        "Original Store job not completed",
    )
    scene.require(
        job["owner_pid"] == terminal["process"]["pid"]
        and job["owner_started"] == terminal["process"]["created"],
        "Store process identity changed",
    )


def admitted(args, stage, calculate):
    from badminton.jobs import run_local_job

    scene.require(
        not any(os.environ.get(name) for name in CREDENTIALS),
        "Credential-free source preparation required",
    )
    prefix = args.output / stage
    scene.require(
        not prefix.exists(), "Stage already attempted; preserve original evidence"
    )
    store = shared_store(args.root)
    prefix.mkdir()
    process, job_id = identity(), None
    write(
        args.output,
        stage + "/attempt.json",
        {
            "started_at": time.time(),
            "process": process,
            "implicit_retry_permitted": False,
        },
    )

    def task(identifier, progress):
        nonlocal job_id
        job_id = identifier
        write(
            args.output,
            stage + "/admission.json",
            {
                "job_id": identifier,
                "process": process,
                "context_sha256": args.context_sha256,
            },
        )
        return calculate(progress)

    try:
        result = run_local_job(
            store, "shuttle_scene_" + stage, "familiar-scene340", task
        )
    except BaseException as error:
        write(
            args.output,
            stage + "/failure.json",
            {
                "job_id": job_id,
                "process": process,
                "error_type": type(error).__name__,
                "message": str(error),
                "implicit_retry_permitted": False,
            },
        )
        raise
    terminal = {
        "status": "completed",
        "job_id": job_id,
        "process": process,
        "summary": result,
        "admission_sha256": scene.file_hash(prefix / "admission.json"),
    }
    write(args.output, stage + "/terminal.json", terminal)
    return result


def prepare(args):
    context, protocol, paths = verified_context(args)
    scene.require(
        {p.name for p in args.output.iterdir()} == {"context.json"},
        "Output was already attempted",
    )
    views, cases = scene.inventory(
        read(paths["familiar-scene-inventory"]),
        read(paths["context-audit-diagnostics"]),
        protocol,
    )

    def work(progress):
        manifest = scene.prepare_sources(
            protocol,
            views,
            paths,
            lambda name, raw: write(args.output, name, raw, binary=True),
            progress,
        )
        scene.validate_gallery_manifest(manifest, views, protocol)
        packing, plan = scene.pack_galleries(manifest["galleries"])
        summary = scene.aggregate(manifest, packing)
        summary.update(
            cases=len(cases),
            context_sha256=args.context_sha256,
            protocol_sha256=context["protocol_sha256"],
            source_judgments_created=0,
        )
        write(args.output, "gallery.json", manifest)
        write(args.output, "plan.json", plan)
        write(args.output, "aggregate.json", summary)
        progress(1)
        verify_stable(args, context, protocol, paths)
        return {
            "status": "prepared",
            "gallery_sha256": scene.file_hash(args.output / "gallery.json"),
            "plan_sha256": scene.file_hash(args.output / "plan.json"),
            "aggregate_sha256": scene.file_hash(args.output / "aggregate.json"),
            "views": len(views),
            "cases": len(cases),
            "image_transfer_bytes": 0,
            "assessor_sessions": 0,
        }

    return admitted(args, "prepare", work)


def audit(args):
    context, protocol, paths = verified_context(args)
    terminal = read(scene.safe_path(args.output, "prepare/terminal.json"))
    require_absent(terminal["process"])
    check_store_terminal(args.root, terminal)
    for key, name in (
        ("gallery_sha256", "gallery.json"),
        ("plan_sha256", "plan.json"),
        ("aggregate_sha256", "aggregate.json"),
    ):
        scene.require(
            scene.file_hash(scene.safe_path(args.output, name))
            == terminal["summary"][key],
            "Prepared artifact changed",
        )
    manifest, original_plan, original_summary = (
        read(args.output / name)
        for name in ("gallery.json", "plan.json", "aggregate.json")
    )
    views, cases = scene.inventory(
        read(paths["familiar-scene-inventory"]),
        read(paths["context-audit-diagnostics"]),
        protocol,
    )

    def work(progress):
        scene.validate_gallery_manifest(manifest, views, protocol)
        image_bytes = scene.audit_images(manifest, args.output)
        scene.audit_native_clocks(manifest, protocol, paths)
        packing, plan = scene.pack_galleries(manifest["galleries"])
        summary = scene.aggregate(manifest, packing)
        summary.update(
            cases=len(cases),
            context_sha256=args.context_sha256,
            protocol_sha256=context["protocol_sha256"],
            source_judgments_created=0,
        )
        scene.require(
            summary == original_summary and plan == original_plan,
            "Independently recomputed plan/aggregate changed",
        )
        expected_images = {
            s["path"] for g in manifest["galleries"] for s in g["sheets"]
        }
        actual_images = {
            p.relative_to(args.output).as_posix() for p in args.output.rglob("*.jpg")
        }
        scene.require(actual_images == expected_images, "Extra/missing derived images")
        expected_files = expected_images | {
            "context.json",
            "gallery.json",
            "plan.json",
            "aggregate.json",
            "prepare/attempt.json",
            "prepare/admission.json",
            "prepare/terminal.json",
            "audit/attempt.json",
            "audit/admission.json",
        }
        actual_files = {
            p.relative_to(args.output).as_posix()
            for p in args.output.rglob("*")
            if p.is_file()
        }
        scene.require(
            actual_files == expected_files, "Unexpected or missing retained output"
        )
        for name in actual_files:
            scene.safe_path(args.output, name)
        progress(1)
        verify_stable(args, context, protocol, paths)
        check_store_terminal(args.root, terminal)
        require_absent(terminal["process"])
        result = {
            "status": "audited",
            "original_preparation_process_absent": True,
            "original_store_completed": True,
            "source_clocks_independently_redecoded": True,
            "original_input_hashes_unchanged": True,
            "images": len(expected_images),
            "derived_image_bytes": image_bytes,
            "views": len(views),
            "cases": len(cases),
            "gallery_sha256": terminal["summary"]["gallery_sha256"],
            "plan_sha256": terminal["summary"]["plan_sha256"],
            "aggregate_sha256": terminal["summary"]["aggregate_sha256"],
            "image_transfer_bytes": 0,
            "assessor_sessions": 0,
        }
        write(args.output, "audit/verification.json", result)
        return result

    return admitted(args, "audit", work)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "prepare", "audit"))
    for name in ("root", "protocol", "bindings", "grant", "ownership", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--context-sha256")
    args = parser.parse_args(argv)
    args.root, args.output = args.root.resolve(), args.output.absolute()
    for name in ("protocol", "bindings", "grant", "ownership"):
        path = getattr(args, name).absolute()
        scene.require(
            path.is_relative_to(args.root) and path.suffix == ".json",
            "Bound JSON argument must stay inside original namespace",
        )
        scene.safe_path(args.root, path.relative_to(args.root).as_posix())
        setattr(args, name, path)
    if args.stage != "freeze" and not args.context_sha256:
        parser.error("Frozen context SHA256 required")
    scene.require(
        args.output.is_relative_to(args.root / ".cache"),
        "Private output must stay below original .cache",
    )
    scene.safe_path(
        args.root, args.output.relative_to(args.root).as_posix(), must_exist=False
    )
    os.environ.update(
        BADMINTON_ROOT=str(args.root),
        BADMINTON_DATA_DIR=str(args.root / "data/processed"),
        BADMINTON_WEIGHTS_DIR=str(args.root / "models/weights"),
    )
    result = {"freeze": freeze, "prepare": prepare, "audit": audit}[args.stage](args)
    # Aggregate status/hashes only: no private view IDs, source paths or images.
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
