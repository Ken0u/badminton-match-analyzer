"""Bounded completion observations. A wake is never a verification verdict."""

import copy
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from .coordinator import StateStore
from .github import GitHub, GitHubError
from .policy import sensitive_scope
from .queue import scope_authorized, spec_hash

OBSERVER = "completion-observer.yml"
CONTROLLER = "agent-queue.yml"
WORKFLOWS = {"main": "ci.yml", "delivery": "release.yml"}
ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}
CONCLUSIONS = {
    "success",
    "failure",
    "cancelled",
    "timed_out",
    "action_required",
    "neutral",
    "skipped",
    "stale",
    "startup_failure",
}
MAX_SECONDS = 90 * 60
POLL_SECONDS = 30
MAX_TARGETS = 16


class CompletionGitHub(GitHub):
    """Time-bound transport with a command-specific dispatch allowlist."""

    def __init__(self, repository, command):
        super().__init__(repository)
        if command not in {"launch", "observe"}:
            raise ValueError("Unknown completion command")
        self.destination = OBSERVER if command == "launch" else CONTROLLER
        self.deadline = time.monotonic() + (120 if command == "launch" else MAX_SECONDS)

    def api(self, path, *, method="GET", data=None, paginate=False):
        prefix = f"repos/{self.repository}/"
        if paginate or not path.startswith(prefix):
            raise ValueError("Unexpected completion transport request")
        relative = path[len(prefix) :]
        if method == "POST":
            if (
                relative != f"actions/workflows/{self.destination}/dispatches"
                or not isinstance(data, dict)
                or data.get("ref") != "main"
            ):
                raise ValueError("Completion transport cannot perform this mutation")
        elif method != "GET" or not relative.startswith(
            ("git/", "compare/", "pulls/", "actions/workflows/", "actions/runs/")
        ):
            raise ValueError("Unexpected completion transport operation")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Completion transport deadline reached")
        args = ["gh", "api", path, "--method", method]
        if data is not None:
            args += ["--input", "-"]
        try:
            result = subprocess.run(
                args,
                input=json.dumps(data) if data is not None else None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=min(20, remaining),
            )
        except subprocess.TimeoutExpired:
            raise TimeoutError("Completion request outcome is unknown") from None
        if result.returncode:
            raise GitHubError("Completion GitHub request failed; outcome unknown")
        return json.loads(result.stdout) if result.stdout.strip() else None


def sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Invalid immutable revision")
    return value


