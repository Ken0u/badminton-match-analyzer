"""Offline regression coverage for durable queue safety boundaries."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from devops.queue import (
    LEASE_SECONDS,
    QueueError,
    apply_request,
    expire_leases,
    initial_state,
    paths_overlap,
    spec_hash,
    validate_spec,
)

HEAD = "a" * 40
BASE = "b" * 40
MERGE = "c" * 40
HASH = "d" * 64
CONFIG = {"trusted_logins": ["Ken0u", "dootz1"], "mode": "active", "milestones": ["M1"]}


def spec(**changes):
    result = {
        "outcome": "Fix source clocks",
        "acceptance": ["PTS survive"],
        "exclusions": ["No new model"],
        "paths": ["backend/clock.py"],
        "capabilities": ["python"],
        "artifacts": {},
        "resources": [],
        "dependencies": [],
        "priority": 2,
        "milestone": "M1",
        "risk": "routine",
        "verification": ["pytest focused"],
        "limits": {"attempts": 3},
    }
    result.update(changes)
    return result


class Harness:
    def __init__(self, mode="active"):
        self.state = initial_state()
        self.now = 100
        self.counter = 0
        self.config = {**CONFIG, "mode": mode}

    def send(self, verb, actor="Ken0u", **fields):
        self.counter += 1
        request = {"request_id": f"r{self.counter}", "verb": verb, **fields}
        self.state = apply_request(self.state, request, actor, self.now, self.config)
        return self.state["receipts"][request["request_id"]]

    def register(self, actor="Ken0u", host_id="mac", session_id="mac1", **fields):
        return self.send(
            "register",
            actor,
            host_id=host_id,
            session_id=session_id,
            capabilities=["python"],
            artifacts={},
            **fields,
        )

    def plan(self, task_id="1", **changes):
        return self.send("plan", task_id=task_id, spec=spec(**changes))

    def next(self, actor="Ken0u", host_id="mac", session_id="mac1", **fields):
        return self.send(
            "next",
            actor,
            host_id=host_id,
            session_id=session_id,
            baseline_sha=BASE,
            **fields,
        )

    def owned(self, verb, **fields):
        return self.send(
            verb, task_id="1", host_id="mac", session_id="mac1", epoch=1, **fields
        )

    def running(self, **changes):
        self.register()
        self.plan(**changes)
        self.next()
        return self

    def submit(self):
        return self.owned(
            "submit",
            pr_number=10,
            head_sha=HEAD,
            base_sha=BASE,
            spec_hash=self.state["tasks"]["1"]["spec_hash"],
        )

    def reviewing(self):
        self.running()
        self.submit()
        self.register("dootz1", "windows", "win1")
        return self.send("review-next", "dootz1", host_id="windows", session_id="win1")

    def review_result(self, verdict="approve", **fields):
        binding = self.state["tasks"]["1"]["submission"]
        return self.send(
            "review-result",
            "dootz1",
            task_id="1",
            host_id="windows",
            session_id="win1",
            epoch=1,
            review_epoch=self.state["tasks"]["1"]["review_epoch"],
            verdict=verdict,
            findings=[],
            reviewed_files=["backend/clock.py"],
            limitations=[],
            evidence=["Focused tests passed"],
            **{**binding, **fields},
        )


def terminal_proof(host="mac"):
    return {
        "host_id": host,
        "terminal": True,
        "process": {
            "pid": 42,
            "creation_time": 1,
            "cwd": "repo",
            "command": "worker",
            "exited": True,
        },
        "store": {"job_id": "job", "status": "completed"},
        "artifacts": {"receipt_sha256": HASH},
    }


def external_authorization(h):
    task = h.state["tasks"]["1"]
    return {
        "task_id": "1",
        "host_id": "mac",
        "session_id": "mac1",
        "epoch": task["epoch"],
        "spec_hash": task["spec_hash"],
        "pr_number": task["pr_number"],
        "head_sha": HEAD,
        "base_sha": BASE,
        "merge_sha": MERGE,
        "evidence_state_sha": "e" * 40,
        "human_review_attestation": {
            "kind": "owner_attestation",
            "reviewer": "dootz1",
            "head_sha": HEAD,
            "statement": "The owner confirmed personal exact-head non-author review.",
        },
    }


def fenced_queue():
    h = Harness().running()
    h.submit()
    h.state["tasks"]["1"]["status"] = "recovery_required"
    h.config["human_approvers"] = ["Ken0u", "dootz1"]
    return h


def test_human_recovery_authorization_is_pending_not_verified_completion():
    h = fenced_queue()
    original = copy.deepcopy(h.state["tasks"]["1"])
    receipt = h.send("recover-merged", **external_authorization(h))
    task = h.state["tasks"]["1"]
    assert receipt["status"] == "recovery_pending"
    assert task["status"] == "recovery_required"
    assert task["claim"] == original["claim"]
    assert "merge_sha" not in task and not task.get("delivery_pending")
    assert task["external_recovery_request"]["actor"] == "Ken0u"
    with pytest.raises(QueueError, match="coordinator"):
        h.send("adopt-external-merge", task_id="1")


@pytest.mark.parametrize("case", ["epoch", "spec", "pr", "sha", "role", "mode", "live"])
def test_external_recovery_authorization_preserves_fencing_and_human_permissions(case):
    h = fenced_queue()
    fields = external_authorization(h)
    if case == "epoch":
        fields["epoch"] += 1
    elif case == "spec":
        fields["spec_hash"] = "f" * 64
    elif case == "pr":
        fields["pr_number"] += 1
    elif case == "sha":
        fields["evidence_state_sha"] = "main"
    elif case == "role":
        h.config["human_approvers"] = ["dootz1"]
    elif case == "mode":
        h.config["mode"] = "observation"
    else:
        h.state["tasks"]["1"]["status"] = "review"
    before = copy.deepcopy(h.state)
    with pytest.raises(QueueError):
        h.send("recover-merged", **fields)
    assert h.state == before


def test_external_recovery_authorization_id_cannot_be_replayed_with_changed_source():
    h = fenced_queue()
    fields = external_authorization(h)
    receipt = h.send("recover-merged", **fields)
    request_id = next(
        key for key, value in h.state["receipts"].items() if value == receipt
    )
    with pytest.raises(QueueError, match="replay"):
        apply_request(
            h.state,
            {
                "verb": "recover-merged",
                "request_id": request_id,
                **fields,
                "merge_sha": "f" * 40,
            },
            "Ken0u",
            h.now,
            h.config,
        )


def test_client_cannot_supply_verified_recovery_or_impersonate_the_authorizer():
    h = fenced_queue()
    fields = external_authorization(h)
    h.state = apply_request(
        h.state,
        {
            "verb": "recover-merged",
            "request_id": "forged-verified-recovery",
            **fields,
            "verified": {"verification_complete": True},
            "actor": "github-actions[bot]",
        },
        "Ken0u",
        h.now,
        h.config,
    )
    task = h.state["tasks"]["1"]
    assert task["status"] == "recovery_required"
    assert "verified" not in task["external_recovery_request"]
    assert task["external_recovery_request"]["actor"] == "Ken0u"


def test_hash_is_canonical_and_does_not_mutate():
    value = spec()
    reordered = dict(reversed(list(value.items())))
    assert spec_hash(value) == spec_hash(reordered)
    assert len(spec_hash(value)) == 64
    validate_spec(value)
    assert value == spec()


@pytest.mark.parametrize(
    "path",
    [
        "../x",
        "/tmp/x",
        "C:/x",
        "backend/../x",
        "backend//x",
        "backend\\x",
        ".git/config",
        ".cache/x",
        "data/video.mp4",
        "datasets/x",
        "weights/x",
        "backend/*.py",
        "backend/[x]",
        "backend/x?",
        "backend/x\n",
        "backend/.env.production",
        "backend/%2e%2e/x",
        "backend/x.",
        "backend/x ",
        "./backend/x",
        "",
        "backend/CON.py",
        "backend/café.py",
        "backend/__pycache__/x.py",
        "docs/video.mp4",
        "secrets/config",
    ],
)
def test_unsafe_paths_fail_closed(path):
    with pytest.raises(QueueError):
        validate_spec(spec(paths=[path]))


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        "backend/",
        "AGENTS.md",
        "scripts/devops/queue.py",
        "data/manifests/",
    ],
)
def test_source_paths_are_valid_even_when_approval_policy_is_separate(path):
    validate_spec(spec(paths=[path]))


@pytest.mark.parametrize(
    "left,right",
    [
        ("backend/", "backend/x.py"),
        ("backend/a", "backend/a/b"),
        ("Backend/X.py", "backend/x.py"),
        ("backend/a/", "backend/a"),
    ],
)
def test_ancestor_paths_conflict(left, right):
    assert paths_overlap(left, right)
    assert paths_overlap(right, left)
    assert not paths_overlap("backend/a", "backend/ab")


@pytest.mark.parametrize(
    "changes",
    [
        {"acceptance": []},
        {"verification": []},
        {"paths": []},
        {"priority": True},
        {"priority": -1},
        {"dependencies": [1]},
        {"artifacts": {"dataset": "bad"}},
        {"capabilities": ["a", "a"]},
        {"risk": "automatic"},
        {"limits": {"seconds": float("nan")}},
        {"paths": ["backend/A.py", "backend/a.py"]},
        {"approved": True},
    ],
)
def test_invalid_specs_are_rejected(changes):
    with pytest.raises(QueueError):
        validate_spec(spec(**changes))


def test_copy_on_success_and_rejection():
    h = Harness()
    before = copy.deepcopy(h.state)
    h.register()
    assert before == initial_state()
    before = copy.deepcopy(h.state)
    with pytest.raises(QueueError):
        h.send("plan", task_id="1", spec=spec(milestone="other"))
    assert h.state == before


def test_replay_is_idempotent_but_modified_replay_fails():
    h = Harness().running()
    req = {
        "request_id": "checkpoint-1",
        "verb": "checkpoint",
        "task_id": "1",
        "host_id": "mac",
        "session_id": "mac1",
        "epoch": 1,
        "checkpoint": {"head": HEAD},
    }
    first = apply_request(h.state, req, "Ken0u", h.now, h.config)
    assert apply_request(first, req, "ken0u", h.now + 100000, h.config) == first
    for mutation, actor in [({"checkpoint": {"head": BASE}}, "Ken0u"), ({}, "dootz1")]:
        with pytest.raises(QueueError, match="replay"):
            apply_request(first, {**req, **mutation}, actor, h.now, h.config)


def test_unknown_actor_cannot_register_or_plan():
    h = Harness()
    with pytest.raises(QueueError, match="not trusted"):
        h.send("plan", "attacker", task_id="1", spec=spec())
    with pytest.raises(QueueError):
        h.send(
            "register",
            "github-actions[bot]",
            host_id="bot",
            session_id="bot1",
            capabilities=[],
            artifacts={},
        )


def test_registration_cannot_impersonate_host_and_sessions_coexist():
    h = Harness().running()
    with pytest.raises(QueueError, match="another actor"):
        h.register("dootz1", "mac", "evil")
    h.register(session_id="mac2")
    assert {"mac/mac1", "mac/mac2"} <= set(h.state["workers"])
    h.owned("heartbeat")
    with pytest.raises(QueueError, match="already owns"):
        h.next(session_id="mac2")


def test_observation_never_grants_or_starts_implementation_or_review():
    h = Harness("observation")
    h.register()
    assert h.plan()["status"] == "proposed"
    assert h.next()["status"] == "observed"
    assert (
        h.send("review-next", host_id="mac", session_id="mac1")["status"] == "observed"
    )
    assert "claim" not in h.state["tasks"]["1"]


def test_paused_queue_blocks_new_claims_but_preserves_work():
    h = Harness().running()
    h.send("pause")
    h.register("dootz1", "windows", "win1")
    assert h.next("dootz1", "windows", "win1")["status"] == "paused"
    h.owned("heartbeat")
    assert h.state["tasks"]["1"]["status"] == "running"


def test_pilot_only_grants_explicitly_selected_tasks():
    h = Harness("pilot")
    h.register()
    h.plan("1", priority=0)
    h.plan("2", priority=1)
    assert h.next()["status"] == "idle"
    h.config["pilot_tasks"] = ["2"]
    assert h.next()["task_id"] == "2"


def test_two_serialized_competing_claims_reserve_path_once():
    h = Harness().running(paths=["backend/"])
    h.plan("2", paths=["backend/new.py"], priority=0)
    h.register("dootz1", "windows", "win1")
    assert h.next("dootz1", "windows", "win1")["status"] == "idle"
    assert h.state["tasks"]["2"]["status"] == "ready"


def test_resource_reservation_and_host_implementation_limit():
    h = Harness().running(resources=["gpu:windows:0"])
    h.plan("2", paths=["docs/report.md"], resources=["gpu:windows:0"])
    h.register("dootz1", "windows", "win1")
    assert h.next("dootz1", "windows", "win1")["status"] == "idle"
    with pytest.raises(QueueError, match="already owns"):
        h.next()


def test_nonconflicting_claims_run_on_two_hosts():
    h = Harness().running()
    h.plan("2", paths=["docs/report.md"])
    h.register("dootz1", "windows", "win1")
    grant = h.next("dootz1", "windows", "win1")
    assert grant["task_id"] == "2"


def test_capabilities_artifact_hashes_and_dependency_gates():
    h = Harness()
    h.register()
    h.plan("1", capabilities=["cuda"])
    h.plan("2", paths=["docs/2.md"], artifacts={"source": HASH})
    h.plan("3", paths=["docs/3.md"], dependencies=["99"])
    assert h.next()["status"] == "idle"


def test_priority_then_issue_number_order_is_deterministic():
    h = Harness()
    h.register()
    for task_id in ["10", "2", "1"]:
        h.plan(task_id, priority=0 if task_id != "1" else 1)
    assert h.next()["task_id"] == "2"


def test_dependency_cycle_rejected_atomically():
    h = Harness()
    h.plan("1", dependencies=["2"])
    before = copy.deepcopy(h.state)
    with pytest.raises(QueueError, match="cycle"):
        h.plan("2", dependencies=["1"])
    assert h.state == before


def test_human_approval_is_hash_bound_and_explicitly_configured():
    h = Harness()
    h.register()
    h.plan(risk="human")
    assert h.next()["status"] == "idle"
    digest = h.state["tasks"]["1"]["spec_hash"]
    with pytest.raises(QueueError, match="approver"):
        h.send("human-approved", task_id="1", spec_hash=digest)
    h.config["human_approvers"] = ["Ken0u"]
    with pytest.raises(QueueError, match="hash"):
        h.send("human-approved", task_id="1", spec_hash=HASH)
    h.send("human-approved", task_id="1", spec_hash=digest)
    assert h.next()["status"] == "granted"


@pytest.mark.parametrize("defect", ["unknown_actor", "stale_spec", "no_approval"])
def test_risk_human_claim_still_requires_valid_owner_scope_authorization(defect):
    h = Harness()
    h.register()
    h.config["human_approvers"] = ["Ken0u"]
    h.plan(risk="human")
    task = h.state["tasks"]["1"]
    h.send("human-approved", task_id="1", spec_hash=task["spec_hash"])
    if defect == "unknown_actor":
        task = h.state["tasks"]["1"]
        task["human_approval"]["actor"] = "outsider"
    elif defect == "stale_spec":
        h.state["tasks"]["1"]["human_approval"]["spec_hash"] = HASH
    else:
        h.state["tasks"]["1"].pop("human_approval")
    assert h.next()["status"] == "idle"


@pytest.mark.parametrize(
    "changes",
    [{"epoch": 2}, {"epoch": True}, {"host_id": "windows"}, {"session_id": "other"}],
)
def test_stale_or_foreign_claim_commands_fail(changes):
    h = Harness().running()
    request = {
        "request_id": "bad",
        "verb": "checkpoint",
        "task_id": "1",
        "host_id": "mac",
        "session_id": "mac1",
        "epoch": 1,
        "checkpoint": {},
        **changes,
    }
    with pytest.raises(QueueError):
        apply_request(h.state, request, "Ken0u", h.now, h.config)
    with pytest.raises(QueueError):
        apply_request(
            h.state,
            {**request, "host_id": "mac", "session_id": "mac1", "epoch": 1},
            "dootz1",
            h.now,
            h.config,
        )


def test_expiry_fences_commands_but_holds_all_reservations():
    h = Harness().running(resources=["gpu:windows:0"])
    old = copy.deepcopy(h.state)
    h.now += LEASE_SECONDS
    h.state = expire_leases(h.state, h.now)
    assert old["tasks"]["1"]["status"] == "running"
    assert h.state["tasks"]["1"]["status"] == "recovery_required"
    for verb, args in [
        ("heartbeat", {}),
        ("checkpoint", {"checkpoint": {}}),
        (
            "submit",
            {"head_sha": HEAD, "base_sha": BASE, "spec_hash": spec_hash(spec())},
        ),
    ]:
        with pytest.raises(QueueError, match="expired"):
            h.owned(verb, **args)
    h.register("dootz1", "windows", "win1")
    h.plan("2", paths=["docs/new.md"], resources=["gpu:windows:0"])
    assert h.next("dootz1", "windows", "win1")["status"] == "idle"
    with pytest.raises(QueueError, match="terminal proof"):
        h.owned("recover")


def test_original_host_terminal_proof_required_before_recovery_and_epoch_increases():
    h = Harness().running(resources=["gpu:windows:0"])
    h.now += LEASE_SECONDS
    for proof in [
        terminal_proof("other"),
        {**terminal_proof(), "terminal": False},
        {**terminal_proof(), "store": {}},
    ]:
        with pytest.raises(QueueError):
            h.owned("recover", terminal_proof=proof)
    h.owned("recover", terminal_proof=terminal_proof())
    grant = h.next()
    assert grant["epoch"] == 2
    assert grant["claim"]["branch"].endswith("-e2")
    with pytest.raises(QueueError, match="epoch"):
        h.owned("heartbeat")


def test_scope_expansion_is_atomic_and_semantics_cannot_change():
    h = Harness().running()
    h.plan("2", paths=["docs/"])
    h.register("dootz1", "windows", "win1")
    h.next("dootz1", "windows", "win1")
    before = copy.deepcopy(h.state)
    with pytest.raises(QueueError, match="conflicts"):
        h.owned("extend-scope", spec=spec(paths=["backend/clock.py", "docs/new.md"]))
    assert h.state == before
    with pytest.raises(QueueError, match="semantics"):
        h.owned("extend-scope", spec=spec(outcome="Do anything"))
    with pytest.raises(QueueError, match="only add"):
        h.owned("extend-scope", spec=spec(paths=["tests/new.py"]))
    new_spec = spec(paths=["backend/clock.py", "tests/test_clock.py"])
    h.owned("extend-scope", spec=new_spec)
    assert h.state["tasks"]["1"]["claim"]["spec_hash"] == spec_hash(new_spec)


def test_active_plan_cannot_replace_granted_scope():
    h = Harness().running()
    with pytest.raises(QueueError, match="scope change"):
        h.plan(paths=["backend/"])


def test_review_requires_distinct_session_and_exact_binding():
    h = Harness().running()
    h.submit()
    assert h.send("review-next", host_id="mac", session_id="mac1")["status"] == "idle"
    h.register("dootz1", "windows", "win1")
    receipt = h.send("review-next", "dootz1", host_id="windows", session_id="win1")
    assert receipt["claim"]["head_sha"] == HEAD
    with pytest.raises(QueueError, match="stale"):
        h.review_result(head_sha=MERGE)
    h.review_result()
    assert h.state["tasks"]["1"]["review"]["verdict"] == "approve"


def test_distinct_reviewer_session_on_implementation_host():
    h = Harness().running()
    h.submit()
    h.register(session_id="review1")
    grant = h.send("review-next", host_id="mac", session_id="review1")
    assert grant["status"] == "granted"
    assert h.state["workers"]["mac/mac1"]["session_id"] == "mac1"


def test_checkpoint_renews_lease():
    h = Harness().running()
    h.now += 200
    h.owned("checkpoint", checkpoint={"head": HEAD})
    assert h.state["tasks"]["1"]["claim"]["expires_at"] == h.now + LEASE_SECONDS


def test_submit_requires_pr_and_review_requires_evidence():
    h = Harness().running()
    with pytest.raises(QueueError, match="pr_number"):
        h.owned(
            "submit",
            head_sha=HEAD,
            base_sha=BASE,
            spec_hash=h.state["tasks"]["1"]["spec_hash"],
        )
    h.submit()
    assert h.state["tasks"]["1"]["pr_number"] == 10
    h.register("dootz1", "windows", "win1")
    h.send("review-next", "dootz1", host_id="windows", session_id="win1")
    with pytest.raises(QueueError, match="findings"):
        h.send(
            "review-result",
            "dootz1",
            task_id="1",
            host_id="windows",
            session_id="win1",
            epoch=1,
            review_epoch=1,
            verdict="approve",
            **h.state["tasks"]["1"]["submission"],
        )


def test_three_repairs_escalate_without_releasing_reservations():
    h = Harness()
    h.reviewing()
    for iteration in range(3):
        if iteration:
            h.submit()
            h.send("review-next", "dootz1", host_id="windows", session_id="win1")
        h.review_result("changes")
    assert h.state["tasks"]["1"]["status"] == "needs_human"
    assert h.state["tasks"]["1"]["claim"]["epoch"] == 1
    h.config["human_approvers"] = ["Ken0u"]
    with pytest.raises(QueueError, match="approval"):
        h.send(
            "human-approved", task_id="1", spec_hash=h.state["tasks"]["1"]["spec_hash"]
        )
    h.owned("release", terminal_proof=terminal_proof())
    assert h.state["tasks"]["1"]["status"] == "needs_human"
    h.send("human-approved", task_id="1", spec_hash=h.state["tasks"]["1"]["spec_hash"])
    assert h.next()["epoch"] == 2


def test_expired_review_can_be_reassigned_without_freeing_implementation():
    h = Harness()
    h.reviewing()
    h.now += LEASE_SECONDS
    h.state = expire_leases(h.state, h.now)
    assert h.state["tasks"]["1"]["status"] == "review"
    assert "review_claim" not in h.state["tasks"]["1"]
    assert (
        h.send("review-next", "dootz1", host_id="windows", session_id="win1")["status"]
        == "granted"
    )
    assert h.state["tasks"]["1"]["review_epoch"] == 2
    with pytest.raises(QueueError, match="review epoch"):
        h.send(
            "review-result",
            "dootz1",
            task_id="1",
            host_id="windows",
            session_id="win1",
            epoch=1,
            review_epoch=1,
            verdict="approve",
            **h.state["tasks"]["1"]["submission"],
        )


def test_review_changes_returns_to_owner_and_submit_invalidates_old_review():
    h = Harness()
    h.reviewing()
    h.review_result("changes")
    assert h.state["tasks"]["1"]["status"] == "running"
    h.submit()
    assert "review" not in h.state["tasks"]["1"]


def test_worker_cannot_claim_merge_success_and_coordinator_requires_checks():
    h = Harness()
    h.reviewing()
    h.review_result()
    binding = h.state["tasks"]["1"]["submission"]
    with pytest.raises(QueueError, match="coordinator"):
        h.send("integrate", task_id="1", checks_passed=True, **binding)
    with pytest.raises(QueueError, match="checks"):
        h.send("integrate", "github-actions[bot]", task_id="1", **binding)
    with pytest.raises(QueueError, match="binding"):
        h.send(
            "integrate",
            "github-actions[bot]",
            task_id="1",
            checks_passed=True,
            **{**binding, "head_sha": MERGE},
        )
    h.send(
        "integrate", "github-actions[bot]", task_id="1", checks_passed=True, **binding
    )
    h.send(
        "verify-main",
        "github-actions[bot]",
        task_id="1",
        merge_sha=MERGE,
        checks_passed=False,
    )
    assert h.state["tasks"]["1"]["status"] == "verifying_main"
    h.send(
        "verify-main",
        "github-actions[bot]",
        task_id="1",
        merge_sha=MERGE,
        checks_passed=True,
    )
    assert h.state["tasks"]["1"]["status"] == "done"


def test_coordinator_invalidation_removes_bound_review():
    h = Harness()
    h.reviewing()
    h.review_result()
    h.send("invalidate-review", "github-actions[bot]", task_id="1")
    assert "review" not in h.state["tasks"]["1"]
    assert h.state["tasks"]["1"]["status"] == "running"


def test_approved_review_is_not_assigned_again():
    h = Harness()
    h.reviewing()
    h.review_result()
    assert (
        h.send("review-next", "dootz1", host_id="windows", session_id="win1")["status"]
        == "idle"
    )


def test_recovery_does_not_accept_live_process_or_nonterminal_store():
    h = Harness().running()
    proof = terminal_proof()
    for section, key, value in [
        ("process", "exited", False),
        ("process", "creation_time", None),
        ("process", "cwd", ""),
        ("store", "status", "running"),
    ]:
        changed = copy.deepcopy(proof)
        changed[section][key] = value
        with pytest.raises(QueueError):
            h.owned("recover", terminal_proof=changed)


def test_unknown_command_and_invalid_clock_fail():
    h = Harness().running()
    with pytest.raises(QueueError, match="unknown verb"):
        h.owned("teleport")
    with pytest.raises(QueueError, match="now"):
        expire_leases(h.state, True)
