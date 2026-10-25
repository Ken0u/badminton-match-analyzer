"""Generated metadata only: no private source/label reads or image execution."""

import copy
import hashlib
import importlib.util
import json
import os
import time
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest
from badminton import rally_review_plan as review
from badminton import rally_temporal_context as temporal


def example(count=8, native_bytes=100, gallery_bytes=100, times=None, rotation=0):
    times = times if times is not None else [Fraction(n, 2) for n in range(count)]
    packet = {
        "source_id": "generated",
        "source_sha256": "a" * 64,
        "clock_sha256": "b" * 64,
        "eligibility": dict(temporal.ELIGIBILITY),
        "frames": [
            {
                "frame": n,
                "pts": time.numerator,
                "time_base": str(Fraction(1, time.denominator)),
                "time_s": float(time),
                "rotation": rotation,
                "source_size": [32, 24],
                "display_size": [24, 32] if rotation in (90, 270) else [32, 24],
                "orientation_error": None,
                "corrupt": False,
                "scene": "HISTORICAL_PRIVATE_SCENE",
                "actors": ["HISTORICAL_PRIVATE_ACTOR"],
                "image": {
                    "path": f"native/{n}.png",
                    "bytes": native_bytes,
                    "sha256": hashlib.sha256(str(n).encode()).hexdigest(),
                    "description": "HISTORICAL_PRIVATE_IMAGE_DESCRIPTION",
                },
            }
            for n, time in enumerate(times)
        ],
        "events": ["HISTORICAL_PRIVATE_EVENTS"],
    }
    gallery = gallery_for(packet, gallery_bytes)
    expected = {
        **{key: packet[key] for key in ("source_id", "source_sha256", "clock_sha256")},
        "packet_sha256": "c" * 64,
        "native_frame_count": len(times),
    }
    bindings = dict.fromkeys(review.BINDING_KEYS, "d" * 64)
    bindings["packet_sha256"] = expected["packet_sha256"]
    return packet, gallery, expected, bindings


def gallery_for(packet, size=100):
    plan = temporal.sample_plan(packet)
    selected = [sample["frame"] for sample in plan["samples"]]
    return {
        "schema_version": 1,
        "plan": plan,
        "historical_label": "HISTORICAL_PRIVATE_GALLERY_LABEL",
        "sheets": [
            {
                "path": f"sheet-{index:03d}.png",
                "sha256": hashlib.sha256(f"sheet-{index}".encode()).hexdigest(),
                "bytes": size,
                "size": list(temporal.SHEET),
                "frames": selected[start : start + 16],
                "description": "HISTORICAL_PRIVATE_SHEET_DESCRIPTION",
            }
            for index, start in enumerate(range(0, len(selected), 16))
        ],
    }


def run(data, **kwargs):
    return review.plan_source(
        data[0], data[1], expected_source=data[2], bindings=data[3], **kwargs
    )


def test_full_native_coverage_overlap_repeated_costs_and_three_prospective_lanes():
    data = example(count=9)
    before = copy.deepcopy(data)
    summary, private = run(data, max_images=4)
    assert data == before
    assert summary["native_frames"] == 9
    assert summary["sampled_frames"] == 5
    assert summary["unsampled_native_frames"] == 4
    assert summary["status"] == "planned"
    assert [batch["frames"] for batch in private["batches"]] == [
        [0, 1, 2],
        [2, 3, 4],
        [4, 5, 6],
        [6, 7, 8],
    ]
    assert [batch["overlap_frame"] for batch in private["batches"]] == [None, 2, 4, 6]
    assert [n for batch in private["batches"] for n in batch["new_frames"]] == list(
        range(9)
    )
    assert summary["native_image_bytes"] == 900
    assert summary["overlap_image_bytes"] == 300
    assert summary["gallery_image_bytes"] == 400
    assert summary["per_lane_image_bytes"] == 1600
    assert summary["per_lane_sessions"] == 4
    assert summary["proposed_sessions"] == 12
    assert summary["proposed_image_bytes"] == 4800
    assert (
        summary["actual_new_scientific_sessions"]
        == summary["actual_new_image_bytes"]
        == 0
    )
    assert summary["eligibility"] == temporal.ELIGIBILITY
    assert [lane["lane"] for lane in private["lane_manifests"]] == list(review.LANES)
    for lane in private["lane_manifests"]:
        assert lane["batch_indices"] == list(range(4))
        assert lane["execution_authorized"] is False
    assert private["output_contract"]["schema_version"] == 1
    assert private["output_contract"] == review.OUTPUT_CONTRACT


