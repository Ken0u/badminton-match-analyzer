"""Exercise real transport/state boundaries without a network or merge token."""

import base64
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from devops.coordinator import (
    StateStore,
    collect,
    integrate,
    json_block,
    reconcile,
    rollout_policy,
)
from devops.github import GitHubError
from devops.policy import policy_errors, sensitive
from devops.queue import initial_state
from test_agent_queue import Harness

HEAD, BASE = "a" * 40, "b" * 40
CONFIG = {
    "repository": "Ken0u/badminton-match-analyzer",
    "mode": "active",
    "trusted_logins": ["Ken0u", "dootz1"],
    "human_approvers": ["Ken0u", "dootz1"],
    "coordination_branch": "codex/coordination",
    "milestones": ["Infrastructure"],
    "required_checks": ["ci/gate"],
    "sensitive_paths": [".github/", "AGENTS.md"],
}


def spec():
    return {
        "outcome": "Preserve timestamps",
        "acceptance": ["source PTS retained"],
        "exclusions": ["No model changes"],
        "paths": ["backend/time.py"],
        "capabilities": ["cpu"],
        "artifacts": {},
        "resources": [],
        "dependencies": [],
        "priority": 1,
        "milestone": "Infrastructure",
        "risk": "routine",
        "verification": ["pytest timing"],
        "limits": {},
    }


class FakeGitHub:
    def __init__(self):
        self.tip = None
        self.objects = {}
        self.calls = []
        self.issues = []
        self.comments = {}
        self.race = False

    def pages(self, path):
        if path.startswith("issues?"):
            return copy.deepcopy(self.issues)
        if path.startswith("issues/"):
            return copy.deepcopy(self.comments.get(int(path.split("/")[1]), []))
        raise AssertionError(path)

    def repo(self, path, *, method="GET", data=None, **kwargs):
        self.calls.append((path, method, copy.deepcopy(data)))
        if method == "GET":
            if path.startswith("git/ref/"):
                if not self.tip:
                    raise GitHubError("404 missing reference")
                return {"object": {"sha": self.tip}}
            return copy.deepcopy(self.objects[path.split("/")[-1]])
        if path in ("git/blobs", "git/trees", "git/commits"):
            key = str(len(self.objects) + 1)
            if path == "git/blobs":
                self.objects[key] = {
                    "content": base64.b64encode(data["content"].encode()).decode()
                }
            elif path == "git/trees":
                self.objects[key] = {"tree": data["tree"]}
            else:
                self.objects[key] = {
                    "tree": {"sha": data["tree"]},
                    "parents": data["parents"],
                }
            return {"sha": key}
        if path == "git/refs":
            if self.tip:
                raise GitHubError("422 existing ref")
            self.tip = data["sha"]
            return {}
        if path.startswith("git/refs/"):
            assert data["force"] is False
            if self.race:
                self.race = False
                raise GitHubError("422 conflicting update")
            self.tip = data["sha"]
            return {}
        raise AssertionError((path, method))


def issue(body, number=1, actor="Ken0u"):
    return {
        "id": number + 100,
        "number": number,
        "body": body,
        "state": "open",
        "created_at": "2026-10-18T00:00:00Z",
        "updated_at": "2026-10-18T00:00:00Z",
        "user": {"login": actor},
    }


def comment(payload, actor="Ken0u", id=1):
    return {
        "id": id,
        "user": {"login": actor},
        "created_at": f"2026-10-18T00:00:{id:02d}Z",
        "body": "<!-- agent-request:v1 -->\n```json\n" + json.dumps(payload) + "\n```",
    }


def test_orphan_state_roundtrip_and_no_force_updates():
    gh = FakeGitHub()
    store = StateStore(gh, CONFIG["coordination_branch"])
    assert store.read() == (None, initial_state())
    tip = store.write(None, initial_state())
    assert gh.objects[tip]["parents"] == []
    state = initial_state()
    state["paused"] = True
    next_tip = store.write(tip, state)
    assert store.read() == (next_tip, state)
    assert gh.objects[next_tip]["parents"] == [tip]


