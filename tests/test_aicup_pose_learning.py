"""Generated controls for the fixed private study; no scientific inputs opened."""

import copy
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from badminton import aicup_actor_correspondence as actor
from badminton import aicup_pose_learning as learning
from badminton import aicup_pose_pilot as producer
from test_aicup_actor_correspondence import original_generated as original_generated
from test_aicup_pose_pilot import integrated_inputs as integrated_inputs


def case():
    frames, clocks = [], []
    for i in range(15):
        people = []
        for identity, x in ((1, 30), (2, 80)):
            people.append(
                {
                    "track_id": identity,
                    "box": [x - 10, 20, x + 10, 70],
                    "keypoints": [[x + i / 10, 30, 0.8] for _ in range(17)],
                }
            )
        frames.append(
            {
                "frame": i,
                "players": people,
                "calibration_valid": True,
                "camera_segment_start_frame": 0,
            }
        )
        clocks.append(
            {
                "frame": i,
                "pts": 1000 + i * 2,
                "time_base": [1, 100],
                "relative_time": [i, 50],
            }
        )
    return (
        {
            "id": "generated:1",
            "source_contact_frame": 7,
            "kind": "shot",
            "family": "clear",
            "side": "forehand",
        },
        {"reference_id": "generated:1", "weak_pair": {"hitter": 1, "defender": 2}},
        {"frames": frames},
        {"width": 120, "height": 90},
        {"rows": clocks},
    )


def feature_rows():
    reference, diagnostic, result, video, ledger = case()
    rows = []
    for fold in ("train", "validation"):
        for i in range(16):
            f = learning.reference_features(
                reference, diagnostic, result, video, ledger
            )
            f.update(
                id=f"{fold}:{i}",
                clip_key=fold,
                fold=fold,
                context=fold,
                family=i % 8,
                side=i % 2,
                training_ready=False,
                scene_truth="unknown",
                actor_truth="unknown",
            )
            rows.append(f)
    return rows


def test_public_protocol_matches_and_import_never_opens_model_runtime():
    root = Path(learning.__file__).resolve().parents[2]
    assert learning.PROTOCOL == producer.read_json(
        root / "data/manifests/aicup_pose_learning_protocol_v1.json"
    )
    env = dict(os.environ, PYTHONPATH=str(root / "backend"))
    subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "from badminton import aicup_pose_learning; import sys; assert 'torch' not in sys.modules; assert 'ultralytics' not in sys.modules",
        ],
        check=True,
        env=env,
        capture_output=True,
    )


def test_exact_center_temporal_and_pts_velocity_arithmetic():
    value = learning.reference_features(*case())
    temporal, static = np.asarray(value["temporal"]), np.asarray(value["static"])
    assert temporal.shape == static.shape == (108,)
    assert temporal[0] == pytest.approx(0.65 / 50)
    assert temporal[1] == pytest.approx(-40 / 50)
    assert temporal[2] == pytest.approx(0.8)
    assert temporal[36] == pytest.approx(0.65 / 50)
    assert temporal[72] == pytest.approx(0.1)
    assert temporal[74] == pytest.approx(0.8)
    np.testing.assert_array_equal(static[:36], static[36:72])
    assert not static[72:].any()
    assert value["observed_joint_slots"] == 120
    assert value["adjacent_joint_pairs"] == 108
    assert [c["frame"] for c in value["native_clocks"]] == list(range(2, 12))