def test_exact_byte_limit_includes_gallery_and_every_overlap_membership():
    summary, private = run(example(), max_bytes=300)
    assert summary["per_lane_sessions"] == 7
    assert summary["per_lane_image_bytes"] == 2100
    assert all(batch["total_image_bytes"] == 300 for batch in private["batches"])
    assert all(batch["distinct_images"] == 3 for batch in private["batches"])


@pytest.mark.parametrize(
    "max_bytes,max_images", [(199, 20), (299, 20), (900, 1), (900, 2)]
)
def test_infeasible_minimum_batch_clears_partial_plan_and_keeps_denominator(
    max_bytes, max_images
):
    summary, private = run(example(), max_bytes=max_bytes, max_images=max_images)
    assert summary["status"] == "unavailable"
    assert summary["reason"] == "oversized_minimum_batch"
    assert summary["native_frames"] == len(private["frames"]) == 8
    assert summary["sampled_frames"] == 5
    assert private["batches"] == []
    assert summary["proposed_sessions"] == summary["proposed_image_bytes"] == 0
    assert all(lane["status"] == "unavailable" for lane in private["lane_manifests"])


def test_gallery_boundary_context_counts_both_sheets_and_nearest_tie_uses_lower_ordinal():
    data = example(count=38, native_bytes=1, gallery_bytes=1)
    summary, private = run(data)
    contexts = {row["frame"]: row for row in private["navigation_context"]}
    assert contexts[31] == {"frame": 31, "nearest_sample": 30, "sheet": 0}
    assert contexts[32] == {"frame": 32, "nearest_sample": 32, "sheet": 1}
    crossing = next(
        batch
        for batch in private["batches"]
        if 31 in batch["frames"] and 32 in batch["frames"]
    )
    assert crossing["gallery_sheets"] == [0, 1]
    assert crossing["gallery_image_bytes"] == 2
    assert crossing["distinct_images"] == len(crossing["frames"]) + 2
    assert summary["native_frames"] == 38


def test_two_context_sheets_can_make_minimum_pair_unavailable_without_silent_omission():
    data = example(
        count=20,
        native_bytes=10,
        gallery_bytes=100,
        times=[Fraction(n) for n in range(20)],
    )
    summary, private = run(data, max_images=3)
    assert summary["status"] == "unavailable"
    assert private["blocked_native_frame"] == 16
    assert private["batches"] == []
    assert summary["native_frames"] == 20


def test_vfr_rational_times_and_rotated_native_geometry_are_retained():
    times = [
        Fraction(100),
        Fraction(1001, 10),
        Fraction(1009, 10),
        Fraction(1014, 10),
        Fraction(1018, 10),
        Fraction(102),
    ]
    data = example(times=times, rotation=90)
    summary, private = run(data)
    assert summary["sampled_frames"] == 3
    assert [row["nearest_sample"] for row in private["navigation_context"]] == [
        0,
        0,
        3,
        3,
        5,
        5,
    ]
    assert [row["pts"] for row in private["frames"]] == [
        row["pts"] for row in data[0]["frames"]
    ]
    assert [row["time_base"] for row in private["frames"]] == [
        row["time_base"] for row in data[0]["frames"]
    ]
    assert all(
        row["rotation"] == 90 and row["display_size"] == [24, 32]
        for row in private["frames"]
    )