def test_collect_uses_authenticated_actor_and_ignores_external_comments():
    gh = FakeGitHub()
    gh.issues = [issue("control")]
    request = {"verb": "register", "request_id": "r", "actor": "github-actions[bot]"}
    gh.comments[1] = [comment(request), comment(request, "stranger", 2)]
    requests, _ = collect(gh, CONFIG)
    assert len(requests) == 1
    assert requests[0]["actor"] == "Ken0u"
    assert requests[0]["source_comment"] == 1


def test_comment_only_metadata_does_not_replan_active_spec():
    gh = FakeGitHub()
    gh.issues = [
        issue("<!-- agent-task:v1 -->\n```json\n" + json.dumps(spec()) + "\n```")
    ]
    first, _ = collect(gh, CONFIG)
    gh.issues[0]["updated_at"] = "2026-10-19T00:00:00Z"
    second, _ = collect(gh, CONFIG)
    assert first[0]["request_id"] == second[0]["request_id"]


def test_dropped_wakeup_duplicate_request_and_commit_race_recover():
    gh = FakeGitHub()
    gh.issues = [issue("control")]
    payload = {
        "request_id": "r",
        "verb": "register",
        "host_id": "mac",
        "session_id": "s",
        "capabilities": ["cpu"],
        "artifacts": {},
    }
    gh.comments[1] = [comment(payload)]
    state = reconcile(gh, CONFIG, now=100)
    assert state["receipts"]["r"]["status"] == "ok"
    tip = gh.tip
    assert reconcile(gh, CONFIG, now=101) == state
    assert gh.tip == tip
    gh.comments[1].append(
        comment({**payload, "request_id": "r2", "session_id": "s2"}, id=2)
    )
    gh.race = True
    state = reconcile(gh, CONFIG, now=102)
    assert state["receipts"]["r2"]["status"] == "ok"


def test_bad_request_does_not_starve_later_commands():
    gh = FakeGitHub()
    gh.issues = [issue("control")]
    gh.comments[1] = [
        comment({"request_id": "bad", "verb": "submit"}),
        comment(
            {
                "request_id": "good",
                "verb": "register",
                "host_id": "mac",
                "session_id": "s",
                "capabilities": [],
                "artifacts": {},
            },
            id=2,
        ),
    ]
    state = reconcile(gh, CONFIG, now=100)
    assert state["receipts"]["bad"]["status"] == "rejected"
    assert state["receipts"]["good"]["status"] == "ok"


def policy_fixture():
    task = {
        "task_id": "42",
        "status": "review",
        "spec": spec(),
        "spec_hash": "spec",
        "claim": {"session_id": "author"},
        "submission": {"head_sha": HEAD, "base_sha": BASE},
        "review": {
            "head_sha": HEAD,
            "base_sha": BASE,
            "spec_hash": "spec",
            "session_id": "reviewer",
            "verdict": "approve",
        },
    }
    pr = {
        "head": {
            "sha": HEAD,
            "ref": "codex/issue-42-time",
            "repo": {"full_name": CONFIG["repository"]},
        },
        "base": {"sha": BASE, "ref": "main"},
        "user": {"login": "dootz1"},
        "state": "open",
        "draft": False,
    }
    check = {
        "id": 1,
        "name": "ci/gate",
        "head_sha": HEAD,
        "status": "completed",
        "conclusion": "success",
        "app": {"slug": "github-actions"},
    }
    return task, pr, ["backend/time.py"], [check], [], CONFIG, BASE


def test_routine_policy_accepts_only_current_independent_evidence():
    args = policy_fixture()
    assert policy_errors(*args) == []
    args[0]["review"]["session_id"] = "author"
    assert "Fresh independent agent review required" in policy_errors(*args)


@pytest.mark.parametrize("change", ["head", "base", "scope", "check", "app", "draft"])
def test_policy_fences_changed_inputs(change):
    args = policy_fixture()
    if change == "head":
        args[1]["head"]["sha"] = "c" * 40
    elif change == "base":
        args[1]["base"]["sha"] = "c" * 40
    elif change == "scope":
        args[2].append("backend/other.py")
    elif change == "check":
        args[3][0]["conclusion"] = "skipped"
    elif change == "app":
        args[3][0]["app"]["slug"] = "another-app"
    else:
        args[1]["draft"] = True
    assert policy_errors(*args)


