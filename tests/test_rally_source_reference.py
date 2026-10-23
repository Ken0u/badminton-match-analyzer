"""Generated provenance/coverage regressions, never badminton accuracy tests."""

import copy
import hashlib
import itertools
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


@pytest.mark.parametrize("change", ["description", "unlinked_id", "swapped_person"])
def test_targeted_composite_rejects_unlinked_source_hitters(change):
    """A locally known hitter is not necessarily linked to retained contacts."""
    p = packet()
    chunk = r.plan_chunks(p, dense=True)[0]
    s = streams()
    del s["adjudication"]
    for lane in r.STREAMS[:2]:
        doc = s[lane][0][0]
        doc["actors"][0]["description"] = "blue-shirt source player"
        if change == "swapped_person":
            doc["actors"].append(
                {
                    "actor_id": "B",
                    "description": "red-shirt source player",
                    "identity_supported": True,
                }
            )
            doc["events"][1]["actor_id"] = "B"
        if lane == "independent_b":
            doc["frame_states"][3]["contact_state"] = "unknown"
        q = receipt(doc, chunk, thread=f"generated-original-{lane}")
        s[lane][0] = (doc, q)
        r.validate_assessment(doc, p, chunk, q, stage="dense", stream=lane)
    assert r.adjudication_targets(s, native_frames=range(8)) == [3]
    s = targeted_resolution(s, [3])
    doc = s["adjudication"][0][0]
    if change == "description":
        doc["actors"][0]["description"] = "a different red-shirt source player"
    elif change == "unlinked_id":
        doc["actors"][0].update(
            actor_id="independent-name", description="blue-shirt source player"
        )
        doc["events"][0]["actor_id"] = "independent-name"
    else:
        doc["actors"][0].update(actor_id="B", description="blue-shirt source player")
        doc["events"][0]["actor_id"] = "B"
    target = {"start_index": 3, "end_index": 4, "frames": [3], "image_bytes": 100}
    q = receipt(doc, target, thread="generated-target")
    s["adjudication"][0] = (doc, q)
    r.validate_assessment(doc, p, target, q, stage="dense", stream="adjudication")
    result = r.targeted_reference_status(
        s, native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
    )
    assert not result["complete_reference"]
    assert not result["all_requested_labels_supported"]
    assert "unlinked_targeted_source_actor" in result["reasons"]


@pytest.mark.parametrize("replace_all_contacts", [False, True])
def test_targeted_composite_accepts_supported_actor_continuity(replace_all_contacts):
    s = streams()
    del s["adjudication"]
    if replace_all_contacts:
        s["independent_b"][0][0]["actors"][0]["identity_supported"] = False
        selected = [1, 2, 3]
    else:
        s["independent_b"][0][0]["frame_states"][3]["contact_state"] = "unknown"
        selected = [3]
    s = targeted_resolution(s, selected)
    doc = s["adjudication"][0][0]
    if replace_all_contacts:
        # All final contact identities now come from the one source-only lane;
        # no cross-stream identity mapping is inferred at a retained contact.
        doc["actors"][0].update(
            actor_id="fresh-source-person", description="fresh source description"
        )
        for event in doc["events"]:
            event["actor_id"] = "fresh-source-person"
    target = {
        "start_index": selected[0],
        "end_index": selected[-1] + 1,
        "frames": selected,
        "image_bytes": len(selected) * 100,
    }
    q = receipt(doc, target, thread="generated-supported-target")
    s["adjudication"][0] = (doc, q)
    r.validate_assessment(
        doc, packet(), target, q, stage="dense", stream="adjudication"
    )
    result = r.targeted_reference_status(
        s, native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
    )
    assert result["complete_reference"]
    assert not any(result["eligibility"].values())


def test_targeted_composite_keeps_retained_contact_actor_before_later_conflict():
    p = packet()
    s = joined_streams()
    del s["adjudication"]
    for lane in r.STREAMS[:2]:
        previous = None
        for index, (doc, _) in enumerate(s[lane]):
            doc["actors"][0]["description"] = (
                "blue-shirt source player" if index == 0 else "red-shirt source player"
            )
            selected = [row["frame"] for row in doc["inspected_frames"]]
            chunk = {
                "start_index": selected[0],
                "end_index": selected[-1] + 1,
                "frames": selected,
                "image_bytes": len(selected) * 100,
            }
            doc["previous_segment_sha256"] = previous["sha256"] if previous else None
            q = receipt(doc, chunk, thread=f"generated-{lane}-{index}")
            s[lane][index] = (doc, q)
            r.validate_assessment(
                doc, p, chunk, q, stage="dense", stream=lane, previous=previous
            )
            previous = {
                "sha256": q["segment_sha256"],
                "stream": lane,
                "source_id": p["source_id"],
                "stage": "dense",
                "last_frames": selected[-2:],
            }
    assert r.adjudication_targets(s, native_frames=range(8)) == list(range(3, 8))
    s = targeted_resolution(s, list(range(3, 8)))
    doc = s["adjudication"][0][0]
    doc["actors"][0]["description"] = "red-shirt source player"
    chunk = {
        "start_index": 3,
        "end_index": 8,
        "frames": list(range(3, 8)),
        "image_bytes": 500,
    }
    q = receipt(doc, chunk, thread="generated-later-target")
    s["adjudication"][0] = (doc, q)
    r.validate_assessment(doc, p, chunk, q, stage="dense", stream="adjudication")
    result = r.targeted_reference_status(
        s, native_frames=range(8), bounds={"start_frame": 0, "end_frame": 7}
    )
    assert not result["complete_reference"]
    assert "unlinked_targeted_source_actor" in result["reasons"]


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


def assessment_protocol():
    """Read the committed specification, without opening source data or labels."""
    return r.load_protocol(
        Path(r.__file__).resolve().parents[2]
        / "data/manifests/rally_reference_protocol_v3.json"
    )


