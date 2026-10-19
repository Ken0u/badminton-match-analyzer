"""Frozen recovery cannot reinterpret incomplete work or mutate source Stores."""

import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import psutil
import pytest

SPEC = importlib.util.spec_from_file_location(
    "recover_frozen_holdout",
    Path(__file__).resolve().parents[1] / "scripts/recover_frozen_holdout.py",
)
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def seal(root, path):
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": recovery.checksum(path),
    }


@pytest.fixture
def experiment(tmp_path):
    sources = [tmp_path / f"video-{i}.mp4" for i in range(2)]
    for index, source in enumerate(sources):
        source.write_bytes(f"generated media {index}".encode())
    videos = [
        {"id": str(i), "path": p.name, "sha256": recovery.checksum(p), "frame_count": 2}
        for i, p in enumerate(sources)
    ]
    requests = [
        {
            "source_ids": [f"known-{i}", f"unknown-{i}"],
            "family_eligible_rows": 1,
            "side_eligible_rows": 1,
        }
        for i in range(2)
    ]
    protocol = write(tmp_path / "protocol.json", {"requests": requests})
    view = write(
        tmp_path / "view.json",
        {
            "frozen_protocol_sha256": recovery.checksum(protocol),
            "cases": [
                {
                    "video_id": v["id"],
                    "source_sha256": v["sha256"],
                    "native_frames": 2,
                    "cut_frames": [],
                }
                for v in videos
            ],
        },
    )
    jobs = []
    for folder in ("main", "research"):
        target = tmp_path / folder
        target.mkdir()
        with sqlite3.connect(target / "catalog.sqlite3") as db:
            db.executescript(
                "CREATE TABLE videos(id TEXT, document TEXT);"
                "CREATE TABLE jobs(id TEXT, document TEXT);"
                "CREATE TABLE annotations(video_id TEXT, revision INTEGER, document TEXT);"
            )
            for v in videos:
                db.execute("INSERT INTO videos VALUES(?,?)", (v["id"], json.dumps(v)))
                db.execute(
                    "INSERT INTO annotations VALUES(?,0,?)",
                    (v["id"], json.dumps({"events": [], "track_assignments": []})),
                )
                if folder == "research":
                    write(target / v["id"] / "timestamps.json", [0, 0.04])
                    for stage in ("players", "shuttle"):
                        job = {
                            "id": f"{v['id']}-{stage}",
                            "kind": stage,
                            "video_id": v["id"],
                            "status": "completed" if v["id"] == "0" else "running",
                        }
                        jobs.append(job)
                        db.execute(
                            "INSERT INTO jobs VALUES(?,?)", (job["id"], json.dumps(job))
                        )
                        if job["status"] == "completed":
                            write(
                                target / v["id"] / "runs" / (job["id"] + ".json"),
                                {
                                    "stage": stage,
                                    "video_id": v["id"],
                                    "video_sha256": v["sha256"],
                                    "cut_frames": [],
                                    "frames": [
                                        {"frame": 0, "time_s": 0},
                                        {"frame": 1, "time_s": 0.04},
                                    ],
                                },
                            )
    native = write(
        tmp_path / "native/request-00.json",
        {
            "request": requests[0],
            "source_sha256": videos[0]["sha256"],
            "runs": {s: f"0-{s}" for s in ("players", "shuttle")},
            "run_sha256": {
                s: recovery.checksum(tmp_path / f"research/0/runs/0-{s}.json")
                for s in ("players", "shuttle")
            },
        },
    )
    archive = tmp_path / "features/request-00.npz"
    archive.parent.mkdir()
    archive.write_bytes(b"opaque pinned feature archive; no predictions")
    feature = write(
        archive.with_suffix(".json"),
        {
            "request": requests[0],
            "evidence_sha256": recovery.checksum(native),
            "features_sha256": recovery.checksum(archive),
        },
    )
    write(
        tmp_path / "audit/request-00.json",
        {
            "native_receipt_sha256": recovery.checksum(native),
            "feature_receipt_sha256": recovery.checksum(feature),
        },
    )
    script = tmp_path / "producer.py"
    script.write_text("# Frozen original producer, never executed by inventory\n")
    worker = write(
        tmp_path / "worker.json",
        {"pid": 999999999, "created": 1, "cwd": str(tmp_path), "script": str(script)},
    )
    runtime = tmp_path / "runtime/code.py"
    runtime.parent.mkdir()
    runtime.write_text("# Frozen runtime\n")
    manifest = {
        "schema_version": 1,
        "protocol": seal(tmp_path, protocol),
        "view_support": seal(tmp_path, view),
        "inputs": [seal(tmp_path, script)],
        "runtimes": [
            {"directory": "runtime", "files": {"code.py": recovery.checksum(runtime)}}
        ],
        "producers": [
            {
                "role": "native",
                "worker": seal(tmp_path, worker),
                "script": seal(tmp_path, script),
            }
        ],
        "research_data": "research",
        "main_data": "main",
        "native_receipts": "native",
        "feature_receipts": "features",
        "input_audit_receipts": "audit",
        "expected": {
            "clips": 2,
            "frames": 4,
            "rows": 4,
            "family_eligible": 2,
            "side_eligible": 2,
        },
    }
    return tmp_path, manifest


