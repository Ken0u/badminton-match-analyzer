"""Generated research guards; no broadcast inputs or installed model access."""

import copy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from badminton import shuttle
from badminton import shuttle_capacity as study
from badminton.shuttle_capacity_synthetic import PARENT_SHA256, PROTOCOL
from PIL import Image


def test_protocol_refuses_any_unfrozen_selection_or_schedule():
    study.validate_protocol(copy.deepcopy(PROTOCOL))
    for field in ("epochs", "learning_rate", "seed"):
        protocol = copy.deepcopy(PROTOCOL)
        protocol["training"][field] += 1
        with pytest.raises(ValueError, match="sole frozen recipe"):
            study.validate_protocol(protocol)


def test_selection_uses_only_finite_validation_loss_with_earliest_tie():
    rows = [
        {
            "epoch": index + 1,
            "validation_loss": loss,
            "test_loss": 100 - index,
            "real_score": index,
        }
        for index, loss in enumerate([0.3, 0.2, 0.2, 0.4])
    ]
    assert study.choose_epoch(rows)["epoch"] == 2
    rows[2]["test_loss"] = -99999
    assert study.choose_epoch(rows)["epoch"] == 2
    for value in (float("nan"), float("inf"), None, True):
        rows[0]["validation_loss"] = value
        with pytest.raises(ValueError, match="finite validation"):
            study.choose_epoch(rows)


def test_balanced_loss_preserves_negative_frames_and_positive_support():
    torch = pytest.importorskip("torch")
    target = torch.zeros(1, 2, 3, 4)
    assert study.balanced_loss(torch.ones_like(target), target).item() == pytest.approx(
        0.5
    )
    target[:, :, 1, 2] = 1
    assert study.balanced_loss(
        torch.zeros_like(target), target
    ).item() == pytest.approx(0.5)
    assert study.balanced_loss(target.clone(), target).item() == 0
    with pytest.raises(ValueError, match="Finite"):
        study.balanced_loss(target * float("nan"), target)
    with pytest.raises(ValueError, match="Matching"):
        study.balanced_loss(target[0], target)


@pytest.mark.parametrize("variant,count", [("decoder", 4), ("convolution", 19)])
def test_actual_tracknet_update_changes_only_granted_convolutions_and_preserves_bn(
    variant, count
):
    torch = pytest.importorskip("torch")
    from badminton.vendor.tracknet_model import TrackNet

    threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        torch.manual_seed(4)
        model = TrackNet(27, 8)
        names = study.configure_training(model, variant)
        assert names == study.trainable_names(variant) and len(names) == count
        assert all(not module.training for module in model.modules())
        before = study.tensor_hashes(model)
        optimizer = torch.optim.AdamW(
            [p for p in model.parameters() if p.requires_grad],
            lr=1e-4,
            weight_decay=1e-4,
        )
        output = model(torch.rand(1, 27, 16, 16))
        loss = study.balanced_loss(output, torch.zeros_like(output))
        loss.backward()
        assert all(
            p.grad is None for name, p in model.named_parameters() if name not in names
        )
        optimizer.step()
        after = study.tensor_hashes(model)
        changed = {name for name in before if before[name] != after[name]}
        assert changed == set(names)
    finally:
        torch.set_num_threads(threads)


