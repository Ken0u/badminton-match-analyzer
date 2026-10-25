"""Run the offline consumer on generated JSON; no scientific images are read."""

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
from badminton import rally_review_contract as contract
from badminton import rally_review_plan as planner
from badminton import rally_temporal_context as temporal

CHECKOUT = Path(__file__).resolve().parents[1]
SCRIPT = CHECKOUT / "scripts/validate_rally_review.py"


def encoded(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()


def plan_example(*, source_id="generated", unavailable=False):
    times = [
        Fraction(25, 2) + i * Fraction(1, 25) + (i // 2) * Fraction(1, 1000)
        for i in range(7)
    ]
    packet = {
        "source_id": source_id,
        "source_sha256": "a" * 64,
        "clock_sha256": "b" * 64,
        "eligibility": dict(temporal.ELIGIBILITY),
        "frames": [
            {
                "frame": n,
                "pts": stamp.numerator,
                "time_base": str(Fraction(1, stamp.denominator)),
                "time_s": float(stamp),
                "rotation": 90,
                "source_size": [32, 24],
                "display_size": [24, 32],
                "orientation_error": None,
                "corrupt": False,
                "image": {
                    "path": f"never-opened/{n}.png",
                    "bytes": 100,
                    "sha256": hashlib.sha256(str(n).encode()).hexdigest(),
                },
            }
            for n, stamp in enumerate(times)
        ],
    }
    sampled = temporal.sample_plan(packet)
    gallery = {
        "schema_version": 1,
        "plan": sampled,
        "sheets": [
            {
                "path": "sheet-000.png",
                "sha256": "e" * 64,
                "bytes": 100,
                "size": list(temporal.SHEET),
                "frames": [s["frame"] for s in sampled["samples"]],
            }
        ],
    }
    bindings = dict.fromkeys(planner.BINDING_KEYS, "d" * 64)
    bindings["packet_sha256"] = "c" * 64
    expected = {
        **{key: packet[key] for key in ("source_id", "source_sha256", "clock_sha256")},
        "packet_sha256": "c" * 64,
        "native_frame_count": 7,
    }
    _, plan = planner.plan_source(
        packet,
        gallery,
        expected_source=expected,
        bindings=bindings,
        max_images=2 if unavailable else 4,
    )
    return plan


def document_example(plan, plan_raw, batch, previous):
    frames = {row["frame"]: row for row in plan["frames"]}
    return {
        "schema_version": 1,
        "kind": "native_rally_review",
        "contract_sha256": contract.CONTRACT_SHA256,
        "plan_sha256": hashlib.sha256(plan_raw).hexdigest(),
        "source": copy.deepcopy(plan["source"]),
        "lane": "independent_a",
        "batch_index": batch["index"],
        "previous_document_sha256": previous,
        "observations": [
            {
                "frame": n,
                "native": copy.deepcopy(frames[n]),
                "camera": "unknown",
                "camera_view": None,
                "scene": "unknown",
                "contact": "unknown",
                "actor_ids": [],
                "notes": "PRIVATE generated café observation",
            }
            for n in batch["frames"]
        ],
        "actors": [],
        "events": [],
        "boundaries": {
            "opening": "unknown",
            "ending": "unknown",
            "notes": "PRIVATE generated boundary uncertainty",
        },
        "event_correspondence": [],
        "actor_correspondence": [],
        "notes": "PRIVATE generated source review; no actual images inspected",
    }


def workspace(tmp_path, *, unavailable=False, bundle=False):
    plan = plan_example(unavailable=unavailable)
    plan_raw = encoded(
        {"generated": plan, "another": plan_example(source_id="another")}
        if bundle
        else plan
    )
    (tmp_path / "plan.json").write_bytes(plan_raw)
    documents, previous = [], None
    for batch in plan["batches"]:
        doc = document_example(plan, plan_raw, batch, previous)
        raw = encoded(doc)
        name = f"document-{batch['index']:03d}.json"
        (tmp_path / name).write_bytes(raw)
        previous = hashlib.sha256(raw).hexdigest()
        documents.append(name)
    (tmp_path / "documents.json").write_bytes(
        encoded({"schema_version": 1, "documents": documents})
    )
    return plan, documents


def invoke(tmp_path, *extra, output="validated.json"):
    env = os.environ.copy()
    for key in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "AGENT_PROJECT_TOKEN",
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "BADMINTON_USERNAME",
        "BADMINTON_PASSWORD",
        "BASE_URL",
    ):
        env.pop(key, None)
    env.update(
        BADMINTON_ROOT=str(tmp_path),
        BADMINTON_DATA_DIR=str(tmp_path / "generated-data"),
        BADMINTON_WEIGHTS_DIR=str(tmp_path / "generated-weights"),
        PYTHONPATH=str(CHECKOUT / "backend"),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
    )
    command = [
        sys.executable,
        str(SCRIPT),
        "--plan",
        str(tmp_path / "plan.json"),
        "--documents",
        str(tmp_path / "documents.json"),
        "--lane",
        "independent_a",
        "--output",
        str(tmp_path / output),
        *extra,
    ]
    runs = tmp_path / "cli-runs"
    runs.mkdir(exist_ok=True)
    run = runs / f"run-{len(list(runs.iterdir())):03d}"
    run.mkdir(exist_ok=False)
    stdout, stderr = run / "stdout.log", run / "stderr.log"
    identities, observation_errors = {}, []
    with stdout.open("wb") as out, stderr.open("wb") as err:
        process = subprocess.Popen(
            command, cwd=CHECKOUT, env=env, stdout=out, stderr=err
        )
        while process.poll() is None:
            try:
                parent = psutil.Process(process.pid)
                for child in [parent, *parent.children(recursive=True)]:
                    try:
                        row = {
                            "pid": child.pid,
                            "created": child.create_time(),
                            "cwd": child.cwd(),
                            "command": child.cmdline(),
                        }
                        identities[(row["pid"], row["created"])] = row
                    except psutil.NoSuchProcess:
                        continue
                    except psutil.AccessDenied:
                        observation_errors.append(child.pid)
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                observation_errors.append(process.pid)
            time.sleep(0.01)
        code = process.wait()
    receipt = {
        "returncode": code,
        "identities": list(identities.values()),
        "observation_errors": observation_errors,
    }
    (run / "cli-process.json").write_bytes(encoded(receipt))
    assert not observation_errors, receipt
    assert identities, receipt
    for pid, created in identities:
        assert not (
            psutil.pid_exists(pid) and psutil.Process(pid).create_time() == created
        )
    return code, stdout.read_text(encoding="utf-8"), stderr.read_text(encoding="utf-8")


def test_actual_cli_preserves_native_denominators_unknowns_and_private_documents(
    tmp_path,
):
    plan, documents = workspace(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.glob("*.json")}
    code, stdout, stderr = invoke(tmp_path)
    assert code == 0, stderr
    summary = json.loads(stdout)
    result = json.loads((tmp_path / "validated.json").read_bytes())
    assert summary == result["summary"]
    assert summary["status"] == "structurally_complete"
    assert summary["expected_native_frames"] == summary["observed_native_frames"] == 7
    assert summary["missing_native_frames"] == 0
    assert summary["received_documents"] == len(documents) == len(plan["batches"])
    assert summary["observation_occurrences"] == sum(
        len(b["frames"]) for b in plan["batches"]
    )
    assert summary["repeated_overlap_observations"] == len(documents) - 1
    assert summary["complete_references"] == 0
    assert summary["eligibility"] == temporal.ELIGIBILITY
    assert (
        summary["execution_authorized"]
        is summary["scientific_acceptance_changed"]
        is False
    )
    assert "PRIVATE" not in stdout and "café" not in stdout
    assert "café" in (tmp_path / "validated.json").read_text(encoding="utf-8")
    assert b"\r" not in (tmp_path / "validated.json").read_bytes()
    for row, name in zip(result["documents"], documents, strict=True):
        assert (
            row["sha256"] == hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
        )
        assert row["document"] == json.loads((tmp_path / name).read_bytes())
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_prefix_output_keeps_full_expected_denominator(tmp_path):
    _, documents = workspace(tmp_path)
    (tmp_path / "documents.json").write_bytes(
        encoded({"schema_version": 1, "documents": documents[:1]})
    )
    code, stdout, stderr = invoke(tmp_path)
    assert code == 0, stderr
    summary = json.loads(stdout)
    assert summary["status"] == "incomplete"
    assert summary["expected_native_frames"] == 7
    assert summary["observed_native_frames"] == 3
    assert summary["missing_native_frames"] == 4


def test_unavailable_plan_does_not_shrink_source_denominator(tmp_path):
    workspace(tmp_path, unavailable=True)
    code, stdout, stderr = invoke(tmp_path)
    assert code == 0, stderr
    summary = json.loads(stdout)
    assert summary["status"] == "unavailable"
    assert summary["expected_native_frames"] == summary["missing_native_frames"] == 7
    assert summary["observed_native_frames"] == 0


def test_source_bundle_requires_explicit_selection(tmp_path):
    workspace(tmp_path, bundle=True)
    code, stdout, _ = invoke(tmp_path)
    assert code == 2 and not stdout and not (tmp_path / "validated.json").exists()
    code, stdout, stderr = invoke(tmp_path, "--source", "generated")
    assert code == 0, stderr
    summary = json.loads(stdout)
    assert summary["selection_scope"]["plan_container"] == "bundle"
    assert summary["selection_scope"]["selected_source_count"] == 1
    assert summary["selection_scope"]["supplied_source_count"] == 2


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "lane",
        "previous_hash",
        "frame",
        "plan_hash",
        "contract_hash",
        "unknown_field",
        "boolean_index",
        "reordered",
        "duplicate_key",
        "nonfinite",
        "invalid_utf8",
    ],
)
def test_rejected_document_cannot_create_or_replace_output(tmp_path, mutation):
    _, names = workspace(tmp_path)
    path = tmp_path / names[1]
    doc = json.loads(path.read_bytes())
    if mutation == "source":
        doc["source"]["clock_sha256"] = "f" * 64
    elif mutation == "lane":
        doc["lane"] = "independent_b"
    elif mutation == "previous_hash":
        doc["previous_document_sha256"] = "f" * 64
    elif mutation == "frame":
        doc["observations"].pop()
    elif mutation == "plan_hash":
        doc["plan_sha256"] = "f" * 64
    elif mutation == "contract_hash":
        doc["contract_sha256"] = "f" * 64
    elif mutation == "unknown_field":
        doc["scientific_truth"] = True
    elif mutation == "boolean_index":
        doc["batch_index"] = True
    elif mutation == "reordered":
        names.reverse()
        (tmp_path / "documents.json").write_bytes(
            encoded({"schema_version": 1, "documents": names})
        )
    raw = encoded(doc)
    if mutation == "duplicate_key":
        raw = b'{"schema_version":1,"schema_version":1}'
    elif mutation == "nonfinite":
        raw = b'{"schema_version":NaN}'
    elif mutation == "invalid_utf8":
        raw = b"\xff"
    path.write_bytes(raw)
    code, stdout, stderr = invoke(tmp_path)
    assert code == 2 and stdout == ""
    assert "PRIVATE" not in stderr
    assert not (tmp_path / "validated.json").exists()
    (tmp_path / "validated.json").write_bytes(b"preserve original result")
    code, _, _ = invoke(tmp_path)
    assert code == 2
    assert (tmp_path / "validated.json").read_bytes() == b"preserve original result"


