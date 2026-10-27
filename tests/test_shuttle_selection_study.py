"""Disposable integrity controls; never read scientific inputs or run inference."""

import copy
import sys
import time
import weakref
from types import SimpleNamespace

import pytest
from badminton import shuttle_selection as selection
from badminton import shuttle_selection_study as study
from badminton import shuttle_selection_synthetic as synthetic


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    study.publish(path, value)
    return study.audit.file_hash(path)


def row(frame):
    return {
        "frame": frame,
        "time_s": frame / 30,
        "shuttle": {
            "visible": False,
            "x": None,
            "y": None,
            "confidence": 0.1,
            "component_candidates": [],
        },
    }


def scorer(available=True):
    return {
        "schema_version": 1,
        "method": selection.METHOD,
        "feature_names": list(selection.FEATURE_NAMES),
        "available": available,
        "reason": None if available else "training_requires_both_candidate_classes",
        "mean": [0.0] * 14,
        "scale": [1.0] * 14,
        "weights": [0.0] * 14,
        "intercept": 0.0,
    }


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    root, output = tmp_path, tmp_path / ".cache/selector330-disposable"
    source = root / "generated.py"
    source.write_bytes(b"disposable consumer\n")
    input_path = root / "unparsed-input.bin"
    input_path.write_bytes(b"not JSON, not weights, no scientific data")
    protocol = copy.deepcopy(study.protocol_value())
    protocol["input_artifacts"] = {"disposable": study.audit.seal(root, input_path)}
    monkeypatch.setattr(study, "protocol_value", lambda: protocol)
    monkeypatch.setattr(
        study,
        "consumers",
        lambda root: {"badminton/generated.py": study.audit.seal(root, source)},
    )
    monkeypatch.setattr(
        study.existing, "runtime_snapshot", lambda: {"disposable": True}
    )

    def ignored(root, output):
        output.mkdir(parents=True, exist_ok=False)
        return output

    monkeypatch.setattr(study.audit, "ignored_output", ignored)
    monkeypatch.setattr(
        synthetic,
        "generate_group",
        lambda *args: pytest.fail("freeze must never generate held-out pixels"),
    )
    public = root / "protocol.json"
    checksum = put(public, protocol)
    granted = time.time() - 2
    result = study.freeze(root, public, checksum, output, granted, granted + 12 * 3600)
    return root, output, result["experiment_sha256"], source, input_path, protocol


def test_protocol_and_seed_inventory_are_metadata_only(monkeypatch):
    monkeypatch.setattr(
        synthetic, "generate_group", lambda *args: pytest.fail("metadata only")
    )
    study.validate_protocol(copy.deepcopy(study.protocol_value()))
    seeds = study.seed_inventory()
    assert {key: len(value) for key, value in seeds.items()} == {
        "train": 128,
        "validation": 16,
        "test": 32,
    }
    assert len({seed for values in seeds.values() for seed in values}) == 176
    changed = copy.deepcopy(study.protocol_value())
    changed["split_groups"]["test"] = 31
    with pytest.raises(ValueError, match="Protocol differs"):
        study.validate_protocol(changed)


def test_freeze_hashes_unparsed_inputs_and_preserves_clock(frozen):
    root, output, expected, _, input_path, _ = frozen
    receipt, _ = study.load(root, output, expected)
    assert receipt["deadline"] == receipt["granted_at"] + 43200
    assert receipt["inputs"]["disposable"]["bytes"] == input_path.stat().st_size
    assert receipt["borrowed_input_bytes"] == input_path.stat().st_size
    assert not (output / "test-opened.json").exists()


@pytest.mark.parametrize("kind", ["source", "copy", "protocol", "experiment", "input"])
def test_changed_frozen_bytes_refuse_before_science(frozen, kind):
    root, output, expected, source, input_path, _ = frozen
    target = {
        "source": source,
        "copy": output / "consumer/badminton/generated.py",
        "protocol": output / "protocol.json",
        "experiment": output / "experiment.json",
        "input": input_path,
    }[kind]
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ValueError):
        study.load(root, output, expected)


@pytest.mark.parametrize("kind", ["expired", "extended", "boolean", "nan"])
def test_load_never_renews_or_accepts_invalid_clock(frozen, monkeypatch, kind):
    root, output, _, _, _, _ = frozen
    receipt = study.audit.read_json((output / "experiment.json").read_bytes())
    if kind == "expired":
        monkeypatch.setattr(study.time, "time", lambda: receipt["deadline"])
    elif kind == "extended":
        receipt["deadline"] += 3600
    elif kind == "boolean":
        receipt.update(granted_at=True, deadline=43201)
        monkeypatch.setattr(study.time, "time", lambda: 2)
    else:
        receipt["granted_at"] = "NaN"
    (output / "experiment.json").write_bytes(study.audit.encoded(receipt))
    with pytest.raises(ValueError, match="deadline"):
        study.load(root, output, study.audit.file_hash(output / "experiment.json"))


