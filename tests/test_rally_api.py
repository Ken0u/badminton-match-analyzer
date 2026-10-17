import json
import time

import pytest
from badminton.api import create_app
from badminton.video import write_json
from fastapi.testclient import TestClient
from rally_fixture import catalog


@pytest.fixture
def workspace(tmp_path):
    data = tmp_path / "processed"
    store, video = catalog(tmp_path, data)
    return tmp_path, data, store, video


def wait(store, job_id):
    for _ in range(200):
        job = next(j for j in store.jobs() if j["id"] == job_id)
        if job["status"] not in ("queued", "running"):
            assert job["status"] == "completed", job
            return job
        time.sleep(0.01)
    pytest.fail("Rally worker did not finish")


def test_api_rally_run_keeps_labels_and_raw_evidence_then_flags_context_edits(
    workspace,
):
    root, data, store, video = workspace
    before = store.annotations(video["id"]).model_dump()
    path = data / video["id"] / "runs"
    raw_inputs = {p.name: p.read_bytes() for p in path.glob("*.json")}
    with TestClient(create_app(root, data)) as client:
        base = f"/api/videos/{video['id']}"
        response = client.post(
            base + "/rallies",
            json={"player_run_id": "qa-players", "shuttle_run_id": "qa-shuttle"},
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        job = wait(store, job_id)
        assert job["summary"]["candidate_count"] == 2
        run = client.get(base + f"/runs/{job_id}").json()
        assert run["requires_proposal_rerun"] is False
        assert run["calibration_provenance"] == "recorded_snapshot"
        assert all(c["player_id"] is None for c in run["candidates"])
        assert store.annotations(video["id"]).model_dump() == before
        raw_result = (path / f"{job_id}.json").read_bytes()
        changed = before | {
            "scene_ranges": [
                {
                    "id": "nonplay",
                    "scene": "non_play",
                    "start_frame": 1,
                    "end_frame": 15,
                }
            ]
        }
        assert client.put(base + "/annotations", json=changed).status_code == 200
        assert (
            client.get(base + f"/runs/{job_id}").json()["requires_proposal_rerun"]
            is True
        )
        assert (path / f"{job_id}.json").read_bytes() == raw_result
        assert {name: (path / name).read_bytes() for name in raw_inputs} == raw_inputs


@pytest.mark.parametrize(
    "failure",
    [
        "wrong_stage",
        "foreign_video",
        "hash",
        "stride",
        "stale_court",
        "source_changed",
        "wrong_pts",
    ],
)
def test_invalid_rally_request_is_rejected_before_queuing(workspace, failure):
    root, data, store, video = workspace
    path = data / video["id"] / "runs" / "qa-players.json"
    run = json.loads(path.read_text())
    if failure == "wrong_stage":
        run["stage"] = "shuttle"
    elif failure == "foreign_video":
        run["video_id"] = "foreign"
    elif failure == "hash":
        run["video_sha256"] = "b" * 64
    elif failure == "stride":
        run["stride"] = 2
    elif failure == "stale_court":
        run["calibration_signature"] = []
    elif failure == "source_changed":
        (root / video["path"]).write_bytes(b"changed media")
    elif failure == "wrong_pts":
        for row in run["frames"]:
            row["time_s"] += 0.01
        shuttle_path = path.with_name("qa-shuttle.json")
        shuttle = json.loads(shuttle_path.read_text())
        for row in shuttle["frames"]:
            row["time_s"] += 0.01
        write_json(shuttle_path, shuttle)
    write_json(path, run)
    with TestClient(create_app(root, data)) as client:
        response = client.post(
            f"/api/videos/{video['id']}/rallies",
            json={"player_run_id": "qa-players", "shuttle_run_id": "qa-shuttle"},
        )
        assert response.status_code == (409 if failure == "source_changed" else 422), (
            response.text
        )
        assert len(store.jobs()) == 2
