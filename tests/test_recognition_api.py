import hashlib
import json
import time

import pytest
from badminton.api import create_app
from badminton.schemas import Annotations, empty_annotations
from badminton.storage import Store
from badminton.video import write_json
from fastapi.testclient import TestClient
from pydantic import ValidationError


@pytest.fixture
def catalog(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"content-addressed fixture; model API does not decode frames")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    video = {
        "id": checksum[:16],
        "sha256": checksum,
        "name": "fixture",
        "path": source.name,
        "mode": "singles",
        "width": 640,
        "height": 360,
        "fps": 25,
        "frame_count": 100,
        "duration_s": 4,
    }
    data = tmp_path / "data"
    store = Store(data)
    store.register(video)
    write_json(data / video["id"] / "timestamps.json", [i / 25 for i in range(100)])
    for stage in ("players", "shuttle", "contacts"):
        artifact = {
            "stage": stage,
            "video_id": video["id"],
            "start_frame": 0,
            "end_frame": 100,
            "frames": [],
            "candidates": [{"id": "contact-30", "frame": 30}],
            "player_run_id": "players",
            "shuttle_run_id": "shuttle",
        }
        write_json(data / video["id"] / "runs" / f"{stage}.json", artifact)
        store.put_job(
            {"id": stage, "kind": stage, "video_id": video["id"], "status": "completed"}
        )
    return tmp_path, data, store, video


def wait(store, identifier):
    for _ in range(300):
        job = next(j for j in store.jobs() if j["id"] == identifier)
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.01)
    pytest.fail("Recognition job did not complete")


def test_recognition_job_creates_separate_predictions_and_only_review_writes_annotations(
    catalog, monkeypatch
):
    import badminton.recognition as recognition

    root, data, store, video = catalog
    calls = []

    def infer(
        v,
        times,
        annotations,
        players,
        shuttle,
        targets,
        player_id,
        progress,
        output,
        threshold,
        contacts_run_id,
    ):
        calls.append((annotations.revision, targets, threshold))
        result = {
            "stage": "recognition",
            "video_id": v["id"],
            "annotation_revision": annotations.revision,
            "player_run_id": player_id,
            "shuttle_run_id": shuttle["run_id"],
            "contacts_run_id": contacts_run_id,
            "candidates": [
                {
                    "id": targets[0]["id"],
                    "frame": 30,
                    "kind": "shot",
                    "family": "clear",
                    "side": "unknown",
                    "status": "predicted",
                    "family_score": 0.8,
                }
            ],
        }
        write_json(output, result)
        progress(1)
        return {key: value for key, value in result.items() if key != "candidates"}

    monkeypatch.setattr(recognition, "recognize_strokes", infer)
    url = f"/api/videos/{video['id']}"
    with TestClient(create_app(root, data)) as client:
        response = client.post(
            url + "/recognize",
            json={
                "player_run_id": "players",
                "shuttle_run_id": "shuttle",
                "contacts_run_id": "contacts",
            },
        )
        assert response.status_code == 202, response.text
        identifier = response.json()["id"]
        assert wait(store, identifier)["status"] == "completed"
        assert (
            store.annotations(video["id"]).revision == 0
            and not store.annotations(video["id"]).events
        )
        result = client.get(url + f"/runs/{identifier}").json()
        assert (
            result["stage"] == "recognition"
            and result["candidates"][0]["side"] == "unknown"
        )
        doc = client.get(url + "/annotations").json()
        doc["events"] = [
            {
                "id": "reviewed",
                "kind": "shot",
                "rally_id": "R1",
                "frame": 30,
                "family": "clear",
                "side": "backhand",
                "classification_run_id": identifier,
                "classification_candidate_id": result["candidates"][0]["id"],
                "family_score": 0.8,
            }
        ]
        saved = client.put(url + "/annotations", json=doc)
        assert saved.status_code == 200, saved.text
        event = saved.json()["events"][0]
        assert event["time_s"] == pytest.approx(1.2) and event["side"] == "backhand"
        assert event["classification_run_id"] == identifier
        exported = client.get(url + "/export?format=csv").text
        assert "classification_run_id" in exported and identifier in exported
        assert client.get(url + "/revisions/0").json()["events"] == []
    assert calls[0][0] == 0