def test_vfr_velocity_uses_exact_rational_clock_and_never_bridges_missing_slot():
    args = case()
    args[-1]["rows"][7]["relative_time"] = [13, 100]
    value = learning.reference_features(*args)
    # Nine differences: seven at .02 sec, one at .01, one at .03.
    assert value["temporal"][72] == pytest.approx((7 * 0.1 + 0.2 + 1 / 15) / 9)
    args[2]["frames"][7]["players"] = []
    value = learning.reference_features(*args)
    assert value["adjacent_joint_pairs"] == 84
    assert value["temporal"][74] == pytest.approx(0.8 * 7 / 9)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "low_confidence",
        "nan_joint",
        "outside_joint",
        "nan_box",
        "zero_box",
        "outside_box",
        "camera",
        "calibration",
        "missing_points",
    ],
)
def test_missing_or_invalid_observations_stay_masked(mutation):
    args = case()
    frame = args[2]["frames"][7]
    person = frame["players"][0]
    if mutation == "missing":
        frame["players"] = []
    elif mutation == "duplicate":
        frame["players"].append(copy.deepcopy(person))
    elif mutation == "low_confidence":
        person["keypoints"][5][2] = 0.24
    elif mutation == "nan_joint":
        person["keypoints"][5][0] = float("nan")
    elif mutation == "outside_joint":
        person["keypoints"][5][0] = 120
    elif mutation == "nan_box":
        person["box"][0] = float("nan")
    elif mutation == "zero_box":
        person["box"][1] = person["box"][3]
    elif mutation == "outside_box":
        person["box"][0] = -1
    elif mutation == "camera":
        # A future frame enters another namespace, leaving the contact camera.
        frame = args[2]["frames"][8]
        frame["camera_segment_start_frame"] = 8
    elif mutation == "calibration":
        frame["calibration_valid"] = False
    else:
        person["keypoints"] = []
    value = learning.reference_features(*args)
    slot = 6 if mutation == "camera" else 5
    assert not value["observed_mask"][slot][0][0]
    assert value["available"]
    assert np.isfinite(value["temporal"]).all()


def test_pooling_preserves_both_endpoints_and_nominal_confidence():
    args = case()
    args[2]["frames"][6]["players"][0]["keypoints"][5][2] = 0
    value = learning.reference_features(*args)
    assert value["temporal"][0] == pytest.approx(0.7 / 50)
    assert value["temporal"][2] == pytest.approx(0.4)
    assert value["temporal"][38] == pytest.approx(0.72)


@pytest.mark.parametrize("frame", [0, 1, 14, None])
def test_native_edges_and_unresolved_rows_are_preserved(frame):
    args = case()
    args[0]["source_contact_frame"] = frame
    if frame in (0, None):
        args[1]["weak_pair"] = None
    value = learning.reference_features(*args)
    assert len(value["native_clocks"]) == 10
    assert not value["native_clocks"][0] if frame in (0, 1, None) else True
    if frame in (0, None):
        assert not value["available"] and not any(value["temporal"])
    else:
        assert value["observed_joint_slots"] < 120


@pytest.mark.parametrize("dt", [0, -1, 11])
def test_invalid_or_long_source_step_never_supplies_velocity(dt):
    args = case()
    args[-1]["rows"][7]["relative_time"] = [12 + dt, 100]
    value = learning.reference_features(*args)
    assert not value["adjacent_mask"][4][0][0]


def test_features_are_blind_to_targets_and_published_coordinates():
    args = case()
    before = learning.reference_features(*args)
    args[0].update(
        family="smash",
        side="backhand",
        kind="serve",
        raw={"Winner": "B", "LandingX": 10, "Hitter": "A"},
    )
    assert learning.reference_features(*args) == before


def test_train_statistics_ignore_all_validation_and_unavailable_inputs():
    rows = feature_rows()
    rows[0]["available"] = False
    data = learning.arrays(rows, "temporal")
    expected = learning.training_statistics(data)
    data["features"][~data["train"]] = 100000
    data["features"][0] = -100000
    data["family"][~data["train"]] = 7
    data["side"][~data["train"]] = 1
    assert learning.training_statistics(data) == expected
    assert expected["normalization_rows"] == 15
    assert min(expected["std"]) >= 0.05
    for weights, support in zip(expected["weights"], expected["support"], strict=True):
        assert np.mean(np.asarray(weights)[support]) == pytest.approx(1)


