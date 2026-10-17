"""Exercise reviewed coverage, identity, and evaluation through the public API."""

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from badminton.api import create_app
from badminton.schemas import Annotations, ShuttlePoint, empty_annotations
from badminton.storage import Store
from badminton.video import write_json
from fastapi.testclient import TestClient
from pydantic import ValidationError


@pytest.fixture
def review_workspace(tmp_path):
    # These routes only verify the file hash; they do not decode media. Keeping
    # the source tiny makes the contract tests independent of codecs and models.
    source = tmp_path / "source.mp4"
    source.write_bytes(b"review-contract-source")
    data = tmp_path / "processed"
    store = Store(data)
    video = {
        "id": "review-video",
        "mode": "singles",
        "path": source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "frame_count": 12,
        "duration_s": 0.72,
        "width": 640,
        "height": 360,
        "source_start_s": 0,
    }
    times = [0, 0.04, 0.1, 0.14, 0.2, 0.24, 0.32, 0.36, 0.44, 0.48, 0.6, 0.64]
    for video_id in (video["id"], "other-video"):
        store.register(video | {"id": video_id})
        write_json(data / video_id / "timestamps.json", times)
    return SimpleNamespace(
        root=tmp_path, data=data, store=store, video=video, times=times
    )


def add_run(
    ctx, run_id="players-1", kind="players", *, job_video=None, status="completed"
):
    video_id = job_video or ctx.video["id"]
    run = {
        "video_id": video_id,
        "stage": kind,
        "start_frame": 0,
        "end_frame": 12,
    }
    if kind == "players":
        run["frames"] = [
            {
                "frame": frame,
                "time_s": ctx.times[frame],
                "players": [
                    {"track_id": track, "player_id": None, "box": [10, 20, 30, 40]}
                ],
            }
            for frame, track in ((2, 7), (4, 7), (6, 8), (8, 8))
        ]
    elif kind == "shuttle":
        run["frames"] = [
            {
                "frame": 4,
                "time_s": ctx.times[4],
                "shuttle": {"visible": True, "x": 320, "y": 180},
            }
        ]
    elif kind == "contacts":
        run |= {
            "player_run_id": "players-1",
            "shuttle_run_id": "shuttle-1",
            "candidates": [
                {
                    "id": f"contact-{frame}",
                    "frame": frame,
                    "time_s": ctx.times[frame],
                    "track_id": track,
                    "player_id": None,
                }
                for frame, track in ((4, 7), (6, 7), (8, 8))
            ],
        }
    path = ctx.data / video_id / "runs" / f"{run_id}.json"
    write_json(path, run)
    ctx.store.put_job(
        {
            "id": run_id,
            "video_id": video_id,
            "kind": kind,
            "status": status,
            "progress": 1,
        }
    )
    return path, run


def assignment(**changes):
    return {
        "run_id": "players-1",
        "track_id": 7,
        "start_frame": 2,
        "end_frame": 6,
        "player_id": "A",
    } | changes


def window(**changes):
    return {
        "id": "window-1",
        "start_frame": 0,
        "end_frame": 12,
        "scene": "live",
        "contacts_complete": False,
    } | changes


def test_review_windows_allow_touching_ranges_and_reject_overlap_duplicate_ids():
    doc = empty_annotations("singles").model_dump()
    doc["review_windows"] = [window(end_frame=6), window(id="window-2", start_frame=6)]
    assert len(Annotations.model_validate(doc).review_windows) == 2
    doc["review_windows"][1]["start_frame"] = 5
    with pytest.raises(ValidationError, match="must not overlap"):
        Annotations.model_validate(doc)
    doc["review_windows"][1] = window(start_frame=6)
    with pytest.raises(ValidationError, match="IDs must be unique"):
        Annotations.model_validate(doc)


