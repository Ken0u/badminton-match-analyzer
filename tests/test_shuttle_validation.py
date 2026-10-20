"""Source identity and uncertainty must survive an immutable review packet."""

import copy
import json
import sqlite3

import av
import numpy as np
import pytest
from badminton import shuttle_validation as audit
from badminton.ingest import inspect_video
from badminton.storage import Store
from media_fixtures import write_rotated_video
from PIL import Image


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    sources, inventory = [], {"schema_version": 1, "sources": []}
    for rotation in (0, 90):
        path = write_rotated_video(tmp_path / f"source-{rotation}.mp4", rotation)
        store = Store(tmp_path / "processed")
        meta = inspect_video(path, "singles", store, tmp_path)
        entries = {
            "video": path,
            "metadata": store.data / meta["id"] / "metadata.json",
            "timestamps": store.data / meta["id"] / "timestamps.json",
        }
        inventory["sources"].append(
            {
                "video_id": meta["id"],
                "frame_count": meta["frame_count"],
                "inputs": {k: audit.seal(tmp_path, p) for k, p in entries.items()},
            }
        )
        sources.append(
            {
                "id": meta["id"],
                "sha256": meta["sha256"],
                "frame_count": meta["frame_count"],
            }
        )
    raw = audit.encoded(inventory)
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_bytes(raw)
    protocol = copy.deepcopy(audit.PROTOCOL)
    protocol.update(
        sources=sources,
        inventory_sha256=audit.digest(raw),
        grid_points_per_source=2,
        extra_frames={sources[0]["id"]: [0]},
    )
    monkeypatch.setattr(audit, "PROTOCOL", protocol)
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_bytes(audit.encoded(protocol))
    return tmp_path, inventory_path, protocol_path, tmp_path / ".cache/packet"


def create(corpus):
    root, inventory, protocol, output = corpus
    return audit.make_packet(
        root, inventory, audit.PROTOCOL["inventory_sha256"], protocol, output
    )


def load(corpus):
    output = corpus[3]
    raw = (output / "packet.json").read_bytes()
    return audit.validate_packet(output, raw, audit.digest(raw))[0]


def reseal_inventory(corpus, change):
    root, path, protocol, _ = corpus
    document = audit.read_json(path.read_bytes())
    change(document, root)
    path.write_bytes(audit.encoded(document))
    audit.PROTOCOL["inventory_sha256"] = audit.file_hash(path)
    protocol.write_bytes(audit.encoded(audit.PROTOCOL))


def test_production_protocol_and_fixed_selection():
    from pathlib import Path

    spec = (
        Path(__file__).resolve().parents[1]
        / "data/manifests/shuttle_visibility_protocol_v1.json"
    )
    assert audit.read_json(spec.read_bytes()) == audit.PROTOCOL
    selections = [audit.selection(s) for s in audit.PROTOCOL["sources"]]
    assert [len(values) for values in selections] == [35, 25]
    assert audit.selection(audit.PROTOCOL["sources"][0]) == sorted(set(selections[0]))
    assert all(f in selections[0] for f in (2039, 2043, 2047, 2048, 2077, 2079))


def test_packet_preserves_real_vfr_pts_and_original_oriented_pixels(corpus):
    result = create(corpus)
    assert result["cases"] == 5 and result["images"] == 8
    packet = load(corpus)
    root = corpus[0]
    for rotation in (0, 90):
        with av.open(str(root / f"source-{rotation}.mp4")) as container:
            frames = list(container.decode(container.streams.video[0]))
        cases = [c for c in packet["cases"] if c["rotation"] == rotation]
        for case in cases:
            for item in case["context"]:
                original = frames[item["frame"]]
                assert item["time_s"] == float(original.pts * original.time_base)
                with Image.open(corpus[3] / item["image"]["path"]) as image:
                    expected = np.rot90(
                        original.to_ndarray(format="rgb24"), rotation // 90
                    )
                    assert np.array_equal(np.asarray(image), expected)
    original = audit.file_hash(corpus[3] / "packet.json")
    with pytest.raises(FileExistsError):
        create(corpus)
    assert audit.file_hash(corpus[3] / "packet.json") == original


@pytest.mark.parametrize("key", ["video", "metadata", "timestamps"])
def test_changed_original_bytes_prevent_any_packet(corpus, key):
    root, path, _, output = corpus
    entry = audit.read_json(path.read_bytes())["sources"][0]["inputs"][key]
    target = root / entry["path"]
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ValueError, match="Changed sealed input"):
        create(corpus)
    assert not output.exists()