@pytest.fixture
def selection(tmp_path):
    output = tmp_path / "research"
    output.mkdir()
    study.publish(output / "protocol.json", PROTOCOL)
    protocol_sha = study.audit.file_hash(output / "protocol.json")
    study.publish(output / "experiment.json", {"protocol_sha256": protocol_sha})
    experiment_sha = study.audit.file_hash(output / "experiment.json")
    for variant in study.VARIANTS:
        method = output / variant
        method.mkdir()
        epochs = []
        for epoch in range(1, 5):
            path = method / f"epoch-{epoch}.pt"
            path.write_bytes(f"generated-{variant}-{epoch}".encode())
            epochs.append(
                {
                    "epoch": epoch,
                    "validation_loss": 0.1 if epoch == 2 else 0.3,
                    "checkpoint": study.audit.seal(method, path),
                    "validation_groups": {str(i): "a" * 64 for i in range(16)},
                }
            )
        common = {
            "study": study.STUDY,
            "variant": variant,
            "parent_sha256": PARENT_SHA256,
            "protocol_sha256": protocol_sha,
            "experiment_sha256": experiment_sha,
        }
        study.publish(
            method / "training.json",
            {
                **common,
                "epochs": epochs,
                "frozen_unchanged": True,
                "trainable_names": study.trainable_names(variant),
                "selection_input": "synthetic validation only",
                "train_groups": {str(i): "b" * 64 for i in range(128)},
            },
        )
        study.publish(
            method / "selection.json",
            {
                **common,
                "epoch": 2,
                "checkpoint": epochs[1]["checkpoint"],
                "training": study.audit.seal(method, method / "training.json"),
            },
        )
    return output, study.selected(output, "decoder")


def test_override_requires_bound_parent_training_protocol_and_selected_model(selection):
    output, value = selection
    path, checksum, provenance = study.checkpoint_override(value)
    assert path == output / "decoder/epoch-2.pt"
    assert checksum == study.audit.file_hash(path)
    assert provenance["parent_sha256"] == PARENT_SHA256 and provenance["epoch"] == 2
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Changed sealed input"):
        study.checkpoint_override(value)


@pytest.mark.parametrize("name", ["selection.json", "training.json", "protocol.json"])
def test_provenance_tamper_cannot_reach_native_reader(selection, monkeypatch, name):
    output, value = selection
    (output / (name if name == "protocol.json" else "decoder/" + name)).write_bytes(
        b"{}"
    )
    monkeypatch.setattr(
        shuttle,
        "timestamps_for",
        lambda *a: pytest.fail("native metadata must not open"),
    )
    with pytest.raises(ValueError):
        shuttle.track_shuttle(
            {},
            Path(),
            Path(),
            0,
            1,
            lambda _: None,
            output / "run.json",
            spatial_layout="full",
            research_checkpoint=value,
        )
    assert not (output / "run.json").exists()


def test_invalid_research_geometry_and_unbound_override_fail_before_media(monkeypatch):
    monkeypatch.setattr(
        shuttle,
        "timestamps_for",
        lambda *a: pytest.fail("native metadata must not open"),
    )
    for value, layout in (({}, "full"), ({}, None), ({"sha256": "a" * 64}, "full")):
        with pytest.raises(ValueError, match="Research"):
            shuttle.track_shuttle(
                {},
                Path(),
                Path(),
                0,
                1,
                lambda _: None,
                Path("unused"),
                research_checkpoint=value,
                spatial_layout=layout,
            )


def test_test_opening_requires_selection_and_cannot_reopen(selection, monkeypatch):
    output, value = selection
    study.publish(output / "synthetic-test-opened.json", {"original": True})
    monkeypatch.setattr(
        study, "admission", lambda *a: pytest.fail("no shared admission on reopen")
    )
    with pytest.raises(ValueError, match="already opened"):
        study.synthetic_test(output, output, "a" * 64)
    assert study.selected(output, "decoder") == value


def test_training_failure_marker_prevents_silent_new_initialization(
    tmp_path, monkeypatch
):
    (tmp_path / "decoder").mkdir()
    study.publish(tmp_path / "decoder/training-opened.json", {"original": True})
    monkeypatch.setattr(
        study, "admission", lambda *a: pytest.fail("no shared admission on repeat")
    )
    with pytest.raises(ValueError, match="preserve prior attempt"):
        study.train(tmp_path, tmp_path, "a" * 64, "decoder")


def test_exclusive_receipts_never_overwrite_prior_evidence(tmp_path):
    path = tmp_path / "receipt.json"
    study.publish(path, {"original": True})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        study.publish(path, {"original": False})
    assert path.read_bytes() == before


