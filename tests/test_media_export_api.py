"""Real HTTP media exports preserve native evidence and shared admission."""

import hashlib
import io
import json
import shutil
import threading
import time

import av
import numpy as np
import pytest
from badminton.api import create_app
from badminton.jobs import JobCancelled
from badminton.schemas import Annotations
from fastapi.testclient import TestClient
from test_rally_overlay import assert_native_media, context

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
MODES = ("plain-rallies", "annotated-rallies", "annotated-full")


def wait(store, job_id):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = store.job(job_id)
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.01)
    pytest.fail(f"Export job {job_id} did not reach a terminal state")


def endpoint(video, job_id=None):
    path = f"/api/videos/{video['id']}/media-exports"
    return path if job_id is None else f"{path}/{job_id}"


def submit(client, store, video, revision, mode="plain-rallies"):
    response = client.post(endpoint(video), json={"revision": revision, "mode": mode})
    assert response.status_code == 202, response.text
    job = wait(store, response.json()["id"])
    assert job["status"] == "completed", job
    return job


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("rotation", [None, 90])
def test_http_downloads_preserve_native_media_and_complete_snapshot(
    tmp_path, mode, rotation
):
    store, video, source, saved, plan = context(
        tmp_path,
        "doubles" if rotation else "singles",
        audio=rotation is None,
        rotation=rotation,
    )
    exports = tmp_path / "downloads"
    immutable = {p: p.read_bytes() for p in store.data.rglob("*.json")}
    source_bytes = source.read_bytes()
    with TestClient(create_app(tmp_path, store.data, export_root=exports)) as client:
        job = submit(client, store, video, saved.revision, mode)
        status = client.get(endpoint(video, job["id"]))
        assert status.status_code == 200, status.text
        result = status.json()
        assert result["available"] and result["job"]["id"] == job["id"]
        manifest_response = client.get(
            endpoint(video, job["id"]) + "/files/manifest.json"
        )
        assert manifest_response.status_code == 200, manifest_response.text
        manifest = manifest_response.json()
        assert manifest["source"] == plan["source"]
        assert manifest["annotations"] == plan["annotations"]
        assert manifest["annotation_revision"] == saved.revision
        assert manifest["counts"] == plan["counts"]
        files = result["files"]
        assert {f["filename"] for f in files} == {
            "manifest.json",
            "full-000001.mp4" if mode == "annotated-full" else "rally-000001.mp4",
        }
        for descriptor in files:
            response = client.get(
                endpoint(video, job["id"]) + "/files/" + descriptor["filename"]
            )
            assert response.status_code == 200, response.text
            assert hashlib.sha256(response.content).hexdigest() == descriptor["sha256"]
            assert len(response.content) == descriptor["size_bytes"]
            assert response.headers["content-type"].startswith(descriptor["media_type"])
            assert (
                response.headers["content-disposition"]
                == f'attachment; filename="{descriptor["filename"]}"'
            )
            if descriptor["filename"].endswith(".mp4"):
                downloaded = tmp_path / "downloaded.mp4"
                downloaded.write_bytes(response.content)
                times = json.loads(
                    (store.data / video["id"] / "timestamps.json").read_bytes()
                )
                start, end = (0, 8) if mode == "annotated-full" else (1, 7)
                duration = (
                    times[end] if end < len(times) else video["duration_s"]
                ) - times[start]
                assert_native_media(downloaded, video, times, start, end, duration)
                with av.open(io.BytesIO(response.content)) as container:
                    assert bool(container.streams.audio) == (rotation is None)
                    if rotation is None:
                        onset = []
                        for frame in container.decode(audio=0):
                            audible = np.flatnonzero(
                                np.abs(frame.to_ndarray()).max(axis=0) > 0.05
                            )
                            if len(audible):
                                onset.append(
                                    float(frame.pts * frame.time_base)
                                    + audible[0] / frame.sample_rate
                                )
                        assert min(onset) == pytest.approx(
                            0.08 - times[start], abs=0.0011
                        )
        if mode != "plain-rallies":
            assert manifest["event_counts"]["total"] == 5
            assert manifest["event_counts"]["excluded"] == 1
    assert store.annotations(video["id"]) == saved
    assert all(p.read_bytes() == b for p, b in immutable.items())
    assert source.read_bytes() == source_bytes


