"""Unresolved reference intervals at review edges in real saved evaluation paths."""

import hashlib
import json
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest
from badminton.api import create_app
from badminton.schemas import Annotations
from badminton.storage import Store
from badminton.video import write_json
from fastapi.testclient import TestClient


@pytest.fixture(params=["singles", "doubles"])
def workspace(tmp_path, request):
    source = tmp_path / "generated.mp4"
    source.write_bytes(b"generated-uncertainty-evaluation-source")
    data = tmp_path / "processed"
    store = Store(data)
    times = [2 + i * 0.04 + (i % 2) * 0.003 for i in range(40)]
    video = {
        "id": "uncertain-video",
        "path": source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "mode": request.param,
        "frame_count": 40,
        "duration_s": times[-1] + 0.04,
        "width": 640,
        "height": 360,
        "fps": 25,
        "source_start_s": 2,
    }
    store.register(video)
    time_path = data / video["id"] / "timestamps.json"
    write_json(time_path, times)
    doc = store.annotations(video["id"]).model_dump()
    doc["events"] = [
        {
            "id": "exact",
            "rally_id": "r1",
            "kind": "shot",
            "frame": 15,
            "status": "reviewed",
            "family": "drive",
            "side": "forehand",
            "player_id": "A",
        }
    ]
    doc["review_windows"] = [
        {
            "id": "reviewed",
            "start_frame": 10,
            "end_frame": 20,
            "scene": "live",
            "contacts_complete": True,
        }
    ]
    saved = store.save_annotations(video["id"], Annotations.model_validate(doc))
    paths = []
    for stage in ("contacts", "recognition"):
        run_id = stage + "-1"
        run = {
            "video_id": video["id"],
            "video_sha256": video["sha256"],
            "stage": stage,
            "run_id": run_id,
            "start_frame": 0,
            "end_frame": 40,
            "candidates": [
                {
                    "id": "prediction",
                    "frame": 15,
                    "time_s": times[15],
                    "status": "predicted",
                    "kind": "shot",
                    "family": "drive",
                    "side": "forehand",
                    "hitter_hint": {"player_id": "A"},
                }
            ],
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
        paths.append(path)
    return SimpleNamespace(
        root=tmp_path,
        data=data,
        store=store,
        video=video,
        doc=saved.model_dump(),
        paths=[source, time_path, *paths],
    )


def api_report(ctx):
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={
                "contacts_run_id": "contacts-1",
                "recognition_run_id": "recognition-1",
            },
        )
    assert response.status_code == 200, response.text
    return response.json()


def snapshot(ctx):
    with ctx.store.connect() as db:
        rows = list(
            db.execute(
                "SELECT revision,document,saved_at FROM annotations ORDER BY revision"
            )
        )
    return (
        rows,
        ctx.store.video(ctx.video["id"]),
        {str(path): path.read_bytes() for path in ctx.paths},
    )


def save_uncertainty(ctx, frame, bounds):
    doc = deepcopy(ctx.doc)
    doc["events"].append(
        doc["events"][0]
        | {
            "id": "unresolved",
            "frame": frame,
            "contact_start_frame": bounds[0],
            "contact_end_frame": bounds[1],
        }
    )
    return ctx.store.save_annotations(
        ctx.video["id"], Annotations.model_validate(doc)
    ).model_dump()


def assert_withheld(report):
    contact, recognition = report["contacts"], report["recognition"]
    assert contact["status"] == "needs_complete_live_review"
    assert contact["metrics"] is contact["interval_coverage"] is None
    for result in (contact, recognition):
        assert result["coverage"]["skipped_windows"] == [
            {"id": "reviewed", "reason": "contact_timing_needs_adjudication"}
        ]
        assert result["coverage"]["excluded_reviewed_contacts"] == 2
        assert result["coverage"]["excluded_candidates"] == 1
    assert recognition["status"] == "needs_complete_live_review"
    assert recognition["family"]["known_contact_count"] == 0
    assert recognition["complete_event"] is None


@pytest.mark.parametrize("frame,bounds", [(9, (9, 10)), (20, (19, 20))])
def test_saved_api_withholds_overlapping_uncertainty(workspace, frame, bounds):
    ctx = workspace
    stable = api_report(ctx)
    assert stable["contacts"]["metrics"]["f1"] == 1
    assert stable["recognition"]["complete_event"]["f1"] == 1
    saved = save_uncertainty(ctx, frame, bounds)
    before = snapshot(ctx)
    report = api_report(ctx)
    assert report["annotation_revision"] == saved["revision"]
    assert snapshot(ctx) == before
    assert ctx.store.annotations(ctx.video["id"]).model_dump() == saved
    assert_withheld(report)


@pytest.mark.parametrize("frame,bounds", [(9, (9, 10)), (20, (19, 20))])
def test_saved_cli_matches_api_and_preserves_revisions(
    workspace, frame, bounds, monkeypatch, capsys
):
    from badminton import cli

    ctx = workspace
    save_uncertainty(ctx, frame, bounds)
    before = snapshot(ctx)
    monkeypatch.setattr(cli, "ROOT", ctx.root)
    monkeypatch.setattr(cli, "DATA", ctx.data)
    output = ctx.root / "report.json"
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
    assert report == api_report(ctx) | {"schema_version": 1}
    assert snapshot(ctx) == before
    assert_withheld(report)


@pytest.mark.parametrize("frame,bounds", [(9, (8, 9)), (20, (20, 21))])
def test_saved_disjoint_uncertainty_keeps_both_scores(workspace, frame, bounds):
    ctx = workspace
    saved = save_uncertainty(ctx, frame, bounds)
    before = snapshot(ctx)
    report = api_report(ctx)
    assert report["contacts"]["metrics"]["f1"] == 1
    assert report["contacts"]["coverage"]["skipped_windows"] == []
    assert report["contacts"]["coverage"]["excluded_reviewed_contacts"] == 1
    assert report["recognition"]["complete_event"]["f1"] == 1
    assert ctx.store.annotations(ctx.video["id"]).model_dump() == saved
    assert snapshot(ctx) == before
