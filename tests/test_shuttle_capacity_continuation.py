"""Disposable continuation guards; no scientific media, labels or weights opened."""

import copy
import hashlib
import time

import pytest
from badminton import shuttle_capacity_continuation as study


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    study.publish(path, value)
    return study.audit.file_hash(path)


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    root = tmp_path
    output = root / ".cache/capacity313-generated"
    source = root / "generated.py"
    source.write_bytes(b"generated source\n")
    code = {"badminton/generated.py": study.audit.seal(root, source)}
    old = {"views": [{"id": "a"}, {"id": "b"}]}
    ready = {"predecessor_view_seals": {"old": "seal"}}
    monkeypatch.setattr(study, "consumers", lambda root: code)
    monkeypatch.setattr(study.existing, "runtime_snapshot", lambda: {"generated": True})
    monkeypatch.setattr(study, "validate_predecessor", lambda root: (old, ready, []))
    monkeypatch.setattr(
        study.predecessor, "diagnostic_inputs", lambda *args: ({}, [], {}, {}, {}, {})
    )
    monkeypatch.setattr(study, "compare_control", lambda *args: {"compatible": True})
    monkeypatch.setattr(
        study.predecessor,
        "completed_views",
        lambda *args: {"a": ({}, {"processed_frames": 1})},
    )
    protocol = copy.deepcopy(study.PROTOCOL)
    protocol.update(imported_control_views=1, imported_control_rows=1)
    monkeypatch.setattr(study, "PROTOCOL", protocol)

    def ignored(root, output):
        output.mkdir(parents=True, exist_ok=False)
        return output

    monkeypatch.setattr(study.audit, "ignored_output", ignored)
    public = root / "protocol.json"
    checksum = put(public, protocol)
    began = time.time() - 2
    result = study.freeze(root, public, checksum, output, began, began + 14400)
    return root, output, result["experiment_sha256"], source


def test_protocol_preserves_exact_remaining_scope():
    study.validate_protocol(copy.deepcopy(study.PROTOCOL))
    for key in ("threshold", "views", "predecessor_deadline", "retained_bytes"):
        value = copy.deepcopy(study.PROTOCOL)
        value[key] += 1
        with pytest.raises(ValueError, match="fixed remaining"):
            study.validate_protocol(value)


def test_frozen_continuation_loads_without_rewriting_old_clock(frozen):
    root, output, expected, _ = frozen
    value = study.load(root, output, expected)
    assert value["deadline"] == value["granted_at"] + 14400
    assert value["predecessor_views"] == {"old": "seal"}
    assert study.PROTOCOL["predecessor_deadline"] == 1792981031


@pytest.mark.parametrize("kind", ["source", "copy", "protocol", "experiment"])
def test_changed_frozen_bytes_refuse_before_native_inputs(frozen, monkeypatch, kind):
    root, output, expected, source = frozen
    target = {
        "source": source,
        "copy": output / "consumer/badminton/generated.py",
        "protocol": output / "protocol.json",
        "experiment": output / "experiment.json",
    }[kind]
    target.write_bytes(target.read_bytes() + b" ")
    monkeypatch.setattr(
        study.predecessor,
        "diagnostic_inputs",
        lambda *args: pytest.fail("no native inputs on tamper"),
    )
    with pytest.raises(ValueError, match="Changed"):
        study.native_variant(root, output, expected, "control")


@pytest.mark.parametrize("kind", ["expired", "extended", "boolean"])
def test_continuation_deadline_cannot_be_renewed(frozen, kind):
    root, output, _, _ = frozen
    value = study.audit.read_json((output / "experiment.json").read_bytes())
    if kind == "expired":
        value.update(granted_at=time.time() - 15000, deadline=time.time() - 600)
    elif kind == "extended":
        value["deadline"] += 3600
    else:
        value["granted_at"] = True
    (output / "experiment.json").write_bytes(study.audit.encoded(value))
    with pytest.raises(ValueError, match="deadline expired or changed"):
        study.load(root, output, study.audit.file_hash(output / "experiment.json"))


