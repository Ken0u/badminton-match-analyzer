"""Contact admission checks native identity before producing review artifacts."""

import copy
import hashlib
import json
import time

import pytest
from badminton.api import create_app
from badminton.contacts import propose_contacts
from badminton.schemas import SceneRange
from badminton.storage import Store
from badminton.video import write_json
from fastapi.testclient import TestClient


@pytest.fixture(params=["singles", "doubles"])
def catalog(tmp_path, monkeypatch, request):
    monkeypatch.delenv("BADMINTON_USERNAME", raising=False)
    monkeypatch.delenv("BADMINTON_PASSWORD", raising=False)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"generated contact inputs; no native decoding or model")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    video = {
        "id": checksum[:16],
        "sha256": checksum,
        "path": source.name,
        "mode": request.param,
        "width": 640,
        "height": 360,
        "frame_count": 25,
        "duration_s": 1,
        "source_start_s": 0,
    }
    data = tmp_path / "data"
    store = Store(data)
    store.register(video)
    times = [index / 25 for index in range(25)]
    write_json(data / video["id"] / "timestamps.json", times)
    runs = {}
    for stage in ("shuttle", "players"):
        rows = []
        for index, timestamp in enumerate(times):
            row = {"frame": index, "time_s": timestamp}
            if stage == "shuttle":
                row["shuttle"] = {
                    "visible": True,
                    "x": 300 + 200 * abs(timestamp - times[12]),
                    "y": 200,
                    "repaired": False,
                }
            else:
                row["players"] = [
                    {"track_id": 7, "box": [280, 180, 380, 320], "keypoints": []}
                ]
            rows.append(row)
        runs[stage] = {
            "stage": stage,
            "video_id": video["id"],
            "video_sha256": checksum,
            "start_frame": 0,
            "end_frame": 25,
            "frames": rows,
        }
        store.put_job(
            {"id": stage, "kind": stage, "video_id": video["id"], "status": "completed"}
        )
    return tmp_path, data, store, video, times, runs


def persist(catalog):
    _, data, _, video, _, runs = catalog
    for stage, run in runs.items():
        write_json(data / video["id"] / "runs" / f"{stage}.json", run)


def snapshot(catalog):
    root, data, store, video, _, _ = catalog
    return {
        "source": (root / video["path"]).read_bytes(),
        "annotations": store.annotations(video["id"]).model_dump(),
        "files": {p.relative_to(data): p.read_bytes() for p in data.rglob("*.json")},
        "jobs": store.jobs(),
    }


def assert_preserved(catalog, before, *, no_new_jobs=False):
    root, data, store, video, _, _ = catalog
    assert (root / video["path"]).read_bytes() == before["source"]
    assert store.annotations(video["id"]).model_dump() == before["annotations"]
    assert all(
        (data / path).read_bytes() == raw for path, raw in before["files"].items()
    )
    if no_new_jobs:
        assert store.jobs() == before["jobs"]
        assert {p.relative_to(data) for p in data.rglob("*.json")} == before[
            "files"
        ].keys()


def reject(catalog, request=None):
    root, data, _, video, _, _ = catalog
    persist(catalog)
    before = snapshot(catalog)
    with TestClient(create_app(root, data), raise_server_exceptions=False) as client:
        response = client.post(
            f"/api/videos/{video['id']}/contacts",
            json=request or {"shuttle_run_id": "shuttle", "player_run_id": "players"},
        )
    assert response.status_code == 422, response.text
    assert isinstance(response.json()["detail"], str) and response.json()["detail"]
    assert_preserved(catalog, before, no_new_jobs=True)


@pytest.mark.parametrize("stage", ["shuttle", "players", "both"])
def test_shifted_perception_clock_is_rejected_before_contact_admission(catalog, stage):
    for name, run in catalog[-1].items():
        if stage in (name, "both"):
            for row in run["frames"]:
                row["time_s"] += 0.4
    reject(catalog)


@pytest.mark.parametrize("stage", ["shuttle", "players"])
@pytest.mark.parametrize("checksum", [None, "not-a-hash", "0" * 64])
def test_explicit_invalid_source_hash_is_rejected(catalog, stage, checksum):
    catalog[-1][stage]["video_sha256"] = checksum
    reject(catalog)


@pytest.mark.parametrize("stage", ["shuttle", "players"])
@pytest.mark.parametrize(
    "mutation",
    [
        "float",
        "boolean",
        "negative",
        "out_of_range",
        "duplicate",
        "reversed",
        "nan_time",
        "negative_time",
    ],
)
def test_invalid_original_row_identity_is_rejected(catalog, stage, mutation):
    rows = catalog[-1][stage]["frames"]
    if mutation == "float":
        rows[12]["frame"] = 12.0
    elif mutation == "boolean":
        rows[0]["frame"] = False
    elif mutation == "negative":
        rows[0]["frame"] = -1
    elif mutation == "out_of_range":
        rows[-1]["frame"] = 25
    elif mutation == "duplicate":
        rows.insert(12, copy.deepcopy(rows[12]))
    elif mutation == "reversed":
        rows[10], rows[11] = rows[11], rows[10]
    elif mutation == "nan_time":
        rows[0]["time_s"] = float("nan")
    else:
        rows[0]["time_s"] = -0.01
    reject(catalog)