def test_dense_assessment_protocol_preserves_both_earlier_protocols():
    folder = Path(r.__file__).resolve().parents[2] / "data/manifests"
    earlier = {
        n: r.load_protocol(folder / f"rally_reference_protocol_v{n}.json")
        for n in (1, 2)
    }
    protocol = assessment_protocol()
    assert (protocol["schema_version"], protocol["task"]) == (3, 210)
    assert protocol["payload"]["max_images_per_session"] == 20
    assert protocol["payload"]["max_image_bytes_per_session"] == 32 * 1024**2
    assert protocol["payload"]["max_total_image_bytes"] == 8 * 1024**3
    assert protocol["limits"]["max_output_bytes"] == 8 * 1024**3
    assert protocol["limits"]["task_seconds_from_grant"] == 8 * 3600
    assert protocol["predecessor"]["task"] == 208
    assert protocol["predecessor"]["image_bytes"] == 1347060833
    assert protocol["sources"] == earlier[2]["sources"]
    assert protocol["eligibility"] == r.ELIGIBILITY
    assert not any(protocol["eligibility"].values())
    for n, before in earlier.items():
        assert r.load_protocol(folder / f"rally_reference_protocol_v{n}.json") == before
        assert before["payload"]["max_image_bytes_per_session"] == 6 * 1024**2
    assert (r.MAX_IMAGES, r.MAX_SESSION_BYTES, r.MAX_PAYLOAD_BYTES) == (
        20,
        6 * 1024**2,
        2 * 1024**3,
    )


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        (None, "schema_version", True),
        (None, "schema_version", 4),
        (None, "task", 208),
        ("payload", "max_images_per_session", 21),
        ("payload", "max_image_bytes_per_session", 32 * 1024**2 + 1),
        ("payload", "max_total_image_bytes", 8 * 1024**3 + 1),
        ("limits", "max_output_bytes", 8 * 1024**3 + 1),
        ("limits", "task_seconds_from_grant", 8 * 3600 + 1),
        ("limits", "paid_services", True),
        ("assessment", "chunk_overlap_frames", 1),
        ("assessment", "adjudication", "third_exhaustive_pass"),
        ("predecessor", "task", 62),
        ("predecessor", "image_bytes", 1347060832),
        ("eligibility", "training_allowed", True),
        ("eligibility", "independent_test_allowed", True),
        ("eligibility", "model_deployment_allowed", True),
        ("eligibility", "dataset_redistribution_allowed", True),
    ],
)
def test_dense_assessment_protocol_rejects_unapproved_scope(
    tmp_path, section, key, value
):
    protocol = assessment_protocol()
    target = protocol if section is None else protocol[section]
    target[key] = value
    path = tmp_path / "changed-protocol.json"
    path.write_bytes(encoded(protocol))
    with pytest.raises(ValueError):
        r.load_protocol(path)


@pytest.mark.parametrize(
    "key",
    [
        "source_id",
        "source_sha256",
        "clock_sha256",
        "packet_sha256",
        "native_frame_count",
    ],
)
def test_dense_assessment_protocol_binds_original_sources(tmp_path, key):
    protocol = assessment_protocol()
    source = protocol["sources"][0]
    source[key] = source[key] + 1 if key == "native_frame_count" else "f" * 64
    path = tmp_path / "changed-source.json"
    path.write_bytes(encoded(protocol))
    with pytest.raises(ValueError):
        r.load_protocol(path)


@pytest.mark.parametrize(
    "key",
    [
        "head_sha",
        "merged_sha",
        "screening_sha256",
        "selection_sha256",
        "context_sha256",
        "terminal_sha256",
        "dense_packets",
        "native_frames",
        "retained_slots",
        "complete_references",
    ],
)
def test_dense_assessment_protocol_rejects_replaced_predecessor_evidence(tmp_path, key):
    protocol = assessment_protocol()
    current = protocol["predecessor"][key]
    if isinstance(current, dict):
        first = next(iter(current))
        current[first] = current[first] + 1 if type(current[first]) is int else "f" * 64
    else:
        protocol["predecessor"][key] = current + 1 if type(current) is int else "f" * 64
    path = tmp_path / "changed-predecessor.json"
    path.write_bytes(encoded(protocol))
    with pytest.raises(ValueError):
        r.load_protocol(path)


def generated_consumer_checkout(tmp_path, monkeypatch):
    """Seal generated files and the real core runtime without requiring ML extras."""
    checkout = tmp_path / "checkout"
    origin = Path(r.__file__).resolve().parents[2]
    for relative in (
        "backend/badminton/generated.py",
        "scripts/prepare_rally_references.py",
        "data/manifests/rally_reference_protocol_v1.json",
        "data/manifests/rally_reference_protocol_v2.json",
        "data/manifests/rally_reference_protocol_v3.json",
        "data/manifests/rally_reference_protocol_v4.json",
        "data/manifests/shuttle_review_sources_v1.json",
        "pyproject.toml",
        "uv.lock",
        "requirements.lock",
    ):
        path = checkout / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            (origin / relative).read_bytes()
            if relative.startswith("data/manifests/")
            else b"# generated consumer fixture\n"
        )
    monkeypatch.setattr(
        r.subprocess,
        "check_output",
        lambda command, **kwargs: "c" * 40 if command[1] == "rev-parse" else "",
    )
    version = r.importlib.metadata.version
    optional = {"torch": "0.generated", "torchvision": "0.generated"}
    monkeypatch.setattr(
        r.importlib.metadata,
        "version",
        lambda name: optional[name] if name in optional else version(name),
    )
    return checkout


def test_dense_consumer_context_keeps_original_grant_and_seals_all_protocol_versions(
    tmp_path, monkeypatch
):
    checkout = generated_consumer_checkout(tmp_path, monkeypatch)
    granted = 1700000000
    protocol_path = checkout / "data/manifests/rally_reference_protocol_v3.json"
    context = r.consumer_context(checkout, protocol_path, tmp_path / "inputs", granted)
    assert context["task"] == 210
    assert context["granted_at"] == granted
    assert context["deadline"] == granted + 28800
    assert context["protocol_path"] == protocol_path.relative_to(checkout).as_posix()
    assert context["runtime"]["torch"] == "0.generated"
    assert context["runtime"]["torchvision"] == "0.generated"
    for n in (1, 2, 3):
        name = f"data/manifests/rally_reference_protocol_v{n}.json"
        assert context["consumers"][name] == file_hash(checkout / name)
    monkeypatch.setattr(r.time, "time", lambda: context["deadline"] - 1)
    r.verify_context(checkout, context)
    monkeypatch.setattr(r.time, "time", lambda: context["deadline"])
    with pytest.raises(ValueError, match="deadline"):
        r.verify_context(checkout, context)


