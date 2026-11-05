"""One audited API entry for the specific untouched #397 scientific commitment.

The scientific source, prospective, cohort claim, output and deadline stay intact.
This module never imports another badminton snapshot into its own process.
"""

import argparse
import hashlib
import json
import math
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

PROTOCOL = {
    "name": "aicup-pose-dispatch-recovery-v1",
    "task": 398,
    "spec_hash": "6a4c4140d9d9762227d9d203b7e379ecaf304658526f86b069c8d68012aceb67",
    "scientific_commit": "8bc2b0270e6350281421d7590855627cfdfc1178",
    "prospective_sha256": "5603570cf1a40bd8dfee776c9a21b3ac44ac6e0c68073810da917ebd964c6be6",
    "claim_sha256": "7831a0d3335dd9924e12e1daf9294c4fe0923d86d27088d4ae5c82689dde6357",
    "original_granted_at": 1793861134,
    "original_committed_at": 1793862568.8576179,
    "scientific_deadline": 1793905768.8576179,
    "grant": {
        "actor": "Ken0u",
        "host_id": "MSI",
        "session_id": "3283a9953d4445739251c6b8dfdb55bd",
        "epoch": 1,
        "granted_at": 1793864201,
    },
    "proofs": {
        "pose397-original-invocation-v1.json": "66b38f21e1ce55e29bcc1d7556acfeb6c21dc88ea33127eafb76b51df9a64499",
        "pose397-original-process-v1.json": "1b033277c273b5e03ba9528a3e73c18d4209cdf950db5fea80b8ee78620134fb",
        "pose397-original-run-v1-verification.json": "410703c726214ee6010fd4afc87d7cea36c6ba09ae7a985fc0481db451e65a42",
        "pose397-original-stderr-v1.log": "21de0ba796addb784217b12dc1f9a1f9948bd67e5eb92b9e6af823e0c0e89bb9",
        "pose397-predispatch-failure-proof-v1.json": "e60dc956a055731b03723b72b23f1555cfdd2692eb2b54acfbbcb54ac1c91873",
    },
    "limits": {
        "task_seconds": 57600,
        "forecast_seconds": 28274.657076463565,
        "extra_headroom_seconds": 7200,
        "grant_observation_seconds": 120,
        "terminal_slot_bytes": 65536,
        "log_slot_bytes": 1048576,
        "corrective_invocations": 1,
        "scientific_operations": 1,
        "real_fits": 1,
        "output_bytes": 4294967296,
    },
}

# This isolated child calls the unchanged API rather than the broken old parser.
# It imports no module from this implementation checkout.
CHILD = r"""
import json, sys
from pathlib import Path
backend, action, prospective, expected, output = sys.argv[1:]
backend = Path(backend).resolve()
sys.path.insert(0, str(backend))
from badminton import aicup_pose_scaling as scaling
assert Path(scaling.__file__).resolve().parents[1] == backend
for name, module in list(sys.modules.items()):
    if name == 'badminton' or name.startswith('badminton.'):
        assert Path(module.__file__).resolve().is_relative_to(backend)
if action == 'check':
    plan = scaling.prospective(Path(prospective), expected, True)
    scaling.learning.validate_workspace(plan)
    scaling.original_inputs(plan)
    scaling.input_sources(plan)
    result = dict(integrity_only=True, new_decodes=0, real_fits=0)
elif action == 'run':
    result = scaling.run(prospective_path=Path(prospective),
                         prospective_sha256=expected, output=Path(output))
elif action == 'verify':
    result = scaling.verify(prospective_path=Path(prospective),
                            prospective_sha256=expected, output=Path(output))
else:
    raise ValueError('Unknown frozen API action')
print(json.dumps(result, indent=2, allow_nan=False))
"""


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON field")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("Nonfinite JSON number")

    return json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=pairs,
        parse_constant=invalid,
    )


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def publish(path, value):
    with Path(path).open("xb") as stream:
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def git(directory, *args):
    return subprocess.check_output(["git", *args], cwd=directory, text=True).strip()


def source_seals():
    root = Path(__file__).resolve().parents[2]
    names = (
        "backend/badminton/aicup_pose_dispatch_recovery.py",
        "scripts/recover_aicup_pose_dispatch.py",
        "data/manifests/aicup_pose_dispatch_recovery_protocol_v1.json",
    )
    return {name: digest(root / name) for name in names}


