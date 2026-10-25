"""Source-time discontinuities through saved generated API/CLI evaluation."""

import hashlib
import json
import sys
from itertools import pairwise
from types import SimpleNamespace

import pytest
from badminton.api import create_app
from badminton.schemas import Annotations
from badminton.storage import Store
from badminton.video import write_json
from fastapi.testclient import TestClient


@pytest.fixture(params=["singles", "doubles"])
def workspace(tmp_path, request):
    source = tmp_path / "generated.mp4"
    source.write_bytes(b"generated-native-contact-discontinuity")
    data = tmp_path / "processed"
    store = Store(data)
    video = {
        "id": "source-gap-video",
        "path": source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "mode": request.param,
        "frame_count": 40,
        "duration_s": 2,
        "width": 640,
        "height": 360,
        "fps": 25,
        "source_start_s": 0,
    }
    store.register(video)
    return SimpleNamespace(
        root=tmp_path, source=source, data=data, video=video, store=store
    )


def prepare(ctx, variant):
    # Irregular native times with a nonzero source origin; no FPS reconstruction.
    times = [0.07]
    for frame in range(1, 40):
        step = 0.042 if frame % 3 == 0 else 0.04
        if frame == 20 and variant != "continuous":
            step = 0.11
        if frame == 30 and variant == "multiple_gaps":
            step = 0.2
        times.append(times[-1] + step)
    write_json(ctx.data / ctx.video["id"] / "timestamps.json", times)
    reference_frame = 19
    candidate_frame = 20
    if variant == "same_side":
        candidate_frame = 18
    elif variant == "interval_end_before":
        candidate_frame = 19
    elif variant == "interval_start_after":
        reference_frame = 21
    elif variant == "evidence_end_before":
        candidate_frame = 19
    doc = ctx.store.annotations(ctx.video["id"]).model_dump()
    doc.update(
        events=[
            {
                "id": "before-gap",
                "rally_id": "r1",
                "kind": "shot",
                "frame": reference_frame,
                "status": "reviewed",
                "family": "drive",
                "side": "forehand",
                "player_id": "A",
            }
        ],
        review_windows=[
            {
                "id": "all-source",
                "start_frame": 0,
                "end_frame": 40,
                "scene": "live",
                "contacts_complete": True,
            }
        ],
    )
    if variant == "touching_windows":
        doc["review_windows"] = [
            {
                "id": "before",
                "start_frame": 0,
                "end_frame": 20,
                "scene": "live",
                "contacts_complete": True,
            },
            {
                "id": "after",
                "start_frame": 20,
                "end_frame": 40,
                "scene": "live",
                "contacts_complete": True,
            },
        ]
    if variant == "removed_camera_gap":
        # A camera correction cannot erase a discontinuity in the native clock.
        doc["camera_corrections"] = [{"frame": 20, "is_cut": False}]
        with pytest.raises(
            ValueError, match="Cannot join a source timestamp discontinuity"
        ):
            ctx.store.save_annotations(ctx.video["id"], Annotations.model_validate(doc))
        doc["camera_corrections"] = []
    ctx.store.save_annotations(ctx.video["id"], Annotations.model_validate(doc))
    for stage in ("contacts", "recognition"):
        candidate = {
            "id": "after-gap",
            "frame": candidate_frame,
            "time_s": times[candidate_frame],
            "kind": "shot",
            "status": "predicted",
            "family": "drive",
            "side": "forehand",
            "hitter_hint": {"player_id": "A"},
        }
        bounds = None
        if variant == "interval_cross":
            bounds = 19, 21
        elif variant == "interval_end_before":
            bounds = 18, 19
        elif variant == "interval_start_after":
            bounds = 20, 21
        if bounds:
            prefix = "contact_" if stage == "recognition" else ""
            candidate.update(
                {
                    prefix + "start_frame": bounds[0],
                    prefix + "end_frame": bounds[1],
                    "start_time_s": times[bounds[0]],
                    "end_time_s": times[bounds[1]],
                }
            )
        if variant == "evidence_cross":
            candidate.update(context_start_frame=18, context_end_frame=23)
        elif variant == "evidence_end_before":
            candidate.update(context_start_frame=17, context_end_frame=20)
        run_id = stage + "-gap"
        run = {
            "video_id": ctx.video["id"],
            "video_sha256": ctx.video["sha256"],
            "stage": stage,
            "run_id": run_id,
            "start_frame": 0,
            "end_frame": 40,
            "cut_frames": [10] if variant == "camera_and_gap" else [],
            "candidates": [candidate],
        }
        write_json(ctx.data / ctx.video["id"] / "runs" / (run_id + ".json"), run)
        ctx.store.put_job(
            {
                "id": run_id,
                "video_id": ctx.video["id"],
                "kind": stage,
                "status": "completed",
                "progress": 1,
            }
        )
    return {path: path.read_bytes() for path in ctx.data.rglob("*.json")}


VARIANTS = [
    "gap",
    "continuous",
    "touching_windows",
    "same_side",
    "interval_cross",
    "evidence_cross",
    "interval_end_before",
    "interval_start_after",
    "evidence_end_before",
    "multiple_gaps",
    "camera_and_gap",
    "removed_camera_gap",
]


