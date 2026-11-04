"""Generated source metadata and readings only; no original scientific inputs."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from badminton import shuttle_scene_review as review
from badminton import shuttle_scene_support as support

FIXTURE_PATH = Path(__file__).with_name("test_shuttle_scene_review.py")
SPEC = importlib.util.spec_from_file_location(
    "support_generated_fixtures", FIXTURE_PATH
)
fixtures = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixtures)


def generated(*, repeated=False, overlap=False, mutate=None):
    gallery, plan, protocol = fixtures.fixture(repeated=repeated, overlap=overlap)
    schedule = review.prepare_schedule(gallery, plan, protocol)
    a, b = (fixtures.results(schedule, lane) for lane in review.LANES)
    if mutate:
        mutate(a, b)
    lanes = [
        review.assemble_lane(schedule, rows, lane)
        for rows, lane in zip((a, b), review.LANES)
    ]
    original = review.compare_lanes(schedule, *lanes)
    cases = [
        {
            "id": g["view"]["case_ids"][0],
            "video_id": "SOURCE",
            "frame": g["view"]["start_frame"] + 1,
        }
        for g in gallery["galleries"]
    ]
    cameras = [
        [{"start_frame": g["view"]["start_frame"], "end_frame": g["view"]["end_frame"]}]
        for g in gallery["galleries"]
    ]
    return [gallery, plan, protocol, *lanes, original, cases, cameras]


def test_complete_generated_views_and_all_denominators():
    args = generated()
    public, private = support.census(*args)
    assert public["views"] == {
        "known_scene_complete": 2,
        "live_stable_camera_complete": 2,
        "known_mixed_or_excluded_complete": 0,
        "incomplete_scene_evidence": 0,
    }
    assert public["denominators"] == {
        "views": 2,
        "cases": 2,
        "sheets": 4,
        "frame_occurrences": 40,
        "unique_source_frames": 40,
        "declared_partitions": 4,
    }
    assert public["occurrence_categories"]["live_same_camera"] == 40
    assert public["review_gaps"]["frame_occurrences"] == 0
    assert public["hypothetical_original_batch_cost"]["one_pass_sessions"] == 0
    assert len(private["occurrences"]) == 40
    assert public["eligibility"] == support.ELIGIBILITY
    assert public["complete_independent_rally_references"] == "0/2"


def test_supported_center_never_certifies_whole_view():
    def mutate(a, b):
        for rows in (a, b):
            text = rows[0]["document"]["sheets"][0]["scene_codes"]
            rows[0]["document"]["sheets"][0]["scene_codes"] = text[:3] + "U" + text[4:]

    public, _ = support.census(*generated(mutate=mutate))
    assert public["cases"]["center_known_agreement"] == 2
    assert public["cases"]["whole_view_known_scene_complete"] == 1
    assert public["review_gaps"]["frame_occurrences"] == 1
    assert public["hypothetical_original_batch_cost"]["one_pass_sessions"] == 1


@pytest.mark.parametrize("code,bucket", [("R", "replay"), ("N", "non_play")])
def test_complete_known_excluded_scenes_are_not_live(code, bucket):
    def mutate(a, b):
        for rows in (a, b):
            for row in rows:
                for sheet in row["document"]["sheets"]:
                    sheet["scene_codes"] = code * len(sheet["scene_codes"])

    public, _ = support.census(*generated(mutate=mutate))
    assert public["views"]["known_scene_complete"] == 2
    assert public["views"]["known_mixed_or_excluded_complete"] == 2
    assert public["views"]["live_stable_camera_complete"] == 0
    assert public["occurrence_categories"][bucket] == 40
    assert public["review_gaps"]["frame_occurrences"] == 0


def test_supported_edit_keeps_known_scene_but_breaks_stable_view():
    def mutate(a, b):
        for rows in (a, b):
            sheet = rows[0]["document"]["sheets"][0]
            sheet["transition_codes"] = (
                sheet["transition_codes"][:2] + "C" + sheet["transition_codes"][3:]
            )

    public, private = support.census(*generated(mutate=mutate))
    assert public["views"]["known_scene_complete"] == 2
    assert public["views"]["live_stable_camera_complete"] == 1
    assert private["views"][0]["supported_edit_occurrences"] == 1
    assert public["occurrence_categories"]["live_edit"] == 1


def test_declared_camera_boundary_is_preserved_without_inventing_scene_edit():
    args = generated()
    args[-1][0] = [
        {"start_frame": 0, "end_frame": 2},
        {"start_frame": 2, "end_frame": 35},
    ]
    public, private = support.census(*args)
    assert public["views"]["known_scene_complete"] == 2
    assert public["views"]["live_stable_camera_complete"] == 1
    assert private["views"][0]["declared_camera_boundaries"] == [2]
    assert private["views"][0]["supported_edit_occurrences"] == 0


@pytest.mark.parametrize("status", ["failed", "missing"])
def test_failed_or_missing_sessions_retain_full_missing_denominators(status):
    def mutate(a, b):
        if status == "missing":
            a.pop(0)
        else:
            a[0].update(status="failed", thread_id=None, document=None)

    public, private = support.census(*generated(mutate=mutate))
    assert public["denominators"]["frame_occurrences"] == 40
    assert public["occurrence_categories"]["unavailable"] == 35
    assert public["views"]["known_scene_complete"] == 1
    assert (
        public["historical_original_sessions"]["independent_a"][
            "failed_sessions" if status == "failed" else "missing_sessions"
        ]
        == 1
    )
    attempt = private["occurrences"][0]["original_attempts"]["independent_a"][0]
    assert attempt["status"] == ("unattempted" if status == "missing" else "failed")
    assert attempt["batch_index"] == 0
    assert (attempt["session_id"] is None) == (status == "missing")


def test_overlap_unknown_and_cross_view_conflicts_stay_unresolved():
    public, private = support.census(*generated(overlap=True))
    assert public["occurrence_categories"]["conflict"] >= 1
    assert public["views"]["known_scene_complete"] < 2
    assert len(private["occurrences"]) == 40
    overlapping = [
        row for row in private["occurrences"] if len(row["original_batch_indices"]) > 1
    ]
    assert overlapping
    for row in overlapping:
        for attempts in row["original_attempts"].values():
            assert [a["batch_index"] for a in attempts] == row["original_batch_indices"]

    def mutate(a, b):
        for rows in (a, b):
            for sheet in rows[1]["document"]["sheets"]:
                sheet["scene_codes"] = "R" * len(sheet["scene_codes"])

    public, _ = support.census(*generated(repeated=True, mutate=mutate))
    assert public["denominators"]["frame_occurrences"] == 59
    assert public["denominators"]["unique_source_frames"] == 40
    assert public["occurrence_categories"]["conflict"] > 0
    assert (
        public["review_gaps"]["frame_occurrences"]
        > public["review_gaps"]["unique_source_frames"]
    )


@pytest.mark.parametrize(
    "change",
    ["frame", "pts", "source", "gap", "case_end", "case_source", "case_duplicate"],
)
def test_clock_source_coverage_and_half_open_membership_guards(change):
    args = generated()
    if change in ("frame", "pts", "source"):
        key = {"frame": "frame", "pts": "pts", "source": "source_id"}[change]
        args[5]["records"][0][key] = "changed"
    elif change == "gap":
        args[0]["galleries"][0]["sheets"][0]["members"].pop()
        fixtures.reseal(args[0], args[1], args[2])
    elif change == "case_end":
        args[-2][0]["frame"] = 35
    elif change == "case_source":
        args[-2][0]["video_id"] = "other"
    else:
        args[-2][1]["id"] = args[-2][0]["id"]
    with pytest.raises(ValueError):
        support.census(*args)


def test_public_report_has_only_aggregate_values_and_costs_never_authorize_dispatch():
    public, _ = support.census(*generated())
    raw = json.dumps(public)
    for forbidden in (
        "SOURCE",
        "case-0",
        "view-0",
        "source_reason",
        "session_id",
        "thread_id",
        "sheet_path",
    ):
        assert forbidden not in raw
    assert public["hypothetical_original_batch_cost"]["authorized_schedule"] is False


def bound_fixture(tmp_path):
    for name in ("original", "preparation", "historical"):
        (tmp_path / name).mkdir()
    path = tmp_path / "original/metadata.json"
    path.write_bytes(support.encode({"generated": True}))
    bindings = {
        "roots": {k: k for k in ("original", "preparation", "historical")},
        "inputs": {
            "example": {
                "path": "original/metadata.json",
                "sha256": support.digest(path.read_bytes()),
                "mode": "json",
            }
        },
        "absent": ["original/missing.json"],
    }
    return bindings


def commitment(bindings):
    return support.digest(
        support.encode(
            {
                "inputs": {
                    k: {f: v[f] for f in ("sha256", "mode")}
                    for k, v in bindings["inputs"].items()
                },
                "absent": bindings["absent"],
                "roots": bindings["roots"],
            }
        )
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "bytes",
        "appeared",
        "extra",
        "path_escape",
        "image",
        "mode",
        "absence_removed",
        "root_escape",
    ],
)
def test_bound_evidence_changes_and_forbidden_bytes_fail(tmp_path, mutation):
    bindings = bound_fixture(tmp_path)
    frozen = commitment(bindings)
    if mutation == "bytes":
        (tmp_path / "original/metadata.json").write_text("changed")
    elif mutation in ("appeared", "extra"):
        (
            tmp_path
            / (
                "original/missing.json"
                if mutation == "appeared"
                else "original/extra.json"
            )
        ).write_text("{}")
    elif mutation == "path_escape":
        bindings["inputs"]["example"]["path"] = "../outside.json"
    elif mutation == "image":
        path = tmp_path / "original/image.jpg"
        path.write_bytes(b"image must not be read")
        bindings["inputs"]["example"].update(
            path="original/image.jpg", sha256=support.digest(path.read_bytes())
        )
        frozen = commitment(bindings)
    elif mutation == "mode":
        bindings["inputs"]["example"]["mode"] = "opaque"
    elif mutation == "absence_removed":
        bindings["absent"] = []
    else:
        bindings["roots"]["original"] = "../outside"
        frozen = commitment(bindings)
    with pytest.raises(ValueError):
        support.EvidenceReader(tmp_path, bindings, frozen)


def test_reader_rechecks_after_source_mutation_and_never_decodes_opaque(tmp_path):
    bindings = bound_fixture(tmp_path)
    reader = support.EvidenceReader(tmp_path, bindings, commitment(bindings))
    assert reader.read("example") == {"generated": True}
    (tmp_path / "original/metadata.json").write_text("changed")
    with pytest.raises(ValueError):
        reader.read("example")
    with pytest.raises(ValueError):
        reader.verify_unchanged()
    bindings["inputs"]["example"].update(
        mode="opaque", sha256=support.digest(b"changed")
    )
    reader = support.EvidenceReader(tmp_path, bindings, commitment(bindings))
    with pytest.raises(ValueError, match="declared"):
        reader.read("example")


def test_changed_consumer_hash_membership_and_source_are_refused(tmp_path):
    for name in support.CONSUMERS:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"generated\n")
    protocol = {
        "consumer_sha256": {
            n: support.digest(b"generated\n") for n in support.CONSUMERS
        }
    }
    support.verify_consumers(tmp_path, protocol)
    bad = copy.deepcopy(protocol)
    bad["consumer_sha256"].pop(support.CONSUMERS[0])
    with pytest.raises(ValueError):
        support.verify_consumers(tmp_path, bad)
    (tmp_path / support.CONSUMERS[0]).write_text("changed")
    with pytest.raises(ValueError):
        support.verify_consumers(tmp_path, protocol)


def chain_fixture(tmp_path, defect=None):
    """Build the full generated historical hash/terminal/session chain."""
    checkout = Path(__file__).resolve().parents[1]
    roots = {key: key for key in ("original", "preparation", "historical")}
    for name in roots.values():
        (tmp_path / name).mkdir()

    def unknown(a, b):
        for rows in (a, b):
            sheet = rows[0]["document"]["sheets"][0]
            sheet["scene_codes"] = (
                sheet["scene_codes"][:3] + "U" + sheet["scene_codes"][4:]
            )

    gallery, plan, old, a, b, original, cases, cameras = generated(mutate=unknown)

    def put(relative, value, raw=False):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if raw else support.encode(value))
        return support.digest(path.read_bytes())

    views = [
        {k: v for k, v in g["view"].items() if k not in ("index", "partition_starts")}
        for g in gallery["galleries"]
    ]
    diagnostics = {
        "eligibility": support.ELIGIBILITY,
        "methods": {
            method: {
                "views": [
                    {
                        "view": view,
                        "segments": [
                            {"start_frame": start, "end_frame": end}
                            for start, end in zip(
                                g["view"]["partition_starts"],
                                [*g["view"]["partition_starts"][1:], view["end_frame"]],
                            )
                        ],
                        "camera_metadata": camera,
                    }
                    for view, g, camera in zip(views, gallery["galleries"], cameras)
                ],
                "cases": [{"case": case} for case in cases],
            }
            for method in ("control", "decoder", "convolution")
        },
    }
    diag_hash = put("preparation/diagnostics.json", diagnostics)
    inventory = {
        "schema_version": 1,
        "origin_diagnostics_sha256": diag_hash,
        "views": views,
        "cases": cases,
    }
    inv_hash = put("preparation/inventory.json", inventory)
    prep = copy.deepcopy(old)
    prep["eligibility"] = support.ELIGIBILITY
    prep["artifacts"].update(
        {"familiar-scene-inventory": inv_hash, "context-audit-diagnostics": diag_hash}
    )
    prep_hash = put("preparation/protocol.json", prep)
    old["eligibility"] = support.ELIGIBILITY
    old["artifacts"].update(
        {
            "scene-gallery": put("preparation/gallery.json", gallery),
            "scene-plan": put("preparation/plan.json", plan),
            "scene-context": put(
                "preparation/context.json", {"protocol_sha256": prep_hash}
            ),
            "scene-aggregate": put("preparation/aggregate.json", {"generated": True}),
        }
    )
    audit = {
        "status": "audited",
        "gallery_sha256": old["artifacts"]["scene-gallery"],
        "plan_sha256": old["artifacts"]["scene-plan"],
        "aggregate_sha256": old["artifacts"]["scene-aggregate"],
    }
    old["artifacts"]["scene-audit"] = put("preparation/audit.json", audit)
    put("preparation/terminal.json", {"summary": audit})
    old_hash = put("preparation/review-protocol.json", old)
    schedule = review.prepare_schedule(gallery, plan, old)
    consumer_hashes = {}
    for name in support.CONSUMERS[:3]:
        consumer_hashes[name] = put(
            "historical/" + name, (checkout / name).read_bytes(), raw=True
        )
    put(
        "original/context.json",
        {
            "protocol_sha256": old_hash,
            "source_commit": "b" * 40,
            "schedule_sha256": support.digest(support.encode(schedule)),
            "consumers": {"files": consumer_hashes},
        },
    )
    for lane in (a, b):
        put(f"original/{lane['lane']}.json", lane)
    comparison_hash = put("original/comparison-original.json", original)
    history = {}
    for lane in (*support.review.LANES, support.review.ADJUDICATION):
        rows = (
            a["results"]
            if lane == a["lane"]
            else b["results"]
            if lane == b["lane"]
            else [
                {
                    "batch_index": 0,
                    "session_id": "generated-adjudication",
                    "thread_id": None,
                    "status": "failed",
                    "document": None,
                }
            ]
        )
        for result in rows:
            batch = schedule[result["batch_index"]]
            folder = f"original/sessions/{lane}/{batch['index']:03d}"
            images = [
                {k: s[k] for k in ("path", "sha256", "bytes")} for s in batch["images"]
            ]
            put(
                folder + "/reservation.json",
                {
                    "lane": lane,
                    "batch_index": batch["index"],
                    "session_id": result["session_id"],
                    "images": images,
                    "image_bytes": sum(s["bytes"] for s in images),
                    "replacement_allowed": False,
                },
            )
            result = copy.deepcopy(result)
            thread = result["thread_id"] or "generated-failed-thread"
            if lane == "adjudication" and defect == "duplicate_failed_thread":
                thread = a["results"][0]["thread_id"]
            events = [
                {"type": "thread.started", "thread_id": thread},
                {"type": "turn.completed"}
                if result["status"] == "completed"
                else {"type": "turn.failed", "error": {"message": "Generated failure"}},
            ]
            if lane == "independent_a" and batch["index"] == 0 and defect == "tool":
                events.insert(
                    1, {"type": "item.completed", "item": {"type": "command_execution"}}
                )
            if lane == "adjudication" and defect == "failed_labels":
                result["document"] = {"invalid": "Failed output cannot label frames"}
            put(
                folder + "/events.jsonl",
                b"".join(support.encode(e).replace(b"\n", b"") + b"\n" for e in events),
                raw=True,
            )
            finish = {
                "exit_code": 0 if result["status"] == "completed" else 1,
                "all_observed_processes_absent": True,
                "stdin_error": None,
                "bounded_stop": False,
                "pipes_reached_eof": True,
                "collection_errors": [],
                "stdout": {"truncated": False},
                "stderr": {"truncated": False},
            }
            if lane == "independent_a" and batch["index"] == 0 and defect == "terminal":
                finish["all_observed_processes_absent"] = False
            put(folder + "/finish.json", finish)
            put(folder + "/result.json", result)
            if result["status"] == "completed":
                put(folder + "/original-final.json", result["document"])
        history[lane] = {
            "successful": sum(r["status"] == "completed" for r in rows),
            "failed": sum(r["status"] == "failed" for r in rows),
            "unattempted_schedule_slots": len(schedule) - len(rows),
            "reserved_image_bytes": sum(
                s["bytes"] for r in rows for s in schedule[r["batch_index"]]["images"]
            ),
            "unresolved_terminal_metadata": 0,
        }
    sealed = {
        name: support.preparation.file_hash(tmp_path / "original" / name)
        for name in support.tree_files(tmp_path / "original")
        if name.startswith(("sessions/independent_a/", "sessions/independent_b/"))
    }
    if defect == "session_seal":
        sealed.pop(next(iter(sealed)))
    seal = {
        "sessions": sealed,
        "lanes": {
            lane["lane"]: support.preparation.file_hash(
                tmp_path / f"original/{lane['lane']}.json"
            )
            for lane in (a, b)
        },
        "comparison_sha256": comparison_hash,
    }
    seal_hash = put("original/original-streams-seal.json", seal)
    put(
        "original/originals/terminal.json",
        {
            "summary": {
                "status": "originals_sealed",
                "seal_sha256": seal_hash,
                "aggregate": original["aggregate"],
            }
        },
    )
    aliases = {
        "original/context.json": "review_context",
        "original/independent_a.json": "lane_a",
        "original/independent_b.json": "lane_b",
        "original/comparison-original.json": "comparison",
        "original/original-streams-seal.json": "original_seal",
        "original/originals/terminal.json": "original_terminal",
        "preparation/protocol.json": "preparation_protocol",
        "preparation/review-protocol.json": "review_protocol",
        "preparation/context.json": "preparation_context",
        "preparation/audit.json": "preparation_audit",
        "preparation/terminal.json": "preparation_terminal",
        "preparation/aggregate.json": "preparation_aggregate",
        "preparation/gallery.json": "gallery",
        "preparation/plan.json": "plan",
        "preparation/inventory.json": "inventory",
        "preparation/diagnostics.json": "diagnostics",
    }
    bindings = {
        "roots": roots,
        "inputs": {},
        "absent": [
            "original/adjudication/terminal.json",
            "original/audit/terminal.json",
            "original/comparison-final.json",
            "original/adjudication.json",
        ],
    }
    files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    for i, path in enumerate(files):
        name = path.relative_to(tmp_path).as_posix()
        bindings["inputs"][aliases.get(name, f"evidence-{i:03d}")] = {
            "path": name,
            "sha256": support.preparation.file_hash(path),
            "mode": "opaque"
            if name.startswith("historical/")
            else "events"
            if path.suffix == ".jsonl"
            else "json",
        }
    protocol = {
        "schema_version": 1,
        "task": 376,
        "eligibility": support.ELIGIBILITY,
        "limits": {
            "image_bytes": 0,
            "assessor_sessions": 0,
            "max_output_bytes": 1024**2,
        },
        "inventory_sha256": commitment(bindings),
        "historical_source_commit": "b" * 40,
        "denominators": old["denominators"],
        "consumer_sha256": {
            n: support.preparation.file_hash(checkout / n) for n in support.CONSUMERS
        },
        "expected_original_status_counts": original["aggregate"]["status_counts"],
        "expected_historical_lanes": history,
    }
    protocol.update(
        evidence_sha256={
            k: {f: v[f] for f in ("sha256", "mode")}
            for k, v in bindings["inputs"].items()
        },
        absence_commitment_sha256=support.digest(support.encode(bindings["absent"])),
        namespace_commitment_sha256=support.digest(support.encode(bindings["roots"])),
    )
    return protocol, bindings


def test_complete_generated_historical_chain_and_unsealed_failed_adjudication(tmp_path):
    protocol, bindings = chain_fixture(tmp_path)
    reader = support.EvidenceReader(tmp_path, bindings, protocol["inventory_sha256"])
    public, private = support.audit_bound(reader, protocol)
    assert public["views"]["known_scene_complete"] == 1
    assert public["historical_execution"]["global_sessions"] == 5
    assert public["historical_execution"]["global_threads"] == 5
    assert (
        public["historical_execution"]["lanes"]["adjudication"][
            "unattempted_schedule_slots"
        ]
        == 1
    )
    assert (
        public["historical_execution"]["adjudication_terminal_seal_available"] is False
    )
    assert len(private["cases"]) == 2
    attempted = private["occurrences"][0]["adjudication_attempts"][0]
    assert attempted["status"] == "failed"
    assert attempted["session_id"] and attempted["thread_ids"]
    unattempted = private["occurrences"][-1]["adjudication_attempts"][0]
    assert unattempted["status"] == "unattempted"
    assert unattempted["session_id"] is None
    assert not (tmp_path / "original/adjudication/terminal.json").exists()


@pytest.mark.parametrize(
    "defect,message",
    [
        ("duplicate_failed_thread", "global assessor thread"),
        ("failed_labels", "Failed session"),
        ("tool", "clean independent terminal"),
        ("terminal", "clean independent terminal"),
        ("session_seal", "seal membership"),
    ],
)
def test_full_chain_refuses_semantically_invalid_generated_evidence(
    tmp_path, defect, message
):
    protocol, bindings = chain_fixture(tmp_path, defect)
    reader = support.EvidenceReader(tmp_path, bindings, protocol["inventory_sha256"])
    with pytest.raises(ValueError, match=message):
        support.audit_bound(reader, protocol)


def test_actual_offline_cli_produces_private_and_public_artifacts_exclusively(tmp_path):
    protocol, bindings = chain_fixture(tmp_path)
    protocol_path, bindings_path = (
        tmp_path / "protocol.json",
        tmp_path / "bindings.json",
    )
    protocol_path.write_bytes(support.encode(protocol))
    bindings_path.write_bytes(support.encode(bindings))
    output = tmp_path / "output"
    script = (
        Path(__file__).resolve().parents[1] / "scripts/audit_shuttle_scene_support.py"
    )
    command = [
        sys.executable,
        str(script),
        "--root",
        str(tmp_path),
        "--protocol",
        str(protocol_path),
        "--bindings",
        str(bindings_path),
        "--output",
        str(output),
    ]
    run = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["completed"] is True
    receipt = support.decode((output / "completion.json").read_bytes())
    assert receipt["completed"] and receipt["image_bytes_read"] == 0
    for name, expected in receipt["outputs"].items():
        assert support.digest((output / name).read_bytes()) == expected
    assert "source_reason" not in (output / "aggregate.json").read_text()
    assert subprocess.run(command, capture_output=True, timeout=30).returncode != 0
    assert not (tmp_path / "original/adjudication/terminal.json").exists()


def test_public_inventory_hashes_and_absence_commitments_are_checked(tmp_path):
    protocol, bindings = chain_fixture(tmp_path)
    support.verify_public_inventory(protocol, bindings)
    for field in (
        "evidence_sha256",
        "absence_commitment_sha256",
        "namespace_commitment_sha256",
    ):
        changed = copy.deepcopy(protocol)
        changed[field] = {}
        with pytest.raises(ValueError, match="prospective evidence"):
            support.verify_public_inventory(changed, bindings)


def load_cli():
    path = (
        Path(__file__).resolve().parents[1] / "scripts/audit_shuttle_scene_support.py"
    )
    spec = importlib.util.spec_from_file_location("scene_support_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "mutation",
    ["input", "protocol", "bindings", "consumer", "budget", "protected_output"],
)
def test_cli_refuses_mutation_or_budget_without_completion_receipt(
    tmp_path, monkeypatch, mutation
):
    cli = load_cli()
    protocol, bindings = chain_fixture(tmp_path)
    if mutation == "budget":
        protocol["limits"]["max_output_bytes"] = 1
    protocol_path, bindings_path = (
        tmp_path / "protocol.json",
        tmp_path / "bindings.json",
    )
    protocol_path.write_bytes(support.encode(protocol))
    bindings_path.write_bytes(support.encode(bindings))
    output = tmp_path / (
        "original/output" if mutation == "protected_output" else "output"
    )
    args = [
        "--root",
        str(tmp_path),
        "--protocol",
        str(protocol_path),
        "--bindings",
        str(bindings_path),
        "--output",
        str(output),
    ]
    original_audit = support.audit_bound
    original_verify = support.verify_consumers
    changed = False

    def audit_then_mutate(*audit_args):
        nonlocal changed
        result = original_audit(*audit_args)
        if mutation == "input":
            (tmp_path / "preparation/inventory.json").write_bytes(b"{}")
        elif mutation == "protocol":
            protocol_path.write_bytes(b"{}")
        elif mutation == "bindings":
            bindings_path.write_bytes(b"{}")
        changed = True
        return result

    def verify(source, manifest):
        if changed and mutation == "consumer":
            raise ValueError("Generated consumer mutation")
        original_verify(source, manifest)

    monkeypatch.setattr(support, "audit_bound", audit_then_mutate)
    monkeypatch.setattr(support, "verify_consumers", verify)
    with pytest.raises(ValueError):
        cli.main(args)
    assert not (output / "completion.json").exists()


def test_source_mutation_during_last_validation_prevents_completion(
    tmp_path, monkeypatch
):
    cli = load_cli()
    protocol, bindings = chain_fixture(tmp_path)
    protocol_path, bindings_path = (
        tmp_path / "protocol.json",
        tmp_path / "bindings.json",
    )
    protocol_path.write_bytes(support.encode(protocol))
    bindings_path.write_bytes(support.encode(bindings))
    output = tmp_path / "output"
    original_verify = support.verify_consumers

    def verify(source, manifest):
        original_verify(source, manifest)
        if (output / "aggregate.json").exists():
            (tmp_path / "preparation/inventory.json").write_bytes(b"{}")

    monkeypatch.setattr(support, "verify_consumers", verify)
    with pytest.raises(ValueError):
        cli.main(
            [
                "--root",
                str(tmp_path),
                "--protocol",
                str(protocol_path),
                "--bindings",
                str(bindings_path),
                "--output",
                str(output),
            ]
        )
    assert (output / "aggregate.json").exists()
    assert not (output / "completion.json").exists()
