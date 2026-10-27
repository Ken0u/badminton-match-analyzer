"""Disposable continuation controls; never read scientific labels or run rows."""

import copy
import json
import os
import sqlite3
import time
from types import SimpleNamespace

import psutil
import pytest
from badminton import shuttle_selection_continuation as study


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    study.publish(path, value)
    return study.audit.file_hash(path)


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    root = tmp_path
    output = root / ".cache/selectorremaining-disposable"
    source = root / "disposable.py"
    source.write_bytes(b"# generated consumer, never executed\n")
    input_path = root / "unparsed.bin"
    input_path.write_bytes(b"not JSON; no labels, weights or scientific rows")
    protocol = copy.deepcopy(study.protocol_value())
    protocol["input_artifacts"] = {"disposable": study.audit.seal(root, input_path)}
    monkeypatch.setattr(study, "protocol_value", lambda: protocol)
    monkeypatch.setattr(
        study,
        "consumers",
        lambda root: {"badminton/disposable.py": study.audit.seal(root, source)},
    )
    monkeypatch.setattr(study, "verify_prior", lambda *args: {"disposable": True})
    monkeypatch.setattr(study, "runtime_snapshot", lambda: {"disposable": True})
    clock = [protocol["deadline"] - 1000]
    monkeypatch.setattr(
        study,
        "time",
        SimpleNamespace(
            time=lambda: clock[0],
            perf_counter=time.perf_counter,
            monotonic=time.monotonic,
        ),
    )

    def ignored(root, path):
        path.mkdir(parents=True, exist_ok=False)
        return path

    monkeypatch.setattr(study.audit, "ignored_output", ignored)
    public = root / "protocol.json"
    checksum = put(public, protocol)
    granted = clock[0] - 2
    result = study.freeze(root, public, checksum, output, granted, protocol["deadline"])
    return SimpleNamespace(
        root=root,
        output=output,
        expected=result["experiment_sha256"],
        source=source,
        input=input_path,
        protocol=protocol,
        clock=clock,
        granted=granted,
    )


def test_protocol_fixes_original_clock_thresholds_and_full_familiar_denominator():
    protocol = study.protocol_value()
    study.validate_protocol(copy.deepcopy(protocol))
    assert protocol["original_granted_at"] == 1793063655
    assert protocol["deadline"] == 1793106855
    assert protocol["fixed_thresholds"] == {
        "control": 0.5,
        "decoder": 0.5,
        "convolution": 0.6,
    }
    assert protocol["familiar"]["cases"] == 60
    assert protocol["familiar"]["truth_states"] == {
        "visible": 25,
        "not_visible": 7,
        "unknown": 28,
    }
    assert not any(protocol["eligibility"].values())


@pytest.mark.parametrize("change", ["deadline", "threshold", "unknown", "eligibility"])
def test_changed_public_protocol_is_not_a_new_remaining_scope(change):
    protocol = copy.deepcopy(study.protocol_value())
    if change == "deadline":
        protocol["deadline"] += 1
    elif change == "threshold":
        protocol["fixed_thresholds"]["decoder"] = 0.6
    elif change == "unknown":
        protocol["familiar"]["truth_states"]["unknown"] -= 1
    else:
        protocol["eligibility"]["training_allowed"] = True
    with pytest.raises(ValueError):
        study.validate_protocol(protocol)


def test_freeze_hashes_unparsed_inputs_and_retains_both_grant_times(frozen):
    receipt, protocol = study.load(frozen.root, frozen.output, frozen.expected)
    assert receipt["original_granted_at"] == protocol["original_granted_at"]
    assert receipt["continuation_granted_at"] == frozen.granted
    assert receipt["deadline"] == protocol["deadline"]
    assert receipt["deadline"] != frozen.granted + 7200
    assert receipt["inputs"]["disposable"]["bytes"] == frozen.input.stat().st_size
    assert not (frozen.output / "familiar-opened.json").exists()
    assert not (frozen.output / "familiar.json").exists()


