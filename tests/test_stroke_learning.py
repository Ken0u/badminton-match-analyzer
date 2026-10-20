"""Generated-input guards and training semantics, without external research data."""

import copy
import hashlib
from pathlib import Path

import numpy as np
import pytest
from badminton import stroke_learning as learning


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    protocol = copy.deepcopy(learning.PROTOCOL)
    for group in protocol["groups"].values():
        group.update(clips=2, rows=6, available=5)
    protocol["training"].update(epochs=2, evaluate_every=1, minimum_threshold_support=2)
    plan = {
        "source_dataset_commit": protocol["source_commit"],
        "sources": {
            str(g["match_id"]): {"id": g["source_id"]}
            for g in protocol["groups"].values()
        },
        "clips": [],
    }
    features = tmp_path / "features"
    features.mkdir()
    recipe = b'{"generated_features":true}\n'
    catalog = b"id,name\n1,training-original\n2,validation-original\n"
    protocol["source_catalog_git_blob"] = hashlib.sha1(
        b"blob " + str(len(catalog)).encode() + b"\0" + catalog
    ).hexdigest()
    protocol["feature_recipe_sha256"] = learning.digest(recipe)
    (features / "recipe.json").write_bytes(recipe)
    (tmp_path / "Match.csv").write_bytes(catalog)
    rng = np.random.default_rng(7)
    for split, group in protocol["groups"].items():
        match = group["match_id"]
        for rally in (1, 2):
            request = {
                "match_id": match,
                "set_id": 1,
                "rally_id": rally,
                "score_key": str(rally),
                "split": split,
                "published_strokes": 3,
            }
            plan["clips"].append(request)
            path = features / f"match{match}-{rally}.npz"
            available = np.array([True, True, rally == 1])
            family, side = np.array([0, 1, 2]), np.array([0, 1, 0])
            np.savez_compressed(
                path,
                features=rng.normal(size=(3, 371)).astype(np.float32),
                available=available,
                family=family,
                side=side,
            )
            records = [
                {
                    "id": f"s2doubles:{match}:1:{rally}:{i}",
                    "features_available": bool(available[i]),
                    "family_target": learning.FAMILIES[family[i]],
                    "side_target": learning.SIDES[side[i]],
                    "exact_truth": False,
                }
                for i in range(3)
            ]
            meta = {
                "request": request,
                "source_sha256": learning.digest(f"source-{match}-{rally}".encode()),
                "features_sha256": learning.digest(path.read_bytes()),
                "records": records,
                "exact_truth": False,
            }
            path.with_suffix(".json").write_bytes(learning.encoded(meta))
    raw_plan = learning.encoded(plan)
    protocol["source_plan_sha256"] = learning.digest(raw_plan)
    (tmp_path / "plan.json").write_bytes(raw_plan)
    (tmp_path / "protocol.json").write_bytes(learning.encoded(protocol))
    monkeypatch.setattr(learning, "PROTOCOL", protocol)
    manifest = tmp_path / "manifest.json"
    learning.prepare(
        tmp_path,
        tmp_path / "plan.json",
        features,
        tmp_path / "Match.csv",
        tmp_path / "protocol.json",
        manifest,
    )
    return tmp_path, manifest


def load(corpus):
    root, manifest = corpus
    raw = manifest.read_bytes()
    return learning.audit(root, raw, learning.digest(raw))


def rewrite_clip(corpus, index, *, arrays=None, change=None):
    root, path = corpus
    manifest = learning.read_json(path.read_bytes())
    entry = manifest["clips"][index]
    meta_path = root / entry["metadata"]["path"]
    feature_path = root / entry["features"]["path"]
    meta = learning.read_json(meta_path.read_bytes())
    if arrays:
        with np.load(feature_path, allow_pickle=False) as archive:
            values = {key: archive[key] for key in archive.files}
        arrays(values, meta)
        np.savez_compressed(feature_path, **values)
        meta["features_sha256"] = learning.digest(feature_path.read_bytes())
        entry["features"] = learning.seal(root, feature_path)
    if change:
        change(meta)
    meta_path.write_bytes(learning.encoded(meta))
    entry["metadata"] = learning.seal(root, meta_path)
    path.write_bytes(learning.encoded(manifest))


