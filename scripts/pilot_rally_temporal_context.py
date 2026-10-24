"""Prospectively sealed sparse-context pilot; no exact contact annotations."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import PIL
import psutil

sys.dont_write_bytecode = True
CHECKOUT = Path(__file__).resolve().parents[1]
PROTOCOL = "data/manifests/rally_temporal_context_v1.json"
CONTINUATION = "data/manifests/rally_temporal_context_v2.json"
PRIOR_PAYLOAD = 8177560145
CONSUMERS = (
    "backend/badminton/rally_temporal_context.py",
    "scripts/pilot_rally_temporal_context.py",
    "tests/test_rally_temporal_context.py",
    PROTOCOL,
    CONTINUATION,
)
CREDENTIALS = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "AGENT_PROJECT_TOKEN",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "CODEX_THREAD_ID",
    "CODEX_SESSION_ID",
)


def read(path):
    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError("Duplicate JSON key")
            result[name] = value
        return result

    return json.loads(
        Path(path).read_bytes(),
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")),
    )


def write(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
        )


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for part in iter(lambda: handle.read(1024**2), b""):
            result.update(part)
    return result.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def library():
    sys.path.insert(0, str(CHECKOUT / "backend"))
    from badminton import rally_temporal_context

    require(
        Path(rally_temporal_context.__file__).resolve() == CHECKOUT / CONSUMERS[0],
        "Wrong temporal consumer origin",
    )
    return rally_temporal_context


def identity(process):
    return {
        "pid": process.pid,
        "creation_time": process.create_time(),
        "cwd": process.cwd(),
        "command": process.cmdline(),
    }


def absent(row):
    require(
        type(row["pid"]) is int
        and row["pid"] > 0
        and type(row["creation_time"]) in (int, float)
        and row["creation_time"] > 0,
        "Actual original lifetime required",
    )
    try:
        require(
            abs(psutil.Process(row["pid"]).create_time() - row["creation_time"])
            >= 0.01,
            "Original lifetime is still alive",
        )
    except psutil.NoSuchProcess:
        pass


def git(*args):
    return subprocess.check_output(["git", *args], cwd=CHECKOUT, text=True).strip()


def binding():
    require(
        not git("status", "--porcelain"), "Commit and test the consumer before freezing"
    )
    cli = shutil.which("codex")
    require(bool(cli), "Existing authenticated Codex CLI required")
    return {
        "commit": git("rev-parse", "HEAD"),
        "files": {p: digest(CHECKOUT / p) for p in CONSUMERS},
        "python": platform.python_version(),
        "pillow": PIL.__version__,
        "psutil": psutil.__version__,
        "platform": platform.platform(),
        "cli": {"path": cli, "sha256": digest(cli)},
    }


def task_bytes(root, task=240):
    total = 0
    prefixes = (f"rally{task}", "rally-temporal") if task == 240 else (f"rally{task}",)
    parents = [p for p in (root / ".cache").iterdir() if p.name.startswith(prefixes)]
    parents.extend(
        p
        for p in (root / ".cache/worktrees").iterdir()
        if p.name.startswith(f"rally{task}")
    )
    for parent in parents:
        require(
            not parent.is_symlink()
            and not getattr(parent.lstat(), "st_file_attributes", 0) & 1024,
            "Linked task root",
        )
        if parent.is_file():
            total += parent.lstat().st_size
            continue
        for folder, directories, files in os.walk(parent, followlinks=False):
            for name in list(directories):
                path = Path(folder) / name
                info = path.lstat()
                if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 1024:
                    total += info.st_size
                    directories.remove(name)
            total += sum((Path(folder) / name).lstat().st_size for name in files)
    return total


def budget(root, protocol):
    new = task_bytes(root, protocol["task"])
    require(
        new < protocol["limits"]["new_output_bytes"] - 1024**2,
        "New output budget exhausted",
    )
    # The frozen census accounting is a lower bound; the original metadata gate
    # independently recounts historical scientific roots before preparation.
    prior = read(root / ".cache/rally238-native-v1/audit-v2.json")[
        "cumulative_retained_output_bytes"
    ]
    gate = root / ".cache/rally240-source-only-v1/metadata-gate.json"
    if gate.is_file():
        prior = max(prior, read(gate)["historical_retained_output_bytes"])
    require(
        task_bytes(root, 240) + task_bytes(root, 242) + prior
        < protocol["limits"]["cumulative_retained_bytes"] - 1024**2,
        "Cumulative retained budget exhausted",
    )
    return new


def freeze(root, output, grant, protocol):
    claim = grant["task"]["claim"]
    now = time.time()
    if protocol["task"] == 242:
        temporal = library()
        original = read(CHECKOUT / PROTOCOL)
        temporal.validate_continuation(protocol, original)
        require(
            digest(CHECKOUT / PROTOCOL)
            == protocol["continuation"]["original_protocol_sha256"],
            "Original protocol bytes changed",
        )
        deadline = temporal.continuation_deadline(grant, protocol, now, platform.node())
    else:
        deadline = claim["granted_at"] + 14400
    require(
        platform.node() == "MSI"
        and grant["task"]["status"] == "running"
        and claim["actor"] == "Ken0u"
        and claim["host_id"] == "MSI"
        and claim["epoch"] == grant["task"]["epoch"]
        and claim["spec_hash"] == protocol["spec_hash"]
        and claim["granted_at"] <= now < claim["expires_at"],
        "Fresh committed original-host grant required",
    )
    context = {
        "task": protocol["task"],
        "protocol_sha256": digest(
            CHECKOUT / (CONTINUATION if protocol["task"] == 242 else PROTOCOL)
        ),
        "consumers": binding(),
        "grant": grant,
        "frozen_at": now,
        "deadline": deadline,
        "old_scientific_runtime_renewed": False,
    }
    require(now < context["deadline"], "Pilot runtime expired")
    budget(root, protocol)
    output.mkdir(exist_ok=False)
    write(output / "context.json", context)
    return {
        "context_sha256": digest(output / "context.json"),
        "deadline": context["deadline"],
    }


def current(output, timestamp, *, live=True):
    context, stamp = read(output / "context.json"), read(timestamp)
    published = datetime.fromisoformat(
        stamp["created_at"].replace("Z", "+00:00")
    ).timestamp()
    require(
        context["consumers"] == binding()
        and stamp["user"]["login"] == "Ken0u"
        and stamp["html_url"].startswith(
            f"https://github.com/Ken0u/badminton-match-analyzer/issues/{context['task']}#issuecomment-"
        )
        and digest(output / "context.json") in stamp["body"]
        and context["frozen_at"] <= published,
        "Prospective context/consumer seal changed",
    )
    if live:
        require(
            published <= time.time() < context["deadline"], "Pilot deadline expired"
        )
    return context


def store_job(root, admission):
    with sqlite3.connect(
        (root / "data/processed/catalog.sqlite3").as_uri() + "?mode=ro", uri=True
    ) as db:
        row = db.execute(
            "select document from jobs where id=?", (admission["job_id"],)
        ).fetchone()
    job = json.loads(row[0]) if row else {}
    require(
        job.get("owner_pid") == admission["process"]["pid"]
        and job.get("owner_started") == admission["process"]["creation_time"],
        "Actual shared Store owner required",
    )
    return job


def live_parent(root, output):
    admission = read(output / "preparation/admission.json")
    job = store_job(root, admission)
    require(
        job.get("status") == "running"
        and admission["context_sha256"] == digest(output / "context.json")
        and time.time() < read(output / "context.json")["deadline"],
        "Live admitted preparation context required",
    )
    owner = admission["process"]
    require(
        any(
            p.pid == owner["pid"]
            and abs(p.create_time() - owner["creation_time"]) < 0.01
            and p.cwd() == owner["cwd"]
            and p.cmdline() == owner["command"]
            for p in psutil.Process().parents()
        ),
        "Metadata gate must descend from its actual Store owner",
    )


def archived_census(root):
    base = root / ".cache/rally238-diagnostics-v1"
    receipts = root / ".cache/rally238-native-v1"
    admission, terminal = read(base / "admission.json"), read(base / "terminal.json")
    audit, finish = read(receipts / "audit-v2.json"), read(receipts / "finish.json")
    require(
        terminal["status"] == "completed"
        and terminal["job_id"] == admission["job_id"]
        and terminal["admission_sha256"] == digest(base / "admission.json")
        and digest(base / "terminal.json") == audit["terminal_sha256"]
        and admission["context_sha256"] == audit["context_sha256"]
        and type(finish["returncode"]) is int
        and finish["returncode"] == 0,
        "Matching original census completion seals required",
    )
    job = store_job(root, admission)
    require(
        job.get("status") == "completed" and job.get("summary") == terminal["summary"],
        "Original census Store completion required",
    )
    for row in [
        admission["process"],
        read(receipts / "owner.json"),
        *finish["observed_lifetimes"],
    ]:
        absent(row)
    for name, checksum in terminal["artifacts"].items():
        require(
            name in ("aggregate.json", "ledger.json")
            and digest(base / name) == checksum,
            "Original census artifact changed",
        )
    require(
        digest(receipts / "stdout.log") == finish["stdout_sha256"]
        and digest(receipts / "stderr.log") == finish["stderr_sha256"],
        "Original census logs changed",
    )


def metadata_gate(root, output, protocol):
    """Clean subprocess: execute frozen metadata rules, never scientific labels."""
    live_parent(root, output)
    context_protocol(read(output / "context.json"), protocol)
    for path, checksum in protocol["sealed_inputs"].items():
        require(digest(root / path) == checksum, "Sealed pilot prerequisite changed")
    archived_census(root)
    source = root / protocol["diagnostic_checkout"]
    for name, checksum in protocol["diagnostic_bindings"].items():
        require(digest(source / name) == checksum, "Frozen diagnostic consumer changed")
    old = module(
        source / "scripts/diagnose_rally_references.py", "temporal_frozen_diagnostics"
    )
    original_protocol = read(
        source / "data/manifests/rally_reference_diagnostics_v1.json"
    )
    recovery, previous, acceptance = old.frozen(root, original_protocol)
    _, _, audit = old.metadata_gate(
        root, recovery, previous, acceptance, original_protocol
    )
    require(
        audit["completed_global_execution_identities"] == 1014
        and audit["validated_target_references"] == 256
        and audit["prior_attempted_image_bytes"] == 8177560145,
        "Historical provenance denominator changed",
    )
    audit.update(
        historical_retained_output_bytes=audit["prior_retained_output_bytes"]
        + old.new_bytes(root),
        process=identity(psutil.Process()),
        completed_at=time.time(),
        scientific_labels_read=False,
    )
    write(output / "metadata-gate.json", audit)
    return {
        "metadata_gate_sha256": digest(output / "metadata-gate.json"),
        "scientific_labels_read": False,
    }


def admitted(root, output, stage, context, calculate):
    prefix = output / stage
    require(not prefix.exists(), "Stage was already attempted; preserve it")
    require(
        all(not os.environ.get(k) for k in CREDENTIALS),
        "Clear account credential variables before jobs",
    )
    sys.path.insert(0, str(CHECKOUT / "backend"))
    from badminton import config
    from badminton.jobs import run_local_job
    from badminton.storage import Store

    require(
        config.ROOT == root
        and config.DATA.resolve() == root / "data/processed"
        and config.WEIGHTS.resolve() == root / "models/weights"
        and (config.DATA / "catalog.sqlite3").is_file(),
        "Pin original roots and real shared Store",
    )
    prefix.mkdir()
    job_id = None

    def work(identifier, progress):
        nonlocal job_id
        job_id = identifier
        write(
            prefix / "admission.json",
            {
                "job_id": identifier,
                "process": identity(psutil.Process()),
                "context_sha256": digest(output / "context.json"),
            },
        )
        require(time.time() < context["deadline"], "Pilot deadline expired")
        result = calculate(progress)
        require(time.time() < context["deadline"], "Pilot deadline expired")
        return result

    try:
        result = run_local_job(
            Store(config.DATA),
            "rally_temporal_" + stage,
            f"source-only-rally{context.get('task', 240)}",
            work,
        )
    except BaseException as error:
        write(
            prefix / "failure.json",
            {
                "job_id": job_id,
                "error_type": type(error).__name__,
                "message": str(error),
                "implicit_retry_permitted": False,
            },
        )
        raise
    write(
        prefix / "terminal.json",
        {
            "job_id": job_id,
            "status": "completed",
            "admission_sha256": digest(prefix / "admission.json"),
            "summary": result,
        },
    )
    return result


def verify_stage(root, output, stage):
    prefix = output / stage
    admission, terminal = (
        read(prefix / "admission.json"),
        read(prefix / "terminal.json"),
    )
    absent(admission["process"])
    require(
        not (prefix / "failure.json").exists()
        and terminal["status"] == "completed"
        and terminal["job_id"] == admission["job_id"]
        and terminal["admission_sha256"] == digest(prefix / "admission.json")
        and admission["context_sha256"] == digest(output / "context.json"),
        "Completed original stage evidence required",
    )
    with sqlite3.connect(
        (root / "data/processed/catalog.sqlite3").as_uri() + "?mode=ro", uri=True
    ) as db:
        row = db.execute(
            "select document from jobs where id=?", (admission["job_id"],)
        ).fetchone()
    job = json.loads(row[0]) if row else {}
    require(
        job.get("status") == "completed"
        and job.get("owner_pid") == admission["process"]["pid"]
        and job.get("owner_started") == admission["process"]["creation_time"]
        and job.get("summary") == terminal["summary"],
        "Matching real Store lifetime/summary required",
    )
    return terminal["summary"]


def context_protocol(context, protocol):
    selected = CHECKOUT / (CONTINUATION if context["task"] == 242 else PROTOCOL)
    require(
        context["task"] == protocol["task"]
        and context["protocol_sha256"] == digest(selected)
        and json.dumps(protocol, sort_keys=True, allow_nan=False)
        == json.dumps(read(selected), sort_keys=True, allow_nan=False),
        "Context/protocol task binding changed",
    )


def gallery_directory(root, output, source_id, protocol):
    require(
        source_id in {s["source_id"] for s in protocol["sources"]},
        "Unknown source gallery",
    )
    prefix = (
        root / protocol["continuation"]["prepared_root"]
        if protocol["task"] == 242
        else output
    )
    return prefix / "galleries" / source_id


def original_prepared(root, protocol):
    """Reverify the unchanged prefix, original exits and Store; never old labels."""
    temporal = library()
    temporal.validate_continuation(protocol, read(CHECKOUT / PROTOCOL))
    continuation = protocol["continuation"]
    old = root / continuation["prepared_root"]
    producer = root / continuation["producer_checkout"]
    receipts = root / continuation["native_receipts"]
    for name, checksum in continuation["original_seals"].items():
        require(
            digest(temporal.safe_file(root, name)) == checksum,
            "Original prepared process/artifact seal changed",
        )
    require(
        digest(old / "context.json") == continuation["context_sha256"]
        and digest(old / "pilot-plan.json") == continuation["plan_sha256"]
        and digest(producer / PROTOCOL) == continuation["original_protocol_sha256"],
        "Original context/plan/protocol changed",
    )
    original = read(old / "context.json")
    for name, checksum in original["consumers"]["files"].items():
        require(
            digest(temporal.safe_file(producer, name)) == checksum,
            "Frozen producer changed",
        )
    require(
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=producer, text=True
        ).strip()
        == original["consumers"]["commit"]
        and not subprocess.check_output(["git", "status", "--porcelain"], cwd=producer),
        "Original producer checkout changed",
    )
    old_claim = original["grant"]["task"]["claim"]
    require(
        type(original["task"]) is int
        and original["task"] == 240
        and type(old_claim["granted_at"]) is int
        and original["deadline"] == old_claim["granted_at"] + 14400
        and old_claim["granted_at"] <= original["frozen_at"] < original["deadline"],
        "Preserve original immutable runtime interval",
    )
    require(
        not (old / "sessions").exists() and not (old / "assessment").exists(),
        "Original blocked pilot must have no assessor attempt",
    )
    owner, finish = read(receipts / "owner.json"), read(receipts / "finish.json")
    require(
        type(finish["returncode"]) is int
        and finish["returncode"] == 0
        and original["frozen_at"]
        <= finish["started_at"]
        < finish["ended_at"]
        <= original["deadline"]
        and digest(receipts / "stdout.log") == finish["stdout_sha256"]
        and digest(receipts / "stderr.log") == finish["stderr_sha256"],
        "Original completed wrapper interval/logs required",
    )
    for lifetime in [owner, *finish["observed_lifetimes"]]:
        absent(lifetime)
    summary = verify_stage(root, old, "preparation")
    admission = read(old / "preparation/admission.json")
    launcher = [
        r for r in finish["observed_lifetimes"] if r["pid"] == finish["launched_pid"]
    ]
    actual_owner = [
        r
        for r in finish["observed_lifetimes"]
        if r["pid"] == admission["process"]["pid"]
        and r["creation_time"] == admission["process"]["creation_time"]
    ]
    require(
        len(launcher) == len(actual_owner) == 1
        and launcher[0]["ppid"] == owner["pid"]
        and (
            actual_owner[0]["pid"] == launcher[0]["pid"]
            or actual_owner[0]["ppid"] == launcher[0]["pid"]
        )
        and summary["pilot_plan_sha256"] == continuation["plan_sha256"]
        and summary["metadata_gate_sha256"] == digest(old / "metadata-gate.json"),
        "Original wrapper/launcher/Store/artifact chain required",
    )
    gate = read(old / "metadata-gate.json")
    absent(gate["process"])
    require(
        gate["scientific_labels_read"] is False,
        "Original label-free metadata gate required",
    )
    plan = read(old / "pilot-plan.json")
    require(
        plan["task"] == 240
        and plan["context_sha256"] == continuation["context_sha256"]
        and plan["scientific_sessions"] == 6
        and plan["new_image_bytes"] == protocol["limits"]["new_image_bytes"],
        "Original exact payload plan changed",
    )
    source_ids = [s["source_id"] for s in protocol["sources"]]
    require(
        [e["source_id"] for e in plan["galleries"]] == source_ids,
        "Original source denominator changed",
    )
    images = []
    for source, entry in zip(protocol["sources"], plan["galleries"]):
        packet_path = temporal.safe_file(
            root / protocol["native_root"], source["source_id"] + ".packet.json"
        )
        require(
            digest(packet_path) == source["packet_sha256"],
            "Original dense packet changed",
        )
        packet = read(packet_path)
        require(
            len(packet["frames"]) == source["native_frame_count"]
            and packet["source_sha256"] == source["source_sha256"]
            and packet["clock_sha256"] == source["clock_sha256"],
            "Original source/clock/denominator changed",
        )
        images.append(
            temporal.verify_original_images(packet, root / protocol["native_root"])
        )
        gallery = gallery_directory(root, old, source["source_id"], protocol)
        require(
            digest(temporal.safe_file(gallery, "gallery.json"))
            == entry["manifest_sha256"]
            == continuation["manifests"][source["source_id"]],
            "Original gallery manifest changed",
        )
        manifest = temporal.verify_gallery(
            read(gallery / "gallery.json"), packet, gallery
        )
        require(
            temporal.payload_cost(manifest) == entry["payload"],
            "Original payload bytes changed",
        )
        require(
            digest(packet_path) == source["packet_sha256"],
            "Original packet changed during verification",
        )
    for name, checksum in continuation["original_seals"].items():
        require(
            digest(temporal.safe_file(root, name)) == checksum,
            "Original prefix changed during reuse",
        )
    return {
        "galleries": plan["galleries"],
        "original_context_sha256": continuation["context_sha256"],
        "original_plan_sha256": continuation["plan_sha256"],
        "original_deadline": original["deadline"],
        "original_store_job": admission["job_id"],
        "original_images": images,
        "rerendered_images": 0,
        "scientific_labels_read": False,
    }


def reuse_prepared(root, output, stamp, protocol):
    context = current(output, stamp)
    context_protocol(context, protocol)

    def calculate(progress):
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "gate",
                "--root",
                str(root),
                "--output",
                str(output),
                "--continuation",
            ],
            capture_output=True,
            check=False,
        )
        for name, raw in (
            ("metadata-stdout.log", result.stdout),
            ("metadata-stderr.log", result.stderr),
        ):
            with (output / name).open("xb") as handle:
                handle.write(raw)
        write(
            output / "metadata-process.json",
            {
                "returncode": result.returncode,
                "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
            },
        )
        require(result.returncode == 0, "Frozen metadata gate failed; preserve attempt")
        gate = read(output / "metadata-gate.json")
        absent(gate["process"])
        reused = original_prepared(root, protocol)
        payload = sum(e["payload"]["image_bytes"] for e in reused["galleries"]) * 3
        require(
            payload == protocol["limits"]["new_image_bytes"]
            and PRIOR_PAYLOAD + payload <= protocol["limits"]["cumulative_image_bytes"],
            "Exact authorized continuation payload required",
        )
        plan = {
            **reused,
            "task": 242,
            "context_sha256": digest(output / "context.json"),
            "scientific_sessions": 6,
            "new_image_bytes": payload,
            "cumulative_image_bytes": PRIOR_PAYLOAD + payload,
            "exact_contact_evidence": False,
        }
        write(output / "pilot-plan.json", plan)
        budget(root, protocol)
        progress(1)
        return {
            "pilot_plan_sha256": digest(output / "pilot-plan.json"),
            "metadata_gate_sha256": digest(output / "metadata-gate.json"),
            "new_image_bytes": payload,
            "scientific_sessions": 6,
            "rerendered_images": 0,
        }

    return admitted(root, output, "preparation", context, calculate)


def prepare(root, output, stamp, protocol):
    if protocol["task"] == 242:
        return reuse_prepared(root, output, stamp, protocol)
    context = current(output, stamp)
    context_protocol(context, protocol)
    temporal = library()

    def calculate(progress):
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "gate",
                "--root",
                str(root),
                "--output",
                str(output),
            ],
            capture_output=True,
            check=False,
        )
        for name, raw in (
            ("metadata-stdout.log", result.stdout),
            ("metadata-stderr.log", result.stderr),
        ):
            with (output / name).open("xb") as handle:
                handle.write(raw)
        write(
            output / "metadata-process.json",
            {
                "returncode": result.returncode,
                "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
            },
        )
        require(result.returncode == 0, "Frozen metadata gate failed; preserve attempt")
        audit = read(output / "metadata-gate.json")
        absent(audit["process"])
        require(
            audit["prior_retained_output_bytes"] + budget(root, protocol)
            < protocol["limits"]["cumulative_retained_bytes"],
            "Recounted cumulative output budget exhausted",
        )
        galleries = []
        for index, source in enumerate(protocol["sources"]):
            require(time.time() < context["deadline"], "Pilot deadline expired")
            packet_path = (
                root / protocol["native_root"] / (source["source_id"] + ".packet.json")
            )
            require(
                digest(packet_path) == source["packet_sha256"],
                "Original dense packet changed",
            )
            packet = read(packet_path)
            require(
                packet["source_id"] == source["source_id"]
                and len(packet["frames"]) == source["native_frame_count"],
                "Retain both original source denominators",
            )
            gallery = output / "galleries" / source["source_id"]
            manifest = temporal.render_gallery(
                packet, root / protocol["native_root"], gallery
            )
            temporal.verify_gallery(manifest, packet, gallery)
            galleries.append(
                {
                    "source_id": source["source_id"],
                    "manifest_sha256": digest(gallery / "gallery.json"),
                    "payload": temporal.payload_cost(manifest),
                    "native_frame_denominator": len(packet["frames"]),
                    "sampled_frames": len(manifest["plan"]["samples"]),
                }
            )
            progress((index + 1) / 2)
        new_payload = sum(g["payload"]["image_bytes"] for g in galleries) * 3
        require(
            new_payload <= 128 * 1024**2 and 8177560145 + new_payload <= 8 * 1024**3,
            "Six-session cumulative payload budget exceeded",
        )
        plan = {
            "task": 240,
            "galleries": galleries,
            "scientific_sessions": 6,
            "new_image_bytes": new_payload,
            "cumulative_image_bytes": 8177560145 + new_payload,
            "context_sha256": digest(output / "context.json"),
            "exact_contact_evidence": False,
        }
        write(output / "pilot-plan.json", plan)
        return {
            "pilot_plan_sha256": digest(output / "pilot-plan.json"),
            "metadata_gate_sha256": digest(output / "metadata-gate.json"),
            "new_image_bytes": new_payload,
            "scientific_sessions": 6,
        }

    return admitted(root, output, "preparation", context, calculate)


def schema():
    def obj(properties):
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": list(properties),
        }

    string = {"type": "string"}
    number = {"type": "integer"}
    boolean = {"type": "boolean"}

    def array(item):
        return {"type": "array", "items": item}

    def choice(options):
        return {"type": "string", "enum": list(options)}

    return obj(
        {
            "source_id": string,
            "lane": choice(("independent_a", "independent_b", "adjudication")),
            "session_id": string,
            "gallery_sha256": string,
            "evidence_kind": choice(("derived_sparse_temporal_context",)),
            "exact_contact_evidence": boolean,
            "eligibility": obj(
                dict.fromkeys(
                    (
                        "training_allowed",
                        "independent_test_allowed",
                        "model_deployment_allowed",
                        "dataset_redistribution_allowed",
                    ),
                    boolean,
                )
            ),
            "inspected_sheets": array(obj({"path": string, "sha256": string})),
            "frame_states": array(
                obj(
                    {
                        "frame": number,
                        "scene": choice(("live", "replay", "non_play", "unknown")),
                        "play_state": choice(
                            (
                                "service_preparation",
                                "exchange",
                                "stopped_play",
                                "non_play",
                                "replay",
                                "unknown",
                            )
                        ),
                        "camera_view": string,
                        "actor_ids": array(string),
                        "reason": string,
                    }
                )
            ),
            "actors": array(
                obj(
                    {
                        "actor_id": string,
                        "description": string,
                        "identity_supported": boolean,
                        "evidence_frames": array(number),
                    }
                )
            ),
            "transitions": array(
                obj(
                    {
                        "from_frame": number,
                        "to_frame": number,
                        "camera_continuity": choice(("same", "changed", "unknown")),
                        "actor_continuity": choice(
                            ("supported", "unresolved", "not_visible")
                        ),
                        "reason": string,
                    }
                )
            ),
            "limitations": string,
        }
    )


def prompt(manifest, lane, session):
    temporal = library()
    metadata = {k: v for k, v in manifest["plan"].items() if k not in ("memberships",)}
    attachments = [
        {"path": s["path"], "sha256": s["sha256"], "frames": s["frames"]}
        for s in manifest["sheets"]
    ]
    return f"""You are a fresh independent source-only badminton coarse temporal-context assessor for owner-authorized issue240. Inspect all attached DERIVED SPARSE CONTACT SHEETS in order; within each sheet read left-to-right then top-to-bottom. Tiles are640x360 letterboxed thumbnails of original source frames, sampled at1Hz plus endpoints. Blank unused tiles are padding. Unavailable labelled samples are unknown. These are NOT original-resolution contact evidence or continuous video. They cannot establish what occurred between samples.