def tested_source():
    root = Path(__file__).resolve().parents[2]
    commit, seals = git(root, "rev-parse", "HEAD"), source_seals()
    require(
        git(root, "branch", "--show-current")
        == "codex/issue-398-perform-the-first-actual-dispatch-of-the",
        "Not the granted recovery branch",
    )
    for name, expected in seals.items():
        original = subprocess.check_output(
            ["git", "show", commit + ":" + name], cwd=root
        )
        require(hashlib.sha256(original).hexdigest() == expected, "Uncommitted wrapper")
    return commit, seals


def paths(workspace):
    root = Path(workspace).resolve()
    cache = root / ".cache"
    original = cache / "pose397-freeze-v1/prospective.json"
    require(original.resolve().is_relative_to(cache), "Escaped original prospective")
    require(digest(original) == PROTOCOL["prospective_sha256"], "Changed prospective")
    plan = read(original)
    require(plan["workspace"] == str(root), "Different real workspace")
    output = Path(plan["output"])
    require(output == cache / "pose397-run-v1", "Different original output")
    require(output.resolve().is_relative_to(cache), "Escaped original output")
    require(
        plan["prospective_directory"] == str(original.parent),
        "Different original freeze directory",
    )
    require(
        plan["tested_commit"] == PROTOCOL["scientific_commit"]
        and plan["granted_at"] == PROTOCOL["original_granted_at"]
        and plan["committed_at"] == PROTOCOL["original_committed_at"]
        and plan["deadline"] == PROTOCOL["scientific_deadline"],
        "Changed original source or scientific clocks",
    )
    require(
        plan["protocol"]["limits"]["task_seconds"] == 57600
        and plan["protocol"]["limits"]["operation_seconds"] == 43200
        and plan["protocol"]["limits"]["output_bytes"]
        == PROTOCOL["limits"]["output_bytes"],
        "Changed original scientific bounds",
    )
    claim = cache / (
        plan["protocol"]["name"]
        + "-"
        + plan["protocol"]["sources"]["archive"]
        + "-start.json"
    )
    require(claim.resolve().is_relative_to(cache), "Escaped original claim")
    require(digest(claim) == PROTOCOL["claim_sha256"], "Changed cohort claim")
    require(
        read(claim)
        == {
            "prospective_sha256": digest(original),
            "output": str(output),
            "committed_at": plan["committed_at"],
            "deadline": plan["deadline"],
        },
        "Original claim contradicts prospective",
    )
    companion = original.parent / "dispatch-recovery-v1"
    require(companion.resolve().is_relative_to(original.parent), "Escaped companion")
    return root, original, plan, output, companion


def live_grant(path, science=True):
    state = read(path)
    task, receipt = state["task"], state["grant_receipt"]
    claim = task["claim"]
    expected = PROTOCOL["grant"] | {"spec_hash": PROTOCOL["spec_hash"]}
    require(
        task["status"] == "running"
        and task["epoch"] == expected["epoch"]
        and task["spec_hash"] == expected["spec_hash"]
        and all(claim.get(k) == v for k, v in expected.items())
        and receipt["status"] == "granted"
        and receipt["task_id"] == str(PROTOCOL["task"])
        and receipt["epoch"] == claim["epoch"]
        and all(receipt["claim"].get(k) == v for k, v in expected.items()),
        "Missing matching committed recovery grant",
    )
    now = time.time()
    require(
        finite(state["at"])
        and 0 <= now - state["at"] <= PROTOCOL["limits"]["grant_observation_seconds"]
        and finite(claim["expires_at"])
        and claim["expires_at"] > now,
        "Stale or expired recovery ownership",
    )
    require(
        claim["branch"] == "codex/issue-398-perform-the-first-actual-dispatch-of-the",
        "Different recovery branch",
    )
    if science:
        require(
            claim["granted_at"]
            <= now
            < claim["granted_at"] + PROTOCOL["limits"]["task_seconds"],
            "Expired recovery task window",
        )
        require(
            PROTOCOL["scientific_deadline"] - now
            >= PROTOCOL["limits"]["forecast_seconds"]
            + PROTOCOL["limits"]["extra_headroom_seconds"],
            "Insufficient original-deadline forecast headroom",
        )
    return expected