def test_shared_admission_prompt_response_and_revision_pinning(tmp_path, monkeypatch):
    from badminton.export_service import MediaExportService

    store, video, _, saved, _ = context(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = MediaExportService.render
    calls = []

    def blocked(self, *args):
        calls.append(args)
        entered.set()
        assert release.wait(10)
        return original(self, *args)

    monkeypatch.setattr(MediaExportService, "render", blocked)
    with TestClient(create_app(tmp_path, store.data)) as client:
        started = time.monotonic()
        response = client.post(
            endpoint(video), json={"revision": saved.revision, "mode": "plain-rallies"}
        )
        assert response.status_code == 202
        assert time.monotonic() - started < 2
        job_id = response.json()["id"]
        assert entered.wait(5)
        try:
            assert client.get(endpoint(video, job_id)).json()["available"] is False
            assert (
                client.get(endpoint(video, job_id) + "/files/manifest.json").status_code
                == 409
            )
            assert (
                client.post(
                    endpoint(video),
                    json={"revision": saved.revision, "mode": "annotated-full"},
                ).status_code
                == 409
            )
            assert (
                client.post(
                    f"/api/videos/{video['id']}/analysis/{job_id}/pause"
                ).status_code
                == 409
            )
            assert len(calls) == len(store.jobs()) == 1
            changed = saved.model_dump()
            changed["players"][0]["name"] = "Newer annotation"
            newer = store.save_annotations(
                video["id"], Annotations.model_validate(changed)
            )
        finally:
            release.set()
        assert wait(store, job_id)["status"] == "completed"
        manifest = client.get(endpoint(video, job_id) + "/files/manifest.json").json()
        assert manifest["annotation_revision"] == saved.revision
        assert manifest["annotations"] == saved.model_dump(mode="json")
        assert store.annotations(video["id"]) == newer


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"revision": True, "mode": "plain-rallies"},
        {"revision": "1", "mode": "plain-rallies"},
        {"revision": -1, "mode": "plain-rallies"},
        {"revision": 1, "mode": "full"},
        {"revision": 1, "mode": "plain-rallies", "output": "../../escape"},
    ],
)
def test_invalid_request_never_starts_job(tmp_path, body):
    store, video, _, _, _ = context(tmp_path)
    with TestClient(create_app(tmp_path, store.data)) as client:
        assert client.post(endpoint(video), json=body).status_code == 422
    assert store.jobs() == []


