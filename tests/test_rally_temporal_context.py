"""Generated sources only; no real images, external assessors or gold labels."""

import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

import pytest
from badminton import rally_temporal_context as t
from badminton.shuttle_supervision import encoded, file_hash
from PIL import Image
from test_rally_source_reference import clock

ROOT = Path(__file__).resolve().parents[1]


def continuation_protocol():
    return (
        json.loads(
            (ROOT / "data/manifests/rally_temporal_context_v2.json").read_bytes()
        ),
        json.loads(
            (ROOT / "data/manifests/rally_temporal_context_v1.json").read_bytes()
        ),
    )


def continuation_grant(protocol):
    claim = {
        "actor": "Ken0u",
        "host_id": "MSI",
        "session_id": "generated-session",
        "epoch": 1,
        "granted_at": 1000,
        "expires_at": 11800,
        "baseline_sha": "a" * 40,
        "branch": "codex/issue-242-generated",
        "spec_hash": protocol["spec_hash"],
    }
    return {
        "task": {
            "status": "running",
            "epoch": 1,
            "claim": claim,
            "spec_hash": protocol["spec_hash"],
            "human_approval": {"actor": "Ken0u", "spec_hash": protocol["spec_hash"]},
        },
        "receipt": {
            "status": "granted",
            "actor": "Ken0u",
            "task_id": "242",
            "epoch": 1,
            "claim": copy.deepcopy(claim),
        },
    }


def test_continuation_preserves_original_protocol_and_exact_cost():
    protocol, original = continuation_protocol()
    before = copy.deepcopy(original)
    assert t.validate_continuation(protocol, original) is protocol
    assert original == before
    assert t.PRIOR_PAYLOAD + protocol["limits"]["new_image_bytes"] == 8211600581
    assert protocol["limits"]["max_sessions"] == 6
    assert protocol["limits"]["replacement_launches"] == 0


@pytest.mark.parametrize(
    "path,value",
    [
        (("task",), True),
        (("schema_version",), True),
        (("sampling", "step_seconds"), 2),
        (("assessment", "no_exact_contacts"), False),
        (("sources", 0, "native_frame_count"), 990),
        (("limits", "runtime_seconds"), 14401),
        (("limits", "new_image_bytes"), 34040437),
        (("limits", "replacement_launches"), True),
        (("limits", "paid_services"), 0),
        (("continuation", "original_attempted_sessions"), False),
        (("continuation", "original_transmitted_image_bytes"), False),
        (("continuation", "rerendering_allowed"), 0),
        (("continuation", "old_runtime_renewed"), True),
        (("continuation", "prepared_root"), ".cache/new-copy"),
        (("continuation", "original_seals"), {}),
        (("eligibility", "training_allowed"), True),
    ],
)
def test_continuation_rejects_changed_scientific_scope_and_weak_types(path, value):
    protocol, original = continuation_protocol()
    target = protocol
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        t.validate_continuation(protocol, original)


def test_fresh_grant_interval_does_not_reclaim_or_renew_old_runtime():
    protocol, _ = continuation_protocol()
    grant = continuation_grant(protocol)
    assert t.continuation_deadline(grant, protocol, 1100, "MSI") == 15400
    grant["task"]["claim"]["expires_at"] = 20000
    assert t.continuation_deadline(grant, protocol, 12000, "MSI") == 15400
    with pytest.raises(ValueError, match="runtime expired"):
        t.continuation_deadline(grant, protocol, 15400, "MSI")


@pytest.mark.parametrize(
    "path,value",
    [
        (("task", "epoch"), True),
        (("task", "status"), "review"),
        (("task", "claim", "epoch"), True),
        (("task", "claim", "granted_at"), True),
        (("task", "claim", "expires_at"), 1050),
        (("task", "claim", "host_id"), "Mac"),
        (("task", "human_approval", "spec_hash"), "0" * 64),
        (("receipt", "status"), "pending"),
        (("receipt", "task_id"), "240"),
        (("receipt", "epoch"), True),
        (("receipt", "claim", "epoch"), True),
    ],
)
def test_continuation_requires_current_committed_owner_authorization(path, value):
    protocol, _ = continuation_protocol()
    grant = continuation_grant(protocol)
    target = grant
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        t.continuation_deadline(grant, protocol, 1100, "MSI")


def test_all_original_pngs_are_verified_including_unsampled_and_unavailable(tmp_path):
    source, original = packet(tmp_path)
    source["frames"][0]["image"] = None
    assert t.verify_original_images(source, original) == {
        "native_frames": 9,
        "original_pngs_verified": 8,
    }
    path = original / source["frames"][1]["image"]["path"]
    path.write_bytes(b"changed unsampled original")
    with pytest.raises(ValueError, match="Original PNG changed"):
        t.verify_original_images(source, original)