@pytest.mark.parametrize("n", [1, 2])
def test_earlier_consumer_contexts_keep_four_hour_deadlines(tmp_path, monkeypatch, n):
    checkout = generated_consumer_checkout(tmp_path, monkeypatch)
    context = r.consumer_context(
        checkout,
        checkout / f"data/manifests/rally_reference_protocol_v{n}.json",
        tmp_path / "inputs",
        1700000000,
    )
    assert context["deadline"] - context["granted_at"] == 14400


@pytest.mark.parametrize(
    "relative",
    [
        "backend/badminton/generated.py",
        "data/manifests/rally_reference_protocol_v2.json",
        "data/manifests/rally_reference_protocol_v3.json",
    ],
)
def test_dense_consumer_context_rejects_changed_consumer_or_protocol(
    tmp_path, monkeypatch, relative
):
    checkout = generated_consumer_checkout(tmp_path, monkeypatch)
    context = r.consumer_context(
        checkout,
        checkout / "data/manifests/rally_reference_protocol_v3.json",
        tmp_path / "inputs",
        1700000000,
    )
    monkeypatch.setattr(r.time, "time", lambda: context["deadline"] - 1)
    path = checkout / relative
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        r.verify_context(checkout, context)


@pytest.mark.parametrize("package", ["torch", "torchvision"])
def test_dense_consumer_context_rejects_changed_optional_runtime(
    tmp_path, monkeypatch, package
):
    checkout = generated_consumer_checkout(tmp_path, monkeypatch)
    context = r.consumer_context(
        checkout,
        checkout / "data/manifests/rally_reference_protocol_v3.json",
        tmp_path / "inputs",
        1700000000,
    )
    monkeypatch.setattr(r.time, "time", lambda: context["deadline"] - 1)
    version = r.importlib.metadata.version
    monkeypatch.setattr(
        r.importlib.metadata,
        "version",
        lambda name: "1.changed" if name == package else version(name),
    )
    with pytest.raises(ValueError, match="runtime changed"):
        r.verify_context(checkout, context)


def test_expanded_chunks_preserve_every_native_frame_and_charge_overlap():
    protocol = assessment_protocol()
    p = packet(26, 1024**2)
    expanded = r.plan_chunks(p, dense=True, protocol=protocol)
    assert [c["frames"] for c in expanded] == [list(range(20)), list(range(18, 26))]
    assert [c["image_bytes"] for c in expanded] == [20 * 1024**2, 8 * 1024**2]
    assert {n for c in expanded for n in c["frames"]} == set(range(26))
    assert expanded[0]["frames"][-2:] == expanded[1]["frames"][:2]
    prior = protocol["predecessor"]["image_bytes"]
    assert r.payload_cost(
        expanded, streams=2, prior_bytes=prior, protocol=protocol
    ) == (prior + 2 * 28 * 1024**2)
    # Calling the authorized path must not mutate the legacy default path.
    legacy = r.plan_chunks(p, dense=True)
    assert len(legacy) == 6
    assert all(c["image_bytes"] <= 6 * 1024**2 for c in legacy)


def test_expanded_chunk_limits_include_exact_session_and_image_boundaries():
    protocol = assessment_protocol()
    p = packet(20, 2 * 1024**2)
    chunks = r.plan_chunks(p, dense=True, protocol=protocol)
    assert [len(c["frames"]) for c in chunks] == [16, 6]
    assert chunks[0]["image_bytes"] == 32 * 1024**2
    assert [
        len(c["frames"])
        for c in r.plan_chunks(packet(21), dense=True, protocol=protocol)
    ] == [
        20,
        3,
    ]
    with pytest.raises(ValueError):
        r.plan_chunks(packet(1, 32 * 1024**2 + 1), dense=True, protocol=protocol)


def test_expanded_cumulative_budget_counts_previous_dispatches_and_repeated_frames():
    protocol = assessment_protocol()
    chunks = r.plan_chunks(packet(26, 1024**2), dense=True, protocol=protocol)
    charge = 2 * sum(c["image_bytes"] for c in chunks)
    limit = 8 * 1024**3
    assert charge == 56 * 1024**2  # Four repeated frame memberships across two streams.
    assert (
        r.payload_cost(chunks, streams=2, prior_bytes=limit - charge, protocol=protocol)
        == limit
    )
    with pytest.raises(ValueError):
        r.payload_cost(
            chunks, streams=2, prior_bytes=limit - charge + 1, protocol=protocol
        )
    with pytest.raises(ValueError):
        r.payload_cost(chunks, streams=2, prior_bytes=2 * 1024**3)
    with pytest.raises(ValueError):
        r.payload_cost(chunks, streams=2, protocol=protocol)


@pytest.mark.parametrize("size", [0, -1, True, 1.5])
@pytest.mark.parametrize("expanded", [False, True])
def test_chunk_planning_rejects_nonpositive_or_noninteger_original_image_bytes(
    size, expanded
):
    protocol = assessment_protocol() if expanded else None
    with pytest.raises(ValueError):
        r.plan_chunks(packet(8, size), dense=True, protocol=protocol)


@pytest.mark.parametrize("size", [0, -1, True, 1.5])
def test_cumulative_budget_rejects_invalid_chunk_charges(size):
    protocol = assessment_protocol()
    chunks = [{"image_bytes": size, "frames": [0]}]
    with pytest.raises(ValueError):
        r.payload_cost(
            chunks,
            streams=2,
            prior_bytes=protocol["predecessor"]["image_bytes"],
            protocol=protocol,
        )


def test_expanded_assessment_receipt_requires_explicit_protocol_and_keeps_unknowns():
    protocol = assessment_protocol()
    p = packet(20, 1024**2)
    chunk = r.plan_chunks(p, dense=True, protocol=protocol)[0]
    document = assessment(p, chunk)
    document["scene"] = "unknown"
    document["actors"][0]["identity_supported"] = False
    document["events"][0]["actor_id"] = None
    document["events"][0]["side"] = "unknown"
    document["events"][1]["actor_id"] = None
    document["events"][-1]["evidence"] = "unknown"
    document["unresolved_gaps"] = [{"interval": [8, 9], "reason": "source occlusion"}]
    for row in document["frame_states"]:
        row["scene"] = "unknown"
    original = copy.deepcopy(document)
    execution = receipt(document, chunk)
    r.validate_assessment(
        document,
        p,
        chunk,
        execution,
        stage="dense",
        stream="independent_a",
        protocol=protocol,
    )
    assert document == original
    assert not any(document["eligibility"].values())
    with pytest.raises(ValueError):
        r.validate_assessment(
            document, p, chunk, execution, stage="dense", stream="independent_a"
        )
    changed = copy.deepcopy(execution)
    changed["image_bytes"] -= 1
    with pytest.raises(ValueError):
        r.validate_assessment(
            document,
            p,
            chunk,
            changed,
            stage="dense",
            stream="independent_a",
            protocol=protocol,
        )


