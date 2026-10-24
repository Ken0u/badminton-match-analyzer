"""Metadata gates for an explicitly authorized source-assessment continuation.

Archived execution is checked against its original clock. Only a separately
frozen current context can authorize a new dispatch. This module never changes
an archived context, reads scientific labels, or decides reference correctness.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import psutil

MAX_BYTES = 8 * 1024**3
MAX_LOG_BYTES = 16 * 1024**2


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("Expected an exact bounded integer")
    return value


def moment(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("Expected a finite nonnegative timestamp")
    return value


def identifier(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a nonempty execution identifier")
    return value


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(part)
    return result.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def exclusive_json(path, value):
    path = Path(path)
    data = json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(data)


def archived_context(saved, actual):
    """Verify bytes/runtime retrospectively, without granting another dispatch."""
    if saved != actual:
        raise ValueError("Archived consumers or runtime changed")
    granted = integer(saved["granted_at"])
    deadline = integer(saved["deadline"])
    if deadline <= granted:
        raise ValueError("Invalid archived execution interval")
    return granted, deadline


def current_deadline(granted_at, *, now=None, seconds=8 * 3600):
    granted_at = integer(granted_at)
    seconds = integer(seconds, 1)
    now = moment(time.time() if now is None else now)
    if not granted_at <= now < granted_at + seconds - 60:
        raise ValueError("Successor dispatch interval is not open")
    return granted_at + seconds


def absent(row):
    pid = integer(row["pid"], 1)
    created = moment(row["creation_time"])
    if created < psutil.boot_time():
        return
    try:
        process = psutil.Process(pid)
        if process.create_time() == created:
            raise ValueError("Recorded process lifetime remains live")
    except psutil.NoSuchProcess:
        pass


class Identities:
    """Global uniqueness and independently observed exit, without process signals."""

    def __init__(self):
        self.threads = set()
        self.sessions = set()
        self.lifetimes = set()

    def add(self, row, *, success=True):
        thread = identifier(row.get("thread_id"))
        session = row.get("session_id")
        if success or session is not None:
            session = identifier(session)
        lifetime = (integer(row["pid"], 1), moment(row["creation_time"]))
        if (
            thread in self.threads
            or (session is not None and session in self.sessions)
            or lifetime in self.lifetimes
        ):
            raise ValueError("Reused execution identity")
        code = row.get("exit_code")
        if (
            type(code) is not int
            or row.get("exited") is not True
            or (success and (code != 0 or row.get("execution_protocol_failures")))
        ):
            raise ValueError("Unsuccessful or malformed execution receipt")
        absent(row)
        self.threads.add(thread)
        if session is not None:
            self.sessions.add(session)
        self.lifetimes.add(lifetime)


def events(path):
    path = Path(path)
    if path.stat().st_size >= MAX_LOG_BYTES:
        raise ValueError("Execution log exceeds its bound")
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    rows = []
    while text.strip():
        text = text.lstrip()
        row, end = decoder.raw_decode(text)
        if not isinstance(row, dict):
            raise ValueError("Malformed execution event")
        rows.append(row)
        text = text[end:]
    return rows


def verify_execution(folder, chunk, *, granted_at, frozen_at, deadline, identities):
    """Check a success using metadata and opaque output hashes only."""
    folder = Path(folder)
    start = read(folder / "start.json")
    finish = read(folder / "finish.json")
    reservation = read(folder / "payload-reservation.json")
    if any(finish.get(key) != value for key, value in start.items()):
        raise ValueError("Start/finish receipt mismatch")
    begin, end, reserved = (
        moment(start["started_at"]),
        moment(finish["ended_at"]),
        moment(reservation["reserved_at"]),
    )
    if not (
        integer(granted_at)
        <= moment(frozen_at)
        <= reserved
        <= begin
        <= end
        < integer(deadline)
    ):
        raise ValueError("Execution is outside its own frozen interval")
    expected = [integer(n) for n in chunk["frames"]]
    images = start["images"]
    if (
        not expected
        or len(expected) != len(set(expected))
        or [integer(row["frame"]) for row in images] != expected
        or reservation["images"] != images
        or reservation["lane"] != "adjudication"
        or reservation["source_id"] != chunk["source_id"]
        or integer(reservation["chunk"]) != integer(chunk["index"])
        or integer(start["image_bytes"], 1) != integer(reservation["image_bytes"], 1)
        or start["image_bytes"] != integer(chunk["image_bytes"], 1)
    ):
        raise ValueError("Execution native membership or payload mismatch")
    rows = events(folder / "events.jsonl")
    if (
        dict(Counter(identifier(row["type"]) for row in rows)) != finish["events"]
        or sum(integer(row["bytes"], 1) for row in rows)
        != integer(finish["stdout_bytes"], 1)
        or finish["stdout_bytes"] >= MAX_LOG_BYTES
        or [row["thread_id"] for row in rows if row["type"] == "thread.started"]
        != [finish["thread_id"]]
        or sum(row["type"] == "turn.completed" for row in rows) != 1
        or any(row["type"] in ("error", "turn.failed") for row in rows)
        or any(
            row.get("item_type") not in (None, "reasoning", "agent_message")
            for row in rows
        )
        or digest(folder / "original-final.json") != finish["original_output_sha256"]
    ):
        raise ValueError("Execution event log or opaque output mismatch")
    identities.add(finish)
    return {
        "source_id": chunk["source_id"],
        "chunk": chunk["index"],
        "original_path": str(folder / "original-final.json"),
        "original_sha256": digest(folder / "original-final.json"),
        "receipt_path": str(folder / "finish.json"),
        "receipt_sha256": digest(folder / "finish.json"),
        "thread_id": finish["thread_id"],
        "session_id": finish["session_id"],
        "frames": expected,
    }


def complete_index(chunks, entries):
    """Require both sources' exact coverage before any scientific reader runs."""
    expected = [(identifier(c["source_id"]), integer(c["index"])) for c in chunks]
    actual = [(identifier(e["source_id"]), integer(e["chunk"])) for e in entries]
    if not expected or len(set(expected)) != len(expected) or actual != expected:
        raise ValueError("Both complete target indexes are required")
    for chunk, entry in zip(chunks, entries):
        frames = [integer(n) for n in chunk["frames"]]
        if not frames or frames != [integer(n) for n in entry["frames"]]:
            raise ValueError("Combined target frame membership changed")
        for field in ("original", "receipt"):
            if digest(entry[field + "_path"]) != entry[field + "_sha256"]:
                raise ValueError("Combined target artifact changed")
    return {"complete": True, "segments": entries, "scientific_labels_read": False}