def test_resealed_but_incorrect_clock_fails_native_decode_without_completion(corpus):
    def alter(document, root):
        item = document["sources"][0]["inputs"]["timestamps"]
        path = root / item["path"]
        times = audit.read_json(path.read_bytes())
        times[1] += 0.005
        path.write_bytes(audit.encoded(times))
        document["sources"][0]["inputs"]["timestamps"] = audit.seal(root, path)

    reseal_inventory(corpus, alter)
    with pytest.raises(ValueError, match="Native source frame clock"):
        create(corpus)
    assert (corpus[3] / "attempt.json").is_file()
    assert not (corpus[3] / "packet.json").exists()
    with pytest.raises(FileExistsError):
        create(corpus)


@pytest.mark.parametrize(
    "relative", ["../escape.mp4", "/absolute.mp4", "C:/source.mp4", "source\\video.mp4"]
)
def test_resealed_paths_cannot_escape_source_root(corpus, relative):
    reseal_inventory(
        corpus,
        lambda document, _root: document["sources"][0]["inputs"]["video"].update(
            path=relative
        ),
    )
    with pytest.raises(ValueError, match=r"relative POSIX|escapes"):
        create(corpus)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["cases"].reverse(),
        lambda p: p["cases"][0].update(frame=p["cases"][0]["frame"] + 1),
        lambda p: p["cases"][0]["context"][0].update(pts=99999),
        lambda p: p["cases"][0]["context"].pop(),
        lambda p: p["cases"][0].update(rotation=90),
        lambda p: p["cases"][0].update(predictions=[{"x": 1, "y": 2}]),
    ],
)
def test_resealed_packet_cannot_substitute_rows_context_pts_or_geometry(
    corpus, mutation
):
    create(corpus)
    packet = audit.read_json((corpus[3] / "packet.json").read_bytes())
    mutation(packet)
    raw = audit.encoded(packet)
    with pytest.raises(ValueError):
        audit.validate_packet(corpus[3], raw, audit.digest(raw))


def test_packet_image_and_original_clock_copies_are_sealed(corpus):
    create(corpus)
    packet = load(corpus)
    image_path = corpus[3] / packet["cases"][0]["context"][0]["image"]["path"]
    image_path.write_bytes(image_path.read_bytes() + b"altered")
    with pytest.raises(ValueError, match="Changed sealed input"):
        load(corpus)


def label(case, **changes):
    return {
        "id": case["id"],
        "state": "unknown",
        "x": None,
        "y": None,
        "uncertainty_px": None,
        "reason": "Tiny white features cannot be distinguished from shuttle on the source image",
        "difficulty": ["unresolved"],
        "context_cut": False,
        **changes,
    }


def test_unknown_unlocalizable_and_invisible_truth_remain_distinct(corpus):
    create(corpus)
    packet = load(corpus)
    for state in audit.PROTOCOL["states"]:
        value = label(packet["cases"][0], state=state)
        if state == "visible":
            value.update(x=12.0, y=21.0, uncertainty_px=3)
        audit.validate_label(value, packet["cases"][0])
    document = {
        "schema_version": 1,
        "packet_sha256": "frozen",
        "assessor_session": "actual-source-review-A",
        "method": "source-only original-size inspection",
        "cases": [label(c) for c in packet["cases"]],
    }
    audit.validate_assessment(document, packet, "frozen")
    document["cases"].reverse()
    with pytest.raises(ValueError, match="assessment label"):
        audit.validate_assessment(document, packet, "frozen")


@pytest.mark.parametrize(
    "changes",
    [
        {"reason": "TODO"},
        {"x": 5},
        {"context_cut": None},
        {"state": "visible", "x": float("nan"), "y": 10, "uncertainty_px": 2},
        {"state": "visible", "x": 10, "y": 10, "uncertainty_px": 0},
        {"difficulty": []},
    ],
)
def test_assessments_reject_invented_nonfinite_or_unassessed_truth(corpus, changes):
    create(corpus)
    case = load(corpus)["cases"][0]
    with pytest.raises(ValueError):
        audit.validate_label(label(case, **changes), case)


def test_duplicate_and_nonfinite_json_are_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        audit.read_json(b'{"state":"unknown","state":"not_visible"}')
    with pytest.raises(ValueError, match="Nonfinite"):
        audit.read_json(b'{"x":NaN}')
    assert json.loads(audit.encoded({"unknown": None})) == {"unknown": None}


