"""Freeze and run bounded private, independent source-scene assessment.

Original images go only to the existing authenticated Codex CLI. The runner
never installs models, reads historical semantic labels or edits app truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import psutil

CHECKOUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CHECKOUT / "backend"))
sys.path.insert(0, str(CHECKOUT / "scripts"))
import prepare_shuttle_scene_review as preparation  # noqa: E402
from badminton import shuttle_scene_preparation as shared  # noqa: E402
from badminton import shuttle_scene_review as review  # noqa: E402

PROTOCOL = "data/manifests/shuttle_scene_review_protocol_v2.json"
SPEC_HASH = "4242e1e1af6137a8a237a432f2f208ba1dafe9ac3431586b289e1f971c24db97"
LANES = ("independent_a", "independent_b")
CREDENTIALS = (*preparation.CREDENTIALS, "CODEX_THREAD_ID", "CODEX_SESSION_ID")
ARTIFACTS = {
    "scene-gallery": "gallery.json",
    "scene-plan": "plan.json",
    "scene-aggregate": "aggregate.json",
    "scene-context": "context.json",
    "scene-audit": "audit/verification.json",
}
LIMITS = {
    "max_runtime_hours": 8,
    "max_output_bytes": 2147483648,
    "max_image_payload_bytes": 976856850,
    "max_assessor_sessions": 225,
    "max_original_sessions": 150,
    "max_adjudication_sessions": 75,
    "session_max_image_bytes": 6291456,
    "session_max_images": 20,
    "max_repair_rounds": 2,
    "paid_services": False,
}
LOCK = threading.RLock()
BUDGET_ROOT = None
STOP = threading.Event()
COLLECT_STOP_GRACE = 3.0
COLLECT_DRAIN_GRACE = 0.5
COLLECT_POLL = 0.05
require = shared.require
read = preparation.read


def write(path, value):
    path = Path(path)
    shared.safe_path(path.parent, path.name, must_exist=False)
    raw = shared.encode(value)
    with LOCK:
        if BUDGET_ROOT is not None:
            require(
                task_bytes(BUDGET_ROOT) + len(raw) <= LIMITS["max_output_bytes"],
                "Retained output budget exceeded",
            )
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())


def identity(process=None):
    process = process or psutil.Process()
    return {
        "pid": process.pid,
        "created": process.create_time(),
        "cwd": process.cwd(),
        "command": process.cmdline(),
    }


def require_absent(original):
    preparation.require_absent(original)


def task_bytes(root):
    """Charge every task attempt/check/worktree, including failures."""
    cache = root / ".cache"
    parents = [p for p in cache.iterdir() if p.name.startswith("scene349")]
    parents.extend(
        p for p in (cache / "worktrees").iterdir() if p.name.startswith("scene349")
    )
    total = 0
    for parent in parents:
        require(
            not parent.is_symlink()
            and not getattr(parent.lstat(), "st_file_attributes", 0) & 1024,
            "Linked retained root is unsupported",
        )
        pending = [parent]
        while pending:
            path = pending.pop()
            info = path.lstat()
            if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 1024:
                # Pytest leaves `current` links in retained evidence. Charge
                # their own metadata without following or deleting targets.
                # Actual input/output writers still refuse linked paths.
                total += info.st_size
            elif path.is_dir():
                pending.extend(path.iterdir())
            else:
                total += info.st_size
    return total


def validate_protocol(protocol):
    require(
        protocol.get("schema_version") == 1
        and protocol.get("task") == 349
        and protocol.get("spec_hash") == SPEC_HASH,
        "Wrong frozen task protocol",
    )
    require(protocol.get("limits") == LIMITS, "Authorized limits changed")
    require(protocol.get("eligibility") == shared.ELIGIBILITY, "Eligibility changed")
    require(
        protocol.get("denominators")
        == {"views": 50, "cases": 60, "frame_occurrences": 13499, "sheets": 870},
        "Original denominators changed",
    )
    require(set(protocol["artifacts"]) == set(ARTIFACTS), "Artifact membership changed")
    require(
        protocol.get("destination") == "existing ChatGPT-authenticated Codex CLI",
        "Unapproved image destination",
    )


def ownership(args, grant, *, now=None):
    now = time.time() if now is None else now
    live = read(args.ownership)
    require(
        grant.get("task_number") == 349 and live.get("task_number") == 349,
        "Fresh task 349 grant and observation required",
    )
    require(
        type(live.get("at")) in (int, float)
        and 0 <= now - live["at"] < 180
        and live.get("paused") is False
        and live["task"]["status"] == "running",
        "Fresh running ownership observation required",
    )
    expected, current = grant["task"]["claim"], live["task"]["claim"]
    for key in (
        "actor",
        "host_id",
        "session_id",
        "epoch",
        "spec_hash",
        "branch",
        "baseline_sha",
        "granted_at",
    ):
        require(current[key] == expected[key], "Original ownership changed")
    require(
        current["host_id"] == platform.node()
        and current["spec_hash"] == SPEC_HASH
        and live["task"]["epoch"] == current["epoch"]
        and current["session_id"] == grant["session_id"],
        "Original host/session/specification required",
    )
    deadline = expected["granted_at"] + 8 * 3600
    require(grant["deadline"] == deadline, "Original deadline changed")
    require(now < min(deadline, current["expires_at"]), "Ownership/deadline expired")
    require(
        live["task"].get("human_approval", {}).get("spec_hash") == SPEC_HASH,
        "Committed payload authorization required",
    )
    return deadline


def consumers():
    files = [
        p.relative_to(CHECKOUT).as_posix() for p in (CHECKOUT / "backend").rglob("*.py")
    ]
    files += [
        "scripts/review_shuttle_scenes.py",
        "scripts/prepare_shuttle_scene_review.py",
        "tests/test_shuttle_scene_review.py",
        PROTOCOL,
    ]
    cli = shutil.which("codex")
    require(bool(cli), "Existing authenticated CLI required")
    config_root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    config_paths = {config_root / "config.toml"}
    for parent in (CHECKOUT, *CHECKOUT.parents):
        config_paths.add(parent / ".codex/config.toml")
    return {
        "files": {p: shared.file_hash(CHECKOUT / p) for p in sorted(files)},
        "python": platform.python_version(),
        "psutil": psutil.__version__,
        "cli": {"path": cli, "sha256": shared.file_hash(cli)},
        "configuration": {
            str(p): shared.file_hash(p) if p.is_file() else None
            for p in sorted(config_paths)
        },
    }


def verify_cli_configuration(context, sandbox):
    expected = context["consumers"]["configuration"]
    for name, digest in expected.items():
        path = Path(name)
        require(
            (shared.file_hash(path) if path.is_file() else None) == digest,
            "CLI configuration changed before dispatch",
        )
    for parent in (sandbox, *sandbox.parents):
        path = parent / ".codex/config.toml"
        if path.is_file():
            require(
                str(path) in expected and shared.file_hash(path) == expected[str(path)],
                "Unfrozen sandbox-ancestor configuration",
            )


def preserved_truth(root, protocol):
    """Hash original documents opaquely; never parse their semantic content."""
    result = {}
    data = root / "data/processed"
    with sqlite3.connect(
        (data / "catalog.sqlite3").as_uri() + "?mode=ro", uri=True
    ) as db:
        for source in protocol["sources"]:
            sid = source["id"]
            for table, field in (("videos", "id"), ("annotations", "video_id")):
                rows = db.execute(
                    f"SELECT document FROM {table} WHERE {field}=? ORDER BY rowid",
                    (sid,),
                ).fetchall()
                result[f"{sid}/{table}"] = [
                    hashlib.sha256(row[0].encode()).hexdigest() for row in rows
                ]
            for directory in ("runs", "predictions"):
                for path in sorted((data / sid / directory).rglob("*")):
                    if path.is_file():
                        result[path.relative_to(data).as_posix()] = shared.file_hash(
                            path
                        )
    return result


def inputs(args, protocol, *, images=False):
    for key, name in ARTIFACTS.items():
        require(
            shared.file_hash(shared.safe_path(args.gallery, name))
            == protocol["artifacts"][key],
            "Original gallery metadata changed",
        )
    gallery, plan = (
        read(args.gallery / "gallery.json"),
        read(args.gallery / "plan.json"),
    )
    schedule = review.prepare_schedule(gallery, plan, protocol)
    for source in protocol["sources"]:
        require(
            shared.file_hash(shared.safe_path(args.root, source["media_path"]))
            == source["sha256"],
            "Original media changed",
        )
    terminal = read(args.gallery / "audit/terminal.json")
    require_absent(terminal["process"])
    preparation.check_store_terminal(args.root, terminal)
    require(
        terminal["summary"]["status"] == "audited"
        and terminal["summary"]["gallery_sha256"]
        == protocol["artifacts"]["scene-gallery"],
        "Successful original audit required",
    )
    if images:
        shared.audit_images(gallery, args.gallery)
    return schedule


def freeze(args):
    protocol, grant = read(args.protocol), read(args.grant)
    validate_protocol(protocol)
    deadline = ownership(args, grant)
    require(
        grant["task"]["spec"]["artifacts"] == protocol["artifacts"],
        "Grant artifacts changed",
    )
    require(
        not subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=CHECKOUT
        ).strip(),
        "Commit and test consumers before freezing",
    )
    require(not args.output.exists(), "Exclusive new output required")
    schedule = inputs(args, protocol, images=True)
    require(len(schedule) == 75, "Original session denominator changed")
    require(
        task_bytes(args.root) < LIMITS["max_output_bytes"] - 768 * 1024**2,
        "Insufficient output allowance",
    )
    context = {
        "schema_version": 1,
        "task": 349,
        "grant": grant,
        "deadline": deadline,
        "root": str(args.root),
        "gallery": str(args.gallery),
        "frozen_at": time.time(),
        "protocol_sha256": shared.file_hash(args.protocol),
        "consumers": consumers(),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=CHECKOUT, text=True
        ).strip(),
        "schedule_sha256": shared.digest(shared.encode(schedule)),
        "preserved_truth": preserved_truth(args.root, protocol),
        "prompt_schema_sha256": {
            lane: shared.digest(
                shared.encode(
                    {
                        "prompt": review.assessment_prompt(
                            schedule[0], "prospective-session", lane
                        ),
                        "schema": review.assessment_schema(
                            schedule[0], "prospective-session", lane
                        ),
                    }
                )
            )
            for lane in (*LANES, "adjudication")
        },
    }
    args.output.mkdir(parents=True, exist_ok=False)
    write(args.output / "context.json", context)
    return {
        "status": "frozen",
        "context_sha256": shared.file_hash(args.output / "context.json"),
        "images_dispatched": 0,
    }


def current(args, *, image_audit=False):
    context = read(args.output / "context.json")
    require(
        shared.file_hash(args.output / "context.json") == args.context_sha256,
        "Frozen context changed",
    )
    protocol = read(args.protocol)
    validate_protocol(protocol)
    require(
        shared.file_hash(args.protocol) == context["protocol_sha256"],
        "Protocol changed",
    )
    require(read(args.grant) == context["grant"], "Frozen grant changed")
    require(
        str(args.root) == context["root"] and str(args.gallery) == context["gallery"],
        "Original namespace changed",
    )
    ownership(args, context["grant"])
    require(consumers() == context["consumers"], "Frozen consumer/runtime changed")
    schedule = inputs(args, protocol, images=image_audit)
    require(
        shared.digest(shared.encode(schedule)) == context["schedule_sha256"],
        "Blind schedule changed",
    )
    require(
        preserved_truth(args.root, protocol) == context["preserved_truth"],
        "Original app truth changed",
    )
    require(
        task_bytes(args.root) <= LIMITS["max_output_bytes"],
        "Retained output budget exceeded",
    )
    return context, protocol, schedule


def published(args, context):
    stamp = read(args.timestamp)
    created = datetime.fromisoformat(
        stamp["created_at"].replace("Z", "+00:00")
    ).timestamp()
    require(
        stamp["user"]["login"] == context["grant"]["task"]["claim"]["actor"]
        and stamp["html_url"].startswith(
            "https://github.com/Ken0u/badminton-match-analyzer/issues/349#issuecomment-"
        )
        and context["frozen_at"] <= created < context["deadline"]
        and args.context_sha256 in stamp["body"]
        and context["source_commit"] in stamp["body"],
        "Public prospective consumer commitment required",
    )


def reserve(args, batch, lane, session):
    """Durably charge every attempted launch before creating a CLI process."""
    with LOCK:
        require(lane in (*LANES, "adjudication"), "Unknown assessment lane")
        receipts = [
            read(p) for p in (args.output / "sessions").glob("*/*/reservation.json")
        ]
        total = sum(r["image_bytes"] for r in receipts)
        require(
            not any(r["session_id"] == session for r in receipts),
            "Reused assessor session",
        )
        same = [r for r in receipts if r["lane"] == lane]
        size = sum(s["bytes"] for s in batch["images"])
        require(
            0 < len(batch["images"]) <= 20 and size <= 6 * 1024**2,
            "Session payload cap exceeded",
        )
        require(len(receipts) < 225 and len(same) < 75, "Session allowance exhausted")
        require(total + size <= 976856850, "Cumulative image allowance exhausted")
        require(
            sum(r["image_bytes"] for r in same) + size <= 325618950,
            "Lane image allowance exhausted",
        )
        require(
            not any(r["batch_index"] == batch["index"] for r in same),
            "Scientific replacement forbidden",
        )
        require(
            task_bytes(args.root) + 4 * 1024**2 <= LIMITS["max_output_bytes"],
            "Insufficient retained output allowance",
        )
        folder = args.output / "sessions" / lane / f"{batch['index']:03d}"
        folder.mkdir(parents=True, exist_ok=False)
        write(
            folder / "reservation.json",
            {
                "lane": lane,
                "batch_index": batch["index"],
                "session_id": session,
                "image_bytes": size,
                "images": [
                    {k: s[k] for k in ("path", "sha256", "bytes")}
                    for s in batch["images"]
                ],
                "reserved_at": time.time(),
                "replacement_allowed": False,
            },
        )
        return folder


def drain(stream, path, result, limit):
    digest, count = hashlib.sha256(), 0
    with path.open("xb") as handle:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
            if count < limit:
                handle.write(block[: limit - count])
            count += len(block)
            result["overflow"] = count > limit
    result.update(bytes=count, sha256=digest.hexdigest(), truncated=count > limit)


def stop_owned(original):
    """Signal only the same directly observed lifetime, directory and command."""
    try:
        process = psutil.Process(original["pid"])
        if process.create_time() != original["created"]:
            return "original_absent_pid_reused"
        require(
            identity(process) == original, "Refusing signal after identity mismatch"
        )
        process.terminate()
        return "termination_requested"
    except psutil.NoSuchProcess:
        return "original_absent"


def pipe_block(stream):
    """Read only available bytes, with one reader per pipe and no reader threads."""
    descriptor = stream.fileno()
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        peek = kernel.PeekNamedPipe
        peek.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPVOID,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        peek.restype = wintypes.BOOL
        available = wintypes.DWORD()
        if not peek(
            msvcrt.get_osfhandle(descriptor),
            None,
            0,
            None,
            ctypes.byref(available),
            None,
        ):
            error = ctypes.get_last_error()
            if error in (109, 232):  # Broken/disconnected anonymous pipe: EOF.
                return b""
            raise ctypes.WinError(error)
        if not available.value:
            return None
        return os.read(descriptor, min(available.value, 65536))
    os.set_blocking(descriptor, False)
    try:
        return os.read(descriptor, 65536)
    except BlockingIOError:
        return None


def collect(child, message, folder, deadline):
    """Bound collection even after parent exit; never infer exit from a timeout.

    The immutable prompt file supplies stdin at process creation. Output pipes
    have no concurrent readers; available-byte reads cannot wait for pipe EOF.
    Unknown descendants or changed identities leave a failed, fenced receipt.
    """
    start = identity(psutil.Process(child.pid))
    output, error, signals, errors = {}, {}, [], []
    observed = {(start["pid"], start["created"]): start}
    streams = [
        (child.stdout, folder / "events.jsonl", output, 2 * 1024**2),
        (child.stderr, folder / "stderr.log", error, 256 * 1024),
    ]
    hashes = [hashlib.sha256(), hashlib.sha256()]
    counts, eof = [0, 0], [False, False]
    stdin_error = "pipe_input_refused" if child.stdin is not None else None
    stopping = False
    stop_until = None
    parent_ended = None
    next_observation = 0.0
    run_until = time.monotonic() + max(0.0, deadline - 120 - time.time())

    def signal_observed():
        for row in reversed(list(observed.values())):
            try:
                result = stop_owned(row)
            except (psutil.Error, ValueError) as exc:
                result = "unverified_" + type(exc).__name__
                errors.append(result)
            signals.append({"process": row, "result": result})

    try:
        write(folder / "start.json", start)
        with ExitStack() as stack:
            logs = [stack.enter_context(path.open("xb")) for _, path, _, _ in streams]
            while True:
                now = time.monotonic()
                code = child.poll()
                if code is not None and parent_ended is None:
                    parent_ended = now
                try:
                    if code is None and now >= next_observation:
                        next_observation = now + COLLECT_POLL
                        parent = psutil.Process(child.pid)
                        current_identity = identity(parent)
                        # POSIX may expose empty fields while exiting between
                        # poll and identity reads. Reap that exact Popen handle
                        # before comparing; live mismatches still fail closed.
                        if child.poll() is None:
                            require(
                                current_identity == start,
                                "CLI process identity changed",
                            )
                            for process in parent.children(recursive=True):
                                try:
                                    row = identity(process)
                                    observed.setdefault(
                                        (row["pid"], row["created"]), row
                                    )
                                except psutil.NoSuchProcess:
                                    pass
                except psutil.NoSuchProcess:
                    pass
                except psutil.Error:
                    if child.poll() is None:
                        raise
                progressed = False
                for index, (stream, _, result, limit) in enumerate(streams):
                    if eof[index]:
                        continue
                    block = pipe_block(stream)
                    if block is None:
                        continue
                    if block == b"":
                        eof[index] = True
                        continue
                    progressed = True
                    hashes[index].update(block)
                    if counts[index] < limit:
                        logs[index].write(block[: limit - counts[index]])
                    counts[index] += len(block)
                    result["overflow"] = counts[index] > limit
                if code is not None and all(eof):
                    break
                if not stopping and (
                    now >= run_until
                    or stdin_error
                    or output.get("overflow")
                    or error.get("overflow")
                    or (
                        parent_ended is not None
                        and now >= parent_ended + COLLECT_DRAIN_GRACE
                    )
                ):
                    stopping = True
                    stop_until = now + COLLECT_STOP_GRACE
                    signal_observed()
                if stopping and now >= stop_until:
                    break
                # Small POSIX pipe buffers must not impose one sleep per block.
                # Deadline/overflow checks still run on every bounded read;
                # process observation retains the same polling cadence.
                if not progressed:
                    time.sleep(COLLECT_POLL)
    except Exception as exc:
        errors.append(type(exc).__name__)
        stopping = True
        signal_observed()
        # No blocking wait or pipe-reader thread survives an I/O/identity error.
        end = (
            stop_until
            if stop_until is not None
            else time.monotonic() + COLLECT_STOP_GRACE
        )
        stop_until = end
        while child.poll() is None and time.monotonic() < end:
            time.sleep(COLLECT_POLL)
    finally:
        for index, (stream, _, result, limit) in enumerate(streams):
            result.update(
                bytes=counts[index],
                sha256=hashes[index].hexdigest(),
                truncated=counts[index] > limit,
                overflow=counts[index] > limit,
                eof=eof[index],
            )
            stream.close()
        if child.stdin is not None:
            child.stdin.close()
    # Reobserve only these frozen lifetimes, without signals or a new cleanup
    # allowance. Parent exit/EOF can precede OS lifetime visibility settling.
    terminal_until = min(
        run_until + COLLECT_STOP_GRACE,
        stop_until
        if stop_until is not None
        else (parent_ended if parent_ended is not None else time.monotonic())
        + COLLECT_STOP_GRACE,
    )
    terminal_observations = []
    while True:
        unresolved = []
        for row in observed.values():
            try:
                require_absent(row)
            except (psutil.Error, ValueError) as exc:
                unresolved.append(
                    {"process": row, "error": type(exc).__name__, "message": str(exc)}
                )
        terminal_observations.append({"at": time.time(), "unresolved": unresolved})
        absent = not unresolved
        remaining = terminal_until - time.monotonic()
        if absent or not all(eof) or child.poll() is None or remaining <= 0:
            errors.extend("terminal_" + row["error"] for row in unresolved)
            break
        time.sleep(min(COLLECT_POLL, remaining))
    complete = absent and all(eof) and child.poll() is not None
    if not complete or errors:
        STOP.set()
    if stopping:
        write(folder / "bounded-stop.json", {"at": time.time(), "signals": signals})
    return {
        "process": start,
        "observed_lifetimes": list(observed.values()),
        "exit_code": child.poll(),
        "ended_at": time.time(),
        "stdout": output,
        "stderr": error,
        "stdin_error": stdin_error,
        "bounded_stop": stopping,
        "all_observed_processes_absent": absent,
        "terminal_observations": terminal_observations,
        "pipes_reached_eof": all(eof),
        "collection_errors": errors,
    }


def event_identity(folder, receipt):
    require(
        receipt["exit_code"] == 0
        and receipt["stdin_error"] is None
        and not receipt["bounded_stop"]
        and not receipt["stdout"]["truncated"]
        and not receipt["stderr"]["truncated"]
        and receipt["all_observed_processes_absent"]
        and receipt.get("pipes_reached_eof") is True
        and receipt.get("collection_errors") == [],
        "Original CLI attempt did not complete cleanly",
    )
    threads, completed = [], 0
    for line in (folder / "events.jsonl").read_bytes().splitlines():
        event = shared.decode(line)
        require(
            type(event) is dict
            and event.get("type")
            in (
                "thread.started",
                "turn.started",
                "item.started",
                "item.updated",
                "item.completed",
                "turn.completed",
            ),
            "Unexpected CLI event",
        )
        if event.get("type") == "thread.started":
            threads.append(event["thread_id"])
        if event.get("type") == "turn.completed":
            completed += 1
        item = event.get("item", {})
        require(
            not item or item.get("type") in ("reasoning", "agent_message"),
            "Assessor used a forbidden tool",
        )
    require(
        len(threads) == 1 and type(threads[0]) is str and threads[0] and completed == 1,
        "Fresh completed CLI thread required",
    )
    return threads[0]


def execute(args, context, batch, lane, prior_note="", claims=None):
    require(not STOP.is_set(), "Another assessor lifetime requires observation")
    ownership(args, context["grant"])
    require(time.time() < context["deadline"] - 180, "No new session near deadline")
    session = "scene349:" + lane + ":" + str(batch["index"]) + ":" + uuid4().hex
    message = review.assessment_prompt(
        batch, session, lane, prior_note=prior_note, claims=claims
    )
    schema = review.assessment_schema(batch, session, lane)
    require(len(message.encode()) < 256 * 1024, "Prompt/context bound exceeded")
    paths = []
    for sheet in batch["images"]:
        path = shared.safe_path(args.gallery, sheet["path"])
        require(
            path.stat().st_size == sheet["bytes"]
            and shared.file_hash(path) == sheet["sha256"],
            "Image payload changed",
        )
        paths.append(path)
    cli = context["consumers"]["cli"]
    require(shared.file_hash(cli["path"]) == cli["sha256"], "CLI binary changed")
    folder = reserve(args, batch, lane, session)
    result = {
        "batch_index": batch["index"],
        "session_id": session,
        "thread_id": None,
        "status": "failed",
        "document": None,
    }
    try:
        write(folder / "schema.json", schema)
        with (folder / "prompt.txt").open("xb") as handle:
            handle.write(message.encode("utf-8"))
        sandbox = folder / "empty-workspace"
        sandbox.mkdir()
        verify_cli_configuration(context, sandbox)
        command = [
            cli["path"],
            "exec",
            "--config",
            "project_doc_max_bytes=0",
            "--config",
            "features.shell_tool=false",
            "--config",
            "features.apps=false",
            "--config",
            'web_search="disabled"',
            "--config",
            "memories.use_memories=false",
            "--config",
            "memories.generate_memories=false",
            "--config",
            'forced_login_method="chatgpt"',
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "--json",
            "--cd",
            str(sandbox),
            "--output-schema",
            str(folder / "schema.json"),
            "--output-last-message",
            str(folder / "original-final.json"),
        ]
        for path in paths:
            command.extend(("--image", str(path)))
        command.append("-")
        env = {k: v for k, v in os.environ.items() if k not in CREDENTIALS}
        with (folder / "prompt.txt").open("rb") as prompt_input:
            # Serialize the final fence check and launch with fatal-lane fencing.
            # A reservation already charged remains evidence even if fenced here.
            with LOCK:
                require(
                    not STOP.is_set(), "Another assessor lifetime requires observation"
                )
                write(
                    folder / "invocation.json",
                    {
                        "command": command,
                        "prompt_sha256": shared.digest(message.encode()),
                        "schema_sha256": shared.file_hash(folder / "schema.json"),
                    },
                )
                child = subprocess.Popen(
                    command,
                    cwd=sandbox,
                    env=env,
                    stdin=prompt_input,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
        receipt = collect(child, message, folder, context["deadline"])
        write(folder / "finish.json", receipt)
        result["thread_id"] = event_identity(folder, receipt)
        final = shared.safe_path(folder, "original-final.json")
        require(final.stat().st_size <= 512 * 1024, "Response too large")
        document = read(final)
        review.validate_reading(document, batch, session, lane)
        for path, sheet in zip(paths, batch["images"]):
            require(
                shared.file_hash(path) == sheet["sha256"],
                "Image changed during assessment",
            )
        ownership(args, context["grant"])
        result.update(status="completed", document=document)
    except Exception as exc:
        write(
            folder / "failure.json",
            {
                "type": type(exc).__name__,
                "message": str(exc),
                "replacement_allowed": False,
            },
        )
        # A launched process without durable terminal evidence is not a failed,
        # safely replaceable session. Stop this orchestration for observation.
        if (folder / "invocation.json").exists() and not (
            folder / "finish.json"
        ).exists():
            STOP.set()
            raise
    write(folder / "result.json", result)
    return result


def lane_run(args, context, schedule, lane):
    results, note, previous_view = [], "", None
    for batch in schedule:
        require(not STOP.is_set(), "Another assessor lifetime requires observation")
        if previous_view != batch["view_index"]:
            note = ""
        result = execute(args, context, batch, lane, note)
        results.append(result)
        note = (
            result["document"]["continuity_note"]
            if result["status"] == "completed"
            else ""
        )
        previous_view = batch["view_index"]
    assembled = review.assemble_lane(schedule, results, lane)
    write(args.output / f"{lane}.json", assembled)
    return assembled


def session_seal(output, lanes):
    return {
        p.relative_to(output).as_posix(): shared.file_hash(p)
        for lane in lanes
        for p in sorted((output / "sessions" / lane).rglob("*"))
        if p.is_file()
    }


def originals(args):
    context, _protocol, schedule = current(args, image_audit=True)
    published(args, context)
    require(
        not (args.output / "originals").exists()
        and not (args.output / "sessions").exists(),
        "Original attempt already exists",
    )

    def calculate(progress):
        failures = []

        def guarded_lane(lane):
            try:
                return lane_run(args, context, schedule, lane)
            except Exception as exc:
                with LOCK:
                    if not failures:
                        failures.append(exc)
                    STOP.set()
                raise

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(guarded_lane, lane) for lane in LANES]
            lanes = []
            for future in futures:
                try:
                    lanes.append(future.result())
                except Exception:
                    # Observe the other already launched lane before propagating
                    # the first fatal cause, even when it was the second future.
                    pass
        if failures:
            raise failures[0]
        comparison = review.compare_lanes(schedule, *lanes)
        write(args.output / "comparison-original.json", comparison)
        seal = {
            "sessions": session_seal(args.output, LANES),
            "lanes": {
                lane: shared.file_hash(args.output / f"{lane}.json") for lane in LANES
            },
            "comparison_sha256": shared.file_hash(
                args.output / "comparison-original.json"
            ),
            "sealed_at": time.time(),
        }
        write(args.output / "original-streams-seal.json", seal)
        current(args, image_audit=True)
        progress(1)
        return {
            "status": "originals_sealed",
            "seal_sha256": shared.file_hash(args.output / "original-streams-seal.json"),
            "aggregate": comparison["aggregate"],
        }

    return admitted(args, "originals", calculate)


def verify_originals(args):
    terminal = read(args.output / "originals/terminal.json")
    require_absent(terminal["process"])
    preparation.check_store_terminal(args.root, terminal)
    seal_path = args.output / "original-streams-seal.json"
    require(
        shared.file_hash(seal_path) == terminal["summary"]["seal_sha256"],
        "Original stream seal changed",
    )
    seal = read(seal_path)
    require(
        session_seal(args.output, LANES) == seal["sessions"],
        "Original assessor evidence changed",
    )
    require(
        all(
            shared.file_hash(args.output / f"{lane}.json") == seal["lanes"][lane]
            for lane in LANES
        ),
        "Original lane changed",
    )
    require(
        shared.file_hash(args.output / "comparison-original.json")
        == seal["comparison_sha256"],
        "Original comparison changed",
    )
    return [read(args.output / f"{lane}.json") for lane in LANES]


def adjudicate(args):
    context, _protocol, schedule = current(args)
    published(args, context)
    lanes = verify_originals(args)
    comparison = review.compare_lanes(schedule, *lanes)

    def calculate(progress):
        results = []
        for batch in schedule:
            keys = {
                (batch["view_index"], m["frame"])
                for s in batch["images"]
                for m in s["members"]
            }
            relevant = [
                r
                for r in comparison["records"]
                if (r["view_index"], r["frame"]) in keys
            ]
            # The compact source claims remain private; no model outputs enter.
            needed = batch["index"] in comparison["adjudication_batch_indices"]
            if needed:
                grouped = {}
                for row in relevant:
                    for name, lane in (
                        ("original_a", LANES[0]),
                        ("original_b", LANES[1]),
                    ):
                        for original in row[name]["readings"]:
                            key = (
                                lane,
                                original["scene"],
                                original["transition"],
                                original["source_reason"],
                            )
                            grouped.setdefault(key, set()).add(row["frame"])
                claims = [
                    {
                        "frames": sorted(frames),
                        "lane": key[0],
                        "scene": key[1],
                        "transition": key[2],
                        "source_reason": key[3],
                    }
                    for key, frames in grouped.items()
                ]
                results.append(
                    execute(args, context, batch, "adjudication", claims=claims)
                )
        resolved = review.assemble_lane(schedule, results, "adjudication")
        final = review.compare_lanes(schedule, *lanes, adjudication=resolved)
        write(args.output / "adjudication.json", resolved)
        write(args.output / "comparison-final.json", final)
        current(args, image_audit=True)
        verify_originals(args)
        progress(1)
        return {
            "status": "adjudication_complete",
            "aggregate": final["aggregate"],
            "comparison_sha256": shared.file_hash(
                args.output / "comparison-final.json"
            ),
            "session_seal": session_seal(args.output, ("adjudication",)),
        }

    return admitted(args, "adjudication", calculate)


def admitted(args, stage, calculate):
    from badminton.jobs import run_local_job

    require(
        not any(os.environ.get(k) for k in CREDENTIALS),
        "Credential-free orchestration environment required",
    )
    store = preparation.shared_store(args.root)
    folder = args.output / stage
    folder.mkdir(exist_ok=False)
    process, job_id = identity(), None
    write(
        folder / "attempt.json",
        {
            "process": process,
            "started_at": time.time(),
            "implicit_retry_permitted": False,
        },
    )

    def work(identifier, progress):
        nonlocal job_id
        job_id = identifier
        write(
            folder / "admission.json",
            {
                "job_id": job_id,
                "process": process,
                "context_sha256": args.context_sha256,
            },
        )
        return calculate(progress)

    try:
        result = run_local_job(
            store, "shuttle_scene_" + stage, "familiar-scene349", work
        )
    except BaseException as exc:
        write(
            folder / "failure.json",
            {
                "job_id": job_id,
                "process": process,
                "type": type(exc).__name__,
                "message": str(exc),
                "implicit_retry_permitted": False,
            },
        )
        raise
    terminal = {
        "status": "completed",
        "job_id": job_id,
        "process": process,
        "summary": result,
        "admission_sha256": shared.file_hash(folder / "admission.json"),
    }
    write(folder / "terminal.json", terminal)
    return {
        "status": result["status"],
        "terminal_sha256": shared.file_hash(folder / "terminal.json"),
    }


def audit(args):
    _context, _protocol, schedule = current(args, image_audit=True)
    lanes = verify_originals(args)
    terminal = read(args.output / "adjudication/terminal.json")
    require_absent(terminal["process"])
    preparation.check_store_terminal(args.root, terminal)
    require(
        session_seal(args.output, ("adjudication",))
        == terminal["summary"]["session_seal"],
        "Adjudication evidence changed",
    )
    comparison = review.compare_lanes(
        schedule, *lanes, adjudication=read(args.output / "adjudication.json")
    )
    require(
        read(args.output / "comparison-final.json") == comparison,
        "Comparison does not reproduce",
    )
    require(
        shared.file_hash(args.output / "comparison-final.json")
        == terminal["summary"]["comparison_sha256"],
        "Final comparison changed",
    )
    reservations = [
        read(p) for p in (args.output / "sessions").glob("*/*/reservation.json")
    ]
    result = {
        "status": "audited",
        "aggregate": comparison["aggregate"],
        "attempted_sessions": len(reservations),
        "attempted_image_bytes": sum(r["image_bytes"] for r in reservations),
        "retained_task_bytes": task_bytes(args.root),
        "original_inputs_and_truth_unchanged": True,
        "terminal_store_verified": True,
        "eligibility": shared.ELIGIBILITY,
        "full_match_accuracy_established": False,
        "complete_independent_rally_references": "0/2",
    }
    require(
        result["attempted_sessions"] <= 225
        and result["attempted_image_bytes"] <= 976856850,
        "Final payload budget exceeded",
    )
    write(args.output / "verification.json", result)
    return result


def validate_output(root, output):
    require(
        output.parent == root / ".cache" and output.name.startswith("scene349"),
        "Task-private output required",
    )


def main(argv=None):
    global BUDGET_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "originals", "adjudicate", "audit"))
    for name in ("root", "gallery", "protocol", "grant", "ownership", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--context-sha256")
    parser.add_argument("--timestamp", type=Path)
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    BUDGET_ROOT = args.root
    for name in ("gallery", "protocol", "grant", "ownership", "output", "timestamp"):
        value = getattr(args, name)
        if value is None:
            continue
        value = value.absolute()
        require(
            value.is_relative_to(args.root), "Bound path outside original namespace"
        )
        shared.safe_path(
            args.root,
            value.relative_to(args.root).as_posix(),
            must_exist=name not in ("output", "gallery"),
        )
        setattr(args, name, value)
    validate_output(args.root, args.output)
    if args.stage != "freeze":
        require(
            args.context_sha256 and args.timestamp,
            "Frozen context and public timestamp required",
        )
    os.environ.update(
        BADMINTON_ROOT=str(args.root),
        BADMINTON_DATA_DIR=str(args.root / "data/processed"),
        BADMINTON_WEIGHTS_DIR=str(args.root / "models/weights"),
    )
    result = {
        "freeze": freeze,
        "originals": originals,
        "adjudicate": adjudicate,
        "audit": audit,
    }[args.stage](args)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
