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
from test_agent_queue import Harness, terminal_proof

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
            key = f"{len(self.objects) + 1:040x}"
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


def scope_fixture(*, explicit_plan=False):
    gh = FakeGitHub()
    original = spec()
    body = "Human context\n<!-- agent-task:v1 -->\n```json\n"
    body += json.dumps(original) + "\n```\nKeep concurrent notes."
    gh.issues = [issue("control" if explicit_plan else body)]
    messages = []
    if explicit_plan:
        messages.append(
            comment(
                {
                    "request_id": "old-plan",
                    "verb": "plan",
                    "task_id": "1",
                    "spec": original,
                }
            )
        )
    messages.extend(
        [
            comment(
                {
                    "request_id": "worker",
                    "verb": "register",
                    "host_id": "mac",
                    "session_id": "s",
                    "capabilities": ["cpu"],
                    "artifacts": {},
                },
                id=2,
            ),
            comment(
                {
                    "request_id": "claim",
                    "verb": "next",
                    "host_id": "mac",
                    "session_id": "s",
                    "baseline_sha": BASE,
                },
                id=3,
            ),
        ]
    )
    gh.comments[1] = messages
    state = reconcile(gh, CONFIG, now=100)
    assert state["tasks"]["1"]["status"] == "running"
    return gh, original, body


def test_committed_extension_survives_old_issue_plan_and_safe_body_sync():
    gh, original, body = scope_fixture()
    expanded = {**original, "paths": [*original["paths"], "tests/test_time.py"]}
    extension = {
        "request_id": "extension",
        "verb": "extend-scope",
        "task_id": "1",
        "host_id": "mac",
        "session_id": "s",
        "epoch": 1,
        "spec": expanded,
    }
    gh.comments[1].append(comment(extension, id=4))
    gh.race = True  # Retry the extension transaction after a concurrent commit.
    state = reconcile(gh, CONFIG, now=101)
    granted = copy.deepcopy(state["tasks"]["1"])
    assert granted["spec"] == expanded
    # Re-reading the original accepted issue is safe after extension, even if a
    # prior state commit response was lost. No worker must race an issue edit.
    for now in (102, 103):
        assert reconcile(gh, CONFIG, now=now)["tasks"]["1"] == granted
    assert gh.issues[0]["body"] == body
    # A human can synchronize just the JSON after acknowledgement. Additional
    # human text does not become a new task or disappear during reconciliation.
    gh.issues[0]["body"] = body.replace(json.dumps(original), json.dumps(expanded))
    gh.issues[0]["body"] += "\nAnother collaborator's new note."
    synchronized = copy.deepcopy(gh.issues)
    synchronized_request = collect(gh, CONFIG)[0][0]["request_id"]
    for now in (104, 105):
        result = reconcile(gh, CONFIG, now=now)
        assert result["tasks"]["1"] == granted
        assert result["receipts"][synchronized_request]["status"] == "running"
    assert gh.issues == synchronized
    assert not any(
        path.startswith("issues/") and method != "GET" for path, method, _ in gh.calls
    )


@pytest.mark.parametrize("replay", ["identical", "actor", "payload", "new-unapproved"])
def test_accepted_predecessor_plan_authenticates_before_fencing(replay):
    gh, original, _ = scope_fixture(explicit_plan=True)
    # Release and legitimately replace before claiming a newer frozen plan.
    gh.comments[1].extend(
        [
            comment(
                {
                    "request_id": "release",
                    "verb": "release",
                    "task_id": "1",
                    "host_id": "mac",
                    "session_id": "s",
                    "epoch": 1,
                    "checkpoint": {"branch": "preserved", "head_sha": HEAD},
                    "terminal_proof": terminal_proof(),
                },
                id=4,
            ),
            comment(
                {
                    "request_id": "new-plan",
                    "verb": "plan",
                    "task_id": "1",
                    "spec": {**original, "paths": ["backend/new_time.py"]},
                },
                id=5,
            ),
            comment(
                {
                    "request_id": "new-claim",
                    "verb": "next",
                    "host_id": "mac",
                    "session_id": "s",
                    "baseline_sha": BASE,
                },
                id=6,
            ),
        ]
    )
    state = reconcile(gh, CONFIG, now=101)
    granted = copy.deepcopy(state["tasks"]["1"])
    assert granted["status"] == "running"
    message = copy.deepcopy(gh.comments[1][0])
    if replay == "actor":
        message["user"]["login"] = "dootz1"
    elif replay in {"payload", "new-unapproved"}:
        payload = {
            "request_id": "old-plan" if replay == "payload" else "unapproved",
            "verb": "plan",
            "task_id": "1",
            "spec": {**original, "paths": ["backend/arbitrary.py"]},
        }
        message = comment(payload, id=7)
    gh.comments[1] = [message]
    for now in (102, 103):
        state = reconcile(gh, CONFIG, now=now)
        if replay == "new-unapproved":
            assert state["tasks"]["1"]["status"] == "recovery_required"
            assert state["tasks"]["1"]["claim"] == granted["claim"]
        else:
            assert state["tasks"]["1"] == granted