def test_equal_native_times_use_lowest_sample_ordinal_for_navigation():
    data = example(times=[Fraction(0), Fraction(0), Fraction(1), Fraction(1)])
    _, private = run(data)
    assert [row["nearest_sample"] for row in private["navigation_context"]] == [
        0,
        0,
        2,
        2,
    ]


def reverse_dicts(value):
    if isinstance(value, dict):
        return {key: reverse_dicts(value[key]) for key in reversed(value)}
    if isinstance(value, list):
        return [reverse_dicts(child) for child in value]
    return value


def test_gallery_input_order_and_dictionary_order_do_not_change_plan():
    data = example(count=38)
    expected = run(data)
    data = reverse_dicts(list(data))
    data[1]["sheets"].reverse()
    assert run(data) == expected


def test_independent_manifests_whitelist_semantics_and_do_not_copy_private_labels():
    summary, private = run(example())
    result = json.dumps([summary, private])
    assert "HISTORICAL_PRIVATE" not in result
    for row in private["frames"]:
        assert "scene" not in row and "actors" not in row
        assert "description" not in row["image"]
    assert "historical_label" not in private
    assert private["bindings"]["packet_sha256"] != private["canonical_packet_sha256"]


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "unordered", "boolean", "negative"]
)
def test_native_ordinals_and_full_denominator_are_strict(change):
    data = example()
    rows = data[0]["frames"]
    if change == "missing":
        rows.pop()
    elif change == "duplicate":
        rows[1]["frame"] = rows[0]["frame"]
    elif change == "unordered":
        rows.reverse()
    elif change == "boolean":
        rows[0]["frame"] = False
    else:
        rows[0]["frame"] = -1
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "clock",
        "count",
        "bool_count",
        "packet_hash",
        "binding_hash",
        "missing_binding",
        "extra_binding",
    ],
)
def test_expected_source_and_exact_raw_provenance_bindings_are_required(change):
    data = example()
    if change == "source":
        data[2]["source_id"] = "other"
    elif change == "clock":
        data[2]["clock_sha256"] = "e" * 64
    elif change == "count":
        data[2]["native_frame_count"] = 7
    elif change == "bool_count":
        data[2]["native_frame_count"] = True
    elif change == "packet_hash":
        data[3]["packet_sha256"] = "e" * 64
    elif change == "binding_hash":
        data[3]["prior_audit_sha256"] = "broken"
    elif change == "missing_binding":
        del data[3]["consumer_sha256"]
    else:
        data[3]["historical_labels"] = "e" * 64
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize(
    "change",
    [
        "plan_clock",
        "plan_bool",
        "sheet_members",
        "sheet_bool",
        "sheet_hash",
        "sheet_size",
        "sheet_missing",
        "sheet_duplicate",
        "schema_bool",
    ],
)
def test_gallery_provenance_and_membership_corruption_are_rejected(change):
    data = example()
    gallery = data[1]
    if change == "plan_clock":
        gallery["plan"]["clock_sha256"] = "e" * 64
    elif change == "plan_bool":
        gallery["plan"]["samples"][0]["frame"] = False
    elif change == "sheet_members":
        gallery["sheets"][0]["frames"].pop()
    elif change == "sheet_bool":
        gallery["sheets"][0]["frames"][0] = False
    elif change == "sheet_hash":
        gallery["sheets"][0]["sha256"] = "missing"
    elif change == "sheet_size":
        gallery["sheets"][0]["size"] = [1, 1]
    elif change == "sheet_missing":
        gallery["sheets"].clear()
    elif change == "sheet_duplicate":
        gallery["sheets"].append(copy.deepcopy(gallery["sheets"][0]))
    else:
        gallery["schema_version"] = True
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("path", "../escape.png"),
        ("path", "/absolute.png"),
        ("path", "C:/drive.png"),
        ("path", "native\\0.png"),
        ("path", "native//0.png"),
        ("path", "."),
        ("bytes", True),
        ("bytes", 0),
        ("sha256", "z" * 64),
    ],
)
def test_native_image_identity_is_safe_and_cost_is_strict(field, value):
    data = example()
    data[0]["frames"][0]["image"][field] = value
    data[1]["plan"]["packet_sha256"] = temporal.fingerprint(data[0])
    with pytest.raises(ValueError):
        run(data)


