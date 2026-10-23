"""Generated data only: source gates, paired outcomes and actual worker exit."""

import io
import os
import subprocess
import sys

import numpy as np
import psutil
import pytest
from badminton import shuttle_threshold_comparison as module
from badminton.shuttle import locate_shuttle
from badminton.storage import ConflictError, Store


def fixture_data(tmp_path, mutation=None):
    root = tmp_path / "original"
    capture = root / ".cache/capture"
    capture.mkdir(parents=True)
    Store(root / "data/processed")
    (root / "consumer.py").write_text("# generated frozen consumer\n", encoding="utf-8")
    spec = module.heatmaps.read(module.PROTOCOL)
    spec["heatmap_shape"] = [32, 32]
    spec["expected"] = {
        "cases": 4,
        "views": 2,
        "native_rows": 4,
        "states": dict.fromkeys(module.STATES, 1),
    }

    def publish(name, value):
        path = capture / name
        module.heatmaps.publish(path, value)
        return module.audit.seal(capture, path)

    cases, assessments, entries, views = [], [], [], []
    for source_index, source in enumerate(("singles", "doubles")):
        rows, targets = [], {}
        first, last = 0, 2
        for frame in range(2):
            ordinal = source_index * 2 + frame
            key = "case" + str(ordinal)
            state = module.STATES[ordinal]
            case = {
                "id": key,
                "video_id": source,
                "frame": frame,
                "width": 512,
                "height": 288,
                "rotation": 0,
                "context": [],
            }
            label = {
                "state": state,
                "x": 10.5 * 512 / 32 if state == "visible" else None,
                "y": 10.5 * 288 / 32 if state == "visible" else None,
                "uncertainty_px": 1.0 if state == "visible" else None,
                "difficulty": ["ordinary"],
            }
            cases.append(case)
            assessments.append(
                {"id": key, "label": label, "disagreement": {"state": False}}
            )
            heat = np.zeros((32, 32), dtype=np.float32)
            heat[10, 10] = (0.3, 0.3, 0.6, 0.2)[ordinal]
            point = locate_shuttle(heat, 512, 288)
            if mutation == "components" and ordinal == 2:
                point["components"] = 0
            rows.append(
                {
                    "frame": frame,
                    "time_s": frame / 25,
                    "camera_segment_start_frame": 0,
                    "shuttle": point,
                }
            )
            if ordinal == 0:
                if mutation == "nonfinite":
                    heat[0, 0] = np.nan
                elif mutation == "shape":
                    heat = np.zeros((3, 3), dtype=np.float32)
            stream = io.BytesIO()
            np.save(stream, heat, allow_pickle=False)
            raw = stream.getvalue()
            if mutation == "trailing" and ordinal == 0:
                raw += b"trailing"
            path = capture / (key + ".npy")
            path.write_bytes(raw)
            targets[key] = {
                "case": case,
                "time_s": frame / 25,
                "view_id": "view" + str(source_index),
                "array": module.audit.seal(capture, path),
            }
        if source_index == 0:
            if mutation == "frame":
                rows[1]["frame"] = 3
            elif mutation == "pts":
                rows[1]["time_s"] = 0.0
            elif mutation == "camera":
                rows[1]["camera_segment_start_frame"] = 1
            elif mutation == "view":
                targets["case0"]["view_id"] = "another_view"
            elif mutation == "extra":
                targets["extra"] = targets["case0"]
        view = {
            "id": "view" + str(source_index),
            "video_id": source,
            "start_frame": first,
            "end_frame": last,
            "case_ids": [c["id"] for c in cases if c["video_id"] == source],
        }
        views.append(view)
        run_entry = publish(
            "run" + str(source_index) + ".json",
            {"start_frame": first, "end_frame": last, "frames": rows},
        )
        entries.append(
            publish(
                "view" + str(source_index) + ".json",
                {
                    "view": view,
                    "clip": view["id"],
                    "context_sha256": "later",
                    "run": run_entry,
                    "heatmaps": targets,
                },
            )
        )
    packet_entry = publish("packet.json", {"cases": cases})
    if mutation == "duplicate_label":
        assessments.append(assessments[0])
    labels_entry = publish(
        "labels.json", {"cases": assessments, "packet_sha256": packet_entry["sha256"]}
    )
    baseline_entry = publish(
        "baseline.json",
        {
            "evidence": {
                "catalogs": {
                    source: {"snapshot": {"video": {"frame_count": 2}}}
                    for source in ("singles", "doubles")
                }
            }
        },
    )
    old_protocol = publish(
        "protocol.json", {"expected": {"cases": 4, "views": 2, "native_view_rows": 4}}
    )
    experiment = {
        "protocol_sha256": old_protocol["sha256"],
        "cases": cases,
        "views": views,
        "packet": module.audit.seal(root, capture / "packet.json"),
        "labels": module.audit.seal(root, capture / "labels.json"),
        "baseline": module.audit.seal(root, capture / "baseline.json"),
    }
    experiment_entry = publish("experiment.json", experiment)
    for entry in entries:
        path = capture / entry["path"]
        record = module.heatmaps.read(path)
        record["context_sha256"] = experiment_entry["sha256"]
        path.write_bytes(module.audit.encoded(record))
        entry.update(module.audit.seal(capture, path))
    index = {
        "context_sha256": experiment_entry["sha256"],
        "protocol_sha256": old_protocol["sha256"],
        "expected": {"cases": 4, "views": 2, "native_view_rows": 4},
        "completed_clips": entries,
    }
    index_entry = publish("index.json", index)
    terminal_entry = publish(
        "terminal.json",
        {
            "status": "completed",
            "context_sha256": experiment_entry["sha256"],
            "output_index": index_entry,
            "completed_clips": entries,
        },
    )
    report_path = capture / "control-report.json"
    publish(
        report_path.name,
        {
            "control_gate": {
                "compatible": True,
                "differences": [],
                "native_rows": 4,
                "views": 2,
            },
            "experiment_sha256": experiment_entry["sha256"],
            "protocol_sha256": old_protocol["sha256"],
            "output_index": index_entry,
            "native_terminal": terminal_entry,
            "cases": [{"id": c["id"]} for c in cases],
        },
    )
    spec.update(
        capture_experiment_sha256=experiment_entry["sha256"],
        capture_report_sha256=module.audit.file_hash(report_path),
        capture_index_sha256=index_entry["sha256"],
        capture_terminal_sha256=terminal_entry["sha256"],
        labels_sha256=labels_entry["sha256"],
        baseline_sha256=baseline_entry["sha256"],
    )
    (root / "generated-protocol.json").write_bytes(module.audit.encoded(spec))
    return root, capture, report_path, spec