@pytest.mark.parametrize("stage", ["overview", "dense"])
@pytest.mark.parametrize("version", [3, 4])
def test_dense_reuse_protocol_refuses_new_preparation_before_admission_or_decode(
    tmp_path, monkeypatch, stage, version
):
    import time

    from badminton import config, jobs
    from badminton.storage import Store

    root = tmp_path / "generated"
    data = root / "data/processed"
    Store(data)
    monkeypatch.setattr(config, "ROOT", root)
    monkeypatch.setattr(config, "DATA", data)
    monkeypatch.setattr(config, "WEIGHTS", root / "models/weights")
    for name in r.CREDENTIALS:
        monkeypatch.delenv(name, raising=False)
    protocol = assessment_protocol() if version == 3 else transport_protocol()
    context_path = root / ".cache/context.json"
    context_path.parent.mkdir()
    context_path.write_bytes(
        encoded({"task": protocol["task"], "inputs": protocol["sources"]})
    )
    stamp = root / ".cache/timestamp.json"
    stamp.write_bytes(
        encoded(
            {
                "context_sha256": file_hash(context_path),
                "url": f"https://github.com/Ken0u/badminton-match-analyzer/issues/{protocol['task']}#issuecomment-0",
                "published_at": time.time(),
            }
        )
    )
    monkeypatch.setattr(r, "load_protocol", lambda path: protocol)
    monkeypatch.setattr(r, "verify_context", lambda checkout, context: None)

    def forbidden(*args, **kwargs):
        pytest.fail("Reuse authorization must not start native preparation")

    monkeypatch.setattr(jobs, "run_local_job", forbidden)
    monkeypatch.setattr(r, "extract_frames", forbidden)
    output = root / f".cache/rally210-source-only-v1/{stage}-forbidden"
    with pytest.raises(ValueError, match="forbids new native preparation"):
        r.run_preparation(
            root,
            root,
            output,
            context_path,
            file_hash(context_path),
            stamp,
            stage=stage,
        )
    assert not output.exists()
    assert Store(data).jobs() == []


@pytest.fixture
def generated_dense_reuse(tmp_path, monkeypatch):
    """Real generated PNG/hash/Store checks, with synthetic protocol freezing.

    Only exact repository protocol constants and current consumer freezing are
    substituted. No source media is decoded, and no labels or research inputs
    are opened. The archived producer is deliberately expired.
    """
    import time

    from badminton.storage import Store
    from PIL import Image

    root = tmp_path / "generated"
    inputs = root / ".cache/inputs"
    output = root / ".cache/rally208-source-only-v1/dense-v1"
    output.mkdir(parents=True)
    sources, packets = [], {}
    bounds = {"start_frame": 5, "end_frame": 10}
    for sid in r.SOURCE_IDS:
        folder = inputs / sid
        folder.mkdir(parents=True)
        # Hash-only original-source validation does not decode this synthetic file.
        (folder / "source.mp4").write_bytes(
            b"generated source identity " + sid.encode()
        )
        census = clock(25)
        census["source_sha256"] = file_hash(folder / "source.mp4")
        (folder / "clock.json").write_bytes(encoded(census))
        source_packet = {
            "source_id": sid,
            "source_sha256": census["source_sha256"],
            "clock_sha256": file_hash(folder / "clock.json"),
            "eligibility": dict(r.ELIGIBILITY),
        }
        (folder / "packet.json").write_bytes(encoded(source_packet))
        sources.append(
            {
                **{
                    k: source_packet[k]
                    for k in ("source_id", "source_sha256", "clock_sha256")
                },
                "packet_sha256": file_hash(folder / "packet.json"),
                "native_frame_count": 25,
            }
        )
        members = r.dense_memberships(census, bounds)
        rows = []
        for member in members:
            native = census["frames"][member["frame"]]
            path = output / f"images/{sid}/{native['frame']:09d}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (32, 24), (native["frame"], 0, 0)).save(path)
            rows.append(
                {
                    **native,
                    "scene": "unknown",
                    "camera_view": "unreviewed",
                    "image": {
                        "path": path.relative_to(output).as_posix(),
                        "sha256": file_hash(path),
                        "bytes": path.stat().st_size,
                    },
                }
            )
        packets[sid] = {
            **source_packet,
            "memberships": members,
            "frames": rows,
            "stage": "dense",
        }
    archived = {"task": 208, "inputs": sources, "deadline": 0}
    (output / "context.json").write_bytes(encoded(archived))
    archived_sha = file_hash(output / "context.json")
    for sid, p in packets.items():
        p["context_sha256"] = archived_sha
        (output / f"{sid}.packet.json").write_bytes(encoded(p))
    states = {
        sid: {"status": "provisional", "bounds": bounds, "complete_reference": False}
        for sid in r.SOURCE_IDS
    }
    base = output.parent
    evidence = base / "generated-assessment.json"
    evidence.write_bytes(encoded({"generated": True}))
    (base / "dense-selection-v1.json").write_bytes(
        encoded(
            {
                "sources": states,
                "assessment_seals": {evidence.name: file_hash(evidence)},
            }
        )
    )
    (base / "screening-sealed-v1.json").write_bytes(encoded({"sources": states}))
    slots = {
        "sources": [
            {"source_id": sid, "status": "unavailable", "complete_reference": False}
            for sid in r.SOURCE_IDS
        ],
        "eligibility": dict(r.ELIGIBILITY),
    }
    (output / "slots.json").write_bytes(encoded(slots))
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,psutil;p=psutil.Process();print(json.dumps({'pid':p.pid,'creation_time':p.create_time()}))",
        ],
        capture_output=True,
        check=True,
        timeout=20,
    )
    process = json.loads(child.stdout)
    admission = {
        "job_id": "generated-reuse",
        "context_sha256": archived_sha,
        "process": process,
    }
    (output / "admission.json").write_bytes(encoded(admission))
    summary = {"generated": True}
    Store(root / "data/processed").put_job(
        {
            "id": admission["job_id"],
            "status": "completed",
            "owner_pid": process["pid"],
            "owner_started": process["creation_time"],
            "summary": summary,
        }
    )
    (output / "terminal.json").write_bytes(
        encoded(
            {
                "job_id": admission["job_id"],
                "status": "completed",
                "admission_sha256": file_hash(output / "admission.json"),
                "summary": summary,
                "artifacts": {},
            }
        )
    )
    protocol = assessment_protocol()
    protocol["sources"] = sources
    predecessor = protocol["predecessor"]
    for name, path in (
        ("context_sha256", output / "context.json"),
        ("terminal_sha256", output / "terminal.json"),
        ("selection_sha256", base / "dense-selection-v1.json"),
        ("screening_sha256", base / "screening-sealed-v1.json"),
    ):
        predecessor[name] = file_hash(path)
    predecessor["dense_packets"] = {
        sid: file_hash(output / f"{sid}.packet.json") for sid in r.SOURCE_IDS
    }
    predecessor["native_frames"] = {sid: len(p["frames"]) for sid, p in packets.items()}
    (base / "payload-reservation.json").write_bytes(
        encoded({"image_bytes": predecessor["image_bytes"] - 340760009})
    )
    current = {
        "task": 210,
        "protocol_path": "data/manifests/rally_reference_protocol_v3.json",
        "input_root": str(inputs),
        "inputs": sources,
        "commit": "c" * 40,
        "granted_at": int(time.time()) - 1,
        "deadline": int(time.time()) + 28800,
    }
    checked_contexts = []
    monkeypatch.setattr(r, "load_protocol", lambda path: protocol)
    monkeypatch.setattr(r, "_validate_dense_protocol", lambda doc: None)
    monkeypatch.setattr(
        r, "verify_context", lambda checkout, doc: checked_contexts.append(doc)
    )
    return root, output, current, protocol, checked_contexts


