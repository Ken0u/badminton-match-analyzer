"""Generated Store/API/CLI coverage for boundary evaluation; no media decoding."""

import hashlib
import json
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest
from badminton.api import create_app
from badminton.rallies import context_signature
from badminton.schemas import Annotations, ReviewWindow
from badminton.storage import Store
from badminton.video import write_json
from fastapi.testclient import TestClient


@pytest.fixture
def boundary_workspace(tmp_path):
    source = tmp_path / "generated.mp4"
    source.write_bytes(b"generated-boundary-evaluation-contract")
    data = tmp_path / "processed"
    store = Store(data)
    video = {
        "id": "boundary-video",
        "mode": "singles",
        "path": source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "frame_count": 12,
        "duration_s": 0.72,
        "width": 640,
        "height": 360,
        "fps": 25,
        "source_start_s": 0,
    }
    times = [0, 0.04, 0.1, 0.14, 0.2, 0.24, 0.32, 0.36, 0.44, 0.48, 0.56, 0.64]
    for video_id in (video["id"], "other-video"):
        store.register(video | {"id": video_id})
        write_json(data / video_id / "timestamps.json", times)
    return SimpleNamespace(
        root=tmp_path, data=data, store=store, video=video, times=times
    )


def add_boundary_run(ctx, *, kind="rallies", status="completed", job_video=None):
    video_id = job_video or ctx.video["id"]
    annotations = ctx.store.annotations(video_id).model_dump()
    run = {
        "schema_version": 1,
        "video_id": video_id,
        "video_sha256": ctx.video["sha256"],
        "stage": kind,
        "start_frame": 0,
        "end_frame": 12,
        "source_timestamps_validated": True,
        "annotation_revision": annotations["revision"],
        "context_start_frame": 0,
        "context_end_frame": 12,
        "context_signature": context_signature(annotations, 0, 12),
        "court_context": {"start_frame": 0, "end_frame": 12, "cut_frames": []},
        "candidates": [
            {
                "id": name,
                "kind": boundary,
                "frame": frame,
                "time_s": ctx.times[frame],
                "start_frame": frame,
                "end_frame": frame,
                "start_time_s": ctx.times[frame],
                "end_time_s": ctx.times[frame],
                "needs_review": True,
                "player_id": None,
            }
            for name, boundary, frame in (
                ("serve-2", "serve", 2),
                ("ending-9", "rally_end", 9),
            )
        ],
    }
    path = ctx.data / video_id / "runs" / "rallies-1.json"
    write_json(path, run)
    ctx.store.put_job(
        {
            "id": "rallies-1",
            "video_id": video_id,
            "kind": kind,
            "status": status,
            "progress": 1,
        }
    )
    return path, run


def save_reference(ctx, *, serves_complete=True, rally_ends_complete=True):
    doc = ctx.store.annotations(ctx.video["id"]).model_dump()
    doc["review_windows"] = [
        {
            "id": "reviewed",
            "start_frame": 0,
            "end_frame": 12,
            "scene": "live",
            "contacts_complete": False,
            "serves_complete": serves_complete,
            "rally_ends_complete": rally_ends_complete,
        }
    ]
    doc["events"] = [
        {"id": "opening", "rally_id": "r1", "kind": "serve", "frame": 2},
        {"id": "terminal", "rally_id": "r1", "kind": "rally_end", "frame": 9},
    ]
    return ctx.store.save_annotations(ctx.video["id"], Annotations.model_validate(doc))


def test_legacy_contact_completeness_does_not_certify_boundaries():
    window = ReviewWindow.model_validate(
        {"id": "old", "start_frame": 0, "end_frame": 10, "contacts_complete": True}
    )
    assert window.contacts_complete
    assert not window.serves_complete
    assert not window.rally_ends_complete
    assert window.model_dump()["serves_complete"] is False
    assert window.model_dump()["rally_ends_complete"] is False


def test_boundary_declarations_persist_independently_in_history_and_export(
    boundary_workspace,
):
    ctx = boundary_workspace
    root = f"/api/videos/{ctx.video['id']}"
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        doc = client.get(root + "/annotations").json()
        doc["review_windows"] = [
            {
                "id": "coverage",
                "start_frame": 0,
                "end_frame": 12,
                "scene": "live",
                "contacts_complete": True,
                "serves_complete": True,
                "rally_ends_complete": False,
            }
        ]
        response = client.put(root + "/annotations", json=doc)
        assert response.status_code == 200, response.text
        first = response.json()
        assert first["revision"] == 1
        updated = deepcopy(first)
        updated["review_windows"][0].update(
            contacts_complete=False, serves_complete=False, rally_ends_complete=True
        )
        response = client.put(root + "/annotations", json=updated)
        assert response.status_code == 200, response.text
        assert client.put(root + "/annotations", json=first).status_code == 409
        current = response.json()
        assert current["revision"] == 2
        assert (
            client.get(root + "/annotations").json()["review_windows"]
            == current["review_windows"]
        )
        assert (
            client.get(root + "/revisions/1").json()["review_windows"]
            == first["review_windows"]
        )
        assert (
            client.get(root + "/export").json()["annotations"]["review_windows"]
            == current["review_windows"]
        )
        assert client.get(root + "/revisions/0").json()["review_windows"] == []


