"""Generated metadata only; no scientific files, source images or model access."""

import ast
import copy
import importlib.util
import itertools
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from badminton import shuttle_context_audit as audit

CHECKOUT = Path(__file__).resolve().parents[1]
SCRIPT = CHECKOUT / "scripts/audit_shuttle_context.py"
SOURCE = "PRIVATE_SOURCE_ID"
SHA = "a" * 64


def interval(first=0, last=20, scene=None):
    value = {"start_frame": first, "end_frame": last}
    if scene is not None:
        value["scene"] = scene
    return value


def metadata():
    view = {
        "id": "PRIVATE_VIEW",
        "video_id": SOURCE,
        "start_frame": 0,
        "end_frame": 20,
        "case_ids": ["PRIVATE_A", "PRIVATE_B"],
    }
    run = {
        "id": "PRIVATE_RUN",
        "video_id": SOURCE,
        "video_sha256": SHA,
        "stage": "shuttle",
        "start_frame": 0,
        "end_frame": 20,
        "camera_ranges": [interval()],
        "cut_frames": [10],
    }
    snapshot = {
        "video": {"id": SOURCE, "sha256": SHA},
        "revision": 2,
        "annotations": {
            "video_id": SOURCE,
            "revision": 2,
            "scene_ranges": [interval(scene="live")],
        },
    }
    return view, run, snapshot


def generated(tmp_path, *, edit_run=None, edit_snapshot=None):
    protocol = json.loads(
        (
            CHECKOUT / "data/manifests/shuttle_context_audit_protocol_v1.json"
        ).read_bytes()
    )
    protocol["denominators"].update(views_per_method=1, cases_per_method=2)
    protocol["fixed_diagnostic_premise"]["unavailable_cases_per_method"] = 2
    bindings, hashes = {}, {}

    def put(name, raw):
        raw = raw if isinstance(raw, bytes) else audit.encode(raw)
        path = tmp_path / (name + ".json")
        path.write_bytes(raw)
        return {"path": path.name, "sha256": audit.checksum(raw)}

    # Invalid JSON proves these scientific/premise containers are hash-only.
    for name in (
        "original-experiment",
        "sealed-familiar-result",
        "original-public-protocol",
    ):
        entry = put(name, b"FORBIDDEN_ORIGINAL_MODEL_OR_RESULT_NOT_JSON")
        bindings[name], hashes[name] = entry["path"], entry["sha256"]
    view, run, snapshot = metadata()
    if edit_run:
        edit_run(run)
    if edit_snapshot:
        edit_snapshot(snapshot)
    snapshot["annotations"]["shots"] = [{"coordinates": "PRIVATE_COORDINATES"}]
    snapshot["jobs"] = {"private": "FORBIDDEN_JOB"}
    snapshot["video"]["path"] = "PRIVATE_VIDEO_PATH"
    packet = {
        "cases": [
            {
                "id": "PRIVATE_A",
                "video_id": SOURCE,
                "frame": 9,
                "label": {"state": "PRIVATE_VISIBILITY"},
            },
            {
                "id": "PRIVATE_B",
                "video_id": SOURCE,
                "frame": 10,
                "point": "PRIVATE_COORDINATES",
            },
        ],
        "labels": "FORBIDDEN_LABELS",
    }
    raw_index = {"references": {}}
    for method in audit.METHODS:
        current = {
            **run,
            "frames": [{"shuttle": "PRIVATE_COORDINATES", "score": "FORBIDDEN_SCORE"}],
        }
        run_ref = put("run-" + method, current)
        receipt_ref = put(
            "receipt-" + method,
            {
                "view": {**view, "pose": "FORBIDDEN_POSE"},
                "run": run_ref,
                "score": "FORBIDDEN_SCORE",
            },
        )
        raw_index["references"][method] = [
            {"origin": "continuation", "run": run_ref, "receipt": receipt_ref}
        ]
    for name, value in (
        ("familiar-packet", packet),
        (
            "baseline-context-container",
            {"evidence": {"catalogs": {SOURCE: {"snapshot": snapshot}}}},
        ),
        ("raw-index", raw_index),
    ):
        entry = put(name, value)
        bindings[name], hashes[name] = entry["path"], entry["sha256"]
    protocol["input_sha256"] = hashes
    return protocol, bindings


