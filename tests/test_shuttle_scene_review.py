"""Generated scene metadata/readings only; no source images or assessor launches."""

import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
from badminton import shuttle_scene_preparation as preparation
from badminton import shuttle_scene_review as review


def fixture(*, overlap=False, repeated=False):
    clocks = [
        {
            "frame": index,
            "pts": 900 + index * 40 + (20 if index > 7 else 0),
            "time_base": "1/1000",
            "rotation": 90,
            "display_size": [720, 1280],
        }
        for index in range(40)
    ]
    galleries = []
    intervals = [(0, 35), (16, 40)] if repeated else [(0, 35), (35, 40)]
    for view_index, (start, end) in enumerate(intervals):
        view = {
            "index": view_index,
            "id": f"view-{view_index}",
            "video_id": "SOURCE",
            "start_frame": start,
            "end_frame": end,
            "case_ids": [f"case-{view_index}"],
            "partition_starts": [start, start + 2],
        }
        sheets = []
        for offset in range(start, end, 16):
            members = [
                {
                    **clock,
                    "partition": int(clock["frame"] >= start + 2),
                    "partition_begins": clock["frame"] in (start, start + 2),
                }
                for clock in clocks[offset : min(end, offset + 16)]
            ]
            path = f"view-{view_index:03d}/sheet-{len(sheets):03d}.jpg"
            sheets.append(
                {
                    "path": path,
                    "sha256": preparation.digest(path.encode()),
                    "bytes": 100,
                    "size": [1280, 864],
                    "members": members,
                    "empty_cells": 16 - len(members),
                }
            )
        galleries.append({"view": view, "sheets": sheets})
    gallery = {
        "schema_version": 1,
        "galleries": galleries,
        "source_clocks": {"SOURCE": clocks},
    }
    max_images = 2 if overlap else 20
    _, plan = preparation.pack_galleries(galleries, max_images=max_images)
    protocol = {
        "sources": [
            {
                "id": "SOURCE",
                "sha256": "a" * 64,
                "frame_count": 40,
                "rotation": 90,
                "display_size": [720, 1280],
            }
        ],
        "denominators": {
            "views": 2,
            "cases": 2,
            "sheets": sum(len(g["sheets"]) for g in galleries),
            "frame_occurrences": sum(end - start for start, end in intervals),
        },
        "artifacts": {
            "scene-gallery": review.fingerprint(gallery),
            "scene-plan": review.fingerprint(plan),
        },
        "limits": {
            "session_max_image_bytes": preparation.MAX_BYTES,
            "session_max_images": max_images,
        },
    }
    return gallery, plan, protocol


def schedule(**kwargs):
    return review.prepare_schedule(*fixture(**kwargs))


def reading(batch, lane="independent_a", scene="L", *, session=None):
    session = session or f"session-{lane}-{batch['index']}"
    sheets = []
    for sheet in batch["images"]:
        transitions = "".join(
            "X" if m["frame"] == batch["view_start"] else "S" for m in sheet["members"]
        )
        if not sheets and sheet["members"][0]["frame"] != batch["view_start"]:
            transitions = "U" + transitions[1:]
        sheets.append(
            {
                "path": sheet["path"],
                "sha256": sheet["sha256"],
                "scene_codes": scene * len(sheet["members"]),
                "transition_codes": transitions,
                "source_reason": "Generated explicit source evidence, not a scientific reading.",
            }
        )
    return {
        "schema_version": 1,
        "session_id": session,
        "lane": lane,
        "batch_index": batch["index"],
        "sheets": sheets,
        "continuity_note": "Generated same-view note.",
        "limitations": ["Generated fixture; no accuracy inference."],
    }


def results(batches, lane="independent_a", scene="L"):
    rows = []
    for batch in batches:
        document = reading(batch, lane, scene)
        rows.append(
            {
                "batch_index": batch["index"],
                "session_id": document["session_id"],
                "thread_id": f"thread-{lane}-{batch['index']}",
                "status": "completed",
                "document": document,
            }
        )
    return rows


def reseal(gallery, plan, protocol):
    protocol["artifacts"].update(
        {
            "scene-gallery": review.fingerprint(gallery),
            "scene-plan": review.fingerprint(plan),
        }
    )


def test_schedule_keeps_every_native_occurrence_and_projects_cases():
    gallery, plan, protocol = fixture(overlap=True)
    before = copy.deepcopy((gallery, plan, protocol))
    batches = review.prepare_schedule(gallery, plan, protocol)
    assert len(batches) == 3
    assert batches[1]["overlap_image"] == batches[0]["images"][-1]["path"]
    assert "case_ids" not in json.dumps(batches)
    assert batches[0]["images"][0]["members"][9]["pts"] == 1280
    assert sum(len(s["members"]) for b in batches for s in b["images"]) == 56
    assert (gallery, plan, protocol) == before


@pytest.mark.parametrize(
    "mutation",
    [
        "gallery_hash",
        "image_hash",
        "pts",
        "source",
        "missing_sheet",
        "duplicate_sheet",
        "duplicate_view",
        "missing_cell",
        "extra_cell",
        "packing",
        "extra_lane",
        "denominator",
        "foreign_field",
        "partition",
    ],
)
def test_schedule_refuses_changed_original_binding(mutation):
    gallery, plan, protocol = fixture(overlap=True)
    if mutation == "gallery_hash":
        protocol["artifacts"]["scene-gallery"] = "f" * 64
    elif mutation == "image_hash":
        gallery["galleries"][0]["sheets"][0]["sha256"] = "f" * 64
    elif mutation == "pts":
        gallery["galleries"][0]["sheets"][0]["members"][0]["pts"] += 1
    elif mutation == "source":
        gallery["galleries"][0]["view"]["video_id"] = "OTHER"
    elif mutation == "missing_sheet":
        gallery["galleries"][0]["sheets"].pop()
    elif mutation == "duplicate_sheet":
        gallery["galleries"][0]["sheets"].append(gallery["galleries"][0]["sheets"][0])
    elif mutation == "duplicate_view":
        gallery["galleries"][1]["view"]["id"] = gallery["galleries"][0]["view"]["id"]
    elif mutation == "missing_cell":
        gallery["galleries"][0]["sheets"][0]["members"].pop()
    elif mutation == "extra_cell":
        gallery["galleries"][0]["sheets"][0]["members"].append(
            gallery["galleries"][0]["sheets"][0]["members"][-1]
        )
    elif mutation == "packing":
        plan["lanes"]["independent_b"][0]["images"].pop()
    elif mutation == "extra_lane":
        plan["lanes"]["prior_labels"] = []
    elif mutation == "denominator":
        protocol["denominators"]["frame_occurrences"] -= 1
    elif mutation == "foreign_field":
        gallery["galleries"][0]["sheets"][0]["members"][0]["prior_label"] = "live"
    elif mutation == "partition":
        gallery["galleries"][0]["view"]["partition_starts"] = [0, 0]
    with pytest.raises(ValueError):
        review.prepare_schedule(gallery, plan, protocol)


