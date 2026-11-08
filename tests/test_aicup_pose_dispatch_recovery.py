"""Generated recovery controls; never open the private scientific inputs."""

import copy
import io
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
from badminton import aicup_pose_dispatch_recovery as recovery
from badminton import aicup_pose_learning as learning
from badminton import aicup_pose_scaling as scaling
from test_aicup_pose_scaling import (  # noqa: F401
    cohort_case,
    combined_case,
    metadata_operation,
    run_case,
)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(recovery.encoded(value))


def commit(root):
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    (root / ".gitattributes").write_bytes(b"* text eol=lf\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Generated",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "Generated frozen snapshot",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return recovery.git(root, "rev-parse", "HEAD")


GENERATED_API = """
import json, os
from pathlib import Path
from types import SimpleNamespace
learning = SimpleNamespace(validate_workspace=lambda _: None)
def prospective(path, expected, clock):
    return json.loads(path.read_text())
def original_inputs(plan):
    return None
def input_sources(plan):
    return None
def run(prospective_path, prospective_sha256, output):
    plan = prospective(prospective_path, prospective_sha256, True)
    assert os.environ['BADMINTON_ROOT'] == plan['workspace']
    assert os.environ['BADMINTON_DATA_DIR'] == str(Path(plan['workspace']) / 'data/processed')
    assert os.environ['BADMINTON_WEIGHTS_DIR'] == str(Path(plan['workspace']) / 'models/weights')
    assert not any('TOKEN' in k or 'SECRET' in k for k in os.environ)
    output.mkdir(exist_ok=False)
    (output / 'completion.json').write_text('{}')
    return dict(api='run', original_output=str(output))
def verify(prospective_path, prospective_sha256, output):
    assert (output / 'completion.json').is_file()
    return dict(api='verify', new_decodes=0, real_fits=0)
"""


@pytest.fixture
def generated(tmp_path, monkeypatch):
    from badminton.storage import Store

    now = 1793864900.0
    monkeypatch.setattr(recovery.time, "time", lambda: now)
    root = tmp_path / "workspace"
    cache = root / ".cache"
    snapshot = cache / "worktrees/scientific"
    backend = snapshot / "backend/badminton"
    backend.mkdir(parents=True)
    (backend / "__init__.py").write_bytes(b"")
    (backend / "aicup_pose_scaling.py").write_text(
        GENERATED_API, encoding="utf-8", newline="\n"
    )
    revision = commit(snapshot)
    protocol = copy.deepcopy(recovery.PROTOCOL)
    protocol["scientific_commit"] = revision
    monkeypatch.setattr(recovery, "PROTOCOL", protocol)
    plan = {
        "workspace": str(root),
        "output": str(cache / "pose397-run-v1"),
        "prospective_directory": str(cache / "pose397-freeze-v1"),
        "tested_commit": revision,
        "granted_at": protocol["original_granted_at"],
        "committed_at": protocol["original_committed_at"],
        "deadline": protocol["scientific_deadline"],
        "protocol": {
            "name": "generated-original",
            "sources": {"archive": "generated"},
            "limits": {
                "task_seconds": 57600,
                "operation_seconds": 43200,
                "output_bytes": protocol["limits"]["output_bytes"],
            },
        },
        "runtime": {"executable": sys.executable},
        "code": {
            str(p.relative_to(snapshot)).replace("\\", "/"): recovery.digest(p)
            for p in backend.iterdir()
        },
    }
    original = Path(plan["prospective_directory"]) / "prospective.json"
    save(original, plan)
    protocol["prospective_sha256"] = recovery.digest(original)
    claim = cache / "generated-original-generated-start.json"
    claim_data = {
        "prospective_sha256": protocol["prospective_sha256"],
        "output": plan["output"],
        "committed_at": plan["committed_at"],
        "deadline": plan["deadline"],
    }
    # Noncanonical whitespace proves accounting uses actual claim-file bytes.
    claim.write_bytes(recovery.encoded(claim_data) + b" " * 200)
    protocol["claim_sha256"] = recovery.digest(claim)
    command = [
        sys.executable,
        str(cache / "worktrees/pose397-e1/scripts/scale_aicup_pose_learning.py"),
        "run",
        "--prospective",
        str(original),
    ]
    save(cache / "pose397-original-invocation-v1.json", {"command": command})
    save(
        cache / "pose397-original-process-v1.json",
        {
            "pid": 1048576,
            "created_at": 1,
            "cwd": str(cache / "worktrees/pose397-e1"),
            "command": command,
        },
    )
    (cache / "pose397-original-stderr-v1.log").write_bytes(
        b"TypeError: run() got an unexpected keyword argument 'prospective'\n"
    )
    (cache / "pose397-original-stdout-v1.log").write_bytes(b"")
    save(
        cache / "pose397-original-run-v1-verification.json",
        {
            "exit_code": 1,
            "original_process_absent": True,
            "original_run_consumed": True,
            "consumer_commit": revision,
            "prospective_sha256": protocol["prospective_sha256"],
            "stderr_sha256": recovery.digest(cache / "pose397-original-stderr-v1.log"),
            "stdout_sha256": recovery.digest(cache / "pose397-original-stdout-v1.log"),
        },
    )
    save(
        cache / "pose397-predispatch-failure-proof-v1.json",
        {
            "public": {
                "scientific_operations_started": 0,
                "new_decodes": 0,
                "new_model_observations": 0,
                "real_fits": 0,
                "run_output_absent": True,
                "original_process_absent": True,
                "prospective_sha256": protocol["prospective_sha256"],
                "original_deadline": plan["deadline"],
            }
        },
    )
    protocol["proofs"] = {
        name: recovery.digest(cache / name) for name in protocol["proofs"]
    }
    grant = protocol["grant"] | {
        "spec_hash": protocol["spec_hash"],
        "expires_at": now + 100,
        "branch": "codex/issue-398-perform-the-first-actual-dispatch-of-the",
    }
    state = {
        "at": now,
        "task": {
            "status": "running",
            "epoch": 1,
            "spec_hash": protocol["spec_hash"],
            "claim": grant,
        },
        "grant_receipt": {
            "status": "granted",
            "task_id": "398",
            "epoch": 1,
            "claim": copy.deepcopy(grant),
        },
    }
    grant_path, protocol_path = cache / "grant.json", cache / "protocol.json"
    save(grant_path, state)
    save(protocol_path, protocol)
    monkeypatch.setattr(
        recovery, "tested_source", lambda: ("a" * 40, {"wrapper": "sealed"})
    )
    store = Store(root / "data/processed")
    return SimpleNamespace(
        root=root,
        cache=cache,
        snapshot=snapshot,
        plan=plan,
        original=original,
        output=Path(plan["output"]),
        companion=original.parent / "dispatch-recovery-v1",
        claim=claim,
        protocol=protocol,
        protocol_path=protocol_path,
        grant_path=grant_path,
        state=state,
        store=store,
        args={
            "workspace": root,
            "snapshot": snapshot,
            "grant_state": grant_path,
            "protocol": protocol_path,
        },
    )


def prepared(generated):
    result = recovery.prepare(**generated.args)
    publication = generated.cache / "publication.json"
    save(
        publication,
        {
            "task": 398,
            "intent_sha256": result["intent_sha256"],
            "wrapper_commit": result["wrapper_commit"],
            "prospective_sha256": generated.protocol["prospective_sha256"],
            "at": time.time(),
            "comment_url": "https://github.com/Ken0u/badminton-match-analyzer/issues/398#issuecomment-123",
        },
    )
    return {
        "workspace": generated.root,
        "intent_sha256": result["intent_sha256"],
        "grant_state": generated.grant_path,
        "publication": publication,
    }


@contextmanager
def terminal_child(generated, monkeypatch, code=None, observation_delay=0):
    """Keep a real generated child alive until its real identity is captured.

    Readiness proves that Python has entered the final command, rather than a
    transient launcher. The separate release follows production process.json
    publication. No production observer, identity field or limit is replaced.
    """
    ready = generated.cache / "fixture-child-ready"
    release = generated.cache / "fixture-child-release"
    prefix = (
        "import os, time; from pathlib import Path\n"
        f"Path({str(ready)!r}).write_text(str(os.getpid()))\n"
        "fixture_deadline = time.monotonic() + 20\n"
        f"while not Path({str(release)!r}).exists():\n"
        "    if time.monotonic() >= fixture_deadline:\n"
        "        raise RuntimeError('Generated identity release not received')\n"
        "    time.sleep(0.005)\n"
    )
    command = (
        recovery.child_command(
            generated.snapshot, generated.plan, generated.original, "run"
        )
        if code is None
        else [sys.executable, "-I", "-B", "-c", code]
    )
    # The Windows venv executable is a launcher with a different PID from the
    # Python child that executes the readiness code. Generated children need
    # only stdlib, so launch the actual interpreter to observe a single lifetime.
    command = [
        getattr(sys, "_base_executable", sys.executable)
        if sys.platform == "win32"
        else command[0],
        *command[1:4],
        prefix + command[4],
        *command[5:],
    ]
    spawn, publish = subprocess.Popen, recovery.publish
    children, observed_handles, identities = [], [], []

    def synchronized_spawn(actual, *args, **kwargs):
        process = spawn(actual, *args, **kwargs)
        if actual != command:
            return process
        children.append(process)
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert process.poll() is None, "Generated child exited before readiness"
            assert time.monotonic() < deadline, "No generated child readiness"
            time.sleep(0.005)
        assert int(ready.read_text()) == process.pid
        native = psutil.Process(process.pid)
        assert native.cmdline() == command, {
            "launched_command": command,
            "observed_command": native.cmdline(),
        }
        assert native.cwd() == str(generated.snapshot), {
            "launched_cwd": str(generated.snapshot),
            "observed_cwd": native.cwd(),
        }
        observed_handles.append(process)
        return process

    def observed(path, value):
        result = publish(path, value)
        if Path(path) == generated.companion / "launched.json":
            # Deliberately give a fast child time to exit in the original tests.
            # The handshake keeps the subject live independently of scheduling.
            time.sleep(observation_delay)
        if Path(path) == generated.companion / "process.json":
            native = psutil.Process(value["pid"])
            assert children[0].poll() is None
            assert value == {
                "pid": native.pid,
                "created_at": native.create_time(),
                "cwd": native.cwd(),
                "command": native.cmdline(),
            }
            assert value["command"] == command
            assert value["cwd"] == str(generated.snapshot)
            identities.append(value)
            release.write_bytes(b"observed")
        return result

    with monkeypatch.context() as scoped:
        scoped.setattr(recovery, "child_command", lambda *_: command)
        scoped.setattr(recovery.subprocess, "Popen", synchronized_spawn)
        scoped.setattr(recovery, "publish", observed)
        try:
            yield identities
        finally:
            # Release only these fixture-owned children on an assertion failure;
            # no termination signal or claim of absence follows from a timeout.
            release.write_bytes(b"fixture cleanup")
            for process in children:
                if process.poll() is None:
                    # Failed startup may precede production reader creation;
                    # drain the owned pipes instead of stranding overflow output.
                    if process not in observed_handles:
                        process.communicate(timeout=15)
                    else:
                        process.wait(timeout=15)


def test_public_protocol_and_import_do_not_load_numerical_runtime():
    root = Path(recovery.__file__).resolve().parents[2]
    assert (
        recovery.read(
            root / "data/manifests/aicup_pose_dispatch_recovery_protocol_v1.json"
        )
        == recovery.PROTOCOL
    )
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import sys; sys.path.insert(0,sys.argv[1]); from badminton import aicup_pose_dispatch_recovery; "
            "assert 'torch' not in sys.modules; assert 'badminton.config' not in sys.modules",
            str(root / "backend"),
        ],
        capture_output=True,
        check=True,
    )


