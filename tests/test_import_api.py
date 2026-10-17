"""Exercise source imports and access controls without external network calls."""

import hashlib
import io
import json
import time

import av
import numpy as np
import pytest
from badminton.api import create_app
from badminton.media_import import MediaImportError, save_upload
from badminton.storage import Store
from fastapi.testclient import TestClient


@pytest.fixture
def import_context(tmp_path, monkeypatch):
    monkeypatch.delenv("BADMINTON_USERNAME", raising=False)
    monkeypatch.delenv("BADMINTON_PASSWORD", raising=False)
    path = tmp_path / "tiny.mp4"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=25)
        stream.width = stream.height = 32
        stream.pix_fmt = "yuv420p"
        for index in range(3):
            frame = av.VideoFrame.from_ndarray(
                np.full((32, 32, 3), index * 50, np.uint8), format="rgb24"
            )
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    content = path.read_bytes()
    path.unlink()
    return tmp_path, tmp_path / "processed", content


def wait_job(store, job_id):
    for _ in range(200):
        job = next(job for job in store.jobs() if job["id"] == job_id)
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(0.01)
    raise AssertionError("Import job did not finish")


def upload(client, content, filename="match.mp4", mode="singles"):
    return client.post(
        "/api/upload",
        files={"file": (filename, content, "video/mp4")},
        data={"mode": mode},
    )


def media_files(root):
    folder = root / ".media"
    return sorted(folder.iterdir()) if folder.exists() else []


@pytest.mark.parametrize(
    "origin", ["https://unrelated.example", "null", "https://testserver.evil"]
)
def test_cross_site_changes_are_rejected_before_processing(import_context, origin):
    root, data, _content = import_context
    with TestClient(create_app(root, data)) as client:
        response = client.post(
            "/api/import/youtube",
            json={"url": "https://youtu.be/abcdefghijk"},
            headers={"Origin": origin},
        )
        assert response.status_code == 403
        assert client.get("/api/jobs").json() == []