def test_runtime_and_seed_mapping_are_frozen(frozen, monkeypatch):
    root, output, expected, *_ = frozen
    monkeypatch.setattr(study.existing, "runtime_snapshot", lambda: {"different": True})
    with pytest.raises(ValueError, match="runtime changed"):
        study.load(root, output, expected)
    monkeypatch.setattr(
        study.existing, "runtime_snapshot", lambda: {"disposable": True}
    )
    monkeypatch.setattr(study, "seed_inventory", lambda: {"train": [1]})
    with pytest.raises(ValueError, match="source-group mapping changed"):
        study.load(root, output, expected)


def test_exhausted_output_budget_refuses(frozen, monkeypatch):
    root, output, expected, _, _, protocol = frozen
    monkeypatch.setattr(
        study, "new_output_bytes", lambda root: protocol["limits"]["new_retained_bytes"]
    )
    with pytest.raises(ValueError, match="output budget exhausted"):
        study.load(root, output, expected)


@pytest.mark.parametrize(
    "stage,marker",
    [
        ("fit", "fit-opened.json"),
        ("fit", "fits.json"),
        ("test", "test-opened.json"),
        ("test", "test.json"),
        ("familiar", "familiar-opened.json"),
        ("familiar", "familiar.json"),
        ("trainval", "trainval.json"),
    ],
)
def test_completed_or_opened_stages_cannot_repeat(tmp_path, monkeypatch, stage, marker):
    put(tmp_path / marker, {"preserved": True})
    monkeypatch.setattr(study, "admission", lambda *args, **kw: pytest.fail("no rerun"))
    monkeypatch.setattr(
        study, "sealed_fits", lambda *args: pytest.fail("no later reads")
    )
    function = {"fit": study.fit_all, "test": study.test}.get(
        stage, getattr(study, stage, None)
    )
    args = (tmp_path, tmp_path, "receipt")
    if stage in ("test", "familiar"):
        args += ("public",)
    with pytest.raises(ValueError):
        function(*args)
    assert study.audit.read_json((tmp_path / marker).read_bytes()) == {
        "preserved": True
    }


def fitted_receipts(output):
    trainval_sha = put(output / "trainval.json", {"disposable": True})
    fits = {
        "experiment_sha256": "experiment",
        "trainval_sha256": trainval_sha,
        "test_generated": False,
        "variants": {
            variant: {
                "scorer": scorer(),
                "validation": {"available": True, "threshold": 0.7},
            }
            for variant in study.VARIANTS
        },
    }
    fits_sha = put(output / "fits.json", fits)
    public = {
        "comment": "https://github.com/Ken0u/badminton-match-analyzer/issues/330#issuecomment-1",
        "experiment_sha256": "experiment",
        "fits_sha256": fits_sha,
    }
    return fits, public, put(output / "fit-public-seal.json", public)


def test_all_three_fits_and_exact_public_seal_required(tmp_path):
    fits, public, seal = fitted_receipts(tmp_path)
    assert study.sealed_fits(tmp_path, "experiment", seal) == (fits, public)
    with pytest.raises(ValueError, match="timestamped fit seal"):
        study.sealed_fits(tmp_path, "experiment", "0" * 64)
    (tmp_path / "fits.json").write_bytes(
        study.audit.encoded({**fits, "test_generated": True})
    )
    with pytest.raises(ValueError, match="public seal"):
        study.sealed_fits(tmp_path, "experiment", seal)


@pytest.mark.parametrize("kind", ["method", "threshold", "experiment", "trainval"])
def test_resealed_invalid_fits_cannot_open_test(tmp_path, kind):
    fits, public, _ = fitted_receipts(tmp_path)
    if kind == "method":
        del fits["variants"]["convolution"]
    elif kind == "threshold":
        fits["variants"]["control"]["validation"]["threshold"] = 0.75
    elif kind == "experiment":
        fits["experiment_sha256"] = "different"
    else:
        fits["trainval_sha256"] = "different"
    (tmp_path / "fits.json").write_bytes(study.audit.encoded(fits))
    public["fits_sha256"] = study.audit.file_hash(tmp_path / "fits.json")
    (tmp_path / "fit-public-seal.json").write_bytes(study.audit.encoded(public))
    with pytest.raises(ValueError):
        study.test(
            tmp_path,
            tmp_path,
            "experiment",
            study.audit.file_hash(tmp_path / "fit-public-seal.json"),
        )
    assert not (tmp_path / "test-opened.json").exists()