def cli_module():
    spec = importlib.util.spec_from_file_location("metadata_context_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_projectors_do_not_retain_nested_forbidden_payloads():
    _, run, snapshot = metadata()
    run.update(
        frames=[{"shuttle": "SECRET"}],
        camera_ranges=[{**interval(), "coordinates": "SECRET"}],
        cut_frames=[{"coordinates": "SECRET"}],
    )
    snapshot["annotations"]["scene_ranges"][0]["coordinates"] = "SECRET"
    snapshot["video"]["path"] = "SECRET"
    projected = {
        "run": audit.project_run(run),
        "snapshot": audit.project_snapshot(snapshot),
        "view": audit.project_view(
            {"id": {"coordinates": "SECRET"}, "case_ids": [{"coordinates": "SECRET"}]}
        ),
    }
    assert b"SECRET" not in audit.encode(projected)
    assert b"coordinates" not in audit.encode(projected)
    assert projected["run"]["cut_frames"] == [{"invalid_type": "dict"}]


def test_partition_matches_exact_archived_guard_on_generated_metadata():
    raw = (CHECKOUT / "backend/badminton/shuttle_selection_study.py").read_text(
        encoding="utf-8"
    )
    node = next(
        n
        for n in ast.parse(raw).body
        if isinstance(n, ast.FunctionDef) and n.name == "eligible_segments"
    )
    namespace = {"__package__": "badminton", "itertools": itertools}
    exec(
        compile(
            ast.Module(body=[node], type_ignores=[]), "archived-generated-guard", "exec"
        ),
        namespace,
    )
    reference = namespace["eligible_segments"]
    cameras = (
        None,
        [],
        [interval()],
        [interval(0, 10), interval(10, 20)],
        [interval(), interval(5, 15)],
        [interval(-5, 30)],
        [{"start_frame": True, "end_frame": 20}],
        [None],
    )
    scenes = (
        None,
        [],
        [interval(scene="live")],
        [interval(scene="unknown")],
        [interval(scene="replay")],
        [interval(scene="non_play")],
        [interval(scene="live"), interval(4, 12, "unknown")],
        [interval(scene="live"), interval(5, 15, "live")],
        [{"start_frame": 0, "end_frame": 20, "scene": "invalid"}],
    )
    for camera, scene, cuts in itertools.product(
        cameras, scenes, ([], [0, 10], [10, 10], [20], [True])
    ):
        run = {
            "start_frame": 0,
            "end_frame": 20,
            "camera_ranges": camera,
            "cut_frames": cuts,
        }
        annotations = {"scene_ranges": scene}
        result, _ = audit.partition_context(run, annotations)
        projected = [
            {k: v[k] for k in ("start_frame", "end_frame", "eligible")} for v in result
        ]
        assert projected == reference(run, annotations), (camera, scene, cuts)


@pytest.mark.parametrize("scene", ("unknown", "replay", "non_play"))
def test_missing_camera_does_not_hide_explicit_scene_exclusion(scene):
    view, run, snapshot = metadata()
    del run["camera_ranges"]
    snapshot["annotations"]["scene_ranges"] = [interval(scene=scene)]
    result = audit.inspect_view(view, run, snapshot)
    case = audit.inspect_case(
        {"id": "PRIVATE_A", "video_id": SOURCE, "frame": 9}, [result]
    )
    expected = {
        "missing_camera_metadata",
        "uncovered_live_context",
        "explicit_" + scene + "_exclusion",
    }
    assert expected <= set(result["flags"])
    assert expected <= set(case["flags"])
    assert not case["eligible_metadata"]
    assert "missing_view_membership" not in case["flags"]


def test_cut_and_half_open_scene_boundaries_preserve_exact_native_frame():
    view, run, snapshot = metadata()
    snapshot["annotations"]["scene_ranges"] = [
        interval(0, 10, "live"),
        interval(10, 20, "unknown"),
    ]
    result = audit.inspect_view(view, run, snapshot)
    before = audit.inspect_case(
        {"id": "PRIVATE_A", "video_id": SOURCE, "frame": 9}, [result]
    )
    after = audit.inspect_case(
        {"id": "PRIVATE_B", "video_id": SOURCE, "frame": 10}, [result]
    )
    assert before["eligible_metadata"] and not after["eligible_metadata"]
    assert "explicit_unknown_exclusion" in after["flags"]
    assert [(v["start_frame"], v["end_frame"]) for v in result["segments"]] == [
        (0, 10),
        (10, 20),
    ]


@pytest.mark.parametrize(
    "cameras,flag",
    (
        ([], "uncovered_camera_context"),
        ([interval(), interval()], "ambiguous_camera_coverage"),
    ),
)
def test_missing_scene_preserves_independent_camera_diagnosis(cameras, flag):
    view, run, snapshot = metadata()
    run["camera_ranges"] = cameras
    del snapshot["annotations"]["scene_ranges"]
    result = audit.inspect_view(view, run, snapshot)
    case = audit.inspect_case(
        {"id": "PRIVATE_A", "video_id": SOURCE, "frame": 9}, [result]
    )
    assert {"missing_scene_metadata", flag} <= set(case["flags"])
    assert not case["eligible_metadata"]


@pytest.mark.parametrize(
    "mutation", ("source", "revision", "bool_revision", "run_extent")
)
def test_conflicting_source_or_revision_never_gets_eligibility(mutation):
    view, run, snapshot = metadata()
    if mutation == "source":
        run["video_sha256"] = "b" * 64
    elif mutation == "revision":
        snapshot["revision"] += 1
    elif mutation == "bool_revision":
        snapshot["revision"] = 1
        snapshot["annotations"]["revision"] = True
    else:
        run["end_frame"] -= 1
    result = audit.inspect_view(view, run, snapshot)
    case = audit.inspect_case(
        {"id": "PRIVATE_A", "video_id": SOURCE, "frame": 9}, [result]
    )
    assert not result["eligible_metadata"] and not case["eligible_metadata"]
    assert "eligible_metadata" not in case["flags"]


@pytest.mark.parametrize("duplicate_within", (False, True))
def test_ambiguous_view_membership_never_selects_favorable_occurrence(duplicate_within):
    view, run, snapshot = metadata()
    if duplicate_within:
        view["case_ids"].append("PRIVATE_A")
    result = audit.inspect_view(view, run, snapshot)
    case = audit.inspect_case(
        {"id": "PRIVATE_A", "video_id": SOURCE, "frame": 9},
        [result] if duplicate_within else [result, copy.deepcopy(result)],
    )
    assert case["flags"] == ["ambiguous_view_membership"]
    assert not case["eligible_metadata"]


def test_frozen_loader_never_decodes_science_and_excludes_forbidden_fields(tmp_path):
    protocol, bindings = generated(tmp_path)
    result, reader = audit.audit_metadata(protocol, bindings, tmp_path)
    raw = audit.encode(result)
    assert not any(
        value in raw
        for value in (
            b"PRIVATE_COORDINATES",
            b"PRIVATE_VISIBILITY",
            b"FORBIDDEN",
            b"PRIVATE_VIDEO_PATH",
        )
    )
    for method in audit.METHODS:
        counts = result["aggregate"][method]
        assert (counts["cases"], counts["views"], counts["eligible_cases"]) == (2, 1, 2)
        assert sum(s["cases"] for s in counts["sources"].values()) == 2
        assert sum(s["views"] for s in counts["sources"].values()) == 1
    reader.verify_unchanged()


def test_missing_run_preserves_every_case_and_method(tmp_path):
    protocol, bindings = generated(tmp_path)
    (tmp_path / "run-decoder.json").unlink()
    result, _ = audit.audit_metadata(protocol, bindings, tmp_path)
    decoder = result["aggregate"]["decoder"]
    assert (decoder["cases"], decoder["views"], decoder["eligible_cases"]) == (2, 1, 0)
    assert decoder["case_flags_non_additive"]["missing_run_metadata"] == 2
    assert result["aggregate"]["control"]["eligible_cases"] == 2


def test_missing_receipt_preserves_unknown_view_and_source_denominators(tmp_path):
    protocol, bindings = generated(tmp_path)
    (tmp_path / "receipt-control.json").unlink()
    result, _ = audit.audit_metadata(protocol, bindings, tmp_path)
    counts = result["aggregate"]["control"]
    assert (counts["cases"], counts["views"], counts["unassigned_views"]) == (2, 1, 1)
    assert sum(s["views"] for s in counts["sources"].values()) == 1
    assert counts["case_flags_non_additive"]["missing_view_membership"] == 2


def test_unknown_source_never_collides_with_a_literal_source_identifier(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sys.modules[__name__], "SOURCE", "None")
    protocol, bindings = generated(tmp_path)
    (tmp_path / "receipt-control.json").unlink()
    result, _ = audit.audit_metadata(protocol, bindings, tmp_path)
    counts = result["aggregate"]["control"]
    assert len(counts["sources"]) == 2
    assert sum(s["cases"] for s in counts["sources"].values()) == 2
    assert sum(s["views"] for s in counts["sources"].values()) == 1


@pytest.mark.parametrize(
    "target",
    ("familiar-packet.json", "run-control.json", "sealed-familiar-result.json"),
)
def test_hash_mutation_rejected_before_output(tmp_path, target):
    protocol, bindings = generated(tmp_path)
    with (tmp_path / target).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="bytes changed"):
        audit.audit_metadata(protocol, bindings, tmp_path)