def test_same_origin_invalid_source_reaches_validation(import_context):
    root, data, _content = import_context
    with TestClient(create_app(root, data)) as client:
        response = client.post(
            "/api/import/youtube",
            json={"url": "not-youtube"},
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 422


def test_upload_registers_content_id_metadata_source_times_and_decodable_media(
    import_context,
):
    root, data, content = import_context
    expected_id = hashlib.sha256(content).hexdigest()[:16]
    with TestClient(create_app(root, data)) as client:
        response = upload(client, content, "../../games\\Sample match.mp4")
        assert response.status_code == 202, response.text
        job = wait_job(Store(data), response.json()["id"])
        assert job["status"] == "completed", job
        videos = client.get("/api/videos").json()
        assert len(videos) == 1
        video = videos[0]
        assert video["id"] == expected_id
        assert video["name"] == "Sample match.mp4"
        assert video["source_type"] == "upload"
        assert video["path"].startswith(".media/")
        assert video["frame_count"] == 3 and video["width"] == 32
        assert client.get(
            f"/api/videos/{expected_id}/timestamps"
        ).json() == pytest.approx([0, 0.04, 0.08])
        assert client.get(f"/api/videos/{expected_id}/media").content == content
        image = client.get(f"/api/videos/{expected_id}/frame?index=1")
        assert (
            image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
        )
    assert len(media_files(root)) == 1


def test_repeated_upload_preserves_review_revision_and_one_original_source(
    import_context,
):
    root, data, content = import_context
    expected_id = hashlib.sha256(content).hexdigest()[:16]
    store = Store(data)
    with TestClient(create_app(root, data)) as client:
        first = upload(client, content)
        assert wait_job(store, first.json()["id"])["status"] == "completed"
        url = f"/api/videos/{expected_id}/annotations"
        doc = client.get(url).json()
        doc["events"] = [
            {
                "id": "manual",
                "rally_id": "R1",
                "kind": "shot",
                "frame": 1,
                "family": "clear",
                "side": "forehand",
                "notes": "Reviewed before duplicate upload",
            }
        ]
        saved = client.put(url, json=doc)
        assert saved.status_code == 200, saved.text
        original_source = media_files(root)
        second = upload(client, content, "another filename.mp4")
        assert second.status_code == 202
        assert wait_job(store, second.json()["id"])["status"] == "completed"
        assert client.get(url).json() == saved.json()
        assert len(client.get("/api/videos").json()) == 1
        assert media_files(root) == original_source
        wrong_mode = upload(client, content, mode="doubles")
        assert wrong_mode.status_code == 202
        failed = wait_job(store, wrong_mode.json()["id"])
        assert (
            failed["status"] == "failed"
            and "different match format" in failed["message"]
        )
        assert client.get(url).json() == saved.json()
    assert media_files(root) == original_source


def test_local_path_reimport_preserves_uploaded_name_and_source_provenance(import_context):
    root, data, content = import_context
    store = Store(data)
    with TestClient(create_app(root, data)) as client:
        response = upload(client, content, "original match.mp4")
        assert wait_job(store, response.json()["id"])["status"] == "completed"
        original = client.get("/api/videos").json()[0]
        assert original["name"] == "original match.mp4"
        response = client.post(
            "/api/import", json={"path": original["path"], "mode": "singles"}
        )
        assert response.status_code == 202, response.text
        assert wait_job(store, response.json()["id"])["status"] == "completed"
        reimported = client.get(f"/api/videos/{original['id']}").json()
        assert reimported == original
        metadata = json.loads((data / original["id"] / "metadata.json").read_text())
        assert metadata == reimported
        assert len(media_files(root)) == 1


@pytest.mark.parametrize(
    "filename,content",
    [("match.txt", b"text"), ("match.mp4", b"not a video"), ("match.mp4", b"")],
)
def test_invalid_upload_is_rejected_without_jobs_or_leftover_files(
    import_context, filename, content
):
    root, data, _ = import_context
    with TestClient(create_app(root, data)) as client:
        response = upload(client, content, filename)
        assert response.status_code == 422, response.text
        assert client.get("/api/videos").json() == []
        assert client.get("/api/jobs").json() == []
    assert media_files(root) == []


def test_upload_size_limit_returns_payload_too_large_and_cleans_source(import_context):
    root, data, content = import_context
    with TestClient(create_app(root, data, max_media_bytes=len(content) - 1)) as client:
        response = upload(client, content)
        assert response.status_code == 413, response.text
        assert client.get("/api/jobs").json() == []
    assert media_files(root) == []


def test_background_import_failure_cleans_uploaded_source(import_context, monkeypatch):
    import badminton.api as api

    root, data, content = import_context

    def fail_inspection(*args, **kwargs):
        raise ValueError("Timestamp inspection failed")

    monkeypatch.setattr(api, "inspect_video", fail_inspection)
    with TestClient(create_app(root, data)) as client:
        response = upload(client, content)
        assert response.status_code == 202
        job = wait_job(Store(data), response.json()["id"])
        assert job["status"] == "failed"
        assert client.get("/api/videos").json() == []
    assert media_files(root) == []


def test_upload_when_worker_busy_returns_conflict_and_does_not_orphan_file(
    import_context,
):
    root, data, content = import_context
    store = Store(data)
    store.claim_job(
        {"id": "live-job", "kind": "players", "video_id": "sample", "status": "running"}
    )
    with TestClient(create_app(root, data)) as client:
        response = upload(client, content)
        assert response.status_code == 409, response.text
        assert len(client.get("/api/jobs").json()) == 1
    assert media_files(root) == []


def test_youtube_metadata_keeps_source_id_separate_from_content_id(
    import_context, monkeypatch
):
    import badminton.media_import as media_import

    root, data, content = import_context
    expected_id = hashlib.sha256(content).hexdigest()[:16]
    calls = []

    def download(url, media_root, max_bytes, progress):
        calls.append(url)
        progress(0.5)
        path = save_upload(io.BytesIO(content), "download.mp4", media_root, max_bytes)
        progress(1)
        return path, {
            "source_type": "youtube",
            "id": "abcdefghijk",
            "url": url,
            "title": "Public badminton video",
            "channel": "Example channel",
        }

    monkeypatch.setattr(media_import, "download_youtube", download)
    with TestClient(create_app(root, data)) as client:
        response = client.post(
            "/api/import/youtube",
            json={"url": "https://youtu.be/abcdefghijk?si=discard", "mode": "singles"},
        )
        assert response.status_code == 202, response.text
        job = wait_job(Store(data), response.json()["id"])
        assert job["status"] == "completed", job
        video = client.get("/api/videos").json()[0]
        assert video["id"] == expected_id
        assert video["sha256"] == hashlib.sha256(content).hexdigest()
        assert video["source_type"] == "youtube"
        assert video["name"] == "Public badminton video"
        assert video["source"]["id"] == "abcdefghijk"
        assert video["source"]["channel"] == "Example channel"
        assert client.get(f"/api/videos/{expected_id}/annotations").status_code == 200
        assert client.get(
            f"/api/videos/{expected_id}/timestamps"
        ).json() == pytest.approx([0, 0.04, 0.08])
        assert client.get(f"/api/videos/{expected_id}/media").content == content
    assert calls == ["https://www.youtube.com/watch?v=abcdefghijk"]
    assert len(media_files(root)) == 1


def test_invalid_youtube_url_creates_no_job_and_failed_download_creates_no_video(
    import_context, monkeypatch
):
    import badminton.media_import as media_import

    root, data, _ = import_context
    calls = []

    def fail_download(*args, **kwargs):
        calls.append(True)
        raise MediaImportError("Public video is unavailable")

    monkeypatch.setattr(media_import, "download_youtube", fail_download)
    with TestClient(create_app(root, data)) as client:
        invalid = client.post(
            "/api/import/youtube", json={"url": "https://127.0.0.1/private"}
        )
        assert invalid.status_code == 422
        assert client.get("/api/jobs").json() == [] and calls == []
        response = client.post(
            "/api/import/youtube", json={"url": "https://youtu.be/abcdefghijk"}
        )
        assert response.status_code == 202
        assert wait_job(Store(data), response.json()["id"])["status"] == "failed"
        assert client.get("/api/videos").json() == []
    assert media_files(root) == []


def test_basic_auth_protects_static_and_api_while_health_remains_public(import_context):
    root, data, _ = import_context
    with TestClient(
        create_app(root, data, username="reviewer", password="private-pass")
    ) as client:
        assert client.get("/api/health").status_code == 200
        for path in (
            "/",
            "/app.js",
            "/style.css",
            "/api/videos",
            "/api/jobs",
            "/api/no-such-route",
        ):
            response = client.get(path)
            assert response.status_code == 401, path
            assert response.headers["www-authenticate"].startswith("Basic ")
        assert client.get("/api/videos", auth=("reviewer", "wrong")).status_code == 401
        assert client.get("/api/videos", auth=("reviewer", "private-pass")).json() == []
        assert client.get("/", auth=("reviewer", "private-pass")).status_code == 200


def test_streamed_request_cannot_bypass_body_limit_without_content_length(
    import_context,
):
    root, data, _ = import_context
    boundary = "bounded-request"
    start = f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="large.mp4"\r\nContent-Type: video/mp4\r\n\r\n'.encode()
    chunks = iter([start, b"x" * (1024**2 + 100), f"\r\n--{boundary}--\r\n".encode()])
    with TestClient(
        create_app(root, data, max_media_bytes=10), raise_server_exceptions=False
    ) as client:
        response = client.post(
            "/api/upload",
            content=chunks,
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )
        assert response.status_code == 413, response.text
        assert client.get("/api/videos").json() == []
        assert client.get("/api/jobs").json() == []
    assert media_files(root) == []


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_media_limit_is_rejected_when_app_is_created(import_context, limit):
    root, data, _ = import_context
    with pytest.raises(ValueError):
        create_app(root, data, max_media_bytes=limit)


@pytest.mark.parametrize(
    "username,password", [("reviewer", None), (None, "secret"), ("", "secret")]
)
def test_incomplete_auth_configuration_is_rejected_at_app_creation(
    import_context, username, password
):
    root, data, _ = import_context
    with pytest.raises(ValueError):
        create_app(root, data, username=username, password=password)
