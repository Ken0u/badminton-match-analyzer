"""Generated development-only capacity and main-admission controls."""

import copy
import time
from pathlib import Path

import numpy as np
import pytest
from badminton import stroke_capacity as capacity
from badminton import stroke_learning as learning


@pytest.fixture
def data():
    rng = np.random.default_rng(81)

    def split(size):
        return {
            "features": rng.normal(size=(size, 371)).astype(np.float32),
            "available": np.arange(size) < size - 2,
            "family": np.arange(size) % 8,
            "side": np.arange(size) % 2,
        }

    return {"train": split(24), "validation": split(20)}


@pytest.fixture
def fast(monkeypatch):
    protocol = copy.deepcopy(capacity.PROTOCOL)
    protocol["training"].update(epochs=3, evaluate_every=1, minimum_threshold_support=2)
    monkeypatch.setattr(capacity, "PROTOCOL", protocol)
    original = copy.deepcopy(learning.PROTOCOL)
    original["training"] = copy.deepcopy(protocol["training"])
    monkeypatch.setattr(learning, "PROTOCOL", original)
    return protocol


def test_committed_protocol_and_original_recipe_are_unchanged():
    path = (
        Path(capacity.__file__).resolve().parents[2]
        / "data/manifests/stroke_capacity_protocol_v2.json"
    )
    assert learning.read_json(path.read_bytes()) == capacity.PROTOCOL
    assert capacity.PROTOCOL["training"] == learning.PROTOCOL["training"]
    assert (
        capacity.code_seals()["stroke_learning.py"]
        == capacity.PROTOCOL["baseline_source_sha256"]
    )
    assert capacity.PROTOCOL["maximum_real_fits"] == 2
    for name, expected in capacity.PROTOCOL["target_source_sha256"].items():
        assert capacity.code_seals()[name] == expected
    historical_path = path.with_name("stroke_capacity_protocol_v1.json")
    assert (
        learning.digest(historical_path.read_bytes())
        == "a1f2d5396c4ab00f188c99bf8fd599036da3aac0be75e5fcd66461a20edc1e77"
    )
    historical = learning.read_json(historical_path.read_bytes())
    assert historical["baseline_source_sha256"] == (
        "745de9212ef0ecf41d47b9ad96426c46741b330e462783baecdcc5c46c700932"
    )
    changed_keys = {
        "schema_version",
        "name",
        "baseline_source_sha256",
        "target_source_sha256",
    }
    assert {k: v for k, v in capacity.PROTOCOL.items() if k not in changed_keys} == {
        k: v for k, v in historical.items() if k not in changed_keys
    }


def test_linear_fit_partial_labels_determinism_normalization_and_rng(data, fast):
    torch = pytest.importorskip("torch")
    data["train"]["family"][[0, 3]] = -1
    data["train"]["side"][[1, 4]] = -1
    before_threads = torch.get_num_threads()
    before_rng = torch.get_rng_state().clone()
    before_numpy = np.random.get_state()
    a, result = capacity.fit_linear(data["train"], data["validation"], lambda *_: None)
    b, repeated = capacity.fit_linear(
        data["train"], data["validation"], lambda *_: None
    )
    assert result == repeated
    assert sum(v.numel() for v in a["state_dict"].values()) == 3720
    assert all(
        torch.equal(value, b["state_dict"][key])
        for key, value in a["state_dict"].items()
    )
    assert result["training_known"] == {"family": 20, "side": 20}
    np.testing.assert_array_equal(
        a["mean"].numpy(), data["train"]["features"][:22].mean(0)
    )
    changed = {**data["validation"], "features": data["validation"]["features"] + 1000}
    c, _ = capacity.fit_linear(data["train"], changed, lambda *_: None)
    assert torch.equal(a["mean"], c["mean"])
    assert torch.equal(a["std"], c["std"])
    assert torch.get_num_threads() == before_threads
    assert torch.equal(torch.get_rng_state(), before_rng)
    np.testing.assert_array_equal(np.random.get_state()[1], before_numpy[1])


def test_unknown_and_unavailable_validation_denominators_remain(data, fast):
    pytest.importorskip("torch")
    data["validation"]["family"][0] = -1
    _, result = capacity.fit_linear(data["train"], data["validation"], lambda *_: None)
    metrics = result["closed_set"]
    assert metrics["source_rows"] == 20
    assert metrics["available_rows"] == 18
    assert metrics["family"]["source_rows"] == 19
    assert metrics["family"]["answered"] == 17
    assert metrics["side"]["source_rows"] == 20
    assert metrics["side"]["answered"] == 18
    assert sum(row["unanswered"] for row in metrics["family"]["matrix"].values()) == 2


