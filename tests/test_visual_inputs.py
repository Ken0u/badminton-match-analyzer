import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from badminton import visual_inputs as inputs
from badminton.segments import BoundaryDetector, scan_boundaries
from badminton.video import SourceChangedError, iter_frames, timestamps_for
from test_segments import make_source


def spec():
    return json.loads(inputs.MANIFEST.read_text())


def test_full_image_letterbox_keeps_edges_and_zero_normalized_padding():
    encoder = spec()["encoder"] | {"input_width": 8, "input_height": 8}
    pixels = np.zeros((2, 8, 3), dtype=np.uint8)
    pixels[:, 0] = [255, 0, 0]
    pixels[:, -1] = [0, 0, 255]
    result = inputs.letterbox_rgb(pixels, encoder)
    assert result.shape == (3, 8, 8) and result.dtype == np.float32
    assert np.all(result[:, :3] == 0) and np.all(result[:, 5:] == 0)
    assert result[0, 3, 0] > 2 and result[2, 3, -1] > 2
    with pytest.raises(ValueError, match="RGB"):
        inputs.letterbox_rgb(pixels.astype(float), encoder)


def test_context_never_crosses_cut_or_real_timestamp_gap():
    config = spec()["context"]
    times = np.arange(60) / 30
    indices, valid = inputs.context_indices(times, [30], config)
    assert np.all(indices[:30][indices[:30] >= 0] < 30)
    assert np.all(indices[30:][indices[30:] >= 0] >= 30)
    assert not valid[0] and not valid[-1] and not valid[29] and not valid[30]
    assert valid[15] and valid[45]
    times[30:] += 0.6
    gap_indices, gap_valid = inputs.context_indices(times, [], config)
    np.testing.assert_array_equal(indices, gap_indices)
    np.testing.assert_array_equal(valid, gap_valid)


def test_context_samples_actual_vfr_pts_and_counts_distinct_flank_frames():
    config = spec()["context"]
    times = np.cumsum([0, 0.025, 0.045, 0.03, 0.04, 0.02, 0.05, 0.03, 0.04])
    indices, _valid = inputs.context_indices(times, [], config)
    offsets = np.asarray(config["offsets_s"])
    for center, row in enumerate(indices):
        for bin_index, observation in enumerate(row):
            if observation >= 0:
                assert (
                    abs(times[observation] - times[center] - offsets[bin_index])
                    <= 0.025 + 1e-8
                )
    # Lots of bins can choose the same low-rate frame. Those are not several
    # independent observations, even when enough bins appear to be available.
    _indices, valid = inputs.context_indices(np.arange(20) * 0.1, [], config)
    assert valid[8]
    _indices, sparse = inputs.context_indices(np.arange(20) * 0.2, [], config)
    assert not sparse.any()  # source gaps exceed the frozen input contract
    for invalid in [[0, 0], [0, float("nan")], []]:
        with pytest.raises(ValueError):
            inputs.context_indices(invalid, [], config)


def test_incremental_scanner_matches_app_for_full_and_partial_vfr_media(tmp_path):
    video, data, _store = make_source(tmp_path, cuts=(5, 40))
    times = timestamps_for(data, video["id"])
    detector = BoundaryDetector(video["fps"], video["width"], video["height"])
    cuts = {}
    for index, timestamp, frame in iter_frames(video, tmp_path, times, 0, len(times)):
        cuts.update(detector.process(index, timestamp, frame))
    app = scan_boundaries(video, tmp_path, data, 0, len(times), lambda _: None)
    assert sorted(cuts) == app["cut_frames"] == [5, 40]
    partial = scan_boundaries(video, tmp_path, data, 38, 41, lambda _: None)
    assert partial["cut_frames"] == [40]