No tools, filesystem, shell, network, delegation, account files, repository instructions, other images or labels are authorized. All inputs are attached. Return private JSON only under the schema. You have no other assessor's judgments; adjudication is another blind source-only reading, not permission to guess previous answers.

Echo source_id={manifest["plan"]["source_id"]}, lane={lane}, session_id={session}, gallery_sha256={temporal.fingerprint(manifest)}. evidence_kind=derived_sparse_temporal_context; exact_contact_evidence=false; all four eligibility flags=false. inspected_sheets must echo every attachment path/hash in order. frame_states must include EVERY sampled native frame in metadata order with explicit scene, coarse play_state, camera_view, actor_ids and concise source-evidence reason. Unknowns remain unknown. service_preparation is a visible preparatory stance, not an exact serve. exchange is only coarse visible play context; stopped_play cannot locate an exact rally ending. Replay needs visual source evidence; never infer live/replay from broadcast layout alone.

Define only source actor groups with concrete visible appearance, your own local stable IDs, identity_supported true ONLY when repeated visible evidence supports linking the same person. Avoid player names, tracker IDs, court end or screen position as sole identity evidence. Evidence_frames is the ordered unique set of sampled frames where that actor_id appears in frame_states; every occurrence must have its local definition. Retain identity_supported=false when unresolved; do not invent links to make a roster. Empty actors/actor_ids is valid if unsupported. A supported identity needs at least two actual visible samples. Camera labels remain stable only with visual evidence; use literal unknown when uncertain.

