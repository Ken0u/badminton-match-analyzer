"""Real HTTP media exports preserve native evidence and shared admission."""

import asyncio
import errno
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import anyio
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


@pytest.mark.parametrize("deny_rename", [False, True])
def test_download_stream_uses_the_verified_handle_without_reopening_path(
    tmp_path, monkeypatch, deny_rename
):
    from badminton.export_service import MediaExportService

    store, video, _, saved, _ = context(tmp_path)
    exports = tmp_path / "exports"
    original = MediaExportService.open_download
    with TestClient(create_app(tmp_path, store.data, export_root=exports)) as client:
        job = submit(client, store, video, saved.revision)
        path = exports / job["id"] / "rally-000001.mp4"
        expected = path.read_bytes()
        retained, blocked = [], []

        def replace_after_open(self, current, filename):
            result = original(self, current, filename)
            retained.append(result["file"])
            try:
                if deny_rename:
                    raise PermissionError(errno.EACCES, "Simulated Windows sharing")
                path.rename(path.with_suffix(".old"))
            except PermissionError as exc:
                # Windows CRT handles can deny rename while the verified file
                # is open. The unchanged handle must still stream correctly.
                assert os.name == "nt" or deny_rename
                assert exc.errno == errno.EACCES or getattr(exc, "winerror", None) in (
                    5,
                    32,
                )
                blocked.append(True)
            else:
                path.write_bytes(b"changed pathname after verification")
            return result

        monkeypatch.setattr(MediaExportService, "open_download", replace_after_open)
        response = client.get(endpoint(video, job["id"]) + "/files/rally-000001.mp4")
        assert response.status_code == 200 and response.content == expected
        assert retained and all(handle.closed for handle in retained)
        assert client.get(endpoint(video, job["id"])).status_code == (
            200 if blocked else 409
        )


def test_reparse_attribute_is_refused_without_requiring_python312_junction_api(
    tmp_path, monkeypatch
):
    store, _, _, _, _ = context(tmp_path)
    target = tmp_path / "exports"
    target.mkdir()
    original = Path.lstat

    def reparse(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == target:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=1024)
        return info

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(ValueError, match=r"symlink|reparse"):
        create_app(tmp_path, store.data, export_root=target)


@pytest.mark.skipif(os.name != "nt", reason="Native Windows junction regression")
@pytest.mark.parametrize("component", ["configured-root", "job-directory"])
def test_native_windows_junctions_cannot_redirect_export_storage(tmp_path, component):
    store, video, _, saved, _ = context(tmp_path)
    exports, outside = tmp_path / "exports", tmp_path / "outside"

    def junction(link, destination):
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(destination)],
            check=True,
            capture_output=True,
            text=True,
        )
        assert link.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT

    if component == "configured-root":
        outside.mkdir()
        junction(exports, outside)
        with pytest.raises(ValueError, match=r"symlink|reparse"):
            create_app(tmp_path, store.data, export_root=exports)
    else:
        with TestClient(
            create_app(tmp_path, store.data, export_root=exports)
        ) as client:
            job = submit(client, store, video, saved.revision)
            folder = exports / job["id"]
            folder.rename(outside)
            junction(folder, outside)
            assert client.get(endpoint(video, job["id"])).status_code == 409
            assert (
                client.get(
                    endpoint(video, job["id"]) + "/files/manifest.json"
                ).status_code
                == 409
            )
            assert (
                client.get(
                    endpoint(video, job["id"]) + "/files/rally-000001.mp4"
                ).status_code
                == 409
            )


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