@pytest.mark.parametrize(
    "failure,code",
    [
        ("no_targets", 422),
        ("mismatched_parent", 422),
        ("wrong_stage", 404),
        ("stride", 422),
        ("doubles", 422),
        ("nan", 422),
    ],
)
def test_recognition_rejects_invalid_context_before_claiming_a_job(
    catalog, failure, code
):
    root, data, store, video = catalog
    body = {
        "player_run_id": "players",
        "shuttle_run_id": "shuttle",
        "contacts_run_id": "contacts",
    }
    if failure == "no_targets":
        body.pop("contacts_run_id")
    if failure == "wrong_stage":
        body["player_run_id"] = "shuttle"
    if failure == "nan":
        body["min_family_score"] = "NaN"
    if failure in ("stride", "mismatched_parent"):
        stage = "players" if failure == "stride" else "contacts"
        path = data / video["id"] / "runs" / f"{stage}.json"
        document = json.loads(path.read_text())
        document["stride" if failure == "stride" else "shuttle_run_id"] = (
            2 if failure == "stride" else "different-run"
        )
        write_json(path, document)
    if failure == "doubles":
        with store.connect() as connection:
            video["mode"] = "doubles"
            connection.execute(
                "UPDATE videos SET document=? WHERE id=?",
                (json.dumps(video), video["id"]),
            )
    with TestClient(create_app(root, data)) as client:
        response = client.post(f"/api/videos/{video['id']}/recognize", json=body)
        assert response.status_code == code, response.text
    assert len(store.jobs()) == 3


def test_classification_provenance_is_paired_unique_and_requires_real_artifact(catalog):
    root, data, store, video = catalog
    doc = empty_annotations("singles").model_dump()
    event = {
        "id": "e",
        "kind": "shot",
        "rally_id": "R1",
        "frame": 30,
        "family": "net",
        "side": "unknown",
        "classification_run_id": "imaginary",
    }
    doc["events"] = [event]
    with pytest.raises(ValidationError, match="both run and candidate"):
        Annotations.model_validate(doc)
    event["classification_candidate_id"] = "missing"
    with TestClient(create_app(root, data)) as client:
        response = client.put(f"/api/videos/{video['id']}/annotations", json=doc)
        assert response.status_code == 422 and "completed recognition" in response.text
    assert store.annotations(video["id"]).revision == 0


@pytest.mark.parametrize(
    "field,value", [("frame", 31), ("family", "drop"), ("family_score", 0.99)]
)
def test_review_cannot_attach_an_old_model_score_to_a_changed_contact(
    catalog, field, value
):
    root, data, store, video = catalog
    candidate = {
        "id": "stroke",
        "frame": 30,
        "kind": "shot",
        "family": "net",
        "family_score": 0.8,
    }
    artifact = {
        "stage": "recognition",
        "video_id": video["id"],
        "candidates": [candidate],
    }
    write_json(data / video["id"] / "runs" / "model.json", artifact)
    store.put_job(
        {
            "id": "model",
            "kind": "recognition",
            "video_id": video["id"],
            "status": "completed",
        }
    )
    doc = store.annotations(video["id"]).model_dump()
    doc["events"] = [
        candidate
        | {
            "rally_id": "QA",
            "side": "unknown",
            "classification_run_id": "model",
            "classification_candidate_id": "stroke",
            field: value,
        }
    ]
    with TestClient(create_app(root, data)) as client:
        response = client.put(f"/api/videos/{video['id']}/annotations", json=doc)
        assert (
            response.status_code == 422
            and "Clear the model family score" in response.text
        )
        doc["events"][0]["family_score"] = None
        assert (
            client.put(f"/api/videos/{video['id']}/annotations", json=doc).status_code
            == 200
        )
    assert (
        json.loads((data / video["id"] / "runs" / "model.json").read_text()) == artifact
    )


