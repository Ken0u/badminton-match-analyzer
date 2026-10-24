"""Generated records only; no external source/image/assessment access."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
from badminton import rally_reference_diagnostics as d
from badminton import rally_reference_recovery as recovery
from badminton import rally_source_reference as acceptance
from test_rally_source_reference import packet, streams

ROOT = Path(__file__).resolve().parents[1]
BOUNDS = {"start_frame": 0, "end_frame": 7}


def script():
    spec = importlib.util.spec_from_file_location(
        "generated_diagnostic", ROOT / "scripts/diagnose_rally_references.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def census(data=None):
    return d.census_lane((data or streams())["independent_a"], native_frames=range(8))


def test_full_denominator_and_private_provenance_preserve_unknown_labels():
    source = streams()
    before = copy.deepcopy(source)
    result, ledger = d.diagnose_source(
        source,
        native_frames=range(8),
        bounds=BOUNDS,
        acceptance=acceptance.targeted_reference_status,
    )
    assert source == before
    a = result["streams"]["independent_a"]
    assert a["native_frame_denominator"] == a["unique_inspected_frames"] == 8
    assert a["inspected_memberships"] == 8 and a["uninspected_native_frames"] == 0
    assert a["unknown_contact_side_occurrences"] == 1
    assert a["shot_family_occurrences"]["unknown"] == 1
    assert result["scientific_status"] == acceptance.targeted_reference_status(
        source, native_frames=range(8), bounds=BOUNDS
    )
    assert ledger["independent_a"]["frames"][3]["state"]["frame"] == 3
    assert (
        ledger["independent_a"]["events"][1]["event"]
        == source["independent_a"][0][0]["events"][1]
    )
    public = json.dumps(result)
    assert "generated actor" not in public and "continuity_notes" not in public
    assert "interval" not in public and "session_id" not in public


def test_repeated_memberships_and_conflicting_variants_are_both_retained():
    source = streams()
    repeated = copy.deepcopy(source["independent_a"][0])
    repeated[0]["frame_states"][3]["contact_state"] = "unknown"
    repeated[0]["frame_states"][3]["scene"] = "unknown"
    repeated[0]["frame_states"][3]["camera_view"] = "unknown"
    source["independent_a"].append(repeated)
    a, ledger = census(source)
    assert a["inspected_memberships"] == 16
    assert a["unique_inspected_frames"] == a["repeated_frame_observation_excess"] == 8
    assert a["conflicting_frame_variants"] == 1
    assert a["contact_state_unique_frame_counts"]["unknown"] == 1
    assert a["contact_state_unique_frame_counts"]["observed"] == 2
    assert sum(a["contact_state_unique_frame_counts"].values()) == 9
    assert a["unknown_camera_frames"] == a["scene_unique_frame_counts"]["unknown"] == 1
    assert len(ledger["frames"]) == 16
    assert (
        a["signature_repeat_excess"] == a["cross_document_signature_repeat_excess"] == 3
    )
    assert a["distinct_key_overlapping_contact_pairs"] == 0


def test_same_key_conflict_and_distinct_overlapping_contacts_are_separate():
    source = streams()
    doc = source["independent_a"][0][0]
    event = doc["events"][1]
    duplicate = copy.deepcopy(event)
    conflict = {**event, "family": "drive"}
    overlap = {**event, "interval": [2, 3]}
    doc["events"].extend([duplicate, conflict, overlap])
    a, ledger = census(source)
    assert a["event_occurrences"] == 6
    assert a["distinct_acceptance_signatures"] == 5
    assert (
        a["signature_repeat_excess"]
        == a["within_document_signature_repeat_excess"]
        == 1
    )
    assert a["conflicting_event_keys"] == 1
    assert a["distinct_contact_keys"] == 3
    assert a["distinct_key_overlapping_contact_pairs"] == 1
    assert len(ledger["events"]) == 6


def test_all_pairs_overlap_inclusive_endpoints_without_merging_intervals():
    source = streams()
    doc = source["independent_a"][0][0]
    event = doc["events"][1]
    doc["events"] = [
        {**event, "interval": pair} for pair in ([1, 6], [2, 3], [3, 4], [6, 6])
    ]
    a, ledger = census(source)
    assert a["distinct_key_overlapping_contact_pairs"] == 4
    assert [r["event"]["interval"] for r in ledger["events"]] == [
        [1, 6],
        [2, 3],
        [3, 4],
        [6, 6],
    ]


def test_local_actor_support_does_not_use_later_definition():
    source = streams()
    first = source["independent_a"][0][0]
    first["actors"][0]["identity_supported"] = False
    repeated = copy.deepcopy(source["independent_a"][0])
    repeated[0]["actors"][0]["identity_supported"] = True
    repeated[0]["actors"][0]["description"] = "different generated definition"
    source["independent_a"].append(repeated)
    a, ledger = census(source)
    assert a["conflicting_actor_definition_groups"] == 1
    assert a["unsupported_identity_contact_occurrences"] == 2
    assert a["unsupported_identity_contact_frames"] == 2
    assert len(ledger["actors"]) == 2


def test_gap_and_censor_unions_do_not_drop_native_denominator():
    source = streams()
    doc = source["independent_a"][0][0]
    doc["unresolved_gaps"] = [
        {"interval": [1, 3], "reason": "generated"},
        {"interval": [3, 4], "reason": "generated"},
    ]
    doc["start_censored"] = True
    doc["scene"] = "unknown"
    a, _ = census(source)
    assert a["native_frame_denominator"] == 8
    assert a["unresolved_gap_frames"] == 4
    assert (
        a["censored_document_frames"] == a["nonlive_or_incomplete_document_frames"] == 8
    )


@pytest.mark.parametrize(
    "bad", [[-1, 2], [0, 8], [4, 3], [True, 3], [1, 3.0], [1], [0, 2]]
)
def test_interval_membership_and_exact_integer_guards(bad):
    with pytest.raises(ValueError):
        d.interval_frames(bad, {0, 1, 3, 4, 5, 6, 7})


@pytest.mark.parametrize("frames", [[], [0, 0], [1, 0], [False, 1], [0, 1.0], [-1, 0]])
def test_bad_native_denominators_fail(frames):
    with pytest.raises(ValueError):
        d.native_set(frames)


def test_partial_adjudication_has_explicit_uninspected_membership():
    source = streams()
    doc = source["adjudication"][0][0]
    doc["inspected_frames"] = doc["inspected_frames"][:2]
    doc["frame_states"] = doc["frame_states"][:2]
    doc["events"] = doc["events"][:1]
    a, _ = d.census_lane(source["adjudication"], native_frames=range(8))
    assert a["native_frame_denominator"] == 8
    assert a["unique_inspected_frames"] == 2 and a["uninspected_native_frames"] == 6


@pytest.mark.parametrize(
    "change", ["source", "image", "lane", "membership", "state", "missing_lane"]
)
def test_mismatched_native_source_and_stream_are_rejected(change):
    source = streams()
    doc = source["independent_b"][0][0]
    if change == "source":
        doc["source_id"] = "another"
    elif change == "image":
        doc["inspected_frames"][0]["sha256"] = "f" * 64
    elif change == "lane":
        doc["stream"] = "independent_a"
    elif change == "membership":
        doc["inspected_frames"][0]["frame"] = 100
    elif change == "state":
        doc["frame_states"].pop()
    else:
        del source["independent_b"]
    with pytest.raises(ValueError):
        d.diagnose_source(
            source,
            native_frames=range(8),
            bounds=BOUNDS,
            acceptance=acceptance.targeted_reference_status,
        )


def test_verdict_parity_is_exact_and_never_a_new_gate():
    source = streams()
    row, _ = d.diagnose_source(
        source,
        native_frames=range(8),
        bounds=BOUNDS,
        acceptance=acceptance.targeted_reference_status,
    )
    original = {
        "complete_references": 1,
        "all_requested_labels_supported_slots": 0,
        "results": [
            {
                "source_id": row["source_id"],
                "native_frames": 8,
                **row["scientific_status"],
            }
        ],
    }
    assert d.require_unchanged([row], original)
    changed = copy.deepcopy(original)
    changed["results"][0]["reasons"].append("generated mutation")
    with pytest.raises(ValueError, match="verdict"):
        d.require_unchanged([row], changed)
    with pytest.raises(ValueError, match="slots"):
        d.require_unchanged([], original)


def test_sealed_hash_failure_precedes_archive_or_scientific_access(tmp_path):
    cli = script()
    raw = tmp_path / "generated-seal"
    raw.write_bytes(b"generated")
    archive = SimpleNamespace(
        archive=lambda *a: pytest.fail("archive must remain unopened")
    )
    with pytest.raises(ValueError, match="Sealed"):
        cli.metadata_gate(
            tmp_path, archive, None, None, {"sealed_inputs": {raw.name: "0" * 64}}
        )


def test_incomplete_global_provenance_cannot_reach_scientific_reader(
    tmp_path, monkeypatch
):
    cli = script()
    output = tmp_path / ".cache/rally228-source-only-v1"
    output.mkdir(parents=True)
    cli.exclusive(
        output / "combined-target-index.json", {"complete": True, "segments": []}
    )
    cli.exclusive(output / "owner.json", {})
    context = {"prefix": [], "suffix": [], "projected_image_bytes": 0}
    archived = SimpleNamespace(
        current=lambda *a, **k: (context, 1),
        archive=lambda *a: ({}, [], [], SimpleNamespace(threads=set())),
        PRIOR_BYTES=0,
        rules=recovery,
    )
    old = SimpleNamespace(
        SINGLES="generated",
        source_chunks=lambda p: [],
        metadata=SimpleNamespace(
            absent=lambda r: None,
            complete_index=lambda c, e: {"complete": True, "segments": []},
            payload_total=lambda *a: 0,
        ),
    )
    with pytest.raises(ValueError, match="global"):
        cli.metadata_gate(tmp_path, archived, old, None, {"sealed_inputs": {}})
    assert not (output / "aggregate.json").exists()


def test_exclusive_outputs_are_never_overwritten(tmp_path):
    cli = script()
    path = tmp_path / "generated.json"
    cli.exclusive(path, {"original": True})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        cli.exclusive(path, {"original": False})
    assert path.read_bytes() == before


def test_wrong_frozen_origin_is_rejected_before_scientific_read(tmp_path, monkeypatch):
    cli = script()
    monkeypatch.setattr(cli, "git", lambda *a: "")
    monkeypatch.setattr(cli, "digest", lambda *a: "f" * 64)
    fake = SimpleNamespace(
        frozen=lambda r: SimpleNamespace(
            frozen_library=lambda *a, **k: SimpleNamespace(
                __file__=str(tmp_path / "wrong.py")
            )
        )
    )
    monkeypatch.setattr(cli, "module", lambda *a: fake)
    protocol = {
        "frozen_checkouts": [
            {"path": "a", "commit": "", "files": {}},
            {
                "path": "b",
                "commit": "",
                "files": {"backend/badminton/rally_source_reference.py": "f" * 64},
            },
        ]
    }
    # Existing imports are also an origin ambiguity: fail before accepting them.
    with pytest.raises(ValueError, match="clean process"):
        cli.frozen(tmp_path, protocol)


def test_wrong_actual_origin_after_clean_import_is_rejected(tmp_path, monkeypatch):
    cli = script()
    monkeypatch.setattr(cli, "git", lambda *a: "")
    monkeypatch.setattr(cli, "digest", lambda *a: "f" * 64)
    for name in list(sys.modules):
        if name == "badminton" or name.startswith("badminton."):
            monkeypatch.delitem(sys.modules, name)
    fake = SimpleNamespace(
        frozen=lambda r: SimpleNamespace(
            frozen_library=lambda *a, **k: SimpleNamespace(
                __file__=str(tmp_path / "wrong.py")
            )
        )
    )
    monkeypatch.setattr(cli, "module", lambda *a: fake)
    protocol = {
        "frozen_checkouts": [
            {"path": "a", "commit": "", "files": {}},
            {
                "path": "b",
                "commit": "",
                "files": {"backend/badminton/rally_source_reference.py": "f" * 64},
            },
        ]
    }
    with pytest.raises(ValueError, match="origin/hash"):
        cli.frozen(tmp_path, protocol)


def test_windows_linked_output_root_is_rejected_before_traversal(tmp_path, monkeypatch):
    cli = script()
    parent = tmp_path / ".cache/rally238-generated"
    parent.mkdir(parents=True)
    (tmp_path / ".cache/worktrees").mkdir()
    lstat = Path.lstat

    def fake_lstat(path):
        if path == parent:
            return SimpleNamespace(st_file_attributes=1024, st_mode=0o40755)
        return lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(ValueError, match="roots"):
        cli.new_bytes(tmp_path)


def test_nested_windows_links_are_counted_without_following_targets(
    tmp_path, monkeypatch
):
    cli = script()
    parent = tmp_path / ".cache/rally238-generated"
    nested = parent / "current"
    nested.mkdir(parents=True)
    (parent / "kept.bin").write_bytes(b"abc")
    (nested / "target-must-not-be-counted.bin").write_bytes(b"not a retained copy")
    (tmp_path / ".cache/worktrees").mkdir()
    lstat = Path.lstat

    def fake_lstat(path):
        if path == nested:
            return SimpleNamespace(st_file_attributes=1024, st_mode=0o40755, st_size=7)
        return lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    assert cli.new_bytes(tmp_path) == 10


@pytest.mark.parametrize("tamper", [False, True])
def test_separate_reader_validates_generated_originals_and_resolution(tmp_path, tamper):
    cli = script()
    base, native = tmp_path / "base", tmp_path / "native"
    native.mkdir()
    p = packet()
    cli.exclusive(native / "generated.packet.json", p)
    data = streams()
    chunks = acceptance.plan_chunks(p, dense=True)
    entries = {}
    for lane, documents in data.items():
        folder = base / "dense-assessment-v1" / lane
        folder.mkdir(parents=True)
        doc, receipt = documents[0]
        cli.exclusive(folder / "original.json", doc)
        cli.exclusive(folder / "receipt.json", receipt)
        entry = {
            "source_id": "generated",
            "chunk": 0,
            "frames": chunks[0]["frames"],
            "original_path": str(folder / "original.json"),
            "receipt_path": str(folder / "receipt.json"),
            "original_sha256": cli.digest(folder / "original.json"),
            "receipt_sha256": cli.digest(folder / "receipt.json"),
        }
        entries[lane] = entry
        cli.exclusive(folder / "index.json", {"segments": [entry]})
    old = SimpleNamespace(
        paths=lambda r: {"base": base, "native": native, "acceptance": tmp_path}
    )
    library = SimpleNamespace(
        STREAMS=acceptance.STREAMS,
        load_protocol=lambda p: None,
        plan_chunks=acceptance.plan_chunks,
        validate_assessment=acceptance.validate_assessment,
    )
    source = {
        "source_id": "generated",
        "chunks": [{**chunks[0], "region_index": 0}],
        "bounds": BOUNDS,
    }
    if tamper:
        (Path(entries["independent_a"]["original_path"])).write_text(
            "{}\n", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="input changed"):
            cli.load_streams(tmp_path, old, library, source, [entries["adjudication"]])
    else:
        actual_packet, actual, provenance = cli.load_streams(
            tmp_path, old, library, source, [entries["adjudication"]]
        )
        assert actual_packet == p and actual == data
        assert (
            provenance["independent_a"][0]["original_sha256"]
            == entries["independent_a"]["original_sha256"]
        )


@pytest.mark.parametrize("fail", [False, True])
def test_generated_actual_store_admission_and_exited_process(tmp_path, fail):
    root = tmp_path / "original-host"
    root.mkdir()
    output = root / ".cache/rally238-generated"
    output.mkdir(parents=True)
    (output / "context.json").write_text("{}\n", encoding="utf-8")
    runner = tmp_path / "generated_runner.py"
    runner.write_text(
        "import importlib.util,json,time\nfrom pathlib import Path\n"
        "from badminton.storage import Store\nfrom badminton import config\n"
        "Store(config.DATA)\n"
        f"s=importlib.util.spec_from_file_location('generated', {str(ROOT / 'scripts/diagnose_rally_references.py')!r})\n"
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
        f"out=Path({str(output)!r})\n"
        "def calculate(progress):\n"
        + (
            "    raise ValueError('generated failure')\n"
            if fail
            else "    m.exclusive(out/'ledger.json', {'generated': True})\n    m.exclusive(out/'aggregate.json', {'generated': True})\n    return {'generated': True}\n"
        )
        + "m.admitted_run(config.ROOT,out,{'deadline':time.time()+60},calculate)\n",
        encoding="utf-8",
        newline="\n",
    )
    env = os.environ.copy()
    for name in script().CREDENTIALS:
        env.pop(name, None)
    env.update(
        BADMINTON_ROOT=str(root),
        BADMINTON_DATA_DIR=str(root / "data/processed"),
        BADMINTON_WEIGHTS_DIR=str(root / "models/weights"),
        PYTHONPATH=str(ROOT / "backend"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    child = subprocess.Popen(
        [sys.executable, str(runner)],
        env=env,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = child.communicate(timeout=40)
    assert child.returncode == (1 if fail else 0), (stdout, stderr)
    admission = json.loads((output / "admission.json").read_bytes())
    try:
        assert (
            psutil.Process(admission["process"]["pid"]).create_time()
            != admission["process"]["creation_time"]
        )
    except psutil.NoSuchProcess:
        pass
    import sqlite3

    with sqlite3.connect(root / "data/processed/catalog.sqlite3") as db:
        job = json.loads(
            db.execute(
                "select document from jobs where id=?", (admission["job_id"],)
            ).fetchone()[0]
        )
    assert job["status"] == ("failed" if fail else "completed")
    assert (output / "failure.json").exists() is fail
    assert (output / "terminal.json").exists() is not fail
    if not fail:
        terminal = json.loads((output / "terminal.json").read_bytes())
        assert terminal["summary"] == job["summary"]
        assert terminal["artifacts"]["ledger.json"] == script().digest(
            output / "ledger.json"
        )