def test_whitespace_change_in_previous_raw_document_invalidates_chain(tmp_path):
    _, names = workspace(tmp_path)
    first = tmp_path / names[0]
    first.write_bytes(first.read_bytes() + b" \n")
    code, _, _ = invoke(tmp_path)
    assert code == 2 and not (tmp_path / "validated.json").exists()


@pytest.mark.parametrize(
    "name",
    [
        "../outside.json",
        "/outside.json",
        "C:/outside.json",
        "sub\\file.json",
        "sub/../file.json",
        "document-000.png",
        "",
        True,
    ],
)
def test_unsafe_manifest_members_are_rejected_before_output(tmp_path, name):
    workspace(tmp_path)
    (tmp_path / "documents.json").write_bytes(
        encoded({"schema_version": 1, "documents": [name]})
    )
    code, _, _ = invoke(tmp_path)
    assert code == 2 and not (tmp_path / "validated.json").exists()


def test_duplicate_manifest_paths_and_unknown_manifest_fields_are_rejected(tmp_path):
    _, names = workspace(tmp_path)
    for manifest in (
        {"schema_version": 1, "documents": [names[0], names[0]]},
        {"schema_version": True, "documents": []},
        {"schema_version": 1, "documents": [], "extra": 1},
    ):
        (tmp_path / "documents.json").write_bytes(encoded(manifest))
        code, _, _ = invoke(tmp_path)
        assert code == 2 and not (tmp_path / "validated.json").exists()


