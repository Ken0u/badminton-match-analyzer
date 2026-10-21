"""Bounded CPU probe contracts exercised with generated media and fake inference."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from badminton.ingest import inspect_video
from badminton.jobs import JobCancelled
from badminton.scene_review import reviewed_run
from badminton.schemas import Annotations
from badminton.storage import ConflictError, Store
from badminton.video import timestamps_for, write_json
from media_fixtures import write_rotated_video
from PIL import Image


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def annotation_documents(store):
    with store.connect() as db:
        return db.execute(
            "SELECT video_id,revision,document FROM annotations ORDER BY revision"
        ).fetchall()


@pytest.fixture
def probe_case(tmp_path):
    root = tmp_path
    data = root / "data" / "processed"
    weights = root / "models" / "weights"
    weights.mkdir(parents=True)
    store = Store(data)
    source = write_rotated_video(root / "generated.mp4", 90)
    video = inspect_video(source, "singles", store, root)
    annotations = store.annotations(video["id"]).model_dump()
    annotations.update(
        camera_corrections=[{"frame": 2, "is_cut": True}],
        scene_ranges=[
            {"id": "unresolved", "start_frame": 2, "end_frame": 3, "scene": "unknown"}
        ],
    )
    store.save_annotations(video["id"], Annotations.model_validate(annotations))
    variants = []
    for variant, letter in (("nano", "n"), ("small", "s")):
        checkpoint = weights / f"yolo11{letter}-pose.pt"
        checkpoint.write_bytes(f"generated {variant} checkpoint fixture".encode())
        variants.append(
            {"variant": variant, "name": checkpoint.name, "sha256": digest(checkpoint)}
        )
    clock = data / video["id"] / "timestamps.json"
    latest_document = annotation_documents(store)[-1][2]
    manifest = {
        "schema_version": 1,
        "video_id": video["id"],
        "source_sha256": digest(source),
        "clock_sha256": digest(clock),
        "annotation_revision": 1,
        "annotation_sha256": hashlib.sha256(latest_document.encode()).hexdigest(),
        "start_frame": 0,
        "end_frame": 4,
        "variants": variants,
        "sample_frames": [0, 2, 3],
        "max_runtime_seconds": 900,
        "max_output_bytes": 67108864,
    }
    old_prediction = data / video["id"] / "runs" / "players-existing.json"
    old_prediction.parent.mkdir()
    old_prediction.write_bytes(b'{"original_prediction": true}\n')
    protected = [
        source,
        clock,
        old_prediction,
        *(weights / v["name"] for v in variants),
    ]
    return SimpleNamespace(
        root=root,
        data=data,
        weights=weights,
        store=store,
        source=source,
        clock=clock,
        video=video,
        manifest=manifest,
        output=root / ".cache" / "probe-new",
        protected={path: path.read_bytes() for path in protected},
        documents=annotation_documents(store),
    )


def fake_tracker(case, *, mutate=None, fail_variant=None):
    calls = []

    def track(
        video,
        root,
        data,
        annotations,
        start,
        end,
        stride,
        progress,
        output,
        player_model="small",
        auto_calibrate=True,
        **_kwargs,
    ):
        calls.append(player_model)
        assert root == case.root and data == case.data
        assert (start, end, stride, auto_calibrate) == (0, 4, 1, False)
        assert annotations.revision == 1
        # Admission must be in the fixture's existing application catalog.
        assert any(job["status"] == "running" for job in case.store.jobs())
        if player_model == fail_variant:
            Path(output).write_bytes(b'{"incomplete":')
            raise RuntimeError("injected small inference failure")
        checkpoint = next(
            entry
            for entry in case.manifest["variants"]
            if entry["variant"] == player_model
        )
        times = timestamps_for(data, video["id"])
        rows = [
            {
                "frame": index,
                "time_s": times[index],
                "players": []
                if index == 1
                else [
                    {
                        "track_id": 1 if index < 2 else 2,
                        "player_id": None,
                        "box": [5, 8, 25, 50],
                        "confidence": 0.8,
                        "keypoints": [[10, 20, 0.9], [15, 30, 0.0]],
                    }
                ],
                "motion_players": [],
                "camera_segment_start_frame": 0 if index < 2 else 2,
                "calibration_valid": False,
            }
            for index in range(start, end)
        ]
        result = reviewed_run(
            {
                "schema_version": 1,
                "video_id": video["id"],
                "stage": "players",
                "video_sha256": video["sha256"],
                "model": checkpoint["name"].removesuffix(".pt"),
                "model_variant": player_model,
                "checkpoint_sha256": checkpoint["sha256"],
                "model_source": "generated-test-fixture",
                "device": "cpu",
                "auto_calibrate": False,
                "start_frame": start,
                "end_frame": end,
                "stride": stride,
                "processed_frames": len(rows),
                "annotation_revision": annotations.revision,
                "cut_frames": [],
                "camera_ranges": [{"start_frame": start, "end_frame": end}],
                "camera_boundary_method": "generated-test-fixture",
                "tracker_reset_at_cuts": True,
                "court_context_version": 1,
                "automatic_calibrations": [],
                "elapsed_s": 0.01,
                "inference_fps": 400,
                "frames": rows,
            },
            annotations,
        )
        if mutate:
            mutate(result)
        write_json(Path(output), result)
        progress(1)
        return {key: value for key, value in result.items() if key != "frames"}

    return track, calls


def run(case, tracker, **kwargs):
    from badminton.player_probe import run_probe

    return run_probe(
        case.root,
        case.data,
        case.weights,
        case.manifest,
        case.output,
        tracker=tracker,
        cpu_check=lambda: None,
        **kwargs,
    )


def assert_preserved(case):
    assert annotation_documents(case.store) == case.documents
    assert {path: path.read_bytes() for path in case.protected} == case.protected


@pytest.mark.parametrize(
    "field",
    ["source_sha256", "clock_sha256", "annotation_sha256", "annotation_revision"],
)
def test_frozen_input_mismatch_refuses_before_inference_or_output(probe_case, field):
    case = probe_case
    case.manifest[field] = 0 if field == "annotation_revision" else "0" * 64
    tracker, calls = fake_tracker(case)
    with pytest.raises((ValueError, RuntimeError)):
        run(case, tracker)
    assert calls == []
    assert not case.output.exists()
    assert case.store.jobs() == []
    assert_preserved(case)


def test_checkpoint_hash_mismatch_refuses_before_inference(probe_case):
    case = probe_case
    case.manifest["variants"][1]["sha256"] = "0" * 64
    tracker, calls = fake_tracker(case)
    with pytest.raises((ValueError, RuntimeError)):
        run(case, tracker)
    assert calls == []
    assert not case.output.exists()
    assert case.store.jobs() == []
    assert_preserved(case)


@pytest.mark.parametrize("argument", ["data", "weights", "output"])
def test_isolated_store_weights_or_noncache_output_are_refused(probe_case, argument):
    case = probe_case
    setattr(case, argument, case.root / "isolated-research" / argument)
    tracker, calls = fake_tracker(case)
    with pytest.raises(ValueError):
        run(case, tracker)
    assert calls == []
    assert not case.output.exists()
    assert case.store.jobs() == []
    assert_preserved(case)


def test_occupied_output_refuses_without_overwriting_evidence(probe_case):
    case = probe_case
    case.output.mkdir(parents=True)
    sentinel = case.output / "receipt.json"
    sentinel.write_bytes(b"previous run evidence")
    tracker, calls = fake_tracker(case)
    with pytest.raises((ValueError, RuntimeError, FileExistsError)):
        run(case, tracker)
    assert calls == []
    assert sentinel.read_bytes() == b"previous run evidence"
    assert case.store.jobs() == []
    assert_preserved(case)


@pytest.mark.parametrize("budget", ["runtime", "output"])
def test_exhausted_budget_preserves_partial_artifacts_and_interrupted_job(
    probe_case, monkeypatch, budget
):
    from badminton import player_probe

    case = probe_case
    if budget == "runtime":
        case.manifest["max_runtime_seconds"] = 1
        clock = iter([0, 10, 10])
        monkeypatch.setattr(
            player_probe, "time", SimpleNamespace(monotonic=lambda: next(clock))
        )
    else:
        case.manifest["max_output_bytes"] = 1
    tracker, calls = fake_tracker(case)
    with pytest.raises(JobCancelled, match=r"budget|runtime"):
        run(case, tracker)
    assert calls == ["nano"]
    job = case.store.jobs()[0]
    assert job["status"] == "interrupted"
    receipt = json.loads((case.output / "receipt.json").read_text())
    assert receipt["status"] == "interrupted"
    assert receipt["shared_job"] == job
    assert receipt["inputs_preserved"] is True
    predictions = case.output / "nano" / "predictions.json"
    assert json.loads(predictions.read_text())["processed_frames"] == 4
    assert receipt["artifacts"]["nano/predictions.json"] == digest(predictions)
    assert not (case.output / "small").exists()
    assert_preserved(case)


@pytest.mark.parametrize("target", ["original_prediction", "raw_annotations"])
def test_input_change_during_inference_blocks_second_model_and_records_failure(
    probe_case, target
):
    case = probe_case
    tracker, calls = fake_tracker(case)
    prediction = case.data / case.video["id"] / "runs" / "players-existing.json"

    def changing_tracker(*args, **kwargs):
        summary = tracker(*args, **kwargs)
        if target == "original_prediction":
            prediction.write_bytes(b"simulated concurrent prediction edit")
        else:
            # Same semantic labels/revision, different source bytes: the raw
            # document hash must still detect the concurrent change.
            with case.store.connect() as db:
                db.execute(
                    "UPDATE annotations SET document=document || ' ' "
                    "WHERE video_id=? AND revision=1",
                    (case.video["id"],),
                )
        return summary

    with pytest.raises(ValueError, match=r"changed|frozen"):
        run(case, changing_tracker)
    assert calls == ["nano"]
    assert case.store.jobs()[0]["status"] == "failed"
    receipt = json.loads((case.output / "receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["inputs_preserved"] is False
    assert "nano/predictions.json" in receipt["artifacts"]
    assert not (case.output / "small").exists()
    assert case.source.read_bytes() == case.protected[case.source]
    assert case.clock.read_bytes() == case.protected[case.clock]
    if target == "original_prediction":
        assert annotation_documents(case.store) == case.documents
    else:
        assert prediction.read_bytes() == case.protected[prediction]


def test_existing_shared_job_blocks_probe_inference(probe_case):
    case = probe_case
    job = {
        "id": "other-live-job",
        "kind": "analysis",
        "video_id": case.video["id"],
        "status": "running",
    }
    case.store.claim_job(job)
    tracker, calls = fake_tracker(case)
    with pytest.raises(ConflictError, match="Another processing job is running"):
        run(case, tracker)
    assert calls == []
    assert case.store.job(job["id"])["status"] == "running"
    assert len(case.store.jobs()) == 1
    assert_preserved(case)


INVALID_RESULTS = [
    pytest.param(
        lambda r: r["frames"].append(copy.deepcopy(r["frames"][-1])), id="duplicate"
    ),
    pytest.param(lambda r: r["frames"].pop(), id="missing-native-frame"),
    pytest.param(lambda r: r["frames"].reverse(), id="out-of-order"),
    pytest.param(lambda r: r["frames"][2].update(time_s=0.08), id="wrong-source-pts"),
    pytest.param(
        lambda r: r["frames"][0].update(time_s=float("nan")), id="nonfinite-pts"
    ),
    pytest.param(lambda r: r.update(device="cuda:0"), id="wrong-device"),
    pytest.param(lambda r: r.update(video_sha256="0" * 64), id="foreign-source"),
    pytest.param(
        lambda r: r.update(checkpoint_sha256="0" * 64), id="foreign-checkpoint"
    ),
    pytest.param(lambda r: r.update(cut_frames=[]), id="lost-reviewed-cut"),
    pytest.param(
        lambda r: r["frames"][2].update(scene="live"), id="lost-scene-exclusion"
    ),
    pytest.param(
        lambda r: r["frames"][0]["players"][0].update(box=[5, 8, float("nan"), 50]),
        id="nonfinite-box",
    ),
    pytest.param(
        lambda r: r["frames"][0]["players"][0].update(box=[25, 8, 5, 50]),
        id="inverted-box",
    ),
    pytest.param(
        lambda r: r["frames"][0]["players"][0].update(
            keypoints=[[10, float("inf"), 0.9]]
        ),
        id="nonfinite-keypoint",
    ),
]


@pytest.mark.parametrize("mutate", INVALID_RESULTS)
def test_invalid_prediction_is_retained_as_failed_evidence(probe_case, mutate):
    case = probe_case
    tracker, calls = fake_tracker(case, mutate=mutate)
    with pytest.raises((ValueError, RuntimeError)):
        run(case, tracker)
    assert calls == ["nano"]
    assert case.store.jobs()[0]["status"] == "failed"
    receipt = json.loads((case.output / "receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert_preserved(case)


def test_two_variants_preserve_truth_and_write_native_overlay_receipts(probe_case):
    case = probe_case
    tracker, calls = fake_tracker(case)
    receipt = run(case, tracker)
    assert calls == ["nano", "small"]
    assert receipt["status"] == "completed"
    assert json.loads((case.output / "receipt.json").read_text()) == receipt
    job = case.store.jobs()[0]
    assert job["status"] == "completed"
    assert receipt["job_id"] == job["id"]
    assert receipt["shared_job"] == job
    assert receipt["shared_store"] == str(case.store.db_path)
    assert receipt["process"]["pid"] == job["owner_pid"]
    assert receipt["process"]["created_at"] == job["owner_started"]
    assert receipt["process"]["cwd"] and receipt["process"]["command"]
    assert receipt["inputs_preserved"] is True
    assert receipt["limitations"]
    before = json.loads((case.output / "inputs-before.json").read_text())
    assert before == json.loads((case.output / "inputs-after.json").read_text())
    assert before["source_sha256"] == case.manifest["source_sha256"]
    assert before["clock_sha256"] == case.manifest["clock_sha256"]
    assert before["annotation_sha256"] == case.manifest["annotation_sha256"]
    assert before["original_predictions"] == {
        f"{case.video['id']}/runs/players-existing.json": digest(
            case.data / case.video["id"] / "runs" / "players-existing.json"
        )
    }
    for variant in ("nano", "small"):
        counts = receipt["variants"][variant]
        assert counts["processed_frames"] == 4
        assert counts["player_observations"] == 3
        assert counts["frames_without_detections"] == 1
        assert counts["keypoints_confidence_at_least_025"] == 3
        assert counts["provisional_track_ids"] == [1, 2]
        assert counts["scene_excluded_frames"] == 1
        assert counts["cut_frames"] == [2]
        assert counts["camera_ranges"] == [
            {"start_frame": 0, "end_frame": 2, "scene": "unknown"},
            {"start_frame": 2, "end_frame": 4, "scene": "unknown"},
        ]
        predictions = case.output / variant / "predictions.json"
        rows = json.loads(predictions.read_text())["frames"]
        assert [row["frame"] for row in rows] == [0, 1, 2, 3]
        assert [row["time_s"] for row in rows] == [0, 0.04, 0.12, 0.16]
        assert rows[1]["players"] == []
        assert rows[2]["scene"] == "unknown"
        assert all(
            player["player_id"] is None for row in rows for player in row["players"]
        )
        for index in case.manifest["sample_frames"]:
            overlay = case.output / variant / f"frame-{index}.jpg"
            with Image.open(overlay) as image:
                assert image.size == (64, 128)
                # Independent asymmetric fixture color after display rotation.
                expected = (20 + index * 5, 20, 230)
                assert (
                    max(abs(a - b) for a, b in zip(image.getpixel((45, 100)), expected))
                    < 15
                )
        assert (case.output / variant / "contact-sheet.jpg").is_file()
    expected_artifacts = {
        str(path.relative_to(case.output)): digest(path)
        for path in case.output.rglob("*")
        if path.is_file() and path.name != "receipt.json"
    }
    assert receipt["artifacts"] == expected_artifacts
    assert_preserved(case)


def test_second_variant_failure_preserves_first_and_terminal_job(probe_case):
    case = probe_case
    tracker, calls = fake_tracker(case, fail_variant="small")
    with pytest.raises(RuntimeError, match="injected small inference failure"):
        run(case, tracker)
    assert calls == ["nano", "small"]
    jobs = case.store.jobs()
    assert len(jobs) == 1 and jobs[0]["status"] == "failed"
    receipt = json.loads((case.output / "receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["shared_job"]["id"] == jobs[0]["id"]
    assert receipt["inputs_preserved"] is True
    assert receipt["variants"]["nano"]["processed_frames"] == 4
    assert "small" not in receipt["variants"]
    assert (case.output / "nano" / "frame-3.jpg").is_file()
    partial = case.output / "small" / "predictions.json"
    assert partial.read_bytes() == b'{"incomplete":'
    assert receipt["artifacts"]["small/predictions.json"] == digest(partial)
    assert_preserved(case)
