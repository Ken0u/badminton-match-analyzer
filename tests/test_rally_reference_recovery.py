"""Generated-only recovery provenance and process tests; no external transport."""

import copy
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from badminton import rally_reference_continuation as metadata
from badminton import rally_reference_recovery as recovery


def load_script():
    path = Path(__file__).resolve().parents[1] / "scripts/recover_rally_references.py"
    spec = importlib.util.spec_from_file_location("generated_recovery", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


def plan():
    chunks = [
        {
            "source_id": "generated",
            "index": i,
            "frames": [i * 2, i * 2 + 1],
            "image_bytes": 11,
        }
        for i in range(4)
    ]
    prefix = [
        {"source_id": c["source_id"], "chunk": c["index"], "frames": c["frames"]}
        for c in chunks[:2]
    ]
    return chunks, prefix, chunks[2:]


def test_recovery_never_renews_inherited_scientific_deadline():
    assert recovery.deadline(100, 500, now=101) == 500
    assert recovery.deadline(100, 100000, now=101) == 28900
    with pytest.raises(ValueError, match="not open"):
        recovery.deadline(100, 500, now=440)
    with pytest.raises(ValueError, match="not open"):
        recovery.deadline(450, 500, now=451)
    with pytest.raises(ValueError, match="not open"):
        recovery.deadline(100, 500, now=99)


@pytest.mark.parametrize("value", [True, False, -1, 1.5, "10", None])
def test_grant_timestamps_are_exact_integers(value):
    with pytest.raises(ValueError):
        recovery.deadline(value, 500, now=101)
    with pytest.raises(ValueError):
        recovery.deadline(100, value, now=101)


@pytest.mark.parametrize("now", [True, None, "101", float("nan"), float("inf")])
def test_observation_clock_must_be_finite(now):
    with pytest.raises(ValueError):
        recovery.deadline(100, 500, now=now)


def test_exact_partition_and_failed_attempt_charged_separately():
    chunks, prefix, suffix = plan()
    assert recovery.partition(chunks, prefix, suffix)
    assert recovery.recovery_cost(100, suffix, limit=122) == 122
    with pytest.raises(ValueError, match="budget"):
        recovery.recovery_cost(100, suffix, limit=121)
    with pytest.raises(ValueError, match="Duplicate"):
        recovery.recovery_cost(100, [suffix[0], suffix[0]])


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "duplicate",
        "overlap",
        "reorder",
        "frames",
        "image_cost",
        "bool_index",
        "bool_frame",
    ],
)
def test_changed_recovery_membership_is_rejected(mutation):
    chunks, prefix, suffix = copy.deepcopy(plan())
    if mutation == "missing":
        suffix.pop()
    elif mutation == "extra":
        suffix.append({**suffix[-1], "index": 99})
    elif mutation == "duplicate":
        prefix.append(prefix[0])
    elif mutation == "overlap":
        suffix.insert(0, chunks[0])
    elif mutation == "reorder":
        suffix.reverse()
    elif mutation == "frames":
        prefix[0]["frames"] = [99]
    elif mutation == "image_cost":
        suffix[0] = {**suffix[0], "image_bytes": 99}
    elif mutation == "bool_index":
        prefix[0]["chunk"] = False
    else:
        prefix[0]["frames"][0] = False
    with pytest.raises(ValueError):
        recovery.partition(chunks, prefix, suffix)


def test_failed_archive_entry_cannot_become_a_reference():
    chunks, prefix, _suffix = plan()
    assert recovery.archived_suffix(chunks, prefix, first=0, failed=2)
    failed = {"source_id": "generated", "chunk": 2, "frames": chunks[2]["frames"]}
    with pytest.raises(ValueError):
        recovery.archived_suffix(chunks, [*prefix, failed], first=0, failed=2)
    with pytest.raises(ValueError):
        recovery.archived_suffix(chunks, prefix[:1], first=0, failed=2)


