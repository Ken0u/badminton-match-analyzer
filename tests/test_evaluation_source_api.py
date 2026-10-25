"""Generated saved-run source-hash checks through evaluation API and CLI."""

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


@pytest.fixture
def workspace(tmp_path):
    source = tmp_path / "generated.mp4"
    source.write_bytes(b"generated-evaluation-source-provenance")
    data = tmp_path / "processed"
    store = Store(data)
    video = {
        "id": "source-video",
        "path": source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "mode": "singles",
        "frame_count": 20,
        "duration_s": 0.8,
        "width": 640,
        "height": 360,
        "fps": 25,
        "source_start_s": 0,
    }
    store.register(video)
    write_json(data / video["id"] / "timestamps.json", [i * 0.04 for i in range(20)])
    doc = store.annotations(video["id"]).model_dump()
    doc.update(
        events=[
            {
                "id": "hit",
                "rally_id": "r1",
                "kind": "shot",
                "frame": 5,
                "status": "reviewed",
                "family": "unknown",
                "side": "unknown",
            }
        ],
        review_windows=[
            {
                "id": "review",
                "start_frame": 0,
                "end_frame": 20,
                "scene": "live",
                "contacts_complete": True,
            }
        ],
        shuttle_points=[{"frame": 5, "visible": True, "x": 0.5, "y": 0.5}],
    )
    store.save_annotations(video["id"], Annotations.model_validate(doc))
    paths = {}
    for stage in ("contacts", "shuttle"):
        run_id = stage + "-1"
        run = {
            "video_id": video["id"],
            "video_sha256": video["sha256"],
            "stage": stage,
            "start_frame": 0,
            "end_frame": 20,
        }
        if stage == "contacts":
            run["candidates"] = [{"id": "proposal", "frame": 5, "time_s": 0.2}]
        else:
            run["frames"] = [
                {
                    "frame": 5,
                    "time_s": 0.2,
                    "shuttle": {"visible": True, "x": 320, "y": 180},
                }
            ]
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
        paths[stage] = path
    return SimpleNamespace(
        root=tmp_path, data=data, video=video, store=store, paths=paths
    )


def prepare(ctx, stage, variant):
    run = json.loads(ctx.paths[stage].read_bytes())
    if variant == "missing":
        run.pop("video_sha256")
    elif variant == "mismatching":
        run["video_sha256"] = "0" * 64
    elif variant == "null":
        run["video_sha256"] = None
    elif variant == "malformed":
        run["video_sha256"] = "not-a-source-hash"
    write_json(ctx.paths[stage], run)
    return {p: p.read_bytes() for p in ctx.data.rglob("*.json")}


@pytest.mark.parametrize("stage", ["contacts", "shuttle"])
@pytest.mark.parametrize(
    "variant", ["matching", "missing", "mismatching", "null", "malformed"]
)
def test_api_evaluation_source_hash_validation(workspace, stage, variant):
    ctx = workspace
    before = prepare(ctx, stage, variant)
    annotations = deepcopy(ctx.store.annotations(ctx.video["id"]).model_dump())
    with TestClient(
        create_app(ctx.root, ctx.data), raise_server_exceptions=False
    ) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={stage + "_run_id": stage + "-1"},
        )
    if variant in ("matching", "missing"):
        assert response.status_code == 200, response.text
        report = response.json()[stage]
        assert report["metrics"]["f1"] == 1
        assert report["prediction_source_hash_status"] == (
            "matched" if variant == "matching" else "unavailable"
        )
    else:
        assert response.status_code == 422, response.text
        assert "source hash" in response.json()["detail"]
        assert stage not in response.json()
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert ctx.store.annotations(ctx.video["id"]).model_dump() == annotations


@pytest.mark.parametrize("stage", ["contacts", "shuttle"])
@pytest.mark.parametrize(
    "variant", ["matching", "missing", "mismatching", "null", "malformed"]
)
def test_cli_evaluation_source_hash_validation(
    workspace, stage, variant, monkeypatch, capsys
):
    from badminton import cli

    ctx = workspace
    before = prepare(ctx, stage, variant)
    output = ctx.root / "report.json"
    monkeypatch.setattr(cli, "ROOT", ctx.root)
    monkeypatch.setattr(cli, "DATA", ctx.data)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "badminton",
            "evaluate",
            ctx.video["id"],
            "--" + stage + "-run",
            stage + "-1",
            "--output",
            str(output),
        ],
    )
    if variant in ("matching", "missing"):
        cli.main()
        report = json.loads(output.read_bytes())[stage]
        assert report["metrics"]["f1"] == 1
        assert report["prediction_source_hash_status"] == (
            "matched" if variant == "matching" else "unavailable"
        )
        assert json.loads(capsys.readouterr().out)[stage] == report
    else:
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 2
        assert not output.exists()
        captured = capsys.readouterr()
        assert not captured.out
        assert "source hash" in captured.err
    assert all(path.read_bytes() == raw for path, raw in before.items())