def label_lineage(corpus):
    create(corpus)
    packet = load(corpus)
    packet_sha = audit.file_hash(corpus[3] / "packet.json")
    assessments = [
        {
            "schema_version": 1,
            "packet_sha256": packet_sha,
            "assessor_session": f"generated-source-{i}",
            "method": "source-only original-size inspection",
            "cases": [label(c) for c in packet["cases"]],
        }
        for i in range(2)
    ]
    assessments[1]["cases"][0].update(state="visible", x=12, y=21, uncertainty_px=3)
    paths = [corpus[0] / f"assessment-{i}.json" for i in range(2)]
    for path, document in zip(paths, assessments):
        path.write_bytes(audit.encoded(document))
    adjudication = {
        "schema_version": 1,
        "packet_sha256": packet_sha,
        "assessment_sha256": [audit.file_hash(p) for p in paths],
        "adjudicator_session": "generated-adjudicator",
        "cases": [
            {
                "id": c["id"],
                "label": label(c),
                "reason": "Generated source cannot establish the tiny object's identity; preserve unresolved truth",
                "evidence_frames": [c["frame"]],
                "observed_cut_frames": [],
            }
            for c in packet["cases"]
        ],
    }
    path = corpus[0] / "adjudication.json"
    path.write_bytes(audit.encoded(adjudication))
    return packet, packet_sha, paths, path


def test_frozen_labels_bind_two_assessors_adjudication_and_all_unknowns(corpus):
    packet, packet_sha, paths, adjudication = label_lineage(corpus)
    output = corpus[0] / ".cache/frozen-labels"
    result = audit.freeze_labels(
        corpus[0], corpus[3], packet_sha, paths, adjudication, output
    )
    assert result["cases"] == 5 and result["disagreements"] == 1
    assert result["states"]["unknown"] == 5
    raw = (output / "labels.json").read_bytes()
    frozen = audit.load_labels(output, raw, result["labels_sha256"], packet, packet_sha)
    assert frozen["cases"][0]["disagreement"]["state"] is True
    with pytest.raises(FileExistsError):
        audit.freeze_labels(
            corpus[0], corpus[3], packet_sha, paths, adjudication, output
        )
    frozen["cases"][0]["label"]["state"] = "not_visible"
    changed = audit.encoded(frozen)
    with pytest.raises(ValueError, match="disagree with original"):
        audit.load_labels(output, changed, audit.digest(changed), packet, packet_sha)
    assessment = output / "assessment-a.json"
    assessment.write_bytes(assessment.read_bytes() + b" ")
    with pytest.raises(ValueError, match="Changed sealed"):
        audit.load_labels(output, raw, result["labels_sha256"], packet, packet_sha)


def test_same_assessor_cannot_supply_both_source_passes(corpus):
    _, packet_sha, paths, adjudication = label_lineage(corpus)
    document = audit.read_json(adjudication.read_bytes())
    document["assessment_sha256"] = [audit.file_hash(paths[0])] * 2
    adjudication.write_bytes(audit.encoded(document))
    output = corpus[0] / ".cache/invalid-labels"
    with pytest.raises(ValueError, match="Two separate assessors"):
        audit.freeze_labels(
            corpus[0], corpus[3], packet_sha, [paths[0], paths[0]], adjudication, output
        )
    assert not output.exists()


def test_unfinished_adjudication_cannot_be_frozen(corpus):
    _, packet_sha, paths, adjudication = label_lineage(corpus)
    document = audit.read_json(adjudication.read_bytes())
    document["cases"][0]["reason"] = "ROOT_PENDING"
    adjudication.write_bytes(audit.encoded(document))
    output = corpus[0] / ".cache/unfinished-labels"
    with pytest.raises(ValueError, match="Invalid source adjudication"):
        audit.freeze_labels(
            corpus[0], corpus[3], packet_sha, paths, adjudication, output
        )
    assert not output.exists()


def test_compatible_measurements_still_retain_raw_disagreements():
    a = {
        "state": "visible",
        "x": 20,
        "y": 30,
        "uncertainty_px": 3,
        "context_cut": False,
        "difficulty": ["blur"],
    }
    b = {**a, "x": 21, "uncertainty_px": 4}
    flags = audit.disagreement(a, b)
    assert flags["point_estimate"] and flags["uncertainty_radius"]
    assert not flags["location"] and not flags["state"]
    assert audit.disagreement(a, {**b, "x": 50})["location"]