def test_invalid_request_identity_cannot_fence_a_grant():
    gh, original, _ = scope_fixture(explicit_plan=True)
    before = copy.deepcopy(StateStore(gh, CONFIG["coordination_branch"]).read()[1])
    gh.comments[1] = [
        comment(
            {
                "request_id": "bad id",
                "verb": "plan",
                "task_id": "1",
                "spec": {**original, "paths": ["backend/other.py"]},
            }
        )
    ]
    result = reconcile(gh, CONFIG, now=101)
    assert result["tasks"] == before["tasks"]


def test_replay_payload_cannot_fence_another_task():
    gh, original, _ = scope_fixture(explicit_plan=True)
    store = StateStore(gh, CONFIG["coordination_branch"])
    tip, state = store.read()
    state["tasks"]["2"] = copy.deepcopy(state["tasks"]["1"])
    state["tasks"]["2"]["spec"]["paths"] = ["backend/other.py"]
    from devops.queue import spec_hash

    state["tasks"]["2"]["spec_hash"] = spec_hash(state["tasks"]["2"]["spec"])
    state["tasks"]["2"]["claim"]["spec_hash"] = state["tasks"]["2"]["spec_hash"]
    store.write(tip, state)
    gh.comments[1] = [
        comment(
            {"request_id": "old-plan", "verb": "plan", "task_id": "2", "spec": original}
        )
    ]
    result = reconcile(gh, CONFIG, now=101)
    assert result == state


