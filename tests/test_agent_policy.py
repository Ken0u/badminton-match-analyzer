"""External recovery retains source gates and truthful human-review provenance."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from devops.policy import external_recovery_errors, policy_errors, require_agent_review
from test_agent_coordinator import HEAD, policy_fixture


def recovery_policy_fixture():
    task, pr, files, checks, reviews, config, _ = policy_fixture()
    task["claim"]["branch"] = pr["head"]["ref"]
    pr.update(merged=True, state="closed")
    request = {
        "actor": "Ken0u",
        "human_review_attestation": {
            "kind": "owner_attestation",
            "reviewer": "Ken0u",
            "head_sha": HEAD,
            "statement": "I personally reviewed and approved this exact source.",
        },
    }
    return task, pr, files, checks, reviews, config, request


def test_attestation_is_distinct_from_github_review_and_never_mutates_evidence():
    args = recovery_policy_fixture()
    before = copy.deepcopy(args)
    assert external_recovery_errors(*args) == []
    assert args == before and args[4] == []


def test_external_recovery_accepts_no_human_review_or_attestation():
    args = recovery_policy_fixture()
    args[-1].pop("human_review_attestation")
    assert external_recovery_errors(*args) == []
    # Optional actual reviews remain evidence and never become a prerequisite.
    args[4].append(
        {"id": 1, "user": {"login": "Ken0u"}, "state": "APPROVED", "commit_id": HEAD}
    )
    assert external_recovery_errors(*args) == []


@pytest.mark.parametrize(
    "case",
    [
        "author_attests_self_review",
        "untrusted_reviewer",
        "stale_review_head",
        "empty_statement",
        "fake_github_kind",
        "untrusted_authorizer",
        "wrong_granted_branch",
        "unmerged_pr",
        "stale_source_check",
        "untrusted_check_app",
        "foreign_scope",
        "changed_source_base",
        "self_agent_review",
        "changes_requested",
    ],
)
def test_external_recovery_does_not_relax_missing_or_conflicting_evidence(case):
    task, pr, files, checks, reviews, config, request = recovery_policy_fixture()
    attestation = request["human_review_attestation"]
    if case == "author_attests_self_review":
        attestation["reviewer"] = pr["user"]["login"]
    elif case == "untrusted_reviewer":
        attestation["reviewer"] = "outsider"
    elif case == "stale_review_head":
        attestation["head_sha"] = "d" * 40
    elif case == "empty_statement":
        attestation["statement"] = " "
    elif case == "fake_github_kind":
        attestation["kind"] = "APPROVED"
    elif case == "untrusted_authorizer":
        request["actor"] = "outsider"
    elif case == "wrong_granted_branch":
        task["claim"]["branch"] += "-another"
    elif case == "unmerged_pr":
        pr["merged"] = False
    elif case == "stale_source_check":
        checks[0]["head_sha"] = "e" * 40
    elif case == "untrusted_check_app":
        checks[0]["app"]["slug"] = "another-app"
    elif case == "foreign_scope":
        files.append("backend/unreserved.py")
    elif case == "changed_source_base":
        pr["base"]["sha"] = "f" * 40
    elif case == "self_agent_review":
        task["review"]["session_id"] = task["claim"]["session_id"]
    else:
        reviews.append(
            {
                "id": 1,
                "user": {"login": "dootz1"},
                "state": "CHANGES_REQUESTED",
                "commit_id": HEAD,
            }
        )
    assert external_recovery_errors(task, pr, files, checks, reviews, config, request)


@pytest.mark.parametrize(
    "approval",
    [
        None,
        {},
        {"actor": "outsider", "spec_hash": "spec"},
        {"actor": "Ken0u", "spec_hash": "stale"},
    ],
)
def test_sensitive_scope_requires_matching_configured_owner_authorization(approval):
    args = policy_fixture()
    args[0]["spec"]["risk"] = "human"
    args[0]["human_approval"] = approval
    assert (
        "Sensitive change requires owner authorization of the frozen task scope"
        in policy_errors(*args)
    )


@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize(
    "defect",
    [
        "missing_review",
        "self_review",
        "stale_head",
        "stale_base",
        "stale_spec",
        "failed_ci",
        "running_ci",
        "requested_changes",
    ],
)
def test_without_human_review_all_independent_and_ci_gates_remain(recovery, defect):
    task, pr, files, checks, reviews, config, base = policy_fixture()
    task["spec"]["risk"] = "human"
    task["human_approval"] = {"actor": "Ken0u", "spec_hash": "spec", "at": 100}
    task["claim"]["branch"] = pr["head"]["ref"]
    if defect == "missing_review":
        task.pop("review")
    elif defect == "self_review":
        task["review"]["session_id"] = task["claim"]["session_id"]
    elif defect.startswith("stale_"):
        key = {
            "stale_head": "head_sha",
            "stale_base": "base_sha",
            "stale_spec": "spec_hash",
        }[defect]
        task["review"][key] = "stale"
    elif defect == "failed_ci":
        checks[0]["conclusion"] = "failure"
    elif defect == "running_ci":
        checks[0]["status"] = "in_progress"
    else:
        reviews.append(
            {
                "id": 1,
                "user": {"login": "dootz1"},
                "state": "CHANGES_REQUESTED",
                "commit_id": HEAD,
            }
        )
    if recovery:
        pr.update(merged=True, state="closed")
        errors = external_recovery_errors(
            task, pr, files, checks, reviews, config, {"actor": "Ken0u"}
        )
    else:
        errors = policy_errors(task, pr, files, checks, reviews, config, base)
    assert errors


@pytest.mark.parametrize("setting", [None, True, 0, 1, "false", "true", [], {}])
def test_agent_review_defaults_required_and_rejects_malformed_opt_out(setting):
    args = list(policy_fixture())
    args[0].pop("review")
    args[5] = {**args[5], "require_agent_review": setting}
    assert require_agent_review(args[5]) is True
    assert "Fresh independent agent review required" in policy_errors(*args)
    args[5].pop("require_agent_review")
    assert "Fresh independent agent review required" in policy_errors(*args)


def test_only_explicit_false_allows_missing_agent_review_without_fabrication():
    args = list(policy_fixture())
    args[0].pop("review")
    args[5] = {**args[5], "require_agent_review": False}
    before = copy.deepcopy(args)
    assert require_agent_review(args[5]) is False
    assert policy_errors(*args) == []
    assert args == before and "review" not in args[0]


@pytest.mark.parametrize(
    "defect",
    ["changes", "head_sha", "base_sha", "spec_hash", "self", "malformed", "active"],
)
def test_optional_review_preserves_real_review_vetoes(defect):
    args = list(policy_fixture())
    args[5] = {**args[5], "require_agent_review": False}
    assert policy_errors(*args) == []
    if defect == "changes":
        args[0]["review"]["verdict"] = "changes"
    elif defect == "self":
        args[0]["review"]["session_id"] = args[0]["claim"]["session_id"]
    elif defect == "malformed":
        args[0]["review"] = None
    elif defect == "active":
        args[0].pop("review")
        args[0]["review_claim"] = {"session_id": "fresh-review"}
    else:
        args[0]["review"][defect] = "stale"
    assert policy_errors(*args)


@pytest.mark.parametrize(
    "defect",
    [
        "submission_head",
        "submission_base",
        "submission_spec",
        "claim_epoch",
        "claim_spec",
        "missing_claim",
        "wrong_branch",
        "foreign_repo",
        "scope",
        "ci_head",
        "ci_app",
        "ci_failed",
        "ci_running",
        "main",
        "owner",
        "native",
        "requested_changes",
    ],
)
def test_optional_no_review_retains_other_source_and_owner_gates(defect):
    args = list(policy_fixture())
    task, pr, files, checks, reviews, config, _ = args
    args[5] = config = {**config, "require_agent_review": False}
    task.pop("review")
    if defect.startswith("submission_"):
        key = {"head": "head_sha", "base": "base_sha", "spec": "spec_hash"}[
            defect.removeprefix("submission_")
        ]
        task["submission"][key] = "stale"
    elif defect == "claim_epoch":
        task["epoch"] += 1
    elif defect == "claim_spec":
        task["claim"]["spec_hash"] = "stale"
    elif defect == "missing_claim":
        task.pop("claim")
    elif defect == "wrong_branch":
        pr["head"]["ref"] = "codex/issue-99-other"
    elif defect == "foreign_repo":
        pr["head"]["repo"]["full_name"] = "outsider/fork"
    elif defect == "scope":
        files.append("backend/unreserved.py")
    elif defect == "ci_head":
        checks[0]["head_sha"] = "f" * 40
    elif defect == "ci_app":
        checks[0]["app"]["slug"] = "untrusted"
    elif defect == "ci_failed":
        checks[0]["conclusion"] = "failure"
    elif defect == "ci_running":
        checks[0]["status"] = "in_progress"
    elif defect == "main":
        args[-1] = "f" * 40
    elif defect == "owner":
        task["spec"]["risk"] = "human"
    elif defect == "native":
        config["native_evidence_paths"] = files[:]
    else:
        reviews.append(
            {"id": 1, "user": {"login": "dootz1"}, "state": "CHANGES_REQUESTED"}
        )
    assert policy_errors(*args)


@pytest.mark.parametrize(
    "defect", ["missing", "self", "head_sha", "base_sha", "spec_hash"]
)
def test_external_recovery_requires_original_review_despite_current_optional_config(
    defect,
):
    args = list(recovery_policy_fixture())
    args[5] = {**args[5], "require_agent_review": False}
    assert external_recovery_errors(*args) == []
    if defect == "missing":
        args[0].pop("review")
    elif defect == "self":
        args[0]["review"]["session_id"] = args[0]["claim"]["session_id"]
    else:
        args[0]["review"][defect] = "stale"
    assert "Fresh independent agent review required" in external_recovery_errors(*args)
