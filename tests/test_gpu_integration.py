"""Opt-in check of the real API/model path, including a clip shorter than seq_len."""

import json
import os
import time

import pytest
from badminton.api import create_app
from badminton.config import DATA, MODEL_MANIFEST, ROOT
from badminton.storage import Store
from badminton.video import timestamps_for, write_json
from fastapi.testclient import TestClient


@pytest.mark.skipif(
    os.environ.get("BADMINTON_GPU_TESTS") != "1",
    reason="Set BADMINTON_GPU_TESTS=1 for the real local checkpoint test",
)
def test_real_shuttle_api_short_clip_preserves_source_frames(tmp_path):
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("CUDA device is unavailable")
    source = Store(DATA)
    video = source.video("970dbd8adfe548d8")
    data = tmp_path / "gpu-review"
    store = Store(data)
    store.register(video)
    write_json(
        data / video["id"] / "timestamps.json", timestamps_for(DATA, video["id"])
    )
    with TestClient(create_app(ROOT, data)) as client:
        response = client.post(
            f"/api/videos/{video['id']}/track",
            json={"start_frame": 2000, "end_frame": 2005, "stage": "shuttle"},
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            job = next(j for j in store.jobs() if j["id"] == job_id)
            if job["status"] not in ("queued", "running"):
                break
            time.sleep(0.05)
        assert job["status"] == "completed", job
        run = client.get(f"/api/videos/{video['id']}/runs/{job_id}").json()
        assert [r["frame"] for r in run["frames"]] == list(range(2000, 2005))
        assert [r["time_s"] for r in run["frames"]] == pytest.approx(
            [80, 80.04, 80.08, 80.12, 80.16]
        )
        assert run["repaired_frames"] == 0 and run["device"] == "cuda:0"
        for row in run["frames"]:
            point = row["shuttle"]
            assert point["repaired"] is False
            assert (point["x"] is None) == (not point["visible"])
        assert store.annotations(video["id"]).events == []


@pytest.mark.skipif(
    os.environ.get("BADMINTON_GPU_TESTS") != "1",
    reason="Opt-in pinned player checkpoint check",
)
@pytest.mark.parametrize("variant", ["small", "nano"])
def test_real_player_api_records_selected_model_source_and_court_snapshot(
    tmp_path, variant
):
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("CUDA device is unavailable")
    source = Store(DATA)
    video = source.video("970dbd8adfe548d8")
    data = tmp_path / "gpu-players"
    store = Store(data)
    store.register(video)
    doc = store.annotations(video["id"])
    doc.calibrations = source.annotations(video["id"]).calibrations
    write_json(
        data / video["id"] / "timestamps.json", timestamps_for(DATA, video["id"])
    )
    store.save_annotations(video["id"], doc)
    with TestClient(create_app(ROOT, data)) as client:
        body = {"start_frame": 2000, "end_frame": 2012, "stage": "players"}
        if variant == "nano":
            body["player_model"] = variant
        response = client.post(f"/api/videos/{video['id']}/track", json=body)
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            job = next(j for j in store.jobs() if j["id"] == job_id)
            if job["status"] not in ("queued", "running"):
                break
            time.sleep(0.05)
        assert job["status"] == "completed", job
        run = client.get(f"/api/videos/{video['id']}/runs/{job_id}").json()
        entry = json.loads(MODEL_MANIFEST.read_text())[
            "player_pose_small" if variant == "small" else "player_pose"
        ]
        assert run["model_variant"] == variant
        assert run["model"] == entry["name"].removesuffix(".pt")
        assert run["checkpoint_sha256"] == entry["sha256"]
        assert run["model_source"] == entry["source"]
        assert run["video_sha256"] == video["sha256"]
        assert run["calibration_signature"] and run["calibrated_frames"] == 12
        assert [r["frame"] for r in run["frames"]] == list(range(2000, 2012))
        assert all(r["time_s"] == pytest.approx(r["frame"] / 25) for r in run["frames"])
        assert store.annotations(video["id"]).events == []
