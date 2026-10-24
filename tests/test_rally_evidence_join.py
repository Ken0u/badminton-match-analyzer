"""Generated metadata regressions; no private sources, images or assessors."""

import copy
import importlib.util
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from badminton import rally_evidence_join as join
from badminton import rally_reference_diagnostics as census
from badminton import rally_source_reference as native
from badminton import rally_temporal_context as temporal
from test_rally_source_reference import assessment, clock, packet, receipt
from test_rally_temporal_context import example, lightweight_manifest

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    source = packet()
    source["clock_sha256"] = temporal.fingerprint(clock(8))
    chunk = native.plan_chunks(source, dense=True)[0]
    streams, ledger = {}, {"provenance": {}, "streams": {}}
    for lane in join.LANES:
        doc = assessment(source, chunk, lane=lane, session="native-" + lane)
        original_receipt = receipt(doc, chunk, thread="native-thread-" + lane)
        streams[lane] = [(doc, original_receipt)]
    rebuild_native(source, streams, ledger)
    manifest = lightweight_manifest(source)
    coarse = {}
    for lane in join.LANES:
        doc, original_receipt = example(manifest, lane)
        coarse[lane] = {
            "document": doc,
            "receipt": original_receipt,
            "provenance": provenance("coarse/" + lane, doc, original_receipt),
        }
    expected = {
        **{k: source[k] for k in join.SOURCE_KEYS},
        "packet_sha256": temporal.fingerprint(source),
        "native_frame_count": len(source["frames"]),
    }
    return source, streams, ledger, manifest, coarse, expected


def provenance(prefix, doc, original_receipt):
    return {
        "original_path": "/generated/" + prefix + "/original.json",
        "original_sha256": temporal.fingerprint(doc),
        "receipt_path": "/generated/" + prefix + "/receipt.json",
        "receipt_sha256": temporal.fingerprint(original_receipt),
    }


def rebuild_native(source, streams, ledger):
    for lane in join.LANES:
        for index, (doc, original_receipt) in enumerate(streams[lane]):
            original_receipt["segment_sha256"] = temporal.fingerprint(doc)
            original_receipt["images"] = copy.deepcopy(doc["inspected_frames"])
            original_receipt["image_bytes"] = sum(
                r["image"]["bytes"]
                for r in source["frames"]
                if r["frame"] in [i["frame"] for i in doc["inspected_frames"]]
            )
        ledger["provenance"][lane] = [
            provenance("native/" + lane + "/" + str(index), doc, r)
            for index, (doc, r) in enumerate(streams[lane])
        ]
        ledger["streams"][lane] = census.census_lane(
            streams[lane], native_frames=[r["frame"] for r in source["frames"]]
        )[1]


def refresh_coarse(item, manifest):
    item["document"]["gallery_sha256"] = temporal.fingerprint(manifest)
    item["receipt"]["gallery_sha256"] = temporal.fingerprint(manifest)
    item["receipt"]["document_sha256"] = temporal.fingerprint(item["document"])
    item["provenance"] = provenance(
        "coarse/" + item["document"]["lane"], item["document"], item["receipt"]
    )


def run(data):
    return join.join_source(*data[:5], expected_source=data[5])


def test_full_native_denominator_exact_sparse_memberships_and_no_mutation():
    data = fixture()
    before = copy.deepcopy(data)
    summary, ledger = run(data)
    assert data == before
    assert summary["native_frames"] == 8
    assert summary["sampled_frames"] == 5
    assert summary["unsampled_native_frames"] == 3
    assert [r["frame"] for r in ledger["frames"]] == list(range(8))
    for frame, original in zip(ledger["frames"], data[0]["frames"], strict=True):
        assert {k: frame[k] for k in join.FRAME_KEYS} == {
            k: original[k] for k in join.FRAME_KEYS
        }
        assert frame["source_id"] == "generated"
        for lane in join.LANES:
            assert len(frame["native"][lane]) == 1
            assert len(frame["coarse"][lane]) == int(frame["sampled"])
    assert ledger["native_original_ledger"] == data[2]
    assert ledger["coarse_manifest"] == data[3]
    assert summary["eligibility"] == temporal.ELIGIBILITY
    assert (
        summary["truth_resolved"] is summary["scientific_acceptance_changed"] is False
    )
    assert summary["contacts_merged"] == summary["actor_links_inferred"] == 0


def test_public_summary_has_counts_only_and_no_labels_or_private_provenance():
    summary, _ = run(fixture())
    public = json.dumps(summary)
    for forbidden in (
        "generated actor",
        "generated contact",
        '"interval":',
        "original_path",
        "receipt_path",
        "session_id",
        "thread_id",
        "actor_id",
        "frame_range",
    ):
        assert forbidden not in public
    assert "forehand" not in public
    assert "ground_contact" not in public


