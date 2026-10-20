import copy
import json
import platform
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
from badminton import shuttle_diagnostic as diagnostic
from badminton.shuttle_supervision import (
    encoded,
    file_hash,
    load_manifest,
    normalize_csv,
    publish_json,
)


def source_clip(csv_text=None, size=6):
    clock = {
        "frame_count": size,
        "frames": [
            {"frame": n, "pts": n * 40, "time_base": "1/1000", "time_s": 2.0 + n * 0.04}
            for n in range(size)
        ],
        "source_size": [1280, 720],
        "display_size": [1280, 720],
        "rotation": 0,
        "time_base": "1/1000",
        "issues": [],
    }
    raw = (
        csv_text
        or "Frame,Visibility,X,Y\n0,1,100,100\n1,1,100,100\n2,1,100,100\n3,0,0,0\n4,0,0,0\n5,2,0,0\n"
    )
    label = normalize_csv(raw.encode(), load_manifest(), clock)
    return {
        "clip": "professional/match1/rally",
        "group": "professional/match1",
        "published_partition": "professional",
        "issues": [],
        "clock": clock,
        "labels": [{"source": "example.csv", **label}],
    }


def row(index, point=None, candidates=None):
    x, y = point if point else (None, None)
    candidates = (
        candidates
        if candidates is not None
        else ([{"id": 1, "x": x, "y": y, "confidence": 0.9}] if point else [])
    )
    return {
        "frame": index,
        "time_s": index * 0.04,
        "shuttle": {
            "visible": point is not None,
            "x": x,
            "y": y,
            "confidence": 0.9 if point else 0.1,
            "repaired": False,
            "component_candidates": candidates,
        },
    }


def test_complete_denominators_wrong_selection_and_unavailable_negatives():
    clip = source_clip()
    wrong = row(
        1,
        (300, 100),
        [
            {"id": 1, "x": 300, "y": 100, "confidence": 0.9},
            {"id": 2, "x": 100, "y": 100, "confidence": 0.8},
        ],
    )
    prediction = {"frames": [row(0, (100, 100)), wrong, row(4, (200, 200)), row(5)]}
    result = diagnostic.summarize(
        [diagnostic.score_clip(clip, prediction, diagnostic.load_protocol())]
    )
    counts = result["counts"]
    assert counts["native_frames"] == 6 and counts["published_rows"] == 6
    assert counts["native_frames_unavailable"] == 2
    assert (
        counts["eligible_published_rows"] == 5
        and counts["ineligible_published_rows"] == 1
    )
    assert counts["unavailable_published_negative"] == 1
    assert result["visibility"]["tp"] == 2 and result["visibility"]["fn"] == 1
    assert result["visibility"]["fp"] == 1 and result["visibility"]["tn"] == 0
    assert result["localization"]["tp"] == 1 and result["localization"]["fn"] == 2
    assert result["localization"]["fp"] == 2 and result["localization"]["tn"] == 0
    assert counts["component_present"] == 2 and counts["component_unavailable"] == 1
    assert counts["wrong_component_selection"] == 1
    assert result["conditional_error_px"]["support"] == 2
    assert result["conditional_error_px"]["mean"] == 100


def test_whole_incomplete_csv_quarantine_retains_native_tail():
    clip = source_clip("Frame,Visibility,X,Y\n0,1,100,100\n1,0,0,0\n")
    result = diagnostic.summarize(
        [
            diagnostic.score_clip(
                clip, {"frames": [row(n) for n in range(6)]}, diagnostic.load_protocol()
            )
        ]
    )
    assert result["counts"]["native_frames"] == 6
    assert (
        result["counts"]["published_rows"] == result["counts"]["quarantined_rows"] == 2
    )
    assert result["counts"]["unlabelled_native_frames"] == 4
    assert result["visibility"]["tn"] == 0 and result["visibility"]["recall"] is None


def test_entire_missing_prediction_is_not_an_all_negative_success():
    result = diagnostic.summarize(
        [diagnostic.score_clip(source_clip(), None, diagnostic.load_protocol())]
    )
    assert result["counts"]["native_frames_unavailable"] == 6
    assert result["visibility"]["fn"] == 3 and result["visibility"]["tn"] == 0
    assert result["counts"]["unavailable_published_negative"] == 2
    assert result["localization"]["recall"] == 0


