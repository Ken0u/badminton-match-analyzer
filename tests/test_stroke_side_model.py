import pytest
from badminton.stroke_side import (
    forward_with_descriptor,
    load_side_predictor,
    predict_side,
)
from badminton.training_features import training_recipe

torch = pytest.importorskip("torch")


def test_bundled_head_is_cpu_loadable_and_missing_optional_model_abstains(tmp_path):
    assert load_side_predictor("cpu", weights=tmp_path, use_packaged=False) is None
    predictor = load_side_predictor("cpu", weights=tmp_path)
    result = predict_side(predictor, torch.zeros(1, 300), "far")
    assert (
        result["side"] in ("forehand", "backhand", "unknown")
        and 0 <= result["side_score"] <= 1
    )
    assert predict_side(predictor, torch.zeros(1, 300), None)["side"] == "unknown"
    (tmp_path / "stroke_side_v1.pt").write_bytes(b"partial install")
    with pytest.raises(RuntimeError, match="incomplete"):
        load_side_predictor("cpu", weights=tmp_path)


def test_uncertain_and_confident_side_outputs_respect_frozen_threshold():
    head = torch.nn.Linear(302, 2)
    with torch.no_grad():
        head.weight.zero_()
        head.bias.zero_()
    predictor = {
        "model": head.eval(),
        "mean": torch.zeros(302),
        "std": torch.ones(302),
        "metadata": {"recipe": training_recipe()},
    }
    result = predict_side(predictor, torch.zeros(1, 300), "near")
    assert result["side"] == "unknown" and result["side_status"] == "abstained"
    with torch.no_grad():
        head.bias[:] = torch.tensor([3.0, -3.0])
    assert predict_side(predictor, torch.zeros(1, 300), "near")["side"] == "forehand"


def test_descriptor_capture_preserves_family_logits_and_removes_hooks_on_failure():
    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.mlp_head = torch.nn.Linear(300, 35)
            self.fail = False

        def forward(self, x):
            if self.fail:
                raise RuntimeError("failed source model")
            return self.mlp_head(x)

    model = Model().eval()
    x = torch.randn(2, 300)
    expected = model(x)
    actual, features = forward_with_descriptor(model, x)
    torch.testing.assert_close(actual, expected)
    torch.testing.assert_close(features, x)
    assert not model.mlp_head._forward_pre_hooks
    model.fail = True
    with pytest.raises(RuntimeError, match="failed source"):
        forward_with_descriptor(model, x)
    assert not model.mlp_head._forward_pre_hooks


def test_versioned_checkpoint_pointer_loads_and_cannot_escape_its_directory(tmp_path):
    import json
    from pathlib import Path

    from badminton.config import MODEL_MANIFEST

    assets = Path(MODEL_MANIFEST).parent / "assets"
    metadata = json.loads((assets / "stroke_side_v1.json").read_text())
    name = f"stroke_side_v1-{metadata['checkpoint_sha256'][:16]}.pt"
    (tmp_path / name).write_bytes((assets / "stroke_side_v1.pt").read_bytes())
    metadata["weights_name"] = name
    (tmp_path / "stroke_side_v1.json").write_text(json.dumps(metadata))
    assert load_side_predictor("cpu", weights=tmp_path) is not None
    metadata["weights_name"] = "../outside.pt"
    (tmp_path / "stroke_side_v1.json").write_text(json.dumps(metadata))
    with pytest.raises(RuntimeError, match="invalid checkpoint name"):
        load_side_predictor("cpu", weights=tmp_path)
