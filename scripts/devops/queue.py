"""Deterministic coordination state machine; all GitHub IO belongs to the adapter.

Apply requests to the latest state inside one serialized, fast-forward-only write.
An expired lease fences workers but deliberately does not release reservations.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from typing import Any

from .policy import scope_authorized, sensitive_scope

LEASE_SECONDS = 3 * 60 * 60
RESERVED = {
    "running",
    "review",
    "integrating",
    "verifying_main",
    "recovery_required",
    "needs_human",
}
SHA = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
DENIED_ROOTS = {
    ".git",
    ".cache",
    ".venv",
    "node_modules",
    "datasets",
    "weights",
    "raw",
    ".aws",
    ".ssh",
    ".codex",
    ".agents",
    ".env",
}
SOURCE_ROOTS = {"backend", "tests", "scripts", "docs", ".github"}
ROOT_FILES = {
    "AGENTS.md",
    "PROGRESS.md",
    "PROJECT_PLAN.md",
    "README.md",
    "Dockerfile",
    ".dockerignore",
    ".gitignore",
    ".gitattributes",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "requirements.lock",
    "uv.lock",
    "MANIFEST.in",
    ".python-version",
    ".node-version",
}
IGNORED_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".pyc", ".pyo"}
WINDOWS_DEVICES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


class QueueError(ValueError):
    """A rejected request; callers must not persist a partial transition."""


def initial_state() -> dict:
    return {"version": 1, "tasks": {}, "workers": {}, "receipts": {}, "paused": False}


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise QueueError("value must be finite JSON") from exc


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 20000:
        raise QueueError(f"{name} must be nonempty text")
    return value


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise QueueError(f"invalid {name}")
    return value


def _strings(value: Any, name: str, *, nonempty: bool = False) -> list:
    if not isinstance(value, list) or (nonempty and not value):
        raise QueueError(f"{name} must be a list")
    for entry in value:
        _text(entry, name)
    if len(set(value)) != len(value):
        raise QueueError(f"duplicate {name}")
    return value


def _path(value: Any) -> str:
    _text(value, "path")
    parts = value.rstrip("/").split("/")
    if (
        value.startswith("/")
        or "\\" in value
        or any(c in value for c in "*?[]{}:%\x00\n\r\t")
        or any(p in {"", ".", ".."} or p.endswith((" ", ".")) for p in parts)
        or any(
            p.casefold() in DENIED_ROOTS or p.casefold().startswith(".env")
            for p in parts
        )
        or any(any(ord(c) < 32 or ord(c) > 126 for c in p) for p in parts)
        or any(p.casefold().split(".")[0] in WINDOWS_DEVICES for p in parts)
        or any(
            p.casefold().endswith(suffix) for suffix in IGNORED_SUFFIXES for p in parts
        )
        or any(
            p.casefold()
            in {
                "__pycache__",
                ".pytest_cache",
                ".ruff_cache",
                ".media",
                "build",
                "test-results",
                "playwright-report",
            }
            or p.casefold().endswith(".egg-info")
            for p in parts
        )
    ):
        raise QueueError(f"unsafe reservation path: {value!r}")
    if not (
        parts[0] in SOURCE_ROOTS
        or value in ROOT_FILES
        or (len(parts) >= 2 and parts[:2] == ["data", "manifests"])
    ):
        raise QueueError(f"unknown source reservation path: {value!r}")
    return value


def paths_overlap(left: str, right: str) -> bool:
    """Conservative case-insensitive ancestor conflicts across Mac and Windows."""
    a, b = left.rstrip("/").casefold(), right.rstrip("/").casefold()
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _artifacts(value: Any) -> dict:
    if not isinstance(value, dict):
        raise QueueError("artifacts must map names to SHA256 hashes")
    for name, digest in value.items():
        _identifier(name, "artifact name")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise QueueError("artifact hash must be lowercase SHA256")
    return value


def validate_spec(spec: dict) -> None:
    required = {
        "outcome",
        "acceptance",
        "exclusions",
        "paths",
        "capabilities",
        "artifacts",
        "resources",
        "dependencies",
        "priority",
        "milestone",
        "risk",
        "verification",
        "limits",
    }
    if not isinstance(spec, dict) or set(spec) != required:
        raise QueueError("spec fields must match the version 1 task contract")
    _text(spec["outcome"], "outcome")
    for key in (
        "acceptance",
        "exclusions",
        "paths",
        "capabilities",
        "resources",
        "dependencies",
        "verification",
    ):
        _strings(
            spec[key], key, nonempty=key in {"acceptance", "paths", "verification"}
        )
    for path in spec["paths"]:
        _path(path)
    if len({p.casefold() for p in spec["paths"]}) != len(spec["paths"]):
        raise QueueError("duplicate case-insensitive paths")
    for key in ("capabilities", "resources"):
        for entry in spec[key]:
            _identifier(entry, key)
    for dep in spec["dependencies"]:
        if not re.fullmatch(r"[1-9][0-9]*", dep):
            raise QueueError("dependency must be a positive issue number string")
    _artifacts(spec["artifacts"])
    if type(spec["priority"]) is not int or not 0 <= spec["priority"] <= 1000:
        raise QueueError("priority must be an integer from 0 to 1000")
    _text(spec["milestone"], "milestone")
    if spec["risk"] not in {"routine", "human"}:
        raise QueueError("risk must be routine or human")
    if not isinstance(spec["limits"], dict):
        raise QueueError("limits must be an object")
    _json(spec)


def spec_hash(spec: dict) -> str:
    validate_spec(spec)
    return hashlib.sha256(_json(spec).encode("utf-8")).hexdigest()


def _clock(now: int) -> None:
    if type(now) is not int or now < 0:
        raise QueueError("now must be a nonnegative integer epoch")


def expire_leases(state: dict, now: int) -> dict:
    _clock(now)
    result = copy.deepcopy(state)
    for task in result["tasks"].values():
        claim = task.get("claim")
        if task["status"] == "running" and claim and claim["expires_at"] <= now:
            task["status"] = "recovery_required"
            task["reason"] = "implementation lease expired; reservations retained"
        review = task.get("review_claim")
        if task["status"] == "review" and review and review["expires_at"] <= now:
            task.pop("review_claim")
            task["reason"] = (
                "review lease expired; implementation reservations retained"
            )
    return result


def _task_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise QueueError("task_id must be a positive issue number string")
    return value


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise QueueError(f"{name} must be a lowercase Git SHA")
    return value


def _worker(state: dict, request: dict, actor: str) -> dict:
    host = _identifier(request.get("host_id"), "host_id")
    session = _identifier(request.get("session_id"), "session_id")
    worker = state["workers"].get(f"{host}/{session}")
    if (
        not worker
        or worker["actor"].casefold() != actor.casefold()
        or worker["session_id"] != session
    ):
        raise QueueError("worker registration does not match actor, host and session")
    return worker


def _owned(
    task: dict,
    request: dict,
    actor: str,
    now: int,
    *,
    review: bool = False,
    expired: bool = False,
) -> dict:
    claim = task.get("review_claim" if review else "claim")
    if type(request.get("epoch")) is not int or (
        review and type(request.get("review_epoch")) is not int
    ):
        raise QueueError("claim epoch must be an integer")
    if (
        not claim
        or any(
            claim.get(key) != request.get(key)
            for key in ("host_id", "session_id", "epoch")
        )
        or claim["actor"].casefold() != actor.casefold()
    ):
        raise QueueError("claim actor, host, session or epoch mismatch")
    if review and claim["review_epoch"] != request["review_epoch"]:
        raise QueueError("review epoch mismatch")
    if not expired and claim["expires_at"] <= now:
        raise QueueError("claim lease expired")
    return claim


def _conflict(state: dict, task_id: str, spec: dict) -> bool:
    for other_id, other in state["tasks"].items():
        if (
            other_id == task_id
            or other["status"] not in RESERVED
            or not other.get("claim")
        ):
            continue
        if set(spec["resources"]) & set(other["spec"]["resources"]):
            return True
        if (
            other_id == state["tasks"].get(task_id, {}).get("repair_for")
            and other["status"] == "verifying_main"
        ):
            continue
        if any(
            paths_overlap(a, b) for a in spec["paths"] for b in other["spec"]["paths"]
        ):
            return True
    return False


def _cycles(tasks: dict) -> None:
    visiting, visited = set(), set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise QueueError("dependency cycle")
        if task_id in visited or task_id not in tasks:
            return
        visiting.add(task_id)
        for dep in tasks[task_id]["spec"]["dependencies"]:
            visit(dep)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in tasks:
        visit(task_id)


def _terminal_proof(request: dict, claim: dict) -> dict:
    proof = request.get("terminal_proof")
    if not isinstance(proof, dict) or proof.get("host_id") != claim["host_id"]:
        raise QueueError("original-host terminal proof required")
    if proof.get("terminal") is not True:
        raise QueueError("explicit terminal proof required; timeout is insufficient")
    for field in ("process", "store", "artifacts"):
        if not isinstance(proof.get(field), dict) or not proof[field]:
            raise QueueError(f"terminal proof requires {field} receipt")
    process = proof["process"]
    if (
        type(process.get("pid")) is not int
        or process["pid"] <= 0
        or type(process.get("creation_time")) not in {int, float}
        or not math.isfinite(process["creation_time"])
        or process["creation_time"] <= 0
        or process.get("exited") is not True
    ):
        raise QueueError(
            "terminal process receipt requires PID, lifetime and explicit exit proof"
        )
    _text(process.get("cwd"), "process cwd")
    _text(process.get("command"), "process command")
    if proof["store"].get("status") not in {
        "completed",
        "failed",
        "cancelled",
        "interrupted",
        "no_job",
    }:
        raise QueueError("terminal Store status required")
    _json(proof)
    return copy.deepcopy(proof)


def _milestone(spec: dict, config: dict) -> None:
    milestones = config.get("milestones", [])
    if spec["milestone"] not in milestones:
        raise QueueError("task milestone is outside configured milestones")


def apply_request(
    state: dict, request: dict, actor: str, now: int, config: dict
) -> dict:
    """Apply one authenticated command atomically, returning a new JSON state.

    ``actor`` comes from GitHub, never the command body. Coordinator-only verbs
    consume adapter-verified PR evidence; the engine itself performs no IO.
    """
    _clock(now)
    if not isinstance(state, dict) or state.get("version") != 1:
        raise QueueError("unsupported queue state version")
    if not isinstance(request, dict):
        raise QueueError("request must be an object")
    _text(actor, "actor")
    request_id = _identifier(request.get("request_id"), "request_id")
    verb = _text(request.get("verb"), "verb")
    coordinator = (
        actor.casefold()
        == config.get("coordinator_login", "github-actions[bot]").casefold()
    )
    trusted = {login.casefold() for login in config.get("trusted_logins", [])}
    if actor.casefold() not in trusted and not coordinator:
        raise QueueError("actor is not trusted")
    fingerprint = hashlib.sha256(
        _json({"request": request, "actor": actor.casefold()}).encode()
    ).hexdigest()
    previous = state["receipts"].get(request_id)
    if previous:
        if previous["fingerprint"] != fingerprint:
            raise QueueError("request_id replay has different contents or actor")
        return copy.deepcopy(state)
    result = expire_leases(state, now)
    mode = config.get("mode", "observation")
    if mode not in {"observation", "pilot", "active"}:
        raise QueueError("unknown queue mode")
    receipt = {
        "verb": verb,
        "actor": actor,
        "at": now,
        "fingerprint": fingerprint,
        "status": "ok",
    }

    if verb == "register":
        if coordinator:
            raise QueueError("coordinator cannot register as a worker")
        host = _identifier(request.get("host_id"), "host_id")
        session = _identifier(request.get("session_id"), "session_id")
        capabilities = _strings(request.get("capabilities"), "capabilities")
        for cap in capabilities:
            _identifier(cap, "capability")
        artifacts = _artifacts(request.get("artifacts"))
        if any(
            w["host_id"] == host and w["actor"].casefold() != actor.casefold()
            for w in result["workers"].values()
        ):
            raise QueueError("host belongs to another actor")
        result["workers"][f"{host}/{session}"] = {
            "actor": actor,
            "host_id": host,
            "session_id": session,
            "capabilities": capabilities,
            "artifacts": artifacts,
            "registered_at": now,
        }
    elif verb == "repair":
        if not coordinator:
            raise QueueError("repair tasks require verified coordinator evidence")
        task_id, original = (
            _task_id(request.get("task_id")),
            _task_id(request.get("repair_for")),
        )
        parent = result["tasks"].get(original, {})
        if parent.get("status") != "verifying_main" or not result["paused"]:
            raise QueueError("repair requires paused failed-main integration")
        spec = copy.deepcopy(request.get("spec"))
        digest = spec_hash(spec)
        _milestone(spec, config)
        if task_id in result["tasks"]:
            raise QueueError("repair task already exists")
        if spec["resources"] or spec["artifacts"] or spec["dependencies"]:
            raise QueueError("CI repairs cannot acquire research/data resources")
        repair_status = (
            "needs_human"
            if spec["risk"] == "human" or sensitive_scope(spec["paths"], config)
            else "ready"
        )
        result["tasks"][task_id] = {
            "spec": spec,
            "spec_hash": digest,
            "status": repair_status,
            "epoch": 0,
            "repair_for": original,
            "planned_by": actor,
            "planned_at": now,
        }
        receipt.update(task_id=task_id, status=repair_status)
    elif verb in {"pause", "resume"}:
        result["paused"] = verb == "pause"
    elif verb == "plan":
        task_id = _task_id(request.get("task_id"))
        spec = copy.deepcopy(request.get("spec"))
        digest = spec_hash(spec)
        _milestone(spec, config)
        old = result["tasks"].get(task_id)
        if old and old["status"] not in {"proposed", "ready", "needs_human", "blocked"}:
            raise QueueError(
                "active/completed tasks require scope change or a new issue"
            )
        if old and old.get("claim"):
            raise QueueError("cannot replace a task with retained reservations")
        status = (
            "needs_human"
            if spec["risk"] == "human"
            else ("proposed" if mode == "observation" else "ready")
        )
        result["tasks"][task_id] = {
            "spec": spec,
            "spec_hash": digest,
            "status": status,
            "epoch": old.get("epoch", 0) if old else 0,
            "planned_by": actor,
            "planned_at": now,
        }
        _cycles(result["tasks"])
        receipt.update(task_id=task_id, status=status)
    elif verb == "recover-merged":
        _worker(result, request, actor)
        if actor.casefold() not in {
            value.casefold() for value in config.get("human_approvers", [])
        }:
            raise QueueError("external recovery requires an explicit human approver")
        task_id = _task_id(request.get("task_id"))
        task = result["tasks"].get(task_id)
        if (
            not task
            or task["status"] not in {"blocked", "recovery_required", "needs_human"}
            or type(request.get("epoch")) is not int
            or request["epoch"] != task["epoch"]
            or request.get("spec_hash") != task["spec_hash"]
        ):
            raise QueueError(
                "external recovery requires the current fenced task binding"
            )
        if mode == "observation" or (
            mode == "pilot"
            and task_id not in {str(value) for value in config.get("pilot_tasks", [])}
        ):
            raise QueueError("external recovery is outside the current rollout mode")
        authorization = {
            "request_id": request_id,
            "actor": actor,
            "at": now,
            "epoch": task["epoch"],
            "spec_hash": task["spec_hash"],
        }
        for key in ("evidence_state_sha", "head_sha", "base_sha", "merge_sha"):
            authorization[key] = _sha(request.get(key), key)
        if (
            type(request.get("pr_number")) is not int
            or request["pr_number"] <= 0
            or request["pr_number"] != task.get("pr_number")
        ):
            raise QueueError("external recovery PR does not match the original task")
        authorization["pr_number"] = request["pr_number"]
        for key in ("human_review_attestation", "terminal_proof"):
            if key in request:
                _json(request[key])
                authorization[key] = copy.deepcopy(request[key])
        if task.get("external_recovery_request"):
            task.setdefault("external_recovery_history", []).append(
                copy.deepcopy(task["external_recovery_request"])
            )
        task["external_recovery_request"] = authorization
        task.pop("external_recovery_error", None)
        receipt.update(task_id=task_id, status="recovery_pending", epoch=task["epoch"])
    elif verb == "human-approved":
        if actor.casefold() not in {
            x.casefold() for x in config.get("human_approvers", [])
        }:
            raise QueueError("explicit configured human approver required")
        task_id = _task_id(request.get("task_id"))
        task = result["tasks"].get(task_id)
        if (
            not task
            or task["status"] not in {"needs_human", "proposed"}
            or request.get("spec_hash") != task["spec_hash"]
            or task.get("claim")
        ):
            raise QueueError("approval requires current proposed spec hash")
        task["human_approval"] = {
            "actor": actor,
            "spec_hash": task["spec_hash"],
            "at": now,
        }
        task["repair_rounds"] = 0
        task["status"] = "proposed" if mode == "observation" else "ready"
        receipt.update(task_id=task_id, status=task["status"])
    elif verb in {"next", "review-next"}:
        worker = _worker(result, request, actor)
        repair_ids = {
            key for key, item in result["tasks"].items() if item.get("repair_for")
        }
        if mode == "observation" or (result["paused"] and not repair_ids):
            receipt["status"] = "observed" if mode == "observation" else "paused"
        else:
            review = verb == "review-next"
            busy = (
                any(
                    t["status"] in RESERVED
                    and t.get("claim", {}).get("host_id") == worker["host_id"]
                    and not (result["paused"] and t["status"] == "verifying_main")
                    for t in result["tasks"].values()
                )
                if not review
                else any(
                    t.get("review_claim", {}).get("host_id") == worker["host_id"]
                    for t in result["tasks"].values()
                )
            )
            if busy:
                raise QueueError("host already owns work in this lane")
            candidates = sorted(
                result["tasks"].items(),
                key=lambda item: (item[1]["spec"]["priority"], int(item[0])),
            )
            chosen = None
            for task_id, task in candidates:
                if (
                    mode == "pilot"
                    and not task.get("repair_for")
                    and task_id not in {str(x) for x in config.get("pilot_tasks", [])}
                ):
                    continue
                if (
                    request.get("task_id") is not None
                    and _task_id(request["task_id"]) != task_id
                ):
                    continue
                spec = task["spec"]
                if result["paused"] and not task.get("repair_for"):
                    continue
                if review:
                    if (
                        task["status"] != "review"
                        or task.get("review_claim")
                        or task.get("review", {}).get("verdict") == "approve"
                        or task["claim"]["session_id"] == worker["session_id"]
                    ):
                        continue
                else:
                    if task["status"] not in {"ready", "proposed"}:
                        continue
                    if spec["risk"] == "human" and not scope_authorized(task, config):
                        continue
                    if not set(spec["capabilities"]) <= set(
                        worker["capabilities"]
                    ) or any(
                        worker["artifacts"].get(k) != v
                        for k, v in spec["artifacts"].items()
                    ):
                        continue
                    if any(
                        result["tasks"].get(dep, {}).get("status") != "done"
                        for dep in spec["dependencies"]
                    ) or _conflict(result, task_id, spec):
                        continue
                chosen = (task_id, task)
                break
            if chosen is None:
                receipt["status"] = "idle"
            else:
                task_id, task = chosen
                if not review:
                    baseline = _sha(request.get("baseline_sha"), "baseline_sha")
                    task["epoch"] += 1
                    slug = (
                        re.sub(
                            r"[^a-z0-9]+", "-", task["spec"]["outcome"].lower()
                        ).strip("-")[:40]
                        or "task"
                    )
                    suffix = f"-e{task['epoch']}" if task["epoch"] > 1 else ""
                    claim = {
                        "actor": actor,
                        "host_id": worker["host_id"],
                        "session_id": worker["session_id"],
                        "epoch": task["epoch"],
                        "granted_at": now,
                        "expires_at": now + LEASE_SECONDS,
                        "spec_hash": task["spec_hash"],
                        "baseline_sha": baseline,
                        "branch": f"codex/issue-{task_id}-{slug}{suffix}",
                    }
                    task.update(status="running", claim=claim)
                else:
                    task["review_epoch"] = task.get("review_epoch", 0) + 1
                    claim = {
                        "actor": actor,
                        "host_id": worker["host_id"],
                        "session_id": worker["session_id"],
                        "epoch": task["epoch"],
                        "review_epoch": task["review_epoch"],
                        "granted_at": now,
                        "expires_at": now + LEASE_SECONDS,
                        **task["submission"],
                    }
                    task["review_claim"] = claim
                receipt.update(
                    task_id=task_id,
                    status="granted",
                    epoch=task["epoch"],
                    claim=copy.deepcopy(claim),
                )
    elif verb in {
        "integrate",
        "verify-main",
        "invalidate-review",
        "fence-external-merge",
        "adopt-external-merge",
    }:
        if not coordinator:
            raise QueueError("adapter-verified coordinator transition required")
        task_id = _task_id(request.get("task_id"))
        task = result["tasks"].get(task_id)
        if not task:
            raise QueueError("unknown task")
        if verb == "adopt-external-merge":
            authorization = task.get("external_recovery_request", {})
            verified = request.get("verified")
            if (
                task["status"] not in {"blocked", "recovery_required", "needs_human"}
                or authorization.get("request_id") != request.get("authorization_id")
                or authorization.get("epoch") != task["epoch"]
                or authorization.get("spec_hash") != task["spec_hash"]
                or result.get("paused")
                or mode == "observation"
                or (
                    mode == "pilot"
                    and task_id
                    not in {str(value) for value in config.get("pilot_tasks", [])}
                )
                or not isinstance(verified, dict)
                or verified.get("verification_complete") is not True
                or any(
                    verified.get(key) != authorization.get(key)
                    for key in (
                        "evidence_state_sha",
                        "head_sha",
                        "base_sha",
                        "merge_sha",
                        "spec_hash",
                        "pr_number",
                    )
                )
            ):
                raise QueueError(
                    "verified external recovery no longer matches authorization"
                )
            original = verified.get("original_task")
            if (
                not isinstance(original, dict)
                or not isinstance(original.get("claim"), dict)
                or original.get("spec_hash") != task["spec_hash"]
                or spec_hash(original.get("spec")) != task["spec_hash"]
            ):
                raise QueueError("original accepted recovery evidence is required")
            if task["spec"]["resources"] or task["spec"]["artifacts"]:
                _terminal_proof(authorization, original["claim"])
            _json(verified)
            task.setdefault("history", []).append(
                {
                    "verb": verb,
                    "at": now,
                    "epoch": task["epoch"],
                    "claim": copy.deepcopy(task.get("claim")),
                    "authorization": copy.deepcopy(authorization),
                }
            )
            task["external_recovery"] = copy.deepcopy(verified)
            task["external_recovery_request"]["completed_at"] = now
            task["submission"] = copy.deepcopy(original["submission"])
            task["review"] = copy.deepcopy(original["review"])
            task.update(
                status="done",
                merge_sha=authorization["merge_sha"],
                delivery_pending=True,
                reason="External merge recovered from verified original evidence",
            )
            task.pop("external_recovery_error", None)
        elif verb == "fence-external-merge":
            if task["status"] == "done":
                raise QueueError("completed work cannot be externally fenced")
            observed = request.get("observed")
            if not isinstance(observed, dict):
                raise QueueError("external merge observations are required")
            _json(observed)
            if "external_merge" not in task:
                task["external_merge"] = {
                    "at": now,
                    "observed": copy.deepcopy(observed),
                    "original": {
                        key: copy.deepcopy(task[key])
                        for key in (
                            "status",
                            "epoch",
                            "spec",
                            "spec_hash",
                            "claim",
                            "submission",
                            "review",
                            "review_epoch",
                            "pr_number",
                            "integration",
                            "merge_sha",
                        )
                        if key in task
                    },
                }
            task["status"] = "recovery_required"
            task["reason"] = (
                "PR merged outside the recorded integration; explicit recovery required"
            )
        elif verb == "invalidate-review":
            if task["status"] not in {"review", "integrating"}:
                raise QueueError("task is not under review/integration")
            task.pop("review_claim", None)
            task.pop("review", None)
            task["status"] = (
                "running" if task["claim"]["expires_at"] > now else "recovery_required"
            )
            task["reason"] = "PR binding changed; submit and review the new head"
        elif verb == "integrate":
            if (
                task["status"] != "review"
                or task.get("review", {}).get("verdict") != "approve"
            ):
                raise QueueError("current approving review required")
            if any(
                request.get(k) != task["submission"][k]
                for k in ("head_sha", "base_sha", "spec_hash")
            ):
                raise QueueError("integration binding changed")
            if request.get("checks_passed") is not True:
                raise QueueError("exact-head checks required")
            if any(
                t["status"] in {"integrating", "verifying_main"}
                for key, t in result["tasks"].items()
                if key != task.get("repair_for")
            ):
                raise QueueError("another integration is unfinished")
            task["status"] = "integrating"
            task["integration"] = {
                "head_sha": request["head_sha"],
                "base_sha": request["base_sha"],
                "at": now,
            }
        else:
            if task["status"] not in {"integrating", "verifying_main"}:
                raise QueueError("task has no integration in progress")
            merge_sha = _sha(request.get("merge_sha"), "merge_sha")
            if task.get("merge_sha") and task["merge_sha"] != merge_sha:
                raise QueueError("merged main SHA changed")
            task["merge_sha"] = merge_sha
            task["status"] = (
                "done" if request.get("checks_passed") is True else "verifying_main"
            )
            if task["status"] == "done" and task.get("repair_for"):
                original = result["tasks"][task["repair_for"]]
                original.update(status="done", verified_by_repair=merge_sha)
                result["paused"] = any(
                    t["status"] == "verifying_main" and t.get("integration_error")
                    for t in result["tasks"].values()
                )
        receipt.update(task_id=task_id, status=task["status"])
    else:
        task_id = _task_id(request.get("task_id"))
        task = result["tasks"].get(task_id)
        if not task:
            raise QueueError("unknown task")
        _worker(result, request, actor)
        if (
            verb == "recover"
            and task["status"] == "recovery_required"
            and not task["spec"]["resources"]
            and not task["spec"]["artifacts"]
            and not request.get("terminal_proof")
        ):
            checkpoint = request.get("checkpoint")
            if (
                not isinstance(checkpoint, dict)
                or not checkpoint.get("branch")
                or not checkpoint.get("head_sha")
                or checkpoint.get("branch") != task["claim"]["branch"]
                or request.get("epoch") != task["epoch"]
            ):
                raise QueueError(
                    "code recovery requires a preserved branch and head checkpoint"
                )
            _sha(checkpoint["head_sha"], "preserved head")
            task.setdefault("history", []).append(
                {
                    "claim": task.pop("claim"),
                    "checkpoint": copy.deepcopy(checkpoint),
                    "at": now,
                }
            )
            task.pop("review_claim", None)
            task.pop("review", None)
            task["epoch"] += 1
            task["status"] = "ready"
            task["checkpoint"] = copy.deepcopy(checkpoint)
            receipt.update(task_id=task_id, status="ready", epoch=task["epoch"])
            result["receipts"][request_id] = receipt
            return result
        review = verb == "review-result" or (
            verb == "heartbeat" and request.get("lane") == "review"
        )
        claim = _owned(
            task,
            request,
            actor,
            now,
            review=review,
            expired=verb in {"recover", "release"},
        )
        if verb == "heartbeat":
            if (not review and task["status"] != "running") or (
                review and task["status"] != "review"
            ):
                raise QueueError("lease cannot be renewed in current status")
            claim["expires_at"] = now + LEASE_SECONDS
        elif verb == "checkpoint":
            if task["status"] != "running":
                raise QueueError("checkpoint requires running work")
            checkpoint = request.get("checkpoint")
            if not isinstance(checkpoint, dict):
                raise QueueError("checkpoint must be an object")
            _json(checkpoint)
            task["checkpoint"] = copy.deepcopy(checkpoint)
            task["checkpoint_at"] = now
            claim["expires_at"] = now + LEASE_SECONDS
        elif verb == "extend-scope":
            if task["status"] != "running":
                raise QueueError("scope change requires running work")
            spec = copy.deepcopy(request.get("spec"))
            digest = spec_hash(spec)
            if any(
                spec[k] != task["spec"][k]
                for k in spec
                if k not in {"paths", "resources"}
            ):
                raise QueueError("scope expansion cannot change task semantics")
            if not set(task["spec"]["paths"]) <= set(spec["paths"]) or not set(
                task["spec"]["resources"]
            ) <= set(spec["resources"]):
                raise QueueError("scope changes may only add reservations")
            if task["spec"]["risk"] == "human":
                raise QueueError(
                    "human-approved scope requires a new explicit approval"
                )
            if _conflict(result, task_id, spec):
                raise QueueError("scope expansion conflicts with reserved work")
            task.update(spec=spec, spec_hash=digest)
            claim["spec_hash"] = digest
        elif verb == "submit":
            if task["status"] != "running":
                raise QueueError("submit requires running work")
            if request.get("spec_hash") != task["spec_hash"]:
                raise QueueError("submitted spec hash is stale")
            if type(request.get("pr_number")) is not int or request["pr_number"] <= 0:
                raise QueueError("submission requires positive integer pr_number")
            task["submission"] = {
                "head_sha": _sha(request.get("head_sha"), "head_sha"),
                "base_sha": _sha(request.get("base_sha"), "base_sha"),
                "spec_hash": task["spec_hash"],
                "pr_number": request["pr_number"],
            }
            if request.get("native_evidence") is not None:
                _json(request["native_evidence"])
                task["submission"]["native_evidence"] = copy.deepcopy(
                    request["native_evidence"]
                )
            task["pr_number"] = request["pr_number"]
            task.pop("review", None)
            task.pop("review_claim", None)
            task["status"] = "review"
        elif verb == "review-result":
            if task["status"] != "review" or any(
                request.get(k) != task["submission"][k]
                for k in ("head_sha", "base_sha", "spec_hash")
            ):
                raise QueueError("review binding is stale")
            if request.get("verdict") not in {"approve", "changes"}:
                raise QueueError("review verdict must be approve or changes")
            for field in ("findings", "reviewed_files", "limitations", "evidence"):
                _strings(
                    request.get(field),
                    field,
                    nonempty=field in {"reviewed_files", "evidence"},
                )
            for path in request["reviewed_files"]:
                _path(path)
            task["review"] = {
                **task["submission"],
                "verdict": request["verdict"],
                "actor": actor,
                "session_id": request["session_id"],
                "at": now,
                **{
                    field: copy.deepcopy(request[field])
                    for field in (
                        "findings",
                        "reviewed_files",
                        "limitations",
                        "evidence",
                    )
                },
            }
            task.pop("review_claim")
            if request["verdict"] == "changes":
                task["repair_rounds"] = task.get("repair_rounds", 0) + 1
                task["status"] = (
                    "running"
                    if task["claim"]["expires_at"] > now
                    else "recovery_required"
                )
                if task["repair_rounds"] >= 3:
                    task["status"] = "needs_human"
                    task["reason"] = (
                        "three repair rounds exhausted; reservations retained pending human recovery"
                    )
        elif verb in {"release", "recover"}:
            if task["status"] not in {
                "running",
                "review",
                "recovery_required",
                "needs_human",
            }:
                raise QueueError("task cannot release/recover in current status")
            proof = _terminal_proof(request, claim)
            task.setdefault("history", []).append(
                {
                    "claim": copy.deepcopy(claim),
                    "terminal_proof": proof,
                    "at": now,
                    "verb": verb,
                }
            )
            task.pop("claim")
            task.pop("review_claim", None)
            task.pop("review", None)
            task["status"] = (
                "needs_human" if task.get("repair_rounds", 0) >= 3 else "ready"
            )
            task["reason"] = "released after terminal proof"
        else:
            raise QueueError(f"unknown verb: {verb}")
        receipt.update(task_id=task_id, status=task["status"], epoch=task["epoch"])
    result["receipts"][request_id] = receipt
    return result