def test_unknowns_are_separate_and_unavailable_rows_count_as_misses():
    rows = feature_rows()
    rows[0].update(available=False, family=-1)
    rows[1]["available"] = False
    data = learning.arrays(rows, "static")
    predictions = [data[k].copy() for k in ("family", "side")]
    for p in predictions:
        p[~data["available"]] = -1
    metrics = learning.evaluate(data, predictions, data["train"])
    assert metrics["source_rows"] == 16 and metrics["unavailable_rows"] == 2
    assert metrics["unknown_joint_targets"] == 1
    assert metrics["strict_joint_all_source_rows"] == 14 / 16
    assert metrics["conditional_denominator"] == 14
    assert metrics["conditional_joint_given_weak_pair_and_known_targets"] == 1
    assert metrics["family"]["known_targets"] == 15
    assert metrics["family"]["unknown_targets"] == 1
    predictions[0][0] = 1
    changed = learning.evaluate(data, predictions, data["train"])
    assert changed["family"]["per_class"] == metrics["family"]["per_class"]
    assert changed["family"]["predictions_on_unknown_truth"] == 1


def test_missing_pose_does_not_drop_a_weakly_matched_training_row():
    rows = feature_rows()
    rows[0]["static"] = [0] * 108
    assert (
        learning.training_statistics(learning.arrays(rows, "static"))[
            "normalization_rows"
        ]
        == 16
    )


@pytest.mark.parametrize("mutation", ["test", "dimension", "nan", "arm"])
def test_invalid_or_heldout_feature_arrays_are_refused(mutation):
    rows, arm = feature_rows(), "static"
    if mutation == "test":
        rows[0]["fold"] = "test"
    elif mutation == "dimension":
        rows[0]["static"] = [0] * 107
    elif mutation == "nan":
        rows[0]["static"][0] = float("nan")
    else:
        arm = "different"
    with pytest.raises(ValueError):
        learning.arrays(rows, arm)


def test_selection_and_arm_ties_keep_earlier_epoch_and_static():
    rows = feature_rows()
    data = learning.arrays(rows, "static")
    predictions = [data[k].copy() for k in ("family", "side")]
    metrics = learning.evaluate(data, predictions, data["validation"])
    assert learning.selection_key(metrics, 5) > learning.selection_key(metrics, 10)
    result = {"selection": {"key": list(learning.selection_key(metrics, 5))}}
    report = learning.report_metrics(
        rows,
        dict.fromkeys(("static", "temporal"), result),
        dict.fromkeys(("static", "temporal"), predictions),
    )
    assert report["selected_development_arm"] == "static"
    assert report["arms"]["static"]["groups"]["all"]["source_rows"] == 32
    assert len(report["arms"]["static"]["groups"]["all"]["family_side"]) == 16


def test_cpu_rng_threads_dtype_and_determinism_restore_even_after_error():
    torch = pytest.importorskip("torch")
    python_rng, numpy_rng, torch_rng = (
        random.getstate(),
        np.random.get_state(),
        torch.get_rng_state(),
    )
    threads, deterministic, dtype = (
        torch.get_num_threads(),
        torch.are_deterministic_algorithms_enabled(),
        torch.get_default_dtype(),
    )
    with pytest.raises(RuntimeError), learning.cpu_state():
        assert torch.get_num_threads() == 2
        assert torch.are_deterministic_algorithms_enabled()
        random.random()
        np.random.rand()
        torch.rand(2)
        raise RuntimeError("generated")
    assert random.getstate() == python_rng
    assert np.array_equal(np.random.get_state()[1], numpy_rng[1])
    assert torch.equal(torch.get_rng_state(), torch_rng)
    assert (
        torch.get_num_threads(),
        torch.are_deterministic_algorithms_enabled(),
        torch.get_default_dtype(),
    ) == (threads, deterministic, dtype)


@pytest.fixture
def short_schedule(monkeypatch):
    pytest.importorskip("torch")
    protocol = copy.deepcopy(learning.PROTOCOL)
    protocol["training"].update(epochs=10, selection_every=5)
    monkeypatch.setattr(learning, "PROTOCOL", protocol)


