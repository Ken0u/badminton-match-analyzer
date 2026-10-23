"""Generated provenance/coverage regressions, never badminton accuracy tests."""

import copy
import hashlib
import json
import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest
from badminton import rally_source_reference as r
from badminton.shuttle_sources import Budget, native_clock
from badminton.shuttle_supervision import encoded, file_hash


def clock(count=101, times=None, rotation=0):
    times = times or [Fraction(n, 2) for n in range(count)]
    return {
        "complete": True,
        "source_sha256": "a" * 64,
        "frame_count": len(times),
        "origin_s": float(times[0]),
        "frames": [
            {
                "frame": n,
                "pts": t.numerator,
                "time_base": str(Fraction(1, t.denominator)),
                "time_s": float(t),
                "rotation": rotation,
                "source_size": [32, 24],
                "display_size": [24, 32] if rotation in (90, 270) else [32, 24],
                "orientation_error": None,
                "corrupt": False,
            }
            for n, t in enumerate(times)
        ],
    }


def packet(count=8, size=100):
    c = clock(count)
    return {
        "source_id": "generated",
        "source_sha256": c["source_sha256"],
        "memberships": [{"frame": n} for n in range(count)],
        "eligibility": dict(r.ELIGIBILITY),
        "frames": [
            {
                **row,
                "scene": "unknown",
                "camera_view": "unreviewed",
                "image": {
                    "path": f"{row['frame']}.png",
                    "bytes": size,
                    "sha256": str(row["frame"]) * 64,
                },
            }
            for row in c["frames"]
        ],
    }


def assessment(
    p, chunk, lane="independent_a", stage="dense", session="a", previous=None
):
    doc = {
        "stage": stage,
        "stream": lane,
        "source_id": p["source_id"],
        "session_id": session,
        "eligibility": dict(r.ELIGIBILITY),
        "independent_source_only": True,
        "inspected_frames": [
            {"frame": row["frame"], "sha256": row["image"]["sha256"]}
            for row in p["frames"]
            if row["frame"] in chunk["frames"]
        ],
        "previous_segment_sha256": previous,
        "continuity_notes": "The same source actor remains visible across this stream's overlap.",
        "coverage_complete": True,
        "scene": "live",
        "start_censored": False,
        "end_censored": False,
        "unresolved_gaps": [],
        "actors": [
            {
                "actor_id": "A",
                "description": "generated actor",
                "identity_supported": True,
            }
        ],
        "events": [
            {
                "kind": "serve",
                "interval": [1, 1],
                "actor_id": "A",
                "side": "forehand",
                "family": None,
                "reason": "generated contact",
            },
            {
                "kind": "shot",
                "interval": [3, 3],
                "actor_id": "A",
                "side": "unknown",
                "family": "unknown",
                "reason": "generated contact",
            },
            {
                "kind": "rally_end",
                "interval": [6, 6],
                "evidence": "ground_contact",
                "reason": "generated terminal",
            },
        ],
        "frame_states": [
            {
                "frame": n,
                "scene": "live",
                "camera_view": "view1",
                "contact_state": "observed" if n in (1, 3) else "none_observed",
            }
            for n in chunk["frames"]
        ],
    }
    if stage == "overview":
        doc["frames"] = [
            {"frame": n, "state": "unknown", "reason": "generated unknown"}
            for n in chunk["frames"]
        ]
    return doc


def receipt(doc, chunk, thread="thread-a"):
    return {
        "thread_id": thread,
        "exit_code": 0,
        "exited": True,
        "segment_sha256": hashlib.sha256(encoded(doc)).hexdigest(),
        "images": doc["inspected_frames"],
        "image_bytes": chunk["image_bytes"],
        "session_id": doc["session_id"],
        "original_resolution_viewing": True,
    }


def test_native_vfr_grid_clamping_and_orientation():
    c = clock(times=[Fraction(0), Fraction(1, 3), Fraction(51, 10), Fraction(9)])
    assert r.validate_clock(c)[2] == Fraction(51, 10)
    members = r.overview_memberships(c)
    assert len(members) == 61 and members[1]["frame"] == 2
    assert members[2] == {"grid_second": 10, "frame": 3, "clamped": True}
    assert members[-1]["frame"] == 3
    assert r.validate_clock(clock(rotation=90))
    assert len(r.dense_memberships(clock(), {"start_frame": 10, "end_frame": 30})) == 37