@pytest.mark.parametrize(
    "mutation",
    [
        "pts",
        "missing_cell",
        "duplicate_view",
        "foreign_cell",
        "bool_frame",
        "bool_pts",
        "negative_pts",
        "extra_clock",
        "frame_gap",
        "bool_size",
        "partial_sheet",
        "bad_hash",
        "reversed_partition",
    ],
)
def test_structural_guards_work_even_with_matching_generated_hashes(mutation):
    gallery, plan, protocol = fixture()
    sheet = gallery["galleries"][0]["sheets"][0]
    if mutation == "pts":
        sheet["members"][0]["pts"] += 1
    elif mutation == "missing_cell":
        sheet["members"].pop()
    elif mutation == "duplicate_view":
        gallery["galleries"][1]["view"]["id"] = gallery["galleries"][0]["view"]["id"]
    elif mutation == "foreign_cell":
        sheet["members"][0]["prediction"] = "live"
    elif mutation == "bool_frame":
        sheet["members"][0]["frame"] = False
    elif mutation == "bool_pts":
        sheet["members"][0]["pts"] = True
    elif mutation == "negative_pts":
        gallery["source_clocks"]["SOURCE"][2]["pts"] = -1
    elif mutation == "extra_clock":
        gallery["source_clocks"]["SOURCE"][0]["predicted"] = True
    elif mutation == "frame_gap":
        sheet["members"][4]["frame"] += 1
    elif mutation == "bool_size":
        sheet["empty_cells"] = False
    elif mutation == "partial_sheet":
        sheet["empty_cells"] = 1
    elif mutation == "bad_hash":
        sheet["sha256"] = "not-a-hash"
    elif mutation == "reversed_partition":
        gallery["galleries"][0]["view"]["partition_starts"] = [0, 4, 2]
    reseal(gallery, plan, protocol)
    with pytest.raises(ValueError):
        review.prepare_schedule(gallery, plan, protocol)


def test_reading_and_schema_cover_only_real_cells():
    batch = schedule()[0]
    document = reading(batch)
    rows = review.validate_reading(
        document, batch, document["session_id"], document["lane"]
    )
    assert len(rows) == 35 and rows[-1]["frame"] == 34
    assert rows[0]["transition"] == "view_start"
    assert rows[2]["partition_begins"] and rows[2]["transition"] == "same"
    assert rows[0]["rotation"] == 90
    schema = review.assessment_schema(batch, document["session_id"], document["lane"])
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(document)
    assert schema["properties"]["sheets"]["items"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_sheet",
        "extra_sheet",
        "wrong_order",
        "image_hash",
        "missing_cell",
        "extra_empty_cell",
        "illegal_scene",
        "illegal_transition",
        "wrong_start",
        "missing_start",
        "bool_batch",
        "bool_schema",
        "wrong_session",
        "wrong_lane",
        "extra_field",
        "blank_reason",
        "missing_limitations",
        "giant_note",
    ],
)
def test_invalid_readings_cannot_be_counted(mutation):
    batch = schedule()[0]
    document = reading(batch)
    sheet = document["sheets"][0]
    if mutation == "missing_sheet":
        document["sheets"].pop()
    elif mutation == "extra_sheet":
        document["sheets"].append(copy.deepcopy(sheet))
    elif mutation == "wrong_order":
        document["sheets"].reverse()
    elif mutation == "image_hash":
        sheet["sha256"] = "a" * 64
    elif mutation == "missing_cell":
        sheet["scene_codes"] = "L" * 15
    elif mutation == "extra_empty_cell":
        document["sheets"][-1]["scene_codes"] = "L" * 16
    elif mutation == "illegal_scene":
        sheet["scene_codes"] = "?" * 16
    elif mutation == "illegal_transition":
        sheet["transition_codes"] = "?" * 16
    elif mutation == "wrong_start":
        sheet["transition_codes"] = "X" * 16
    elif mutation == "missing_start":
        sheet["transition_codes"] = "S" * 16
    elif mutation == "bool_batch":
        document["batch_index"] = False
    elif mutation == "bool_schema":
        document["schema_version"] = True
    elif mutation == "wrong_session":
        document["session_id"] = "different"
    elif mutation == "wrong_lane":
        document["lane"] = "independent_b"
    elif mutation == "extra_field":
        sheet["model_prediction"] = "live"
    elif mutation == "blank_reason":
        sheet["source_reason"] = " "
    elif mutation == "missing_limitations":
        document["limitations"] = []
    elif mutation == "giant_note":
        document["continuity_note"] = "a" * 2001
    with pytest.raises(ValueError):
        review.validate_reading(
            document, batch, "session-independent_a-0", "independent_a"
        )


def test_prompt_uses_explicit_unknowns_and_cannot_receive_other_stream_labels():
    batch = schedule()[0]
    prompt = review.assessment_prompt(batch, "s", "independent_a", "own same-view note")
    assert "EVERY actual native cell" in prompt
    assert "ALONE does not prove live play" in prompt
    assert "own same-view note" in prompt
    assert "case-" not in prompt
    with pytest.raises(ValueError, match="blind"):
        review.assessment_prompt(batch, "s", "independent_a", claims=[])
    with pytest.raises(ValueError, match="source-only"):
        review.assessment_prompt(
            batch, "s", "adjudication", claims=[{"model_score": 0.9}]
        )


def test_missing_and_failed_sessions_preserve_full_native_denominator():
    batches = schedule(overlap=True)
    rows = results(batches)
    rows[0].update(status="failed", thread_id=None, document=None)
    lane = review.assemble_lane(batches, rows[:2], "independent_a")
    assert lane["aggregate"]["frame_occurrences"] == 40
    assert lane["aggregate"]["failed_sessions"] == 1
    assert lane["aggregate"]["missing_sessions"] == 1
    assert lane["aggregate"]["unavailable_cells"] == 21
    assert lane["records"][0]["scene"] == "unknown"
    assert all(value is False for value in lane["aggregate"]["eligibility"].values())