@pytest.mark.parametrize("action", ["run", "verify"])
def test_isolated_child_binds_original_api_arguments_before_opening_any_input(
    tmp_path, action
):
    root = Path(recovery.__file__).resolve().parents[2]
    output = tmp_path / "never-created"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            recovery.CHILD,
            str(root / "backend"),
            action,
            str(tmp_path / "missing.json"),
            "0" * 64,
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "FileNotFoundError" in result.stderr and "TypeError" not in result.stderr
    assert not output.exists()


@pytest.mark.parametrize("action", ["prepare", "dispatch", "verify"])
def test_public_recovery_cli_reaches_its_validator(tmp_path, action):
    root = Path(recovery.__file__).resolve().parents[2]
    args = [
        "--workspace",
        str(tmp_path),
        "--grant-state",
        str(tmp_path / "missing-grant.json"),
    ]
    if action == "prepare":
        args += [
            "--snapshot",
            str(tmp_path),
            "--protocol",
            str(tmp_path / "missing-protocol.json"),
        ]
    else:
        args += ["--intent-sha256", "0" * 64]
        if action == "dispatch":
            args += ["--publication", str(tmp_path / "missing-publication.json")]
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(root / "scripts/recover_aicup_pose_dispatch.py"),
            action,
            *args,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "FileNotFoundError" in result.stderr and "TypeError" not in result.stderr
    assert not (tmp_path / ".cache").exists()


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'])
def test_receipts_reject_duplicate_and_nonfinite_json(tmp_path, raw):
    path = tmp_path / "bad.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        recovery.read(path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("at", 0),
        ("at", 1793864901),
        ("status", "ready"),
        ("epoch", 2),
        ("spec_hash", "0" * 64),
        ("actor", "another"),
        ("host_id", "another"),
        ("session_id", "another"),
        ("expires_at", 1793864900),
        ("granted_at", 1793864901),
        ("branch", "another"),
    ],
)
def test_stale_or_different_grant_cannot_prepare(generated, field, value):
    state = generated.state
    if field == "at":
        state[field] = value
    elif field in ("status", "epoch", "spec_hash"):
        state["task"][field] = value
    else:
        state["task"]["claim"][field] = value
    save(generated.grant_path, state)
    with pytest.raises(ValueError):
        recovery.prepare(**generated.args)
    assert not generated.companion.exists() and not generated.output.exists()