def test_continuation_uses_original_gallery_without_creating_a_copy(tmp_path):
    protocol, _ = continuation_protocol()
    cli = script()
    directory = cli.gallery_directory(
        tmp_path, tmp_path / "new", "go2uajSiBnE", protocol
    )
    assert (
        directory == tmp_path / ".cache/rally240-source-only-v1/galleries/go2uajSiBnE"
    )
    assert not directory.exists() and not (tmp_path / "new").exists()
    with pytest.raises(ValueError, match="Unknown source"):
        cli.gallery_directory(tmp_path, tmp_path / "new", "another-source", protocol)


def test_context_cannot_switch_back_to_original_task_or_change_frozen_limits():
    protocol, original = continuation_protocol()
    cli = script()
    context = {"task": 242, "protocol_sha256": cli.digest(ROOT / cli.CONTINUATION)}
    cli.context_protocol(context, protocol)
    with pytest.raises(ValueError, match="binding"):
        cli.context_protocol(context, original)
    protocol["limits"]["new_image_bytes"] += 1
    with pytest.raises(ValueError, match="binding"):
        cli.context_protocol(context, protocol)


def test_context_binding_preserves_clean_process_for_frozen_metadata_import(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib.util,sys; from pathlib import Path; "
            "root=Path(sys.argv[1]); "
            "spec=importlib.util.spec_from_file_location('clean_context',root/'scripts/pilot_rally_temporal_context.py'); "
            "cli=importlib.util.module_from_spec(spec); spec.loader.exec_module(cli); "
            "protocol=cli.read(root/cli.CONTINUATION); "
            "cli.context_protocol({'task':242,'protocol_sha256':cli.digest(root/cli.CONTINUATION)},protocol); "
            "assert not any(n=='badminton' or n.startswith('badminton.') for n in sys.modules); "
            "cli.metadata_gate=lambda *args: cli.require(not any(n=='badminton' or n.startswith('badminton.') for n in sys.modules),'Clean frozen imports required') or {}; "
            "cli.main(['gate','--continuation','--root',sys.argv[2],'--output',str(Path(sys.argv[2])/'.cache/generated')])",
            str(ROOT),
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("position", range(10))
def test_reuse_rejects_every_changed_original_receipt_before_parsing(
    tmp_path, monkeypatch, position
):
    protocol, _ = continuation_protocol()
    cli = script()
    seals = protocol["continuation"]["original_seals"]
    paths = []
    for name in seals:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"generated sealed process metadata")
        seals[name] = cli.digest(path)
        paths.append(path)
    paths[position].write_bytes(b"corrupted preserved evidence")
    original_read = cli.read

    def public_protocol_only(path):
        assert Path(path) == ROOT / cli.PROTOCOL, (
            "Do not parse corrupt/private evidence"
        )
        return original_read(path)

    monkeypatch.setattr(cli, "read", public_protocol_only)
    with pytest.raises(ValueError, match="process/artifact seal"):
        cli.original_prepared(tmp_path, protocol)


def test_linked_task_root_is_rejected_without_following_target(tmp_path, monkeypatch):
    cli = script()
    (tmp_path / ".cache/worktrees").mkdir(parents=True)
    linked = tmp_path / ".cache/rally242-linked"
    linked.mkdir()
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p == linked or original(p))
    with pytest.raises(ValueError, match="Linked task root"):
        cli.task_bytes(tmp_path, 242)


def test_nested_links_are_counted_as_metadata_without_following_them(tmp_path):
    cli = script()
    (tmp_path / ".cache/worktrees").mkdir(parents=True)
    folder = tmp_path / ".cache/rally242-generated"
    folder.mkdir()
    target = tmp_path / "outside-generated-task"
    target.mkdir()
    (target / "large").write_bytes(b"x" * 10000)
    link = folder / "nested"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Filesystem does not permit generated directory symlinks")
    assert cli.task_bytes(tmp_path, 242) == link.lstat().st_size


def test_authorized_payload_budget_rejects_new_launch_and_preserves_reservations(
    tmp_path, monkeypatch
):
    cli = script()
    source, _ = packet(tmp_path)
    manifest = lightweight_manifest(source)
    protocol, _ = continuation_protocol()
    output = tmp_path / "output"
    previous = output / "sessions/independent_b/generated"
    previous.mkdir(parents=True)
    cli.write(previous / "payload-reservation.json", {"image_bytes": 34040436})

    def forbidden_launch(*args, **kwargs):
        pytest.fail("Budget exhaustion must not launch any assessor")

    monkeypatch.setattr(cli.subprocess, "Popen", forbidden_launch)
    with pytest.raises(ValueError, match="payload budget exhausted"):
        cli.execute_session(
            output,
            tmp_path,
            manifest,
            "independent_a",
            {"task": 242, "deadline": time.time() + 120},
            protocol,
        )
    assert cli.read(previous / "payload-reservation.json") == {"image_bytes": 34040436}
    assert not (
        output / "sessions/independent_a/generated/payload-reservation.json"
    ).exists()


