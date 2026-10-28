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


class CLIProcessObserver:
    """Keep denied observations distinct from identity and terminal evidence."""

    def __init__(self, process_factory=None):
        self.process_factory = process_factory or psutil.Process
        self.identities = {}
        self.unavailable = {}

    def read(self, process, field, phase):
        if field == "children":
            return process.children(recursive=True)
        return getattr(process, field)()

    def denied(self, pid, created, field, phase):
        key = (pid, created, field, phase)
        item = self.unavailable.setdefault(
            key,
            {
                "pid": pid,
                "created": created,
                "field": field,
                "phase": phase,
                "status": "unavailable",
                "count": 0,
            },
        )
        item["count"] += 1

    def remember(self, process, phase):
        try:
            created = self.read(process, "create_time", phase)
        except psutil.AccessDenied:
            self.identities.setdefault(
                (process.pid, None), {"pid": process.pid, "created": None}
            )
            self.denied(process.pid, None, "create_time", phase)
            return
        except psutil.NoSuchProcess:
            return
        identity = self.identities.setdefault(
            (process.pid, created), {"pid": process.pid, "created": created}
        )
        try:
            cwd = self.read(process, "cwd", phase)
        except psutil.AccessDenied:
            self.denied(process.pid, created, "cwd", phase)
            return
        except psutil.NoSuchProcess:
            return
        try:
            command = self.read(process, "cmdline", phase)
        except psutil.AccessDenied:
            self.denied(process.pid, created, "cmdline", phase)
            return
        except psutil.NoSuchProcess:
            return
        identity.update(cwd=cwd, command=command)

    def observe(self, process, phase):
        try:
            owner = self.process_factory(process.pid)
        except psutil.AccessDenied:
            self.identities.setdefault(
                (process.pid, None), {"pid": process.pid, "created": None}
            )
            self.denied(process.pid, None, "process", phase)
            return
        except psutil.NoSuchProcess:
            return
        self.remember(owner, phase)
        try:
            children = self.read(owner, "children", phase)
        except psutil.AccessDenied:
            self.denied(owner.pid, None, "children", phase)
            return
        except psutil.NoSuchProcess:
            return
        for child in children:
            self.remember(child, phase)

    def startup_identity(self, record, nonce, gated):
        assert record["nonce"] == nonce
        identity = self.identities.get((record["pid"], record["created"]))
        if identity is None or not {"cwd", "command"} <= identity.keys():
            return None
        assert identity["command"] == record["command"]
        assert identity["command"][1:] == gated[1:]
        assert (
            Path(record["cwd"]).resolve() == Path(identity["cwd"]).resolve() == CHECKOUT
        )
        return dict(identity)

    def verify_terminal(self):
        for identity in self.identities.values():
            try:
                process = self.process_factory(identity["pid"])
                current = self.read(process, "create_time", "terminal")
                absent = (
                    current != identity["created"]
                    if identity["created"] is not None
                    else None
                )
            except psutil.NoSuchProcess:
                absent = True
            except psutil.AccessDenied:
                absent = None
                self.denied(
                    identity["pid"], identity["created"], "create_time", "terminal"
                )
            identity["independently_absent_lifetime"] = absent


def invoke(tmp_path, *extra, adjudication=False, observer=None):
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
    observer = observer if observer is not None else CLIProcessObserver()
    identities = observer.identities

    stdout, stderr = directory / "stdout.log", directory / "stderr.log"
    startup_error, verified, startup_identity = None, False, None
    with stdout.open("wb") as out, stderr.open("wb") as err:
        process = subprocess.Popen(
            gated, cwd=CHECKOUT, env=env, stdin=subprocess.PIPE, stdout=out, stderr=err
        )
        try:
            deadline = time.monotonic() + 10
            while startup_identity is None:
                assert process.poll() is None and time.monotonic() < deadline, (
                    "Startup identity unavailable before release"
                )
                observer.observe(process, "startup")
                if startup.exists():
                    record = json.loads(startup.read_bytes())
                    startup_identity = observer.startup_identity(record, nonce, gated)
                if startup_identity is not None:
                    break
                time.sleep(0.01)
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
            observer.observe(process, "running")
            time.sleep(0.01)
        code = process.wait()
    observer.verify_terminal()
    (directory / "receipt.json").write_bytes(
        contract.encode_json(
            {
                "command": command,
                "startup_verified": verified,
                "startup_identity": startup_identity,
                "unavailable_observations": list(observer.unavailable.values()),
                "returncode": code,
                "identities": list(identities.values()),
            }
        )
    )
    assert identities and all(
        i["independently_absent_lifetime"] is True for i in identities.values()
    ), "Original process lifetime unavailable or still live"
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


