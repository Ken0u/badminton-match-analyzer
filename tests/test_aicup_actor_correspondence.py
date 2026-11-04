"""Generated source/geometry controls; no scientific images or models opened."""

import copy
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest
from badminton import aicup_actor_correspondence as actor
from badminton import aicup_pose_pilot as producer
from test_aicup_pose_pilot import integrated_inputs as integrated_inputs
from test_aicup_pose_pilot import pose_case, prepare_generated


def person(identity, x=20, y=70, height=40):
    return {
        "track_id": identity,
        "box": [x - 5, y - height, x + 5, y],
        "keypoints": [[x, y, 0.9] for _ in range(17)],
    }


def case():
    reference = {
        "id": "generated:1",
        "clip_key": "train:00001",
        "source_contact_frame": 1,
        "family": "clear",
        "side": "forehand",
        "raw": {
            "HitterLocationX": "20",
            "HitterLocationY": "70",
            "DefenderLocationX": "80",
            "DefenderLocationY": "70",
        },
    }
    frames = [
        {
            "frame": i,
            "players": [person(1), person(2, 80)],
            "camera_segment_start_frame": 0,
            "calibration_valid": True,
        }
        for i in range(2)
    ]
    return reference, {"frames": frames}, {"width": 100, "height": 80}


def test_fixed_protocol_and_import_without_learning_runtime():
    root = Path(actor.__file__).resolve().parents[2]
    assert (
        actor.read_json(
            root / "data/manifests/aicup_actor_correspondence_protocol_v1.json"
        )
        == actor.PROTOCOL
    )
    assert (
        actor.PROTOCOL["real_fits"],
        actor.PROTOCOL["native_passes"],
        actor.PROTOCOL["image_bytes"],
    ) == (0, 0, 0)
    script = "from badminton import aicup_actor_correspondence; import sys; assert 'torch' not in sys.modules; assert 'ultralytics' not in sys.modules"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "backend")
    subprocess.run(
        [sys.executable, "-B", "-c", script], env=env, check=True, capture_output=True
    )


def test_pair_requires_two_frames_and_both_representations():
    result = actor.diagnose(*case())
    assert result["weak_pair"] == {"hitter": 1, "defender": 2}
    assert result["published_interval"] == [0, 1]
    assert len(result["endpoints"]) == 2 and not result["reasons"]
    assert (
        result["correct_hitter"] is None and result["source_scene_truth"] == "unknown"
    )
    assert not result["training_ready"]


@pytest.mark.parametrize("mutation", ["family", "side", "landing", "A/B", "winner"])
def test_matching_is_blind_to_class_side_landing_actor_and_winner(mutation):
    reference, result, video = case()
    before = actor.diagnose(reference, result, video)
    if mutation in ("family", "side"):
        reference[mutation] = "unknown"
    else:
        reference["raw"].update(
            LandingX="nan", LandingY="999999", Hitter="B", Winner="A"
        )
    assert actor.diagnose(reference, result, video) == before