def test_inventory_preserves_databases_unknown_rows_and_partial_jobs(experiment):
    root, manifest = experiment
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    with (
        patch.object(
            recovery.psutil, "Process", side_effect=psutil.NoSuchProcess(999999999)
        ),
        patch.object(recovery.psutil, "process_iter", return_value=[]),
    ):
        result = recovery.inventory(root, manifest)
    assert result["totals"] == manifest["expected"]
    assert (
        result["totals"]["rows"] == 4
    )  # Unknown truth stays in the source denominator.
    assert result["original_workers_proven_stopped"]
    assert result["cases"][0]["input_audit_receipt"]
    assert all(
        j["reusable"]
        for values in result["cases"][0]["stages"].values()
        for j in values
    )
    assert not result["cases"][1]["native_receipt"]
    assert all(
        not j["reusable"]
        for values in result["cases"][1]["stages"].values()
        for j in values
    )
    assert not result["execution_authorized_by_inventory"]
    assert all(path.read_bytes() == value for path, value in before.items())


@pytest.mark.parametrize(
    "path",
    [
        "video-1.mp4",
        "runtime/code.py",
        "producer.py",
        "worker.json",
        "features/request-00.npz",
    ],
)
def test_changed_existing_inputs_are_not_silently_recomputed(experiment, path):
    root, manifest = experiment
    (root / path).write_bytes(b"changed")
    with pytest.raises(ValueError):
        recovery.inventory(root, manifest)


def test_missing_catalog_is_not_created(experiment):
    root, manifest = experiment
    manifest["main_data"] = "missing"
    with pytest.raises(FileNotFoundError):
        recovery.inventory(root, manifest)
    assert not (root / "missing").exists()


def test_reused_pid_and_unverifiable_process_never_authorize_execution(experiment):
    root, manifest = experiment
    worker = recovery.read_json(root / "worker.json")
    with patch.object(recovery.psutil, "Process") as process:
        process.return_value.create_time.return_value = 2
        assert recovery.process_state(worker) == "original_exited_pid_reused"
    with (
        patch.object(
            recovery.psutil, "Process", side_effect=psutil.AccessDenied(worker["pid"])
        ),
        patch.object(recovery.psutil, "process_iter", return_value=[]),
    ):
        result = recovery.inventory(root, manifest)
    assert not result["original_workers_proven_stopped"]
    assert not result["execution_authorized_by_inventory"]


def test_corrupt_clock_receipt_and_denominators_fail_closed(experiment):
    root, manifest = experiment
    write(root / "research/1/timestamps.json", [0, 0])
    with pytest.raises(ValueError, match="clock"):
        recovery.inventory(root, manifest)
    write(root / "research/1/timestamps.json", [0, 0.04])
    manifest["expected"]["family_eligible"] = 1
    with pytest.raises(ValueError, match="denominators"):
        recovery.inventory(root, manifest)


def test_sealed_path_cannot_escape_workspace(experiment):
    root, manifest = experiment
    manifest["protocol"]["path"] = "../private.json"
    with pytest.raises(ValueError, match="inside"):
        recovery.inventory(root, manifest)


