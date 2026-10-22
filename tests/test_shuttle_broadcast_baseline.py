"""Generated development-diagnostic regressions; never open research inputs."""

import copy
import json
import platform
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
from badminton import shuttle_broadcast_baseline as baseline
from badminton.shuttle_supervision import file_hash, publish_json


def native_clock(count=256, rotation=0):
    """A nonzero-origin VFR source clock with display orientation metadata."""
    pts = [27000 + index * 3000 + (index // 3) * 900 for index in range(count)]
    return {
        "frame_count": count,
        "frames": [
            {
                "frame": index,
                "pts": value,
                "time_base": "1/90000",
                "time_s": value / 90000,
                "source_size": [1280, 720],
                "display_size": [720, 1280] if rotation in (90, 270) else [1280, 720],
                "rotation": rotation,
            }
            for index, value in enumerate(pts)
        ],
        "source_size": [1280, 720],
        "display_size": [720, 1280] if rotation in (90, 270) else [1280, 720],
        "rotation": rotation,
        "time_base": "1/90000",
        "origin_s": pts[0] / 90000,
        "issues": [],
    }


def case(index=0, center=64, source="singles", visibility="visible_localizable"):
    localizable = visibility == "visible_localizable"
    return {
        "key": f"{source}/{index}",
        "source_id": source,
        "case_id": index,
        "center_frame": center,
        "visibility": visibility,
        "x": 100 if localizable else None,
        "y": 100 if localizable else None,
        "uncertainty_radius": 20 if localizable else None,
        "scene": "play_view",
        "difficulty": ["blur", "small_far"],
    }


def observation(frame=64, point=None, components=None, time_s=None):
    x, y = point if point is not None else (None, None)
    return {
        "frame": frame,
        "time_s": time_s
        if time_s is not None
        else native_clock()["frames"][frame]["time_s"]
        - native_clock()["frames"][0]["time_s"],
        "shuttle": {
            "visible": point is not None,
            "x": x,
            "y": y,
            "confidence": 0.9 if point is not None else 0.0,
            "repaired": False,
            "component_candidates": components
            if components is not None
            else ([{"id": 1, "x": x, "y": y, "confidence": 0.9}] if point else []),
            "selected_component_id": 1 if point else None,
        },
    }


def raw_prediction(window, spec, cut=None):
    from badminton.shuttle import localization_recipe

    start, end = window["start_frame"], window["end_frame"]
    ranges = [{"start_frame": start, "end_frame": end}]
    if cut is not None:
        ranges = [
            {"start_frame": start, "end_frame": cut},
            {"start_frame": cut, "end_frame": end},
        ]
    rows = []
    for native in window["frames"]:
        row = observation(
            native["frame"], time_s=native["time_s"] - window.get("origin_s", 0)
        )
        row["camera_segment_start_frame"] = (
            cut if cut is not None and native["frame"] >= cut else start
        )
        rows.append(row)
    return {
        "checkpoint_sha256": spec["checkpoint_sha256"],
        "input_size": [512, 288],
        "seq_len": 8,
        "precision": "float16",
        "device": "cuda:generated-stub",
        "start_frame": start,
        "end_frame": end,
        "processed_frames": len(rows),
        "repaired_frames": 0,
        "localization": localization_recipe(),
        "ensemble": "weighted overlapping windows",
        "camera_ranges": ranges,
        "cut_frames": [] if cut is None else [cut],
        "temporal_context_crosses_detected_cuts": False,
        "frames": rows,
    }


def attempt_proof(tmp_path, host=None, pid=4444, started=12.0, status="completed"):
    shared = tmp_path / "data/processed"
    shared.mkdir(parents=True)
    with sqlite3.connect(shared / "catalog.sqlite3") as connection:
        connection.execute("CREATE TABLE jobs (id TEXT, document TEXT)")
        connection.execute(
            "INSERT INTO jobs VALUES (?,?)",
            (
                "generated-job",
                json.dumps(
                    {"owner_pid": pid, "owner_started": started, "status": status}
                ),
            ),
        )
    output = tmp_path / ".cache/generated-output"
    admission = output / "attempts/first/admission.json"
    publish_json(
        admission,
        {
            "job_id": "generated-job",
            "host_id": host or platform.node(),
            "process": {
                "pid": pid,
                "creation_time": started,
                "cwd": str(tmp_path),
                "command": ["generated-cpu-stub"],
            },
        },
    )
    publish_json(admission.with_name("terminal.json"), {"generated": True})
    return output, admission


def test_fixed_128_windows_have_exact_8192_native_memberships():
    clocks = {
        name: native_clock(count=5000, rotation=90 if name == "doubles" else 0)
        for name in ("singles", "doubles")
    }
    windows = [
        baseline.window_memberships(case(index, index * 4999 // 63, name), clocks[name])
        for name in clocks
        for index in range(64)
    ]
    assert len(windows) == len({window["key"] for window in windows}) == 128
    assert sum(len(window["frames"]) for window in windows) == 8192
    for window in windows:
        center = window["center_frame"]
        assert window["start_frame"] == max(0, center - 32)
        assert window["end_frame"] == min(5000, center + 33)
        assert (
            window["frames"]
            == clocks[window["source_id"]]["frames"][
                max(0, center - 32) : min(5000, center + 33)
            ]
        )


@pytest.mark.parametrize(
    "center,start,end",
    [(0, 0, 33), (1, 0, 34), (32, 0, 65), (223, 191, 256), (255, 223, 256)],
)
def test_windows_clamp_half_open_native_endpoints_without_fps_reconstruction(
    center, start, end
):
    clock = native_clock(rotation=90)
    window = baseline.window_memberships(case(center=center), clock)
    assert (window["start_frame"], window["end_frame"]) == (start, end)
    assert [row["frame"] for row in window["frames"]] == list(range(start, end))
    assert window["frames"] == clock["frames"][start:end]
    assert (
        clock["frames"][3]["pts"] - clock["frames"][2]["pts"]
        != clock["frames"][2]["pts"] - clock["frames"][1]["pts"]
    )


@pytest.mark.parametrize("center", [-1, 256, True, 64.0])
def test_window_refuses_foreign_or_noninteger_center(center):
    with pytest.raises(ValueError):
        baseline.window_memberships(case(center=center), native_clock())


def test_fixed_disk_and_original_uncertainty_are_separate_inclusive_metrics():
    assessment = case()
    at_edge = baseline.score_case(assessment, observation(point=(103, 104)), (600, 800))
    assert at_edge["distance_pixels"] == 5
    assert at_edge["selected_within_fixed"] is True
    assert at_edge["outcome"] == "within"
    displaced = baseline.score_case(
        assessment, observation(point=(110, 100)), (600, 800)
    )
    assert displaced["outcome"] == "displaced"
    assert displaced["selected_within_fixed"] is False
    assert displaced["within_uncertainty"] is True


def test_observed_alternate_hit_does_not_replace_displaced_selected_component():
    candidates = [
        {"id": 1, "x": 300, "y": 100, "confidence": 0.9},
        {"id": 2, "x": 100, "y": 100, "confidence": 0.8},
    ]
    result = baseline.score_case(
        case(), observation(point=(300, 100), components=candidates), (600, 800)
    )
    assert result["outcome"] == "displaced"
    assert result["selected_within_fixed"] is False
    assert result["any_component_within_fixed"] is True
    assert result["component_count"] == 2
    assert result["distance_pixels"] == 200


def test_center_coordinate_metric_uses_display_orientation_geometry():
    assessment = {**case(), "x": 700, "y": 1200}
    result = baseline.score_case(
        assessment, observation(point=(700, 1200)), (720, 1280)
    )
    assert result["outcome"] == "within" and result["distance_pixels"] == 0


def test_foreign_center_row_cannot_score_as_a_case_hit():
    with pytest.raises(ValueError):
        baseline.score_case(
            case(center=64), observation(frame=63, point=(100, 100)), (600, 800)
        )


def test_missing_observation_and_unavailable_output_are_distinct():
    missing = baseline.score_case(case(), observation(), (600, 800))
    unavailable = baseline.score_case(case(), None, (600, 800))
    assert missing["available"] is True and missing["outcome"] == "missing"
    assert unavailable["available"] is False and unavailable["outcome"] == "unavailable"
    assert missing["distance_pixels"] is unavailable["distance_pixels"] is None


def test_complete_128_case_denominators_retain_every_unknown_and_unavailable_case():
    parts = []
    for index in range(37):
        prediction = (
            observation(point=(100, 100))
            if index == 0
            else observation()
            if index < 36
            else None
        )
        parts.append(baseline.score_case(case(index=index), prediction, (600, 800)))
    for index in range(5):
        prediction = (
            None
            if index == 4
            else observation(point=(100, 100))
            if index == 0
            else observation()
        )
        parts.append(
            baseline.score_case(
                case(index=index + 37, visibility="not_visible"), prediction, (600, 800)
            )
        )
    parts.append(
        baseline.score_case(
            case(index=42, visibility="visible_unlocalizable"),
            observation(point=(100, 100)),
            (600, 800),
        )
    )
    parts.extend(
        baseline.score_case(
            case(index=index + 43, visibility="unknown"),
            None if index % 2 else observation(point=(100, 100)),
            (600, 800),
        )
        for index in range(85)
    )
    result = baseline.summarize(parts)
    assert result["cases"] == 128
    assert result["visibility_support"] == {
        "visible_localizable": 37,
        "visible_unlocalizable": 1,
        "not_visible": 5,
        "unknown": 85,
    }
    assert (
        result["localizable_denominator"] == 37 and result["negative_denominator"] == 5
    )
    assert result["localizable_outcomes"] == {
        "within": 1,
        "missing": 35,
        "unavailable": 1,
    }
    assert result["negative_outcomes"] == {
        "false_observation": 1,
        "absence": 3,
        "unavailable": 1,
    }
    assert result["strict_fixed_agreement"] == 1 / 37
    assert result["available"] == 84
    assert sum(result["outcomes"].values()) == 128


def test_undefined_support_is_undefined_not_perfect_agreement():
    result = baseline.summarize(
        [baseline.score_case(case(visibility="unknown"), observation(), (600, 800))]
    )
    assert (
        result["localizable_denominator"] == 0
        and result["strict_fixed_agreement"] is None
    )
    assert result["negative_denominator"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "nominal_fps",
        "duplicate",
        "reordered",
        "cross_cut",
        "selection_context",
        "foreign_component",
        "threshold",
        "incomplete",
    ],
)
def test_native_prediction_binds_vfr_pts_cut_context_and_unchanged_recipe(mutation):
    clock = native_clock(rotation=90)
    window = {
        **baseline.window_memberships(case(), clock),
        "origin_s": clock["origin_s"],
    }
    spec = baseline.load_protocol()
    raw = raw_prediction(window, spec, cut=64)
    if mutation == "nominal_fps":
        raw["frames"][3]["time_s"] = raw["frames"][0]["time_s"] + 3 / 30
    elif mutation == "duplicate":
        raw["frames"][1]["frame"] = raw["frames"][0]["frame"]
    elif mutation == "reordered":
        raw["frames"][0:2] = reversed(raw["frames"][0:2])
    elif mutation == "cross_cut":
        raw["temporal_context_crosses_detected_cuts"] = True
    elif mutation == "selection_context":
        raw["frames"][32]["shuttle"]["selection_context_start_frame"] = 63
    elif mutation == "foreign_component":
        raw["frames"][0]["shuttle"] = observation(point=(100, 100))["shuttle"]
        raw["frames"][0]["shuttle"]["selected_component_id"] = 99
    elif mutation == "threshold":
        raw["localization"]["heatmap_threshold"] = 0.4
    elif mutation == "incomplete":
        raw["frames"].pop()
    if mutation:
        with pytest.raises(ValueError):
            baseline.validate_prediction(raw, window, spec)
    else:
        assert baseline.validate_prediction(raw, window, spec) == raw


@pytest.mark.parametrize("visibility", ["unknown", "visible_unlocalizable"])
@pytest.mark.parametrize(
    "prediction", [None, observation(), observation(point=(100, 100))]
)
def test_unknown_and_unlocalizable_never_become_negative_or_coordinate_truth(
    visibility, prediction
):
    result = baseline.score_case(case(visibility=visibility), prediction, (600, 800))
    assert result["outcome"] == ("unavailable" if prediction is None else "unscored")
    assert result["distance_pixels"] is None
    assert result["selected_within_fixed"] is None
    assert result["within_uncertainty"] is None


@pytest.mark.parametrize("scene", ["play_view", "non_play", "replay", "unknown"])
def test_only_supported_negative_labels_supply_absence_truth(scene):
    assessment = {**case(visibility="not_visible"), "scene": scene}
    assert (
        baseline.score_case(assessment, observation(), (600, 800))["outcome"]
        == "absence"
    )
    assert (
        baseline.score_case(assessment, observation(point=(100, 100)), (600, 800))[
            "outcome"
        ]
        == "false_observation"
    )
    assert baseline.score_case(assessment, None, (600, 800))["outcome"] == "unavailable"
    unknown = {**assessment, "visibility": "unknown"}
    assert (
        baseline.score_case(unknown, observation(), (600, 800))["outcome"] == "unscored"
    )


def test_foreign_host_recovery_refuses_without_original_host_lifetime_proof(tmp_path):
    output, _admission = attempt_proof(tmp_path, host="not-this-host")
    with pytest.raises(ValueError, match="original-host"):
        baseline.prior_proofs(tmp_path, output)


def test_store_completed_does_not_establish_that_original_process_exited(tmp_path):
    process = psutil.Process()
    output, _admission = attempt_proof(
        tmp_path, pid=process.pid, started=process.create_time()
    )
    with pytest.raises(ValueError, match="still alive"):
        baseline.prior_proofs(tmp_path, output)


@pytest.mark.parametrize("status", ["completed", "running"])
def test_reused_pid_requires_matching_original_store_terminal_status(
    tmp_path, monkeypatch, status
):
    output, _admission = attempt_proof(tmp_path, status=status)

    class ReusedPid:
        def create_time(self):
            return 13.0

    monkeypatch.setattr(psutil, "Process", lambda _pid: ReusedPid())
    if status == "completed":
        assert (
            baseline.prior_proofs(tmp_path, output)[0]["original_lifetime_exited"]
            is True
        )
    else:
        with pytest.raises(ValueError, match="not terminal"):
            baseline.prior_proofs(tmp_path, output)


def test_isolated_store_is_not_accepted_as_shared_admission(tmp_path, monkeypatch):
    from badminton import config

    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", tmp_path / ".cache/isolated-store")
    monkeypatch.setattr(config, "WEIGHTS", tmp_path / "models/weights")
    with pytest.raises(ValueError, match="real shared Store"):
        baseline._require_store(tmp_path)


def test_recursive_consumers_include_native_vendor_configuration_and_entrypoint():
    consumers = baseline._consumers()
    assert {
        "backend/badminton/shuttle.py",
        "backend/badminton/vendor/tracknet_model.py",
        "backend/badminton/video.py",
        "backend/badminton/av_runtime.py",
        "backend/badminton/config.py",
        "backend/badminton/jobs.py",
        "scripts/diagnose_shuttle_broadcasts.py",
        "pyproject.toml",
        "uv.lock",
    } <= consumers.keys()


def test_truth_snapshot_does_not_read_unrelated_annotations_or_prediction_files(
    tmp_path, monkeypatch
):
    from badminton.storage import Store

    store = Store(tmp_path / "data/processed")
    with store.connect() as connection:
        for index, checksum in enumerate(("a" * 64, "b" * 64, "c" * 64)):
            connection.execute(
                "INSERT INTO videos VALUES (?,?)",
                (
                    f"video-{index}",
                    json.dumps({"id": f"video-{index}", "sha256": checksum}),
                ),
            )
            connection.execute(
                "INSERT INTO annotations(video_id,revision,document) VALUES (?,0,?)",
                (f"video-{index}", f"generated-{index}"),
            )
    unrelated = store.data / "video-2/poisoned-private-predictions.json"
    unrelated.parent.mkdir()
    unrelated.write_bytes(b"must never be opened\n")
    matching = store.data / "video-0/predictions.json"
    matching.parent.mkdir()
    matching.write_bytes(b"matching original prediction\n")
    real_hash = baseline.file_hash

    def scoped_hash(path):
        if Path(path) == unrelated:
            pytest.fail("Source diagnostic opened an unrelated research artifact")
        return real_hash(path)

    monkeypatch.setattr(baseline, "file_hash", scoped_hash)
    before = baseline._truth_seals(tmp_path, ["a" * 64, "b" * 64])
    assert set(before["processed_files"]) == {"video-0/predictions.json"}
    with store.connect() as connection:
        connection.execute(
            "UPDATE annotations SET document='changed poison' WHERE video_id='video-2'"
        )
    unrelated.write_bytes(b"changed, still must not be opened\n")
    assert baseline._truth_seals(tmp_path, ["a" * 64, "b" * 64]) == before
    matching.write_bytes(b"changed matching prediction\n")
    assert baseline._truth_seals(tmp_path, ["a" * 64, "b" * 64]) != before


def test_native_accounting_preserves_frame_identity_model_result_and_patch_lifetimes(
    monkeypatch,
):
    from badminton import segments, shuttle, video

    class Frame:
        def __init__(self, ordinal):
            self.ordinal = ordinal
            self.pts = (27000, 30000, 34200)[ordinal]
            self.time_base = "1/90000"

        def to_ndarray(self, **_kwargs):
            return ("original-array", self.pts)

    class Model:
        def forward(self, tensor):
            return ("original-model-result", tensor)

    class Container:
        def decode(self, *_args, **_kwargs):
            yield from (Frame(index) for index in range(3))

    @contextmanager
    def open_media(*_args, **_kwargs):
        yield Container()

    def iter_frames(*_args, **_kwargs):
        with video.open_media("generated") as container:
            for frame in container.decode():
                yield frame.ordinal, frame.pts / 90000, frame

    def infer(*_args, **_kwargs):
        yield from shuttle.iter_frames("generated")

    monkeypatch.setitem(
        sys.modules, "badminton.vendor.tracknet_model", SimpleNamespace(TrackNet=Model)
    )
    monkeypatch.setattr(video, "open_media", open_media)
    monkeypatch.setattr(segments, "iter_frames", iter_frames)
    monkeypatch.setattr(shuttle, "iter_frames", iter_frames)
    monkeypatch.setattr(shuttle, "infer_camera_segment", infer)
    tensor = SimpleNamespace(shape=(1, 27, 288, 512))
    original_forward = Model.forward
    expected = [(0, 0.3, 27000), (1, 1 / 3, 30000), (2, 0.38, 34200)]
    with baseline.native_accounting() as accounting:
        scan = [
            (index, stamp, frame.pts)
            for index, stamp, frame in segments.iter_frames("generated")
        ]
        samples = []
        background = []
        for index, stamp, frame in shuttle.iter_frames("generated"):
            background.append((index, stamp, frame.pts))
            if index != 1:
                samples.append(frame.to_ndarray(format="rgb24"))
        inference = [
            (index, stamp, frame.pts)
            for index, stamp, frame in shuttle.infer_camera_segment("generated")
        ]
        assert Model().forward(tensor) == ("original-model-result", tensor)
    assert scan == background == inference == expected
    assert samples == [("original-array", 27000), ("original-array", 34200)]
    assert accounting["camera_scan_yields"] == 3
    assert accounting["background_reader_yields"] == 3
    assert accounting["median_background_samples"] == 2
    assert accounting["inference_reader_yields"] == 3
    assert accounting["decoder_frames_total"] == 9
    assert accounting["model_calls"] == 1
    assert accounting["model_sequence_slots"] == 8
    assert accounting["model_background_slots"] == 1
    assert video.open_media is open_media
    assert segments.iter_frames is iter_frames
    assert shuttle.iter_frames is iter_frames
    assert shuttle.infer_camera_segment is infer
    assert Model.forward is original_forward
    with pytest.raises(RuntimeError, match="generated interruption"):
        with baseline.native_accounting():
            raise RuntimeError("generated interruption")
    assert video.open_media is open_media and shuttle.iter_frames is iter_frames
    assert Model.forward is original_forward


def prepared_fixture(tmp_path, monkeypatch, count=2):
    from badminton.storage import Store

    root = tmp_path.resolve()
    shared = root / "data/processed"
    store = Store(shared)
    monkeypatch.setattr(baseline, "_require_store", lambda _root: shared)
    consumer = root / "generated-consumer.py"
    consumer.write_text("frozen = True\n", encoding="utf-8")
    monkeypatch.setattr(
        baseline, "_consumers", lambda: {"generated-consumer.py": consumer}
    )
    monkeypatch.setattr(baseline, "_runtime", lambda: {"generated": True})
    monkeypatch.setattr(
        baseline, "_git_state", lambda: {"commit": "generated", "tracked_changes": ""}
    )
    monkeypatch.setattr(
        baseline, "_truth_seals", lambda _root, _hashes: {"generated_truth": True}
    )
    weights = root / "models/weights/TrackNet_best.pt"
    weights.parent.mkdir(parents=True)
    weights.write_bytes(b"generated checkpoint, no model\n")
    spec = copy.deepcopy(baseline.load_protocol())
    monkeypatch.setattr(baseline, "CHECKPOINT", file_hash(weights))
    spec["checkpoint_sha256"] = file_hash(weights)
    monkeypatch.setattr(
        baseline, "load_protocol", lambda _path=baseline.PROTOCOL: copy.deepcopy(spec)
    )
    clock = native_clock()
    cases = [case(index=index, center=64 + index * 65) for index in range(count)]
    windows = [
        {**baseline.window_memberships(value, clock), "origin_s": clock["origin_s"]}
        for value in cases
    ]
    source = {
        "clock": clock,
        "metadata": {"fps": 30, "duration": 10},
        "declaration": {"source_sha256": "a" * 64},
        "source_path": str(root / "generated.mp4"),
    }
    monkeypatch.setattr(
        baseline,
        "_source_inputs",
        lambda *_args: (
            {"singles": source},
            copy.deepcopy(windows),
            copy.deepcopy(cases),
        ),
    )
    packet, assessments = root / ".cache/packet", root / ".cache/assessments"
    output = root / ".cache/output"
    prepared = baseline.prepare(root, packet, assessments, output)
    return root, output, prepared["context"]["sha256"], consumer, store, spec


@pytest.mark.parametrize(
    "mutation", ["consumer", "projection", "checkpoint", "context", "occupied"]
)
def test_prepared_context_refuses_changed_sealed_inputs_or_occupied_output(
    tmp_path, monkeypatch, mutation
):
    root, output, context_sha, consumer, _store, _spec = prepared_fixture(
        tmp_path, monkeypatch
    )
    if mutation == "consumer":
        consumer.write_text("changed = True\n", encoding="utf-8")
    elif mutation == "projection":
        (output / "clock-data/singles/timestamps.json").write_bytes(b"[]\n")
    elif mutation == "checkpoint":
        (root / "models/weights/TrackNet_best.pt").write_bytes(b"changed weights\n")
    elif mutation == "context":
        (output / "context.json").write_bytes(b"{}\n")
    if mutation == "occupied":
        original = (output / "context.json").read_bytes()
        with pytest.raises(ValueError, match="already exists"):
            baseline.prepare(
                root, root / ".cache/packet", root / ".cache/assessments", output
            )
        assert (output / "context.json").read_bytes() == original
    else:
        with pytest.raises(ValueError):
            baseline._verify_context(root, output, context_sha, baseline.PROTOCOL)


def fake_native_fixture(tmp_path, monkeypatch):
    from badminton import shuttle

    root, output, context_sha, consumer, store, spec = prepared_fixture(
        tmp_path, monkeypatch
    )
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)),
    )
    monkeypatch.setitem(sys.modules, "torchvision", SimpleNamespace())

    @contextmanager
    def generated_accounting():
        yield {"generated_model_calls": 1}

    monkeypatch.setattr(baseline, "native_accounting", generated_accounting)
    monkeypatch.setattr(
        baseline,
        "_native_video",
        lambda *_args: {"id": "generated", "sha256": "a" * 64},
    )
    calls = []

    def track(_video, _root, _data, start, end, progress, path, **_kwargs):
        calls.append((start, end))
        clock = native_clock()
        window = {
            "start_frame": start,
            "end_frame": end,
            "frames": clock["frames"][start:end],
            "origin_s": clock["origin_s"],
        }
        raw = raw_prediction(window, spec)
        raw["video_sha256"] = "a" * 64
        publish_json(path, raw)
        progress(1)

    monkeypatch.setattr(shuttle, "track_shuttle", track)
    return root, output, context_sha, consumer, store, calls


