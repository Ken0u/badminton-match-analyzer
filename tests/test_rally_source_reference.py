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


@pytest.mark.parametrize("change", ["camera", "contact", "unsupported_event", "source"])
def test_complete_reference_checks_cross_stream_source_and_frame_evidence(change):
    s = streams()
    if change == "camera":
        s["independent_b"][0][0]["frame_states"][3]["camera_view"] = "conflicting-view"
    elif change == "contact":
        s["independent_b"][0][0]["frame_states"][3]["contact_state"] = "none_observed"
    elif change == "unsupported_event":
        for lane in r.STREAMS:
            s[lane][0][0]["frame_states"][3]["contact_state"] = "none_observed"
    else:
        s["independent_b"][0][0]["source_id"] = "another-source"
    result = r.reference_status(
        s, native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
    )
    assert not result["complete_reference"]


@pytest.mark.parametrize(
    "change", ["before_serve", "overlapping_contacts", "other_family"]
)
def test_reference_summary_preserves_order_and_requested_taxonomy(change):
    s = streams()
    for lane in r.STREAMS:
        d = s[lane][0][0]
        if change == "before_serve":
            event = copy.deepcopy(d["events"][1])
            event["interval"] = [0, 0]
            d["events"].insert(0, event)
            d["frame_states"][0]["contact_state"] = "observed"
        elif change == "overlapping_contacts":
            d["events"][1]["interval"] = [2, 3]
            event = copy.deepcopy(d["events"][1])
            event["interval"] = [3, 4]
            d["events"].insert(2, event)
        else:
            for e in d["events"]:
                if e["kind"] == "shot":
                    e["family"], e["side"] = "other", "forehand"
    result = r.reference_status(
        s, native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
    )
    if change == "other_family":
        assert result["complete_reference"]
        assert not result["all_requested_labels_supported"]
    else:
        assert not result["complete_reference"]


def joined_streams(change=None):
    p = packet()
    chunks = [
        {
            "start_index": 0,
            "end_index": 5,
            "frames": list(range(5)),
            "image_bytes": 500,
        },
        {
            "start_index": 3,
            "end_index": 8,
            "frames": list(range(3, 8)),
            "image_bytes": 500,
        },
    ]
    result = {}
    for lane in r.STREAMS:
        previous = None
        result[lane] = []
        for index, chunk in enumerate(chunks):
            doc = assessment(
                p,
                chunk,
                lane=lane,
                session=f"{lane}-{index}",
                previous=None if previous is None else previous["sha256"],
            )
            doc["events"] = [
                e
                for e in doc["events"]
                if chunk["frames"][0]
                <= e["interval"][0]
                <= e["interval"][1]
                <= chunk["frames"][-1]
            ]
            if index == 1:
                row = doc["frame_states"][0]
                if change == "camera":
                    row["camera_view"] = "conflicting-view"
                if change == "contact":
                    row["contact_state"] = "none_observed"
                if change == "duplicate":
                    doc["events"].insert(0, copy.deepcopy(doc["events"][0]))
            q = receipt(doc, chunk, thread=f"thread-{lane}-{index}")
            r.validate_assessment(
                doc, p, chunk, q, stage="dense", stream=lane, previous=previous
            )
            result[lane].append((doc, q))
            previous = {
                "sha256": q["segment_sha256"],
                "stream": lane,
                "source_id": p["source_id"],
                "stage": "dense",
                "last_frames": chunk["frames"][-2:],
            }
    return result


@pytest.mark.parametrize("change", ["camera", "contact"])
def test_contradictory_native_overlap_is_not_complete(change):
    assert r.reference_status(
        joined_streams(),
        native_frames=range(8),
        bounds={"start_frame": 0, "end_frame": 7},
    )["complete_reference"]
    result = r.reference_status(
        joined_streams(change),
        native_frames=range(8),
        bounds={"start_frame": 0, "end_frame": 7},
    )
    assert not result["complete_reference"]
    assert "conflicting_native_frame_chunk_join" in result["reasons"]