def test_restarted_producer_under_another_pid_blocks_readiness(experiment):
    root, manifest = experiment
    restarted = SimpleNamespace(
        info={
            "pid": 42,
            "create_time": 123,
            "cwd": str(root),
            "cmdline": ["python", str(root / "producer.py")],
        }
    )
    with patch.object(recovery.psutil, "process_iter", return_value=[restarted]):
        result = recovery.inventory(root, manifest)
    assert result["matching_producer_processes"][0]["pid"] == 42
    assert not result["original_workers_proven_stopped"]
    assert not result["execution_authorized_by_inventory"]


def test_nonfinite_or_boolean_timestamps_are_rejected(experiment):
    root, manifest = experiment
    clock = root / "research/1/timestamps.json"
    clock.write_text("[0, NaN]", encoding="utf-8")
    with pytest.raises(ValueError, match="Nonfinite"):
        recovery.inventory(root, manifest)
    write(clock, [False, 0.04])
    with pytest.raises(ValueError, match="clock"):
        recovery.inventory(root, manifest)


def test_receipts_publish_once_without_replacing_prior_bytes(tmp_path):
    path = tmp_path / "receipts" / "case.json"
    recovery.create_json(path, {"completed": True})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        recovery.create_json(path, {"completed": False})
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.tmp"))


def test_os_lock_rejects_competing_writer_and_releases_after_failure(tmp_path):
    with pytest.raises(RuntimeError, match="interrupted"):
        with recovery.output_lock(tmp_path):
            with pytest.raises(OSError):
                with recovery.output_lock(tmp_path):
                    pytest.fail("Competing writer admitted")
            raise RuntimeError("interrupted")
    with recovery.output_lock(tmp_path):
        pass


def test_native_reuses_completed_player_after_interruption(experiment):
    root, _manifest = experiment
    videos, jobs, _annotations = recovery.database_snapshot(root / "research")
    support = recovery.read_json(root / "view.json")["cases"][0]
    player = jobs["0-players"]
    artifact = root / "research/0/runs/0-players.json"
    before = artifact.read_bytes()
    # A second stage never completed, so its absent output must be retried.
    shuttle = jobs["0-shuttle"]
    shuttle["status"] = "interrupted"
    artifact.with_name("0-shuttle.json").unlink()
    assert (
        recovery.select_native(
            root, root / "research", videos["0"], support, [player, shuttle], "players"
        )["id"]
        == "0-players"
    )
    assert (
        recovery.select_native(
            root, root / "research", videos["0"], support, [player, shuttle], "shuttle"
        )
        is None
    )
    assert artifact.read_bytes() == before
    # An orphan artifact is evidence to inspect, not a license to replace it.
    shuttle["status"] = "failed"
    write(artifact.with_name("0-shuttle.json"), {"partial": True})
    with pytest.raises((KeyError, ValueError)):
        recovery.select_native(
            root, root / "research", videos["0"], support, [player, shuttle], "shuttle"
        )


def test_successful_native_needs_real_completed_parent_and_sealed_receipts(experiment):
    root, manifest = experiment
    output = root / "recovery"
    attempt = output / "attempts/first"
    case = root / "native/request-00.json"
    manifest["expected"]["clips"] = 1
    proof = {
        "main_job_id": "parent",
        "totals": manifest["expected"],
        "cases": [{"ordinal": 0, **seal(root, case)}],
    }
    write(attempt / "native-completed.json", proof)
    with pytest.raises(ValueError, match="released"):
        recovery.successful_native(root, manifest, output)
    write(attempt / "admission-released.json", {"clips": 1})

    def parent(status):
        with sqlite3.connect(root / "main/catalog.sqlite3") as db:
            db.execute("DELETE FROM jobs")
            db.execute(
                "INSERT INTO jobs VALUES(?,?)",
                ("parent", json.dumps({"id": "parent", "status": status})),
            )

    parent("interrupted")
    with pytest.raises(ValueError, match="Store"):
        recovery.successful_native(root, manifest, output)
    parent("completed")
    assert (
        recovery.successful_native(root, manifest, output)
        == attempt / "native-completed.json"
    )
    case.write_bytes(b"changed")
    with pytest.raises(ValueError, match="Frozen bytes"):
        recovery.successful_native(root, manifest, output)