def test_same_native_path_cannot_silently_collapse_two_frame_images():
    data = example()
    data[0]["frames"][1]["image"]["path"] = data[0]["frames"][0]["image"]["path"]
    data[1].update(gallery_for(data[0]))
    with pytest.raises(ValueError, match="Duplicate native image"):
        run(data)


@pytest.mark.parametrize("change", ["image", "corrupt", "orientation_error"])
def test_unavailable_native_evidence_retains_every_frame_and_prevents_partial_schedule(
    change,
):
    data = example()
    row = data[0]["frames"][3]
    if change == "image":
        row["image"] = None
    elif change == "corrupt":
        row["corrupt"] = True
    else:
        row["orientation_error"] = "unsupported display orientation"
    data[1].update(gallery_for(data[0]))
    summary, private = run(data)
    assert summary["reason"] == "unavailable_native_input"
    assert summary["native_frames"] == 8
    assert summary["available_native_frames"] == 7
    assert len(private["frames"]) == 8 and private["batches"] == []
    assert summary["proposed_image_bytes"] == summary["proposed_sessions"] == 0


@pytest.mark.parametrize(
    "change",
    [
        "pts_bool",
        "time_disagrees",
        "nonfinite",
        "rotation_bool",
        "geometry",
        "corrupt_int",
        "eligibility",
    ],
)
def test_native_clock_orientation_and_eligibility_corruption_rejected(change):
    data = example()
    row = data[0]["frames"][0]
    if change == "pts_bool":
        row["pts"] = False
    elif change == "time_disagrees":
        row["time_s"] = 9
    elif change == "nonfinite":
        row["time_s"] = float("inf")
    elif change == "rotation_bool":
        row["rotation"] = False
    elif change == "geometry":
        row["display_size"] = [24, 32]
    elif change == "corrupt_int":
        row["corrupt"] = 0
    else:
        data[0]["eligibility"]["training_allowed"] = True
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize(
    "raw",
    [
        '{"frame":1,"frame":2}',
        '{"x":{"a":1,"a":2}}',
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":-Infinity}',
        '{"x":1e999}',
        '{"x":[1e999]}',
    ],
)
def test_duplicate_json_keys_and_nonfinite_values_are_rejected(raw):
    with pytest.raises(ValueError):
        review.strict_json(raw)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_bytes": True},
        {"max_bytes": 0},
        {"max_bytes": review.MAX_BYTES + 1},
        {"max_images": False},
        {"max_images": 0},
        {"max_images": review.MAX_IMAGES + 1},
    ],
)
def test_caps_cannot_silently_expand_or_use_boolean_integers(kwargs):
    with pytest.raises(ValueError):
        run(example(), **kwargs)


def test_single_native_frame_needs_no_manufactured_overlap():
    summary, private = run(example(count=1))
    assert summary["per_lane_sessions"] == 1
    assert summary["overlap_image_bytes"] == 0
    assert private["batches"][0]["frames"] == [0]
    assert private["batches"][0]["overlap_frame"] is None


def test_source_aggregation_order_denominators_and_unavailability_are_explicit():
    first = run(example())[0]
    second = copy.deepcopy(first)
    second["source_id"] = "other"
    result = review.summarize_sources([second, first])
    assert result == review.summarize_sources([first, second])
    assert result["source_count"] == 2
    assert result["native_frames"] == 16
    assert result["proposed_sessions"] == 6
    assert result["full_match_accuracy_established"] is False
    unavailable = run(example(), max_bytes=1)[0]
    unavailable["source_id"] = "unavailable"
    combined = review.summarize_sources([first, unavailable])
    assert combined["status"] == "unavailable"
    assert combined["native_frames"] == 16
    assert [s["status"] for s in combined["sources"]] == ["planned", "unavailable"]
    with pytest.raises(ValueError, match="Duplicate source"):
        review.summarize_sources([first, first])


