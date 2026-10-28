"""Generated sources only: no original video, semantic label or model access."""

import copy
import importlib.util
import io
import itertools
import json
import os
import platform
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import av
import numpy as np
import psutil
import pytest
from badminton import shuttle_scene_preparation as scene
from badminton.storage import Store
from media_fixtures import write_rotated_video
from PIL import Image

CHECKOUT = Path(__file__).resolve().parents[1]
SCRIPT = CHECKOUT / "scripts/prepare_shuttle_scene_review.py"


def cli_module():
    spec = importlib.util.spec_from_file_location(
        "scene_preparation_cli_generated", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def protocol():
    return scene.decode(
        (
            CHECKOUT / "data/manifests/shuttle_scene_preparation_protocol_v1.json"
        ).read_bytes()
    )


def generated_metadata():
    value = protocol()
    views = [
        {
            "id": "PRIVATE_VIEW_A",
            "video_id": "PRIVATE_A",
            "start_frame": 0,
            "end_frame": 35,
            "case_ids": ["PRIVATE_A0", "PRIVATE_A34"],
        },
        {
            "id": "PRIVATE_VIEW_B",
            "video_id": "PRIVATE_B",
            "start_frame": 0,
            "end_frame": 18,
            "case_ids": ["PRIVATE_B0", "PRIVATE_B17"],
        },
    ]
    cases = [
        {"id": name, "video_id": view["video_id"], "frame": frame}
        for view in views
        for name, frame in zip(view["case_ids"], (0, view["end_frame"] - 1))
    ]
    value["denominators"] = {
        "views": 2,
        "cases": 4,
        "frame_occurrences": 53,
        "sheets": 5,
    }
    for source, view in zip(value["sources"], views):
        source.update(
            id=view["video_id"],
            frame_count=view["end_frame"],
            rotation=0,
            display_size=[64, 32],
        )
    diagnostics = {"eligibility": dict(scene.ELIGIBILITY), "methods": {}}
    for method in ("control", "decoder", "convolution"):
        diagnostics["methods"][method] = {
            "views": [
                {
                    "view": copy.deepcopy(view),
                    "segments": [
                        {
                            "start_frame": a,
                            "end_frame": b,
                            "eligible": False,
                            "flags": ["uncovered_live_context"],
                        }
                        for a, b in zip(starts, [*starts[1:], view["end_frame"]])
                    ],
                }
                for view, starts in zip(views, ([0, 8, 21], [0, 9]))
            ]
        }
    raw = {
        "schema_version": 1,
        "origin_diagnostics_sha256": scene.digest(scene.encode(diagnostics)),
        "views": views,
        "cases": cases,
    }
    for original in diagnostics["methods"].values():
        original["cases"] = [{"case": copy.deepcopy(case)} for case in cases]
    raw["origin_diagnostics_sha256"] = scene.digest(scene.encode(diagnostics))
    return value, raw, diagnostics


def generated_video(path, count):
    path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path), "w") as output:
        stream = output.add_stream("ffv1", rate=25)
        stream.width, stream.height, stream.pix_fmt = 64, 32, "bgr0"
        stream.time_base = Fraction(1, 1000)
        stream.codec_context.time_base = Fraction(1, 1000)
        pts = 900
        for index in range(count):
            pixels = np.zeros((32, 64, 3), dtype=np.uint8)
            pixels[:, :32] = [240, 10, index % 255]
            pixels[:, 32:] = [5, 20, 240]
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = pts, Fraction(1, 1000)
            pts += 40 if index % 3 else 80
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    return path


def generate_sources(tmp_path):
    value, raw, diagnostics = generated_metadata()
    paths = {
        s["artifact"]: generated_video(tmp_path / (s["id"] + ".mkv"), s["frame_count"])
        for s in value["sources"]
    }
    views, cases = scene.inventory(raw, diagnostics, value)
    return value, raw, diagnostics, views, cases, paths


def gallery_fixture(tmp_path):
    value, raw, diagnostics, views, cases, paths = generate_sources(tmp_path)
    images = {}
    manifest = scene.prepare_sources(
        value, views, paths, lambda name, data: images.__setitem__(name, data)
    )
    return value, raw, diagnostics, views, cases, paths, manifest, images