def test_changed_or_newly_available_source_rejected_at_final_check(tmp_path):
    path = tmp_path / "value.json"
    raw = audit.encode({"value": 1})
    path.write_bytes(raw)
    reader = audit.BoundMetadata(tmp_path)
    descriptor = {"path": path.name, "sha256": audit.checksum(raw)}
    reader.read(descriptor)
    path.write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="changed during"):
        reader.verify_unchanged()
    path.unlink()
    with pytest.raises(FileNotFoundError):
        reader.read(descriptor)
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="appeared"):
        reader.verify_unchanged()


def test_path_escape_and_non_json_targets_are_refused(tmp_path):
    reader = audit.BoundMetadata(tmp_path)
    for path in ("../outside.json", "weights.pt", "source.mp4"):
        with pytest.raises(ValueError):
            reader.read({"path": path, "sha256": "a" * 64})


def test_reparse_ancestor_is_refused_before_opening_metadata(tmp_path, monkeypatch):
    from types import SimpleNamespace

    directory = tmp_path / "linked"
    directory.mkdir()
    path = directory / "metadata.json"
    raw = audit.encode({"value": 1})
    path.write_bytes(raw)
    original = Path.lstat

    def linked_info(self, *args, **kwargs):
        if self == directory:
            return SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", linked_info)
    with pytest.raises(ValueError, match="Symlink or reparse"):
        audit.BoundMetadata(tmp_path).read(
            {"path": "linked/metadata.json", "sha256": audit.checksum(raw)}
        )


