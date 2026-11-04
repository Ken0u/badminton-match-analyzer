"""Generated source/split/clock/admission controls; no research inputs opened."""

import copy
import hashlib
import json
import time
import zipfile
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest
from badminton import aicup_pose_pilot as pilot


def source_row(clip="00001", frame=1, family="3", side="2", number=1):
    from badminton.aicup_data import normalize_clip

    raw = {
        "ShotSeq": str(number),
        "HitFrame": str(frame),
        "Hitter": "A",
        "Backhand": side,
        "BallType": family,
        "Winner": "X",
    }
    row = normalize_clip([raw], clip, "train")[0]
    # Independent generated selection rows, already canonical-source bound by
    # canonical_rows in integration tests below.
    row.update(fold="train", clip_key=f"train:{clip}", contact_label_eligible=True)
    row.update(id=f"aicup2023:train:{clip}:{number + 1}", source_row=number + 1)
    return row


def test_public_protocol_matches_fixed_rule():
    root = Path(pilot.__file__).resolve().parents[2]
    assert (
        pilot.read_json(root / "data/manifests/aicup_pose_pilot_protocol_v1.json")
        == pilot.PROTOCOL
    )
    assert pilot.PROTOCOL["limits"]["fits"] == 0
    assert pilot.PROTOCOL["limits"]["external_image_bytes"] == 0
    assert pilot.PROTOCOL["limits"]["native_passes_per_clip"] == 1
    assert "half smash" not in pilot.FAMILIES


def test_fixed_selection_order_shortfalls_and_full_clip_denominator():
    rows = [source_row(f"{i:05}", number=1) for i in range(1, 7)]
    extra = source_row("00001", family="1", number=2)
    extra["side"] = "unknown"
    rows.append(extra)
    actual = pilot.select_cohort(rows)
    expected = sorted(
        rows[:-1],
        key=lambda r: hashlib.sha256(
            f"aicup-pose-pilot-v1|train|{r['id']}".encode()
        ).hexdigest(),
    )[:2]
    assert actual["selected_row_ids"] == [r["id"] for r in expected]
    assert len(actual["cells"]) == 24
    assert sum(c["selected"] for c in actual["cells"]) == 2
    assert sum(c["shortfall"] for c in actual["cells"]) == 46
    assert (
        pilot.select_cohort(list(reversed(rows)))["selected_row_ids"]
        == actual["selected_row_ids"]
    )
    # Force a serve/unknown into an independently selected clip and retain it.
    extra["clip_key"] = expected[0]["clip_key"]
    actual = pilot.select_cohort(rows)
    assert extra in actual["reference_rows"]
    assert actual["pool_rows"] == len(rows)


def test_selection_deduplicates_clips_without_dropping_references():
    a, b = source_row(), source_row(frame=2, family="4", number=2)
    result = pilot.select_cohort([a, b])
    assert len(result["selected_row_ids"]) == 2
    assert result["clip_keys"] == ["train:00001"]
    assert result["reference_rows"] == [a, b]


@pytest.mark.parametrize("mutation", ["test", "duplicate", "ineligible", "unknown"])
def test_selection_fences_held_out_duplicate_and_ineligible_rows(mutation):
    row = source_row()
    if mutation == "test":
        row["fold"] = "test"
    if mutation == "duplicate":
        with pytest.raises(ValueError, match="Duplicate"):
            pilot.select_cohort([row, row])
        return
    if mutation == "ineligible":
        row["contact_label_eligible"] = False
    if mutation == "unknown":
        row["side"] = "unknown"
    if mutation == "test":
        with pytest.raises(ValueError, match="Held-out"):
            pilot.select_cohort([row])
    else:
        assert pilot.select_cohort([row])["selected_row_ids"] == []


