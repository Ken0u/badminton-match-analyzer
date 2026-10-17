import hashlib
import json

import pytest
from badminton import tracking
from badminton.api import TrackingRequest


@pytest.mark.parametrize(
    "variant,name", [("small", "yolo11s-pose.pt"), ("nano", "yolo11n-pose.pt")]
)
def test_only_explicit_manifest_verified_player_weights_load(
    tmp_path, monkeypatch, variant, name
):
    content = b"test fixture, never unpickled"
    entry = {
        "name": name,
        "source": "fixture",
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"player_pose_small" if variant == "small" else "player_pose": entry}
        )
    )
    monkeypatch.setattr(tracking, "MODEL_MANIFEST", manifest)
    monkeypatch.setattr(tracking, "WEIGHTS", tmp_path)
    with pytest.raises(RuntimeError, match="missing"):
        tracking.player_checkpoint(variant)
    (tmp_path / name).write_bytes(content)
    path, actual = tracking.player_checkpoint(variant)
    assert path == tmp_path / name and actual == entry
    (tmp_path / name).write_bytes(b"corrupt or replaced checkpoint")
    with pytest.raises(RuntimeError, match="pinned"):
        tracking.player_checkpoint(variant)
    entry["name"] = "../elsewhere.pt"
    manifest.write_text(
        json.dumps(
            {"player_pose_small" if variant == "small" else "player_pose": entry}
        )
    )
    with pytest.raises(ValueError, match="weights directory"):
        tracking.player_checkpoint(variant)


def test_player_model_selection_has_safe_default_and_rejects_arbitrary_paths():
    assert TrackingRequest(start_frame=0, end_frame=25).player_model == "small"
    assert (
        TrackingRequest(start_frame=0, end_frame=25, player_model="nano").player_model
        == "nano"
    )
    with pytest.raises(ValueError):
        TrackingRequest(start_frame=0, end_frame=25, player_model="../../weights.pt")
    with pytest.raises(ValueError, match="small or nano"):
        tracking.player_checkpoint("arbitrary")