def test_wrong_localization_counts_both_fp_fn_and_keeps_all_negative_frames():
    groups = [{"labels": [], "rows": []}]
    for frame in range(24):
        visible = frame < 3
        point = {
            "visible": frame < 2,
            "x": 100 if frame == 1 else 20,
            "y": 20,
            "component_candidates": [{"x": 20, "y": 20}],
        }
        groups[0]["labels"].append(
            {
                "frame": frame,
                "visible": visible,
                "x": 20 if visible else None,
                "y": 20 if visible else None,
            }
        )
        groups[0]["rows"].append({"frame": frame, "shuttle": point})
    result = study.synthetic_metrics(groups)
    assert (
        result["frames"] == 24 and result["visible"] == 3 and result["negative"] == 21
    )
    assert (
        result["localization_tp"],
        result["localization_fp"],
        result["localization_fn"],
        result["localization_tn"],
    ) == (1, 1, 2, 21)
    assert result["displaced"] == 1 and result["component_agrees"] == 3


def test_report_cannot_open_familiar_labels_before_exact_external_raw_seal(
    tmp_path, monkeypatch
):
    study.publish(
        tmp_path / "raw-public-seal.json", {"comment": "", "raw_index_sha256": "x"}
    )
    monkeypatch.setattr(
        study, "diagnostic_inputs", lambda *a: pytest.fail("no label scoring")
    )
    with pytest.raises(ValueError, match="timestamped raw seal"):
        study.report(tmp_path, tmp_path, "a" * 64, "b" * 64)


def test_control_mismatch_blocks_candidate_before_shared_admission(
    tmp_path, monkeypatch
):
    study.publish(tmp_path / "synthetic-test.json", {})
    monkeypatch.setattr(study, "selected", lambda *a: {})
    monkeypatch.setattr(study, "validate_test", lambda *a: {})
    monkeypatch.setattr(study, "load", lambda *a: {})
    monkeypatch.setattr(study, "diagnostic_inputs", lambda *a: ())
    monkeypatch.setattr(study, "control_gate", lambda *a: {"compatible": False})
    monkeypatch.setattr(
        study, "admission", lambda *a: pytest.fail("candidate must not launch")
    )
    with pytest.raises(ValueError, match="mismatch blocks"):
        study.native_variant(tmp_path, tmp_path, "a" * 64, "convolution")


def test_research_override_runs_native_producer_with_bound_metadata(
    selection, monkeypatch
):
    torch = pytest.importorskip("torch")
    from badminton.vendor import tracknet_model

    output, value = selection

    class Model:
        def __init__(self, *args):
            pass

        def load_state_dict(self, state):
            pass

        def to(self, device):
            return self

        def eval(self):
            return self

        def __call__(self, tensor):
            assert tensor.shape == (1, 27, 288, 512)
            result = torch.zeros((1, 8, 288, 512))
            result[:, :, 50, 60] = 0.9
            return result

    monkeypatch.setattr(tracknet_model, "TrackNet", Model)
    monkeypatch.setattr(
        torch,
        "load",
        lambda *a, **kw: {
            "param_dict": {"seq_len": 8, "bg_mode": "concat"},
            "model": {},
        },
    )
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    times = [0.1, 0.135, 0.19]
    monkeypatch.setattr(shuttle, "timestamps_for", lambda *a: times)
    monkeypatch.setattr(shuttle, "validate_range", lambda *a: None)
    monkeypatch.setattr(
        shuttle,
        "scan_boundaries",
        lambda *a: {
            "cut_frames": [],
            "method": "generated",
            "camera_ranges": [{"start_frame": 0, "end_frame": 3}],
        },
    )

    def frames(video, root, ts, first, last):
        for i in range(first, last):
            pixels = np.full((36, 64, 3), i, dtype=np.uint8)
            yield (
                i,
                ts[i],
                SimpleNamespace(
                    to_image=lambda p=pixels: Image.fromarray(p),
                    to_ndarray=lambda format, p=pixels: p.copy(),
                ),
            )

    monkeypatch.setattr(shuttle, "iter_frames", frames)
    video = {"id": "generated", "sha256": "a" * 64, "width": 64, "height": 36}
    path = output / "run.json"
    result = shuttle.track_shuttle(
        video,
        output,
        output,
        0,
        3,
        lambda _: None,
        path,
        annotations={},
        spatial_layout="full",
        research_checkpoint=value,
    )
    run = study.audit.read_json(path.read_bytes())
    assert run["checkpoint_sha256"] == study.checkpoint_override(value)[1]
    assert result["research_adaptation"] == study.checkpoint_override(value)[2]
    assert [row["time_s"] for row in run["frames"]] == times
    assert [row["frame"] for row in run["frames"]] == [0, 1, 2]
    assert run["model_calls"] == 1 and run["repaired_frames"] == 0
    assert all(row["shuttle"]["visible"] for row in run["frames"])