def test_source_cut_requires_exact_reviewed_transition_evidence(corpus):
    _, packet_sha, paths, adjudication = label_lineage(corpus)
    document = audit.read_json(adjudication.read_bytes())
    document["cases"][0]["label"]["context_cut"] = True
    document["cases"][0]["observed_cut_frames"] = [1]
    adjudication.write_bytes(audit.encoded(document))
    with pytest.raises(ValueError, match="Observed cuts"):
        audit.freeze_labels(
            corpus[0],
            corpus[3],
            packet_sha,
            paths,
            adjudication,
            corpus[0] / ".cache/cuts",
        )
    document["cases"][0]["evidence_frames"] = [0, 1]
    adjudication.write_bytes(audit.encoded(document))
    assert (
        audit.freeze_labels(
            corpus[0],
            corpus[3],
            packet_sha,
            paths,
            adjudication,
            corpus[0] / ".cache/cuts",
        )["cases"]
        == 5
    )


def test_visibility_point_truth_unknowns_missing_outputs_and_uncertainty_are_separate():
    cases = [{"id": str(i), "width": 600, "height": 800} for i in range(9)]
    states = (
        ["visible"] * 3
        + ["visible_unlocalizable", "unknown"]
        + ["not_visible"] * 3
        + ["visible_unlocalizable"]
    )
    labels = [
        {"id": c["id"], "label": label(c, state=state)}
        for c, state in zip(cases, states)
    ]
    for entry in labels[:3]:
        entry["label"].update(x=100, y=100, uncertainty_px=1)
    labels[1]["label"]["uncertainty_px"] = 2
    observations = {
        c["id"]: {"available": True, "point": {"visible": True, "x": 100, "y": 100}}
        for c in cases
    }
    observations["1"]["point"]["x"] = 106
    observations["6"]["point"] = {"visible": False, "x": None, "y": None}
    for i in (2, 7, 8):
        observations[str(i)] = {
            "available": False,
            "point": None,
            "reason": "missing_cached_output",
        }
    result = audit.score_cases(cases, labels, observations)
    assert result["cases"] == 9 and result["visibility_known"] == 8
    assert (
        result["localization_eligible"] == 6
        and result["localization_truth_unavailable"] == 2
    )
    assert result["output_unavailable"] == 3
    assert {k: result["visibility"][k] for k in ("tp", "fp", "fn", "tn")} == {
        "tp": 3,
        "fp": 1,
        "fn": 2,
        "tn": 1,
    }
    assert {k: result["localization"][k] for k in ("tp", "fp", "fn", "tn")} == {
        "tp": 1,
        "fp": 2,
        "fn": 2,
        "tn": 1,
    }
    assert result["nominal_correct_frame_fraction"] == 2 / 6
    assert result["strict_localization_recall_lower_bound"] == 1 / 5
    assert result["strict_localization_recall_upper_bound"] == 3 / 5
    assert result["frames"][4]["outcome"] == "unknown_truth"
    observations["4"]["point"]["x"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        audit.score_cases(cases, labels, observations)


def test_all_unknown_truth_never_becomes_negative_accuracy():
    case = {"id": "unknown", "width": 600, "height": 800}
    result = audit.score_cases(
        [case],
        [{"id": case["id"], "label": label(case)}],
        {case["id"]: {"available": True, "point": {"visible": False}}},
    )
    assert result["cases"] == 1 and result["visibility_known"] == 0
    assert result["visibility"]["tn"] == 0
    assert result["localization"]["recall"] is None
    assert result["nominal_correct_frame_fraction"] is None


@pytest.fixture
def native(corpus):
    """A complete tiny generated v1 graph; no model or ignored helper executes."""
    from badminton.rallies import context_signature

    packet, packet_sha, assessment_paths, adjudication = label_lineage(corpus)
    root, _, _, packet_root = corpus
    truth = audit.read_json(adjudication.read_bytes())
    truth["cases"][0]["label"].update(state="visible", x=20, y=30, uncertainty_px=1)
    truth["cases"][1]["label"]["state"] = "not_visible"
    adjudication.write_bytes(audit.encoded(truth))
    label_root = root / ".cache/labels"
    labels_result = audit.freeze_labels(
        root, packet_root, packet_sha, assessment_paths, adjudication, label_root
    )
    labels_sha = labels_result["labels_sha256"]
    _, sources, labels = audit.audit_inputs(
        root, packet_root, packet_sha, label_root, labels_sha
    )
    locations = {k: root / k for k in ("data", "runtime", "weights")}
    for path in locations.values():
        path.mkdir()
    models = {}
    for key in ("player_pose", "player_pose_small", "shuttle"):
        path = locations["weights"] / (key + ".pt")
        path.write_bytes(("generated bytes, not a model: " + key).encode())
        models[key] = {"name": path.name, "sha256": audit.file_hash(path)}
    (locations["runtime"] / "model_manifest.json").write_bytes(audit.encoded(models))
    for name in (
        "pipeline.py",
        "shuttle.py",
        "tracking.py",
        "segments.py",
        "scene_review.py",
        "calibration_context.py",
    ):
        (locations["runtime"] / name).write_text(
            "raise RuntimeError('Never execute generated runtime')\n", encoding="utf-8"
        )
    source_files = {p.name: audit.file_hash(p) for p in locations["runtime"].iterdir()}
    plans = []
    with sqlite3.connect(locations["data"] / "catalog.sqlite3") as cx:
        cx.executescript(
            "CREATE TABLE videos(id TEXT,document TEXT);"
            "CREATE TABLE annotations(video_id TEXT,revision INTEGER,document TEXT);"
            "CREATE TABLE jobs(id TEXT,document TEXT);"
        )
        for _, meta, times, _ in sources:
            vid = meta["id"]
            folder = locations["data"] / vid
            (folder / "runs").mkdir(parents=True)
            (folder / "metadata.json").write_bytes(audit.encoded(meta))
            (folder / "timestamps.json").write_bytes(audit.encoded(times))
            ann = {
                "revision": 0,
                "camera_corrections": [],
                "scene_ranges": [],
                "calibrations": [],
            }
            cx.execute("INSERT INTO videos VALUES (?,?)", (vid, json.dumps(meta)))
            cx.execute(
                "INSERT INTO annotations VALUES (?,?,?)", (vid, 0, json.dumps(ann))
            )
            recipe = {
                "method": "overlapping source windows with immutable stage checkpoints v1",
                "video": {
                    k: meta.get(k)
                    for k in (
                        "id",
                        "sha256",
                        "mode",
                        "width",
                        "height",
                        "rotation",
                        "source_start_s",
                        "duration_s",
                        "frame_count",
                        "fps",
                    )
                },
                "timestamps_sha256": audit.recipe_hash(times),
                "settings": {
                    "player_model": "small",
                    "auto_calibrate": True,
                    "recognize": False,
                },
                "core_seconds": 60,
                "halo_seconds": 4,
                "source_files": source_files,
                "context_signature": context_signature(ann, 0, len(times)),
                "local_side_files": {},
                "library_versions": {"generator": "not real inference"},
            }
            key = audit.recipe_hash(recipe)
            window = {
                "index": 0,
                "core_start_frame": 0,
                "core_end_frame": len(times),
                "start_frame": 0,
                "end_frame": len(times),
            }
            plan = {
                "schema_version": 1,
                "stage": "analysis",
                "video_id": vid,
                "video_sha256": meta["sha256"],
                "analysis_key": key,
                "recipe": recipe,
                "parts": [{"window": window, "stages": {}}],
                "job_id": "parent-" + vid,
                "state": "completed",
                "processing_complete": True,
                "fully_annotated": False,
            }
            dependencies = {}
            for stage in ("segments", "players", "shuttle"):
                stage_key = audit.native_stage_key(
                    recipe, stage, None if stage == "segments" else window, dependencies
                )
                run_id = stage_key[:32]
                run = {
                    "schema_version": 1,
                    "stage": stage,
                    "video_id": vid,
                    "video_sha256": meta["sha256"],
                    "analysis_key": key,
                    "analysis_stage_key": stage_key,
                    "analysis_part_index": -1 if stage == "segments" else 0,
                    "start_frame": 0,
                    "end_frame": len(times),
                    "cut_frames": [],
                    "raw_cut_frames": [],
                    "known_preceding_cut_frames": [],
                    "known_preceding_timestamp_gaps": [],
                    "preceding_reviewed_cut_frame": None,
                    "applied_camera_corrections": [],
                }
                if stage == "segments":
                    run.update(
                        boundaries=[],
                        timestamp_gap_threshold_s=max(0.1, 2.5 / meta["fps"]),
                    )
                else:
                    run.update(
                        analysis_core_start_frame=0,
                        analysis_core_end_frame=len(times),
                        processed_frames=len(times),
                        checkpoint_sha256=models[
                            "player_pose_small" if stage == "players" else "shuttle"
                        ]["sha256"],
                    )
                    run["frames"] = []
                    for frame, time_s in enumerate(times):
                        row = {
                            "frame": frame,
                            "time_s": time_s,
                            "camera_segment_start_frame": 0,
                        }
                        if stage == "shuttle":
                            candidate = {"id": 1, "x": 20, "y": 30, "confidence": 0.9}
                            row["shuttle"] = {
                                **candidate,
                                "visible": True,
                                "repaired": False,
                                "component_candidates": [candidate],
                                "selected_component_id": 1,
                                "selection_context_start_frame": frame,
                                "selection_context_end_frame": frame + 1,
                                "selection_context_excluded": False,
                            }
                        else:
                            row["players"] = []
                        run["frames"].append(row)
                    if stage == "shuttle":
                        run.update(
                            repaired_frames=0,
                            temporal_context_crosses_detected_cuts=False,
                            localization={"method": "generated observed component"},
                        )
                    else:
                        run.update(calibration_signature=[], automatic_calibrations=[])
                path = folder / "runs" / (run_id + ".json")
                path.write_bytes(audit.encoded(run))
                cp = {
                    "run_id": run_id,
                    "sha256": audit.file_hash(path),
                    "owned_candidate_count": 0,
                }
                if stage == "segments":
                    plan["segments"] = cp
                else:
                    plan["parts"][0]["stages"][stage] = cp
                dependencies[stage] = cp["sha256"]
                job = {
                    "id": run_id,
                    "kind": stage,
                    "video_id": vid,
                    "status": "completed",
                    "summary": {"checkpoint": cp},
                }
                cx.execute("INSERT INTO jobs VALUES (?,?)", (run_id, json.dumps(job)))
            parent = {
                "kind": "analysis",
                "video_id": vid,
                "status": "completed",
                "summary": {"analysis_key": key},
            }
            cx.execute(
                "INSERT INTO jobs VALUES (?,?)", (plan["job_id"], json.dumps(parent))
            )
            path = folder / "analysis" / key / "manifest.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(audit.encoded(plan))
            plans.append(path)
    return {
        "root": root,
        "packet_root": packet_root,
        "packet_sha": packet_sha,
        "label_root": label_root,
        "labels_sha": labels_sha,
        "sources": sources,
        "packet": packet,
        "labels": labels,
        "locations": locations,
        "plans": plans,
    }


def native_evidence(native):
    return audit.native_observations(
        native["root"],
        native["sources"],
        native["packet"]["cases"],
        native["labels"]["cases"],
        {
            k: v.relative_to(native["root"]).as_posix()
            for k, v in native["locations"].items()
        },
    )


def edit_native_shuttle(native, change):
    """Simulate internally sealed but malformed source data, not just bad hashes."""
    plan_path = native["plans"][0]
    plan = audit.read_json(plan_path.read_bytes())
    cp = plan["parts"][0]["stages"]["shuttle"]
    path = (
        native["locations"]["data"]
        / plan["video_id"]
        / "runs"
        / (cp["run_id"] + ".json")
    )
    run = audit.read_json(path.read_bytes())
    change(run)
    path.write_bytes(audit.encoded(run))
    cp["sha256"] = audit.file_hash(path)
    plan_path.write_bytes(audit.encoded(plan))
    with sqlite3.connect(native["locations"]["data"] / "catalog.sqlite3") as cx:
        row = cx.execute(
            "SELECT document FROM jobs WHERE id=?", (cp["run_id"],)
        ).fetchone()
        job = json.loads(row[0])
        job["summary"]["checkpoint"] = cp
        cx.execute(
            "UPDATE jobs SET document=? WHERE id=?", (json.dumps(job), cp["run_id"])
        )
    return path


def test_complete_generated_native_graph_freeze_audit_and_groups(native):
    n = native
    baseline_root = n["root"] / ".cache/native-index"
    result = audit.freeze_baseline(
        n["root"],
        n["packet_root"],
        n["packet_sha"],
        n["label_root"],
        n["labels_sha"],
        n["locations"],
        baseline_root,
    )
    assert result["cases"] == result["available"] == 5
    output = n["root"] / ".cache/audit"
    result = audit.evaluate_baseline(
        n["root"],
        n["packet_root"],
        n["packet_sha"],
        n["label_root"],
        n["labels_sha"],
        baseline_root / "baseline.json",
        result["baseline_sha256"],
        output,
    )
    report = audit.read_json((output / "report.json").read_bytes())
    assert result["all"]["visibility_known"] == 2
    assert result["all"]["truth_states"]["unknown"] == 3
    assert result["all"]["visibility"]["tp"] == result["all"]["visibility"]["fp"] == 1
    assert report["groups"]["difficulty/occlusion"]["cases"] == 0
    assert report["groups"]["availability/no"]["cases"] == 0
    assert (
        sum(
            report["groups"]["source/" + s["id"]]["cases"]
            for s in audit.PROTOCOL["sources"]
        )
        == 5
    )
    assert report["groups"]["all"]["frames"][0]["outcome"] == "correct_localization"
    assert report["groups"]["selection/known_gap"]["cases"] == 1
    assert report["groups"]["selection/uniform"]["cases"] == 4
    assert report["disagreements"]["camera_context"] == 0
    assert len(report["consumer_files"]) == 10
    assert all(
        audit.file_hash(output / "consumer" / name) == sha
        for name, sha in report["consumer_files"].items()
    )


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda r: r["frames"][1].update(frame=0), "membership/PTS"),
        (lambda r: r["frames"][1].update(time_s=0.05), "membership/PTS"),
        (lambda r: r["frames"].reverse(), "membership/PTS"),
        (lambda r: r.update(video_sha256="0" * 64), "stage/source/range"),
        (
            lambda r: r["frames"][0]["shuttle"].update(x=999),
            "native visible coordinate",
        ),
        (
            lambda r: r["frames"][0]["shuttle"].update(x=21),
            "selected observed component",
        ),
        (
            lambda r: r["frames"][0].update(camera_segment_start_frame=1),
            "camera identity",
        ),
    ],
)
def test_resealed_native_substitutions_still_rejected(native, change, match):
    edit_native_shuttle(native, change)
    with pytest.raises(ValueError, match=match):
        native_evidence(native)