def policy_fixture():
    task = {
        "task_id": "42",
        "status": "review",
        "spec": spec(),
        "spec_hash": "spec",
        "epoch": 1,
        "claim": {"session_id": "author", "spec_hash": "spec", "epoch": 1},
        "submission": {"head_sha": HEAD, "base_sha": BASE, "spec_hash": "spec"},
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


@pytest.mark.parametrize("sensitive_path", [False, True])
def test_sensitive_or_risk_human_scope_keeps_owner_authorization_without_pr_review(
    sensitive_path,
):
    args = policy_fixture()
    if sensitive_path:
        args[0]["spec"]["paths"].append(".github/")
        args[2].append(".github/workflows/ci.yml")
    else:
        args[0]["spec"]["risk"] = "human"
    assert policy_errors(*args)
    # A PR approval cannot authorize an unapproved frozen task scope.
    args[4].append(
        {"id": 1, "user": {"login": "Ken0u"}, "state": "APPROVED", "commit_id": HEAD}
    )
    assert policy_errors(*args)
    args[4].clear()
    args[0]["human_approval"] = {"actor": "dootz1", "spec_hash": "spec", "at": 100}
    assert not policy_errors(*args)
    # The owner can also be the PR author; no second human approval is required.
    args[0]["human_approval"]["actor"] = "Ken0u"
    assert not policy_errors(*args)
    args[4].append(
        {"id": 2, "user": {"login": "Ken0u"}, "state": "DISMISSED", "commit_id": HEAD}
    )
    assert not policy_errors(*args)


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

    def graphql(self, _query, **_variables):
        return {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }

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
        if path.startswith("compare/"):
            return {"status": "ahead", "merge_base_commit": {"sha": self.main}}
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


def optional_merge_setup():
    gh, store, config = merge_setup()
    config.update(require_agent_review=False, candidate_visibility="public")
    tip, state = store.read()
    state["tasks"]["1"].pop("review")
    store.write(tip, state)
    return gh, store, config


@pytest.mark.parametrize("reviewed", [False, True])
def test_optional_review_controller_merges_verifies_main_and_completes_public_delivery(
    reviewed,
):
    gh, store, config = optional_merge_setup()
    if reviewed:
        # Use an actual distinct-session queue review; never manufacture approval.
        h = approved_state()
        store.write(store.read()[0], h.state)
    state = integrate(gh, config, store.read()[1])
    task = state["tasks"]["1"]
    assert task["status"] == "integrating" and gh.pr["merged"] is True
    assert ("review" in task) is reviewed
    state = integrate(gh, config, store.read()[1])
    assert state["tasks"]["1"]["status"] == "verifying_main"
    gh.ci = [
        {
            "id": 10,
            "event": "push",
            "head_branch": "main",
            "head_sha": gh.merge_sha,
            "status": "completed",
            "conclusion": "success",
        }
    ]
    state = integrate(gh, config, store.read()[1])
    assert state["tasks"]["1"]["status"] == "done"
    assert state["tasks"]["1"]["delivery_pending"] is True
    assert config["candidate_visibility"] == "public"
    assert any(
        path == "actions/workflows/release.yml/dispatches"
        and data["inputs"]["source_sha"] == gh.merge_sha
        for path, data in gh.external
    )
    # The existing release workflow retains its historical run title in public mode.
    gh.releases = [
        {
            "id": 11,
            "display_title": f"Private candidate {gh.merge_sha}",
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://github.com/run/11",
        }
    ]
    state = integrate(gh, config, store.read()[1])
    task = state["tasks"]["1"]
    assert task["delivery_pending"] is False
    assert task["candidate_run"] == "https://github.com/run/11"
    assert ("review" in task) is reviewed
    assert integrate(gh, config, store.read()[1]) == state


@pytest.mark.parametrize("setting", [None, True, 0, "false", [], {}])
def test_controller_missing_review_is_blocked_for_default_and_invalid_config(setting):
    gh, store, config = optional_merge_setup()
    config["require_agent_review"] = setting
    state = integrate(gh, config, store.read()[1])
    assert state["tasks"]["1"]["status"] == "review"
    assert gh.pr["merged"] is False


@pytest.mark.parametrize(
    "defect", ["conversation", "ancestry", "owner", "native", "changes", "reservation"]
)
def test_optional_controller_retains_nonapproval_vetoes(defect):
    gh, store, config = optional_merge_setup()
    if defect == "conversation":
        gh.graphql = lambda *_args, **_kwargs: {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [{"isResolved": False}],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }
    elif defect == "ancestry":
        original_repo = gh.repo
        gh.repo = lambda path, **kwargs: (
            {"status": "diverged", "merge_base_commit": {"sha": "f" * 40}}
            if path.startswith("compare/")
            else original_repo(path, **kwargs)
        )
    elif defect == "native":
        config["native_evidence_paths"] = ["backend/clock.py"]
    else:
        tip, state = store.read()
        task = state["tasks"]["1"]
        if defect == "owner":
            task["spec"]["risk"] = "human"
        elif defect == "changes":
            task["review"] = {**task["submission"], "verdict": "changes"}
        else:
            task["review_claim"] = {
                "session_id": "actual-fresh-review",
                "expires_at": 9999999999,
            }
        store.write(tip, state)
    state = integrate(gh, config, store.read()[1])
    assert gh.pr["merged"] is False
    assert state["tasks"]["1"]["status"] == "review"


def test_external_review_merge_is_fenced_without_adoption_or_duplicate_incidents():
    gh, store, config = merge_setup()
    original = copy.deepcopy(store.read()[1]["tasks"]["1"])
    gh.pr.update(
        merged=True,
        state="closed",
        merge_commit_sha=gh.merge_sha,
        merged_by={"login": "dootz1"},
        html_url="https://github.com/Ken0u/badminton-match-analyzer/pull/42",
    )
    gh.main = gh.merge_sha
    state = integrate(gh, config, store.read()[1])
    task = state["tasks"]["1"]
    assert task["status"] == "recovery_required"
    assert task["claim"] == original["claim"]
    assert task["submission"] == original["submission"]
    assert task["review"] == original["review"]
    assert task["external_merge"]["original"]["review"] == original["review"]
    assert task["external_merge"]["observed"]["merge_sha"] == gh.merge_sha
    assert task["external_merge"]["observed"]["merged_by"] == "dootz1"
    assert "merge_sha" not in task and not task.get("delivery_pending")
    assert not gh.external
    assert len(gh.issues) == 1
    again = integrate(gh, config, store.read()[1])
    assert again == state
    assert len(gh.issues) == 1


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


@pytest.mark.parametrize("mode", ["active", "pilot"])
@pytest.mark.parametrize("kind", ["risk_human", "sensitive_file", "ancestor_scope"])
def test_sensitive_main_repair_has_its_own_owner_authorization_and_completes(
    mode, kind
):
    from devops.queue import QueueError, apply_request, spec_hash

    gh, store, config = merge_setup()
    config["human_approvers"] = ["Ken0u"]
    tip, state = store.read()
    original = state["tasks"]["1"]
    if kind == "risk_human":
        original["spec"]["risk"] = "human"
    else:
        config["sensitive_paths"] = ["backend/clock.py"]
        if kind == "ancestor_scope":
            original["spec"]["paths"] = ["backend/"]
    digest = spec_hash(original["spec"])
    original["spec_hash"] = digest
    for field in ("claim", "submission", "review"):
        original[field]["spec_hash"] = digest
    original["human_approval"] = {"actor": "Ken0u", "spec_hash": digest, "at": 90}
    store.write(tip, state)
    integrate(gh, config, store.read()[1])
    failed_sha = gh.merge_sha
    gh.ci = [
        {"id": 1, "event": "push", "head_sha": failed_sha, "conclusion": "failure"}
    ]
    state = integrate(gh, config, store.read()[1])
    repair = state["tasks"]["900"]
    assert state["paused"] and repair["repair_for"] == "1"
    assert repair["status"] == "needs_human" and repair["spec"]["risk"] == "human"
    assert "human_approval" not in repair and repair["spec_hash"] != digest
    config.update(mode=mode, pilot_tasks=[1])
    counter = 0

    def send(verb, actor="Ken0u", **fields):
        nonlocal state, counter
        counter += 1
        request = {"verb": verb, "request_id": f"repair-life-{counter}", **fields}
        state = apply_request(state, request, actor, 110 + counter, config)
        return state["receipts"][request["request_id"]]

    worker = {"host_id": "win", "session_id": "repair-impl"}
    send("register", **worker, capabilities=["cpu"], artifacts={})
    assert (
        send("next", task_id="900", **worker, baseline_sha=failed_sha)["status"]
        == "idle"
    )
    with pytest.raises(QueueError, match="approver"):
        send(
            "human-approved",
            actor="dootz1",
            task_id="900",
            spec_hash=repair["spec_hash"],
        )
    with pytest.raises(QueueError, match="hash"):
        send("human-approved", task_id="900", spec_hash=digest)
    send("human-approved", task_id="900", spec_hash=repair["spec_hash"])
    assert state["tasks"]["900"]["repair_for"] == "1"
    grant = send("next", task_id="900", **worker, baseline_sha=failed_sha)
    assert grant["status"] == "granted"
    gh.pr.update(number=900, merged=False, state="open")
    gh.pr.pop("merge_commit_sha", None)
    gh.pr["head"].update(sha="d" * 40, ref=grant["claim"]["branch"])
    gh.pr["base"]["sha"] = failed_sha
    binding = {
        "head_sha": "d" * 40,
        "base_sha": failed_sha,
        "spec_hash": repair["spec_hash"],
    }
    send("submit", task_id="900", epoch=1, **worker, pr_number=900, **binding)
    assert send("review-next", task_id="900", **worker)["status"] == "idle"
    reviewer = {"host_id": "win", "session_id": "repair-review"}
    send("register", **reviewer, capabilities=["cpu"], artifacts={})
    review = send("review-next", task_id="900", **reviewer)
    assert review["status"] == "granted"
    send(
        "review-result",
        task_id="900",
        epoch=1,
        review_epoch=review["claim"]["review_epoch"],
        **reviewer,
        **binding,
        verdict="approve",
        findings=[],
        reviewed_files=["backend/clock.py"],
        limitations=[],
        evidence=["Independent repair regression checks passed"],
    )
    # No human PR review is supplied by the fake transport; scope approval is separate.
    store.write(store.read()[0], state)
    gh.merge_sha = "e" * 40
    state = integrate(gh, config, store.read()[1])
    assert state["tasks"]["900"]["status"] == "integrating" and gh.pr["merged"]
    assert state["paused"]
    gh.ci = [
        {
            "id": 2,
            "event": "push",
            "head_branch": "main",
            "head_sha": gh.merge_sha,
            "status": "completed",
            "conclusion": "success",
        }
    ]
    gh.releases = [
        {
            "id": 3,
            "display_title": f"Private candidate {gh.merge_sha}",
            "status": "completed",
            "conclusion": "success",
            "html_url": "run/3",
        }
    ]
    state = integrate(gh, config, store.read()[1])
    assert state["tasks"]["900"]["status"] == "done" and not state["paused"]
    assert state["tasks"]["900"]["delivery_pending"] is False
    assert state["tasks"]["1"]["status"] == "done"
    assert state["tasks"]["1"]["merge_sha"] == failed_sha
    assert state["tasks"]["1"]["verified_by_repair"] == gh.merge_sha


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
def test_every_privileged_entrypoint_is_sensitive(path):
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


def test_candidate_workflow_separates_verified_source_from_frozen_publisher():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/release.yml"
    ).read_text()
    assert "AGENT_PROJECT_TOKEN" not in workflow
    assert "publisher: ${{ steps.validate.outputs.publisher }}" in workflow
    assert workflow.count("ref: main") == 1
    for job in ("package:", "images:"):
        block = workflow.split("  " + job, 1)[1].split("\n  images:", 1)[0]
        assert "ref: ${{ needs.eligibility.outputs.source }}" in block
        assert "ref: ${{ needs.eligibility.outputs.publisher }}" in block
        assert "path: source" in block and "path: publisher" in block
        assert "python publisher/scripts/release_candidate.py" in block
        assert "PUBLISHER_SHA: ${{ needs.eligibility.outputs.publisher }}" in block
    assert "context: source" in workflow
    assert "inventory --source-root source" in workflow
    assert "image-receipt --source-root source" in workflow


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
    "defect", [None, "policy", "changes_requested", "ci", "base", "extra_path"]
)
def test_rollout_policy_is_narrow_and_never_merges(before, after, defect):
    _, pr, _, checks, reviews, _, _ = policy_fixture()
    config = {**copy.deepcopy(CONFIG), "mode": before, "pilot_tasks": [1, 2]}
    proposed = {**copy.deepcopy(config), "mode": after}
    changed = [
        {"filename": ".github/automation.json", "status": "modified", "sha": HEAD}
    ]
    if defect == "policy":
        proposed["trusted_logins"] = ["stranger"]
    elif defect == "changes_requested":
        reviews.append(
            {
                "id": 1,
                "user": {"login": "Ken0u"},
                "state": "CHANGES_REQUESTED",
                "commit_id": HEAD,
            }
        )
    elif defect == "ci":
        checks[0]["conclusion"] = "skipped"
    elif defect == "base":
        pr["base"]["sha"] = HEAD
    elif defect == "extra_path":
        changed.append({"filename": ".github/workflows/ci.yml"})

    class RolloutGitHub:
        def __init__(self):
            self.verdict = None

        def graphql(self, _query, **_variables):
            return {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            }

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


