"""External recovery retains source gates and truthful human-review provenance."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from devops.policy import external_recovery_errors
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


def test_current_github_non_author_review_can_supply_real_review_evidence():
    args = recovery_policy_fixture()
    args[-1].pop("human_review_attestation")
    assert external_recovery_errors(*args)
    args[4].append(
        {"id": 1, "user": {"login": "Ken0u"}, "state": "APPROVED", "commit_id": HEAD}
    )
    assert external_recovery_errors(*args) == []


@pytest.mark.parametrize(
    "case",
    [
        "no_attestation",
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
    if case == "no_attestation":
        request.pop("human_review_attestation")
    elif case == "author_attests_self_review":
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
