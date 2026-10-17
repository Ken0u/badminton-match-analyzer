"""Event uncertainty intervals stay explicit across validation and revisions."""

import csv
import io

import pytest
from badminton.api import create_app
from badminton.schemas import Event
from badminton.storage import Store
from badminton.video import write_json
from fastapi.testclient import TestClient
from pydantic import ValidationError


def shot(**changes):
    return {
        "id": "shot-1",
        "rally_id": "R1",
        "kind": "shot",
        "frame": 2,
        "family": "unknown",
        "side": "unknown",
        "player_id": None,
    } | changes


@pytest.fixture
def interval_workspace(tmp_path, monkeypatch):
    monkeypatch.delenv("BADMINTON_USERNAME", raising=False)
    monkeypatch.delenv("BADMINTON_PASSWORD", raising=False)
    data = tmp_path / "processed"
    store = Store(data)
    video = {
        "id": "interval-video",
        "name": "Interval contract fixture",
        "mode": "singles",
        "frame_count": 6,
    }
    store.register(video)
    write_json(
        data / video["id"] / "timestamps.json", [0, 0.04, 0.12, 0.16, 0.24, 0.28]
    )
    return tmp_path, data, store, video


def test_point_events_default_to_no_uncertainty_bounds():
    event = Event.model_validate(shot())
    assert event.contact_start_frame is None
    assert event.contact_end_frame is None
    assert (
        event.family == "unknown"
        and event.side == "unknown"
        and event.player_id is None
    )


@pytest.mark.parametrize("start,end", [(0, 2), (2, 5), (1, 3), (2, 2)])
def test_contact_interval_is_inclusive_and_may_be_a_single_frame(start, end):
    event = Event.model_validate(shot(contact_start_frame=start, contact_end_frame=end))
    assert event.contact_start_frame == start
    assert event.contact_end_frame == end


def test_serve_can_record_contact_uncertainty_without_a_shot_family():
    event = Event(
        id="serve",
        rally_id="R1",
        kind="serve",
        frame=2,
        contact_start_frame=1,
        contact_end_frame=3,
    )
    assert event.family is None
    assert event.contact_start_frame == 1 and event.contact_end_frame == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"contact_start_frame": 1},
        {"contact_end_frame": 3},
        {"contact_start_frame": 1, "contact_end_frame": None},
        {"contact_start_frame": None, "contact_end_frame": 3},
        {"contact_start_frame": 3, "contact_end_frame": 1},
        {"contact_start_frame": 3, "contact_end_frame": 4},
        {"contact_start_frame": 0, "contact_end_frame": 1},
        {"contact_start_frame": -1, "contact_end_frame": 3},
        {"contact_start_frame": -2, "contact_end_frame": -1},
    ],
)
def test_invalid_contact_interval_requires_a_paired_ordered_range_containing_frame(
    changes,
):
    with pytest.raises(ValidationError):
        Event.model_validate(shot(**changes))


def test_rally_end_cannot_contain_contact_uncertainty():
    with pytest.raises(ValidationError):
        Event(
            id="end",
            rally_id="R1",
            kind="rally_end",
            frame=2,
            contact_start_frame=1,
            contact_end_frame=3,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"terminal_start_frame": 1},
        {"terminal_end_frame": 3},
        {"terminal_start_frame": 3, "terminal_end_frame": 4},
        {"terminal_start_frame": 0, "terminal_end_frame": 1},
        {"terminal_start_frame": -1, "terminal_end_frame": 3},
        {"kind": "serve", "terminal_start_frame": 1, "terminal_end_frame": 3},
    ],
)
def test_terminal_intervals_require_rally_end_and_paired_bounds(changes):
    with pytest.raises(ValidationError):
        Event.model_validate(
            {"id": "end", "rally_id": "R1", "kind": "rally_end", "frame": 2} | changes
        )


def test_terminal_interval_history_exports_removal_and_vfr_time(interval_workspace):
    root, data, store, video = interval_workspace
    url = f"/api/videos/{video['id']}"
    with TestClient(create_app(root, data)) as client:
        initial = client.get(url + "/annotations").json()
        initial["events"] = [
            {
                "id": "terminal",
                "rally_id": "R1",
                "kind": "rally_end",
                "frame": 2,
                "time_s": 99,
                "terminal_start_frame": 1,
                "terminal_end_frame": 5,
            }
        ]
        first = client.put(url + "/annotations", json=initial)
        assert first.status_code == 200, first.text
        assert first.json()["events"][0]["time_s"] == pytest.approx(0.12)
        invalid = first.json()
        invalid["events"][0]["terminal_end_frame"] = 6
        assert client.put(url + "/annotations", json=invalid).status_code == 422
        assert store.annotations(video["id"]).revision == 1
        assert client.get(url + "/export").json()["annotations"] == first.json()
        row = next(
            csv.DictReader(io.StringIO(client.get(url + "/export?format=csv").text))
        )
        assert row["terminal_start_frame"] == "1"
        assert row["terminal_end_frame"] == "5"
        assert row["contact_start_frame"] == "" and row["contact_end_frame"] == ""
        cleared = first.json()
        cleared["events"][0] |= {
            "terminal_start_frame": None,
            "terminal_end_frame": None,
        }
        response = client.put(url + "/annotations", json=cleared)
        assert response.status_code == 200, response.text
        assert client.get(url + "/revisions/1").json() == first.json()
        assert response.json()["events"][0]["terminal_end_frame"] is None
        assert client.put(url + "/annotations", json=first.json()).status_code == 409