def test_canonical_csv_binding_and_test_open_fence(tmp_path, monkeypatch):
    path = tmp_path / "generated.zip"
    raw = (
        b"ShotSeq,HitFrame,Hitter,Backhand,BallType,Winner\n1,0,A,1,1,X\n2,3,B,2,3,B\n"
    )
    label = "part1/train/00001/00001_S2.csv"
    clips = [
        {
            "source_partition": "train",
            "source_clip_id": "00001",
            "media_path": "part1/train/00001/00001.mp4",
            "label_path": label,
            "label_sha256": hashlib.sha256(raw).hexdigest(),
        },
        {"source_partition": "train", "source_clip_id": "00002"},
    ]
    with zipfile.ZipFile(path, "w") as source:
        source.writestr(label, raw)
        source.writestr("part1/train/00002/00002_S2.csv", "INVALID HELD OUT")
    opened = []
    original = zipfile.ZipFile.open

    def guarded(self, name, *args, **kwargs):
        member = name.filename if isinstance(name, zipfile.ZipInfo) else name
        assert "00002" not in member
        opened.append(member)
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", guarded)
    rows = pilot.canonical_rows(
        path, clips, {"train:00001": "train", "train:00002": "test"}
    )
    assert opened == [label]
    assert [r["side"] for r in rows] == ["backhand", "forehand"]
    assert [r["family"] for r in rows] == [None, "clear"]
    assert rows[0]["source_contact_frame"] == 0
    assert rows[1]["raw"]["HitFrame"] == "3"
    clips[0]["label_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="binding changed"):
        pilot.canonical_rows(
            path, clips, {"train:00001": "train", "train:00002": "test"}
        )


@pytest.mark.parametrize(
    "mutation", ["duplicate", "missing", "overlap", "bad_fold", "byte_overlap"]
)
def test_capture_fold_integrity(mutation):
    clips = [
        {"source_partition": "train", "source_clip_id": "00001", "media_sha256": "a"},
        {"source_partition": "val", "source_clip_id": "00002", "media_sha256": "b"},
    ]
    groups = {
        "source_groups": [
            {"id": "one", "fold": "train", "members": ["train:00001"]},
            {"id": "two", "fold": "validation", "members": ["val:00002"]},
        ]
    }
    assert pilot.capture_folds(clips, groups)[0] == {
        "train:00001": "train",
        "val:00002": "validation",
    }
    if mutation == "duplicate":
        groups["source_groups"][1]["id"] = "one"
    elif mutation == "missing":
        groups["source_groups"][1]["members"] = []
    elif mutation == "overlap":
        groups["source_groups"][1]["members"].append("train:00001")
    elif mutation == "bad_fold":
        groups["source_groups"][0]["fold"] = "development"
    else:
        clips[1]["media_sha256"] = "a"
    with pytest.raises(ValueError):
        pilot.capture_folds(clips, groups)


@pytest.mark.parametrize(
    "start,end", [(0, 0), (0, float("nan")), (1, float("inf")), (1, 28802), (101, 102)]
)
def test_original_deadline_cannot_be_extended(monkeypatch, start, end):
    monkeypatch.setattr(pilot.time, "time", lambda: 100)
    with pytest.raises(ValueError, match="deadline"):
        pilot.check_deadline(start, end)
    pilot.check_deadline(50, 101)


def test_output_budget_and_exclusive_publication(tmp_path):
    pilot.publish(tmp_path / "one.json", {"original": True})
    with pytest.raises(FileExistsError):
        pilot.publish(tmp_path / "one.json", {"original": False})
    assert pilot.read_json(tmp_path / "one.json") == {"original": True}
    for kwargs in (
        {"frames": 32001},
        {"media_bytes": 1073741825},
        {"reserve": 4294967296},
    ):
        with pytest.raises(ValueError, match="budget"):
            pilot.check_budget(tmp_path, **kwargs)


@pytest.mark.parametrize(
    "name", ["../secret", "/absolute", "a\\b", "a:stream", "a//b", "a/./b"]
)
def test_private_artifact_paths_stay_inside_root(tmp_path, name):
    with pytest.raises(ValueError):
        pilot.inside(tmp_path, name)


def pose_case():
    from badminton.tracking import TRACKING_RECIPE

    video = {
        "id": "video",
        "sha256": "source",
        "frame_count": 3,
        "width": 100,
        "height": 80,
        "rotation": 0,
    }
    times = [0, 0.03333333, 0.1]
    scan = {
        "cut_frames": [2],
        "camera_ranges": [
            {"start_frame": 0, "end_frame": 2, "scene": "unknown"},
            {"start_frame": 2, "end_frame": 3, "scene": "unknown"},
        ],
    }
    ledger = {
        "source_sha256": "source",
        "rotation": 0,
        "display_dimensions": [100, 80],
        "origin_pts": 100,
        "stream_time_base": [1, 3000],
        "rows": [
            {
                "frame": i,
                "pts": 100 + pts,
                "time_base": [1, 3000],
                "relative_time": ratio,
            }
            for i, pts, ratio in ((0, 0, [0, 1]), (1, 100, [1, 30]), (2, 300, [1, 10]))
        ],
    }
    rows = []
    for i, timestamp in enumerate(times):
        person = {
            "box": [1, 2, 50, 70],
            "confidence": 0.8,
            "keypoints": [[10, 10, 0.8] for _ in range(17)],
            "track_id": 1 if i < 2 else 2,
            "baseline_track_id": 1 if i < 2 else 2,
        }
        rows.append(
            {
                "frame": i,
                "time_s": timestamp,
                "players": [person],
                "motion_players": [],
                "camera_segment_start_frame": 0 if i < 2 else 2,
                "calibration_valid": False,
            }
        )
    result = {
        "stage": "players",
        "video_id": "video",
        "video_sha256": "source",
        "checkpoint_sha256": pilot.PROTOCOL["sources"]["model"],
        "model_variant": "small",
        "image_size": 1280,
        "tracking_recipe": copy.deepcopy(TRACKING_RECIPE),
        "stride": 1,
        "auto_calibrate": True,
        "start_frame": 0,
        "end_frame": 3,
        "processed_frames": 3,
        "cut_frames": scan["cut_frames"],
        "camera_ranges": scan["camera_ranges"],
        "automatic_calibrations": [],
        "court_context_version": 1,
        "frames": rows,
    }
    return result, video, times, scan, ledger


def test_pose_validation_preserves_vfr_and_missing_support():
    args = pose_case()
    args[0]["frames"][1]["players"] = []
    result = pilot.validate_pose(*args)
    assert result["processed_frames"] == 3
    assert result["frames_without_pose_players"] == 1
    assert result["player_observations"] == 2


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_frame",
        "nan",
        "rotation",
        "pts",
        "time",
        "cut",
        "id",
        "baseline_id",
        "stale_calibration",
        "model",
        "recipe",
    ],
)
def test_pose_validation_rejects_clock_context_and_observation_mutations(mutation):
    result, video, times, scan, ledger = pose_case()
    if mutation == "missing_frame":
        result["frames"].pop()
    elif mutation == "nan":
        result["frames"][0]["players"][0]["keypoints"][5][0] = float("nan")
    elif mutation == "rotation":
        ledger["rotation"] = 90
    elif mutation == "pts":
        ledger["rows"][1]["pts"] += 1
    elif mutation == "time":
        result["frames"][1]["time_s"] = 0.04
    elif mutation == "cut":
        result["frames"][2]["camera_segment_start_frame"] = 0
    elif mutation in ("id", "baseline_id"):
        name = "track_id" if mutation == "id" else "baseline_track_id"
        result["frames"][2]["players"][0][name] = 1
    elif mutation == "stale_calibration":
        result["frames"][2]["calibration_valid"] = True
    elif mutation == "model":
        result["checkpoint_sha256"] = "altered"
    else:
        result["tracking_recipe"]["detector_confidence"] = 0.9
    with pytest.raises(ValueError):
        pilot.validate_pose(result, video, times, scan, ledger)