def test_predecessor_expired_loader_keeps_its_original_rejection(tmp_path):
    output = tmp_path / ".cache/old"
    checksum = put(output / "experiment.json", {"deadline": 1})
    with pytest.raises(ValueError, match="Original research runtime allowance expired"):
        study.predecessor.load(tmp_path, output, checksum)


def test_changed_predecessor_membership_is_not_new_provenance(frozen, monkeypatch):
    root, output, expected, _ = frozen
    monkeypatch.setattr(
        study,
        "validate_predecessor",
        lambda root: (
            {"views": [{"id": "different"}]},
            {"predecessor_view_seals": {}},
            [],
        ),
    )
    with pytest.raises(ValueError, match="predecessor continuation binding"):
        study.load(root, output, expected)


def tensor_states(method):
    torch = pytest.importorskip("torch")
    names = study.predecessor.trainable_names(method)
    parent = {name: torch.zeros(2) for name in names}
    parent.update(
        {"frozen." + str(index): torch.zeros(2) for index in range(104 - len(names))}
    )
    selected = {name: value.clone() for name, value in parent.items()}
    for name in names:
        selected[name].add_(1)
    frozen = {
        name: hashlib.sha256(value.numpy().tobytes()).hexdigest()
        for name, value in parent.items()
        if name not in names
    }
    return parent, selected, frozen


@pytest.mark.parametrize("method,count", [("decoder", 4), ("convolution", 19)])
def test_cpu_tensor_bytes_verify_exact_capacity_and_frozen_state(method, count):
    parent, selected, frozen = tensor_states(method)
    result = study.audit_states(parent, selected, method, frozen)
    assert len(result["changed_tensors"]) == count
    assert result["byte_equal_frozen_tensors"] == 104 - count
    assert result["all_tensors_read_on_cpu"]


@pytest.mark.parametrize(
    "change", ["frozen", "shape", "dtype", "nan", "missing", "eligible", "receipt"]
)
def test_cpu_tensor_audit_refuses_changed_or_incomplete_states(change):
    torch = pytest.importorskip("torch")
    parent, selected, frozen = tensor_states("decoder")
    eligible = study.predecessor.trainable_names("decoder")[0]
    if change == "frozen":
        selected["frozen.0"].add_(1)
    elif change == "shape":
        selected[eligible] = torch.ones(3)
    elif change == "dtype":
        selected[eligible] = selected[eligible].double()
    elif change == "nan":
        selected[eligible][0] = float("nan")
    elif change == "missing":
        selected.pop(eligible)
    elif change == "eligible":
        selected[eligible] = parent[eligible].clone()
    else:
        frozen["frozen.0"] = "wrong"
    with pytest.raises(ValueError):
        study.audit_states(parent, selected, "decoder", frozen)


def test_tensor_opening_is_exclusive_before_admission(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "load", lambda *args: {})
    monkeypatch.setattr(study, "admission", lambda *args: {"not_executed": True})
    study.tensor_audit(tmp_path, tmp_path, "a" * 64)
    with pytest.raises(FileExistsError):
        study.tensor_audit(tmp_path, tmp_path, "a" * 64)


def test_candidate_cannot_start_when_control_differs(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "load", lambda *args: {})
    monkeypatch.setattr(study, "require_tensor_audit", lambda *args: {})
    monkeypatch.setattr(study.predecessor, "diagnostic_inputs", lambda *args: ())
    monkeypatch.setattr(study, "control_gate", lambda *args: {"compatible": False})
    monkeypatch.setattr(
        study, "admission", lambda *args: pytest.fail("no candidate admission")
    )
    with pytest.raises(ValueError, match="mismatch blocks"):
        study.native_variant(tmp_path, tmp_path, "a" * 64, "convolution")


def control_example():
    rows = [
        {
            "frame": 4,
            "time_s": 0.135,
            "camera_segment_start_frame": 0,
            "shuttle": {
                "visible": True,
                "x": 5,
                "confidence": 0.8,
                "selection_context_start_frame": 4,
            },
        }
    ]
    view = {
        "id": "a",
        "video_id": "generated",
        "core_index": 0,
        "start_frame": 4,
        "end_frame": 5,
        "expected_rows_sha256": study.audit.digest(
            study.audit.encoded([study.existing.native_row(row) for row in rows])
        ),
    }
    experiment = {"views": [view]}
    originals = {("generated", 0): {"start_frame": 4, "frames": rows}}
    values = {"a": ({"origin": "predecessor"}, {"frames": copy.deepcopy(rows)})}
    return experiment, values, originals


