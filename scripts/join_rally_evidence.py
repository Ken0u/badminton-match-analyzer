"""Freeze, assemble and audit private metadata; never view or transfer images.

Requires original-host artifacts and a prospective issue seal. Historical
metadata gates run in a clean subprocess before original scientific JSON is
opened. No earlier writing preparation, assessment or aggregation is invoked.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil

sys.dont_write_bytecode = True
CHECKOUT = Path(__file__).resolve().parents[1]
PROTOCOL = "data/manifests/rally_evidence_join_v1.json"
CONSUMERS = (
    "backend/badminton/rally_evidence_join.py",
    "scripts/join_rally_evidence.py",
    "tests/test_rally_evidence_join.py",
    PROTOCOL,
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
LANES = ("independent_a", "independent_b", "adjudication")
EXECUTION_ARTIFACTS = (
    "context.json",
    "attempt.json",
    "admission.json",
    "metadata-gate.json",
    "native-inputs.json",
    "aggregate.json",
    "joined-ledger.json",
    "gate-process.json",
    "gate-stdout.log",
    "gate-stderr.log",
    "native-process.json",
    "native-stdout.log",
    "native-stderr.log",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Nonfinite JSON")

    value = json.loads(
        Path(path).read_bytes(), object_pairs_hook=pairs, parse_constant=constant
    )

    def finite(node):
        if isinstance(node, float):
            require(math.isfinite(node), "Nonfinite JSON number")
        elif isinstance(node, dict):
            for child in node.values():
                finite(child)
        elif isinstance(node, list):
            for child in node:
                finite(child)

    finite(value)
    return value


def write(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
        )


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024**2), b""):
            value.update(block)
    return value.hexdigest()


def equal(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right, sort_keys=True, allow_nan=False
    )


def validate_protocol(protocol):
    require(
        protocol["output_root"] == ".cache/rally250-joined-v1",
        "Single preserved output root required",
    )
    require(
        type(protocol["schema_version"]) is int
        and protocol["schema_version"] == 1
        and type(protocol["task"]) is int
        and protocol["task"] == 250
        and protocol["spec_hash"]
        == "04005309f18cfbea6f9141393f18ca23a02fb07cc1273f497808c2ba3903c10d",
        "Frozen metadata task required",
    )
    require(
        equal(
            protocol["limits"],
            {
                "runtime_seconds": 14400,
                "new_output_bytes": 1073741824,
                "cumulative_retained_bytes": 8589934592,
                "new_scientific_sessions": 0,
                "new_image_payload_bytes": 0,
                "max_repair_rounds": 3,
                "implicit_retries": 0,
                "paid_services": False,
            },
        )
        and equal(
            protocol["denominators"],
            {
                "sources": 2,
                "native_frames": 1532,
                "sampled_frames": 53,
                "unsampled_frames": 1479,
            },
        ),
        "Frozen bounds and denominators changed",
    )
    require(
        equal(
            protocol["sources"],
            read(CHECKOUT / "data/manifests/rally_temporal_context_v2.json")["sources"],
        )
        and equal(
            protocol["preserved_result"],
            {
                "complete_references": 0,
                "all_requested_labels_supported_slots": 0,
                "eligibility": dict.fromkeys(
                    (
                        "training_allowed",
                        "independent_test_allowed",
                        "model_deployment_allowed",
                        "dataset_redistribution_allowed",
                    ),
                    False,
                ),
            },
        ),
        "Original source/result binding changed",
    )
    return protocol


def require_output(root, output, protocol):
    require(
        output == root / protocol["output_root"],
        "Single frozen private output required; no second attempt root",
    )


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def safe(root, name):
    root = Path(root).resolve(strict=True)
    path = root / name
    require(
        not Path(name).is_absolute() and path.resolve().is_relative_to(root),
        "Input escapes original root",
    )
    current = path
    while current != root:
        require(
            not current.is_symlink()
            and not getattr(current.lstat(), "st_file_attributes", 0) & 1024,
            "Linked metadata input",
        )
        current = current.parent
    return path


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
        and math.isfinite(row["creation_time"])
        and row["creation_time"] > 0,
        "Exact actual process lifetime required",
    )
    require(
        isinstance(row["cwd"], str)
        and bool(row["cwd"])
        and isinstance(row["command"], list)
        and bool(row["command"]),
        "Original cwd and command required",
    )
    try:
        require(
            abs(psutil.Process(row["pid"]).create_time() - row["creation_time"])
            >= 0.01,
            "Recorded lifetime still alive",
        )
    except psutil.NoSuchProcess:
        pass


def binding():
    require(
        not git(CHECKOUT, "status", "--porcelain"),
        "Commit tested consumer before freezing",
    )
    return {
        "commit": git(CHECKOUT, "rev-parse", "HEAD"),
        "files": {name: digest(CHECKOUT / name) for name in CONSUMERS},
        "python": platform.python_version(),
        "platform": platform.platform(),
        "psutil": psutil.__version__,
    }


def validate_grant(grant, protocol, now, host):
    task, receipt = grant["task"], grant["receipt"]
    claim = task["claim"]
    require(
        task["status"] == "running"
        and host == claim["host_id"] == "MSI"
        and claim["actor"] == receipt["actor"] == "Ken0u",
        "Current original-host owner grant required",
    )
    require(
        type(task["epoch"]) is int
        and task["epoch"] > 0
        and equal(task["epoch"], claim["epoch"])
        and equal(task["epoch"], receipt["epoch"]),
        "Strict ownership epoch required",
    )
    require(
        receipt["status"] == "granted"
        and receipt["task_id"] == "250"
        and type(receipt["claim"]["expires_at"]) is int
        and type(claim["expires_at"]) is int
        and receipt["claim"]["expires_at"] <= claim["expires_at"]
        and equal(
            {k: v for k, v in receipt["claim"].items() if k != "expires_at"},
            {k: v for k, v in claim.items() if k != "expires_at"},
        ),
        "Genuine committed grant receipt required",
    )
    require(
        task["spec_hash"] == claim["spec_hash"] == protocol["spec_hash"]
        and claim["branch"].startswith("codex/issue-250-"),
        "Frozen task binding changed",
    )
    require(
        type(claim["granted_at"]) is int
        and type(claim["expires_at"]) is int
        and claim["granted_at"] <= now < claim["expires_at"],
        "Current unexpired ownership required",
    )
    deadline = claim["granted_at"] + protocol["limits"]["runtime_seconds"]
    require(now < deadline, "Fresh metadata runtime expired")
    return deadline


def sealed(root, protocol):
    for name, checksum in protocol["sealed_inputs"].items():
        require(
            digest(safe(root, name)) == checksum,
            "Sealed original input changed: " + name,
        )


def frozen(root, protocol):
    for row in protocol["frozen_checkouts"]:
        checkout = safe(root, row["path"])
        require(
            git(checkout, "rev-parse", "HEAD") == row["commit"]
            and not git(checkout, "status", "--porcelain"),
            "Frozen checkout changed",
        )
        require(
            all(
                digest(safe(checkout, name)) == checksum
                for name, checksum in row["files"].items()
            ),
            "Frozen consumer changed",
        )
    native = module(
        root
        / protocol["frozen_checkouts"][0]["path"]
        / "scripts/diagnose_rally_references.py",
        "join_original_native",
    )
    temporal = module(
        root
        / protocol["frozen_checkouts"][1]["path"]
        / "scripts/pilot_rally_temporal_context.py",
        "join_original_temporal",
    )
    return native, temporal


def budget(root, protocol, prior=0):
    require(
        type(prior) is int and prior >= 0,
        "Nonnegative original retained-byte count required",
    )
    total = 0
    parents = [p for p in (root / ".cache").iterdir() if p.name.startswith("rally250")]
    parents.extend(
        p
        for p in (root / ".cache/worktrees").iterdir()
        if p.name.startswith("rally250")
    )
    for parent in parents:
        require(
            not parent.is_symlink()
            and not getattr(parent.lstat(), "st_file_attributes", 0) & 1024,
            "Linked task output root",
        )
        if parent.is_file():
            total += parent.stat().st_size
            continue
        for folder, dirs, names in os.walk(parent, followlinks=False):
            dirs[:] = [
                n
                for n in dirs
                if not (Path(folder) / n).is_symlink()
                and not getattr((Path(folder) / n).lstat(), "st_file_attributes", 0)
                & 1024
            ]
            total += sum((Path(folder) / n).lstat().st_size for n in names)
    require(
        total < protocol["limits"]["new_output_bytes"] - 1024**2
        and total + prior < protocol["limits"]["cumulative_retained_bytes"] - 1024**2,
        "Retained output budget exhausted",
    )
    return total


def freeze(root, output, grant, protocol):
    validate_protocol(protocol)
    require_output(root, output, protocol)
    now = time.time()
    deadline = validate_grant(grant, protocol, now, platform.node())
    sealed(root, protocol)
    context = {
        "task": 250,
        "consumers": binding(),
        "protocol_sha256": digest(CHECKOUT / PROTOCOL),
        "grant": grant,
        "frozen_at": now,
        "deadline": deadline,
        "old_scientific_runtime_renewed": False,
        "new_scientific_sessions": 0,
        "new_image_payload_bytes": 0,
    }
    budget(root, protocol)
    output.mkdir(exist_ok=False)
    write(output / "context.json", context)
    return {"context_sha256": digest(output / "context.json"), "deadline": deadline}


def current(output, stamp, protocol, *, live=True):
    validate_protocol(protocol)
    context, timestamp = read(output / "context.json"), read(stamp)
    published = datetime.fromisoformat(
        timestamp["created_at"].replace("Z", "+00:00")
    ).timestamp()
    require(
        equal(context["consumers"], binding())
        and context["protocol_sha256"] == digest(CHECKOUT / PROTOCOL),
        "Tested consumer binding changed",
    )
    require(
        timestamp["user"]["login"] == "Ken0u"
        and timestamp["html_url"].startswith(
            "https://github.com/Ken0u/badminton-match-analyzer/issues/250#issuecomment-"
        )
        and digest(output / "context.json") in timestamp["body"]
        and context["frozen_at"] <= published,
        "Prospective owning-issue seal required",
    )
    require(
        context["deadline"]
        == context["grant"]["task"]["claim"]["granted_at"]
        + protocol["limits"]["runtime_seconds"],
        "Immutable metadata interval changed",
    )
    if live:
        validate_grant(context["grant"], protocol, time.time(), platform.node())
        require(
            published <= time.time() < context["deadline"], "Metadata runtime expired"
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
        "Matching actual shared Store owner required",
    )
    return job


def live_parent(root, output):
    live_interval(output)
    admission = read(output / "admission.json")
    require(
        store_job(root, admission).get("status") == "running"
        and admission["context_sha256"] == digest(output / "context.json"),
        "Live real Store admission required",
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
        "Metadata process must descend from admitted owner",
    )


def live_interval(output):
    context = read(output / "context.json")
    require(
        context["frozen_at"]
        <= time.time()
        < min(context["deadline"], context["grant"]["task"]["claim"]["expires_at"]),
        "Metadata interval expired",
    )
    return context


def historical_stage(root, temporal, short, stage):
    base = root / ".cache/rally242-source-only-v1"
    receipts = root / f".cache/rally242-native-{short}-v1"
    summary = temporal.verify_stage(root, base, stage)
    owner, finish = read(receipts / "owner.json"), read(receipts / "finish.json")
    require(
        type(finish["returncode"]) is int
        and finish["returncode"] == 0
        and digest(receipts / "stdout.log") == finish["stdout_sha256"]
        and digest(receipts / "stderr.log") == finish["stderr_sha256"],
        "Original stage completion/log mismatch",
    )
    for row in [owner, *finish["observed_lifetimes"]]:
        absent(row)
    admission = read(base / stage / "admission.json")
    launcher = next(
        r for r in finish["observed_lifetimes"] if r["pid"] == finish["launched_pid"]
    )
    actual = next(
        r
        for r in finish["observed_lifetimes"]
        if r["pid"] == admission["process"]["pid"]
        and r["creation_time"] == admission["process"]["creation_time"]
    )
    require(
        launcher["ppid"] == owner["pid"]
        and (actual["pid"] == launcher["pid"] or actual["ppid"] == launcher["pid"]),
        "Original wrapper/launcher/Store chain required",
    )
    context = read(base / "context.json")
    require(
        context["frozen_at"]
        <= finish["started_at"]
        < finish["ended_at"]
        <= context["deadline"],
        "Original stage lifetime outside preserved interval",
    )
    return summary


def metadata(root, output, protocol, *, scientific=False):
    """Clean process: replay historical provenance before scientific parsing."""
    require(
        not any(n == "badminton" or n.startswith("badminton.") for n in sys.modules),
        "Clean historical metadata process required",
    )
    live_parent(root, output)
    sealed(root, protocol)
    native, temporal = frozen(root, protocol)
    temporal.archived_census(root)
    prior_protocol = read(
        root
        / protocol["frozen_checkouts"][0]["path"]
        / "data/manifests/rally_reference_diagnostics_v1.json"
    )
    recovery, old, acceptance = native.frozen(root, prior_protocol)
    plan, entries, audit = native.metadata_gate(
        root, recovery, old, acceptance, prior_protocol
    )
    # Reconstruct the unique native execution inventory using metadata only.
    _, _, suffix, identities = recovery.archive(root, old, acceptance)
    archived = root / ".cache/rally228-source-only-v1"
    context, published = recovery.current(
        archived, archived / "timestamp.json", live=False
    )
    for chunk in suffix:
        old.verify_run(
            root,
            acceptance,
            archived / "runs" / f"{old.SINGLES}-{chunk['index']:03d}",
            chunk,
            identities,
            granted_at=context["granted_at"],
            frozen_at=published,
            deadline=context["deadline"],
        )
    require(
        len(identities.threads) == 1014, "Original global execution denominator changed"
    )
    prepared = historical_stage(root, temporal, "prepare", "preparation")
    assessed = historical_stage(root, temporal, "assess", "assessment")
    base = root / protocol["coarse_root"]
    require(not (base / "STOP.json").exists(), "Preserve coarse failure fence")
    absent(read(base / "metadata-gate.json")["process"])
    index = read(base / "session-index.json")
    expected = {(lane, s["source_id"]) for lane in LANES for s in protocol["sources"]}
    require(
        len(index) == 6 and {(e["lane"], e["source_id"]) for e in index} == expected,
        "Exact six coarse executions required",
    )
    require(
        assessed["completed_sessions"] == 6
        and assessed["index_sha256"] == digest(base / "session-index.json")
        and prepared["pilot_plan_sha256"] == digest(base / "pilot-plan.json"),
        "Original coarse stage artifact mismatch",
    )
    old_context = read(base / "context.json")
    require(
        old_context["deadline"]
        == old_context["grant"]["task"]["claim"]["granted_at"] + 14400,
        "Original coarse deadline changed",
    )
    for entry in index:
        folder = base / "sessions" / entry["lane"] / entry["source_id"]
        require(
            digest(folder / "finish.json") == entry["receipt_sha256"]
            and digest(folder / "original-final.json") == entry["document_sha256"],
            "Original coarse execution/output changed",
        )
        finish = read(folder / "finish.json")
        require(
            finish["session_id"] == entry["session_id"]
            and finish["thread_id"] == entry["thread_id"]
            and type(finish["exit_code"]) is int
            and finish["exit_code"] == 0
            and finish["exited"] is True
            and finish["forbidden_items"] == [],
            "Coarse execution identity or exit invalid",
        )
        require(
            old_context["frozen_at"]
            <= finish["started_at"]
            < finish["ended_at"]
            <= old_context["deadline"],
            "Original coarse execution lifetime changed",
        )
        absent(finish)
        for row in finish["observed_lifetimes"]:
            absent(row)
        require(
            digest(folder / "events.jsonl") == finish["stdout"]["sha256"]
            and digest(folder / "stderr.log") == finish["stderr"]["sha256"]
            and not finish["stdout"]["truncated"]
            and not finish["stderr"]["truncated"],
            "Original bounded coarse logs changed",
        )
        identities.add(finish)
    require(len(identities.threads) == 1020, "Global execution independence changed")
    # Full original preparation seals/Store/lifetimes, without gallery rendering
    # or invoking the old image-decoding reuse helper.
    prior = read(
        root
        / protocol["frozen_checkouts"][1]["path"]
        / "data/manifests/rally_temporal_context_v2.json"
    )
    original = root / prior["continuation"]["prepared_root"]
    require(
        not (original / "sessions").exists() and not (original / "assessment").exists(),
        "Original blocked preparation acquired an assessor",
    )
    temporal.verify_stage(root, original, "preparation")
    receipts = root / prior["continuation"]["native_receipts"]
    original_finish = read(receipts / "finish.json")
    for row in [
        read(receipts / "owner.json"),
        *original_finish["observed_lifetimes"],
        read(original / "metadata-gate.json")["process"],
    ]:
        absent(row)
    new_bytes = budget(
        root,
        protocol,
        audit["prior_retained_output_bytes"]
        + native.new_bytes(root)
        + temporal.task_bytes(root, 240)
        + temporal.task_bytes(root, 242),
    )
    result = {
        "historical_execution_identities": 1014,
        "coarse_execution_identities": 6,
        "global_execution_identities": 1020,
        "target_references": len(entries),
        "scientific_labels_read": False,
        "process": identity(psutil.Process()),
        "completed_at": time.time(),
        "new_retained_bytes": new_bytes,
        "prior_retained_bytes": audit["prior_retained_output_bytes"]
        + native.new_bytes(root)
        + temporal.task_bytes(root, 240)
        + temporal.task_bytes(root, 242),
    }
    require(len(entries) == 256, "Original target denominator changed")
    if not scientific:
        live_interval(output)
        write(output / "metadata-gate.json", result)
        return result
    require(
        (output / "metadata-gate.json").is_file()
        and read(output / "metadata-gate.json")["scientific_labels_read"] is False,
        "Completed metadata gate required before scientific read",
    )
    sources = []
    for source in plan["sources"]:
        live_interval(output)
        packet, streams, provenance = native.load_streams(
            root, old, acceptance, source, entries
        )
        status = acceptance.targeted_reference_status(
            streams,
            native_frames=[r["frame"] for r in packet["frames"]],
            bounds=source["bounds"],
        )
        sources.append(
            {
                "source_id": source["source_id"],
                "packet": packet,
                "streams": streams,
                "provenance": provenance,
                "scientific_status": status,
            }
        )
    # Compare frozen original status; no replacement scientific acceptance.
    diagnostics = module(
        root
        / protocol["frozen_checkouts"][0]["path"]
        / "backend/badminton/rally_reference_diagnostics.py",
        "join_original_diagnostics",
    )
    original_aggregate = read(root / ".cache/rally228-source-only-v1/aggregate.json")
    diagnostics.require_unchanged(
        [
            {
                "source_id": s["source_id"],
                "native_frames": len(s["packet"]["frames"]),
                "scientific_status": s["scientific_status"],
            }
            for s in sources
        ],
        original_aggregate,
    )
    sealed(root, protocol)
    live_interval(output)
    write(
        output / "native-inputs.json",
        {
            "sources": sources,
            "process": identity(psutil.Process()),
            "gate_sha256": digest(output / "metadata-gate.json"),
        },
    )
    return {"source_slots": len(sources), "scientific_acceptance_changed": False}


def child(root, output, phase):
    live_interval(output)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        phase,
        "--root",
        str(root),
        "--output",
        str(output),
    ]
    started = time.time()
    with (
        (output / (phase + "-stdout.log")).open("xb") as stdout,
        (output / (phase + "-stderr.log")).open("xb") as stderr,
    ):
        process = subprocess.Popen(command, cwd=CHECKOUT, stdout=stdout, stderr=stderr)
        observed = identity(psutil.Process(process.pid))
        lifetimes = {}
        while process.poll() is None:
            try:
                launcher = psutil.Process(process.pid)
                for descendant in [launcher, *launcher.children(recursive=True)]:
                    try:
                        row = {**identity(descendant), "ppid": descendant.ppid()}
                        lifetimes[(row["pid"], row["creation_time"])] = row
                    except psutil.NoSuchProcess:
                        pass
            except psutil.NoSuchProcess:
                pass
            time.sleep(0.1)
        code = process.wait()
    write(
        output / (phase + "-process.json"),
        {
            "process": observed,
            "observed_lifetimes": list(lifetimes.values()),
            "returncode": code,
            "started_at": started,
            "ended_at": time.time(),
            "stdout_sha256": digest(output / (phase + "-stdout.log")),
            "stderr_sha256": digest(output / (phase + "-stderr.log")),
        },
    )
    require(code == 0, "Preserve failed historical subprocess; no implicit repeat")
    absent(observed)
    artifact = read(
        output / ("metadata-gate.json" if phase == "gate" else "native-inputs.json")
    )
    verify_child_evidence(
        read(output / (phase + "-process.json")),
        artifact["process"],
        read(output / "context.json"),
    )


def verify_child_evidence(receipt, actual, context):
    require(
        all(
            type(receipt[k]) in (int, float) and math.isfinite(receipt[k])
            for k in ("started_at", "ended_at")
        ),
        "Finite real subprocess timestamps required",
    )
    require(
        context["frozen_at"]
        <= receipt["started_at"]
        < receipt["ended_at"]
        <= context["deadline"],
        "Metadata subprocess outside immutable interval",
    )
    rows = receipt["observed_lifetimes"]
    keys = [(r["pid"], r["creation_time"]) for r in rows]
    require(
        len(set(keys)) == len(keys) and len({r["pid"] for r in rows}) == len(rows),
        "Duplicate or ambiguous observed process lifetime",
    )
    require(
        all(type(r["ppid"]) is int and r["ppid"] > 0 for r in rows),
        "Observed parent process IDs required",
    )
    launched = receipt["process"]
    require(
        any(equal({k: r[k] for k in launched}, launched) for r in rows)
        and any(equal({k: r[k] for k in actual}, actual) for r in rows),
        "Actual worker and launcher must be independently observed",
    )
    ancestry = {r["pid"]: r for r in rows}
    cursor, visited = actual["pid"], set()
    while cursor != launched["pid"]:
        require(
            cursor in ancestry and cursor not in visited,
            "Actual worker escaped observed launcher chain",
        )
        visited.add(cursor)
        cursor = ancestry[cursor]["ppid"]
    for row in [launched, actual, *rows]:
        absent(row)


def library():
    sys.path.insert(0, str(CHECKOUT / "backend"))
    from badminton import rally_evidence_join

    require(
        Path(rally_evidence_join.__file__).resolve() == CHECKOUT / CONSUMERS[0],
        "Wrong joined consumer origin",
    )
    return rally_evidence_join


def assemble(root, output, protocol):
    child(root, output, "gate")
    child(root, output, "native")
    live_interval(output)
    join = library()
    native = read(output / "native-inputs.json")
    census = read(root / protocol["native_ledger"])
    by_source = {s["source_id"]: s for s in native["sources"]}
    require(
        len(by_source) == len(native["sources"]) == 2 and set(census) == set(by_source),
        "Both original sources required",
    )
    ledgers, results = {}, []
    for source in sorted(protocol["sources"], key=lambda s: s["source_id"]):
        live_interval(output)
        sid = source["source_id"]
        row = by_source[sid]
        packet_path = safe(root / protocol["native_root"], sid + ".packet.json")
        require(
            digest(packet_path) == source["packet_sha256"]
            and equal(read(packet_path), row["packet"]),
            "Exact native packet changed",
        )
        require(
            equal(row["provenance"], census[sid]["provenance"]),
            "Original census document provenance changed",
        )
        coarse = {}
        for lane in LANES:
            folder = root / protocol["coarse_root"] / "sessions" / lane / sid
            coarse[lane] = {
                "document": read(folder / "original-final.json"),
                "receipt": read(folder / "finish.json"),
                "provenance": {
                    "original_path": str(folder / "original-final.json"),
                    "original_sha256": digest(folder / "original-final.json"),
                    "receipt_path": str(folder / "finish.json"),
                    "receipt_sha256": digest(folder / "finish.json"),
                },
            }
        manifest = read(root / protocol["gallery_root"] / sid / "gallery.json")
        aggregate, ledger = join.join_source(
            row["packet"],
            row["streams"],
            census[sid],
            manifest,
            coarse,
            expected_source=source,
        )
        results.append(aggregate)
        ledgers[sid] = ledger
    summary = join.summarize_sources(results)
    require(
        summary["native_frames"] == 1532
        and summary["sampled_frames"] == 53
        and summary["unsampled_native_frames"] == 1479,
        "Joined native/sparse denominator changed",
    )
    sealed(root, protocol)
    preserved = read(root / protocol["native_aggregate"])
    require(
        type(preserved["complete_references"]) is int
        and preserved["complete_references"] == 0
        and type(preserved["all_requested_labels_supported_slots"]) is int
        and preserved["all_requested_labels_supported_slots"] == 0
        and equal(
            preserved["eligibility"], protocol["preserved_result"]["eligibility"]
        ),
        "Historical acceptance changed",
    )
    aggregate = {
        "task": 250,
        "diagnostics": summary,
        "complete_references": 0,
        "all_requested_labels_supported_slots": 0,
        "eligibility": preserved["eligibility"],
        "scientific_acceptance_changed": False,
        "new_scientific_sessions": 0,
        "new_image_payload_bytes": 0,
        "full_match_accuracy_established": False,
        "metadata_gate_sha256": digest(output / "metadata-gate.json"),
        "context_sha256": digest(output / "context.json"),
        "protocol_sha256": digest(CHECKOUT / PROTOCOL),
    }
    live_interval(output)
    write(output / "joined-ledger.json", ledgers)
    aggregate["joined_ledger_sha256"] = digest(output / "joined-ledger.json")
    live_interval(output)
    write(output / "aggregate.json", aggregate)
    budget(root, protocol, read(output / "metadata-gate.json")["prior_retained_bytes"])
    return {
        "aggregate_sha256": digest(output / "aggregate.json"),
        "joined_ledger_sha256": digest(output / "joined-ledger.json"),
        "source_slots": 2,
        "complete_references": 0,
        "full_match_accuracy_established": False,
        "artifacts": {name: digest(output / name) for name in EXECUTION_ARTIFACTS},
    }


def execute(root, output, stamp, protocol):
    require_output(root, output, protocol)
    context = current(output, stamp, protocol)
    require(
        not any(
            (output / n).exists()
            for n in (
                "admission.json",
                "terminal.json",
                "failure.json",
                "attempt.json",
                "aggregate.json",
                "metadata-gate.json",
                "native-inputs.json",
                "joined-ledger.json",
            )
        ),
        "Attempt already exists; preserve it and diagnose before another",
    )
    require(
        all(not os.environ.get(k) for k in CREDENTIALS),
        "Credential-free metadata execution required",
    )
    write(
        output / "attempt.json",
        {
            "started_at": time.time(),
            "process": identity(psutil.Process()),
            "implicit_retry_permitted": False,
        },
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
        "Pin original roots and real existing shared Store before imports",
    )
    job_id = None

    def work(identifier, progress):
        nonlocal job_id
        job_id = identifier
        write(
            output / "admission.json",
            {
                "job_id": identifier,
                "context_sha256": digest(output / "context.json"),
                "process": identity(psutil.Process()),
            },
        )
        require(time.time() < context["deadline"], "Metadata interval expired")
        result = assemble(root, output, protocol)
        require(time.time() < context["deadline"], "Metadata interval expired")
        progress(1)
        return result

    try:
        result = run_local_job(
            Store(config.DATA), "rally_evidence_join", "sealed-rally250", work
        )
    except BaseException as error:
        write(
            output / "failure.json",
            {
                "job_id": job_id,
                "error_type": type(error).__name__,
                "message": str(error),
                "implicit_retry_permitted": False,
            },
        )
        raise
    write(
        output / "terminal.json",
        {
            "status": "completed",
            "job_id": job_id,
            "admission_sha256": digest(output / "admission.json"),
            "summary": result,
        },
    )
    return result


def verify_completed_artifacts(output, summary):
    require(
        set(summary["artifacts"]) == set(EXECUTION_ARTIFACTS),
        "Exact completed artifact inventory required",
    )
    for name, checksum in summary["artifacts"].items():
        require(
            digest(output / name) == checksum,
            "Completed execution artifact changed: " + name,
        )
    require(
        {p.name for p in output.iterdir()}
        == set(EXECUTION_ARTIFACTS) | {"terminal.json"},
        "Unexpected private execution output",
    )


def audit(root, output, stamp, protocol):
    current(output, stamp, protocol, live=False)
    require(
        not (output / "failure.json").exists(),
        "Failed original attempt must remain fenced",
    )
    admission, terminal = (
        read(output / "admission.json"),
        read(output / "terminal.json"),
    )
    absent(admission["process"])
    absent(read(output / "attempt.json")["process"])
    job = store_job(root, admission)
    require(
        job.get("status") == terminal["status"] == "completed"
        and equal(job.get("summary"), terminal["summary"])
        and terminal["job_id"] == admission["job_id"]
        and terminal["admission_sha256"] == digest(output / "admission.json"),
        "Matching completed Store/terminal required",
    )
    verify_completed_artifacts(output, terminal["summary"])
    sealed(root, protocol)
    for phase in ("gate", "native"):
        receipt = read(output / (phase + "-process.json"))
        require(
            type(receipt["returncode"]) is int and receipt["returncode"] == 0,
            "Subprocess did not complete",
        )
        require(
            receipt["stdout_sha256"] == digest(output / (phase + "-stdout.log"))
            and receipt["stderr_sha256"] == digest(output / (phase + "-stderr.log")),
            "Subprocess logs changed",
        )
        absent(receipt["process"])
        actual = read(
            output / ("metadata-gate.json" if phase == "gate" else "native-inputs.json")
        )["process"]
        verify_child_evidence(receipt, actual, read(output / "context.json"))
    gate, native = (
        read(output / "metadata-gate.json"),
        read(output / "native-inputs.json"),
    )
    absent(gate["process"])
    absent(native["process"])
    require(
        native["gate_sha256"] == digest(output / "metadata-gate.json")
        and gate["global_execution_identities"] == 1020,
        "Historical metadata gate changed",
    )
    aggregate = read(output / "aggregate.json")
    require(
        aggregate["metadata_gate_sha256"] == digest(output / "metadata-gate.json")
        and aggregate["context_sha256"] == digest(output / "context.json")
        and aggregate["protocol_sha256"] == digest(CHECKOUT / PROTOCOL),
        "Aggregate gate/context/protocol binding changed",
    )
    require(
        terminal["summary"]["aggregate_sha256"] == digest(output / "aggregate.json")
        and terminal["summary"]["joined_ledger_sha256"]
        == aggregate["joined_ledger_sha256"]
        == digest(output / "joined-ledger.json"),
        "Completed joined artifact changed",
    )
    join = library()
    originals = read(root / protocol["native_ledger"])
    ledgers = read(output / "joined-ledger.json")
    results = []
    for source in sorted(protocol["sources"], key=lambda s: s["source_id"]):
        sid = source["source_id"]
        row = next(s for s in native["sources"] if s["source_id"] == sid)
        streams = {}
        for lane in LANES:
            folder = root / protocol["coarse_root"] / "sessions" / lane / sid
            streams[lane] = {
                "document": read(folder / "original-final.json"),
                "receipt": read(folder / "finish.json"),
                "provenance": {
                    "original_path": str(folder / "original-final.json"),
                    "original_sha256": digest(folder / "original-final.json"),
                    "receipt_path": str(folder / "finish.json"),
                    "receipt_sha256": digest(folder / "finish.json"),
                },
            }
        result, rebuilt = join.join_source(
            row["packet"],
            row["streams"],
            originals[sid],
            read(root / protocol["gallery_root"] / sid / "gallery.json"),
            streams,
            expected_source=source,
        )
        require(
            equal(rebuilt, ledgers[sid]),
            "Joined occurrence ledger differs from original evidence",
        )
        results.append(result)
    require(
        equal(join.summarize_sources(results), aggregate["diagnostics"]),
        "Aggregate denominator/occurrences changed",
    )
    require(
        all(
            aggregate[k] is False
            for k in (
                "scientific_acceptance_changed",
                "full_match_accuracy_established",
            )
        )
        and aggregate["new_scientific_sessions"]
        == aggregate["new_image_payload_bytes"]
        == aggregate["complete_references"]
        == aggregate["all_requested_labels_supported_slots"]
        == 0
        and equal(
            aggregate["eligibility"], protocol["preserved_result"]["eligibility"]
        ),
        "Join cannot promote historical science",
    )
    budget(root, protocol, gate["prior_retained_bytes"])
    return {
        "task": 250,
        "aggregate_sha256": digest(output / "aggregate.json"),
        "joined_ledger_sha256": digest(output / "joined-ledger.json"),
        "original_inputs_unchanged": True,
        "all_recorded_metadata_lifetimes_absent": True,
        "new_scientific_sessions": 0,
        "new_image_payload_bytes": 0,
        "complete_references": 0,
        "full_match_accuracy_established": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run", "gate", "native", "audit"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--timestamp", type=Path)
    args = parser.parse_args(argv)
    root, output = args.root.resolve(strict=True), args.output.resolve()
    for key in CREDENTIALS:
        os.environ.pop(key, None)
    os.environ.update(
        BADMINTON_ROOT=str(root),
        BADMINTON_DATA_DIR=str(root / "data/processed"),
        BADMINTON_WEIGHTS_DIR=str(root / "models/weights"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    protocol = validate_protocol(read(CHECKOUT / PROTOCOL))
    require_output(root, output, protocol)
    if args.phase == "freeze":
        require(args.grant is not None, "Committed grant required")
        result = freeze(root, output, read(args.grant), protocol)
    elif args.phase in ("gate", "native"):
        result = metadata(root, output, protocol, scientific=args.phase == "native")
    else:
        require(args.timestamp is not None, "Prospective issue timestamp required")
        result = (execute if args.phase == "run" else audit)(
            root, output, args.timestamp, protocol
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