@pytest.mark.parametrize("outcome", ["success", "failure", "in_progress"])
def test_exhausted_delivery_observes_external_recovery_without_extra_retries(outcome):
    gh, store, config = merge_setup()
    tip, state = store.read()
    task = state["tasks"]["1"]
    reason = "Private publishing failed after three attempts"
    task.update(
        status="done",
        merge_sha=gh.merge_sha,
        delivery_pending=True,
        delivery_attempts=3,
        delivery_error=reason,
    )
    store.write(tip, state)
    gh.releases = [
        {
            "id": 99,
            "display_title": f"Private candidate {gh.merge_sha}",
            "conclusion": None if outcome == "in_progress" else outcome,
            "status": "in_progress" if outcome == "in_progress" else "completed",
            "html_url": "https://github.com/run/99",
        }
    ]
    result = integrate(gh, config, store.read()[1])
    recovered = result["tasks"]["1"]
    assert recovered["delivery_attempts"] == 3
    assert recovered["delivery_pending"] is (outcome != "success")
    if outcome == "success":
        assert recovered["candidate_run"] == "https://github.com/run/99"
        assert recovered["delivery_recovered_from"] == reason
        assert "delivery_error" not in recovered
    else:
        assert recovered["delivery_error"] == reason
    assert not any(path.startswith("actions/") for path, _data in gh.external)
    # Observing the repaired run is idempotent and never clears failure evidence
    # based on a queued/failed workflow or starts a fourth automatic attempt.
    again = integrate(gh, config, store.read()[1])
    assert again["tasks"]["1"] == recovered