def test_full_control_retains_exact_physical_projection_and_tolerance():
    experiment, values, originals = control_example()
    values["a"][1]["frames"][0]["shuttle"].update(
        confidence=0.800001, selection_context_start_frame=0
    )
    assert study.compare_control(experiment, values, originals)["compatible"]
    values["a"][1]["frames"][0]["shuttle"]["x"] = 6
    result = study.compare_control(experiment, values, originals)
    assert not result["compatible"] and result["differences"]
    assert result["omitted_dependency_fields"] == sorted(
        study.existing.DEPENDENCY_FIELDS
    )


def test_control_missing_or_changed_original_rows_fences_candidates():
    experiment, values, originals = control_example()
    with pytest.raises(ValueError, match="All original control views"):
        study.compare_control(experiment, {}, originals)
    originals[("generated", 0)]["frames"][0]["time_s"] = 0.2
    with pytest.raises(ValueError, match="Original control rows changed"):
        study.compare_control(experiment, values, originals)


def test_paired_transitions_retain_unknown_and_unavailable_cases():
    left = [
        {"id": "known", "outcome": "miss"},
        {"id": "unknown", "outcome": "unknown_truth"},
        {"id": "missing", "outcome": "unavailable_visible_output"},
    ]
    right = copy.deepcopy(left)
    right[0]["outcome"] = "correct_localization"
    assert study.paired_transitions(left, right) == {
        "miss->correct_localization": 1,
        "unknown_truth->unknown_truth": 1,
        "unavailable_visible_output->unavailable_visible_output": 1,
    }
    with pytest.raises(ValueError, match="membership"):
        study.paired_transitions(left, right[:2])


def test_report_does_not_open_labels_without_owning_issue_seal(tmp_path, monkeypatch):
    seal = {
        "comment": "https://github.com/Ken0u/badminton-match-analyzer/issues/311#issuecomment-1",
        "raw_index_sha256": "not-ready",
    }
    checksum = put(tmp_path / "raw-public-seal.json", seal)
    monkeypatch.setattr(
        study.predecessor, "diagnostic_inputs", lambda *args: pytest.fail("no scoring")
    )
    with pytest.raises(ValueError, match="owning-issue"):
        study.report(tmp_path, tmp_path, "a" * 64, checksum)


def test_budget_includes_predecessor_failures_and_both_worktrees(tmp_path, monkeypatch):
    for name in (
        ".cache/capacity311-failed/raw",
        ".cache/capacity313-generated/raw",
        ".cache/worktrees/capacity311-e1/owned",
        ".cache/worktrees/capacity313-e1/owned",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"123")
    assert study.budget(tmp_path)["bytes"] == 12
    monkeypatch.setitem(study.PROTOCOL, "retained_bytes", 11)
    with pytest.raises(ValueError, match="Cumulative"):
        study.budget(tmp_path)


def test_real_generated_store_admission_preserves_actual_live_owner(
    tmp_path, monkeypatch
):
    torch = pytest.importorskip("torch")
    from badminton import config
    from badminton.storage import Store

    output = tmp_path / ".cache/capacity313-generated"
    output.mkdir(parents=True)
    shared = tmp_path / "data/processed"
    store = Store(shared)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", shared)
    monkeypatch.setattr(config, "WEIGHTS", tmp_path / "models/weights")
    monkeypatch.setattr(study, "load", lambda *args: {"deadline": time.time() + 600})
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "reset_peak_memory_stats", lambda: None)
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda: 0)
    result = study.admission(
        tmp_path, output, "a" * 64, "tensor-audit", lambda *args: {"generated": True}
    )
    attempt = output / result["attempt"]
    admission = study.audit.read_json((attempt / "admission.json").read_bytes())
    terminal = study.audit.read_json((attempt / "terminal.json").read_bytes())
    assert terminal["status"] == "completed"
    assert store.job(admission["job_id"])["status"] == "completed"
    with pytest.raises(ValueError, match="still alive"):
        study.terminal_proof(output, shared)


