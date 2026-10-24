"""Generated execution evidence; no scientific input or external transport."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import psutil
import pytest
from badminton import rally_reference_continuation as continuation


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    continuation.exclusive_json(path, value)
    return path


def execution(tmp_path):
    folder = tmp_path / "generated"
    folder.mkdir()
    document = folder / "original-final.json"
    document.write_text('"SEALED GENERATED SCIENTIFIC CONTENT"', encoding="utf-8")
    image = {"frame": 7, "sha256": "a" * 64}
    start = {
        "pid": 1,
        "creation_time": 1,
        "started_at": 40,
        "images": [image],
        "image_bytes": 16,
        "session_id": "generated-session",
    }
    rows = [
        {"type": "thread.started", "thread_id": "generated-thread", "bytes": 10},
        {"type": "turn.completed", "bytes": 20},
    ]
    finish = {
        **start,
        "ended_at": 50,
        "exit_code": 0,
        "exited": True,
        "thread_id": "generated-thread",
        "events": {"thread.started": 1, "turn.completed": 1},
        "stdout_bytes": 30,
        "original_output_sha256": continuation.digest(document),
    }
    write(folder / "start.json", start)
    write(folder / "finish.json", finish)
    write(
        folder / "payload-reservation.json",
        {
            "reserved_at": 30,
            "lane": "adjudication",
            "source_id": "generated-source",
            "chunk": 0,
            "image_bytes": 16,
            "images": [image],
        },
    )
    (folder / "events.jsonl").write_text(
        "\n".join(json.dumps(row, indent=2) for row in rows), encoding="utf-8"
    )
    chunk = {
        "source_id": "generated-source",
        "index": 0,
        "frames": [7],
        "image_bytes": 16,
    }
    return folder, chunk


def check(folder, chunk, **kwargs):
    return continuation.verify_execution(
        folder,
        chunk,
        granted_at=10,
        frozen_at=20,
        deadline=60,
        identities=continuation.Identities(),
        **kwargs,
    )


def mutate(path, **values):
    value = continuation.read(path)
    value.update(values)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_archived_deadline_is_not_a_new_dispatch_permission():
    saved = {"granted_at": 10, "deadline": 100, "consumers": {"source": "frozen"}}
    assert continuation.archived_context(saved, dict(saved)) == (10, 100)
    with pytest.raises(ValueError, match="not open"):
        continuation.current_deadline(10, now=100, seconds=90)
    assert continuation.current_deadline(200, now=201, seconds=90) == 290
    with pytest.raises(ValueError, match="changed"):
        continuation.archived_context(saved, {**saved, "deadline": 1000})


@pytest.mark.parametrize("value", [True, False, 0.0, -1, None, "1"])
def test_exact_integer_fields(value):
    with pytest.raises(ValueError):
        continuation.integer(value)


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), -1, "10"])
def test_finite_time_fields(value):
    with pytest.raises(ValueError):
        continuation.moment(value)


def test_execution_hashes_labels_without_reading_them(tmp_path, monkeypatch):
    folder, chunk = execution(tmp_path)
    reader = continuation.read

    def metadata_only(path):
        assert Path(path).name != "original-final.json"
        return reader(path)

    monkeypatch.setattr(continuation, "read", metadata_only)
    entry = check(folder, chunk)
    index = continuation.complete_index([chunk], [entry])
    assert index["complete"] is True
    assert index["scientific_labels_read"] is False
    with pytest.raises(ValueError, match="complete target indexes"):
        continuation.complete_index([chunk, {**chunk, "index": 1}], [entry])
    (folder / "original-final.json").write_bytes(b"mutated")
    with pytest.raises(ValueError, match="artifact changed"):
        continuation.complete_index([chunk], [entry])


@pytest.mark.parametrize(
    "field,value",
    [
        ("exit_code", False),
        ("exit_code", 0.0),
        ("exit_code", 1),
        ("exited", 1),
        ("thread_id", ""),
        ("session_id", None),
        ("pid", True),
        ("creation_time", True),
    ],
)
def test_malformed_execution_identity_is_rejected(tmp_path, field, value):
    folder, chunk = execution(tmp_path)
    mutate(folder / "finish.json", **{field: value})
    with pytest.raises(ValueError):
        check(folder, chunk)


@pytest.mark.parametrize(
    "file,field,value",
    [
        ("start.json", "started_at", 1),
        ("finish.json", "ended_at", 60),
        ("payload-reservation.json", "reserved_at", 41),
        ("payload-reservation.json", "chunk", False),
        ("payload-reservation.json", "image_bytes", 16.0),
    ],
)
def test_execution_timing_and_native_metadata_are_strict(tmp_path, file, field, value):
    folder, chunk = execution(tmp_path)
    mutate(folder / file, **{field: value})
    with pytest.raises(ValueError):
        check(folder, chunk)


def test_duplicate_thread_session_or_lifetime_is_rejected(tmp_path):
    folder, chunk = execution(tmp_path)
    check(folder, chunk)
    original = continuation.read(folder / "finish.json")
    for key in ("thread_id", "session_id", "pid"):
        identities = continuation.Identities()
        identities.add(original)
        other = {
            **original,
            "thread_id": "new-thread",
            "session_id": "new-session",
            "pid": 2,
        }
        other[key] = original[key]
        with pytest.raises(ValueError, match="Reused"):
            identities.add(other)


def test_frame_alias_and_changed_event_log_are_rejected(tmp_path):
    folder, chunk = execution(tmp_path)
    with pytest.raises(ValueError):
        check(folder, {**chunk, "frames": [7.0]})
    (folder / "events.jsonl").write_text(
        '{"type":"turn.failed","bytes":30}', encoding="utf-8"
    )
    with pytest.raises(ValueError):
        check(folder, chunk)


def test_failed_repeated_attempts_are_each_charged(tmp_path):
    paths = [write(tmp_path / str(i), {"image_bytes": 10}) for i in range(3)]
    assert continuation.payload_total(100, paths) == 130
    with pytest.raises(ValueError, match="exceeds"):
        continuation.payload_total(100, paths, limit=129)
    with pytest.raises(ValueError, match="Duplicate"):
        continuation.payload_total(100, [*paths, paths[0]])
    paths[0].write_text('{"image_bytes":true}', encoding="utf-8")
    with pytest.raises(ValueError):
        continuation.payload_total(100, paths)


def test_reservation_is_durable_before_launch_and_preserves_failure(tmp_path):
    output = tmp_path / "output"
    run = output / "runs" / "generated-000"
    run.mkdir(parents=True)
    reservation = {"run_name": run.name, "image_bytes": 16}

    def launch():
        assert continuation.read(run / "payload-reservation.json")["image_bytes"] == 16
        raise OSError("generated transport failure")

    with pytest.raises(OSError):
        continuation.reserve_and_launch(
            output, reservation, granted_at=10, prior_bytes=100, launch=launch, now=11
        )
    assert (
        continuation.payload_total(100, output.glob("runs/*/payload-reservation.json"))
        == 116
    )
    assert (output / "STOP.json").exists()
    with pytest.raises(ValueError, match="fenced"):
        continuation.reserve_and_launch(
            output,
            reservation,
            granted_at=10,
            prior_bytes=100,
            launch=lambda: pytest.fail("must not launch"),
            now=11,
        )


def test_deadline_and_budget_refuse_before_reservation_or_child(tmp_path):
    (tmp_path / "runs" / "generated").mkdir(parents=True)
    reservation = {"run_name": "generated", "image_bytes": 16}
    for granted, now, prior in [
        (10, 10 + 8 * 3600 - 60, 0),
        (10, 11, continuation.MAX_BYTES),
    ]:
        with pytest.raises(ValueError):
            continuation.reserve_and_launch(
                tmp_path,
                reservation,
                granted_at=granted,
                prior_bytes=prior,
                launch=lambda: pytest.fail("must not launch"),
                now=now,
            )
        assert not (tmp_path / "runs/generated/payload-reservation.json").exists()


def test_exclusive_outputs_keep_original_bytes(tmp_path):
    path = write(tmp_path / "sealed.json", {"original": True})
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        continuation.exclusive_json(path, {"original": False})
    assert path.read_bytes() == original


def test_actual_process_lifetime_is_not_declared_exited():
    process = psutil.Process()
    with pytest.raises(ValueError, match="remains live"):
        continuation.absent(
            {"pid": process.pid, "creation_time": process.create_time()}
        )
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        observed = psutil.Process(child.pid)
        row = {"pid": observed.pid, "creation_time": observed.create_time()}
    except psutil.NoSuchProcess:
        row = None
    assert child.wait() == 0
    if row:
        continuation.absent(row)


@pytest.mark.parametrize("run_name", ["../outside", "a/b", "a\\b", ".", "", None, True])
def test_reservation_cannot_escape_output(tmp_path, run_name):
    with pytest.raises(ValueError, match="run name"):
        continuation.reserve_and_launch(
            tmp_path,
            {"run_name": run_name, "image_bytes": 1},
            granted_at=10,
            prior_bytes=0,
            launch=lambda: pytest.fail("must not launch"),
            now=11,
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "mode",
    ["success", "malformed", "tool", "failed", "duplicate", "oversized", "stderr"],
)
def test_actual_child_output_is_drained_and_exit_observed(tmp_path, monkeypatch, mode):
    rows = [{"type": "thread.started", "thread_id": "generated-thread"}]
    if mode == "duplicate":
        rows += rows
    rows.append(
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution" if mode == "tool" else "agent_message",
                "text": "GENERATED_SECRET_PAYLOAD",
            },
        }
    )
    rows.append({"type": "turn.failed" if mode == "failed" else "turn.completed"})
    stdout = "\n".join(json.dumps(row) for row in rows) + "\n"
    if mode == "malformed":
        stdout += "not json\n"
    if mode == "oversized":
        stdout += "x" * 4096
    stderr = "GENERATED_SECRET_STDERR" * (200 if mode == "stderr" else 1)
    monkeypatch.setattr(continuation, "MAX_LOG_BYTES", 2048)
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys;sys.stdin.read();sys.stdout.buffer.write("
            + repr(stdout.encode())
            + ");sys.stderr.buffer.write("
            + repr(stderr.encode())
            + ")",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    reasons = []
    result = continuation.collect_output(
        child, "generated prompt", tmp_path, reasons.append
    )
    assert child.poll() == result["exit_code"] == 0
    assert result["exited"] is True
    assert result["stderr_bytes"] == len(stderr.encode())
    assert result["stdout_bytes"] == len(stdout.encode())
    log = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "GENERATED_SECRET" not in log
    assert len(log.encode()) < 2048
    assert bool(reasons) == (mode != "success")
    assert bool(result["execution_protocol_failures"]) == (mode != "success")


def load_script():
    path = Path(__file__).resolve().parents[1] / "scripts/continue_rally_references.py"
    spec = importlib.util.spec_from_file_location("generated_continuation_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_global_gate_returns_before_any_scientific_reader(tmp_path, monkeypatch):
    script = load_script()
    monkeypatch.setattr(script, "verify_current", lambda *a, **k: ({}, 0))
    monkeypatch.setattr(
        script,
        "predecessor",
        lambda *a, **k: pytest.fail(
            "must not read source evidence before complete indexes"
        ),
    )
    assert script.audit(tmp_path, tmp_path, None, None) == {
        "ready": False,
        "reason": "both_complete_target_indexes_required",
        "scientific_labels_read": False,
    }


def test_original_public_schema_and_rubric_remain_source_only():
    script = load_script()
    assert script.SCHEMA["properties"]["stream"]["enum"] == [
        "independent_a",
        "independent_b",
        "adjudication",
    ]
    assert script.SCHEMA["additionalProperties"] is False
    prompt = script.assessment_prompt(
        session="generated-session",
        sid="generated-source",
        previous=None,
        own_notes="generated own notes",
        assigned=[],
    )
    assert "issue226" in prompt
    assert "No original assessor labels" in prompt
    assert "No tools, filesystem, network" in prompt
    assert "Same-stream prior source-only continuity" in prompt
    assert "exclude half smash" in prompt


def test_successor_protocol_preserves_originals_and_denominators():
    script = load_script()
    work = Path(__file__).resolve().parents[1]
    protocol = json.loads(
        (work / "data/manifests/rally_reference_protocol_v5.json").read_bytes()
    )
    for number, expected in protocol["original_public_protocols"].items():
        assert (
            script.metadata.digest(
                work / f"data/manifests/rally_reference_protocol_v{number}.json"
            )
            == expected
        )
    assert protocol["native_frames"] == {"go2uajSiBnE": 991, "H1setLK1tig": 541}
    assert protocol["retained_successes"] == {"go2uajSiBnE": 94, "H1setLK1tig": 84}
    assert protocol["remaining_singles_chunks"] == {
        "first": 94,
        "last": 171,
        "count": 78,
    }
    assert (
        protocol["payload"]["projected_cumulative_image_bytes"]
        == 8169246915
        < 8 * 1024**3
    )
    assert all(value is False for value in protocol["eligibility"].values())