def test_grant_receipt_is_required_even_with_correct_task_claim(generated):
    generated.state["grant_receipt"]["claim"]["session_id"] = "forged"
    save(generated.grant_path, generated.state)
    with pytest.raises(ValueError, match="matching committed"):
        recovery.prepare(**generated.args)


def test_lease_extension_cannot_reset_original_deadline_or_forecast(
    generated, monkeypatch
):
    now = (
        generated.protocol["scientific_deadline"]
        - generated.protocol["limits"]["forecast_seconds"]
        - 7199
    )
    monkeypatch.setattr(recovery.time, "time", lambda: now)
    generated.state["at"] = now
    generated.state["task"]["claim"]["expires_at"] = now + 10000
    save(generated.grant_path, generated.state)
    with pytest.raises(ValueError, match="headroom"):
        recovery.prepare(**generated.args)
    assert not generated.companion.exists()


@pytest.mark.parametrize(
    "field",
    ["tested_commit", "granted_at", "committed_at", "deadline", "output", "workspace"],
)
def test_even_resealed_plan_cannot_change_original_commitment(generated, field):
    generated.plan[field] = "changed" if isinstance(generated.plan[field], str) else 0
    save(generated.original, generated.plan)
    generated.protocol["prospective_sha256"] = recovery.digest(generated.original)
    with pytest.raises(ValueError):
        recovery.paths(generated.root)


