"""Offline client delivery failures retain one real request and its identity."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "scripts/agent_queue.py"
    spec = importlib.util.spec_from_file_location("generated_queue_client", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    shared = tmp_path / "shared"
    identity_path = shared / ".cache/agent-worker.json"
    identity_path.parent.mkdir(parents=True)
    identity = {"host_id": "generated-host", "session_id": "generated-session"}
    identity_path.write_text(json.dumps(identity), encoding="utf-8")
    before = identity_path.read_bytes()
    work = tmp_path / "linked-worktree"
    work.mkdir()
    monkeypatch.setattr(module, "ROOT", work)

    def git_identity(command, **kwargs):
        assert command == [
            "git",
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ]
        assert kwargs["cwd"] == work
        return str(shared / ".git") + "\n"

    monkeypatch.setattr(module.subprocess, "check_output", git_identity)
    monkeypatch.setattr(module.platform, "system", lambda: "GeneratedOS")
    monkeypatch.setattr(module.platform, "machine", lambda: "generated-arch")
    config = {"repository": "generated/repo", "coordination_branch": "generated"}
    monkeypatch.setattr(module, "load_config", lambda: config)

    class Transport:
        def __init__(self):
            self.writes = []
            self.at_post = None

        def pages(self, path):
            assert path == "issues?state=all&labels=agent-control&per_page=100"
            return [{"number": 74}]

        def repo(self, path, *, method, data):
            assert method in {"POST", "PATCH"}
            if self.at_post:
                self.at_post()
            self.writes.append((path, method, data))
            return {
                "id": 123,
                "html_url": "https://github.com/generated/repo/issues/74#issuecomment-123",
                "user": {"login": "generated-owner"},
            }

    transport = Transport()
    monkeypatch.setattr(module, "GitHub", lambda repo: transport)

    class State:
        def __init__(self, *args):
            pass

        def read(self):
            return "generated-tip", {"receipts": {}, "tasks": {}}

    monkeypatch.setattr(module, "StateStore", State)
    return module, transport, work, identity_path, before


def run(module, verb="checkpoint", request_id="generated-request", payload=None):
    args = [verb, "--request-id", request_id, "--wait", "0"]
    if verb != "register":
        args.extend(["--task", "223", "--epoch", "1"])
    if payload:
        args.extend(["--payload", str(payload)])
    module.main(args)


@pytest.mark.parametrize("verb", ["checkpoint", "register"])
def test_fresh_linked_worktree_prepares_receipt_before_post(client, verb, capsys):
    module, transport, work, identity_path, before = client
    assert not (work / ".cache").exists()

    def prepared():
        assert (work / ".cache").is_dir()

    transport.at_post = prepared
    run(module, verb)
    assert len(transport.writes) == 1
    assert transport.writes[0][:2] == ("issues/74/comments", "POST")
    saved = json.loads((work / ".cache/agent-last-request.json").read_bytes())
    assert saved["request"]["request_id"] == "generated-request"
    assert saved["request"]["verb"] == verb
    assert saved["request"]["host_id"] == "generated-host"
    assert saved["request"]["session_id"] == "generated-session"
    posted = (
        transport.writes[0][2]["body"].split("```json\n", 1)[1].split("\n```", 1)[0]
    )
    assert json.loads(posted) == saved["request"]
    assert identity_path.read_bytes() == before
    assert json.loads(capsys.readouterr().out)["request_id"] == "generated-request"


def test_first_heartbeat_and_existing_comment_patch_reuse(client, capsys):
    module, transport, work, identity_path, before = client
    run(module, "heartbeat", "heartbeat-first")
    index = work / ".cache/agent-heartbeat-comments.json"
    saved = index.read_bytes()
    assert json.loads(saved) == {
        "generated-host/generated-session/223/implementation": 123
    }
    run(module, "heartbeat", "heartbeat-second")
    assert [row[:2] for row in transport.writes] == [
        ("issues/74/comments", "POST"),
        ("issues/comments/123", "PATCH"),
    ]
    assert index.read_bytes() == saved
    assert identity_path.read_bytes() == before
    receipt = json.loads((work / ".cache/agent-last-request.json").read_bytes())
    assert receipt["request"]["request_id"] == "heartbeat-second"
    assert "heartbeat-second" in capsys.readouterr().out


def test_directory_preparation_failure_prevents_remote_write(client, monkeypatch):
    module, transport, work, _, _ = client
    original = Path.mkdir

    def denied(path, *args, **kwargs):
        if path == work / ".cache":
            raise PermissionError("generated-secret-must-not-appear")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", denied)
    with pytest.raises(ValueError) as failure:
        run(module)
    message = str(failure.value)
    assert "not submitted" in message and "PermissionError" in message
    assert "generated-secret" not in message
    assert transport.writes == []


@pytest.mark.parametrize(
    "filename", ["agent-last-request.json", "agent-heartbeat-comments.json"]
)
def test_post_success_local_write_failure_retains_actual_identity(
    client, monkeypatch, filename
):
    module, transport, work, _, _ = client
    cache = work / ".cache"
    cache.mkdir()
    pending = cache / "agent-last-request.json"
    pending.write_text('{"existing": true}\n', encoding="utf-8")
    before = pending.read_bytes()
    payload = work / "private-payload.json"
    payload.write_text(
        '{"checkpoint": {"private": "generated-private-payload"}}', encoding="utf-8"
    )
    original = Path.replace

    def denied(path, target):
        if Path(target) == cache / filename:
            raise PermissionError("generated-secret-must-not-appear")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", denied)
    verb = "heartbeat" if filename == "agent-heartbeat-comments.json" else "checkpoint"
    with pytest.raises(ValueError) as failure:
        run(module, verb, "actual-posted-request", payload)
    message = str(failure.value)
    assert "actual-posted-request" in message
    assert "https://github.com/generated/repo/issues/74#issuecomment-123" in message
    assert "PermissionError" in message and "same request ID" in message
    assert (
        "generated-secret" not in message and "generated-private-payload" not in message
    )
    assert len(transport.writes) == 1
    assert pending.read_bytes() == before
    assert not list(cache.glob("*.tmp"))


def test_status_remains_read_only_without_local_receipt_directory(client, capsys):
    module, transport, work, identity_path, before = client
    module.main(["status", "--request-id", "generated-request"])
    assert json.loads(capsys.readouterr().out) == {"status": "pending"}
    assert transport.writes == []
    assert not (work / ".cache").exists()
    assert identity_path.read_bytes() == before