def test_real_main_admission_rejects_before_research_store_or_inference(
    experiment, monkeypatch
):
    import sys

    from badminton.schemas import Calibration, Point, SceneRange
    from badminton.storage import ConflictError, Store

    root, manifest = experiment
    court = root / "court.csv"
    court.write_text(
        "id,upleft_x,upleft_y,upright_x,upright_y,downright_x,downright_y,downleft_x,downleft_y\n2,400,200,900,200,1100,700,200,700\n"
    )
    view = recovery.read_json(root / "view.json")
    view["published_homography_sha256"] = recovery.checksum(court)
    write(root / "view.json", view)
    manifest["view_support"] = seal(root, root / "view.json")
    manifest["execution"] = {"court_path": "court.csv"}
    # Real app Store with an actual live claim; native recovery must honor it.
    shared = Store(root / "shared-main")
    shared.claim_job(
        {"id": "live-owner", "kind": "players", "video_id": None, "status": "running"}
    )
    seen = []

    def construct(folder):
        seen.append(folder)
        assert folder == root / "shared-main", (
            "Research Store constructed before shared admission"
        )
        return shared

    monkeypatch.setattr(recovery, "bind_runtime", lambda *args: None)
    monkeypatch.setattr(
        recovery, "prepare_attempt", lambda *args: (root / "attempt", {})
    )
    manifest["main_data"] = "shared-main"
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)),
    )
    monkeypatch.setitem(sys.modules, "torchvision", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "badminton.schemas",
        SimpleNamespace(Calibration=Calibration, Point=Point, SceneRange=SceneRange),
    )
    monkeypatch.setitem(
        sys.modules, "badminton.storage", SimpleNamespace(Store=construct)
    )

    def forbidden(*args):
        pytest.fail("Inference admitted despite live shared owner")

    monkeypatch.setitem(
        sys.modules, "badminton.shuttle", SimpleNamespace(track_shuttle=forbidden)
    )
    monkeypatch.setitem(
        sys.modules, "badminton.tracking", SimpleNamespace(track_players=forbidden)
    )
    with pytest.raises(ConflictError, match="Another processing job"):
        recovery.native_recovery(root, manifest, root / ".cache/recovery")
    assert seen == [root / "shared-main"]


def test_generated_feature_audit_retains_unknown_and_unavailable_rows(experiment):
    import numpy as np

    root, manifest = experiment
    video = recovery.database_snapshot(root / "research")[0]["0"]
    request = {
        "source_ids": ["known-0", "unknown-0"],
        "set_id": 1,
        "rally_id": 1,
        "lower_cfr_hint": 100,
        "upper_cfr_hint_inclusive": 101,
    }
    source = write(
        root / "clocks/match2-set1-rally1.json",
        {
            "request": request,
            "clip_sha256": video["sha256"],
            "frames": [
                {
                    "local_frame": i,
                    "parent_time_s": 4 + i * 0.04,
                    "parent_cfr_hint": 100 + i,
                }
                for i in range(2)
            ],
        },
    )
    manifest["execution"] = {"source_receipt_directory": "clocks"}
    meta_path = root / "features/request-00.json"
    evidence_path = root / "native/request-00.json"
    evidence = recovery.read_json(evidence_path)
    arrays = {
        "r2_features": np.zeros((2, 254), np.float32),
        "r3_features": np.zeros((2, 371), np.float32),
        "r2_available": np.array([False, False]),
        "r3_available": np.array([False, False]),
        "family": np.array([0, -1], np.int64),
        "side": np.array([1, -1], np.int64),
    }
    rows = {
        name: {
            "source_frame": 101 + i,
            "kind": "shot",
            "family": "clear" if not i else "unknown",
            "family_eligible": not i,
            "side": "backhand" if not i else "unknown",
            "side_eligible": not i,
        }
        for i, name in enumerate(request["source_ids"])
    }
    context = SimpleNamespace(
        times=[0, 0.04],
        players={
            "cut_frames": [],
            "frames": [{"calibration_valid": True}, {"calibration_valid": True}],
        },
        cuts=[],
        blocked=np.zeros(2, bool),
    )
    meta = {
        "request": request,
        "video_id": video["id"],
        "source_sha256": video["sha256"],
        "evidence_sha256": recovery.checksum(evidence_path),
        "native_run_sha256": evidence["run_sha256"],
        "source_metadata_sha256": recovery.checksum(source),
        "records": [
            {
                "id": name,
                "cue_local_frame": i,
                "r2_available": False,
                "r3_available": False,
                "association": {"status": "abstained"},
            }
            for i, name in enumerate(request["source_ids"])
        ],
    }

    def audit():
        np.savez_compressed(meta_path.with_suffix(".npz"), **arrays)
        meta["features_sha256"] = recovery.checksum(meta_path.with_suffix(".npz"))
        write(meta_path, meta)
        return recovery.audit_features(
            root,
            manifest,
            0,
            request,
            {"calibration_start_frame": 0},
            video,
            evidence_path,
            meta_path,
            rows,
            context,
        )

    result = audit()
    assert result["totals"]["rows"] == 2
    assert result["totals"]["family_eligible"] == result["totals"]["side_eligible"] == 1
    assert result["available"] == {"r2": 0, "r3": 0}
    arrays["family"][1] = 0
    with pytest.raises(ValueError, match="unknown truth"):
        audit()
    arrays["family"][1] = -1
    arrays["r2_features"][0, 1] = 1
    with pytest.raises(ValueError, match="unavailable"):
        audit()