@pytest.mark.parametrize("change", [None, "duplicate", "lineage", "bytes"])
def test_inherited_views_keep_original_seals_and_cannot_be_replaced(
    tmp_path, monkeypatch, change
):
    view = {
        "id": "a",
        "video_id": "generated",
        "core_index": 0,
        "start_frame": 4,
        "end_frame": 5,
    }
    old = tmp_path / study.PREVIOUS
    run_path = old / "attempts/generated/run.json"
    put(run_path, {"frames": [{"frame": 4, "time_s": 0.135}], "processed_frames": 1})
    receipt = old / "control/a.json"
    put(
        receipt,
        {
            "experiment_sha256": study.PROTOCOL["predecessor_experiment_sha256"],
            "view": view,
            "run": study.audit.seal(old, run_path),
        },
    )
    output = tmp_path / ".cache/capacity313-generated"
    experiment = {
        "views": [view],
        "predecessor_views": {
            receipt.relative_to(tmp_path).as_posix(): study.audit.file_hash(receipt)
        },
    }
    inputs = (
        {},
        [(None, {"id": "generated"}, [0.135], None)],
        {},
        {
            "evidence": {
                "catalogs": {
                    "generated": {"snapshot": {"annotations": {"source": "generated"}}}
                }
            }
        },
        {("generated", 0): {}},
        {},
    )
    seen = []
    monkeypatch.setattr(
        study.existing,
        "validate_research_run",
        lambda *args, **kwargs: seen.append((args, kwargs)),
    )
    if change == "duplicate":
        put(output / "control/a.json", {})
    elif change == "lineage":
        value = study.audit.read_json(receipt.read_bytes())
        value["experiment_sha256"] = "new-study"
        receipt.write_bytes(study.audit.encoded(value))
        experiment["predecessor_views"][receipt.relative_to(tmp_path).as_posix()] = (
            study.audit.file_hash(receipt)
        )
    elif change == "bytes":
        run_path.write_bytes(b"{}")
    if change:
        with pytest.raises(ValueError):
            study.completed_views(
                tmp_path, output, "control", experiment, "new", inputs
            )
    else:
        values = study.completed_views(
            tmp_path, output, "control", experiment, "new", inputs
        )
        assert values["a"][0]["origin"] == "predecessor"
        assert values["a"][0]["run"] == study.audit.seal(tmp_path, run_path)
        assert seen[0][0][1] == view
        assert seen[0][1]["annotations"] == {"source": "generated"}
        assert not (output / "control/a.json").exists()


@pytest.mark.parametrize(
    "status,worker", [("completed", None), ("completed", "failed"), ("running", None)]
)
def test_terminal_gate_never_infers_worker_success_from_store(
    tmp_path, monkeypatch, status, worker
):
    admission = tmp_path / "attempts/generated/admission.json"
    put(admission, {"stage": "control"})
    monkeypatch.setattr(
        study.existing,
        "prior_attempt_proof",
        lambda *args: [
            {"admission": study.audit.seal(tmp_path, admission), "store_status": status}
        ],
    )
    if worker:
        put(admission.parent / "terminal.json", {"status": worker})
    with pytest.raises(ValueError):
        study.terminal_proof(tmp_path, tmp_path)


def test_interrupted_predecessor_retains_missing_worker_terminal(tmp_path, monkeypatch):
    admission = tmp_path / "attempts/generated/admission.json"
    put(admission, {"stage": "control"})
    monkeypatch.setattr(
        study.existing,
        "prior_attempt_proof",
        lambda *args: [
            {
                "admission": study.audit.seal(tmp_path, admission),
                "store_status": "interrupted",
            }
        ],
    )
    proof = study.terminal_proof(tmp_path, tmp_path)
    assert (
        proof[0]["worker_terminal"] is None
        and proof[0]["store_status"] == "interrupted"
    )
    with pytest.raises(ValueError, match="All remaining stages"):
        study.terminal_proof(tmp_path, tmp_path, completed=True)


def test_public_protocol_matches_exact_implementation():
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "data/manifests/shuttle_capacity_continuation_protocol_v1.json"
    )
    study.validate_protocol(study.audit.read_json(path.read_bytes()))