def test_overlap_unknown_is_not_silently_replaced_by_known_reading():
    batches = schedule(overlap=True)
    lane = review.assemble_lane(batches, results(batches), "independent_a")
    overlap = lane["records"][16]
    assert len(overlap["readings"]) == 2
    assert {r["transition"] for r in overlap["readings"]} == {"same", "unknown"}
    assert overlap["status"] == "overlap_conflict"
    assert overlap["transition"] == "unknown"
    assert lane["aggregate"]["frame_occurrences"] == 40


def test_cross_view_contradictions_preserve_occurrences_and_each_reading():
    batches = schedule(repeated=True)
    original = results(batches)
    original[1]["document"]["sheets"][0]["scene_codes"] = "R" * 16
    lane = review.assemble_lane(batches, original, "independent_a")
    assert lane["aggregate"]["frame_occurrences"] == 59
    assert lane["cross_view_conflicts"][0]["frame"] == 16
    assert lane["cross_view_conflicts"][0]["scenes"] == ["live", "replay"]
    assert len([r for r in lane["records"] if r["frame"] == 16]) == 2
    assert all(r["cross_view_conflict"] for r in lane["records"] if r["frame"] == 16)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_batch",
        "reused_session",
        "reused_thread",
        "missing_thread",
        "running",
        "failed_labels",
    ],
)
def test_invalid_session_provenance_is_refused(mutation):
    batches = schedule()
    rows = results(batches)
    if mutation == "duplicate_batch":
        rows.append(copy.deepcopy(rows[0]))
    elif mutation == "reused_session":
        rows[1]["session_id"] = rows[0]["session_id"]
    elif mutation == "reused_thread":
        rows[1]["thread_id"] = rows[0]["thread_id"]
    elif mutation == "missing_thread":
        rows[0]["thread_id"] = None
    elif mutation == "running":
        rows[0]["status"] = "running"
    elif mutation == "failed_labels":
        rows[0]["status"] = "failed"
    with pytest.raises(ValueError):
        review.assemble_lane(batches, rows, "independent_a")


def test_independent_agreement_retains_two_full_original_readings():
    batches = schedule()
    a = review.assemble_lane(batches, results(batches), "independent_a")
    b = review.assemble_lane(
        batches, results(batches, "independent_b"), "independent_b"
    )
    result = review.compare_lanes(batches, a, b)
    assert result["aggregate"]["status_counts"]["independent_agreement"] == 40
    assert result["adjudication_batch_indices"] == []
    assert result["records"][0]["original_a"] == a["records"][0]
    assert result["records"][0]["original_b"] == b["records"][0]
    assert result["aggregate"]["complete_independent_rally_references"] == "0/2"


def test_cross_lane_thread_reuse_and_tampered_assembly_fail():
    batches = schedule()
    ar, br = results(batches), results(batches, "independent_b")
    br[0]["thread_id"] = ar[0]["thread_id"]
    a = review.assemble_lane(batches, ar, "independent_a")
    b = review.assemble_lane(batches, br, "independent_b")
    with pytest.raises(ValueError, match="reused"):
        review.compare_lanes(batches, a, b)
    b = review.assemble_lane(
        batches, results(batches, "independent_b"), "independent_b"
    )
    b["records"][0]["scene"] = "replay"
    with pytest.raises(ValueError, match="changed"):
        review.compare_lanes(batches, a, b)


def test_unknown_agreement_stays_unknown_without_adjudication():
    batches = schedule()
    a = review.assemble_lane(batches, results(batches, scene="U"), "independent_a")
    b = review.assemble_lane(
        batches, results(batches, "independent_b", "U"), "independent_b"
    )
    result = review.compare_lanes(batches, a, b)
    assert result["aggregate"]["status_counts"]["unknown"] == 40
    assert result["aggregate"]["status_counts"]["independent_agreement"] == 0
    assert result["aggregate"]["scene_counts"] == {"unknown": 40}
    assert result["adjudication_batch_indices"] == [0, 1]


def test_source_adjudication_is_distinct_from_independent_agreement():
    batches = schedule()
    a = review.assemble_lane(batches, results(batches, scene="U"), "independent_a")
    b = review.assemble_lane(
        batches, results(batches, "independent_b", "R"), "independent_b"
    )
    adjudication = review.assemble_lane(
        batches, results(batches, "adjudication", "L"), "adjudication"
    )
    result = review.compare_lanes(batches, a, b, adjudication)
    assert result["aggregate"]["status_counts"]["adjudicated"] == 40
    assert result["aggregate"]["status_counts"]["independent_agreement"] == 0
    assert result["records"][0]["original_a"]["scene"] == "unknown"
    assert result["records"][0]["original_b"]["scene"] == "replay"


def test_adjudication_cannot_make_unavailable_original_complete():
    batches = schedule()
    ar = results(batches)
    ar[0].update(status="failed", thread_id=None, document=None)
    a = review.assemble_lane(batches, ar, "independent_a")
    b = review.assemble_lane(
        batches, results(batches, "independent_b"), "independent_b"
    )
    adjudication = review.assemble_lane(
        batches, results(batches, "adjudication")[:1], "adjudication"
    )
    result = review.compare_lanes(batches, a, b, adjudication)
    assert result["aggregate"]["status_counts"]["unavailable"] == 35
    assert result["aggregate"]["original_streams_complete"] is False


def test_adjudication_requires_both_original_attempts_and_needed_batch():
    batches = schedule()
    a = review.assemble_lane(batches, results(batches)[:1], "independent_a")
    b = review.assemble_lane(
        batches, results(batches, "independent_b"), "independent_b"
    )
    adjudication = review.assemble_lane(
        batches, results(batches, "adjudication"), "adjudication"
    )
    with pytest.raises(ValueError, match="Seal both"):
        review.compare_lanes(batches, a, b, adjudication)
    a = review.assemble_lane(batches, results(batches), "independent_a")
    with pytest.raises(ValueError, match="Unneeded"):
        review.compare_lanes(batches, a, b, adjudication)


