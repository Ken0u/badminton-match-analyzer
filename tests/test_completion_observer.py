"""Exercise completion wakes with the real queue state machine and fake GitHub."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from devops import completion_observer as observer
from devops.coordinator import integrate
from devops.github import GitHubError
from test_agent_coordinator import optional_merge_setup


class Clock:
    def __init__(self):
        self.now = 0
        self.tick = lambda: None

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert 0 < seconds <= 30
        self.now += seconds
        self.tick()


def setup(stage="main"):
    gh, store, config = optional_merge_setup()
    state = integrate(gh, config, store.read()[1])
    tip = store.read()[0]
    if stage == "delivery":
        task = state["tasks"]["1"]
        task.update(status="done", delivery_pending=True, delivery_attempts=1)
        tip = store.write(tip, state)
    binding = observer.identity("1", state["tasks"]["1"], config)
    inputs = {
        k: str(binding[k])
        for k in ("task_id", "epoch", "stage", "source_sha", "attempt")
    }
    inputs["coordination_sha"] = tip
    tables = {
        name: []
        for name in ("ci.yml", "release.yml", observer.OBSERVER, observer.CONTROLLER)
    }
    metas = {
        name: {"id": i + 100, "path": f".github/workflows/{name}", "state": "active"}
        for i, name in enumerate(tables)
    }
    transport = gh.repo
    effects, reads = [], []

    def repo(path, *, method="GET", data=None, **kwargs):
        if path.startswith("compare/"):
            start, end = path.removeprefix("compare/").split("...")
            if start in gh.objects:
                current = end
                while current != start:
                    parents = gh.objects[current]["parents"]
                    if not parents:
                        return {"status": "diverged"}
                    current = parents[0]
            elif start != gh.merge_sha or end != gh.main:
                return {"status": "diverged"}
            return {"status": "ahead", "merge_base_commit": {"sha": start}}
        if path.startswith("actions/"):
            if method != "GET":
                effects.append((path, copy.deepcopy(data)))
                return None
            reads.append(path)
            if path.startswith("actions/runs/"):
                run_id = int(path.split("/")[-1])
                return copy.deepcopy(
                    next(
                        r for runs in tables.values() for r in runs if r["id"] == run_id
                    )
                )
            name = path.split("/")[2]
            if "/runs?" not in path:
                return copy.deepcopy(metas[name])
            query = parse_qs(urlsplit(path).query)
            rows = [
                r
                for r in tables[name]
                if "status" not in query or r["status"] == query["status"][0]
            ]
            page = int(query["page"][0])
            return {
                "total_count": len(rows),
                "workflow_runs": copy.deepcopy(rows[(page - 1) * 100 : page * 100]),
            }
        return transport(path, method=method, data=data, **kwargs)

    gh.repo = repo
    clock = Clock()
    return gh, store, config, inputs, binding, tables, metas, effects, reads, clock


def run_record(
    context, name=None, *, outcome="success", event="workflow_dispatch", run_id=501
):
    _, _, config, _, binding, _, metas, _, _, _ = context
    name = name or observer.WORKFLOWS[binding["stage"]]
    return {
        "id": run_id,
        "workflow_id": metas[name]["id"],
        "path": metas[name]["path"],
        "head_branch": "main",
        "head_sha": binding["source_sha"],
        "event": event,
        "repository": {"full_name": config["repository"]},
        "head_repository": {"full_name": config["repository"]},
        "display_title": (
            observer.title(binding)
            if name == observer.OBSERVER
            else ("Verify " if name == "ci.yml" else "Private candidate ")
            + binding["source_sha"]
        ),
        "status": "completed" if outcome not in observer.ACTIVE else outcome,
        "conclusion": None if outcome in observer.ACTIVE else outcome,
        "run_attempt": 1,
    }


def invoke(context):
    gh, _, config, inputs, _, _, _, _, _, clock = context
    return observer.observe(
        gh, config, inputs, monotonic=clock.monotonic, sleep=clock.sleep
    )


@pytest.mark.parametrize("stage", ["main", "delivery"])
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled", "timed_out"])
def test_terminal_observation_only_wakes_unchanged_controller(stage, outcome):
    ctx = setup(stage)
    gh, store, config, _, _, tables, _, effects, _, _ = ctx
    before = store.read()
    tables[observer.WORKFLOWS[stage]] = [run_record(ctx, outcome=outcome)]
    result = invoke(ctx)
    assert result["outcome"] == "controller_dispatched"
    assert result["observed_conclusion"] == outcome
    assert effects == [
        ("actions/workflows/agent-queue.yml/dispatches", {"ref": "main"})
    ]
    assert store.read() == before
    # No observer-supplied success, mutation or CI/publisher rerun reaches policy.
    assert "checks_passed" not in json.dumps(result)
    assert config["required_checks"] == ["ci/gate"]
    assert gh.main == before[1]["tasks"]["1"]["merge_sha"]


@pytest.mark.parametrize("stage", ["main", "delivery"])
def test_pending_then_terminal_and_old_active_pr_controller_wait(stage):
    ctx = setup(stage)
    _, _, _, _, _, tables, _, effects, reads, clock = ctx
    target = run_record(ctx, outcome="in_progress")
    tables[observer.WORKFLOWS[stage]] = [target]
    controller = run_record(
        ctx,
        observer.CONTROLLER,
        outcome="in_progress",
        event="pull_request_target",
        run_id=502,
    )
    controller["head_branch"] = "codex/feature"
    tables[observer.CONTROLLER] = [controller]

    def tick():
        assert effects == []
        target.update(status="completed", conclusion="success")
        if clock.now >= 60:
            controller.update(status="completed", conclusion="success")

    clock.tick = tick
    assert invoke(ctx)["outcome"] == "controller_dispatched"
    assert clock.now == 60 and len(effects) == 1
    assert any("status=in_progress" in r for r in reads)


@pytest.mark.parametrize(
    "defect",
    [
        "workflow_id",
        "path",
        "repository",
        "head_repository",
        "head_branch",
        "event",
        "run_attempt",
        "status",
        "conclusion",
        "head_sha",
    ],
)
def test_wrong_target_identity_or_malformed_state_never_wakes(defect):
    ctx = setup()
    target = run_record(ctx, event="push")
    target[defect] = (
        {"full_name": "outsider/repo"}
        if defect in ("repository", "head_repository")
        else "invalid"
    )
    ctx[5]["ci.yml"] = [target]
    with pytest.raises(ValueError):
        invoke(ctx)
    assert not ctx[7]


@pytest.mark.parametrize(
    "defect",
    [
        "epoch",
        "spec",
        "source",
        "status",
        "attempt",
        "journal",
        "submission",
        "claim",
        "external",
    ],
)
def test_current_task_changes_reject_stale_observation(defect):
    ctx = setup("delivery")
    tip, state = ctx[1].read()
    task = state["tasks"]["1"]
    if defect == "epoch":
        task["epoch"] += 1
    elif defect == "spec":
        task["spec"]["outcome"] += " changed"
    elif defect == "source":
        task["merge_sha"] = "f" * 40
    elif defect == "status":
        task["delivery_pending"] = False
    elif defect == "attempt":
        task["delivery_attempts"] += 1
    elif defect == "journal":
        task["integration"]["head_sha"] = "f" * 40
    elif defect == "submission":
        task["submission"]["base_sha"] = "f" * 40
    elif defect == "claim":
        task["claim"]["session_id"] = "other"
    else:
        task["external_recovery_request"] = {"completed_at": 1}
    ctx[1].write(tip, state)
    assert invoke(ctx)["outcome"] == "stale"
    assert not ctx[7]


@pytest.mark.parametrize(
    "key,value",
    [
        ("epoch", "2"),
        ("attempt", "1"),
        ("source_sha", "f" * 40),
        ("stage", "delivery"),
        ("task_id", "../1"),
        ("coordination_sha", "main"),
        ("epoch", "1; echo unsafe"),
    ],
)
def test_untrusted_inputs_do_not_become_authority(key, value):
    ctx = setup()
    ctx[3][key] = value
    with pytest.raises((ValueError, KeyError)):
        invoke(ctx)
    assert not ctx[7]


def test_missing_run_times_out_unknown_without_effect(monkeypatch):
    ctx = setup()
    monkeypatch.setattr(observer, "MAX_SECONDS", 60)
    result = invoke(ctx)
    assert result == {
        "outcome": "timeout_unknown",
        "run_id": None,
        "verification_accepted": False,
    }
    assert ctx[9].now == 60 and not ctx[7]


def test_changed_run_attempt_stops_without_accepting_retry():
    ctx = setup()
    target = run_record(ctx, outcome="in_progress")
    ctx[5]["ci.yml"] = [target]
    ctx[9].tick = lambda: target.update(run_attempt=2)
    with pytest.raises(ValueError, match="attempt changed"):
        invoke(ctx)
    assert not ctx[7]


def test_stale_after_controller_wait_does_not_wake():
    ctx = setup()
    ctx[5]["ci.yml"] = [run_record(ctx)]
    ctx[5][observer.CONTROLLER] = [
        run_record(ctx, observer.CONTROLLER, outcome="in_progress", run_id=502)
    ]

    def tick():
        tip, state = ctx[1].read()
        state["tasks"]["1"]["status"] = "done"
        ctx[1].write(tip, state)

    ctx[9].tick = tick
    assert invoke(ctx)["outcome"] == "stale"
    assert not ctx[7]


@pytest.mark.parametrize(
    "outcome", ["queued", "in_progress", "success", "failure", "cancelled"]
)
def test_launcher_reuses_even_terminal_observer(outcome):
    ctx = setup()
    ctx[5][observer.OBSERVER] = [run_record(ctx, observer.OBSERVER, outcome=outcome)]
    result = observer.launch(ctx[0], ctx[2])
    assert result["targets"] == [{"task_id": "1", "outcome": "reused"}]
    assert not ctx[7]


def test_launcher_dispatches_bound_immutable_inputs_once():
    ctx = setup()
    assert observer.launch(ctx[0], ctx[2])["targets"][0]["outcome"] == "dispatched"
    assert ctx[7] == [
        (
            "actions/workflows/completion-observer.yml/dispatches",
            {"ref": "main", "inputs": ctx[3]},
        )
    ]


def test_lost_dispatch_response_is_not_retried():
    ctx = setup()
    ctx[5]["ci.yml"] = [run_record(ctx)]
    transport = ctx[0].repo

    def repo(path, **kwargs):
        value = transport(path, **kwargs)
        if kwargs.get("method") == "POST":
            raise GitHubError("lost response")
        return value

    ctx[0].repo = repo
    with pytest.raises(GitHubError):
        invoke(ctx)
    assert len(ctx[7]) == 1


def test_incomplete_listing_and_foreign_history_fail_closed():
    ctx = setup()
    transport = ctx[0].repo

    def repo(path, **kwargs):
        if "/runs?" in path:
            return {"total_count": 101, "workflow_runs": []}
        return transport(path, **kwargs)

    ctx[0].repo = repo
    with pytest.raises(ValueError, match="Incomplete"):
        observer.launch(ctx[0], ctx[2])
    assert not ctx[7]
    ctx = setup()
    ctx[0].objects["e" * 40] = {"tree": {"sha": "f" * 40}, "parents": []}
    ctx[3]["coordination_sha"] = "e" * 40
    with pytest.raises(ValueError, match="outside trusted"):
        invoke(ctx)


def entrypoint():
    path = Path(__file__).resolve().parents[1] / "scripts/observe_completion.py"
    spec = importlib.util.spec_from_file_location("completion_entrypoint", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "defect", ["local", "repository", "branch", "workflow", "event"]
)
def test_entrypoint_rejects_untrusted_context_before_transport(monkeypatch, defect):
    module = entrypoint()
    repository = "Ken0u/badminton-match-analyzer"
    values = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": repository,
        "GITHUB_WORKFLOW_REF": f"{repository}/.github/workflows/completion-observer.yml@refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
    }
    if defect == "local":
        values["GITHUB_ACTIONS"] = "false"
    elif defect == "repository":
        values["GITHUB_REPOSITORY"] = "outsider/repo"
    elif defect == "branch":
        values["GITHUB_WORKFLOW_REF"] = values["GITHUB_WORKFLOW_REF"].replace(
            "heads/main", "heads/feature"
        )
    elif defect == "workflow":
        values["GITHUB_WORKFLOW_REF"] = values["GITHUB_WORKFLOW_REF"].replace(
            "completion-observer.yml", "ci.yml"
        )
    else:
        values["GITHUB_EVENT_NAME"] = "pull_request"
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        module,
        "CompletionGitHub",
        lambda *_: pytest.fail("No transport before context validation"),
    )
    with pytest.raises(SystemExit):
        module.main(["observe"])


def test_workflow_has_no_implementation_checkout_secret_or_shell_input():
    root = Path(__file__).resolve().parents[1]
    content = (root / ".github/workflows/completion-observer.yml").read_text(
        encoding="utf-8"
    )
    assert "timeout-minutes: 95" in content
    assert "ref: main" in content and "persist-credentials: false" in content
    assert "contents: write" not in content and "issues: write" not in content
    assert "actions: write" in content and "secrets." not in content
    assert "pull_request:" not in content and "workflow_run:" not in content
    assert all("${{" not in line for line in content.splitlines() if "run:" in line)
    assert observer.MAX_SECONDS == 5400 and observer.POLL_SECONDS == 30
    queue = (root / ".github/workflows/agent-queue.yml").read_text(encoding="utf-8")
    assert queue.index("agent_queue.py integrate") < queue.index(
        "observe_completion.py launch"
    )


def test_push_and_eventually_visible_exact_runs_are_observed():
    ctx = setup()
    ctx[9].tick = lambda: ctx[5]["ci.yml"].append(run_record(ctx, event="push"))
    assert invoke(ctx)["outcome"] == "controller_dispatched"
    assert ctx[9].now == 30


@pytest.mark.parametrize(
    "defect", ["merge", "head", "base", "repository", "unmerged", "ancestry"]
)
def test_actual_pr_and_main_lineage_must_still_match(defect):
    ctx = setup()
    pr = ctx[0].pr
    if defect == "merge":
        pr["merge_commit_sha"] = "f" * 40
    elif defect == "head":
        pr["head"]["sha"] = "f" * 40
    elif defect == "base":
        pr["base"]["sha"] = "f" * 40
    elif defect == "repository":
        pr["head"]["repo"]["full_name"] = "outsider/repo"
    elif defect == "unmerged":
        pr["merged"] = False
    else:
        transport = ctx[0].repo

        def divergent(path, **kwargs):
            if path.startswith(f"compare/{ctx[4]['source_sha']}..."):
                return {"status": "diverged"}
            return transport(path, **kwargs)

        ctx[0].repo = divergent
    assert invoke(ctx)["outcome"] == "stale"
    assert not ctx[7]


def test_sensitive_scope_still_requires_matching_owner_authorization():
    ctx = setup()
    ctx[2]["sensitive_paths"] = ["backend/"]
    with pytest.raises(ValueError, match="frozen grant"):
        invoke(ctx)
    assert not ctx[7]


def test_exhausted_publication_is_preserved_and_not_restarted():
    ctx = setup("delivery")
    tip, state = ctx[1].read()
    state["tasks"]["1"]["delivery_attempts"] = 3
    state["tasks"]["1"]["delivery_error"] = "Preserved three-attempt failure"
    ctx[1].write(tip, state)
    result = observer.launch(ctx[0], ctx[2])
    assert result == {"outcome": "idle", "unsupported_tasks": ["1"]}
    assert not ctx[7]


def test_lost_launch_response_can_reuse_eventually_visible_observer():
    ctx = setup()
    transport = ctx[0].repo

    def repo(path, **kwargs):
        value = transport(path, **kwargs)
        if kwargs.get("method") == "POST":
            ctx[5][observer.OBSERVER].append(
                run_record(ctx, observer.OBSERVER, outcome="queued")
            )
            raise GitHubError("lost launch response")
        return value

    ctx[0].repo = repo
    with pytest.raises(GitHubError):
        observer.launch(ctx[0], ctx[2])
    assert observer.launch(ctx[0], ctx[2])["targets"][0]["outcome"] == "reused"
    assert len(ctx[7]) == 1


@pytest.mark.parametrize(
    "command,operation",
    [
        ("observe", "pulls/42/merge"),
        ("observe", "git/refs/heads/main"),
        ("observe", "actions/runs/501/rerun-failed-jobs"),
        ("observe", "actions/workflows/ci.yml/dispatches"),
        ("observe", "actions/workflows/release.yml/dispatches"),
        ("observe", "actions/workflows/completion-observer.yml/dispatches"),
        ("launch", "actions/workflows/agent-queue.yml/dispatches"),
    ],
)
def test_transport_refuses_other_mutation_destinations(monkeypatch, command, operation):
    gh = observer.CompletionGitHub("Ken0u/badminton-match-analyzer", command)
    monkeypatch.setattr(
        observer.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("Forbidden transport"),
    )
    with pytest.raises(ValueError):
        gh.repo(operation, method="POST", data={"ref": "main"})


def test_transport_timeout_has_no_retry_or_sensitive_diagnostic(monkeypatch):
    gh = observer.CompletionGitHub("Ken0u/badminton-match-analyzer", "observe")
    calls = []

    def transport(args, **kwargs):
        calls.append((args, kwargs))
        assert 0 < kwargs["timeout"] <= 20
        assert json.loads(kwargs["input"]) == {"ref": "main"}
        raise subprocess.TimeoutExpired("sensitive diagnostic", 20)

    monkeypatch.setattr(observer.subprocess, "run", transport)
    with pytest.raises(TimeoutError, match="outcome is unknown") as error:
        gh.repo(
            "actions/workflows/agent-queue.yml/dispatches",
            method="POST",
            data={"ref": "main"},
        )
    assert "sensitive" not in str(error.value) and len(calls) == 1


def test_entrypoint_reports_unknown_without_payload_or_transport_details(
    monkeypatch, capsys
):
    module = entrypoint()
    repository = "Ken0u/badminton-match-analyzer"
    for key, value in {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": repository,
        "GITHUB_WORKFLOW_REF": f"{repository}/.github/workflows/agent-queue.yml@refs/heads/main",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(module, "CompletionGitHub", lambda *_args: object())

    def failure(*_args):
        raise GitHubError("sensitive diagnostic")

    monkeypatch.setattr(module, "launch", failure)
    assert module.main(["launch"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "outcome": "unknown",
        "error_type": "GitHubError",
        "verification_accepted": False,
    }