@pytest.mark.parametrize(
    "fault", ["incomplete", "duplicate", "order", "threads", "bytes", "bool"]
)
def test_global_gate_preserves_full_denominator_and_failed_execution_census(fault):
    chunks, _prefix, _suffix = plan()
    entries = [
        {"source_id": c["source_id"], "chunk": c["index"], "frames": c["frames"]}
        for c in chunks
    ]
    arguments = {
        "completed_threads": 6,
        "expected_threads": 6,
        "total": 122,
        "projected": 122,
    }
    assert recovery.global_gate(chunks, entries, **arguments)
    if fault == "incomplete":
        entries.pop()
    elif fault == "duplicate":
        entries[-1] = entries[0]
    elif fault == "order":
        entries.reverse()
    elif fault == "threads":
        arguments["completed_threads"] = 5
    elif fault == "bytes":
        arguments["total"] = 121
    else:
        entries[0]["chunk"] = False
    with pytest.raises(ValueError):
        recovery.global_gate(chunks, entries, **arguments)


def test_incomplete_indexes_return_before_scientific_or_archive_reader(
    tmp_path, monkeypatch
):
    script = load_script()
    monkeypatch.setattr(script, "current", lambda *a, **k: ({}, 0))
    monkeypatch.setattr(
        script, "archive", lambda *a: pytest.fail("no archive read before indexes")
    )
    monkeypatch.setattr(
        script,
        "scientific_status",
        lambda *a: pytest.fail("scientific labels must stay sealed"),
    )
    assert script.audit(tmp_path, tmp_path, None, None, None) == {
        "ready": False,
        "reason": "both_complete_target_indexes_required",
        "scientific_labels_read": False,
    }


def test_invalid_global_census_never_opens_scientific_labels(tmp_path, monkeypatch):
    script = load_script()
    folder = tmp_path / "runs/generated-001"
    folder.mkdir(parents=True)
    chunk = {"source_id": "generated", "index": 1, "frames": [2], "image_bytes": 1}
    entry = {"source_id": "generated", "chunk": 1, "frames": [2]}
    for name, row in {
        "start.json": {"started_at": 10},
        "finish.json": {"ended_at": 11},
        "payload-reservation.json": {},
        "entry.json": entry,
    }.items():
        metadata.exclusive_json(folder / name, row)
    metadata.exclusive_json(
        tmp_path / "combined-target-index.json", {"segments": [entry]}
    )
    metadata.exclusive_json(tmp_path / "owner.json", {})
    context = {
        "prefix": [],
        "suffix": [chunk],
        "granted_at": 1,
        "deadline": 100,
        "projected_image_bytes": 2,
    }
    monkeypatch.setattr(script, "current", lambda *a, **k: (context, 2))
    monkeypatch.setattr(
        script, "archive", lambda *a: ({}, [], [chunk], SimpleNamespace(threads=set()))
    )
    monkeypatch.setattr(
        script,
        "scientific_status",
        lambda *a: pytest.fail("global identity failure must stop scientific read"),
    )
    old = SimpleNamespace(
        SINGLES="generated",
        source_chunks=lambda p: [chunk],
        verify_run=lambda *a, **k: entry,
        metadata=SimpleNamespace(
            absent=lambda x: None,
            complete_index=lambda c, e: {"segments": e},
            payload_total=lambda *a: 2,
        ),
    )
    with pytest.raises(ValueError, match="global"):
        script.audit(tmp_path, tmp_path, None, old, None)