def test_sensitive_paths_require_non_author_current_human_approval():
    args = policy_fixture()
    args[0]["spec"]["paths"].append(".github/")
    args[2].append(".github/workflows/ci.yml")
    assert policy_errors(*args)
    args[4].append(
        {"id": 1, "user": {"login": "Ken0u"}, "state": "APPROVED", "commit_id": HEAD}
    )
    assert not policy_errors(*args)
    args[4].append(
        {"id": 2, "user": {"login": "Ken0u"}, "state": "DISMISSED", "commit_id": HEAD}
    )
    assert policy_errors(*args)


def test_issue_content_is_json_only_not_shell_code():
    assert json_block("ordinary issue $(touch /tmp/unsafe)", "agent-task:v1") is None
    with pytest.raises(ValueError):
        json_block("agent-task:v1\n```json\n[]\n```", "agent-task:v1")


def approved_state():
    h = Harness()
    h.plan()
    h.register()
    h.next()
    h.send(
        "submit",
        task_id="1",
        host_id="mac",
        session_id="mac1",
        epoch=1,
        head_sha=HEAD,
        base_sha=BASE,
        spec_hash=h.state["tasks"]["1"]["spec_hash"],
        pr_number=42,
    )
    h.register(host_id="mac", session_id="review")
    grant = h.send("review-next", host_id="mac", session_id="review")
    h.send(
        "review-result",
        task_id="1",
        host_id="mac",
        session_id="review",
        epoch=1,
        review_epoch=grant["claim"]["review_epoch"],
        head_sha=HEAD,
        base_sha=BASE,
        spec_hash=h.state["tasks"]["1"]["spec_hash"],
        verdict="approve",
        findings=[],
        reviewed_files=["backend/clock.py"],
        limitations=[],
        evidence=["pytest passed"],
    )
    return h


class MergeGitHub(FakeGitHub):
    def __init__(self):
        super().__init__()
        self.main = BASE
        self.merge_sha = "c" * 40
        self.pr = {
            "number": 42,
            "state": "open",
            "draft": False,
            "head": {
                "sha": HEAD,
                "ref": "codex/issue-1-fix",
                "repo": {"full_name": CONFIG["repository"]},
            },
            "base": {"sha": BASE, "ref": "main"},
            "user": {"login": "Ken0u"},
            "merged": False,
        }
        self.ci = []
        self.releases = []
        self.crash_before_merge = False
        self.lose_merge_response = False
        self.external = []

    def pages(self, path):
        if "/files?" in path:
            return [{"filename": "backend/clock.py"}]
        if "/reviews?" in path:
            return []
        return super().pages(path)

    def repo(self, path, *, method="GET", data=None, **kwargs):
        if path == "branches/main/protection":
            return {
                "required_status_checks": {
                    "strict": True,
                    "contexts": ["ci/gate", "automation/policy"],
                },
                "required_pull_request_reviews": {},
                "enforce_admins": {"enabled": True},
            }
        if path == "git/ref/heads/main":
            return {"object": {"sha": self.main}}
        if path.startswith("pulls/"):
            if method == "GET":
                return copy.deepcopy(self.pr)
            assert path.endswith("/merge") and data["sha"] == self.pr["head"]["sha"]
            if self.crash_before_merge:
                self.crash_before_merge = False
                raise GitHubError("simulated crash before merge")
            self.pr.update(merged=True, state="closed", merge_commit_sha=self.merge_sha)
            self.main = self.merge_sha
            if self.lose_merge_response:
                self.lose_merge_response = False
                raise GitHubError("merge response lost")
            return {"merged": True, "sha": self.merge_sha}
        if "/check-runs?" in path:
            return [
                {
                    "check_runs": [
                        {
                            "id": 1,
                            "name": "ci/gate",
                            "head_sha": self.pr["head"]["sha"],
                            "status": "completed",
                            "conclusion": "success",
                            "app": {"slug": "github-actions"},
                        }
                    ]
                }
            ]
        if path.startswith("actions/workflows/ci.yml/runs"):
            return {"workflow_runs": self.ci}
        if path.startswith("actions/workflows/release.yml/runs"):
            return {"workflow_runs": self.releases}
        if path == "issues" and method == "POST":
            value = issue(data["body"], number=900)
            self.issues.append(value)
            return value
        if (
            path == "check-runs"
            or (method == "PATCH" and path.startswith("issues/"))
            or (method == "POST" and path.startswith("actions/"))
        ):
            self.external.append((path, copy.deepcopy(data)))
            return {}
        return super().repo(path, method=method, data=data, **kwargs)