def test_every_native_occurrence_pts_orientation_partition_and_partial_cell_retained(
    tmp_path,
):
    value, _, _, views, _, paths, manifest, images = gallery_fixture(tmp_path)
    scene.validate_gallery_manifest(manifest, views, value)
    assert len(images) == 5
    assert (
        sum(len(s["members"]) for g in manifest["galleries"] for s in g["sheets"]) == 53
    )
    assert [s["empty_cells"] for s in manifest["galleries"][0]["sheets"]] == [0, 0, 13]
    rows = manifest["source_clocks"]["PRIVATE_A"]
    assert (
        rows[0]["pts"] == 900
        and len({b["pts"] - a["pts"] for a, b in itertools.pairwise(rows)}) == 2
    )
    members = [r for s in manifest["galleries"][0]["sheets"] for r in s["members"]]
    assert [r["frame"] for r in members if r["partition_begins"]] == [0, 8, 21]
    assert members[7]["partition"] == 0 and members[8]["partition"] == 1
    assert members[20]["partition"] == 1 and members[21]["partition"] == 2
    scene.audit_native_clocks(manifest, value, paths)
    for name, data in images.items():
        path = tmp_path / "output" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    assert scene.audit_images(manifest, tmp_path / "output") == sum(
        map(len, images.values())
    )
    image = np.asarray(Image.open(io.BytesIO(next(iter(images.values())))))
    assert np.all(np.abs(image[80, 80].astype(int) - [240, 10, 0]) < 8)
    assert np.all(np.abs(image[80, 240].astype(int) - [5, 20, 240]) < 8)


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
def test_actual_rotated_native_decode_preserves_pts_and_display_pixels(
    tmp_path, rotation
):
    path = write_rotated_video(tmp_path / "rotated.mp4", rotation)
    with av.open(str(path)) as container:
        originals = list(container.decode(container.streams.video[0]))
    decoded = list(scene.native_frames(path))
    assert len(decoded) == len(originals)
    for original, (clock, display) in zip(originals, decoded):
        assert clock["pts"] == original.pts and clock["time_base"] == str(
            original.time_base
        )
        assert clock["rotation"] == rotation
        assert clock["display_size"] == (
            [64, 128] if rotation in (90, 270) else [128, 64]
        )
        assert np.array_equal(
            display.to_ndarray(format="rgb24"),
            np.rot90(original.to_ndarray(format="rgb24"), rotation // 90),
        )


def test_thumbnail_contains_full_nonstandard_source_aspect():
    source = Image.new("RGB", (64, 64), "red")
    tile = scene.cell_image(SimpleNamespace(to_image=lambda: source))
    assert tile.size == scene.TILE
    pixels = np.asarray(tile)
    assert np.all(pixels[:, 0] == 0) and np.all(pixels[:, 319] == 0)
    assert pixels[90, 160, 0] == 255 and pixels[0, 160, 0] == 255


@pytest.mark.parametrize(
    "mutation",
    (
        "case_count",
        "view_member",
        "view_source",
        "method_inventory",
        "frame",
        "partition",
    ),
)
def test_changed_or_ambiguous_inventory_never_silently_shrinks_denominator(mutation):
    value, raw, diagnostics = generated_metadata()
    if mutation == "case_count":
        raw["cases"].pop()
    elif mutation == "view_member":
        raw["views"][0]["case_ids"].append("PRIVATE_A0")
    elif mutation == "view_source":
        raw["views"][0]["video_id"] = "OTHER"
    elif mutation == "method_inventory":
        diagnostics["methods"]["decoder"]["views"].reverse()
    elif mutation == "frame":
        raw["cases"][0]["frame"] = True
    else:
        diagnostics["methods"]["control"]["views"][0]["segments"][1]["start_frame"] += 1
    raw["origin_diagnostics_sha256"] = scene.digest(scene.encode(diagnostics))
    with pytest.raises((ValueError, KeyError)):
        scene.inventory(raw, diagnostics, value)


@pytest.mark.parametrize(
    "mutation", ("missing", "extra", "clock", "orientation", "partition", "partial")
)
def test_malformed_gallery_or_clock_is_rejected_before_accepting_coverage(
    tmp_path, mutation
):
    value, _, _, views, _, _, manifest, _ = gallery_fixture(tmp_path)
    sheet = manifest["galleries"][0]["sheets"][0]
    if mutation == "missing":
        sheet["members"].pop()
    elif mutation == "extra":
        sheet["members"].append(copy.deepcopy(sheet["members"][-1]))
    elif mutation == "clock":
        manifest["source_clocks"]["PRIVATE_A"][2]["pts"] = 0
    elif mutation == "orientation":
        manifest["source_clocks"]["PRIVATE_A"][2]["rotation"] = 90
    elif mutation == "partition":
        sheet["members"][8]["partition_begins"] = False
    else:
        sheet["empty_cells"] += 1
    with pytest.raises(ValueError):
        scene.validate_gallery_manifest(manifest, views, value)


@pytest.mark.parametrize("failure", ("missing", "extra", "dimension"))
def test_incomplete_decode_never_produces_complete_gallery(
    tmp_path, monkeypatch, failure
):
    value, _, _, views, _, paths = generate_sources(tmp_path)
    original = scene.native_frames

    def changed(path):
        rows = list(original(path))
        if failure == "missing":
            rows.pop()
        elif failure == "extra":
            clock, frame = rows[-1]
            rows.append(({**clock, "frame": len(rows)}, frame))
        else:
            rows[0][0]["display_size"][0] += 1
        yield from rows

    monkeypatch.setattr(scene, "native_frames", changed)
    with pytest.raises(ValueError):
        scene.prepare_sources(value, views, paths, lambda *_: None)


def packed_fixture(sizes, *, second_view=False):
    sheets = [
        {
            "path": f"view-000/sheet-{i:03d}.jpg",
            "sha256": "a" * 64,
            "bytes": n,
            "members": [{"frame": i}],
        }
        for i, n in enumerate(sizes)
    ]
    result = [{"view": {"index": 0}, "sheets": sheets}]
    if second_view:
        result.append(
            {
                "view": {"index": 1},
                "sheets": [
                    {
                        "path": "view-001/sheet-000.jpg",
                        "sha256": "b" * 64,
                        "bytes": 10,
                        "members": [{"frame": 0}],
                    }
                ],
            }
        )
    return result


def test_actual_bytes_and_overlap_are_counted_for_both_blind_passes():
    mb = 1024**2
    summary, plan = scene.pack_galleries(packed_fixture([3 * mb] * 3), max_images=2)
    assert (
        summary["sessions_per_pass"] == 2
        and summary["payload_bytes_per_pass"] == 12 * mb
    )
    assert (
        summary["two_pass_sessions"] == 4
        and summary["two_pass_payload_bytes"] == 24 * mb
    )
    assert summary["overlap_image_occurrences_per_pass"] == 1
    assert summary["adjudication_reserve"]["image_payload_bytes"] == 12 * mb
    assert plan["lanes"]["independent_a"] == plan["lanes"]["independent_b"]
    batches = plan["lanes"]["independent_a"]
    assert batches[0]["overlap_image"] is None
    assert batches[1]["overlap_image"] == batches[0]["images"][-1]["path"]
    assert summary["new_assessor_sessions"] == summary["new_image_transfer_bytes"] == 0


def test_packing_never_carries_overlap_between_original_views():
    _, plan = scene.pack_galleries(
        packed_fixture([10, 10, 10], second_view=True), max_images=2
    )
    batches = plan["lanes"]["independent_a"]
    assert batches[-1]["view_index"] == 1 and batches[-1]["overlap_image"] is None
    assert len(batches[-1]["images"]) == 1


@pytest.mark.parametrize(
    "sizes,max_images",
    (([scene.MAX_BYTES + 1], 20), ([scene.MAX_BYTES, 1], 20), ([1, 1], 1)),
)
def test_infeasible_images_or_overlap_preserve_complete_denominators(sizes, max_images):
    summary, plan = scene.pack_galleries(packed_fixture(sizes), max_images=max_images)
    assert summary["status"] == "unavailable" and summary["sheets_per_pass"] == len(
        sizes
    )
    assert summary["native_frame_occurrences_per_pass"] == len(sizes)
    assert (
        summary["sessions_per_pass"] is None
        and summary["payload_bytes_per_pass"] is None
    )
    assert all(not rows for rows in plan["lanes"].values()) and plan["unavailable"]


@pytest.mark.parametrize("raw", (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}'))
def test_strict_json_refuses_duplicate_nonfinite_and_overflow(raw):
    with pytest.raises(ValueError):
        scene.decode(raw)


@pytest.mark.parametrize(
    "name",
    ("../escape", "a/../escape", "/absolute", "a\\file", "weights:stream", "a//b"),
)
def test_unsafe_paths_are_refused(tmp_path, name):
    with pytest.raises(ValueError):
        scene.safe_path(tmp_path, name, must_exist=False)


def test_linked_root_or_parent_is_refused(tmp_path, monkeypatch):
    original = Path.lstat

    def linked(self, *args, **kwargs):
        info = original(self, *args, **kwargs)
        if self == tmp_path:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=1024)
        return info

    monkeypatch.setattr(Path, "lstat", linked)
    with pytest.raises(ValueError, match="Linked"):
        scene.safe_path(tmp_path, "new", must_exist=False)


def test_changed_derived_image_is_not_accepted_as_source_review_preparation(tmp_path):
    _, _, _, _, _, _, manifest, images = gallery_fixture(tmp_path)
    for name, data in images.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    target = tmp_path / next(iter(images))
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ValueError, match="bytes changed"):
        scene.audit_images(manifest, tmp_path)


