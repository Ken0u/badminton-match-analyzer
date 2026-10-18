import json

import numpy as np
import pytest
from badminton import visual_learning as learning
from badminton.visual_inputs import MANIFEST, context_indices


def spec():
    return json.loads(MANIFEST.read_text())


def reference(id, left, right, labels=(0, 0, 0)):
    return {
        "id": id,
        "left": left,
        "right": right,
        "start_s": left / 30,
        "end_s": right / 30,
        "labels": list(labels),
        "left_censored": right == 0,
    }


def fixture_clip(config=None, *, key="clip", fold="train", length=90, cuts=()):
    config = config or spec()
    rng = np.random.default_rng(19)
    values = rng.normal(size=(length, config["encoder"]["feature_dim"])).astype(
        np.float16
    )
    times = np.arange(length) / 30
    indices, valid = context_indices(times, list(cuts), config["context"])
    return {
        "key": key,
        "fold": fold,
        "arrays": {
            "features.npy": values,
            "mirrored.npy": values[:, ::-1],
            "times.npy": times,
        },
        "indices": indices,
        "valid": valid,
        "cuts": list(cuts),
        "refs": [
            reference("serve", 19, 20, (7, 1, 1)),
            reference("net", 59, 60, (2, 0, 0)),
        ],
        "receipt_sha256": "fixture-source-only",
        "encoder_runtime": {"device": "test-fixture"},
    }


def test_reference_preserves_ordinal_ambiguity_and_censored_denominator():
    records = [
        {
            "id": "r",
            "source_contact_frame": h,
            "kind": "serve",
            "family": None,
            "side": "backhand",
            "source_court_end": "near",
        }
        for h in (0, 5)
    ]
    refs = learning.references(records, np.arange(10) / 30, spec())
    assert [(r["left"], r["right"]) for r in refs] == [(0, 0), (4, 5)]
    assert refs[0]["left_censored"] and not refs[1]["left_censored"]
    assert refs[1]["labels"] == [7, 1, 0]
    records[0]["source_contact_frame"] = 10
    with pytest.raises(ValueError, match="outside"):
        learning.references(records, np.arange(10) / 30, spec())


def test_training_bags_and_negatives_preserve_missing_context_and_all_exclusions():
    config = spec()
    clip = fixture_clip(config)
    clip["refs"].append(reference("censored", 0, 0))
    samples = learning.training_samples(
        clip["refs"],
        clip["arrays"]["times.npy"],
        clip["valid"],
        config["training"],
        np.random.default_rng(1),
    )
    positive = [s for s in samples if s["positive"]]
    assert [s["centers"] for s in positive] == [[19, 20], [59, 60]]
    assert len([s for s in samples if not s["positive"]]) == 4
    for sample in samples:
        if not sample["positive"]:
            t = clip["arrays"]["times.npy"][sample["centers"][0]]
            assert all(
                max(ref["start_s"] - t, t - ref["end_s"]) > 0.2 for ref in clip["refs"]
            )


def test_normalization_uses_only_training_original_and_true_pixel_mirror_cache():
    train = {
        "fold": "train",
        "arrays": {
            "features.npy": np.asarray([[1.0, 3.0]]),
            "mirrored.npy": np.asarray([[3.0, 7.0]]),
        },
    }
    heldout = {"fold": "test", "arrays": {"features.npy": np.full((2, 2), 10000)}}
    mean, std, count = learning.normalization([train, heldout], 2)
    np.testing.assert_array_equal(mean, [2, 5])
    np.testing.assert_array_equal(std, [1, 2])
    assert count == 2


def test_missing_windows_remain_zero_after_normalization():
    values = np.asarray([[5.0, 8.0], [10.0, 4.0]])
    windows, mask = learning.input_windows(
        values,
        np.asarray([[-1, 0, 1]]),
        [0],
        np.asarray([3.0, 2.0]),
        np.asarray([1.0, 2.0]),
    )
    np.testing.assert_array_equal(mask, [[0, 1, 1]])
    np.testing.assert_array_equal(windows, [[[0, 0], [2, 3], [7, 1]]])


def test_interval_matching_does_not_greedily_steal_only_candidate():
    refs = [reference("a", 30, 30), reference("b", 33, 33)]
    candidates = [{"time_s": 0.95}, {"time_s": 1.04}]
    pairs = learning.match_intervals(refs, candidates, 0.061)
    assert [(r["id"], p["time_s"]) for r, p in pairs] == [("a", 0.95), ("b", 1.04)]
    interval = reference("ambiguous", 29, 30)
    assert len(learning.match_intervals([interval], [{"time_s": 29 / 30}], 0)) == 1