def test_missing_native_file_retains_known_visible_miss(native):
    path = edit_native_shuttle(native, lambda r: None)
    path.unlink()
    evidence = native_evidence(native)
    result = audit.score_cases(
        native["packet"]["cases"], native["labels"]["cases"], evidence["observations"]
    )
    assert result["cases"] == 5 and result["output_unavailable"] == 3
    assert result["visibility"]["fn"] == 1 and result["visibility"]["tn"] == 0
    assert result["localization"]["fn"] == 1
    assert "missing_native_stage_file" in next(iter(result["unavailable_reasons"]))


def test_changed_native_runtime_weight_and_index_rejected(native):
    n = native
    folder = n["root"] / ".cache/sealed-native"
    result = audit.freeze_baseline(
        n["root"],
        n["packet_root"],
        n["packet_sha"],
        n["label_root"],
        n["labels_sha"],
        n["locations"],
        folder,
    )
    for path in (
        n["locations"]["runtime"] / "shuttle.py",
        n["locations"]["weights"] / "shuttle.pt",
    ):
        original = path.read_bytes()
        path.write_bytes(original + b"changed")
        with pytest.raises(ValueError, match="Changed native dependency bytes"):
            native_evidence(n)
        path.write_bytes(original)
    index = folder / "baseline.json"
    index.write_bytes(index.read_bytes() + b" ")
    with pytest.raises(ValueError, match="Changed frozen baseline index"):
        audit.evaluate_baseline(
            n["root"],
            n["packet_root"],
            n["packet_sha"],
            n["label_root"],
            n["labels_sha"],
            index,
            result["baseline_sha256"],
            n["root"] / ".cache/invalid-audit",
        )