def test_duplicate_within_chunk_contact_is_not_an_overlap_copy():
    with pytest.raises(ValueError, match="Duplicate within-chunk"):
        joined_streams("duplicate")


def targeted_resolution(s, frames):
    p = packet()
    chunk = {
        "start_index": frames[0],
        "end_index": frames[-1] + 1,
        "frames": frames,
        "image_bytes": len(frames) * 100,
    }
    d = assessment(p, chunk, lane="adjudication", session="fresh-resolution")
    d["events"] = [
        e
        for e in d["events"]
        if frames[0] <= e["interval"][0] <= e["interval"][1] <= frames[-1]
    ]
    q = receipt(d, chunk, thread="fresh-resolution-thread")
    r.validate_assessment(d, p, chunk, q, stage="dense", stream="adjudication")
    s["adjudication"] = [(d, q)]
    return s


def test_two_exhaustive_agreeing_streams_do_not_require_third_exhaustive():
    s = streams()
    del s["adjudication"]
    assert r.adjudication_targets(s, native_frames=range(8)) == []
    assert r.targeted_reference_status(
        s, native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
    )["complete_reference"]


@pytest.mark.parametrize("change", ["camera", "contact", "actor", "event", "unknown"])
def test_targeted_source_adjudication_covers_only_required_region(change):
    s = streams()
    del s["adjudication"]
    doc = s["independent_b"][0][0]
    if change == "camera":
        doc["frame_states"][3]["camera_view"] = "another-view"
    elif change == "contact":
        doc["frame_states"][3]["contact_state"] = "none_observed"
    elif change == "actor":
        doc["actors"][0]["identity_supported"] = False
    elif change == "event":
        doc["events"][1]["side"] = "backhand"
    else:
        doc["frame_states"][3]["contact_state"] = "unknown"
    targets = r.adjudication_targets(s, native_frames=range(8))
    assert targets and len(targets) < 8
    assert not r.targeted_reference_status(
        s, native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
    )["complete_reference"]
    s = targeted_resolution(s, list(range(min(targets), max(targets) + 1)))
    result = r.targeted_reference_status(
        s, native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
    )
    assert result["complete_reference"]
    assert not result["all_requested_labels_supported"]
    assert not any(result["eligibility"].values())


def test_targeted_unknown_and_impersonation_stay_incomplete():
    s = streams()
    s["independent_b"][0][0]["frame_states"][3]["contact_state"] = "unknown"
    s = targeted_resolution(s, [3])
    s["adjudication"][0][0]["frame_states"][0]["contact_state"] = "unknown"
    assert not r.targeted_reference_status(
        s, native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
    )["complete_reference"]
    s["adjudication"][0][1]["thread_id"] = s["independent_a"][0][1]["thread_id"]
    with pytest.raises(ValueError, match="distinct"):
        r.targeted_reference_status(
            s, native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
        )


def test_targeted_original_coverage_cannot_shrink():
    s = streams()
    s["independent_b"][0][0]["frame_states"].pop()
    with pytest.raises(ValueError, match="every native frame"):
        r.adjudication_targets(s, native_frames=range(8))


@pytest.mark.parametrize("change", ["source", "image"])
def test_targeted_adjudication_cannot_mix_original_sources(change):
    s = streams()
    if change == "source":
        s["independent_b"][0][0]["source_id"] = "another-source"
    else:
        s["independent_b"][0][0]["inspected_frames"][3]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="same dense source"):
        r.targeted_reference_status(
            s, native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
        )


def test_targeted_event_without_observed_native_contact_requires_resolution():
    s = streams()
    for lane in r.STREAMS:
        s[lane][0][0]["frame_states"][3]["contact_state"] = "none_observed"
    assert r.adjudication_targets(s, native_frames=range(8)) == [3]
    assert not r.targeted_reference_status(
        s, native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
    )["complete_reference"]