def test_public_protocol_matches_fixed_recipe():
    path = (
        Path(__file__).resolve().parents[1]
        / "data/manifests/portable_stroke_training_v1.json"
    )
    assert learning.read_json(path.read_bytes()) == learning.PROTOCOL
    assert learning.PROTOCOL["training"]["epochs"] == 300
    assert learning.PROTOCOL["training"]["seed"] == 20261018


def test_complete_audit_and_immutable_manifest_creation(corpus):
    data, proof = load(corpus)
    assert len(data["train"]["features"]) == 6
    assert proof["counts"]["validation"]["available"] == 5
    assert proof["counts"]["train"]["unknown_family"] == 0
    root, manifest = corpus
    before = manifest.read_bytes()
    with pytest.raises(FileExistsError):
        learning.prepare(
            root,
            root / "plan.json",
            root / "features",
            root / "Match.csv",
            root / "protocol.json",
            manifest,
        )
    assert manifest.read_bytes() == before


@pytest.mark.parametrize(
    "key",
    ["protocol", "plan", "source_catalog", "feature_recipe", "metadata", "features"],
)
def test_changed_input_bytes_fail_closed(corpus, key):
    root, manifest_path = corpus
    manifest = learning.read_json(manifest_path.read_bytes())
    entry = manifest[key] if key in manifest else manifest["clips"][0][key]
    path = root / entry["path"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="Changed sealed"):
        load(corpus)


def test_changed_manifest_digest(corpus):
    root, path = corpus
    with pytest.raises(ValueError, match="Changed input manifest"):
        learning.audit(root, path.read_bytes(), "0" * 64)


@pytest.mark.parametrize(
    "path",
    ["../outside.json", "/outside.json", "C:/outside.json", "features\\file.json"],
)
def test_manifest_path_escape(corpus, path):
    _root, manifest_path = corpus
    manifest = learning.read_json(manifest_path.read_bytes())
    manifest["clips"][0]["metadata"]["path"] = path
    manifest_path.write_bytes(learning.encoded(manifest))
    with pytest.raises(ValueError, match="path"):
        load(corpus)


def test_duplicate_json_keys_are_not_reinterpreted():
    with pytest.raises(ValueError, match="Duplicate JSON"):
        learning.read_json(b'{"schema_version":1,"schema_version":2}')


@pytest.mark.parametrize(
    "edit",
    [
        lambda m: m["clips"].pop(),
        lambda m: m["clips"].reverse(),
        lambda m: m["clips"][0].update(request={}),
    ],
)
def test_incomplete_or_substituted_split(corpus, edit):
    _, path = corpus
    manifest = learning.read_json(path.read_bytes())
    edit(manifest)
    path.write_bytes(learning.encoded(manifest))
    with pytest.raises(ValueError, match=r"Incomplete|membership"):
        load(corpus)


@pytest.mark.parametrize(
    "change",
    [
        lambda m: m["records"][1].update(id=m["records"][0]["id"]),
        lambda m: m["records"][0].update(id="s2doubles:1:1:999:0"),
        lambda m: m["records"].pop(),
        lambda m: m["records"][0].update(features_available=False),
        lambda m: m["records"][0].update(family_target="drive"),
    ],
)
def test_invalid_record_identity_availability_and_labels(corpus, change):
    rewrite_clip(corpus, 0, change=change)
    with pytest.raises(ValueError, match=r"identity|records|availability|Targets"):
        load(corpus)


@pytest.mark.parametrize(
    "key,value",
    [
        ("features", np.full((3, 371), np.nan, np.float32)),
        ("features", np.zeros((3, 371), np.float64)),
        ("available", np.ones(3, np.int64)),
        ("family", np.array([-2, 1, 2])),
        ("side", np.array([0.0, 1.0, 0.0])),
    ],
)
def test_nonfinite_wrong_type_and_out_of_range_arrays(corpus, key, value):
    rewrite_clip(corpus, 0, arrays=lambda arrays, _meta: arrays.update({key: value}))
    with pytest.raises(ValueError, match="Invalid"):
        load(corpus)