def integer(value, minimum=1, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid bounded integer")
    return value


def identity(task_id, task, config):
    """Only ordinary, journalled tasks; external recovery stays with its controller."""
    if not isinstance(task_id, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", task_id):
        raise ValueError("Invalid task identifier")
    if task.get("external_recovery_request") or task.get("verified_by_repair"):
        raise ValueError("Recovery tasks require the existing recovery path")
    if task.get("status") == "verifying_main" and not task.get("integration_error"):
        stage, attempt = "main", 0
    elif task.get("status") == "done" and task.get("delivery_pending") is True:
        stage = "delivery"
        attempt = integer(task.get("delivery_attempts"), maximum=3)
        if task.get("delivery_error"):
            raise ValueError("Exhausted delivery is not an observation target")
    else:
        raise ValueError("Task no longer needs observation")
    epoch = integer(task.get("epoch"))
    source = sha(task.get("merge_sha"))
    submission, journal, claim = (
        task.get("submission", {}),
        task.get("integration", {}),
        task.get("claim", {}),
    )
    digest = spec_hash(task["spec"])
    if (
        task.get("spec_hash") != digest
        or submission.get("spec_hash") != digest
        or claim.get("spec_hash") != digest
        or claim.get("epoch") != epoch
        or submission.get("pr_number") != task.get("pr_number")
        or (
            (
                task["spec"]["risk"] == "human"
                or sensitive_scope(task["spec"]["paths"], config)
            )
            and not scope_authorized(task, config)
        )
    ):
        raise ValueError("Task evidence does not bind the frozen grant")
    for key in ("head_sha", "base_sha"):
        if sha(submission.get(key)) != journal.get(key):
            raise ValueError("Missing or mismatched integration journal")
    integer(journal.get("at"))
    integer(task.get("pr_number"))
    return {
        "task_id": task_id,
        "epoch": epoch,
        "stage": stage,
        "source_sha": source,
        "attempt": attempt,
        "spec_hash": digest,
        "submission": copy.deepcopy(submission),
        "integration": copy.deepcopy(journal),
        "ownership": {
            k: claim.get(k)
            for k in ("actor", "host_id", "session_id", "epoch", "branch", "spec_hash")
        },
    }


def title(binding):
    return "Observe {task_id}/{epoch}/{stage}/{source_sha}/{attempt}".format(**binding)


def workflow(gh, name):
    value = gh.repo(f"actions/workflows/{name}")
    integer(value.get("id"))
    if (
        value.get("path") != f".github/workflows/{name}"
        or value.get("state") != "active"
    ):
        raise ValueError("Unexpected or inactive workflow")
    return value


def validate_run(run, meta, repository):
    integer(run.get("id"))
    integer(run.get("run_attempt"))
    sha(run.get("head_sha"))
    if (
        run.get("workflow_id") != meta["id"]
        or run.get("path") != meta["path"]
        or run.get("head_branch") != "main"
        or run.get("repository", {}).get("full_name") != repository
        or run.get("head_repository", {}).get("full_name") != repository
        or run.get("status") not in ACTIVE | {"completed"}
        or (run["status"] == "completed" and run.get("conclusion") not in CONCLUSIONS)
        or (run["status"] in ACTIVE and run.get("conclusion") is not None)
    ):
        raise ValueError("Unexpected workflow run identity or state")
    return run


def runs_since(gh, name, since=None, *, status=None):
    """Bound complete listings; unknown/truncated data cannot authorize dispatch."""
    filters = {}
    if since is not None:
        filters["created"] = ">=" + datetime.fromtimestamp(
            integer(since), timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    if status is not None:
        filters["status"] = status
    rows, ids = [], set()
    for page in range(1, 11):
        query = urlencode({"per_page": 100, "page": page, **filters})
        result = gh.repo(f"actions/workflows/{name}/runs?{query}")
        total = integer(result.get("total_count"), minimum=0, maximum=1000)
        batch = result.get("workflow_runs")
        if not isinstance(batch, list) or len(batch) > 100:
            raise ValueError("Malformed workflow listing")
        for run in batch:
            run_id = integer(run.get("id"))
            if run_id in ids:
                raise ValueError("Unstable workflow listing")
            ids.add(run_id)
        rows.extend(batch)
        if len(rows) == total:
            return rows
        if len(batch) < 100 or len(rows) > total:
            raise ValueError("Incomplete workflow listing")
    raise ValueError("Workflow listing exceeds observation bound")


def current_binding(gh, store, expected, config):
    _, state = store.read()
    if config.get("mode") not in {"active", "pilot"}:
        return False
    try:
        actual = identity(
            expected["task_id"], state["tasks"][expected["task_id"]], config
        )
    except (KeyError, TypeError, ValueError):
        return False
    if actual != expected:
        return False
    submission = expected["submission"]
    pr = gh.repo(f"pulls/{submission['pr_number']}")
    if (
        pr.get("number") != submission["pr_number"]
        or pr.get("merged") is not True
        or pr.get("merge_commit_sha") != expected["source_sha"]
        or pr.get("head", {}).get("sha") != submission["head_sha"]
        or pr.get("head", {}).get("repo", {}).get("full_name") != config["repository"]
        or pr.get("base", {}).get("sha") != submission["base_sha"]
        or pr.get("base", {}).get("ref") != "main"
    ):
        return False
    main = sha(gh.repo("git/ref/heads/main")["object"]["sha"])
    comparison = gh.repo(f"compare/{expected['source_sha']}...{main}")
    return (
        comparison.get("status") in {"ahead", "identical"}
        and comparison.get("merge_base_commit", {}).get("sha") == expected["source_sha"]
    )


def launch(gh, config):
    """Serialized trusted controller step, without modifying coordination."""
    if config.get("mode") not in {"active", "pilot"}:
        return {"outcome": "disabled"}
    store = StateStore(gh, config["coordination_branch"])
    revision, state = store.read()
    candidates, skipped = [], []
    for task_id, task in state["tasks"].items():
        if task.get("status") != "verifying_main" and not (
            task.get("status") == "done" and task.get("delivery_pending") is True
        ):
            continue
        try:
            candidates.append(identity(task_id, task, config))
        except (KeyError, TypeError, ValueError):
            skipped.append(task_id)
    if not candidates:
        return {"outcome": "idle", "unsupported_tasks": skipped}
    if len(candidates) > MAX_TARGETS:
        raise ValueError("Too many completion targets")
    meta = workflow(gh, OBSERVER)
    existing = runs_since(gh, OBSERVER, min(b["integration"]["at"] for b in candidates))
    results = []
    for binding in candidates:
        matching = [r for r in existing if r.get("display_title") == title(binding)]
        if matching:
            for run in matching:
                validate_run(run, meta, config["repository"])
                if run.get("event") != "workflow_dispatch":
                    raise ValueError("Unexpected observer event")
            results.append({"task_id": binding["task_id"], "outcome": "reused"})
            continue
        if not current_binding(gh, store, binding, config):
            results.append({"task_id": binding["task_id"], "outcome": "stale"})
            continue
        inputs = {
            k: str(binding[k])
            for k in ("task_id", "epoch", "stage", "source_sha", "attempt")
        }
        inputs["coordination_sha"] = sha(revision)
        # No automatic retry, even when the dispatch response is lost.
        gh.repo(
            f"actions/workflows/{OBSERVER}/dispatches",
            method="POST",
            data={"ref": "main", "inputs": inputs},
        )
        results.append({"task_id": binding["task_id"], "outcome": "dispatched"})
    return {"outcome": "launched", "targets": results, "unsupported_tasks": skipped}


def matches(run, binding):
    source = binding["source_sha"]
    if binding["stage"] == "delivery":
        return run.get("display_title") == f"Private candidate {source}"
    return (run.get("event") == "push" and run.get("head_sha") == source) or run.get(
        "display_title"
    ) == f"Verify {source}"


def validate_target(run, binding, meta, config):
    validate_run(run, meta, config["repository"])
    if (
        not matches(run, binding)
        or (binding["stage"] == "delivery" and run.get("event") != "workflow_dispatch")
        or (
            binding["stage"] == "main"
            and run.get("event") not in {"push", "workflow_dispatch"}
        )
        or (
            binding["stage"] == "main"
            and run["event"] == "push"
            and run["head_sha"] != binding["source_sha"]
        )
    ):
        raise ValueError("Run does not match the exact observation target")
    return run


def controller_active(gh, meta, config):
    # Include the originating controller: its run predates integration.at.
    # PR-target controller runs can name the PR branch while checking out main.
    for status in sorted(ACTIVE):
        runs = runs_since(gh, CONTROLLER, status=status)
        for run in runs:
            integer(run.get("id"))
            if (
                run.get("workflow_id") != meta["id"]
                or run.get("path") != meta["path"]
                or run.get("repository", {}).get("full_name") != config["repository"]
                or run.get("status") not in ACTIVE | {"completed"}
            ):
                raise ValueError("Uncertain controller lifetime")
            if run["status"] in ACTIVE:
                return True
    return False


def observe(gh, config, inputs, *, monotonic=time.monotonic, sleep=time.sleep):
    """Poll one source, then dispatch the unchanged controller at most once."""
    if set(inputs) != {
        "task_id",
        "epoch",
        "stage",
        "source_sha",
        "attempt",
        "coordination_sha",
    }:
        raise ValueError("Unexpected observer inputs")
    revision = sha(inputs["coordination_sha"])
    for key in ("epoch", "attempt"):
        if not isinstance(inputs[key], str) or not re.fullmatch(
            r"0|[1-9][0-9]{0,9}", inputs[key]
        ):
            raise ValueError("Invalid observation input")
    sha(inputs["source_sha"])
    store = StateStore(gh, config["coordination_branch"])
    original = store.read_at(revision)
    binding = identity(inputs["task_id"], original["tasks"][inputs["task_id"]], config)
    if any(
        str(binding[k]) != inputs[k]
        for k in ("epoch", "attempt", "stage", "source_sha")
    ):
        raise ValueError("Inputs differ from immutable task evidence")
    if not current_binding(gh, store, binding, config):
        return {"outcome": "stale"}
    name = WORKFLOWS[binding["stage"]]
    meta, controller = workflow(gh, name), workflow(gh, CONTROLLER)
    deadline = monotonic() + MAX_SECONDS
    selected, selected_attempt = None, None
    while monotonic() < deadline:
        if selected is None:
            runs = runs_since(gh, name, binding["integration"]["at"])
            matching = [r for r in runs if matches(r, binding)]
            for run in matching:
                validate_target(run, binding, meta, config)
            if matching:
                selected = max(matching, key=lambda r: r["id"])["id"]
                selected_attempt = next(
                    r["run_attempt"] for r in matching if r["id"] == selected
                )
        if selected is not None:
            run = validate_target(
                gh.repo(f"actions/runs/{selected}"), binding, meta, config
            )
            if run["id"] != selected or run["run_attempt"] != selected_attempt:
                raise ValueError("Selected run or attempt changed")
            if run["status"] == "completed":
                if not current_binding(gh, store, binding, config):
                    return {"outcome": "stale", "run_id": selected}
                if not controller_active(gh, controller, config):
                    # Re-read terminal status and source-bound state after the
                    # controller wait. The controller itself evaluates success.
                    final = validate_target(
                        gh.repo(f"actions/runs/{selected}"), binding, meta, config
                    )
                    if any(
                        final.get(k) != run.get(k)
                        for k in (
                            "id",
                            "run_attempt",
                            "head_sha",
                            "event",
                            "display_title",
                            "workflow_id",
                            "path",
                            "head_branch",
                            "status",
                            "conclusion",
                        )
                    ):
                        raise ValueError("Terminal observation changed")
                    if not current_binding(gh, store, binding, config):
                        return {"outcome": "stale", "run_id": selected}
                    if monotonic() >= deadline:
                        break
                    gh.repo(
                        f"actions/workflows/{CONTROLLER}/dispatches",
                        method="POST",
                        data={"ref": "main"},
                    )
                    return {
                        "outcome": "controller_dispatched",
                        "run_id": selected,
                        "run_attempt": selected_attempt,
                        "observed_conclusion": run["conclusion"],
                        "source_sha": binding["source_sha"],
                        "stage": binding["stage"],
                    }
        sleep(min(POLL_SECONDS, max(0, deadline - monotonic())))
    return {
        "outcome": "timeout_unknown",
        "run_id": selected,
        "verification_accepted": False,
    }