@pytest.mark.parametrize(
    "change", ["source", "copy", "protocol", "experiment", "input"]
)
def test_changed_frozen_bytes_refuse_before_familiar_reads(frozen, monkeypatch, change):
    target = {
        "source": frozen.source,
        "copy": frozen.output / "consumer/badminton/disposable.py",
        "protocol": frozen.output / "protocol.json",
        "experiment": frozen.output / "experiment.json",
        "input": frozen.input,
    }[change]
    target.write_bytes(target.read_bytes() + b" ")
    monkeypatch.setattr(
        study.predecessor,
        "cached_views",
        lambda *args: pytest.fail("no familiar reads after tampering"),
    )
    with pytest.raises(ValueError):
        study.load(frozen.root, frozen.output, frozen.expected)


@pytest.mark.parametrize("change", ["runtime", "prior"])
def test_new_environment_or_predecessor_cannot_reuse_a_freeze(
    frozen, monkeypatch, change
):
    if change == "runtime":
        monkeypatch.setattr(study, "runtime_snapshot", lambda: {"changed": True})
    else:
        monkeypatch.setattr(study, "verify_prior", lambda *args: {"changed": True})
    with pytest.raises(ValueError):
        study.load(frozen.root, frozen.output, frozen.expected)


@pytest.mark.parametrize(
    "change",
    ["expired", "extended", "original_grant", "future_grant", "new_boolean", "nan"],
)
def test_old_deadline_cannot_be_renewed_by_new_grant_or_resealed_receipt(
    frozen, change
):
    value = study.audit.read_json((frozen.output / "experiment.json").read_bytes())
    if change == "expired":
        frozen.clock[0] = frozen.protocol["deadline"]
    elif change == "extended":
        value["deadline"] += 3600
    elif change == "original_grant":
        value["original_granted_at"] += 1000
    elif change == "future_grant":
        value["continuation_granted_at"] = frozen.clock[0] + 1
    elif change == "new_boolean":
        value["continuation_granted_at"] = True
    else:
        value["continuation_granted_at"] = "NaN"
    (frozen.output / "experiment.json").write_bytes(study.audit.encoded(value))
    with pytest.raises(ValueError):
        study.load(
            frozen.root,
            frozen.output,
            study.audit.file_hash(frozen.output / "experiment.json"),
        )


def test_input_manifest_cannot_escape_the_original_root(tmp_path):
    protocol = copy.deepcopy(study.protocol_value())
    protocol["input_artifacts"] = {
        "escape": {"path": "../outside.json", "sha256": "a" * 64}
    }
    with pytest.raises(ValueError):
        study.verify_inputs(tmp_path, protocol)