def test_original_source_and_clip_bytes_cannot_overlap_splits(corpus, monkeypatch):
    root, path = corpus
    manifest = learning.read_json(path.read_bytes())
    original = learning.read_json(
        (root / manifest["clips"][0]["metadata"]["path"]).read_bytes()
    )
    rewrite_clip(
        corpus, 2, change=lambda m: m.update(source_sha256=original["source_sha256"])
    )
    with pytest.raises(ValueError, match="Source bytes overlap"):
        load(corpus)
    protocol = copy.deepcopy(learning.PROTOCOL)
    protocol["groups"]["validation"]["source_id"] = protocol["groups"]["train"][
        "source_id"
    ]
    monkeypatch.setattr(learning, "PROTOCOL", protocol)
    with pytest.raises(ValueError, match="source groups overlap"):
        learning.expected_requests(
            learning.read_json((root / "plan.json").read_bytes())
        )


def test_unknown_truth_and_unavailable_input_remain_distinct(corpus):
    def unknown(arrays, meta):
        arrays["family"][0] = -1
        meta["records"][0]["family_target"] = None

    rewrite_clip(corpus, 2, arrays=unknown)
    data, proof = load(corpus)
    validation = data["validation"]
    probabilities = []
    for key, size in (("family", 8), ("side", 2)):
        values = np.zeros((6, size))
        values[np.arange(6), np.maximum(validation[key], 0)] = 1
        probabilities.append(values)
    result = learning.evaluate(validation, probabilities)
    assert proof["counts"]["validation"]["unknown_family"] == 1
    assert result["source_rows"] == 6 and result["available_rows"] == 5
    assert result["family"]["source_rows"] == 5
    assert result["family"]["strict_accuracy"] == 4 / 5
    assert result["side"]["source_rows"] == 6
    assert result["side"]["strict_accuracy"] == 5 / 6
    assert result["family_side_tuple_given_weak_source_hitter_clock"] == 4 / 5


def test_thresholds_retain_disabled_classes_and_ignore_unknowns(corpus):
    data, _ = load(corpus)
    data = data["validation"]
    probabilities = [np.zeros((6, 8)), np.zeros((6, 2))]
    for values in probabilities:
        values[:, 0] = 0.95
    data["family"][:] = 0
    data["side"][:] = 0
    config = copy.deepcopy(learning.PROTOCOL["training"])
    limits, evidence = learning.select_thresholds(data, probabilities, config)
    assert limits[0][0] == 0.95 and evidence[0][0]["validation_accepted"] == 5
    assert limits[0][1:] == [1.01] * 7
    data["family"][:] = -1
    limits, evidence = learning.select_thresholds(data, probabilities, config)
    assert limits[0] == [1.01] * 8
    assert not any(row["enabled"] for row in evidence[0])


def test_fit_partial_labels_determinism_and_training_only_normalization(corpus):
    torch = pytest.importorskip("torch")
    data, _ = load(corpus)
    train, validation = data["train"], data["validation"]
    train["family"][[0, 3]] = -1
    train["side"][[1, 4]] = -1
    before_threads, before_rng = torch.get_num_threads(), torch.get_rng_state().clone()
    checkpoint, result = learning.fit(train, validation, lambda *_: None)
    repeated, repeated_result = learning.fit(train, validation, lambda *_: None)
    assert result == repeated_result
    assert all(
        torch.equal(value, repeated["state_dict"][key])
        for key, value in checkpoint["state_dict"].items()
    )
    assert result["training_known"] == {"family": 3, "side": 3}
    np.testing.assert_array_equal(
        checkpoint["mean"].numpy(), train["features"][train["available"]].mean(0)
    )
    changed = {**validation, "features": validation["features"] * 1000 + 1000}
    other, _ = learning.fit(train, changed, lambda *_: None)
    assert torch.equal(checkpoint["mean"], other["mean"])
    assert torch.equal(checkpoint["std"], other["std"])
    assert torch.get_num_threads() == before_threads
    assert torch.equal(torch.get_rng_state(), before_rng)


def test_selection_ties_prefer_earlier_epoch(corpus, monkeypatch):
    pytest.importorskip("torch")
    protocol = copy.deepcopy(learning.PROTOCOL)
    protocol["training"]["learning_rate"] = 0.0
    monkeypatch.setattr(learning, "PROTOCOL", protocol)
    data, _ = load_without_protocol_reaudit(corpus)
    _, result = learning.fit(data["train"], data["validation"], lambda *_: None)
    assert result["epoch"] == 1