def test_existing_success_output_is_never_overwritten(tmp_path):
    workspace(tmp_path)
    original = b"preexisting private output"
    (tmp_path / "validated.json").write_bytes(original)
    code, stdout, _ = invoke(tmp_path)
    assert code == 2 and not stdout
    assert (tmp_path / "validated.json").read_bytes() == original


@pytest.mark.parametrize("target", ["plan", "document", "parent", "output"])
def test_symlink_input_or_output_preserves_targets(tmp_path, target):
    _, names = workspace(tmp_path)
    real = tmp_path / "real.json"
    real.write_bytes(b"private original target")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation unavailable on this host")
    if target == "plan":
        (tmp_path / "plan.json").unlink()
        (tmp_path / "plan.json").symlink_to(real)
    elif target == "document":
        (tmp_path / "documents.json").write_bytes(
            encoded({"schema_version": 1, "documents": ["link.json"]})
        )
    elif target == "parent":
        directory = tmp_path / "directory"
        directory.mkdir()
        (directory / "doc.json").write_bytes((tmp_path / names[0]).read_bytes())
        (tmp_path / "linked-directory").symlink_to(directory, target_is_directory=True)
        (tmp_path / "documents.json").write_bytes(
            encoded({"schema_version": 1, "documents": ["linked-directory/doc.json"]})
        )
    else:
        (tmp_path / "validated.json").symlink_to(real)
    code, _, _ = invoke(tmp_path)
    assert code == 2
    assert real.read_bytes() == b"private original target"


