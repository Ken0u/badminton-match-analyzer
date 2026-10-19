"""Durable GitHub coordination. All mutations use trusted checked-out code."""

import base64
import copy
import hashlib
import json
import re
from datetime import datetime, timezone

from .github import GitHubError
from .policy import policy_errors, rollout_errors

REQUEST_MARKER = "<!-- agent-request:v1 -->"
HEARTBEAT_MARKER = "<!-- agent-heartbeat:v1 -->"
TASK_MARKER = "agent-task:v1"


def json_block(body, marker):
    if marker not in (body or ""):
        return None
    match = re.search(
        r"```(?:json|agent-task:v1)\s*\n(.*?)\n```", body.split(marker, 1)[1], re.S
    )
    if not match:
        raise ValueError("Missing fenced JSON after automation marker")
    value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise ValueError("Automation payload must be an object")
    return value


class StateStore:
    def __init__(self, gh, branch):
        self.gh, self.branch = gh, branch

    def read(self):
        from .queue import initial_state

        try:
            tip = self.gh.repo(f"git/ref/heads/{self.branch}")["object"]["sha"]
        except GitHubError as exc:
            if "404" not in str(exc):
                raise
            return None, initial_state()
        commit = self.gh.repo(f"git/commits/{tip}")
        tree = self.gh.repo(f"git/trees/{commit['tree']['sha']}")
        entry = next(e for e in tree["tree"] if e["path"] == "state.json")
        blob = self.gh.repo(f"git/blobs/{entry['sha']}")
        return tip, json.loads(base64.b64decode(blob["content"]))

    def write(self, tip, state):
        # Parent/tree/state receipt commit is the transaction. No force push.
        blob = self.gh.repo(
            "git/blobs",
            method="POST",
            data={
                "content": json.dumps(state, sort_keys=True, indent=2) + "\n",
                "encoding": "utf-8",
            },
        )
        tree = self.gh.repo(
            "git/trees",
            method="POST",
            data={
                "tree": [
                    {
                        "path": "state.json",
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob["sha"],
                    }
                ]
            },
        )
        commit = self.gh.repo(
            "git/commits",
            method="POST",
            data={
                "message": "Reconcile agent ownership and receipts",
                "tree": tree["sha"],
                "parents": [tip] if tip else [],
            },
        )
        if tip:
            self.gh.repo(
                f"git/refs/heads/{self.branch}",
                method="PATCH",
                data={"sha": commit["sha"], "force": False},
            )
        else:
            self.gh.repo(
                "git/refs",
                method="POST",
                data={"ref": f"refs/heads/{self.branch}", "sha": commit["sha"]},
            )
        return commit["sha"]


def collect(gh, config):
    """Never infer authority from payload actor fields or prose."""
    requests, issues = [], {}
    for issue in gh.pages("issues?state=all&per_page=100"):
        if "pull_request" in issue:
            continue
        issues[str(issue["number"])] = issue
        actor = issue["user"]["login"]
        if actor in config["trusted_logins"] and issue["state"] == "open":
            try:
                spec = json_block(issue.get("body"), TASK_MARKER)
                if spec:
                    requests.append(
                        {
                            "request_id": f"spec-{issue['number']}-"
                            + hashlib.sha256(
                                json.dumps(spec, sort_keys=True).encode()
                            ).hexdigest(),
                            "verb": "plan",
                            "task_id": str(issue["number"]),
                            "spec": spec,
                            "actor": actor,
                            "created_at": issue["created_at"],
                        }
                    )
            except (ValueError, json.JSONDecodeError):
                pass  # Malformed plans are visible issues, never executable commands.
        for comment in gh.pages(f"issues/{issue['number']}/comments?per_page=100"):
            actor = comment["user"]["login"]
            if actor not in config["trusted_logins"]:
                continue
            try:
                heartbeat = HEARTBEAT_MARKER in (comment.get("body") or "")
                request = json_block(
                    comment.get("body"),
                    HEARTBEAT_MARKER if heartbeat else REQUEST_MARKER,
                )
                if request:
                    if heartbeat and request.get("verb") != "heartbeat":
                        continue
                    if request.get("verb") in ("integrate", "verify-main"):
                        continue
                    request.update(
                        actor=actor,
                        created_at=comment.get("updated_at", comment["created_at"])
                        if heartbeat
                        else comment["created_at"],
                        source_comment=comment["id"],
                    )
                    requests.append(request)
            except (ValueError, json.JSONDecodeError):
                pass
    return sorted(
        requests, key=lambda r: (r["created_at"], str(r.get("source_comment", "")))
    ), issues