def test_generated_two_fits_reproduce_all_checkpoints_without_refitting(
    tmp_path, monkeypatch, short_schedule
):
    rows = feature_rows()
    rows[0]["available"] = False
    results, predictions, progress = {}, {}, []
    for arm in ("static", "temporal"):
        data = learning.arrays(rows, arm)
        results[arm] = learning.fit(
            data, tmp_path / arm, lambda e, c: progress.append((e, c))
        )
        predictions[arm] = producer.read_json(tmp_path / arm / "predictions.json")
    monkeypatch.setattr(
        learning, "fit", lambda *_: pytest.fail("Verifier fitted model")
    )
    for arm in ("static", "temporal"):
        result, prediction = learning.verify_arm(
            learning.arrays(rows, arm), tmp_path / arm
        )
        assert result == results[arm]
        assert [p.tolist() for p in prediction] == predictions[arm]
    assert (
        results["static"]["parameter_count"]
        == results["temporal"]["parameter_count"]
        == 9386
    )
    assert len(progress) == 24


def test_deterministic_generated_fit_and_unsupported_classes(tmp_path, short_schedule):
    rows = feature_rows()
    for r in rows:
        if r["fold"] == "train" and r["family"] == 7:
            r["family"] = -1
    data = learning.arrays(rows, "static")
    a = learning.fit(data, tmp_path / "a", lambda *_: None)
    b = learning.fit(data, tmp_path / "b", lambda *_: None)
    assert a == b
    assert producer.read_json(tmp_path / "a/history.json") == producer.read_json(
        tmp_path / "b/history.json"
    )
    assert not producer.read_json(tmp_path / "a/statistics.json")["support"][0][7]
    assert 7 not in producer.read_json(tmp_path / "a/predictions.json")[0]


@pytest.fixture
def sealed_actor(original_generated, monkeypatch):
    workspace, prepared, native, _, _ = original_generated
    protocol_path = workspace / "actor-protocol.json"
    producer.publish(protocol_path, actor.PROTOCOL)
    plan_dir = workspace / ".cache/actor-freeze"
    plan = actor.freeze(
        workspace,
        prepared,
        native,
        protocol_path,
        time.time() - 1,
        time.time() + 120,
        plan_dir,
    )
    audit = workspace / ".cache/actor-audit"
    actor.audit(plan_dir / "prospective.json", plan["prospective_sha256"], audit)
    protocol = copy.deepcopy(learning.PROTOCOL)
    protocol.update(
        preparation_sha256=producer.digest(prepared / "freeze.json"),
        native_completion_sha256=producer.digest(native / "completion.json"),
        actor_prospective_sha256=producer.digest(plan_dir / "prospective.json"),
        actor_completion_sha256=producer.digest(audit / "completion.json"),
        actor_diagnostics_sha256=producer.digest(audit / "diagnostics.json"),
        expected={
            "references": 3,
            "train_rows": 3,
            "validation_rows": 0,
            "weak_pairs": 0,
            "unresolved": 3,
        },
    )
    monkeypatch.setattr(learning, "PROTOCOL", protocol)
    return workspace, prepared, native, plan_dir / "prospective.json", audit


def test_original_seals_and_canonical_cohort_validate_without_replacing_producer_inventory(
    sealed_actor, monkeypatch
):
    monkeypatch.setattr(
        producer, "code_seals", lambda: pytest.fail("Historical seal replaced")
    )
    observations, diagnostics = learning.load_inputs(*sealed_actor[1:])
    assert len(observations) == 1 and len(diagnostics) == 3


@pytest.mark.parametrize(
    "field",
    ["preparation", "native", "prospective", "diagnostics", "completion", "inventory"],
)
def test_original_input_mutations_are_refused(sealed_actor, field):
    _, prepared, native, plan, audit = sealed_actor
    path = {
        "preparation": prepared / "freeze.json",
        "native": native / "completion.json",
        "prospective": plan,
        "diagnostics": audit / "diagnostics.json",
        "completion": audit / "completion.json",
        "inventory": audit / "unexpected.json",
    }[field]
    path.write_bytes(b"{}")
    with pytest.raises(ValueError):
        learning.load_inputs(prepared, native, plan, audit)