def install(monkeypatch, root, spec):
    monkeypatch.setattr(module, "protocol", lambda: spec)
    monkeypatch.setattr(
        module, "PROTOCOL_SHA", module.audit.digest(module.audit.encoded(spec))
    )
    monkeypatch.setattr(
        module,
        "consumers",
        lambda original: {
            "consumer": module.audit.seal(original, original / "consumer.py")
        },
    )
    monkeypatch.setattr(
        module, "_require_store", lambda original: original / "data/processed"
    )


def frozen(tmp_path, monkeypatch, mutation=None):
    root, capture, report, spec = fixture_data(tmp_path, mutation)
    install(monkeypatch, root, spec)
    output = root / ".cache/comparison"
    expected = module.freeze(root, capture, report, output)["experiment_sha256"]
    return root, capture, output, expected, spec


def test_frozen_protocol_and_no_application_default_change():
    spec = module.protocol()
    assert spec["candidate_threshold"] == 0.25
    assert spec["control_threshold"] == 0.5
    assert not any(spec["eligibility"].values())
    assert module.audit.file_hash(module.PROTOCOL) == module.PROTOCOL_SHA


def test_complete_paired_outputs_and_unknown_component_support(tmp_path, monkeypatch):
    root, _, output, expected, spec = frozen(tmp_path, monkeypatch)
    context = module.load(root, output, expected)
    raw = module.compute(root, context, spec, lambda _value: None)
    assert raw["compatible"]
    values = {}
    for item, record in zip(context["cases"], raw["cases"], strict=True):
        values[item["label"]["state"]] = module.outcome(
            record["candidate"], item["case"], item["label"], 0.005
        )
    assert values["visible"]["outcome"] == "localized"
    assert values["not_visible"]["outcome"] == "false_observation"
    assert values["unknown"]["outcome"] == "observed_unscored"
    assert values["unknown"]["any_component_agrees"] is None
    assert values["visible_unlocalizable"]["outcome"] == "absent_unscored"
    assert sum(record["control"]["visible"] for record in raw["cases"]) == 1
    assert sum(record["candidate"]["visible"] for record in raw["cases"]) == 3