def test_native_context_incompatibility_is_unavailable_not_absence(native):
    data = native["locations"]["data"]
    vid = native["sources"][0][1]["id"]
    with sqlite3.connect(data / "catalog.sqlite3") as cx:
        raw = cx.execute(
            "SELECT document FROM annotations WHERE video_id=?", (vid,)
        ).fetchone()[0]
        doc = json.loads(raw)
        doc["camera_corrections"] = [{"frame": 2, "is_cut": True}]
        doc["scene_ranges"] = [
            {"id": "excluded", "start_frame": 2, "end_frame": 3, "scene": "unknown"}
        ]
        cx.execute(
            "UPDATE annotations SET document=? WHERE video_id=?", (json.dumps(doc), vid)
        )
    evidence = native_evidence(native)
    result = audit.score_cases(
        native["packet"]["cases"], native["labels"]["cases"], evidence["observations"]
    )
    assert result["cases"] == 5 and result["output_unavailable"] == 3
    assert result["visibility"]["fn"] == 1
    assert all(
        "incompatible_frozen_inference_context" in value["reason"]
        for key, value in evidence["observations"].items()
        if key.startswith(vid)
    )


def test_invalid_transitive_selection_retains_case_and_known_truth(native):
    edit_native_shuttle(
        native,
        lambda r: r["frames"][0]["shuttle"].update(selection_context_start_frame=-1),
    )
    evidence = native_evidence(native)
    row = evidence["observations"][native["packet"]["cases"][0]["id"]]
    assert not row["available"] and "transitive_selection_context" in row["reason"]
    result = audit.score_cases(
        native["packet"]["cases"], native["labels"]["cases"], evidence["observations"]
    )
    assert result["localization"]["fn"] == 1