def reconcile(gh, config, *, now=None):
    from .queue import QueueError, apply_request, expire_leases, spec_hash

    now = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    requests, issues = collect(gh, config)
    store = StateStore(gh, config["coordination_branch"])
    for attempt in range(4):
        tip, state = store.read()
        old = copy.deepcopy(state)
        # Renew existing ownership at GitHub's authenticated receipt time before
        # an hourly/delayed wakeup expires it. Payload timestamps have no authority.
        for request in requests:
            if request.get("verb") not in ("heartbeat", "checkpoint"):
                continue
            if not isinstance(request.get("request_id"), str):
                continue
            command = {
                k: v
                for k, v in request.items()
                if k not in ("actor", "created_at", "source_comment")
            }
            try:
                received = int(
                    datetime.fromisoformat(
                        request["created_at"].replace("Z", "+00:00")
                    ).timestamp()
                )
                if received <= now:
                    state = apply_request(
                        state, command, request["actor"], received, config
                    )
            except (QueueError, KeyError, TypeError, ValueError):
                pass  # Normal processing below records rejected requests.
        state = expire_leases(state, now)
        for task_id, task in state["tasks"].items():
            issue = issues.get(task_id)
            if issue and issue["state"] == "closed" and task["status"] != "done":
                if task.get("claim"):
                    if task["status"] not in ("integrating", "verifying_main"):
                        task.update(
                            status="recovery_required",
                            reason="Issue closed; preserve reservations and checkpoint before recovery",
                        )
                else:
                    task.update(
                        status="blocked",
                        reason="Issue closed by collaborator; re-plan explicitly after reopening",
                    )
        for request in requests:
            if not isinstance(request.get("request_id"), str):
                continue
            previous = state.get("receipts", {}).get(request.get("request_id"))
            if previous and previous.get("status") == "rejected":
                continue
            try:
                command = {
                    k: v
                    for k, v in request.items()
                    if k not in ("actor", "created_at", "source_comment")
                }
                if command.get("verb") == "plan":
                    existing = state["tasks"].get(command.get("task_id"), {})
                    if (
                        existing.get("claim")
                        and spec_hash(command["spec"]) != existing["spec_hash"]
                    ):
                        existing.update(
                            status="recovery_required",
                            reason="Active specification edited; preserve work and obtain a new scope grant",
                        )
                if command.get("verb") == "recover" and not command.get(
                    "terminal_proof"
                ):
                    checkpoint = command.get("checkpoint", {})
                    existing = state["tasks"].get(command.get("task_id"), {})
                    if checkpoint.get("branch") != existing.get("claim", {}).get(
                        "branch"
                    ):
                        raise QueueError(
                            "Recovery checkpoint must preserve the original granted branch"
                        )
                    try:
                        remote = gh.repo(f"git/ref/heads/{checkpoint['branch']}")[
                            "object"
                        ]["sha"]
                    except GitHubError as exc:
                        if "404" not in str(exc):
                            raise
                        raise QueueError(
                            "Recovery requires a preserved remote branch; checkpoint it first"
                        ) from exc
                    if remote != checkpoint.get("head_sha"):
                        raise QueueError(
                            "Recovery checkpoint does not match preserved remote branch"
                        )
                if (
                    command.get("verb") == "next"
                    and command.get("task_id") in issues
                    and issues[command["task_id"]]["state"] == "closed"
                ):
                    raise QueueError("Closed issue is not executable")
                state = apply_request(state, command, request["actor"], now, config)
            except (QueueError, KeyError, TypeError, ValueError) as exc:
                # A bad command cannot starve later requests. Fence its identity.
                key = request.get("request_id")
                if isinstance(key, str) and len(key) <= 160:
                    state.setdefault("receipts", {}).setdefault(
                        key,
                        {
                            "status": "rejected",
                            "reason": str(exc),
                            "actor": request["actor"],
                            "verb": request.get("verb"),
                        },
                    )
        if state == old:
            return state
        try:
            store.write(tip, state)
            return state
        except GitHubError:
            if attempt == 3:
                raise
    raise RuntimeError("Coordination update contention")


def check_run(gh, head, errors):
    gh.repo(
        "check-runs",
        method="POST",
        data={
            "name": "automation/policy",
            "head_sha": head,
            "status": "completed",
            "conclusion": "failure" if errors else "success",
            "output": {
                "title": "Automation integration policy",
                "summary": "\n".join(errors)
                if errors
                else "Current ownership, review and CI verified.",
            },
        },
    )


