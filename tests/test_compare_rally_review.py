"""Actual offline CLI and generated-file safety checks; no scientific source I/O."""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psutil
import pytest
from badminton import rally_review_contract as contract
from test_rally_review_comparison import inputs, known_documents
from test_rally_review_contract import rebuild_chain
from test_rally_review_contract_cli import CLI_STARTUP_GATE

CHECKOUT = Path(__file__).resolve().parents[1]
SCRIPT = CHECKOUT / "scripts/compare_rally_review.py"


def workspace(tmp_path, *, unavailable=False, bundle=False, adjudication=False):
    plan, raw, streams = inputs(unavailable=unavailable, first=40, rotation=90)
    if bundle:
        raw = contract.encode_json({"generated": plan})
    if adjudication:
        streams["source_adjudication"] = []
    for lane in streams:
        docs = known_documents(plan, lane, plan_raw=raw)
        parsed = [contract.strict_json(doc) for doc in docs]
        for doc in parsed:
            doc["notes"] = "PRIVATE generated original judgments"
        streams[lane] = rebuild_chain(parsed)
    (tmp_path / "plan.json").write_bytes(raw)
    for lane, docs in streams.items():
        directory = tmp_path / lane
        directory.mkdir()
        names = []
        for index, raw_doc in enumerate(docs):
            name = f"{lane}/{index:03d}.json"
            (tmp_path / name).write_bytes(raw_doc)
            names.append(name)
        (tmp_path / (lane + ".json")).write_bytes(
            contract.encode_json({"schema_version": 1, "documents": names})
        )
    return plan, streams


def arguments(tmp_path, *, adjudication=False):
    return SimpleNamespace(
        plan=tmp_path / "plan.json",
        independent_a=tmp_path / "independent_a.json",
        independent_b=tmp_path / "independent_b.json",
        source_adjudication=tmp_path / "source_adjudication.json"
        if adjudication
        else None,
        source=None,
        output=tmp_path / "comparison.json",
    )


def invoke(tmp_path, *extra, adjudication=False):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("BADMINTON_")
        and key
        not in (
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "AGENT_PROJECT_TOKEN",
            "OPENAI_API_KEY",
            "CODEX_API_KEY",
            "BASE_URL",
        )
    }
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
        "--independent-a",
        str(tmp_path / "independent_a.json"),
        "--independent-b",
        str(tmp_path / "independent_b.json"),
        "--output",
        str(tmp_path / "comparison.json"),
    ]
    if adjudication:
        command += ["--source-adjudication", str(tmp_path / "source_adjudication.json")]
    command += extra
    directory = tmp_path / ("process-" + uuid4().hex)
    directory.mkdir()
    gate, startup = directory / "gate.py", directory / "startup.json"
    gate.write_text(CLI_STARTUP_GATE, encoding="utf-8", newline="\n")
    nonce = uuid4().hex
    gated = [command[0], str(gate), str(startup), nonce, *command[1:]]
    identities = {}

    def observe(process):
        try:
            owner = psutil.Process(process.pid)
            for child in [owner, *owner.children(recursive=True)]:
                try:
                    identity = {
                        "pid": child.pid,
                        "created": child.create_time(),
                        "cwd": child.cwd(),
                        "command": child.cmdline(),
                    }
                    identities[(child.pid, identity["created"])] = identity
                except psutil.NoSuchProcess:
                    pass
        except psutil.NoSuchProcess:
            pass

    stdout, stderr = directory / "stdout.log", directory / "stderr.log"
    startup_error, verified = None, False
    with stdout.open("wb") as out, stderr.open("wb") as err:
        process = subprocess.Popen(
            gated, cwd=CHECKOUT, env=env, stdin=subprocess.PIPE, stdout=out, stderr=err
        )
        try:
            deadline = time.monotonic() + 10
            while not startup.exists():
                observe(process)
                assert process.poll() is None and time.monotonic() < deadline
                time.sleep(0.01)
            record = json.loads(startup.read_bytes())
            observe(process)
            identity = identities[(record["pid"], record["created"])]
            assert record["nonce"] == nonce
            assert identity["command"] == record["command"]
            assert identity["command"][1:] == gated[1:]
            assert Path(identity["cwd"]).resolve() == CHECKOUT
            verified = True
            process.stdin.write(b"\n")
            process.stdin.flush()
        except BaseException as error:
            startup_error = error
        finally:
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
        while process.poll() is None:
            observe(process)
            time.sleep(0.01)
        code = process.wait()
    for identity in identities.values():
        try:
            identity["independently_absent_lifetime"] = (
                psutil.Process(identity["pid"]).create_time() != identity["created"]
            )
        except psutil.NoSuchProcess:
            identity["independently_absent_lifetime"] = True
    (directory / "receipt.json").write_bytes(
        contract.encode_json(
            {
                "command": command,
                "startup_verified": verified,
                "returncode": code,
                "identities": list(identities.values()),
            }
        )
    )
    assert identities and all(
        i["independently_absent_lifetime"] for i in identities.values()
    )
    if startup_error:
        raise startup_error
    assert verified
    return code, stdout.read_text(encoding="utf-8"), stderr.read_text(encoding="utf-8")