def test_no_baseline_recipe_selection_by_results(native):
    path = native["plans"][0]
    alternative = path.parent.parent / ("f" * 64) / "manifest.json"
    alternative.parent.mkdir()
    alternative.write_bytes(path.read_bytes())
    with pytest.raises(ValueError, match="Ambiguous baseline"):
        native_evidence(native)


def test_sqlite_source_metadata_is_authoritative_without_optional_sidecar(native):
    for _, meta, _, _ in native["sources"]:
        (native["locations"]["data"] / meta["id"] / "metadata.json").unlink()
    evidence = native_evidence(native)
    assert all(row["available"] for row in evidence["observations"].values())
    # Missing registered metadata is never repaired from the optional sidecar.
    vid = native["sources"][0][1]["id"]
    with sqlite3.connect(native["locations"]["data"] / "catalog.sqlite3") as cx:
        cx.execute("DELETE FROM videos WHERE id=?", (vid,))
    evidence = native_evidence(native)
    assert all(
        not value["available"]
        for key, value in evidence["observations"].items()
        if key.startswith(vid)
    )


def test_native_clock_and_stage_recipe_cannot_be_substituted(native):
    plan_path = native["plans"][0]
    plan = audit.read_json(plan_path.read_bytes())
    path = native["locations"]["data"] / plan["video_id"] / "timestamps.json"
    original = path.read_bytes()
    times = audit.read_json(original)
    times[1] += 0.001
    path.write_bytes(audit.encoded(times))
    with pytest.raises(ValueError, match="Substituted native source clock"):
        native_evidence(native)
    path.write_bytes(original)
    plan["parts"][0]["stages"]["shuttle"]["run_id"] = "0" * 32
    plan_path.write_bytes(audit.encoded(plan))
    with pytest.raises(ValueError, match="dependency/recipe key mismatch"):
        native_evidence(native)


