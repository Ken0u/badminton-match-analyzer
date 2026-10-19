"""Generated native clocks and immutable revisions for reviewed export plans."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from badminton.ingest import inspect_video
from badminton.rally_export import (
    ExportPlanStore,
    plan_rally_exports,
    write_export_plan,
)
from badminton.schemas import Annotations
from badminton.storage import Store
from media_fixtures import write_lossless_vfr_video, write_rotated_video


def context(tmp_path, mode="singles", origin=0, rotation=None):
    if rotation is None:
        path = write_lossless_vfr_video(
            tmp_path / "source.mkv", tuple(origin + t for t in (0, 40, 80, 680))
        )
    else:
        path = write_rotated_video(tmp_path / "source.mp4", rotation)
    store = Store(tmp_path / "data")
    video = inspect_video(path, mode, store, tmp_path)
    doc = store.annotations(video["id"]).model_dump()
    doc["events"] = [
        {"id": "serve", "rally_id": "R1", "kind": "serve", "frame": 0},
        {
            "id": "shot",
            "rally_id": "R1",
            "kind": "shot",
            "frame": 1,
            "family": "unknown",
            "side": "unknown",
            "status": "predicted",
        },
        {
            "id": "end",
            "rally_id": "R1",
            "kind": "rally_end",
            "frame": 3,
            "status": "corrected",
        },
    ]
    saved = store.save_annotations(video["id"], Annotations.model_validate(doc))
    return store, video, path, saved


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize("origin", [0, 3000])
def test_complete_rally_uses_actual_vfr_source_endpoint_and_preserves_evidence(
    tmp_path, mode, origin
):
    store, video, source, saved = context(tmp_path, mode, origin)
    prediction = store.data / video["id"] / "runs" / "original.json"
    prediction.parent.mkdir()
    prediction.write_bytes(b'{"prediction": "unchanged"}')
    before = source.read_bytes(), prediction.read_bytes(), saved.model_dump()
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    assert plan["counts"] == {"total": 1, "eligible": 1, "ineligible": 0}
    interval = plan["rallies"][0]["source_range"]
    assert interval["start_frame"] == 0 and interval["end_frame_exclusive"] == 4
    assert interval["start_s"] == 0 and interval["end_s_exclusive"] == pytest.approx(
        0.72
    )
    assert interval["source_end_s_exclusive"] == pytest.approx(origin / 1000 + 0.72)
    assert (
        interval["start_pts"] == origin
        and interval["end_pts_exclusive"] == origin + 720
    )
    assert plan["annotations"] == saved.model_dump()
    assert plan["annotations"]["events"][1]["status"] == "predicted"
    assert plan["annotations"]["events"][1]["family"] == "unknown"
    assert plan["annotations"]["events"][1]["player_id"] is None
    assert plan["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert (
        source.read_bytes(),
        prediction.read_bytes(),
        store.annotations(video["id"]).model_dump(),
    ) == before
    assert plan == plan_rally_exports(store, video["id"], saved.revision, tmp_path)


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_display_orientation_and_immutable_annotation_revision(tmp_path, rotation):
    store, video, _, first = context(tmp_path, rotation=rotation)
    doc = first.model_dump()
    doc["events"][0]["notes"] = "newer annotation"
    newer = store.save_annotations(video["id"], Annotations.model_validate(doc))
    plan = plan_rally_exports(store, video["id"], first.revision, tmp_path)
    assert plan["source"]["rotation"] == rotation
    assert plan["annotations"] == first.model_dump()
    assert plan["annotation_revision"] != newer.revision
    assert (
        plan["annotation_sha256"]
        != plan_rally_exports(store, video["id"], newer.revision, tmp_path)[
            "annotation_sha256"
        ]
    )


@pytest.mark.parametrize(
    "case,reason",
    [
        ("missing_start", "missing_or_ambiguous_start"),
        ("missing_end", "missing_or_ambiguous_end"),
        ("predicted_start", "unreviewed_start"),
        ("predicted_end", "unreviewed_end"),
        ("uncertain_start", "uncertain_start"),
        ("uncertain_end", "uncertain_end"),
    ],
)
def test_partial_predicted_or_uncertain_boundaries_remain_in_denominator(
    tmp_path, case, reason
):
    store, video, _, first = context(tmp_path)
    doc = first.model_dump()
    if case.startswith("missing"):
        kind = "serve" if case.endswith("start") else "rally_end"
        doc["events"] = [e for e in doc["events"] if e["kind"] != kind]
    else:
        event = doc["events"][0 if case.endswith("start") else -1]
        if case.startswith("predicted"):
            event["status"] = "predicted"
        elif case.endswith("start"):
            event.update(contact_start_frame=0, contact_end_frame=1)
        else:
            event.update(terminal_start_frame=2, terminal_end_frame=3)
    saved = store.save_annotations(video["id"], Annotations.model_validate(doc))
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    assert plan["counts"] == {"total": 1, "eligible": 0, "ineligible": 1}
    assert plan["rallies"][0]["reasons"] == [reason]
    assert plan["rallies"][0]["source_range"] is None
    assert plan["annotations"] == saved.model_dump()


def test_overlapping_rallies_are_not_silently_exported_as_unambiguous(tmp_path):
    store, video, _, first = context(tmp_path)
    doc = first.model_dump()
    doc["events"][1] = {"id": "s2", "rally_id": "R2", "kind": "serve", "frame": 1}
    doc["events"].append(
        {"id": "e2", "rally_id": "R2", "kind": "rally_end", "frame": 2}
    )
    saved = store.save_annotations(video["id"], Annotations.model_validate(doc))
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    assert plan["counts"] == {"total": 2, "eligible": 0, "ineligible": 2}
    assert all(r["reasons"] == ["overlapping_rallies"] for r in plan["rallies"])


def test_next_native_pts_and_preserved_scene_camera_calibration_context(tmp_path):
    store, video, _, first = context(tmp_path)
    doc = first.model_dump()
    doc["events"][-1]["frame"] = 2
    doc["scene_ranges"] = [
        {"id": "scene", "start_frame": 0, "end_frame": 4, "scene": "unknown"}
    ]
    doc["camera_corrections"] = [{"frame": 2, "is_cut": True}]
    doc["calibrations"] = [
        {
            "start_frame": 0,
            "end_frame": 2,
            "corners": [
                {"x": 0.1, "y": 0.1},
                {"x": 0.9, "y": 0.1},
                {"x": 0.9, "y": 0.9},
                {"x": 0.1, "y": 0.9},
            ],
        }
    ]
    saved = store.save_annotations(video["id"], Annotations.model_validate(doc))
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    assert plan["rallies"][0]["source_range"]["end_s_exclusive"] == 0.68
    assert plan["rallies"][0]["source_range"]["end_pts_exclusive"] == 680
    for field in ("scene_ranges", "camera_corrections", "calibrations"):
        assert plan["annotations"][field] == saved.model_dump()[field]


@pytest.mark.parametrize(
    "change",
    ["source", "timeline", "metadata", "unavailable_source", "unavailable_timeline"],
)
def test_changed_or_unavailable_inputs_are_explicit_failures(tmp_path, change):
    store, video, source, saved = context(tmp_path)
    timeline = store.data / video["id"] / "timestamps.json"
    if change == "source":
        source.write_bytes(b"changed")
    elif change == "timeline":
        timeline.write_text("[0, 0.04, 0.1, 0.68]")
    elif change == "metadata":
        store.register(video | {"duration_s": 1.28})
    elif change == "unavailable_source":
        source.unlink()
    else:
        timeline.unlink()
    with pytest.raises((ValueError, OSError)):
        plan_rally_exports(store, video["id"], saved.revision, tmp_path)


def test_missing_final_sample_duration_retains_unavailable_case(tmp_path):
    store, video, _, saved = context(tmp_path)
    from badminton.av_runtime import open_media

    @contextmanager
    def without_duration(*args):
        with open_media(*args) as original:

            class Reader:
                streams = original.streams

                def decode(self, stream):
                    for frame in original.decode(stream):
                        frame.duration = 0
                        yield frame

            yield Reader()

    with patch("badminton.rally_export.open_media", without_duration):
        plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    assert plan["source"]["audited_endpoint_s"] is None
    assert plan["rallies"][0]["reasons"] == ["unavailable_final_sample_duration"]


def test_empty_or_unavailable_revision_and_nonoverwriting_output(tmp_path):
    store, video, source, saved = context(tmp_path)
    assert plan_rally_exports(store, video["id"], 0, tmp_path)["counts"]["total"] == 0
    with pytest.raises(KeyError, match="revision"):
        plan_rally_exports(store, video["id"], 999, tmp_path)
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    output = tmp_path / "export-plan.json"
    write_export_plan(output, plan, store.data)
    assert json.loads(output.read_text()) == plan
    with pytest.raises(FileExistsError):
        write_export_plan(output, plan, store.data)
    with pytest.raises(FileExistsError):
        write_export_plan(source, plan, store.data)
    with pytest.raises(ValueError, match="outside"):
        write_export_plan(store.data / "new.json", plan, store.data)


def test_cli_snapshot_and_friendly_error_without_overwriting_output(tmp_path):
    store, video, _, saved = context(tmp_path)
    output = tmp_path / "plan.json"
    env = os.environ | {
        "BADMINTON_ROOT": str(tmp_path),
        "BADMINTON_DATA_DIR": str(store.data),
    }
    command = [
        sys.executable,
        "-m",
        "badminton.cli",
        "export-rally-plan",
        video["id"],
        "--revision",
        str(saved.revision),
        "--output",
        str(output),
    ]
    original_db = store.db_path.read_bytes()
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == json.loads(output.read_text())
    assert json.loads(result.stdout)["counts"]["eligible"] == 1
    assert store.db_path.read_bytes() == original_db
    again = subprocess.run(command, env=env, capture_output=True, text=True)
    assert again.returncode == 2 and "File exists" in again.stderr
    assert "Traceback" not in again.stderr


def test_export_catalog_is_read_only_and_never_created_when_unavailable(tmp_path):
    with pytest.raises(FileNotFoundError, match="catalog"):
        ExportPlanStore(tmp_path / "absent")
    assert not (tmp_path / "absent").exists()
    store, video, _, _ = context(tmp_path)
    reader = ExportPlanStore(store.data)
    with reader.connect() as db:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("DELETE FROM annotations")
    assert reader.annotations(video["id"]).revision == 1


@pytest.mark.parametrize(
    "times", [[], {}, None, [0, 0.04, 0.04, 0.68], [0, 0.04, float("nan"), 0.68]]
)
def test_invalid_timeline_does_not_create_a_partial_plan(tmp_path, times):
    store, video, _, saved = context(tmp_path)
    (store.data / video["id"] / "timestamps.json").write_text(json.dumps(times))
    with pytest.raises(ValueError, match="timeline"):
        plan_rally_exports(store, video["id"], saved.revision, tmp_path)


@pytest.mark.parametrize("change", ["source", "timeline", "metadata", "revision"])
def test_changed_inputs_during_source_audit_fail_instead_of_mixing_snapshots(
    tmp_path, change
):
    store, video, source, saved = context(tmp_path)
    from badminton.rally_export import _audit_source

    def change_after_audit(*args):
        result = _audit_source(*args)
        if change == "source":
            source.write_bytes(b"changed after decode")
        elif change == "timeline":
            timeline = store.data / video["id"] / "timestamps.json"
            timeline.write_bytes(timeline.read_bytes() + b"\n")
        elif change == "metadata":
            store.register(video | {"name": "concurrent reimport"})
        else:
            with store.connect() as db:
                db.execute(
                    "UPDATE annotations SET document=replace(document, 'Player A', 'Changed A') WHERE revision=?",
                    (saved.revision,),
                )
        return result

    with patch("badminton.rally_export._audit_source", change_after_audit):
        with pytest.raises(ValueError, match="changed during"):
            plan_rally_exports(store, video["id"], saved.revision, tmp_path)