def create_cli_fixture(tmp_path):
    value, raw, diagnostics, _, _, paths = generate_sources(tmp_path)
    value["helper_sha256"] = {
        name: scene.file_hash(CHECKOUT / name) for name in value["helper_sha256"]
    }
    bindings = {}
    for source in value["sources"]:
        path = paths[source["artifact"]]
        source["sha256"] = scene.file_hash(path)
        value["artifacts"][source["artifact"]] = source["sha256"]
        bindings[source["artifact"]] = path.relative_to(tmp_path).as_posix()
    for name, document in (
        ("familiar-scene-inventory", raw),
        ("context-audit-diagnostics", diagnostics),
        ("context-audit-protocol", {"metadata_only": True}),
    ):
        path = tmp_path / (name + ".json")
        path.write_bytes(scene.encode(document))
        value["artifacts"][name] = scene.file_hash(path)
        bindings[name] = path.name
    cache = tmp_path / ".cache"
    cache.mkdir()
    protocol_path = cache / "protocol.json"
    protocol_path.write_bytes(scene.encode(value))
    bindings_path = cache / "bindings.json"
    bindings_path.write_bytes(scene.encode(bindings))
    now = time.time()
    claim = {
        "epoch": 1,
        "actor": "generated",
        "host_id": platform.node(),
        "session_id": "generated",
        "spec_hash": value["spec_hash"],
        "granted_at": int(now) - 1,
        "expires_at": int(now) + 3600,
        "branch": "generated",
        "baseline_sha": "a" * 40,
    }
    task = {
        "status": "running",
        "epoch": 1,
        "spec_hash": value["spec_hash"],
        "claim": claim,
        "spec": {"artifacts": value["artifacts"]},
    }
    grant = {
        "task": task,
        "session_id": "generated",
        "deadline": claim["granted_at"] + 6 * 3600,
    }
    grant_path = cache / "grant.json"
    grant_path.write_bytes(scene.encode(grant))
    ownership_path = cache / "ownership.json"
    ownership_path.write_bytes(scene.encode({"at": now, "paused": False, "task": task}))
    subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True
    )
    Store(tmp_path / "data/processed")
    command = [sys.executable, "-B", str(SCRIPT)]
    arguments = [
        "--root",
        str(tmp_path),
        "--protocol",
        str(protocol_path),
        "--bindings",
        str(bindings_path),
        "--grant",
        str(grant_path),
        "--ownership",
        str(ownership_path),
        "--output",
        str(cache / "output"),
    ]
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("BADMINTON_") and k not in cli_module().CREDENTIALS
    }

    def run(stage, context=None):
        result = subprocess.run(
            command
            + [stage]
            + arguments
            + (["--context-sha256", context] if context else []),
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        return result

    return SimpleNamespace(
        run=run,
        root=tmp_path,
        output=cache / "output",
        env=env,
        protocol=value,
        protocol_path=protocol_path,
        bindings_path=bindings_path,
        grant=grant,
        ownership_path=ownership_path,
    )


def test_real_generated_cli_freeze_prepare_audit_and_exclusive_outputs(tmp_path):
    fixture = create_cli_fixture(tmp_path)
    hashes = {p: scene.file_hash(p) for p in tmp_path.iterdir() if p.is_file()}
    frozen = fixture.run("freeze")
    assert frozen.returncode == 0, frozen.stderr
    context = json.loads(frozen.stdout)["context_sha256"]
    prepared = fixture.run("prepare", context)
    assert prepared.returncode == 0, prepared.stderr
    terminal = scene.decode((fixture.output / "prepare/terminal.json").read_bytes())
    cli_module().require_absent(terminal["process"])
    audited = fixture.run("audit", context)
    assert audited.returncode == 0, audited.stderr
    public = json.loads(audited.stdout)
    assert public["source_clocks_independently_redecoded"] and public["images"] == 5
    assert (
        public["original_preparation_process_absent"]
        and public["original_store_completed"]
    )
    for output in (frozen.stdout, prepared.stdout, audited.stdout):
        assert "PRIVATE" not in output and str(tmp_path) not in output
    assert all(scene.file_hash(p) == digest for p, digest in hashes.items())
    before = {
        p.relative_to(fixture.output).as_posix(): scene.file_hash(p)
        for p in fixture.output.rglob("*")
        if p.is_file()
    }
    repeated = fixture.run("prepare", context)
    assert repeated.returncode != 0
    assert before == {
        p.relative_to(fixture.output).as_posix(): scene.file_hash(p)
        for p in fixture.output.rglob("*")
        if p.is_file()
    }


def test_real_cli_uses_shared_store_admission_and_preserves_busy_job(tmp_path):
    fixture = create_cli_fixture(tmp_path)
    frozen = fixture.run("freeze")
    assert frozen.returncode == 0, frozen.stderr
    store = Store(tmp_path / "data/processed")
    store.claim_job(
        {
            "id": "busy",
            "kind": "generated-existing",
            "video_id": None,
            "status": "running",
        }
    )
    original = store.jobs()[0]
    result = fixture.run("prepare", json.loads(frozen.stdout)["context_sha256"])
    assert (
        result.returncode != 0 and "Another processing job is running" in result.stderr
    )
    assert store.jobs() == [original] and not list(fixture.output.rglob("*.jpg"))
    failure = scene.decode((fixture.output / "prepare/failure.json").read_bytes())
    assert failure["job_id"] is None and failure["implicit_retry_permitted"] is False


def test_real_cli_rejects_mutated_source_before_store_admission(tmp_path):
    fixture = create_cli_fixture(tmp_path)
    frozen = fixture.run("freeze")
    assert frozen.returncode == 0, frozen.stderr
    source = tmp_path / "PRIVATE_A.mkv"
    source.write_bytes(source.read_bytes() + b" ")
    result = fixture.run("prepare", json.loads(frozen.stdout)["context_sha256"])
    assert result.returncode != 0 and "Original input hash changed" in result.stderr
    assert Store(tmp_path / "data/processed").jobs() == []
    assert {p.name for p in fixture.output.iterdir()} == {"context.json"}


def test_current_process_is_not_terminal_and_access_denial_stays_unresolved(
    monkeypatch,
):
    module = cli_module()
    with pytest.raises(ValueError, match="still present"):
        module.require_absent(module.identity())
    monkeypatch.setattr(
        module.psutil, "Process", lambda _: (_ for _ in ()).throw(psutil.AccessDenied())
    )
    with pytest.raises(psutil.AccessDenied):
        module.require_absent({"pid": 123, "created": 1.0})


def fixture_arguments(fixture, context):
    return SimpleNamespace(
        root=fixture.root,
        output=fixture.output,
        protocol=fixture.protocol_path,
        bindings=fixture.bindings_path,
        grant=fixture.root / ".cache/grant.json",
        ownership=fixture.ownership_path,
        context_sha256=context,
    )


@pytest.mark.parametrize(
    "target", ("bindings.json", "grant.json", "protocol.json", "output/context.json")
)
def test_final_mutation_guards_reject_changed_metadata_after_freeze(tmp_path, target):
    fixture = create_cli_fixture(tmp_path)
    frozen = fixture.run("freeze")
    assert frozen.returncode == 0, frozen.stderr
    args = fixture_arguments(fixture, json.loads(frozen.stdout)["context_sha256"])
    module = cli_module()
    context, value, paths = module.verified_context(args)
    path = tmp_path / ".cache" / target
    path.write_bytes(path.read_bytes() + b" ")
    if target == "grant.json":
        # Byte changes to grant whitespace alone do not alter the bound value;
        # change its actual identity as well.
        changed = scene.decode(path.read_bytes())
        changed["session_id"] = "changed"
        path.write_bytes(scene.encode(changed))
    with pytest.raises(ValueError):
        module.verify_stable(args, context, value, paths)


def test_source_changed_by_last_progress_callback_rejects_preparation(
    tmp_path, monkeypatch
):
    fixture = create_cli_fixture(tmp_path)
    frozen = fixture.run("freeze")
    assert frozen.returncode == 0, frozen.stderr
    args = fixture_arguments(fixture, json.loads(frozen.stdout)["context_sha256"])
    module = cli_module()

    def admitted_generated_only(args, stage, calculate):
        def progress(value):
            if value == 1:
                path = tmp_path / "PRIVATE_A.mkv"
                path.write_bytes(path.read_bytes() + b" ")

        return calculate(progress)

    monkeypatch.setattr(module, "admitted", admitted_generated_only)
    with pytest.raises(ValueError, match="Original input hash changed"):
        module.prepare(args)
    assert not (fixture.output / "prepare/terminal.json").exists()


def test_revoked_ownership_at_final_check_rejects_preparation(tmp_path, monkeypatch):
    fixture = create_cli_fixture(tmp_path)
    frozen = fixture.run("freeze")
    assert frozen.returncode == 0, frozen.stderr
    args = fixture_arguments(fixture, json.loads(frozen.stdout)["context_sha256"])
    module = cli_module()

    def admitted_generated_only(args, stage, calculate):
        def progress(value):
            if value == 1:
                live = scene.decode(fixture.ownership_path.read_bytes())
                live["paused"] = True
                fixture.ownership_path.write_bytes(scene.encode(live))

        return calculate(progress)

    monkeypatch.setattr(module, "admitted", admitted_generated_only)
    with pytest.raises(ValueError, match="Fresh authoritative ownership"):
        module.prepare(args)
    assert not (fixture.output / "prepare/terminal.json").exists()


def test_real_audit_rejects_extra_retained_file_without_rewriting_original_output(
    tmp_path,
):
    fixture = create_cli_fixture(tmp_path)
    frozen = fixture.run("freeze")
    assert frozen.returncode == 0, frozen.stderr
    context = json.loads(frozen.stdout)["context_sha256"]
    prepared = fixture.run("prepare", context)
    assert prepared.returncode == 0, prepared.stderr
    (fixture.output / "unexpected.png").write_bytes(b"not an authorized output")
    before = (fixture.output / "prepare/terminal.json").read_bytes()
    result = fixture.run("audit", context)
    assert (
        result.returncode != 0
        and "Unexpected or missing retained output" in result.stderr
    )
    assert (fixture.output / "prepare/terminal.json").read_bytes() == before
    assert not (fixture.output / "audit/verification.json").exists()


def test_isolated_worktree_cannot_supply_a_replacement_shared_store(
    tmp_path, monkeypatch
):
    from badminton import config

    module = cli_module()
    Store(tmp_path / "data/processed")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", tmp_path / "data/processed")
    monkeypatch.setattr(config, "WEIGHTS", tmp_path / "models/weights")
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda *a, **k: str(tmp_path.parent / ".git") + "\n",
    )
    with pytest.raises(ValueError, match="original shared namespace"):
        module.shared_store(tmp_path)