def test_metrics_count_censored_unavailable_and_wrong_semantics_as_misses():
    clip = fixture_clip()
    clip["refs"].append(reference("censored", 0, 0))
    predictions = [
        {"time_s": 20 / 30, "frame": 20, "labels": [7, 1, 1]},
        {"time_s": 60 / 30, "frame": 60, "labels": [2, 1, 0]},
    ]
    metrics = learning.event_metrics([clip], {clip["key"]: predictions}, spec())
    assert metrics["contact"]["tp"] == 2 and metrics["contact"]["fn"] == 1
    assert metrics["tuple"]["tp"] == 1 and metrics["tuple"]["fn"] == 2
    assert metrics["tuple"]["fp"] == 1
    assert (
        metrics["left_censored_references"]
        == metrics["reference_contacts_without_valid_context"]
        == 1
    )
    assert len(metrics["family_side_metrics"]) == 16
    assert metrics["family_side_metrics"]["net/forehand"]["fn"] == 1
    assert metrics["family_side_metrics"]["net/backhand"]["fp"] == 1
    assert metrics["family_side_metrics"]["smash/backhand"]["support"] == 0
    assert metrics["family_side_metrics"]["smash/backhand"]["recall"] is None


def test_spotting_uses_scores_and_contexts_without_reference_contacts():
    config = spec()
    clip = fixture_clip(config, cuts=(45,))
    clip["refs"] = []  # Not a model input.
    logits = np.full((90, 13), -20.0, np.float32)
    logits[[19, 20, 40, 49], 0] = [2, 3, 4, 4]
    logits[:, 1 + 4] = 1
    logits[:, 9 + 1] = 1
    logits[:, 11] = 1
    events = learning.spot_events(clip, logits, 0.5, config)
    assert [e["frame"] for e in events] == [20, 40, 49]
    assert all(e["labels"] == [4, 1, 0] for e in events)
    assert learning.spot_events(clip, logits, 0.9999, config) == []


def test_nms_does_not_suppress_events_across_timestamp_discontinuity():
    config = spec()
    clip = fixture_clip(config)
    times = np.r_[np.arange(10) / 100, 0.21 + np.arange(10) / 100]
    clip["arrays"]["times.npy"] = times
    clip["valid"] = np.ones(20, dtype=bool)
    logits = np.full((20, 13), -20.0, np.float32)
    logits[[9, 10], 0] = 8
    events = learning.spot_events(clip, logits, 0.5, config)
    assert [e["frame"] for e in events] == [9, 10]


def test_test_prediction_refuses_unfinished_selection_before_loading_torch(tmp_path):
    (tmp_path / "selected.json").write_text(json.dumps({"selection_final": False}))
    (tmp_path / "protocol.json").write_text("{}")
    with pytest.raises(ValueError, match="completed, unchanged"):
        learning.evaluate_visual(
            tmp_path, tmp_path, tmp_path, tmp_path / "test.json", lambda _: None
        )
    assert not (tmp_path / "test.json").exists()


def test_loader_checks_completed_receipt_registry_and_runtime(tmp_path, monkeypatch):
    config = spec()
    members = [
        {"source_partition": "train", "source_clip_id": "00001", "media_sha256": "a"},
        {"source_partition": "train", "source_clip_id": "00002", "media_sha256": "b"},
    ]
    folds = {"train:00001": "train", "train:00002": "validation"}
    monkeypatch.setattr(
        learning, "load_protocol", lambda index: (config, {}, members, folds)
    )
    records, registry = [], []
    arrays = fixture_clip(config)["arrays"]
    runtimes = [{"device": "cpu"}, {"device": "cpu"}]
    for i, member in enumerate(members):
        key = learning.clip_key(member)
        directory = tmp_path / key.replace(":", "-")
        directory.mkdir()
        (directory / "receipt.json").write_text("fixture pinned receipt")
        registry.append(
            {
                "clip": key,
                "fold": folds[key],
                "receipt_sha256": learning.sha256(directory / "receipt.json"),
            }
        )
        records.append(
            member
            | {
                "id": key,
                "source_contact_frame": 20,
                "kind": "serve",
                "family": None,
                "side": "backhand",
                "source_court_end": "near",
            }
        )

    def cache(directory, member, recipe, mirror):
        index = int(member["source_clip_id"]) - 1
        return {"cuts": [], "runtime": runtimes[index]}, arrays

    monkeypatch.setattr(learning, "read_features", cache)
    (tmp_path / "records.json").write_text(json.dumps(records))
    completed = {
        "recipe": learning.feature_recipe(config),
        "members": registry,
        "capture_manifest_sha256": learning.sha256(learning.GROUPS),
        "learning_manifest_sha256": learning.sha256(learning.MANIFEST),
    }
    (tmp_path / "completed.json").write_text(json.dumps(completed))
    _config, loaded = learning.load_clips(
        tmp_path, tmp_path, folds_to_open={"train", "validation"}
    )
    assert len(loaded) == 2
    runtimes[1] = {"device": "cuda:0"}
    with pytest.raises(ValueError, match="consistent encoder runtime"):
        learning.load_clips(tmp_path, tmp_path, folds_to_open={"train", "validation"})
    runtimes[1] = runtimes[0]
    (tmp_path / "train-00001/receipt.json").write_text("changed after completion")
    with pytest.raises(ValueError, match="receipt changed"):
        learning.load_clips(tmp_path, tmp_path, folds_to_open={"train", "validation"})
    completed["members"] = [registry[0], registry[0]]
    (tmp_path / "completed.json").write_text(json.dumps(completed))
    with pytest.raises(ValueError, match="exactly once"):
        learning.load_clips(tmp_path, tmp_path, folds_to_open={"train", "validation"})