For EVERY consecutive pair of sampled native frames provide one transition with exact from_frame/to_frame, camera_continuity=same/changed/unknown and actor_continuity=supported/unresolved/not_visible. Supported requires same known camera and a shared visually supported local actor at BOTH endpoints; it does NOT establish continuous unsampled tracking. All other transitions remain unresolved or not_visible. Do not claim no contacts, exact contacts, shot family/side, precise serve/end, exhaustive coverage, human gold or complete rallies. Explain sparse/thumbnail/occlusion uncertainty in limitations. Whole-window context may still be insufficient; that is a valid result.

Native sparse metadata: {json.dumps(metadata, separators=(",", ":"))}
Ordered attachments: {json.dumps(attachments, separators=(",", ":"))}
"""


def bounded_drain(stream, path, record, limit=16 * 1024**2):
    value = hashlib.sha256()
    size = 0
    with path.open("xb") as handle:
        for block in iter(lambda: stream.read(65536), b""):
            value.update(block)
            if size < limit:
                handle.write(block[: limit - size])
            size += len(block)
    record.update(bytes=size, sha256=value.hexdigest(), truncated=size > limit)


def execute_session(output, gallery, manifest, lane, context, protocol):
    temporal = library()
    sid = manifest["plan"]["source_id"]
    folder = output / "sessions" / lane / sid
    folder.mkdir(parents=True, exist_ok=False)
    session = (
        f"codex-cli:temporal{context.get('task', 240)}:{lane}:{sid}:{time.time_ns()}"
    )
    message = prompt(manifest, lane, session)
    schema_path = folder / "schema.json"
    write(schema_path, schema())
    transport = temporal.payload_cost(
        manifest,
        context_bytes=len(json.dumps(message).encode()) + schema_path.stat().st_size,
    )
    existing = list((output / "sessions").glob("*/*/payload-reservation.json"))
    payload = sum(read(p)["image_bytes"] for p in existing) + transport["image_bytes"]
    require(
        len(existing) < 6
        and payload <= protocol.get("limits", {}).get("new_image_bytes", 128 * 1024**2)
        and 8177560145 + payload <= 8 * 1024**3,
        "Frozen pilot launch/payload budget exhausted",
    )
    require(time.time() < context["deadline"] - 60, "No new session in final minute")
    write(
        folder / "payload-reservation.json",
        {
            **transport,
            "lane": lane,
            "source_id": sid,
            "session_id": session,
            "reserved_at": time.time(),
        },
    )
    sandbox = folder / "empty-workspace"
    sandbox.mkdir()
    command = [
        context["consumers"]["cli"]["path"],
        "exec",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--ephemeral",
        "--json",
        "--cd",
        str(sandbox),
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(folder / "original-final.json"),
    ]
    for sheet in manifest["sheets"]:
        command.extend(("--image", str(temporal.safe_file(gallery, sheet["path"]))))
    command.append("-")
    env = os.environ.copy()
    for key in CREDENTIALS:
        env.pop(key, None)
    require(
        digest(command[0]) == context["consumers"]["cli"]["sha256"],
        "CLI executable changed",
    )
    write(
        folder / "invocation.json",
        {
            "command": command,
            "prompt_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
            "schema_sha256": digest(schema_path),
            "reserved_session_id": session,
        },
    )
    child = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=sandbox,
    )
    process = psutil.Process(child.pid)
    start = {
        **identity(process),
        "started_at": time.time(),
        "session_id": session,
        "gallery_sha256": temporal.fingerprint(manifest),
    }
    write(folder / "start.json", start)
    stdout, stderr = {}, {}
    readers = [
        threading.Thread(
            target=bounded_drain, args=(child.stdout, folder / "events.jsonl", stdout)
        ),
        threading.Thread(
            target=bounded_drain, args=(child.stderr, folder / "stderr.log", stderr)
        ),
    ]
    for thread in readers:
        thread.start()
    stdin_error = None
    try:
        child.stdin.write(message.encode("utf-8"))
        child.stdin.close()
    except OSError as error:
        stdin_error = type(error).__name__
    observed = {}
    while child.poll() is None:
        try:
            for live in [process, *process.children(recursive=True)]:
                try:
                    row = identity(live)
                    observed[(row["pid"], row["creation_time"])] = row
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except psutil.NoSuchProcess:
            pass
        time.sleep(0.2)
    code = child.wait()
    for thread in readers:
        thread.join()
    events, forbidden, threads, parse_errors = [], [], [], []
    if not stdout["truncated"]:
        for raw in (folder / "events.jsonl").read_bytes().splitlines():
            try:
                event = json.loads(raw)
                events.append(event.get("type"))
                if event.get("type") == "thread.started":
                    threads.append(event["thread_id"])
                item = event.get("item", {}).get("type")
                if item and item not in ("reasoning", "agent_message"):
                    forbidden.append(item)
            except (ValueError, KeyError, AttributeError, TypeError) as error:
                parse_errors.append(type(error).__name__)
    receipt = {
        **start,
        "ended_at": time.time(),
        "exit_code": code,
        "exited": True,
        "stdout": stdout,
        "stderr": stderr,
        "events": events,
        "forbidden_items": forbidden,
        "thread_id": threads[0] if len(threads) == 1 else None,
        "observed_lifetimes": list(observed.values()),
        "stdin_error": stdin_error,
        "parse_errors": parse_errors,
    }
    final = folder / "original-final.json"
    document = None
    if final.is_file():
        receipt["original_output_sha256"] = digest(final)
        try:
            document = read(final)
            receipt["document_sha256"] = temporal.fingerprint(document)
        except (ValueError, TypeError) as error:
            parse_errors.append(type(error).__name__)
    write(folder / "finish.json", receipt)
    absent(start)
    for row in observed.values():
        absent(row)
    require(
        not parse_errors and stdin_error is None,
        "Malformed original response/input; preserve completed execution receipt",
    )
    require(
        not stdout["truncated"]
        and not stderr["truncated"]
        and time.time() < context["deadline"],
        "Bounded pilot output/runtime exceeded",
    )
    require(not set(events) & {"error", "turn.failed"}, "Original CLI reported failure")
    require(
        final.is_file(), "Original assessor output missing; no replacement permitted"
    )
    temporal.validate_assessment(document, manifest, receipt, lane)
    return {
        "lane": lane,
        "source_id": sid,
        "receipt_sha256": digest(folder / "finish.json"),
        "document_sha256": digest(final),
        "session_id": session,
        "thread_id": receipt["thread_id"],
    }


def assess(root, output, stamp, gallery_stamp, protocol):
    context = current(output, stamp)
    context_protocol(context, protocol)
    temporal = library()
    prepared = verify_stage(root, output, "preparation")
    require(
        prepared["pilot_plan_sha256"] == digest(output / "pilot-plan.json"),
        "Prepared plan changed",
    )
    published = read(gallery_stamp)
    timestamp = datetime.fromisoformat(
        published["created_at"].replace("Z", "+00:00")
    ).timestamp()
    require(
        published["user"]["login"] == "Ken0u"
        and published["html_url"].startswith(
            f"https://github.com/Ken0u/badminton-match-analyzer/issues/{context['task']}#issuecomment-"
        )
        and digest(output / "pilot-plan.json") in published["body"]
        and context["frozen_at"] <= timestamp <= time.time(),
        "Prospective exact gallery/payload seal required",
    )
    plan = read(output / "pilot-plan.json")
    require(
        plan["task"] == protocol["task"]
        and plan["context_sha256"] == digest(output / "context.json"),
        "Prepared plan/context task binding changed",
    )

    def calculate(progress):
        entries = []
        try:
            for lane in temporal.LANES:
                for source in plan["galleries"]:
                    budget(root, protocol)
                    gallery = gallery_directory(
                        root, output, source["source_id"], protocol
                    )
                    require(
                        digest(gallery / "gallery.json") == source["manifest_sha256"],
                        "Sealed gallery manifest changed",
                    )
                    manifest = read(gallery / "gallery.json")
                    packet = read(
                        root
                        / protocol["native_root"]
                        / (source["source_id"] + ".packet.json")
                    )
                    temporal.verify_gallery(manifest, packet, gallery)
                    entries.append(
                        execute_session(
                            output, gallery, manifest, lane, context, protocol
                        )
                    )
                    write(
                        output / (f"completed-session-{len(entries):02d}.json"),
                        entries[-1],
                    )
                    progress(len(entries) / 6)
        except BaseException:
            write(
                output / "STOP.json",
                {
                    "sessions_completed": len(entries),
                    "stopped_at": time.time(),
                    "replacement_permitted": False,
                },
            )
            raise
        require(
            len({e["session_id"] for e in entries})
            == len({e["thread_id"] for e in entries})
            == 6,
            "Six genuine independent identities required",
        )
        write(output / "session-index.json", entries)
        return {
            "index_sha256": digest(output / "session-index.json"),
            "completed_sessions": 6,
            "new_image_bytes": plan["new_image_bytes"],
        }

    return admitted(root, output, "assessment", context, calculate)


def audit(root, output, stamp, protocol):
    context = current(output, stamp, live=False)
    context_protocol(context, protocol)
    temporal = library()
    if protocol["task"] == 242:
        original_prepared(root, protocol)
    prepared = verify_stage(root, output, "preparation")
    result = verify_stage(root, output, "assessment")
    require(
        result["index_sha256"] == digest(output / "session-index.json")
        and prepared["pilot_plan_sha256"] == digest(output / "pilot-plan.json"),
        "Completed stage artifacts changed",
    )
    entries = read(output / "session-index.json")
    expected = {
        (lane, s["source_id"]) for lane in temporal.LANES for s in protocol["sources"]
    }
    require(
        len(entries) == 6
        and {(e["lane"], e["source_id"]) for e in entries} == expected
        and len({e["thread_id"] for e in entries})
        == len({e["session_id"] for e in entries})
        == 6,
        "Global independent execution inventory incomplete",
    )
    # Audit every execution before reading any scientific JSON for comparison.
    receipts = {}
    for entry in entries:
        folder = output / "sessions" / entry["lane"] / entry["source_id"]
        require(
            digest(folder / "finish.json") == entry["receipt_sha256"]
            and digest(folder / "original-final.json") == entry["document_sha256"],
            "Original execution/output changed",
        )
        receipt = read(folder / "finish.json")
        require(
            receipt["session_id"] == entry["session_id"]
            and receipt["thread_id"] == entry["thread_id"]
            and type(receipt["exit_code"]) is int
            and receipt["exit_code"] == 0,
            "Original execution identity mismatch",
        )
        context = read(output / "context.json")
        require(
            context["frozen_at"]
            <= receipt["started_at"]
            < receipt["ended_at"]
            <= context["deadline"],
            "Original execution outside immutable pilot interval",
        )
        absent(receipt)
        for row in receipt["observed_lifetimes"]:
            absent(row)
        require(
            digest(folder / "events.jsonl") == receipt["stdout"]["sha256"]
            and digest(folder / "stderr.log") == receipt["stderr"]["sha256"]
            and receipt["forbidden_items"] == []
            and not receipt["stdout"]["truncated"]
            and not receipt["stderr"]["truncated"],
            "Original bounded tool-free logs required",
        )
        receipts[(entry["lane"], entry["source_id"])] = receipt
    summaries = []
    for source in protocol["sources"]:
        sid = source["source_id"]
        gallery = gallery_directory(root, output, sid, protocol)
        manifest = read(gallery / "gallery.json")
        documents = {}
        for lane in temporal.LANES:
            document = read(output / "sessions" / lane / sid / "original-final.json")
            documents[lane] = temporal.validate_assessment(
                document, manifest, receipts[(lane, sid)], lane
            )
        summaries.append(temporal.summarize(manifest, documents))
    aggregate = {
        "task": protocol["task"],
        "sources": summaries,
        "completed_pilot_sessions": 6,
        "native_frame_denominator": 1532,
        "complete_references": 0,
        "eligibility": dict(temporal.ELIGIBILITY),
        "new_image_bytes": result["new_image_bytes"],
        "prior_attempted_image_bytes": 8177560145,
        "retained_new_bytes": budget(root, protocol),
        "scientific_acceptance_changed": False,
    }
    write(output / "aggregate.json", aggregate)
    return {
        "aggregate_sha256": digest(output / "aggregate.json"),
        "completed_pilot_sessions": 6,
        "complete_references": 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=("freeze", "gate", "prepare", "assess", "audit")
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--timestamp", type=Path)
    parser.add_argument("--gallery-timestamp", type=Path)
    parser.add_argument("--continuation", action="store_true")
    args = parser.parse_args(argv)
    root, output = args.root.resolve(), args.output.resolve()
    require(
        output.is_relative_to(root / ".cache") and output != root / ".cache",
        "Private exclusive task output required",
    )
    protocol = read(CHECKOUT / (CONTINUATION if args.continuation else PROTOCOL))
    # The metadata subprocess must import only the frozen acceptance package.
    # Its protocol is checked against the already sealed context in metadata_gate.
    if args.continuation and args.stage != "gate":
        library().validate_continuation(protocol, read(CHECKOUT / PROTOCOL))
    if args.stage == "freeze":
        result = freeze(root, output, read(args.grant), protocol)
    elif args.stage == "gate":
        result = metadata_gate(root, output, protocol)
    elif args.stage == "prepare":
        result = prepare(root, output, args.timestamp, protocol)
    elif args.stage == "assess":
        result = assess(root, output, args.timestamp, args.gallery_timestamp, protocol)
    else:
        result = audit(root, output, args.timestamp, protocol)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