@pytest.mark.parametrize("start,end", [(-1, 4), (4, 4), (5, 4), (0, 13)])
def test_review_window_range_is_validated_against_source(review_workspace, start, end):
    ctx = review_workspace
    doc = ctx.store.annotations(ctx.video["id"]).model_dump()
    doc["review_windows"] = [window(start_frame=start, end_frame=end)]
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.put(f"/api/videos/{ctx.video['id']}/annotations", json=doc)
    assert response.status_code == 422
    assert ctx.store.annotations(ctx.video["id"]).revision == 0


@pytest.mark.parametrize(
    "point",
    [
        {"frame": 4, "visible": True},
        {"frame": 4, "visible": True, "x": 0.5},
        {"frame": 4, "visible": False, "x": 0.5, "y": 0.5},
        {"frame": 4, "visible": True, "x": -0.01, "y": 0.5},
        {"frame": 4, "visible": True, "x": 0.5, "y": 1.01},
        {"frame": -1, "visible": False},
    ],
)
def test_shuttle_label_contract_rejects_ambiguous_positions(point):
    with pytest.raises(ValidationError):
        ShuttlePoint.model_validate(point)


def test_shuttle_labels_preserve_edges_and_explicit_absence():
    assert ShuttlePoint(frame=0, visible=True, x=0, y=1).model_dump() == {
        "frame": 0,
        "visible": True,
        "x": 0,
        "y": 1,
        "notes": "",
    }
    assert ShuttlePoint(frame=1, visible=False).x is None
    doc = empty_annotations("singles").model_dump()
    doc["shuttle_points"] = [{"frame": 4, "visible": False}] * 2
    with pytest.raises(ValidationError, match="Only one shuttle label"):
        Annotations.model_validate(doc)


def test_shuttle_label_source_bounds_are_enforced(review_workspace):
    ctx = review_workspace
    doc = ctx.store.annotations(ctx.video["id"]).model_dump()
    doc["shuttle_points"] = [{"frame": 12, "visible": False}]
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.put(f"/api/videos/{ctx.video['id']}/annotations", json=doc)
    assert response.status_code == 422
    assert "exceeds the video" in response.text


@pytest.mark.parametrize(
    "case",
    [
        "missing_job",
        "wrong_kind",
        "unfinished",
        "other_video_job",
        "missing_artifact",
        "wrong_artifact_video",
        "wrong_artifact_stage",
        "before_run",
        "after_run",
        "outside_source",
        "missing_tracker",
        "tracker_absent_in_range",
    ],
)
def test_assignments_require_usable_same_video_player_artifact(review_workspace, case):
    ctx = review_workspace
    mapping = assignment()
    if case != "missing_job":
        kind = "shuttle" if case == "wrong_kind" else "players"
        job_video = "other-video" if case == "other_video_job" else None
        status = "failed" if case == "unfinished" else "completed"
        path, run = add_run(ctx, kind=kind, job_video=job_video, status=status)
        if case == "missing_artifact":
            path.unlink()
        elif case in ("wrong_artifact_video", "wrong_artifact_stage"):
            field = "video_id" if case == "wrong_artifact_video" else "stage"
            run[field] = "other-video" if field == "video_id" else "shuttle"
            write_json(path, run)
        elif case == "before_run":
            run["start_frame"] = 3
            write_json(path, run)
        elif case == "after_run":
            run["end_frame"] = 5
            write_json(path, run)
        elif case == "outside_source":
            mapping["end_frame"] = 13
        elif case == "missing_tracker":
            mapping["track_id"] = 99
        elif case == "tracker_absent_in_range":
            mapping |= {"start_frame": 6, "end_frame": 9}
    doc = ctx.store.annotations(ctx.video["id"]).model_dump()
    doc["track_assignments"] = [mapping]
    with TestClient(
        create_app(ctx.root, ctx.data), raise_server_exceptions=False
    ) as client:
        response = client.put(f"/api/videos/{ctx.video['id']}/annotations", json=doc)
    assert response.status_code == 422, (case, response.status_code, response.text)
    assert ctx.store.annotations(ctx.video["id"]).revision == 0