@pytest.mark.parametrize("filename", ["rally-000001.mp4", "manifest.json"])
@pytest.mark.parametrize("mutation", ["overwrite", "truncate", "grow"])
def test_download_snapshot_survives_in_place_mutation_before_http_iteration(
    tmp_path, monkeypatch, filename, mutation
):
    from badminton.export_service import MediaExportService

    store, video, _, saved, _ = context(tmp_path)
    exports = tmp_path / "exports"
    original = MediaExportService.open_download
    retained = []
    with TestClient(create_app(tmp_path, store.data, export_root=exports)) as client:
        job = submit(client, store, video, saved.revision)
        path = exports / job["id"] / filename
        expected = path.read_bytes()
        receipt = next(f for f in job["summary"]["files"] if f["filename"] == filename)
        expected_names = {f["filename"] for f in job["summary"]["files"]}

        def mutate_after_snapshot(self, current, name):
            result = original(self, current, name)
            retained.append(result["file"])
            before = path.stat().st_ino
            changed = (
                bytes([expected[0] ^ 1]) + expected[1:]
                if mutation == "overwrite"
                else expected[:-1]
                if mutation == "truncate"
                else expected + b"extra"
            )
            with path.open("r+b") as target:
                target.write(changed)
                target.truncate()
            assert path.stat().st_ino == before
            return result

        monkeypatch.setattr(MediaExportService, "open_download", mutate_after_snapshot)
        response = client.get(endpoint(video, job["id"]) + "/files/" + filename)
        assert response.status_code == 200 and response.content == expected
        assert len(response.content) == int(response.headers["content-length"])
        assert len(response.content) == receipt["size_bytes"]
        assert hashlib.sha256(response.content).hexdigest() == receipt["sha256"]
        assert retained and all(handle.closed for handle in retained)
        assert {p.name for p in path.parent.iterdir()} == expected_names
        assert client.get(endpoint(video, job["id"])).status_code == 409
        if filename == "manifest.json":
            assert response.json()["annotations"] == saved.model_dump(mode="json")
        else:
            downloaded = tmp_path / "downloaded.mp4"
            downloaded.write_bytes(response.content)
            times = json.loads(
                (store.data / video["id"] / "timestamps.json").read_bytes()
            )
            assert_native_media(downloaded, video, times, 1, 7, times[7] - times[1])


@pytest.mark.parametrize("filename", ["rally-000001.mp4", "manifest.json"])
@pytest.mark.parametrize("timing", ["after-verification", "during-copy"])
@pytest.mark.parametrize("mutation", ["overwrite", "truncate", "grow"])
def test_mutable_source_is_reverified_when_building_download_snapshot(
    tmp_path, monkeypatch, filename, timing, mutation
):
    from badminton import export_service

    store, video, _, saved, _ = context(tmp_path)
    exports = tmp_path / "exports"
    original = export_service.MediaExportService._validated
    temporary_file = export_service.tempfile.TemporaryFile
    retained, source_handles, read_sizes = [], [], []
    with TestClient(create_app(tmp_path, store.data, export_root=exports)) as client:
        job = submit(client, store, video, saved.revision)
        path = exports / job["id"] / filename
        expected = path.read_bytes()
        original_files = {p.name: p.read_bytes() for p in path.parent.iterdir()}

        def mutate():
            # Change the tail so a mid-copy mutation affects unread bytes.
            changed = (
                expected[:-1] + bytes([expected[-1] ^ 1])
                if mutation == "overwrite"
                else expected[:-1]
                if mutation == "truncate"
                else expected + b"extra"
            )
            with path.open("r+b") as target:
                target.write(changed)
                target.truncate()

        class MutatingReader:
            def __init__(self, handle):
                self.handle = handle
                self.started = False

            def seek(self, offset):
                return self.handle.seek(offset)

            def read(self, size):
                assert 0 < size <= 512
                read_sizes.append(size)
                chunk = self.handle.read(size)
                if not self.started:
                    self.started = True
                    mutate()
                    # Discard read-ahead to force the next read to see the
                    # rewritten inode, deterministically on every platform.
                    position = self.handle.tell()
                    self.handle.seek(len(expected) + 10)
                    self.handle.seek(position)
                return chunk

        def changed_validation(self, current, stack, requested=None):
            result = original(self, current, stack, requested)
            if requested is not None:
                source_handles.extend(result[2].values())
                if timing == "after-verification":
                    mutate()
                else:
                    result[2][filename] = MutatingReader(result[2][filename])
            return result

        def track_temporary():
            handle = temporary_file()
            retained.append(handle)
            return handle

        monkeypatch.setattr(export_service, "_COPY_CHUNK", 512)
        monkeypatch.setattr(export_service.tempfile, "TemporaryFile", track_temporary)
        monkeypatch.setattr(
            export_service.MediaExportService, "_validated", changed_validation
        )
        response = client.get(endpoint(video, job["id"]) + "/files/" + filename)
        assert response.status_code == 409, response.text
        assert retained and all(handle.closed for handle in retained)
        assert source_handles and all(handle.closed for handle in source_handles)
        if timing == "during-copy":
            assert len(read_sizes) > 1
        assert {p.name for p in path.parent.iterdir()} == set(original_files)
        assert all(
            (path.parent / name).read_bytes() == content
            for name, content in original_files.items()
            if name != filename
        )
        assert store.job(job["id"])["summary"] == job["summary"]