@pytest.mark.parametrize("frame", [0, -1, 2, None, True])
def test_censored_and_unavailable_intervals_stay_in_denominator(frame):
    reference, result, video = case()
    reference["source_contact_frame"] = frame
    d = actor.diagnose(reference, result, video)
    assert d["weak_pair"] is None and not d["interval_available"] and not d["endpoints"]


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("", "missing_or_invalid_coordinate"),
        (None, "missing_or_invalid_coordinate"),
        (True, "missing_or_invalid_coordinate"),
        ("NaN", "nonfinite_coordinate"),
        ("inf", "nonfinite_coordinate"),
        ("-1", "coordinate_outside_display"),
        ("100", "coordinate_outside_display"),
    ],
)
def test_invalid_coordinate_preserves_unknown(value, reason):
    reference, result, video = case()
    reference["raw"]["HitterLocationX"] = value
    d = actor.diagnose(reference, result, video)
    assert d["weak_pair"] is None and "hitter:" + reason in d["reasons"]
    assert d["coordinates"]["hitter"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "one_player",
        "no_players",
        "missing_id",
        "duplicate_id",
        "zero_height",
        "nan_box",
        "missing_ankles",
        "weak_ankles",
        "out_ankle",
        "nan_ankle",
        "tie",
        "remote",
        "representation",
        "endpoint",
        "same_actor",
        "cut",
        "calibration",
    ],
)
def test_ambiguous_missing_or_conflicting_observations_never_force_a_pair(mutation):
    reference, result, video = case()
    frames = result["frames"]
    for f in frames:
        a, b = f["players"]
        if mutation == "one_player":
            f["players"] = [a]
        elif mutation == "no_players":
            f["players"] = []
        elif mutation == "missing_id":
            a["track_id"] = None
        elif mutation == "duplicate_id":
            b["track_id"] = 1
        elif mutation == "zero_height":
            a["box"][1] = a["box"][3]
        elif mutation == "nan_box":
            a["box"][1] = float("nan")
        elif mutation == "missing_ankles":
            a["keypoints"] = []
        elif mutation == "weak_ankles":
            for i in (15, 16):
                a["keypoints"][i][2] = 0.1
        elif mutation == "out_ankle":
            a["keypoints"][15][0] = 1000
        elif mutation == "nan_ankle":
            a["keypoints"][15][0] = float("nan")
        elif mutation == "tie":
            f["players"] = [person(1, 10), person(2, 30)]
        elif mutation == "remote":
            for p in f["players"]:
                p["box"][1] = p["box"][3] - 5
            reference["raw"]["HitterLocationY"] = "0"
        elif mutation == "representation":
            a["keypoints"], b["keypoints"] = b["keypoints"], a["keypoints"]
        elif mutation == "same_actor":
            reference["raw"].update(DefenderLocationX="20")
    if mutation == "endpoint":
        frames[1]["players"][0]["track_id"] = 3
    elif mutation == "cut":
        frames[1]["camera_segment_start_frame"] = 1
    elif mutation == "calibration":
        frames[1]["calibration_valid"] = False
    d = actor.diagnose(reference, result, video)
    assert d["weak_pair"] is None and d["reasons"]
    assert len(d["endpoints"]) == 2 and not d["training_ready"]


def test_exact_distance_and_margin_boundaries_and_order_independence():
    candidates = [
        {"track_id": 1, "height": 10, "ankle": [[0, 0]]},
        {"track_id": 2, "height": 10, "ankle": [[12.5, 0]]},
    ]
    ranked = actor.rank([5, 0], candidates, "ankle")
    assert ranked["candidate_track"] == 1
    assert [r["normalized_distance"] for r in ranked["distances"]] == [0.5, 0.75]
    assert actor.rank([5, 0], list(reversed(candidates)), "ankle") == ranked
    assert actor.rank([5.001, 0], candidates, "ankle")["candidate_track"] is None


def test_distances_use_each_candidates_height_and_keep_all_candidates():
    candidates = [
        {"track_id": 1, "height": 10, "ankle": [[3, 0]]},
        {"track_id": 2, "height": 20, "ankle": [[4, 0]]},
        {"track_id": 3, "height": 10, "ankle": [[30, 0]]},
    ]
    result = actor.rank([0, 0], candidates, "ankle")
    assert [r["track_id"] for r in result["distances"]] == [2, 1, 3]
    assert result["candidate_track"] is None and "small_margin" in result["reasons"]


@pytest.mark.parametrize(
    "mutation",
    ["pts", "time", "origin", "rotation", "dimensions", "count", "order", "fraction"],
)
def test_native_clocks_reject_conflicts(mutation):
    _, video, times, _, ledger = pose_case()
    if mutation == "pts":
        ledger["rows"][1]["pts"] += 1
    elif mutation == "time":
        times[1] += 0.01
    elif mutation == "origin":
        ledger["origin_pts"] += 1
    elif mutation == "rotation":
        ledger["rotation"] = 90
    elif mutation == "dimensions":
        ledger["display_dimensions"] = [80, 100]
    elif mutation == "count":
        ledger["rows"].pop()
    elif mutation == "order":
        ledger["rows"][1]["frame"] = 2
    else:
        ledger["rows"][1]["time_base"] = [-1, 3000]
    with pytest.raises(ValueError):
        actor.validate_clocks(video, ledger, times)


def test_native_clock_preserves_vfr_origin_and_rational_precision():
    _, video, times, _, ledger = pose_case()
    actor.validate_clocks(video, ledger, times)