@pytest.mark.parametrize("tamper", [None, "packet", "original", "gallery", "producer"])
def test_generated_original_prefix_reuse_preserves_bytes_and_rejects_changes(
    tmp_path, monkeypatch, tamper
):
    cli = script()
    protocol, original = continuation_protocol()
    continuation = protocol["continuation"]
    old = tmp_path / continuation["prepared_root"]
    producer = tmp_path / continuation["producer_checkout"]
    receipts = tmp_path / continuation["native_receipts"]
    native = tmp_path / protocol["native_root"]
    for directory in (old, producer, receipts, native):
        directory.mkdir(parents=True)
    entries, candidates = [], {}
    for position, source in enumerate(protocol["sources"]):
        source_root = tmp_path / str(position)
        source_root.mkdir()
        p, images = packet(source_root)
        p["source_id"] = source["source_id"]
        for row in p["frames"]:
            name = source["source_id"] + "-" + row["image"]["path"]
            target = native / name
            target.write_bytes((images / row["image"]["path"]).read_bytes())
            row["image"]["path"] = name
            candidates["original"] = target
        packet_path = native / (source["source_id"] + ".packet.json")
        cli.write(packet_path, p)
        source.update(
            native_frame_count=len(p["frames"]),
            source_sha256=p["source_sha256"],
            clock_sha256=p["clock_sha256"],
            packet_sha256=cli.digest(packet_path),
        )
        gallery = old / "galleries" / source["source_id"]
        gallery.parent.mkdir(exist_ok=True)
        manifest = t.render_gallery(p, native, gallery)
        entries.append(
            {
                "source_id": source["source_id"],
                "manifest_sha256": cli.digest(gallery / "gallery.json"),
                "payload": t.payload_cost(manifest),
            }
        )
        continuation["manifests"][source["source_id"]] = entries[-1]["manifest_sha256"]
        candidates["packet"] = packet_path
        candidates["gallery"] = gallery / manifest["sheets"][0]["path"]
    original["sources"] = copy.deepcopy(protocol["sources"])
    producer_protocol = producer / cli.PROTOCOL
    producer_protocol.parent.mkdir(parents=True)
    cli.write(producer_protocol, original)
    continuation["original_protocol_sha256"] = cli.digest(producer_protocol)
    candidates["producer"] = producer_protocol
    cli.write(
        old / "context.json",
        {
            "task": 240,
            "grant": {"task": {"claim": {"granted_at": 1000}}},
            "frozen_at": 1100,
            "deadline": 15400,
            "consumers": {
                "commit": "a" * 40,
                "files": {cli.PROTOCOL: cli.digest(producer_protocol)},
            },
        },
    )
    continuation["context_sha256"] = cli.digest(old / "context.json")
    cli.write(
        old / "pilot-plan.json",
        {
            "task": 240,
            "context_sha256": continuation["context_sha256"],
            "scientific_sessions": 6,
            "new_image_bytes": protocol["limits"]["new_image_bytes"],
            "galleries": entries,
        },
    )
    continuation["plan_sha256"] = cli.digest(old / "pilot-plan.json")
    lifetime = {"pid": 100, "creation_time": 1, "ppid": 99}
    cli.write(
        old / "metadata-gate.json",
        {"process": lifetime, "scientific_labels_read": False},
    )
    preparation = old / "preparation"
    preparation.mkdir()
    cli.write(
        preparation / "admission.json", {"process": lifetime, "job_id": "generated-job"}
    )
    cli.write(preparation / "terminal.json", {"generated": True})
    cli.write(receipts / "owner.json", {"pid": 99, "creation_time": 1})
    for name in ("stdout.log", "stderr.log"):
        (receipts / name).write_bytes(b"generated original log")
    cli.write(
        receipts / "finish.json",
        {
            "returncode": 0,
            "started_at": 1200,
            "ended_at": 1300,
            "stdout_sha256": cli.digest(receipts / "stdout.log"),
            "stderr_sha256": cli.digest(receipts / "stderr.log"),
            "observed_lifetimes": [lifetime],
            "launched_pid": 100,
        },
    )
    cli.write(receipts / "audit.json", {"generated": True})
    for name in continuation["original_seals"]:
        continuation["original_seals"][name] = cli.digest(tmp_path / name)
    actual_read = cli.read
    monkeypatch.setattr(
        cli,
        "read",
        lambda p: original if Path(p) == ROOT / cli.PROTOCOL else actual_read(p),
    )
    monkeypatch.setattr(
        cli.subprocess,
        "check_output",
        lambda command, **_: "a" * 40 if command[1] == "rev-parse" else "",
    )
    observed = []
    monkeypatch.setattr(cli, "absent", observed.append)
    monkeypatch.setattr(
        cli,
        "verify_stage",
        lambda *_: {
            "pilot_plan_sha256": continuation["plan_sha256"],
            "metadata_gate_sha256": cli.digest(old / "metadata-gate.json"),
        },
    )
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    if tamper:
        candidates[tamper].write_bytes(b"changed original evidence")
        with pytest.raises(ValueError):
            cli.original_prepared(tmp_path, protocol)
    else:
        result = cli.original_prepared(tmp_path, protocol)
        assert result["galleries"] == entries
        assert result["rerendered_images"] == 0
        assert result["scientific_labels_read"] is False
        assert sum(r["original_pngs_verified"] for r in result["original_images"]) == 18
        assert len(observed) == 3
        assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("failure_at", [0, 1, 4])
