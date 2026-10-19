"""External recovery retains source gates and truthful human-review provenance."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from devops.policy import external_recovery_errors, policy_errors
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
