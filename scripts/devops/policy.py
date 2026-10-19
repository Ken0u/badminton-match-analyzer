"""Deterministic integration policy, evaluated by trusted main code."""

import re

SHA = re.compile(r"^[0-9a-f]{40}$")


def in_scope(path, prefixes):
    return any(
        path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in prefixes
    )


def sensitive(files, config):
    return any(in_scope(f, config["sensitive_paths"]) for f in files)


def latest_reviews(reviews):
    result = {}
    for review in sorted(reviews, key=lambda r: r.get("id", 0)):
        if review.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            result[review["user"]["login"]] = review
    return result


def review_errors(reviews, config):
    if any(
        review.get("state") == "CHANGES_REQUESTED"
        for login, review in latest_reviews(reviews).items()
        if login in config["trusted_logins"]
    ):
        return ["A collaborator's requested changes must be approved or dismissed"]
    return []


def rollout_errors(pr, changed, proposed, checks, reviews, config, main_sha):
    """One-time, manually merged mode changes cannot depend on queue grants."""
    head = pr["head"]["sha"]
    errors = review_errors(reviews, config)
    if (
        len(changed) != 1
        or changed[0].get("filename") != ".github/automation.json"
        or changed[0].get("status") != "modified"
        or changed[0].get("previous_filename")
    ):
        errors.append("Rollout PR may only modify .github/automation.json")
    if (
        not isinstance(proposed, dict)
        or {k: v for k, v in proposed.items() if k not in ("mode", "pilot_tasks")}
        != {k: v for k, v in config.items() if k not in ("mode", "pilot_tasks")}
        or (config["mode"], proposed.get("mode"))
        not in {("observation", "pilot"), ("pilot", "active")}
        or not isinstance(proposed.get("pilot_tasks"), list)
        or not proposed["pilot_tasks"]
        or not all(type(n) is int and n > 0 for n in proposed["pilot_tasks"])
    ):
        errors.append("Only observation-to-pilot or pilot-to-active rollout is allowed")
    if (
        pr.get("draft")
        or pr.get("state") != "open"
        or pr["base"]["ref"] != "main"
        or pr["base"]["sha"] != main_sha
        or pr["head"].get("repo", {}).get("full_name") != config["repository"]
    ):
        errors.append(
            "Rollout requires an open same-repository PR against current main"
        )
    latest = {}
    for check in sorted(checks, key=lambda c: c.get("id", 0)):
        if (
            check.get("head_sha") == head
            and check.get("app", {}).get("slug") == "github-actions"
        ):
            latest[check["name"]] = check
    for name in config["required_checks"]:
        if (
            latest.get(name, {}).get("conclusion") != "success"
            or latest.get(name, {}).get("status") != "completed"
        ):
            errors.append(f"Required check missing or unsuccessful: {name}")
    return errors


