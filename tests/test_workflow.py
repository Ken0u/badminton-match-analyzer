"""Exercise video timing, durable edits, and the public API together."""

import json
from fractions import Fraction

import av
import numpy as np
import pytest
from badminton.api import create_app
from badminton.ingest import inspect_video
from badminton.schemas import Annotations, Calibration, Event, empty_annotations
from badminton.storage import Store
from fastapi.testclient import TestClient
from pydantic import ValidationError


@pytest.fixture
def workspace(tmp_path):
    source = tmp_path / "fixture.mp4"
    # A small real VFR video catches accidental index/fps timestamp conversion.
    with av.open(str(source), "w") as container:
        stream = container.add_stream("libx264", rate=25)
        stream.width = 160
        stream.height = 96
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 1000)
        stream.codec_context.time_base = Fraction(1, 1000)
        for i, pts in enumerate([0, 40, 120, 160, 240, 280]):
            image = np.full((96, 160, 3), i * 35, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            frame.pts = pts
            frame.time_base = Fraction(1, 1000)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    data = tmp_path / "processed"
    store = Store(data)
    video = inspect_video(source, "singles", store, tmp_path)
    return tmp_path, data, store, video


def test_actual_timestamps_and_exact_frame(workspace):
    root, data, _store, v = workspace
    times = json.loads((data / v["id"] / "timestamps.json").read_text())
    assert times == pytest.approx([0, 0.04, 0.12, 0.16, 0.24, 0.28])
    assert v["variable_frame_rate"] is True
    with TestClient(create_app(root, data)) as client:
        image = client.get(f"/api/videos/{v['id']}/frame?index=2")
        assert (
            image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
        )
        import io

        from PIL import Image

        pixel = np.asarray(Image.open(io.BytesIO(image.content))).mean()
        assert 55 < pixel < 80
        assert client.get(f"/api/videos/{v['id']}/frame?index=6").status_code == 422


def test_revision_conflict_preserves_history_and_export(workspace):
    root, data, store, v = workspace
    with TestClient(create_app(root, data)) as client:
        url = f"/api/videos/{v['id']}"
        doc = client.get(url + "/annotations").json()
        initial = json.loads(json.dumps(doc))
        doc["events"] = [
            {
                "id": "e1",
                "rally_id": "R1",
                "kind": "shot",
                "frame": 2,
                "time_s": 99,
                "player_id": "A",
                "family": "clear",
                "side": "forehand",
                "notes": "=SUM(A1)",
            }
        ]
        saved = client.put(url + "/annotations", json=doc)
        assert saved.status_code == 200, saved.text
        assert saved.json()["revision"] == 1
        assert saved.json()["events"][0]["time_s"] == pytest.approx(0.12)
        assert client.put(url + "/annotations", json=initial).status_code == 409
        assert client.get(url + "/revisions/0").json()["events"] == []
        assert client.get(url + "/export").json()["annotations"]["revision"] == 1
        csv = client.get(url + "/export?format=csv").text
        assert "team_id" in csv and "T1" in csv and "'=SUM(A1)" in csv
        # Re-importing must not reset corrections.
        inspect_video(root / "fixture.mp4", "singles", store, root)
        assert store.annotations(v["id"]).revision == 1
        with pytest.raises(ValueError, match="different match format"):
            inspect_video(root / "fixture.mp4", "doubles", store, root)
        assert store.video(v["id"])["mode"] == "singles"


def test_schema_rejects_removed_class_and_invalid_identity():
    with pytest.raises(ValidationError):
        Event(
            id="e",
            rally_id="R1",
            kind="shot",
            frame=0,
            family="half_smash",
            side="forehand",
        )
    doc = empty_annotations("doubles").model_dump()
    doc["events"] = [
        {
            "id": "e",
            "rally_id": "R1",
            "kind": "shot",
            "frame": 0,
            "family": "drive",
            "side": "backhand",
            "player_id": "E",
        }
    ]
    with pytest.raises(ValidationError, match="Unknown player"):
        Annotations.model_validate(doc)


def test_boundaries_and_court_order_are_validated():
    doc = empty_annotations("singles").model_dump()
    doc["events"] = [
        {"id": "s", "rally_id": "R1", "kind": "serve", "frame": 10},
        {"id": "end", "rally_id": "R1", "kind": "rally_end", "frame": 5},
    ]
    with pytest.raises(ValidationError, match="ending must follow"):
        Annotations.model_validate(doc)
    with pytest.raises(ValidationError, match="convex"):
        Calibration(
            start_frame=0,
            end_frame=100,
            corners=[
                {"x": 0.1, "y": 0.1},
                {"x": 0.9, "y": 0.9},
                {"x": 0.9, "y": 0.1},
                {"x": 0.1, "y": 0.9},
            ],
        )


def test_api_range_streaming_and_path_containment(workspace):
    root, data, _store, v = workspace
    with TestClient(create_app(root, data)) as client:
        url = f"/api/videos/{v['id']}"
        r = client.get(url + "/media", headers={"Range": "bytes=0-31"})
        assert r.status_code == 206 and len(r.content) == 32
        assert (
            client.post(
                "/api/import", json={"path": "../elsewhere.mp4", "mode": "singles"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                url + "/track", json={"start_frame": 4, "end_frame": 3}
            ).status_code
            == 422
        )
        assert client.get("/api/videos/missing/annotations").status_code == 404


def test_interrupted_jobs_are_recoverable(workspace):
    root, data, store, v = workspace
    store.put_job(
        {
            "id": "abandoned",
            "video_id": v["id"],
            "status": "running",
            "kind": "players",
            "progress": 0.3,
        }
    )
    with TestClient(create_app(root, data)) as client:
        job = client.get("/api/jobs").json()[0]
        assert job["status"] == "interrupted"
        assert "retry" in job["message"]


def test_job_claims_are_shared_and_recovery_preserves_live_workers(workspace):
    from concurrent.futures import ThreadPoolExecutor

    from badminton.storage import ConflictError

    root, data, store, v = workspace

    def claim(number):
        job = {
            "id": f"worker-{number}",
            "video_id": v["id"],
            "kind": "players",
            "status": "running",
            "progress": 0,
        }
        try:
            Store(data).claim_job(job)
            return job
        except ConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = [job for job in pool.map(claim, [1, 2]) if job]
    assert len(winners) == 1
    # A second web instance must not interrupt a still-running CLI/server worker.
    with TestClient(create_app(root, data)) as client:
        assert client.get("/api/jobs").json()[0]["status"] == "running"
    job = winners[0]
    job["owner_started"] += 1  # Same PID, different process lifetime is stale.
    store.put_job(job)
    store.recover_jobs()
    assert store.jobs()[0]["status"] == "interrupted"


def test_changed_video_is_rejected_before_streaming_or_tracking(workspace):
    root, data, _store, v = workspace
    with (root / "fixture.mp4").open("ab") as out:
        out.write(b"changed")
    with TestClient(create_app(root, data)) as client:
        assert client.get(f"/api/videos/{v['id']}/media").status_code == 409
        assert client.get(f"/api/videos/{v['id']}/frame?index=0").status_code == 409
        assert (
            client.post(
                f"/api/videos/{v['id']}/track", json={"start_frame": 0, "end_frame": 3}
            ).status_code
            == 409
        )


def test_nonfinite_clip_arguments_are_rejected(workspace):
    from badminton.video import seconds_to_frames, timestamps_for

    _root, data, _store, v = workspace
    for start, duration in [
        (float("nan"), 1),
        (0, float("nan")),
        (0, float("inf")),
        (-1, 1),
        (5, 1),
    ]:
        with pytest.raises(ValueError):
            seconds_to_frames(v, timestamps_for(data, v["id"]), start, duration)


def test_calibration_summary_only_counts_the_selected_clip(workspace, monkeypatch):
    import sys
    from types import SimpleNamespace

    torch = pytest.importorskip("torch")
    import badminton.tracking as tracking
    from badminton.tracking import track_players

    root, data, store, v = workspace
    weights = root / "weights"
    weights.mkdir()
    (weights / "yolo11n-pose.pt").write_bytes(b"unit-test-placeholder")
    monkeypatch.setattr(tracking, "WEIGHTS", weights)
    doc = store.annotations(v["id"])
    doc.calibrations = [
        Calibration(
            start_frame=4,
            end_frame=6,
            corners=[
                {"x": 0.1, "y": 0.1},
                {"x": 0.9, "y": 0.1},
                {"x": 0.9, "y": 0.9},
                {"x": 0.1, "y": 0.9},
            ],
        )
    ]

    class FakeModel:
        def __init__(self, path):
            pass

        def track(self, *args, **kwargs):
            return [SimpleNamespace(boxes=[])]

    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=FakeModel))
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    summary = track_players(
        v, root, data, doc, 0, 3, 1, lambda p: None, data / "run.json"
    )
    assert summary["processed_frames"] == 3
    assert summary["calibrated"] is False and summary["calibrated_frames"] == 0