@pytest.mark.parametrize(
    "event",
    [
        shot(contact_start_frame=0, contact_end_frame=6),
        shot(contact_start_frame=1, contact_end_frame=7),
        shot(contact_start_frame=3, contact_end_frame=4),
        shot(contact_start_frame=1),
        shot(contact_start_frame=-1, contact_end_frame=3),
        {
            "id": "end",
            "rally_id": "R1",
            "kind": "rally_end",
            "frame": 2,
            "contact_start_frame": 1,
            "contact_end_frame": 3,
        },
    ],
)
def test_api_rejects_invalid_interval_without_creating_revision(
    interval_workspace, event
):
    root, data, store, video = interval_workspace
    url = f"/api/videos/{video['id']}/annotations"
    with TestClient(create_app(root, data)) as client:
        doc = client.get(url).json()
        doc["events"] = [event]
        response = client.put(url, json=doc)
    assert response.status_code == 422, response.text
    assert store.annotations(video["id"]).revision == 0


def test_api_history_json_and_csv_preserve_inclusive_bounds_and_source_times(
    interval_workspace,
):
    root, data, _store, video = interval_workspace
    url = f"/api/videos/{video['id']}"
    with TestClient(create_app(root, data)) as client:
        initial = client.get(url + "/annotations").json()
        initial["events"] = [
            shot(contact_start_frame=0, contact_end_frame=5, time_s=99)
        ]
        response = client.put(url + "/annotations", json=initial)
        assert response.status_code == 200, response.text
        first = response.json()
        assert first["revision"] == 1
        assert first["events"][0]["time_s"] == pytest.approx(0.12)
        assert first["events"][0]["contact_start_frame"] == 0
        assert first["events"][0]["contact_end_frame"] == 5
        changed = response.json()
        changed["events"][0] |= {
            "frame": 3,
            "contact_start_frame": 1,
            "contact_end_frame": 4,
            "status": "corrected",
        }
        response = client.put(url + "/annotations", json=changed)
        assert response.status_code == 200, response.text
        assert client.put(url + "/annotations", json=first).status_code == 409
        assert client.get(url + "/revisions/1").json() == first
        latest = client.get(url + "/annotations").json()
        assert latest["revision"] == 2 and latest["events"][0][
            "time_s"
        ] == pytest.approx(0.16)
        assert client.get(url + "/export").json()["annotations"] == latest
        rows = list(
            csv.DictReader(io.StringIO(client.get(url + "/export?format=csv").text))
        )
        assert len(rows) == 1
        assert rows[0]["frame"] == "3"
        assert rows[0]["contact_start_frame"] == "1"
        assert rows[0]["contact_end_frame"] == "4"
        assert rows[0]["family"] == "unknown" and rows[0]["side"] == "unknown"
        assert rows[0]["player_id"] == ""


def test_removing_bounds_restores_point_event_and_exports_empty_interval_fields(
    interval_workspace,
):
    root, data, _store, video = interval_workspace
    url = f"/api/videos/{video['id']}"
    with TestClient(create_app(root, data)) as client:
        doc = client.get(url + "/annotations").json()
        doc["events"] = [shot(contact_start_frame=1, contact_end_frame=3)]
        response = client.put(url + "/annotations", json=doc)
        assert response.status_code == 200, response.text
        changed = response.json()
        changed["events"][0] |= {"contact_start_frame": None, "contact_end_frame": None}
        response = client.put(url + "/annotations", json=changed)
        assert response.status_code == 200, response.text
        point = response.json()["events"][0]
        assert (
            point["contact_start_frame"] is None and point["contact_end_frame"] is None
        )
        row = next(
            csv.DictReader(io.StringIO(client.get(url + "/export?format=csv").text))
        )
        assert row["contact_start_frame"] == "" and row["contact_end_frame"] == ""


def test_reviewed_uncertainty_does_not_modify_contact_prediction_artifact(
    interval_workspace,
):
    root, data, store, video = interval_workspace
    artifact = data / video["id"] / "runs" / "contacts-1.json"
    write_json(
        artifact,
        {
            "video_id": video["id"],
            "stage": "contacts",
            "start_frame": 0,
            "end_frame": 6,
            "player_run_id": None,
            "shuttle_run_id": "shuttle-1",
            "candidates": [
                {
                    "id": "contact-2",
                    "frame": 2,
                    "time_s": 0.12,
                    "track_id": None,
                    "player_id": None,
                }
            ],
        },
    )
    before = artifact.read_bytes()
    store.put_job(
        {
            "id": "contacts-1",
            "kind": "contacts",
            "video_id": video["id"],
            "status": "completed",
        }
    )
    url = f"/api/videos/{video['id']}"
    with TestClient(create_app(root, data)) as client:
        doc = client.get(url + "/annotations").json()
        doc["events"] = [
            shot(
                contact_start_frame=1,
                contact_end_frame=3,
                source_run_id="contacts-1",
                candidate_id="contact-2",
            )
        ]
        response = client.put(url + "/annotations", json=doc)
        assert response.status_code == 200, response.text
        assert response.json()["events"][0]["contact_start_frame"] == 1
        predictions = client.get(url + "/runs/contacts-1").json()
        assert predictions["candidates"][0]["frame"] == 2
        assert predictions["candidates"][0].get("contact_start_frame") is None
    assert artifact.read_bytes() == before