def test_missing_video_revision_and_authentication(tmp_path):
    store, video, _, saved, _ = context(tmp_path)
    with TestClient(
        create_app(tmp_path, store.data, username="reviewer", password="secret")
    ) as client:
        assert (
            client.post(
                endpoint(video),
                json={"revision": saved.revision, "mode": "plain-rallies"},
            ).status_code
            == 401
        )
        client.auth = ("reviewer", "secret")
        assert (
            client.post(
                endpoint({"id": "missing"}),
                json={"revision": 0, "mode": "plain-rallies"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                endpoint(video), json={"revision": 999, "mode": "plain-rallies"}
            ).status_code
            == 404
        )
        assert store.jobs() == []
        job = submit(client, store, video, saved.revision)
        assert client.get(endpoint({"id": "foreign"}, job["id"])).status_code == 404
        assert (
            client.get(
                endpoint({"id": "foreign"}, job["id"]) + "/files/manifest.json"
            ).status_code
            == 404
        )
        client.auth = None
        assert client.get(endpoint(video, job["id"])).status_code == 401
        assert (
            client.get(endpoint(video, job["id"]) + "/files/manifest.json").status_code
            == 401
        )


@pytest.mark.parametrize("failure", ["source", "encoder", "interrupted"])
def test_failed_or_interrupted_exports_are_durable_and_not_downloadable(
    tmp_path, monkeypatch, failure
):
    from badminton import rally_video
    from badminton.export_service import MediaExportService

    store, video, source, saved, _ = context(tmp_path)
    exports = tmp_path / "exports"
    if failure == "source":
        source.write_bytes(b"source changed")
    elif failure == "encoder":

        def fail(*args, **kwargs):
            raise RuntimeError("Generated encoder failure")

        monkeypatch.setattr(rally_video, "_run", fail)
    else:

        def cancel(*args, **kwargs):
            raise JobCancelled("Generated interrupted export")

        monkeypatch.setattr(MediaExportService, "render", cancel)
    with TestClient(create_app(tmp_path, store.data, export_root=exports)) as client:
        response = client.post(
            endpoint(video), json={"revision": saved.revision, "mode": "plain-rallies"}
        )
        assert response.status_code == 202
        job = wait(store, response.json()["id"])
        assert job["status"] == (
            "interrupted" if failure == "interrupted" else "failed"
        )
        assert not client.get(endpoint(video, job["id"])).json()["available"]
        assert (
            client.get(endpoint(video, job["id"]) + "/files/manifest.json").status_code
            == 409
        )
        assert not list(exports.rglob("manifest.json"))
        assert not list(exports.rglob("*.mp4"))
    assert store.annotations(video["id"]) == saved


def test_restart_fences_dead_export_and_preserves_incomplete_artifact(tmp_path):
    store, video, _, saved, _ = context(tmp_path)
    identifier = "b" * 32
    store.put_job(
        {
            "id": identifier,
            "video_id": video["id"],
            "kind": "media-export",
            "status": "running",
            "owner_pid": 999999999,
            "owner_started": 0,
            "details": {"revision": saved.revision, "mode": "plain-rallies"},
        }
    )
    incomplete = tmp_path / "exports" / identifier
    incomplete.mkdir(parents=True)
    (incomplete / "rally-000001.mp4").write_bytes(b"incomplete")
    with TestClient(create_app(tmp_path, store.data)) as client:
        status = client.get(endpoint(video, identifier)).json()
        assert status["job"]["status"] == "interrupted" and not status["available"]
        assert (
            client.get(
                endpoint(video, identifier) + "/files/rally-000001.mp4"
            ).status_code
            == 409
        )
        job = submit(client, store, video, saved.revision)
        assert job["id"] != identifier
    assert (incomplete / "rally-000001.mp4").read_bytes() == b"incomplete"


@pytest.mark.parametrize(
    "tamper",
    ["manifest", "media", "missing", "file-symlink", "folder-symlink", "root-symlink"],
)
def test_changed_completed_artifacts_cannot_be_served(tmp_path, tamper):
    store, video, _, saved, _ = context(tmp_path)
    exports = tmp_path / "exports"
    with TestClient(create_app(tmp_path, store.data, export_root=exports)) as client:
        job = submit(client, store, video, saved.revision)
        folder = exports / job["id"]
        media = folder / "rally-000001.mp4"
        if tamper in ("manifest", "media"):
            path = folder / "manifest.json" if tamper == "manifest" else media
            path.write_bytes(path.read_bytes() + b" ")
        elif tamper == "missing":
            media.unlink()
        elif tamper == "file-symlink":
            target = tmp_path / "elsewhere.mp4"
            media.rename(target)
            media.symlink_to(target)
        elif tamper == "folder-symlink":
            target = tmp_path / "elsewhere"
            folder.rename(target)
            folder.symlink_to(target, target_is_directory=True)
        else:
            target = tmp_path / "elsewhere"
            exports.rename(target)
            exports.symlink_to(target, target_is_directory=True)
        assert client.get(endpoint(video, job["id"])).status_code == 409
        assert (
            client.get(endpoint(video, job["id"]) + "/files/manifest.json").status_code
            == 409
        )
        assert (
            client.get(
                endpoint(video, job["id"]) + "/files/rally-000001.mp4"
            ).status_code
            == 409
        )


def test_arbitrary_files_nonexport_jobs_and_empty_rallies(tmp_path):
    store, video, _, saved, _ = context(tmp_path)
    changed = saved.model_dump()
    changed["events"][0]["status"] = "predicted"
    ineligible = store.save_annotations(
        video["id"], Annotations.model_validate(changed)
    )
    exports = tmp_path / "exports"
    with TestClient(create_app(tmp_path, store.data, export_root=exports)) as client:
        job = submit(client, store, video, ineligible.revision)
        manifest = client.get(
            endpoint(video, job["id"]) + "/files/manifest.json"
        ).json()
        assert manifest["counts"] == {"total": 1, "eligible": 0, "ineligible": 1}
        assert manifest["rallies"][0]["reasons"] == ["unreviewed_start"]
        assert len(client.get(endpoint(video, job["id"])).json()["files"]) == 1
        assert (
            client.get(endpoint(video, job["id"]) + "/files/secret.txt").status_code
            == 404
        )
        for filename in ("%2e%2e%2fsecret", "%2e%2e%5csecret", "%2e%2e", "plan.json"):
            assert client.get(
                endpoint(video, job["id"]) + "/files/" + filename
            ).status_code in (404, 409)
        extra = exports / job["id"] / "secret.txt"
        extra.write_text("private")
        assert client.get(endpoint(video, job["id"])).status_code == 409
        assert (
            client.get(endpoint(video, job["id"]) + "/files/secret.txt").status_code
            == 409
        )
        extra.unlink()
        other = job | {"id": "c" * 32, "kind": "analysis"}
        store.put_job(other)
        assert client.get(endpoint(video, other["id"])).status_code == 404
        assert (
            client.get(
                endpoint(video, other["id"]) + "/files/manifest.json"
            ).status_code
            == 404
        )
        full = submit(client, store, video, ineligible.revision, "annotated-full")
        manifest = client.get(
            endpoint(video, full["id"]) + "/files/manifest.json"
        ).json()
        assert manifest["exports"][0]["frame_count"] == video["frame_count"]


@pytest.mark.parametrize("unsafe", ["within-data", "symlink"])
def test_unsafe_export_storage_configuration_is_rejected(tmp_path, unsafe):
    store, _, _, _, _ = context(tmp_path)
    target = store.data / "exports"
    if unsafe == "symlink":
        target = tmp_path / "linked"
        target.symlink_to(store.data, target_is_directory=True)
    with pytest.raises(ValueError):
        create_app(tmp_path, store.data, export_root=target)


def test_configured_root_is_lazy_and_http_contract_is_typed(tmp_path, monkeypatch):
    store, video, _, saved, _ = context(tmp_path)
    target = tmp_path / "server-owned" / "exports"
    monkeypatch.setenv("BADMINTON_EXPORT_DIR", str(target))
    with TestClient(create_app(tmp_path, store.data)) as client:
        assert not target.exists()
        schema = client.get("/openapi.json").json()["components"]["schemas"][
            "MediaExportRequest"
        ]
        assert set(schema["required"]) == {"revision", "mode"}
        assert set(schema["properties"]["mode"]["enum"]) == set(MODES)
        assert schema["additionalProperties"] is False
        job = submit(client, store, video, saved.revision)
        assert (target / job["id"] / "manifest.json").is_file()


def test_directory_descriptor_fallback_preserves_verified_binary_downloads(
    tmp_path, monkeypatch
):
    from badminton import export_service

    store, video, _, saved, _ = context(tmp_path)
    monkeypatch.setattr(export_service.os, "supports_dir_fd", set())
    monkeypatch.setattr(export_service.os, "supports_fd", set())
    with TestClient(create_app(tmp_path, store.data)) as client:
        job = submit(client, store, video, saved.revision)
        response = client.get(endpoint(video, job["id"]) + "/files/rally-000001.mp4")
        assert response.status_code == 200
        assert (
            hashlib.sha256(response.content).hexdigest()
            == job["summary"]["files"][1]["sha256"]
        )
        with av.open(io.BytesIO(response.content)) as container:
            assert len(list(container.decode(video=0))) == 6


def test_download_stream_uses_the_verified_handle_without_reopening_path(
    tmp_path, monkeypatch
):
    from badminton.export_service import MediaExportService

    store, video, _, saved, _ = context(tmp_path)
    exports = tmp_path / "exports"
    original = MediaExportService.open_download
    with TestClient(create_app(tmp_path, store.data, export_root=exports)) as client:
        job = submit(client, store, video, saved.revision)
        path = exports / job["id"] / "rally-000001.mp4"
        expected = path.read_bytes()

        def replace_after_open(self, current, filename):
            result = original(self, current, filename)
            path.rename(path.with_suffix(".old"))
            path.write_bytes(b"changed pathname after verification")
            return result

        monkeypatch.setattr(MediaExportService, "open_download", replace_after_open)
        response = client.get(endpoint(video, job["id"]) + "/files/rally-000001.mp4")
        assert response.status_code == 200 and response.content == expected
        assert client.get(endpoint(video, job["id"])).status_code == 409


@pytest.mark.parametrize(
    "field,value",
    [
        ("video_id", "foreign"),
        ("annotation_revision", 99),
        ("mode", "annotated-full"),
        ("manifest_sha256", "0" * 64),
        ("files", []),
    ],
)
def test_modified_job_completion_binding_is_rejected(tmp_path, field, value):
    store, video, _, saved, _ = context(tmp_path)
    with TestClient(create_app(tmp_path, store.data)) as client:
        job = submit(client, store, video, saved.revision)
        job["summary"][field] = value
        store.put_job(job)
        assert client.get(endpoint(video, job["id"])).status_code == 409
        assert (
            client.get(endpoint(video, job["id"]) + "/files/manifest.json").status_code
            == 409
        )