def load_without_protocol_reaudit(corpus):
    # This fixture helper reads the already-audited original generated arrays;
    # it is used only when testing a deliberately modified in-memory trainer.
    root, path = corpus
    manifest = learning.read_json(path.read_bytes())
    chunks = {split: [] for split in ("train", "validation")}
    for entry in manifest["clips"]:
        with np.load(root / entry["features"]["path"], allow_pickle=False) as archive:
            chunks[entry["split"]].append({key: archive[key] for key in archive.files})
    return {
        split: {key: np.concatenate([c[key] for c in values]) for key in values[0]}
        for split, values in chunks.items()
    }, None


def workspace(corpus, monkeypatch):
    from badminton import config

    root, _ = corpus
    main = root / "workspace"
    (main / "data/processed").mkdir(parents=True)
    (main / "data/processed/catalog.sqlite3").touch()
    (main / "AGENTS.md").write_text("Generated workspace", encoding="utf-8")
    monkeypatch.setattr(config, "ROOT", main)
    monkeypatch.setattr(config, "DATA", main / "data/processed")
    monkeypatch.setenv("BADMINTON_ROOT", str(main))
    monkeypatch.setenv("BADMINTON_DATA_DIR", str(main / "data/processed"))
    return main


def test_real_main_admission_denial_precedes_training(corpus, monkeypatch):
    from badminton import storage

    main = workspace(corpus, monkeypatch)

    class Denied:
        def __init__(self, data):
            assert data == main / "data/processed"

        def claim_job(self, _job):
            raise RuntimeError("Real main admission denied")

    monkeypatch.setattr(storage, "Store", Denied)
    monkeypatch.setattr(
        learning, "fit", lambda *_: pytest.fail("Training bypassed admission")
    )
    root, manifest = corpus
    output = main / ".cache/output"
    with pytest.raises(RuntimeError, match="admission denied"):
        learning.train(
            main, root, manifest, learning.digest(manifest.read_bytes()), output
        )
    assert not (output / "selected.pt").exists()
    assert not (output / "completed.json").exists()


def test_completion_follows_successful_main_release_and_outputs_never_overwrite(
    corpus, monkeypatch
):
    torch = pytest.importorskip("torch")
    from badminton import storage

    main = workspace(corpus, monkeypatch)
    root, manifest = corpus
    output = main / ".cache/output"
    completed = []

    class Main:
        def __init__(self, data):
            assert data == main / "data/processed"

        def claim_job(self, _job):
            pass

        def put_job(self, job):
            if job["status"] == "completed":
                assert not (output / "completed.json").exists()
                completed.append(job["id"])

    def fake_fit(_train, _validation, progress):
        progress(1, 1)
        return {"state_dict": {"value": torch.tensor([1])}}, {"epoch": 1}

    monkeypatch.setattr(storage, "Store", Main)
    monkeypatch.setattr(learning, "fit", fake_fit)
    arguments = (main, root, manifest, learning.digest(manifest.read_bytes()), output)
    learning.train(*arguments)
    proof = learning.read_json((output / "completed.json").read_bytes())
    assert proof["job_id"] == completed[0]
    before = (output / "selected.pt").read_bytes()
    with pytest.raises(FileExistsError):
        learning.train(*arguments)
    assert (output / "selected.pt").read_bytes() == before


def test_inputs_changed_during_training_prevent_model_publication(corpus, monkeypatch):
    pytest.importorskip("torch")
    from badminton import storage

    main = workspace(corpus, monkeypatch)
    root, manifest = corpus
    output = main / ".cache/output"
    statuses = []

    class Main:
        def __init__(self, _data):
            pass

        def claim_job(self, _job):
            pass

        def put_job(self, job):
            statuses.append(job["status"])

    def mutation(*_):
        (root / "features/recipe.json").write_bytes(b"changed")
        return {}, {"epoch": 1}

    monkeypatch.setattr(storage, "Store", Main)
    monkeypatch.setattr(learning, "fit", mutation)
    with pytest.raises(ValueError, match="Changed sealed"):
        learning.train(
            main, root, manifest, learning.digest(manifest.read_bytes()), output
        )
    assert statuses[-1] == "failed"
    assert not (output / "selected.pt").exists()
    assert not (output / "completed.json").exists()