def test_reuse_preserves_expired_producer_and_only_publishes_metadata(
    generated_dense_reuse, monkeypatch
):
    root, original, context, protocol, checked = generated_dense_reuse
    original_files = {
        path.relative_to(root).as_posix(): file_hash(path)
        for path in (root / ".cache").rglob("*")
        if path.is_file()
    }

    def forbidden(*args, **kwargs):
        pytest.fail("Reuse must not decode or copy native source frames")

    monkeypatch.setattr(r, "extract_frames", forbidden)
    result = r.reuse_dense_packets(root, root, context, original)
    assert result["source_slots"] == 2
    assert result["native_frames"] == sum(
        protocol["predecessor"]["native_frames"].values()
    )
    assert result["prior_charged_image_bytes"] == 1347060833
    assert not any(result["eligibility"].values())
    assert checked == [context, context]
    assert {
        path.relative_to(root).as_posix(): file_hash(path)
        for path in (root / ".cache").rglob("*")
        if path.is_file()
    } == original_files


@pytest.mark.parametrize(
    "change",
    [
        "context",
        "terminal",
        "selection",
        "screening",
        "packet",
        "native_png",
        "source",
        "census",
        "evidence",
        "prior_charge",
    ],
)
def test_reuse_rejects_tampered_archived_inputs_without_decode(
    generated_dense_reuse, monkeypatch, change
):
    root, original, context, protocol, _ = generated_dense_reuse
    sid = r.SOURCE_IDS[0]
    paths = {
        "context": original / "context.json",
        "terminal": original / "terminal.json",
        "selection": original.parent / "dense-selection-v1.json",
        "screening": original.parent / "screening-sealed-v1.json",
        "packet": original / f"{sid}.packet.json",
        "native_png": original / f"images/{sid}/000000000.png",
        "source": Path(context["input_root"]) / sid / "source.mp4",
        "census": Path(context["input_root"]) / sid / "clock.json",
        "evidence": original.parent / "generated-assessment.json",
        "prior_charge": original.parent / "payload-reservation.json",
    }
    path = paths[change]
    if change == "prior_charge":
        path.write_bytes(
            encoded({"image_bytes": protocol["predecessor"]["image_bytes"]})
        )
    else:
        path.write_bytes(path.read_bytes() + b"\n")
    monkeypatch.setattr(
        r, "extract_frames", lambda *args, **kwargs: pytest.fail("Unexpected decode")
    )
    with pytest.raises(ValueError):
        r.reuse_dense_packets(root, root, context, original)


def transport_protocol():
    """The separately authorized transport plan, without opening real inputs."""
    return r.load_protocol(
        Path(r.__file__).resolve().parents[2]
        / "data/manifests/rally_reference_protocol_v4.json"
    )


def test_transport_protocol_retains_sources_and_prior_failed_dispatches():
    protocol = transport_protocol()
    previous = assessment_protocol()
    assert (protocol["schema_version"], protocol["task"]) == (4, 212)
    assert protocol["sources"] == previous["sources"]
    assert protocol["selection"] == previous["selection"]
    assert protocol["assessment"] == previous["assessment"]
    assert protocol["payload"]["max_images_per_session"] == 20
    assert protocol["payload"]["max_image_bytes_per_session"] == 9 * 1024**2
    assert protocol["payload"]["max_total_image_bytes"] == 8 * 1024**3
    assert protocol["limits"]["max_output_bytes"] == 8 * 1024**3
    assert protocol["limits"]["task_seconds_from_grant"] == 8 * 3600
    assert protocol["limits"]["max_parallel_assessors"] == 2
    assert protocol["predecessor"]["image_bytes"] == 1400881755
    assert protocol["predecessor"]["complete_references"] == 0
    assert protocol["eligibility"] == r.ELIGIBILITY
    assert not any(protocol["eligibility"].values())
    assert assessment_protocol() == previous
    assert previous["payload"]["max_image_bytes_per_session"] == 32 * 1024**2


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        (None, "schema_version", 3),
        (None, "schema_version", True),
        (None, "task", 210),
        ("payload", "max_images_per_session", 21),
        ("payload", "max_image_bytes_per_session", 32 * 1024**2),
        ("payload", "max_image_bytes_per_session", float(9 * 1024**2)),
        ("payload", "max_total_image_bytes", 8 * 1024**3 + 1),
        ("payload", "max_locally_controlled_encoded_request_bytes", 15 * 1024**2),
        ("payload", "encoded_envelope_reserve_bytes", 1024**2),
        ("limits", "max_output_bytes", 8 * 1024**3 + 1),
        ("limits", "task_seconds_from_grant", 8 * 3600 + 1),
        ("limits", "max_parallel_assessors", 3),
        ("limits", "paid_services", True),
        ("assessment", "chunk_overlap_frames", 1),
        ("assessment", "adjudication", "third_exhaustive_pass"),
        ("predecessor", "image_bytes", 1347060833),
        ("predecessor", "image_bytes", 1400881754),
        ("predecessor", "complete_references", 1),
        ("eligibility", "training_allowed", True),
    ],
)
def test_transport_protocol_rejects_scope_changes_and_downgrade(
    tmp_path, section, key, value
):
    protocol = transport_protocol()
    (protocol if section is None else protocol[section])[key] = value
    path = tmp_path / "changed-v4.json"
    path.write_bytes(encoded(protocol))
    with pytest.raises(ValueError):
        r.load_protocol(path)
    # Bypassing the JSON reader must not weaken the selected protocol either.
    with pytest.raises(ValueError):
        r.plan_chunks(packet(8), dense=True, protocol=protocol)