def test_rallies_only_api_binds_source_revision_run_and_native_times(
    boundary_workspace,
):
    ctx = boundary_workspace
    save_reference(ctx)
    path, original = add_boundary_run(ctx)
    before = path.read_bytes()
    annotations = ctx.store.annotations(ctx.video["id"]).model_dump()
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={"rallies_run_id": "rallies-1"},
        )
    assert response.status_code == 200, response.text
    report = response.json()
    result = report["rallies"]
    assert set(report) == {"video_id", "video_sha256", "annotation_revision", "rallies"}
    assert report["video_sha256"] == ctx.video["sha256"]
    assert result["run_id"] == "rallies-1"
    assert result["video_id"] == ctx.video["id"]
    assert result["video_sha256"] == ctx.video["sha256"]
    assert result["annotation_revision"] == annotations["revision"]
    assert set(result["kinds"]) == {"serve", "rally_end"}
    for kind in result["kinds"].values():
        assert kind["representative_timing"]["metrics"]["tp"] == 1
        assert kind["representative_timing"]["metrics"]["fp"] == 0
        assert kind["representative_timing"]["metrics"]["fn"] == 0
    assert path.read_bytes() == before
    assert ctx.store.annotations(ctx.video["id"]).model_dump() == annotations
    assert json.loads(before) == original


@pytest.mark.parametrize("serves,ends", [(True, False), (False, True), (False, False)])
def test_api_does_not_infer_other_boundary_coverage(boundary_workspace, serves, ends):
    ctx = boundary_workspace
    save_reference(ctx, serves_complete=serves, rally_ends_complete=ends)
    add_boundary_run(ctx)
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={"rallies_run_id": "rallies-1"},
        )
    assert response.status_code == 200, response.text
    kinds = response.json()["rallies"]["kinds"]
    for kind, complete in (("serve", serves), ("rally_end", ends)):
        timing = kinds[kind]["representative_timing"]
        assert (timing is not None) is complete
        assert kinds[kind]["status"] == (
            "scored" if complete else "needs_complete_live_review"
        )
        if complete:
            assert timing["metrics"]["tp"] == 1


@pytest.mark.parametrize(
    "case,expected",
    [
        ("missing_job", 404),
        ("wrong_kind", 404),
        ("running", 404),
        ("other_job_video", 404),
        ("missing_artifact", 404),
        ("wrong_artifact_video", 422),
        ("wrong_artifact_stage", 422),
        ("source_hash", 422),
        ("candidate_clock", 422),
        ("source_clock", 422),
        ("stale_context", 422),
        ("candidate_kind", 422),
    ],
)
def test_rally_api_rejects_missing_mismatched_or_stale_inputs(
    boundary_workspace, case, expected
):
    ctx = boundary_workspace
    save_reference(ctx)
    if case != "missing_job":
        path, run = add_boundary_run(
            ctx,
            kind="shuttle" if case == "wrong_kind" else "rallies",
            status="running" if case == "running" else "completed",
            job_video="other-video" if case == "other_job_video" else None,
        )
        if case == "missing_artifact":
            path.unlink()
        elif case == "source_clock":
            times = ctx.times.copy()
            times[2] += 0.001
            write_json(ctx.data / ctx.video["id"] / "timestamps.json", times)
        else:
            if case == "wrong_artifact_video":
                run["video_id"] = "other-video"
            elif case == "wrong_artifact_stage":
                run["stage"] = "shuttle"
            elif case == "source_hash":
                run["video_sha256"] = "f" * 64
            elif case == "candidate_clock":
                run["candidates"][0]["time_s"] += 0.01
            elif case == "candidate_kind":
                run["candidates"][0]["kind"] = "shot"
            elif case == "stale_context":
                run["context_signature"] = {}
            write_json(path, run)
    with TestClient(
        create_app(ctx.root, ctx.data), raise_server_exceptions=False
    ) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={"rallies_run_id": "rallies-1"},
        )
    assert response.status_code == expected, (case, response.status_code, response.text)