def merge_setup():
    h, gh = approved_state(), MergeGitHub()
    config = {
        **CONFIG,
        "coordinator_login": "github-actions[bot]",
        "milestones": ["M1", "Infrastructure"],
    }
    store = StateStore(gh, config["coordination_branch"])
    store.write(None, h.state)
    return gh, store, config


@pytest.mark.parametrize("lost", [False, True])
def test_journalled_merge_retry_and_response_loss(lost):
    gh, store, config = merge_setup()
    gh.lose_merge_response, gh.crash_before_merge = lost, not lost
    with pytest.raises(GitHubError):
        integrate(gh, config, store.read()[1])
    assert store.read()[1]["tasks"]["1"]["status"] == "integrating"
    if not lost:
        integrate(gh, config, store.read()[1])
    gh.ci = [
        {"id": 1, "event": "push", "head_sha": gh.merge_sha, "conclusion": "success"}
    ]
    state = integrate(gh, config, store.read()[1])
    assert state["tasks"]["1"]["status"] == "done"
    assert state["tasks"]["1"]["delivery_pending"] is True
    gh.releases = [
        {
            "id": 2,
            "display_title": f"Private candidate {gh.merge_sha}",
            "conclusion": "success",
            "html_url": "https://github.com/run/2",
        }
    ]
    state = integrate(gh, config, store.read()[1])
    assert state["tasks"]["1"]["delivery_pending"] is False


@pytest.mark.parametrize(
    "conclusion", ["failure", "cancelled", "skipped", "timed_out", "action_required"]
)
@pytest.mark.parametrize("mode", ["active", "pilot"])
def test_failed_verification_grants_only_a_bounded_repair(conclusion, mode):
    from devops.queue import apply_request

    gh, store, config = merge_setup()
    integrate(gh, config, store.read()[1])
    gh.ci = [
        {"id": 1, "event": "push", "head_sha": gh.merge_sha, "conclusion": conclusion}
    ]
    state = integrate(gh, config, store.read()[1])
    assert state["paused"] and state["tasks"]["900"]["repair_for"] == "1"
    config.update(mode=mode, pilot_tasks=[1])
    state = apply_request(
        state,
        {
            "request_id": "repair-worker",
            "verb": "register",
            "host_id": "win",
            "session_id": "win1",
            "capabilities": ["cpu"],
            "artifacts": {},
        },
        "dootz1",
        100,
        config,
    )
    state = apply_request(
        state,
        {
            "request_id": "repair-next",
            "verb": "next",
            "host_id": "win",
            "session_id": "win1",
            "baseline_sha": gh.merge_sha,
        },
        "dootz1",
        101,
        config,
    )
    assert state["receipts"]["repair-next"]["task_id"] == "900"


def test_malformed_request_id_does_not_starve_queue():
    gh = FakeGitHub()
    gh.issues = [issue("control")]
    gh.comments[1] = [
        comment({"request_id": [], "verb": "register"}),
        comment(
            {
                "request_id": "valid",
                "verb": "register",
                "host_id": "mac",
                "session_id": "s",
                "capabilities": [],
                "artifacts": {},
            },
            id=2,
        ),
    ]
    assert reconcile(gh, CONFIG, now=100)["receipts"]["valid"]["status"] == "ok"


def test_closed_ready_issue_cannot_be_claimed():
    h = Harness()
    h.plan()
    h.register()
    gh = FakeGitHub()
    gh.issues = [issue("task")]
    gh.issues[0]["state"] = "closed"
    StateStore(gh, CONFIG["coordination_branch"]).write(None, h.state)
    state = reconcile(gh, {**CONFIG, "milestones": ["M1"]}, now=101)
    assert state["tasks"]["1"]["status"] == "blocked"


