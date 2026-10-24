"""Durable GitHub coordination. All mutations use trusted checked-out code."""

import base64
import copy
import hashlib
import json
import re
from datetime import datetime, timezone

from .github import GitHubError
from .policy import (
    external_recovery_errors,
    policy_errors,
    rollout_errors,
    sensitive_scope,
)

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
        return tip, self._read_commit(tip)

    def _read_commit(self, revision):
        commit = self.gh.repo(f"git/commits/{revision}")
        tree = self.gh.repo(f"git/trees/{commit['tree']['sha']}")
        entry = next(e for e in tree["tree"] if e["path"] == "state.json")
        blob = self.gh.repo(f"git/blobs/{entry['sha']}")
        return json.loads(base64.b64decode(blob["content"]))

    def read_at(self, revision):
        """Read only immutable evidence already in the controller's history."""
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Recovery evidence requires an immutable coordination SHA")
        tip = self.gh.repo(f"git/ref/heads/{self.branch}")["object"]["sha"]
        comparison = self.gh.repo(f"compare/{revision}...{tip}")
        if (
            comparison.get("status") not in {"ahead", "identical"}
            or comparison.get("merge_base_commit", {}).get("sha") != revision
        ):
            raise ValueError(
                "Recovery evidence is outside trusted coordination history"
            )
        return self._read_commit(revision)

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
    from .queue import (
        QueueError,
        apply_request,
        expire_leases,
        request_fingerprint,
        spec_hash,
    )

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
                # Accepted requests have already performed their adapter work.
                # Authenticate actor and complete payload before any plan fence
                # or recovery lookup; replay cannot reinterpret advanced state.
                request_fingerprint(command, request["actor"], config)
                if previous:
                    state = apply_request(state, command, request["actor"], now, config)
                    continue
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
        if task.get("delivery_error"):
            task["delivery_recovered_from"] = task.pop("delivery_error")
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


def verified_external_recovery(gh, config, store, task_id, task, main):
    """Verify original accepted evidence; never trust a caller's verdict fields."""
    from .queue import spec_hash

    request = task["external_recovery_request"]
    original = store.read_at(request["evidence_state_sha"])["tasks"][task_id]
    binding = original.get("submission", {})
    if (
        original.get("spec_hash") != task.get("spec_hash")
        or spec_hash(original["spec"]) != task["spec_hash"]
        or any(
            binding.get(key) != request.get(key)
            for key in ("head_sha", "base_sha", "spec_hash", "pr_number")
        )
        or original.get("pr_number") != request["pr_number"]
        or original.get("claim", {}).get("spec_hash") != task["spec_hash"]
        or original.get("claim", {}).get("epoch") != original.get("epoch")
        or original.get("review", {}).get("actor") not in config["trusted_logins"]
    ):
        raise ValueError("Original accepted task evidence does not match recovery")
    if task.get("claim") and any(
        task["claim"].get(key) != original["claim"].get(key)
        for key in ("actor", "host_id", "session_id", "epoch", "branch", "spec_hash")
    ):
        raise ValueError("Another ownership epoch retains this task's reservations")
    pr = gh.repo(f"pulls/{request['pr_number']}")
    if pr.get("merge_commit_sha") != request["merge_sha"]:
        raise ValueError("Actual merged source does not match recovery")
    files = gh.pages(f"pulls/{request['pr_number']}/files?per_page=100")
    paths = [item["filename"] for item in files] + [
        item["previous_filename"] for item in files if item.get("previous_filename")
    ]
    checks = [
        check
        for page in gh.repo(
            f"commits/{request['head_sha']}/check-runs?per_page=100", paginate=True
        )
        for check in page["check_runs"]
    ]
    reviews = gh.pages(f"pulls/{request['pr_number']}/reviews?per_page=100")
    errors = external_recovery_errors(
        {**original, "task_id": task_id}, pr, paths, checks, reviews, config, request
    )
    errors += conversation_errors(gh, config, request["pr_number"])
    if errors:
        raise ValueError("; ".join(errors))
    remote = gh.repo(f"git/ref/heads/{original['claim']['branch']}")["object"]["sha"]
    if remote != request["head_sha"]:
        raise ValueError(
            "Original granted branch is not preserved at the reviewed head"
        )
    head = gh.repo(f"git/commits/{request['head_sha']}")
    merged = gh.repo(f"git/commits/{request['merge_sha']}")
    tree = head.get("tree", {}).get("sha")
    if (
        not isinstance(tree, str)
        or not re.fullmatch(r"[0-9a-f]{40}", tree)
        or tree != merged.get("tree", {}).get("sha")
    ):
        raise ValueError("Merged tree differs from the independently reviewed source")
    for start, end in (
        (request["base_sha"], request["head_sha"]),
        (request["merge_sha"], main),
    ):
        comparison = gh.repo(f"compare/{start}...{end}")
        if (
            comparison.get("status") not in {"ahead", "identical"}
            or comparison.get("merge_base_commit", {}).get("sha") != start
        ):
            raise ValueError("Recovery source is not in the verified main lineage")
    runs = gh.repo("actions/workflows/ci.yml/runs?per_page=100")["workflow_runs"]
    matching = [
        run
        for run in runs
        if run.get("head_branch") == "main"
        and (
            (run.get("event") == "push" and run.get("head_sha") == request["merge_sha"])
            or (
                run.get("event") == "workflow_dispatch"
                and run.get("display_title") == f"Verify {request['merge_sha']}"
            )
        )
    ]
    latest = max(matching, key=lambda run: run["id"]) if matching else {}
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ValueError(
            "Successful complete exact merged-main verification is required"
        )
    if gh.repo("git/ref/heads/main")["object"]["sha"] != main:
        raise ValueError("Main advanced during external recovery verification")
    return {
        **{
            key: request[key]
            for key in (
                "evidence_state_sha",
                "head_sha",
                "base_sha",
                "merge_sha",
                "spec_hash",
                "pr_number",
            )
        },
        "verification_complete": True,
        "original_task": copy.deepcopy(original),
        "source_epoch": original["epoch"],
        "tree_sha": tree,
        "main_sha_at_verification": main,
        "verification_run": {
            key: latest.get(key)
            for key in ("id", "event", "head_sha", "display_title", "html_url")
        },
        "merged_by": (pr.get("merged_by") or {}).get("login"),
        "review_evidence": {
            "github_reviews": [
                {
                    "id": review.get("id"),
                    "reviewer": review.get("user", {}).get("login"),
                    "state": review.get("state"),
                    "commit_id": review.get("commit_id"),
                }
                for review in reviews
            ],
            "owner_attestation": copy.deepcopy(request.get("human_review_attestation")),
            "authorized_by": request["actor"],
        },
    }


