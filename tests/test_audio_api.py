import hashlib
import time

import pytest
from badminton.api import create_app
from badminton.storage import Store
from badminton.video import write_json
from fastapi.testclient import TestClient


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.delenv("BADMINTON_USERNAME", raising=False)
    monkeypatch.delenv("BADMINTON_PASSWORD", raising=False)
    source = tmp_path / "fixture.mp4"
    source.write_bytes(b"fixture; decoder is isolated in audio tests")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    video = {
        "id": checksum[:16],
        "sha256": checksum,
        "path": source.name,
        "name": "fixture",
        "mode": "singles",
        "width": 640,
        "height": 360,
        "frame_count": 25,
        "duration_s": 1,
        "source_start_s": 0,
    }
    data = tmp_path / "data"
    store = Store(data)
    store.register(video)
    write_json(data / video["id"] / "timestamps.json", [i * 0.04 for i in range(25)])
    for stage in ("shuttle", "players"):
        write_json(
            data / video["id"] / "runs" / f"{stage}.json",
            {
                "stage": stage,
                "video_id": video["id"],
                "frames": [],
                "start_frame": 0,
                "end_frame": 25,
            },
        )
        store.put_job(
            {"id": stage, "kind": stage, "video_id": video["id"], "status": "completed"}
        )
    return tmp_path, data, store, video


def wait(store, identifier):
    for _ in range(200):
        job = next(job for job in store.jobs() if job["id"] == identifier)
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.01)
    pytest.fail("Contact job did not finish")


@pytest.mark.parametrize(
    "enabled,status", [(False, "available"), (True, "missing"), (True, "available")]
)
def test_audio_is_opt_in_and_never_changes_annotations(
    catalog, monkeypatch, enabled, status
):
    import badminton.audio as audio
    import badminton.contacts as contacts

    root, data, store, video = catalog
    visual = [
        {
            "id": "contact-10",
            "frame": 10,
            "time_s": 0.4,
            "track_id": None,
            "player_id": None,
        }
    ]
    monkeypatch.setattr(contacts, "propose_contacts", lambda *_: visual)
    calls = []

    def decode(v, r, start, end):
        calls.append((v["sha256"], r, start, end))
        return {"status": status, "peaks": []}

    monkeypatch.setattr(audio, "extract_audio_cues", decode)
    base = f"/api/videos/{video['id']}"
    with TestClient(create_app(root, data)) as client:
        request = {"shuttle_run_id": "shuttle", "player_run_id": "players"}
        if enabled:
            request["include_audio"] = True
        response = client.post(base + "/contacts", json=request)
        assert response.status_code == 202
        job = wait(store, response.json()["id"])
        assert job["status"] == "completed", job
        result = client.get(base + "/runs/" + job["id"]).json()
        assert result["candidates"] == visual
        assert "audio" not in job["summary"]
        if enabled:
            assert calls == [(video["sha256"], root, 0, 1)]
            assert result["audio"]["status"] == status
            assert job["summary"]["audio_status"] == status
        else:
            assert not calls and "audio" not in result
    assert store.annotations(video["id"]).revision == 0


def test_audio_request_requires_pose_and_rejects_unknown_flags(catalog):
    root, data, store, video = catalog
    with TestClient(create_app(root, data)) as client:
        base = f"/api/videos/{video['id']}/contacts"
        assert (
            client.post(
                base, json={"shuttle_run_id": "shuttle", "include_audio": True}
            ).status_code
            == 422
        )
        assert (
            client.post(
                base, json={"shuttle_run_id": "shuttle", "audio": True}
            ).status_code
            == 422
        )
    assert len(store.jobs()) == 2