def test_repeated_event_mentions_and_overlapping_keys_are_retained_separately():
    data = fixture()
    doc = data[1]["independent_a"][0][0]
    shot = copy.deepcopy(doc["events"][1])
    doc["events"].append(copy.deepcopy(shot))
    doc["events"].append({**shot, "interval": [2, 3]})
    rebuild_native(data[0], data[1], data[2])
    summary, ledger = run(data)
    lane = summary["native_lanes"]["independent_a"]
    assert lane["event_occurrences"] == 5
    assert lane["signature_repeat_excess"] == 1
    assert lane["distinct_key_overlapping_contact_pairs"] == 1
    retained = ledger["native_event_occurrences"]["independent_a"]
    assert [r["event"] for r in retained] == doc["events"]
    assert retained[1]["reference"]["row"] == 1
    assert retained[3]["reference"]["row"] == 3
    assert retained[1]["event"] == retained[3]["event"]
    overlaps = [
        q for q in ledger["review_questions"] if q["kind"] == "overlapping_contact_keys"
    ]
    assert len(overlaps) == 1
    assert len(overlaps[0]["occurrences"]) == 3
    assert overlaps[0]["frame_range"] == [2, 3]


def test_conflicting_duplicate_frame_occurrences_and_unknowns_survive():
    data = fixture()
    duplicate = copy.deepcopy(data[1]["independent_a"][0])
    duplicate[0]["session_id"] = duplicate[1]["session_id"] = "fresh-duplicate"
    duplicate[0]["frame_states"][3]["scene"] = "unknown"
    duplicate[0]["frame_states"][3]["contact_state"] = "unknown"
    duplicate[0]["actors"][0]["description"] = "different source actor definition"
    data[1]["independent_a"].append(duplicate)
    rebuild_native(data[0], data[1], data[2])
    summary, ledger = run(data)
    states = ledger["frames"][3]["native"]["independent_a"]
    assert len(states) == 2
    assert states[0]["state"]["scene"] == "live"
    assert states[1]["state"]["scene"] == "unknown"
    assert [r["reference"]["document"] for r in states] == [0, 1]
    assert summary["native_lanes"]["independent_a"]["inspected_memberships"] == 16
    assert len(ledger["native_actor_occurrences"]["independent_a"]) == 2
    assert summary["native_lanes"]["independent_a"]["actor_definition_occurrences"] == 2


def test_actor_definitions_are_document_local_and_equal_strings_do_not_link():
    data = fixture()
    first = data[1]["independent_a"][0][0]
    first["actors"][0]["identity_supported"] = False
    second = copy.deepcopy(data[1]["independent_a"][0])
    second[0]["session_id"] = second[1]["session_id"] = "fresh-supported"
    second[0]["actors"][0]["identity_supported"] = True
    second[0]["actors"][0]["description"] = "another actor wearing same colour"
    data[1]["independent_a"].append(second)
    rebuild_native(data[0], data[1], data[2])
    manifest = data[3]
    for lane, item in data[4].items():
        doc = item["document"]
        doc["actors"] = [
            {
                "actor_id": "A",
                "description": "coarse actor",
                "identity_supported": True,
                "evidence_frames": [0, 2],
            }
        ]
        doc["frame_states"][0]["actor_ids"] = ["A"]
        doc["frame_states"][1]["actor_ids"] = ["A"]
        refresh_coarse(item, manifest)
    summary, ledger = run(data)
    assert summary["actor_links_inferred"] == 0
    assert (
        summary["native_lanes"]["independent_a"][
            "unsupported_identity_contact_occurrences"
        ]
        == 2
    )
    questions = [
        q
        for q in ledger["review_questions"]
        if q["kind"] == "document_local_actor"
        and q["occurrences"][0]["lane"] == "independent_a"
    ]
    for question in questions:
        event = question["occurrences"][0]
        assert all(
            r["document"] == event["document"] and r["granularity"] == "native"
            for r in question["occurrences"]
        )
    assert (
        ledger["frames"][0]["coarse"]["independent_a"][0]["local_actor_references"][0][
            "granularity"
        ]
        == "coarse"
    )


def test_scene_support_compares_every_variant_without_majority_vote():
    data = fixture()
    for lane, item in data[4].items():
        item["document"]["frame_states"][0]["scene"] = (
            "replay" if lane == "adjudication" else "live"
        )
        refresh_coarse(item, data[3])
    _, ledger = run(data)
    comparisons = ledger["frames"][0]["scene_comparisons"]
    assert Counter(r["support"] for r in comparisons) == {"agreement": 6, "conflict": 3}
    assert len(ledger["frames"][1]["scene_comparisons"]) == 9
    assert all(
        r["support"] == "unavailable" for r in ledger["frames"][1]["scene_comparisons"]
    )
    assert all(
        r["coarse_reference"] is None for r in ledger["frames"][1]["scene_comparisons"]
    )
    assert "resolved_scene" not in ledger["frames"][0]