def test_reference_rows_keep_unknowns_censoring_unavailable_and_actor_ambiguity():
    result, *_ = pose_case()
    rows = [source_row(frame=f, number=i + 1) for i, f in enumerate((0, 1, 2, 9))]
    rows[0]["side"] = "unknown"
    rows[3]["family"] = "unknown"
    support = pilot.reference_support(rows, result)
    assert len(support) == 4
    assert support[0]["censored_H0"] and not support[0]["interval_available"]
    assert support[1]["published_interval"] == [0, 1]
    assert support[2]["crosses_camera_boundary"]
    assert not support[3]["interval_available"]
    assert all(
        r["correct_hitter"] is None and r["candidate_actor_ambiguous"] for r in support
    )
    assert all(not r["training_ready"] for r in support)
    assert support[1]["pose_observations"][0]["wrists"] == 2


@pytest.fixture
def generated_preparation(tmp_path, monkeypatch):
    source = tmp_path / "sources"
    source.mkdir()
    paths = {}
    for name in pilot.PROTOCOL["sources"]:
        path = source / name
        path.write_text(name, encoding="utf-8")
        paths[name] = path
    protocol = copy.deepcopy(pilot.PROTOCOL)
    protocol["sources"] = {k: pilot.digest(p) for k, p in paths.items()}
    monkeypatch.setattr(pilot, "PROTOCOL", protocol)
    monkeypatch.setattr(pilot, "runtime", lambda: {"generated": True})
    prep = tmp_path / "prepared"
    prep.mkdir()
    pilot.publish(prep / "cohort.json", {"reference_rows": []})
    value = {
        "protocol": protocol,
        "code": pilot.code_seals(),
        "runtime": pilot.runtime(),
        "granted_at": time.time() - 10,
        "deadline": time.time() + 300,
        "sources": {
            k: {"path": str(p), "sha256": pilot.digest(p)} for k, p in paths.items()
        },
        "native_frames": 0,
        "media_bytes": 0,
        "clips": [],
        "artifacts": pilot.inventory(prep),
    }
    pilot.publish(prep / "freeze.json", value)
    return prep, pilot.digest(prep / "freeze.json"), paths, value