@pytest.mark.parametrize(
    "target", ["prospective", "claim", *recovery.PROTOCOL["proofs"]]
)
def test_missing_or_changed_seals_refuse_before_companion_creation(generated, target):
    path = {"prospective": generated.original, "claim": generated.claim}.get(
        target, generated.cache / target
    )
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        recovery.prepare(**generated.args)
    assert not generated.companion.exists() and not generated.output.exists()


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("pose397-predispatch-failure-proof-v1.json", "real_fits", 1),
        ("pose397-predispatch-failure-proof-v1.json", "new_decodes", 1),
        (
            "pose397-predispatch-failure-proof-v1.json",
            "scientific_operations_started",
            1,
        ),
        ("pose397-original-run-v1-verification.json", "exit_code", 0),
        ("pose397-original-process-v1.json", "cwd", "changed"),
    ],
)
def test_resealed_but_contradictory_predecessor_proof_is_rejected(
    generated, target, field, value
):
    path = generated.cache / target
    data = recovery.read(path)
    (data["public"] if "public" in data else data)[field] = value
    save(path, data)
    generated.protocol["proofs"][target] = recovery.digest(path)
    save(generated.protocol_path, generated.protocol)
    with pytest.raises(ValueError):
        recovery.prepare(**generated.args)
    assert not generated.companion.exists()