def test_targeted_adjudication_preserves_supported_original_agreements():
    batches = schedule()
    ar = results(batches, scene="R")
    br = results(batches, "independent_b", "R")
    # Only one original cell is unresolved; other cells are adjudication context.
    ar[0]["document"]["sheets"][0]["scene_codes"] = "R" * 5 + "U" + "R" * 10
    a = review.assemble_lane(batches, ar, "independent_a")
    b = review.assemble_lane(batches, br, "independent_b")
    adjudication = review.assemble_lane(
        batches, results(batches, "adjudication", "L")[:1], "adjudication"
    )
    compared = review.compare_lanes(batches, a, b, adjudication)
    assert compared["records"][5]["status"] == "adjudicated"
    assert compared["records"][5]["scene"] == "live"
    assert compared["records"][6]["status"] == "independent_agreement"
    assert compared["records"][6]["scene"] == "replay"
    assert compared["records"][6]["adjudication"]["scene"] == "live"
    assert compared["aggregate"]["status_counts"]["independent_agreement"] == 39


def test_unknown_adjudication_does_not_erase_original_conflict():
    batches = schedule()
    a = review.assemble_lane(batches, results(batches, scene="L"), "independent_a")
    b = review.assemble_lane(
        batches, results(batches, "independent_b", "R"), "independent_b"
    )
    adjudication = review.assemble_lane(
        batches, results(batches, "adjudication", "U"), "adjudication"
    )
    compared = review.compare_lanes(batches, a, b, adjudication)
    assert compared["aggregate"]["status_counts"]["conflict"] == 40
    assert compared["aggregate"]["scene_counts"] == {"unknown": 40}
    assert compared["records"][0]["original_a"]["scene"] == "live"
    assert compared["records"][0]["original_b"]["scene"] == "replay"


def test_unattached_predecessor_cannot_be_labeled_same_camera():
    batch = schedule(overlap=True)[1]
    document = reading(batch)
    document["sheets"][0]["transition_codes"] = "S" * 16
    with pytest.raises(ValueError, match="Unattached"):
        review.validate_reading(
            document, batch, document["session_id"], document["lane"]
        )


def cli_module():
    path = Path(__file__).resolve().parents[1] / "scripts/review_shuttle_scenes.py"
    spec = importlib.util.spec_from_file_location("generated_scene_review_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cli_args(tmp_path):
    (tmp_path / ".cache/worktrees").mkdir(parents=True)
    output = tmp_path / ".cache/scene342-generated"
    output.mkdir()
    return SimpleNamespace(
        root=tmp_path,
        output=output,
        ownership=tmp_path / "ownership.json",
        context_sha256="f" * 64,
    )


def ownership_fixture(module, args):
    now = time.time()
    claim = {
        "actor": "generated",
        "host_id": module.platform.node(),
        "session_id": "generated-session",
        "epoch": 1,
        "spec_hash": module.SPEC_HASH,
        "branch": "generated-branch",
        "baseline_sha": "a" * 40,
        "granted_at": now - 20,
        "expires_at": now + 3600,
    }
    task = {
        "status": "running",
        "epoch": 1,
        "claim": claim,
        "human_approval": {"spec_hash": module.SPEC_HASH},
    }
    grant = {
        "task": copy.deepcopy(task),
        "session_id": claim["session_id"],
        "deadline": claim["granted_at"] + 28800,
    }
    live = {"at": now, "paused": False, "task": task}
    module.write(args.ownership, live)
    return grant, live, now


@pytest.mark.parametrize(
    "change",
    [
        "stale",
        "future",
        "paused",
        "epoch",
        "host",
        "spec",
        "session",
        "grant_time",
        "expired",
        "approval",
        "deadline",
    ],
)
def test_cli_ownership_refuses_stale_or_changed_authority(tmp_path, change):
    module, args = cli_module(), cli_args(tmp_path)
    grant, live, now = ownership_fixture(module, args)
    assert module.ownership(args, grant, now=now) == grant["deadline"]
    if change == "stale":
        live["at"] = now - 180
    elif change == "future":
        live["at"] = now + 1
    elif change == "paused":
        live["paused"] = True
    elif change == "epoch":
        live["task"]["epoch"] = 2
    elif change == "host":
        live["task"]["claim"]["host_id"] = "different"
    elif change == "spec":
        live["task"]["claim"]["spec_hash"] = "b" * 64
    elif change == "session":
        live["task"]["claim"]["session_id"] = "other-session"
    elif change == "grant_time":
        live["task"]["claim"]["granted_at"] += 1
    elif change == "expired":
        live["task"]["claim"]["expires_at"] = now
    elif change == "approval":
        live["task"]["human_approval"] = {}
    elif change == "deadline":
        grant["deadline"] += 1
    args.ownership.write_bytes(preparation.encode(live))
    with pytest.raises(ValueError):
        module.ownership(args, grant, now=now)


def test_cli_renewal_does_not_extend_original_deadline(tmp_path):
    module, args = cli_module(), cli_args(tmp_path)
    grant, live, _now = ownership_fixture(module, args)
    live["task"]["claim"]["expires_at"] = grant["deadline"] + 3600
    live["at"] = grant["deadline"]
    args.ownership.write_bytes(preparation.encode(live))
    with pytest.raises(ValueError, match="expired"):
        module.ownership(args, grant, now=grant["deadline"])


def test_cli_reservation_is_durable_and_failed_attempt_cannot_be_replaced(tmp_path):
    module, args = cli_module(), cli_args(tmp_path)
    batch = schedule(overlap=True)[0]
    folder = module.reserve(args, batch, "independent_a", "generated-first")
    reservation = module.read(folder / "reservation.json")
    assert reservation["image_bytes"] == 200
    assert reservation["replacement_allowed"] is False
    module.write(folder / "failure.json", {"status": "failed"})
    before = (folder / "reservation.json").read_bytes()
    with pytest.raises(ValueError, match="replacement"):
        module.reserve(args, batch, "independent_a", "generated-replacement")
    assert (folder / "reservation.json").read_bytes() == before


@pytest.mark.parametrize(
    "limit", ["images", "bytes", "lane_sessions", "lane_bytes", "total_bytes", "output"]
)
def test_cli_payload_and_output_budgets_refuse_before_launch(
    tmp_path, monkeypatch, limit
):
    module, args = cli_module(), cli_args(tmp_path)
    batch = copy.deepcopy(schedule()[0])
    if limit == "images":
        batch["images"] *= 8
    elif limit == "bytes":
        batch["images"][0]["bytes"] = 6 * 1024**2 + 1
    elif limit in ("lane_sessions", "lane_bytes", "total_bytes"):
        count = 75 if limit == "lane_sessions" else 1
        for i in range(count):
            folder = args.output / "sessions" / "independent_a" / f"{i + 100:03d}"
            folder.mkdir(parents=True)
            module.write(
                folder / "reservation.json",
                {
                    "lane": "independent_a"
                    if limit != "total_bytes"
                    else "independent_b",
                    "batch_index": i + 100,
                    "session_id": f"previous-{i}",
                    "image_bytes": 325618950
                    if limit == "lane_bytes"
                    else 976856850
                    if limit == "total_bytes"
                    else 1,
                },
            )
    elif limit == "output":
        monkeypatch.setattr(
            module, "task_bytes", lambda _: module.LIMITS["max_output_bytes"] - 1
        )
    with pytest.raises(ValueError):
        module.reserve(args, batch, "independent_a", "new")
    assert not (args.output / "sessions/independent_a/000").exists()


def test_cli_reservation_rejects_unapproved_lanes_and_reused_session(tmp_path):
    module, args = cli_module(), cli_args(tmp_path)
    batches = schedule()
    with pytest.raises(ValueError):
        module.reserve(args, batches[0], "third_original", "bad-lane")
    module.reserve(args, batches[0], "independent_a", "same-session")
    with pytest.raises(ValueError):
        module.reserve(args, batches[1], "independent_b", "same-session")


def test_cli_counts_failed_outputs_and_checks_retained_parent(tmp_path, monkeypatch):
    module, args = cli_module(), cli_args(tmp_path)
    (args.output / "failed.log").write_bytes(b"x" * 13)
    worktree = tmp_path / ".cache/worktrees/scene342-generated"
    worktree.mkdir()
    (worktree / "generated.txt").write_bytes(b"y" * 7)
    assert module.task_bytes(tmp_path) == 20
    original = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda path: path == args.output or original(path)
    )
    with pytest.raises(ValueError, match="Linked"):
        module.task_bytes(tmp_path)