def test_duplicate_contact_and_provenance_are_rejected():
    doc = empty_annotations("singles").model_dump()
    doc["events"] = [
        {"id": "s", "rally_id": "R1", "kind": "serve", "frame": 10},
        {
            "id": "shot",
            "rally_id": "R1",
            "kind": "shot",
            "frame": 10,
            "family": "clear",
            "side": "forehand",
        },
    ]
    with pytest.raises(ValidationError, match="only one serve or shot"):
        Annotations.model_validate(doc)
    with pytest.raises(ValidationError, match="both run and candidate"):
        Event(
            id="s",
            rally_id="R1",
            kind="shot",
            frame=10,
            family="clear",
            side="forehand",
            candidate_id="orphan",
        )


def test_contact_job_produces_separate_artifact_without_editing_annotations(workspace):
    import time

    from badminton.video import write_json

    root, data, store, v = workspace
    run_id = "cached-shuttle"
    run = {
        "stage": "shuttle",
        "video_id": v["id"],
        "start_frame": 0,
        "end_frame": 6,
        "frames": [],
    }
    write_json(data / v["id"] / "runs" / f"{run_id}.json", run)
    store.put_job(
        {
            "id": run_id,
            "video_id": v["id"],
            "kind": "shuttle",
            "status": "completed",
            "progress": 1,
        }
    )
    with TestClient(create_app(root, data)) as client:
        response = client.post(
            f"/api/videos/{v['id']}/contacts", json={"shuttle_run_id": run_id}
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        for _ in range(200):
            job = next(j for j in store.jobs() if j["id"] == job_id)
            if job["status"] not in ("queued", "running"):
                break
            time.sleep(0.01)
        assert job["status"] == "completed"
        result = client.get(f"/api/videos/{v['id']}/runs/{job_id}").json()
        assert result["candidates"] == [] and result["shuttle_run_id"] == run_id
        assert store.annotations(v["id"]).revision == 0
        assert (
            client.post(
                f"/api/videos/{v['id']}/contacts", json={"shuttle_run_id": job_id}
            ).status_code
            == 404
        )


def test_missing_run_artifact_is_a_recoverable_not_found(workspace):
    root, data, store, v = workspace
    store.put_job(
        {
            "id": "missing-run",
            "video_id": v["id"],
            "kind": "shuttle",
            "status": "completed",
            "progress": 1,
        }
    )
    with TestClient(create_app(root, data)) as client:
        assert client.get(f"/api/videos/{v['id']}/runs/missing-run").status_code == 404
        assert (
            client.post(
                f"/api/videos/{v['id']}/contacts",
                json={"shuttle_run_id": "missing-run"},
            ).status_code
            == 404
        )


def test_cli_runner_releases_admission_after_success_and_interrupt(workspace):
    from badminton.jobs import run_local_job

    _root, _data, store, v = workspace

    def succeed(job_id, progress):
        progress(0.5)
        return {"processed": 1}

    assert run_local_job(store, "import", None, succeed) == {"processed": 1}
    assert store.jobs()[0]["status"] == "completed"

    def interrupt(job_id, progress):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_local_job(store, "players", v["id"], interrupt)
    assert store.jobs()[0]["status"] == "interrupted"
    assert run_local_job(store, "players", v["id"], succeed) == {"processed": 1}