def test_freeze_is_integrity_only_and_rejects_uncommitted_code(
    sealed_actor, monkeypatch
):
    workspace, prepared, native, plan, audit = sealed_actor
    protocol_path = workspace / "learning-protocol.json"
    producer.publish(protocol_path, learning.PROTOCOL)
    monkeypatch.setattr(learning, "runtime", lambda: {"generated": True})
    monkeypatch.setattr(learning, "tested_commit", lambda: "generated-tested-commit")
    monkeypatch.setattr(
        learning,
        "extract",
        lambda *_: pytest.fail("Feature extraction before freeze publication"),
    )
    monkeypatch.setattr(
        learning, "fit", lambda *_: pytest.fail("Fit before freeze publication")
    )
    result = learning.freeze(
        workspace,
        prepared,
        native,
        plan,
        audit,
        protocol_path,
        time.time() - 1,
        time.time() + 100,
        workspace / ".cache/freeze",
    )
    assert not result["features_extracted"] and result["real_fits"] == 0
    assert (
        producer.read_json(workspace / ".cache/freeze/prospective.json")[
            "tested_commit"
        ]
        == "generated-tested-commit"
    )


@pytest.fixture
def generated_run(tmp_path, monkeypatch, short_schedule):
    from badminton.storage import Store

    workspace = tmp_path / "workspace"
    data = workspace / "data/processed"
    Store(data)
    plan_dir = workspace / ".cache/prospective"
    plan_dir.mkdir(parents=True)
    directories = {
        k: workspace / ".cache" / k
        for k in ("prepared", "native", "audit", "actor-freeze")
    }
    for p in directories.values():
        p.mkdir()
    producer.publish(
        directories["native"] / "completion.json", {"shared_data": str(data)}
    )
    producer.publish(
        directories["actor-freeze"] / "prospective.json", {"workspace": str(workspace)}
    )
    now = time.time()
    plan = {
        "workspace": str(workspace),
        "prepared": str(directories["prepared"]),
        "native": str(directories["native"]),
        "audit": str(directories["audit"]),
        "actor_prospective": str(directories["actor-freeze"] / "prospective.json"),
        "prospective_directory": str(plan_dir),
        "protocol": learning.PROTOCOL,
        "granted_at": now - 1,
        "deadline": now + 120,
        "runtime": {"generated": True},
        "code": learning.code_seals(),
    }
    path = plan_dir / "prospective.json"
    producer.publish(path, plan)
    monkeypatch.setattr(learning, "runtime", lambda: {"generated": True})
    monkeypatch.setattr(
        producer,
        "configure_workspace",
        lambda _: (workspace, data, workspace / "models/weights"),
    )
    monkeypatch.setattr(learning, "load_inputs", lambda **_: ([], []))
    rows = feature_rows()
    monkeypatch.setattr(learning, "extract", lambda *_: copy.deepcopy(rows))
    return workspace, path, producer.digest(path), workspace / ".cache/run", rows


def test_complete_generated_store_run_and_readonly_verification(
    generated_run, monkeypatch
):
    workspace, path, sha, output, _ = generated_run
    before = producer.annotation_snapshot(workspace / "data/processed")
    result = learning.run(path, sha, output)
    assert result["real_fits"] == 2
    monkeypatch.setattr(learning, "fit", lambda *_: pytest.fail("Unexpected third fit"))
    original_time = time.time()
    monkeypatch.setattr(learning.time, "time", lambda: original_time + 100000)
    assert learning.verify(path, sha, output)["verified_references"] == 32
    assert producer.annotation_snapshot(workspace / "data/processed") == before
    with pytest.raises(ValueError, match="Expired"):
        learning.run(path, sha, workspace / ".cache/new")


def test_store_admission_blocks_extraction_and_consumes_original_claim(
    generated_run, monkeypatch
):
    from badminton.storage import ConflictError, Store

    workspace, path, sha, output, _ = generated_run
    store = Store(workspace / "data/processed")
    store.claim_job({"id": "competing", "kind": "players", "status": "running"})
    monkeypatch.setattr(
        learning,
        "extract",
        lambda *_: pytest.fail("Extraction without real Store admission"),
    )
    with pytest.raises(ConflictError):
        learning.run(path, sha, output)
    assert producer.read_json(output / "failure.json")["original_run_consumed"]
    assert store.job("competing")["status"] == "running"
    with pytest.raises(FileExistsError):
        learning.run(path, sha, workspace / ".cache/another-run")