def test_missing_training_classes_are_disabled_and_earlier_tie_is_kept(data, fast):
    pytest.importorskip("torch")
    fast["training"]["learning_rate"] = 0.0
    data["train"]["family"][:] %= 2
    checkpoint, result = capacity.fit_linear(
        data["train"], data["validation"], lambda *_: None
    )
    assert result["epoch"] == 1
    assert checkpoint["supported_family"].tolist() == [
        True,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
    ]
    for row in result["closed_set"]["family"]["matrix"].values():
        assert all(row[name] == 0 for name in learning.FAMILIES[2:])


@pytest.mark.parametrize("key", ["available", "family", "side"])
def test_no_usable_training_support_fails(data, fast, key):
    pytest.importorskip("torch")
    data["train"][key][:] = False if key == "available" else -1
    with pytest.raises(ValueError, match=r"No available|No known"):
        capacity.fit_linear(data["train"], data["validation"], lambda *_: None)


@pytest.fixture
def frozen(tmp_path, monkeypatch, data, fast):
    """Small generated seals; original source-audit behavior has its own suite."""
    pytest.importorskip("torch")
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b'{"generated_manifest":true}\n')
    feature = tmp_path / "features.npz"
    feature.write_bytes(b"generated-input-seal")
    fast["input_manifest_sha256"] = learning.digest(manifest.read_bytes())
    protocol = tmp_path / "protocol.json"
    protocol.write_bytes(learning.encoded(fast))

    def audit(root, raw, sha):
        assert learning.digest(raw) == sha
        return copy.deepcopy(data), {
            "seals": [learning.seal(root, feature)],
            "counts": {},
        }

    monkeypatch.setattr(learning, "audit", audit)
    path = tmp_path / "freeze.json"
    result = capacity.freeze(
        tmp_path,
        manifest,
        fast["input_manifest_sha256"],
        protocol,
        time.time() + 1000,
        path,
    )
    main = tmp_path / "workspace"
    (main / "data/processed").mkdir(parents=True)
    (main / "data/processed/catalog.sqlite3").touch()
    (main / "AGENTS.md").write_bytes(b"Generated workspace\n")
    from badminton import config

    monkeypatch.setattr(config, "ROOT", main)
    monkeypatch.setattr(config, "DATA", main / "data/processed")
    monkeypatch.setenv("BADMINTON_ROOT", str(main))
    monkeypatch.setenv("BADMINTON_DATA_DIR", str(main / "data/processed"))
    output = main / ".cache/run"
    return main, tmp_path, path, result["freeze_sha256"], output


def main_store(monkeypatch, frozen, *, deny=False):
    from badminton import storage

    main, _, _, _, output = frozen
    statuses = []

    class Main:
        def __init__(self, path):
            assert path == main / "data/processed"

        def claim_job(self, _job):
            if deny:
                raise RuntimeError("Real shared admission denied")
            statuses.append("running")

        def put_job(self, job):
            statuses.append(job["status"])
            if job["status"] == "completed":
                assert not (output / "completed.json").exists()

    monkeypatch.setattr(storage, "Store", Main)
    return statuses


def test_freeze_and_outputs_are_immutable_and_completion_follows_admission(
    frozen, monkeypatch
):
    statuses = main_store(monkeypatch, frozen)
    main, root, path, sha, output = frozen
    original_protocol = learning.encoded(learning.PROTOCOL)
    result = capacity.run(*frozen)
    assert statuses[0] == "running" and statuses[-1] == "completed"
    assert result["model_installed_in_app"] is False
    assert (
        learning.read_json((output / "completed.json").read_bytes())["job_id"]
        == result["job_id"]
    )
    comparison = learning.read_json((output / "comparison.json").read_bytes())
    assert comparison["variants"]["linear"]["parameters"] == 3720
    assert comparison["variants"]["baseline_mlp"]["parameters"] == 56522
    assert learning.encoded(learning.PROTOCOL) == original_protocol
    before = (output / "linear/selected.pt").read_bytes()
    with pytest.raises(FileExistsError):
        capacity.run(*frozen)
    assert (output / "linear/selected.pt").read_bytes() == before
    with pytest.raises(FileExistsError):
        capacity.freeze(
            root,
            root / "manifest.json",
            capacity.PROTOCOL["input_manifest_sha256"],
            root / "protocol.json",
            time.time() + 1000,
            path,
        )
    # A cross-variant tie preserves the baseline, independent of epoch numbers.
    results = {
        name: learning.read_json((output / name / "validation.json").read_bytes())
        for name in capacity.PROTOCOL["order"]
    }
    results["linear"] = copy.deepcopy(results["baseline_mlp"])
    results["linear"]["epoch"] = 1
    assert capacity.compare(results)["validation_preferred_variant"] == "baseline_mlp"
    assert main.is_dir() and sha


