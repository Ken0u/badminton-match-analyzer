"""The resolution experiment must preserve default pixels and source context."""

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from badminton import shuttle
from badminton import shuttle_resolution as experiment
from PIL import Image

pytest_plugins = ["test_shuttle_validation"]


def frame(index):
    pixels = np.zeros((36, 64, 3), dtype=np.uint8)
    pixels[:, :, 0] = np.arange(64)
    pixels[:, :, 1] = index * 20
    return SimpleNamespace(to_image=lambda: Image.fromarray(pixels))


@pytest.mark.parametrize(
    "size",
    [None, True, (True, 288), (512, 288.0), (513, 288), (768, 433), (1024, 576)],
)
def test_resolution_rejects_unfrozen_or_noninteger_variants(size):
    with pytest.raises(ValueError, match="512x288 or 768x432"):
        shuttle.validate_input_size(size)


def test_default_rgb_pixels_are_identical_and_variant_never_mutates_globals():
    source = frame(1)
    original = np.asarray(source.to_image().resize((512, 288)), dtype=np.uint8)
    np.testing.assert_array_equal(shuttle._rgb(source), original)
    larger = shuttle._rgb(source, shuttle.validate_input_size([768, 432]))
    assert larger.shape == (432, 768, 3)
    assert (shuttle.WIDTH, shuttle.HEIGHT) == (512, 288)
    np.testing.assert_array_equal(shuttle._rgb(source), original)