def test_stopped_play_does_not_supply_precise_terminal_or_contact_absence():
    data = fixture()
    for lane, item in data[4].items():
        item["document"]["frame_states"][-1]["play_state"] = "stopped_play"
        refresh_coarse(item, data[3])
        doc = data[1][lane][0][0]
        doc["events"] = [e for e in doc["events"] if e["kind"] != "rally_end"]
    rebuild_native(data[0], data[1], data[2])
    _, ledger = run(data)
    assert all(
        e["event"]["kind"] != "rally_end"
        for rows in ledger["native_event_occurrences"].values()
        for e in rows
    )
    endings = [q for q in ledger["review_questions"] if q["kind"] == "terminal_context"]
    assert len(endings) == 3
    assert all(q["frame_range"] == [0, 7] for q in endings)
    assert all(q["truth_resolved"] is False for q in endings)
    assert "contact_absent" not in json.dumps(ledger)


@pytest.mark.parametrize("key", ["source_id", "source_sha256", "clock_sha256"])
def test_source_and_clock_mismatch_rejected(key):
    data = fixture()
    data[5][key] = "wrong" if key == "source_id" else "f" * 64
    with pytest.raises(ValueError, match="source/clock"):
        run(data)


@pytest.mark.parametrize(
    "change",
    ["missing", "extra", "duplicate", "boolean", "pts", "time_base", "orientation"],
)
def test_native_ordinal_clock_or_orientation_corruption_is_rejected(change):
    data = fixture()
    rows = data[0]["frames"]
    if change == "missing":
        rows.pop(3)
    elif change == "extra":
        rows.append(copy.deepcopy(rows[-1]))
    elif change == "duplicate":
        rows[3]["frame"] = 2
    elif change == "boolean":
        rows[1]["frame"] = True
    elif change == "pts":
        rows[3]["pts"] += 1
    elif change == "time_base":
        rows[3]["time_base"] = "0"
    else:
        rows[3]["rotation"] = 90
    with pytest.raises((ValueError, ZeroDivisionError)):
        run(data)


@pytest.mark.parametrize("lane", join.LANES)
@pytest.mark.parametrize("where", ["native", "native_ledger", "provenance", "coarse"])
def test_omitted_lanes_are_rejected(lane, where):
    data = fixture()
    target = {
        "native": data[1],
        "native_ledger": data[2]["streams"],
        "provenance": data[2]["provenance"],
        "coarse": data[4],
    }[where]
    del target[lane]
    with pytest.raises(ValueError, match="lanes"):
        run(data)


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "lane",
        "bool_frame",
        "image",
        "receipt",
        "session",
        "raw_provenance",
        "extra_provenance",
        "missing_provenance",
        "ledger_frame",
        "ledger_event",
        "ledger_actor",
    ],
)
def test_original_native_occurrence_provenance_is_required(change):
    data = fixture()
    doc, original_receipt = data[1]["independent_a"][0]
    original_ledger = data[2]["streams"]["independent_a"]
    if change == "source":
        doc["source_id"] = "another"
    elif change == "lane":
        doc["stream"] = "independent_b"
    elif change == "bool_frame":
        doc["inspected_frames"][1]["frame"] = True
    elif change == "image":
        doc["inspected_frames"][3]["sha256"] = "f" * 64
    elif change == "receipt":
        original_receipt["segment_sha256"] = "f" * 64
    elif change == "session":
        original_receipt["session_id"] = "other"
    elif change == "raw_provenance":
        data[2]["provenance"]["independent_a"][0]["original_sha256"] = "malformed"
    elif change == "extra_provenance":
        data[2]["provenance"]["independent_a"][0]["actor_link"] = "A"
    elif change == "missing_provenance":
        data[2]["provenance"]["independent_a"].clear()
    elif change == "ledger_frame":
        original_ledger["frames"].pop()
    elif change == "ledger_event":
        original_ledger["events"].pop()
    else:
        original_ledger["actors"].pop()
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize(
    "change",
    [
        "extra_sample",
        "missing_sample",
        "bool_frame",
        "coarse_clock",
        "sheet",
        "source",
        "actor_link",
        "receipt",
        "extra_lane",
        "eligibility",
    ],
)
def test_coarse_membership_corruption_or_actor_inference_rejected(change):
    data = fixture()
    doc = data[4]["independent_a"]["document"]
    if change == "extra_sample":
        row = copy.deepcopy(doc["frame_states"][0])
        row["frame"] = 1
        doc["frame_states"].insert(1, row)
        refresh_coarse(data[4]["independent_a"], data[3])
    elif change == "missing_sample":
        doc["frame_states"].pop()
        refresh_coarse(data[4]["independent_a"], data[3])
    elif change == "bool_frame":
        doc["frame_states"][0]["frame"] = False
        refresh_coarse(data[4]["independent_a"], data[3])
    elif change == "coarse_clock":
        data[3]["plan"]["clock_sha256"] = "f" * 64
    elif change == "sheet":
        data[3]["sheets"][0]["frames"].reverse()
    elif change == "source":
        doc["source_id"] = "other"
        refresh_coarse(data[4]["independent_a"], data[3])
    elif change == "actor_link":
        doc["frame_states"][0]["actor_ids"] = ["A"]
        refresh_coarse(data[4]["independent_a"], data[3])
    elif change == "receipt":
        data[4]["independent_a"]["receipt"]["document_sha256"] = "f" * 64
    elif change == "extra_lane":
        data[4]["unexpected"] = copy.deepcopy(data[4]["independent_a"])
    else:
        doc["eligibility"]["training_allowed"] = True
        refresh_coarse(data[4]["independent_a"], data[3])
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
def test_duplicate_keys_and_all_nonfinite_json_are_rejected(raw):
    with pytest.raises(ValueError):
        join.strict_json(raw)


