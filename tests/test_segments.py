import json
import time
from fractions import Fraction

import av
import numpy as np
import pytest
from badminton.api import create_app
from badminton.ingest import inspect_video
from badminton.segments import camera_ranges, scan_boundaries, scan_video
from badminton.storage import Store
from badminton.video import SourceChangedError, timestamps_for
from fastapi.testclient import TestClient


def make_source(tmp_path, *, gap=False, fade=False, rate=25, cuts=(20, 40)):
    path = tmp_path / "cameras.mkv"
    pts = 0
    with av.open(str(path), "w") as container:
        stream = container.add_stream("ffv1", rate=rate)
        stream.width, stream.height, stream.pix_fmt = 96, 64, "bgr0"
        stream.time_base = Fraction(1, 1000)
        stream.codec_context.time_base = Fraction(1, 1000)
        for index in range(65):
            color = (
                [0, 0, 0]
                if gap
                else [index * 3] * 3
                if fade
                else [240, 0, 0]
                if index < cuts[0]
                else [0, 240, 0]
                if index < cuts[1]
                else [0, 0, 240]
            )
            frame = av.VideoFrame.from_ndarray(
                np.full((64, 96, 3), color, np.uint8), "rgb24"
            )
            frame.pts, frame.time_base = pts, Fraction(1, 1000)
            for packet in stream.encode(frame):
                container.mux(packet)
            pts += 200 if rate == 5 else 40 if index % 2 else 60
            if gap and index == 29:
                pts += 600
        for packet in stream.encode():
            container.mux(packet)
    data = tmp_path / "data"
    store = Store(data)
    video = inspect_video(path, "singles", store, tmp_path)
    return video, data, store


def test_full_vfr_scan_preserves_source_frames_times_and_annotations(tmp_path):
    video, data, store = make_source(tmp_path)
    times = timestamps_for(data, video["id"])
    progress = []
    output = data / "segments.json"
    summary = scan_video(video, tmp_path, data, progress.append, output)
    result = json.loads(output.read_text())
    assert result["cut_frames"] == [20, 40]
    assert [cut["time_s"] for cut in result["boundaries"]] == [times[20], times[40]]
    assert video["variable_frame_rate"] is True
    assert result["video_sha256"] == video["sha256"]
    assert result["camera_ranges"] == camera_ranges(0, 65, [20, 40])
    assert all(not cut["reviewed"] for cut in result["boundaries"])
    assert all(segment["scene"] == "unknown" for segment in result["camera_ranges"])
    assert "boundaries" not in summary
    assert progress == sorted(progress) and progress[-1] == 1
    assert store.annotations(video["id"]).revision == 0
    # Look-ahead handles cuts near the end of a requested processing window.
    clip = scan_boundaries(video, tmp_path, data, 16, 21, lambda _: None)
    assert clip["cut_frames"] == [20]
    assert clip["camera_ranges"] == camera_ranges(16, 21, [20])


@pytest.mark.parametrize("early", [5, 10, 14])
def test_early_source_edit_is_not_hidden_by_initial_minimum_scene_length(
    tmp_path, early
):
    video, data, _store = make_source(tmp_path, cuts=(early, 40))
    times = timestamps_for(data, video["id"])
    result = scan_boundaries(video, tmp_path, data, 0, 65, lambda _: None)
    assert result["cut_frames"] == [early, 40]
    assert result["boundaries"][0]["time_s"] == times[early]
    clipped = scan_boundaries(
        video, tmp_path, data, early - 1, early + 1, lambda _: None
    )
    assert clipped["cut_frames"] == [early]


def test_timestamp_gap_splits_context_even_without_visual_change(tmp_path):
    video, data, _store = make_source(tmp_path, gap=True)
    result = scan_boundaries(video, tmp_path, data, 0, 65, lambda _: None)
    assert result["cut_frames"] == [30]
    assert result["boundaries"][0]["reason"] == "timestamp_discontinuity"