def payload_total(prior_bytes, reservations, *, limit=MAX_BYTES):
    total = integer(prior_bytes)
    paths = [Path(p).resolve() for p in reservations]
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate reservation path would double-charge metadata")
    for path in paths:
        total += integer(read(path)["image_bytes"], 1)
    if total > integer(limit, 1):
        raise ValueError("Cumulative attempted payload exceeds its bound")
    return total


@contextmanager
def dispatch_lock(path):
    """OS-owned exclusive lock; interruption never requires deleting a lock file."""
    with Path(path).open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def reserve_and_launch(
    output, reservation, *, granted_at, prior_bytes, launch, now=None
):
    """Single serialized budget/clock/fence check immediately before launch."""
    output = Path(output)
    run_name = reservation.get("run_name")
    if not isinstance(run_name, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,128}", run_name
    ):
        raise ValueError("Invalid exclusive run name")
    with dispatch_lock(output / "dispatch.lock"):
        if (output / "STOP.json").exists():
            raise ValueError("Continuation dispatch is fenced")
        current_deadline(granted_at, now=now)
        total = payload_total(
            prior_bytes, output.glob("runs/*/payload-reservation.json")
        )
        amount = integer(reservation["image_bytes"], 1)
        if total + amount > MAX_BYTES:
            raise ValueError("New attempt would exceed cumulative image budget")
        target = output / "runs" / reservation["run_name"] / "payload-reservation.json"
        exclusive_json(target, reservation)
        try:
            child = launch()
        except BaseException:
            if not (output / "STOP.json").exists():
                exclusive_json(output / "STOP.json", {"reason": "launch_failed"})
            raise
        return total + amount, child