def test_mixed_evaluation_retains_existing_contact_result(boundary_workspace):
    ctx = boundary_workspace
    save_reference(ctx)
    add_boundary_run(ctx)
    contact = {
        "video_id": ctx.video["id"],
        "stage": "contacts",
        "start_frame": 0,
        "end_frame": 12,
        "candidates": [],
    }
    write_json(ctx.data / ctx.video["id"] / "runs" / "contacts-1.json", contact)
    ctx.store.put_job(
        {
            "id": "contacts-1",
            "video_id": ctx.video["id"],
            "kind": "contacts",
            "status": "completed",
            "progress": 1,
        }
    )
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={"rallies_run_id": "rallies-1", "contacts_run_id": "contacts-1"},
        )
    assert response.status_code == 200, response.text
    report = response.json()
    assert set(report) >= {"contacts", "rallies"}
    assert report["contacts"]["status"] == "needs_complete_live_review"
    assert report["contacts"]["run_id"] == "contacts-1"


def test_api_retains_uncertain_ending_support_without_point_metrics(boundary_workspace):
    ctx = boundary_workspace
    saved = save_reference(ctx).model_dump()
    saved["events"][1].update(terminal_start_frame=8, terminal_end_frame=10)
    ctx.store.save_annotations(ctx.video["id"], Annotations.model_validate(saved))
    add_boundary_run(ctx)
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={"rallies_run_id": "rallies-1"},
        )
    assert response.status_code == 200, response.text
    kinds = response.json()["rallies"]["kinds"]
    ending = kinds["rally_end"]
    assert ending["status"] == "needs_exact_boundary_timing"
    assert ending["representative_timing"] is None
    assert ending["coverage"]["usable_window_ids"] == ["reviewed"]
    assert ending["coverage"]["point_timing_skipped_windows"] == [
        {"id": "reviewed", "reason": "boundary_timing_needs_adjudication"}
    ]
    support = ending["interval_compatibility"]
    assert support["matched_count"] == 1
    assert support["matches"][0]["event_interval_frames"] == 3
    assert "f1" not in support
    assert kinds["serve"]["representative_timing"]["metrics"]["tp"] == 1


def test_api_applies_explicit_tolerance_without_changing_saved_proposals(
    boundary_workspace,
):
    ctx = boundary_workspace
    save_reference(ctx)
    path, run = add_boundary_run(ctx)
    run["candidates"][0].update(
        frame=3,
        time_s=ctx.times[3],
        start_frame=3,
        end_frame=3,
        start_time_s=ctx.times[3],
        end_time_s=ctx.times[3],
    )
    write_json(path, run)
    original = path.read_bytes()
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        narrow = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={"rallies_run_id": "rallies-1", "tolerance_s": 0.01},
        )
        wide = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={"rallies_run_id": "rallies-1", "tolerance_s": 0.06},
        )
    assert narrow.status_code == wide.status_code == 200
    narrow_metrics = narrow.json()["rallies"]["kinds"]["serve"][
        "representative_timing"
    ]["metrics"]
    assert (narrow_metrics["tp"], narrow_metrics["fp"], narrow_metrics["fn"]) == (
        0,
        1,
        1,
    )
    assert (
        wide.json()["rallies"]["kinds"]["serve"]["representative_timing"]["metrics"][
            "tp"
        ]
        == 1
    )
    assert path.read_bytes() == original


def test_api_rejects_changed_media_before_boundary_evaluation(boundary_workspace):
    ctx = boundary_workspace
    save_reference(ctx)
    path, _ = add_boundary_run(ctx)
    original = path.read_bytes()
    (ctx.root / ctx.video["path"]).write_bytes(b"replacement-media")
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={"rallies_run_id": "rallies-1"},
        )
    assert response.status_code == 409, response.text
    assert path.read_bytes() == original


def test_cli_rallies_only_matches_api_report_and_writes_same_download(
    boundary_workspace, monkeypatch, capsys
):
    from badminton import cli

    ctx = boundary_workspace
    save_reference(ctx)
    add_boundary_run(ctx)
    output = ctx.root / "boundary-report.json"
    monkeypatch.setattr(cli, "ROOT", ctx.root)
    monkeypatch.setattr(cli, "DATA", ctx.data)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "badminton",
            "evaluate",
            ctx.video["id"],
            "--rallies-run",
            "rallies-1",
            "--output",
            str(output),
        ],
    )
    cli.main()
    report = json.loads(capsys.readouterr().out)
    assert json.loads(output.read_bytes()) == report
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={"rallies_run_id": "rallies-1"},
        )
    assert response.status_code == 200, response.text
    assert report["rallies"] == response.json()["rallies"]
    assert report["schema_version"] == 1


