"""Actual API/CLI evaluation of generated registered shuttle artifacts."""

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


@pytest.fixture(params=["singles", "doubles"])
def workspace(tmp_path, request):
    source = tmp_path / "generated.mp4"
    source.write_bytes(b"generated-shuttle-clock")
    data = tmp_path / "processed"
    store = Store(data)
    video = {
        "id": "clock-video",
        "path": source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "mode": request.param,
        "frame_count": 20,
        "width": 640,
        "height": 360,
        "duration_s": 1,
        "fps": 25,
        "source_start_s": 1.25,
    }
    store.register(video)
    return SimpleNamespace(
        root=tmp_path, source=source, data=data, store=store, video=video
    )


def prepare(ctx, variable, variant):
    times = [i * 0.04 + (i // 3) * 0.003 * variable for i in range(20)]
    clock = ctx.data / ctx.video["id"] / "timestamps.json"
    write_json(clock, times)
    doc = ctx.store.annotations(ctx.video["id"]).model_dump()
    doc.update(
        events=[
            {
                "id": "hit",
                "rally_id": "r1",
                "kind": "shot",
                "frame": 15,
                "family": "drive",
                "side": "forehand",
                "player_id": "A",
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
        shuttle_points=[{"frame": 15, "visible": True, "x": 0.5, "y": 0.5}],
    )
    ctx.store.save_annotations(ctx.video["id"], Annotations.model_validate(doc))
    for stage in ("shuttle", "contacts", "recognition"):
        run = {
            "stage": stage,
            "video_id": ctx.video["id"],
            "video_sha256": ctx.video["sha256"],
            "start_frame": 0,
            "end_frame": 20,
        }
        if stage == "shuttle":
            run["frames"] = [
                {
                    "frame": 15,
                    "time_s": times[15],
                    "shuttle": {"visible": True, "x": 320, "y": 180},
                }
            ]
            if variant == "wrong_time":
                run["frames"][0]["time_s"] = times[5]
            elif variant == "unlabelled_wrong_time":
                run["frames"].append(
                    {
                        "frame": 5,
                        "time_s": times[15],
                        "shuttle": {"visible": False, "x": None, "y": None},
                    }
                )
        else:
            run["candidates"] = [
                {
                    "id": "hit",
                    "frame": 15,
                    "time_s": times[15],
                    "kind": "shot",
                    "family": "drive",
                    "side": "forehand",
                    "status": "predicted",
                    "hitter_hint": {"player_id": "A"},
                }
            ]
        run_id = stage + "-clock"
        write_json(ctx.data / ctx.video["id"] / "runs" / (run_id + ".json"), run)
        ctx.store.put_job(
            {
                "id": run_id,
                "video_id": ctx.video["id"],
                "kind": stage,
                "status": "completed",
                "progress": 1,
            }
        )
    if variant == "missing_clock":
        clock.unlink()
    elif variant == "malformed_clock":
        clock.write_bytes(b"not-json")
    elif variant == "short_clock":
        write_json(clock, times[:-1])
    return {p: p.read_bytes() for p in ctx.data.rglob("*.json")}


VARIANTS = [
    "matching",
    "wrong_time",
    "unlabelled_wrong_time",
    "missing_clock",
    "malformed_clock",
    "short_clock",
]


@pytest.mark.parametrize("variable", [False, True], ids=["cfr", "vfr"])
@pytest.mark.parametrize("variant", VARIANTS)
def test_api_shuttle_native_clock(workspace, variable, variant):
    ctx = workspace
    before = prepare(ctx, variable, variant)
    with TestClient(
        create_app(ctx.root, ctx.data), raise_server_exceptions=False
    ) as client:
        response = client.post(
            "/api/videos/clock-video/evaluate", json={"shuttle_run_id": "shuttle-clock"}
        )
    if variant == "matching":
        assert response.status_code == 200, response.text
        report = response.json()["shuttle"]
        assert report["metrics"]["f1"] == 1
        assert report["prediction_clock_status"] == "validated"
    else:
        assert response.status_code == 422, response.text
        assert "time" in response.json()["detail"].lower()
        assert "shuttle" not in response.json()
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert ctx.source.read_bytes() == b"generated-shuttle-clock"


@pytest.mark.parametrize("variable", [False, True], ids=["cfr", "vfr"])
@pytest.mark.parametrize("variant", VARIANTS)
def test_cli_shuttle_native_clock(workspace, variable, variant, monkeypatch, capsys):
    from badminton import cli

    ctx = workspace
    before = prepare(ctx, variable, variant)
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
            "clock-video",
            "--shuttle-run",
            "shuttle-clock",
            "--output",
            str(output),
        ],
    )
    if variant == "matching":
        cli.main()
        report = json.loads(output.read_bytes())
        assert report["shuttle"]["metrics"]["f1"] == 1
        assert report["shuttle"]["prediction_clock_status"] == "validated"
        assert json.loads(capsys.readouterr().out) == report
    else:
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 2
        assert output.read_bytes() == previous
        captured = capsys.readouterr()
        assert not captured.out
        assert "time" in captured.err.lower()
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert ctx.source.read_bytes() == b"generated-shuttle-clock"


@pytest.mark.parametrize("bad_shuttle", [False, True])
def test_combined_evaluation_validates_shuttle_before_publishing_any_report(
    workspace, bad_shuttle
):
    ctx = workspace
    before = prepare(ctx, True, "wrong_time" if bad_shuttle else "matching")
    with TestClient(
        create_app(ctx.root, ctx.data), raise_server_exceptions=False
    ) as client:
        response = client.post(
            "/api/videos/clock-video/evaluate",
            json={
                stage + "_run_id": stage + "-clock"
                for stage in ("shuttle", "contacts", "recognition")
            },
        )
    if bad_shuttle:
        assert response.status_code == 422, response.text
        assert "contacts" not in response.json()
        assert "recognition" not in response.json()
    else:
        assert response.status_code == 200, response.text
        for stage in ("contacts", "recognition", "shuttle"):
            assert response.json()[stage]["prediction_clock_status"] == "validated"
        assert response.json()["shuttle"]["metrics"]["f1"] == 1
    assert all(p.read_bytes() == raw for p, raw in before.items())


@pytest.mark.parametrize("bad_shuttle", [False, True])
def test_cli_combined_evaluation_preserves_existing_report_on_failure(
    workspace, bad_shuttle, monkeypatch, capsys
):
    from badminton import cli

    ctx = workspace
    before = prepare(ctx, True, "wrong_time" if bad_shuttle else "matching")
    output = ctx.root / "combined.json"
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
            "clock-video",
            "--shuttle-run",
            "shuttle-clock",
            "--contacts-run",
            "contacts-clock",
            "--recognition-run",
            "recognition-clock",
            "--output",
            str(output),
        ],
    )
    if bad_shuttle:
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 2
        assert output.read_bytes() == previous
        assert not capsys.readouterr().out
    else:
        cli.main()
        report = json.loads(output.read_bytes())
        for stage in ("contacts", "recognition", "shuttle"):
            assert report[stage]["prediction_clock_status"] == "validated"
        assert json.loads(capsys.readouterr().out) == report
    assert all(p.read_bytes() == raw for p, raw in before.items())