@pytest.mark.parametrize(
    "mutation",
    [
        "ordinal",
        "pts",
        "time",
        "base",
        "rotation",
        "geometry",
        "complete",
        "missing",
        "duplicate",
        "bool",
    ],
)
def test_clock_tampering(mutation):
    c = clock()
    if mutation == "ordinal":
        c["frames"][3]["frame"] = 4
    if mutation == "pts":
        c["frames"][3]["pts"] = c["frames"][2]["pts"]
    if mutation == "time":
        c["frames"][3]["time_s"] = float("nan")
    if mutation == "base":
        c["frames"][3]["time_base"] = "0"
    if mutation == "rotation":
        c["frames"][3]["rotation"] = 90
    if mutation == "geometry":
        c["frames"][3]["source_size"] = [0, 24]
    if mutation == "complete":
        c["complete"] = False
    if mutation == "missing":
        c["frames"].pop()
    if mutation == "duplicate":
        c["frames"].insert(3, copy.deepcopy(c["frames"][2]))
    if mutation == "bool":
        c["frames"][3]["frame"] = True
    with pytest.raises(ValueError):
        r.validate_clock(c)


def test_selection_is_earliest_and_never_claims_completeness():
    c = clock(701)
    rows = [
        {"frame": m["frame"], "state": "unknown", "reason": "generated"}
        for m in r.overview_memberships(c)
    ]
    for i, state in enumerate(("service_preparation", "exchange", "stopped_play"), 2):
        rows[i]["state"] = state
    for i, state in enumerate(("service_preparation", "exchange", "stopped_play"), 8):
        rows[i]["state"] = state
    candidate = r.earliest_candidate(c, {"frames": rows})
    assert candidate["start_frame"] == 20 and candidate["end_frame"] == 40
    assert candidate["complete_reference"] is False
    rows[3]["state"] = "replay"
    assert r.earliest_candidate(c, {"frames": rows})["start_frame"] == 80
    rows[9]["state"] = "unknown"
    assert r.earliest_candidate(c, {"frames": rows}) is None
    rows.pop()
    with pytest.raises(ValueError):
        r.earliest_candidate(c, {"frames": rows})


@pytest.mark.parametrize(
    "bounds",
    [
        {"start_frame": 0, "end_frame": 100},
        {"start_frame": 4, "end_frame": 4},
        {"start_frame": 4, "end_frame": 102},
    ],
)
def test_dense_bounds_refuse_censoring_or_overlength(bounds):
    with pytest.raises(ValueError):
        r.dense_memberships(clock(), bounds)


def test_chunk_overlap_and_cumulative_payload():
    p = packet(53)
    chunks = r.plan_chunks(p, dense=True)
    assert [len(c["frames"]) for c in chunks] == [20, 20, 17]
    assert chunks[0]["frames"][-2:] == chunks[1]["frames"][:2]
    assert r.payload_cost(chunks) == 57 * 100 * 3
    with pytest.raises(ValueError):
        r.payload_cost(chunks, prior_bytes=r.MAX_PAYLOAD_BYTES)
    p["frames"][5]["frame"] += 1
    with pytest.raises(ValueError):
        r.plan_chunks(p, dense=True)
    with pytest.raises(ValueError):
        r.plan_chunks(packet(8, r.MAX_SESSION_BYTES), dense=True)
    p = packet()
    p["frames"][3]["image"] = None
    with pytest.raises(ValueError):
        r.plan_chunks(p, dense=True)


@pytest.mark.parametrize(
    "change",
    [
        "missing_image",
        "duplicate",
        "sha",
        "scene",
        "gap",
        "contacts",
        "half_smash",
        "terminal",
        "serve_family",
        "actor",
        "censor",
        "thread",
        "exited",
        "coverage",
        "bytes",
        "own_join",
    ],
)
def test_assessment_failures(change):
    p = packet()
    chunk = r.plan_chunks(p, dense=True)[0]
    d = assessment(p, chunk)
    if change == "missing_image":
        d["inspected_frames"].pop()
    if change == "duplicate":
        d["inspected_frames"][1] = d["inspected_frames"][0]
    if change == "sha":
        d["inspected_frames"][1]["sha256"] = "f" * 64
    if change == "scene":
        d["scene"] = "probably_live"
    if change == "gap":
        d["unresolved_gaps"] = [{"interval": [1, 10], "reason": "missing"}]
    if change == "contacts":
        d["events"].pop(1)
    if change == "half_smash":
        d["events"][1]["family"] = "half_smash"
    if change == "terminal":
        d["events"][-1]["evidence"] = "last_stroke"
    if change == "serve_family":
        d["events"][0]["family"] = "drive"
    if change == "actor":
        d["events"][0]["actor_id"] = "tracker17"
    if change == "censor":
        del d["start_censored"]
    if change == "coverage":
        d["frame_states"].pop()
    if change == "own_join":
        d["previous_segment_sha256"] = "invented"
    q = receipt(d, chunk)
    if change == "thread":
        q["thread_id"] = None
    if change == "exited":
        q["exited"] = False
    if change == "bytes":
        q["image_bytes"] += 1
    with pytest.raises(ValueError):
        r.validate_assessment(d, p, chunk, q, stage="dense", stream="independent_a")