@pytest.mark.parametrize("run_id", [None, "missing"])
def test_cli_reports_missing_input_without_launching_analysis(
    boundary_workspace, monkeypatch, capsys, run_id
):
    from badminton import cli

    ctx = boundary_workspace
    monkeypatch.setattr(cli, "ROOT", ctx.root)
    monkeypatch.setattr(cli, "DATA", ctx.data)
    argv = ["badminton", "evaluate", ctx.video["id"]]
    if run_id:
        argv += ["--rallies-run", run_id]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert "--rallies-run" in capsys.readouterr().err or run_id == "missing"
    assert ctx.store.jobs(ctx.video["id"]) == []


@pytest.mark.parametrize("consumer", ["api", "cli"])
@pytest.mark.parametrize("kind,frame", [("serve", 2), ("rally_end", 9)])
@pytest.mark.parametrize("barrier", ["camera_cut", "timestamp_gap", "review_gap"])
def test_saved_boundary_evidence_barriers_preserve_references_and_original_inputs(
    boundary_workspace, monkeypatch, capsys, consumer, kind, frame, barrier
):
    from badminton import cli

    ctx = boundary_workspace
    timestamps_path = ctx.data / ctx.video["id"] / "timestamps.json"
    if barrier == "timestamp_gap":
        ctx.times[frame:] = [time + 0.2 for time in ctx.times[frame:]]
        write_json(timestamps_path, ctx.times)
        ctx.video["duration_s"] += 0.2
        ctx.store.register(ctx.video)
    save_reference(ctx)
    if barrier == "review_gap":
        doc = ctx.store.annotations(ctx.video["id"]).model_dump()
        template = doc["review_windows"][0]
        doc["review_windows"] = [
            template | {"id": "before", "start_frame": 0, "end_frame": frame - 1},
            template | {"id": "after", "start_frame": frame, "end_frame": 12},
        ]
        ctx.store.save_annotations(ctx.video["id"], Annotations.model_validate(doc))
    path, run = add_boundary_run(ctx)
    target = next(item for item in run["candidates"] if item["kind"] == kind)
    target.update(context_start_frame=frame - 1, context_end_frame=frame + 2)
    if barrier == "camera_cut":
        run["cut_frames"] = run["court_context"]["cut_frames"] = [frame]
    write_json(path, run)
    original = path.read_bytes()
    source_before = (ctx.root / ctx.video["path"]).read_bytes()
    clock_before = timestamps_path.read_bytes()
    annotations_before = ctx.store.annotations(ctx.video["id"]).model_dump()
    jobs_before = ctx.store.jobs(ctx.video["id"])
    if consumer == "api":
        with TestClient(create_app(ctx.root, ctx.data)) as client:
            response = client.post(
                f"/api/videos/{ctx.video['id']}/evaluate",
                json={"rallies_run_id": "rallies-1"},
            )
        assert response.status_code == 200, response.text
        report = response.json()["rallies"]
    else:
        output = ctx.root / "generated-evidence-report.json"
        monkeypatch.setattr(cli, "ROOT", ctx.root)
        monkeypatch.setattr(cli, "DATA", ctx.data)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "badminton",
                "evaluate",
                ctx.video["id"],
                "--rallies-run",
                "rallies-1",
                "--output",
                str(output),
            ],
        )
        cli.main()
        printed = json.loads(capsys.readouterr().out)
        assert json.loads(output.read_bytes()) == printed
        report = printed["rallies"]
    result = report["kinds"][kind]
    metrics = result["representative_timing"]["metrics"]
    assert (metrics["tp"], metrics["fp"], metrics["fn"], metrics["f1"]) == (0, 0, 1, 0)
    assert result["interval_compatibility"]["matched_count"] == 0
    assert result["interval_compatibility"]["reviewed_event_count"] == 1
    coverage = result["coverage"]
    assert coverage["reviewed_frames"] == (11 if barrier == "review_gap" else 12)
    assert coverage["reviewed_events"] == 1 and coverage["evaluated_candidates"] == 0
    assert coverage["excluded_event_ids"] == []
    assert coverage["excluded_candidate_ids"] == [target["id"]]
    excluded = coverage["candidate_evidence_context"]["excluded_candidates"]
    assert excluded == [
        {
            "id": target["id"],
            "reason": {
                "camera_cut": "evidence_context_crosses_camera_cut",
                "timestamp_gap": "evidence_context_crosses_source_timestamp_gap",
                "review_gap": "evidence_context_outside_reviewed_coverage",
            }[barrier],
            "context_start_frame": frame - 1,
            "context_end_frame": frame + 2,
        }
    ]
    other = report["kinds"]["rally_end" if kind == "serve" else "serve"]
    assert other["representative_timing"]["metrics"]["tp"] == 1
    assert path.read_bytes() == original
    assert (ctx.root / ctx.video["path"]).read_bytes() == source_before
    assert timestamps_path.read_bytes() == clock_before
    assert ctx.store.annotations(ctx.video["id"]).model_dump() == annotations_before
    assert ctx.store.jobs(ctx.video["id"]) == jobs_before