def external_merge_incident(gh, store, state, task_id):
    """Retry a lost issue response without losing the already durable fence."""
    observation = state["tasks"][task_id].get("external_merge", {})
    if not observation or observation.get("incident_issue"):
        return state
    merged = observation.get("observed", {}).get("merge_sha")
    if not isinstance(merged, str) or not re.fullmatch(r"[0-9a-f]{40}", merged):
        return state
    try:
        number = failure_issue(
            gh,
            merged,
            observation["observed"].get("pr_url")
            or "Preserved external-merge observations in coordination history",
            "external-merge",
        )
        tip, current = store.read()
        current["tasks"][task_id]["external_merge"]["incident_issue"] = number
        store.write(tip, current)
        return current
    except GitHubError:
        # Keep the fence and retry on the next normal pass; no merge is authorized.
        return state


def close_recovered_issue(gh, store, state, task_id):
    """Retry issue projection separately from accepted evidence and delivery."""
    if (
        state["tasks"][task_id]["external_recovery_request"].get("issue_closed_at")
        is not None
    ):
        return state
    try:
        gh.repo(
            f"issues/{task_id}",
            method="PATCH",
            data={"state": "closed", "state_reason": "completed"},
        )
    except GitHubError:
        return state
    tip, current = store.read()
    current["tasks"][task_id]["external_recovery_request"]["issue_closed_at"] = int(
        datetime.now(timezone.utc).timestamp()
    )
    store.write(tip, current)
    return current


def recover_external_merges(gh, config, store, state, main):
    """One fenced incident cannot starve unrelated serial integration."""
    from .queue import QueueError, apply_request

    for task_id, task in list(state.get("tasks", {}).items()):
        authorization = task.get("external_recovery_request", {})
        if not authorization:
            continue
        if authorization.get("completed_at") is not None:
            if task["status"] == "done":
                state = close_recovered_issue(gh, store, state, task_id)
            continue
        if task["status"] not in {"blocked", "recovery_required", "needs_human"}:
            continue
        try:
            verified = verified_external_recovery(
                gh, config, store, task_id, task, main
            )
            tip, current = store.read()
            current = apply_request(
                current,
                {
                    "request_id": "adopt-"
                    + hashlib.sha256(authorization["request_id"].encode()).hexdigest(),
                    "verb": "adopt-external-merge",
                    "task_id": task_id,
                    "authorization_id": authorization["request_id"],
                    "verified": verified,
                },
                config["coordinator_login"],
                int(datetime.now(timezone.utc).timestamp()),
                config,
            )
            if gh.repo("git/ref/heads/main")["object"]["sha"] != main:
                raise ValueError("Main advanced before external recovery was recorded")
            store.write(tip, current)
        except (GitHubError, KeyError, TypeError, ValueError, QueueError) as error:
            reason = (
                "GitHub recovery evidence is unavailable"
                if isinstance(error, (GitHubError, KeyError, TypeError))
                else str(error)
            )
            tip, current = store.read()
            target = current["tasks"][task_id]
            if (
                target.get("external_recovery_request", {}).get("completed_at")
                is not None
            ):
                state = current
                continue
            if target.get("external_recovery_error") != reason:
                target["external_recovery_error"] = reason
                store.write(tip, current)
            state = current
            continue
        # The common integration outbox owns publication, once per pass.
        state = close_recovered_issue(gh, store, current, task_id)
    return state


