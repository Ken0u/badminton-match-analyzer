"""Compare prospective review judgments without accepting scientific source truth.

Only original JSON bytes are consumed. Frame agreement concerns supplied labels,
never accuracy, assessor independence, physical absence or contact cardinality.
"""

from __future__ import annotations

import copy
from collections import Counter

from . import rally_review_contract as contract

FIELDS = ("camera", "scene", "contact")
STATUSES = ("missing", "overlap_conflict", "unknown", "agreement", "disagreement")
INDEPENDENT = ("independent_a", "independent_b")
ADJUDICATION = "source_adjudication"
PROTOCOL = {
    "schema_version": 1,
    "kind": "prospective_rally_review_comparison",
    "contract_sha256": contract.CONTRACT_SHA256,
    "fields": list(FIELDS),
    "statuses": list(STATUSES),
    "rules": {
        "inputs": "Exact original plan bytes and explicit chronological lane document bytes; unchanged structural validation precedes comparison.",
        "denominator": "Every expected native frame is retained, including missing prefixes and unavailable plans. One exclusive status per field/frame; separate flags are non-additive.",
        "overlap": "All original overlap occurrences remain. Multiple distinct values, including known/unknown mixtures, conflict; no vote or favorable selection.",
        "status": "Missing takes precedence, then overlap conflict, then unknown, then consistent known agreement/disagreement. All applicable missing/conflict/unknown flags remain visible.",
        "agreement": "Two lanes must each have exactly one consistent known value. Equal labels establish neither scientific truth nor assessor independence. Not-observed is a reported label, not physical absence.",
        "identity": "Camera views, actors, events, boundaries and correspondence stay document-local variants with qualified original-byte pointers; equal strings/interval overlap imply no global identity or event match.",
        "adjudication": "Optional adjudication remains a separate stream. It never overwrites, votes on, resolves or changes independent comparison counts.",
        "authority": "No image inspection, assessor provenance, execution authority, contact/family/identity score, scientific acceptance or eligibility follows from comparison.",
    },
}
PROTOCOL_SHA256 = contract.fingerprint(PROTOCOL)
LIMITATIONS = [
    "Agreement compares supplied judgments; accuracy and assessor independence are unavailable.",
    "Unknown and not-observed do not prove physical absence.",
    "Document-local identities and event mentions are not merged or matched.",
    "Separate adjudication does not resolve original disagreements automatically.",
    "No scientific input access, execution authorization or acceptance is supplied.",
]


def _pointer(lane, item, *, index=None):
    result = {
        "lane": lane,
        "batch_index": item["document"]["batch_index"],
        "document_sha256": item["sha256"],
    }
    if index is not None:
        result["observation_index"] = index
    return result


def _observations(lane, stream):
    indexed = {}
    for item in stream["documents"]:
        for index, observation in enumerate(item["document"]["observations"]):
            indexed.setdefault(observation["frame"], []).append(
                {"pointer": _pointer(lane, item, index=index), "value": observation}
            )
    return indexed


def _judgment(occurrences, field):
    variants = [
        {"pointer": row["pointer"], "value": row["value"][field]} for row in occurrences
    ]
    values = sorted({row["value"] for row in variants})
    state = (
        "missing"
        if not variants
        else "overlap_conflict"
        if len(values) != 1
        else "unknown"
        if values == ["unknown"]
        else "known"
    )
    return {
        "state": state,
        "value": values[0] if state == "known" else None,
        "reported_values": values,
        "contains_unknown": "unknown" in values,
        "occurrences": variants,
    }


def _pair(left, right):
    flags = []
    for name, judgment in (("a", left), ("b", right)):
        if judgment["state"] in ("missing", "overlap_conflict"):
            flags.append(judgment["state"] + "_" + name)
        if judgment["contains_unknown"]:
            flags.append("unknown_" + name)
    for state in ("missing", "overlap_conflict", "unknown"):
        if state in (left["state"], right["state"]):
            return {"status": state, "flags": flags}
    status = "agreement" if left["value"] == right["value"] else "disagreement"
    return {"status": status, "flags": flags}