def conversation_errors(gh, config, number):
    """Inspect every review thread, including outdated unresolved discussions."""
    owner, repo = config["repository"].split("/", 1)
    cursor = None
    while True:
        data = gh.graphql(
            """query($owner:String!, $repo:String!, $number:Int!, $cursor:String) {
              repository(owner:$owner, name:$repo) {
                pullRequest(number:$number) {
                  reviewThreads(first:100, after:$cursor) {
                    nodes { isResolved }
                    pageInfo { hasNextPage endCursor }
                  }
                }
              }
            }""",
            owner=owner,
            repo=repo,
            number=int(number),
            cursor=cursor,
        )
        threads = data["repository"]["pullRequest"]["reviewThreads"]
        if any(thread["isResolved"] is not True for thread in threads["nodes"]):
            return ["Resolve all PR review conversations before integration"]
        page = threads["pageInfo"]
        if page["hasNextPage"] is False:
            return []
        if not page["endCursor"] or page["endCursor"] == cursor:
            raise ValueError("Review-thread pagination did not advance")
        cursor = page["endCursor"]


def evaluate_pr(gh, config, task, main):
    pr = gh.repo(f"pulls/{task['pr_number']}")
    changed = gh.pages(f"pulls/{task['pr_number']}/files?per_page=100")
    # Renames must reserve both old and new paths.
    files = [f["filename"] for f in changed] + [
        f["previous_filename"] for f in changed if f.get("previous_filename")
    ]
    checks = [
        c
        for page in gh.repo(
            f"commits/{pr['head']['sha']}/check-runs?per_page=100", paginate=True
        )
        for c in page["check_runs"]
    ]
    reviews = gh.pages(f"pulls/{task['pr_number']}/reviews?per_page=100")
    errors = policy_errors(task, pr, files, checks, reviews, config, main)
    comparison = gh.repo(f"compare/{main}...{pr['head']['sha']}")
    if (
        comparison.get("status") not in ("ahead", "identical")
        or comparison.get("merge_base_commit", {}).get("sha") != main
    ):
        errors.append(
            "Update the PR branch to include current main, then rerun CI and review"
        )
    errors += conversation_errors(gh, config, task["pr_number"])
    return pr, errors


def rollout_policy(gh, config):
    """Publish a narrow activation check from trusted main; never merge here."""
    main = gh.repo("git/ref/heads/main")["object"]["sha"]
    for item in gh.pages("pulls?state=open&base=main&per_page=100"):
        number = item["number"]
        changed = gh.pages(f"pulls/{number}/files?per_page=100")
        if len(changed) != 1 or changed[0].get("filename") != ".github/automation.json":
            continue
        pr = gh.repo(f"pulls/{number}")
        try:
            blob = gh.repo(f"git/blobs/{changed[0]['sha']}")
            proposed = json.loads(base64.b64decode(blob["content"]))
        except (ValueError, KeyError):
            proposed = None
        checks = [
            check
            for page in gh.repo(
                f"commits/{pr['head']['sha']}/check-runs?per_page=100", paginate=True
            )
            for check in page["check_runs"]
        ]
        reviews = gh.pages(f"pulls/{number}/reviews?per_page=100")
        check_run(
            gh,
            pr["head"]["sha"],
            rollout_errors(pr, changed, proposed, checks, reviews, config, main)
            + conversation_errors(gh, config, number),
        )


def protections_present(gh):
    protection = gh.repo("branches/main/protection")
    checks = protection.get("required_status_checks") or {}
    names = set(checks.get("contexts", [])) | {
        c["context"] for c in checks.get("checks", [])
    }
    return (
        checks.get("strict") is True
        and {"ci/gate", "automation/policy"} <= names
        and protection.get("required_pull_request_reviews") is not None
        and protection.get("enforce_admins", {}).get("enabled") is True
        and not protection.get("allow_force_pushes", {}).get("enabled", False)
        and not protection.get("allow_deletions", {}).get("enabled", False)
    )


def failure_issue(gh, source, run_url, kind):
    """One actionable incident per failed source, safe to repeat after a crash."""
    marker = f"<!-- agent-incident:{kind}:{source} -->"
    for issue in gh.pages("issues?state=all&per_page=100"):
        if marker in (issue.get("body") or ""):
            return issue["number"]
    issue = gh.repo(
        "issues",
        method="POST",
        data={
            "title": f"Repair {kind} verification for {source[:12]}",
            "body": f"{marker}\n\nVerification failed: {run_url}\n\nPreserve the failed artifacts and inspect the exact source commit `{source}`. "
            "Implementation claims/integration pause on main failures. Prepare a bounded repair or revert; never relax checks or restart research jobs. "
            "Owner intervention is required if protected policy needs changing.",
        },
    )
    return issue["number"]