def test_partial_fit_failure_is_preserved_and_not_restarted(generated_run, monkeypatch):
    workspace, path, sha, output, _ = generated_run
    monkeypatch.setattr(
        learning,
        "fit",
        lambda *_: (_ for _ in ()).throw(RuntimeError("generated failure")),
    )
    with pytest.raises(RuntimeError, match="generated"):
        learning.run(path, sha, output)
    failure = producer.read_json(output / "failure.json")
    assert failure["completed_fits"] == [] and failure["original_run_consumed"]
    assert (output / "process.json").is_file() and (output / "features.json").is_file()
    with pytest.raises(FileExistsError):
        learning.run(path, sha, workspace / ".cache/replacement")


@pytest.mark.parametrize(
    "mutation", ["code", "protocol", "runtime", "hash", "deadline", "budget", "input"]
)
def test_changes_and_limits_stop_original_run(generated_run, monkeypatch, mutation):
    _, path, sha, output, _ = generated_run
    if mutation == "code":
        monkeypatch.setattr(learning, "code_seals", lambda: {})
    elif mutation == "protocol":
        monkeypatch.setattr(learning, "PROTOCOL", {})
    elif mutation == "runtime":
        monkeypatch.setattr(learning, "runtime", lambda: {})
    elif mutation == "hash":
        sha = "0" * 64
    elif mutation == "deadline":
        now = time.time()
        monkeypatch.setattr(learning.time, "time", lambda: now + 10000)
    elif mutation == "budget":
        monkeypatch.setattr(
            learning, "budget", lambda *_: (_ for _ in ()).throw(ValueError("budget"))
        )
    else:
        monkeypatch.setattr(
            learning,
            "load_inputs",
            lambda **_: (_ for _ in ()).throw(ValueError("input")),
        )
    with pytest.raises(ValueError):
        learning.run(path, sha, output)


@pytest.mark.parametrize(
    "field", ["prepared", "native", "audit", "prospective_directory"]
)
def test_run_output_never_overlaps_frozen_inputs(generated_run, field):
    _, path, sha, _, _ = generated_run
    plan = producer.read_json(path)
    with pytest.raises(ValueError, match="overlap"):
        learning.run(path, sha, Path(plan[field]) / "new")


def test_resealed_history_selection_corruption_is_detected(tmp_path, short_schedule):
    data = learning.arrays(feature_rows(), "static")
    output = tmp_path / "arm"
    learning.fit(data, output, lambda *_: None)
    history = producer.read_json(output / "history.json")
    history[4]["validation"]["correct_joint"] += 1
    (output / "history.json").write_text(json.dumps(history), encoding="utf-8")
    with pytest.raises(ValueError, match="history"):
        learning.verify_arm(data, output)


@pytest.mark.parametrize(
    "mutation",
    ["features", "normalization", "selection", "predictions", "checkpoint", "job"],
)
def test_resealed_output_corruption_cannot_pass_scientific_verification(
    generated_run, mutation
):
    import sqlite3

    workspace, path, sha, output, _ = generated_run
    learning.run(path, sha, output)
    completion = producer.read_json(output / "completion.json")
    if mutation == "features":
        filename = output / "features.json"
        value = producer.read_json(filename)
        value[0]["temporal"][0] += 1
    elif mutation == "normalization":
        filename = output / "static/statistics.json"
        value = producer.read_json(filename)
        value["mean"][0] += 1
    elif mutation == "selection":
        filename = output / "static/result.json"
        value = producer.read_json(filename)
        value["selection"]["epoch"] += 1
    elif mutation == "predictions":
        filename = output / "static/predictions.json"
        value = producer.read_json(filename)
        value[0][0] = (value[0][0] + 1) % 8
    elif mutation == "checkpoint":
        shutil_source = output / "static/epoch-005.pt"
        filename = output / "static/epoch-010.pt"
        filename.write_bytes(shutil_source.read_bytes())
    else:
        with sqlite3.connect(workspace / "data/processed/catalog.sqlite3") as db:
            db.execute(
                "UPDATE jobs SET document=? WHERE id=?",
                (json.dumps({"status": "failed"}), completion["job_id"]),
            )
    if mutation not in ("job", "checkpoint"):
        filename.write_bytes(producer.encoded(value))
    completion["artifacts"] = {
        p.relative_to(output).as_posix(): producer.digest(p)
        for p in output.rglob("*")
        if p.is_file() and p.name != "completion.json"
    }
    (output / "completion.json").write_bytes(producer.encoded(completion))
    with pytest.raises(ValueError):
        learning.verify(path, sha, output)