def test_targeted_identity_definitions_and_interval_closure():
    s = streams()
    s["independent_b"][0][0]["actors"][0]["description"] = "a different source person"
    assert set(r.adjudication_targets(s, native_frames=range(8))) == {1, 3}
    s = streams()
    for lane in r.STREAMS[:2]:
        s[lane][0][0]["events"][1]["interval"] = [2, 4]
    s["independent_b"][0][0]["frame_states"][3]["contact_state"] = "unknown"
    assert r.adjudication_targets(s, native_frames=range(8)) == [2, 3, 4]
    s = targeted_resolution(s, [3])
    result = r.targeted_reference_status(
        s, native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
    )
    assert not result["complete_reference"]
    assert "partial_targeted_event_interval" in result["reasons"]


def test_extended_protocol_keeps_v1_and_full_grid():
    folder = Path(r.__file__).resolve().parents[2] / "data/manifests"
    v1 = r.load_protocol(folder / "rally_reference_protocol_v1.json")
    v2 = r.load_protocol(folder / "rally_reference_protocol_v2.json")
    c = clock(2001)
    assert len(r.overview_memberships(c, v1)) == 61
    assert len(r.overview_memberships(c, v2)) == 181
    assert r.overview_memberships(c, v2)[-1] == {
        "grid_second": 900,
        "frame": 1800,
        "clamped": False,
    }
    assert v2["payload"]["max_total_image_bytes"] == 4 * 1024**3
    assert v2["predecessor"]["image_bytes"] == 340760009


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
    changed_clock = copy.deepcopy(c)
    changed_clock["frames"][0]["corrupt"] = True
    with pytest.raises(ValueError, match="membership/source"):
        r.verify_packet(p, out, changed_clock, members)
    for kind in ("pts", "camera", "member", "image", "missing", "alias"):
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
        if kind == "alias":
            changed["frames"][0]["image"]["path"] = changed["frames"][1]["image"][
                "path"
            ]
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
    (output / "context.json").write_bytes(encoded({"generated": True}))
    slots = {
        "sources": [
            {"source_id": sid, "status": "unavailable", "complete_reference": False}
            for sid in r.SOURCE_IDS
        ],
        "eligibility": dict(r.ELIGIBILITY),
    }
    (output / "slots.json").write_bytes(encoded(slots))
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
    a={"job_id":identifier,"context_sha256":file_hash(out/"context.json"),"process":{"pid":p.pid,"creation_time":p.create_time(),"cwd":p.cwd(),"command":p.cmdline()}}
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
    original_context = (output / "context.json").read_bytes()
    (output / "context.json").write_bytes(encoded({"tampered": True}))
    with pytest.raises(ValueError, match="context seal"):
        r.verify_worker(output, root)
    (output / "context.json").write_bytes(original_context)
    changed_slots = copy.deepcopy(slots)
    changed_slots["sources"].pop()
    (output / "slots.json").write_bytes(encoded(changed_slots))
    with pytest.raises(ValueError, match="source slots"):
        r.verify_worker(output, root)
    (output / "slots.json").write_bytes(encoded(slots))
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


def test_dense_selection_requires_timestamp_and_both_slots(tmp_path):
    base = tmp_path / ".cache/rally62-source-only-v1"
    base.mkdir(parents=True)
    path = base / "selection.json"
    selection = {
        "screening_sealed": True,
        "sources": {},
        "eligibility": dict(r.ELIGIBILITY),
    }
    path.write_bytes(encoded(selection))
    with pytest.raises(ValueError, match="exact screening decision"):
        r.verify_selection(selection, path, {}, tmp_path)
    stamp = {"selection_sha256": file_hash(path)}
    with pytest.raises(ValueError, match="both independently screened"):
        r.verify_selection(selection, path, stamp, tmp_path)
    selection["sources"] = {key: {} for key in r.SOURCE_IDS}
    path.write_bytes(encoded(selection))
    stamp["selection_sha256"] = file_hash(path)
    with pytest.raises(ValueError, match="Original scientific assessments"):
        r.verify_selection(selection, path, stamp, tmp_path)


