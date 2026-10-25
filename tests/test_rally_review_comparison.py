"""Generated prospective judgments only; never original scientific inputs."""

import copy
import hashlib
from fractions import Fraction

import pytest
from badminton import rally_review_comparison as comparison
from badminton import rally_review_contract as contract
from test_rally_review_contract import (
    event,
    generated_documents,
    generated_plan,
    rebuild_chain,
    with_overlap_entities,
)


def known_documents(plan, lane, *, plan_raw=None, **values):
    docs = generated_documents(plan, plan_raw, lane=lane)
    parsed = [contract.strict_json(raw) for raw in docs]
    for doc in parsed:
        for row in doc["observations"]:
            row.update(camera="unchanged", camera_view="local-view", scene="live")
            row["contact"] = "not_observed"
            row.update(values)
            if row["contact"] in ("observed", "possible"):
                doc["events"].append(event(f"local-{row['frame']}", row["frame"]))
    return rebuild_chain(parsed)


def inputs(**options):
    plan = generated_plan(**options)
    return (
        plan,
        contract.encode_json(plan),
        {lane: known_documents(plan, lane) for lane in comparison.INDEPENDENT},
    )


def check_denominators(result, count):
    assert result["summary"]["expected_native_frames"] == count
    assert len(result["frames"]) == count
    for counts in result["summary"]["field_status_counts"].values():
        assert sum(counts.values()) == count
    assert result["summary"]["complete_references"] == 0
    assert not any(result["summary"]["eligibility"].values())
    assert result["summary"]["assessor_independence"] == "unavailable"
    assert result["summary"]["scientific_acceptance_changed"] is False
    assert result["summary"]["execution_authorized"] is False
    assert result["summary"]["actual_new_scientific_sessions"] == 0
    assert result["summary"]["actual_new_image_bytes"] == 0


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"first": 53, "rotation": 90},
        {"rotation": 270},
        {"times": [Fraction(70) + Fraction(n * n, 20) for n in range(9)]},
        {"count": 1},
    ],
)
def test_consistent_known_labels_keep_complete_native_denominator_without_truth(
    options,
):
    plan, raw, streams = inputs(**options)
    original = copy.deepcopy((raw, streams))
    result = comparison.compare_streams(raw, **streams)
    assert (raw, streams) == original
    check_denominators(result, len(plan["frames"]))
    assert result["coverage"]["expected_frames"] == [f["frame"] for f in plan["frames"]]
    assert result["coverage"]["plan_sha256"] == hashlib.sha256(raw).hexdigest()
    assert not result["source_review_questions"]
    for field in comparison.FIELDS:
        assert result["summary"]["field_status_counts"][field]["agreement"] == len(
            plan["frames"]
        )
    for lane in comparison.INDEPENDENT:
        assert result["streams"][lane] == contract.validate_stream(
            raw, streams[lane], lane
        )


@pytest.mark.parametrize(
    "field,left,right,status",
    [
        ("camera", "change", "unchanged", "disagreement"),
        ("camera", "unknown", "change", "unknown"),
        ("scene", "live", "replay", "disagreement"),
        ("scene", "non_play", "unknown", "unknown"),
        ("scene", "unknown", "unknown", "unknown"),
        ("contact", "observed", "possible", "disagreement"),
        ("contact", "not_observed", "unknown", "unknown"),
        ("contact", "observed", "observed", "agreement"),
        ("contact", "possible", "not_observed", "disagreement"),
    ],
)
def test_field_judgments_are_compared_without_unknown_as_negative(
    field, left, right, status
):
    plan, raw, _ = inputs()
    streams = {
        lane: known_documents(plan, lane, **{field: value})
        for lane, value in zip(comparison.INDEPENDENT, (left, right))
    }
    result = comparison.compare_streams(raw, **streams)
    check_denominators(result, 9)
    assert result["summary"]["field_status_counts"][field][status] == 9
    for row in result["frames"]:
        compared = row["fields"][field]
        assert compared["independent_comparison"]["status"] == status
        assert compared["lanes"]["independent_a"]["reported_values"] == [left]
        assert compared["lanes"]["independent_b"]["reported_values"] == [right]
    assert "physical absence" in " ".join(result["summary"]["limitations"])