def test_cli_bounded_drain_preserves_total_hash_and_truncation(tmp_path):
    module = cli_module()
    result = {}
    module.drain(io.BytesIO(b"abcdef"), tmp_path / "generated.log", result, 4)
    assert (tmp_path / "generated.log").read_bytes() == b"abcd"
    assert result == {
        "overflow": True,
        "bytes": 6,
        "sha256": preparation.digest(b"abcdef"),
        "truncated": True,
    }


def clean_receipt():
    return {
        "exit_code": 0,
        "stdin_error": None,
        "bounded_stop": False,
        "stdout": {"truncated": False},
        "stderr": {"truncated": False},
        "all_observed_processes_absent": True,
        "pipes_reached_eof": True,
        "collection_errors": [],
    }


@pytest.mark.parametrize(
    "invalid",
    [
        "error",
        "failed",
        "tool_item",
        "unknown_tool_event",
        "duplicate_thread",
        "no_turn",
        "unproven_exit",
        "truncated",
        "unproven_pipe",
        "collection_error",
    ],
)
def test_cli_event_identity_requires_clean_tool_free_terminal(tmp_path, invalid):
    module = cli_module()
    events = [
        {"type": "thread.started", "thread_id": "generated-thread"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "generated"},
        },
        {"type": "turn.completed"},
    ]
    receipt = clean_receipt()
    if invalid == "error":
        events.append({"type": "error"})
    elif invalid == "failed":
        events.append({"type": "turn.failed"})
    elif invalid == "tool_item":
        events.append({"type": "item.completed", "item": {"type": "command_execution"}})
    elif invalid == "unknown_tool_event":
        events.append({"type": "tool.executed", "name": "read_private_labels"})
    elif invalid == "duplicate_thread":
        events.append({"type": "thread.started", "thread_id": "another-thread"})
    elif invalid == "no_turn":
        events.pop()
    elif invalid == "unproven_exit":
        receipt["all_observed_processes_absent"] = False
    elif invalid == "truncated":
        receipt["stdout"]["truncated"] = True
    elif invalid == "unproven_pipe":
        receipt.pop("pipes_reached_eof")
    elif invalid == "collection_error":
        receipt["collection_errors"] = ["generated"]
    (tmp_path / "events.jsonl").write_bytes(
        b"\n".join(json.dumps(event).encode() for event in events)
    )
    with pytest.raises(ValueError):
        module.event_identity(tmp_path, receipt)


def test_cli_actual_store_denies_competing_work_before_calculation(
    tmp_path, monkeypatch
):
    from badminton.storage import ConflictError, Store

    module, args = cli_module(), cli_args(tmp_path)
    for key in module.CREDENTIALS:
        monkeypatch.delenv(key, raising=False)
    store = Store(tmp_path / "data/processed")
    store.claim_job(
        {"id": "existing", "kind": "generated", "video_id": None, "status": "running"}
    )
    before = store.jobs()
    monkeypatch.setattr(module.preparation, "shared_store", lambda _: store)
    called = []
    with pytest.raises(ConflictError, match="Another processing"):
        module.admitted(args, "originals", lambda _: called.append(True))
    assert called == [] and store.jobs() == before
    failure = module.read(args.output / "originals/failure.json")
    assert failure["job_id"] is None and not failure["implicit_retry_permitted"]
    assert not (args.output / "originals/terminal.json").exists()


def test_cli_store_terminal_matches_real_generated_job(tmp_path, monkeypatch):
    from badminton.storage import Store

    module, args = cli_module(), cli_args(tmp_path)
    for key in module.CREDENTIALS:
        monkeypatch.delenv(key, raising=False)
    store = Store(tmp_path / "data/processed")
    monkeypatch.setattr(module.preparation, "shared_store", lambda _: store)
    result = module.admitted(
        args, "originals", lambda _: {"status": "generated_done", "value": 3}
    )
    assert result["status"] == "generated_done"
    terminal = module.read(args.output / "originals/terminal.json")
    module.preparation.check_store_terminal(tmp_path, terminal)
    assert store.jobs()[0]["status"] == "completed"
    terminal["summary"]["value"] = 4
    with pytest.raises(ValueError, match="not completed"):
        module.preparation.check_store_terminal(tmp_path, terminal)


def test_cli_current_or_unobservable_process_never_counts_as_terminal(monkeypatch):
    module = cli_module()
    with pytest.raises(ValueError, match="still present"):
        module.require_absent(module.identity())
    monkeypatch.setattr(
        module.psutil, "Process", lambda _: (_ for _ in ()).throw(psutil.AccessDenied())
    )
    with pytest.raises(psutil.AccessDenied):
        module.require_absent({"pid": 123, "created": 1.0})