def test_frozen_scoring_and_independent_saved_audit_preserve_strict_denominators(
    experiment,
):
    import copy

    import numpy as np

    root, manifest = experiment
    output = root / "recovery"
    directory = output / "evaluation"
    directory.mkdir(parents=True)
    requests = recovery.read_json(root / "protocol.json")["requests"]
    ids = []
    for ordinal, request in enumerate(requests):
        path = root / f"features/request-{ordinal:02d}.npz"
        np.savez_compressed(
            path,
            family=np.array([0, -1], np.int64),
            side=np.array([1, -1], np.int64),
            r2_features=np.zeros((2, 254), np.float32),
            r3_features=np.zeros((2, 371), np.float32),
            r2_available=np.array([ordinal == 0, ordinal == 1]),
            r3_available=np.array([ordinal == 0, ordinal == 1]),
        )
        write(
            path.with_suffix(".json"),
            {
                "request": request,
                "records": [{"id": i} for i in request["source_ids"]],
                "features_sha256": recovery.checksum(path),
            },
        )
        ids.extend(request["source_ids"])
    data, actual_ids = recovery.assembled_features(root, manifest, output)
    assert actual_ids == ids
    probability_family = np.zeros((4, 8), np.float32)
    probability_family[:, 0], probability_family[:, 1] = 0.8, 0.2
    probability_side = np.tile(np.array([0.1, 0.9], np.float32), (4, 1))
    thresholds = [[0.85] * 8, [0.8] * 2]
    proof = {"source_ids": ids, "totals": manifest["expected"], "models": {}}
    for name in ("R2", "R3"):
        available = data[name.lower() + "_available"]
        closed, closed_predictions = recovery.score_probabilities(
            data, [probability_family, probability_side], available
        )
        abstaining, abstaining_predictions = recovery.score_probabilities(
            data, [probability_family, probability_side], available, thresholds
        )
        assert closed["family"]["source_rows"] == 2
        assert closed["family"]["unavailable_truth_rows"] == 2
        assert closed["family"]["strict_accuracy"] == 0.5
        assert closed["family"]["precision_given_answered"] == 1
        assert abstaining["family"]["strict_accuracy"] == 0
        assert abstaining["side"]["strict_accuracy"] == 0.5
        assert abstaining["joint_correct"] == 0
        path = directory / (name.lower() + "-predictions.npz")
        np.savez_compressed(
            path,
            family_probabilities=probability_family,
            side_probabilities=probability_side,
            closed_set_predictions=closed_predictions,
            with_abstention_predictions=abstaining_predictions,
        )
        proof["models"][name] = {
            "closed_set": closed,
            "with_abstention": abstaining,
            "validation_thresholds": thresholds,
            "prediction_artifact_sha256": recovery.checksum(path),
        }
    audit = recovery.audit_saved_metrics(root, manifest, output, proof)
    assert audit["all_metrics_exact_recompute"]
    assert (
        audit["summaries"]["R2"]["closed_set"]["family_side_cells"]["smash/backhand"][
            "support"
        ]
        == 0
    )
    corrupted = copy.deepcopy(proof)
    corrupted["models"]["R2"]["closed_set"]["family"]["source_rows"] = 1
    with pytest.raises(ValueError, match="denominator"):
        recovery.audit_saved_metrics(root, manifest, output, corrupted)
    corrupted = copy.deepcopy(proof)
    corrupted["models"]["R2"]["closed_set"]["family"]["confusion"][0][0] += 1
    with pytest.raises(ValueError, match="confusion"):
        recovery.audit_saved_metrics(root, manifest, output, corrupted)
    for fields in (
        ("family", "macro_f1_supported"),
        ("family", "balanced_recall"),
        ("family", "precision_given_answered"),
        ("family", "supported_classes"),
        ("family", "confusion_columns"),
        ("family", "per_class", "clear", "precision"),
        ("family", "per_class", "clear", "recall"),
        ("family", "per_class", "clear", "predicted"),
        ("available_input_rows",),
        ("available_joint_eligible_rows",),
        ("source_rows",),
        ("exact_truth",),
    ):
        corrupted = copy.deepcopy(proof)
        cursor = corrupted["models"]["R2"]["closed_set"]
        for field in fields[:-1]:
            cursor = cursor[field]
        cursor[fields[-1]] = 0.12345
        with pytest.raises(ValueError, match="recomput"):
            recovery.audit_saved_metrics(root, manifest, output, corrupted)