def test_expired_code_checkpoint_can_transfer_but_resource_jobs_cannot():
    from devops.queue import LEASE_SECONDS, QueueError

    for resources in ([], ["gpu:windows"]):
        h = Harness()
        h.plan(resources=resources)
        h.register()
        h.next()
        h.now += LEASE_SECONDS + 1
        h.register(actor="dootz1", host_id="win", session_id="win1")
        payload = {
            "task_id": "1",
            "host_id": "win",
            "session_id": "win1",
            "epoch": 1,
            "checkpoint": {
                "branch": h.state["tasks"]["1"]["claim"]["branch"],
                "head_sha": HEAD,
            },
        }
        if resources:
            with pytest.raises(QueueError):
                h.send("recover", actor="dootz1", **payload)
        else:
            h.send("recover", actor="dootz1", **payload)
            assert h.state["tasks"]["1"]["status"] == "ready"


def test_repair_verification_resumes_queue_and_preserves_original_failure():
    from devops.queue import apply_request

    gh, store, config = merge_setup()
    integrate(gh, config, store.read()[1])
    original_merge = gh.merge_sha
    gh.ci = [
        {"id": 1, "event": "push", "head_sha": original_merge, "conclusion": "failure"}
    ]
    state = integrate(gh, config, store.read()[1])
    counter = 0

    def send(verb, **fields):
        nonlocal state, counter
        counter += 1
        request = {
            "request_id": f"fix-{counter}",
            "verb": verb,
            "host_id": "win",
            "session_id": "fixer",
            **fields,
        }
        state = apply_request(state, request, "dootz1", 100 + counter, config)
        return state["receipts"][request["request_id"]]

    send("register", capabilities=["cpu"], artifacts={})
    send("next", baseline_sha=original_merge)
    repaired_head = "d" * 40
    digest = state["tasks"]["900"]["spec_hash"]
    send(
        "submit",
        task_id="900",
        epoch=1,
        spec_hash=digest,
        head_sha=repaired_head,
        base_sha=original_merge,
        pr_number=43,
    )
    send("register", session_id="fix-reviewer", capabilities=["cpu"], artifacts={})
    grant = send("review-next", session_id="fix-reviewer")
    send(
        "review-result",
        session_id="fix-reviewer",
        task_id="900",
        epoch=1,
        review_epoch=grant["claim"]["review_epoch"],
        spec_hash=digest,
        head_sha=repaired_head,
        base_sha=original_merge,
        verdict="approve",
        findings=[],
        reviewed_files=["backend/clock.py"],
        limitations=[],
        evidence=["repair regression passes"],
    )
    store.write(store.read()[0], state)
    gh.pr.update(
        number=43,
        merged=False,
        state="open",
        head={
            "sha": repaired_head,
            "ref": "codex/issue-900-repair",
            "repo": {"full_name": CONFIG["repository"]},
        },
        base={"sha": original_merge, "ref": "main"},
    )
    gh.merge_sha = "e" * 40
    integrate(gh, config, store.read()[1])
    gh.ci = [
        {"id": 2, "event": "push", "head_sha": gh.merge_sha, "conclusion": "success"}
    ]
    result = integrate(gh, config, store.read()[1])
    assert result["paused"] is False
    assert result["tasks"]["900"]["status"] == "done"
    assert result["tasks"]["1"]["verified_by_repair"] == gh.merge_sha
    assert result["tasks"]["1"]["merge_sha"] == original_merge
    assert result["tasks"]["1"]["integration_error"]


def test_publishing_failure_keeps_outbox_until_verified_completion():
    gh, store, config = merge_setup()
    integrate(gh, config, store.read()[1])
    gh.ci = [
        {"id": 1, "event": "push", "head_sha": gh.merge_sha, "conclusion": "success"}
    ]
    integrate(gh, config, store.read()[1])
    gh.releases = [
        {
            "id": 2,
            "display_title": f"Private candidate {gh.merge_sha}",
            "conclusion": "failure",
            "status": "completed",
            "html_url": "run/2",
        }
    ]
    result = integrate(gh, config, store.read()[1])
    assert result["tasks"]["1"]["delivery_pending"]
    assert any(
        path == "actions/runs/2/rerun-failed-jobs" for path, _data in gh.external
    )
    gh.releases[0].update(conclusion="success")
    assert not integrate(gh, config, store.read()[1])["tasks"]["1"]["delivery_pending"]