def sized_file(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_budget_counts_original_new_and_preserved_worktrees_without_double_charge(
    tmp_path,
):
    sized_file(tmp_path / ".cache/selector330-old/a.bin", 3)
    sized_file(tmp_path / ".cache/selector332-failure/b.bin", 5)
    sized_file(tmp_path / ".cache/selector-remaining-planning/c.bin", 7)
    sized_file(tmp_path / ".cache/SELECTOR330_CURRENT.md", 11)
    sized_file(tmp_path / ".cache/selector-plan-old/d.bin", 13)
    sized_file(tmp_path / ".cache/selector-planning-v1/overlap.bin", 31)
    sized_file(tmp_path / ".cache/selector-preflight-old/e.bin", 17)
    sized_file(tmp_path / ".cache/selectorremaining-experiment-v1/consumer/i.bin", 37)
    sized_file(tmp_path / ".cache/worktrees/selector330-e1/f.bin", 19)
    sized_file(tmp_path / ".cache/worktrees/selectorremaining-e1/g.bin", 23)
    sized_file(tmp_path / ".cache/worktrees/selector332-test/h.bin", 29)
    sized_file(tmp_path / ".cache/unrelated/borrowed.bin", 100)
    result = study.budget(tmp_path)
    assert result["bytes"] == 195
    assert result["files"] == 11
    assert result["limit_bytes"] == 4294967296


@pytest.mark.parametrize("over", [0, 1])
def test_budget_refuses_at_limit_without_deleting_preserved_outputs(
    tmp_path, monkeypatch, over
):
    path = tmp_path / ".cache/selector332-previous/failure.bin"
    sized_file(path, 2)
    protocol = copy.deepcopy(study.protocol_value())
    protocol["limits"]["cumulative_retained_bytes"] = 2 - over
    monkeypatch.setattr(study, "protocol_value", lambda: protocol)
    with pytest.raises(ValueError):
        study.budget(tmp_path)
    assert path.read_bytes() == b"xx"


def public_seal(frozen, **changes):
    value = {
        "comment": "https://github.com/Ken0u/badminton-match-analyzer/issues/332#issuecomment-1",
        "experiment_sha256": frozen.expected,
        "protocol_sha256": study.audit.file_hash(frozen.output / "protocol.json"),
    }
    value.update(changes)
    return put(frozen.output / "public-seal.json", value)


@pytest.mark.parametrize("change", ["hash", "experiment", "protocol", "comment"])
def test_missing_public_binding_refuses_before_job_or_familiar_reads(
    frozen, monkeypatch, change
):
    fields = {
        "experiment": {"experiment_sha256": "a" * 64},
        "protocol": {"protocol_sha256": "b" * 64},
        "comment": {
            "comment": "https://github.com/Ken0u/badminton-match-analyzer/issues/330#issuecomment-1"
        },
    }
    checksum = public_seal(frozen, **fields.get(change, {}))
    if change == "hash":
        checksum = "c" * 64
    from badminton import jobs

    monkeypatch.setattr(
        jobs, "run_local_job", lambda *args: pytest.fail("no unsealed job")
    )
    with pytest.raises(ValueError):
        study.evaluate(frozen.root, frozen.output, frozen.expected, checksum)


@pytest.mark.parametrize(
    "marker",
    [
        "evaluate-attempt.json",
        "familiar-opened.json",
        "familiar.json",
        "familiar-selected-control.json",
        "attempts",
    ],
)
def test_any_prior_attempt_or_result_prevents_silent_scientific_retry(
    frozen, monkeypatch, marker
):
    checksum = public_seal(frozen)
    put(frozen.output / marker, {"preserved": True})
    from badminton import jobs

    monkeypatch.setattr(
        jobs, "run_local_job", lambda *args: pytest.fail("no repeated job")
    )
    with pytest.raises(ValueError):
        study.evaluate(frozen.root, frozen.output, frozen.expected, checksum)
    assert study.audit.read_json((frozen.output / marker).read_bytes()) == {
        "preserved": True
    }


def admitted_fixture(frozen, monkeypatch):
    from badminton import config, jobs, storage

    root = frozen.root
    monkeypatch.setattr(config, "ROOT", root)
    monkeypatch.setattr(config, "DATA", root / "data/processed")
    monkeypatch.setattr(config, "WEIGHTS", root / "models/weights")
    shared = config.DATA
    shared.mkdir(parents=True)
    (shared / "catalog.sqlite3").write_bytes(b"disposable Store marker")
    store, events = object(), []

    def make_store(path):
        assert path == shared
        events.append("store")
        return store

    def run(store_value, kind, video_id, function):
        assert store_value is store
        assert kind == "feature-preparation" and video_id is None
        events.append("admitted")
        return function("disposable-job", lambda value: events.append(value))

    fits = {"variants": {}}
    original_public = {"fits_sha256": "d" * 64}
    monkeypatch.setattr(storage, "Store", make_store)
    monkeypatch.setattr(jobs, "run_local_job", run)
    monkeypatch.setattr(
        study.predecessor, "sealed_fits", lambda *args: (fits, original_public)
    )
    return events


def test_cached_diagnostic_is_admitted_to_original_shared_store_and_new_output(
    frozen, monkeypatch
):
    events = admitted_fixture(frozen, monkeypatch)

    def diagnostic(root, output, expected, fits, public, protocol, progress, **kwargs):
        assert root == frozen.root and output == frozen.output
        assert expected == frozen.expected
        assert kwargs["fit_output"] == root / protocol["predecessor_root"]
        assert (
            kwargs["fit_experiment_sha256"] == protocol["predecessor_experiment_sha256"]
        )
        assert (
            kwargs["public_seal_sha256"]
            == protocol["predecessor_fit_public_seal_sha256"]
        )
        assert "admitted" in events
        admitted = list((output / "attempts").glob("*/admission.json"))
        assert len(admitted) == 1
        assert (
            study.audit.read_json(admitted[0].read_bytes())["job_id"]
            == "disposable-job"
        )
        progress(0.5)
        put(output / "familiar-opened.json", {"experiment_sha256": expected})
        checksum = put(output / "familiar.json", {"cases": 60, "unknown": 28})
        return {"familiar_sha256": checksum, "cases": 60, "unknown": 28}

    monkeypatch.setattr(
        study.predecessor, "familiar_diagnostic", diagnostic, raising=False
    )
    result = study.evaluate(
        frozen.root, frozen.output, frozen.expected, public_seal(frozen)
    )
    assert result["result"]["cases"] == 60 and result["result"]["unknown"] == 28
    terminals = list((frozen.output / "attempts").glob("*/terminal.json"))
    assert len(terminals) == 1
    assert study.audit.read_json(terminals[0].read_bytes())["status"] == "completed"
    assert 0.5 in events


@pytest.mark.parametrize("where", ["admission", "diagnostic"])
def test_failed_admission_or_diagnostic_remains_one_attempt(frozen, monkeypatch, where):
    events = admitted_fixture(frozen, monkeypatch)
    from badminton import jobs

    def failed(*args, **kwargs):
        raise RuntimeError("disposable preserved failure")

    if where == "admission":
        monkeypatch.setattr(jobs, "run_local_job", failed)
    else:
        monkeypatch.setattr(
            study.predecessor, "familiar_diagnostic", failed, raising=False
        )
    checksum = public_seal(frozen)
    with pytest.raises(RuntimeError, match="disposable preserved failure"):
        study.evaluate(frozen.root, frozen.output, frozen.expected, checksum)
    assert (frozen.output / "evaluate-attempt.json").exists()
    terminals = list((frozen.output / "attempts").glob("*/terminal.json"))
    assert len(terminals) == 1
    assert study.audit.read_json(terminals[0].read_bytes())["status"] == "failed"
    before = list(events)
    with pytest.raises(ValueError):
        study.evaluate(frozen.root, frozen.output, frozen.expected, checksum)
    assert events == before


def test_progress_enforces_original_deadline_during_cached_scoring(frozen, monkeypatch):
    admitted_fixture(frozen, monkeypatch)

    def diagnostic(root, output, expected, fits, public, protocol, progress, **kwargs):
        frozen.clock[0] = protocol["deadline"]
        progress(0.5)
        pytest.fail("expired diagnostic must not continue")

    monkeypatch.setattr(
        study.predecessor, "familiar_diagnostic", diagnostic, raising=False
    )
    with pytest.raises(ValueError):
        study.evaluate(frozen.root, frozen.output, frozen.expected, public_seal(frozen))
    assert not (frozen.output / "familiar.json").exists()


@pytest.mark.parametrize("location", ["root", "data", "weights", "database"])
def test_wrong_shared_store_configuration_refuses_before_admission(
    frozen, monkeypatch, location
):
    events = admitted_fixture(frozen, monkeypatch)
    from badminton import config

    if location == "database":
        (config.DATA / "catalog.sqlite3").unlink()
    else:
        name = {"root": "ROOT", "data": "DATA", "weights": "WEIGHTS"}[location]
        monkeypatch.setattr(config, name, frozen.root / "unrelated")
    with pytest.raises(ValueError):
        study.evaluate(frozen.root, frozen.output, frozen.expected, public_seal(frozen))
    assert events == []
    assert not (frozen.output / "evaluate-attempt.json").exists()


@pytest.mark.parametrize("change", ["cases", "unknown", "result_hash"])
def test_incomplete_or_changed_cached_result_is_preserved_as_failed(
    frozen, monkeypatch, change
):
    admitted_fixture(frozen, monkeypatch)

    def diagnostic(root, output, expected, fits, public, protocol, progress, **kwargs):
        checksum = put(output / "familiar.json", {"disposable": True})
        result = {"familiar_sha256": checksum, "cases": 60, "unknown": 28}
        key = {
            "cases": "cases",
            "unknown": "unknown",
            "result_hash": "familiar_sha256",
        }[change]
        result[key] = "a" * 64 if change == "result_hash" else result[key] - 1
        return result

    monkeypatch.setattr(
        study.predecessor, "familiar_diagnostic", diagnostic, raising=False
    )
    with pytest.raises(ValueError):
        study.evaluate(frozen.root, frozen.output, frozen.expected, public_seal(frozen))
    terminal = next((frozen.output / "attempts").glob("*/terminal.json"))
    assert study.audit.read_json(terminal.read_bytes())["status"] == "failed"
    assert (frozen.output / "familiar.json").exists()


def prior_fixture(root, monkeypatch, change=None):
    """Construct original terminal provenance from generated bytes only."""
    protocol = copy.deepcopy(study.protocol_value())
    protocol["predecessor_root"] = ".cache/selector330-disposable"
    old = root / protocol["predecessor_root"]
    old.mkdir(parents=True)
    monkeypatch.setattr(study, "runtime_snapshot", lambda: {"disposable": True})
    source = root / "original-source.py"
    source.write_bytes(b"# disposable original consumer\n")
    copied = old / "consumer/badminton/disposable.py"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(source.read_bytes())
    opaque = root / "unparsed-source.bin"
    opaque.write_bytes(b"opaque source metadata; not scientific labels")
    inherited = root / "inherited.bin"
    inherited.write_bytes(b"inherited opaque bytes")
    original_inputs = {"opaque": study.audit.seal(root, opaque)}
    old_protocol = {
        "familiar": protocol["familiar"],
        "input_artifacts": original_inputs,
    }
    if change == "denominator":
        old_protocol = copy.deepcopy(old_protocol)
        old_protocol["familiar"]["cases"] -= 1
    old_protocol_sha = put(old / "protocol.json", old_protocol)
    original = {
        "granted_at": protocol["original_granted_at"],
        "deadline": protocol["deadline"],
        "protocol_sha256": old_protocol_sha,
        "runtime": {"disposable": True},
        "inputs": {
            "opaque": {**original_inputs["opaque"], "bytes": opaque.stat().st_size}
        },
        "consumer_files": {"badminton/disposable.py": study.audit.seal(root, source)},
    }
    if change == "old_deadline":
        original["deadline"] += 3600
    elif change == "old_grant":
        original["granted_at"] += 1
    elif change == "runtime":
        original["runtime"] = {"changed": True}
    expected = put(old / "experiment.json", original)
    protocol["predecessor_experiment_sha256"] = expected
    trainval = old / "trainval.json"
    trainval.write_bytes(b"not JSON: train/validation completion is hash-only")
    fits = {
        "experiment_sha256": expected,
        "test_generated": False,
        "trainval_sha256": study.audit.file_hash(trainval),
        "variants": {
            name: {"validation": {"available": True, "threshold": threshold}}
            for name, threshold in protocol["fixed_thresholds"].items()
        },
    }
    if change == "threshold":
        fits["variants"]["decoder"]["validation"]["threshold"] = 0.7
    elif change == "fitted_after_test":
        fits["test_generated"] = True
    elif change == "missing_method":
        fits["variants"].pop("control")
    fits_sha = put(old / "fits.json", fits)
    protocol["predecessor_fits_sha256"] = fits_sha
    test = old / "test.json"
    test.write_bytes(b"not JSON: consumed test predictions must never be parsed")
    protocol["predecessor_test_sha256"] = study.audit.file_hash(test)
    public_prefix = (
        "https://github.com/Ken0u/badminton-match-analyzer/issues/330#issuecomment-"
    )
    put(
        old / "experiment-public-seal.json",
        {"experiment_sha256": expected, "comment": public_prefix + "1"},
    )
    if change == "public_binding":
        put_value = {"experiment_sha256": "a" * 64, "comment": public_prefix + "1"}
        (old / "experiment-public-seal.json").write_bytes(
            study.audit.encoded(put_value)
        )
    fit_comment = public_prefix + "2"
    if change == "fit_public_binding":
        fit_comment = "https://example.invalid/unrelated"
    fit_public_sha = put(
        old / "fit-public-seal.json",
        {
            "experiment_sha256": expected,
            "fits_sha256": fits_sha,
            "comment": fit_comment,
        },
    )
    protocol["predecessor_fit_public_seal_sha256"] = fit_public_sha
    identity = {
        "pid": os.getpid(),
        "creation_time": psutil.Process().create_time() - 100,
        "cwd": str(root),
        "command": ["generated-original-worker"],
    }
    statuses = {
        "trainval": "completed",
        "fit": "completed",
        "test": "completed",
        "familiar": "failed",
    }
    stages, jobs, folders = [], [], {}
    result_hashes = {
        "trainval": ("trainval_sha256", study.audit.file_hash(trainval)),
        "fit": ("fits_sha256", fits_sha),
        "test": ("test_sha256", protocol["predecessor_test_sha256"]),
    }
    for stage, status in statuses.items():
        folder = old / "attempts" / stage
        folders[stage] = folder
        process = dict(identity)
        if change == "live" and stage == "test":
            process["creation_time"] = psutil.Process().create_time()
        if change == "empty_cwd" and stage == "test":
            process["cwd"] = ""
        if change == "relative_cwd" and stage == "test":
            process["cwd"] = "."
        job_id = "generated-" + stage
        admitted = {
            "experiment_sha256": expected,
            "stage": stage,
            "job_id": job_id,
            "process": process,
        }
        put(folder / "admission.json", admitted)
        if stage == "familiar":
            terminal = {
                "status": "failed",
                "error_type": "FileNotFoundError",
                "error": "missing generated provenance metadata",
            }
        else:
            key, value = result_hashes[stage]
            terminal = {"status": status, "result": {key: value}}
        if change == "terminal_result" and stage == "fit":
            terminal["result"]["fits_sha256"] = "a" * 64
        if change == "test_result" and stage == "test":
            terminal["result"]["test_sha256"] = "a" * 64
        if change == "failure_type" and stage == "familiar":
            terminal["error_type"] = "RuntimeError"
        terminal_sha = put(folder / "terminal.json", terminal)
        record = {"stage": stage, "job_id": job_id, "store_status": status}
        if stage == "familiar":
            record["terminal_sha256"] = terminal_sha
        stages.append(record)
        job = {
            "id": job_id,
            "status": "running" if change == "store" and stage == "test" else status,
            "owner_pid": process["pid"],
            "owner_started": process["creation_time"],
        }
        if change == "store_creation" and stage == "test":
            job["owner_started"] += 1
        if change == "store_pid" and stage == "test":
            job["owner_pid"] += 1
        jobs.append(job)
    borrowed = {
        path.relative_to(root).as_posix(): {
            "sha256": study.audit.file_hash(path),
            "bytes": path.stat().st_size,
        }
        for path in (opaque, inherited)
    }
    proof = {
        "experiment_sha256": expected,
        "familiar_status": "failed_before_scoring",
        "scientific_protocol_complete": False,
        "scientific_rerun": False,
        "borrowed_file_inventory": borrowed,
        "stages": stages,
    }
    proof_path = root / "preservation.json"
    put(proof_path, proof)
    completion_path = root / "delivery.json"
    put(
        completion_path,
        {
            "task": 330,
            "source": protocol["predecessor_delivered_source"],
            "familiar_status": "failed_before_scoring",
            "scientific_success": False,
            "promoted": False,
        },
    )
    inputs = dict(original_inputs)
    inputs.update(
        {
            name: study.audit.seal(root, path)
            for name, path in {
                "selection-experiment": old / "experiment.json",
                "selection-fits": old / "fits.json",
                "selection-test-completion": test,
                "selection-trainval": trainval,
                "selection-experiment-public-seal": old / "experiment-public-seal.json",
                "selection-fit-public-seal": old / "fit-public-seal.json",
                "selection-preservation-proof": proof_path,
                "selection-delivery-completion": completion_path,
            }.items()
        }
    )
    protocol["input_artifacts"] = inputs
    database = root / "data/processed/catalog.sqlite3"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE jobs (document TEXT)")
        db.executemany(
            "INSERT INTO jobs VALUES (?)", [(json.dumps(job),) for job in jobs]
        )
    if change == "original_source":
        source.write_bytes(source.read_bytes() + b"changed")
    elif change == "consumer_copy":
        copied.write_bytes(copied.read_bytes() + b"changed")
    elif change == "borrowed":
        inherited.write_bytes(b"changed")
    elif change == "missing_terminal":
        (folders["fit"] / "terminal.json").unlink()
    elif change == "duplicate_stage":
        extra = old / "attempts/extra-test"
        for name in ("admission.json", "terminal.json"):
            value = study.audit.read_json((folders["test"] / name).read_bytes())
            put(extra / name, value)
    elif change in ("opened", "result", "selected"):
        name = {
            "opened": "familiar-opened.json",
            "result": "familiar.json",
            "selected": "familiar-selected-control.json",
        }[change]
        put(old / name, {"preserved": True})
    return protocol, old


def test_actual_prior_verification_hashes_consumed_test_without_parsing_rows(
    tmp_path, monkeypatch
):
    protocol, old = prior_fixture(tmp_path, monkeypatch)
    result = study.verify_prior(tmp_path, protocol)
    assert result["test_sha256"] == study.audit.file_hash(old / "test.json")
    assert {job["stage"]: job["status"] for job in result["jobs"]} == {
        "trainval": "completed",
        "fit": "completed",
        "test": "completed",
        "familiar": "failed",
    }
    assert (old / "test.json").read_bytes().startswith(b"not JSON")


@pytest.mark.parametrize(
    "change",
    [
        "old_deadline",
        "old_grant",
        "runtime",
        "denominator",
        "original_source",
        "consumer_copy",
        "borrowed",
        "threshold",
        "fitted_after_test",
        "missing_method",
        "public_binding",
        "fit_public_binding",
        "store",
        "store_creation",
        "store_pid",
        "live",
        "empty_cwd",
        "relative_cwd",
        "terminal_result",
        "test_result",
        "failure_type",
        "missing_terminal",
        "duplicate_stage",
        "opened",
        "result",
        "selected",
    ],
)
def test_actual_prior_refuses_changed_or_incomplete_evidence(
    tmp_path, monkeypatch, change
):
    protocol, _ = prior_fixture(tmp_path, monkeypatch, change)
    if change in ("empty_cwd", "relative_cwd"):
        # A missing cwd must not acquire authority by resolving to current root.
        monkeypatch.chdir(tmp_path)
    with pytest.raises((ValueError, FileNotFoundError)):
        study.verify_prior(tmp_path, protocol)


def test_unobservable_original_lifetime_is_not_assumed_exited(tmp_path, monkeypatch):
    protocol, _ = prior_fixture(tmp_path, monkeypatch)

    def denied(pid):
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr(study.psutil, "Process", denied)
    with pytest.raises(ValueError, match="absence"):
        study.verify_prior(tmp_path, protocol)


@pytest.mark.parametrize("change", ["input", "prior", "runtime"])
def test_freeze_does_not_publish_when_evidence_changes_during_consumer_copy(
    frozen, monkeypatch, change
):
    original = study.audit.sealed_bytes

    def changed(root, entry):
        raw = original(root, entry)
        if entry["path"] == frozen.source.relative_to(root).as_posix():
            if change == "input":
                frozen.input.write_bytes(b"changed during consumer copying")
            elif change == "prior":
                monkeypatch.setattr(
                    study, "verify_prior", lambda *args: {"changed": True}
                )
            else:
                monkeypatch.setattr(
                    study, "runtime_snapshot", lambda: {"changed": True}
                )
        return raw

    monkeypatch.setattr(study.audit, "sealed_bytes", changed)
    output = frozen.root / ".cache/selectorremaining-raced"
    public = frozen.root / "protocol.json"
    with pytest.raises(ValueError):
        study.freeze(
            frozen.root,
            public,
            study.audit.file_hash(public),
            output,
            frozen.granted,
            frozen.protocol["deadline"],
        )
    assert not (output / "experiment.json").exists()


@pytest.mark.parametrize(
    "relative",
    [
        ".cache/selector330-original",
        ".cache/uncounted-output",
        ".cache/nested/selector332-x",
    ],
)
def test_freeze_refuses_original_or_uncounted_output_namespaces(frozen, relative):
    public = frozen.root / "protocol.json"
    output = frozen.root / relative
    with pytest.raises(ValueError):
        study.freeze(
            frozen.root,
            public,
            study.audit.file_hash(public),
            output,
            frozen.granted,
            frozen.protocol["deadline"],
        )
    assert not output.exists()