def test_low_rate_source_does_not_create_a_timestamp_boundary_on_every_frame(tmp_path):
    video, data, _store = make_source(tmp_path, rate=5)
    result = scan_boundaries(video, tmp_path, data, 0, 65, lambda _: None)
    assert video["fps"] == 5
    assert result["timestamp_gap_threshold_s"] == 0.5
    assert result["cut_frames"] == [20, 40]
    assert all(item["reason"] == "visual_cut" for item in result["boundaries"])


def test_gradual_lighting_change_does_not_become_an_abrupt_camera_edit(tmp_path):
    video, data, _store = make_source(tmp_path, fade=True)
    assert (
        scan_boundaries(video, tmp_path, data, 0, 65, lambda _: None)["cut_frames"]
        == []
    )
    with pytest.raises(ValueError, match="inside"):
        scan_boundaries(video, tmp_path, data, 0, 100, lambda _: None)
    (tmp_path / video["path"]).write_bytes(b"source changed")
    with pytest.raises(SourceChangedError):
        scan_boundaries(video, tmp_path, data, 0, 65, lambda _: None)


def test_range_edges_are_half_open_and_duplicates_do_not_create_empty_views():
    assert camera_ranges(10, 30, [0, 10, 20, 20, 30, 40]) == [
        {"start_frame": 10, "end_frame": 20, "scene": "unknown"},
        {"start_frame": 20, "end_frame": 30, "scene": "unknown"},
    ]
    with pytest.raises(ValueError):
        camera_ranges(2, 2, [])


def test_incomplete_decode_cannot_be_reported_as_a_successful_no_cut_scan(
    tmp_path, monkeypatch
):
    from badminton import segments

    video, data, _store = make_source(tmp_path)
    original = segments.iter_frames

    def truncated(*args):
        for index, item in enumerate(original(*args)):
            if index == 5:
                return
            yield item

    monkeypatch.setattr(segments, "iter_frames", truncated)
    with pytest.raises(SourceChangedError, match="every requested"):
        scan_boundaries(video, tmp_path, data, 0, 65, lambda _: None)


def test_scan_api_uses_job_admission_and_preserves_reviewed_revisions(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("BADMINTON_USERNAME", raising=False)
    monkeypatch.delenv("BADMINTON_PASSWORD", raising=False)
    video, data, store = make_source(tmp_path)
    initial = store.annotations(video["id"]).model_dump()
    base = f"/api/videos/{video['id']}"
    with TestClient(create_app(tmp_path, data)) as client:
        response = client.post(base + "/segments")
        assert response.status_code == 202
        job_id = response.json()["id"]
        for _ in range(200):
            job = next(job for job in store.jobs() if job["id"] == job_id)
            if job["status"] not in ("running", "queued"):
                break
            time.sleep(0.01)
        assert job["status"] == "completed", job
        result = client.get(base + "/runs/" + job_id)
        assert result.status_code == 200
        assert result.json()["cut_frames"] == [20, 40]
        assert result.json()["video_sha256"] == video["sha256"]
        # Artifact lineage checks apply to the new stage too.
        path = data / video["id"] / "runs" / f"{job_id}.json"
        broken = result.json() | {"stage": "players"}
        path.write_text(json.dumps(broken))
        assert client.get(base + "/runs/" + job_id).status_code == 422
        store.claim_job(
            {
                "id": "other-job",
                "kind": "players",
                "video_id": video["id"],
                "status": "running",
            }
        )
        assert client.post(base + "/segments").status_code == 409
        store.put_job(
            {
                "id": "other-job",
                "kind": "players",
                "video_id": video["id"],
                "status": "completed",
            }
        )
        (tmp_path / video["path"]).write_bytes(b"changed")
        assert client.post(base + "/segments").status_code == 409
    assert store.annotations(video["id"]).model_dump() == initial