@pytest.mark.parametrize("size", [(512, 288), (768, 432)])
def test_resolution_ensemble_keeps_every_native_frame_pts_and_source_coordinates(size):
    timestamps = [0.0, 0.031, 0.073, 0.11, 0.162, 0.193]
    inputs = [(i, t, frame(i)) for i, t in enumerate(timestamps)]
    background = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    windows = []

    def predict(images):
        assert all(image.shape == background.shape for image in images)
        windows.append([int(image[0, 0, 1]) // 20 for image in images[1:]])
        heat = np.zeros((3, size[1], size[0]), dtype=np.float32)
        heat[:, size[1] // 2, size[0] // 2] = 0.9
        return heat

    rows = list(
        shuttle.infer_camera_segment(
            inputs, background, 3, predict, 1280, 720, input_size=size
        )
    )
    assert windows == [[0, 1, 2], [1, 2, 3], [2, 3, 4], [3, 4, 5]]
    assert [row["frame"] for row in rows] == list(range(6))
    assert [row["time_s"] for row in rows] == timestamps
    expected = (
        (size[0] / 2 + 0.5) * 1280 / size[0],
        (size[1] / 2 + 0.5) * 720 / size[1],
    )
    assert [(row["shuttle"]["x"], row["shuttle"]["y"]) for row in rows] == [
        expected
    ] * 6
    assert all(row["shuttle"]["repaired"] is False for row in rows)


def test_explicit_default_preserves_ensemble_and_scene_reset_exactly():
    inputs = [(i, i * 0.04, frame(i)) for i in range(7)]
    background = np.zeros((288, 512, 3), dtype=np.uint8)

    def predict(images):
        heat = np.zeros((4, 288, 512), dtype=np.float32)
        heat[:, 100, 100] = 0.9
        return heat

    kwargs = {"selection_reset_frames": [3]}
    before = list(
        shuttle.infer_camera_segment(
            inputs, background, 4, predict, 1280, 720, **kwargs
        )
    )
    after = list(
        shuttle.infer_camera_segment(
            inputs,
            background,
            4,
            predict,
            1280,
            720,
            input_size=(512, 288),
            **copy.deepcopy(kwargs),
        )
    )
    assert after == before


@pytest.fixture
def frozen(native, monkeypatch):
    from test_shuttle_validation import edit_native_shuttle

    n = native
    audit = experiment.audit

    # Actual track_shuttle publishes reviewed context flags; reproduce that
    # producer document shape in the generated native graph as well.
    def context_flags(run):
        for row in run["frames"]:
            row["shuttle"]["selection_context_excluded"] = False

    for plan in n["plans"]:
        edit_native_shuttle({**n, "plans": [plan]}, context_flags)
    baseline_root = n["root"] / ".cache/resolution-original-baseline"
    baseline = audit.freeze_baseline(
        n["root"],
        n["packet_root"],
        n["packet_sha"],
        n["label_root"],
        n["labels_sha"],
        n["locations"],
        baseline_root,
    )
    public = (
        Path(__file__).resolve().parents[1]
        / "data/manifests/shuttle_resolution_protocol_v1.json"
    )
    protocol = json.loads(public.read_bytes())
    protocol.update(
        inventory_sha256=audit.PROTOCOL["inventory_sha256"],
        packet_sha256=n["packet_sha"],
        labels_sha256=n["labels_sha"],
        baseline_sha256=baseline["baseline_sha256"],
        checkpoint_sha256=audit.file_hash(n["locations"]["weights"] / "shuttle.pt"),
    )
    protocol["metrics"]["case_count"] = 5
    protocol_path = n["root"] / "comparison.json"
    protocol_path.write_bytes(audit.encoded(protocol))
    consumer = n["root"] / "consumer.py"
    consumer.write_bytes(b"# Synthetic frozen consumer; never executed.\n")
    monkeypatch.setattr(
        experiment,
        "consumer_files",
        lambda root: {"consumer.py": audit.seal(root, consumer)},
    )
    monkeypatch.setattr(
        experiment, "runtime_snapshot", lambda: {"fixture": "no GPU or model execution"}
    )
    output = n["root"] / ".cache/resolution"
    result = experiment.freeze_experiment(
        n["root"],
        n["packet_root"],
        n["label_root"],
        baseline_root / "baseline.json",
        protocol_path,
        audit.file_hash(protocol_path),
        output,
    )
    return {
        **n,
        "output": output,
        "experiment_sha": result["experiment_sha256"],
        "consumer": consumer,
        "protocol": protocol_path,
        "baseline_path": baseline_root / "baseline.json",
    }


def test_frozen_experiment_keeps_complete_views_and_refuses_changed_code(frozen):
    n = frozen
    receipt, _protocol, _inputs = experiment.load_experiment(
        n["root"], n["output"], n["experiment_sha"]
    )
    assert len(receipt["views"]) == 2
    assert all(
        (view["start_frame"], view["end_frame"]) == (0, 4) for view in receipt["views"]
    )
    assert sum(len(view["case_ids"]) for view in receipt["views"]) == 5
    with pytest.raises(FileExistsError):
        experiment.freeze_experiment(
            n["root"],
            n["packet_root"],
            n["label_root"],
            n["baseline_path"],
            n["protocol"],
            experiment.audit.file_hash(n["protocol"]),
            n["output"],
        )
    n["consumer"].write_bytes(b"changed")
    with pytest.raises(ValueError, match="code or runtime changed"):
        experiment.load_experiment(n["root"], n["output"], n["experiment_sha"])


def test_control_gate_rejects_geometry_or_missing_rows_but_only_tolerates_scores():
    expected = [
        {
            "frame": 8,
            "time_s": 0.37,
            "camera_segment_start_frame": 5,
            "shuttle": {
                "visible": True,
                "x": 20.0,
                "y": 30.0,
                "confidence": 0.9,
                "component_candidates": [{"id": 1, "confidence": 0.9}],
            },
        }
    ]
    changed = copy.deepcopy(expected)
    changed[0]["shuttle"]["confidence"] += 0.000001
    changed[0]["shuttle"]["component_candidates"][0]["confidence"] += 0.000001
    assert experiment.compare_rows(expected, changed, 0.00001) == []
    changed[0]["shuttle"]["x"] += 0.000001
    assert experiment.compare_rows(expected, changed, 0.00001) == ["0/shuttle/x"]
    assert experiment.compare_rows(expected, [], 0.00001) == ["/length"]
    changed = copy.deepcopy(expected)
    changed[0]["shuttle"]["component_candidates"][0]["confidence"] = float("nan")
    assert experiment.compare_rows(expected, changed, 0.00001) == [
        "0/shuttle/component_candidates/0/confidence"
    ]


def test_candidate_refuses_incomplete_control_before_gpu_or_store(frozen, monkeypatch):
    from badminton import config

    n = frozen
    shared = n["root"] / "data/processed"
    shared.mkdir()
    (shared / "catalog.sqlite3").touch()
    monkeypatch.setattr(config, "ROOT", n["root"])
    monkeypatch.setattr(config, "DATA", shared)
    monkeypatch.setattr(config, "WEIGHTS", n["root"] / "models/weights")
    with pytest.raises(ValueError, match="All original control views must finish"):
        experiment.run_variant(n["root"], n["output"], n["experiment_sha"], "candidate")
    assert not (n["output"] / "attempts").exists()


def test_real_shared_admission_blocks_competing_resolution_job(frozen, monkeypatch):
    from badminton import config
    from badminton.storage import ConflictError, Store

    n = frozen
    shared = n["root"] / "data/processed"
    store = Store(shared)
    store.claim_job(
        {
            "id": "other-live-job",
            "kind": "shuttle",
            "status": "running",
            "video_id": None,
        }
    )
    monkeypatch.setattr(config, "ROOT", n["root"])
    monkeypatch.setattr(config, "DATA", shared)
    monkeypatch.setattr(config, "WEIGHTS", n["root"] / "models/weights")
    with pytest.raises(ConflictError, match="Another processing job"):
        experiment.run_variant(n["root"], n["output"], n["experiment_sha"], "control")
    assert store.jobs()[0]["status"] == "running"
    assert not list((n["output"] / "attempts").glob("*/admission.json"))


def complete_generated_variant(n, variant):
    """Generated observations, not a model execution or independent truth."""
    audit = experiment.audit
    receipt, protocol, inputs = experiment.load_experiment(
        n["root"], n["output"], n["experiment_sha"]
    )
    runs = inputs[4]
    folder = n["output"] / variant
    folder.mkdir()
    for view in receipt["views"]:
        run = copy.deepcopy(runs[(view["video_id"], view["core_index"])])
        run.update(
            input_size=protocol["variants"][variant],
            device="cuda:0",
            precision="float16",
            seq_len=8,
            checkpoint_sha256=protocol["checkpoint_sha256"],
            elapsed_s=1.0,
            peak_gpu_memory_mb=1.0,
        )
        path = n["output"] / f"generated-{variant}-{view['id']}.json"
        path.write_bytes(audit.encoded(run))
        audit.publish(
            folder / (view["id"] + ".json"),
            {
                "experiment_sha256": n["experiment_sha"],
                "view": view,
                "run": audit.seal(n["output"], path),
            },
        )
    return receipt, protocol, inputs


def test_report_keeps_unknown_and_missing_candidate_denominators(frozen):
    n = frozen
    complete_generated_variant(n, "control")
    output = n["root"] / ".cache/partial-comparison-report"
    experiment.evaluate_experiment(n["root"], n["output"], n["experiment_sha"], output)
    report = json.loads((output / "report.json").read_bytes())
    assert report["comparison_status"] == "compatible"
    control = report["variants"]["control"]["groups"]["all"]["metrics"]
    candidate = report["variants"]["candidate"]["groups"]["all"]["metrics"]
    assert control["cases"] == candidate["cases"] == 5
    assert (
        control["truth_states"]["unknown"] == candidate["truth_states"]["unknown"] == 3
    )
    assert control["localization"]["tp"] == 1 and control["localization"]["fp"] == 1
    assert candidate["output_unavailable"] == 5
    assert candidate["localization"]["fn"] == 1 and candidate["localization"]["tn"] == 0
    assert (
        report["variants"]["candidate"]["groups"]["difficulty/occlusion"]["metrics"][
            "cases"
        ]
        == 0
    )


def test_control_mismatch_blocks_even_opening_candidate_predictions(frozen):
    n = frozen
    receipt, _, _ = complete_generated_variant(n, "control")
    view = receipt["views"][0]
    manifest_path = n["output"] / "control" / (view["id"] + ".json")
    manifest = json.loads(manifest_path.read_bytes())
    path = experiment.audit.inside(n["output"], manifest["run"]["path"])
    run = json.loads(path.read_bytes())
    run["frames"][0]["shuttle"]["x"] += 1
    run["frames"][0]["shuttle"]["component_candidates"][0]["x"] += 1
    path.write_bytes(experiment.audit.encoded(run))
    manifest["run"] = experiment.audit.seal(n["output"], path)
    manifest_path.write_bytes(experiment.audit.encoded(manifest))
    candidate = n["output"] / "candidate"
    candidate.mkdir()
    (candidate / (view["id"] + ".json")).write_bytes(b"MUST NOT OPEN BLOCKED CANDIDATE")
    output = n["root"] / ".cache/blocked-comparison-report"
    experiment.evaluate_experiment(n["root"], n["output"], n["experiment_sha"], output)
    report = json.loads((output / "report.json").read_bytes())
    assert report["comparison_status"] == "blocked_control_mismatch_or_unavailable"
    assert report["control_gate"]["compatible"] is False
    assert report["variants"]["candidate"]["groups"] is None
    assert report["variants"]["candidate"]["all_cases_retained"] == 5


def test_resealed_unknown_candidate_row_cannot_hide_wrong_native_clock(frozen):
    n = frozen
    complete_generated_variant(n, "control")
    receipt, _, _ = complete_generated_variant(n, "candidate")
    view = receipt["views"][0]
    manifest_path = n["output"] / "candidate" / (view["id"] + ".json")
    manifest = json.loads(manifest_path.read_bytes())
    path = experiment.audit.inside(n["output"], manifest["run"]["path"])
    run = json.loads(path.read_bytes())
    run["frames"][-1]["time_s"] += 0.001
    path.write_bytes(experiment.audit.encoded(run))
    manifest["run"] = experiment.audit.seal(n["output"], path)
    manifest_path.write_bytes(experiment.audit.encoded(manifest))
    with pytest.raises(ValueError, match="membership/PTS"):
        experiment.evaluate_experiment(
            n["root"],
            n["output"],
            n["experiment_sha"],
            n["root"] / ".cache/invalid-clock-report",
        )


@pytest.mark.parametrize("size", [(512, 288), (768, 432)])
def test_adapter_resizes_each_original_camera_median_and_reports_actual_size(
    tmp_path, monkeypatch, size
):
    audit = experiment.audit
    weights = tmp_path / "weights"
    weights.mkdir()
    checkpoint = weights / "TrackNet_best.pt"
    checkpoint.write_bytes(b"not a model; synthetic loader below")
    manifest = tmp_path / "models.json"
    manifest.write_bytes(
        audit.encoded({"shuttle": {"sha256": audit.file_hash(checkpoint)}})
    )
    monkeypatch.setattr(shuttle, "WEIGHTS", weights)
    monkeypatch.setattr(shuttle, "MODEL_MANIFEST", manifest)
    model = SimpleNamespace()
    model.load_state_dict = lambda state: None
    model.to = lambda device: model
    model.eval = lambda: model
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            load=lambda *args, **kwargs: {
                "param_dict": {"seq_len": 8, "bg_mode": "concat"},
                "model": {},
            },
            cuda=SimpleNamespace(is_available=lambda: False),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "badminton.vendor.tracknet_model",
        SimpleNamespace(TrackNet=lambda *args: model),
    )
    times = [0.0, 0.031, 0.085, 0.12]
    monkeypatch.setattr(shuttle, "timestamps_for", lambda *args: times)
    pixels = [
        np.full((36, 64, 3), level, dtype=np.uint8) for level in (0, 20, 200, 240)
    ]

    def frames(video, root, times, first, last):
        for index in range(first, last):
            yield (
                index,
                times[index],
                SimpleNamespace(to_ndarray=lambda format, index=index: pixels[index]),
            )

    monkeypatch.setattr(shuttle, "iter_frames", frames)
    backgrounds = []

    def infer(frames, background, length, predict, width, height, **kwargs):
        assert kwargs["input_size"] == size and background.shape == (
            size[1],
            size[0],
            3,
        )
        backgrounds.append(background.copy())
        for index, stamp, _ in frames:
            yield {
                "frame": index,
                "time_s": stamp,
                "shuttle": {
                    "visible": False,
                    "x": None,
                    "y": None,
                    "confidence": 0.0,
                    "selection_reason": "no_observed_component",
                    "repaired": False,
                },
            }

    monkeypatch.setattr(shuttle, "infer_camera_segment", infer)
    video = {
        "id": "source",
        "sha256": "1" * 64,
        "frame_count": 4,
        "width": 64,
        "height": 36,
        "duration_s": 0.16,
    }
    scan = {
        "stage": "segments",
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "start_frame": 0,
        "end_frame": 4,
        "cut_frames": [2],
        "boundaries": [],
        "method": "generated",
    }
    output = tmp_path / "output.json"
    result = shuttle.track_shuttle(
        video,
        tmp_path,
        tmp_path,
        0,
        4,
        lambda value: None,
        output,
        annotations={"revision": 0, "camera_corrections": [], "scene_ranges": []},
        camera_scan=scan,
        input_size=size,
    )
    assert result["input_size"] == list(size)
    assert result["processed_frames"] == 4
    assert len(backgrounds) == 2
    assert np.all(backgrounds[0] == 10) and np.all(backgrounds[1] == 220)
    rows = audit.read_json(output.read_bytes())["frames"]
    assert [row["time_s"] for row in rows] == times
    assert [row["camera_segment_start_frame"] for row in rows] == [0, 0, 2, 2]


def test_resume_checks_original_pid_lifetime_and_store_without_mutating_job(
    tmp_path, monkeypatch
):
    from badminton.storage import Store

    shared = tmp_path / "data/processed"
    store = Store(shared)
    job = store.claim_job(
        {
            "id": "original",
            "kind": "feature-preparation",
            "status": "running",
            "video_id": None,
        }
    )
    output = tmp_path / ".cache/experiment"
    attempt = output / "attempts/original"
    attempt.mkdir(parents=True)
    experiment.audit.publish(
        attempt / "admission.json",
        {
            "job_id": job["id"],
            "process": {
                "pid": job["owner_pid"],
                "creation_time": job["owner_started"],
                "cwd": str(tmp_path),
                "command": ["generated original attempt"],
            },
        },
    )
    with pytest.raises(ValueError, match="still alive"):
        experiment.prior_attempt_proof(output, shared)
    # A reused PID represents a different lifetime; it cannot resurrect the
    # original worker, and the read-only proof still never changes Store state.
    monkeypatch.setattr(
        experiment.psutil,
        "Process",
        lambda pid: SimpleNamespace(create_time=lambda: job["owner_started"] + 1),
    )
    proof = experiment.prior_attempt_proof(output, shared)
    assert proof[0]["original_lifetime_exited"] is True
    assert proof[0]["store_status"] == "running"
    assert store.jobs()[0]["status"] == "running"


def test_atomic_checkpoint_interruption_never_publishes_partial_or_overwrites(
    tmp_path, monkeypatch
):
    target = tmp_path / "checkpoint.json"
    original_open = Path.open
    publisher = experiment.publish

    class TornWrite:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def write(self, raw):
            self.handle.write(raw[:8])
            self.handle.flush()
            raise KeyboardInterrupt("Generated interruption during checkpoint write")

    def torn_open(path, mode="r", *args, **kwargs):
        handle = original_open(path, mode, *args, **kwargs)
        return TornWrite(handle) if mode == "xb" else handle

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", torn_open)
        with pytest.raises(KeyboardInterrupt):
            publisher(target, {"complete": True})
    assert not target.exists()
    publisher(target, {"complete": True})
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        publisher(target, {"complete": False})
    assert target.read_bytes() == original