def absent_process(identity):
    import psutil

    require(
        type(identity["pid"]) is int
        and identity["pid"] > 0
        and finite(identity["created_at"]),
        "Invalid original process identity",
    )
    try:
        current = psutil.Process(identity["pid"])
        require(
            abs(current.create_time() - identity["created_at"]) >= 0.01,
            "Preserve live original process",
        )
    except psutil.NoSuchProcess:
        pass


def store_jobs(root):
    database = root / "data/processed/catalog.sqlite3"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        return [
            json.loads(row[0])
            for row in connection.execute("SELECT document FROM jobs")
        ]


def predecessor(root, original, plan, output, untouched):
    cache = root / ".cache"
    for name, expected in PROTOCOL["proofs"].items():
        path = cache / name
        require(path.resolve().is_relative_to(cache), "Escaped predecessor evidence")
        require(digest(path) == expected, "Changed predecessor evidence: " + name)
    invocation = read(cache / "pose397-original-invocation-v1.json")
    identity = read(cache / "pose397-original-process-v1.json")
    terminal = read(cache / "pose397-original-run-v1-verification.json")
    proof = read(cache / "pose397-predispatch-failure-proof-v1.json")["public"]
    absent_process(identity)
    require(
        identity["command"] == invocation["command"]
        and identity["cwd"] == str(root / ".cache/worktrees/pose397-e1")
        and terminal["exit_code"] == 1
        and terminal["original_process_absent"] is True
        and terminal["original_run_consumed"] is True
        and terminal["consumer_commit"] == plan["tested_commit"]
        and terminal["prospective_sha256"] == digest(original)
        and terminal["stderr_sha256"]
        == digest(cache / "pose397-original-stderr-v1.log")
        and terminal["stdout_sha256"]
        == digest(cache / "pose397-original-stdout-v1.log")
        and (cache / "pose397-original-stderr-v1.log")
        .read_text(encoding="utf-8")
        .endswith(
            "TypeError: run() got an unexpected keyword argument 'prospective'\n"
        ),
        "Not the preserved pre-entry CLI failure",
    )
    require(
        proof["scientific_operations_started"]
        == proof["new_decodes"]
        == proof["new_model_observations"]
        == proof["real_fits"]
        == 0
        and proof["run_output_absent"] is True
        and proof["original_process_absent"] is True
        and proof["prospective_sha256"] == digest(original)
        and proof["original_deadline"] == plan["deadline"],
        "Predecessor may have entered science",
    )
    jobs = store_jobs(root)
    require(
        not any(
            job.get("owner_pid") == identity["pid"]
            and job.get("owner_started") == identity["created_at"]
            for job in jobs
        ),
        "Preserve predecessor Store job",
    )
    if untouched:
        require(not output.exists(), "Preserve original output/partial dispatch")
        require(
            not any(job.get("status") in ("queued", "running") for job in jobs),
            "Preserve active shared Store work",
        )
        import psutil

        for process in psutil.process_iter(["pid", "name"]):
            if (
                process.pid == os.getpid()
                or "python" not in (process.info["name"] or "").lower()
            ):
                continue
            try:
                command = process.cmdline()
                require(
                    not (
                        str(original) in command
                        and any(action in command for action in ("run", "dispatch"))
                    ),
                    "Preserve existing scientific dispatch",
                )
            except psutil.NoSuchProcess:
                pass
    return {name: digest(cache / name) for name in PROTOCOL["proofs"]}


def scientific_snapshot(snapshot, root, plan):
    snapshot = Path(snapshot).resolve()
    require(
        snapshot.is_relative_to(root / ".cache/worktrees"),
        "Not a private scientific snapshot",
    )
    require(
        git(snapshot, "rev-parse", "HEAD") == plan["tested_commit"],
        "Different scientific source revision",
    )
    require(not git(snapshot, "status", "--porcelain"), "Dirty scientific snapshot")
    require(
        not list((snapshot / "backend").rglob("*.pyc")),
        "Preserve source-only frozen imports",
    )
    require(
        not git(snapshot, "ls-files", "--others", "--exclude-standard", "backend"),
        "Untracked frozen scientific backend",
    )
    for name, expected in plan["code"].items():
        path = (snapshot / name).resolve()
        require(path.is_relative_to(snapshot), "Escaped scientific source")
        require(digest(path) == expected, "Changed frozen scientific code")
    return snapshot