@pytest.mark.parametrize(
    "mutation",
    ["none", "source", "clock", "extra", "freeze", "code", "runtime", "deadline"],
)
def test_frozen_preparation_refuses_mutation(
    generated_preparation, monkeypatch, mutation
):
    prep, sha, paths, _ = generated_preparation
    if mutation == "none":
        assert pilot.validate_prepared(prep, sha)["native_frames"] == 0
        return
    if mutation == "source":
        paths["archive"].write_text("changed", encoding="utf-8")
    elif mutation == "clock":
        (prep / "cohort.json").write_text("changed", encoding="utf-8")
    elif mutation == "extra":
        (prep / "extra").write_text("unfrozen", encoding="utf-8")
    elif mutation == "freeze":
        sha = "0" * 64
    elif mutation == "code":
        monkeypatch.setattr(pilot, "code_seals", lambda: {})
    elif mutation == "runtime":
        monkeypatch.setattr(pilot, "runtime", lambda: {"changed": True})
    else:
        original_time = time.time()
        monkeypatch.setattr(pilot.time, "time", lambda: original_time + 100000)
    with pytest.raises(ValueError):
        pilot.validate_prepared(prep, sha)


def test_shared_admission_denial_prevents_any_tracker_call(tmp_path, monkeypatch):
    from badminton import jobs, tracking
    from badminton.storage import ConflictError, Store

    workspace = tmp_path / "workspace"
    data = workspace / "data/processed"
    weights = workspace / "models/weights"
    store = Store(data)
    store.claim_job({"id": "owner", "kind": "players", "status": "running"})
    prepared = workspace / ".cache/prepared"
    prepared.mkdir(parents=True)
    output = workspace / ".cache/new-run"
    monkeypatch.setattr(
        pilot, "configure_workspace", lambda _: (workspace, data, weights)
    )
    monkeypatch.setattr(
        pilot,
        "validate_prepared",
        lambda *_: {"sources": {"model": {"path": str(weights / "yolo11s-pose.pt")}}},
    )
    monkeypatch.setattr(
        tracking,
        "track_players",
        lambda *_a, **_k: pytest.fail("GPU called without admission"),
    )
    assert jobs.run_local_job
    with pytest.raises(ConflictError, match="Another processing"):
        pilot.run(workspace, prepared, "freeze", output)
    assert (output / "failure.json").is_file()
    assert store.job("owner")["status"] == "running"


def test_json_rejects_nonfinite_and_duplicate_fields(tmp_path):
    path = tmp_path / "bad.json"
    for text in ('{"a":1,"a":2}', '{"a":NaN}'):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError):
            pilot.read_json(path)


def test_annotation_snapshot_excludes_jobs_but_preserves_history(tmp_path):
    from badminton.storage import Store

    store = Store(tmp_path)
    before = pilot.annotation_snapshot(tmp_path)
    store.claim_job(
        {"id": "metadata", "kind": "feature-preparation", "status": "running"}
    )
    assert pilot.annotation_snapshot(tmp_path) == before
    with store.connect() as db:
        db.execute(
            "INSERT INTO videos VALUES (?,?)", ("video", json.dumps({"id": "video"}))
        )
    assert pilot.annotation_snapshot(tmp_path) != before