def test_transport_packing_keeps_every_frame_and_charges_overlap_and_retries():
    protocol = transport_protocol()
    p = packet(26, 1024**2)
    before = copy.deepcopy(p)
    chunks = r.plan_chunks(p, dense=True, protocol=protocol)
    assert [c["frames"] for c in chunks] == [
        list(range(8)),
        list(range(6, 14)),
        list(range(12, 20)),
        list(range(18, 26)),
    ]
    assert {n for c in chunks for n in c["frames"]} == set(range(26))
    assert all(
        left["frames"][-2:] == right["frames"][:2]
        for left, right in itertools.pairwise(chunks)
    )
    assert p == before
    prior = protocol["predecessor"]["image_bytes"]
    assert r.payload_cost(chunks, streams=2, prior_bytes=prior, protocol=protocol) == (
        prior + 64 * 1024**2
    )
    # Charge a failed or replacement dispatch too, even with identical membership.
    assert (
        r.payload_cost(
            [*chunks, chunks[0]], streams=2, prior_bytes=prior, protocol=protocol
        )
        == prior + 80 * 1024**2
    )
    with pytest.raises(ValueError):
        r.payload_cost(chunks, streams=2, prior_bytes=prior - 1, protocol=protocol)
    limit = protocol["payload"]["max_total_image_bytes"]
    assert (
        r.payload_cost(
            chunks, streams=2, prior_bytes=limit - 64 * 1024**2, protocol=protocol
        )
        == limit
    )
    with pytest.raises(ValueError):
        r.payload_cost(
            chunks,
            streams=2,
            prior_bytes=limit - 64 * 1024**2 + 1,
            protocol=protocol,
        )


@pytest.mark.parametrize("size", [0, -1, True, 1.5, "100", None])
def test_transport_packing_rejects_invalid_raw_sizes(size):
    with pytest.raises(ValueError):
        r.plan_chunks(packet(8, size), dense=True, protocol=transport_protocol())


def test_transport_packing_session_boundaries_and_overlap_capacity():
    protocol = transport_protocol()
    assert [
        len(c["frames"])
        for c in r.plan_chunks(packet(21), dense=True, protocol=protocol)
    ] == [20, 3]
    assert (
        r.plan_chunks(packet(1, 9 * 1024**2), dense=True, protocol=protocol)[0][
            "image_bytes"
        ]
        == 9 * 1024**2
    )
    for p in (packet(1, 9 * 1024**2 + 1), packet(4, 4 * 1024**2)):
        with pytest.raises(ValueError):
            r.plan_chunks(p, dense=True, protocol=protocol)
    with pytest.raises(ValueError):
        r.plan_chunks(packet(), dense=True, overlap=1, protocol=protocol)