def test_actual_cli_survives_transient_prestartup_command_denial(tmp_path, monkeypatch):
    workspace(tmp_path)
    command_line = psutil.Process.cmdline
    calls = []

    def denied_once(process):
        calls.append(process.pid)
        # Deny before any complete startup identity can release the gate.
        if len(calls) == 1:
            raise psutil.AccessDenied(process.pid)
        return command_line(process)

    monkeypatch.setattr(psutil.Process, "cmdline", denied_once)
    code, stdout, stderr = invoke(tmp_path)
    assert code == 0, stderr
    assert json.loads(stdout)["expected_native_frames"] == 9
    receipt = json.loads(next(tmp_path.glob("process-*/receipt.json")).read_bytes())
    assert receipt["startup_verified"] and receipt["returncode"] == 0
    assert any(
        item["field"] == "cmdline" and item["phase"] == "startup"
        for item in receipt["unavailable_observations"]
    )
    assert all(i["independently_absent_lifetime"] for i in receipt["identities"])


def observed_process(*, pid=41, created=123.0):
    return SimpleNamespace(
        pid=pid,
        create_time=lambda: created,
        cwd=lambda: str(CHECKOUT),
        cmdline=lambda: ["generated-python", "gate.py", "startup.json", "nonce"],
        children=lambda recursive: [],
    )


@pytest.mark.parametrize(
    "field", ["process", "create_time", "cwd", "cmdline", "children"]
)
def test_denied_observation_never_establishes_process_exit_or_identity(field):
    process = observed_process()

    def factory(pid):
        if field == "process":
            raise psutil.AccessDenied(pid)
        return process

    observer = CLIProcessObserver(factory)
    read = observer.read

    def denied(actual, name, phase):
        if phase == "startup" and name == field:
            raise psutil.AccessDenied(actual.pid)
        return read(actual, name, phase)

    observer.read = denied
    observer.observe(process, "startup")
    assert any(item["field"] == field for item in observer.unavailable.values())
    assert not any(
        "independently_absent_lifetime" in i for i in observer.identities.values()
    )
    record = {
        "pid": process.pid,
        "created": process.create_time(),
        "nonce": "nonce",
        "command": process.cmdline(),
        "cwd": process.cwd(),
    }
    identity = observer.startup_identity(record, "nonce", process.cmdline())
    assert (identity is not None) is (field == "children")
    observer.verify_terminal()
    assert all(
        i["independently_absent_lifetime"] is not True
        for i in observer.identities.values()
    )


@pytest.mark.parametrize("outcome", ["gone", "reused", "same", "denied"])
@pytest.mark.parametrize("created", [None, 123.0])
def test_terminal_proof_distinguishes_absence_reuse_live_and_unavailable(
    outcome, created
):
    process = observed_process(created=456.0 if outcome == "reused" else 123.0)

    def factory(pid):
        if outcome == "gone":
            raise psutil.NoSuchProcess(pid)
        if outcome == "denied":
            raise psutil.AccessDenied(pid)
        return process

    observer = CLIProcessObserver(factory)
    observer.identities[(process.pid, created)] = {
        "pid": process.pid,
        "created": created,
    }
    observer.verify_terminal()
    identity = observer.identities[(process.pid, created)]
    expected = (
        True
        if outcome == "gone"
        else (None if outcome == "denied" or created is None else outcome == "reused")
    )
    assert identity["independently_absent_lifetime"] is expected
    assert bool(observer.unavailable) is (outcome == "denied")


@pytest.mark.parametrize("mutation", ["nonce", "pid", "created", "command", "cwd"])
def test_startup_never_releases_for_mismatched_binding(mutation):
    process = observed_process()
    observer = CLIProcessObserver(lambda pid: process)
    observer.observe(process, "startup")
    record = {
        "pid": process.pid,
        "created": process.create_time(),
        "nonce": "nonce",
        "command": process.cmdline(),
        "cwd": process.cwd(),
    }
    record[mutation] = {
        "nonce": "different",
        "pid": 99,
        "created": 999.0,
        "command": ["different"],
        "cwd": str(CHECKOUT.parent),
    }[mutation]
    if mutation in ("pid", "created"):
        assert observer.startup_identity(record, "nonce", process.cmdline()) is None
    else:
        with pytest.raises(AssertionError):
            observer.startup_identity(record, "nonce", process.cmdline())


def test_observer_preserves_lifetime_and_rejects_unexpected_errors():
    process = observed_process()
    observer = CLIProcessObserver(lambda pid: process)
    observer.observe(process, "startup")
    original = dict(observer.identities[(process.pid, process.create_time())])

    def denied():
        raise psutil.AccessDenied(process.pid)

    process.cmdline = denied
    observer.observe(process, "running")
    assert observer.identities[(process.pid, process.create_time())] == original

    def unexpected():
        raise RuntimeError("generated unexpected observation failure")

    process.cmdline = unexpected
    with pytest.raises(RuntimeError, match="unexpected observation"):
        observer.observe(process, "running")