@pytest.fixture
def original_generated(integrated_inputs, monkeypatch):
    workspace, paths, protocol_path, calls = integrated_inputs
    # A real test-fold sentinel is present in the same original archive/index.
    # The consumer may inspect split metadata but must never open its contents.
    test_clip = {
        "source_partition": "train",
        "source_clip_id": "00002",
        "media_path": "part1/train/00002/00002.mp4",
        "media_bytes": 7,
        "media_sha256": "d" * 64,
        "label_path": "part1/train/00002/00002_S2.csv",
        "label_sha256": "e" * 64,
    }
    with zipfile.ZipFile(paths["archive"], "a") as archive:
        archive.writestr(test_clip["label_path"], b"FORBIDDEN TEST TARGETS")
        archive.writestr(test_clip["media_path"], b"FORBIDDEN TEST MEDIA")
    clips = actor.read_json(paths["clips"])
    clips.append(test_clip)
    paths["clips"].write_bytes(producer.encoded(clips))
    groups = actor.read_json(paths["groups"])
    groups["source_groups"].append(
        {"id": "heldout sentinel", "fold": "test", "members": ["train:00002"]}
    )
    groups.update(
        source_archive_sha256=actor.digest(paths["archive"]),
        source_clip_index_sha256=actor.digest(paths["clips"]),
    )
    paths["groups"].write_bytes(producer.encoded(groups))
    producer_protocol = copy.deepcopy(producer.PROTOCOL)
    producer_protocol["sources"] = {
        key: actor.digest(path) for key, path in paths.items()
    }
    monkeypatch.setattr(producer, "PROTOCOL", producer_protocol)
    protocol_path.write_bytes(producer.encoded(producer_protocol))
    prepared, sha = prepare_generated(integrated_inputs)
    native = workspace / ".cache/native"
    producer.run(workspace, prepared, sha, native)
    protocol = copy.deepcopy(actor.PROTOCOL)
    protocol.update(
        preparation_sha256=producer.digest(prepared / "freeze.json"),
        completion_sha256=producer.digest(native / "completion.json"),
        expected={"clips": 1, "native_frames": 3, "references": 3},
    )
    monkeypatch.setattr(actor, "PROTOCOL", protocol)
    return workspace, prepared, native, paths, calls


def test_complete_original_validation_without_new_inference_or_current_glob_equality(
    original_generated, monkeypatch
):
    _, prepared, native, _, calls = original_generated
    monkeypatch.setattr(
        producer,
        "code_seals",
        lambda: pytest.fail("Historical producer inventory replaced with later glob"),
    )
    monkeypatch.setattr(
        producer, "runtime", lambda: pytest.fail("Model runtime imported")
    )
    observations = actor.load_inputs(prepared, native)
    assert len(observations) == 1 and len(observations[0][3]) == 3 and len(calls) == 1


@pytest.mark.parametrize(
    "mutation",
    ["coordinate", "target", "order", "missing", "extra", "duplicate", "fold"],
)
def test_canonical_source_binding_refuses_resealed_cohort_corruption(
    original_generated, mutation
):
    _, prepared, _, _, _ = original_generated
    freeze = actor.read_json(prepared / "freeze.json")
    cohort = actor.read_json(prepared / "cohort.json")
    if mutation == "coordinate":
        cohort["reference_rows"][0]["raw"]["HitterLocationX"] = "999"
    elif mutation == "target":
        cohort["reference_rows"][1]["family"] = "drive"
        cohort["reference_rows"][1]["raw"]["BallType"] = "4"
    elif mutation == "order":
        cohort["reference_rows"].reverse()
    elif mutation == "missing":
        cohort["reference_rows"].pop()
    elif mutation == "extra":
        cohort["reference_rows"].append(copy.deepcopy(cohort["reference_rows"][0]))
    elif mutation == "duplicate":
        cohort["reference_rows"][1]["id"] = cohort["reference_rows"][0]["id"]
    else:
        freeze["clips"][0]["fold"] = "test"
    with pytest.raises(ValueError):
        actor.canonical_cohort(freeze, cohort)


def test_canonical_loader_never_opens_test_csv_or_media(
    original_generated, monkeypatch
):
    _, prepared, _, _, _ = original_generated
    freeze = actor.read_json(prepared / "freeze.json")
    cohort = actor.read_json(prepared / "cohort.json")
    opened = []
    original = zipfile.ZipFile.open

    def guarded(self, name, *args, **kwargs):
        value = name.filename if hasattr(name, "filename") else name
        assert value.endswith("_S2.csv") and "00001" in value
        opened.append(value)
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", guarded)
    actor.canonical_cohort(freeze, cohort)
    assert len(opened) == 1


