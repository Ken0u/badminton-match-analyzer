import copy
import hashlib
import json

import pytest
from badminton import pipeline
from badminton.jobs import JobCancelled, run_local_job
from badminton.scene_review import corrected_boundaries, reviewed_contacts, reviewed_run
from badminton.schemas import CameraCorrection, Event, SceneRange
from badminton.segments import slice_camera_scan
from badminton.storage import ConflictError, Store
from badminton.video import write_json

SETTINGS = {"player_model": "small", "auto_calibrate": True, "recognize": True}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"synthetic processing contract, not decoded media")
    data = tmp_path / "data"
    store = Store(data)
    times = [i / 10 for i in range(1300)]
    video = {
        "id": "test",
        "path": source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "mode": "singles",
        "width": 640,
        "height": 360,
        "frame_count": len(times),
        "duration_s": 130,
        "source_start_s": 0,
        "fps": 10,
    }
    store.register(video)
    write_json(data / "test" / "timestamps.json", times)
    calls = []

    def scan(v, root, _data, callback, output):
        calls.append(("segments", 0))
        write_json(
            output,
            {
                "stage": "segments",
                "video_id": v["id"],
                "video_sha256": v["sha256"],
                "start_frame": 0,
                "end_frame": len(times),
                "cut_frames": [350],
                "boundaries": [{"frame": 350, "time_s": 35, "reason": "visual_cut"}],
                "method": "synthetic",
                "decoded_frames": len(times),
            },
        )
        callback(1)

    def players(v, root, _data, doc, first, last, stride, callback, output, **kwargs):
        calls.append(("players", first))
        assert kwargs["camera_scan"]["end_frame"] == len(times)
        callback(0.5)
        write_json(
            output,
            {
                "stage": "players",
                "video_id": v["id"],
                "video_sha256": v["sha256"],
                "start_frame": first,
                "end_frame": last,
                "stride": stride,
                "calibration_signature": [],
                "frames": [
                    {
                        "frame": i,
                        "time_s": times[i],
                        "players": [],
                        "calibration_valid": False,
                    }
                    for i in range(first, last)
                ],
            },
        )

    def shuttle(v, root, _data, first, last, callback, output, doc, **kwargs):
        calls.append(("shuttle", first))
        callback(0.5)
        write_json(
            output,
            {
                "stage": "shuttle",
                "video_id": v["id"],
                "video_sha256": v["sha256"],
                "start_frame": first,
                "end_frame": last,
                "stride": 1,
                "frames": [
                    {
                        "frame": i,
                        "time_s": times[i],
                        "shuttle": {
                            "visible": False,
                            "x": None,
                            "y": None,
                            "repaired": False,
                        },
                    }
                    for i in range(first, last)
                ],
            },
        )

    monkeypatch.setattr(pipeline, "scan_video", scan)
    monkeypatch.setattr(pipeline, "track_players", players)
    monkeypatch.setattr(pipeline, "track_shuttle", shuttle)
    return tmp_path, store, video, times, calls


def execute(ctx, settings=None):
    root, store, video, _, _ = ctx
    return run_local_job(
        store,
        "analysis",
        video["id"],
        lambda identifier, progress: pipeline.process_match(
            video,
            root,
            store,
            store.annotations(video["id"]),
            identifier,
            progress,
            settings or SETTINGS,
        ),
    )


def test_source_windows_own_every_frame_once_and_keep_temporal_halos(workspace):
    _, _, video, times, _ = workspace
    windows = pipeline.plan_windows(video, times)
    assert [(w["core_start_frame"], w["core_end_frame"]) for w in windows] == [
        (0, 600),
        (600, 1200),
        (1200, 1300),
    ]
    assert [(w["start_frame"], w["end_frame"]) for w in windows] == [
        (0, 640),
        (560, 1240),
        (1160, 1300),
    ]
    assert [
        i for w in windows for i in range(w["core_start_frame"], w["core_end_frame"])
    ] == list(range(1300))
    variable = [i * 0.04 + 0.02 * (i % 2) for i in range(4000)]
    windows = pipeline.plan_windows(
        video | {"frame_count": len(variable), "duration_s": 160}, variable
    )
    assert windows[-1]["core_end_frame"] == len(variable)
    assert all(
        variable[w["end_frame"] - 1] - variable[w["start_frame"]] <= 68 for w in windows
    )