def test_actual_cli_persistent_startup_denial_fails_closed(tmp_path, monkeypatch):
    workspace(tmp_path)

    def denied(process):
        raise psutil.AccessDenied(process.pid)

    monkeypatch.setattr(psutil.Process, "cmdline", denied)
    with pytest.raises(AssertionError, match="Startup identity unavailable"):
        invoke(tmp_path)
    receipt = json.loads(next(tmp_path.glob("process-*/receipt.json")).read_bytes())
    assert not receipt["startup_verified"] and receipt["startup_identity"] is None
    assert receipt["returncode"] != 0 and not (tmp_path / "comparison.json").exists()
    assert all(
        i["independently_absent_lifetime"] is True for i in receipt["identities"]
    )
    assert receipt["unavailable_observations"]


def test_actual_cli_denial_after_verified_startup_retains_original_evidence(
    tmp_path, monkeypatch
):
    workspace(tmp_path)
    released = tmp_path / "post-startup-observed"
    # A generated rendezvous after the unchanged nonce gate makes the race
    # deterministic. The original CLI runs only after the denied observation.
    gate = CLI_STARTUP_GATE.replace(
        "runpy.run_path(sys.argv[0], run_name='__main__')",
        "import time\n"
        f"released = Path({str(released)!r})\n"
        "until = time.monotonic() + 10\n"
        "while not released.exists():\n"
        "    if time.monotonic() >= until:\n"
        "        raise SystemExit('Generated runtime observation not reached')\n"
        "    time.sleep(0.01)\n"
        "runpy.run_path(sys.argv[0], run_name='__main__')",
    )
    monkeypatch.setitem(globals(), "CLI_STARTUP_GATE", gate)
    observer = CLIProcessObserver()
    read = observer.read

    def denied_running(process, field, phase):
        if phase == "running" and field == "cmdline":
            released.touch(exist_ok=True)
            raise psutil.AccessDenied(process.pid)
        return read(process, field, phase)

    observer.read = denied_running
    code, stdout, stderr = invoke(tmp_path, observer=observer)
    assert code == 0, stderr
    assert json.loads(stdout)["expected_native_frames"] == 9
    receipt = json.loads(next(tmp_path.glob("process-*/receipt.json")).read_bytes())
    assert receipt["startup_verified"] and receipt["startup_identity"]["command"]
    assert all(
        i["independently_absent_lifetime"] is True for i in receipt["identities"]
    )
    assert any(
        i["phase"] == "running" and i["field"] == "cmdline"
        for i in receipt["unavailable_observations"]
    )


def test_actual_cli_cannot_accept_returncode_zero_with_unavailable_terminal_proof(
    tmp_path,
):
    workspace(tmp_path)

    class DeniedTerminal(CLIProcessObserver):
        def verify_terminal(self):
            original = self.process_factory

            def denied(pid):
                raise psutil.AccessDenied(pid)

            self.process_factory = denied
            try:
                super().verify_terminal()
            finally:
                self.process_factory = original

    with pytest.raises(AssertionError, match="Original process lifetime unavailable"):
        invoke(tmp_path, observer=DeniedTerminal())
    receipt = json.loads(next(tmp_path.glob("process-*/receipt.json")).read_bytes())
    assert receipt["startup_verified"] and receipt["returncode"] == 0
    assert all(
        i["independently_absent_lifetime"] is None for i in receipt["identities"]
    )
    assert any(i["phase"] == "terminal" for i in receipt["unavailable_observations"])
    # Independent cleanup observation is distinct from the deliberately denied
    # observer's unknown receipt, and never signals or restarts a child.
    cleanup = []
    for identity in receipt["identities"]:
        try:
            absent = (
                psutil.Process(identity["pid"]).create_time() != identity["created"]
            )
        except psutil.NoSuchProcess:
            absent = True
        cleanup.append(
            {"pid": identity["pid"], "created": identity["created"], "absent": absent}
        )
    (tmp_path / "independent-cleanup.json").write_bytes(contract.encode_json(cleanup))
    assert all(item["absent"] for item in cleanup)


def test_actual_cli_preserves_unexpected_observation_error(tmp_path):
    workspace(tmp_path)
    observer = CLIProcessObserver()
    read = observer.read

    def unexpected(process, field, phase):
        if field == "cmdline" and phase == "startup":
            raise RuntimeError("generated unexpected observation failure")
        return read(process, field, phase)

    observer.read = unexpected
    with pytest.raises(RuntimeError, match="unexpected observation"):
        invoke(tmp_path, observer=observer)
    receipt = json.loads(next(tmp_path.glob("process-*/receipt.json")).read_bytes())
    assert not receipt["startup_verified"] and receipt["returncode"] != 0
    assert all(
        i["independently_absent_lifetime"] is True for i in receipt["identities"]
    )
    assert not (tmp_path / "comparison.json").exists()