@pytest.mark.parametrize(
    "mutation",
    ["source", "native", "inventory", "code", "completion", "annotation", "job"],
)
def test_original_input_and_store_mutation_refused(
    original_generated, monkeypatch, mutation
):
    workspace, prepared, native, paths, _ = original_generated
    if mutation == "source":
        paths["archive"].write_bytes(b"changed")
    elif mutation == "native":
        (native / "clip-00/players.json").write_bytes(b"changed")
    elif mutation == "inventory":
        (prepared / "extra.json").write_bytes(b"{}")
    elif mutation == "code":
        freeze = actor.read_json(prepared / "freeze.json")
        with pytest.raises(ValueError):
            actor.verify_producer_code(
                dict(freeze["code"], **{"aicup_data.py": "0" * 64})
            )
        return
    elif mutation == "completion":
        (native / "completion.json").write_bytes(b"{}")
    elif mutation == "annotation":
        monkeypatch.setattr(producer, "annotation_snapshot", lambda _: "changed")
    else:
        import sqlite3

        completion = actor.read_json(native / "completion.json")
        with sqlite3.connect(workspace / "data/processed/catalog.sqlite3") as db:
            db.execute(
                "UPDATE jobs SET document=? WHERE id=?",
                (json.dumps({"status": "running"}), completion["job_id"]),
            )
    with pytest.raises(ValueError):
        actor.load_inputs(prepared, native)


@pytest.fixture
def generated_freeze(original_generated, monkeypatch):
    workspace, prepared, native, _, calls = original_generated
    protocol = workspace / "protocol-actor.json"
    producer.publish(protocol, actor.PROTOCOL)
    folder = workspace / ".cache/prospective"
    with monkeypatch.context() as guarded:
        guarded.setattr(
            actor,
            "diagnose",
            lambda *_: pytest.fail("Geometry executed before prospective freeze"),
        )
        receipt = actor.freeze(
            workspace,
            prepared,
            native,
            protocol,
            time.time() - 1,
            time.time() + 300,
            folder,
        )
    return (
        workspace,
        prepared,
        native,
        folder / "prospective.json",
        receipt["prospective_sha256"],
        calls,
    )


def test_freeze_does_not_run_geometry_and_audit_verifies_after_deadline(
    generated_freeze, monkeypatch
):
    workspace, _, _, plan, sha, calls = generated_freeze
    assert actor.read_json(plan)["audit_executed"] is False
    output = workspace / ".cache/audit"
    summary = actor.audit(plan, sha, output)
    assert summary["references"] == 3 and summary["weak_pairs"] == 0
    assert len(calls) == 1
    monkeypatch.setattr(actor.time, "time", lambda: 10**12)
    assert actor.verify(plan, sha, output)["verified_references"] == 3
    rows = actor.read_json(output / "diagnostics.json")
    assert [r["reference_id"] for r in rows] == [
        r["id"]
        for r in actor.read_json(workspace / ".cache/prepared/cohort.json")[
            "reference_rows"
        ]
    ]
    assert sum(not r["interval_available"] for r in rows) == 2
    assert all(not r["training_ready"] for r in rows)


def test_second_output_or_second_freeze_cannot_repeat_consumed_audit(generated_freeze):
    workspace, _, _, plan, sha, _ = generated_freeze
    actor.audit(plan, sha, workspace / ".cache/audit")
    alternate = workspace / ".cache/alternate-plan"
    alternate.mkdir()
    (alternate / "prospective.json").write_bytes(plan.read_bytes())
    with pytest.raises(FileExistsError):
        actor.audit(
            alternate / "prospective.json", sha, workspace / ".cache/alternate-audit"
        )


def test_failed_audit_preserves_partial_and_consumes_claim(
    generated_freeze, monkeypatch
):
    workspace, _, _, plan, sha, _ = generated_freeze
    monkeypatch.setattr(
        actor,
        "load_inputs",
        lambda *_: (_ for _ in ()).throw(ValueError("generated failure")),
    )
    output = workspace / ".cache/audit"
    with pytest.raises(ValueError):
        actor.audit(plan, sha, output)
    assert actor.read_json(output / "failure.json")["original_audit_consumed"]
    with pytest.raises(FileExistsError):
        actor.audit(plan, sha, workspace / ".cache/replacement")


