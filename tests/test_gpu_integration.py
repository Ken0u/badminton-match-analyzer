"""Opt-in check of the real API/model path, including a clip shorter than seq_len."""

import os
import time

import pytest
from badminton.api import create_app
from badminton.config import DATA, ROOT
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