def test_assessment_stops_dispatch_on_first_failed_session(
    tmp_path, monkeypatch, failure_at
):
    cli = script()
    protocol, _ = continuation_protocol()
    output = tmp_path / "output"
    output.mkdir()
    cli.write(output / "context.json", {"task": 242})
    entries = []
    for source in protocol["sources"]:
        gallery = cli.gallery_directory(tmp_path, output, source["source_id"], protocol)
        gallery.mkdir(parents=True)
        cli.write(gallery / "gallery.json", {"source_id": source["source_id"]})
        native = tmp_path / protocol["native_root"]
        native.mkdir(parents=True, exist_ok=True)
        cli.write(native / (source["source_id"] + ".packet.json"), {})
        entries.append(
            {
                "source_id": source["source_id"],
                "manifest_sha256": cli.digest(gallery / "gallery.json"),
            }
        )
    cli.write(
        output / "pilot-plan.json",
        {
            "task": 242,
            "context_sha256": cli.digest(output / "context.json"),
            "galleries": entries,
        },
    )
    cli.write(
        output / "stamp.json",
        {
            "user": {"login": "Ken0u"},
            "html_url": "https://github.com/Ken0u/badminton-match-analyzer/issues/242#issuecomment-generated",
            "created_at": "2026-01-01T00:00:00Z",
            "body": cli.digest(output / "pilot-plan.json"),
        },
    )
    monkeypatch.setattr(cli, "current", lambda *_: {"task": 242, "frozen_at": 0})
    monkeypatch.setattr(cli, "context_protocol", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "verify_stage",
        lambda *_: {"pilot_plan_sha256": cli.digest(output / "pilot-plan.json")},
    )
    monkeypatch.setattr(
        cli,
        "admitted",
        lambda root, output, stage, context, calculate: calculate(lambda _: None),
    )
    monkeypatch.setattr(cli, "budget", lambda *_: 0)
    monkeypatch.setattr(t, "verify_gallery", lambda *_: None)
    dispatched = []

    def session(output, gallery, manifest, lane, context, protocol):
        dispatched.append((lane, manifest["source_id"]))
        if len(dispatched) == failure_at + 1:
            raise ValueError("Original attempt failed")
        return {"generated": len(dispatched)}

    monkeypatch.setattr(cli, "execute_session", session)
    with pytest.raises(ValueError, match="Original attempt failed"):
        cli.assess(tmp_path, output, None, output / "stamp.json", protocol)
    assert len(dispatched) == failure_at + 1
    assert cli.read(output / "STOP.json")["sessions_completed"] == failure_at
    assert cli.read(output / "STOP.json")["replacement_permitted"] is False
    assert not (output / "session-index.json").exists()


def script():
    spec = importlib.util.spec_from_file_location(
        "generated_temporal_cli", ROOT / "scripts/pilot_rally_temporal_context.py"
    )
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def packet(tmp_path, times=None, count=9, rotation=0):
    times = times or [Fraction(n, 4) for n in range(count)]
    c = clock(len(times), times=times, rotation=rotation)
    original = tmp_path / "originals"
    original.mkdir()
    rows = []
    for row in c["frames"]:
        path = original / f"{row['frame']:09d}.png"
        Image.new("RGB", row["display_size"], "red").save(path)
        rows.append(
            {
                **row,
                "image": {
                    "path": path.name,
                    "sha256": file_hash(path),
                    "bytes": path.stat().st_size,
                },
            }
        )
    return {
        "source_id": "generated",
        "source_sha256": c["source_sha256"],
        "clock_sha256": t.fingerprint(c),
        "frames": rows,
        "eligibility": dict(t.ELIGIBILITY),
    }, original


def example(manifest, lane="independent_a"):
    document = {
        "source_id": manifest["plan"]["source_id"],
        "lane": lane,
        "session_id": "generated-" + lane,
        "gallery_sha256": t.fingerprint(manifest),
        "evidence_kind": "derived_sparse_temporal_context",
        "exact_contact_evidence": False,
        "eligibility": dict(t.ELIGIBILITY),
        "inspected_sheets": [
            {"path": s["path"], "sha256": s["sha256"]} for s in manifest["sheets"]
        ],
        "frame_states": [
            {
                "frame": s["frame"],
                "scene": "unknown",
                "play_state": "unknown",
                "camera_view": "unknown",
                "actor_ids": [],
                "reason": "Generated unavailable/uncertain context",
            }
            for s in manifest["plan"]["samples"]
        ],
        "actors": [],
        "transitions": [],
        "limitations": "Sparse generated thumbnails do not establish contacts or complete rallies",
    }
    document["transitions"] = [
        {
            "from_frame": a["frame"],
            "to_frame": b["frame"],
            "camera_continuity": "unknown",
            "actor_continuity": "unresolved",
            "reason": "Unseen native interval",
        }
        for a, b in zip(document["frame_states"], document["frame_states"][1:])
    ]
    return document, receipt(document, manifest)