@pytest.mark.parametrize(
    "fit_available,validation_available", [(False, False), (True, False)]
)
def test_unavailable_fitted_method_retains_rows_and_reasons(
    fit_available, validation_available
):
    rows = [row(0), row(1)]
    before = copy.deepcopy(rows)
    fitted = {
        "scorer": scorer(fit_available),
        "validation": {
            "available": validation_available,
            "threshold": None,
            "reason": "validation_has_no_available_localization_truth",
        },
    }
    groups = [
        {
            "split": "test",
            "rows": rows,
            "labels": [{"frame": i, "visible": False} for i in range(2)],
        }
    ]
    result = study.selected_groups(groups, fitted)
    assert rows == before
    assert len(result[0]["rows"]) == 2
    assert all(not r["selection_available"] for r in result[0]["rows"])
    assert all(r["selection_unavailable_reason"] for r in result[0]["rows"])
    metrics = selection.metrics(result)
    assert metrics["frames"] == metrics["unavailable_negative"] == 2
    assert metrics["localization_tn"] == 0


def test_source_context_keeps_cuts_exclusions_and_unknowns_unavailable():
    run = {
        "start_frame": 0,
        "end_frame": 10,
        "camera_ranges": [
            {"start_frame": 0, "end_frame": 5},
            {"start_frame": 5, "end_frame": 10},
        ],
        "cut_frames": [5],
    }
    annotations = {
        "scene_ranges": [
            {"start_frame": 0, "end_frame": 3, "scene": "live"},
            {"start_frame": 3, "end_frame": 6, "scene": "replay"},
            {"start_frame": 6, "end_frame": 9, "scene": "live"},
        ]
    }
    segments = study.eligible_segments(run, annotations)
    eligibility = {
        frame: segment["eligible"]
        for segment in segments
        for frame in range(segment["start_frame"], segment["end_frame"])
    }
    assert eligibility == {frame: frame < 3 or 6 <= frame < 9 for frame in range(10)}
    assert not any(s["start_frame"] < 5 < s["end_frame"] for s in segments)


@pytest.mark.parametrize("annotations", [None, {}, {"scene_ranges": []}])
def test_missing_reviewed_scene_context_never_infers_live(annotations):
    run = {
        "start_frame": 0,
        "end_frame": 2,
        "camera_ranges": [{"start_frame": 0, "end_frame": 2}],
        "cut_frames": [],
    }
    assert not any(s["eligible"] for s in study.eligible_segments(run, annotations))


def test_admission_uses_original_shared_store_and_records_terminal(frozen, monkeypatch):
    from badminton import config, jobs, storage

    root, output, expected, *_ = frozen
    shared = root / "data/processed"
    shared.mkdir(parents=True)
    (shared / "catalog.sqlite3").write_bytes(b"disposable marker")
    monkeypatch.setattr(config, "ROOT", root)
    monkeypatch.setattr(config, "DATA", shared)
    monkeypatch.setattr(config, "WEIGHTS", root / "models/weights")
    monkeypatch.setattr(study.existing, "prior_attempt_proof", lambda *args: [])
    store = object()
    seen = []
    monkeypatch.setattr(storage, "Store", lambda path: seen.append(path) or store)

    def admitted(actual, kind, video_id, callback):
        assert actual is store and kind == "feature-preparation" and video_id is None
        return callback("disposable-job", lambda progress: None)

    monkeypatch.setattr(jobs, "run_local_job", admitted)

    def body(experiment, protocol, attempt, progress):
        evidence = study.audit.read_json((attempt / "admission.json").read_bytes())
        assert evidence["job_id"] == "disposable-job"
        assert evidence["process"]["pid"] > 0
        assert evidence["process"]["creation_time"] > 0
        progress(1)
        return {"disposable": True}

    result = study.admission(root, output, expected, "fit", body)
    assert seen == [shared]
    terminal = study.audit.read_json(
        (output / result["attempt"] / "terminal.json").read_bytes()
    )
    assert terminal == {"status": "completed", "result": {"disposable": True}}


@pytest.mark.parametrize("bad", ["root", "data", "weights", "catalog", "running"])
def test_admission_refuses_isolated_or_nonterminal_store(frozen, monkeypatch, bad):
    from badminton import config, jobs

    root, output, expected, *_ = frozen
    shared = root / "data/processed"
    shared.mkdir(parents=True)
    if bad != "catalog":
        (shared / "catalog.sqlite3").write_bytes(b"disposable marker")
    monkeypatch.setattr(config, "ROOT", root / "wrong" if bad == "root" else root)
    monkeypatch.setattr(config, "DATA", root / "wrong" if bad == "data" else shared)
    monkeypatch.setattr(
        config,
        "WEIGHTS",
        root / "wrong" if bad == "weights" else root / "models/weights",
    )
    monkeypatch.setattr(
        study.existing,
        "prior_attempt_proof",
        lambda *args: [{"store_status": "running"}] if bad == "running" else [],
    )
    monkeypatch.setattr(
        jobs, "run_local_job", lambda *args: pytest.fail("no job admission")
    )
    with pytest.raises(ValueError):
        study.admission(
            root, output, expected, "fit", lambda *args: pytest.fail("no work")
        )