@pytest.mark.parametrize("mutation", ["code", "protocol", "hash", "deadline", "budget"])
def test_consumer_changes_and_limits_refuse_audit(
    generated_freeze, monkeypatch, mutation
):
    workspace, _, _, plan, sha, _ = generated_freeze
    if mutation == "code":
        monkeypatch.setattr(actor, "code_seals", lambda: {})
    elif mutation == "protocol":
        monkeypatch.setattr(actor, "PROTOCOL", dict(actor.PROTOCOL, name="different"))
    elif mutation == "hash":
        sha = "0" * 64
    elif mutation == "deadline":
        monkeypatch.setattr(actor.time, "time", lambda: 10**12)
    else:
        monkeypatch.setattr(
            actor,
            "total_budget",
            lambda *_: (_ for _ in ()).throw(ValueError("budget")),
        )
    with pytest.raises(ValueError):
        actor.audit(plan, sha, workspace / ".cache/audit")


def test_private_output_and_original_source_preservation(generated_freeze):
    workspace, prepared, native, plan, sha, _ = generated_freeze
    before = (producer.inventory(prepared), producer.inventory(native))
    with pytest.raises(ValueError):
        actor.audit(plan, sha, prepared / "injected")
    with pytest.raises(ValueError):
        actor.audit(plan, sha, native / "injected")
    with pytest.raises(ValueError):
        actor.audit(plan, sha, workspace / "public-output")
    protocol = workspace / "protocol-actor.json"
    for target in (prepared / "prospective", native / "prospective"):
        with pytest.raises(ValueError):
            actor.freeze(
                workspace,
                prepared,
                native,
                protocol,
                time.time() - 1,
                time.time() + 300,
                target,
            )
    actor.audit(plan, sha, workspace / ".cache/audit")
    assert before == (producer.inventory(prepared), producer.inventory(native))


def test_resealed_diagnostics_cannot_become_truth(generated_freeze):
    workspace, _, _, plan, sha, _ = generated_freeze
    output = workspace / ".cache/audit"
    actor.audit(plan, sha, output)
    rows = actor.read_json(output / "diagnostics.json")
    rows[0]["correct_hitter"] = "fabricated"
    (output / "diagnostics.json").write_bytes(producer.encoded(rows))
    completion = actor.read_json(output / "completion.json")
    completion["artifacts"]["diagnostics.json"] = producer.digest(
        output / "diagnostics.json"
    )
    (output / "completion.json").write_bytes(producer.encoded(completion))
    with pytest.raises(ValueError, match="reproduce"):
        actor.verify(plan, sha, output)


def test_source_change_during_audit_preserves_failure_and_original_claim(
    generated_freeze, monkeypatch
):
    workspace, prepared, _, plan, sha, _ = generated_freeze
    original = actor.diagnose
    mutated = False

    def mutate_after_first_read(*args):
        nonlocal mutated
        if not mutated:
            (prepared / "clip-00/source.mp4").write_bytes(b"changed during diagnostic")
            mutated = True
        return original(*args)

    monkeypatch.setattr(actor, "diagnose", mutate_after_first_read)
    output = workspace / ".cache/audit"
    with pytest.raises(ValueError):
        actor.audit(plan, sha, output)
    assert (output / "diagnostics.json").is_file()
    assert (output / "failure.json").is_file()
    assert not (output / "completion.json").exists()
    with pytest.raises(FileExistsError):
        actor.audit(plan, sha, workspace / ".cache/replacement")


@pytest.mark.parametrize(
    ("start", "end"), [(0, 1), (1, 1), (True, 2), (float("nan"), 2), (1, 20000)]
)
def test_deadline_requires_original_bounded_fresh_window(start, end, monkeypatch):
    monkeypatch.setattr(actor.time, "time", lambda: 1.5)
    with pytest.raises(ValueError):
        actor.check_deadline(start, end)


def test_aggregate_keeps_all_unknown_rows_and_denominators():
    ref, result, video = case()
    second = copy.deepcopy(ref)
    second.update(
        id="unknown", source_contact_frame=0, family="unknown", side="unknown"
    )
    observations = [
        ({"fold": "train", "context": "generated"}, video, result, [ref, second])
    ]
    diagnostics = [actor.diagnose(r, result, video) for r in (ref, second)]
    summary = actor.aggregate(observations, diagnostics)
    assert summary["groups"]["all"] == {
        "references": 2,
        "available_intervals": 1,
        "weak_pairs": 1,
        "unresolved_pairs": 1,
        "training_ready": 0,
        **{"reason:" + r: 1 for r in diagnostics[1]["reasons"]},
    }
    assert summary["groups"]["family:unknown"]["references"] == 1
    assert summary["groups"]["side:unknown"]["references"] == 1
    with pytest.raises(ValueError):
        actor.aggregate(observations, diagnostics[:1])
