"""Generated cross-camera evaluation through saved Store/API/CLI artifacts."""

import hashlib
import json
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest
from badminton.api import create_app
from badminton.evaluation import evaluate_contacts
from badminton.recognition_evaluation import evaluate_recognition
from badminton.schemas import Annotations
from badminton.storage import Store
from badminton.video import write_json
from fastapi.testclient import TestClient


@pytest.fixture
def workspace(tmp_path):
    source = tmp_path / "generated.mp4"
    source.write_bytes(b"generated-contact-camera-evaluation")
    data = tmp_path / "processed"
    store = Store(data)
    video = {
        "id": "camera-video",
        "path": source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "mode": "doubles",
        "frame_count": 40,
        "duration_s": 1.6,
        "width": 640,
        "height": 360,
        "fps": 25,
        "source_start_s": 0,
    }
    store.register(video)
    write_json(data / video["id"] / "timestamps.json", [i * 0.04 for i in range(40)])
    doc = store.annotations(video["id"]).model_dump()
    doc["events"] = [
        {
            "id": "before-cut",
            "rally_id": "r1",
            "kind": "shot",
            "frame": 19,
            "status": "reviewed",
            "family": "drive",
            "side": "forehand",
            "player_id": "A",
        }
    ]
    doc["review_windows"] = [
        {
            "id": "reviewed",
            "start_frame": 0,
            "end_frame": 40,
            "scene": "live",
            "contacts_complete": True,
        }
    ]
    saved = store.save_annotations(video["id"], Annotations.model_validate(doc))
    paths, runs = {}, {}
    for stage in ("contacts", "recognition"):
        run_id = stage + "-1"
        candidate = {
            "id": "after-cut",
            "frame": 20,
            "time_s": 0.8,
            "status": "predicted",
            "kind": "shot",
            "family": "drive",
            "side": "forehand",
            "hitter_hint": {"player_id": "A"},
        }
        run = {
            "video_id": video["id"],
            "video_sha256": video["sha256"],
            "stage": stage,
            "run_id": run_id,
            "start_frame": 0,
            "end_frame": 40,
            "cut_frames": [20],
            "calibration_signature": [],
            "court_context": {"start_frame": 0, "end_frame": 40, "cut_frames": [20]},
            "candidates": [candidate],
        }
        path = data / video["id"] / "runs" / (run_id + ".json")
        write_json(path, run)
        store.put_job(
            {
                "id": run_id,
                "video_id": video["id"],
                "kind": stage,
                "status": "completed",
                "progress": 1,
            }
        )
        paths[stage], runs[stage] = path, run
    return SimpleNamespace(
        root=tmp_path,
        data=data,
        store=store,
        video=video,
        doc=saved.model_dump(),
        paths=paths,
        runs=runs,
    )


def api_report(ctx, payload=None):
    with TestClient(
        create_app(ctx.root, ctx.data), raise_server_exceptions=False
    ) as client:
        return client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json=payload
            or {"contacts_run_id": "contacts-1", "recognition_run_id": "recognition-1"},
        )


def assert_no_cross_cut_credit(report):
    contact = report["contacts"]
    assert contact["coverage"]["frame_ranges"] == [[0, 20], [20, 40]]
    assert contact["coverage"]["reviewed_frames"] == 40
    assert contact["coverage"]["reviewed_contacts"] == 1
    assert contact["coverage"]["evaluated_candidates"] == 1
    assert contact["metrics"]["tp"] == 0
    assert contact["metrics"]["fp"] == contact["metrics"]["fn"] == 1
    assert contact["metrics"]["f1"] == 0
    assert contact["matches"] == []
    assert contact["tighter_tolerance"]["matches"] == []
    assert contact["interval_coverage"]["matched_count"] == 0
    recognition = report["recognition"]
    assert recognition["family"]["per_class"]["drive"]["tp"] == 0
    assert recognition["family"]["per_class"]["drive"]["fp"] == 1
    assert recognition["family"]["per_class"]["drive"]["fn"] == 1
    assert recognition["hitter"]["correct_count"] == 0
    assert recognition["hitter"]["known_contact_count"] == 1
    assert recognition["complete_event"]["tp"] == 0
    assert (
        recognition["complete_event"]["fp"] == recognition["complete_event"]["fn"] == 1
    )
    assert recognition["unmatched_candidate_ids"] == ["after-cut"]


def test_api_contact_and_recognition_cannot_credit_across_camera_cut(workspace):
    ctx = workspace
    before = {key: path.read_bytes() for key, path in ctx.paths.items()}
    response = api_report(ctx)
    assert response.status_code == 200, response.text
    report = response.json()
    assert_no_cross_cut_credit(report)
    assert report["video_sha256"] == ctx.video["sha256"]
    assert report["annotation_revision"] == ctx.doc["revision"]
    assert report["contacts"] == evaluate_contacts(
        ctx.video, ctx.doc, ctx.runs["contacts"]
    )
    assert report["recognition"] == evaluate_recognition(
        ctx.video, ctx.doc, ctx.runs["recognition"]
    )
    assert ctx.store.annotations(ctx.video["id"]).model_dump() == ctx.doc
    assert before == {key: path.read_bytes() for key, path in ctx.paths.items()}