@pytest.mark.parametrize(
    "field", ["deadline", "inherited_deadline", "consumers", "stamp", "cli"]
)
def test_current_binding_rejects_changed_context_before_dispatch(
    tmp_path, monkeypatch, field
):
    script = load_script()
    cli = tmp_path / "generated-cli"
    cli.write_bytes(b"generated CLI, never executed")
    context = {
        "granted_at": 100,
        "deadline": 28900,
        "inherited_deadline": script.INHERITED_DEADLINE,
        "consumers": {"generated": True},
        "frozen_at": 101,
        "cli": {"path": str(cli), "sha256": script.digest(cli)},
    }
    if field == "deadline":
        context["deadline"] += 1
    elif field == "inherited_deadline":
        context["inherited_deadline"] += 1
    elif field == "consumers":
        context["consumers"] = {}
    metadata.exclusive_json(tmp_path / "context.json", context)
    stamp = {
        "created_at": "1970-01-01T00:01:42Z",
        "user": {"login": "Ken0u"},
        "html_url": "https://example.invalid/issues/228#issuecomment-generated",
        "body": script.digest(tmp_path / "context.json"),
    }
    if field == "stamp":
        stamp["user"]["login"] = "untrusted"
    elif field == "cli":
        cli.write_bytes(b"changed")
    metadata.exclusive_json(tmp_path / "stamp.json", stamp)
    monkeypatch.setattr(script, "binding", lambda: {"generated": True})
    with pytest.raises(ValueError):
        script.current(tmp_path, tmp_path / "stamp.json", live=False)


@pytest.mark.parametrize("mode", ["success", "validation_failure", "malformed"])
def test_recovery_runs_generated_child_and_preserves_failure_fence(
    tmp_path, monkeypatch, mode
):
    script = load_script()
    output = tmp_path / "generated-output"
    (output / "runs").mkdir(parents=True)
    native = tmp_path / "generated-native"
    native.mkdir()
    (native / "frame.png").write_bytes(b"generated bytes; never decoded")
    packet = {
        "frames": [
            {
                "frame": 7,
                "pts": 7,
                "time_base": [1, 25],
                "time_s": 0.28,
                "rotation": 0,
                "display_size": [1, 1],
                "image": {
                    "path": "frame.png",
                    "sha256": script.digest(native / "frame.png"),
                },
            }
        ]
    }
    metadata.exclusive_json(native / "generated.packet.json", packet)
    previous = output / "generated-previous.json"
    metadata.exclusive_json(previous, {"continuity_notes": "only own generated notes"})
    previous_receipt = output / "generated-receipt.json"
    metadata.exclusive_json(
        previous_receipt, {"segment_sha256": script.digest(previous)}
    )
    prefix = [
        {
            "source_id": "generated",
            "chunk": 150,
            "frames": [5, 6],
            "original_path": str(previous),
            "receipt_path": str(previous_receipt),
        }
    ]
    chunk = {
        "source_id": "generated",
        "index": 151,
        "region_index": 0,
        "frames": [7],
        "image_bytes": (native / "frame.png").stat().st_size,
        "base64_bytes": 40,
    }
    source_chunks = [{"region_index": 0}] * 152
    context = {
        "prefix": prefix,
        "suffix": [chunk],
        "granted_at": int(time.time()) - 10,
        "deadline": int(time.time()) + 1000,
        "cli": {"path": "generated-cli"},
    }
    monkeypatch.setattr(script, "INHERITED_DEADLINE", context["deadline"])
    monkeypatch.setattr(script, "current", lambda *a, **k: (context, time.time() - 5))
    monkeypatch.setattr(
        script,
        "archive",
        lambda *a: (
            {"sources": [{"source_id": "generated", "chunks": source_chunks}]},
            prefix,
            [chunk],
            None,
        ),
    )
    monkeypatch.setattr(script, "retained", lambda *a: 0)
    monkeypatch.setattr(script.time, "sleep", lambda n: None)
    schema = {"generated": True}
    metadata.exclusive_json(output / "runs/schema.json", schema)

    def encoded(doc):
        return json.dumps(doc, sort_keys=True, indent=2).encode() + b"\n"

    def validate(*args, **kwargs):
        if mode == "validation_failure":
            raise ValueError("generated identity mismatch")

    library = SimpleNamespace(
        encoded=encoded,
        load_protocol=lambda p: {},
        transport_cost=lambda *a, **k: {"base64_image_bytes": 40},
        validate_assessment=validate,
    )
    actual_popen = subprocess.Popen
    observed = []

    def launch(command, **kwargs):
        assert command[0] == "generated-cli" and command[-1] == "-"
        assert command.count("--image") == 1 and "--ephemeral" in command
        final = command[command.index("--output-last-message") + 1]
        source = (
            "import sys,pathlib,json;sys.stdin.read();pathlib.Path("
            + repr(final)
            + ").write_text("
            + repr(
                "not json"
                if mode == "malformed"
                else json.dumps({"continuity_notes": "generated own notes"})
            )
            + ",encoding='utf-8');print(json.dumps({'type':'thread.started','thread_id':'generated-unique-thread'}));print(json.dumps({'type':'turn.completed'}))"
        )
        child = actual_popen([sys.executable, "-c", source], **kwargs)
        observed.append(child)
        return child

    monkeypatch.setattr(script.subprocess, "Popen", launch)

    def fence(folder, reason):
        if not (folder / "STOP.json").exists():
            metadata.exclusive_json(folder / "STOP.json", {"reason": reason})

    def verify(root, lib, folder, c, identities, **kwargs):
        return metadata.verify_execution(folder, c, identities=identities, **kwargs)

    old = SimpleNamespace(
        SINGLES="generated",
        SCHEMA=schema,
        metadata=metadata,
        paths=lambda r: {"native": native, "producer": tmp_path},
        owner=lambda: {},
        assessment_prompt=lambda **k: "generated source-only prompt",
        fence=fence,
        verify_run=verify,
        source_chunks=lambda p: [chunk],
    )
    if mode == "success":
        assert script.run(tmp_path, output, None, old, library)["new_sessions"] == 1
        assert (output / "combined-target-index.json").is_file()
    else:
        with pytest.raises(ValueError):
            script.run(tmp_path, output, None, old, library)
        assert (output / "STOP.json").is_file()
        assert not (output / "combined-target-index.json").exists()
    assert len(observed) == 1 and observed[0].poll() == 0
    assert (output / "runs/generated-151/finish.json").is_file()
    with pytest.raises(ValueError):
        script.run(tmp_path, output, None, old, library)
    assert len(observed) == 1