def small_spec():
    config = spec()
    config["encoder"]["feature_dim"] = 4
    config["training"] |= {
        "hidden_dim": 8,
        "dropout": 0.0,
        "epochs": 2,
        "evaluate_every": 1,
        "batch_size": 4,
    }
    return config


def test_torch_fast_path_matches_all_masked_windows_and_cut_edges():
    torch = pytest.importorskip("torch")
    torch.set_num_threads(2)
    torch.manual_seed(31)
    config = small_spec()
    clip = fixture_clip(config, length=1100, cuts=(40, 600))
    model = learning.create_model(config).eval()
    mean, std = np.zeros(4, np.float32), np.ones(4, np.float32)
    fast = learning.predict_clip(model, clip, config, mean, std, "cpu")
    centers = [0, 1, 5, 39, 40, 41, 510, 511, 512, 513, 599, 600, 601, 1099]
    values, mask = learning.input_windows(
        clip["arrays"]["features.npy"], clip["indices"], centers, mean, std
    )
    with torch.inference_mode():
        expected = model(torch.from_numpy(values), torch.from_numpy(mask))[
            :, 15
        ].numpy()
    np.testing.assert_allclose(fast[centers], expected, rtol=1e-5, atol=1e-6)


def test_torch_end_to_end_training_freezes_selection_before_test(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    config = small_spec()
    clips = [
        fixture_clip(config, key=fold, fold=fold)
        for fold in ("train", "validation", "test")
    ]
    opened = []

    def load(*args, folds_to_open):
        opened.append(folds_to_open)
        return config, [c for c in clips if c["fold"] in folds_to_open]

    monkeypatch.setattr(learning, "load_clips", load)
    run = tmp_path / "run"
    result = learning.train_visual(
        tmp_path, tmp_path, run, lambda _: None, device="cpu"
    )
    assert opened == [{"train", "validation"}]
    assert result["epochs"] == 2 and result["selected"]["selection_final"] is True
    assert result["installed_in_app"] is False
    selection = json.loads((run / "selected.json").read_text())
    (run / "selected.json").write_text(json.dumps(selection | {"threshold": 0.12345}))
    with pytest.raises(ValueError, match="unchanged"):
        learning.evaluate_visual(
            tmp_path,
            tmp_path,
            run,
            tmp_path / "unfrozen-test.json",
            lambda _: None,
            device="cpu",
        )
    assert not (tmp_path / "unfrozen-test.json").exists()
    (run / "selected.json").write_text(json.dumps(selection))
    report = learning.evaluate_visual(
        tmp_path, tmp_path, run, tmp_path / "test.json", lambda _: None, device="cpu"
    )
    assert opened[-1] == {"test"}
    assert report["metrics"]["references"] == 2
    assert (tmp_path / "test.json").is_file()
    with pytest.raises(ValueError, match="already exists"):
        learning.evaluate_visual(
            tmp_path,
            tmp_path,
            run,
            tmp_path / "test.json",
            lambda _: None,
            device="cpu",
        )
    (run / "selected.pt").write_bytes(b"changed checkpoint")
    with pytest.raises(ValueError, match="unchanged"):
        learning.evaluate_visual(
            tmp_path,
            tmp_path,
            run,
            tmp_path / "altered-test.json",
            lambda _: None,
            device="cpu",
        )