def test_cli_matches_api_and_preserves_saved_artifacts(workspace, monkeypatch, capsys):
    from badminton import cli

    ctx = workspace
    before = {key: path.read_bytes() for key, path in ctx.paths.items()}
    response = api_report(ctx)
    assert response.status_code == 200, response.text
    monkeypatch.setattr(cli, "ROOT", ctx.root)
    monkeypatch.setattr(cli, "DATA", ctx.data)
    output = ctx.root / "evaluation.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "badminton",
            "evaluate",
            ctx.video["id"],
            "--contacts-run",
            "contacts-1",
            "--recognition-run",
            "recognition-1",
            "--output",
            str(output),
        ],
    )
    cli.main()
    report = json.loads(capsys.readouterr().out)
    assert report == json.loads(output.read_bytes())
    assert report == response.json() | {"schema_version": 1}
    assert_no_cross_cut_credit(report)
    assert before == {key: path.read_bytes() for key, path in ctx.paths.items()}
    assert ctx.store.annotations(ctx.video["id"]).model_dump() == ctx.doc


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize("cut", [True, -1, 40, "20", None])
def test_api_rejects_malformed_saved_camera_metadata(workspace, stage, cut):
    ctx = workspace
    run = deepcopy(ctx.runs[stage])
    run["cut_frames"] = [cut]
    write_json(ctx.paths[stage], run)
    response = api_report(ctx, {stage + "_run_id": stage + "-1"})
    assert response.status_code == 422, response.text
    assert ctx.store.annotations(ctx.video["id"]).model_dump() == ctx.doc


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
def test_api_rejects_saved_context_after_reviewed_camera_change(workspace, stage):
    ctx = workspace
    changed = deepcopy(ctx.doc)
    changed["camera_corrections"] = [{"frame": 10, "is_cut": True}]
    ctx.store.save_annotations(ctx.video["id"], Annotations.model_validate(changed))
    response = api_report(ctx, {stage + "_run_id": stage + "-1"})
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
def test_api_rejects_removed_top_level_cut_with_separate_court_context(
    workspace, stage
):
    ctx = workspace
    run = ctx.runs[stage]
    run["court_context"]["cut_frames"] = []
    write_json(ctx.paths[stage], run)
    changed = deepcopy(ctx.doc)
    changed["camera_corrections"] = [{"frame": 20, "is_cut": False}]
    ctx.store.save_annotations(ctx.video["id"], Annotations.model_validate(changed))
    response = api_report(ctx, {stage + "_run_id": stage + "-1"})
    assert response.status_code == 422, response.text
    assert "Camera review changed" in response.json()["detail"]


@pytest.mark.parametrize("evidence_only", [False, True])
def test_api_excludes_cross_camera_proposal_domain_from_both_evaluators(
    workspace, evidence_only
):
    ctx = workspace
    for stage, run in ctx.runs.items():
        candidate = run["candidates"][0]
        if evidence_only:
            candidate.update(context_start_frame=18, context_end_frame=22)
        elif stage == "contacts":
            candidate.update(start_frame=19, end_frame=21)
        else:
            candidate.update(contact_start_frame=19, contact_end_frame=21)
        write_json(ctx.paths[stage], run)
    response = api_report(ctx)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["contacts"]["metrics"]["fn"] == 1
    assert (
        report["contacts"]["metrics"]["tp"] == report["contacts"]["metrics"]["fp"] == 0
    )
    assert report["contacts"]["coverage"]["evaluated_candidate_ids"] == []
    assert report["contacts"]["coverage"]["excluded_candidates"] == 1
    assert report["recognition"]["family"]["per_class"]["drive"]["fn"] == 1
    assert report["recognition"]["family"]["per_class"]["drive"]["fp"] == 0
    assert report["recognition"]["complete_event"]["fp"] == 0
    assert report["recognition"]["complete_event"]["fn"] == 1
    assert report["recognition"]["unmatched_candidate_ids"] == []


def test_existing_same_view_matching_and_negative_coverage_remain(workspace):
    ctx = workspace
    for stage, run in ctx.runs.items():
        run["candidates"][0].update(frame=18, time_s=0.72)
        write_json(ctx.paths[stage], run)
    response = api_report(ctx)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["contacts"]["metrics"]["tp"] == 1
    assert report["recognition"]["complete_event"]["tp"] == 1
    assert report["contacts"]["coverage"]["reviewed_frames"] == 40