def assert_domain(report, variant, stages=("contacts", "recognition")):
    excluded = variant in ("interval_cross", "evidence_cross")
    matched = variant in (
        "continuous",
        "same_side",
        "interval_end_before",
        "interval_start_after",
        "evidence_end_before",
    )
    gaps = [] if variant == "continuous" else [20]
    if variant == "multiple_gaps":
        gaps.append(30)
    cuts = [10] if variant == "camera_and_gap" else []
    edges = [0, *sorted(set(gaps + cuts)), 40]
    ranges = [[left, right] for left, right in pairwise(edges)]
    for stage in stages:
        result = report[stage]
        assert result["prediction_clock_status"] == "validated"
        coverage = result["coverage"]
        assert coverage["frame_ranges"] == ranges
        assert coverage["reviewed_frames"] == 40
        assert coverage["reviewed_contacts"] == 1
        assert coverage["source_timestamp_gap_frames"] == gaps
        assert coverage["camera_cut_frames"] == cuts
        assert coverage["evaluated_candidates"] == (0 if excluded else 1)
        assert coverage["excluded_candidates"] == int(excluded)
        if excluded:
            reason = (
                "contact_interval_crosses_source_timestamp_gap"
                if variant == "interval_cross"
                else "evidence_context_crosses_source_timestamp_gap"
            )
            assert coverage["candidate_exclusions"] == [
                {"id": "after-gap", "reason": reason}
            ]
        else:
            assert coverage["evaluated_candidate_ids"] == ["after-gap"]
        if stage == "contacts":
            assert result["metrics"]["tp"] == int(matched)
            assert result["metrics"]["fp"] == int(not matched and not excluded)
            assert result["metrics"]["fn"] == int(not matched)
            if not matched:
                assert result["matches"] == []
                assert result["tighter_tolerance"]["metrics"]["tp"] == 0
                assert result["interval_coverage"]["matched_count"] == 0
        else:
            assert result["family"]["per_class"]["drive"]["tp"] == int(matched)
            assert result["family"]["per_class"]["drive"]["fn"] == int(not matched)
            assert result["family"]["per_class"]["drive"]["fp"] == int(
                not matched and not excluded
            )
            assert result["hitter"]["known_contact_count"] == 1
            assert result["hitter"]["correct_count"] == int(matched)
            # Uncertain proposal matches do not establish an exact complete event.
            complete = matched and variant not in (
                "interval_end_before",
                "interval_start_after",
            )
            assert result["complete_event"]["tp"] == int(complete)
            if excluded:
                assert result["unmatched_candidate_ids"] == []
                assert result["complete_event"]["fp"] == 0


@pytest.mark.parametrize("variant", VARIANTS)
def test_api_matching_stays_inside_native_source_time(workspace, variant):
    ctx = workspace
    before = prepare(ctx, variant)
    annotations = ctx.store.annotations(ctx.video["id"]).model_dump()
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={
                "contacts_run_id": "contacts-gap",
                "recognition_run_id": "recognition-gap",
            },
        )
    assert response.status_code == 200, response.text
    assert_domain(response.json(), variant)
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert ctx.store.annotations(ctx.video["id"]).model_dump() == annotations
    assert ctx.source.read_bytes() == b"generated-native-contact-discontinuity"


@pytest.mark.parametrize("variant", VARIANTS)
def test_cli_matches_api_without_mutating_inputs(
    workspace, variant, monkeypatch, capsys
):
    from badminton import cli

    ctx = workspace
    before = prepare(ctx, variant)
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={
                "contacts_run_id": "contacts-gap",
                "recognition_run_id": "recognition-gap",
            },
        )
    monkeypatch.setattr(cli, "ROOT", ctx.root)
    monkeypatch.setattr(cli, "DATA", ctx.data)
    output = ctx.root / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "badminton",
            "evaluate",
            ctx.video["id"],
            "--contacts-run",
            "contacts-gap",
            "--recognition-run",
            "recognition-gap",
            "--output",
            str(output),
        ],
    )
    cli.main()
    report = json.loads(capsys.readouterr().out)
    assert report == json.loads(output.read_bytes())
    assert report == response.json() | {"schema_version": 1}
    assert_domain(report, variant)
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
def test_individual_saved_run_uses_source_gap_barriers(workspace, stage):
    ctx = workspace
    prepare(ctx, "gap")
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={stage + "_run_id": stage + "-gap"},
        )
    assert response.status_code == 200, response.text
    assert_domain(response.json(), "gap", (stage,))


def test_api_cannot_remove_native_gap_with_camera_review(workspace):
    ctx = workspace
    before = prepare(ctx, "gap")
    doc = ctx.store.annotations(ctx.video["id"]).model_dump()
    doc["camera_corrections"] = [{"frame": 20, "is_cut": False}]
    with TestClient(create_app(ctx.root, ctx.data)) as client:
        response = client.put(f"/api/videos/{ctx.video['id']}/annotations", json=doc)
        assert response.status_code == 422, response.text
        report = client.post(
            f"/api/videos/{ctx.video['id']}/evaluate",
            json={
                "contacts_run_id": "contacts-gap",
                "recognition_run_id": "recognition-gap",
            },
        )
    assert report.status_code == 200, report.text
    assert_domain(report.json(), "gap")
    assert all(path.read_bytes() == raw for path, raw in before.items())
