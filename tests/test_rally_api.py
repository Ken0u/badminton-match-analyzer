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


@pytest.mark.parametrize("mode", ["singles", "doubles"])
def test_saved_proposal_evaluation_requires_full_component_history(workspace, mode):
    from copy import deepcopy

    from badminton.rallies import propose_rallies
    from badminton.shuttle import _ComponentSelector

    root, data, store, video = workspace
    original_video = video
    if mode == "doubles":
        from badminton.ingest import inspect_video
        from badminton.schemas import Annotations
        from rally_fixture import scene

        extra_people = scene("doubles")[1]["frames"][0]["players"][2:]
        # A distinct generated source avoids changing an existing registration.
        source = root / "doubles-qa.mp4"
        source.write_bytes((root / original_video["path"]).read_bytes() + b"\0doubles")
        video = inspect_video(source, "doubles", store, root)
        doc = store.annotations(video["id"]).model_dump()
        doc["calibrations"] = store.annotations(original_video["id"]).model_dump()[
            "calibrations"
        ]
        store.save_annotations(video["id"], Annotations.model_validate(doc))
    run_dir = data / video["id"] / "runs"
    original_dir = data / original_video["id"] / "runs"
    players = json.loads((original_dir / "qa-players.json").read_bytes())
    flight_path = run_dir / "qa-shuttle.json"
    flight = json.loads((original_dir / "qa-shuttle.json").read_bytes())
    if mode == "doubles":
        for run in (players, flight):
            run.update(video_id=video["id"], video_sha256=video["sha256"])
        for row in players["frames"]:
            row["players"].extend(deepcopy(extra_people))
        write_json(run_dir / "qa-players.json", players)
        for run, job_id in ((players, "qa-players"), (flight, "qa-shuttle")):
            store.put_job(
                {
                    "id": job_id,
                    "video_id": video["id"],
                    "kind": run["stage"],
                    "status": "completed",
                    "progress": 1,
                    "summary": {k: v for k, v in run.items() if k != "frames"},
                }
            )
    before_doc = store.annotations(video["id"]).model_dump()
    times = [row["time_s"] for row in players["frames"]]
    control = propose_rallies(video, players, flight, before_doc, source_times=times)
    assert control["candidate_count"] == 2
    selector = _ComponentSelector(video["width"], video["height"])
    for row in flight["frames"]:
        point = row["shuttle"]
        good = {"id": 1, "x": point["x"], "y": point["y"], "confidence": 0.9}
        raw = point | {"component_candidates": [good], "confidence": 0.9}
        if row["frame"] >= 3:
            raw.update(x=-100000, y=-100000)
        row["shuttle"] = selector.select(raw, row["frame"], row["time_s"])
    write_json(flight_path, flight)
    refs = []
    for c in control["candidates"]:
        prefix = "contact_" if c["kind"] == "serve" else "terminal_"
        refs.append(
            dict(
                id=c["id"],
                rally_id="generated-rally",
                frame=c["frame"],
                time_s=c["time_s"],
                kind=c["kind"],
                status="reviewed",
                **{
                    prefix + "start_frame": c["start_frame"],
                    prefix + "end_frame": c["end_frame"],
                },
            )
        )
    doc = deepcopy(before_doc)
    doc.update(
        events=refs,
        review_windows=[
            {
                "id": "review",
                "start_frame": min(
                    c["context_start_frame"] for c in control["candidates"]
                ),
                "end_frame": max(c["context_end_frame"] for c in control["candidates"]),
                "scene": "live",
                "serves_complete": True,
                "rally_ends_complete": True,
            }
        ],
    )
    inputs = {p.name: p.read_bytes() for p in run_dir.glob("*.json")}
    clock = (data / video["id"] / "timestamps.json").read_bytes()
    with TestClient(create_app(root, data)) as client:
        base = f"/api/videos/{video['id']}"
        saved = client.put(base + "/annotations", json=doc)
        assert saved.status_code == 200, saved.text
        saved_doc = saved.json()
        response = client.post(
            base + "/rallies",
            json={"player_run_id": "qa-players", "shuttle_run_id": "qa-shuttle"},
        )
        assert response.status_code == 202, response.text
        job = wait(store, response.json()["id"])
        run_id = job["id"]
        payload = {"rallies_run_id": run_id}
        run = client.get(base + f"/runs/{run_id}").json()
        assert all(c["context_start_frame"] == 0 for c in run["candidates"])
        raw_result = (run_dir / f"{run_id}.json").read_bytes()
        response = client.post(base + "/evaluate", json=payload)
        assert response.status_code == 200, response.text
        for report in response.json()["rallies"]["kinds"].values():
            assert report["coverage"]["reviewed_events"] == 1
            assert report["interval_compatibility"]["matched_count"] == 0
        complete_doc = deepcopy(saved_doc)
        complete_doc["review_windows"][0]["start_frame"] = 0
        response = client.put(base + "/annotations", json=complete_doc)
        assert response.status_code == 200, response.text
        complete_doc = response.json()
        response = client.post(base + "/evaluate", json=payload)
        assert response.status_code == 200, response.text
        for report in response.json()["rallies"]["kinds"].values():
            assert report["coverage"]["reviewed_events"] == 1
            assert report["interval_compatibility"]["matched_count"] == 1
        assert client.get(base + "/annotations").json() == complete_doc
        assert (
            client.get(base + f"/revisions/{saved_doc['revision']}").json() == saved_doc
        )
        assert (run_dir / f"{run_id}.json").read_bytes() == raw_result
    assert {name: (run_dir / name).read_bytes() for name in inputs} == inputs
    assert (data / video["id"] / "timestamps.json").read_bytes() == clock
    assert store.video(video["id"]) == video


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
        for candidate in run["candidates"]:
            assert 0 <= candidate["context_start_frame"] <= candidate["start_frame"]
            assert candidate["end_frame"] < candidate["context_end_frame"] <= 100
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