def follow_merged_pr(gh, config, store, task, response):
    """One confirmation-only pass; the merge response is never adoption evidence."""
    if not isinstance(response, dict) or response.get("merged") is not True:
        return store.read()[1]
    merged = response.get("sha")
    if not isinstance(merged, str) or not re.fullmatch(r"[0-9a-f]{40}", merged):
        return store.read()[1]
    # Re-read trusted state rather than replaying the pre-merge snapshot. Any
    # concurrent task change defers to an ordinary pass with its normal gates.
    _, state = store.read()
    expected = {key: value for key, value in task.items() if key != "task_id"}
    if state.get("tasks", {}).get(task["task_id"]) != expected:
        return state
    return integrate(
        gh, config, state, _merged_only=(task["task_id"], merged, expected)
    )


def integrate(gh, config, state, *, _merged_only=None):
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
    if _merged_only is None:
        for task_id in state.get("tasks", {}):
            state = external_merge_incident(gh, store, state, task_id)
        state = recover_external_merges(gh, config, store, state, main)
    # Delivery is an independent outbox. Failed/exhausted publication cannot
    # occupy the serial merge lane or starve later eligible implementation.
    for task_id, task in list(state.get("tasks", {}).items()):
        if (
            _merged_only is None
            and task.get("status") == "done"
            and task.get("delivery_pending")
        ):
            state = deliver(gh, store, state, task_id, task["merge_sha"])
    tasks = {
        task_id: {**task, "task_id": task_id}
        for task_id, task in state.get("tasks", {}).items()
    }
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
    if _merged_only is not None:
        task_id, merged, expected = _merged_only
        if main != merged or state.get("tasks", {}).get(task_id) != expected:
            return state
        candidates = [t for t in active if t["task_id"] == task_id]
    for task in sorted(candidates, key=lambda t: str(t["task_id"])):
        pr = gh.repo(f"pulls/{task['pr_number']}")
        if _merged_only is not None and (
            pr.get("merged") is not True
            or pr.get("merge_commit_sha") != _merged_only[1]
            or pr.get("number") != task["pr_number"]
            or pr.get("base", {}).get("ref") != "main"
            or pr.get("head", {}).get("repo", {}).get("full_name")
            != config["repository"]
        ):
            # Eventual consistency is allowed. Never merge again, adopt from
            # the response alone, or fence a transient observation in this pass.
            return state
        if pr.get("merged"):
            merged = pr["merge_commit_sha"]
            submission = task.get("submission", {})
            journal = task.get("integration", {})
            journalled = (
                task["status"] in ("integrating", "verifying_main")
                and journal.get("head_sha") == pr["head"]["sha"]
                and journal.get("head_sha") == submission.get("head_sha")
                and journal.get("base_sha") == submission.get("base_sha")
                and journal.get("base_sha") == pr.get("base", {}).get("sha")
                and submission.get("spec_hash") == task.get("spec_hash")
                and (not task.get("merge_sha") or task["merge_sha"] == merged)
            )
            if not journalled:
                if _merged_only is not None:
                    return state
                tip, current = store.read()
                current = apply_request(
                    current,
                    {
                        "request_id": f"external-merge-{task['task_id']}-{merged}",
                        "verb": "fence-external-merge",
                        "task_id": task["task_id"],
                        "observed": {
                            "pr_number": task["pr_number"],
                            "pr_url": pr.get("html_url"),
                            "head_sha": pr.get("head", {}).get("sha"),
                            "base_sha": pr.get("base", {}).get("sha"),
                            "merge_sha": merged,
                            "merged_by": (pr.get("merged_by") or {}).get("login"),
                            "main_sha": main,
                        },
                    },
                    config["coordinator_login"],
                    int(datetime.now(timezone.utc).timestamp()),
                    config,
                )
                store.write(tip, current)
                state = external_merge_incident(gh, store, current, task["task_id"])
                continue
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
            if _merged_only is not None and (
                current.get("tasks", {}).get(task["task_id"]) != _merged_only[2]
                or gh.repo("git/ref/heads/main")["object"]["sha"] != merged
            ):
                return current
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
                        risk=(
                            "human"
                            if task["spec"]["risk"] == "human"
                            or sensitive_scope(task["spec"]["paths"], config)
                            else "routine"
                        ),
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
        response = gh.repo(
            f"pulls/{task['pr_number']}/merge",
            method="PUT",
            data={"sha": pr["head"]["sha"], "merge_method": "squash"},
        )
        return follow_merged_pr(gh, config, store, target, response)
    return state