def test_actual_store_admission_refuses_competing_generated_worker(
    tmp_path, monkeypatch
):
    from badminton.storage import ConflictError

    root, output, context_sha, _consumer, store, calls = fake_native_fixture(
        tmp_path, monkeypatch
    )
    store.claim_job(
        {
            "id": "occupied",
            "kind": "generated-no-gpu",
            "video_id": None,
            "status": "running",
        }
    )
    with pytest.raises(ConflictError, match="Another processing job is running"):
        baseline.run(root, output, context_sha)
    assert calls == []
    terminal = baseline.read_json(next((output / "attempts").glob("*/terminal.json")))
    assert terminal["status"] == "failed"
    assert len(terminal["case_availability"]) == 2
    assert all(value["complete"] is None for value in terminal["case_availability"])


def test_successful_generated_native_windows_seal_and_resume_without_reinference(
    tmp_path, monkeypatch
):
    root, output, context_sha, _consumer, _store, calls = fake_native_fixture(
        tmp_path, monkeypatch
    )
    result = baseline.run(root, output, context_sha)
    assert result["completed_windows"] == 2 and result["scored"] is False
    assert len(calls) == 2
    first = next((output / "attempts").glob("*/terminal.json"))
    with pytest.raises(ValueError, match="still alive"):
        baseline.prior_proofs(root, output)
    # Same-process generated stub only: actual lifetime checks are tested above.
    monkeypatch.setattr(
        baseline, "prior_proofs", lambda *_args: [{"generated_stub": True}]
    )
    result = baseline.run(
        root, output, context_sha, resume_receipt=first, resume_sha256=file_hash(first)
    )
    assert result["completed_windows"] == 2 and len(calls) == 2