def test_live_original_process_or_unobservable_identity_is_never_absent(monkeypatch):
    process = psutil.Process()
    identity = {"pid": process.pid, "created_at": process.create_time()}
    with pytest.raises(ValueError, match="live original"):
        recovery.absent_process(identity)
    recovery.absent_process(
        {"pid": process.pid, "created_at": process.create_time() - 100}
    )
    monkeypatch.setattr(
        psutil, "Process", lambda _: (_ for _ in ()).throw(psutil.AccessDenied())
    )
    with pytest.raises(psutil.AccessDenied):
        recovery.absent_process(identity)


@pytest.mark.parametrize("collision", ["output", "store"])
def test_existing_output_or_shared_work_prevents_science(generated, collision):
    if collision == "output":
        generated.output.mkdir()
        (generated.output / "partial.json").write_bytes(b"preserve")
    else:
        generated.store.claim_job(
            {"id": "other-owner", "kind": "players", "status": "running"}
        )
    with pytest.raises(ValueError, match="Preserve"):
        recovery.prepare(**generated.args)
    assert not generated.companion.exists()
    if collision == "store":
        assert generated.store.job("other-owner")["status"] == "running"


@pytest.mark.parametrize("change", ["tracked", "untracked", "bytecode"])
def test_frozen_scientific_snapshot_rejects_source_or_import_changes(generated, change):
    backend = generated.snapshot / "backend/badminton"
    path = (
        backend
        / {
            "tracked": "aicup_pose_scaling.py",
            "untracked": "injected.py",
            "bytecode": "injected.pyc",
        }[change]
    )
    path.write_bytes(b"changed")
    with pytest.raises(ValueError):
        recovery.scientific_snapshot(generated.snapshot, generated.root, generated.plan)


def test_child_strips_credentials_and_roots_before_import(generated, monkeypatch):
    for key in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "MY_SECRET",
        "PASSWORD",
        "OPENAI_API_KEY",
        "AUTH_COOKIE",
        "CREDENTIAL_PATH",
    ):
        monkeypatch.setenv(key, "generated-secret-value")
    monkeypatch.setenv("PYTHONPATH", "untrusted")
    env = recovery.child_environment(generated.root)
    assert "generated-secret-value" not in env.values() and "PYTHONPATH" not in env
    assert env["BADMINTON_ROOT"] == str(generated.root)
    command = recovery.child_command(
        generated.snapshot, generated.plan, generated.original, "check"
    )
    assert command[1:4] == ["-I", "-B", "-c"]
    subprocess.run(
        command, cwd=generated.snapshot, env=env, capture_output=True, check=True
    )


def test_output_accounting_counts_actual_claim_bytes(generated):
    expected = generated.original.stat().st_size + generated.claim.stat().st_size
    assert recovery.output_budget(generated.original, generated.output) == expected
    with pytest.raises(ValueError, match="budget"):
        recovery.output_budget(
            generated.original,
            generated.output,
            generated.protocol["limits"]["output_bytes"] - expected + 1,
        )


def test_prepare_preserves_original_and_uses_exclusive_intent(generated):
    original_bytes, claim_bytes = (
        generated.original.read_bytes(),
        generated.claim.read_bytes(),
    )
    recovery.prepare(**generated.args)
    assert generated.original.read_bytes() == original_bytes
    assert generated.claim.read_bytes() == claim_bytes
    assert not generated.output.exists()
    assert recovery.read(generated.companion / "terminal.json")["terminal"] is False
    assert (
        generated.companion / "scientific.stdout"
    ).stat().st_size == generated.protocol["limits"]["log_slot_bytes"]
    with pytest.raises(ValueError, match="existing recovery"):
        recovery.prepare(**generated.args)