def test_failed_incomplete_test_keeps_opening_marker(tmp_path, monkeypatch):
    fits, public, seal = fitted_receipts(tmp_path)
    monkeypatch.setattr(study, "checkpoint_paths", lambda *args: {})

    def admitted(root, output, expected, stage, function, **kwargs):
        assert stage == "test"
        return function({}, {}, tmp_path, lambda value: None)

    monkeypatch.setattr(study, "admission", admitted)

    def fail(*args, **kwargs):
        assert kwargs["resume"] is False
        assert (tmp_path / "test-opened.json").exists()
        raise RuntimeError("disposable interrupted inference")

    monkeypatch.setattr(study, "generated_inference", fail)
    with pytest.raises(RuntimeError, match="disposable interrupted"):
        study.test(tmp_path, tmp_path, "experiment", seal)
    with pytest.raises(ValueError, match="already opened"):
        study.test(tmp_path, tmp_path, "experiment", seal)
    assert study.sealed_fits(tmp_path, "experiment", seal) == (fits, public)


@pytest.mark.parametrize("variant", study.VARIANTS)
@pytest.mark.parametrize(
    "change", [None, "fp", "fn", "tn", "cases", "states", "components"]
)
def test_full_familiar_baseline_gate_checks_more_than_true_positives(variant, change):
    protocol = study.protocol_value()
    familiar = protocol["familiar"]
    original = {
        "all": {
            "metrics": {
                "cases": familiar["cases"],
                "truth_states": {
                    **dict.fromkeys(study.audit.PROTOCOL["states"], 0),
                    **familiar["truth_states"],
                },
                "visibility": copy.deepcopy(
                    familiar["baseline_visibility_counts"][variant]
                ),
                "localization": copy.deepcopy(
                    familiar["baseline_localization_counts"][variant]
                ),
            },
            "components": {
                "component_present": familiar["baseline_agreeing_components"][variant]
            },
        }
    }
    if change is None:
        study.validate_baseline(original, protocol, variant)
        return
    if change in {"fp", "fn", "tn"}:
        original["all"]["metrics"]["localization"][change] += 1
    elif change == "cases":
        original["all"]["metrics"]["cases"] -= 1
    elif change == "states":
        original["all"]["metrics"]["truth_states"]["unknown"] -= 1
    else:
        original["all"]["components"]["component_present"] += 1
    with pytest.raises(ValueError):
        study.validate_baseline(original, protocol, variant)


def test_generated_pairing_retains_unknown_and_unavailable_membership():
    left = {
        "outcomes": [
            {
                "group": 0,
                "frame": 0,
                "state": "unknown",
                "visibility": "unscored",
                "localization": "unscored",
            },
            {
                "group": 0,
                "frame": 1,
                "state": "not_visible",
                "visibility": "fp",
                "localization": "fp",
            },
        ]
    }
    right = copy.deepcopy(left)
    right["outcomes"][1].update(visibility="unavailable", localization="unavailable")
    pairs = study.paired_generated(left, right)
    assert pairs["localization"] == {"fp->unavailable": 1, "unscored->unscored": 1}
    right["outcomes"][1]["frame"] = 2
    with pytest.raises(ValueError, match="membership changed"):
        study.paired_generated(left, right)


@pytest.fixture
def generated_caches(tmp_path, monkeypatch):
    from badminton import shuttle_capacity as capacity

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda: None)),
    )
    monkeypatch.setattr(synthetic, "SPLITS", {"train": 1})
    live_models = []

    class Model:
        pass

    def model_from(path, device):
        assert device == "cuda:0"
        assert all(reference() is None for reference in live_models), (
            "previous callback retains a neural model"
        )
        model = Model()
        live_models.append(weakref.ref(model))
        return model

    monkeypatch.setattr(capacity, "model_from", model_from)
    monkeypatch.setattr(
        capacity, "predict_function", lambda model: (lambda *args: model, [0])
    )
    identity = {
        "split": "train",
        "index": 0,
        "seed": 1,
        "pixels_sha256": "disposable-pixels",
        "background_sha256": "disposable-background",
        "labels": [{"frame": i, "visible": False} for i in range(synthetic.FRAMES)],
    }
    monkeypatch.setattr(
        study, "generated_group", lambda *args: (None, None, copy.deepcopy(identity))
    )
    calls = []
    monkeypatch.setattr(
        study,
        "infer_group",
        lambda *args: calls.append(True) or [row(i) for i in range(synthetic.FRAMES)],
    )
    paths = {}
    for variant in study.VARIANTS:
        path = tmp_path / (variant + ".bin")
        path.write_bytes(b"disposable, not neural weights")
        paths[variant] = path
    output = tmp_path / "output"
    output.mkdir()
    return tmp_path, output, paths, calls, live_models