def test_strict_json_retains_explicit_unknowns_and_finite_source_values():
    assert join.strict_json(b'{"x":null,"unknown":"unknown","time":1.5}') == {
        "x": None,
        "unknown": "unknown",
        "time": 1.5,
    }


@pytest.mark.parametrize(
    "change",
    [
        "missing_frame",
        "duplicate_frame",
        "bool_frame",
        "forward_fill",
        "native_event",
        "actor_link",
        "hidden_unknown",
        "eligibility",
        "merged_contact",
        "summary_count",
        "question_reference",
        "extra_field",
    ],
)
def test_independent_rebuild_audit_rejects_omissions_and_inference(change):
    data = fixture()
    summary, ledger = run(data)
    if change == "missing_frame":
        ledger["frames"].pop()
    elif change == "duplicate_frame":
        ledger["frames"].append(copy.deepcopy(ledger["frames"][0]))
    elif change == "bool_frame":
        ledger["frames"][1]["frame"] = True
    elif change == "forward_fill":
        ledger["frames"][1]["coarse"] = copy.deepcopy(ledger["frames"][0]["coarse"])
    elif change == "native_event":
        ledger["native_event_occurrences"]["independent_a"].pop()
    elif change == "actor_link":
        ledger["frames"][0]["persistent_actor"] = "A"
    elif change == "hidden_unknown":
        ledger["frames"][0]["coarse"]["independent_a"][0]["state"]["scene"] = "live"
    elif change == "eligibility":
        ledger["eligibility"]["training_allowed"] = True
    elif change == "merged_contact":
        summary["contacts_merged"] = 1
    elif change == "summary_count":
        summary["sampled_frames"] += 1
    elif change == "question_reference":
        ledger["review_questions"][0]["occurrences"][0]["original_sha256"] = "f" * 64
    else:
        ledger["accepted"] = True
    with pytest.raises(ValueError, match="differs"):
        join.audit_join(summary, ledger, *data[:5], expected_source=data[5])


def test_rebuild_audit_passes_exact_ledger_and_questions_bind_original_hashes():
    data = fixture()
    summary, ledger = run(data)
    result = join.audit_join(summary, ledger, *data[:5], expected_source=data[5])
    assert result["verified"] is True
    assert result["native_frames"] == 8
    for question in ledger["review_questions"]:
        assert question["clock_sha256"] == data[0]["clock_sha256"]
        assert question["source_sha256"] == data[0]["source_sha256"]
        assert 0 <= question["frame_range"][0] <= question["frame_range"][1] <= 7
        assert question["truth_resolved"] is False
        for reference in question["occurrences"]:
            origin = (
                data[2]["provenance"][reference["lane"]][reference["document"]]
                if reference["granularity"] == "native"
                else data[4][reference["lane"]]["provenance"]
            )
            assert all(reference[k] == origin[k] for k in join.PROVENANCE_KEYS)


def test_dictionary_and_source_list_iteration_order_cannot_change_exact_join():
    data = fixture()
    first = run(data)
    reordered = list(copy.deepcopy(data))
    for index in (0, 1, 2, 3, 4, 5):
        reordered[index] = dict(reversed(list(reordered[index].items())))
    assert run(reordered) == first
    a, _ = first
    b = copy.deepcopy(a)
    b["source_id"] = "second"
    assert join.summarize_sources([a, b]) == join.summarize_sources([b, a])
    with pytest.raises(ValueError, match="Duplicate source"):
        join.summarize_sources([a, a])


def test_returned_private_ledger_does_not_alias_scientific_inputs():
    data = fixture()
    before = copy.deepcopy(data)
    _, ledger = run(data)
    ledger["native_documents"]["independent_a"][0]["document"]["actors"][0][
        "description"
    ] = "edited"
    ledger["native_original_ledger"]["streams"]["independent_a"]["events"].clear()
    ledger["frames"][0]["image"]["path"] = "edited"
    ledger["coarse_documents"]["independent_a"]["document"]["frame_states"].clear()
    assert data == before