@pytest.mark.parametrize(
    "mutation", ["intent", "proof", "integrity", "publication", "grant", "protocol"]
)
def test_changed_dispatch_evidence_fails_before_consuming_attempt(generated, mutation):
    args = prepared(generated)
    if mutation == "grant":
        generated.state["task"]["claim"]["epoch"] = 2
        save(generated.grant_path, generated.state)
    elif mutation == "publication":
        value = recovery.read(args["publication"])
        value["wrapper_commit"] = "changed"
        save(args["publication"], value)
    elif mutation == "protocol":
        generated.protocol["scientific_deadline"] += 1
    else:
        name = {
            "intent": "intent.json",
            "proof": "pose397-original-process-v1.json",
            "integrity": "integrity.stdout",
        }[mutation]
        path = generated.companion / name
        path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        recovery.dispatch(**args)
    assert not (generated.companion / "dispatch-start.json").exists()
    assert not generated.output.exists()


def test_corrective_child_dispatch_is_single_use_and_verification_is_readonly(
    generated, monkeypatch
):
    args = prepared(generated)
    before = generated.original.read_bytes(), generated.claim.read_bytes()
    with terminal_child(generated, monkeypatch) as identities:
        result = recovery.dispatch(**args)
    assert len(identities) == 1 and result["process"] == identities[0]
    assert result["scientific_success"] is True and result["terminal"] is True
    assert result["original_process_absent"] is True
    assert result["corrective_invocation_consumed"] is True
    assert all(
        log["complete"] and not log["overflow"] for log in result["logs"].values()
    )
    assert before == (generated.original.read_bytes(), generated.claim.read_bytes())
    with pytest.raises(ValueError, match="Preserve"):
        recovery.dispatch(**args)
    args.pop("publication")
    verified = recovery.verify(**args)
    assert verified == {"api": "verify", "new_decodes": 0, "real_fits": 0}
    assert (
        recovery.read(generated.companion / "readonly-verification.json")["real_fits"]
        == 0
    )


def test_log_capture_never_exceeds_reserved_disk_bytes(tmp_path, monkeypatch):
    monkeypatch.setitem(recovery.PROTOCOL["limits"], "log_slot_bytes", 32)
    path = tmp_path / "log"
    recovery.reserve_slot(path, 32)
    state = {}
    recovery.capture_log(io.BytesIO(b"x" * 1000), path, state)
    assert path.read_bytes() == b"x" * 32
    assert state == {
        "bytes": 1000,
        "retained_bytes": 32,
        "overflow": True,
        "complete": True,
    }


def test_terminal_child_failure_remains_consumed_without_false_success(
    generated, monkeypatch
):
    args = prepared(generated)
    with terminal_child(
        generated, monkeypatch, "raise RuntimeError('generated failure')"
    ):
        with pytest.raises(ValueError, match="scientific operation failed"):
            recovery.dispatch(**args)
    receipt = recovery.read(generated.companion / "terminal.json")
    assert receipt["terminal"] is True and receipt["exit_code"] != 0
    assert (
        receipt["original_process_absent"] is True
        and receipt["scientific_success"] is False
    )
    assert not generated.output.exists()
    with pytest.raises(ValueError, match="terminal recovery"):
        recovery.dispatch(**args)


@pytest.mark.parametrize("completion", ["missing", "directory"])
@pytest.mark.parametrize("observation_delay", [0, 0.2])
def test_zero_exit_without_a_completion_file_never_persists_scientific_success(
    generated, monkeypatch, completion, observation_delay
):
    args = prepared(generated)
    code = (
        "from pathlib import Path; "
        f"output = Path({str(generated.output)!r}); output.mkdir(); "
        + ("(output / 'completion.json').mkdir()" if completion == "directory" else "")
    )
    before = generated.original.read_bytes(), generated.claim.read_bytes()
    with terminal_child(generated, monkeypatch, code, observation_delay) as identities:
        with pytest.raises(ValueError, match="No durable scientific completion"):
            recovery.dispatch(**args)
    assert len(identities) == 1
    receipt = recovery.read(generated.companion / "terminal.json")
    assert receipt["terminal"] is True and receipt["exit_code"] == 0
    assert receipt["original_process_absent"] is True
    assert receipt["scientific_success"] is False
    assert receipt["corrective_invocation_consumed"] is True
    assert before == (generated.original.read_bytes(), generated.claim.read_bytes())
    terminal_bytes = (generated.companion / "terminal.json").read_bytes()
    with pytest.raises(ValueError, match="Preserve original output"):
        recovery.dispatch(**args)
    assert terminal_bytes == (generated.companion / "terminal.json").read_bytes()
    args.pop("publication")
    with pytest.raises(ValueError, match="No successful terminal"):
        recovery.verify(**args)


