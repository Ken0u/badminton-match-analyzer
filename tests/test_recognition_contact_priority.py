"""Reviewed contact uncertainty has priority over competing model hypotheses."""

import copy
import hashlib
import json
import sys

import pytest
from badminton.recognition import recognition_targets
from badminton.schemas import Annotations, empty_annotations
from badminton.video import write_json
from fastapi.testclient import TestClient
from test_recognition_api import catalog as catalog
from test_recognition_api import wait


def saved_shot(mode="singles", status="reviewed"):
    doc = empty_annotations(mode).model_dump()
    doc["events"] = [
        {
            "id": "saved",
            "rally_id": "r1",
            "kind": "shot",
            "frame": 30,
            "family": "unknown",
            "side": "unknown",
            "status": status,
            "contact_start_frame": 28,
            "contact_end_frame": 34,
        }
    ]
    return Annotations.model_validate(doc)


def proposal(left, right, frame):
    return {
        "id": "candidate",
        "frame": frame,
        "start_frame": left,
        "end_frame": right,
        "timing": "uncertain_interval",
    }


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize("status", ["reviewed", "corrected"])
@pytest.mark.parametrize(
    "candidate",
    [
        proposal(26, 28, 26),
        proposal(34, 36, 36),
        proposal(26, 29, 26),
        proposal(33, 36, 36),
        proposal(31, 32, 31),
        proposal(26, 36, 33),
        proposal(28, 28, 28),
        proposal(34, 34, 34),
        {"id": "candidate", "frame": 28},
        {"id": "candidate", "frame": 34},
    ],
)
def test_saved_uncertain_shot_has_priority_without_changing_either_input(
    mode, status, candidate
):
    annotations = saved_shot(mode, status)
    run = {"candidates": [copy.deepcopy(candidate)]}
    before = copy.deepcopy((annotations, run))
    targets = recognition_targets(annotations, run)
    assert [
        (t["frame"], t["event_id"], t["contact_candidate_id"]) for t in targets
    ] == [(30, "saved", None)]
    assert targets[0]["contact_start_frame"] == 28
    assert targets[0]["contact_end_frame"] == 34
    assert (annotations, run) == before


@pytest.mark.parametrize("candidate", [proposal(26, 27, 26), proposal(35, 36, 36)])
def test_adjacent_disjoint_proposal_keeps_its_original_target_and_id(candidate):
    annotations = saved_shot()
    isolated = recognition_targets(
        empty_annotations("singles"), {"candidates": [candidate]}
    )
    targets = recognition_targets(annotations, {"candidates": [candidate]})
    assert len(targets) == 2
    assert next(t for t in targets if t["contact_candidate_id"]) == isolated[0]
    assert [t["frame"] for t in targets] == sorted([30, candidate["frame"]])


def test_reviewed_navigation_frame_outside_window_still_reserves_possible_contact():
    run = {"candidates": [proposal(34, 36, 34), {"id": "disjoint", "frame": 38}]}
    targets = recognition_targets(saved_shot(), run, start_frame=32, end_frame=40)
    assert [(t["event_id"], t["contact_candidate_id"]) for t in targets] == [
        (None, "disjoint")
    ]


def test_two_saved_shots_are_never_collapsed_by_their_overlapping_uncertainty():
    doc = saved_shot().model_dump()
    doc["events"].append(
        doc["events"][0]
        | {"id": "another-saved", "frame": 32, "contact_start_frame": 31}
    )
    targets = recognition_targets(
        Annotations.model_validate(doc), {"candidates": [proposal(34, 36, 36)]}
    )
    assert [(t["frame"], t["event_id"]) for t in targets] == [
        (30, "saved"),
        (32, "another-saved"),
    ]


@pytest.mark.parametrize("with_uncertainty", [False, True])
def test_legacy_and_explicit_reviewed_points_keep_existing_priority(with_uncertainty):
    doc = saved_shot().model_dump()
    for key in ("contact_start_frame", "contact_end_frame"):
        doc["events"][0][key] = 30 if with_uncertainty else None
    targets = recognition_targets(
        Annotations.model_validate(doc),
        {"candidates": [proposal(29, 31, 31), {"id": "next-frame", "frame": 32}]},
    )
    assert [(t["event_id"], t["contact_candidate_id"]) for t in targets] == [
        ("saved", None),
        (None, "next-frame"),
    ]