def test_unavailable_native_input_and_sample_stay_explicit_without_labels():
    data = fixture()
    source = data[0]
    source["frames"][0]["image"] = None
    for lane in join.LANES:
        doc = data[1][lane][0][0]
        doc["inspected_frames"] = [
            r for r in doc["inspected_frames"] if r["frame"] != 0
        ]
        doc["frame_states"] = [r for r in doc["frame_states"] if r["frame"] != 0]
    rebuild_native(source, data[1], data[2])
    data[3]["plan"] = temporal.sample_plan(source)
    data[5]["packet_sha256"] = temporal.fingerprint(source)
    for item in data[4].values():
        refresh_coarse(item, data[3])
    summary, ledger = run(data)
    assert summary["native_frames"] == 8
    assert summary["unavailable_native_frames"] == summary["unavailable_samples"] == 1
    frame = ledger["frames"][0]
    assert frame["available"] is False
    assert frame["image"] is None
    assert all(not rows for rows in frame["native"].values())
    assert all(
        rows[0]["state"]["scene"] == "unknown" for rows in frame["coarse"].values()
    )
    assert all(r["support"] == "unavailable" for r in frame["scene_comparisons"])


def cli():
    spec = importlib.util.spec_from_file_location(
        "generated_join_cli", ROOT / "scripts/join_rally_evidence.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def protocol():
    return json.loads(
        (ROOT / "data/manifests/rally_evidence_join_v1.json").read_bytes()
    )


def generated_grant():
    p = protocol()
    claim = {
        "actor": "Ken0u",
        "host_id": "MSI",
        "session_id": "generated-session",
        "epoch": 1,
        "granted_at": 1000,
        "expires_at": 11800,
        "baseline_sha": "a" * 40,
        "branch": "codex/issue-250-generated",
        "spec_hash": p["spec_hash"],
    }
    return {
        "task": {
            "status": "running",
            "epoch": 1,
            "claim": claim,
            "spec_hash": p["spec_hash"],
        },
        "receipt": {
            "status": "granted",
            "actor": "Ken0u",
            "task_id": "250",
            "epoch": 1,
            "claim": copy.deepcopy(claim),
        },
    }


@pytest.mark.parametrize(
    "raw",
    [
        '{"a":1,"a":2}',
        '{"nested":{"a":1,"a":2}}',
        '{"v":NaN}',
        '{"v":Infinity}',
        '{"v":1e999}',
    ],
)
def test_cli_read_rejects_duplicate_and_nonfinite_json(tmp_path, raw):
    path = tmp_path / "generated.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        cli().read(path)


@pytest.mark.parametrize(
    "path,value",
    [
        (("task", "epoch"), True),
        (("task", "claim", "epoch"), True),
        (("receipt", "epoch"), True),
        (("receipt", "claim", "epoch"), True),
        (("task", "status"), "review"),
        (("task", "spec_hash"), "f" * 64),
        (("task", "claim", "host_id"), "Mac"),
        (("task", "claim", "granted_at"), True),
        (("task", "claim", "expires_at"), True),
        (("task", "claim", "expires_at"), 1050),
        (("task", "claim", "branch"), "codex/issue-242-old"),
        (("receipt", "status"), "pending"),
        (("receipt", "task_id"), "242"),
        (("receipt", "actor"), "other"),
    ],
)
def test_cli_requires_exact_current_original_host_grant(path, value):
    grant = generated_grant()
    target = grant
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        cli().validate_grant(grant, protocol(), 1100, "MSI")


def test_cli_fresh_metadata_deadline_never_renews_old_runtime():
    script = cli()
    grant = generated_grant()
    assert script.validate_grant(grant, protocol(), 1100, "MSI") == 15400
    grant["task"]["claim"]["expires_at"] = 20000
    grant["receipt"]["claim"]["expires_at"] = 20000
    assert script.validate_grant(grant, protocol(), 12000, "MSI") == 15400
    with pytest.raises(ValueError, match="runtime expired"):
        script.validate_grant(grant, protocol(), 15400, "MSI")
    assert not script.equal({"epoch": 1}, {"epoch": True})


def test_current_lease_renewal_preserves_original_receipt_and_metadata_deadline():
    script = cli()
    grant = generated_grant()
    grant["task"]["claim"]["expires_at"] = 20000
    assert script.validate_grant(grant, protocol(), 12000, "MSI") == 15400
    with pytest.raises(ValueError, match="runtime expired"):
        script.validate_grant(grant, protocol(), 15400, "MSI")


@pytest.mark.parametrize("value", [True, 20001])
def test_original_lease_receipt_cannot_be_malformed_or_later_than_current(value):
    grant = generated_grant()
    grant["receipt"]["claim"]["expires_at"] = value
    with pytest.raises(ValueError, match="grant receipt"):
        cli().validate_grant(grant, protocol(), 1100, "MSI")


@pytest.mark.parametrize("relative", ["../escape.json", "/absolute.json"])
def test_cli_rejects_metadata_path_escape(tmp_path, relative):
    with pytest.raises(ValueError, match="escapes"):
        cli().safe(tmp_path, relative)


def test_cli_rejects_linked_metadata_inputs(tmp_path, monkeypatch):
    path = tmp_path / "generated.json"
    path.write_text("{}", encoding="utf-8")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p == path or original(p))
    with pytest.raises(ValueError, match="Linked"):
        cli().safe(tmp_path, path.name)