@pytest.mark.parametrize("observation_delay", [0, 0.2])
def test_log_overflow_keeps_fixed_reservations_and_prevents_success(
    generated, monkeypatch, observation_delay
):
    args = prepared(generated)
    size = generated.protocol["limits"]["log_slot_bytes"]
    code = (
        "import sys; from pathlib import Path; "
        f"output = Path({str(generated.output)!r}); output.mkdir(); "
        "(output / 'completion.json').write_text('{}'); "
        "sys.stdout.buffer.write(b'x'*" + str(size + 100) + ")"
    )
    with terminal_child(generated, monkeypatch, code, observation_delay) as identities:
        with pytest.raises(ValueError, match="process/log observation"):
            recovery.dispatch(**args)
    assert len(identities) == 1
    receipt = recovery.read(generated.companion / "terminal.json")
    assert receipt["terminal"] is True and receipt["exit_code"] == 0
    assert receipt["scientific_success"] is False
    assert receipt["logs"]["stdout"]["overflow"] is True
    assert (generated.companion / "scientific.stdout").stat().st_size == size


def test_lost_process_identity_never_claims_absence_or_allows_restart(
    generated, monkeypatch
):
    args = prepared(generated)
    real_process = psutil.Process
    real_spawn = subprocess.Popen
    launched = []

    class Launched:
        pid = 999999
        stdout = io.BytesIO(b"")
        stderr = io.BytesIO(b"")

        def poll(self):
            return None

    def spawn(command, *args, **kwargs):
        if recovery.CHILD not in command:
            return real_spawn(command, *args, **kwargs)
        child = Launched()
        launched.append(child)
        return child

    def observe(pid, *args, **kwargs):
        if pid == 999999:
            raise psutil.AccessDenied(pid)
        return real_process(pid, *args, **kwargs)

    monkeypatch.setattr(recovery.subprocess, "Popen", spawn)
    monkeypatch.setattr(psutil, "Process", observe)
    with pytest.raises(psutil.AccessDenied):
        recovery.dispatch(**args)
    receipt = recovery.read(generated.companion / "terminal.json")
    assert receipt["terminal"] is False and receipt["process_state"] == "unknown"
    assert (
        receipt["original_process_absent"] is None
        and receipt["scientific_success"] is False
    )
    assert receipt["launched_pid"] == 999999
    with pytest.raises(FileExistsError):
        recovery.dispatch(**args)
    assert len(launched) == 1


def test_frozen_child_entry_reaches_actual_shared_store_api_and_readonly_verify(
    metadata_operation,  # noqa: F811
    monkeypatch,
    capsys,
):
    """The same CHILD text drives real run/verify bodies with generated inputs."""
    plan, store, result, predictions = metadata_operation
    fits = []

    def fit(data, output, progress):
        fits.append(output)
        output.mkdir()
        save(output / "predictions.json", [p.tolist() for p in predictions])
        return result

    monkeypatch.setattr(learning, "fit", fit)
    backend = Path(scaling.__file__).resolve().parents[1]
    args = [
        "generated-api",
        str(backend),
        "run",
        "generated-prospective",
        "generated-hash",
        plan["output"],
    ]
    monkeypatch.setattr(sys, "argv", args)
    exec(compile(recovery.CHILD, "<frozen-api-entry>", "exec"), {})
    capsys.readouterr()
    output = Path(plan["output"])
    process = recovery.read(output / "process.json")
    assert store.job(process["job_id"])["status"] == "completed"
    assert len(fits) == 1
    monkeypatch.setattr(learning, "verify_arm", lambda *_: (result, predictions))
    monkeypatch.setattr(learning, "fit", lambda *_: pytest.fail("Verification refit"))
    monkeypatch.setattr(
        scaling, "new_clip", lambda *_: pytest.fail("Verification decoded")
    )
    args[2] = "verify"
    exec(compile(recovery.CHILD, "<frozen-api-entry>", "exec"), {})
    assert len(fits) == 1