def receipt(document, manifest):
    return {
        "exit_code": 0,
        "exited": True,
        "forbidden_items": [],
        "session_id": document["session_id"],
        "thread_id": "generated-thread-" + document["lane"],
        "pid": 12345,
        "creation_time": 1.0,
        "gallery_sha256": t.fingerprint(manifest),
        "document_sha256": t.fingerprint(document),
    }


def lightweight_manifest(p):
    return {
        "schema_version": 1,
        "plan": t.sample_plan(p),
        "sheets": [
            {
                "path": "sheet-000.png",
                "sha256": "b" * 64,
                "bytes": 100,
                "size": list(t.SHEET),
                "frames": [s["frame"] for s in t.sample_plan(p)["samples"]],
            }
        ],
    }


def test_vfr_pts_grid_preserves_endpoint_and_duplicate_memberships(tmp_path):
    p, _ = packet(
        tmp_path,
        times=[
            Fraction(100),
            Fraction(1001, 10),
            Fraction(1009, 10),
            Fraction(1014, 10),
            Fraction(1018, 10),
            Fraction(102),
        ],
    )
    plan = t.sample_plan(p)
    assert [s["frame"] for s in plan["samples"]] == [0, 3, 5]
    assert plan["memberships"] == [
        {"reason": "first", "frame": 0},
        {"reason": "grid", "offset_seconds": 0, "frame": 0},
        {"reason": "grid", "offset_seconds": 1, "frame": 3},
        {"reason": "grid", "offset_seconds": 2, "frame": 5},
        {"reason": "last", "frame": 5},
    ]
    assert (
        plan["native_frame_denominator"] == 6 and plan["unsampled_native_frames"] == 3
    )
    assert plan["exact_contact_evidence"] is False


def test_unavailable_grid_sample_is_retained_without_replacement(tmp_path):
    p, _ = packet(tmp_path)
    p["frames"][4]["image"] = None
    plan = t.sample_plan(p)
    assert [s["frame"] for s in plan["samples"]] == [0, 4, 8]
    assert plan["samples"][1]["available"] is False
    document, r = example(lightweight_manifest(p))
    t.validate_assessment(document, lightweight_manifest(p), r, "independent_a")
    document["frame_states"][1]["scene"] = "live"
    with pytest.raises(ValueError, match="Unavailable"):
        t.validate_assessment(
            document,
            lightweight_manifest(p),
            receipt(document, lightweight_manifest(p)),
            "independent_a",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("frame", True),
        ("pts", True),
        ("rotation", True),
        ("time_s", float("nan")),
        ("time_s", True),
        ("time_base", "0"),
        ("display_size", [24, 32]),
    ],
)
def test_native_integer_time_and_orientation_aliases_rejected(tmp_path, field, value):
    p, _ = packet(tmp_path)
    p["frames"][0][field] = value
    with pytest.raises(ValueError):
        t.sample_plan(p)


def test_duplicate_pts_uses_first_native_and_reversal_or_gaps_fail(tmp_path):
    p, _ = packet(tmp_path, times=[Fraction(0), Fraction(0), Fraction(1), Fraction(2)])
    assert [s["frame"] for s in t.sample_plan(p)["samples"]] == [0, 2, 3]
    broken = copy.deepcopy(p)
    broken["frames"][1]["frame"] = 7
    with pytest.raises(ValueError, match="dense"):
        t.sample_plan(broken)
    p["frames"][2].update(pts=-1, time_s=-1)
    with pytest.raises(ValueError, match="reversal"):
        t.sample_plan(p)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rendered_gallery_is_labelled_letterboxed_and_preserves_originals(
    tmp_path, rotation
):
    p, original = packet(tmp_path, rotation=rotation)
    before = {n.name: file_hash(n) for n in original.iterdir()}
    output = tmp_path / "gallery"
    manifest = t.render_gallery(p, original, output)
    assert t.verify_gallery(manifest, p, output) == manifest
    assert before == {n.name: file_hash(n) for n in original.iterdir()}
    with Image.open(output / "sheet-000.png") as image:
        assert image.size == t.SHEET
        assert image.getpixel((320, 180)) == (255, 0, 0)
        assert image.getpixel((1, 180)) == (0, 0, 0)
        assert image.getpixel((2500, 1400)) == (0, 0, 0)
        assert image.crop((0, 360, 640, 384)).getbbox() is not None
    with pytest.raises(ValueError, match="Exclusive"):
        t.render_gallery(p, original, output)


def test_sheet_order_and_unavailable_placeholders(tmp_path):
    p, original = packet(tmp_path, count=81)
    p["frames"][4]["image"] = None
    manifest = t.render_gallery(p, original, tmp_path / "gallery")
    assert len(manifest["sheets"]) == 2
    assert manifest["sheets"][0]["frames"] == list(range(0, 64, 4))
    assert manifest["sheets"][1]["frames"] == [64, 68, 72, 76, 80]
    assert manifest["plan"]["unsampled_native_frames"] == 60