def test_generated_cache_resume_never_repeats_completed_groups_or_retains_models(
    generated_caches,
):
    root, output, paths, calls, live_models = generated_caches
    first = study.generated_inference(
        root, output, "experiment", paths, ("train",), lambda value: None, resume=True
    )
    assert len(calls) == 3
    assert all(reference() is None for reference in live_models)
    second = study.generated_inference(
        root, output, "experiment", paths, ("train",), lambda value: None, resume=True
    )
    assert second == first
    assert len(calls) == 3


@pytest.mark.parametrize(
    "change", ["missing_seal", "row", "binding", "orphan", "oneshot"]
)
def test_generated_cache_resume_rejects_unverified_or_changed_completion(
    generated_caches, change
):
    root, output, paths, calls, _ = generated_caches
    study.generated_inference(
        root, output, "experiment", paths, ("train",), lambda value: None, resume=True
    )
    path = output / "groups/control/train/000.json"
    seal = path.with_suffix(".seal.json")
    if change == "missing_seal":
        seal.unlink()
    elif change == "row":
        group = study.audit.read_json(path.read_bytes())
        group["rows"][0]["shuttle"]["confidence"] = 0.2
        path.write_bytes(study.audit.encoded(group))
    elif change == "binding":
        value = study.audit.read_json(seal.read_bytes())
        value["experiment_sha256"] = "different"
        seal.write_bytes(study.audit.encoded(value))
    elif change == "orphan":
        path.unlink()
    with pytest.raises(ValueError):
        study.generated_inference(
            root,
            output,
            "experiment",
            paths,
            ("train",),
            lambda value: None,
            resume=change != "oneshot",
        )
    assert len(calls) == 3


def cached_fixture(root, change=None):
    output = root / ".cache/continued"
    output.mkdir(parents=True)
    view = {
        "id": "generated-view",
        "video_id": "generated-source",
        "start_frame": 0,
        "end_frame": 2,
    }
    old_sha = put(output / "experiment.json", {"views": [view]})
    predecessor = root / ".cache/predecessor/experiment.json"
    prior_sha = put(predecessor, {"generated": True})
    inputs = {
        "capacity-continuation-experiment": study.audit.seal(
            root, output / "experiment.json"
        ),
        "capacity-experiment": study.audit.seal(root, predecessor),
    }
    references, files = {}, {}
    for variant in study.VARIANTS:
        checkpoint = root / (variant + ".bin")
        checkpoint.write_bytes(b"disposable checkpoint identity " + variant.encode())
        key = "parent-checkpoint" if variant == "control" else variant + "-checkpoint"
        inputs[key] = study.audit.seal(root, checkpoint)
        run = {
            "checkpoint_sha256": inputs[key]["sha256"],
            "video_id": view["video_id"],
            "input_size": [512, 288],
            "seq_len": 8,
            "temporal_context_crosses_detected_cuts": False,
            "start_frame": 0,
            "end_frame": 2,
            "processed_frames": 2,
            "frames": [row(0), row(1)],
        }
        if variant == "control":
            if change == "checkpoint":
                run["checkpoint_sha256"] = "different"
            if change == "clock":
                run["frames"][1]["time_s"] = 0
            if change == "frames":
                run["frames"].pop()
            if change == "source":
                run["video_id"] = "different"
            if change == "context":
                run["temporal_context_crosses_detected_cuts"] = True
        run_path = output / (variant + "-run.json")
        put(run_path, run)
        receipt_path = output / (variant + "-receipt.json")
        receipt = {
            "view": view,
            "experiment_sha256": old_sha,
            "run": study.audit.seal(output, run_path),
        }
        if variant == "control" and change == "receipt":
            receipt["experiment_sha256"] = prior_sha
        put(receipt_path, receipt)
        references[variant] = [
            {
                "origin": "continuation",
                "receipt": study.audit.seal(root, receipt_path),
                "run": study.audit.seal(root, run_path),
            }
        ]
        files[variant + "-run"] = study.audit.seal(output, run_path)
        files[variant + "-receipt"] = study.audit.seal(output, receipt_path)
    if change == "denominator":
        references["decoder"] = []
    if change == "duplicate":
        references["control"] *= 2
    raw = {"experiment_sha256": old_sha, "references": references, "files": files}
    raw_path = output / "raw-index.json"
    put(raw_path, raw)
    inputs["capacity-raw-index"] = study.audit.seal(root, raw_path)
    return {
        "input_artifacts": inputs,
        "familiar": {
            "raw_output_root": ".cache/continued",
            "views_per_method": 1,
            "rows_per_method": 2,
        },
    }


def test_cached_views_validate_original_hash_lineage_without_native_execution(tmp_path):
    protocol = cached_fixture(tmp_path)
    result = study.cached_views(tmp_path, protocol)
    assert set(result) == set(study.VARIANTS)
    assert all(len(values) == 1 for values in result.values())