@pytest.mark.parametrize(
    "failure",
    [
        "create",
        "write",
        "short-write",
        "corrupt-write",
        "flush",
        "seek",
        "read",
        "source-read",
        "directory-exit",
    ],
)
def test_snapshot_storage_failures_reject_before_http_success_and_close_handles(
    tmp_path, monkeypatch, failure
):
    from contextlib import contextmanager

    from badminton import export_service

    store, video, source, saved, _ = context(tmp_path)
    exports = tmp_path / "exports"
    temporary_file = export_service.tempfile.TemporaryFile
    open_file = export_service._open_file
    retained, source_handles = [], []
    with TestClient(create_app(tmp_path, store.data, export_root=exports)) as client:
        job = submit(client, store, video, saved.revision)
        folder = exports / job["id"]
        original_files = {p.name: p.read_bytes() for p in folder.iterdir()}
        original_source = source.read_bytes()
        original_data = {p: p.read_bytes() for p in store.data.rglob("*.json")}

        class FailingTemporary:
            def __init__(self, handle):
                self.handle = handle

            def __getattr__(self, name):
                return getattr(self.handle, name)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.handle.close()

            def write(self, chunk):
                if failure == "write":
                    raise OSError(errno.ENOSPC, "Snapshot storage is full")
                if failure == "short-write":
                    return self.handle.write(chunk[:-1])
                if failure == "corrupt-write":
                    chunk = bytes([chunk[0] ^ 1]) + chunk[1:]
                return self.handle.write(chunk)

            def flush(self):
                if failure == "flush":
                    raise OSError(errno.ENOSPC, "Deferred snapshot storage failure")
                return self.handle.flush()

            def seek(self, offset):
                if failure == "seek":
                    raise OSError(errno.EIO, "Snapshot seek failed")
                return self.handle.seek(offset)

            def read(self, size):
                if failure == "read":
                    raise OSError(errno.EIO, "Snapshot read failed")
                return self.handle.read(size)

        def failing_temporary():
            if failure == "create":
                raise OSError(errno.ENOSPC, "Cannot create download snapshot")
            handle = temporary_file()
            retained.append(handle)
            return FailingTemporary(handle)

        def track_source(*args):
            handle = open_file(*args)
            source_handles.append(handle)
            return handle

        original_validation = export_service.MediaExportService._validated

        def fail_source_after_validation(self, current, stack, requested=None):
            result = original_validation(self, current, stack, requested)
            if requested is not None:
                handle = result[2][requested]
                source_handles.append(handle)
                if failure == "source-read":

                    class Unreadable:
                        def seek(self, offset):
                            return handle.seek(offset)

                        def read(self, size):
                            raise OSError(errno.EIO, "Source read failed during copy")

                    result[2][requested] = Unreadable()
            return result

        if failure == "directory-exit":
            original_directory = export_service._directory

            @contextmanager
            def failing_directory(path):
                with original_directory(path) as descriptor:
                    yield descriptor
                raise ValueError("Directory changed during fallback exit validation")

            monkeypatch.setattr(export_service, "_directory", failing_directory)
        monkeypatch.setattr(export_service, "_open_file", track_source)
        monkeypatch.setattr(export_service.tempfile, "TemporaryFile", failing_temporary)
        monkeypatch.setattr(
            export_service.MediaExportService,
            "_validated",
            fail_source_after_validation,
        )
        response = client.get(endpoint(video, job["id"]) + "/files/rally-000001.mp4")
        assert response.status_code == 409 and "Start a new export" in response.text
        assert all(handle.closed for handle in retained)
        assert source_handles and all(handle.closed for handle in source_handles)
        assert {p.name: p.read_bytes() for p in folder.iterdir()} == original_files
        assert source.read_bytes() == original_source
        assert all(p.read_bytes() == content for p, content in original_data.items())
        assert store.job(job["id"])["summary"] == job["summary"]
    # Failure of one download must not invalidate a prior completed export.
    monkeypatch.undo()
    with TestClient(create_app(tmp_path, store.data, export_root=exports)) as client:
        response = client.get(endpoint(video, job["id"]) + "/files/rally-000001.mp4")
        assert response.status_code == 200
        assert response.content == original_files["rally-000001.mp4"]