@pytest.mark.parametrize(
    "tamper", ["original", "derived", "mapping", "geometry", "packet"]
)
def test_hash_and_native_mapping_tampering_fails(tmp_path, tamper):
    p, original = packet(tmp_path)
    output = tmp_path / "gallery"
    if tamper == "original":
        (original / p["frames"][0]["image"]["path"]).write_bytes(b"changed")
        with pytest.raises(ValueError, match="Original"):
            t.render_gallery(p, original, output)
        return
    manifest = t.render_gallery(p, original, output)
    if tamper == "derived":
        (output / "sheet-000.png").write_bytes(b"changed")
    elif tamper == "mapping":
        manifest["sheets"][0]["frames"].reverse()
    elif tamper == "geometry":
        manifest["sheets"][0]["size"] = [1, 1]
    else:
        p["frames"][0]["image"]["sha256"] = "f" * 64
    with pytest.raises(ValueError):
        t.verify_gallery(manifest, p, output)


@pytest.mark.parametrize(
    "name", ["../outside.png", "/outside.png", "C:/outside.png", "a\\b.png", ""]
)
def test_gallery_artifacts_cannot_escape_root(tmp_path, name):
    with pytest.raises(ValueError):
        t.safe_file(tmp_path, name)


@pytest.mark.parametrize(
    "sizes,context",
    [
        ([9 * 1024**2 + 1], 0),
        ([1] * 21, 0),
        ([False], 0),
        ([100], 2 * 1024**2),
        ([100], True),
    ],
)
def test_payload_and_encoded_context_limits_are_fail_closed(sizes, context):
    with pytest.raises(ValueError):
        t.payload_cost(
            {"sheets": [{"bytes": size} for size in sizes]}, context_bytes=context
        )


def test_base64_is_charged_per_image_and_context_reserved():
    assert t.payload_cost({"sheets": [{"bytes": 1}, {"bytes": 2}]}) == {
        "image_bytes": 3,
        "base64_bytes": 8,
        "images": 2,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("exit_code", False),
        ("exit_code", 0.0),
        ("exit_code", 1),
        ("exited", 1),
        ("thread_id", ""),
        ("session_id", "wrong"),
        ("pid", True),
        ("creation_time", float("nan")),
        ("forbidden_items", ["command_execution"]),
        ("document_sha256", "f" * 64),
    ],
)
def test_receipt_must_bind_actual_success_and_genuine_identifiers(
    tmp_path, field, value
):
    p, _ = packet(tmp_path)
    manifest = lightweight_manifest(p)
    document, r = example(manifest)
    r[field] = value
    with pytest.raises(ValueError):
        t.validate_assessment(document, manifest, r, "independent_a")


@pytest.mark.parametrize(
    "change",
    [
        "event",
        "eligibility",
        "frame_bool",
        "missing_frame",
        "missing_transition",
        "wrong_lane",
        "wrong_source",
        "wrong_sheet",
        "exact_contact",
    ],
)
def test_sparse_assessment_cannot_gain_contacts_or_drop_denominators(tmp_path, change):
    p, _ = packet(tmp_path)
    manifest = lightweight_manifest(p)
    document, _ = example(manifest)
    if change == "event":
        document["events"] = [{"kind": "serve"}]
    elif change == "eligibility":
        document["eligibility"]["training_allowed"] = 0
    elif change == "frame_bool":
        document["frame_states"][0]["frame"] = False
    elif change == "missing_frame":
        document["frame_states"].pop()
    elif change == "missing_transition":
        document["transitions"].pop()
    elif change == "wrong_lane":
        document["lane"] = "independent_b"
    elif change == "wrong_source":
        document["source_id"] = "other"
    elif change == "wrong_sheet":
        document["inspected_sheets"] = []
    else:
        document["exact_contact_evidence"] = True
    with pytest.raises(ValueError):
        t.validate_assessment(
            document, manifest, receipt(document, manifest), "independent_a"
        )


def test_local_actor_evidence_required_for_every_supported_transition(tmp_path):
    p, _ = packet(tmp_path)
    manifest = lightweight_manifest(p)
    document, _ = example(manifest)
    selected = [s["frame"] for s in document["frame_states"]]
    document["actors"] = [
        {
            "actor_id": "a",
            "description": "generated distinct clothing",
            "identity_supported": True,
            "evidence_frames": selected,
        }
    ]
    for row in document["frame_states"]:
        row.update(camera_view="view1", actor_ids=["a"])
    for row in document["transitions"]:
        row.update(camera_continuity="same", actor_continuity="supported")
    t.validate_assessment(
        document, manifest, receipt(document, manifest), "independent_a"
    )
    document["actors"][0]["identity_supported"] = False
    with pytest.raises(ValueError, match="Persistent identity"):
        t.validate_assessment(
            document, manifest, receipt(document, manifest), "independent_a"
        )