def test_scanner_rejects_missing_source_observations(tmp_path):
    video, data, _store = make_source(tmp_path)
    times = timestamps_for(data, video["id"])
    frames = iter_frames(video, tmp_path, times, 0, 3)
    detector = BoundaryDetector(video["fps"], video["width"], video["height"])
    detector.process(*next(frames))
    next(frames)
    with pytest.raises(SourceChangedError, match="consecutive"):
        detector.process(*next(frames))
    frames.close()


class EncoderFixture:
    def __init__(self):
        self.runtime = {"device": "test-fixture"}

    def encode(self, images, mirror=False):
        # Preserve two pixel positions: a true pixel flip swaps both values.
        return np.asarray(
            [
                [image[0, 0, -1] if mirror else image[0, 0, 0], image.mean()]
                for image in images
            ],
            dtype=np.float16,
        )


def test_actual_decode_cache_has_exact_pts_and_cuts_and_detects_corruption(tmp_path):
    video, data, store = make_source(tmp_path, cuts=(5, 40))
    before = store.annotations(video["id"]).model_dump()
    raw = (tmp_path / video["path"]).read_bytes()
    clip = {
        "media_sha256": hashlib.sha256(raw).hexdigest(),
        "source_partition": "train",
        "source_clip_id": "00001",
    }
    config = spec()
    config["encoder"] |= {"input_width": 48, "input_height": 32, "feature_dim": 2}
    recipe = inputs.feature_recipe(config)
    directory = tmp_path / "features"
    receipt = inputs.encode_clip(
        raw, directory, clip, config, recipe, EncoderFixture(), True, 8
    )
    assert receipt["frames"] == 65 and receipt["annotation_inputs"] is False
    assert [c["frame"] for c in receipt["cuts"]] == [5, 40]
    _receipt, arrays = inputs.read_features(directory, clip, recipe, True)
    np.testing.assert_array_equal(
        arrays["times.npy"], timestamps_for(data, video["id"])
    )
    assert arrays["features.npy"].shape == (65, 2)
    assert store.annotations(video["id"]).model_dump() == before
    del arrays
    with pytest.raises(ValueError, match="Incompatible"):
        inputs.read_features(directory, clip, recipe, False)
    (directory / "features.npy").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="Corrupted"):
        inputs.read_features(directory, clip, recipe, True)
    with pytest.raises(SourceChangedError, match="hash"):
        inputs.encode_clip(
            b"wrong source", directory, clip, config, recipe, EncoderFixture(), True, 8
        )


def test_frozen_group_manifest_covers_969_clips_without_labelled_val_leakage():
    groups = json.loads(inputs.GROUPS.read_text())
    members = [key for group in groups["source_groups"] for key in group["members"]]
    assert len(members) == len(set(members)) == 969
    labelled = dict.fromkeys(("train", "validation", "test"), 0)
    for group in groups["source_groups"]:
        labelled[group["fold"]] += sum(
            key.startswith("train:") for key in group["members"]
        )
    assert labelled == {"train": 424, "validation": 176, "test": 200}


def test_cli_preparation_uses_shared_admission_and_exposes_resume_args(
    tmp_path, monkeypatch, capsys
):
    from badminton import cli
    from badminton.storage import Store

    store = Store(tmp_path / "app")
    monkeypatch.setattr(cli, "Store", lambda *args: store)
    seen = []

    def prepare(*args, **kwargs):
        assert [j["kind"] for j in store.jobs() if j["status"] == "running"] == [
            "feature-preparation"
        ]
        seen.append((args, kwargs))
        return {"clips": 800}

    monkeypatch.setattr(inputs, "prepare_features", prepare)
    monkeypatch.setattr(
        "sys.argv",
        [
            "badminton",
            "prepare-visual-features",
            "source.zip",
            "--index",
            "index",
            "--weights",
            "weights.pth",
            "--output",
            "features",
        ],
    )
    cli.main()
    assert json.loads(capsys.readouterr().out) == {"clips": 800}
    assert seen[0][0][0] == Path("source.zip")
    assert not any(j["status"] == "running" for j in store.jobs())