def test_shared_admission_refuses_disposable_root_before_any_work(
    tmp_path, monkeypatch
):
    from badminton import jobs

    monkeypatch.setattr(study, "load", lambda *a: {"deadline": study.time.time() + 60})
    monkeypatch.setattr(
        jobs, "run_local_job", lambda *a: pytest.fail("must use original shared Store")
    )
    with pytest.raises(ValueError, match="real original root"):
        study.admission(
            tmp_path,
            tmp_path,
            "a" * 64,
            "train",
            lambda *a: pytest.fail("must not run"),
        )


def test_both_independent_selections_are_required_before_any_test_pixels(
    selection, monkeypatch
):
    output, _ = selection
    (output / "convolution/selection.json").unlink()
    monkeypatch.setattr(
        study, "generate_group", lambda *a: pytest.fail("no test pixels")
    )
    monkeypatch.setattr(study, "admission", lambda *a: pytest.fail("no native launch"))
    with pytest.raises(FileNotFoundError):
        study.synthetic_test(output, output, "a" * 64)


@pytest.mark.parametrize(
    "field,value",
    [
        ("study", "old"),
        ("variant", "other"),
        ("variant", "convolution"),
        ("selection_sha256", "a" * 64),
    ],
)
def test_override_cannot_substitute_method_or_study(selection, field, value):
    _, override = selection
    override[field] = value
    with pytest.raises(ValueError):
        study.checkpoint_override(override)


def test_changed_experiment_or_parent_protocol_cannot_reach_decoder(
    selection, monkeypatch
):
    output, override = selection
    (output / "experiment.json").write_bytes(b"{}")
    monkeypatch.setattr(shuttle, "timestamps_for", lambda *a: pytest.fail("no media"))
    with pytest.raises(ValueError):
        shuttle.track_shuttle(
            {},
            output,
            output,
            0,
            1,
            lambda _: None,
            output / "no.json",
            spatial_layout="full",
            research_checkpoint=override,
        )


def test_opened_test_fences_both_training_recipes(tmp_path, monkeypatch):
    study.publish(tmp_path / "synthetic-test-opened.json", {})
    monkeypatch.setattr(study, "admission", lambda *a: pytest.fail("no training"))
    for variant in study.VARIANTS:
        with pytest.raises(ValueError, match="already opened"):
            study.train(tmp_path, tmp_path, "a" * 64, variant)


def test_unknown_capacity_recipe_never_initializes_model():
    with pytest.raises(ValueError, match="Unknown frozen"):
        study.configure_training(None, "fallback")