@pytest.mark.parametrize(
    "mutation", ["frame", "pts", "camera", "view", "extra", "duplicate_label"]
)
def test_source_identity_and_membership_fail_before_freeze(
    tmp_path, monkeypatch, mutation
):
    with pytest.raises(ValueError):
        frozen(tmp_path, monkeypatch, mutation)


@pytest.mark.parametrize("mutation", ["components", "nonfinite", "shape", "trailing"])
def test_all_controls_gate_every_candidate_and_preserve_unavailable(
    tmp_path, monkeypatch, mutation
):
    root, _, output, expected, spec = frozen(tmp_path, monkeypatch, mutation)
    original = module.locate_shuttle
    calls = []

    def observe(heat, width, height, threshold):
        calls.append(threshold)
        return original(heat, width, height, threshold)

    monkeypatch.setattr(module, "locate_shuttle", observe)
    raw = module.compute(
        root, module.load(root, output, expected), spec, lambda _value: None
    )
    assert not raw["compatible"] and len(raw["cases"]) == 4
    assert 0.25 not in calls
    assert all(
        record["control"] is record["candidate"] is None for record in raw["cases"]
    )


@pytest.mark.parametrize("changed", ["input", "consumer", "runtime", "protocol"])
def test_frozen_context_tamper_is_refused_or_unscored(tmp_path, monkeypatch, changed):
    root, capture, output, expected, spec = frozen(tmp_path, monkeypatch)
    if changed == "input":
        (capture / "case0.npy").write_bytes(b"truncated")
        raw = module.compute(
            root, module.load(root, output, expected), spec, lambda _value: None
        )
        assert not raw["compatible"]
        assert len(raw["cases"]) == 4
    else:
        if changed == "consumer":
            (root / "consumer.py").write_text("# changed\n", encoding="utf-8")
        elif changed == "runtime":
            monkeypatch.setattr(module, "runtime", lambda: {"changed": True})
        else:
            monkeypatch.setattr(module, "PROTOCOL_SHA", "0" * 64)
        with pytest.raises(ValueError, match="changed"):
            module.load(root, output, expected)


def test_strict_threshold_connectivity_first_largest_and_source_geometry():
    heat = np.zeros((288, 512), dtype=np.float32)
    heat[0, 0] = 0.25
    heat[10, 20] = 0.5
    heat[11, 21] = 0.5
    heat[30, 40:42] = 0.5
    assert not locate_shuttle(heat, 1024, 576, 0.5)["visible"]
    point = locate_shuttle(heat, 1024, 576, 0.25)
    assert point["components"] == 2
    assert point["selected_component_id"] == 1
    assert (point["x"], point["y"]) == (42.0, 22.0)


def test_live_comparison_lifetime_blocks_interpretation_and_second_attempt(
    tmp_path, monkeypatch
):
    root, _, output, expected, _ = frozen(tmp_path, monkeypatch)
    module.run(root, output, expected)
    terminal = next(output.glob("attempts/*/terminal.json"))
    with pytest.raises(ValueError, match="lifetime remains present"):
        module.interpret(
            root, output, expected, terminal, module.audit.file_hash(terminal)
        )
    with pytest.raises(FileExistsError):
        module.run(root, output, expected)
    assert len(list(output.glob("attempts/*/terminal.json"))) == 1


def test_real_store_admission_blocks_all_comparison_work(tmp_path, monkeypatch):
    root, _, output, expected, _ = frozen(tmp_path, monkeypatch)
    store = Store(root / "data/processed")
    active = {"id": "existing", "kind": "generated", "status": "running"}
    store.claim_job(active)
    monkeypatch.setattr(
        module, "compute", lambda *_args: pytest.fail("admission bypass")
    )
    try:
        with pytest.raises(ConflictError):
            module.run(root, output, expected)
        terminal = module.heatmaps.read(next(output.glob("attempts/*/terminal.json")))
        assert terminal["status"] == "failed" and terminal["job_id"] is None
        assert not list(output.glob("attempts/*/raw.json"))
        assert store.job("existing")["status"] == "running"
    finally:
        active["status"] = "completed"
        store.put_job(active)