def test_registered_target_changes_invalidate_frozen_baseline(native):
    n = native
    folder = n["root"] / ".cache/registered-native"
    result = audit.freeze_baseline(
        n["root"],
        n["packet_root"],
        n["packet_sha"],
        n["label_root"],
        n["labels_sha"],
        n["locations"],
        folder,
    )
    plan = audit.read_json(n["plans"][0].read_bytes())
    with sqlite3.connect(n["locations"]["data"] / "catalog.sqlite3") as cx:
        job = json.loads(
            cx.execute(
                "SELECT document FROM jobs WHERE id=?", (plan["job_id"],)
            ).fetchone()[0]
        )
        job["status"] = "failed"
        cx.execute(
            "UPDATE jobs SET document=? WHERE id=?", (json.dumps(job), plan["job_id"])
        )
    with pytest.raises(
        ValueError, match="Frozen native baseline inputs/results changed"
    ):
        audit.evaluate_baseline(
            n["root"],
            n["packet_root"],
            n["packet_sha"],
            n["label_root"],
            n["labels_sha"],
            folder / "baseline.json",
            result["baseline_sha256"],
            n["root"] / ".cache/invalid-registration",
        )


@pytest.mark.parametrize("coordinate", [float("nan"), float("inf"), True])
def test_native_nonfinite_visible_coordinates_cannot_hide_in_unknown_cases(
    native, coordinate
):
    n = native
    plan = audit.read_json(n["plans"][0].read_bytes())
    run_id = plan["parts"][0]["stages"]["shuttle"]["run_id"]
    run = audit.read_json(
        (
            n["locations"]["data"] / plan["video_id"] / "runs" / (run_id + ".json")
        ).read_bytes()
    )
    run["frames"][-1]["shuttle"]["x"] = coordinate
    with pytest.raises(ValueError, match="native visible coordinate"):
        audit.native_rows(
            run, n["sources"][0][1], n["sources"][0][2], plan["parts"][0]["window"]
        )