def test_generated_test_uses_all_three_fixed_methods_and_identical_complete_inputs(
    selection, monkeypatch
):
    torch = pytest.importorskip("torch")
    output, _ = selection
    experiment_sha = study.audit.file_hash(output / "experiment.json")
    calls = []

    def generate(split, index):
        assert study.both_selected(output)
        assert (output / "synthetic-test-opened.json").is_file()
        calls.append((split, index))
        return (
            np.full((24, 2, 2, 3), index, dtype=np.uint8),
            np.zeros((2, 2, 3), dtype=np.uint8),
            [{"frame": i, "visible": False, "x": None, "y": None} for i in range(24)],
        )

    def infer(source, *args):
        return [
            {
                "frame": i,
                "shuttle": {
                    "visible": False,
                    "x": None,
                    "y": None,
                    "component_candidates": [],
                },
            }
            for i, _, _ in source
        ]

    monkeypatch.setattr(study, "generate_group", generate)
    monkeypatch.setattr(study, "model_from", lambda *a: object())
    monkeypatch.setattr(study, "predict_function", lambda *a: (None, [0]))
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)
    monkeypatch.setattr(shuttle, "infer_camera_segment", infer)
    monkeypatch.setattr(
        study, "admission", lambda r, o, e, s, f: f({}, o, lambda _: None)
    )
    study.synthetic_test(output, output, experiment_sha)
    assert calls == [("test", i) for i in range(16)] * 3
    value = study.validate_test(output, experiment_sha)
    assert set(value["results"]) == {"control", "decoder", "convolution"}
    assert all(v["metrics"]["negative"] == 384 for v in value["results"].values())
    path = output / "synthetic-test.json"
    value["results"]["decoder"]["groups"][0]["pixels_sha256"] = "c" * 64
    path.write_bytes(study.audit.encoded(value))
    with pytest.raises(ValueError, match="inputs differ"):
        study.validate_test(output, experiment_sha)


def test_admitted_generated_work_records_real_process_and_terminal_state(
    tmp_path, monkeypatch
):
    torch = pytest.importorskip("torch")
    import badminton.storage as storage
    from badminton import config, jobs

    shared = tmp_path / "data/processed"
    shared.mkdir(parents=True)
    (shared / "catalog.sqlite3").write_bytes(b"generated sentinel")
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", shared)
    monkeypatch.setattr(config, "WEIGHTS", tmp_path / "models/weights")
    monkeypatch.setattr(study, "load", lambda *a: {"deadline": study.time.time() + 60})
    monkeypatch.setattr(study.existing, "prior_attempt_proof", lambda *a: [])
    monkeypatch.setattr(storage, "Store", lambda path: path)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "reset_peak_memory_stats", lambda: None)
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda _: "generated")
    monkeypatch.setattr(
        torch.cuda, "get_device_properties", lambda _: SimpleNamespace(total_memory=1)
    )
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda: 0)
    admissions = []

    def admitted(store, kind, video, task):
        assert store == shared and kind == "feature-preparation" and video is None
        admissions.append("generated-job")
        return task("generated-job", lambda _: None)

    monkeypatch.setattr(jobs, "run_local_job", admitted)
    result = study.admission(
        tmp_path, output, "a" * 64, "generated", lambda e, a, p: {"ok": True}
    )
    attempt = output / result["attempt"]
    record = study.audit.read_json((attempt / "admission.json").read_bytes())
    assert admissions == ["generated-job"] and record["job_id"] == "generated-job"
    assert record["process"]["pid"] == study.psutil.Process().pid
    assert record["process"]["creation_time"] == study.psutil.Process().create_time()
    assert (
        study.audit.read_json((attempt / "terminal.json").read_bytes())["status"]
        == "completed"
    )


def test_report_opening_is_exclusive_before_label_access(tmp_path, monkeypatch):
    study.publish(tmp_path / "report-opened.json", {"original": True})
    monkeypatch.setattr(study, "diagnostic_inputs", lambda *a: pytest.fail("no labels"))
    with pytest.raises(ValueError, match="already opened"):
        study.report(tmp_path, tmp_path, "a" * 64, "b" * 64)
