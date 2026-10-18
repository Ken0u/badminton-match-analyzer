import copy
import hashlib

import pytest
from badminton.api import create_app
from badminton.contacts import propose_contacts
from badminton.evaluation import evaluate_contacts
from badminton.recognition import recognition_targets
from badminton.scene_review import corrected_boundaries, reviewed_contacts, reviewed_run
from badminton.schemas import Annotations, empty_annotations
from badminton.storage import Store
from badminton.video import write_json
from fastapi.testclient import TestClient
from pydantic import ValidationError


def test_component_selection_dependency_is_masked_without_rewriting_raw_points():
    from badminton.contacts import _raw_visible
    from badminton.rallies import _point

    doc = empty_annotations("singles").model_dump()
    run = {
        "stage": "shuttle",
        "start_frame": 0,
        "end_frame": 10,
        "frames": [
            {
                "frame": 6,
                "time_s": 0.24,
                "shuttle": {
                    "visible": True,
                    "x": 100,
                    "y": 120,
                    "selection_context_start_frame": 1,
                    "selection_context_end_frame": 7,
                },
            }
        ],
    }
    before = copy.deepcopy(run)
    doc["scene_ranges"] = [scene(1, 2)]
    masked = reviewed_run(run, doc)
    point = masked["frames"][0]
    assert point["shuttle"]["visible"] and point["shuttle"]["x"] == 100
    assert point["shuttle"]["selection_context_excluded"]
    assert not _raw_visible(point) and _point(point) is None
    assert run == before
    doc["scene_ranges"] = []
    assert not reviewed_run(masked, doc)["frames"][0]["shuttle"][
        "selection_context_excluded"
    ]


def scene(start=20, end=30, kind="replay"):
    return {
        "id": "scene-test",
        "start_frame": start,
        "end_frame": end,
        "scene": kind,
        "notes": "independent QA fixture",
    }


def test_scene_edit_invalidates_remote_identity_evidence_without_changing_raw_data():
    from badminton.calibration_context import court_context_changed, court_run_context
    from badminton.identity import apply_assignments
    from badminton.schemas import TrackAssignment

    doc = empty_annotations("singles").model_dump()
    raw = {
        "stage": "players",
        "start_frame": 0,
        "end_frame": 100,
        "cut_frames": [],
        "preceding_reviewed_cut_frame": None,
        "uses_motion_continuity": True,
        "continuity_scene_signature": [],
        "track_continuity": {
            "links": [{"left": 1, "right": 3}],
            "scene_signature": [],
            "status": "completed",
        },
        "frames": [
            {
                "frame": 75,
                "time_s": 3,
                "players": [
                    {
                        "track_id": 1,
                        "baseline_track_id": 3,
                        "player_id": "A",
                        "box": [10, 10, 20, 30],
                    }
                ],
            }
        ],
    }
    original = copy.deepcopy(raw)
    assert not reviewed_run(raw, doc)["requires_continuity_rerun"]
    doc["scene_ranges"] = [scene(20, 21)]
    changed = reviewed_run(raw, doc)
    assert changed["requires_tracking_rerun"] and changed["requires_continuity_rerun"]
    assert changed["track_continuity"]["status"] == "stale_context"
    assert changed["frames"][0]["players"][0]["track_id"] == 3
    assert changed["frames"][0]["players"][0]["player_id"] is None
    assignment = TrackAssignment(
        run_id="r", track_id=3, player_id="B", start_frame=70, end_frame=80
    )
    mapped = apply_assignments(changed, [assignment], "r")
    assert mapped["frames"][0]["players"][0]["player_id"] == "B"
    dependent = {"court_context": court_run_context(raw)}
    assert court_context_changed(doc, dependent)
    assert reviewed_contacts(dependent | {"candidates": []}, doc)[
        "requires_context_rerun"
    ]
    assert raw == original
    doc["scene_ranges"] = [scene(101, 102)]
    assert not reviewed_run(raw, doc)["requires_continuity_rerun"]


@pytest.mark.parametrize(
    "changes",
    [
        {"camera_corrections": [{"frame": 0, "is_cut": True}]},
        {
            "camera_corrections": [
                {"frame": 20, "is_cut": True},
                {"frame": 20, "is_cut": False},
            ]
        },
        {"scene_ranges": [scene(), scene(29, 35)]},
        {"scene_ranges": [scene(30, 20)]},
        {"scene_ranges": [scene(20, 30, "bad-scene")]},
    ],
)
def test_scene_schema_rejects_ambiguous_corrections_and_ranges(changes):
    with pytest.raises(ValidationError):
        Annotations.model_validate(empty_annotations("singles").model_dump() | changes)