def test_assignment_schema_rejects_simultaneous_tracks_for_one_player():
    doc = empty_annotations("singles").model_dump()
    doc["track_assignments"] = [assignment(), assignment(track_id=8)]
    with pytest.raises(ValidationError, match="overlapping tracks"):
        Annotations.model_validate(doc)
    doc["track_assignments"] = [assignment(player_id="unrecognized")]
    with pytest.raises(ValidationError, match="Unknown player"):
        Annotations.model_validate(doc)


def test_applied_player_and_contact_views_follow_current_review_without_mutating_runs(
    review_workspace,
):
    ctx = review_workspace
    player_path, raw_players = add_run(ctx)
    contact_path, raw_contacts = add_run(ctx, "contacts-1", "contacts")
    initial_player_bytes, initial_contact_bytes = (
        player_path.read_bytes(),
        contact_path.read_bytes(),
    )
    url = f"/api/videos/{ctx.video['id']}"
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        doc = client.get(url + "/annotations").json()
        doc["track_assignments"] = [assignment()]
        response = client.put(url + "/annotations", json=doc)
        assert response.status_code == 200, response.text
        players = client.get(url + "/runs/players-1").json()
        assert [row["players"][0]["player_id"] for row in players["frames"]] == [
            "A",
            "A",
            None,
            None,
        ]
        assert players["identity_annotation_revision"] == 1
        contacts = client.get(url + "/runs/contacts-1").json()
        assert [item["player_id"] for item in contacts["candidates"]] == [
            "A",
            None,
            None,
        ]
        assert contacts["identity_annotation_revision"] == 1
        doc = response.json()
        doc["track_assignments"] = [assignment(player_id="B")]
        assert client.put(url + "/annotations", json=doc).status_code == 200
        contacts = client.get(url + "/runs/contacts-1").json()
        assert contacts["candidates"][0]["player_id"] == "B"
        assert contacts["identity_annotation_revision"] == 2
    assert player_path.read_bytes() == initial_player_bytes
    assert contact_path.read_bytes() == initial_contact_bytes
    assert json.loads(player_path.read_text()) == raw_players
    assert json.loads(contact_path.read_text()) == raw_contacts


def test_revision_history_and_export_preserve_review_labels_and_mappings(
    review_workspace,
):
    ctx = review_workspace
    add_run(ctx)
    url = f"/api/videos/{ctx.video['id']}"
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        doc = client.get(url + "/annotations").json()
        doc["review_windows"] = [
            window(contacts_complete=True, notes="Exhaustive live review")
        ]
        doc["shuttle_points"] = [
            {"frame": 4, "visible": True, "x": 0.5, "y": 0.5},
            {"frame": 5, "visible": False},
        ]
        doc["track_assignments"] = [assignment()]
        response = client.put(url + "/annotations", json=doc)
        assert response.status_code == 200, response.text
        first = response.json()
        next_doc = deepcopy(first)
        next_doc["shuttle_points"][0]["x"] = 0.6
        assert client.put(url + "/annotations", json=next_doc).status_code == 200
        assert client.put(url + "/annotations", json=first).status_code == 409
        historical = client.get(url + "/revisions/1").json()
        for field in ("review_windows", "shuttle_points", "track_assignments"):
            assert historical[field] == first[field]
        initial = client.get(url + "/revisions/0").json()
        assert all(
            initial[field] == []
            for field in ("review_windows", "shuttle_points", "track_assignments")
        )
        exported = client.get(url + "/export").json()["annotations"]
        assert exported["revision"] == 2 and exported["shuttle_points"][0]["x"] == 0.6
        assert exported["review_windows"] == first["review_windows"]
        assert exported["track_assignments"] == first["track_assignments"]