def streams():
    p = packet()
    chunk = r.plan_chunks(p, dense=True)[0]
    result = {}
    for lane in r.STREAMS:
        d = assessment(p, chunk, lane=lane, session=lane)
        q = receipt(d, chunk, thread=lane)
        r.validate_assessment(d, p, chunk, q, stage="dense", stream=lane)
        result[lane] = [(d, q)]
    return result


def test_complete_reference_is_separate_from_unknown_requested_labels():
    result = r.reference_status(
        streams(), native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
    )
    assert result["complete_reference"] is True
    assert result["all_requested_labels_supported"] is False
    assert not any(result["eligibility"].values())


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "replay",
        "unknown",
        "gap",
        "censored",
        "identity",
        "unresolved",
        "disagreement",
        "last_hit",
        "terminal",
        "omission",
    ],
)
def test_reference_incomplete_cases(change):
    s = streams()
    d = s["adjudication"][0][0]
    if change == "missing":
        del s["independent_b"]
    if change == "replay":
        d["scene"] = "replay"
    if change == "unknown":
        d["frame_states"][2]["scene"] = "unknown"
    if change == "gap":
        d["unresolved_gaps"] = [{"interval": [2, 3], "reason": "hidden"}]
    if change == "censored":
        d["start_censored"] = True
    if change == "identity":
        d["actors"][0]["identity_supported"] = False
    if change == "unresolved":
        d["events"][1]["kind"] = "unresolved_contact"
    if change == "disagreement":
        d["events"][1]["interval"] = [3, 4]
    if change == "last_hit":
        d["events"][-1]["interval"] = [3, 3]
    if change == "terminal":
        d["events"][-1]["evidence"] = "stopped_play"
    if change == "omission":
        d["inspected_frames"].pop()
    assert (
        r.reference_status(
            s, native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
        )["complete_reference"]
        is False
    )


def test_no_impersonated_independent_session():
    s = streams()
    s["independent_b"][0][1]["thread_id"] = "independent_a"
    with pytest.raises(ValueError):
        r.reference_status(
            s, native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
        )


def test_overlapping_chunks_require_same_stream_context():
    p = packet(26)
    first, second = r.plan_chunks(p, dense=True)
    prior = {
        "sha256": "a" * 64,
        "stream": "independent_a",
        "stage": "dense",
        "source_id": p["source_id"],
        "last_frames": first["frames"][-2:],
    }
    d = assessment(p, second, previous=prior["sha256"])
    d["events"] = []
    for row in d["frame_states"]:
        row["contact_state"] = "none_observed"
    r.validate_assessment(
        d,
        p,
        second,
        receipt(d, second),
        stage="dense",
        stream="independent_a",
        previous=prior,
    )
    for key, value in (
        ("stream", "independent_b"),
        ("last_frames", [0, 1]),
        ("source_id", "another"),
    ):
        changed = {**prior, key: value}
        with pytest.raises(ValueError):
            r.validate_assessment(
                d,
                p,
                second,
                receipt(d, second),
                stage="dense",
                stream="independent_a",
                previous=changed,
            )


def test_overview_unknowns_are_preserved_and_chunk_membership_is_bound():
    p = packet()
    chunk = r.plan_chunks(p, dense=False, overlap=0)[0]
    d = assessment(p, chunk, stage="overview")
    r.validate_assessment(
        d, p, chunk, receipt(d, chunk), stage="overview", stream="independent_a"
    )
    changed = copy.deepcopy(chunk)
    changed["start_index"] = 1
    with pytest.raises(ValueError):
        r.validate_assessment(
            d, p, changed, receipt(d, chunk), stage="overview", stream="independent_a"
        )