def test_changed_published_native_reference_cannot_relabel_a_prediction():
    clip = source_clip()
    clip["labels"][0]["records"][0]["native_frame"] = {
        **clip["clock"]["frames"][0],
        "pts": 999,
    }
    with pytest.raises(ValueError, match="frame reference changed"):
        diagnostic.score_clip(
            clip, {"frames": [row(0, (100, 100))]}, diagnostic.load_protocol()
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "reordered",
        "foreign",
        "timestamp",
        "nonfinite",
        "repaired",
        "duplicate_component",
        "component_nan",
    ],
)
def test_invalid_prediction_identity_and_values_fail(mutation):
    value = {"frames": [row(0, (100, 100)), row(1, (100, 100))]}
    if mutation == "duplicate":
        value["frames"][1]["frame"] = 0
    elif mutation == "reordered":
        value["frames"].reverse()
    elif mutation == "foreign":
        value["frames"][1]["frame"] = 100
    elif mutation == "timestamp":
        value["frames"][1]["time_s"] = 0.1
    elif mutation == "nonfinite":
        value["frames"][0]["shuttle"]["x"] = float("nan")
    elif mutation == "repaired":
        value["frames"][0]["shuttle"]["repaired"] = True
    elif mutation == "duplicate_component":
        value["frames"][0]["shuttle"]["component_candidates"] *= 2
    else:
        value["frames"][0]["shuttle"]["component_candidates"][0]["confidence"] = float(
            "inf"
        )
    with pytest.raises(ValueError):
        diagnostic.validate_predictions(
            value, source_clip()["clock"], diagnostic.load_protocol()
        )


def test_native_pts_gaps_are_not_replaced_with_nominal_fps():
    clock = source_clip()["clock"]
    clock["frames"][1]["time_s"] = 2.075
    prediction = {"frames": [row(0), {**row(1), "time_s": 0.075}]}
    assert (
        len(
            diagnostic.validate_predictions(
                prediction, clock, diagnostic.load_protocol()
            )
        )
        == 2
    )
    prediction["frames"][1]["time_s"] = 0.04
    with pytest.raises(ValueError, match="timestamp"):
        diagnostic.validate_predictions(prediction, clock, diagnostic.load_protocol())


def test_group_rollup_preserves_counts_without_averaging_rates():
    clip = source_clip()
    good = diagnostic.score_clip(
        clip,
        {"frames": [row(n, (100, 100)) for n in range(6)]},
        diagnostic.load_protocol(),
    )
    missing = diagnostic.score_clip(clip, None, diagnostic.load_protocol())
    result = diagnostic.summarize([good, missing])
    assert result["counts"]["native_frames"] == 12
    assert result["counts"]["published_rows"] == 12
    assert result["visibility"]["tp"] == 3 and result["visibility"]["fn"] == 3
    assert result["conditional_error_px"]["support"] == 3


def test_protocol_bytes_are_fixed_and_changed_copy_is_rejected(tmp_path):
    assert diagnostic.load_protocol()["input_size"] == [512, 288]
    path = tmp_path / "protocol.json"
    path.write_bytes(diagnostic.PROTOCOL.read_bytes() + b" ")
    with pytest.raises(ValueError, match="protocol"):
        diagnostic.load_protocol(path)


def context_fixture(tmp_path, monkeypatch):
    root = tmp_path
    source = root / "producer.py"
    source.write_text("frozen = True\n")
    protocol = root / "protocol.json"
    protocol.write_bytes(b"{}\n")
    for name in ("source.json", "weights.pt"):
        (root / name).write_bytes(b"fixed\n")
    spec = {
        "source_evidence": {
            "path": "source.json",
            "sha256": file_hash(root / "source.json"),
        },
        "checkpoint": {"path": "weights.pt", "sha256": file_hash(root / "weights.pt")},
    }
    monkeypatch.setattr(diagnostic, "load_protocol", lambda _p: copy.deepcopy(spec))
    monkeypatch.setattr(
        diagnostic, "_consumers", lambda: {"badminton/producer.py": source}
    )
    monkeypatch.setattr(diagnostic, "_runtime", lambda: {"python": "fixture"})
    return root, root / ".cache/output", source, protocol, spec


def test_context_freezes_consumers_and_rejects_changed_code_and_copy(
    tmp_path, monkeypatch
):
    root, output, source, protocol, spec = context_fixture(tmp_path, monkeypatch)
    frozen, seal = diagnostic.context(root, output, protocol, spec)
    assert diagnostic.context(root, output, protocol, spec) == (frozen, seal)
    snapshot = output / "consumer/badminton/producer.py"
    original = snapshot.read_bytes()
    snapshot.write_bytes(b"altered")
    with pytest.raises(ValueError, match="copy changed"):
        diagnostic.context(root, output, protocol, spec)
    snapshot.write_bytes(original)
    source.write_bytes(b"changed source")
    with pytest.raises(ValueError, match="context changed"):
        diagnostic.context(root, output, protocol, spec)