def test_real_budget_aggregates_freeze_claim_and_output(generated_run, monkeypatch):
    _, path, _, output, _ = generated_run
    plan = producer.read_json(path)
    output.mkdir()
    (output / "large").write_bytes(b"x" * 100)
    protocol = copy.deepcopy(learning.PROTOCOL)
    protocol["limits"]["output_bytes"] = path.stat().st_size + 99
    monkeypatch.setattr(learning, "PROTOCOL", protocol)
    with pytest.raises(ValueError, match="budget"):
        learning.budget(plan, path, output)


@pytest.mark.parametrize("duration", [-1, 14401, float("inf"), float("nan")])
def test_deadline_refuses_expired_unbounded_and_nonfinite_windows(duration):
    now = time.time()
    with pytest.raises(ValueError):
        learning.check_deadline(now - 1, now + duration)


def test_changed_code_during_first_fit_fences_original_run(generated_run, monkeypatch):
    _, path, sha, output, _ = generated_run
    seals = learning.code_seals()
    checks = []

    def changing():
        checks.append(True)
        return seals if len(checks) == 1 else {}

    monkeypatch.setattr(learning, "code_seals", changing)
    with pytest.raises(ValueError, match="consumer"):
        learning.run(path, sha, output)
    assert producer.read_json(output / "failure.json")["completed_fits"] == []
    assert (output / "static/statistics.json").is_file()
    assert not (output / "temporal").exists()


def test_tested_commit_rejects_local_source_drift(monkeypatch):
    monkeypatch.setattr(
        learning, "code_seals", lambda: {"backend/example.py": "0" * 64}
    )
    monkeypatch.setattr(
        learning.subprocess,
        "check_output",
        lambda args, **_: "a" * 40 if args[1] == "rev-parse" else b"changed source",
    )
    with pytest.raises(ValueError, match="committed tested"):
        learning.tested_commit()


def test_alternate_research_store_cannot_bypass_original_admission(
    generated_run, monkeypatch
):
    workspace, path, _, _, _ = generated_run
    plan = producer.read_json(path)
    isolated = workspace / "isolated"
    (isolated / ".cache").mkdir(parents=True)
    plan["workspace"] = str(isolated)
    path.write_bytes(producer.encoded(plan))
    monkeypatch.setattr(
        producer,
        "configure_workspace",
        lambda *_: pytest.fail("Opened competing research Store"),
    )
    with pytest.raises(ValueError, match="real shared Store"):
        learning.run(path, producer.digest(path), isolated / ".cache/run")


def test_freeze_refuses_writing_under_original_inputs(sealed_actor, monkeypatch):
    workspace, prepared, native, plan, audit = sealed_actor
    protocol_path = workspace / "learning-overlap-protocol.json"
    producer.publish(protocol_path, learning.PROTOCOL)
    monkeypatch.setattr(learning, "runtime", lambda: {"generated": True})
    monkeypatch.setattr(learning, "tested_commit", lambda: "generated")
    with pytest.raises(ValueError, match="overlap"):
        learning.freeze(
            workspace,
            prepared,
            native,
            plan,
            audit,
            protocol_path,
            time.time() - 1,
            time.time() + 100,
            prepared / "new-freeze",
        )
    assert not (prepared / "new-freeze").exists()