@pytest.mark.parametrize("sizes", [[1], [1, 2, 3, 4], [1] * 20, [9 * 1024**2]])
def test_transport_cost_rounds_each_original_separately(sizes):
    original = list(sizes)
    cost = r.transport_cost(sizes, protocol=transport_protocol())
    assert cost["base64_image_bytes"] == sum(4 * ((size + 2) // 3) for size in sizes)
    assert cost["reserved_envelope_bytes"] == 2 * 1024**2
    assert cost["estimated_encoded_bytes"] == (cost["base64_image_bytes"] + 2 * 1024**2)
    assert cost["estimated_encoded_bytes"] <= 14 * 1024**2
    assert sizes == original


@pytest.mark.parametrize(
    "sizes",
    [
        [],
        [0],
        [-1],
        [True],
        [1.5],
        ["2"],
        [None],
        [1] * 21,
        [9 * 1024**2 + 1],
        [5 * 1024**2, 5 * 1024**2],
    ],
)
def test_transport_cost_rejects_unapproved_image_payload(sizes):
    with pytest.raises(ValueError):
        r.transport_cost(sizes, protocol=transport_protocol())


@pytest.mark.parametrize("context_bytes", [-1, True, 1.5, "1", None, 2 * 1024**2])
def test_transport_cost_rejects_invalid_or_excessive_context(context_bytes):
    with pytest.raises(ValueError):
        r.transport_cost(
            [1], context_bytes=context_bytes, protocol=transport_protocol()
        )


def test_transport_cost_context_is_inside_reserved_envelope():
    protocol = transport_protocol()
    header = len("data:image/png;base64,".encode("ascii"))
    maximum = 2 * 1024**2 - 20 * header
    empty = r.transport_cost([1] * 20, protocol=protocol)
    full = r.transport_cost([1] * 20, context_bytes=maximum, protocol=protocol)
    assert full["estimated_encoded_bytes"] == empty["estimated_encoded_bytes"]
    with pytest.raises(ValueError):
        r.transport_cost([1] * 20, context_bytes=maximum + 1, protocol=protocol)


@pytest.mark.parametrize("version", [1, 2, 3])
def test_transport_cost_requires_separate_v4_authorization(version):
    protocol = r.load_protocol(
        Path(r.__file__).resolve().parents[2]
        / f"data/manifests/rally_reference_protocol_v{version}.json"
    )
    with pytest.raises(ValueError):
        r.transport_cost([100], protocol=protocol)


def test_transport_cost_rejects_padding_overflow_below_raw_budget():
    # Separate base64 encodings add padding even when raw bytes total exactly 9 MiB.
    with pytest.raises(ValueError, match="transport guard"):
        r.transport_cost([1, 9 * 1024**2 - 1], protocol=transport_protocol())


def test_transport_assessment_requires_exact_cost_and_preserves_unknowns():
    protocol = transport_protocol()
    p = packet()
    chunk = r.plan_chunks(p, dense=True, protocol=protocol)[0]
    document = assessment(p, chunk)
    document["scene"] = "unknown"
    document["events"][1]["family"] = "unknown"
    document["unresolved_gaps"] = [{"interval": [2, 2], "reason": "occlusion"}]
    execution = receipt(document, chunk)
    execution["transport_cost"] = r.transport_cost(
        [100] * 8, context_bytes=301, protocol=protocol
    )
    before = copy.deepcopy(document)
    r.validate_assessment(
        document,
        p,
        chunk,
        execution,
        stage="dense",
        stream="independent_a",
        protocol=protocol,
    )
    assert document == before
    assert not any(document["eligibility"].values())
    for field in execution["transport_cost"]:
        # An otherwise valid receipt cannot understate any encoded payload field.
        changed = copy.deepcopy(execution)
        changed["transport_cost"][field] -= 1
        if field == "context_bytes":
            changed["transport_cost"][field] = -1
        with pytest.raises(ValueError):
            r.validate_assessment(
                document,
                p,
                chunk,
                changed,
                stage="dense",
                stream="independent_a",
                protocol=protocol,
            )
    changed = copy.deepcopy(execution)
    del changed["transport_cost"]
    with pytest.raises(ValueError):
        r.validate_assessment(
            document,
            p,
            chunk,
            changed,
            stage="dense",
            stream="independent_a",
            protocol=protocol,
        )
    changed_chunk = {**chunk, "base64_bytes": chunk["base64_bytes"] - 1}
    with pytest.raises(ValueError):
        r.validate_assessment(
            document,
            p,
            changed_chunk,
            execution,
            stage="dense",
            stream="independent_a",
            protocol=protocol,
        )


def test_transport_context_seals_all_versions_and_immutable_eight_hour_clock(
    tmp_path, monkeypatch
):
    checkout = generated_consumer_checkout(tmp_path, monkeypatch)
    path = checkout / "data/manifests/rally_reference_protocol_v4.json"
    context = r.consumer_context(checkout, path, tmp_path / "inputs", 1700000000)
    assert context["task"] == 212
    assert context["granted_at"] == 1700000000
    assert context["deadline"] == 1700000000 + 8 * 3600
    for n in (1, 2, 3, 4):
        name = f"data/manifests/rally_reference_protocol_v{n}.json"
        assert context["consumers"][name] == file_hash(checkout / name)
    monkeypatch.setattr(r.time, "time", lambda: context["deadline"] - 1)
    r.verify_context(checkout, context)
    extended = copy.deepcopy(context)
    extended["deadline"] += 1
    with pytest.raises(ValueError):
        r.verify_context(checkout, extended)
    monkeypatch.setattr(r.time, "time", lambda: context["deadline"])
    with pytest.raises(ValueError, match="deadline"):
        r.verify_context(checkout, context)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_transport_context_detects_changed_earlier_or_selected_protocol(
    tmp_path, monkeypatch, version
):
    checkout = generated_consumer_checkout(tmp_path, monkeypatch)
    context = r.consumer_context(
        checkout,
        checkout / "data/manifests/rally_reference_protocol_v4.json",
        tmp_path / "inputs",
        1700000000,
    )
    monkeypatch.setattr(r.time, "time", lambda: context["deadline"] - 1)
    path = checkout / f"data/manifests/rally_reference_protocol_v{version}.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        r.verify_context(checkout, context)


@pytest.fixture
def generated_failed_successor(tmp_path, monkeypatch):
    """Synthetic sealed failure evidence; no private attempts or images are read."""
    root = tmp_path / "generated"
    base = root / ".cache/rally210-source-only-v1"
    failures = []
    folders = []
    for ordinal, stream in enumerate(r.STREAMS[:2]):
        folder = base / "dense-assessment-v1" / stream / f"{r.SOURCE_IDS[0]}-000"
        folder.mkdir(parents=True)
        images = [{"frame": n, "sha256": "a" * 64} for n in range(20)]
        (folder / "payload-reservation.json").write_bytes(
            encoded({"images": images, "image_bytes": 26910461})
        )
        (folder / "finish.json").write_bytes(
            encoded(
                {
                    "images": images,
                    "image_bytes": 26910461,
                    "exited": True,
                    "exit_code": 1,
                    "pid": 12345 + ordinal,
                    "creation_time": 1700000000.0,
                    "thread_id": f"generated-{stream}",
                }
            )
        )
        (folder / "start.json").write_bytes(
            encoded({"pid": 12345 + ordinal, "creation_time": 1700000000.0})
        )
        (folder / "events.jsonl").write_bytes(
            b'{"error":"generated oversized request"}\n'
        )
        failures.append(
            {
                "stream": stream,
                "source_id": r.SOURCE_IDS[0],
                "chunk": 0,
                "reservation_sha256": file_hash(folder / "payload-reservation.json"),
                "receipt_sha256": file_hash(folder / "finish.json"),
                "events_sha256": file_hash(folder / "events.jsonl"),
            }
        )
        folders.append(folder)
    aggregate = {
        "task": 210,
        "completed_original_streams": 0,
        "complete_references": 0,
        "successful_assessment_sessions": 0,
        "failures": failures,
        "eligibility": dict(r.ELIGIBILITY),
        "new_attempted_image_bytes": 53820922,
        "prior_charged_image_bytes": 1347060833,
        "cumulative_image_bytes": 1400881755,
    }
    path = base / "final-incomplete-v1.json"
    path.write_bytes(encoded(aggregate))
    predecessor = transport_protocol()["predecessor"]
    predecessor["failed_successor"]["aggregate_sha256"] = file_hash(path)

    def absent(pid):
        raise r.psutil.NoSuchProcess(pid)

    monkeypatch.setattr(r.psutil, "Process", absent)
    return root, predecessor, path, aggregate, folders


def test_transport_predecessor_charges_both_failed_original_dispatches(
    generated_failed_successor,
):
    root, predecessor, _, _, _ = generated_failed_successor
    assert r._failed_successor_bytes(root, predecessor) == 53820922
    assert (
        predecessor["image_bytes_before_failed_successor"] + 53820922
        == (predecessor["image_bytes"])
    )


@pytest.mark.parametrize(
    "change",
    [
        "aggregate",
        "reservation",
        "receipt",
        "events",
        "unexpected_final",
        "start_identity",
        "uncharged_attempt",
        "old_charge",
        "total_charge",
        "failed_charge",
        "success",
        "missing_lane",
    ],
)
def test_transport_predecessor_rejects_changed_or_incomplete_failure_evidence(
    generated_failed_successor, change
):
    root, predecessor, path, aggregate, folders = generated_failed_successor
    if change == "aggregate":
        path.write_bytes(path.read_bytes() + b"\n")
    elif change in ("reservation", "receipt", "events"):
        name = {
            "reservation": "payload-reservation.json",
            "receipt": "finish.json",
            "events": "events.jsonl",
        }[change]
        target = folders[0] / name
        target.write_bytes(target.read_bytes() + b"\n")
    elif change == "unexpected_final":
        (folders[0] / "original-final.json").write_bytes(b"{}\n")
    elif change == "start_identity":
        (folders[0] / "start.json").write_bytes(encoded({"pid": 54321}))
    elif change == "uncharged_attempt":
        extra = path.parent / "uncharged/payload-reservation.json"
        extra.parent.mkdir()
        extra.write_bytes(encoded({"image_bytes": 26910461}))
    else:
        if change == "old_charge":
            aggregate["prior_charged_image_bytes"] -= 1
        elif change == "total_charge":
            aggregate["cumulative_image_bytes"] -= 1
        elif change == "failed_charge":
            aggregate["new_attempted_image_bytes"] -= 1
        elif change == "success":
            aggregate["successful_assessment_sessions"] = 1
        elif change == "missing_lane":
            aggregate["failures"] = aggregate["failures"][:1]
        path.write_bytes(encoded(aggregate))
        # Keep the seal consistent so semantic accounting checks are exercised.
        predecessor["failed_successor"]["aggregate_sha256"] = file_hash(path)
    with pytest.raises(ValueError):
        r._failed_successor_bytes(root, predecessor)


@pytest.mark.parametrize("state", ["same_lifetime", "different_lifetime", "denied"])
def test_transport_predecessor_independently_checks_original_process_lifetime(
    generated_failed_successor, monkeypatch, state
):
    root, predecessor, _, _, _ = generated_failed_successor

    class Process:
        def __init__(self, pid):
            if state == "denied":
                raise r.psutil.AccessDenied(pid)

        def create_time(self):
            return 1700000000.0 if state == "same_lifetime" else 1700000001.0

    monkeypatch.setattr(r.psutil, "Process", Process)
    if state == "different_lifetime":
        assert r._failed_successor_bytes(root, predecessor) == 53820922
    else:
        with pytest.raises(ValueError, match="lifetime"):
            r._failed_successor_bytes(root, predecessor)


def test_unresolved_source_slot_is_retained_without_blocking_other_slot():
    bounds = {"start_frame": 2, "end_frame": 6}
    assert (
        r.screened_bounds(
            {"status": "provisional", "bounds": bounds, "complete_reference": False}
        )
        == bounds
    )
    assert (
        r.screened_bounds(
            {"status": "unresolved", "bounds": None, "complete_reference": False}
        )
        is None
    )
    for row in (
        {"status": "unresolved", "bounds": bounds, "complete_reference": False},
        {"status": "provisional", "bounds": None, "complete_reference": False},
        {"status": "provisional", "bounds": bounds, "complete_reference": True},
    ):
        with pytest.raises(ValueError):
            r.screened_bounds(row)


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


@pytest.mark.parametrize("stage", ["overview", "dense_one_unresolved"])
def test_generated_preparation_entry_admission_and_exclusive_output(
    tmp_path, monkeypatch, stage
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
    if stage == "dense_one_unresolved":
        selection = {
            "screening_sealed": True,
            "context_sha256": file_hash(context_path),
            "sources": {
                ids[0]: {
                    "status": "provisional",
                    "bounds": {"start_frame": 2, "end_frame": 6},
                    "complete_reference": False,
                },
                ids[1]: {
                    "status": "unresolved",
                    "bounds": None,
                    "complete_reference": False,
                },
            },
        }
        (root / ".cache/selection.json").write_bytes(encoded(selection))
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
r.verify_selection=lambda *args:None
stage=sys.argv[3]
r.run_preparation(root,root,out,root/".cache/context.json",file_hash(root/".cache/context.json"),root/".cache/timestamp.json",stage="dense" if stage=="dense_one_unresolved" else "overview",selection_path=root/".cache/selection.json" if stage=="dense_one_unresolved" else None)
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
    command = [sys.executable, str(script), str(root), str(output), stage]
    child = subprocess.run(command, env=env, capture_output=True, timeout=60)
    assert child.returncode == 0, child.stderr.decode()
    assert r.verify_worker(output, root)["original_lifetime_absent"]
    prepared_ids = ids[:1] if stage == "dense_one_unresolved" else ids
    for sid in prepared_ids:
        p = json.loads((output / f"{sid}.packet.json").read_bytes())
        expected = (
            r.dense_memberships(census, {"start_frame": 2, "end_frame": 6})
            if stage == "dense_one_unresolved"
            else r.overview_memberships(census)
        )
        r.verify_packet(p, output, census, expected)
        if stage == "overview":
            assert len(p["memberships"]) == 61 and len(p["frames"]) == 2
    if stage == "dense_one_unresolved":
        assert not (output / f"{ids[1]}.packet.json").exists()
        terminal = json.loads((output / "terminal.json").read_bytes())
        assert terminal["summary"]["sources"] == 2
        assert terminal["summary"]["unresolved_sources"] == [ids[1]]
    repeated = subprocess.run(command, env=env, capture_output=True, timeout=30)
    assert repeated.returncode != 0 and b"exclusive" in repeated.stderr
    with sqlite3.connect(data / "catalog.sqlite3") as db:
        assert db.execute("select count(*) from jobs").fetchone()[0] == 1