def test_context_catches_hash_copy_race(tmp_path, monkeypatch):
    root, output, source, protocol, spec = context_fixture(tmp_path, monkeypatch)
    real_hash = diagnostic.file_hash

    def race(path):
        result = real_hash(path)
        if Path(path) == source:
            source.write_bytes(b"changed after hashing")
        return result

    monkeypatch.setattr(diagnostic, "file_hash", race)
    with pytest.raises(ValueError, match="while copying"):
        diagnostic.context(root, output, protocol, spec)
    assert not (output / "consumer/badminton/producer.py").exists()


def test_foreign_output_and_shared_cache_root_cannot_be_adopted(tmp_path, monkeypatch):
    root, output, _source, protocol, spec = context_fixture(tmp_path, monkeypatch)
    output.mkdir(parents=True)
    foreign = output / "keep.txt"
    foreign.write_text("preserved")
    with pytest.raises(ValueError, match="foreign"):
        diagnostic.context(root, output, protocol, spec)
    assert foreign.read_text() == "preserved"
    with pytest.raises(ValueError, match="dedicated"):
        diagnostic.context(root, root / ".cache", protocol, spec)


def test_recursive_consumer_manifest_includes_native_vendor_and_both_entrypoints():
    consumers = diagnostic._consumers()
    assert "badminton/vendor/tracknet_model.py" in consumers
    assert "badminton/shuttle.py" in consumers
    assert "scripts/diagnose_shuttle_corpus.py" in consumers
    assert "scripts/prepare_shuttle_supervision.py" in consumers


def test_native_vfr_projection_preserves_exact_frame_identity_without_app_registration(
    tmp_path, monkeypatch
):
    from badminton import shuttle_supervision
    from badminton.video import timestamps_for
    from test_segments import make_source

    monkeypatch.setattr(
        shuttle_supervision.importlib.util, "find_spec", lambda _name: None
    )
    original, data, store = make_source(tmp_path)
    clock = shuttle_supervision.decode_clock(tmp_path / original["path"], 100)
    clip = {
        "clip": "fixture/match/rally",
        "clock": clock,
        "inputs": {
            "video": [
                {"extracted": {"path": original["path"], "sha256": original["sha256"]}}
            ]
        },
    }
    before = store.videos()
    clock_data = tmp_path / ".cache/projected-clocks"
    projected = diagnostic._native_video(tmp_path, tmp_path, clip, clock_data)
    assert projected["frame_count"] == 65
    assert (projected["width"], projected["height"]) == (96, 64)
    assert timestamps_for(clock_data, projected["id"]) == pytest.approx(
        timestamps_for(data, original["id"]), abs=0.00002
    )
    assert store.videos() == before
    assert (
        clock["frames"][1]["pts"] - clock["frames"][0]["pts"]
        != clock["frames"][-1]["pts"] - clock["frames"][-2]["pts"]
    )


def test_isolated_store_cannot_supply_native_admission(tmp_path, monkeypatch):
    from badminton import config

    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", tmp_path / ".cache/isolated-store")
    monkeypatch.setattr(config, "WEIGHTS", tmp_path / "models/weights")
    with pytest.raises(ValueError, match="real shared Store"):
        diagnostic._require_store(tmp_path)


def proof_fixture(tmp_path, host=None, pid=4444, started=12.0, status="completed"):
    root = tmp_path
    shared = root / "data/processed"
    shared.mkdir(parents=True)
    with sqlite3.connect(shared / "catalog.sqlite3") as cx:
        cx.execute("CREATE TABLE jobs (id TEXT, document TEXT)")
        cx.execute(
            "INSERT INTO jobs VALUES (?,?)",
            (
                "job",
                json.dumps(
                    {"owner_pid": pid, "owner_started": started, "status": status}
                ),
            ),
        )
    output = root / ".cache/output"
    admission = output / "attempts/first/admission.json"
    publish_json(
        admission,
        {
            "job_id": "job",
            "host_id": host or platform.node(),
            "process": {
                "pid": pid,
                "creation_time": started,
                "cwd": "frozen",
                "command": ["frozen"],
            },
        },
    )
    publish_json(admission.with_name("terminal.json"), {"test_fixture": True})
    return root, output, admission