def test_complete_processing_and_resume_reuse_immutable_registered_artifacts(workspace):
    _, store, video, _, calls = workspace
    before = store.annotations(video["id"]).model_dump()
    result = execute(workspace)
    assert result["parts"] == 3 and result["completed_stages"] == 16
    assert result["reused_stages"] == 0 and not result["fully_annotated"]
    snapshots = {
        p.name: p.read_bytes() for p in (store.data / "test" / "runs").glob("*.json")
    }
    calls.clear()
    resumed = execute(workspace)
    assert resumed["reused_stages"] == 16 and calls == []
    assert {
        p.name: p.read_bytes() for p in (store.data / "test" / "runs").glob("*.json")
    } == snapshots
    assert store.annotations(video["id"]).model_dump() == before
    assert all(j["status"] == "completed" for j in store.jobs())


def test_pause_mid_stage_keeps_finished_work_and_resume_runs_only_missing_stages(
    workspace, monkeypatch
):
    _, store, _, _, calls = workspace
    original = pipeline.track_players

    def interrupted(*args, **kwargs):
        if args[4] == 560:
            active = next(
                j
                for j in store.jobs()
                if j["kind"] == "analysis" and j["status"] == "running"
            )
            store.request_cancel(active["id"])
            args[7](0.1)
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "track_players", interrupted)
    with pytest.raises(JobCancelled, match="paused"):
        execute(workspace)
    job = next(j for j in store.jobs() if j["kind"] == "analysis")
    assert job["status"] == "interrupted" and job["cancel_requested"]
    plan = next((store.data / "test" / "analysis").glob("*/manifest.json"))
    saved = json.loads(plan.read_text(encoding="utf-8"))
    assert saved["state"] == "interrupted" and not saved["processing_complete"]
    assert len(saved["parts"][0]["stages"]) == 5
    snapshots = {
        p.name: p.read_bytes() for p in (store.data / "test" / "runs").glob("*.json")
    }
    monkeypatch.setattr(pipeline, "track_players", original)
    calls.clear()
    result = execute(workspace)
    assert result["reused_stages"] == 6
    assert calls == [
        ("players", 560),
        ("shuttle", 560),
        ("players", 1160),
        ("shuttle", 1160),
    ]
    assert all(
        (store.data / "test" / "runs" / n).read_bytes() == raw
        for n, raw in snapshots.items()
    )


def test_changed_cached_bytes_fail_without_overwriting_or_rerunning(workspace):
    _, store, _, _, calls = workspace
    execute(workspace)
    source = next((store.data / "test" / "runs").glob("*.json"))
    source.write_bytes(b"corrupted checkpoint")
    calls.clear()
    with pytest.raises(ValueError, match="artifact changed"):
        execute(workspace)
    assert calls == [] and source.read_bytes() == b"corrupted checkpoint"


def test_recipe_uses_inference_context_and_settings_not_event_labels(workspace):
    _, store, video, times, _ = workspace
    doc = store.annotations("test")
    base = pipeline.processing_recipe(video, times, doc, SETTINGS)
    changed = doc.model_copy(deep=True)
    changed.revision += 1
    changed.events = [
        Event(
            id="reviewed",
            rally_id="R1",
            kind="shot",
            family="smash",
            side="backhand",
            frame=1,
        )
    ]
    assert pipeline.processing_recipe(video, times, changed, SETTINGS) == base
    changed.camera_corrections = [CameraCorrection(frame=350, is_cut=False)]
    assert pipeline.processing_recipe(video, times, changed, SETTINGS) != base
    assert (
        pipeline.processing_recipe(
            video, times, doc, SETTINGS | {"player_model": "nano"}
        )
        != base
    )
    assert pipeline.processing_recipe(video | {"fps": 25}, times, doc, SETTINGS) != base


def test_cancel_request_is_not_lost_to_an_older_progress_snapshot(workspace):
    _, store, _, _, _ = workspace
    job = {"id": "active", "kind": "analysis", "video_id": "test", "status": "running"}
    store.claim_job(job)
    stale = copy.deepcopy(job)
    store.request_cancel("active")
    stale["progress"] = 0.5
    store.put_job(stale)
    assert store.job("active")["cancel_requested"]
    with pytest.raises(ConflictError, match="Another"):
        store.claim_job(
            {"id": "second", "kind": "players", "video_id": "test", "status": "queued"}
        )


