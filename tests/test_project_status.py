"""Authoritative status projection never changes history or coordination state."""

from __future__ import annotations

import base64
import copy
import hashlib
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
        self.revision = "a" * 40
        self.tree_id = "b" * 40

    def raw_state(self):
        return json.dumps(self.state).encode()

    def api(self, path):
        self.reads.append(path)
        if "/git/ref/heads/" in path:
            assert path.endswith("/git/ref/heads/codex%2Fcoordination")
            self.raw = self.raw_state()
            self.blob_id = hashlib.sha1(
                f"blob {len(self.raw)}\0".encode() + self.raw
            ).hexdigest()
            return {
                "ref": "refs/heads/codex/coordination",
                "object": {"type": "commit", "sha": self.revision},
            }
        if path.endswith("/git/commits/" + self.revision):
            return {"sha": self.revision, "tree": {"sha": self.tree_id}}
        if path.endswith("/git/trees/" + self.tree_id):
            return {
                "sha": self.tree_id,
                "truncated": False,
                "tree": [
                    {
                        "path": "state.json",
                        "type": "blob",
                        "mode": "100644",
                        "size": len(self.raw),
                        "sha": self.blob_id,
                    }
                ],
            }
        if path.endswith("/git/blobs/" + self.blob_id):
            return {
                "sha": self.blob_id,
                "size": len(self.raw),
                "encoding": "base64",
                "content": base64.encodebytes(self.raw).decode(),
            }
        assert "/git/" not in path and "/contents/" not in path
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
    assert sum("/git/ref/heads/" in path for path in gh.reads) == 2
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
            if "/git/ref/heads/" in path and self.present:
                # The second attempt must project fresh state, not a stale
                # pre-failure snapshot, while the first write's result is unknown.
                self.state["tasks"]["40"]["status"] = "blocked"
            return super().api(path)

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


@pytest.mark.parametrize("size", [100, 1050479, 1090534])
def test_small_and_original_incident_sizes_project_complete_state(size):
    gh = FakeGitHub()
    # Include a status after the padding so prefix-only reads cannot pass.
    gh.state = {"version": 1, "history": "", "tasks": {"40": {"status": "running"}}}
    gh.state["history"] = "x" * (size - len(gh.raw_state()))
    assert len(gh.raw_state()) == size
    original = copy.deepcopy(gh.state)
    status.sync_status(gh, repo="o/r", owner="o", number=1)
    assert gh.writes[0]["value"] == "Running" and gh.state == original
    assert gh.reads[:4] == [
        "repos/o/r/git/ref/heads/codex%2Fcoordination",
        "repos/o/r/git/commits/" + gh.revision,
        "repos/o/r/git/trees/" + gh.tree_id,
        "repos/o/r/git/blobs/" + gh.blob_id,
    ]


def test_observed_contents_none_is_bypassed_without_following_urls():
    class LargeState(FakeGitHub):
        def api(self, path):
            if "/contents/" in path:
                return {
                    "size": 1050479,
                    "encoding": "none",
                    "content": "",
                    "sha": "469908320c4b96b420fa849c05e32cee0d4baa0f",
                    "download_url": "https://untrusted.invalid/credentials",
                }
            return super().api(path)

    gh = LargeState()
    gh.state["history"] = "x" * 1050479
    status.sync_status(gh, repo="o/r", owner="o", number=1)
    assert len(gh.writes) == 1
    assert not any("contents" in path or "https:" in path for path in gh.reads)


def test_branch_movement_does_not_mix_commit_tree_or_blob():
    class MovingBranch(FakeGitHub):
        def api(self, path):
            result = super().api(path)
            if "/git/ref/heads/" in path:
                self.state["tasks"]["40"]["status"] = "blocked"
                # The returned ref's commit is immutable. Simulate a new branch
                # tip without changing that commit's captured file bytes.
                self.new_branch_revision = "c" * 40
            return result

    gh = MovingBranch()
    status.sync_status(gh, repo="o/r", owner="o", number=1)
    assert gh.writes[0]["value"] == "Running"
    assert sum("/git/ref/heads/" in path for path in gh.reads) == 1
    assert all(gh.new_branch_revision not in path for path in gh.reads)