def test_interrupted_generated_native_attempt_keeps_all_planned_cases_and_reuses_success(
    tmp_path, monkeypatch
):
    from badminton import shuttle

    root, output, context_sha, _consumer, store, calls = fake_native_fixture(
        tmp_path, monkeypatch
    )
    original_track = shuttle.track_shuttle

    def interrupted(*args, **kwargs):
        if len(calls) == 1:
            raise KeyboardInterrupt
        return original_track(*args, **kwargs)

    monkeypatch.setattr(shuttle, "track_shuttle", interrupted)
    with pytest.raises(KeyboardInterrupt):
        baseline.run(root, output, context_sha)
    first = next((output / "attempts").glob("*/terminal.json"))
    receipt = baseline.read_json(first)
    assert receipt["status"] == "interrupted"
    assert len(receipt["completed_clips"]) == len(calls) == 1
    assert len(receipt["case_availability"]) == 2
    interrupted_record = baseline.read_json(
        baseline._verified(output, receipt["case_availability"][1]["complete"])
    )
    assert interrupted_record["raw_prediction"] is None
    assert interrupted_record["unavailable_reason"] == "native_interrupted"
    with store.connect() as connection:
        assert (
            json.loads(connection.execute("SELECT document FROM jobs").fetchone()[0])[
                "status"
            ]
            == "interrupted"
        )
    retained = {path: file_hash(path) for path in output.rglob("raw-prediction.json")}
    monkeypatch.setattr(shuttle, "track_shuttle", original_track)
    monkeypatch.setattr(
        baseline, "prior_proofs", lambda *_args: [{"generated_stub": True}]
    )
    result = baseline.run(
        root, output, context_sha, resume_receipt=first, resume_sha256=file_hash(first)
    )
    assert result["completed_windows"] == 2 and len(calls) == 2
    assert all(file_hash(path) == checksum for path, checksum in retained.items())