class RecoveryGitHub(MergeGitHub):
    def __init__(self):
        super().__init__()
        self.source_tree = self.merged_tree = "d" * 40
        self.history_ancestor = self.main_ancestor = True
        self.preserved_head = HEAD
        self.source_reviews = []
        self.source_checks = None

    def pages(self, path):
        if "/reviews?" in path:
            return copy.deepcopy(self.source_reviews)
        return super().pages(path)

    def repo(self, path, *, method="GET", data=None, **kwargs):
        if method == "GET":
            if path == f"git/commits/{HEAD}":
                return {"tree": {"sha": self.source_tree}}
            if path == f"git/commits/{self.merge_sha}":
                return {"tree": {"sha": self.merged_tree}}
            if path == f"git/ref/heads/{self.pr['head']['ref']}":
                return {"object": {"sha": self.preserved_head}}
            if path.startswith("compare/"):
                start, end = path.removeprefix("compare/").split("...")
                allowed = (
                    self.history_ancestor if end == self.tip else self.main_ancestor
                )
                return {
                    "status": ("identical" if start == end else "ahead")
                    if allowed
                    else "diverged",
                    "merge_base_commit": {"sha": start if allowed else "f" * 40},
                }
            if "/check-runs?" in path and self.source_checks is not None:
                return [{"check_runs": copy.deepcopy(self.source_checks)}]
        return super().repo(path, method=method, data=data, **kwargs)