@pytest.mark.parametrize(
    "change",
    [
        "checkpoint",
        "clock",
        "frames",
        "source",
        "context",
        "receipt",
        "denominator",
        "duplicate",
    ],
)
def test_cached_views_reject_resealed_invalid_native_lineage(tmp_path, change):
    protocol = cached_fixture(tmp_path, change)
    with pytest.raises(ValueError):
        study.cached_views(tmp_path, protocol)


@pytest.mark.parametrize(
    "change",
    [
        None,
        "missing_admission",
        "missing_terminal",
        "failed",
        "experiment",
        "stage",
        "result",
        "changed_output",
    ],
)
def test_completed_stage_requires_matching_admission_terminal_and_result(
    tmp_path, change
):
    path = tmp_path / "test.json"
    checksum = put(path, {"disposable": True})
    attempt = tmp_path / "attempts/generated"
    admission = {"experiment_sha256": "experiment", "stage": "test"}
    terminal = {"status": "completed", "result": {"test_sha256": checksum}}
    if change == "failed":
        terminal["status"] = "failed"
    if change == "experiment":
        admission["experiment_sha256"] = "different"
    if change == "stage":
        admission["stage"] = "fit"
    if change == "result":
        terminal["result"]["test_sha256"] = "different"
    if change != "missing_admission":
        put(attempt / "admission.json", admission)
    if change != "missing_terminal":
        put(attempt / "terminal.json", terminal)
    if change == "changed_output":
        path.write_bytes(path.read_bytes() + b" ")
    if change is None:
        assert (
            study.completed_stage(tmp_path, "experiment", "test", path, "test_sha256")
            == checksum
        )
    else:
        with pytest.raises(ValueError, match="incomplete or its result changed"):
            study.completed_stage(tmp_path, "experiment", "test", path, "test_sha256")


def test_familiar_refuses_unadmitted_test_before_reading_familiar_inputs(
    tmp_path, monkeypatch
):
    _, public, seal = fitted_receipts(tmp_path)
    put(
        tmp_path / "test.json",
        {
            "experiment_sha256": "experiment",
            "fits_sha256": public["fits_sha256"],
            "variants": {variant: {} for variant in study.VARIANTS},
        },
    )
    monkeypatch.setattr(
        study,
        "admission",
        lambda *args, **kwargs: pytest.fail("no familiar work before completed test"),
    )
    monkeypatch.setattr(
        study, "cached_views", lambda *args: pytest.fail("no familiar inputs")
    )
    with pytest.raises(ValueError, match="incomplete"):
        study.familiar(tmp_path, tmp_path, "experiment", seal)
    assert not (tmp_path / "familiar-opened.json").exists()


def test_familiar_dispatch_resolves_provenance_from_nested_packet(
    tmp_path, monkeypatch
):
    _, public, seal = fitted_receipts(tmp_path)
    put(
        tmp_path / "test.json",
        {
            "experiment_sha256": "experiment",
            "fits_sha256": public["fits_sha256"],
            "variants": {variant: {} for variant in study.VARIANTS},
        },
    )
    monkeypatch.setattr(study, "completed_stage", lambda *args: "completed")
    packet_root = tmp_path / "nested/source-packet"
    metadata = packet_root / "provenance/source/metadata.json"
    put(metadata, {"id": "disposable-source"})
    packet = {"source_inputs": {"metadata": study.audit.seal(packet_root, metadata)}}
    packet_path = packet_root / "packet.json"
    put(packet_path, packet)
    inputs = {"familiar-source-packet": study.audit.seal(tmp_path, packet_path)}
    for name in ("familiar-source-labels", "familiar-source-baseline"):
        path = tmp_path / (name + ".json")
        put(path, {})
        inputs[name] = study.audit.seal(tmp_path, path)
    monkeypatch.setattr(study, "cached_views", lambda *args: {})
    monkeypatch.setattr(
        study,
        "admission",
        lambda root, output, expected, stage, function: function(
            {}, {"input_artifacts": inputs}, tmp_path, lambda progress: None
        ),
    )

    class ProvenanceVerified(Exception):
        pass

    def validate(root, value, views):
        assert root == packet_root
        assert study.audit.read_json(
            study.audit.sealed_bytes(root, value["source_inputs"]["metadata"])
        ) == {"id": "disposable-source"}
        raise ProvenanceVerified

    monkeypatch.setattr(study, "validate_source_views", validate)
    with pytest.raises(ProvenanceVerified):
        study.familiar(tmp_path, tmp_path, "experiment", seal)
    assert not (tmp_path / "familiar-opened.json").exists()


def test_failed_fit_preserves_opening_marker_and_never_silently_retrains(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        study,
        "load_trainval",
        lambda *args: {
            variant: {"train": [], "validation": []} for variant in study.VARIANTS
        },
    )
    monkeypatch.setattr(
        study,
        "admission",
        lambda root, output, expected, stage, function: function(
            {}, {}, tmp_path, lambda progress: None
        ),
    )

    def interrupted(*args):
        assert (tmp_path / "fit-opened.json").exists()
        raise RuntimeError("disposable fit interruption")

    monkeypatch.setattr(selection, "fit", interrupted)
    with pytest.raises(RuntimeError, match="disposable fit interruption"):
        study.fit_all(tmp_path, tmp_path, "experiment")
    with pytest.raises(ValueError, match="silently retrained"):
        study.fit_all(tmp_path, tmp_path, "experiment")