def test_global_scan_preserves_preceding_cuts_and_current_rejections():
    video = {"id": "v", "sha256": "source", "frame_count": 200}
    scan = {
        "stage": "segments",
        "video_id": "v",
        "video_sha256": "source",
        "start_frame": 0,
        "end_frame": 200,
        "cut_frames": [40, 80, 120],
        "boundaries": [
            {"frame": 40, "reason": "visual_cut"},
            {"frame": 80, "reason": "timestamp_discontinuity"},
            {"frame": 120, "reason": "visual_cut"},
        ],
    }
    raw = slice_camera_scan(video, scan, 100, 150)
    original = copy.deepcopy(scan)
    corrected = corrected_boundaries(raw, {}, 100, 150)
    assert (
        corrected["cut_frames"] == [120]
        and corrected["preceding_reviewed_cut_frame"] == 80
    )
    rejected = {"camera_corrections": [{"frame": 80, "is_cut": False}]}
    assert (
        corrected_boundaries(raw, rejected, 100, 150)["preceding_reviewed_cut_frame"]
        == 80
    )
    scan["boundaries"][1]["reason"] = "visual_cut"
    raw = slice_camera_scan(video, scan, 100, 150)
    initial = corrected_boundaries(raw, {}, 100, 150)
    run = {**initial, "stage": "players", "start_frame": 100, "end_frame": 150}
    assert reviewed_run(run, rejected)["requires_tracking_rerun"]
    assert reviewed_contacts({"court_context": run, "candidates": []}, rejected)[
        "requires_context_rerun"
    ]
    assert original["cut_frames"] == scan["cut_frames"]


def test_recover_both_registration_and_manifest_write_interruption(workspace):
    _, store, _, _, calls = workspace
    result = execute(workspace)
    path = pipeline.plan_path(store, "test", result["analysis_key"])
    plan = json.loads(path.read_text(encoding="utf-8"))
    registered_id = plan["parts"][0]["stages"]["players"]["run_id"]
    plan["parts"][0]["stages"].pop("players")
    write_json(path, plan)
    with store.connect() as db:
        db.execute(
            "DELETE FROM jobs WHERE id=?",
            (plan["parts"][1]["stages"]["shuttle"]["run_id"],),
        )
    calls.clear()
    recovered = execute(workspace)
    assert recovered["reused_stages"] == 16 and calls == []
    assert store.job(registered_id)["status"] == "completed"
    assert (
        pipeline.read_plan(store, "test", result["analysis_key"])["parts"][0]["stages"][
            "players"
        ]["run_id"]
        == registered_id
    )


def test_incomplete_native_output_is_never_registered_as_completed(
    workspace, monkeypatch
):
    _, store, _, _, _ = workspace
    original = pipeline.track_players

    def missing(*args, **kwargs):
        original(*args, **kwargs)
        path = args[8]
        run = json.loads(path.read_text(encoding="utf-8"))
        run["frames"].pop()
        write_json(path, run)

    monkeypatch.setattr(pipeline, "track_players", missing)
    with pytest.raises(ValueError, match="every requested source frame"):
        execute(workspace)
    assert not any(
        j["kind"] == "players" and j["status"] == "completed" for j in store.jobs()
    )


def test_new_inference_context_pauses_old_snapshot_before_native_work(workspace):
    root, store, video, _, calls = workspace
    old = store.annotations("test")
    changed = old.model_copy(deep=True)
    changed.scene_ranges = [
        SceneRange(id="replay", scene="replay", start_frame=0, end_frame=10)
    ]
    store.save_annotations("test", changed)
    with pytest.raises(JobCancelled, match="context changed"):
        run_local_job(
            store,
            "analysis",
            "test",
            lambda job_id, progress: pipeline.process_match(
                video, root, store, old, job_id, progress, SETTINGS
            ),
        )
    assert calls == []


def test_overlap_proposals_are_owned_by_only_one_core():
    candidates = [{"frame": 600, "time_s": 60}]
    first = {
        "start_frame": 0,
        "end_frame": 640,
        "analysis_core_start_frame": 0,
        "analysis_core_end_frame": 600,
        "candidates": candidates,
    }
    second = {
        "start_frame": 560,
        "end_frame": 1240,
        "analysis_core_start_frame": 600,
        "analysis_core_end_frame": 1200,
        "candidates": candidates,
    }
    assert pipeline.owned_candidates(first) == []
    assert pipeline.owned_candidates(second) == candidates


def test_disabling_recognition_reuses_all_completed_perception(workspace):
    _, _, _, _, calls = workspace
    execute(workspace)
    calls.clear()
    result = execute(workspace, SETTINGS | {"recognize": False})
    assert result["reused_stages"] == 13
    assert calls == []