def _source_errors(task, pr, files, checks, reviews, config):
    """Evidence that remains necessary for both normal and external integration."""
    errors = review_errors(reviews, config)
    head, base = pr["head"]["sha"], pr["base"]["sha"]
    spec = task["spec"]
    if not files:
        errors.append("No changed-file evidence")
    if any(not in_scope(f, spec["paths"]) for f in files):
        errors.append("Changed paths exceed the granted scope")
    if task.get("submission", {}).get("base_sha") != base:
        errors.append("Submission does not match PR base")
    if task.get("submission", {}).get("head_sha") != head:
        errors.append("Submission does not match PR head")
    if (
        pr["base"]["ref"] != "main"
        or pr["head"].get("repo", {}).get("full_name") != config["repository"]
    ):
        errors.append("PR must originate in this repository and target main")
    if not pr["head"]["ref"].startswith(f"codex/issue-{task['task_id']}-"):
        errors.append("PR branch does not belong to the task")
    latest = {}
    for check in sorted(checks, key=lambda c: c.get("id", 0)):
        if (
            check.get("head_sha") == head
            and check.get("app", {}).get("slug") == "github-actions"
        ):
            latest[check["name"]] = check
    for name in config["required_checks"]:
        check = latest.get(name, {})
        if check.get("status") != "completed" or check.get("conclusion") != "success":
            errors.append(f"Required check missing or unsuccessful: {name}")
    if any(in_scope(path, config.get("native_evidence_paths", [])) for path in files):
        evidence = task.get("submission", {}).get("native_evidence", {})
        if (
            not isinstance(evidence, dict)
            or evidence.get("code_sha") != head
            or not all(
                isinstance(evidence.get(key), str)
                and re.fullmatch(r"[0-9a-f]{64}", evidence[key])
                for key in ("source_sha256", "model_sha256", "receipt_sha256")
            )
            or not isinstance(evidence.get("limitations"), list)
            or not evidence["limitations"]
        ):
            errors.append(
                "Inference changes require source/model/code-bound native evidence and limitations"
            )
    verdict = task.get("review", {})
    if (
        verdict.get("verdict") != "approve"
        or verdict.get("head_sha") != head
        or verdict.get("base_sha") != base
        or verdict.get("spec_hash") != task.get("spec_hash")
        or verdict.get("session_id") == task.get("claim", {}).get("session_id")
    ):
        errors.append("Fresh independent agent review required")
    return errors


def scope_authorized(task, config):
    """Owner authorization binds the frozen task, not a human PR review."""
    approval = task.get("human_approval")
    return (
        isinstance(approval, dict)
        and isinstance(approval.get("actor"), str)
        and approval["actor"].casefold()
        in {login.casefold() for login in config.get("human_approvers", [])}
        and approval.get("spec_hash") == task.get("spec_hash")
        and isinstance(task.get("spec_hash"), str)
        and bool(task["spec_hash"])
    )


def policy_errors(task, pr, files, checks, reviews, config, main_sha):
    """Missing or stale evidence fails closed, including newly discovered paths."""
    errors = _source_errors(task, pr, files, checks, reviews, config)
    if (
        pr["base"]["sha"] != main_sha
        or task.get("submission", {}).get("base_sha") != pr["base"]["sha"]
    ):
        errors.append("Update branch and review against current main")
    if task.get("status") not in ("review", "merge_ready", "integrating", "merging"):
        errors.append("Task has no valid integration reservation")
    if pr.get("draft") or pr.get("state") != "open":
        errors.append("PR is not open and ready")
    if (
        task["spec"].get("risk") == "human" or sensitive(files, config)
    ) and not scope_authorized(task, config):
        errors.append(
            "Sensitive change requires owner authorization of the frozen task scope"
        )
    return errors


def external_recovery_errors(task, pr, files, checks, reviews, config, request):
    """A recovery authorization cannot replace original source/review evidence.

    The trusted adapter authenticates the request actor and checks immutable
    coordination history, source/merge trees, ancestry and exact-main CI.
    An owner attestation is recorded separately from GitHub approval reviews.
    """
    errors = _source_errors(task, pr, files, checks, reviews, config)
    if pr.get("merged") is not True or pr.get("state") != "closed" or pr.get("draft"):
        errors.append("External recovery requires an actually merged PR")
    if pr["head"]["ref"] != task.get("claim", {}).get("branch"):
        errors.append("Recovery branch does not match the original grant")
    if request.get("actor") not in config["human_approvers"]:
        errors.append("External recovery requires an authenticated human approver")
    attestation = request.get("human_review_attestation")
    valid_attestation = (
        isinstance(attestation, dict)
        and attestation.get("kind") == "owner_attestation"
        and attestation.get("reviewer") in config["human_approvers"]
        and attestation.get("reviewer") != pr["user"]["login"]
        and attestation.get("head_sha") == pr["head"]["sha"]
        and isinstance(attestation.get("statement"), str)
        and 0 < len(attestation["statement"].strip()) <= 4000
    )
    if attestation is not None and not valid_attestation:
        errors.append("Invalid external human-review attestation")
    return errors
