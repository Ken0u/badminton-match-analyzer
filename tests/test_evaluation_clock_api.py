"""Native clock identity through registered generated evaluation artifacts."""

import hashlib
import json
import sys
from types import SimpleNamespace

import pytest
from badminton.api import create_app
from badminton.schemas import Annotations
from badminton.storage import Store
from badminton.video import write_json
from fastapi.testclient import TestClient


@pytest.fixture(params=[False, True], ids=["constant-clock", "variable-clock"])
def workspace(tmp_path, request):
    source = tmp_path / "generated.mp4"
    source.write_bytes(b"generated-evaluation-native-clock")
    data = tmp_path / "processed"
    store = Store(data)
    times = [i * 0.04 + (i // 3) * 0.003 * request.param for i in range(20)]
    video = {
        "id": "clock-video",
        "path": source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "mode": "singles",
        "frame_count": len(times),
        "duration_s": times[-1] + 0.04,
        "width": 640,
        "height": 360,
        "fps": 25,
        "source_start_s": 0,
    }
    store.register(video)
    clock_path = data / video["id"] / "timestamps.json"
    write_json(clock_path, times)
    doc = store.annotations(video["id"]).model_dump()
    doc.update(
        events=[
            {
                "id": "hit",
                "rally_id": "r1",
                "kind": "shot",
                "frame": 15,
                "status": "reviewed",
                "family": "drive",
                "side": "forehand",
                "player_id": "A",
            }
        ],
        review_windows=[
            {
                "id": "review",
                "start_frame": 0,
                "end_frame": len(times),
                "scene": "live",
                "contacts_complete": True,
            }
        ],
        shuttle_points=[{"frame": 15, "visible": True, "x": 0.5, "y": 0.5}],
    )
    store.save_annotations(video["id"], Annotations.model_validate(doc))
    paths = {}
    for stage in ("contacts", "recognition", "shuttle"):
        run_id = stage + "-clock"
        run = {
            "video_id": video["id"],
            "video_sha256": video["sha256"],
            "stage": stage,
            "start_frame": 0,
            "end_frame": len(times),
        }
        if stage == "shuttle":
            run["frames"] = [
                {
                    "frame": 15,
                    "time_s": times[15],
                    "shuttle": {"visible": True, "x": 320, "y": 180},
                }
            ]
        else:
            run["candidates"] = [
                {
                    "id": "proposal",
                    "frame": 15,
                    "time_s": times[15],
                    "kind": "shot",
                    "family": "drive",
                    "side": "forehand",
                    "status": "predicted",
                    "hitter_hint": {"player_id": "A"},
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
        root=tmp_path,
        source=source,
        data=data,
        video=video,
        store=store,
        times=times,
        clock_path=clock_path,
        paths=paths,
    )


def prepare(ctx, stage, variant):
    run = json.loads(ctx.paths[stage].read_bytes())
    candidate = run["candidates"][0]
    if variant == "nearby":
        candidate.update(frame=14, time_s=ctx.times[14])
    elif variant in ("wrong_time", "excluded_wrong_time"):
        candidate["frame"] = 5
    elif variant in ("wrong_start", "wrong_end"):
        candidate.update(start_time_s=ctx.times[14], end_time_s=ctx.times[16])
        if stage == "contacts":
            candidate.update(start_frame=14, end_frame=16)
        else:
            candidate.update(contact_start_frame=14, contact_end_frame=16)
        if variant == "wrong_start":
            candidate["start_time_s"] = ctx.times[13]
        else:
            candidate["end_time_s"] = ctx.times[17]
    elif variant == "missing_time":
        candidate.pop("time_s")
    elif variant == "missing_clock":
        ctx.clock_path.unlink()
    elif variant == "malformed_clock":
        ctx.clock_path.write_text("not-json", encoding="utf-8")
    elif variant == "null_clock":
        write_json(ctx.clock_path, None)
    elif variant == "short_clock":
        write_json(ctx.clock_path, ctx.times[:-1])
    elif variant == "boolean_clock":
        write_json(ctx.clock_path, [False, *ctx.times[1:]])
    elif variant == "duplicate_clock":
        write_json(ctx.clock_path, [ctx.times[1], *ctx.times[1:]])
    elif variant == "changed_clock":
        write_json(ctx.clock_path, [t + 0.002 for t in ctx.times])
    if variant == "excluded_wrong_time":
        doc = ctx.store.annotations(ctx.video["id"]).model_dump()
        doc.update(events=[], review_windows=[])
        ctx.store.save_annotations(ctx.video["id"], Annotations.model_validate(doc))
    write_json(ctx.paths[stage], run)
    return {p: p.read_bytes() for p in ctx.data.rglob("*.json")}


VARIANTS = [
    "matching",
    "nearby",
    "wrong_time",
    "wrong_start",
    "wrong_end",
    "missing_time",
    "excluded_wrong_time",
    "missing_clock",
    "malformed_clock",
    "null_clock",
    "short_clock",
    "boolean_clock",
    "duplicate_clock",
    "changed_clock",
]


def assert_scored(report, stage):
    assert report["prediction_clock_status"] == "validated"
    if stage == "contacts":
        assert report["metrics"]["f1"] == 1
    else:
        assert report["family"]["per_class"]["drive"]["f1"] == 1
        assert report["complete_event"]["f1"] == 1


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize("variant", VARIANTS)
def test_api_native_clock_validation(workspace, stage, variant):
    ctx = workspace
    before = prepare(ctx, stage, variant)
    annotations = ctx.store.annotations(ctx.video["id"]).model_dump()
    with TestClient(
        create_app(ctx.root, ctx.data), raise_server_exceptions=False
    ) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={stage + "_run_id": stage + "-clock"},
        )
    if variant in ("matching", "nearby"):
        assert response.status_code == 200, response.text
        assert_scored(response.json()[stage], stage)
    else:
        assert response.status_code == 422, response.text
        assert "time" in response.json()["detail"].lower()
        assert stage not in response.json()
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert ctx.store.annotations(ctx.video["id"]).model_dump() == annotations
    assert ctx.source.read_bytes() == b"generated-evaluation-native-clock"
    if variant == "missing_clock":
        assert not ctx.clock_path.exists()


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize("variant", VARIANTS)
def test_cli_native_clock_validation(workspace, stage, variant, monkeypatch, capsys):
    from badminton import cli

    ctx = workspace
    before = prepare(ctx, stage, variant)
    annotations = ctx.store.annotations(ctx.video["id"]).model_dump()
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
            stage + "-clock",
            "--output",
            str(output),
        ],
    )
    if variant in ("matching", "nearby"):
        cli.main()
        report = json.loads(output.read_bytes())
        assert_scored(report[stage], stage)
        assert json.loads(capsys.readouterr().out) == report
    else:
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 2
        assert not output.exists()
        captured = capsys.readouterr()
        assert not captured.out
        assert "time" in captured.err.lower()
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert ctx.store.annotations(ctx.video["id"]).model_dump() == annotations


def test_combined_saved_evaluation_uses_native_clock_and_preserves_shuttle(workspace):
    ctx = workspace
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={stage + "_run_id": stage + "-clock" for stage in ctx.paths},
        )
    assert response.status_code == 200, response.text
    assert_scored(response.json()["contacts"], "contacts")
    assert_scored(response.json()["recognition"], "recognition")
    assert response.json()["shuttle"]["metrics"]["f1"] == 1


def test_cli_rejected_clock_does_not_overwrite_existing_report(
    workspace, monkeypatch, capsys
):
    from badminton import cli

    ctx = workspace
    prepare(ctx, "contacts", "wrong_time")
    output = ctx.root / "report.json"
    previous = b'{"previous_verified_report":true}\n'
    output.write_bytes(previous)
    monkeypatch.setattr(cli, "ROOT", ctx.root)
    monkeypatch.setattr(cli, "DATA", ctx.data)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "badminton",
            "evaluate",
            ctx.video["id"],
            "--contacts-run",
            "contacts-clock",
            "--output",
            str(output),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert output.read_bytes() == previous
    assert not capsys.readouterr().out