def snapshot(tmp_path):
    return {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*.json")}


@pytest.mark.parametrize("adjudication", [False, True])
def test_actual_cli_preserves_originals_and_private_details_with_aggregate_stdout(
    tmp_path, adjudication
):
    _, streams = workspace(tmp_path, adjudication=adjudication)
    before = snapshot(tmp_path)
    code, stdout, stderr = invoke(tmp_path, adjudication=adjudication)
    assert code == 0, stderr
    result = json.loads((tmp_path / "comparison.json").read_bytes())
    assert json.loads(stdout) == result["summary"]
    assert result["summary"]["expected_native_frames"] == 9
    assert result["summary"]["field_status_counts"]["scene"]["agreement"] == 9
    assert result["summary"]["adjudication_provided"] is adjudication
    assert "PRIVATE" not in stdout and "local-view" not in stdout
    assert str(tmp_path) not in stdout and "source_sha256" not in stdout
    assert b"PRIVATE" in (tmp_path / "comparison.json").read_bytes()
    assert result["summary"]["assessor_independence"] == "unavailable"
    assert result["coverage"]["expected_frames"] == list(range(40, 49))
    for path, raw in before.items():
        assert (tmp_path / path).read_bytes() == raw
    for lane, docs in streams.items():
        assert result["input_manifests"][lane]["documents"] == [
            hashlib.sha256(doc).hexdigest() for doc in docs
        ]
    assert not (tmp_path / "generated-data").exists()


def test_actual_cli_unavailable_and_bundle_selection(tmp_path):
    workspace(tmp_path, unavailable=True, bundle=True)
    code, stdout, _ = invoke(tmp_path)
    assert code == 2 and not stdout
    assert not (tmp_path / "comparison.json").exists()
    code, stdout, stderr = invoke(tmp_path, "--source", "generated")
    assert code == 0, stderr
    summary = json.loads(stdout)
    assert summary["status"] == "unavailable"
    assert summary["expected_native_frames"] == 9
    assert summary["field_status_counts"]["contact"]["missing"] == 9


@pytest.mark.parametrize("collision", ["comparison.json", "plan.json"])
def test_actual_cli_preserves_output_and_input_collisions(tmp_path, collision):
    workspace(tmp_path)
    output = tmp_path / collision
    if not output.exists():
        output.write_bytes(b"preserved existing result\n")
    before = output.read_bytes()
    code, stdout, stderr = invoke(tmp_path, "--output", str(output))
    assert code == 2 and not stdout
    assert output.read_bytes() == before
    assert str(tmp_path) not in stderr and "PRIVATE" not in stderr


@pytest.mark.parametrize(
    "bad",
    [
        "../plan.json",
        "/absolute.json",
        "C:/outside.json",
        "folder\\file.json",
        "a/../b.json",
    ],
)
def test_actual_cli_rejects_unsafe_manifest_document_paths(tmp_path, bad):
    workspace(tmp_path)
    (tmp_path / "independent_b.json").write_bytes(
        contract.encode_json({"schema_version": 1, "documents": [bad]})
    )
    code, stdout, stderr = invoke(tmp_path)
    assert code == 2 and not stdout
    assert not (tmp_path / "comparison.json").exists()
    assert bad not in stderr


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_path", "duplicate_key", "nonfinite", "wrong_lane", "raw_chain"],
)
def test_actual_cli_rejects_invalid_bytes_without_partial_publication(
    tmp_path, mutation
):
    _, streams = workspace(tmp_path)
    manifest = tmp_path / "independent_b.json"
    first = tmp_path / "independent_b/000.json"
    if mutation == "duplicate_path":
        manifest.write_bytes(
            contract.encode_json(
                {"schema_version": 1, "documents": ["independent_b/000.json"] * 2}
            )
        )
    elif mutation == "duplicate_key":
        manifest.write_bytes(b'{"schema_version":1,"schema_version":1,"documents":[]}')
    elif mutation == "nonfinite":
        first.write_bytes(b'{"private":NaN}')
    elif mutation == "wrong_lane":
        first.write_bytes(streams["independent_a"][0])
    else:
        first.write_bytes(first.read_bytes() + b"\n")
    before = snapshot(tmp_path)
    code, stdout, stderr = invoke(tmp_path)
    assert code == 2 and not stdout
    assert "PRIVATE" not in stderr and str(tmp_path) not in stderr
    assert not (tmp_path / "comparison.json").exists()
    assert all((tmp_path / p).read_bytes() == raw for p, raw in before.items())