@pytest.mark.parametrize("control", ["disabled", "predicted", "serve", "rally_end"])
def test_disabled_review_predicted_labels_and_other_event_kinds_keep_existing_behavior(
    control,
):
    doc = saved_shot().model_dump()
    event = doc["events"][0]
    if control == "predicted":
        event["status"] = "predicted"
    if control in ("serve", "rally_end"):
        event.update(kind=control, family=None, side=None)
        if control == "rally_end":
            event.update(contact_start_frame=None, contact_end_frame=None)
    candidate = proposal(34, 36, 36)
    expected = recognition_targets(
        empty_annotations("singles"), {"candidates": [candidate]}
    )
    actual = recognition_targets(
        Annotations.model_validate(doc),
        {"candidates": [candidate]},
        include_reviewed=control != "disabled",
    )
    assert actual == expected


def test_scene_exclusions_and_disjoint_proposal_order_are_preserved():
    doc = saved_shot().model_dump()
    doc["scene_ranges"] = [
        {"id": "replay", "start_frame": 28, "end_frame": 37, "scene": "replay"}
    ]
    targets = recognition_targets(
        Annotations.model_validate(doc),
        {
            "candidates": [
                {"id": "later", "frame": 50},
                proposal(34, 36, 36),
                {"id": "earlier", "frame": 40},
            ]
        },
    )
    assert [(t["frame"], t["contact_candidate_id"]) for t in targets] == [
        (40, "earlier"),
        (50, "later"),
    ]


@pytest.mark.parametrize("entrypoint", ["api", "cli"])
def test_saved_api_and_cli_select_one_reviewed_target_and_preserve_source_artifacts(
    catalog, entrypoint, monkeypatch, capsys
):
    from badminton import cli, recognition
    from badminton.api import create_app

    root, data, store, video = catalog
    contacts_path = data / video["id"] / "runs" / "contacts.json"
    contacts = json.loads(contacts_path.read_bytes())
    contacts["candidates"] = [
        proposal(34, 35, 35),
        {"id": "disjoint", "frame": 60},
    ]
    write_json(contacts_path, contacts)
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
        calls.append(copy.deepcopy(targets))
        assert times[30] == 1.2
        assert annotations.revision == 1
        result = {
            "stage": "recognition",
            "video_id": v["id"],
            "video_sha256": v["sha256"],
            "annotation_revision": annotations.revision,
            "player_run_id": player_id,
            "shuttle_run_id": "shuttle",
            "contacts_run_id": contacts_run_id,
            "start_frame": 0,
            "end_frame": 100,
            "candidates": [
                t | {"status": "abstained", "reason": "Generated orchestration only"}
                for t in targets
            ],
        }
        write_json(output, result)
        progress(1)
        return {k: v for k, v in result.items() if k != "candidates"}

    monkeypatch.setattr(recognition, "recognize_strokes", infer)
    url = f"/api/videos/{video['id']}"
    with TestClient(create_app(root, data)) as client:
        response = client.put(url + "/annotations", json=saved_shot().model_dump())
        assert response.status_code == 200, response.text
        saved = response.json()
        original_paths = [root / video["path"], *(data / video["id"]).rglob("*.json")]
        original_hashes = {
            p: hashlib.sha256(p.read_bytes()).hexdigest() for p in original_paths
        }
        if entrypoint == "api":
            response = client.post(
                url + "/recognize",
                json={
                    "player_run_id": "players",
                    "shuttle_run_id": "shuttle",
                    "contacts_run_id": "contacts",
                },
            )
            assert response.status_code == 202, response.text
            job_id = response.json()["id"]
            assert wait(store, job_id)["status"] == "completed"
        else:
            monkeypatch.setattr(cli, "ROOT", root)
            monkeypatch.setattr(cli, "DATA", data)
            monkeypatch.setattr(
                sys,
                "argv",
                [
                    "badminton",
                    "recognize",
                    video["id"],
                    "--players-run",
                    "players",
                    "--shuttle-run",
                    "shuttle",
                    "--contacts-run",
                    "contacts",
                ],
            )
            cli.main()
            summary = json.loads(capsys.readouterr().out)
            assert summary["annotation_revision"] == 1
            completed = [j for j in store.jobs() if j["kind"] == "recognition"]
            assert len(completed) == 1 and completed[0]["status"] == "completed"
            job_id = completed[0]["id"]
        artifact = client.get(url + f"/runs/{job_id}")
        assert artifact.status_code == 200, artifact.text
        assert len(calls) == 1
        assert [
            (t["frame"], t["event_id"], t["contact_candidate_id"]) for t in calls[0]
        ] == [
            (30, "saved", None),
            (60, None, "disjoint"),
        ]
        assert artifact.json()["candidates"] == [
            t | {"status": "abstained", "reason": "Generated orchestration only"}
            for t in calls[0]
        ]
        assert store.annotations(video["id"]).model_dump() == saved
        assert {
            p: hashlib.sha256(p.read_bytes()).hexdigest() for p in original_paths
        } == original_hashes