def test_corrections_preserve_raw_cuts_and_never_join_physical_timestamp_gaps():
    raw = {
        "cut_frames": [20, 40, 70],
        "boundaries": [{"frame": 70, "reason": "timestamp_discontinuity"}],
    }
    doc = {
        "revision": 4,
        "camera_corrections": [
            {"frame": 20, "is_cut": False},
            {"frame": 30, "is_cut": True},
            {"frame": 70, "is_cut": False},
        ],
    }
    original = copy.deepcopy(raw)
    result = corrected_boundaries(raw, doc, 0, 100)
    assert raw == original
    assert result["cut_frames"] == [30, 40, 70]
    assert result["raw_cut_frames"] == [20, 40, 70]
    assert result["camera_annotation_revision"] == 4


def test_scene_changes_are_reversible_views_and_changed_camera_context_is_stale():
    raw = {
        "stage": "shuttle",
        "start_frame": 10,
        "end_frame": 60,
        "cut_frames": [20],
        "frames": [
            {"frame": i, "time_s": i * 0.04, "shuttle": {"visible": False}}
            for i in range(10, 60)
        ],
    }
    original = copy.deepcopy(raw)
    reviewed = reviewed_run(raw, {"scene_ranges": [scene()]})
    assert all(
        r.get("scene") == "replay" for r in reviewed["frames"] if 20 <= r["frame"] < 30
    )
    assert reviewed["requires_tracking_rerun"] is False
    restored = reviewed_run(reviewed, {})
    assert all("scene" not in row for row in restored["frames"])
    assert raw == original
    doc = {"camera_corrections": [{"frame": 30, "is_cut": True}]}
    changed = reviewed_run(raw, doc)
    assert changed["requires_tracking_rerun"] is True
    assert reviewed_run(changed, doc)["requires_tracking_rerun"] is True
    assert reviewed_run(changed, {})["requires_tracking_rerun"] is True
    preceding = reviewed_run(
        raw, {"camera_corrections": [{"frame": 5, "is_cut": True}]}
    )
    assert preceding["preceding_reviewed_cut_frame"] == 5
    assert preceding["requires_tracking_rerun"] is True


def test_removing_review_restores_original_scene_evidence():
    raw = {
        "start_frame": 0,
        "end_frame": 10,
        "frames": [{"frame": 5, "scene": "replay"}],
    }
    reviewed = reviewed_run(raw, {"scene_ranges": [scene(0, 10, "live")]})
    assert reviewed["frames"][0]["scene"] == "live"
    restored = reviewed_run(reviewed, {})
    assert restored["frames"][0] == {"frame": 5, "scene": "replay"}


@pytest.mark.parametrize("kind", ["replay", "non_play", "unknown"])
def test_reviewed_nonlive_context_cannot_create_contact_proposals(kind):
    rows = []
    for i in range(25):
        rows.append(
            {
                "frame": i,
                "time_s": i * 0.04,
                "shuttle": {
                    "visible": True,
                    "x": 300 + 200 * abs(i * 0.04 - 0.48),
                    "y": 200,
                },
            }
        )
    shuttle = {"stage": "shuttle", "start_frame": 0, "end_frame": 25, "frames": rows}
    players = {
        "frames": [
            {
                "frame": i,
                "time_s": i * 0.04,
                "players": [
                    {"track_id": 1, "box": [280, 180, 380, 320], "keypoints": []}
                ],
            }
            for i in range(25)
        ]
    }
    video = {"width": 640, "height": 360}
    assert len(propose_contacts(shuttle, players, video)) == 1
    filtered = reviewed_run(shuttle, {"scene_ranges": [scene(9, 16, kind)]})
    assert propose_contacts(filtered, players, video) == []
    assert len(propose_contacts(shuttle, players, video)) == 1


def test_existing_contacts_are_flagged_without_deletion_or_source_mutation():
    raw = {
        "candidates": [
            {"id": "a", "frame": 30, "start_frame": 28, "end_frame": 32},
            {"id": "b", "frame": 50},
        ]
    }
    doc = {"revision": 2, "scene_ranges": [scene(20, 30)]}
    original = copy.deepcopy(raw)
    result = reviewed_contacts(raw, doc)
    assert raw == original and len(result["candidates"]) == 2
    assert result["candidates"][0]["scene_excluded"] is True
    assert result["candidates"][1]["scene_excluded"] is False


def test_contact_scene_review_checks_evidence_outside_its_navigation_interval():
    raw = {
        "candidates": [
            {
                "id": "profile",
                "frame": 30,
                "start_frame": 29,
                "end_frame": 31,
                "context_start_frame": 26,
                "context_end_frame": 35,
            }
        ]
    }
    before = copy.deepcopy(raw)
    result = reviewed_contacts(raw, {"scene_ranges": [scene(26, 28)]})
    assert result["candidates"][0]["scene_excluded"] is True
    assert raw == before
    assert (
        reviewed_contacts(raw, {"scene_ranges": [scene(35, 40)]})["candidates"][0][
            "scene_excluded"
        ]
        is False
    )