def test_foreign_host_requires_original_host_proof(tmp_path):
    root, output, _ = proof_fixture(tmp_path, host="another-host")
    with pytest.raises(ValueError, match="original-host"):
        diagnostic.prior_proofs(root, output)


def test_completed_store_bit_does_not_prove_live_process_exit(tmp_path):
    process = psutil.Process()
    root, output, _ = proof_fixture(
        tmp_path, pid=process.pid, started=process.create_time()
    )
    with pytest.raises(ValueError, match="still alive"):
        diagnostic.prior_proofs(root, output)


@pytest.mark.parametrize("status", ["completed", "running"])
def test_pid_reuse_and_matching_terminal_store_required(tmp_path, monkeypatch, status):
    root, output, _ = proof_fixture(tmp_path, status=status)

    class NewLifetime:
        def create_time(self):
            return 13.0

    monkeypatch.setattr(psutil, "Process", lambda _pid: NewLifetime())
    if status == "completed":
        assert diagnostic.prior_proofs(root, output)[0]["original_lifetime_exited"]
    else:
        with pytest.raises(ValueError, match="not terminal"):
            diagnostic.prior_proofs(root, output)


def test_score_requires_exact_matching_native_terminal_and_external_hash(tmp_path):
    output = tmp_path
    admission = output / "attempts/first/admission.json"
    publish_json(admission, {"job_id": "job"})
    index = {"completed_clips": [{"path": "clip.json", "sha256": "a" * 64}]}
    entry = {"path": "attempts/first/output-index.json", "sha256": "b" * 64}
    terminal = admission.with_name("terminal.json")
    receipt = {
        "context_sha256": "context",
        "status": "completed",
        "output_index": entry,
        "completed_clips": index["completed_clips"],
        "job_id": "job",
    }
    publish_json(terminal, receipt)
    proofs = [
        {"admission": diagnostic._seal(output, admission), "store_status": "completed"}
    ]
    assert diagnostic.terminal_binding(
        output, terminal, file_hash(terminal), entry, index, "context", proofs
    )
    changed = {**entry, "sha256": "c" * 64}
    with pytest.raises(ValueError, match="matching completed"):
        diagnostic.terminal_binding(
            output, terminal, file_hash(terminal), changed, index, "context", proofs
        )
    with pytest.raises(ValueError, match="output changed"):
        diagnostic.terminal_binding(
            output, terminal, "0" * 64, entry, index, "context", proofs
        )
    proofs[0]["store_status"] = "failed"
    with pytest.raises(ValueError, match="matching completed"):
        diagnostic.terminal_binding(
            output, terminal, file_hash(terminal), entry, index, "context", proofs
        )


def test_resume_rejects_altered_completed_output(tmp_path):
    output = tmp_path
    clip = output / "clip.json"
    publish_json(clip, {"clip": "clip", "context_sha256": "context"})
    terminal = output / "attempts/old/terminal.json"
    publish_json(
        terminal,
        {
            "context_sha256": "context",
            "completed_clips": [diagnostic._seal(output, clip)],
        },
    )
    terminal_sha = file_hash(terminal)
    clip.write_bytes(encoded({"clip": "different", "context_sha256": "context"}))
    with pytest.raises(ValueError, match="output changed"):
        diagnostic._resume(output, terminal, terminal_sha, "context")


def test_resume_cannot_ignore_existing_attempt_or_changed_history(tmp_path):
    output = tmp_path
    terminal = output / "attempts/first/terminal.json"
    publish_json(
        terminal,
        {
            "context_sha256": "context",
            "completed_clips": [],
            "prior_terminal_seals": [],
            "elapsed_s": 2.5,
        },
    )
    with pytest.raises(ValueError, match="externally sealed"):
        diagnostic.resume_plan(output, None, None, "context")
    reusable, seals, elapsed = diagnostic.resume_plan(
        output, terminal, file_hash(terminal), "context"
    )
    assert reusable == {} and len(seals) == 1 and elapsed == 2.5
    extra = output / "attempts/unbound/terminal.json"
    publish_json(extra, {"elapsed_s": 1})
    with pytest.raises(ValueError, match="history"):
        diagnostic.resume_plan(output, terminal, file_hash(terminal), "context")


def test_exited_attempt_without_terminal_cannot_be_ignored(tmp_path, monkeypatch):
    root, output, admission = proof_fixture(tmp_path)
    admission.with_name("terminal.json").unlink()

    class NewLifetime:
        def create_time(self):
            return 13.0

    monkeypatch.setattr(psutil, "Process", lambda _pid: NewLifetime())
    with pytest.raises(ValueError, match="no terminal receipt"):
        diagnostic.prior_proofs(root, output)