def external_recovery_setup(
    archived=False, resources=False, attested=True, review_defect=None
):
    from devops.queue import apply_request, spec_hash

    h, gh = approved_state(), RecoveryGitHub()
    if review_defect == "missing":
        h.state["tasks"]["1"].pop("review")
    elif review_defect == "self":
        h.state["tasks"]["1"]["review"]["session_id"] = "mac1"
    elif review_defect:
        h.state["tasks"]["1"]["review"][review_defect] = "stale"
    if resources:
        source = h.state["tasks"]["1"]
        source["spec"]["resources"] = ["gpu:windows"]
        source["spec_hash"] = spec_hash(source["spec"])
        for field in ("claim", "submission", "review"):
            source[field]["spec_hash"] = source["spec_hash"]
    config = {
        **CONFIG,
        "coordinator_login": "github-actions[bot]",
        "milestones": ["M1", "Infrastructure"],
    }
    store = StateStore(gh, config["coordination_branch"])
    evidence = store.write(None, h.state)
    original = copy.deepcopy(h.state["tasks"]["1"])
    gh.pr["head"]["ref"] = original["claim"]["branch"]
    gh.pr.update(
        merged=True,
        state="closed",
        merge_commit_sha=gh.merge_sha,
        merged_by={"login": "dootz1"},
        html_url="https://github.com/pull/42",
    )
    gh.main = gh.merge_sha
    state = integrate(gh, config, store.read()[1])
    if archived:
        state = apply_request(
            state,
            {
                "request_id": "archive-original",
                "verb": "recover",
                "task_id": "1",
                "epoch": 1,
                "host_id": "mac",
                "session_id": "mac1",
                "checkpoint": {"branch": original["claim"]["branch"], "head_sha": HEAD},
            },
            "Ken0u",
            200,
            config,
        )
        closed = issue("Preserve externally merged task", number=1)
        closed["state"] = "closed"
        gh.issues.append(closed)
        store.write(store.read()[0], state)
        state = reconcile(gh, config, now=200)
        assert state["tasks"]["1"]["status"] == "blocked"
        assert (
            "claim" not in state["tasks"]["1"] and "review" not in state["tasks"]["1"]
        )
    request = {
        "request_id": "owner-external-recovery",
        "verb": "recover-merged",
        "task_id": "1",
        "epoch": state["tasks"]["1"]["epoch"],
        "host_id": "mac",
        "session_id": "mac1",
        "pr_number": 42,
        "head_sha": HEAD,
        "base_sha": BASE,
        "spec_hash": original["spec_hash"],
        "merge_sha": gh.merge_sha,
        "evidence_state_sha": evidence,
        "human_review_attestation": {
            "kind": "owner_attestation",
            "reviewer": "dootz1",
            "head_sha": HEAD,
            "statement": "The owner confirmed dootz1 personally approved this exact head.",
        },
    }
    if not attested:
        request.pop("human_review_attestation")
    state = apply_request(state, request, "Ken0u", 201, config)
    store.write(store.read()[0], state)
    gh.ci = [
        {
            "id": 10,
            "event": "push",
            "head_branch": "main",
            "head_sha": gh.merge_sha,
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://github.com/run/10",
        }
    ]
    gh.releases = [
        {
            "id": 11,
            "display_title": f"Private candidate {gh.merge_sha}",
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://github.com/run/11",
        }
    ]
    return gh, store, config, original


@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize("attested", [False, True])
def test_explicit_recovery_uses_immutable_accepted_history_and_existing_delivery(
    archived,
    attested,
):
    gh, store, config, original = external_recovery_setup(archived, attested=attested)
    epoch = store.read()[1]["tasks"]["1"]["epoch"]
    state = integrate(gh, config, store.read()[1])
    task = state["tasks"]["1"]
    assert task["status"] == "done" and task["epoch"] == epoch
    assert task["merge_sha"] == gh.merge_sha and task["delivery_pending"] is False
    assert task["candidate_run"] == "https://github.com/run/11"
    assert task["review"] == original["review"]
    assert task["external_recovery"]["source_epoch"] == 1
    assert task["external_recovery"]["review_evidence"]["github_reviews"] == []
    attestation = task["external_recovery"]["review_evidence"]["owner_attestation"]
    assert (attestation["reviewer"] == "dootz1") if attested else attestation is None
    assert gh.external == [
        ("issues/1", {"state": "closed", "state_reason": "completed"})
    ]

    again = integrate(gh, config, store.read()[1])
    assert again == state and len(gh.issues) == 1 + archived
    assert gh.external == [
        ("issues/1", {"state": "closed", "state_reason": "completed"})
    ]


@pytest.mark.parametrize(
    "defect", [None, "missing", "self", "head_sha", "base_sha", "spec_hash"]
)
def test_optional_config_does_not_waive_original_external_recovery_review(defect):
    gh, store, config, original = external_recovery_setup(
        attested=False, review_defect=defect
    )
    config["require_agent_review"] = False
    state = integrate(gh, config, store.read()[1])
    task = state["tasks"]["1"]
    if defect is None:
        assert task["status"] == "done"
        assert task["review"] == original["review"]
        assert task["delivery_pending"] is False
    else:
        assert task["status"] == "recovery_required"
        assert task["external_recovery_error"]
        assert "external_recovery" not in task


@pytest.mark.parametrize(
    "case",
    [
        "unrelated_history",
        "changed_tree",
        "changed_head",
        "changed_base",
        "changed_merge",
        "changed_branch",
        "failed_source_check",
        "missing_main",
        "running_main",
        "failed_main",
        "untrusted_workflow_branch",
        "not_in_main",
        "human_changes_requested",
    ],
)
def test_external_recovery_keeps_unknown_or_changed_remote_evidence_incomplete(case):
    gh, store, config, original = external_recovery_setup()
    if case == "unrelated_history":
        gh.history_ancestor = False
    elif case == "changed_tree":
        gh.merged_tree = "e" * 40
    elif case == "changed_head":
        gh.pr["head"]["sha"] = "e" * 40
    elif case == "changed_base":
        gh.pr["base"]["sha"] = "e" * 40
    elif case == "changed_merge":
        gh.pr["merge_commit_sha"] = "e" * 40
    elif case == "changed_branch":
        gh.preserved_head = "e" * 40
    elif case == "failed_source_check":
        gh.source_checks = []
    elif case == "missing_main":
        gh.ci = []
    elif case == "running_main":
        gh.ci[0].update(status="in_progress", conclusion=None)
    elif case == "failed_main":
        gh.ci[0]["conclusion"] = "failure"
    elif case == "untrusted_workflow_branch":
        gh.ci[0]["head_branch"] = "unreviewed-feature"
    elif case == "not_in_main":
        gh.main_ancestor = False
    else:
        gh.source_reviews = [
            {
                "id": 1,
                "user": {"login": "dootz1"},
                "state": "CHANGES_REQUESTED",
                "commit_id": HEAD,
            }
        ]
    state = integrate(gh, config, store.read()[1])
    task = state["tasks"]["1"]
    assert task["status"] == "recovery_required"
    assert task["review"] == original["review"]
    assert task["external_recovery_error"]
    assert "external_recovery" not in task and not task.get("delivery_pending")
    assert not gh.external
    assert integrate(gh, config, store.read()[1]) == state