def load_cli():
    spec = importlib.util.spec_from_file_location("comparison_cli_generated", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("limit", ["input", "documents", "output"])
def test_combined_limits_apply_before_any_output(tmp_path, monkeypatch, capsys, limit):
    workspace(tmp_path)
    module = load_cli()
    args = arguments(tmp_path)
    if limit == "input":
        monkeypatch.setattr(module, "MAX_TOTAL_BYTES", args.plan.stat().st_size + 1)
    elif limit == "documents":
        monkeypatch.setattr(module, "MAX_DOCUMENTS", 1)
    else:
        total = sum(p.stat().st_size for p in tmp_path.rglob("*.json"))
        monkeypatch.setattr(module, "MAX_TOTAL_BYTES", total + 1)
    with pytest.raises(ValueError):
        module.run(args)
    assert not args.output.exists() and not capsys.readouterr().out


def test_reparse_or_symlink_inputs_are_rejected_without_following_them(tmp_path):
    workspace(tmp_path)
    link = tmp_path / "linked.json"
    try:
        link.symlink_to(tmp_path / "independent_b.json")
    except OSError as error:
        pytest.skip(
            f"Creating test symlinks unavailable on this host: {error.winerror if hasattr(error, 'winerror') else error.errno}"
        )
    code, stdout, _ = invoke(tmp_path, "--independent-b", str(link))
    assert code == 2 and not stdout
    assert not (tmp_path / "comparison.json").exists()


def test_cross_stream_duplicate_paths_are_rejected_before_label_comparison(tmp_path):
    workspace(tmp_path)
    (tmp_path / "independent_b.json").write_bytes(
        (tmp_path / "independent_a.json").read_bytes()
    )
    code, stdout, _ = invoke(tmp_path)
    assert code == 2 and not stdout
    assert not (tmp_path / "comparison.json").exists()


@pytest.mark.parametrize("mode", ["partial", "external_change"])
def test_actual_bounded_reader_rejects_partial_or_changed_document_reads(
    tmp_path, monkeypatch, capsys, mode
):
    workspace(tmp_path)
    module = load_cli()
    args = arguments(tmp_path)
    target = tmp_path / "independent_b/000.json"
    original = target.read_bytes()
    original_open = Path.open

    class InterruptedRead:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, limit):
            raw = self.stream.read(limit)
            if mode == "partial":
                return raw[:-1]
            with original_open(target, "ab") as writer:
                writer.write(b"\n")
            return raw

    def interrupted(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        if path == target and args == ("rb",):
            return InterruptedRead(stream)
        return stream

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", interrupted)
        with pytest.raises(ValueError, match="changed"):
            module.run(args)
    assert not args.output.exists() and not capsys.readouterr().out
    assert target.read_bytes() == original + (
        b"\n" if mode == "external_change" else b""
    )