@pytest.mark.parametrize(
    "spec,termination",
    [
        ("2.4", "success"),
        ("2.0", "success"),
        ("2.4", "start-error"),
        ("2.4", "body-error"),
        ("2.4", "pre-body-cancel"),
        ("2.0", "disconnect-before-body"),
        ("2.0", "disconnect-during-body"),
    ],
)
def test_native_download_asgi_termination_closes_snapshot(
    tmp_path, monkeypatch, spec, termination
):
    from badminton.export_service import MediaExportService
    from starlette.requests import ClientDisconnect

    store, video, _, saved, _ = context(tmp_path)
    app = create_app(tmp_path, store.data)
    original = MediaExportService.open_download
    retained, reads, messages = [], [], []

    class ObservedHandle:
        def __init__(self, handle):
            self.handle = handle

        def read(self, size):
            reads.append(size)
            return self.handle.read(size)

        def close(self):
            self.handle.close()

    def track_snapshot(self, job, filename):
        result = original(self, job, filename)
        retained.append(result["file"])
        result["file"] = ObservedHandle(result["file"])
        return result

    with TestClient(app) as client:
        job = submit(client, store, video, saved.revision)
        monkeypatch.setattr(MediaExportService, "open_download", track_snapshot)
        route = next(
            route
            for route in app.routes
            if getattr(route, "path", None)
            == "/api/videos/{video_id}/media-exports/{job_id}/files/{filename}"
        )
        # Use the real endpoint's native snapshot and Starlette's real ASGI
        # protocol/disconnect machinery; no TestClient eager body consumption.
        response = route.endpoint(video["id"], job["id"], "rally-000001.mp4")
        assert retained and not reads and not retained[0].closed

        async def run_response():
            disconnect = anyio.Event()

            async def send(message):
                messages.append(message)
                if message["type"] == "http.response.start":
                    if termination == "start-error":
                        raise OSError("Connection lost before first body read")
                    if termination == "pre-body-cancel":
                        raise asyncio.CancelledError()
                    if termination == "disconnect-before-body":
                        disconnect.set()
                        await anyio.sleep_forever()
                elif message.get("body"):
                    if termination == "body-error":
                        raise OSError("Connection lost during body send")
                    if termination == "disconnect-during-body":
                        disconnect.set()
                        await anyio.sleep_forever()

            async def receive():
                await disconnect.wait()
                return {"type": "http.disconnect"}

            await response(
                {"type": "http", "asgi": {"spec_version": spec}}, receive, send
            )

        if termination in ("start-error", "body-error"):
            with pytest.raises(ClientDisconnect):
                asyncio.run(run_response())
        elif termination == "pre-body-cancel":
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(run_response())
        else:
            asyncio.run(run_response())
        assert all(handle.closed for handle in retained)
        if termination in ("start-error", "pre-body-cancel", "disconnect-before-body"):
            assert not reads
        else:
            assert reads and all(size == 64 * 1024 for size in reads)
        if termination == "success":
            content = b"".join(message.get("body", b"") for message in messages)
            receipt = job["summary"]["files"][1]
            assert len(content) == receipt["size_bytes"]
            assert hashlib.sha256(content).hexdigest() == receipt["sha256"]


def test_download_response_construction_failure_closes_snapshot(tmp_path):
    from badminton.api import _ExportDownloadResponse
    from badminton.export_service import MediaExportService

    store, video, _, saved, _ = context(tmp_path)
    exports = tmp_path / "exports"
    with TestClient(create_app(tmp_path, store.data, export_root=exports)) as client:
        job = submit(client, store, video, saved.revision)
        service = MediaExportService(tmp_path, store.data, exports)
        download = service.open_download(job, "rally-000001.mp4")
        del download["filename"]
        with pytest.raises(KeyError):
            _ExportDownloadResponse(download)
        assert download["file"].closed