def test_evaluation_requires_a_run_and_recognizes_unlabeled_data(review_workspace):
    ctx = review_workspace
    add_run(ctx, "contacts-1", "contacts")
    add_run(ctx, "shuttle-1", "shuttle")
    url = f"/api/videos/{ctx.video['id']}/evaluate"
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        assert client.post(url, json={}).status_code == 422
        response = client.post(
            url, json={"contacts_run_id": "contacts-1", "shuttle_run_id": "shuttle-1"}
        )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["annotation_revision"] == 0
    assert result["contacts"]["status"] == "needs_complete_live_review"
    assert result["contacts"]["metrics"] is None
    assert result["contacts"]["coverage"]["reviewed_contacts"] == 0
    assert result["shuttle"]["status"] == "needs_shuttle_labels"
    assert result["shuttle"]["metrics"] is None


@pytest.mark.parametrize(
    "case",
    [
        "missing_job",
        "wrong_kind",
        "missing_artifact",
        "wrong_artifact_stage",
        "wrong_artifact_video",
    ],
)
def test_evaluation_rejects_missing_or_mismatched_contact_artifact(
    review_workspace, case
):
    ctx = review_workspace
    if case != "missing_job":
        path, run = add_run(
            ctx, "contacts-1", "players" if case == "wrong_kind" else "contacts"
        )
        if case == "missing_artifact":
            path.unlink()
        elif case.startswith("wrong_artifact"):
            field = "stage" if case.endswith("stage") else "video_id"
            run[field] = "shuttle" if field == "stage" else "other-video"
            write_json(path, run)
    with TestClient(
        create_app(ctx.root, ctx.data), raise_server_exceptions=False
    ) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={"contacts_run_id": "contacts-1"},
        )
    expected = 422 if case.startswith("wrong_artifact") else 404
    assert response.status_code == expected, (case, response.status_code, response.text)


@pytest.mark.parametrize(
    "scene,complete", [("live", False), ("unknown", True), ("replay", True)]
)
def test_incomplete_or_nonlive_coverage_cannot_generate_contact_accuracy(
    review_workspace, scene, complete
):
    ctx = review_workspace
    add_run(ctx, "contacts-1", "contacts")
    doc = ctx.store.annotations(ctx.video["id"]).model_dump()
    doc["review_windows"] = [window(scene=scene, contacts_complete=complete)]
    doc["events"] = [
        {
            "id": "shot-4",
            "rally_id": "r1",
            "kind": "shot",
            "frame": 4,
            "family": "unknown",
            "side": "unknown",
        }
    ]
    ctx.store.save_annotations(ctx.video["id"], Annotations.model_validate(doc))
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={"contacts_run_id": "contacts-1"},
        )
    assert response.status_code == 200, response.text
    result = response.json()["contacts"]
    assert result["metrics"] is None
    assert result["coverage"]["reviewed_frames"] == 0
    assert result["coverage"]["excluded_reviewed_contacts"] == 1


def test_complete_live_review_uses_saved_source_times_and_visible_shuttle_labels(
    review_workspace,
):
    ctx = review_workspace
    add_run(ctx, "contacts-1", "contacts")
    add_run(ctx, "shuttle-1", "shuttle")
    doc = ctx.store.annotations(ctx.video["id"]).model_dump()
    doc["review_windows"] = [window(contacts_complete=True)]
    doc["events"] = [
        {
            "id": "shot-4",
            "rally_id": "r1",
            "kind": "shot",
            "frame": 4,
            "time_s": 100,
            "family": "clear",
            "side": "forehand",
        }
    ]
    doc["shuttle_points"] = [{"frame": 4, "visible": True, "x": 0.5, "y": 0.5}]
    saved = ctx.store.save_annotations(ctx.video["id"], Annotations.model_validate(doc))
    assert saved.events[0].time_s == ctx.times[4]
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={
                "contacts_run_id": "contacts-1",
                "shuttle_run_id": "shuttle-1",
                "tolerance_s": 0.01,
            },
        )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["contacts"]["metrics"] == {
        "tp": 1,
        "fp": 2,
        "fn": 0,
        "precision": 1 / 3,
        "recall": 1,
        "f1": 0.5,
    }
    assert result["contacts"]["matches"][0]["event_time_s"] == ctx.times[4]
    assert result["shuttle"]["metrics"]["tp"] == 1
    assert result["shuttle"]["metrics"]["fn"] == 0