def test_real_generated_native_extraction_and_tamper(tmp_path):
    path = tmp_path / "generated.mp4"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width = 32
        stream.height = 24
        stream.pix_fmt = "yuv420p"
        for n in range(12):
            frame = av.VideoFrame.from_ndarray(
                np.full((24, 32, 3), n * 10, dtype=np.uint8), format="rgb24"
            )
            for pkt in stream.encode(frame):
                container.mux(pkt)
        for pkt in stream.encode():
            container.mux(pkt)
    out = tmp_path / "output"
    out.mkdir()
    b = Budget(out, {"output_bytes": 1024**2, "worker_seconds": 120})
    c = native_clock(path, b)
    members = [{"frame": n} for n in range(2, 9)]
    p = r.extract_frames(path, c, members, out / "images", "generated", b)
    r.verify_packet(p, out, c, members)
    for kind in ("pts", "camera", "member", "image", "missing"):
        changed = copy.deepcopy(p)
        if kind == "pts":
            changed["frames"][0]["pts"] += 1
        if kind == "camera":
            changed["frames"][0]["camera_view"] = "live"
        if kind == "member":
            changed["memberships"].append({"frame": 10})
        if kind == "image":
            changed["frames"][0]["image"]["sha256"] = "f" * 64
        if kind == "missing":
            changed["frames"].pop()
        with pytest.raises(ValueError):
            r.verify_packet(changed, out, c, members)
    with pytest.raises(FileExistsError):
        r.extract_frames(path, c, members, out / "images", "generated", b)


def test_actual_generated_store_worker_exit_required(tmp_path):
    root = tmp_path / "original"
    data = root / "data/processed"
    data.mkdir(parents=True)
    output = root / ".cache/generated"
    output.mkdir(parents=True)
    script = tmp_path / "worker.py"
    script.write_text(
        """import json,os,sys
from pathlib import Path
import psutil
from badminton.storage import Store
from badminton.jobs import run_local_job
from badminton.shuttle_supervision import encoded,file_hash
root,out=map(Path,sys.argv[1:]);p=psutil.Process()
def task(identifier,progress):
    a={"job_id":identifier,"process":{"pid":p.pid,"creation_time":p.create_time(),"cwd":p.cwd(),"command":p.cmdline()}}
    (out/"admission.json").write_bytes(encoded(a));return {"generated":True}
summary=run_local_job(Store(root/"data/processed"),"generated_reference","generated",task)
a=json.loads((out/"admission.json").read_bytes())
(out/"terminal.json").write_bytes(encoded({"job_id":a["job_id"],"status":"completed","admission_sha256":file_hash(out/"admission.json"),"summary":summary,"artifacts":{}}))
""",
        encoding="utf-8",
    )
    env = dict(
        os.environ,
        PYTHONPATH=str(Path(r.__file__).resolve().parents[1]),
        BADMINTON_ROOT=str(root),
        BADMINTON_DATA_DIR=str(data),
        BADMINTON_WEIGHTS_DIR=str(root / "models/weights"),
    )
    completed = subprocess.run(
        [sys.executable, str(script), str(root), str(output)],
        env=env,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    assert r.verify_worker(output, root)["store_completed"]
    admission = json.loads((output / "admission.json").read_bytes())
    admission["process"]["pid"] = os.getpid()
    import psutil

    admission["process"]["creation_time"] = psutil.Process().create_time()
    (output / "admission.json").write_bytes(encoded(admission))
    terminal = json.loads((output / "terminal.json").read_bytes())
    terminal["admission_sha256"] = file_hash(output / "admission.json")
    (output / "terminal.json").write_bytes(encoded(terminal))
    with pytest.raises(ValueError, match="still alive"):
        r.verify_worker(output, root)


def test_prospective_protocol_and_budget_guards(tmp_path):
    protocol = (
        Path(r.__file__).resolve().parents[2]
        / "data/manifests/rally_reference_protocol_v1.json"
    )
    assert r.load_protocol(protocol)["task"] == 62
    changed = json.loads(protocol.read_bytes())
    changed["eligibility"]["training_allowed"] = True
    target = tmp_path / "protocol.json"
    target.write_bytes(encoded(changed))
    with pytest.raises(ValueError):
        r.load_protocol(target)
    target.write_bytes(b"123456")
    assert r.persisted_bytes(tmp_path) == 6