def fake_native_fixture(tmp_path, monkeypatch, change_consumer=False):
    """Generated CPU stub only: exercise real Store admission without a GPU task."""
    from badminton import shuttle
    from badminton.storage import Store

    root, output, source, protocol, spec = context_fixture(tmp_path, monkeypatch)
    spec.update(
        {
            "max_native_seconds": 100,
            "input_size": [512, 288],
            "heatmap_threshold": 0.5,
            "clock_tolerance_s": 0.00002,
            "expected": {"clips": 1},
            "source_report": spec["source_evidence"],
            "limitations": ["generated CPU stub, no model inference"],
        }
    )
    shared = root / "data/processed"
    store = Store(shared)
    monkeypatch.setattr(diagnostic, "_require_store", lambda _root: shared)
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)),
    )
    monkeypatch.setitem(sys.modules, "torchvision", SimpleNamespace())
    ref = {"clip": "professional/match1/rally", "path": "clip.json", "sha256": "a" * 64}
    monkeypatch.setattr(
        diagnostic, "source_catalog", lambda _root, _spec: (root, [ref])
    )
    monkeypatch.setattr(diagnostic, "verify_clip", lambda *_args: source_clip())
    monkeypatch.setattr(
        diagnostic,
        "_native_video",
        lambda *_args: {"id": "fixture", "sha256": "source"},
    )

    def fake_track(_video, _root, _data, start, end, progress, path, **_kwargs):
        progress(0.5)
        publish_json(
            path,
            {
                "checkpoint_sha256": spec["checkpoint"]["sha256"],
                "input_size": [512, 288],
                "device": "cuda:generated-stub",
                "precision": "float16",
                "repaired_frames": 0,
                "video_sha256": "source",
                "localization": {"heatmap_threshold": 0.5},
                "start_frame": start,
                "end_frame": end,
                "temporal_context_crosses_detected_cuts": False,
                "frames": [row(n) for n in range(6)],
            },
        )
        if change_consumer:
            source.write_text("changed during generated work\n")

    monkeypatch.setattr(shuttle, "track_shuttle", fake_track)
    return root, output, protocol, store


def test_context_failure_marks_real_store_failed_before_completion(
    tmp_path, monkeypatch
):
    root, output, protocol, store = fake_native_fixture(
        tmp_path, monkeypatch, change_consumer=True
    )
    with pytest.raises(ValueError, match="context changed"):
        diagnostic.run(root, output, protocol)
    with sqlite3.connect(store.data / "catalog.sqlite3") as cx:
        jobs = [json.loads(row[0]) for row in cx.execute("SELECT document FROM jobs")]
    assert len(jobs) == 1 and jobs[0]["status"] == "failed"
    terminal = diagnostic.read_json(next((output / "attempts").glob("*/terminal.json")))
    assert terminal["status"] == "failed" and terminal["completed_clips"] == []
    assert list((output / "attempts").glob("*/clips/*/raw-prediction.json"))


def test_native_stub_seals_outputs_but_live_lifetime_still_blocks_scoring(
    tmp_path, monkeypatch
):
    root, output, protocol, store = fake_native_fixture(tmp_path, monkeypatch)
    result = diagnostic.run(root, output, protocol)
    assert result["completed_clips"] == 1 and not result["scored"]
    index = diagnostic.read_json(diagnostic._verified(output, result["output_index"]))
    assert len(index["completed_clips"]) == 1
    with sqlite3.connect(store.data / "catalog.sqlite3") as cx:
        job = json.loads(cx.execute("SELECT document FROM jobs").fetchone()[0])
    assert job["status"] == "completed"
    with pytest.raises(ValueError, match="still alive"):
        diagnostic.prior_proofs(root, output)


def test_real_store_admission_refuses_competing_native_stub(tmp_path, monkeypatch):
    from badminton.storage import ConflictError

    root, output, protocol, store = fake_native_fixture(tmp_path, monkeypatch)
    store.claim_job(
        {
            "id": "occupied",
            "kind": "generated-no-gpu",
            "video_id": None,
            "status": "running",
        }
    )
    with pytest.raises(ConflictError, match="Another processing job is running"):
        diagnostic.run(root, output, protocol)
    assert not list((output / "attempts").glob("*/clips/*/raw-prediction.json"))