def test_windows_probe_resolves_command_script(monkeypatch, tmp_path):
    from devops import environment

    calls = []
    monkeypatch.setattr(environment.shutil, "which", lambda _name: "C:/node/npm.cmd")
    monkeypatch.setattr(
        environment.subprocess,
        "run",
        lambda command, **_kw: (
            calls.append(command) or type("Result", (), {"returncode": 0})()
        ),
    )
    assert environment.probe(["npm", "--version"], tmp_path)["ok"]
    assert calls == [["C:/node/npm.cmd", "--version"]]


@pytest.mark.parametrize(
    "path",
    [
        "scripts/agent_queue.py",
        "scripts/project_status.py",
        "scripts/release_candidate.py",
        "scripts/setup_automation.py",
        "scripts/backfill_project.py",
        "scripts/devops/coordinator.py",
        ".github/workflows/agent-queue.yml",
    ],
)
def test_every_privileged_entrypoint_requires_human_review(path):
    config = json.loads(
        (Path(__file__).resolve().parents[1] / ".github/automation.json").read_text()
    )
    assert sensitive([path], config)


def test_controller_project_token_and_base_checkout_contract():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/agent-queue.yml"
    ).read_text()
    assert "pull_request_target:" in workflow and "  pull_request:" not in workflow
    assert "ref: main" in workflow
    assert "AGENT_PROJECT_TOKEN: ${{ secrets.AGENT_PROJECT_TOKEN }}" in workflow
    assert "Private candidates" in workflow


def test_native_inference_evidence_is_bound_to_source_model_and_code():
    args = list(policy_fixture())
    args[5] = {**CONFIG, "native_evidence_paths": ["backend/time.py"]}
    assert policy_errors(*args)
    args[0]["submission"]["native_evidence"] = {
        "code_sha": HEAD,
        "source_sha256": "a" * 64,
        "model_sha256": "b" * 64,
        "receipt_sha256": "c" * 64,
        "limitations": ["Development coverage only"],
    }
    assert not policy_errors(*args)
    args[0]["submission"]["native_evidence"]["code_sha"] = BASE
    assert policy_errors(*args)


@pytest.mark.parametrize(
    "before,after", [("observation", "pilot"), ("pilot", "active")]
)
@pytest.mark.parametrize(
    "defect", [None, "policy", "approval", "ci", "base", "extra_path"]
)
def test_rollout_policy_is_narrow_and_never_merges(before, after, defect):
    _, pr, _, checks, reviews, _, _ = policy_fixture()
    config = {**copy.deepcopy(CONFIG), "mode": before, "pilot_tasks": [1, 2]}
    proposed = {**copy.deepcopy(config), "mode": after}
    changed = [
        {"filename": ".github/automation.json", "status": "modified", "sha": HEAD}
    ]
    reviews.append(
        {"id": 1, "user": {"login": "Ken0u"}, "state": "APPROVED", "commit_id": HEAD}
    )
    if defect == "policy":
        proposed["trusted_logins"] = ["stranger"]
    elif defect == "approval":
        reviews[0]["commit_id"] = BASE
    elif defect == "ci":
        checks[0]["conclusion"] = "skipped"
    elif defect == "base":
        pr["base"]["sha"] = HEAD
    elif defect == "extra_path":
        changed.append({"filename": ".github/workflows/ci.yml"})

    class RolloutGitHub:
        def __init__(self):
            self.verdict = None

        def pages(self, path):
            if path.startswith("pulls?"):
                return [{"number": 1}]
            if path.endswith("/files?per_page=100"):
                return changed
            if path.endswith("/reviews?per_page=100"):
                return reviews
            raise AssertionError(path)

        def repo(self, path, *, method="GET", data=None, **kwargs):
            if path == "git/ref/heads/main":
                return {"object": {"sha": BASE}}
            if path == "pulls/1":
                return pr
            if path.startswith("git/blobs/"):
                return {
                    "content": base64.b64encode(json.dumps(proposed).encode()).decode()
                }
            if "/check-runs?" in path:
                return [{"check_runs": checks}]
            if path == "check-runs" and method == "POST":
                self.verdict = data["conclusion"]
                return {}
            raise AssertionError((path, method))

    gh = RolloutGitHub()
    rollout_policy(gh, config)
    assert gh.verdict == (
        "success" if defect is None else None if defect == "extra_path" else "failure"
    )