@pytest.mark.parametrize(
    "mutation", [None, "missing_pts", "orientation", "reverse", "close_mutation"]
)
def test_exact_native_clock_preserves_vfr_origin_orientation_and_teardown(
    tmp_path, monkeypatch, mutation
):
    import sys

    from badminton import av_runtime, orientation

    media = tmp_path / "generated.mp4"
    media.write_bytes(b"generated source")
    frames = [
        SimpleNamespace(pts=p, time_base=Fraction(1, 3000), duration=100, rotation=90)
        for p in (100, 200, 400)
    ]
    if mutation == "missing_pts":
        frames[1].pts = None
    elif mutation == "orientation":
        frames[1].rotation = 0
    elif mutation == "reverse":
        frames[1].pts = 100
    stream = SimpleNamespace(
        time_base=Fraction(1, 3000),
        start_time=100,
        average_rate=Fraction(30),
        width=100,
        height=80,
        codec_context=SimpleNamespace(name="generated"),
    )

    @contextmanager
    def opened(_):
        yield SimpleNamespace(
            streams=SimpleNamespace(video=[stream]), decode=lambda _: iter(frames)
        )
        if mutation == "close_mutation":
            media.write_bytes(b"replaced after decode")

    monkeypatch.setitem(sys.modules, "torchvision", SimpleNamespace())
    monkeypatch.setattr(av_runtime, "open_media", opened)
    monkeypatch.setattr(orientation, "frame_rotation", lambda f: f.rotation)
    if mutation:
        with pytest.raises(ValueError):
            pilot.native_clock(media)
        return
    ledger, times, video = pilot.native_clock(media)
    assert times == [0, 0.03333333, 0.1]
    assert [r["pts"] for r in ledger["rows"]] == [100, 200, 400]
    assert ledger["rows"][1]["relative_time"] == [1, 30]
    assert ledger["display_dimensions"] == [80, 100]
    assert video["source_start_s"] == 1 / 30
    assert video["duration_s"] == 0.13333333


@pytest.fixture
def integrated_inputs(tmp_path, monkeypatch):
    from badminton import segments, tracking
    from badminton.storage import Store

    workspace = tmp_path / "workspace"
    data, weights = workspace / "data/processed", workspace / "models/weights"
    Store(data)
    weights.mkdir(parents=True)
    model = weights / "yolo11s-pose.pt"
    model.write_bytes(b"generated model, never deserialized")
    index = workspace / "index"
    index.mkdir()
    archive = workspace / "part1.zip"
    raw = b"ShotSeq,HitFrame,Hitter,Backhand,BallType,Winner\n1,0,A,1,1,X\n2,1,B,2,3,X\n3,9,A,0,9,A\n"
    media = b"generated media; native reader substituted"
    label = "part1/train/00001/00001_S2.csv"
    clip = {
        "source_partition": "train",
        "source_clip_id": "00001",
        "media_path": "part1/train/00001/00001.mp4",
        "media_bytes": len(media),
        "media_sha256": hashlib.sha256(media).hexdigest(),
        "label_path": label,
        "label_sha256": hashlib.sha256(raw).hexdigest(),
    }
    with zipfile.ZipFile(archive, "w") as source:
        source.writestr(label, raw)
        source.writestr(clip["media_path"], media)
    pilot.publish(index / "clips.json", [clip])
    (index / "records.json").write_bytes(b"intentionally not deserialized")
    groups = workspace / "groups.json"
    pilot.publish(
        groups,
        {
            "source_groups": [
                {"id": "generated context", "fold": "train", "members": ["train:00001"]}
            ],
            "source_archive_sha256": pilot.digest(archive),
            "source_clip_index_sha256": pilot.digest(index / "clips.json"),
            "source_records_sha256": pilot.digest(index / "records.json"),
        },
    )
    paths = pilot.source_paths(archive, index, model, groups)
    protocol = copy.deepcopy(pilot.PROTOCOL)
    protocol["sources"] = {k: pilot.digest(p) for k, p in paths.items()}
    monkeypatch.setattr(pilot, "PROTOCOL", protocol)
    monkeypatch.setattr(pilot, "runtime", lambda: {"generated": True})
    monkeypatch.setattr(
        pilot, "configure_workspace", lambda _: (workspace, data, weights)
    )
    protocol_path = workspace / "protocol.json"
    pilot.publish(protocol_path, protocol)
    result, video, times, scan, ledger = pose_case()
    for value in (video,):
        value.update(
            id=clip["media_sha256"][:16],
            sha256=clip["media_sha256"],
            duration_s=0.13333333,
            mode="singles",
        )
    ledger["source_sha256"] = clip["media_sha256"]
    result.update(
        video_id=video["id"],
        video_sha256=video["sha256"],
        checkpoint_sha256=protocol["sources"]["model"],
    )
    scan.update(
        stage="segments",
        video_id=video["id"],
        video_sha256=video["sha256"],
        start_frame=0,
        end_frame=3,
    )
    monkeypatch.setattr(
        pilot,
        "native_clock",
        lambda _: (copy.deepcopy(ledger), list(times), copy.deepcopy(video)),
    )
    monkeypatch.setattr(
        segments,
        "scan_video",
        lambda _v, _r, _d, _p, target: pilot.publish(target, scan),
    )
    calls = []

    def observe(
        _video,
        _root,
        _data,
        annotations,
        start,
        end,
        stride,
        progress,
        output,
        **kwargs,
    ):
        assert annotations.events == []
        assert (start, end, stride) == (0, 3, 1)
        assert kwargs["player_model"] == "small" and kwargs["auto_calibrate"]
        calls.append(output)
        progress(0.5)
        pilot.publish(output, result)

    monkeypatch.setattr(tracking, "track_players", observe)
    return workspace, paths, protocol_path, calls