def test_native_refusal_keeps_unavailable_case_without_claiming_absence(
    tmp_path, monkeypatch
):
    from badminton import shuttle

    root, output, context_sha, _consumer, _store, calls = fake_native_fixture(
        tmp_path, monkeypatch
    )
    original_track = shuttle.track_shuttle

    def refused(*args, **kwargs):
        if len(calls) == 1:
            raise RuntimeError("generated decoder refusal")
        return original_track(*args, **kwargs)

    monkeypatch.setattr(shuttle, "track_shuttle", refused)
    baseline.run(root, output, context_sha)
    terminal = baseline.read_json(next((output / "attempts").glob("*/terminal.json")))
    assert terminal["status"] == "completed" and len(terminal["case_availability"]) == 2
    assert len(terminal["completed_clips"]) == len(calls) == 1
    record = baseline.read_json(
        baseline._verified(output, terminal["case_availability"][1]["complete"])
    )
    assert record["raw_prediction"] is None
    assert record["unavailable_reason"] == "native_refusal:RuntimeError"


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("corrupt", "corrupt_or_unsupported_orientation"),
        ("pts", "inconsistent_native_pts"),
        ("orientation", "changing_native_geometry"),
    ],
)
def test_bad_native_clock_or_geometry_is_unavailable_without_relabeling(
    mutation, reason
):
    clock = native_clock()
    window = copy.deepcopy(baseline.window_memberships(case(), clock))
    assert baseline.window_unavailable(window) is None
    if mutation == "corrupt":
        window["frames"][4]["corrupt"] = True
    elif mutation == "pts":
        window["frames"][4]["pts"] += 1
    else:
        window["frames"][4]["rotation"] = 90
    assert baseline.window_unavailable(window) == reason