@pytest.mark.parametrize("mode", ["reused", "changed_command", "access_denied"])
def test_cli_never_signals_an_unproven_process_lifetime(monkeypatch, mode):
    module = cli_module()
    signals = []
    original = {"pid": 123, "created": 1.0, "cwd": "generated", "command": ["original"]}
    process = SimpleNamespace(
        pid=123,
        create_time=lambda: 2.0 if mode == "reused" else 1.0,
        cwd=lambda: "generated",
        cmdline=lambda: ["changed"],
        terminate=lambda: signals.append(True),
    )
    monkeypatch.setattr(module.psutil, "Process", lambda _: process)
    if mode == "access_denied":
        monkeypatch.setattr(
            module.psutil,
            "Process",
            lambda _: (_ for _ in ()).throw(psutil.AccessDenied()),
        )
        with pytest.raises(psutil.AccessDenied):
            module.stop_owned(original)
    elif mode == "changed_command":
        with pytest.raises(ValueError, match="identity mismatch"):
            module.stop_owned(original)
    else:
        assert module.stop_owned(original) == "original_absent_pid_reused"
    assert signals == []


def test_cli_source_mutation_fails_before_any_assessor_or_store(tmp_path, monkeypatch):
    module, args = cli_module(), cli_args(tmp_path)
    args.gallery = tmp_path / "gallery"
    args.gallery.mkdir()
    protocol = {"artifacts": dict.fromkeys(module.ARTIFACTS, "a" * 64)}
    (args.gallery / "gallery.json").write_bytes(b"changed original metadata")
    called = []
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: called.append(True))
    monkeypatch.setattr(
        module.preparation, "shared_store", lambda _: called.append(True)
    )
    with pytest.raises(ValueError, match="metadata changed"):
        module.inputs(args, protocol)
    assert called == []


def test_cli_original_lane_continuity_is_only_same_view_and_own_reading(
    tmp_path, monkeypatch
):
    module, args = cli_module(), cli_args(tmp_path)
    batches = schedule(overlap=True)
    calls = []

    def fake_execute(args, context, batch, lane, prior_note="", claims=None):
        calls.append((batch["index"], lane, prior_note, claims))
        return results([batch], lane)[0]

    monkeypatch.setattr(module, "execute", fake_execute)
    module.lane_run(args, {}, batches, "independent_a")
    assert calls == [
        (0, "independent_a", "", None),
        (1, "independent_a", "Generated same-view note.", None),
        (2, "independent_a", "", None),
    ]


@pytest.mark.parametrize("invalid", ["outside", "duplicate", "boolean", "extra_field"])
def test_adjudication_grouped_claims_cannot_add_unattached_or_foreign_context(invalid):
    batch = schedule()[0]
    claim = {
        "frames": [0, 1],
        "lane": "independent_a",
        "scene": "unknown",
        "transition": "unknown",
        "source_reason": "Generated uncertain source detail.",
    }
    prompt = review.assessment_prompt(
        batch, "adjudicator", "adjudication", claims=[claim]
    )
    assert "Do not majority vote" in prompt
    assert "conflicting/unknown readings from sealed original streams" in prompt
    if invalid == "outside":
        claim["frames"] = [batch["view_end"]]
    elif invalid == "duplicate":
        claim["frames"] = [0, 0]
    elif invalid == "boolean":
        claim["frames"] = [False]
    elif invalid == "extra_field":
        claim["old_prediction"] = "L"
    with pytest.raises(ValueError):
        review.assessment_prompt(batch, "adjudicator", "adjudication", claims=[claim])


def execute_fixture(module, tmp_path, monkeypatch):
    args = cli_args(tmp_path)
    args.gallery = tmp_path / "gallery"
    args.gallery.mkdir()
    batch = copy.deepcopy(schedule()[0])
    for sheet in batch["images"]:
        path = args.gallery / sheet["path"]
        path.parent.mkdir(exist_ok=True)
        raw = b"Generated bytes never sent to a real process: " + sheet["path"].encode()
        path.write_bytes(raw)
        sheet.update(bytes=len(raw), sha256=preparation.digest(raw))
    cli = tmp_path / "generated-cli.exe"
    cli.write_bytes(b"Not executable. subprocess.Popen is replaced in this test.")
    context = {
        "grant": {},
        "deadline": time.time() + 3600,
        "consumers": {"cli": {"path": str(cli), "sha256": preparation.file_hash(cli)}},
    }
    monkeypatch.setattr(module, "ownership", lambda *a, **k: context["deadline"])
    monkeypatch.setattr(module, "verify_cli_configuration", lambda *a: None)
    calls = []
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)) or object(),
    )
    return args, batch, context, calls


def test_cli_invocation_is_blind_and_removes_other_credentials(tmp_path, monkeypatch):
    module = cli_module()
    args, batch, context, calls = execute_fixture(module, tmp_path, monkeypatch)
    for key in module.CREDENTIALS:
        monkeypatch.setenv(key, "GENERATED-TEST-VALUE")

    def fake_collect(child, message, folder, deadline):
        schema = module.read(folder / "schema.json")
        session = schema["properties"]["session_id"]["enum"][0]
        lane = schema["properties"]["lane"]["enum"][0]
        module.write(
            folder / "original-final.json", reading(batch, lane, session=session)
        )
        events = [
            {"type": "thread.started", "thread_id": "generated-independent-thread"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "generated"},
            },
            {"type": "turn.completed"},
        ]
        (folder / "events.jsonl").write_bytes(
            b"\n".join(json.dumps(event).encode() for event in events)
        )
        return clean_receipt()

    monkeypatch.setattr(module, "collect", fake_collect)
    result = module.execute(args, context, batch, "independent_a", "own source note")
    assert result["status"] == "completed" and len(calls) == 1
    command, kwargs = calls[0]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in command and "--output-schema" in command
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    overrides = {
        command[index + 1] for index, value in enumerate(command) if value == "--config"
    }
    assert {
        "project_doc_max_bytes=0",
        "features.shell_tool=false",
        "features.apps=false",
        'web_search="disabled"',
        "memories.use_memories=false",
        "memories.generate_memories=false",
        'forced_login_method="chatgpt"',
    } <= overrides
    assert "--model" not in command and not any(
        value.startswith("model_provider=") for value in overrides
    )
    assert command.count("--image") == len(batch["images"])
    assert command[-1] == "-"
    assert not set(module.CREDENTIALS).intersection(kwargs["env"])
    assert kwargs["stdin"] != subprocess.PIPE
    assert Path(kwargs["stdin"].name).name == "prompt.txt"
    folder = args.output / "sessions/independent_a/000"
    prompt = (folder / "prompt.txt").read_text(encoding="utf-8")
    assert "own source note" in prompt and "independent_b" not in prompt
    assert (
        module.read(folder / "reservation.json")["session_id"] == result["session_id"]
    )