def test_missing_recovery_branch_rejects_only_that_request():
    class MissingRefGitHub(FakeGitHub):
        def repo(self, path, **kwargs):
            if path.startswith("git/ref/heads/codex/issue-"):
                raise GitHubError("404 missing worker branch")
            return super().repo(path, **kwargs)

    gh = MissingRefGitHub()
    h = Harness()
    h.plan()
    h.register()
    h.next()
    branch = h.state["tasks"]["1"]["claim"]["branch"]
    gh.issues = [issue("control")]
    gh.comments[1] = [
        comment(
            {
                "request_id": "missing-branch",
                "verb": "recover",
                "task_id": "1",
                "checkpoint": {"branch": branch, "head_sha": HEAD},
            }
        ),
        comment(
            {
                "request_id": "later",
                "verb": "register",
                "host_id": "win",
                "session_id": "win1",
                "capabilities": ["cpu"],
                "artifacts": {},
            },
            id=2,
        ),
    ]
    StateStore(gh, CONFIG["coordination_branch"]).write(None, h.state)
    state = reconcile(gh, CONFIG, now=999999)
    assert state["receipts"]["missing-branch"]["status"] == "rejected"
    assert state["receipts"]["later"]["status"] == "ok"
    assert state["tasks"]["1"]["status"] == "recovery_required"
    assert state["tasks"]["1"]["claim"]["branch"] == branch


@pytest.mark.parametrize("timely", [True, False])
def test_delayed_watchdog_uses_authenticated_heartbeat_time(timely):
    from datetime import datetime, timezone

    from devops.queue import LEASE_SECONDS

    gh = FakeGitHub()
    h = Harness()
    h.plan()
    h.register()
    h.next()
    expiry = h.state["tasks"]["1"]["claim"]["expires_at"]
    received = expiry - 30 if timely else expiry + 1
    payload = {
        "request_id": "heartbeat",
        "verb": "heartbeat",
        "task_id": "1",
        "host_id": "mac",
        "session_id": "mac1",
        "epoch": 1,
        "timestamp": expiry - 60,
    }
    message = comment(payload)
    message["body"] = message["body"].replace("agent-request:v1", "agent-heartbeat:v1")
    message["updated_at"] = datetime.fromtimestamp(received, timezone.utc).isoformat()
    gh.issues = [issue("control")]
    gh.comments[1] = [message]
    StateStore(gh, CONFIG["coordination_branch"]).write(None, h.state)
    state = reconcile(gh, CONFIG, now=expiry + 30)
    task = state["tasks"]["1"]
    assert task["status"] == ("running" if timely else "recovery_required")
    if timely:
        assert task["claim"]["expires_at"] == received + LEASE_SECONDS
        assert state["receipts"]["heartbeat"]["status"] == "running"
    else:
        assert state["receipts"]["heartbeat"]["status"] == "rejected"


def test_exhausted_publication_does_not_starve_a_later_merge():
    gh, store, config = merge_setup()
    tip, state = store.read()
    old = copy.deepcopy(state["tasks"]["1"])
    old.update(
        status="done", merge_sha="f" * 40, delivery_pending=True, delivery_attempts=3
    )
    state["tasks"]["0"] = old
    store.write(tip, state)
    gh.releases = [
        {
            "id": 2,
            "display_title": "Private candidate " + "f" * 40,
            "conclusion": "failure",
            "status": "completed",
            "html_url": "run/2",
        }
    ]
    result = integrate(gh, config, store.read()[1])
    assert result["tasks"]["0"]["delivery_error"]
    assert result["tasks"]["0"]["delivery_pending"]
    assert result["tasks"]["1"]["status"] == "integrating"
    assert gh.pr["merged"] is True