@pytest.mark.parametrize(
    "change",
    [
        None,
        "source_set",
        "source_hash",
        "frame_count",
        "geometry",
        "rotation",
        "run_hash",
        "run_stage",
        "pts",
    ],
)
def test_source_views_bind_metadata_geometry_and_exact_native_pts(
    tmp_path, monkeypatch, change
):
    protocol = copy.deepcopy(study.audit.PROTOCOL)
    protocol["sources"] = [
        {"id": "generated-source", "sha256": "generated-sha", "frame_count": 2}
    ]
    monkeypatch.setattr(study.audit, "PROTOCOL", protocol)
    meta = {
        "id": "generated-source",
        "sha256": "generated-sha",
        "width": 640,
        "height": 360,
        "rotation": 90,
    }
    times = [0, 1 / 30]
    if change == "source_hash":
        meta["sha256"] = "different"
    if change == "frame_count":
        times.append(2 / 30)
    metadata = tmp_path / "metadata.json"
    timestamps = tmp_path / "timestamps.json"
    put(metadata, meta)
    put(timestamps, times)
    packet = {
        "source_inputs": {
            "generated-source": {
                "metadata": study.audit.seal(tmp_path, metadata),
                "timestamps": study.audit.seal(tmp_path, timestamps),
            }
        },
        "cases": [
            {
                "id": "generated-case",
                "video_id": "generated-source",
                "width": 640,
                "height": 360,
                "rotation": 90,
            }
        ],
    }
    if change == "source_set":
        packet["source_inputs"] = {}
    if change == "geometry":
        packet["cases"][0]["width"] = 641
    if change == "rotation":
        packet["cases"][0]["rotation"] = 0
    view = {
        "id": "generated-view",
        "video_id": "generated-source",
        "start_frame": 0,
        "end_frame": 2,
    }
    run = {
        "video_sha256": "generated-sha",
        "stage": "shuttle",
        "processed_frames": 2,
        "frames": [row(0), row(1)],
    }
    if change == "run_hash":
        run["video_sha256"] = "different"
    if change == "run_stage":
        run["stage"] = "players"
    if change == "pts":
        run["frames"][1]["time_s"] += 0.01
    views = {variant: {"generated-view": (view, run)} for variant in study.VARIANTS}
    if change is None:
        study.validate_source_views(tmp_path, packet, views)
    else:
        with pytest.raises(ValueError):
            study.validate_source_views(tmp_path, packet, views)


def familiar_disposable(root, monkeypatch, module):
    """Generated cached rows with known visible/negative/unknown denominators."""
    output = root / "original"
    fits, public, seal = fitted_receipts(output)
    put(
        output / "test.json",
        {
            "experiment_sha256": "experiment",
            "fits_sha256": public["fits_sha256"],
            "variants": {variant: {} for variant in module.VARIANTS},
        },
    )
    cases, labels = [], []
    for frame, state in enumerate(("visible", "not_visible", "unknown")):
        case = {
            "id": f"generated-{frame}",
            "video_id": "generated",
            "frame": frame,
            "width": 512,
            "height": 288,
        }
        cases.append(case)
        labels.append(
            {
                "id": case["id"],
                "disagreement": {"state": False},
                "label": {
                    "id": case["id"],
                    "state": state,
                    "x": 1.0 if state == "visible" else None,
                    "y": 1.0 if state == "visible" else None,
                    "uncertainty_px": 0.1 if state == "visible" else None,
                    "reason": "Generated disposable observation",
                    "difficulty": ["unresolved"],
                    "context_cut": False,
                },
            }
        )
    scenes = [{"start_frame": 0, "end_frame": 3, "scene": "live"}]
    inputs = {}
    values = {
        "familiar-source-packet": {"cases": cases},
        "familiar-source-labels": {"cases": labels},
        "familiar-source-baseline": {
            "evidence": {
                "catalogs": {
                    "generated": {"snapshot": {"annotations": {"scene_ranges": scenes}}}
                }
            }
        },
    }
    for name, value in values.items():
        path = root / "nested/packet" / (name + ".json")
        put(path, value)
        inputs[name] = module.audit.seal(root, path)
    view = {
        "id": "generated-view",
        "video_id": "generated",
        "start_frame": 0,
        "end_frame": 3,
        "case_ids": [case["id"] for case in cases],
    }
    run = {
        "start_frame": 0,
        "end_frame": 3,
        "processed_frames": 3,
        "camera_ranges": [{"start_frame": 0, "end_frame": 3}],
        "cut_frames": [],
        "frames": [row(frame) for frame in range(3)],
    }
    views = {v: {view["id"]: (view, run)} for v in module.VARIANTS}
    monkeypatch.setattr(module, "cached_views", lambda *args: views)
    monkeypatch.setattr(module, "validate_source_views", lambda *args: None)

    def baseline(value, protocol, variant):
        metrics = value["all"]["metrics"]
        assert metrics["cases"] == 3 and metrics["truth_states"]["unknown"] == 1
        assert metrics["localization"]["fn"] == metrics["localization"]["tn"] == 1

    monkeypatch.setattr(module, "validate_baseline", baseline)
    monkeypatch.setattr(module, "completed_stage", lambda *args: "completed")
    protocol = {
        "input_artifacts": inputs,
        "familiar": {
            "cases": 3,
            "truth_states": {"visible": 1, "not_visible": 1, "unknown": 1},
        },
        "limitations": ["Generated fixture, not scientific source data"],
    }
    monkeypatch.setattr(
        module,
        "admission",
        lambda root, output, expected, stage, function: function(
            {}, protocol, root / "attempt", lambda progress: None
        ),
    )
    return output, fits, public, seal, protocol