def test_cli_changed_image_blocks_launch_before_budget_charge(tmp_path, monkeypatch):
    module = cli_module()
    args, batch, context, calls = execute_fixture(module, tmp_path, monkeypatch)
    (args.gallery / batch["images"][0]["path"]).write_bytes(b"changed generated image")
    with pytest.raises(ValueError, match="payload changed"):
        module.execute(args, context, batch, "independent_a")
    assert calls == [] and not (args.output / "sessions").exists()


def test_cli_unknown_terminal_process_preserves_attempt_and_refuses_result(
    tmp_path, monkeypatch
):
    module = cli_module()
    args, batch, context, calls = execute_fixture(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "collect", lambda *a, **k: (_ for _ in ()).throw(psutil.AccessDenied())
    )
    with pytest.raises(psutil.AccessDenied):
        module.execute(args, context, batch, "independent_a")
    folder = args.output / "sessions/independent_a/000"
    assert len(calls) == 1
    assert (folder / "reservation.json").exists() and (folder / "failure.json").exists()
    assert (
        not (folder / "finish.json").exists() and not (folder / "result.json").exists()
    )
    assert module.STOP.is_set()
    with pytest.raises(ValueError, match="requires observation"):
        module.execute(args, context, batch, "independent_b")
    assert len(calls) == 1
    assert not (args.output / "sessions/independent_b").exists()


def test_cli_durable_write_refuses_budget_overflow_before_creation(
    tmp_path, monkeypatch
):
    module, args = cli_module(), cli_args(tmp_path)
    monkeypatch.setattr(module, "BUDGET_ROOT", tmp_path)
    raw_size = len(preparation.encode({"generated": True}))
    monkeypatch.setattr(
        module, "task_bytes", lambda _: module.LIMITS["max_output_bytes"] - raw_size + 1
    )
    destination = args.output / "bounded-result.json"
    with pytest.raises(ValueError, match="budget exceeded"):
        module.write(destination, {"generated": True})
    assert not destination.exists()
    monkeypatch.setattr(
        module, "task_bytes", lambda _: module.LIMITS["max_output_bytes"] - raw_size
    )
    module.write(destination, {"generated": True})
    assert module.read(destination) == {"generated": True}


@pytest.mark.parametrize(
    "mutation", ["changed", "added", "removed", "sandbox_ancestor"]
)
def test_cli_configuration_drift_refused_before_dispatch(
    tmp_path, monkeypatch, mutation
):
    module = cli_module()
    existing, absent = tmp_path / "existing.toml", tmp_path / "absent.toml"
    existing.write_bytes(b'model = "generated-example"\n')
    context = {
        "consumers": {
            "configuration": {
                str(existing): preparation.file_hash(existing),
                str(absent): None,
            }
        }
    }
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    original_is_file = Path.is_file
    # This generated check never reads the workstation's actual configuration.
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda path: original_is_file(path) if path.is_relative_to(tmp_path) else False,
    )
    module.verify_cli_configuration(context, sandbox)
    if mutation == "changed":
        existing.write_bytes(b'model = "different-generated-example"\n')
    elif mutation == "added":
        absent.write_bytes(b"new = true\n")
    elif mutation == "removed":
        existing.unlink()
    elif mutation == "sandbox_ancestor":
        (tmp_path / ".codex").mkdir()
        (tmp_path / ".codex/config.toml").write_bytes(b"unexpected = true\n")
    with pytest.raises(ValueError, match="configuration"):
        module.verify_cli_configuration(context, sandbox)


def test_cli_retained_pytest_links_are_charged_without_following(tmp_path, monkeypatch):
    module, args = cli_module(), cli_args(tmp_path)
    linked = args.output / "current"
    linked.mkdir()
    (linked / "target-bytes-must-not-be-read").write_bytes(b"x" * 10000)
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p == linked or original(p))
    # Simulate the link marker portably; directory traversal must stop here.
    assert module.task_bytes(tmp_path) == linked.lstat().st_size