def test_public_recovery_protocol_keeps_originals_and_deadline():
    script = load_script()
    work = Path(__file__).resolve().parents[1]
    protocol = json.loads(
        (work / "data/manifests/rally_reference_protocol_v6.json").read_bytes()
    )
    for number, expected in protocol["original_public_protocols"].items():
        assert (
            script.digest(
                work / f"data/manifests/rally_reference_protocol_v{number}.json"
            )
            == expected
        )
    assert protocol["frozen226_files"] == script.FROZEN_FILES
    assert protocol["inherited_deadline"] == script.INHERITED_DEADLINE
    assert (
        protocol["prior_attempted_image_bytes"] + protocol["planned_suffix_image_bytes"]
        == protocol["projected_cumulative_image_bytes"]
        == 8177560145
    )
    assert protocol["replacement"]["additional_replacements"] is False
    assert all(value is False for value in protocol["eligibility"].values())


def test_opaque_inventory_detects_content_membership_and_path_changes(tmp_path):
    original = tmp_path / "sealed.json"
    original.write_bytes(b"SEALED GENERATED LABELS")
    first = recovery.opaque_inventory(tmp_path)
    assert first["files"] == 1
    assert recovery.opaque_inventory(tmp_path) == first
    original.write_bytes(b"ALTERED GENERATED LABELS")
    assert recovery.opaque_inventory(tmp_path) != first
    original.write_bytes(b"SEALED GENERATED LABELS")
    assert recovery.opaque_inventory(tmp_path) == first
    original.rename(tmp_path / "different.json")
    assert recovery.opaque_inventory(tmp_path) != first
    (tmp_path / "new.json").write_bytes(b"new evidence")
    assert recovery.opaque_inventory(tmp_path)["files"] == 2


def test_empty_archive_cannot_be_a_preservation_seal(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        recovery.opaque_inventory(tmp_path)
