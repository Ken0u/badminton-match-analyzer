"""Authoritative status projection never changes history or coordination state."""

from __future__ import annotations

import base64
import importlib.util
import json
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