def deliver(gh, store, state, task_id, source):
    """Keep the outbox pending until the complete package/image workflow succeeds."""
    runs = gh.repo("actions/workflows/release.yml/runs?per_page=100")["workflow_runs"]
    matching = [
        r for r in runs if r.get("display_title") == f"Private candidate {source}"
    ]
    latest = max(matching, key=lambda r: r["id"]) if matching else {}
    tip, current = store.read()
    task = current["tasks"][task_id]
    if latest.get("conclusion") == "success":
        task.update(delivery_pending=False, candidate_run=latest["html_url"])
        store.write(tip, current)
        return current
    if latest.get("status") in (
        "queued",
        "in_progress",
        "waiting",
        "pending",
        "requested",
    ):
        return state
    attempts = task.get("delivery_attempts", 0)
    if attempts >= 3:
        task["delivery_error"] = "Private publishing failed after three attempts"
        store.write(tip, current)
        failure_issue(
            gh, source, latest.get("html_url", "GitHub Actions"), "private-candidate"
        )
        return current
    task["delivery_attempts"] = attempts + 1
    store.write(tip, current)
    if latest:
        gh.repo(
            f"actions/runs/{latest['id']}/rerun-failed-jobs", method="POST", data={}
        )
    else:
        gh.repo(
            "actions/workflows/release.yml/dispatches",
            method="POST",
            data={"ref": "main", "inputs": {"source_sha": source}},
        )
    return current