def child_environment(root):
    # The numerical child needs no network credentials; leave other apps alone.
    result = {
        key: value
        for key, value in os.environ.items()
        if not any(
            token in key.upper()
            for token in (
                "TOKEN",
                "SECRET",
                "PASSWORD",
                "API_KEY",
                "CREDENTIAL",
                "AUTH",
                "COOKIE",
            )
        )
        and key.upper() not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")
    }
    result.update(
        BADMINTON_ROOT=str(root),
        BADMINTON_DATA_DIR=str(root / "data/processed"),
        BADMINTON_WEIGHTS_DIR=str(root / "models/weights"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    return result


def child_command(snapshot, plan, original, action):
    require(action in ("check", "run", "verify"), "Unknown scientific API action")
    executable = plan["runtime"]["executable"]
    require(
        Path(sys.executable).resolve() == Path(executable).resolve(),
        "Different original Python runtime",
    )
    return [
        executable,
        "-I",
        "-B",
        "-c",
        CHILD,
        str(snapshot / "backend"),
        action,
        str(original),
        PROTOCOL["prospective_sha256"],
        plan["output"],
    ]


def output_budget(original, output, reserve=0):
    require(type(reserve) is int and reserve >= 0, "Invalid metadata reservation")
    files = [
        p
        for directory in (original.parent, output)
        for p in directory.rglob("*")
        if p.is_file()
    ]
    total = sum(path.stat().st_size for path in files)
    plan = read(original)
    claim = original.parent.parent / (
        plan["protocol"]["name"]
        + "-"
        + plan["protocol"]["sources"]["archive"]
        + "-start.json"
    )
    total += claim.stat().st_size
    require(
        total + reserve <= PROTOCOL["limits"]["output_bytes"],
        "Cumulative scientific output budget",
    )
    return total


def reserve_slot(path, size, initial=b""):
    require(len(initial) <= size, "Initial receipt exceeds reservation")
    with Path(path).open("xb") as stream:
        stream.write(initial.ljust(size, b" "))
        stream.flush()
        os.fsync(stream.fileno())


def store_terminal(path, record):
    data = encoded(record)
    size = PROTOCOL["limits"]["terminal_slot_bytes"]
    require(len(data) <= size, "Terminal receipt exceeds reserved metadata slot")
    with Path(path).open("r+b") as stream:
        require(
            os.fstat(stream.fileno()).st_size == size, "Changed terminal reservation"
        )
        stream.write(data.ljust(size, b" "))
        stream.flush()
        os.fsync(stream.fileno())


def capture_log(source, path, result):
    """Drain without signalling the child; disk use never exceeds its reservation."""
    size, total = PROTOCOL["limits"]["log_slot_bytes"], 0
    try:
        with Path(path).open("r+b") as target:
            require(
                os.fstat(target.fileno()).st_size == size, "Changed log reservation"
            )
            while block := source.read(65536):
                retained = min(len(block), max(0, size - total))
                target.write(block[:retained])
                total += len(block)
            target.flush()
            os.fsync(target.fileno())
        result.update(
            bytes=total,
            retained_bytes=min(total, size),
            overflow=total > size,
            complete=True,
        )
    except BaseException as error:
        # Never copy arbitrary exception text from a child environment into receipts.
        result.update(complete=False, error_type=type(error).__name__)
        # Continue draining if a write failed, so a full pipe cannot strand science.
        try:
            while source.read(65536):
                pass
        except OSError:
            pass
    finally:
        source.close()


def prepare(workspace, snapshot, grant_state, protocol):
    require(read(protocol) == PROTOCOL, "Changed recovery protocol")
    root, original, plan, output, companion = paths(workspace)
    grant = live_grant(grant_state)
    require(not companion.exists(), "Preserve existing recovery intent/attempt")
    proofs = predecessor(root, original, plan, output, True)
    snapshot = scientific_snapshot(snapshot, root, plan)
    commit, code = tested_source()
    result = subprocess.run(
        child_command(snapshot, plan, original, "check"),
        cwd=snapshot,
        env=child_environment(root),
        capture_output=True,
        check=True,
    )
    require(
        json.loads(result.stdout)
        == {"integrity_only": True, "new_decodes": 0, "real_fits": 0},
        "Original integrity check did not pass",
    )
    # Revalidate after the potentially slow opaque producer/input seal checks.
    require(
        proofs == predecessor(root, original, plan, output, True),
        "Changed pre-dispatch proof",
    )
    live_grant(grant_state)
    require((commit, code) == tested_source(), "Wrapper changed during preparation")
    output_budget(
        original,
        output,
        PROTOCOL["limits"]["terminal_slot_bytes"]
        + 2 * PROTOCOL["limits"]["log_slot_bytes"]
        + 1024 * 1024,
    )
    companion.mkdir(exist_ok=False)
    for name in PROTOCOL["proofs"]:
        with (companion / name).open("xb") as stream:
            stream.write((root / ".cache" / name).read_bytes())
    (companion / "integrity.stdout").write_bytes(result.stdout)
    (companion / "integrity.stderr").write_bytes(result.stderr)
    reserve_slot(
        companion / "terminal.json",
        PROTOCOL["limits"]["terminal_slot_bytes"],
        encoded({"terminal": False, "reserved_slot": True}),
    )
    for name in ("scientific.stdout", "scientific.stderr"):
        reserve_slot(companion / name, PROTOCOL["limits"]["log_slot_bytes"])
    intent = {
        "protocol": PROTOCOL,
        "wrapper_commit": commit,
        "wrapper_code": code,
        "scientific_snapshot": str(snapshot),
        "scientific_prospective": str(original),
        "prospective_sha256": digest(original),
        "scientific_commit": plan["tested_commit"],
        "scientific_deadline": plan["deadline"],
        "original_output": str(output),
        "grant": grant,
        "proofs": proofs,
        "prepared_at": time.time(),
        "integrity_stdout_sha256": digest(companion / "integrity.stdout"),
        "integrity_stderr_sha256": digest(companion / "integrity.stderr"),
        "new_decodes": 0,
        "real_fits": 0,
    }
    publish(companion / "intent.json", intent)
    output_budget(original, output)
    return {
        "intent_sha256": digest(companion / "intent.json"),
        "wrapper_commit": commit,
        "original_scientific_deadline": plan["deadline"],
        "new_decodes": 0,
        "real_fits": 0,
    }


def intent_state(workspace, expected, grant_state, science):
    root, original, plan, output, companion = paths(workspace)
    grant = live_grant(grant_state, science)
    require(digest(companion / "intent.json") == expected, "Changed recovery intent")
    intent = read(companion / "intent.json")
    require(
        intent["protocol"] == PROTOCOL
        and intent["grant"] == grant
        and intent["prospective_sha256"] == digest(original)
        and intent["scientific_prospective"] == str(original)
        and intent["original_output"] == str(output)
        and intent["scientific_commit"] == plan["tested_commit"]
        and intent["scientific_deadline"] == plan["deadline"],
        "Recovery intent contradicts original commitment",
    )
    require(
        (intent["wrapper_commit"], intent["wrapper_code"]) == tested_source(),
        "Changed tested recovery wrapper",
    )
    snapshot = scientific_snapshot(intent["scientific_snapshot"], root, plan)
    proofs = predecessor(root, original, plan, output, science)
    require(intent["proofs"] == proofs, "Changed original failure proof")
    for name, expected_proof in proofs.items():
        require(digest(companion / name) == expected_proof, "Changed companion proof")
    for name in ("stdout", "stderr"):
        require(
            digest(companion / ("integrity." + name))
            == intent["integrity_" + name + "_sha256"],
            "Changed original integrity receipt",
        )
    output_budget(original, output, 32768)
    return root, original, plan, output, companion, intent, snapshot


def dispatch(workspace, intent_sha256, grant_state, publication):
    root, original, plan, output, companion, intent, snapshot = intent_state(
        workspace, intent_sha256, grant_state, True
    )
    published = read(publication)
    require(
        published["task"] == PROTOCOL["task"]
        and published["intent_sha256"] == intent_sha256
        and published["wrapper_commit"] == intent["wrapper_commit"]
        and published["prospective_sha256"] == digest(original)
        and finite(published["at"])
        and intent["prepared_at"] <= published["at"] <= time.time()
        and published["comment_url"].startswith(
            "https://github.com/Ken0u/badminton-match-analyzer/issues/398#issuecomment-"
        ),
        "Missing matching prospective recovery publication",
    )
    require(
        read(companion / "terminal.json")["terminal"] is False,
        "Preserve terminal recovery",
    )
    live_grant(grant_state)
    # Exclusive intent/start and original output reservation jointly fence even
    # failures before the numerical function begins. Never retry this command.
    publish(
        companion / "dispatch-start.json",
        {
            "at": time.time(),
            "intent_sha256": intent_sha256,
            "publication": published,
            "original_cli_invocations": 1,
            "corrective_invocations": 1,
        },
    )
    import psutil

    started = time.time()
    identity, process = None, None
    logs, readers = {}, []
    code, error = None, None
    try:
        command = child_command(snapshot, plan, original, "run")
        process = subprocess.Popen(
            command,
            cwd=snapshot,
            env=child_environment(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # Persist the handle before fallible identity observation. A missing full
        # identity never means a launched child is absent, nor permits a retry.
        publish(
            companion / "launched.json",
            {"pid": process.pid, "at": time.time(), "intent_sha256": intent_sha256},
        )
        for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            logs[name] = {"complete": False}
            reader = threading.Thread(
                target=capture_log,
                args=(pipe, companion / ("scientific." + name), logs[name]),
                daemon=True,
            )
            reader.start()
            readers.append(reader)
        observed = psutil.Process(process.pid)
        identity = {
            "pid": observed.pid,
            "created_at": observed.create_time(),
            "cwd": observed.cwd(),
            "command": observed.cmdline(),
        }
        require(
            identity["command"] == command and identity["cwd"] == str(snapshot),
            "Scientific process identity differs from launched command/root",
        )
        publish(companion / "process.json", identity)
        code = process.wait()
        for reader in readers:
            reader.join()
    except BaseException as failure:
        error = {"type": type(failure).__name__}
        raise
    finally:
        # A lost observation/parent interruption is never proof of child exit.
        if process is not None:
            code = process.poll()
        exited = process is not None and code is not None
        logs_ok = len(logs) == 2 and all(
            value.get("complete") and not value.get("overflow")
            for value in logs.values()
        )
        terminal = {
            "terminal": exited,
            "process_state": "exited" if exited else "unknown",
            "started_at": started,
            "observed_at": time.time(),
            "exit_code": code,
            "process": identity,
            "launched_pid": process.pid if process is not None else None,
            "original_process_absent": True if exited else None,
            "error": error,
            "logs": logs,
            "intent_sha256": intent_sha256,
            "original_invocation_consumed": True,
            "corrective_invocation_consumed": True,
            "scientific_success": code == 0
            and exited
            and identity is not None
            and error is None
            and logs_ok,
        }
        store_terminal(companion / "terminal.json", terminal)
    output_budget(original, output)
    require(
        code == 0, "Frozen scientific operation failed; preserve all partial evidence"
    )
    require(
        terminal["scientific_success"],
        "Incomplete process/log observation; preserve dispatch",
    )
    require((output / "completion.json").exists(), "No durable scientific completion")
    return terminal


def verify(workspace, intent_sha256, grant_state):
    root, original, plan, output, companion, _, snapshot = intent_state(
        workspace, intent_sha256, grant_state, False
    )
    terminal = read(companion / "terminal.json")
    require(
        terminal["scientific_success"] is True and terminal["exit_code"] == 0,
        "No successful terminal scientific dispatch",
    )
    absent_process(terminal["process"])
    result = subprocess.run(
        child_command(snapshot, plan, original, "verify"),
        cwd=snapshot,
        env=child_environment(root),
        capture_output=True,
        check=True,
    )
    output_budget(original, output, len(result.stdout) + len(result.stderr) + 65536)
    publish(
        companion / "readonly-verification.json",
        {
            "at": time.time(),
            "intent_sha256": intent_sha256,
            "result": json.loads(result.stdout),
            "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
            "new_decodes": 0,
            "real_fits": 0,
        },
    )
    output_budget(original, output)
    return json.loads(result.stdout)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("prepare")
    for name in ("workspace", "snapshot", "grant-state", "protocol"):
        command.add_argument("--" + name, type=Path, required=True)
    for action in ("dispatch", "verify"):
        command = commands.add_parser(action)
        command.add_argument("--workspace", type=Path, required=True)
        command.add_argument("--grant-state", type=Path, required=True)
        command.add_argument("--intent-sha256", required=True)
        if action == "dispatch":
            command.add_argument("--publication", type=Path, required=True)
    values = vars(parser.parse_args(argv))
    action = values.pop("command")
    print(
        json.dumps(
            {"prepare": prepare, "dispatch": dispatch, "verify": verify}[action](
                **values
            ),
            indent=2,
        )
    )