def _variants(streams):
    result = {"actors": [], "events": [], "boundaries": [], "camera_views": []}
    for lane, stream in streams.items():
        for item in stream["documents"]:
            doc, pointer = item["document"], _pointer(lane, item)
            for kind in ("actors", "events"):
                for definition in doc[kind]:
                    result[kind].append(
                        {
                            "pointer": dict(pointer),
                            "definition": copy.deepcopy(definition),
                        }
                    )
            result["boundaries"].append(
                {
                    "pointer": dict(pointer),
                    "definition": copy.deepcopy(doc["boundaries"]),
                }
            )
            for index, observation in enumerate(doc["observations"]):
                result["camera_views"].append(
                    {
                        "pointer": _pointer(lane, item, index=index),
                        "frame": observation["frame"],
                        "camera_view": observation["camera_view"],
                        "actor_ids": list(observation["actor_ids"]),
                    }
                )
    return result


def compare_streams(
    plan_raw: bytes,
    independent_a: list[bytes],
    independent_b: list[bytes],
    source_adjudication: list[bytes] | None = None,
    *,
    source_id=None,
):
    """Return complete private variants and aggregate comparison counts.

    Structural completion does not authorize or certify any source assessment.
    Both independent streams are explicit; an empty prefix is valid missing data.
    """
    inputs = dict(zip(INDEPENDENT, (independent_a, independent_b)))
    if source_adjudication is not None:
        inputs[ADJUDICATION] = source_adjudication
    streams = {
        lane: contract.validate_stream(plan_raw, raw, lane, source_id=source_id)
        for lane, raw in inputs.items()
    }
    coverage = streams[INDEPENDENT[0]]["coverage"]
    identity_keys = ("source", "plan_sha256", "expected_frames")
    contract.require(
        all(
            all(stream["coverage"][key] == coverage[key] for key in identity_keys)
            for stream in streams.values()
        ),
        "Review streams must share exact source/clock/plan/native coverage",
    )
    indexed = {lane: _observations(lane, stream) for lane, stream in streams.items()}
    counts = {field: Counter(dict.fromkeys(STATUSES, 0)) for field in FIELDS}
    flag_counts = {field: Counter() for field in FIELDS}
    frames, questions = [], []
    for frame in coverage["expected_frames"]:
        fields = {}
        for field in FIELDS:
            judgments = {
                lane: _judgment(rows.get(frame, []), field)
                for lane, rows in indexed.items()
            }
            comparison = _pair(*(judgments[lane] for lane in INDEPENDENT))
            counts[field][comparison["status"]] += 1
            flag_counts[field].update(comparison["flags"])
            fields[field] = {"independent_comparison": comparison, "lanes": judgments}
            if comparison["status"] != "agreement":
                questions.append(
                    {"frame": frame, "field": field, **copy.deepcopy(comparison)}
                )
        frames.append({"frame": frame, "fields": fields})
    variants = _variants(streams)
    summary = {
        "schema_version": 1,
        "protocol_sha256": PROTOCOL_SHA256,
        "status": "unavailable"
        if streams[INDEPENDENT[0]]["summary"]["status"] == "unavailable"
        else "compared",
        "expected_native_frames": len(coverage["expected_frames"]),
        "field_status_counts": {key: dict(value) for key, value in counts.items()},
        "field_flag_counts_non_additive": {
            key: dict(value) for key, value in flag_counts.items()
        },
        "lane_coverage": {
            lane: {
                key: stream["summary"][key]
                for key in (
                    "status",
                    "expected_documents",
                    "received_documents",
                    "observed_native_frames",
                    "missing_native_frames",
                    "observation_occurrences",
                )
            }
            for lane, stream in streams.items()
        },
        "adjudication_provided": source_adjudication is not None,
        "event_variants": len(variants["events"]),
        "actor_variants": len(variants["actors"]),
        "boundary_variants": len(variants["boundaries"]),
        "frame_field_questions": len(questions),
        "assessor_independence": "unavailable",
        "complete_references": 0,
        "eligibility": dict(contract.temporal.ELIGIBILITY),
        "scientific_acceptance_changed": False,
        "execution_authorized": False,
        "actual_new_scientific_sessions": 0,
        "actual_new_image_bytes": 0,
        "limitations": list(LIMITATIONS),
    }
    return {
        "summary": summary,
        "coverage": {key: copy.deepcopy(coverage[key]) for key in identity_keys},
        "frames": frames,
        "source_review_questions": questions,
        "document_local_variants": variants,
        "streams": streams,
    }