def integrate(gh, config, state):
    """Serial external side effects, journalled before merging and replay-safe."""
    from .queue import apply_request

    store = StateStore(gh, config["coordination_branch"])
    if config["mode"] == "observation":
        return state
    enforcement = config.get("integration_enforcement", "controller")
    if enforcement not in ("controller", "github"):
        raise ValueError("Unknown integration enforcement; integration disabled")
    # GitHub Free uses controller policy. Optional server enforcement must never
    # silently downgrade when protections disappear or their API is unavailable.
    if enforcement == "github" and not protections_present(gh):
        raise ValueError("Required branch protections are absent; integration disabled")
    main = gh.repo("git/ref/heads/main")["object"]["sha"]
    # Delivery is an independent outbox. Failed/exhausted publication cannot
    # occupy the serial merge lane or starve later eligible implementation.
    for task_id, task in list(state.get("tasks", {}).items()):
        if (
            task.get("status") == "done"
            and task.get("delivery_pending")
            and not task.get("delivery_error")
        ):
            state = deliver(gh, store, state, task_id, task["merge_sha"])
    tasks = state.get("tasks", {})
    for task_id, task in tasks.items():
        task["task_id"] = task_id
    active = [
        t
        for t in tasks.values()
        if t.get("status") in ("integrating", "merging", "verifying_main")
    ]
    repair_reviews = [
        t for t in tasks.values() if t.get("repair_for") and t["status"] == "review"
    ]
    inflight = [
        t for t in active if t["status"] == "integrating" or t.get("repair_for")
    ]
    candidates = (
        repair_reviews
        or inflight
        or active
        or [
            t
            for t in tasks.values()
            if t.get("pr_number") and t.get("status") in ("review", "merge_ready")
        ]
    )
    if state.get("paused") and not active:
        return state
    for task in sorted(candidates, key=lambda t: str(t["task_id"])):
        pr = gh.repo(f"pulls/{task['pr_number']}")
        if pr.get("merged"):
            merged = pr["merge_commit_sha"]
            runs = gh.repo("actions/workflows/ci.yml/runs?per_page=100")[
                "workflow_runs"
            ]
            valid = [
                r
                for r in runs
                if (r.get("event") == "push" and r["head_sha"] == merged)
                or (
                    r.get("event") == "workflow_dispatch"
                    and r.get("display_title") == f"Verify {merged}"
                )
            ]
            latest = max(valid, key=lambda r: r["id"]) if valid else {}
            success = latest.get("conclusion") == "success"
            failed = latest.get("conclusion") in (
                "failure",
                "timed_out",
                "cancelled",
                "skipped",
                "action_required",
            )
            tip, current = store.read()
            target = current["tasks"][str(task["task_id"])]
            if target["status"] != "done":
                current = apply_request(
                    current,
                    {
                        "request_id": f"verify-{task['task_id']}-{merged}-{success}",
                        "verb": "verify-main",
                        "task_id": task["task_id"],
                        "merge_sha": merged,
                        "checks_passed": success,
                    },
                    config["coordinator_login"],
                    int(datetime.now(timezone.utc).timestamp()),
                    config,
                )
            target = current["tasks"][task["task_id"]]
            if success:
                target["delivery_pending"] = True
            if failed and not success:
                current["paused"] = True
                target["integration_error"] = (
                    "Merged main verification failed; repair required"
                )
            store.write(tip, current)
            if failed:
                if task.get("repair_for"):
                    failure_issue(
                        gh,
                        merged,
                        latest.get("html_url", "GitHub Actions"),
                        "repair-main",
                    )
                    return current
                repair_id = str(
                    failure_issue(
                        gh, merged, latest.get("html_url", "GitHub Actions"), "main"
                    )
                )
                repair_tip, repair_state = store.read()
                if repair_id not in repair_state["tasks"]:
                    repair_spec = copy.deepcopy(task["spec"])
                    repair_spec.update(
                        outcome=f"Repair main verification for {merged[:12]}",
                        paths=list(dict.fromkeys([*task["spec"]["paths"], "tests/"])),
                        capabilities=["cpu"],
                        artifacts={},
                        resources=[],
                        dependencies=[],
                        priority=0,
                        milestone="Infrastructure",
                        risk="routine",
                    )
                    repair_state = apply_request(
                        repair_state,
                        {
                            "request_id": f"repair-{merged}",
                            "verb": "repair",
                            "task_id": repair_id,
                            "repair_for": task["task_id"],
                            "spec": repair_spec,
                        },
                        config["coordinator_login"],
                        int(datetime.now(timezone.utc).timestamp()),
                        config,
                    )
                    store.write(repair_tip, repair_state)
                return repair_state
            if not valid:
                gh.repo(
                    "actions/workflows/ci.yml/dispatches",
                    method="POST",
                    data={"ref": "main", "inputs": {"verify_sha": merged}},
                )
            if success:
                gh.repo(
                    f"issues/{task['task_id']}",
                    method="PATCH",
                    data={"state": "closed"},
                )
                return deliver(gh, store, current, task["task_id"], merged)
            return current
        submission = task.get("submission", {})
        if any(
            submission.get(key) != value
            for key, value in (("head_sha", pr["head"]["sha"]), ("base_sha", main))
        ):
            tip, current = store.read()
            current = apply_request(
                current,
                {
                    "request_id": f"invalidate-{task['task_id']}-{pr['head']['sha']}-{main}",
                    "verb": "invalidate-review",
                    "task_id": task["task_id"],
                },
                config["coordinator_login"],
                int(datetime.now(timezone.utc).timestamp()),
                config,
            )
            current["tasks"][task["task_id"]]["reason"] = (
                "Update branch against current main, run checks, then resubmit for a fresh review"
            )
            store.write(tip, current)
            return current
        pr, errors = evaluate_pr(gh, config, task, main)
        check_run(gh, pr["head"]["sha"], errors)
        if errors:
            continue
        # A branch update/main race invalidates both evidence and the merge request.
        if gh.repo("git/ref/heads/main")["object"]["sha"] != main:
            return state
        tip, current = store.read()
        target = current["tasks"][str(task["task_id"])]
        current = apply_request(
            current,
            {
                "request_id": f"integrate-{task['task_id']}-{pr['head']['sha']}-{main}",
                "verb": "integrate",
                "task_id": task["task_id"],
                "head_sha": pr["head"]["sha"],
                "base_sha": main,
                "spec_hash": task["spec_hash"],
                "checks_passed": True,
            },
            config["coordinator_login"],
            int(datetime.now(timezone.utc).timestamp()),
            config,
        )
        store.write(tip, current)
        # Revalidate after journalling too: no protected-branch requirement exists
        # in controller mode. External writers still must honor the protocol.
        target = current["tasks"][str(task["task_id"])]
        target["task_id"] = task["task_id"]
        pr, errors = evaluate_pr(gh, config, target, main)
        if errors or gh.repo("git/ref/heads/main")["object"]["sha"] != main:
            check_run(
                gh,
                pr["head"]["sha"],
                errors or ["Main advanced; refresh integration evidence"],
            )
            return current
        gh.repo(
            f"pulls/{task['pr_number']}/merge",
            method="PUT",
            data={"sha": pr["head"]["sha"], "merge_method": "squash"},
        )
        return current
    return state