def test_extracted_familiar_helper_preserves_entry_point_results(tmp_path, monkeypatch):
    output, fits, public, seal, protocol = familiar_disposable(
        tmp_path, monkeypatch, study
    )
    original = study.familiar(tmp_path, output, "experiment", seal)
    direct_output = tmp_path / "separate-continuation"
    direct_output.mkdir()
    direct = study.familiar_diagnostic(
        tmp_path,
        direct_output,
        "experiment",
        fits,
        public,
        protocol,
        lambda progress: None,
        public_seal_sha256=seal,
        fit_output=output,
        fit_experiment_sha256="experiment",
    )
    assert original == direct
    for name in (
        "familiar-opened.json",
        "familiar.json",
        *(f"familiar-selected-{variant}.json" for variant in study.VARIANTS),
    ):
        assert (output / name).read_bytes() == (direct_output / name).read_bytes()
    assert direct["cases"] == 3 and direct["unknown"] == 1


def sized_file(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_retained_budget_does_not_rescan_static_task_tree_per_progress(
    tmp_path, monkeypatch
):
    output = tmp_path / ".cache/selector330-generated"
    sized_file(output / "current.bin", 5)
    sized_file(tmp_path / ".cache/selector330-preserved/prior.bin", 7)
    clock, scans = [100.0], []
    original = study.new_output_bytes

    def counted(root):
        scans.append(root)
        return original(root)

    monkeypatch.setattr(study, "new_output_bytes", counted)
    monkeypatch.setattr(study.time, "monotonic", lambda: clock[0])
    check = study.retained_budget(tmp_path, output, 100, refresh_seconds=60)
    for _ in range(20):
        check()
    assert len(scans) == 1
    clock[0] = 159.9
    check()
    assert len(scans) == 1
    clock[0] = 160.0
    check()
    assert len(scans) == 2


@pytest.mark.parametrize("output_name", ["selector330-generated", "generic-generated"])
def test_retained_budget_includes_live_output_once_and_stops_at_limit(
    tmp_path, output_name
):
    output = tmp_path / ".cache" / output_name
    sized_file(output / "current.bin", 5)
    sized_file(tmp_path / ".cache/selector330-preserved/prior.bin", 7)
    check = study.retained_budget(tmp_path, output, 13)
    check()  # Twelve bytes: a counted output must not be included twice.
    sized_file(output / "new.bin", 1)
    with pytest.raises(ValueError, match="budget"):
        check()  # Thirteen bytes: even an uncounted generic output is retained.


def test_retained_budget_refresh_detects_external_preserved_growth(
    tmp_path, monkeypatch
):
    output = tmp_path / ".cache/selector330-generated"
    static = tmp_path / ".cache/selector330-preserved/prior.bin"
    sized_file(output / "current.bin", 5)
    sized_file(static, 7)
    clock = [100.0]
    monkeypatch.setattr(study.time, "monotonic", lambda: clock[0])
    check = study.retained_budget(tmp_path, output, 20, refresh_seconds=60)
    check()
    sized_file(static, 15)
    clock[0] = 159.0
    check()
    clock[0] = 160.0
    with pytest.raises(ValueError, match="budget"):
        check()


def test_retained_budget_initial_full_scope_cannot_be_omitted(tmp_path):
    output = tmp_path / ".cache/selector330-generated"
    sized_file(output / "current.bin", 2)
    sized_file(tmp_path / ".cache/selector-planning-v1/preserved.bin", 3)
    sized_file(tmp_path / ".cache/selector-preflight-v1/preserved.bin", 3)
    sized_file(tmp_path / ".cache/worktrees/selector330-old/preserved.bin", 4)
    with pytest.raises(ValueError, match="budget"):
        study.retained_budget(tmp_path, output, 12)()
