"""Remote planning/history tests: no GitHub access or credential required."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts/devops/project.py"
SPEC = importlib.util.spec_from_file_location("devops_project", MODULE_PATH)
project = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = project
SPEC.loader.exec_module(project)


class FakeGitHub:
    def __init__(self):
        self.issues = []
        self.milestones = []
        self.writes = []
        self.pulls = [
            {
                "number": 1,
                "title": "Review app",
                "state": "closed",
                "merged_at": "2026-10-18",
                "merge_commit_sha": "abc",
                "html_url": "https://example.invalid/pull/1",
            },
            {"number": 2, "title": "Not merged", "state": "closed", "merged_at": None},
            {
                "number": 30,
                "title": "Existing research",
                "state": "open",
                "merged_at": None,
                "html_url": "https://example.invalid/pull/30",
            },
        ]

    def pages(self, path):
        assert "per_page=100" in path
        if "/issues?" in path:
            assert "state=all" in path
            return self.issues
        if "/milestones?" in path:
            return self.milestones
        if "/pulls?" in path:
            assert "state=all" in path
            return self.pulls
        raise AssertionError(path)

    def api(self, path, *, method="GET", data=None):
        self.writes.append((path, method, data))
        if path.endswith("/milestones"):
            value = {**data, "number": len(self.milestones) + 1}
            self.milestones.append(value)
            return value
        if path.endswith("/issues"):
            value = {
                **data,
                "number": len(self.issues) + 1,
                "state": "open",
                "node_id": f"I_{len(self.issues) + 1}",
            }
            self.issues.append(value)
            return value
        number = int(path.rsplit("/", 1)[-1])
        value = next(issue for issue in self.issues if issue["number"] == number)
        value.update(data)
        return value

    def graphql(self, *args, **kwargs):
        raise RuntimeError("Project permission denied")


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    spec = {
        "outcome": "Test bounded outcome",
        "acceptance": ["Observable result"],
        "milestone": "infrastructure",
        "paths": ["tests/"],
    }
    backlog = tmp_path / "backlog.json"
    backlog.write_text(
        json.dumps(
            {
                "milestones": [{"key": "infrastructure", "description": "Infra"}],
                "tasks": [{"key": "example", "title": "Example", "spec": spec}],
            }
        )
    )
    monkeypatch.setattr(
        project, "report_links", lambda *args: ["[Report](https://example.invalid)"]
    )
    return {"backlog_path": backlog, "root": tmp_path}


def test_dry_run_never_writes(inputs):
    gh = FakeGitHub()
    result = project.sync_project(gh, **inputs)
    assert not gh.writes
    assert result["issues"] == 4  # merged, active, report index, proposed task
    assert (
        len([item for item in result["changes"] if item["action"] == "create-issue"])
        == 4
    )


def test_apply_idempotent_preserves_human_edits_and_rejected_scope(inputs):
    gh = FakeGitHub()
    project.sync_project(gh, apply=True, **inputs)
    assert len(gh.issues) == 4
    assert gh.issues[0]["state"] == "closed"
    assert "rejected model" in gh.issues[0]["body"]
    assert "not an executable task" in gh.issues[1]["body"]
    gh.issues[-1]["body"] += "\nHuman clarification."
    gh.issues[-1]["state"] = "closed"
    writes = len(gh.writes)
    result = project.sync_project(gh, apply=True, **inputs)
    assert len(gh.writes) == writes
    assert not result["changes"]
    assert gh.issues[-1]["body"].endswith("Human clarification.")
    assert gh.issues[-1]["state"] == "closed"


def test_interrupted_close_is_repaired(inputs):
    gh = FakeGitHub()
    project.sync_project(gh, apply=True, **inputs)
    gh.issues[0]["state"] = "open"
    result = project.sync_project(gh, apply=True, **inputs)
    assert result["changes"] == [{"action": "close-history", "key": "pr:1"}]
    assert gh.issues[0]["state"] == "closed"


def test_project_permission_failure_preserves_issues(inputs):
    gh = FakeGitHub()
    result = project.sync_project(gh, apply=True, number=1, **inputs)
    assert len(gh.issues) == 4
    assert "Project permission denied" in result["project_warning"]
    assert "Do not delete/recreate issues" in result["project_warning"]


def test_duplicate_existing_marker_fails_closed(inputs):
    gh = FakeGitHub()
    gh.issues = [{"body": project.marker("pr:1")}, {"body": project.marker("pr:1")}]
    with pytest.raises(ValueError, match="Duplicate backfill marker"):
        project.sync_project(gh, apply=True, **inputs)
    assert not gh.writes


def test_report_index_only_includes_committed_reports(tmp_path):
    class Result:
        stdout = "docs/BASELINE_REPORT.md\ndocs/notes.md\ndocs/image.png\n"

    original = project.subprocess.run
    try:
        project.subprocess.run = lambda args, **kwargs: (
            type("Revision", (), {"stdout": "abc\n"})()
            if "rev-parse" in args
            else Result()
        )
        links = project.report_links(tmp_path, "owner/repo", "abc")
    finally:
        project.subprocess.run = original
    assert links == [
        "[BASELINE_REPORT.md](https://github.com/owner/repo/blob/abc/docs/BASELINE_REPORT.md)"
    ]


def test_board_pagination_and_existing_card_preserved():
    class Board:
        def __init__(self):
            self.cursors = []
            self.mutations = []

        def graphql(self, query, **variables):
            if query.startswith("mutation"):
                self.mutations.append(variables)
                return {"addProjectV2ItemById": {"item": {"id": "new"}}}
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
                                            {"id": value, "name": value}
                                            for value in project.STATUS_OPTIONS
                                        ],
                                    }
                                ]
                            },
                        }
                    }
                }
            cursor = variables["cursor"]
            self.cursors.append(cursor)
            return {
                "node": {
                    "items": {
                        "nodes": [
                            {
                                "id": "existing",
                                "content": {"id": "I_1"},
                                "fieldValueByName": {"name": "Running"},
                            }
                        ]
                        if cursor
                        else [],
                        "pageInfo": {
                            "hasNextPage": cursor is None,
                            "endCursor": "next",
                        },
                    }
                }
            }

    gh = Board()
    result = project.sync_board(
        gh,
        "owner",
        1,
        [
            ({"number": 1, "node_id": "I_1"}, "Done"),
            ({"number": 2, "node_id": "I_2"}, "Ready"),
        ],
        apply=True,
    )
    assert gh.cursors == [None, "next"]
    assert result["add"] == [{"issue": 2, "status": "Ready"}]
    assert len(gh.mutations) == 2


def test_transport_paginates_all_pages(monkeypatch):
    gh = project.GitHub()
    calls = []
    monkeypatch.setattr(
        gh, "_run", lambda args: calls.append(args) or [[{"n": 1}], [{"n": 2}]]
    )
    assert gh.pages("repos/o/r/issues?state=all") == [{"n": 1}, {"n": 2}]
    assert "--paginate" in calls[0]
    assert "--slurp" in calls[0]


def test_create_project_reuses_existing_without_configuration_writes():
    class Existing:
        def graphql(self, query, **variables):
            assert query.startswith("query")
            return {
                "user": {
                    "id": "U",
                    "projectsV2": {
                        "nodes": [
                            {
                                "id": "P",
                                "number": 5,
                                "title": "Board",
                                "closed": False,
                                "public": False,
                            }
                        ],
                        "pageInfo": {"hasNextPage": False},
                    },
                }
            }

    assert project.create_private_project(Existing(), "owner", "Board")["number"] == 5


def test_create_project_is_private_and_initializes_new_options():
    class New:
        def __init__(self):
            self.writes = []

        def graphql(self, query, **variables):
            if "projectsV2(" in query:
                return {
                    "user": {
                        "id": "U",
                        "projectsV2": {
                            "nodes": [],
                            "pageInfo": {"hasNextPage": False},
                        },
                    }
                }
            if "createProjectV2(" in query:
                self.writes.append(query)
                return {"createProjectV2": {"projectV2": {"id": "P", "number": 1}}}
            if "fields(first" in query:
                return {"node": {"fields": {"nodes": [{"id": "S", "name": "Status"}]}}}
            self.writes.append(query)
            return {}

    gh = New()
    assert project.create_private_project(gh, "owner", "Board")["number"] == 1
    assert any("public:false" in query for query in gh.writes)
    assert any("singleSelectOptions" in query for query in gh.writes)