@pytest.mark.parametrize("right", ["unknown", "replay"])
def test_overlap_conflicts_preserve_every_occurrence_and_all_applicable_flags(right):
    plan, raw, streams = inputs()
    docs = [contract.strict_json(doc) for doc in streams["independent_a"]]
    overlap = plan["batches"][1]["overlap_frame"]
    docs[1]["observations"][0]["scene"] = right
    streams["independent_a"] = rebuild_chain(docs)
    result = comparison.compare_streams(raw, **streams)
    check_denominators(result, 9)
    field = next(row for row in result["frames"] if row["frame"] == overlap)["fields"][
        "scene"
    ]
    assert field["independent_comparison"]["status"] == "overlap_conflict"
    assert "overlap_conflict_a" in field["independent_comparison"]["flags"]
    assert ("unknown_a" in field["independent_comparison"]["flags"]) == (
        right == "unknown"
    )
    judgment = field["lanes"]["independent_a"]
    assert judgment["reported_values"] == sorted(["live", right])
    assert len(judgment["occurrences"]) == 2
    assert {o["pointer"]["batch_index"] for o in judgment["occurrences"]} == {0, 1}
    assert result["summary"]["field_status_counts"]["scene"]["agreement"] == 8
    assert result["summary"]["field_status_counts"]["scene"]["overlap_conflict"] == 1
    streams["independent_b"] = []
    missing = comparison.compare_streams(raw, **streams)
    field = next(row for row in missing["frames"] if row["frame"] == overlap)["fields"][
        "scene"
    ]
    assert field["independent_comparison"]["status"] == "missing"
    assert {"missing_b", "overlap_conflict_a"} <= set(
        field["independent_comparison"]["flags"]
    )


@pytest.mark.parametrize("a_count,b_count", [(0, 0), (1, 0), (1, 2), (2, 1)])
def test_prefixes_retain_expected_frames_and_explicit_missing_judgments(
    a_count, b_count
):
    _plan, raw, streams = inputs(first=40)
    streams["independent_a"] = streams["independent_a"][:a_count]
    streams["independent_b"] = streams["independent_b"][:b_count]
    result = comparison.compare_streams(raw, **streams)
    check_denominators(result, 9)
    assert result["coverage"]["expected_frames"] == list(range(40, 49))
    shared = set()
    for lane in comparison.INDEPENDENT:
        observed = {
            row["frame"]
            for doc in streams[lane]
            for row in contract.strict_json(doc)["observations"]
        }
        shared = observed if lane == "independent_a" else shared & observed
        assert result["summary"]["lane_coverage"][lane]["missing_native_frames"] == (
            9 - len(observed)
        )
    assert result["summary"]["field_status_counts"]["scene"]["missing"] == 9 - len(
        shared
    )


def test_unavailable_plan_preserves_original_denominator_and_reasons():
    plan = generated_plan(unavailable=True, first=90)
    result = comparison.compare_streams(contract.encode_json(plan), [], [])
    check_denominators(result, 9)
    assert result["summary"]["status"] == "unavailable"
    assert result["coverage"]["expected_frames"] == list(range(90, 99))
    for stream in result["streams"].values():
        assert stream["summary"]["reason"] == plan["summary"]["reason"]
    assert result["summary"]["field_status_counts"]["contact"]["missing"] == 9


def test_adjudication_is_separate_and_never_votes_or_changes_independent_comparison():
    plan, raw, streams = inputs()
    streams["independent_b"] = known_documents(plan, "independent_b", scene="replay")
    original = comparison.compare_streams(raw, **streams)
    for value in ("live", "replay", "unknown"):
        adjudication = known_documents(plan, "source_adjudication", scene=value)
        result = comparison.compare_streams(
            raw, **streams, source_adjudication=adjudication
        )
        assert (
            result["summary"]["field_status_counts"]
            == original["summary"]["field_status_counts"]
        )
        assert result["source_review_questions"] == original["source_review_questions"]
        for before, after in zip(original["frames"], result["frames"]):
            for field in comparison.FIELDS:
                assert (
                    after["fields"][field]["independent_comparison"]
                    == before["fields"][field]["independent_comparison"]
                )
        assert result["streams"]["source_adjudication"]["documents"]
        check_denominators(result, 9)


