"""Authoritative status projection never changes history or coordination state."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    SPEC = importlib.util.spec_from_file_location(
        "project_status", SCRIPTS / "project_status.py"
    )
    status = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(status)
finally:
    sys.path.pop(0)


class FakeGitHub:
    def __init__(self, tasks=None):
        self.state = {
            "version": 1,
            "tasks": tasks if tasks is not None else {"40": {"status": "running"}},
        }
        self.reads = []
        self.writes = []

    def api(self, path):
        self.reads.append(path)
        if "/contents/state.json" in path:
            assert "ref=codex%2Fcoordination" in path
            return {
                "encoding": "base64",
                "content": base64.b64encode(json.dumps(self.state).encode()).decode(),
            }
        return {"number": int(path.rsplit("/", 1)[-1]), "node_id": "I_40"}

    def graphql(self, query, **variables):
        if "user(login" in query:
            return {
                "user": {
                    "projectV2": {
                        "id": "P",
                        "fields": {
                            "nodes": [
                                {
                                    "id": "F",
                                    "name": "Status",
                                    "options": [
                                        {"id": name, "name": name}
                                        for name in status.STATUSES.values()
                                    ],
                                }
                            ]
                        },
                    }
                }
            }
        if query.startswith("query"):
            return {
                "node": {
                    "items": {
                        "nodes": [
                            {
                                "id": "historical",
                                "content": {"id": "I_1"},
                                "fieldValueByName": {"name": "Done"},
                            },
                            {
                                "id": "managed",
                                "content": {"id": "I_40"},
                                "fieldValueByName": {"name": "Ready"},
                            },
                        ],
                        "pageInfo": {"hasNextPage": False},
                    }
                }
            }
        self.writes.append(variables)
        return {
            "updateProjectV2ItemFieldValue": {
                "projectV2Item": {"id": variables["item"]}
            }
        }


def test_only_managed_task_status_changes():
    gh = FakeGitHub()
    result = status.sync_status(gh, repo="owner/repo", owner="owner", number=1)
    assert result["add"] == [{"issue": 40, "status": "Running"}]
    assert len(gh.writes) == 1
    assert gh.writes[0]["item"] == "managed"
    assert gh.writes[0]["value"] == "Running"
    assert not any("issues/1" in path for path in gh.reads)
    assert gh.state["tasks"]["40"]["status"] == "running"


@pytest.mark.parametrize("value", list(status.STATUSES))
def test_all_queue_states_project(value):
    gh = FakeGitHub({"40": {"status": value}})
    status.sync_status(gh, repo="o/r", owner="o", number=1)
    assert gh.writes[0]["value"] == status.STATUSES[value]


def test_unknown_status_fails_without_writes():
    gh = FakeGitHub({"40": {"status": "running"}, "41": {"status": "invented"}})
    with pytest.raises(ValueError, match="Unknown coordination status"):
        status.sync_status(gh, repo="o/r", owner="o", number=1)
    assert not gh.writes


def test_history_only_board_unchanged_when_queue_empty():
    gh = FakeGitHub({})
    status.sync_status(gh, repo="o/r", owner="o", number=1)
    assert not gh.writes


def test_unconfigured_project_explicit_noop(monkeypatch, capsys):
    monkeypatch.delenv("BADMINTON_PROJECT_NUMBER", raising=False)
    monkeypatch.delenv("AGENT_PROJECT_TOKEN", raising=False)
    status.main([])
    assert json.loads(capsys.readouterr().out)["status"] == "not-configured"


def test_configured_project_requires_dedicated_token(monkeypatch, capsys):
    monkeypatch.delenv("AGENT_PROJECT_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "ordinary-repo-token")
    with pytest.raises(SystemExit, match="1"):
        status.main(["--project-number", "1"])
    assert "AGENT_PROJECT_TOKEN is missing" in capsys.readouterr().err


def test_configured_token_only_used_for_projection(monkeypatch, capsys):
    monkeypatch.setenv("AGENT_PROJECT_TOKEN", "project-secret")
    monkeypatch.setattr(status, "GitHub", FakeGitHub)
    status.main(["--project-number", "1"])
    output = capsys.readouterr().out
    assert "project-secret" not in output
    assert json.loads(output)["status"] == "projected"


HTTP_502 = "gh failed (1): gh: HTTP 502"
QUERY_ERROR = (
    "gh failed (1): gh: Something went wrong while executing your query on "
    "2026-10-21T02:09:54Z. Please include `7869:45CC:15652B5:452AABD:6AD81EF1` "
    "when reporting this issue."
)
REFUSED_STREAM = (
    'gh failed (1): Post "https://api.github.com/graphql": http2: Transport: '
    "cannot retry err [stream error: stream ID 1; REFUSED_STREAM; received from peer] "
    "after Request.Body was written; define Request.GetBody to avoid this error"
)


class FailingProject(FakeGitHub):
    def __init__(self, error, failures):
        super().__init__()
        self.error = error
        self.failures = failures
        self.attempts = 0

    def graphql(self, query, **variables):
        if "user(login" in query:
            self.attempts += 1
            if self.attempts <= self.failures:
                raise self.error
        return super().graphql(query, **variables)


@pytest.fixture
def projection_run(monkeypatch):
    """Exercise the actual CLI boundary without network or real credentials."""
    monkeypatch.setenv("AGENT_PROJECT_TOKEN", "project-secret")
    monkeypatch.setenv("GH_TOKEN", "original-repo-token")
    delays = []
    # The baseline has no retry clock; patching time.sleep also permits a
    # before/after reproduction through main rather than a helper-only test.
    import time

    monkeypatch.setattr(time, "sleep", delays.append)

    def run(gh):
        monkeypatch.setattr(status, "GitHub", lambda: gh)
        status.main(["--project-number", "1"])

    return run, delays


@pytest.mark.parametrize("error", [HTTP_502, QUERY_ERROR, REFUSED_STREAM])
def test_transient_failure_reloads_state_and_recovers(projection_run, capsys, error):
    run, delays = projection_run
    gh = FailingProject(RuntimeError(error), failures=1)
    run(gh)
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "projected"
    assert gh.attempts == 2
    assert sum("/contents/state.json" in path for path in gh.reads) == 2
    assert len(gh.writes) == 1
    assert delays == [2]
    assert "retrying" in output.err
    assert "project-secret" not in output.out + output.err
    assert "original-repo-token" not in output.out + output.err
    assert os.environ["GH_TOKEN"] == "original-repo-token"


def test_transient_exhaustion_is_nonzero_and_bounded(projection_run, capsys):
    run, delays = projection_run
    gh = FailingProject(RuntimeError(HTTP_502), failures=100)
    with pytest.raises(SystemExit, match="1"):
        run(gh)
    output = capsys.readouterr()
    assert not output.out
    assert "exhausted 3 projection attempts" in output.err
    assert gh.attempts == 3
    assert delays == [2, 4]
    assert not gh.writes
    assert os.environ["GH_TOKEN"] == "original-repo-token"


def test_final_allowed_attempt_can_recover(projection_run, capsys):
    run, delays = projection_run
    gh = FailingProject(RuntimeError(QUERY_ERROR), failures=2)
    run(gh)
    assert json.loads(capsys.readouterr().out)["status"] == "projected"
    assert gh.attempts == 3 and delays == [2, 4]
    assert len(gh.writes) == 1


def test_permanent_error_after_transient_stops_immediately(projection_run, capsys):
    class ChangedFailure(FailingProject):
        def graphql(self, query, **variables):
            if self.attempts == 1:
                self.error = RuntimeError("gh failed (1): gh: HTTP 403 project-secret")
            return super().graphql(query, **variables)

    run, delays = projection_run
    gh = ChangedFailure(RuntimeError(HTTP_502), failures=100)
    with pytest.raises(SystemExit, match="1"):
        run(gh)
    output = capsys.readouterr()
    assert gh.attempts == 2 and delays == [2]
    assert "credentials/access" in output.err
    assert "project-secret" not in output.err
    assert not gh.writes


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("gh failed (1): gh: HTTP 401 Bad credentials project-secret"),
        RuntimeError("gh failed (1): gh: HTTP 403 Forbidden project-secret"),
        RuntimeError("gh failed (1): gh: HTTP 404"),
        RuntimeError("gh failed (1): gh: HTTP 429"),
        RuntimeError("user Project not found or inaccessible"),
        RuntimeError("Project requires a single-select Status field"),
        RuntimeError("Add these Status options to the Project: Running"),
        RuntimeError("GraphQL request failed: project-secret"),
        RuntimeError("unknown error with project-secret HTTP 502 REFUSED_STREAM"),
        RuntimeError("gh failed (1): gh: HTTP 403 Forbidden; HTTP 502"),
        ValueError("Unknown coordination status for task project-secret"),
    ],
)
def test_permanent_or_unknown_errors_fail_without_retry(projection_run, capsys, error):
    run, delays = projection_run
    gh = FailingProject(error, failures=100)
    with pytest.raises(SystemExit, match="1"):
        run(gh)
    output = capsys.readouterr()
    assert gh.attempts == 1
    assert not delays and not gh.writes and not output.out
    assert "Project projection failed:" in output.err
    assert "project-secret" not in output.err
    assert "original-repo-token" not in output.err
    assert os.environ["GH_TOKEN"] == "original-repo-token"


def test_ambiguous_applied_add_is_reinventoried_before_retry(projection_run, capsys):
    class AppliedThenLost(FakeGitHub):
        def __init__(self):
            super().__init__()
            self.present = False
            self.adds = 0
            self.inventories = 0

        def api(self, path):
            result = super().api(path)
            if "/contents/state.json" in path and self.present:
                # The second attempt must project fresh state, not a stale
                # pre-failure snapshot, while the first write's result is unknown.
                self.state["tasks"]["40"]["status"] = "blocked"
                result["content"] = base64.b64encode(
                    json.dumps(self.state).encode()
                ).decode()
            return result

        def graphql(self, query, **variables):
            if query.startswith("query($id:ID!,$cursor"):
                self.inventories += 1
                data = super().graphql(query, **variables)
                items = data["node"]["items"]["nodes"]
                items[:] = [item for item in items if item["id"] == "historical"]
                if self.present:
                    items.append({"id": "added-once", "content": {"id": "I_40"}})
                return data
            if "addProjectV2ItemById" in query:
                self.adds += 1
                self.present = True
                raise RuntimeError(REFUSED_STREAM)
            if "updateProjectV2ItemFieldValue" in query:
                assert os.environ["GH_TOKEN"] == "project-secret"
            return super().graphql(query, **variables)

    run, delays = projection_run
    gh = AppliedThenLost()
    run(gh)
    assert json.loads(capsys.readouterr().out)["status"] == "projected"
    assert gh.adds == 1 and gh.inventories == 2
    assert delays == [2]
    assert gh.writes == [
        {"project": "P", "item": "added-once", "field": "F", "value": "Blocked"}
    ]
    assert gh.state["tasks"]["40"]["status"] == "blocked"
    assert not any("issues/1" in path for path in gh.reads)


def test_projection_token_removed_when_previously_absent(projection_run, monkeypatch):
    run, _ = projection_run
    monkeypatch.delenv("GH_TOKEN")
    run(FakeGitHub())
    assert "GH_TOKEN" not in os.environ
