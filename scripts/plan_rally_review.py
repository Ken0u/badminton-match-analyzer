"""Freeze, run and audit a private metadata-only prospective review schedule.

No assessor, image dispatcher or authenticated service client is provided.
The historical read-only audit must pass before packet/gallery JSON is opened.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil

sys.dont_write_bytecode = True
CHECKOUT = Path(__file__).resolve().parents[1]
PROTOCOL = "data/manifests/rally_review_plan_v1.json"
CONSUMERS = (
    "backend/badminton/rally_review_plan.py",
    "scripts/plan_rally_review.py",
    "tests/test_rally_review_plan.py",
    PROTOCOL,
    "scripts/join_rally_evidence.py",
    "backend/badminton/rally_temporal_context.py",
    "backend/badminton/rally_evidence_join.py",
)
_spec = importlib.util.spec_from_file_location(
    "rally_review_common", CHECKOUT / "scripts/join_rally_evidence.py"
)
common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(common)
require, read, write, digest = common.require, common.read, common.write, common.digest
equal, safe, identity, absent = (
    common.equal,
    common.safe,
    common.identity,
    common.absent,
)
CREDENTIALS = (
    *common.CREDENTIALS,
    "BADMINTON_USERNAME",
    "BADMINTON_PASSWORD",
    "BASE_URL",
)
ARTIFACTS = (
    "context.json",
    "attempt.json",
    "admission.json",
    "prior-audit-process.json",
    "prior-audit-stdout.log",
    "prior-audit-stderr.log",
    "plan.json",
    "aggregate.json",
)


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, child in items:
            require(key not in value, "Duplicate JSON key")
            value[key] = child
        return value

    def finite(value):
        if type(value) is float:
            require(math.isfinite(value), "Nonfinite JSON")
        elif isinstance(value, (list, dict)):
            for child in value.values() if isinstance(value, dict) else value:
                finite(child)

    value = json.loads(raw, object_pairs_hook=pairs)
    finite(value)
    return value


def validate_protocol(protocol):
    original = read(CHECKOUT / "data/manifests/rally_evidence_join_v1.json")
    require(
        type(protocol["schema_version"]) is int
        and protocol["schema_version"] == 1
        and type(protocol["task"]) is int
        and protocol["task"] == 262
        and protocol["spec_hash"]
        == "4d86dceb4dc5d9a2cdc73b334d55205f17af6c0cea288ff0dd87744c1a93b021"
        and protocol["output_root"] == ".cache/rally262-plan-v1",
        "Frozen metadata task/output required",
    )
    require(
        equal(
            protocol["limits"],
            {
                "runtime_seconds": 14400,
                "new_output_bytes": 536870912,
                "cumulative_retained_bytes": 8589934592,
                "new_scientific_sessions": 0,
                "new_image_payload_bytes": 0,
                "max_repair_rounds": 3,
                "implicit_retries": 0,
                "paid_services": False,
            },
        )
        and equal(
            protocol["packing"],
            {
                "max_bytes": 9437184,
                "max_images": 20,
                "preceding_overlap_frames": 1,
                "nearest_sample_tie": "lower_native_ordinal",
                "lanes": ["independent_a", "independent_b", "source_adjudication"],
            },
        ),
        "Frozen limits/packing changed",
    )
    for key in (
        "sources",
        "native_root",
        "gallery_root",
        "denominators",
        "preserved_result",
        "historical_provenance",
    ):
        require(
            equal(protocol[key], original[key]), "Historical binding changed: " + key
        )
    require(
        protocol["prior"]["checkout"] == ".cache/worktrees/rally250-producer-v1"
        and protocol["prior"]["commit"] == "001ddea7734c189049363fa33bedc88c7544705a"
        and protocol["prior"]["output"] == ".cache/rally250-joined-v1"
        and protocol["prior"]["timestamp"] == ".cache/rally250-timestamp-v1.json",
        "Original tested audit only",
    )
    require(
        all(
            protocol["sealed_inputs"].get(k) == v
            for k, v in original["sealed_inputs"].items()
        ),
        "Original input seals changed",
    )
    return protocol


def binding():
    require(
        not common.git(CHECKOUT, "status", "--porcelain"),
        "Commit tested consumer first",
    )
    return {
        "commit": common.git(CHECKOUT, "rev-parse", "HEAD"),
        "files": {name: digest(CHECKOUT / name) for name in CONSUMERS},
        "python": platform.python_version(),
        "platform": platform.platform(),
        "psutil": psutil.__version__,
    }


def validate_grant(grant, protocol, now, host):
    task, receipt = grant["task"], grant["receipt"]
    claim = task["claim"]
    require(
        type(now) in (int, float)
        and math.isfinite(now)
        and task["status"] == "running"
        and host == claim["host_id"] == "MSI"
        and claim["actor"] == receipt["actor"] == "Ken0u",
        "Current original-host grant required",
    )
    require(
        all(
            type(v) is int and v > 0
            for v in (task["epoch"], claim["epoch"], receipt["epoch"])
        )
        and task["epoch"] == claim["epoch"] == receipt["epoch"]
        and receipt["status"] == "granted"
        and receipt["task_id"] == "262"
        and type(receipt["claim"]["expires_at"]) is int
        and type(claim["expires_at"]) is int
        and receipt["claim"]["expires_at"] <= claim["expires_at"]
        and equal(
            {k: v for k, v in receipt["claim"].items() if k != "expires_at"},
            {k: v for k, v in claim.items() if k != "expires_at"},
        ),
        "Genuine committed epoch and receipt required",
    )
    require(
        task["spec_hash"] == claim["spec_hash"] == protocol["spec_hash"]
        and claim["branch"].startswith("codex/issue-262-")
        and type(claim["granted_at"]) is int
        and claim["granted_at"] <= now < claim["expires_at"],
        "Unexpired frozen ownership required",
    )
    deadline = claim["granted_at"] + protocol["limits"]["runtime_seconds"]
    require(now < deadline, "Immutable metadata runtime expired")
    return deadline


def require_output(root, output, protocol):
    require(
        output == root / protocol["output_root"], "Single fixed private output required"
    )
    require(not output.is_symlink(), "Linked output forbidden")


def verify_inputs(root, protocol):
    common.sealed(root, protocol)
    prior = protocol["prior"]
    checkout = safe(root, prior["checkout"])
    require(
        common.git(checkout, "rev-parse", "HEAD") == prior["commit"]
        and not common.git(checkout, "status", "--porcelain"),
        "Historical tested checkout changed",
    )
    require(
        all(digest(safe(checkout, k)) == v for k, v in prior["files"].items()),
        "Historical tested consumer changed",
    )


def budget(root, protocol, prior=0):
    require(
        type(prior) is int and prior >= 0, "Nonnegative prior output count required"
    )
    total = 0
    parents = [p for p in (root / ".cache").iterdir() if p.name.startswith("rally262")]
    parents += [
        p
        for p in (root / ".cache/worktrees").iterdir()
        if p.name.startswith("rally262")
    ]
    for parent in parents:
        require(
            not parent.is_symlink()
            and not getattr(parent.lstat(), "st_file_attributes", 0) & 1024,
            "Linked task outputs",
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
    require_output(root, output, protocol)
    now = time.time()
    deadline = validate_grant(grant, protocol, now, platform.node())
    verify_inputs(root, protocol)
    consumers = binding()
    require(
        common.git(CHECKOUT, "branch", "--show-current")
        == grant["task"]["claim"]["branch"],
        "Granted implementation branch required",
    )
    budget(root, protocol)
    output.mkdir(exist_ok=False)
    write(
        output / "context.json",
        {
            "task": 262,
            "consumers": consumers,
            "protocol_sha256": digest(CHECKOUT / PROTOCOL),
            "grant": grant,
            "frozen_at": now,
            "deadline": deadline,
            "new_scientific_sessions": 0,
            "new_image_payload_bytes": 0,
            "old_scientific_runtime_renewed": False,
        },
    )
    return {"context_sha256": digest(output / "context.json"), "deadline": deadline}


def current(output, stamp, protocol, *, live=True):
    context, timestamp = read(output / "context.json"), read(stamp)
    published = datetime.fromisoformat(
        timestamp["created_at"].replace("Z", "+00:00")
    ).timestamp()
    require(
        equal(context["consumers"], binding())
        and context["protocol_sha256"] == digest(CHECKOUT / PROTOCOL),
        "Tested consumer/protocol changed",
    )
    require(
        timestamp["user"]["login"] == "Ken0u"
        and timestamp["html_url"].startswith(
            "https://github.com/Ken0u/badminton-match-analyzer/issues/262#issuecomment-"
        )
        and digest(output / "context.json") in timestamp["body"]
        and context["frozen_at"] <= published < context["deadline"],
        "Prospective owning-issue seal required",
    )
    require(
        context["deadline"] == context["grant"]["task"]["claim"]["granted_at"] + 14400,
        "Immutable metadata interval changed",
    )
    if live:
        validate_grant(context["grant"], protocol, time.time(), platform.node())
        require(
            published <= time.time() < context["deadline"], "Metadata interval expired"
        )
    return context


def prior_command(root, protocol):
    prior = protocol["prior"]
    checkout = safe(root, prior["checkout"])
    return [
        sys.executable,
        str(checkout / "scripts/join_rally_evidence.py"),
        "audit",
        "--root",
        str(root),
        "--output",
        str(root / prior["output"]),
        "--timestamp",
        str(root / prior["timestamp"]),
    ]


def prior_environment(root, protocol):
    env = os.environ.copy()
    for key in CREDENTIALS:
        env.pop(key, None)
    env.update(
        BADMINTON_ROOT=str(root),
        BADMINTON_DATA_DIR=str(root / "data/processed"),
        BADMINTON_WEIGHTS_DIR=str(root / "models/weights"),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
        PYTHONPATH=str(root / protocol["prior"]["checkout"] / "backend"),
    )
    return env


def validate_prior_result(root, protocol, raw):
    # Parse only the audit's public completion metadata, never its scientific ledger.
    result = strict_json(raw)
    require(
        result.get("task") == 250
        and result.get("aggregate_sha256")
        == protocol["sealed_inputs"][".cache/rally250-joined-v1/aggregate.json"]
        and result.get("joined_ledger_sha256")
        == protocol["sealed_inputs"][".cache/rally250-joined-v1/joined-ledger.json"]
        and result.get("original_inputs_unchanged") is True
        and result.get("all_recorded_metadata_lifetimes_absent") is True
        and type(result.get("complete_references")) is int
        and result["complete_references"] == 0
        and type(result.get("new_scientific_sessions")) is int
        and result["new_scientific_sessions"] == 0
        and type(result.get("new_image_payload_bytes")) is int
        and result["new_image_payload_bytes"] == 0
        and result.get("full_match_accuracy_established") is False,
        "Completed original provenance audit required before metadata parsing",
    )
    # Validate outer execution evidence in addition to the frozen audit's inner checks.
    pre = read(root / ".cache/rally250-pre-execution-grant-v1.json")
    receipts = root / ".cache/rally250-native-v1"
    owner, finish = read(receipts / "owner.json"), read(receipts / "finish.json")
    require(
        type(finish["returncode"]) is int and finish["returncode"] == 0,
        "Original outer execution failed",
    )
    require(
        finish["stdout_sha256"] == digest(receipts / "stdout.log")
        and finish["stderr_sha256"] == digest(receipts / "stderr.log"),
        "Original execution logs changed",
    )
    context = read(root / protocol["prior"]["output"] / "context.json")
    require(
        context["frozen_at"]
        <= finish["started_at"]
        < finish["ended_at"]
        <= context["deadline"],
        "Original immutable runtime changed",
    )
    for row in [pre["process"], owner, *finish["observed_lifetimes"]]:
        absent(row)
    return result


def audit_history(root, output, protocol):
    verify_inputs(root, protocol)
    command, started, seen = prior_command(root, protocol), time.time(), {}
    observation_errors = []
    with (
        (output / "prior-audit-stdout.log").open("xb") as stdout,
        (output / "prior-audit-stderr.log").open("xb") as stderr,
    ):
        process = subprocess.Popen(
            command,
            cwd=root / protocol["prior"]["checkout"],
            env=prior_environment(root, protocol),
            stdout=stdout,
            stderr=stderr,
        )
        while process.poll() is None:
            try:
                launcher = psutil.Process(process.pid)
                for child in [launcher, *launcher.children(recursive=True)]:
                    try:
                        row = {**identity(child), "ppid": child.ppid()}
                        seen[(row["pid"], row["creation_time"])] = row
                    except psutil.NoSuchProcess:
                        pass
                    except psutil.AccessDenied:
                        observation_errors.append(
                            {"pid": child.pid, "error": "AccessDenied"}
                        )
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                observation_errors.append({"pid": process.pid, "error": "AccessDenied"})
            time.sleep(0.1)
        code = process.wait()
    write(
        output / "prior-audit-process.json",
        {
            "command": command,
            "launched_pid": process.pid,
            "returncode": code,
            "started_at": started,
            "ended_at": time.time(),
            "observed_lifetimes": list(seen.values()),
            "observation_errors": observation_errors,
            "stdout_sha256": digest(output / "prior-audit-stdout.log"),
            "stderr_sha256": digest(output / "prior-audit-stderr.log"),
        },
    )
    require(code == 0, "Historical audit failed; preserve output and do not repeat")
    require(
        not observation_errors,
        "Historical observation incomplete; terminal receipt preserved",
    )
    require(
        any(r["pid"] == process.pid for r in seen.values()),
        "Original launcher was not observed",
    )
    for row in seen.values():
        absent(row)
    return validate_prior_result(
        root, protocol, (output / "prior-audit-stdout.log").read_bytes()
    )


def library():
    sys.path.insert(0, str(CHECKOUT / "backend"))
    from badminton import rally_review_plan

    require(
        Path(rally_review_plan.__file__).resolve() == CHECKOUT / CONSUMERS[0],
        "Wrong planner origin",
    )
    return rally_review_plan


def sealed_json(root, name, protocol):
    """Hash and parse the same opened bytes; do not trust a second pathname read."""
    raw = safe(root, name).read_bytes()
    require(
        hashlib.sha256(raw).hexdigest() == protocol["sealed_inputs"].get(name),
        "Sealed metadata bytes changed: " + name,
    )
    return strict_json(raw)


def build(root, output, protocol):
    # Caller has independently verified historical completion before entering here.
    planner = library()
    context = read(output / "context.json")
    summaries, plans = [], {}
    for source in sorted(protocol["sources"], key=lambda s: s["source_id"]):
        sid = source["source_id"]
        packet_name = protocol["native_root"] + "/" + sid + ".packet.json"
        gallery_name = protocol["gallery_root"] + "/" + sid + "/gallery.json"
        packet = sealed_json(root, packet_name, protocol)
        gallery = sealed_json(root, gallery_name, protocol)
        bindings = {
            "packet_sha256": protocol["sealed_inputs"][packet_name],
            "gallery_sha256": protocol["sealed_inputs"][gallery_name],
            "prior_audit_sha256": digest(output / "prior-audit-stdout.log"),
            "protocol_sha256": digest(CHECKOUT / PROTOCOL),
            "consumer_sha256": fingerprint(context["consumers"]),
        }
        require(
            bindings["packet_sha256"] == source["packet_sha256"],
            "Original packet identity changed",
        )
        summary, plan = planner.plan_source(
            packet,
            gallery,
            expected_source=source,
            bindings=bindings,
            max_bytes=protocol["packing"]["max_bytes"],
            max_images=protocol["packing"]["max_images"],
        )
        summaries.append(summary)
        plans[sid] = plan
    return planner.summarize_sources(summaries), plans


def prior_bytes(root, protocol):
    gate = read(root / protocol["prior"]["output"] / "metadata-gate.json")
    original = read(CHECKOUT / "data/manifests/rally_evidence_join_v1.json")
    return gate["prior_retained_bytes"] + common.budget(root, original)


def execute(root, output, stamp, protocol):
    context = current(output, stamp, protocol)
    require_output(root, output, protocol)
    require(
        {p.name for p in output.iterdir()} == {"context.json"},
        "Original attempt exists; preserve it and do not repeat",
    )
    require(
        all(not os.environ.get(k) for k in CREDENTIALS),
        "Credential-free execution required",
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
        "Real original shared Store required",
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
        audit_history(root, output, protocol)
        validate_grant(context["grant"], protocol, time.time(), platform.node())
        prior = prior_bytes(root, protocol)
        budget(root, protocol, prior)
        summary, plans = build(root, output, protocol)
        require(
            summary["native_frames"] == 1532 and summary["sampled_frames"] == 53,
            "Original full denominator changed",
        )
        write(output / "plan.json", plans)
        write(
            output / "aggregate.json",
            {
                "task": 262,
                "context_sha256": digest(output / "context.json"),
                "protocol_sha256": digest(CHECKOUT / PROTOCOL),
                "prior_audit_sha256": digest(output / "prior-audit-stdout.log"),
                "plan_sha256": digest(output / "plan.json"),
                "diagnostics": summary,
                "prior_retained_bytes": prior,
                "new_scientific_sessions": 0,
                "new_image_payload_bytes": 0,
                "preserved_result": protocol["preserved_result"],
                "scientific_acceptance_changed": False,
                "full_match_accuracy_established": False,
            },
        )
        verify_inputs(root, protocol)
        budget(root, protocol, prior)
        validate_grant(context["grant"], protocol, time.time(), platform.node())
        result = {
            "aggregate_sha256": digest(output / "aggregate.json"),
            "plan_sha256": digest(output / "plan.json"),
            "artifacts": {n: digest(output / n) for n in ARTIFACTS},
        }
        progress(1)
        return result

    try:
        result = run_local_job(
            Store(config.DATA), "rally_review_plan", "sealed-rally262", work
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


def audit(root, output, stamp, protocol):
    current(output, stamp, protocol, live=False)
    require_output(root, output, protocol)
    require(
        not (output / "failure.json").exists(), "Failed original attempt remains fenced"
    )
    admission, terminal = (
        read(output / "admission.json"),
        read(output / "terminal.json"),
    )
    attempt, context = read(output / "attempt.json"), read(output / "context.json")
    for row in (admission["process"], attempt["process"]):
        absent(row)
    job = common.store_job(root, admission)
    require(
        job.get("status") == terminal["status"] == "completed"
        and equal(job.get("summary"), terminal["summary"])
        and terminal["job_id"] == admission["job_id"]
        and admission["context_sha256"] == digest(output / "context.json")
        and terminal["admission_sha256"] == digest(output / "admission.json"),
        "Actual Store/admission/terminal mismatch",
    )
    summary = terminal["summary"]
    require(
        set(summary["artifacts"]) == set(ARTIFACTS)
        and {p.name for p in output.iterdir()} == set(ARTIFACTS) | {"terminal.json"},
        "Exact exclusive artifact inventory required",
    )
    require(
        all(digest(output / n) == h for n, h in summary["artifacts"].items()),
        "Completed artifact changed",
    )
    verify_inputs(root, protocol)
    receipt = read(output / "prior-audit-process.json")
    require(
        type(receipt["returncode"]) is int
        and receipt["returncode"] == 0
        and receipt["observation_errors"] == []
        and equal(receipt["command"], prior_command(root, protocol))
        and context["frozen_at"]
        <= attempt["started_at"]
        <= receipt["started_at"]
        < receipt["ended_at"]
        <= min(context["deadline"], context["grant"]["task"]["claim"]["expires_at"]),
        "Original historical process/runtime mismatch",
    )
    require(
        receipt["stdout_sha256"] == digest(output / "prior-audit-stdout.log")
        and receipt["stderr_sha256"] == digest(output / "prior-audit-stderr.log"),
        "Audit logs changed",
    )
    require(
        any(r["pid"] == receipt["launched_pid"] for r in receipt["observed_lifetimes"]),
        "Missing independently observed launcher",
    )
    for row in receipt["observed_lifetimes"]:
        absent(row)
    validate_prior_result(
        root, protocol, (output / "prior-audit-stdout.log").read_bytes()
    )
    # Fresh read-only replay precedes this audit's original metadata reads too.
    replay = subprocess.run(
        prior_command(root, protocol),
        cwd=root / protocol["prior"]["checkout"],
        env=prior_environment(root, protocol),
        capture_output=True,
        check=False,
    )
    require(
        replay.returncode == 0,
        "Read-only original audit failed; preserve original plan",
    )
    validate_prior_result(root, protocol, replay.stdout)
    require(
        replay.stdout == (output / "prior-audit-stdout.log").read_bytes(),
        "Original audit result changed",
    )
    actual = read(output / "aggregate.json")
    rebuilt, plans = build(root, output, protocol)
    require(
        equal(plans, read(output / "plan.json"))
        and equal(rebuilt, actual["diagnostics"]),
        "Planning schedule/cost/coverage differs from original metadata",
    )
    require(
        actual["context_sha256"] == digest(output / "context.json")
        and actual["protocol_sha256"] == digest(CHECKOUT / PROTOCOL)
        and actual["prior_audit_sha256"] == digest(output / "prior-audit-stdout.log")
        and actual["plan_sha256"]
        == summary["plan_sha256"]
        == digest(output / "plan.json")
        and summary["aggregate_sha256"] == digest(output / "aggregate.json")
        and equal(actual["preserved_result"], protocol["preserved_result"])
        and actual["new_scientific_sessions"] == actual["new_image_payload_bytes"] == 0
        and actual["scientific_acceptance_changed"]
        is actual["full_match_accuracy_established"]
        is False,
        "Bound metadata aggregate changed",
    )
    budget(root, protocol, prior_bytes(root, protocol))
    return {
        "task": 262,
        "aggregate_sha256": digest(output / "aggregate.json"),
        "plan_sha256": digest(output / "plan.json"),
        "original_inputs_unchanged": True,
        "all_recorded_metadata_lifetimes_absent": True,
        "new_scientific_sessions": 0,
        "new_image_payload_bytes": 0,
        "complete_references": 0,
        "full_match_accuracy_established": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run", "audit"))
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
        require(args.grant is not None, "Current committed grant required")
        result = freeze(root, output, read(args.grant), protocol)
    else:
        require(args.timestamp is not None, "Prospective owning-issue seal required")
        function = execute if args.phase == "run" else audit
        result = function(root, output, args.timestamp, protocol)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