def test_legacy_motion_candidate_gets_a_conservative_review_context_without_rewrite():
    raw = {
        "start_frame": 20,
        "end_frame": 40,
        "candidates": [
            {"id": "old", "frame": 30, "evidence_source": "observed_trajectory"}
        ],
    }
    before = copy.deepcopy(raw)
    result = reviewed_contacts(raw, {"scene_ranges": [scene(27, 29)]})
    candidate = result["candidates"][0]
    assert candidate["scene_excluded"] is True
    assert (
        candidate["context_start_frame"] == 27 and candidate["context_end_frame"] == 34
    )
    assert candidate["context_provenance"] == "conservative_legacy_window"
    assert raw == before


def test_context_mask_blocks_recognition_and_counts_a_live_contact_as_missed():
    doc = empty_annotations("singles").model_dump()
    doc["scene_ranges"] = [scene(44, 46)]
    doc["events"] = [
        {
            "id": "truth",
            "rally_id": "R",
            "kind": "shot",
            "family": "unknown",
            "side": "unknown",
            "frame": 50,
            "time_s": 2,
            "status": "reviewed",
        }
    ]
    doc["review_windows"] = [
        {
            "id": "live",
            "start_frame": 48,
            "end_frame": 60,
            "scene": "live",
            "contacts_complete": True,
        }
    ]
    run = {
        "video_id": "v",
        "stage": "contacts",
        "start_frame": 0,
        "end_frame": 100,
        "candidates": [
            {
                "id": "cached",
                "frame": 50,
                "time_s": 2,
                "start_frame": 50,
                "end_frame": 50,
                "context_start_frame": 44,
                "context_end_frame": 55,
            }
        ],
    }
    before = copy.deepcopy(run)
    assert (
        recognition_targets(
            Annotations.model_validate(doc), run, include_reviewed=False
        )
        == []
    )
    # Independently reviewed events remain valid; predicted context is separate.
    assert len(recognition_targets(Annotations.model_validate(doc), run)) == 1
    report = evaluate_contacts(
        {"id": "v", "sha256": "a" * 64, "frame_count": 100}, doc, run
    )
    assert report["metrics"]["tp"] == 0 and report["metrics"]["fn"] == 1
    assert report["coverage"]["scene_context_excluded_candidate_ids"] == ["cached"]
    assert run == before


def test_recognition_targets_and_strict_metrics_honor_scene_exclusions():
    doc = empty_annotations("singles").model_dump()
    doc["events"] = [
        {
            "id": "shot",
            "rally_id": "r",
            "kind": "shot",
            "status": "reviewed",
            "frame": 6,
            "player_id": None,
            "family": "unknown",
            "side": "unknown",
            "time_s": 0.24,
        }
    ]
    doc["scene_ranges"] = [scene(0, 10)]
    assert recognition_targets(Annotations.model_validate(doc)) == []
    doc["review_windows"] = [
        {
            "id": "w",
            "start_frame": 0,
            "end_frame": 20,
            "contacts_complete": True,
            "scene": "live",
        }
    ]
    video = {"id": "v", "sha256": "a" * 64, "frame_count": 100}
    run = {
        "video_id": "v",
        "stage": "contacts",
        "start_frame": 0,
        "end_frame": 100,
        "candidates": [{"id": "c", "frame": 6, "time_s": 0.24}],
    }
    report = evaluate_contacts(video, doc, run)
    assert report["metrics"] is None
    assert report["coverage"]["skipped_windows"] == [
        {"id": "w", "reason": "reviewed_scene_excludes_window"}
    ]


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.delenv("BADMINTON_USERNAME", raising=False)
    monkeypatch.delenv("BADMINTON_PASSWORD", raising=False)
    path = tmp_path / "fixture.mp4"
    path.write_bytes(b"source fixture; perception artifacts provided separately")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    v = {
        "id": sha[:16],
        "sha256": sha,
        "path": path.name,
        "name": "fixture",
        "mode": "singles",
        "frame_count": 100,
        "fps": 25,
        "duration_s": 4,
        "width": 640,
        "height": 360,
    }
    data = tmp_path / "data"
    store = Store(data)
    store.register(v)
    write_json(
        data / v["id"] / "timestamps.json",
        [i * 0.04 + (0.4 if i >= 50 else 0) for i in range(100)],
    )
    for stage in ("players", "shuttle"):
        write_json(
            data / v["id"] / "runs" / f"{stage}.json",
            {
                "video_id": v["id"],
                "stage": stage,
                "start_frame": 0,
                "end_frame": 100,
                "frames": [],
            },
        )
        store.put_job(
            {"id": stage, "kind": stage, "video_id": v["id"], "status": "completed"}
        )
    return tmp_path, data, store, v


