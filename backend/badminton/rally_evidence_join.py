"""Join sealed source occurrences by native ordinal, without resolving labels.

The caller must verify raw input hashes and historical execution evidence before
calling this module. This module neither reads files nor assesses images. Its
private ledger is a review index, structurally separate from annotation truth.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
import re
from collections import Counter

from . import rally_reference_diagnostics as census
from . import rally_temporal_context as temporal
from .shuttle_supervision import encoded

LANES = census.LANES
ELIGIBILITY = temporal.ELIGIBILITY
SHA = re.compile(r"[0-9a-f]{64}\Z")
SOURCE_KEYS = ("source_id", "source_sha256", "clock_sha256")
FRAME_KEYS = (
    "frame",
    "pts",
    "time_base",
    "time_s",
    "rotation",
    "source_size",
    "display_size",
    "orientation_error",
    "corrupt",
    "image",
)
PROVENANCE_KEYS = (
    "original_path",
    "original_sha256",
    "receipt_path",
    "receipt_sha256",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _json(value):
    """Reject nonfinite values recursively, including exponent overflow."""
    if isinstance(value, dict):
        require(all(type(k) is str for k in value), "JSON object keys must be text")
        for item in value.values():
            _json(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _json(item)
    elif type(value) is float:
        require(math.isfinite(value), "Nonfinite JSON value")
    else:
        require(type(value) in (str, int, bool, type(None)), "Non-JSON value")
    return value


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    return _json(json.loads(raw, object_pairs_hook=pairs))


def fingerprint(value):
    return hashlib.sha256(encoded(_json(value))).hexdigest()


def _same(left, right):
    # Canonical JSON comparison distinguishes bool/int and ignores dict order.
    return encoded(_json(left)) == encoded(_json(right))


def _sha(value):
    require(type(value) is str and SHA.fullmatch(value) is not None, "SHA256 required")
    return value


def _integer(value, minimum=0):
    require(type(value) is int and value >= minimum, "Exact integer required")
    return value


def _text(value):
    require(type(value) is str and bool(value.strip()), "Nonempty text required")
    return value


def _provenance(value):
    require(set(value) == set(PROVENANCE_KEYS), "Exact original provenance required")
    for name in PROVENANCE_KEYS:
        (_sha if name.endswith("sha256") else _text)(value[name])
    require(
        value["original_path"] != value["receipt_path"],
        "Distinct original files required",
    )
    return copy.deepcopy(value)


def _reference(granularity, lane, index, section, row, provenance, document):
    return {
        "granularity": granularity,
        "lane": lane,
        "document": index,
        "section": section,
        "row": row,
        **copy.deepcopy(provenance),
        "parsed_document_sha256": fingerprint(document),
    }


def _question(kind, packet, interval, references, requirement, packet_sha256):
    return {
        "kind": kind,
        **{k: packet[k] for k in SOURCE_KEYS},
        "frame_range": list(interval),
        "packet_record": {
            "original_packet_sha256": packet_sha256,
            "section": "frames",
            "inclusive_rows": [n - packet["frames"][0]["frame"] for n in interval],
        },
        "occurrences": copy.deepcopy(references),
        "requirement": requirement,
        "status": "new_independent_source_evidence_required",
        "truth_resolved": False,
    }


def _native(packet, streams, ledger):
    require(set(streams) == set(LANES), "All three native lanes required")
    require(set(ledger) == {"provenance", "streams"}, "Original native ledger required")
    require(
        set(ledger["provenance"]) == set(ledger["streams"]) == set(LANES),
        "All original provenance/ledger lanes required",
    )
    images = {r["frame"]: r["image"] for r in packet["frames"]}
    rows, documents, summaries = {}, {}, {}
    for lane in LANES:
        require(type(streams[lane]) is list, "Explicit native document list required")
        provenance = ledger["provenance"][lane]
        require(
            type(provenance) is list and len(provenance) == len(streams[lane]),
            "Original document/provenance count differs",
        )
        documents[lane] = []
        for index, pair in enumerate(streams[lane]):
            require(
                isinstance(pair, (list, tuple)) and len(pair) == 2,
                "Original document/receipt pair required",
            )
            doc, receipt = pair
            prov = _provenance(provenance[index])
            require(
                doc.get("source_id") == packet["source_id"]
                and doc.get("stage") == "dense"
                and doc.get("stream") == lane,
                "Native source/lane mismatch",
            )
            require(
                _same(doc.get("eligibility"), ELIGIBILITY), "Native eligibility changed"
            )
            require(
                type(receipt.get("exit_code")) is int
                and receipt["exit_code"] == 0
                and receipt.get("exited") is True
                and receipt.get("original_resolution_viewing") is True
                and doc.get("independent_source_only") is True
                and _text(doc.get("session_id")) == _text(receipt.get("session_id"))
                and _text(receipt.get("thread_id"))
                and receipt.get("segment_sha256") == fingerprint(doc),
                "Native canonical document/receipt identity differs",
            )
            inspected = doc["inspected_frames"]
            require(
                type(inspected) is list and bool(inspected),
                "Explicit native inspections required",
            )
            for item in inspected:
                n = _integer(item["frame"])
                require(
                    n in images
                    and images[n] is not None
                    and item["sha256"] == images[n]["sha256"],
                    "Original native image identity differs",
                )
            require(
                _same(receipt.get("images"), inspected),
                "Original receipt images differ",
            )
            require(
                type(receipt.get("image_bytes")) is int
                and receipt["image_bytes"]
                == sum(images[r["frame"]]["bytes"] for r in inspected),
                "Original image byte count differs",
            )
            for item in doc["frame_states"]:
                _integer(item["frame"])
            documents[lane].append(
                {
                    "document": copy.deepcopy(doc),
                    "receipt": copy.deepcopy(receipt),
                    "provenance": prov,
                }
            )
        summary, rebuilt = census.census_lane(streams[lane], native_frames=images)
        require(
            _same(rebuilt, ledger["streams"][lane]),
            "Sealed native occurrence ledger differs",
        )
        rows[lane], summaries[lane] = rebuilt, summary
    return rows, documents, summaries


def _coarse(packet, manifest, streams):
    require(set(streams) == set(LANES), "All three coarse lanes required")
    require(
        type(manifest.get("schema_version")) is int and manifest["schema_version"] == 1,
        "Original gallery schema required",
    )
    require(
        _same(manifest["plan"], temporal.sample_plan(packet)),
        "Coarse source/clock/sample plan differs",
    )
    samples = manifest["plan"]["samples"]
    require(
        len(manifest["sheets"]) == math.ceil(len(samples) / 16),
        "Exact coarse sheet count required",
    )
    for index, sheet in enumerate(manifest["sheets"]):
        require(
            sheet["path"] == f"sheet-{index:03d}.png"
            and sheet["frames"]
            == [s["frame"] for s in samples[index * 16 : (index + 1) * 16]]
            and _same(sheet["size"], list(temporal.SHEET)),
            "Coarse sheet membership differs",
        )
        _sha(sheet["sha256"])
        _integer(sheet["bytes"], 1)
    result = {}
    for lane in LANES:
        item = streams[lane]
        require(
            set(item) == {"document", "receipt", "provenance"},
            "Original coarse document/receipt/provenance required",
        )
        prov = _provenance(item["provenance"])
        doc = temporal.validate_assessment(
            item["document"], manifest, item["receipt"], lane
        )
        result[lane] = {
            "document": copy.deepcopy(doc),
            "receipt": copy.deepcopy(item["receipt"]),
            "provenance": prov,
        }
    return result


def join_source(
    packet,
    native_streams,
    native_ledger,
    temporal_manifest,
    temporal_streams,
    *,
    expected_source,
):
    """Return aggregate diagnostics and a private occurrence-preserving join.

    Raw file hashes and actual process/Store exits are a caller prerequisite.
    This function checks canonical records and reproduces the sealed census;
    it never calls historical acceptance or resolves scientific uncertainty.
    """
    inputs = (
        packet,
        native_streams,
        native_ledger,
        temporal_manifest,
        temporal_streams,
        expected_source,
    )
    before = fingerprint(inputs)

    def question(kind, original, interval, references, requirement):
        return _question(
            kind,
            original,
            interval,
            references,
            requirement,
            expected_source["packet_sha256"],
        )

    for key in SOURCE_KEYS:
        (_text if key == "source_id" else _sha)(expected_source[key])
        require(
            packet[key] == expected_source[key],
            "Original source/clock identity differs",
        )
    _sha(expected_source["packet_sha256"])
    require(
        len(packet["frames"]) == _integer(expected_source["native_frame_count"], 1),
        "Native denominator differs",
    )
    plan = temporal.sample_plan(packet)
    native, documents, native_summaries = _native(packet, native_streams, native_ledger)
    coarse = _coarse(packet, temporal_manifest, temporal_streams)
    frames = {
        row["frame"]: {
            **{k: packet[k] for k in SOURCE_KEYS},
            **{k: copy.deepcopy(row[k]) for k in FRAME_KEYS},
            "available": row["image"] is not None
            and row["corrupt"] is False
            and row["orientation_error"] is None,
            "sampled": False,
            "native": {lane: [] for lane in LANES},
            "coarse": {lane: [] for lane in LANES},
            "scene_comparisons": [],
        }
        for row in packet["frames"]
    }
    questions, document_refs = [], []
    event_occurrences, actor_occurrences = {}, {}
    for lane in LANES:
        event_occurrences[lane], actor_occurrences[lane] = [], []
        for index, original in enumerate(documents[lane]):
            doc, prov = original["document"], original["provenance"]
            document_refs.append(
                _reference("native", lane, index, "document", None, prov, doc)
            )
        for item in native[lane]["frames"]:
            original = documents[lane][item["document"]]
            reference = _reference(
                "native",
                lane,
                item["document"],
                "frame_states",
                item["row"],
                original["provenance"],
                original["document"],
            )
            frames[item["state"]["frame"]]["native"][lane].append(
                {"reference": reference, "state": copy.deepcopy(item["state"])}
            )
        for section, field, target in (
            ("events", "event", event_occurrences),
            ("actors", "definition", actor_occurrences),
        ):
            for item in native[lane][section]:
                original = documents[lane][item["document"]]
                reference = _reference(
                    "native",
                    lane,
                    item["document"],
                    section,
                    item["row"],
                    original["provenance"],
                    original["document"],
                )
                target[lane].append(
                    {"reference": reference, field: copy.deepcopy(item[field])}
                )
        original = coarse[lane]
        doc, prov = original["document"], original["provenance"]
        document_refs.append(_reference("coarse", lane, 0, "document", None, prov, doc))
        for index, (state, sample) in enumerate(
            zip(doc["frame_states"], plan["samples"], strict=True)
        ):
            row = frames[state["frame"]]
            row["sampled"] = True
            row["coarse"][lane].append(
                {
                    "reference": _reference(
                        "coarse", lane, 0, "frame_states", index, prov, doc
                    ),
                    "state": copy.deepcopy(state),
                    "sample": copy.deepcopy(sample),
                    "local_actor_references": [
                        _reference("coarse", lane, 0, "actors", ordinal, prov, doc)
                        for ordinal, actor in enumerate(doc["actors"])
                        if actor["actor_id"] in state["actor_ids"]
                    ],
                }
            )

    bounds = [packet["frames"][0]["frame"], packet["frames"][-1]["frame"]]
    questions.append(
        question(
            "whole_window_context",
            packet,
            bounds,
            document_refs,
            "Independently inspect contiguous original source context, camera boundaries and live/replay/non-play transitions; sparse equal scenes do not label unsampled frames.",
        )
    )
    comparisons = Counter()
    for n, frame in frames.items():
        native_rows = list(itertools.chain.from_iterable(frame["native"].values()))
        coarse_rows = list(itertools.chain.from_iterable(frame["coarse"].values()))
        for a, b in itertools.product(LANES, repeat=2):
            left, right = frame["native"][a], frame["coarse"][b]
            for x, y in itertools.product(left or [None], right or [None]):
                if not frame["available"] or x is None or y is None:
                    state = "unavailable"
                elif "unknown" in (x["state"]["scene"], y["state"]["scene"]):
                    state = "unknown"
                else:
                    state = (
                        "agreement"
                        if x["state"]["scene"] == y["state"]["scene"]
                        else "conflict"
                    )
                comparison = {
                    "native_lane": a,
                    "coarse_lane": b,
                    "native_reference": x["reference"] if x else None,
                    "coarse_reference": y["reference"] if y else None,
                    "support": state,
                }
                frame["scene_comparisons"].append(comparison)
                comparisons[state] += 1
        variants = {
            (r["state"]["scene"], r["state"]["contact_state"]) for r in native_rows
        }
        unresolved = (
            not frame["available"]
            or not frame["sampled"]
            or not native_rows
            or any(
                "unknown" in (r["state"]["scene"], r["state"]["contact_state"])
                for r in native_rows
            )
            or len(variants) > 1
            or any(r["state"]["scene"] == "unknown" for r in coarse_rows)
            or any(r["support"] == "conflict" for r in frame["scene_comparisons"])
        )
        if unresolved:
            questions.append(
                question(
                    "frame_context",
                    packet,
                    [n, n],
                    [r["reference"] for r in native_rows + coarse_rows],
                    "Retain every source judgment, unknown and unavailable input. New contiguous original-source evidence is required; none_observed and unsampled are not verified contact negatives.",
                )
            )

    for first, last in itertools.pairwise(plan["samples"]):
        if last["frame"] - first["frame"] > 1:
            refs = [
                r["reference"]
                for n in (first["frame"], last["frame"])
                for lane in LANES
                for r in frames[n]["coarse"][lane]
            ]
            questions.append(
                question(
                    "unsampled_contiguous_interval",
                    packet,
                    [first["frame"] + 1, last["frame"] - 1],
                    refs,
                    "Inspect every intervening native frame in temporal order; sampled camera/actor continuity cannot fill this interval or establish contact absence.",
                )
            )

    for lane in LANES:
        events = event_occurrences[lane]
        for item in events:
            event, reference = item["event"], item["reference"]
            original = documents[lane][reference["document"]]["document"]
            if event["kind"] in ("serve", "shot", "unresolved_contact"):
                actor_refs = [
                    a["reference"]
                    for a in actor_occurrences[lane]
                    if a["reference"]["document"] == reference["document"]
                    and a["definition"]["actor_id"] == event.get("actor_id")
                ]
                questions.append(
                    question(
                        "physical_contact_identity",
                        packet,
                        event["interval"],
                        [reference],
                        "Establish physical-contact identity with new original-source temporal evidence across chunk overlaps. Keep repeated mentions, competing intervals and unsupported labels separate; do not vote, average timestamps or merge mentions.",
                    )
                )
                questions.append(
                    question(
                        "document_local_actor",
                        packet,
                        event["interval"],
                        [reference, *actor_refs],
                        "Support the hitter from this document's original visual evidence; equal IDs, court positions or definitions in other documents/lanes/experiments do not identify a person.",
                    )
                )
                require(
                    all(
                        a["actor_id"] != event.get("actor_id")
                        or type(a["identity_supported"]) is bool
                        for a in original["actors"]
                    ),
                    "Explicit local actor uncertainty required",
                )
        for pair in native[lane]["distinct_key_overlapping_contact_pairs"]:
            (ka, ia), (kb, ib) = pair
            refs = [
                e["reference"]
                for e in events
                if (e["event"]["kind"] == ka and _same(e["event"]["interval"], ia))
                or (e["event"]["kind"] == kb and _same(e["event"]["interval"], ib))
            ]
            questions.append(
                question(
                    "overlapping_contact_keys",
                    packet,
                    [min(ia[0], ib[0]), max(ia[1], ib[1])],
                    refs,
                    "Resolve whether these distinct inclusive contact keys describe separate physical contacts using fresh contiguous source evidence; duplicate-signature removal cannot resolve overlap.",
                )
            )
        for kind, question_kind in (
            ("serve", "opening_context"),
            ("rally_end", "terminal_context"),
        ):
            selected = [e for e in events if e["event"]["kind"] == kind]
            refs = [e["reference"] for e in selected] or [
                r
                for r in document_refs
                if r["granularity"] == "native" and r["lane"] == lane
            ]
            questions.append(
                question(
                    question_kind,
                    packet,
                    bounds,
                    refs,
                    "Require original-source opening/terminal evidence and retain censoring, missing events and uncertainty intervals. A last stroke, missing shuttle, stopped_play or sparse service preparation does not establish an exact rally boundary.",
                )
            )

    aggregate = {
        "source_id": packet["source_id"],
        "native_frames": len(frames),
        "sampled_frames": len(plan["samples"]),
        "unsampled_native_frames": plan["unsampled_native_frames"],
        "unavailable_native_frames": sum(not r["available"] for r in frames.values()),
        "unavailable_samples": sum(not r["available"] for r in plan["samples"]),
        "native_lanes": {
            lane: {
                key: native_summaries[lane][key]
                for key in (
                    "documents",
                    "inspected_memberships",
                    "unique_inspected_frames",
                    "uninspected_native_frames",
                    "event_occurrences",
                    "actor_definition_occurrences",
                    "signature_repeat_excess",
                    "distinct_key_overlapping_contact_pairs",
                    "unsupported_identity_contact_occurrences",
                )
            }
            for lane in LANES
        },
        "coarse_lanes": {
            lane: {
                "documents": 1,
                "frame_occurrences": len(coarse[lane]["document"]["frame_states"]),
                "actor_definitions": len(coarse[lane]["document"]["actors"]),
                "transitions": len(coarse[lane]["document"]["transitions"]),
            }
            for lane in LANES
        },
        "scene_occurrence_pair_support": {
            k: comparisons[k]
            for k in ("agreement", "conflict", "unknown", "unavailable")
        },
        "review_question_counts": dict(
            sorted(Counter(q["kind"] for q in questions).items())
        ),
        "eligibility": dict(ELIGIBILITY),
        "scientific_acceptance_changed": False,
        "truth_resolved": False,
        "actor_links_inferred": 0,
        "contacts_merged": 0,
        "full_match_accuracy_established": False,
    }
    ledger = {
        "schema_version": 1,
        "evidence_kind": "metadata_only_joined_review_index",
        **{k: packet[k] for k in SOURCE_KEYS},
        "packet_sha256": expected_source["packet_sha256"],
        "parsed_packet_sha256": fingerprint(packet),
        "native_original_ledger": copy.deepcopy(native_ledger),
        "native_documents": documents,
        "coarse_manifest": copy.deepcopy(temporal_manifest),
        "coarse_documents": coarse,
        "frames": [frames[n] for n in sorted(frames)],
        "native_event_occurrences": event_occurrences,
        "native_actor_occurrences": actor_occurrences,
        "review_questions": questions,
        "eligibility": dict(ELIGIBILITY),
        "truth_resolved": False,
        "scientific_acceptance_changed": False,
    }
    require(fingerprint(inputs) == before, "Scientific inputs mutated")
    return aggregate, ledger


def audit_join(aggregate, ledger, *args, **kwargs):
    """Rebuild from original evidence to reject omissions or inferred fields."""
    expected_aggregate, expected_ledger = join_source(*args, **kwargs)
    require(
        _same(aggregate, expected_aggregate),
        "Joined aggregate differs from original evidence",
    )
    require(
        _same(ledger, expected_ledger), "Joined ledger differs from original evidence"
    )
    return {
        "verified": True,
        "ledger_sha256": fingerprint(ledger),
        "native_frames": aggregate["native_frames"],
    }


def summarize_sources(results):
    """Stable source-order-independent counts; never a reference verdict."""
    require(type(results) is list and bool(results), "Explicit source results required")
    ordered = sorted(results, key=lambda r: r["source_id"])
    require(
        len({r["source_id"] for r in ordered}) == len(ordered),
        "Duplicate source result",
    )
    for row in ordered:
        require(
            _same(row["eligibility"], ELIGIBILITY)
            and row["truth_resolved"] is False
            and row["scientific_acceptance_changed"] is False,
            "No acceptance or eligibility promotion",
        )
    return {
        "source_slots": len(ordered),
        **{
            key: sum(_integer(r[key]) for r in ordered)
            for key in (
                "native_frames",
                "sampled_frames",
                "unsampled_native_frames",
                "unavailable_native_frames",
                "unavailable_samples",
            )
        },
        "sources": copy.deepcopy(ordered),
        "new_scientific_sessions": 0,
        "new_image_payload_bytes": 0,
        "eligibility": dict(ELIGIBILITY),
        "truth_resolved": False,
        "scientific_acceptance_changed": False,
        "full_match_accuracy_established": False,
    }