@pytest.mark.parametrize(
    "key,value",
    [
        ("actual_new_scientific_sessions", False),
        ("actual_new_image_bytes", 1),
        ("complete_references", 1),
        ("scientific_acceptance_changed", True),
        ("native_frames", 9),
        ("sampled_frames", False),
        ("available_native_frames", 7),
        ("per_lane_sessions", 2),
        ("proposed_image_bytes", 1),
        ("overlap_image_bytes", 5),
        ("reason", "hidden partial failure"),
        ("status", "unavailable"),
    ],
)
def test_aggregate_rejects_promoted_truth_and_inconsistent_denominators_or_costs(
    key, value
):
    summary = run(example())[0]
    summary[key] = value
    with pytest.raises(ValueError):
        review.summarize_sources([summary])


def command_module():
    path = Path(__file__).resolve().parents[1] / "scripts/plan_rally_review.py"
    spec = importlib.util.spec_from_file_location("generated_review_cli", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def command_protocol(cli):
    return cli.read(cli.CHECKOUT / cli.PROTOCOL)


def command_grant(protocol):
    claim = {
        "actor": "Ken0u",
        "host_id": "MSI",
        "session_id": "generated",
        "epoch": 1,
        "granted_at": 1000,
        "expires_at": 11800,
        "baseline_sha": "a" * 40,
        "branch": "codex/issue-262-generated",
        "spec_hash": protocol["spec_hash"],
    }
    return {
        "task": {
            "status": "running",
            "epoch": 1,
            "claim": claim,
            "spec_hash": protocol["spec_hash"],
        },
        "receipt": {
            "status": "granted",
            "task_id": "262",
            "actor": "Ken0u",
            "epoch": 1,
            "claim": copy.deepcopy(claim),
        },
    }


def test_cli_original_protocol_and_immutable_grant_interval():
    cli = command_module()
    protocol = command_protocol(cli)
    assert cli.validate_protocol(protocol) is protocol
    grant = command_grant(protocol)
    assert cli.validate_grant(grant, protocol, 1100, "MSI") == 15400
    grant["task"]["claim"]["expires_at"] = 20000
    assert cli.validate_grant(grant, protocol, 12000, "MSI") == 15400
    with pytest.raises(ValueError, match="runtime expired"):
        cli.validate_grant(grant, protocol, 15400, "MSI")


@pytest.mark.parametrize(
    "path,value",
    [
        (("task", "status"), "review"),
        (("task", "epoch"), True),
        (("task", "claim", "epoch"), True),
        (("task", "claim", "host_id"), "elsewhere"),
        (("task", "claim", "actor"), "elsewhere"),
        (("task", "claim", "spec_hash"), "0" * 64),
        (("task", "claim", "branch"), "ungranted"),
        (("task", "claim", "granted_at"), True),
        (("task", "claim", "expires_at"), 1050),
        (("receipt", "epoch"), True),
        (("receipt", "status"), "pending"),
        (("receipt", "task_id"), "250"),
        (("receipt", "claim", "session_id"), "another-session"),
    ],
)
def test_cli_requires_current_committed_matching_grant(path, value):
    cli = command_module()
    protocol = command_protocol(cli)
    grant = command_grant(protocol)
    target = grant
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        cli.validate_grant(grant, protocol, 1100, "MSI")


@pytest.mark.parametrize(
    "path,value",
    [
        (("task",), True),
        (("schema_version",), True),
        (("output_root",), ".cache/new-attempt"),
        (("limits", "runtime_seconds"), 14401),
        (("limits", "new_scientific_sessions"), False),
        (("limits", "new_image_payload_bytes"), 1),
        (("packing", "max_bytes"), 9437185),
        (("packing", "max_images"), True),
        (("packing", "preceding_overlap_frames"), 0),
        (("denominators", "native_frames"), 1531),
        (("preserved_result", "complete_references"), 1),
        (("prior", "commit"), "a" * 40),
        (("sources", 0, "source_sha256"), "0" * 64),
    ],
)
def test_cli_rejects_changed_protocol_bounds_and_provenance(path, value):
    cli = command_module()
    protocol = command_protocol(cli)
    target = protocol
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        cli.validate_protocol(protocol)


def test_cli_same_bytes_are_hashed_and_parsed_once(tmp_path, monkeypatch):
    cli = command_module()
    path = tmp_path / "packet.json"
    original = b'{"ordinal":0,"unknown":null}'
    path.write_bytes(original)
    protocol = {"sealed_inputs": {"packet.json": hashlib.sha256(original).hexdigest()}}
    actual_read, calls = Path.read_bytes, []

    def changed_after_read(candidate):
        raw = actual_read(candidate)
        if candidate == path:
            calls.append(candidate)
            candidate.write_bytes(b'{"ordinal":999}')
        return raw

    monkeypatch.setattr(Path, "read_bytes", changed_after_read)
    assert cli.sealed_json(tmp_path, "packet.json", protocol) == {
        "ordinal": 0,
        "unknown": None,
    }
    assert calls == [path]
    with pytest.raises(ValueError, match="Sealed metadata bytes changed"):
        cli.sealed_json(tmp_path, "packet.json", protocol)


@pytest.mark.parametrize(
    "raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'{"x":[Infinity]}']
)
def test_cli_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(raw):
    with pytest.raises(ValueError):
        command_module().strict_json(raw)


def frozen_command_fixture(tmp_path, monkeypatch):
    cli = command_module()
    protocol = command_protocol(cli)
    output = tmp_path / protocol["output_root"]
    output.parent.mkdir()
    monkeypatch.setattr(cli, "verify_inputs", lambda *_: None)
    monkeypatch.setattr(cli, "budget", lambda *_: 0)
    monkeypatch.setattr(
        cli, "binding", lambda: {"commit": "b" * 40, "files": {"generated": "c" * 64}}
    )
    monkeypatch.setattr(cli.common, "git", lambda *_: "codex/issue-262-generated")
    monkeypatch.setattr(cli.platform, "node", lambda: "MSI")
    monkeypatch.setattr(cli.time, "time", lambda: 1100)
    cli.freeze(tmp_path, output, command_grant(protocol), protocol)
    stamp = tmp_path / "stamp.json"
    cli.write(
        stamp,
        {
            "user": {"login": "Ken0u"},
            "html_url": "https://github.com/Ken0u/badminton-match-analyzer/issues/262#issuecomment-generated",
            "created_at": datetime.fromtimestamp(1101, timezone.utc).isoformat(),
            "body": cli.digest(output / "context.json"),
        },
    )
    monkeypatch.setattr(cli.time, "time", lambda: 1102)
    return cli, protocol, output, stamp


def test_cli_freeze_is_exclusive_and_context_bound(tmp_path, monkeypatch):
    cli, protocol, output, stamp = frozen_command_fixture(tmp_path, monkeypatch)
    assert cli.current(output, stamp, protocol)["deadline"] == 15400
    before = (output / "context.json").read_bytes()
    with pytest.raises(FileExistsError):
        cli.freeze(tmp_path, output, command_grant(protocol), protocol)
    assert (output / "context.json").read_bytes() == before
    monkeypatch.setattr(cli, "binding", lambda: {"commit": "d" * 40})
    with pytest.raises(ValueError, match="consumer/protocol changed"):
        cli.current(output, stamp, protocol)


@pytest.mark.parametrize("change", ["author", "issue", "hash", "time", "deadline"])
def test_cli_requires_prospective_owning_issue_seal(tmp_path, monkeypatch, change):
    cli, protocol, output, stamp = frozen_command_fixture(tmp_path, monkeypatch)
    value = cli.read(stamp)
    if change == "author":
        value["user"]["login"] = "someone"
    elif change == "issue":
        value["html_url"] = value["html_url"].replace("/262#", "/250#")
    elif change == "hash":
        value["body"] = "0" * 64
    elif change == "time":
        value["created_at"] = datetime.fromtimestamp(1099, timezone.utc).isoformat()
    else:
        context = cli.read(output / "context.json")
        context["deadline"] += 1
        (output / "context.json").write_text(json.dumps(context), encoding="utf-8")
        value["body"] = cli.digest(output / "context.json")
    stamp.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        cli.current(output, stamp, protocol)


@pytest.mark.parametrize(
    "name",
    ["attempt.json", "failure.json", "admission.json", "plan.json", "unexpected.txt"],
)
def test_cli_existing_attempt_fences_reexecution_before_store_access(
    tmp_path, monkeypatch, name
):
    cli, protocol, output, stamp = frozen_command_fixture(tmp_path, monkeypatch)
    (output / name).write_bytes(b"preserve original")
    monkeypatch.setattr(
        cli, "audit_history", lambda *_: pytest.fail("must not execute audit")
    )
    with pytest.raises(ValueError, match="Original attempt exists"):
        cli.execute(tmp_path, output, stamp, protocol)
    assert (output / name).read_bytes() == b"preserve original"


def test_cli_historical_failure_marks_real_generated_store_failed_and_blocks_planning(
    tmp_path, monkeypatch
):
    from badminton import config
    from badminton.storage import Store

    cli, protocol, output, stamp = frozen_command_fixture(tmp_path, monkeypatch)
    data = tmp_path / "data/processed"
    store = Store(data)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", data)
    monkeypatch.setattr(config, "WEIGHTS", tmp_path / "models/weights")
    for name in cli.CREDENTIALS:
        monkeypatch.delenv(name, raising=False)

    def rejected(*_):
        raise ValueError("generated historical audit failure")

    monkeypatch.setattr(cli, "audit_history", rejected)
    monkeypatch.setattr(
        cli, "build", lambda *_: pytest.fail("unverified scientific metadata parsed")
    )
    with pytest.raises(ValueError, match="generated historical audit failure"):
        cli.execute(tmp_path, output, stamp, protocol)
    failure = cli.read(output / "failure.json")
    assert failure["implicit_retry_permitted"] is False
    assert failure["error_type"] == "ValueError"
    assert store.job(failure["job_id"])["status"] == "failed"
    assert not (output / "plan.json").exists()
    with pytest.raises(ValueError, match="Original attempt exists"):
        cli.execute(tmp_path, output, stamp, protocol)


def test_cli_clears_credentials_and_pins_historical_pythonpath(tmp_path, monkeypatch):
    cli = command_module()
    protocol = command_protocol(cli)
    for key in cli.CREDENTIALS:
        monkeypatch.setenv(key, "generated-never-forward")
    env = cli.prior_environment(tmp_path, protocol)
    assert not any(key in env for key in cli.CREDENTIALS)
    assert env["BADMINTON_DATA_DIR"] == str(tmp_path / "data/processed")
    assert env["PYTHONPATH"] == str(
        tmp_path / protocol["prior"]["checkout"] / "backend"
    )
    (tmp_path / protocol["prior"]["checkout"]).mkdir(parents=True)
    assert "generated-never-forward" not in json.dumps(
        cli.prior_command(tmp_path, protocol)
    )


def test_cli_lifetime_absence_never_treats_live_owner_as_terminal():
    import psutil

    cli = command_module()
    row = cli.identity(psutil.Process())
    assert row["pid"] == os.getpid() and row["creation_time"] < time.time()
    with pytest.raises(ValueError, match="still alive"):
        cli.absent(row)
    with pytest.raises(ValueError, match="lifetime required"):
        cli.absent({**row, "pid": True})


def test_cli_historical_subprocess_failure_is_preserved_without_metadata_read(
    tmp_path, monkeypatch
):
    cli = command_module()
    protocol = command_protocol(cli)
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(cli, "verify_inputs", lambda *_: None)
    monkeypatch.setattr(cli, "prior_command", lambda *_: ["generated-audit"])
    monkeypatch.setattr(
        cli.subprocess,
        "Popen",
        lambda *_, **__: SimpleNamespace(pid=123, poll=lambda: 1, wait=lambda: 1),
    )
    monkeypatch.setattr(
        cli, "validate_prior_result", lambda *_: pytest.fail("failed audit admitted")
    )
    with pytest.raises(ValueError, match="Historical audit failed"):
        cli.audit_history(tmp_path, output, protocol)
    receipt = cli.read(output / "prior-audit-process.json")
    assert receipt["returncode"] == 1
    assert (output / "prior-audit-stdout.log").exists()


def test_cli_observation_error_reaps_same_handle_and_preserves_receipt(
    tmp_path, monkeypatch
):
    cli = command_module()
    output = tmp_path / "output"
    output.mkdir()
    calls, polls = [], iter([None, 0])
    process = SimpleNamespace(
        pid=123, poll=lambda: next(polls), wait=lambda: calls.append("wait") or 0
    )
    launcher = SimpleNamespace(pid=123, children=lambda **_: [])
    monkeypatch.setattr(cli, "verify_inputs", lambda *_: None)
    monkeypatch.setattr(cli, "prior_command", lambda *_: ["generated-audit"])
    monkeypatch.setattr(
        cli.subprocess, "Popen", lambda *_, **__: calls.append("launch") or process
    )
    monkeypatch.setattr(cli.psutil, "Process", lambda _: launcher)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)

    def denied(_):
        raise cli.psutil.AccessDenied(123)

    monkeypatch.setattr(cli, "identity", denied)
    monkeypatch.setattr(
        cli,
        "validate_prior_result",
        lambda *_: pytest.fail("incomplete process proof admitted"),
    )
    with pytest.raises(ValueError, match="observation incomplete"):
        cli.audit_history(tmp_path, output, command_protocol(cli))
    receipt = cli.read(output / "prior-audit-process.json")
    assert receipt["returncode"] == 0
    assert receipt["observation_errors"] == [{"pid": 123, "error": "AccessDenied"}]
    assert calls == ["launch", "wait"]