def test_changed_preflight_blocks_before_any_application_import_or_weights(
    experiment, monkeypatch
):
    root, manifest = experiment
    preflight = write(
        root / "preflight.json",
        {
            "schema_version": 1,
            "verdict": "approve",
            "code_sha256": "old-code",
            "protocol_sha256": manifest["protocol"]["sha256"],
            "blockers": [],
            "reviewer_session": "generated-fixture-only",
            "evidence": ["synthetic test"],
        },
    )
    monkeypatch.setattr(
        recovery,
        "bind_runtime",
        lambda *args: pytest.fail("Runtime imported before valid review"),
    )
    with pytest.raises(ValueError, match="preflight"):
        recovery.evaluation_recovery(
            root, manifest, root / ".cache/new-output", preflight
        )
    assert not (root / ".cache/new-output").exists()


def test_recovery_output_cannot_overlap_originals_or_escape_workspace(experiment):
    root, manifest = experiment
    assert (
        recovery.recovery_output(root, manifest, ".cache/new-lineage")
        == root / ".cache/new-lineage"
    )
    manifest["native_receipts"] = ".cache/original-native"
    for path in (
        ".cache",
        ".cache/original-native",
        ".cache/original-native/child",
        "../other",
        "data/recovery",
    ):
        with pytest.raises(ValueError):
            recovery.recovery_output(root, manifest, path)


def test_between_case_frozen_revalidation_rejects_changed_runtime(experiment):
    root, manifest = experiment
    recovery.stable_frozen(root, manifest)
    (root / "runtime/code.py").write_bytes(b"Changed after preflight")
    with pytest.raises(ValueError, match="runtime changed during"):
        recovery.stable_frozen(root, manifest)


def test_between_case_source_revalidation_rejects_changed_source_or_metadata(
    experiment,
):
    import hashlib

    root, manifest = experiment
    video = recovery.database_snapshot(root / "research")[0]["0"]
    support = {"source_sha256": video["sha256"]}
    request = {
        "set_id": 1,
        "rally_id": 1,
        "lower_cfr_hint": 10,
        "upper_cfr_hint_inclusive": 11,
    }
    manifest["execution"] = {"source_receipt_directory": "clocks"}
    write(
        root / "clocks/match2-set1-rally1.json",
        {
            "request": request,
            "clip_sha256": video["sha256"],
            "frames": [
                {"local_frame": i, "parent_time_s": i * 0.04, "parent_cfr_hint": 10 + i}
                for i in range(2)
            ],
        },
    )
    expected = hashlib.sha256(recovery.encoded(video)).hexdigest()
    recovery.stable_source(root, manifest, video, support, request, expected)
    video["rotation_degrees"] = 90
    with pytest.raises(ValueError, match="registered metadata"):
        recovery.stable_source(root, manifest, video, support, request, expected)
    video.pop("rotation_degrees")
    (root / video["path"]).write_bytes(b"changed during long job")
    with pytest.raises(ValueError, match="Source bytes"):
        recovery.stable_source(root, manifest, video, support, request, expected)