def test_cli_rejects_changed_sealed_original_input_before_any_scientific_parse(
    tmp_path,
):
    script = cli()
    path = tmp_path / "original.json"
    path.write_text("not even scientific JSON", encoding="utf-8")
    p = {"sealed_inputs": {path.name: script.digest(path)}}
    script.sealed(tmp_path, p)
    path.write_text("changed original", encoding="utf-8")
    with pytest.raises(ValueError, match="Sealed original input changed"):
        script.sealed(tmp_path, p)


@pytest.mark.parametrize("live", [True, False])
def test_cli_lifetime_uses_creation_time_and_never_pid_alone(monkeypatch, live):
    script = cli()
    row = {
        "pid": 123,
        "creation_time": 10.0,
        "cwd": "/generated",
        "command": ["python", "generated.py"],
    }
    monkeypatch.setattr(
        script.psutil,
        "Process",
        lambda _: SimpleNamespace(create_time=lambda: 10.0 if live else 11.0),
    )
    if live:
        with pytest.raises(ValueError, match="still alive"):
            script.absent(row)
    else:
        script.absent(row)


@pytest.mark.parametrize(
    "key,value",
    [
        ("pid", True),
        ("pid", 0),
        ("creation_time", True),
        ("creation_time", float("nan")),
        ("cwd", ""),
        ("command", []),
    ],
)
def test_cli_requires_complete_actual_lifetime_metadata(key, value):
    row = {
        "pid": 123,
        "creation_time": 10.0,
        "cwd": "/generated",
        "command": ["python", "generated.py"],
    }
    row[key] = value
    with pytest.raises(ValueError):
        cli().absent(row)


@pytest.mark.parametrize(
    "change", ["missing", "creation", "cwd", "command", "store", "context"]
)
def test_cli_metadata_gate_requires_actual_admitted_ancestor(
    tmp_path, monkeypatch, change
):
    script = cli()
    monkeypatch.setattr(script, "live_interval", lambda *_: None)
    owner = {
        "pid": 123,
        "creation_time": 10.0,
        "cwd": "/generated",
        "command": ["python", "generated.py"],
    }
    admission = {"process": owner, "context_sha256": "a" * 64}
    script.write(tmp_path / "admission.json", admission)
    monkeypatch.setattr(
        script, "digest", lambda _: "b" * 64 if change == "context" else "a" * 64
    )
    monkeypatch.setattr(
        script,
        "store_job",
        lambda *_: {"status": "completed" if change == "store" else "running"},
    )
    parent = SimpleNamespace(
        pid=123,
        create_time=lambda: 11.0 if change == "creation" else 10.0,
        cwd=lambda: "/other" if change == "cwd" else "/generated",
        cmdline=lambda: ["other"] if change == "command" else owner["command"],
    )
    monkeypatch.setattr(
        script.psutil,
        "Process",
        lambda: SimpleNamespace(
            parents=lambda: [] if change == "missing" else [parent]
        ),
    )
    with pytest.raises(ValueError):
        script.live_parent(tmp_path, tmp_path)


def test_cli_clean_historical_import_gate_precedes_any_original_access(
    tmp_path, monkeypatch
):
    script = cli()
    reached = []
    monkeypatch.setattr(script, "live_parent", lambda *_: reached.append("live"))
    with pytest.raises(ValueError, match="Clean historical"):
        script.metadata(tmp_path, tmp_path, protocol())
    assert reached == []


def test_cli_output_write_is_exclusive_and_preserves_original(tmp_path):
    script = cli()
    path = tmp_path / "generated.json"
    script.write(path, {"original": True})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        script.write(path, {"overwrite": True})
    assert path.read_bytes() == before


def test_cli_budget_counts_task_outputs_and_rejects_ceiling(tmp_path):
    script = cli()
    (tmp_path / ".cache/worktrees").mkdir(parents=True)
    data = tmp_path / ".cache/rally250-generated"
    data.mkdir()
    (data / "payload").write_bytes(b"1234")
    (tmp_path / ".cache/unrelated").write_bytes(b"unrelated")
    p = {
        "limits": {
            "new_output_bytes": 1024**2 + 5,
            "cumulative_retained_bytes": 1024**2 + 10,
        }
    }
    assert script.budget(tmp_path, p) == 4
    with pytest.raises(ValueError, match="budget"):
        script.budget(tmp_path, p, prior=6)
    p["limits"]["new_output_bytes"] = 1024**2 + 4
    with pytest.raises(ValueError, match="budget"):
        script.budget(tmp_path, p)


@pytest.mark.parametrize("prior", [-1, True, float("nan")])
def test_cli_budget_rejects_invalid_prior_accounting(tmp_path, prior):
    (tmp_path / ".cache/worktrees").mkdir(parents=True)
    with pytest.raises(ValueError):
        cli().budget(tmp_path, protocol(), prior=prior)