def prepare_generated(inputs):
    workspace, paths, protocol, _ = inputs
    prepared = workspace / ".cache/prepared"
    summary = pilot.prepare(
        paths["archive"],
        paths["clips"].parent,
        paths["model"],
        paths["groups"],
        protocol,
        time.time() - 1,
        time.time() + 300,
        prepared,
    )
    return prepared, summary["freeze_sha256"]


def test_complete_generated_pipeline_preserves_rows_and_store_release(
    integrated_inputs,
):
    from badminton.storage import Store

    workspace, _, _, calls = integrated_inputs
    prepared, sha = prepare_generated(integrated_inputs)
    cohort = pilot.read_json(prepared / "cohort.json")
    assert len(cohort["selected_row_ids"]) == 1
    assert len(cohort["reference_rows"]) == 3
    assert cohort["reference_rows"][-1]["side"] == "unknown"
    output = workspace / ".cache/native"
    completed = pilot.run(workspace, prepared, sha, output)
    assert len(calls) == 1
    assert completed["summary"]["native_frames"] == 3
    assert completed["receipts"][0]["reference_rows"] == 3
    assert completed["receipts"][0]["available_intervals"] == 1
    assert (
        Store(workspace / "data/processed").job(completed["job_id"])["status"]
        == "completed"
    )
    assert pilot.verify(prepared, sha, output)["verified_clips"] == 1
    with pytest.raises(FileExistsError):
        pilot.run(workspace, prepared, sha, output)
    with pytest.raises(FileExistsError):
        pilot.run(workspace, prepared, sha, workspace / ".cache/alternate-native")
    assert len(calls) == 1


def test_partial_native_failure_is_durable_without_repeat(
    integrated_inputs, monkeypatch
):
    from badminton import tracking
    from badminton.storage import Store

    workspace, _, _, _ = integrated_inputs
    prepared, sha = prepare_generated(integrated_inputs)

    def fail(*args, **kwargs):
        raise ValueError("generated native failure")

    monkeypatch.setattr(tracking, "track_players", fail)
    output = workspace / ".cache/failed-native"
    with pytest.raises(ValueError, match="generated native failure"):
        pilot.run(workspace, prepared, sha, output)
    assert (output / "failure.json").is_file()
    assert not (output / "completion.json").exists()
    job_id = pilot.read_json(output / "process.json")["job_id"]
    assert Store(workspace / "data/processed").job(job_id)["status"] == "failed"
    assert (prepared / "freeze.json").is_file()


@pytest.mark.parametrize("target", ["support", "receipt", "denominator", "job"])
def test_completion_verification_refuses_false_support_and_unreleased_job(
    integrated_inputs, target
):
    from badminton.storage import Store

    workspace, _, _, _ = integrated_inputs
    prepared, sha = prepare_generated(integrated_inputs)
    output = workspace / ".cache/native"
    completion = pilot.run(workspace, prepared, sha, output)
    if target == "support":
        path = output / "clip-00/support.json"
        changed = pilot.read_json(path)
        changed.pop()
        path.write_bytes(pilot.encoded(changed))
    elif target == "receipt":
        path = output / "clip-00/receipt.json"
        changed = pilot.read_json(path)
        changed["available_intervals"] = 3
        path.write_bytes(pilot.encoded(changed))
    elif target == "denominator":
        completion["summary"]["native_frames"] = 2
    else:
        store = Store(workspace / "data/processed")
        job = store.job(completion["job_id"])
        job["status"] = "running"
        store.put_job(job)
    if target in ("support", "receipt"):
        completion["artifacts"][path.relative_to(output).as_posix()] = pilot.digest(
            path
        )
    (output / "completion.json").write_bytes(pilot.encoded(completion))
    with pytest.raises(ValueError):
        pilot.verify(prepared, sha, output)