def test_equal_local_ids_keep_qualified_actor_event_boundary_and_view_variants():
    plan, raw, _ = inputs(count=7)
    streams = {}
    for lane in (*comparison.INDEPENDENT, "source_adjudication"):
        docs, _ = with_overlap_entities(plan, generated_documents(plan, lane=lane))
        for doc in docs:
            doc["events"][0].update(family="drive", side="backhand")
        streams[lane] = rebuild_chain(docs)
    result = comparison.compare_streams(raw, **streams)
    variants = result["document_local_variants"]
    assert len(variants["events"]) == len(variants["actors"]) == 6
    assert len(variants["boundaries"]) == 6
    assert len({e["definition"]["event_id"] for e in variants["events"]}) == 1
    assert len({e["definition"]["actor_id"] for e in variants["actors"]}) == 1
    assert (
        len(
            {
                (e["pointer"]["lane"], e["pointer"]["document_sha256"])
                for e in variants["events"]
            }
        )
        == 6
    )
    assert all(e["definition"]["family"] == "drive" for e in variants["events"])
    assert all(e["definition"]["side"] == "backhand" for e in variants["events"])
    assert result["summary"]["event_variants"] == 6
    assert result["summary"]["actor_variants"] == 6
    assert any(row["actor_ids"] == ["local-person"] for row in variants["camera_views"])
    check_denominators(result, 7)


@pytest.mark.parametrize("change", ["lane", "source", "clock", "chain", "field"])
def test_one_invalid_stream_rejects_the_combined_comparison(change):
    _, raw, streams = inputs()
    docs = [contract.strict_json(doc) for doc in streams["independent_b"]]
    if change == "lane":
        docs[0]["lane"] = "independent_a"
    elif change == "source":
        docs[0]["source"]["source_sha256"] = "f" * 64
    elif change == "clock":
        docs[0]["source"]["clock_sha256"] = "f" * 64
    elif change == "field":
        docs[0]["observations"][0]["extra"] = "unsupported"
    streams["independent_b"] = rebuild_chain(docs)
    if change == "chain":
        streams["independent_b"][0] += b"\n"
    original = copy.deepcopy(streams)
    with pytest.raises(ValueError):
        comparison.compare_streams(raw, **streams)
    assert streams == original


def test_raw_identity_and_bundle_selection_remain_exact():
    plan, raw, streams = inputs()
    with pytest.raises(ValueError):
        comparison.compare_streams(raw + b"\n", **streams)
    bundle_raw = contract.encode_json({"generated": plan})
    rebound = {
        lane: known_documents(plan, lane, plan_raw=bundle_raw)
        for lane in comparison.INDEPENDENT
    }
    with pytest.raises(ValueError):
        comparison.compare_streams(bundle_raw, **rebound)
    result = comparison.compare_streams(bundle_raw, **rebound, source_id="generated")
    assert result["coverage"]["plan_sha256"] == hashlib.sha256(bundle_raw).hexdigest()
    assert all(
        stream["summary"]["selection_scope"]
        == {
            "plan_container": "bundle",
            "selected_source_count": 1,
            "supplied_source_count": 1,
        }
        for stream in result["streams"].values()
    )
    for lane in comparison.INDEPENDENT:
        assert (
            result["streams"][lane]["documents"][0]["sha256"]
            == hashlib.sha256(rebound[lane][0]).hexdigest()
        )


@pytest.mark.parametrize("bad", [None, (), [b"{}"], [b'{"x":1,"x":2}'], [b'{"x":NaN}']])
def test_missing_or_malformed_explicit_stream_is_not_silently_reinterpreted(bad):
    _, raw, streams = inputs()
    with pytest.raises(ValueError):
        comparison.compare_streams(raw, bad, streams["independent_b"])


def test_comparison_is_deterministic_and_preserves_protocol_binding():
    _, raw, streams = inputs()
    result = comparison.compare_streams(raw, **streams)
    assert comparison.compare_streams(raw, **streams) == result
    assert comparison.PROTOCOL_SHA256 == contract.fingerprint(comparison.PROTOCOL)
    assert comparison.PROTOCOL["contract_sha256"] == contract.CONTRACT_SHA256
    assert result["summary"]["protocol_sha256"] == comparison.PROTOCOL_SHA256