def test_cli_budget_does_not_follow_linked_task_roots(tmp_path, monkeypatch):
    script = cli()
    (tmp_path / ".cache/worktrees").mkdir(parents=True)
    task = tmp_path / ".cache/rally250-generated"
    task.mkdir()
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p == task or original(p))
    with pytest.raises(ValueError, match="Linked"):
        script.budget(tmp_path, protocol())


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema_version",), True),
        (("task",), True),
        (("spec_hash",), "f" * 64),
        (("sources", 0, "source_sha256"), "f" * 64),
        (("sources", 0, "clock_sha256"), "f" * 64),
        (("sources", 0, "packet_sha256"), "f" * 64),
        (("denominators", "native_frames"), 1531),
        (("denominators", "sampled_frames"), 54),
        (("limits", "new_scientific_sessions"), True),
        (("limits", "new_image_payload_bytes"), 1),
        (("limits", "runtime_seconds"), 14401),
        (("limits", "paid_services"), 0),
        (("preserved_result", "complete_references"), True),
        (("preserved_result", "eligibility", "training_allowed"), True),
    ],
)
def test_cli_protocol_cannot_promote_acceptance_change_sources_or_expand_bounds(
    path, value
):
    p = protocol()
    target = p
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        cli().validate_protocol(p)


def child_evidence():
    launcher = {
        "pid": 123,
        "creation_time": 10.0,
        "cwd": "/generated",
        "command": ["venv-python", "metadata.py"],
    }
    actual = {
        "pid": 124,
        "creation_time": 10.1,
        "cwd": "/generated",
        "command": ["python", "metadata.py"],
    }
    rows = [{**launcher, "ppid": 100}, {**actual, "ppid": 123}]
    return (
        {
            "process": launcher,
            "observed_lifetimes": rows,
            "started_at": 11.0,
            "ended_at": 12.0,
        },
        actual,
        {"frozen_at": 10.0, "deadline": 20.0},
    )


def test_cli_observed_windows_launcher_worker_chain_accepted_after_generated_absence(
    monkeypatch,
):
    script = cli()
    receipt, actual, context = child_evidence()
    observed_absence = []
    # Generated process records only; no real process is declared absent here.
    monkeypatch.setattr(
        script,
        "absent",
        lambda r: observed_absence.append((r["pid"], r["creation_time"])),
    )
    script.verify_child_evidence(receipt, actual, context)
    assert set(observed_absence) == {(123, 10.0), (124, 10.1)}


@pytest.mark.parametrize(
    "change",
    [
        "unrelated",
        "missing_actual",
        "missing_launcher",
        "duplicate_identity",
        "duplicate_pid",
        "cycle",
        "started_before",
        "ended_after",
        "reversed_time",
    ],
)
def test_cli_child_audit_rejects_unobserved_or_unrelated_worker_and_expired_interval(
    monkeypatch, change
):
    script = cli()
    receipt, actual, context = child_evidence()
    monkeypatch.setattr(script, "absent", lambda _: None)  # Generated evidence only.
    if change == "unrelated":
        receipt["observed_lifetimes"][1]["ppid"] = 999
    elif change == "missing_actual":
        receipt["observed_lifetimes"].pop()
    elif change == "missing_launcher":
        receipt["observed_lifetimes"].pop(0)
    elif change == "duplicate_identity":
        receipt["observed_lifetimes"].append(
            copy.deepcopy(receipt["observed_lifetimes"][0])
        )
    elif change == "duplicate_pid":
        receipt["observed_lifetimes"].append(
            {**receipt["observed_lifetimes"][1], "creation_time": 10.2}
        )
    elif change == "cycle":
        receipt["observed_lifetimes"][1]["ppid"] = actual["pid"]
    elif change == "started_before":
        receipt["started_at"] = 9.0
    elif change == "ended_after":
        receipt["ended_at"] = 21.0
    else:
        receipt["ended_at"] = 10.0
    with pytest.raises(ValueError):
        script.verify_child_evidence(receipt, actual, context)


def test_cli_expired_gate_prevents_native_launch_or_scientific_read(
    tmp_path, monkeypatch
):
    script = cli()
    script.write(
        tmp_path / "context.json",
        {
            "frozen_at": 10.0,
            "deadline": 20.0,
            "grant": {"task": {"claim": {"expires_at": 30}}},
        },
    )
    now = [11.0]
    monkeypatch.setattr(script.time, "time", lambda: now[0])
    original_child = script.child
    reached = []

    def child(root, output, phase):
        if phase == "gate":
            script.live_interval(output)
            reached.append("gate_completed")
            now[0] = 20.0
            return
        original_child(root, output, phase)

    monkeypatch.setattr(script, "child", child)
    monkeypatch.setattr(
        script.subprocess, "Popen", lambda *_args, **_kwargs: reached.append("spawned")
    )
    monkeypatch.setattr(script, "library", lambda: reached.append("scientific_import"))
    with pytest.raises(ValueError, match="interval expired"):
        script.assemble(tmp_path, tmp_path, protocol())
    assert reached == ["gate_completed"]


