"""Generated spatial inference checks; no external scientific inputs."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from badminton import shuttle
from badminton import shuttle_resolution as experiment
from badminton.shuttle_tiling import CANVAS, ORIGINS, predict_tiles, spatial_recipe
from PIL import Image
from test_shuttle_resolution import complete_generated_variant
from test_shuttle_resolution import frozen as frozen

pytest_plugins = ["test_shuttle_validation"]


def canvases(count=9):
    y, x = np.indices((432, 768))
    return [
        np.stack((x % 256, y % 256, x * 0 + i), axis=-1).astype(np.uint8)
        for i in range(count)
    ]


def test_tiles_align_background_and_every_sequence_frame_and_max_fuse_overlaps():
    images = canvases()
    observed = []

    def predict(crops):
        index = len(observed)
        x, y = ORIGINS[index]
        for original, crop in zip(images, crops):
            np.testing.assert_array_equal(crop, original[y : y + 288, x : x + 512])
        observed.append(index)
        return np.full((8, 288, 512), (index + 1) / 4, dtype=np.float32)

    heat = predict_tiles(images, predict)
    assert observed == [0, 1, 2, 3]
    assert heat.shape == (8, 432, 768)
    assert heat.dtype == np.float32
    assert np.all(heat[:, :144, :256] == 0.25)
    assert np.all(heat[:, :144, 256:] == 0.5)
    assert np.all(heat[:, 144:, :256] == 0.75)
    assert np.all(heat[:, 144:, 256:] == 1)
    np.testing.assert_array_equal(images[0], canvases()[0])


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        [np.zeros((432, 768, 3))],
        [np.zeros((288, 512, 3), dtype=np.uint8)] * 2,
    ],
)
def test_invalid_canvases_fail_without_model_calls(bad):
    with pytest.raises((TypeError, ValueError)):
        predict_tiles(bad, lambda _: pytest.fail("model must not run"))


@pytest.mark.parametrize(
    "bad",
    [
        np.zeros((8, 287, 512)),
        np.zeros((8, 288, 512), dtype=int),
        np.full((8, 288, 512), np.nan),
        np.full((8, 288, 512), np.inf),
        np.full((8, 288, 512), -0.01),
        np.full((8, 288, 512), 1.01),
    ],
)
def test_invalid_tile_heatmaps_fail_before_publication(bad):
    with pytest.raises(ValueError, match="finite probability"):
        predict_tiles(canvases(), lambda _: bad)


@pytest.mark.parametrize(
    "layout,size",
    [(True, CANVAS), ("other", CANVAS), ("overlap_2x2", (512, 288)), ([], CANVAS)],
)
def test_layout_is_explicit_and_fixed(layout, size):
    with pytest.raises(ValueError):
        spatial_recipe(layout, size)


def test_full_default_is_unmarked_and_research_provenance_is_exact():
    assert spatial_recipe(None, (512, 288)) is None
    assert spatial_recipe("full", (512, 288))["model_calls_per_window"] == 1
    recipe = spatial_recipe("overlap_2x2", CANVAS)
    assert recipe["model_input_size"] == [512, 288]
    assert recipe["canvas_size"] == [768, 432]
    assert recipe["tile_origins"] == [list(p) for p in ORIGINS]
    assert recipe["model_calls_per_window"] == 4


def test_temporal_fusion_preserves_native_vfr_coordinates_and_scene_reset():
    times = [0.4, 0.431, 0.48, 0.514, 0.56]
    source = SimpleNamespace(to_image=lambda: Image.fromarray(canvases(1)[0]))
    inputs = [(i, t, source) for i, t in enumerate(times)]
    calls = []

    def model(images):
        calls.append([int(i[0, 0, 2]) for i in images])
        heat = np.zeros((3, 288, 512), dtype=np.float32)
        heat[:, 20, 30] = 0.9
        return heat

    rows = list(
        shuttle.infer_camera_segment(
            inputs,
            canvases(1)[0],
            3,
            lambda images: predict_tiles(images, model),
            1280,
            720,
            input_size=CANVAS,
            selection_reset_frames=[3],
        )
    )
    assert len(calls) == 12
    assert [r["frame"] for r in rows] == list(range(5))
    assert [r["time_s"] for r in rows] == times
    assert all(r["shuttle"]["repaired"] is False for r in rows)
    assert rows[0]["shuttle"]["x"] == pytest.approx(30.5 * 1280 / 768)
    assert rows[0]["shuttle"]["y"] == pytest.approx(20.5 * 720 / 432)
    assert rows[3]["shuttle"]["selection_context_start_frame"] == 3


def test_actual_adapter_default_and_explicit_full_match_and_tiles_reset_at_cuts(
    tmp_path, monkeypatch
):
    torch = pytest.importorskip("torch")
    from badminton.vendor import tracknet_model

    calls = []

    class Model(torch.nn.Module):
        def __init__(self, *args):
            super().__init__()

        def load_state_dict(self, *args):
            pass

        def forward(self, tensor):
            calls.append(tuple(tensor.shape))
            return torch.zeros((1, 8, tensor.shape[2], tensor.shape[3]))

    weights = tmp_path / "TrackNet_best.pt"
    weights.write_bytes(b"generated model stand-in")
    checksum = hashlib.sha256(weights.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"shuttle": {"sha256": checksum}}), encoding="utf-8")
    monkeypatch.setattr(shuttle, "WEIGHTS", tmp_path)
    monkeypatch.setattr(shuttle, "MODEL_MANIFEST", manifest)
    monkeypatch.setattr(
        torch,
        "load",
        lambda *a, **k: {
            "param_dict": {"seq_len": 8, "bg_mode": "concat"},
            "model": {},
        },
    )
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(tracknet_model, "TrackNet", Model)
    times = [i * 0.04 for i in range(6)]
    monkeypatch.setattr(shuttle, "timestamps_for", lambda *a: times)
    monkeypatch.setattr(shuttle, "validate_range", lambda *a: None)
    ranges = [{"start_frame": 0, "end_frame": 3}, {"start_frame": 3, "end_frame": 6}]
    monkeypatch.setattr(
        shuttle,
        "scan_boundaries",
        lambda *a: {
            "cut_frames": [3],
            "method": "generated",
            "camera_ranges": copy.deepcopy(ranges),
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

    def run(name, **kw):
        path = tmp_path / (name + ".json")
        shuttle.track_shuttle(
            video, tmp_path, tmp_path, 0, 6, lambda _: None, path, annotations={}, **kw
        )
        return json.loads(path.read_bytes())

    default = run("default")
    full = run("full", spatial_layout="full")
    assert default["frames"] == full["frames"]
    assert "spatial_inference" not in default
    assert full["model_calls"] == full["model_windows"] == 2
    tiled = run("tiled", spatial_layout="overlap_2x2", input_size=CANVAS)
    assert tiled["model_calls"] == 8 and tiled["model_windows"] == 2
    assert calls == [(1, 27, 288, 512)] * 12
    assert tiled["spatial_inference"] == spatial_recipe("overlap_2x2", CANVAS)
    assert [r["camera_segment_start_frame"] for r in tiled["frames"]] == [0] * 3 + [
        3
    ] * 3
    assert [r["time_s"] for r in tiled["frames"]] == times
    with pytest.raises(ValueError, match="768x432"):
        run("invalid", spatial_layout="overlap_2x2")
    assert not (tmp_path / "invalid.json").exists()


def test_control_projection_omits_only_explicit_dependency_metadata_and_keeps_legacy_strict():
    old = {
        "frame": 5,
        "time_s": 0.2,
        "camera_segment_start_frame": 0,
        "shuttle": {"x": 3.0, "confidence": 0.8},
    }
    new = copy.deepcopy(old)
    new["shuttle"].update(
        selection_context_start_frame=0,
        selection_context_end_frame=6,
        selection_context_frames=[1, 2, 3],
        selection_context_excluded=False,
    )
    assert experiment.compare_rows(
        [experiment.native_row(old)], [experiment.native_row(new)], 1e-5
    )
    projection = experiment.PHYSICAL_PROJECTION
    assert (
        experiment.compare_rows(
            [experiment.native_row(old, projection)],
            [experiment.native_row(new, projection)],
            1e-5,
        )
        == []
    )
    new["shuttle"]["unexpected_field"] = True
    assert experiment.compare_rows(
        [experiment.native_row(old, projection)],
        [experiment.native_row(new, projection)],
        1e-5,
    )
    with pytest.raises(ValueError, match="projection"):
        experiment.native_row(old, "unknown")


@pytest.mark.parametrize(
    "change",
    [
        {"spatial_layouts": {"control": "full", "candidate": "other"}},
        {"control_projection": experiment.PHYSICAL_PROJECTION},
        {
            "spatial_layouts": {"control": "full", "candidate": "overlap_2x2"},
            "control_projection": "other",
        },
    ],
)
def test_experiment_refuses_unfrozen_layout_projection_pair(change):
    protocol = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "data/manifests/shuttle_resolution_protocol_v1.json"
        ).read_bytes()
    )
    protocol.update(change)
    with pytest.raises(ValueError, match="fixed tiling"):
        experiment.validate_protocol(protocol)


def test_tiled_run_provenance_and_model_accounting_are_validated(frozen):
    n = frozen
    receipt, protocol, inputs = complete_generated_variant(n, "candidate")
    view = receipt["views"][0]
    _entry, run = experiment.completed_view(
        n["output"], "candidate", view, n["experiment_sha"]
    )
    source = next(s for s in inputs[1] if s[1]["id"] == view["video_id"])
    original = inputs[4][(view["video_id"], view["core_index"])]
    protocol.update(
        spatial_layouts={"control": "full", "candidate": "overlap_2x2"},
        control_projection=experiment.PHYSICAL_PROJECTION,
    )
    run.update(
        spatial_inference=spatial_recipe("overlap_2x2", CANVAS),
        model_windows=1,
        model_calls=4,
    )
    for row in run["frames"]:
        heat = np.zeros((432, 768), dtype=np.float32)
        heat[10, 20] = 0.9
        point = shuttle._ComponentSelector(
            source[1]["width"], source[1]["height"]
        ).select(
            shuttle.locate_shuttle(heat, source[1]["width"], source[1]["height"]),
            row["frame"],
            row["time_s"],
        )
        point["selection_context_excluded"] = False
        row["shuttle"] = point

    def validate():
        return experiment.validate_research_run(
            run, view, "candidate", protocol, original, source[1], source[2]
        )

    assert len(validate()) == 4
    boolean_geometry = copy.deepcopy(run["spatial_inference"])
    boolean_geometry["tile_origins"][0][0] = False
    for key, value in [
        ("model_calls", True),
        ("model_calls", 1),
        ("model_windows", 2),
        ("spatial_inference", spatial_recipe("full", CANVAS)),
        ("spatial_inference", boolean_geometry),
    ]:
        before = copy.deepcopy(run)
        run[key] = value
        with pytest.raises(ValueError, match="spatial recipe"):
            validate()
        run.clear()
        run.update(before)
    run["frames"][0]["shuttle"]["selection_context_start_frame"] = -1
    with pytest.raises(ValueError, match="selector history"):
        validate()


@pytest.fixture
def tiled_frozen(native, monkeypatch):
    from test_shuttle_validation import edit_native_shuttle

    def geometry(run):
        for row in run["frames"]:
            point = row["shuttle"]
            point.update(
                largest_component_id=1, selection_reason="largest_heatmap_component"
            )
            point["component_candidates"][0]["area_heatmap_pixels"] = 1

    for plan in native["plans"]:
        edit_native_shuttle({**native, "plans": [plan]}, geometry)
    n = frozen.__wrapped__(native, monkeypatch)
    protocol = json.loads(n["protocol"].read_bytes())
    protocol.update(
        spatial_layouts={"control": "full", "candidate": "overlap_2x2"},
        candidate_spatial_recipe=spatial_recipe("overlap_2x2", CANVAS),
        control_projection=experiment.PHYSICAL_PROJECTION,
    )
    protocol["control_gate"]["omitted_dependency_fields"] = sorted(
        experiment.DEPENDENCY_FIELDS
    )
    path = n["root"] / "tiling.json"
    path.write_bytes(experiment.audit.encoded(protocol))
    output = n["root"] / ".cache/tiling"
    result = experiment.freeze_experiment(
        n["root"],
        n["packet_root"],
        n["label_root"],
        n["baseline_path"],
        path,
        experiment.audit.file_hash(path),
        output,
    )
    return {**n, "output": output, "experiment_sha": result["experiment_sha256"]}


def complete_tiled_variant(n, variant):
    receipt, protocol, inputs = complete_generated_variant(n, variant)
    for view in receipt["views"]:
        manifest_path = n["output"] / variant / (view["id"] + ".json")
        manifest = json.loads(manifest_path.read_bytes())
        path = experiment.audit.inside(n["output"], manifest["run"]["path"])
        run = json.loads(path.read_bytes())
        spatial = spatial_recipe(
            protocol["spatial_layouts"][variant], protocol["variants"][variant]
        )
        run.update(
            spatial_inference=spatial,
            model_windows=1,
            model_calls=spatial["model_calls_per_window"],
        )
        path.write_bytes(experiment.audit.encoded(run))
        manifest["run"] = experiment.audit.seal(n["output"], path)
        manifest_path.write_bytes(experiment.audit.encoded(manifest))
    return receipt, protocol, inputs


def test_complete_tiled_report_preserves_unknowns_and_actual_accounting(tiled_frozen):
    n = tiled_frozen
    complete_tiled_variant(n, "control")
    complete_tiled_variant(n, "candidate")
    output = n["root"] / ".cache/tiling-report"
    experiment.evaluate_experiment(n["root"], n["output"], n["experiment_sha"], output)
    report = json.loads((output / "report.json").read_bytes())
    assert report["comparison_status"] == "compatible"
    assert report["control_gate"]["projection"] == experiment.PHYSICAL_PROJECTION
    assert report["variants"]["control"]["performance"]["model_calls"] == 2
    assert report["variants"]["candidate"]["performance"]["model_calls"] == 8
    for value in report["variants"].values():
        assert value["all_cases_retained"] == 5
        assert value["groups"]["all"]["metrics"]["truth_states"]["unknown"] == 3


@pytest.mark.parametrize("flag", [True, 1, None])
def test_projected_dependencies_still_require_exact_source_replay(tiled_frozen, flag):
    n = tiled_frozen
    receipt, protocol, inputs = complete_tiled_variant(n, "control")
    view = receipt["views"][0]
    _, run = experiment.completed_view(
        n["output"], "control", view, n["experiment_sha"]
    )
    run["frames"][0]["shuttle"]["selection_context_excluded"] = flag
    source = next(s for s in inputs[1] if s[1]["id"] == view["video_id"])
    with pytest.raises(ValueError, match=r"provenance differs|must be boolean"):
        experiment.validate_research_run(
            run,
            view,
            "control",
            protocol,
            inputs[4][(view["video_id"], view["core_index"])],
            source[1],
            source[2],
        )


def test_native_tiling_protocol_rejects_claimed_geometry_change():
    path = (
        Path(__file__).resolve().parents[1]
        / "data/manifests/shuttle_tiling_protocol_v1.json"
    )
    protocol = json.loads(path.read_bytes())
    experiment.validate_protocol(protocol)
    protocol["candidate_spatial_recipe"]["tile_origins"][1][0] += 1
    with pytest.raises(ValueError, match="fixed tiling"):
        experiment.validate_protocol(protocol)


@pytest.mark.parametrize(
    "field", ["spatial_layouts", "control_projection", "candidate_spatial_recipe"]
)
def test_null_research_protocol_fields_are_rejected_before_any_execution(field):
    path = (
        Path(__file__).resolve().parents[1]
        / "data/manifests/shuttle_resolution_protocol_v1.json"
    )
    protocol = json.loads(path.read_bytes())
    protocol[field] = None
    with pytest.raises(ValueError, match="fixed tiling"):
        experiment.validate_protocol(protocol)