def test_resource_bearing_external_recovery_requires_original_host_terminal_proof():
    from devops.queue import apply_request
    from test_agent_queue import terminal_proof

    gh, store, config, original = external_recovery_setup(resources=True)
    state = integrate(gh, config, store.read()[1])
    assert state["tasks"]["1"]["status"] == "recovery_required"
    assert "terminal proof" in state["tasks"]["1"]["external_recovery_error"]
    assert state["tasks"]["1"]["claim"] == original["claim"]
    for host in ("other-host", "mac"):
        request = {
            **state["tasks"]["1"]["external_recovery_request"],
            "request_id": f"proof-{host}",
            "verb": "recover-merged",
            "task_id": "1",
            "host_id": "mac",
            "session_id": "mac1",
            "terminal_proof": terminal_proof(host),
        }
        state = apply_request(state, request, "Ken0u", 202, config)
        store.write(store.read()[0], state)
        state = integrate(gh, config, store.read()[1])
        if host == "other-host":
            assert state["tasks"]["1"]["status"] == "recovery_required"
    assert state["tasks"]["1"]["status"] == "done"
    assert state["tasks"]["1"]["delivery_pending"] is False


@pytest.mark.parametrize("response_lost", [False, True])
def test_fence_retries_an_interrupted_incident_without_authorizing_a_merge(
    response_lost,
):
    gh, store, config = merge_setup()
    gh.pr.update(merged=True, state="closed", merge_commit_sha=gh.merge_sha)
    gh.main = gh.merge_sha
    transport = gh.repo
    interrupted = False

    def fail_issue_once(path, *, method="GET", data=None, **kwargs):
        nonlocal interrupted
        if path == "issues" and method == "POST" and not interrupted:
            interrupted = True
            if response_lost:
                transport(path, method=method, data=data, **kwargs)
            raise GitHubError("temporary issue transport failure")
        return transport(path, method=method, data=data, **kwargs)

    gh.repo = fail_issue_once
    state = integrate(gh, config, store.read()[1])
    assert state["tasks"]["1"]["status"] == "recovery_required"
    assert len(gh.issues) == int(response_lost)
    assert "incident_issue" not in state["tasks"]["1"]["external_merge"]
    state = integrate(gh, config, store.read()[1])
    assert len(gh.issues) == 1
    assert state["tasks"]["1"]["external_merge"]["incident_issue"] == 900
    assert integrate(gh, config, store.read()[1]) == state
    assert not gh.external


def test_external_merge_fence_does_not_starve_an_unrelated_valid_integration():
    from devops.queue import spec_hash

    gh, store, config = merge_setup()
    state = store.read()[1]
    other = copy.deepcopy(state["tasks"]["1"])
    other["spec"]["paths"] = ["backend/unrelated.py"]
    other["spec_hash"] = spec_hash(other["spec"])
    other["pr_number"] = 43
    other["claim"].update(
        branch="codex/issue-2-unrelated",
        host_id="win",
        session_id="impl2",
        baseline_sha=gh.merge_sha,
    )
    other["review"].update(
        session_id="review2", reviewed_files=["backend/unrelated.py"]
    )
    for key in ("claim", "submission", "review"):
        other[key]["spec_hash"] = other["spec_hash"]
    for key in ("submission", "review"):
        other[key].update(head_sha="e" * 40, base_sha=gh.merge_sha, pr_number=43)
    state["tasks"]["2"] = other
    store.write(store.read()[0], state)
    gh.pr.update(merged=True, state="closed", merge_commit_sha=gh.merge_sha)
    gh.main = gh.merge_sha
    pr2 = {
        "number": 43,
        "state": "open",
        "draft": False,
        "merged": False,
        "head": {
            "sha": "e" * 40,
            "ref": "codex/issue-2-unrelated",
            "repo": {"full_name": CONFIG["repository"]},
        },
        "base": {"sha": gh.merge_sha, "ref": "main"},
        "user": {"login": "Ken0u"},
    }
    transport, pages = gh.repo, gh.pages

    def multi_pr(path, *, method="GET", data=None, **kwargs):
        if path == "pulls/43" and method == "GET":
            return copy.deepcopy(pr2)
        if path == "pulls/43/merge" and method == "PUT":
            assert data["sha"] == pr2["head"]["sha"]
            pr2.update(merged=True, state="closed", merge_commit_sha="f" * 40)
            gh.main = "f" * 40
            return {"merged": True, "sha": gh.main}
        if path == f"commits/{'e' * 40}/check-runs?per_page=100":
            return [
                {
                    "check_runs": [
                        {
                            "id": 1,
                            "name": "ci/gate",
                            "head_sha": "e" * 40,
                            "status": "completed",
                            "conclusion": "success",
                            "app": {"slug": "github-actions"},
                        }
                    ]
                }
            ]
        return transport(path, method=method, data=data, **kwargs)

    def multi_pages(path):
        return (
            [{"filename": "backend/unrelated.py"}]
            if path.startswith("pulls/43/files?")
            else pages(path)
        )

    gh.repo, gh.pages = multi_pr, multi_pages
    state = integrate(gh, config, store.read()[1])
    assert state["tasks"]["1"]["status"] == "recovery_required"
    assert state["tasks"]["2"]["status"] == "integrating"
    assert pr2["merged"] is True and gh.main == "f" * 40