CHILD = r"""
import json
import os
from pathlib import Path
import sys
from badminton import shuttle_threshold_comparison as module
root = Path(sys.argv[1])
spec = module.heatmaps.read(root / 'generated-protocol.json')
module.protocol = lambda: spec
module.PROTOCOL_SHA = module.audit.digest(module.audit.encoded(spec))
module.consumers = lambda original: {'consumer': module.audit.seal(original, original / 'consumer.py')}
capture = root / '.cache/capture'
output = root / '.cache/comparison'
expected = module.freeze(root, capture, capture / 'control-report.json', output)['experiment_sha256']
result = module.run(root, output, expected)
(root / 'worker-result.json').write_bytes(module.audit.encoded({'expected': expected, 'result': result}))
"""


@pytest.mark.parametrize(
    ("mismatch", "tamper"),
    [
        (False, None),
        (True, None),
        (False, "owner"),
        (False, "status"),
        (False, "raw"),
        (False, "input"),
        (False, "missing_job"),
    ],
)
def test_exited_generated_worker_store_proof_and_complete_interpretation(
    tmp_path, monkeypatch, mismatch, tamper
):
    root, _, _, spec = fixture_data(tmp_path, "components" if mismatch else None)
    install(monkeypatch, root, spec)
    env = os.environ.copy()
    for name in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "AGENT_PROJECT_TOKEN",
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
    ):
        env.pop(name, None)
    env.update(
        BADMINTON_ROOT=str(root),
        BADMINTON_DATA_DIR=str(root / "data/processed"),
        BADMINTON_WEIGHTS_DIR=str(root / "models/weights"),
        PYTHONPATH=str(module.CODE_ROOT / "backend"),
    )
    child = subprocess.Popen(
        [sys.executable, "-c", CHILD, str(root)],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = child.communicate(timeout=45)  # No signal on observation timeout.
    assert child.returncode == 0, (stdout, stderr)
    output = root / ".cache/comparison"
    saved = module.heatmaps.read(root / "worker-result.json")
    expected = saved["expected"]
    terminal = next(output.glob("attempts/*/terminal.json"))
    value = module.heatmaps.read(terminal)
    try:
        assert (
            psutil.Process(value["process"]["pid"]).create_time()
            != value["process"]["creation_time"]
        )
    except psutil.NoSuchProcess:
        pass
    if tamper:
        if tamper == "owner":
            value["process"]["creation_time"] += 1
        elif tamper == "status":
            value["status"] = "failed"
        elif tamper == "raw":
            (output / value["raw"]["path"]).write_bytes(b"changed")
        elif tamper == "input":
            (root / ".cache/capture/case0.npy").write_bytes(b"changed")
        else:
            value["job_id"] = "missing-registration"
        terminal.write_bytes(module.audit.encoded(value))
        with pytest.raises(ValueError):
            module.interpret(
                root, output, expected, terminal, module.audit.file_hash(terminal)
            )
        assert not list(output.glob("interpretations/*/report.json"))
        return
    result = module.interpret(
        root, output, expected, terminal, module.audit.file_hash(terminal)
    )
    report = module.heatmaps.read(module.audit.sealed_path(output, result["report"]))
    assert report["summary"]["cases"] == 4
    assert report["summary"]["states"] == dict.fromkeys(module.STATES, 1)
    assert not any(report["eligibility"].values())
    assert len(report["cases"]) == 4
    if mismatch:
        assert report["disposition"] == "incompatible_unscored"
        assert report["summary"]["variants"]["candidate"]["unavailable"] == 4
    else:
        assert (
            report["disposition"] == "rejected"
        )  # Recall gain adds a false observation.
        unknown = report["groups"]["state:unknown"]["variants"]["candidate"]
        assert unknown["outcomes"] == {"observed_unscored": 1}
        assert unknown["observed_components"] == 1
        assert unknown["visible_reference_support"] == 0
        assert report["groups"]["difficulty:occlusion"]["cases"] == 0
    assert Store(root / "data/processed").job(value["job_id"])["status"] == "completed"


def test_duplicate_and_malformed_observations_are_refused():
    with pytest.raises(ValueError, match="Duplicate"):
        module.unique([{"id": "same"}, {"id": "same"}])
    case = {"width": 512, "height": 288}
    label = {"state": "unknown"}
    point = locate_shuttle(np.ones((2, 2)), 512, 288)
    point["x"] = float("nan")
    with pytest.raises(ValueError, match="coordinates"):
        module.outcome(point, case, label, 0.005)


def test_cli_rejects_credentials_before_research(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "generated-noncredential")
    with pytest.raises(SystemExit):
        module.main(
            [
                "run",
                "--root",
                str(tmp_path),
                "--output",
                str(tmp_path / ".cache/new"),
                "--experiment-sha256",
                "0" * 64,
            ]
        )