@pytest.mark.parametrize("fault", ["store", "artifact", "inventory"])
def test_cli_completed_audit_fences_store_and_artifact_mismatch_before_metadata(
    tmp_path, monkeypatch, fault
):
    cli = command_module()
    protocol = command_protocol(cli)
    output = tmp_path / protocol["output_root"]
    output.mkdir(parents=True)
    for name in cli.ARTIFACTS:
        cli.write(output / name, {})
    admission = {
        "job_id": "generated",
        "process": {},
        "context_sha256": cli.digest(output / "context.json"),
    }
    (output / "admission.json").write_text(json.dumps(admission), encoding="utf-8")
    (output / "attempt.json").write_text('{"process":{}}', encoding="utf-8")
    summary = {"artifacts": {name: cli.digest(output / name) for name in cli.ARTIFACTS}}
    terminal = {
        "status": "completed",
        "job_id": "generated",
        "admission_sha256": cli.digest(output / "admission.json"),
        "summary": summary,
    }
    cli.write(output / "terminal.json", terminal)
    job = {"status": "completed", "summary": copy.deepcopy(summary)}
    if fault == "store":
        job["status"] = "running"
    elif fault == "artifact":
        (output / "plan.json").write_bytes(b"changed")
    else:
        (output / "surprise.json").write_bytes(b"{}")
    monkeypatch.setattr(cli, "current", lambda *_, **__: {})
    monkeypatch.setattr(cli, "absent", lambda _: None)
    monkeypatch.setattr(cli.common, "store_job", lambda *_: job)
    monkeypatch.setattr(
        cli,
        "verify_inputs",
        lambda *_: pytest.fail("artifact mismatch reached historical parsing"),
    )
    with pytest.raises(
        ValueError,
        match=r"Store/admission/terminal mismatch|artifact inventory|artifact changed",
    ):
        cli.audit(tmp_path, output, tmp_path / "unused", protocol)