@pytest.mark.parametrize("response_lost", [False, True])
def test_recovered_issue_projection_retries_without_repeating_adoption_or_delivery(
    response_lost,
):
    gh, store, config, _original = external_recovery_setup(archived=True)
    transport = gh.repo
    interrupted = False

    def fail_projection_once(path, *, method="GET", data=None, **kwargs):
        nonlocal interrupted
        if path == "issues/1" and method == "PATCH" and not interrupted:
            interrupted = True
            if response_lost:
                transport(path, method=method, data=data, **kwargs)
            raise GitHubError("issue completion response unavailable")
        return transport(path, method=method, data=data, **kwargs)

    gh.repo = fail_projection_once
    state = integrate(gh, config, store.read()[1])
    task = state["tasks"]["1"]
    assert task["status"] == "done" and task["delivery_pending"] is False
    proof = copy.deepcopy(task["external_recovery"])
    assert "issue_closed_at" not in task["external_recovery_request"]
    state = integrate(gh, config, store.read()[1])
    assert state["tasks"]["1"]["external_recovery"] == proof
    assert state["tasks"]["1"]["external_recovery_request"]["issue_closed_at"]
    assert not any(path.startswith("actions/") for path, _data in gh.external)
    assert integrate(gh, config, store.read()[1]) == state


@pytest.mark.parametrize("latest", [("in_progress", None), ("completed", "failure")])
def test_newer_main_verification_cannot_reuse_an_older_green_run(latest):
    gh, store, config, _original = external_recovery_setup()
    gh.ci.append({**gh.ci[0], "id": 11, "status": latest[0], "conclusion": latest[1]})
    state = integrate(gh, config, store.read()[1])
    assert state["tasks"]["1"]["status"] == "recovery_required"
    assert "merged-main verification" in state["tasks"]["1"]["external_recovery_error"]
    assert not gh.external


@pytest.mark.parametrize("candidate", ["missing", "failure", "in_progress"])
def test_external_adoption_delivers_once_then_reuses_visible_candidate(candidate):
    gh, store, config, _original = external_recovery_setup()
    visible = {
        **gh.releases[0],
        "status": "in_progress",
        "conclusion": None,
    }
    if candidate == "missing":
        gh.releases = []
        expected = [
            (
                "actions/workflows/release.yml/dispatches",
                {"ref": "main", "inputs": {"source_sha": gh.merge_sha}},
            )
        ]
    elif candidate == "failure":
        gh.releases[0]["conclusion"] = "failure"
        expected = [("actions/runs/11/rerun-failed-jobs", {})]
    else:
        gh.releases = [visible]
        expected = []

    def release_actions():
        return [
            (path, data) for path, data in gh.external if path.startswith("actions/")
        ]

    state = integrate(gh, config, store.read()[1])
    task = state["tasks"]["1"]
    assert task["status"] == "done" and task["delivery_pending"] is True
    assert release_actions() == expected
    assert task.get("delivery_attempts", 0) == len(expected)

    # GitHub exposes the dispatched or rerun candidate on a later pass.
    gh.releases = [visible]
    state = integrate(gh, config, store.read()[1])
    assert state["tasks"]["1"]["delivery_pending"] is True
    assert release_actions() == expected
    assert state["tasks"]["1"].get("delivery_attempts", 0) == len(expected)

    gh.releases[0].update(status="completed", conclusion="success")
    state = integrate(gh, config, store.read()[1])
    assert state["tasks"]["1"]["delivery_pending"] is False
    assert state["tasks"]["1"]["candidate_run"] == visible["html_url"]
    assert release_actions() == expected
    assert state["tasks"]["1"].get("delivery_attempts", 0) == len(expected)
