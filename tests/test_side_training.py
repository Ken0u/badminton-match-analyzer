import copy
import io
import json
import zlib

import numpy as np
import pytest
from badminton.stroke_side import (
    normalization_from_training,
    side_metrics,
    training_arrays,
)
from badminton.training_features import (
    archive_members,
    file_sha,
    join_feature_labels,
    load_training_clip,
    training_recipe,
)


def technical_entry(path="dataset_npy/train/Top_挑球/1_1_1_2_joints.npy", extra=""):
    return f"Path = {path}\nFolder = -\nSize = 128\nCRC = 1234ABCD\nSymbolic Link = \nHard Link = \nCopy Link = \nEncrypted = -\nAlternate Stream = -\n{extra}\n"


def test_archive_paths_checksums_and_links_are_checked_before_extraction(tmp_path):
    text = "header\n----------\n" + technical_entry()
    members = archive_members(text, tmp_path)
    assert list(members) == ["dataset_npy/train/Top_挑球/1_1_1_2_joints.npy"]
    assert archive_members(text.replace("\n", "\r\r\n"), tmp_path) == members
    for path in (
        "../escape.npy",
        "C:\\escape.npy",
        "dataset_npy/train/../escape.npy",
        "dataset_npy/code.py",
    ):
        with pytest.raises(ValueError):
            archive_members("----------\n" + technical_entry(path), tmp_path)
    with pytest.raises(ValueError, match="links"):
        archive_members(
            "----------\n" + technical_entry(extra="Symbolic Link = outside"), tmp_path
        )
    with pytest.raises(ValueError, match="unique"):
        archive_members(text + "\n" + technical_entry(), tmp_path)


def test_feature_join_requires_exact_source_stroke_type_split_and_unique_hitter():
    recipe = training_recipe()
    row = {
        "side_eligible": True,
        "family_eligible": True,
        "kind": "shot",
        "family": "lift",
        "match_id": 1,
        "set_id": 1,
        "rally_id": 1,
        "stroke_order": 2,
        "split": "train",
        "raw": {"type": "挑球"},
        "id": "label",
        "side": "backhand",
    }
    members = {
        f"dataset_npy/train/Top_挑球/1_1_1_2_{name}.npy": {}
        for name in ("joints", "shuttle")
    }
    found, excluded = join_feature_labels([row], members, recipe=recipe)
    assert not excluded and found[0]["label"] == 1 and found[0]["court_end"] == 0
    ambiguous = members | {p.replace("Top_", "Bottom_"): {} for p in members}
    assert join_feature_labels([row], ambiguous, recipe=recipe)[0] == []
    modified = copy.deepcopy(row)
    modified["raw"]["type"] = "長球"
    assert join_feature_labels([modified], members, recipe=recipe)[0] == []
    with pytest.raises(ValueError, match="unique"):
        join_feature_labels([row, row], members, recipe=recipe)


def test_feature_array_integrity_and_missing_input_gate(tmp_path):
    branch = "dataset_npy/train/Top_挑球/1_1_1_2"
    members = {}

    def save(suffix, array):
        relative = branch + suffix + ".npy"
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO()
        np.save(buffer, array, allow_pickle=False)
        raw = buffer.getvalue()
        path.write_bytes(raw)
        members[relative] = {"size": len(raw), "crc": f"{zlib.crc32(raw):08X}"}
        return path

    save("_joints", np.ones((25, 2, 17, 2), np.float32) * 0.1)
    path = save("_shuttle", np.ones((25, 2), np.float32) * 0.4)
    clip = load_training_clip(tmp_path, {"branch": branch}, members)
    assert clip[0].shape == (30, 2, 72) and clip[2] == 25
    path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="pinned archive"):
        load_training_clip(tmp_path, {"branch": branch}, members)
    save("_shuttle", np.zeros((25, 2), np.float32))
    assert load_training_clip(tmp_path, {"branch": branch}, members) is None


def test_normalization_uses_train_only_and_abstentions_are_not_removed_from_strict_recall():
    mean, std = normalization_from_training(
        np.array([[1.0, 2.0], [3.0, 2.0], [1000.0, 9000.0]]),
        np.array([True, True, False]),
    )
    np.testing.assert_array_equal(mean, [2, 2])
    np.testing.assert_array_equal(std, [1, 1])
    result = side_metrics([0, 1], [[0.99, 0.01], [0.4, 0.6]], 0.8)
    assert result["balanced_accuracy"] == 1 and result["coverage"] == 0.5
    assert (
        result["accuracy_of_answered"] == 1
        and result["balanced_recall_counting_abstentions_as_misses"] == 0.5
    )
    assert side_metrics([0], [[0.6, 0.4]])["balanced_accuracy"] is None
    with pytest.raises(ValueError, match="finite"):
        side_metrics([0], [[0.5, 0.5]], float("nan"))


def test_descriptor_cache_rejects_hash_tampering_and_match_leakage(tmp_path):
    recipe = training_recipe()
    features = np.zeros((6, 302), np.float32)
    features[:, -2] = 1
    arrays = {
        "features": features,
        "labels": np.array([0, 1, 0, 1, 0, 1]),
        "splits": np.array(
            ["train", "train", "validation", "validation", "test", "test"]
        ),
        "matches": np.array([1, 1, 35, 35, 39, 39]),
        "families": np.array(["lift"] * 6),
        "record_ids": np.array([str(i) for i in range(6)]),
    }
    path = tmp_path / "descriptors.npz"

    def save():
        np.savez_compressed(path, **arrays)
        (tmp_path / "manifest.json").write_text(
            json.dumps(
                {
                    "recipe": recipe,
                    "array_sha256": file_sha(path),
                    "label_index_sha256": recipe["label_index_sha256"],
                }
            )
        )

    save()
    assert len(training_arrays(tmp_path)[0]["features"]) == 6
    arrays["matches"][2] = 1
    save()
    with pytest.raises(ValueError, match="frozen"):
        training_arrays(tmp_path)
    path.write_bytes(b"changed cache")
    with pytest.raises(ValueError, match="hash"):
        training_arrays(tmp_path)


def test_packaged_head_and_recipe_match_the_model_inventory():
    from pathlib import Path

    from badminton.config import MODEL_MANIFEST

    manifest = json.loads(MODEL_MANIFEST.read_text())
    folder = Path(MODEL_MANIFEST).parent / "assets"
    metadata = json.loads((folder / "stroke_side_v1.json").read_text())
    assert (
        file_sha(folder / "stroke_side_v1.pt")
        == manifest["stroke_side"]["sha256"]
        == metadata["checkpoint_sha256"]
    )
    assert (
        metadata["recipe"] == training_recipe()
        and metadata["test_used_for_selection"] is False
    )