def collect_output(child, prompt, folder, fence):
    """Drain both pipes, retain bounded metadata and observe actual child exit.

    No raw CLI error or event payload is persisted or printed. Malformed or
    oversized streams fence new work while the original process is drained.
    """
    failures = set()
    stderr = {"bytes": 0}
    failure_lock = threading.Lock()

    def fail(reason):
        with failure_lock:
            if reason not in failures:
                failures.add(reason)
                try:
                    fence(reason)
                except Exception:
                    failures.add("fence_persistence_failed")

    def drain_errors():
        result = hashlib.sha256()
        try:
            for part in iter(lambda: child.stderr.read(65536), b""):
                result.update(part)
                stderr["bytes"] += len(part)
                if stderr["bytes"] >= MAX_LOG_BYTES:
                    fail("stderr_limit_exceeded")
        except OSError:
            fail("stderr_read_failed")
        stderr["sha256"] = result.hexdigest()

    errors = threading.Thread(target=drain_errors)
    errors.start()

    def send_prompt():
        try:
            child.stdin.write(prompt.encode("utf-8"))
        except OSError:
            fail("stdin_write_failed")
        finally:
            try:
                child.stdin.close()
            except OSError:
                fail("stdin_close_failed")

    writer = threading.Thread(target=send_prompt)
    writer.start()
    thread = None
    counts = Counter()
    raw_hash = hashlib.sha256()
    raw_bytes = log_bytes = 0
    with (Path(folder) / "events.jsonl").open("xb") as handle:
        try:
            while raw := child.stdout.readline(MAX_LOG_BYTES + 1):
                raw_hash.update(raw)
                raw_bytes += len(raw)
                if raw_bytes >= MAX_LOG_BYTES:
                    fail("stdout_limit_exceeded")
                    continue
                try:
                    row = json.loads(raw)
                    if not isinstance(row, dict):
                        raise ValueError
                    kind = identifier(row.get("type"))
                    item = row.get("item", {})
                    if not isinstance(item, dict):
                        raise ValueError
                    item_type = item.get("type")
                    if item_type not in (None, "reasoning", "agent_message"):
                        fail("unexpected_tool_exposure")
                except (ValueError, UnicodeError, RecursionError):
                    fail("malformed_stdout_event")
                    kind, item_type, row = "invalid.stdout", None, {}
                counts[kind] += 1
                if kind in ("error", "turn.failed"):
                    fail("cli_reported_failure")
                if kind == "thread.started":
                    candidate = row.get("thread_id")
                    if (
                        thread is not None
                        or not isinstance(candidate, str)
                        or not candidate.strip()
                    ):
                        fail("invalid_or_duplicate_thread")
                    else:
                        thread = candidate
                small = {
                    "type": kind,
                    "item_type": item_type,
                    "bytes": len(raw),
                    "raw_sha256": hashlib.sha256(raw).hexdigest(),
                }
                if kind == "thread.started":
                    small["thread_id"] = row.get("thread_id")
                data = (json.dumps(small, sort_keys=True) + "\n").encode("utf-8")
                if log_bytes + len(data) >= MAX_LOG_BYTES:
                    fail("execution_metadata_limit_exceeded")
                else:
                    handle.write(data)
                    log_bytes += len(data)
        except OSError:
            fail("stdout_read_failed")
    code = child.wait()
    writer.join()
    errors.join()
    if counts["thread.started"] != 1 or not thread or counts["turn.completed"] != 1:
        fail("incomplete_execution_events")
    if code != 0:
        fail("nonzero_child_exit")
    return {
        "thread_id": thread,
        "exit_code": code,
        "exited": True,
        "ended_at": time.time(),
        "events": dict(counts),
        "stdout_sha256": raw_hash.hexdigest(),
        "stdout_bytes": raw_bytes,
        "stderr_sha256": stderr["sha256"],
        "stderr_bytes": stderr["bytes"],
        "execution_protocol_failures": sorted(failures),
    }