def test_questions_for_uninspected_unsampled_frame_cite_original_packet_record():
    data = fixture()
    data[0]["frames"][1]["image"] = None
    for lane in join.LANES:
        doc = data[1][lane][0][0]
        doc["events"] = [e for e in doc["events"] if e["interval"] != [1, 1]]
        doc["inspected_frames"] = [
            r for r in doc["inspected_frames"] if r["frame"] != 1
        ]
        doc["frame_states"] = [r for r in doc["frame_states"] if r["frame"] != 1]
    rebuild_native(data[0], data[1], data[2])
    data[3]["plan"] = temporal.sample_plan(data[0])
    data[5]["packet_sha256"] = temporal.fingerprint(data[0])
    for item in data[4].values():
        refresh_coarse(item, data[3])
    _, ledger = run(data)
    question = next(
        q
        for q in ledger["review_questions"]
        if q["kind"] == "frame_context" and q["frame_range"] == [1, 1]
    )
    assert question["occurrences"] == []
    assert question["packet_record"] == {
        "original_packet_sha256": data[5]["packet_sha256"],
        "section": "frames",
        "inclusive_rows": [1, 1],
    }


@pytest.mark.parametrize(
    "which",
    [
        "metadata-gate.json",
        "native-inputs.json",
        "gate-process.json",
        "native-process.json",
        "context.json",
        "gate-stdout.log",
    ],
)
def test_completed_store_seal_rejects_changed_execution_sidecars(tmp_path, which):
    script = cli()
    for name in (*script.EXECUTION_ARTIFACTS, "terminal.json"):
        (tmp_path / name).write_text("original\n", encoding="utf-8")
    summary = {
        "artifacts": {
            name: script.digest(tmp_path / name) for name in script.EXECUTION_ARTIFACTS
        }
    }
    script.verify_completed_artifacts(tmp_path, summary)
    (tmp_path / which).write_text(
        "altered accounting or provenance\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="artifact changed"):
        script.verify_completed_artifacts(tmp_path, summary)


@pytest.mark.parametrize("change", ["extra", "missing_seal"])
def test_completed_output_inventory_cannot_hide_extra_or_unsealed_sources(
    tmp_path, change
):
    script = cli()
    for name in (*script.EXECUTION_ARTIFACTS, "terminal.json"):
        (tmp_path / name).write_text("original\n", encoding="utf-8")
    summary = {
        "artifacts": {
            name: script.digest(tmp_path / name) for name in script.EXECUTION_ARTIFACTS
        }
    }
    if change == "extra":
        (tmp_path / "extra-source.json").write_text("{}", encoding="utf-8")
    else:
        del summary["artifacts"]["native-inputs.json"]
    with pytest.raises(ValueError, match=r"inventory|Unexpected"):
        script.verify_completed_artifacts(tmp_path, summary)


def test_same_grant_cannot_escape_preserved_failure_under_second_output(tmp_path):
    script = cli()
    output = tmp_path / protocol()["output_root"]
    output.mkdir(parents=True)
    script.write(output / "failure.json", {"implicit_retry_permitted": False})
    script.require_output(tmp_path, output, protocol())
    with pytest.raises(ValueError, match="no second attempt"):
        script.require_output(
            tmp_path, tmp_path / ".cache/rally250-replacement-v1", protocol()
        )
    assert script.read(output / "failure.json")["implicit_retry_permitted"] is False


def test_metadata_interval_also_stops_at_frozen_lease_expiry(tmp_path, monkeypatch):
    script = cli()
    script.write(
        tmp_path / "context.json",
        {
            "frozen_at": 10,
            "deadline": 30,
            "grant": {"task": {"claim": {"expires_at": 20}}},
        },
    )
    monkeypatch.setattr(script.time, "time", lambda: 20)
    with pytest.raises(ValueError, match="interval expired"):
        script.live_interval(tmp_path)


def test_failed_real_generated_store_attempt_is_preserved_and_not_readmitted(
    tmp_path, monkeypatch
):
    from badminton import config
    from badminton.storage import Store

    script = cli()
    output = tmp_path / protocol()["output_root"]
    output.mkdir(parents=True)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", tmp_path / "data/processed")
    monkeypatch.setattr(config, "WEIGHTS", tmp_path / "models/weights")
    store = Store(config.DATA)
    monkeypatch.setattr(script, "current", lambda *_: {"deadline": float("inf")})
    calls = []

    def failure(*_):
        calls.append("metadata")
        raise ValueError("generated input provenance failure")

    monkeypatch.setattr(script, "assemble", failure)
    for name in script.CREDENTIALS:
        monkeypatch.delenv(name, raising=False)
    script.write(output / "context.json", {})
    with pytest.raises(ValueError, match="generated input provenance failure"):
        script.execute(tmp_path, output, None, protocol())
    assert script.read(output / "failure.json")["implicit_retry_permitted"] is False
    assert len(store.jobs()) == 1 and store.jobs()[0]["status"] == "failed"
    with pytest.raises(ValueError, match="Attempt already exists"):
        script.execute(tmp_path, output, None, protocol())
    assert calls == ["metadata"] and len(store.jobs()) == 1