@pytest.mark.parametrize(
    "change",
    [
        "ref_name",
        "ref_type",
        "revision",
        "commit_id",
        "tree_id",
        "truncated",
        "missing_file",
        "duplicate_file",
        "symlink",
        "submodule",
        "file_type",
        "file_id",
        "zero_size",
        "oversized",
        "boolean_size",
        "blob_id",
        "blob_size",
        "blob_bool_size",
        "encoding",
        "empty",
        "invalid_base64",
        "nonstring",
        "truncated_content",
        "hash",
        "padded_huge",
        "missing_key",
        "null_tree",
        "null_blob",
    ],
)
def test_invalid_object_chain_fails_closed_and_is_sanitized(
    projection_run, capsys, monkeypatch, change
):
    class Corrupt(FakeGitHub):
        def api(self, path):
            result = super().api(path)
            if "/git/ref/heads/" in path:
                if change == "ref_name":
                    result["ref"] = "refs/heads/other"
                if change == "ref_type":
                    result["object"]["type"] = "tag"
                if change == "revision":
                    result["object"]["sha"] = "../../project-secret"
            if "/git/commits/" in path and change == "commit_id":
                result["sha"] = "c" * 40
            if "/git/trees/" in path:
                if change == "null_tree":
                    return None
                if change == "tree_id":
                    result["sha"] = "c" * 40
                if change == "truncated":
                    result["truncated"] = True
                if change == "missing_file":
                    result["tree"] = []
                if change == "duplicate_file":
                    result["tree"] *= 2
                entry = result["tree"][0] if result["tree"] else {}
                if change == "symlink":
                    entry["mode"] = "120000"
                if change == "submodule":
                    entry["mode"] = "160000"
                if change == "file_type":
                    entry["type"] = "tree"
                if change == "file_id":
                    entry["sha"] = "not-a-git-id"
                if change == "zero_size":
                    entry["size"] = 0
                if change == "oversized":
                    entry["size"] = status.MAX_STATE_BYTES + 1
                if change == "boolean_size":
                    entry["size"] = True
            if "/git/blobs/" in path:
                if change == "null_blob":
                    return None
                if change == "blob_id":
                    result["sha"] = "c" * 40
                if change == "blob_size":
                    result["size"] += 1
                if change == "blob_bool_size":
                    result["size"] = True
                if change == "encoding":
                    result["encoding"] = "none"
                if change == "empty":
                    result["content"] = ""
                if change == "invalid_base64":
                    result["content"] = "project-secret!"
                if change == "nonstring":
                    result["content"] = []
                if change == "truncated_content":
                    result["content"] = result["content"][:-5]
                if change == "hash":
                    result["content"] = base64.b64encode(b"x" * len(self.raw)).decode()
                if change == "padded_huge":
                    result["content"] = " " * (2 * status.MAX_STATE_BYTES + 1)
                if change == "missing_key":
                    del result["content"]
            return result

    monkeypatch.setattr(
        status,
        "sync_board",
        lambda *_a, **_kw: pytest.fail("Project write boundary reached"),
    )
    run, delays = projection_run
    gh = Corrupt()
    with pytest.raises(SystemExit, match="1"):
        run(gh)
    output = capsys.readouterr()
    assert "invalid coordination state" in output.err
    assert "project-secret" not in output.err + output.out
    assert not gh.writes and not delays
    assert not any("/issues/" in path for path in gh.reads)


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b"\xff",
        b"null",
        b"[]",
        b'{"version":2,"tasks":{}}',
        b'{"version":true,"tasks":{}}',
        b'{"version":1,"tasks":[]}',
        b'{"version":1,"version":1,"tasks":{}}',
        b'{"version":1,"tasks":{"40":{"status":"running","status":"done"}}}',
        b'{"version":1,"history":NaN,"tasks":{}}',
        b'{"version":1,"tasks":{"40":{"status":[]}}}',
        b'{"version":1,"tasks":{"40":{"status":"invented"}}}',
        b'{"version":1,"tasks":{"0":{"status":"running"}}}',
    ],
)
def test_invalid_complete_blob_json_or_schema_never_writes(
    projection_run, capsys, monkeypatch, raw
):
    class InvalidState(FakeGitHub):
        def raw_state(self):
            return raw

    monkeypatch.setattr(
        status,
        "sync_board",
        lambda *_a, **_kw: pytest.fail("Project write boundary reached"),
    )
    run, delays = projection_run
    gh = InvalidState()
    with pytest.raises(SystemExit, match="1"):
        run(gh)
    assert "Project projection failed:" in capsys.readouterr().err
    assert not gh.writes and not delays