def test_api_preserves_revision_history_and_rejects_unsafe_ranges(catalog):
    root, data, store, v = catalog
    base = f"/api/videos/{v['id']}"
    with TestClient(create_app(root, data)) as client:
        original = client.get(base + "/annotations").json()
        assert original["scene_ranges"] == [] and original["camera_corrections"] == []
        draft = original | {
            "scene_ranges": [scene()],
            "camera_corrections": [{"frame": 20, "is_cut": True, "notes": "QA"}],
        }
        saved = client.put(base + "/annotations", json=draft)
        assert saved.status_code == 200, saved.text
        assert saved.json()["revision"] == 1
        assert client.get(base + "/export").json()["annotations"]["scene_ranges"] == [
            scene()
        ]
        assert store.annotations(v["id"], 0).scene_ranges == []
        assert client.put(base + "/annotations", json=draft).status_code == 409
        # Changed camera handling invalidates old cached tracking for inference.
        response = client.post(
            base + "/contacts",
            json={"shuttle_run_id": "shuttle", "player_run_id": "players"},
        )
        assert response.status_code == 422 and "rerun tracking" in response.text
        for changes in (
            {"scene_ranges": [scene(90, 101)]},
            {"camera_corrections": [{"frame": 100, "is_cut": True}]},
            {"camera_corrections": [{"frame": 50, "is_cut": False}]},
        ):
            response = client.put(base + "/annotations", json=saved.json() | changes)
            assert response.status_code == 422, response.text
        assert store.annotations(v["id"]).revision == 1


def test_api_restores_baseline_before_applying_reviewed_names_after_scene_edit(catalog):
    root, data, store, video = catalog
    path = data / video["id"] / "runs/players.json"
    raw = {
        "video_id": video["id"],
        "stage": "players",
        "start_frame": 0,
        "end_frame": 100,
        "cut_frames": [],
        "preceding_reviewed_cut_frame": None,
        "track_continuity": {"links": [{"left": 1, "right": 3}], "scene_signature": []},
        "frames": [
            {
                "frame": 75,
                "time_s": 3.4,
                "players": [
                    {
                        "track_id": 1,
                        "baseline_track_id": 3,
                        "player_id": None,
                        "box": [10, 10, 20, 30],
                    }
                ],
            }
        ],
    }
    write_json(path, raw)
    original = path.read_bytes()
    base = f"/api/videos/{video['id']}"
    with TestClient(create_app(root, data)) as client:
        document = client.get(base + "/annotations").json()
        document["track_assignments"] = [
            {
                "run_id": "players",
                "track_id": 1,
                "player_id": "A",
                "start_frame": 70,
                "end_frame": 80,
            }
        ]
        saved = client.put(base + "/annotations", json=document)
        assert saved.status_code == 200, saved.text
        assert (
            client.get(base + "/runs/players").json()["frames"][0]["players"][0][
                "player_id"
            ]
            == "A"
        )
        updated = client.put(
            base + "/annotations", json=saved.json() | {"scene_ranges": [scene(20, 21)]}
        )
        assert updated.status_code == 200, updated.text
        result = client.get(base + "/runs/players").json()
        assert result["requires_continuity_rerun"] and result["requires_tracking_rerun"]
        assert result["frames"][0]["players"][0]["track_id"] == 3
        assert result["frames"][0]["players"][0]["player_id"] is None
        assert (
            client.post(
                base + "/contacts",
                json={"shuttle_run_id": "shuttle", "player_run_id": "players"},
            ).status_code
            == 422
        )
        assert len(store.annotations(video["id"]).track_assignments) == 1
    assert path.read_bytes() == original


def test_scene_import_is_idempotent_and_preserves_unrelated_labels(catalog):
    from scripts.import_scene_review import prepare

    root, _data, store, v = catalog
    entry = {"video_id": v["id"], "sha256": v["sha256"], "scene_ranges": [scene()]}
    doc = prepare(store, entry, root)
    assert doc.events == store.annotations(v["id"]).events
    assert doc.review_windows == []
    saved = store.save_annotations(v["id"], doc)
    assert prepare(store, entry, root) == saved
    with pytest.raises(ValueError, match="conflicts"):
        prepare(store, entry | {"scene_ranges": [scene(kind="live")]}, root)
    with pytest.raises(ValueError, match="different source"):
        prepare(store, entry | {"sha256": "wrong"}, root)