@pytest.mark.parametrize("stage", ["shuttle", "players"])
@pytest.mark.parametrize(
    "mutation", ["video", "stage", "start", "end", "boolean_bound"]
)
def test_invalid_run_identity_or_declared_range_is_rejected(catalog, stage, mutation):
    run = catalog[-1][stage]
    if mutation == "video":
        run["video_id"] = "another-video"
    elif mutation == "stage":
        run["stage"] = "contacts"
    elif mutation == "start":
        run["start_frame"] = 1
    elif mutation == "end":
        run["end_frame"] = 26
    else:
        run["start_frame"] = False
    reject(catalog)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "short",
        "nan",
        "negative",
        "boolean",
        "duplicate",
        "reversed",
        "object",
    ],
)
def test_entire_native_map_is_checked_even_without_tracking_rows(catalog, mutation):
    _, data, _, video, times, runs = catalog
    for run in runs.values():
        run["frames"] = []
    path = data / video["id"] / "timestamps.json"
    changed = list(times)
    if mutation == "missing":
        path.unlink()
    else:
        if mutation == "short":
            changed.pop()
        elif mutation == "nan":
            changed[-1] = float("nan")
        elif mutation == "negative":
            changed[0] = -1
        elif mutation == "boolean":
            changed[0] = False
        elif mutation == "duplicate":
            changed[1] = changed[0]
        elif mutation == "reversed":
            changed.reverse()
        else:
            changed = {"timestamps": times}
        write_json(path, changed)
    reject(catalog)


def test_bad_input_outside_live_scene_is_not_hidden_by_review_filtering(catalog):
    _, _, store, video, _, runs = catalog
    doc = store.annotations(video["id"])
    doc.scene_ranges = [
        SceneRange(id="excluded", start_frame=0, end_frame=5, scene="replay")
    ]
    store.save_annotations(video["id"], doc)
    runs["shuttle"]["frames"][0]["time_s"] = 0.2
    reject(catalog)


@pytest.mark.parametrize(
    "variant",
    [
        "stable",
        "vfr",
        "sparse",
        "different_windows",
        "legacy",
        "uppercase",
        "no_player",
    ],
)
def test_valid_contact_inputs_keep_candidates_and_original_truth(catalog, variant):
    root, data, store, video, times, runs = catalog
    if variant == "vfr":
        times = [index * 0.039 + (0.001 if index % 2 else 0) for index in range(25)]
        write_json(data / video["id"] / "timestamps.json", times)
        for stage, run in runs.items():
            for row in run["frames"]:
                row["time_s"] = times[row["frame"]]
                if stage == "shuttle":
                    row["shuttle"]["x"] = 300 + 200 * abs(row["time_s"] - times[12])
    if variant == "sparse":
        runs["players"]["frames"] = runs["players"]["frames"][::2]
    if variant == "different_windows":
        runs["players"].update(start_frame=5, end_frame=20)
        runs["players"]["frames"] = runs["players"]["frames"][5:20]
    for run in runs.values():
        if variant == "legacy":
            run.pop("video_sha256")
        elif variant == "uppercase":
            run["video_sha256"] = run["video_sha256"].upper()
    players = None if variant == "no_player" else runs["players"]
    expected = propose_contacts(runs["shuttle"], players, video)
    assert len(expected) == 1 and expected[0]["frame"] == 12
    persist(catalog)
    before = snapshot(catalog)
    body = {"shuttle_run_id": "shuttle"}
    if players is not None:
        body["player_run_id"] = "players"
    with TestClient(create_app(root, data)) as client:
        response = client.post(f"/api/videos/{video['id']}/contacts", json=body)
        assert response.status_code == 202, response.text
        identifier = response.json()["id"]
        for _ in range(300):
            job = store.job(identifier)
            if job["status"] not in ("queued", "running"):
                break
            time.sleep(0.01)
        assert job["status"] == "completed", job
    artifact = json.loads(
        (data / video["id"] / "runs" / f"{identifier}.json").read_bytes()
    )
    assert artifact["candidates"] == expected
    assert artifact["video_sha256"] == video["sha256"]
    assert artifact["source_timestamps_validated"] is True
    expected_hash_status = "unavailable" if variant == "legacy" else "matched"
    assert artifact["input_source_hash_status"] == {
        "shuttle": expected_hash_status,
        "players": "not_requested" if players is None else expected_hash_status,
    }
    assert_preserved(catalog, before)
