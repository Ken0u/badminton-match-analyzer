import json
import threading
import time
from types import SimpleNamespace

import pytest
from badminton import pipeline
from badminton.api import create_app
from fastapi.testclient import TestClient
from test_pipeline import mode_workspace, mutate_input
from test_pipeline import workspace as workspace


def wait(store, job_id):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        job = store.job(job_id)
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.01)
    pytest.fail("The same processing job did not reach a terminal state")


def test_full_source_api_and_resume_preserve_annotations_and_expose_window_artifacts(
    workspace,
):
    root, store, _, _, calls = workspace
    before = store.annotations("test").model_dump()
    with TestClient(create_app(root, store.data)) as client:
        response = client.post("/api/videos/test/analysis", json={})
        assert response.status_code == 202
        identifier = response.json()["id"]
        job = wait(store, identifier)
        assert job["status"] == "completed", job
        result = client.get(f"/api/videos/test/analysis/{identifier}").json()
        assert result["completed_stages"] == 17
        assert result["processing_complete"] and not result["fully_annotated"]
        assert not result["requires_processing_rerun"]
        identity_url = "/api/videos/test/runs/" + result["identities"]["run_id"]
        identity = client.get(identity_url)
        assert identity.status_code == 200 and identity.json()["stage"] == "identities"
        assert not identity.json()["requires_context_rerun"]
        for part in result["parts"]:
            for stage in part["stages"].values():
                loaded = client.get("/api/videos/test/runs/" + stage["run_id"])
                assert loaded.status_code == 200, loaded.text
                assert (
                    loaded.json()["analysis_core_start_frame"]
                    == part["window"]["core_start_frame"]
                )
        calls.clear()
        resumed = client.post("/api/videos/test/analysis", json={})
        job = wait(store, resumed.json()["id"])
        assert job["status"] == "completed" and job["summary"]["reused_stages"] == 17
        assert calls == [] and store.annotations("test").model_dump() == before
        changed = before | {
            "scene_ranges": [
                {
                    "id": "replay",
                    "start_frame": 350,
                    "end_frame": 400,
                    "scene": "replay",
                }
            ]
        }
        assert (
            client.put("/api/videos/test/annotations", json=changed).status_code == 200
        )
        assert client.get(f"/api/videos/test/analysis/{identifier}").json()[
            "requires_processing_rerun"
        ]
        assert client.get(identity_url).json()["requires_context_rerun"]


def test_api_pause_preserves_admission_until_worker_acknowledges_then_resumes(
    workspace, monkeypatch
):
    root, store, _, _, _ = workspace
    entered, release = threading.Event(), threading.Event()
    original = pipeline.track_players

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5), "Test did not release the same worker"
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "track_players", blocked)
    with TestClient(create_app(root, store.data)) as client:
        response = client.post("/api/videos/test/analysis", json={})
        identifier = response.json()["id"]
        assert entered.wait(5)
        try:
            assert (
                client.post(f"/api/videos/test/analysis/{identifier}/pause").status_code
                == 202
            )
            assert client.post("/api/videos/test/analysis", json={}).status_code == 409
            assert (
                client.post(
                    f"/api/videos/foreign/analysis/{identifier}/pause"
                ).status_code
                == 404
            )
        finally:
            release.set()
        assert wait(store, identifier)["status"] == "interrupted"
        paused = client.get(f"/api/videos/test/analysis/{identifier}").json()
        assert paused["completed_stages"] == 1
        assert paused["state"] == "interrupted"
        monkeypatch.setattr(pipeline, "track_players", original)
        response = client.post("/api/videos/test/analysis", json={})
        final = wait(store, response.json()["id"])
        assert final["status"] == "completed" and final["summary"]["reused_stages"] == 1
        assert (
            client.post(f"/api/videos/test/analysis/{identifier}/pause").status_code
            == 409
        )


def test_source_and_request_guards_reject_before_queuing(workspace):
    root, store, video, _, calls = workspace
    with TestClient(create_app(root, store.data)) as client:
        assert (
            client.post(
                "/api/videos/test/analysis", json={"player_model": "../../model"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/videos/test/analysis", json={"core_seconds": 9999}
            ).status_code
            == 422
        )
        (root / video["path"]).write_bytes(b"changed source")
        assert client.post("/api/videos/test/analysis", json={}).status_code == 409
        assert store.jobs() == [] and calls == []


def test_doubles_processing_records_unavailable_labels_instead_of_fake_recognition(
    workspace,
):
    root, store, video, _, _ = workspace
    # A separate registered video avoids changing the original source's mode.
    other = video | {"id": "doubles", "mode": "doubles"}
    store.register(other)
    source_times = json.loads(
        (store.data / "test/timestamps.json").read_text(encoding="utf-8")
    )
    from badminton.video import write_json

    write_json(store.data / "doubles/timestamps.json", source_times)
    with TestClient(create_app(root, store.data)) as client:
        response = client.post("/api/videos/doubles/analysis", json={})
        identifier = response.json()["id"]
        job = wait(store, identifier)
        assert job["status"] == "completed", job
        plan = client.get(f"/api/videos/doubles/analysis/{identifier}").json()
        assert not plan["fully_annotated"]
        run_id = plan["parts"][0]["stages"]["recognition"]["run_id"]
        run = client.get(f"/api/videos/doubles/runs/{run_id}").json()
        assert run["status"] == "unsupported" and run["candidates"] == []


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize("mutation", ["source", "timestamps", "context"])
def test_api_cached_resume_exposes_changed_inputs_as_incomplete(
    workspace, monkeypatch, mode, mutation
):
    ctx = mode_workspace(workspace, mode)
    root, store, video, _, calls = ctx
    with TestClient(create_app(root, store.data)) as client:
        initial = client.post("/api/videos/test/analysis", json={})
        assert initial.status_code == 202
        assert wait(store, initial.json()["id"])["status"] == "completed"
        originals = {
            p: p.read_bytes()
            for p in (store.data / video["id"] / "runs").glob("*.json")
        }
        calls.clear()
        original = pipeline.process_match
        changed = []
        monkeypatch.setattr(pipeline, "time", SimpleNamespace(monotonic=lambda: 100))

        def process(v, root, store, snapshot, job_id, progress, settings, **kwargs):
            def report(value):
                if not changed:
                    mutate_input(ctx, mutation)
                    changed.append(job_id)
                progress(value)

            return original(
                v, root, store, snapshot, job_id, report, settings, **kwargs
            )

        monkeypatch.setattr(pipeline, "process_match", process)
        response = client.post("/api/videos/test/analysis", json={})
        assert response.status_code == 202
        job_id = response.json()["id"]
        job = wait(store, job_id)
        state = "interrupted" if mutation == "context" else "failed"
        assert job["status"] == state and "summary" not in job
        loaded = client.get(f"/api/videos/test/analysis/{job_id}")
        assert loaded.status_code == 200
        plan = loaded.json()
        assert plan["state"] == state and not plan["processing_complete"]
        assert changed == [job_id] and calls == []
        assert all(p.read_bytes() == raw for p, raw in originals.items())