def script_module():
    spec = importlib.util.spec_from_file_location("generated_review_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_cli_byte_limits_and_same_bytes_read(tmp_path, monkeypatch):
    module = script_module()
    raw = b'{"generated":true}\n'
    path = tmp_path / "data.json"
    path.write_bytes(raw)
    assert module.read_bytes(path, len(raw)) == raw
    with pytest.raises(ValueError, match="byte limit"):
        module.read_bytes(path, len(raw) - 1)
    first = module.file_identity
    calls = []

    def changed(info):
        result = first(info)
        calls.append(result)
        return (*result[:-1], result[-1] + int(len(calls) > 1))

    monkeypatch.setattr(module, "file_identity", changed)
    with pytest.raises(ValueError, match="changed"):
        module.read_bytes(path, len(raw))


def test_manifest_count_cap_is_enforced_without_opening_documents(tmp_path):
    module = script_module()
    manifest = {
        "schema_version": 1,
        "documents": [f"{n}.json" for n in range(module.MAX_DOCUMENTS + 1)],
    }
    with pytest.raises(ValueError, match="manifest"):
        module.document_paths(encoded(manifest), tmp_path, contract.strict_json)


@pytest.mark.parametrize("target", ["file", "parent"])
def test_reparse_attribute_is_rejected_without_symlink_creation(
    tmp_path, monkeypatch, target
):
    module = script_module()
    directory = tmp_path / "generated-directory"
    directory.mkdir()
    path = directory / "generated.json"
    path.write_bytes(b"{}")
    selected = path if target == "file" else directory
    original = Path.lstat

    def reparse(value):
        info = original(value)
        if value == selected:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(ValueError, match="reparse"):
        module.ordinary_path(path)


def test_combined_input_limit_rejects_before_creating_output(tmp_path, monkeypatch):
    _, documents = workspace(tmp_path)
    module = script_module()
    maximum = (
        sum(
            (tmp_path / name).stat().st_size
            for name in ("plan.json", "documents.json", documents[0])
        )
        - 1
    )
    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", maximum)
    args = SimpleNamespace(
        plan=tmp_path / "plan.json",
        documents=tmp_path / "documents.json",
        lane="independent_a",
        source=None,
        output=tmp_path / "validated.json",
    )
    with pytest.raises(ValueError, match="Combined JSON inputs"):
        module.run(args)
    assert not args.output.exists()


def test_public_manifest_mirrors_exact_contract_and_cli_limits():
    module = script_module()
    protocol = json.loads(
        (CHECKOUT / "data/manifests/rally_review_contract_v1.json").read_bytes()
    )
    assert protocol["schema_version"] == 1 and protocol["task"] == 270
    assert protocol["contract"] == contract.CONTRACT
    assert protocol["contract_sha256"] == contract.CONTRACT_SHA256
    assert protocol["io_limits"] == module.IO_LIMITS
