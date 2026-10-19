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
    by_user = latest_reviews(reviews)
    if not any(
        user in config["human_approvers"]
        and user != pr["user"]["login"]
        and review.get("state") == "APPROVED"
        and review.get("commit_id") == head
        for user, review in by_user.items()
    ):
        errors.append("Rollout requires a current non-author human approval")
    return errors


def policy_errors(task, pr, files, checks, reviews, config, main_sha):
    """Missing or stale evidence fails closed, including newly discovered paths."""
    errors = review_errors(reviews, config)
    head, base = pr["head"]["sha"], pr["base"]["sha"]
    spec = task["spec"]
    if not files:
        errors.append("No changed-file evidence")
    if any(not in_scope(f, spec["paths"]) for f in files):
        errors.append("Changed paths exceed the granted scope")
    if base != main_sha or task.get("submission", {}).get("base_sha") != base:
        errors.append("Update branch and review against current main")
    if task.get("submission", {}).get("head_sha") != head:
        errors.append("Submission does not match PR head")
    if task.get("status") not in ("review", "merge_ready", "integrating", "merging"):
        errors.append("Task has no valid integration reservation")
    if pr.get("draft") or pr.get("state") != "open":
        errors.append("PR is not open and ready")
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
    if spec.get("risk") == "human" or sensitive(files, config):
        by_user = latest_reviews(reviews)
        if not any(
            login in config["human_approvers"]
            and login != pr["user"]["login"]
            and review.get("state") == "APPROVED"
            and review.get("commit_id") == head
            for login, review in by_user.items()
        ):
            errors.append(
                "Sensitive change requires a current non-author human approval"
            )
    return errors