def test_aggregates_keep_unknown_agreement_and_unsampled_frames_separate(tmp_path):
    p, _ = packet(tmp_path)
    manifest = lightweight_manifest(p)
    documents = {lane: example(manifest, lane)[0] for lane in t.LANES}
    documents["independent_b"]["frame_states"][0]["scene"] = "live"
    result = t.summarize(manifest, documents)
    assert result["native_frame_denominator"] == 9
    assert result["sampled_frames"] == 3 and result["unsampled_native_frames"] == 6
    assert result["agreement"]["independent_a:independent_b"] == {
        "scene_equal_including_unknown": 2,
        "scene_known_equal": 0,
        "scene_unknown_in_either": 3,
    }
    assert not result["complete_reference"] and result["eligibility"] == t.ELIGIBILITY
    assert "description" not in json.dumps(result) and "session_id" not in json.dumps(
        result
    )
    documents.pop("adjudication")
    with pytest.raises(ValueError, match="three"):
        t.summarize(manifest, documents)


def test_schema_cannot_request_exact_events_and_all_fields_are_required():
    value = script().schema()
    assert value["additionalProperties"] is False
    assert set(value["required"]) == set(value["properties"])
    assert "events" not in value["properties"]
    assert "family" not in json.dumps(value)


def test_bounded_pipe_drain_hashes_all_bytes_and_retains_only_limit(tmp_path):
    record = {}
    script().bounded_drain(io.BytesIO(b"0123456789"), tmp_path / "log", record, limit=4)
    assert (tmp_path / "log").read_bytes() == b"0123"
    assert record == {
        "bytes": 10,
        "sha256": __import__("hashlib").sha256(b"0123456789").hexdigest(),
        "truncated": True,
    }


def test_prompt_uses_only_whole_source_gallery_and_no_other_lane_labels(tmp_path):
    p, _ = packet(tmp_path)
    manifest = lightweight_manifest(p)
    message = script().prompt(manifest, "independent_a", "generated-session")
    assert "generated-session" in message and "other assessor" in message
    assert "DERIVED SPARSE" in message and "cannot establish" in message
    assert "No tools" in message and "no labels" not in message


def test_json_reader_rejects_duplicate_keys_and_nonfinite_values(tmp_path):
    path = tmp_path / "bad.json"
    for raw in ('{"a":1,"a":2}', '{"a":NaN}'):
        path.write_text(raw, encoding="utf-8")
        with pytest.raises(ValueError):
            script().read(path)


@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("task", [240, 242])
def test_actual_generated_store_stage_completes_or_preserves_failure(
    tmp_path, fail, task
):
    root = tmp_path / "generated-root"
    data = root / "data/processed"
    data.mkdir(parents=True)
    output = root / ".cache/pilot"
    output.mkdir(parents=True)
    (output / "context.json").write_bytes(
        encoded({"generated": True, "deadline": time.time() + 120})
    )
    code = """import importlib.util,json,subprocess,sys,time
from pathlib import Path
root,source,output,fail=Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),sys.argv[4]=='True'
sys.path.insert(0,str(source.parents[1]/'backend'))
from badminton.storage import Store
Store(root/'data/processed')
spec=importlib.util.spec_from_file_location('generated',source)
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
cli.write(output/'original-owner.json',cli.identity(cli.psutil.Process()))
def calculate(progress):
    progress(.5)
    if fail: raise RuntimeError('generated preserved failure')
    nested='import importlib.util,sys;from pathlib import Path;s=importlib.util.spec_from_file_location("gate",sys.argv[1]);c=importlib.util.module_from_spec(s);s.loader.exec_module(c);c.live_parent(Path(sys.argv[2]),Path(sys.argv[3]))'
    result=subprocess.run([sys.executable,'-c',nested,str(source),str(root),str(output)],capture_output=True)
    if result.returncode: raise RuntimeError(result.stderr.decode())
    return {'generated':True}
cli.admitted(root,output,'preparation',{'task':int(sys.argv[5]),'deadline':time.time()+30},calculate)
"""
    env = os.environ.copy()
    for key in script().CREDENTIALS:
        env.pop(key, None)
    env.update(
        BADMINTON_ROOT=str(root),
        BADMINTON_DATA_DIR=str(data),
        BADMINTON_WEIGHTS_DIR=str(root / "models/weights"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(root),
            str(ROOT / "scripts/pilot_rally_temporal_context.py"),
            str(output),
            str(fail),
            str(task),
        ],
        env=env,
        capture_output=True,
        timeout=30,
    )
    cli = script()
    cli.absent(cli.read(output / "original-owner.json"))
    if fail:
        assert result.returncode != 0
        assert (
            cli.read(output / "preparation/failure.json")["implicit_retry_permitted"]
            is False
        )
        assert not (output / "preparation/terminal.json").exists()
    else:
        assert result.returncode == 0, result.stderr.decode()
        assert cli.verify_stage(root, output, "preparation") == {"generated": True}
        # The census checker requires a freshly absent original lifetime and
        # actual completed Store record, even when durable hashes still match.
        archived = root / ".cache/rally238-diagnostics-v1"
        native = root / ".cache/rally238-native-v1"
        archived.mkdir()
        native.mkdir()
        admission = cli.read(output / "preparation/admission.json")
        terminal = cli.read(output / "preparation/terminal.json")
        for name in ("aggregate.json", "ledger.json"):
            cli.write(archived / name, {"generated": True})
        terminal["artifacts"] = {
            name: cli.digest(archived / name)
            for name in ("aggregate.json", "ledger.json")
        }
        cli.write(archived / "admission.json", admission)
        cli.write(archived / "terminal.json", terminal)
        cli.write(
            native / "audit-v2.json",
            {
                "terminal_sha256": cli.digest(archived / "terminal.json"),
                "context_sha256": admission["context_sha256"],
            },
        )
        cli.write(native / "owner.json", cli.read(output / "original-owner.json"))
        for name in ("stdout.log", "stderr.log"):
            (native / name).write_bytes(b"")
        cli.write(
            native / "finish.json",
            {
                "returncode": 0,
                "observed_lifetimes": [admission["process"]],
                "stdout_sha256": cli.digest(native / "stdout.log"),
                "stderr_sha256": cli.digest(native / "stderr.log"),
            },
        )
        cli.archived_census(root)
        (archived / "ledger.json").write_bytes(b"changed")
        with pytest.raises(ValueError, match="artifact"):
            cli.archived_census(root)
        with pytest.raises(ValueError, match="already attempted"):
            cli.admitted(
                root,
                output,
                "preparation",
                {"deadline": time.time() + 30},
                lambda _: {},
            )