def test_real_shared_admission_denial_precedes_both_fits(frozen, monkeypatch):
    main_store(monkeypatch, frozen, deny=True)
    monkeypatch.setattr(
        learning, "fit", lambda *_: pytest.fail("Training bypassed admission")
    )
    monkeypatch.setattr(
        capacity, "fit_linear", lambda *_: pytest.fail("Training bypassed admission")
    )
    with pytest.raises(RuntimeError, match="admission denied"):
        capacity.run(*frozen)
    assert not (frozen[-1] / "baseline_mlp").exists()
    assert not (frozen[-1] / "completed.json").exists()


@pytest.mark.parametrize(
    "name", ["stroke_learning.py", "datasets.py", "doubles_data.py"]
)
def test_changed_declared_baseline_parser_or_mapping_fails_before_freeze(
    frozen, monkeypatch, name
):
    original = capacity.code_seals()
    monkeypatch.setattr(capacity, "code_seals", lambda: {**original, name: "0" * 64})
    _main, root, _path, _sha, _output = frozen
    path = root / "changed-consumer-freeze.json"
    with pytest.raises(
        ValueError, match=r"Changed fixed baseline|Changed canonical target"
    ):
        capacity.freeze(
            root,
            root / "manifest.json",
            capacity.PROTOCOL["input_manifest_sha256"],
            root / "protocol.json",
            time.time() + 1000,
            path,
        )
    assert not path.exists()


@pytest.mark.parametrize(
    "name", ["manifest.json", "protocol.json", "features.npz", "freeze.json"]
)
def test_changed_frozen_inputs_fail_before_admission(frozen, monkeypatch, name):
    statuses = main_store(monkeypatch, frozen)
    path = frozen[1] / name
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Changed"):
        capacity.run(*frozen)
    assert not statuses
    assert not frozen[-1].exists()


def test_conflicting_imported_configuration_is_rejected(frozen, monkeypatch):
    from badminton import config

    monkeypatch.setattr(config, "DATA", frozen[1] / "another-store")
    with pytest.raises(ValueError, match="before real workspace pins"):
        capacity.run(*frozen)
    assert not frozen[-1].exists()


@pytest.mark.parametrize(
    "mutation",
    ["input", "consumer", "parser", "mapping", "freeze", "deadline", "budget"],
)
def test_mutation_during_fit_fails_without_publishing_a_checkpoint(
    frozen, monkeypatch, mutation
):
    statuses = main_store(monkeypatch, frozen)

    def changed(*args):
        if mutation == "input":
            (frozen[1] / "features.npz").write_bytes(b"changed")
        elif mutation in ("consumer", "parser", "mapping"):
            original = capacity.code_seals()
            name = {
                "consumer": "stroke_capacity.py",
                "parser": "datasets.py",
                "mapping": "doubles_data.py",
            }[mutation]
            monkeypatch.setattr(
                capacity,
                "code_seals",
                lambda: {**original, name: "0" * 64},
            )
        elif mutation == "freeze":
            frozen[2].write_bytes(b"changed")
        elif mutation == "deadline":
            monkeypatch.setattr(capacity.time, "time", lambda: 1e20)
        else:
            monkeypatch.setitem(capacity.PROTOCOL, "maximum_output_bytes", 0)
        args[2](1, 1)
        pytest.fail("Mutation was not rejected")

    monkeypatch.setattr(learning, "fit", changed)
    with pytest.raises(ValueError, match=r"Changed|changed|expired|allowance"):
        capacity.run(*frozen)
    assert statuses[-1] == "failed"
    assert not (frozen[-1] / "baseline_mlp/selected.pt").exists()
    assert not (frozen[-1] / "completed.json").exists()


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), 0])
def test_invalid_or_elapsed_deadlines_fail(deadline):
    with pytest.raises(ValueError, match="deadline"):
        capacity.check_deadline(deadline)


def test_cli_requires_an_explicit_freeze_and_workspace():
    with pytest.raises(SystemExit):
        capacity.main(["run"])
