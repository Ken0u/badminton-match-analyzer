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
def test_actual_generated_store_stage_completes_or_preserves_failure(tmp_path, fail):
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
cli.admitted(root,output,'preparation',{'deadline':time.time()+30},calculate)
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