def test_absence_check_rejects_own_live_lifetime():
    cli = script()
    with pytest.raises(ValueError, match="still alive"):
        cli.absent(cli.identity(cli.psutil.Process()))


@pytest.mark.parametrize(
    "mode", ["success", "tool", "failed", "missing", "bad_event", "bad_final"]
)
def test_actual_generated_assessor_process_preserves_original_and_fails_closed(
    tmp_path, monkeypatch, mode
):
    """Launch Python fixture processes, never the external scientific CLI."""
    cli = script()
    p, original = packet(tmp_path)
    gallery = tmp_path / "gallery"
    manifest = t.render_gallery(p, original, gallery)
    document, _ = example(manifest)
    fixture = tmp_path / "generated-assessor.py"
    fixture.write_text(
        "import json,re,sys,uuid\n"
        "from pathlib import Path\n"
        "message=sys.stdin.read()\n"
        f"document=json.loads({json.dumps(json.dumps(document))})\n"
        "document['session_id']=re.search(r'session_id=([^,\\s]+)',message).group(1)\n"
        "print(json.dumps({'type':'thread.started','thread_id':uuid.uuid4().hex}),flush=True)\n"
        f"mode={mode!r}\n"
        "if mode=='bad_event': print('NOT-JSON',flush=True)\n"
        "if mode=='tool': print(json.dumps({'type':'item.completed','item':{'type':'command_execution'}}),flush=True)\n"
        "if mode!='missing': Path(sys.argv[1]).write_text('{' if mode=='bad_final' else json.dumps(document),encoding='utf-8')\n"
        "print(json.dumps({'type':'turn.completed'}),flush=True)\n"
        "raise SystemExit(1 if mode=='failed' else 0)\n",
        encoding="utf-8",
        newline="\n",
    )
    native_popen = subprocess.Popen

    def generated_popen(command, **kwargs):
        output = command[command.index("--output-last-message") + 1]
        return native_popen([sys.executable, str(fixture), output], **kwargs)

    monkeypatch.setattr(cli.subprocess, "Popen", generated_popen)
    context = {
        "deadline": time.time() + 300,
        "consumers": {
            "cli": {"path": sys.executable, "sha256": file_hash(sys.executable)}
        },
    }
    output = tmp_path / "pilot"
    output.mkdir()
    if mode == "success":
        entry = cli.execute_session(
            output, gallery, manifest, "independent_a", context, {}
        )
        assert entry["source_id"] == "generated"
        assert entry["thread_id"] and entry["session_id"].startswith(
            "codex-cli:temporal240"
        )
    else:
        with pytest.raises(ValueError):
            cli.execute_session(output, gallery, manifest, "independent_a", context, {})
    folder = output / "sessions/independent_a/generated"
    finish = cli.read(folder / "finish.json")
    cli.absent(finish)
    assert (folder / "payload-reservation.json").exists()
    assert finish["stdout"]["truncated"] is False
    assert (folder / "original-final.json").exists() == (mode != "missing")
    if mode == "tool":
        assert finish["forbidden_items"] == ["command_execution"]
    elif mode == "failed":
        assert finish["exit_code"] == 1
    elif mode in ("bad_event", "bad_final"):
        assert finish["parse_errors"]
        assert finish["exit_code"] == 0 and finish["exited"] is True