def collect_generated(
    module, tmp_path, code, *, message=b"generated", pipe=False, run_seconds=1
):
    prompt = tmp_path / "generated-input.txt"
    prompt.write_bytes(message)
    ready, release = tmp_path / "generated-ready", tmp_path / "generated-release"
    bootstrap = "\n".join(
        [
            "import time; from pathlib import Path",
            f"Path({str(ready)!r}).write_bytes(b'ready')",
            "began=time.monotonic()",
            f"while not Path({str(release)!r}).exists():",
            " if time.monotonic()-began>5: raise TimeoutError('generated handshake')",
            " time.sleep(.005)",
            f"exec({code!r})",
        ]
    )
    with prompt.open("rb") as incoming:
        child = subprocess.Popen(
            [sys.executable, "-c", bootstrap],
            cwd=tmp_path,
            stdin=subprocess.PIPE if pipe else incoming,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    original_identity = module.identity

    def release_after_identity(process=None):
        row = original_identity(process)
        if not release.exists():
            release.write_bytes(b"start")
        return row

    try:
        initialized = time.monotonic()
        while not ready.exists() and child.poll() is None:
            assert time.monotonic() - initialized < 5, "Generated startup timed out"
            time.sleep(0.005)
        assert ready.exists(), "Generated interpreter exited before initialization"
        # macOS Python launchers can exec the framework interpreter during
        # startup. Observe the stable test program before releasing its body.
        module.identity = release_after_identity
        began = time.monotonic()
        receipt = module.collect(
            child, message.decode(), tmp_path, time.time() + 120 + run_seconds
        )
        assert time.monotonic() - began < 4, receipt
        return receipt
    finally:
        module.identity = original_identity
        # Every generated program self-exits within 2.5 seconds; observe the
        # exact Popen handle without overriding an intentionally refused signal.
        if child.poll() is None:
            child.wait(timeout=8)  # Includes a failed startup handshake.


def test_cli_real_file_input_avoids_stalled_pipe_and_preserves_output(tmp_path):
    module = cli_module()
    receipt = collect_generated(
        module,
        tmp_path,
        "import sys,time; time.sleep(.15); print(len(sys.stdin.buffer.read()),flush=True)",
        message=b"x" * (256 * 1024),
    )
    assert receipt["exit_code"] == 0 and not receipt["bounded_stop"], receipt
    assert receipt["stdin_error"] is None and receipt["pipes_reached_eof"]
    assert receipt["collection_errors"] == []
    assert receipt["all_observed_processes_absent"]
    raw = (tmp_path / "events.jsonl").read_bytes()
    assert raw.strip() == b"262144"
    assert receipt["stdout"]["sha256"] == preparation.digest(raw)
    assert receipt["stdout"]["bytes"] == len(raw)


def test_cli_real_unread_pipe_input_is_refused_without_blocking(tmp_path):
    module = cli_module()
    module.COLLECT_STOP_GRACE = 0.5
    receipt = collect_generated(
        module,
        tmp_path,
        "import time; time.sleep(2)",
        message=b"x" * (256 * 1024),
        pipe=True,
    )
    assert receipt["stdin_error"] == "pipe_input_refused"
    assert receipt["bounded_stop"]
    assert (tmp_path / "bounded-stop.json").is_file()


def test_cli_real_parent_exit_does_not_wait_for_descendant_pipe_eof(tmp_path):
    module = cli_module()
    module.COLLECT_DRAIN_GRACE = 0.1
    module.COLLECT_STOP_GRACE = 0.5
    receipt = collect_generated(
        module,
        tmp_path,
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c',"
        "'import time; print(123,flush=True); time.sleep(2.5)']); "
        "time.sleep(.4)",
    )
    assert receipt["bounded_stop"]
    assert len(receipt["observed_lifetimes"]) >= 2, receipt
    assert (tmp_path / "bounded-stop.json").is_file()
    with pytest.raises(ValueError, match="cleanly"):
        module.event_identity(tmp_path, receipt)


@pytest.mark.parametrize("failure", ["read", "log_open", "start_write", "identity"])
def test_cli_real_collection_error_has_receipt_and_no_unbounded_wait(
    tmp_path, monkeypatch, failure
):
    module = cli_module()
    module.COLLECT_STOP_GRACE = 0.5
    if failure == "read":
        monkeypatch.setattr(
            module, "pipe_block", lambda _: (_ for _ in ()).throw(OSError("generated"))
        )
    elif failure == "log_open":
        (tmp_path / "events.jsonl").write_bytes(b"preserved")
    elif failure == "start_write":
        original_write = module.write

        def failed_start(path, value):
            if path.name == "start.json":
                raise OSError("generated write failure")
            original_write(path, value)

        monkeypatch.setattr(module, "write", failed_start)
    else:
        original = module.identity
        calls = []

        def denied(process=None):
            calls.append(True)
            if len(calls) > 1:
                raise psutil.AccessDenied()
            return original(process)

        monkeypatch.setattr(module, "identity", denied)
    receipt = collect_generated(module, tmp_path, "import time; time.sleep(.8)")
    assert receipt["bounded_stop"] and receipt["collection_errors"]
    assert module.STOP.is_set()
    if failure == "log_open":
        assert (tmp_path / "events.jsonl").read_bytes() == b"preserved"


@pytest.mark.parametrize("small_reads", [False, True])
def test_cli_real_output_overflow_preserves_cap_and_rejects_attempt(
    tmp_path, monkeypatch, small_reads
):
    module = cli_module()
    module.COLLECT_STOP_GRACE = 0.5
    if small_reads:
        original_read = module.os.read
        monkeypatch.setattr(
            module.os, "read", lambda fd, size: original_read(fd, min(size, 1024))
        )
    receipt = collect_generated(
        module,
        tmp_path,
        "import sys,time; sys.stdout.buffer.write(b'x'*(3*1024**2)); "
        "sys.stdout.flush(); time.sleep(2)",
        run_seconds=3,
    )
    assert receipt["bounded_stop"]
    assert receipt["stdout"]["truncated"], receipt
    assert (tmp_path / "events.jsonl").stat().st_size == 2 * 1024**2
    with pytest.raises(ValueError, match="cleanly"):
        module.event_identity(tmp_path, receipt)


def test_cli_exit_during_identity_read_is_reaped_before_comparison(
    tmp_path, monkeypatch
):
    module = cli_module()
    original_identity = module.identity
    calls = []

    def exit_during_read(process=None):
        row = original_identity(process)
        calls.append(True)
        if len(calls) == 2:
            process.wait(timeout=2)
            # POSIX can expose empty command/cwd fields during process exit.
            return {**row, "command": [], "cwd": ""}
        return row

    monkeypatch.setattr(module, "identity", exit_during_read)
    receipt = collect_generated(
        module, tmp_path, "import time; time.sleep(.1); print('complete',flush=True)"
    )
    assert receipt["exit_code"] == 0 and not receipt["bounded_stop"], receipt
    assert receipt["collection_errors"] == []
    assert receipt["pipes_reached_eof"] and receipt["all_observed_processes_absent"]
    assert (tmp_path / "events.jsonl").read_bytes().strip() == b"complete"


def test_cli_live_identity_mismatch_still_refuses_signals(tmp_path, monkeypatch):
    module = cli_module()
    module.COLLECT_STOP_GRACE = 0.2
    original_identity = module.identity
    calls = []

    def changed_live(process=None):
        row = original_identity(process)
        calls.append(True)
        return {**row, "command": ["changed"]} if len(calls) > 1 else row

    monkeypatch.setattr(module, "identity", changed_live)
    receipt = collect_generated(module, tmp_path, "import time; time.sleep(.4)")
    assert receipt["bounded_stop"] and receipt["collection_errors"]
    assert module.STOP.is_set()
    signals = module.read(tmp_path / "bounded-stop.json")["signals"]
    assert signals and all(s["result"] == "unverified_ValueError" for s in signals)


def test_cli_unresolved_pipe_fences_next_dispatch_even_after_parent_exit(
    tmp_path, monkeypatch
):
    module = cli_module()
    module.COLLECT_DRAIN_GRACE = 0.1
    module.COLLECT_STOP_GRACE = 0.2
    monkeypatch.setattr(module, "pipe_block", lambda _: None)
    receipt = collect_generated(module, tmp_path, "import time; time.sleep(.15)")
    assert receipt["exit_code"] == 0
    assert receipt["all_observed_processes_absent"]
    assert not receipt["pipes_reached_eof"] and receipt["bounded_stop"]
    assert module.STOP.is_set()
    with pytest.raises(ValueError, match="cleanly"):
        module.event_identity(tmp_path, receipt)