def test_generated_preparation_entry_admission_and_exclusive_output(
    tmp_path, monkeypatch
):
    import shutil
    import sqlite3
    import time

    from badminton.storage import Store

    ids = ("generated-a", "generated-b")
    monkeypatch.setattr(r, "SOURCE_IDS", ids)
    root = tmp_path / "original"
    data = root / "data/processed"
    Store(data)
    inputs = root / ".cache/generated-inputs"
    inputs.mkdir(parents=True)
    media = tmp_path / "generated.mp4"
    with av.open(str(media), "w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 32, 24, "yuv420p"
        for n in range(12):
            frame = av.VideoFrame.from_ndarray(
                np.full((24, 32, 3), n * 10, dtype=np.uint8), format="rgb24"
            )
            for item in stream.encode(frame):
                container.mux(item)
        for item in stream.encode():
            container.mux(item)
    census_dir = tmp_path / "census"
    census_dir.mkdir()
    census = native_clock(
        media, Budget(census_dir, {"output_bytes": 1024**2, "worker_seconds": 120})
    )
    sources = []
    for sid in ids:
        folder = inputs / sid
        folder.mkdir()
        shutil.copyfile(media, folder / "source.mp4")
        (folder / "clock.json").write_bytes(encoded(census))
        packet = {
            "source_id": sid,
            "source_sha256": file_hash(media),
            "clock_sha256": file_hash(folder / "clock.json"),
            "eligibility": dict(r.ELIGIBILITY),
        }
        (folder / "packet.json").write_bytes(encoded(packet))
        sources.append(
            {
                "source_id": sid,
                "source_sha256": file_hash(media),
                "clock_sha256": file_hash(folder / "clock.json"),
                "packet_sha256": file_hash(folder / "packet.json"),
                "native_frame_count": 12,
            }
        )
    protocol = {"sources": sources, "selection": {"overview_seconds": 300}}
    context = {
        "input_root": str(inputs),
        "inputs": sources,
        "deadline": time.time() + 120,
    }
    context_path = root / ".cache/context.json"
    context_path.write_bytes(encoded(context))
    protocol_path = root / ".cache/generated-protocol.json"
    protocol_path.write_bytes(encoded(protocol))
    stamp = root / ".cache/timestamp.json"
    stamp.write_bytes(
        encoded(
            {
                "context_sha256": file_hash(context_path),
                "url": "https://github.com/Ken0u/badminton-match-analyzer/issues/62#issuecomment-0",
                "published_at": time.time(),
            }
        )
    )
    output = root / ".cache/rally62-source-only-v1/generated-overview"
    script = tmp_path / "generated-entry.py"
    script.write_text(
        """import sys
from pathlib import Path
from badminton import rally_source_reference as r
from badminton.shuttle_supervision import read_json,file_hash
root=Path(sys.argv[1]);out=Path(sys.argv[2])
r.SOURCE_IDS=("generated-a","generated-b")
# Only repository/owner-protocol freezing is substituted for this generated
# integration fixture. Native source/census/packet validation, real Store,
# admission, output bounds, exclusive publication and exit proofs are actual.
r.load_protocol=lambda path:read_json(root/".cache/generated-protocol.json")
r.verify_context=lambda checkout,context:None
r.run_preparation(root,root,out,root/".cache/context.json",file_hash(root/".cache/context.json"),root/".cache/timestamp.json",stage="overview")
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
    for key in r.CREDENTIALS:
        env.pop(key, None)
    command = [sys.executable, str(script), str(root), str(output)]
    child = subprocess.run(command, env=env, capture_output=True, timeout=60)
    assert child.returncode == 0, child.stderr.decode()
    assert r.verify_worker(output, root)["original_lifetime_absent"]
    for sid in ids:
        p = json.loads((output / f"{sid}.packet.json").read_bytes())
        r.verify_packet(p, output, census, r.overview_memberships(census))
        assert len(p["memberships"]) == 61 and len(p["frames"]) == 2
    repeated = subprocess.run(command, env=env, capture_output=True, timeout=30)
    assert repeated.returncode != 0 and b"exclusive" in repeated.stderr
    with sqlite3.connect(data / "catalog.sqlite3") as db:
        assert db.execute("select count(*) from jobs").fetchone()[0] == 1