@pytest.mark.parametrize(
    "change", [None, "changed_window", "changed_context", "unsealed_attempt"]
)
def test_partial_resume_requires_sealed_unchanged_complete_history(tmp_path, change):
    complete = tmp_path / "windows/one.json"
    publish_json(complete, {"clip": "singles/1", "context_sha256": "frozen-context"})
    first = tmp_path / "attempts/first/terminal.json"
    seal = {
        "path": complete.relative_to(tmp_path).as_posix(),
        "sha256": file_hash(complete),
    }
    publish_json(
        first,
        {
            "context_sha256": "frozen-context",
            "completed_clips": [seal],
            "prior_terminal_seals": [],
            "elapsed_s": 2.5,
        },
    )
    first_sha = file_hash(first)
    if change == "changed_window":
        publish_json(tmp_path / "changed.json", {"generated": True})
        complete.write_bytes(b"changed\n")
    elif change == "unsealed_attempt":
        publish_json(tmp_path / "attempts/another/terminal.json", {"elapsed_s": 10})
    context_sha = "changed-context" if change == "changed_context" else "frozen-context"
    if change:
        with pytest.raises(ValueError):
            baseline.resume_plan(tmp_path, first, first_sha, context_sha)
    else:
        reusable, history, elapsed = baseline.resume_plan(
            tmp_path, first, first_sha, context_sha
        )
        assert list(reusable) == ["singles/1"]
        assert history == [
            {"path": "attempts/first/terminal.json", "sha256": first_sha}
        ]
        assert elapsed == 2.5
        with pytest.raises(ValueError, match="externally sealed"):
            baseline.resume_plan(tmp_path, None, None, context_sha)


def test_fixed_protocol_rejects_even_whitespace_only_byte_changes(tmp_path):
    spec = baseline.load_protocol()
    assert spec["recipe"]["input_size"] == [512, 288]
    changed = tmp_path / "changed-protocol.json"
    changed.write_bytes(baseline.PROTOCOL.read_bytes() + b" ")
    with pytest.raises(ValueError, match="protocol"):
        baseline.load_protocol(changed)


def test_public_protocol_preserves_complete_frozen_support_and_recipe():
    protocol = baseline.load_protocol()
    assert protocol["expected"]["cases"] == 128
    assert protocol["expected"]["requested_rows"] == 8192
    assert protocol["expected"]["visibility"] == {
        "visible_localizable": 37,
        "visible_unlocalizable": 1,
        "not_visible": 5,
        "unknown": 85,
    }
    assert set(protocol["eligibility"].values()) == {False}
    recipe = protocol["recipe"]
    assert (recipe["input_size"], recipe["sequence_length"], recipe["threshold"]) == (
        [512, 288],
        8,
        0.5,
    )
    assert recipe["precision"] == "float16" and recipe["device"] == "cuda"
    assert recipe["radius_diagonal"] == 0.005