def test_actual_generated_cli_stdout_is_aggregate_only_and_output_is_exclusive(
    tmp_path,
):
    protocol, bindings = generated(tmp_path)
    protocol_path, bindings_path = (
        tmp_path / "protocol.json",
        tmp_path / "bindings.json",
    )
    protocol_path.write_bytes(audit.encode(protocol))
    bindings_path.write_bytes(audit.encode(bindings))
    output = tmp_path / "new-private-output"
    command = [
        sys.executable,
        "-B",
        str(SCRIPT),
        "--root",
        str(tmp_path),
        "--protocol",
        str(protocol_path),
        "--bindings",
        str(bindings_path),
        "--output",
        str(output),
    ]
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("BADMINTON_")
        and k
        not in (
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "AGENT_PROJECT_TOKEN",
            "OPENAI_API_KEY",
            "CODEX_API_KEY",
        )
    }
    result = subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    public = json.loads(result.stdout)
    assert public["completed"] and public["methods"]["control"]["cases"] == 2
    assert "PRIVATE" not in result.stdout and str(tmp_path) not in result.stdout
    assert not any(public["eligibility"].values())
    completion = json.loads((output / "completion.json").read_bytes())
    for name, digest in completion["outputs"].items():
        assert audit.checksum((output / name).read_bytes()) == digest
    assert "PRIVATE" not in (output / "aggregate.json").read_text(encoding="utf-8")
    original = (output / "completion.json").read_bytes()
    again = subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30
    )
    assert (
        again.returncode != 0 and (output / "completion.json").read_bytes() == original
    )


@pytest.mark.parametrize(
    "target", ("run-control.json", "protocol.json", "bindings.json")
)
def test_cli_rechecks_consumer_and_source_before_publishing(
    tmp_path, monkeypatch, target
):
    protocol, bindings = generated(tmp_path)
    protocol_path, bindings_path = (
        tmp_path / "protocol.json",
        tmp_path / "bindings.json",
    )
    protocol_path.write_bytes(audit.encode(protocol))
    bindings_path.write_bytes(audit.encode(bindings))
    module = cli_module()
    original = module.verify_consumers
    calls = []

    def mutate_after_read(value):
        original(value)
        calls.append(True)
        if len(calls) == 2:
            (tmp_path / target).write_bytes(b"changed")

    monkeypatch.setattr(module, "verify_consumers", mutate_after_read)
    # The final source check must occur after the final consumer check as well.
    with pytest.raises(ValueError, match="changed"):
        module.main(
            [
                "--root",
                str(tmp_path),
                "--protocol",
                str(protocol_path),
                "--bindings",
                str(bindings_path),
                "--output",
                str(tmp_path / "new-output"),
            ]
        )
    assert not (tmp_path / "new-output").exists()