def test_recognition_hitter_view_uses_current_reviewed_mapping_without_rewriting_artifact(
    catalog,
):
    root, data, store, video = catalog
    artifact = {
        "stage": "recognition",
        "video_id": video["id"],
        "player_run_id": "players",
        "candidates": [{"frame": 30, "hitter_hint": {"track_id": 7, "player_id": "A"}}],
    }
    path = data / video["id"] / "runs" / "model.json"
    write_json(path, artifact)
    before = path.read_bytes()
    store.put_job(
        {
            "id": "model",
            "kind": "recognition",
            "video_id": video["id"],
            "status": "completed",
        }
    )
    players_path = data / video["id"] / "runs" / "players.json"
    players = json.loads(players_path.read_text())
    players["frames"] = [{"frame": 30, "players": [{"track_id": 7}]}]
    write_json(players_path, players)
    with TestClient(create_app(root, data)) as client:
        url = f"/api/videos/{video['id']}"
        assert (
            client.get(url + "/runs/model").json()["candidates"][0]["hitter_hint"][
                "player_id"
            ]
            is None
        )
        doc = store.annotations(video["id"]).model_dump()
        doc["track_assignments"] = [
            {
                "run_id": "players",
                "track_id": 7,
                "player_id": "B",
                "start_frame": 30,
                "end_frame": 31,
            }
        ]
        assert client.put(url + "/annotations", json=doc).status_code == 200
        assert (
            client.get(url + "/runs/model").json()["candidates"][0]["hitter_hint"][
                "player_id"
            ]
            == "B"
        )
    assert path.read_bytes() == before


def test_recognition_evaluation_api_excludes_model_assisted_labels_and_reports_missing_side(
    catalog,
):
    root, data, store, video = catalog
    artifact = {
        "stage": "recognition",
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "start_frame": 0,
        "end_frame": 100,
        "candidates": [
            {
                "id": "c",
                "frame": 30,
                "time_s": 1.2,
                "kind": "shot",
                "family": "clear",
                "side": "unknown",
                "status": "predicted",
                "hitter_hint": {"player_id": "A"},
            }
        ],
    }
    write_json(data / video["id"] / "runs" / "model.json", artifact)
    store.put_job(
        {
            "id": "model",
            "kind": "recognition",
            "video_id": video["id"],
            "status": "completed",
        }
    )
    url = f"/api/videos/{video['id']}"
    with TestClient(create_app(root, data)) as client:
        doc = client.get(url + "/annotations").json()
        doc["events"] = [
            {
                "id": "gold",
                "rally_id": "R",
                "frame": 30,
                "kind": "shot",
                "family": "clear",
                "side": "backhand",
                "player_id": "A",
            }
        ]
        doc["review_windows"] = [
            {
                "id": "w",
                "start_frame": 0,
                "end_frame": 100,
                "scene": "live",
                "contacts_complete": True,
            }
        ]
        saved = client.put(url + "/annotations", json=doc)
        assert saved.status_code == 200, saved.text
        response = client.post(url + "/evaluate", json={"recognition_run_id": "model"})
        assert response.status_code == 200, response.text
        result = response.json()["recognition"]
        assert (
            result["run_id"] == "model"
            and result["family"]["per_class"]["clear"]["f1"] == 1
        )
        assert (
            result["complete_event"]["f1"] == 0
            and result["side"]["balanced_accuracy"] is None
        )
        doc = saved.json()
        doc["events"][0].update(
            classification_run_id="model", classification_candidate_id="c"
        )
        assert client.put(url + "/annotations", json=doc).status_code == 200
        result = client.post(
            url + "/evaluate", json={"recognition_run_id": "model"}
        ).json()["recognition"]
        assert result["family"]["macro_f1_supported"] is None
        assert result["labels"]["excluded_model_assisted_event_ids"] == ["gold"]
        assert (
            client.post(
                url + "/evaluate", json={"recognition_run_id": "players"}
            ).status_code
            == 404
        )
