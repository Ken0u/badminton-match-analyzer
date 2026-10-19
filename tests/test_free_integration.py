"""GitHub Free retains controller policy without probing paid protection APIs."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from devops.coordinator import conversation_errors, integrate
from devops.github import GitHubError
from devops.policy import policy_errors
from setup_automation import setup
from test_agent_coordinator import BASE, CONFIG, HEAD, merge_setup, policy_fixture


def deny_protection_api(gh, monkeypatch, message="403 upgrade required"):
    original = gh.repo

    def repo(path="", **kwargs):
        if path == "branches/main/protection":
            raise GitHubError(message)
        return original(path, **kwargs)

    monkeypatch.setattr(gh, "repo", repo)


def test_free_mode_merges_then_verifies_and_delivers_without_protection_api(
    monkeypatch,
):
    gh, store, config = merge_setup()
    config["integration_enforcement"] = "controller"
    deny_protection_api(gh, monkeypatch)
    state = integrate(gh, config, store.read()[1])
    assert gh.pr["merged"] and state["tasks"]["1"]["status"] == "integrating"
    gh.ci = [
        {"id": 1, "event": "push", "head_sha": gh.merge_sha, "conclusion": "success"}
    ]
    state = integrate(gh, config, store.read()[1])
    assert state["tasks"]["1"]["status"] == "done"
    assert state["tasks"]["1"]["delivery_pending"]


@pytest.mark.parametrize(
    "fault",
    ["ci", "review", "scope", "base", "human", "changes", "conversation", "behind"],
)
def test_free_mode_preserves_merge_gates(monkeypatch, fault):
    gh, store, config = merge_setup()
    config["integration_enforcement"] = "controller"
    deny_protection_api(gh, monkeypatch)
    tip, state = store.read()
    if fault == "review":
        state["tasks"]["1"]["review"]["session_id"] = "mac1"
    elif fault == "scope":
        state["tasks"]["1"]["spec"]["paths"] = ["backend/unrelated.py"]
    elif fault == "base":
        gh.main = "e" * 40
    elif fault == "human":
        config["sensitive_paths"] = ["backend/"]
    elif fault in ("ci", "behind"):
        original = gh.repo

        def repo(path="", **kwargs):
            result = original(path, **kwargs)
            if fault == "ci" and "/check-runs?" in path:
                result[0]["check_runs"][0]["conclusion"] = "failure"
            if fault == "behind" and path.startswith("compare/"):
                result.update(status="diverged", merge_base_commit={"sha": "f" * 40})
            return result

        monkeypatch.setattr(gh, "repo", repo)
    elif fault == "changes":
        original_pages = gh.pages
        monkeypatch.setattr(
            gh,
            "pages",
            lambda path: (
                [
                    {
                        "id": 1,
                        "user": {"login": "dootz1"},
                        "state": "CHANGES_REQUESTED",
                        "commit_id": HEAD,
                    }
                ]
                if "/reviews?" in path
                else original_pages(path)
            ),
        )
    else:
        monkeypatch.setattr(
            gh,
            "graphql",
            lambda *_a, **_kw: {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [{"isResolved": False}],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            },
        )
    store.write(tip, state)
    integrate(gh, config, store.read()[1])
    assert not gh.pr["merged"]


@pytest.mark.parametrize("failure", ["403 upgrade required", "404 no protections"])
def test_optional_github_mode_never_falls_back(monkeypatch, failure):
    gh, store, config = merge_setup()
    config["integration_enforcement"] = "github"
    deny_protection_api(gh, monkeypatch, failure)
    with pytest.raises(GitHubError):
        integrate(gh, config, store.read()[1])
    assert not gh.pr["merged"]


def test_optional_github_mode_requires_complete_protections(monkeypatch):
    gh, store, config = merge_setup()
    config["integration_enforcement"] = "github"
    original = gh.repo
    monkeypatch.setattr(
        gh,
        "repo",
        lambda path="", **kw: (
            {} if path == "branches/main/protection" else original(path, **kw)
        ),
    )
    with pytest.raises(ValueError, match="protections"):
        integrate(gh, config, store.read()[1])
    assert not gh.pr["merged"]


def test_unknown_enforcement_is_rejected():
    gh, store, config = merge_setup()
    config["integration_enforcement"] = "typo"
    with pytest.raises(ValueError, match="Unknown integration enforcement"):
        integrate(gh, config, store.read()[1])
    assert not gh.pr["merged"]


@pytest.mark.parametrize("fault", ["head", "main", "conversation", "ci"])
def test_changes_during_journal_commit_block_merge(monkeypatch, fault):
    gh, store, config = merge_setup()
    original = gh.repo
    seen = 0
    pull_reads = 0

    def repo(path="", **kwargs):
        nonlocal seen, pull_reads
        if path == "pulls/42" and kwargs.get("method", "GET") == "GET":
            pull_reads += 1
            if fault == "head" and pull_reads == 3:
                gh.pr["head"]["sha"] = "e" * 40
        result = original(path, **kwargs)
        if "/check-runs?" in path:
            seen += 1
            if seen == 2:
                if fault == "main":
                    gh.main = "e" * 40
                elif fault == "ci":
                    result[0]["check_runs"][0]["conclusion"] = "failure"
        return result

    monkeypatch.setattr(gh, "repo", repo)
    original_graphql = gh.graphql
    monkeypatch.setattr(
        gh,
        "graphql",
        lambda *args, **kw: (
            {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [{"isResolved": False}],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            }
            if fault == "conversation" and seen >= 2
            else original_graphql(*args, **kw)
        ),
    )
    integrate(gh, config, store.read()[1])
    assert not gh.pr["merged"]


def test_conversations_paginate_and_fail_closed():
    class GitHub:
        def __init__(self):
            self.cursors = []

        def graphql(self, _query, **variables):
            self.cursors.append(variables["cursor"])
            second = variables["cursor"] is not None
            return {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [{"isResolved": not second}],
                            "pageInfo": {
                                "hasNextPage": not second,
                                "endCursor": "page2",
                            },
                        }
                    }
                }
            }

    gh = GitHub()
    assert conversation_errors(gh, CONFIG, 42)
    assert gh.cursors == [None, "page2"]


def test_conversation_api_failure_cannot_be_treated_as_resolved(monkeypatch):
    gh, store, config = merge_setup()

    def unavailable(*_args, **_kwargs):
        raise GitHubError("503 review threads unavailable")

    monkeypatch.setattr(gh, "graphql", unavailable)
    with pytest.raises(GitHubError):
        integrate(gh, config, store.read()[1])
    assert not gh.pr["merged"]


def test_latest_collaborator_review_can_clear_requested_changes():
    args = policy_fixture()
    args[4].append(
        {
            "id": 1,
            "user": {"login": "Ken0u"},
            "state": "CHANGES_REQUESTED",
            "commit_id": BASE,
        }
    )
    assert policy_errors(*args)
    args[4].append(
        {"id": 2, "user": {"login": "Ken0u"}, "state": "DISMISSED", "commit_id": BASE}
    )
    assert not policy_errors(*args)


class SetupGitHub:
    def __init__(self, admin=False):
        self.admin = admin
        self.writes = []

    def repo(self, path="", *, method="GET", data=None):
        if not path:
            return {
                "private": True,
                "full_name": CONFIG["repository"],
                "permissions": {"admin": self.admin},
            }
        self.writes.append((path, method, copy.deepcopy(data)))
        return {}

    def pages(self, path):
        assert path.startswith("issues?")
        return [{"number": 74}]


def test_free_setup_needs_no_admin_subscription_or_protection_api():
    gh = SetupGitHub()
    result = setup(gh, apply=True)
    assert result["subscription_required"] is False
    assert result["owner_action_required"] is False
    assert result["protection"] is None
    assert not gh.writes


def test_optional_setup_changes_protections_only_when_requested_by_admin():
    gh = SetupGitHub(admin=True)
    setup(gh, apply=True, protections=True, enforcement="github")
    assert gh.writes[0][0:2] == ("branches/main/protection", "PUT")
    with pytest.raises(ValueError, match="owner/admin"):
        setup(SetupGitHub(), apply=True, protections=True)
